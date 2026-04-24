"""
回测数据配置和管理API
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Body
from sqlalchemy.orm import Session
from sqlalchemy import bindparam, text
from datetime import date, datetime, timedelta
from typing import List, Optional
import asyncio
import logging
import pandas as pd

from api.database import get_db, get_db_ctx, UserDB
from api.deps import require_api_user as get_current_user
from api.data_downloader import DataDownloader
from api.quantclass_downloader import QuantClassDownloader
from api.quantclass_importer import import_stock_daily_from_quantclass
from api.data_quality_manager import DataQualityManager
from api.data_source_monitor import get_data_source_monitor
from api.services.daily_kline_parquet_store import get_daily_kline_parquet_stats, write_daily_kline_parquet_cache
from .backtest_data_models import (
    BacktestDataTaskCreate, BacktestDataTask,
    BacktestDataConfigCreate, BacktestDataConfig,
    BacktestDataSubscriptionStatus,
    BacktestDataStats, BatchDataDownloadRequest,
    BacktestDataTaskListResponse, BacktestDataConfigListResponse,
    BacktestDataStatsListResponse
)
from api.services import backtest_data_auto_update_service

router = APIRouter(prefix="/v1/backtest-data", tags=["backtest-data"])

_TABLE_STATS_MAPPING = {
    "daily_kline": ("stock_daily_kline", "trade_date"),
    "index_data": ("index_daily_data", "trade_date"),
    "minute_kline": ("stock_minute_kline", "trade_time"),
}


def _normalize_config_payload(payload: dict) -> dict:
    raw = dict(payload or {})
    config_name = str(raw.get("config_name") or "default").strip() or "default"
    enabled_data_types = raw.get("enabled_data_types")
    if not enabled_data_types:
        enabled_data_types = raw.get("data_types") or []
    enabled_data_types = [str(item).strip() for item in enabled_data_types if str(item).strip()]
    default_symbols = raw.get("default_symbols")
    if default_symbols is None:
        default_symbols = raw.get("symbols") or []
    default_symbols = [str(item).strip().upper() for item in default_symbols if str(item).strip()]

    date_range_start = raw.get("date_range_start")
    date_range_end = raw.get("date_range_end")
    default_date_range_days = raw.get("default_date_range_days")
    if default_date_range_days in (None, "", 0):
        try:
            if date_range_start and date_range_end:
                start = date.fromisoformat(str(date_range_start))
                end = date.fromisoformat(str(date_range_end))
                default_date_range_days = max((end - start).days + 1, 1)
            else:
                default_date_range_days = 365
        except Exception:
            default_date_range_days = 365

    data_source_preference = str(
        raw.get("data_source_preference")
        or raw.get("data_source")
        or "akshare"
    ).strip() or "akshare"
    auto_download = bool(raw.get("auto_download")) if "auto_download" in raw else bool(raw.get("auto_update", False))
    update_frequency = raw.get("update_frequency")
    if not update_frequency and auto_download:
        update_frequency = "daily"
    schedule_time = str(raw.get("schedule_time") or "18:30").strip() or "18:30"
    timezone_value = str(raw.get("timezone") or "Asia/Shanghai").strip() or "Asia/Shanghai"
    only_trading_day = bool(raw.get("only_trading_day", True))
    return {
        "config_name": config_name,
        "enabled_data_types": enabled_data_types,
        "default_date_range_days": max(int(default_date_range_days or 365), 1),
        "default_symbols": default_symbols,
        "data_source_preference": data_source_preference,
        "auto_download": auto_download,
        "update_frequency": str(update_frequency).strip() if update_frequency else None,
        "schedule_time": schedule_time,
        "timezone": timezone_value,
        "only_trading_day": only_trading_day,
    }


def _row_to_backtest_config(row) -> BacktestDataConfig:
    return BacktestDataConfig(
        id=row.id,
        user_id=row.user_id,
        config_name=row.config_name,
        enabled_data_types=row.enabled_data_types or [],
        default_date_range_days=row.default_date_range_days,
        default_symbols=row.default_symbols or [],
        data_source_preference=row.data_source_preference,
        auto_download=row.auto_download,
        update_frequency=row.update_frequency,
        schedule_time=getattr(row, "schedule_time", None),
        timezone=getattr(row, "timezone", None),
        only_trading_day=bool(getattr(row, "only_trading_day", True)),
        last_run_at=getattr(row, "last_run_at", None),
        last_success_at=getattr(row, "last_success_at", None),
        last_updated_at=row.last_updated_at,
        subscription_status=None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _build_backtest_table_stat(db: Session, *, data_type: str, table_name: str, date_column: str) -> BacktestDataStats | None:
    table_exists = db.execute(text("""
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = :table_name
    """), {"table_name": table_name}).scalar()
    if not table_exists:
        return None

    row = db.execute(text(f"""
        SELECT
            COUNT(*) AS total_records,
            COUNT(DISTINCT symbol) AS symbol_count,
            COUNT(DISTINCT DATE({date_column})) AS trading_days,
            MIN(DATE({date_column})) AS date_range_start,
            MAX(DATE({date_column})) AS date_range_end
        FROM {table_name}
    """)).fetchone()
    db_stats = None if row is None else {
        "total_records": int(row.total_records or 0),
        "symbol_count": int(row.symbol_count or 0),
        "trading_days": int(row.trading_days or 0),
        "date_range_start": row.date_range_start,
        "date_range_end": row.date_range_end,
    }

    cache_stats = get_daily_kline_parquet_stats() if data_type == "daily_kline" else None
    effective_stats = cache_stats or db_stats
    if effective_stats is None or int(effective_stats.get("total_records") or 0) <= 0:
        return None

    issues_score = 100
    duplicate_count = db.execute(text(f"""
        SELECT COUNT(*) FROM (
            SELECT symbol, {date_column}
            FROM {table_name}
            GROUP BY symbol, {date_column}
            HAVING COUNT(*) > 1
        ) t
    """)).scalar() or 0
    if int(duplicate_count) > 0:
        issues_score -= 20

    null_close_count = db.execute(text(f"""
        SELECT COUNT(*)
        FROM {table_name}
        WHERE close IS NULL
    """)).scalar() or 0
    if int(null_close_count) > 0:
        issues_score -= 10

    last_table_updated_at = None
    if _table_has_column(db, table_name, "updated_at"):
        last_table_updated_at = db.execute(text(f"SELECT MAX(updated_at) FROM {table_name}")).scalar()
    elif _table_has_column(db, table_name, "created_at"):
        last_table_updated_at = db.execute(text(f"SELECT MAX(created_at) FROM {table_name}")).scalar()

    if cache_stats and db_stats and db_stats.get("date_range_end") and cache_stats.get("date_range_end"):
        if cache_stats["date_range_end"] < db_stats["date_range_end"]:
            lag_days = max((db_stats["date_range_end"] - cache_stats["date_range_end"]).days, 1)
            issues_score -= min(40, 10 + lag_days * 3)

    effective_last_updated_at = last_table_updated_at
    if cache_stats:
        effective_last_updated_at = cache_stats.get("last_table_updated_at") or effective_last_updated_at

    return BacktestDataStats(
        data_type=data_type,
        symbol=None,
        date_range_start=effective_stats.get("date_range_start"),
        date_range_end=effective_stats.get("date_range_end"),
        total_records=int(effective_stats.get("total_records") or 0),
        symbol_count=int(effective_stats.get("symbol_count") or 0),
        trading_days=int(effective_stats.get("trading_days") or 0),
        last_updated_date=effective_stats.get("date_range_end"),
        last_table_updated_at=effective_last_updated_at,
        coverage_source="parquet_cache" if cache_stats else "postgresql",
        db_date_range_start=db_stats.get("date_range_start") if db_stats else None,
        db_date_range_end=db_stats.get("date_range_end") if db_stats else None,
        cache_date_range_start=cache_stats.get("date_range_start") if cache_stats else None,
        cache_date_range_end=cache_stats.get("date_range_end") if cache_stats else None,
        cache_last_updated_at=cache_stats.get("last_table_updated_at") if cache_stats else None,
        data_quality_score=max(int(issues_score), 0),
        missing_dates=[],
        created_at=effective_last_updated_at or datetime.utcnow(),
        updated_at=effective_last_updated_at or datetime.utcnow(),
    )


def _table_has_column(db: Session, table_name: str, column_name: str) -> bool:
    return bool(db.execute(text("""
        SELECT COUNT(*)
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = :table_name
          AND column_name = :column_name
    """), {
        "table_name": table_name,
        "column_name": column_name,
    }).scalar())


def _load_daily_kline_frame_for_cache(
    db: Session,
    *,
    start_date: date,
    end_date: date,
    symbols: Optional[list[str]] = None,
) -> pd.DataFrame | None:
    params = {
        "start_date": start_date,
        "end_date": end_date,
    }
    if symbols:
        query = text("""
            SELECT symbol, trade_date AS date, open, high, low, close, volume, amount,
                   turnover_rate, pre_close, float_market_cap, total_market_cap, net_profit_ttm
            FROM stock_daily_kline
            WHERE trade_date >= :start_date
              AND trade_date <= :end_date
              AND symbol IN :symbols
            ORDER BY trade_date, symbol
        """).bindparams(bindparam("symbols", expanding=True))
        params["symbols"] = symbols
    else:
        query = text("""
            SELECT symbol, trade_date AS date, open, high, low, close, volume, amount,
                   turnover_rate, pre_close, float_market_cap, total_market_cap, net_profit_ttm
            FROM stock_daily_kline
            WHERE trade_date >= :start_date
              AND trade_date <= :end_date
            ORDER BY trade_date, symbol
        """)
    rows = db.execute(query, params).mappings().all()
    if not rows:
        return None
    return pd.DataFrame(rows)


def _refresh_daily_kline_cache_from_db(
    db: Session,
    *,
    start_date: date | None,
    end_date: date | None,
    symbols: Optional[list[str]] = None,
) -> dict:
    if start_date is None or end_date is None or start_date > end_date:
        return {"updated": False, "written_paths": None, "records": 0}
    frame = _load_daily_kline_frame_for_cache(db, start_date=start_date, end_date=end_date, symbols=symbols)
    if frame is None or frame.empty:
        return {"updated": False, "written_paths": None, "records": 0}
    written_paths = write_daily_kline_parquet_cache(frame)
    return {
        "updated": bool(written_paths),
        "written_paths": written_paths,
        "records": int(len(frame)),
        "date_range_start": start_date,
        "date_range_end": end_date,
    }


def _get_actual_table_coverage(db: Session, *, task_type: str) -> dict | None:
    mapping = _TABLE_STATS_MAPPING.get(task_type)
    if not mapping:
        return None
    table_name, date_column = mapping
    table_exists = db.execute(text("""
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = :table_name
    """), {"table_name": table_name}).scalar()
    if not table_exists:
        return None
    row = db.execute(text(f"""
        SELECT
            COUNT(*) AS total_records,
            MIN(DATE({date_column})) AS date_range_start,
            MAX(DATE({date_column})) AS date_range_end
        FROM {table_name}
    """)).fetchone()
    if row is None:
        return None
    return {
        "total_records": int(row.total_records or 0),
        "date_range_start": row.date_range_start,
        "date_range_end": row.date_range_end,
    }


def _parse_optional_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))

# 数据源兼容性映射
DATA_SOURCE_COMPATIBILITY = {
    'daily_kline': ['quantclass', 'akshare', 'baostock', 'tushare', 'eastmoney'],
    'minute_kline': ['qmt', 'akshare'],  # QMT 优先，AKShare 作为兜底
    'index_data': ['quantclass', 'akshare', 'baostock', 'tushare', 'eastmoney'],
    'chip_data': ['quantclass'],  # 只有量化课堂支持
    'financial_data': ['quantclass'],  # 只有量化课堂支持
    'research_reports': ['eastmoney']  # 只有东方财富支持
}

# ========== 数据下载任务API ==========

@router.post("/tasks", response_model=BacktestDataTask)
async def create_backtest_data_task(
    task: BacktestDataTaskCreate,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建回测数据下载任务"""
    try:
        # 插入任务记录
        query = text("""
            INSERT INTO backtest_data_tasks 
            (user_id, task_type, data_source, date_range_start, date_range_end, symbols, status)
            VALUES (:user_id, :task_type, :data_source, :date_range_start, :date_range_end, :symbols, 'pending')
            RETURNING id
        """)
        
        result = db.execute(query, {
            "user_id": current_user.id,
            "task_type": task.task_type,
            "data_source": task.data_source or "akshare",
            "date_range_start": task.date_range_start,
            "date_range_end": task.date_range_end,
            "symbols": task.symbols or []
        })
        task_id = result.fetchone()[0]
        db.commit()
        
        # 获取创建的任务
        task_query = text("""
            SELECT * FROM backtest_data_tasks WHERE id = :task_id
        """)
        task_result = db.execute(task_query, {"task_id": task_id})
        row = task_result.fetchone()
        
        return BacktestDataTask(
            id=row.id,
            user_id=row.user_id,
            task_type=row.task_type,
            data_source=row.data_source,
            date_range_start=row.date_range_start,
            date_range_end=row.date_range_end,
            symbols=row.symbols or [],
            status=row.status,
            progress=row.progress or 0,
            total_records=row.total_records or 0,
            downloaded_records=row.downloaded_records or 0,
            error_message=row.error_message,
            created_at=row.created_at,
            updated_at=row.updated_at,
            completed_at=row.completed_at
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建任务失败: {str(e)}")


@router.get("/tasks", response_model=BacktestDataTaskListResponse)
async def list_backtest_data_tasks(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100
):
    """获取回测数据下载任务列表"""
    try:
        # 获取任务总数
        count_query = text("""
            SELECT COUNT(*) FROM backtest_data_tasks WHERE user_id = :user_id
        """)
        count_result = db.execute(count_query, {"user_id": current_user.id})
        total = count_result.fetchone()[0]
        
        # 获取任务列表
        tasks_query = text("""
            SELECT * FROM backtest_data_tasks 
            WHERE user_id = :user_id 
            ORDER BY created_at DESC 
            LIMIT :limit OFFSET :skip
        """)
        tasks_result = db.execute(tasks_query, {
            "user_id": current_user.id,
            "limit": limit,
            "skip": skip
        })
        
        tasks = []
        for row in tasks_result:
            tasks.append(BacktestDataTask(
                id=row.id,
                user_id=row.user_id,
                task_type=row.task_type,
                data_source=row.data_source,
                date_range_start=row.date_range_start,
                date_range_end=row.date_range_end,
                symbols=row.symbols or [],
                status=row.status,
                progress=row.progress or 0,
                total_records=row.total_records or 0,
                downloaded_records=row.downloaded_records or 0,
                error_message=row.error_message,
                created_at=row.created_at,
                updated_at=row.updated_at,
                completed_at=row.completed_at
            ))
        
        return BacktestDataTaskListResponse(tasks=tasks, total=total)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取任务列表失败: {str(e)}")


@router.get("/tasks/{task_id}", response_model=BacktestDataTask)
async def get_backtest_data_task(
    task_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取单个回测数据下载任务"""
    try:
        query = text("""
            SELECT * FROM backtest_data_tasks 
            WHERE id = :task_id AND user_id = :user_id
        """)
        result = db.execute(query, {"task_id": task_id, "user_id": current_user.id})
        row = result.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        return BacktestDataTask(
            id=row.id,
            user_id=row.user_id,
            task_type=row.task_type,
            data_source=row.data_source,
            date_range_start=row.date_range_start,
            date_range_end=row.date_range_end,
            symbols=row.symbols or [],
            status=row.status,
            progress=row.progress or 0,
            total_records=row.total_records or 0,
            downloaded_records=row.downloaded_records or 0,
            error_message=row.error_message,
            created_at=row.created_at,
            updated_at=row.updated_at,
            completed_at=row.completed_at
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取任务失败: {str(e)}")


# ========== 数据配置API ==========

@router.post("/configs", response_model=BacktestDataConfig)
async def create_backtest_data_config(
    payload: dict = Body(...),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建或更新回测数据配置"""
    try:
        normalized = _normalize_config_payload(payload)
        try:
            BacktestDataConfigCreate(**normalized)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"配置参数无效: {exc}") from exc

        existing_query = text("""
            SELECT * FROM backtest_data_configs
            WHERE user_id = :user_id AND config_name = :config_name
        """)
        existing = db.execute(existing_query, {
            "user_id": current_user.id,
            "config_name": normalized["config_name"],
        }).fetchone()

        if existing:
            db.execute(text("""
                UPDATE backtest_data_configs
                SET enabled_data_types = :enabled_data_types,
                    default_date_range_days = :default_date_range_days,
                    default_symbols = :default_symbols,
                    data_source_preference = :data_source_preference,
                    auto_download = :auto_download,
                    update_frequency = :update_frequency,
                    schedule_time = :schedule_time,
                    timezone = :timezone,
                    only_trading_day = :only_trading_day,
                    updated_at = NOW()
                WHERE id = :config_id
            """), {
                "config_id": existing.id,
                **normalized,
            })
            config_id = existing.id
        else:
            result = db.execute(text("""
                INSERT INTO backtest_data_configs
                (user_id, config_name, enabled_data_types, default_date_range_days,
                 default_symbols, data_source_preference, auto_download, update_frequency,
                 schedule_time, timezone, only_trading_day)
                VALUES (:user_id, :config_name, :enabled_data_types, :default_date_range_days,
                        :default_symbols, :data_source_preference, :auto_download, :update_frequency,
                        :schedule_time, :timezone, :only_trading_day)
                RETURNING id
            """), {
                "user_id": current_user.id,
                **normalized,
            })
            config_id = result.fetchone()[0]
        db.commit()

        config_query = text("""
            SELECT * FROM backtest_data_configs WHERE id = :config_id
        """)
        config_result = db.execute(config_query, {"config_id": config_id})
        row = config_result.fetchone()
        config = _row_to_backtest_config(row)
        config.subscription_status = backtest_data_auto_update_service.get_config_status(int(row.id), user_id=str(current_user.id))
        return config
    except Exception as e:
        db.rollback()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"创建配置失败: {str(e)}")


@router.get("/configs", response_model=BacktestDataConfigListResponse)
async def list_backtest_data_configs(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取回测数据配置列表"""
    try:
        # 获取配置列表
        query = text("""
            SELECT * FROM backtest_data_configs 
            WHERE user_id = :user_id 
            ORDER BY created_at DESC
        """)
        result = db.execute(query, {"user_id": current_user.id})
        
        configs = []
        for row in result:
            config = _row_to_backtest_config(row)
            try:
                config.subscription_status = backtest_data_auto_update_service.get_config_status(int(row.id), user_id=str(current_user.id))
            except Exception:
                config.subscription_status = None
            configs.append(config)
        
        return BacktestDataConfigListResponse(configs=configs, total=len(configs))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取配置列表失败: {str(e)}")


@router.get("/configs/{config_id}/subscription-status", response_model=BacktestDataSubscriptionStatus)
async def get_backtest_data_subscription_status(
    config_id: int,
    current_user: UserDB = Depends(get_current_user),
):
    """获取订阅配置执行状态、水位与下次执行时间"""
    try:
        payload = backtest_data_auto_update_service.get_config_status(config_id, user_id=str(current_user.id))
        return BacktestDataSubscriptionStatus(**payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"获取订阅状态失败: {exc}") from exc


@router.post("/configs/{config_id}/run")
async def run_backtest_data_subscription_now(
    config_id: int,
    current_user: UserDB = Depends(get_current_user),
):
    """立即按当前订阅配置执行一次增量下载"""
    try:
        status = backtest_data_auto_update_service.get_config_status(config_id, user_id=str(current_user.id))
        del status
        task_ids = backtest_data_auto_update_service.trigger_config_now(config_id)
        return {
            "message": "订阅执行已触发" if task_ids else "当前没有可执行的增量任务",
            "config_id": config_id,
            "task_ids": task_ids,
            "created_count": len(task_ids),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"立即执行订阅失败: {exc}") from exc


# ========== 数据统计API ==========

@router.get("/stats", response_model=BacktestDataStatsListResponse)
async def get_backtest_data_stats(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取回测数据统计"""
    try:
        stats: list[BacktestDataStats] = []
        for data_type, (table_name, date_column) in _TABLE_STATS_MAPPING.items():
            item = _build_backtest_table_stat(db, data_type=data_type, table_name=table_name, date_column=date_column)
            if item is not None:
                stats.append(item)
        return BacktestDataStatsListResponse(stats=stats, total=len(stats))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取数据统计失败: {str(e)}")


@router.post("/daily-kline/cache-sync")
async def sync_daily_kline_parquet_cache(
    payload: Optional[dict] = Body(None),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """将 PostgreSQL 的 stock_daily_kline 同步到日线 Parquet 回测缓存。"""
    try:
        payload = payload or {}
        force_full = bool(payload.get("force_full", False))
        start_date = _parse_optional_date(payload.get("start_date"))
        end_date = _parse_optional_date(payload.get("end_date"))

        db_coverage = _get_actual_table_coverage(db, task_type="daily_kline")
        if not db_coverage or int(db_coverage.get("total_records") or 0) <= 0:
            raise HTTPException(status_code=404, detail="数据库 stock_daily_kline 暂无可同步数据")

        cache_before = get_daily_kline_parquet_stats()
        db_start = db_coverage.get("date_range_start")
        db_end = db_coverage.get("date_range_end")
        if db_start is None or db_end is None:
            raise HTTPException(status_code=404, detail="数据库 stock_daily_kline 缺少有效日期区间")

        if start_date is None or end_date is None:
            if force_full or cache_before is None or not cache_before.get("date_range_end"):
                start_date = db_start
                end_date = db_end
            else:
                cache_end = cache_before.get("date_range_end")
                if cache_end >= db_end:
                    return {
                        "success": True,
                        "message": "日线 Parquet 缓存已与数据库一致，无需同步",
                        "synced": False,
                        "db_coverage": db_coverage,
                        "cache_before": cache_before,
                        "cache_after": cache_before,
                    }
                start_date = cache_end + timedelta(days=1)
                end_date = db_end

        if start_date > end_date:
            raise HTTPException(status_code=400, detail="同步开始日期不能晚于结束日期")

        result = _refresh_daily_kline_cache_from_db(
            db,
            start_date=start_date,
            end_date=end_date,
        )
        cache_after = get_daily_kline_parquet_stats()
        quality_manager = DataQualityManager()
        quality_result = quality_manager.validate_database_integrity(db, "stock_daily_kline", "daily_kline")
        return {
            "success": True,
            "message": "日线 Parquet 缓存同步完成" if result.get("updated") else "未发现可写入的日线数据",
            "synced": bool(result.get("updated")),
            "sync_range": {
                "start_date": start_date,
                "end_date": end_date,
            },
            "result": result,
            "db_coverage": db_coverage,
            "cache_before": cache_before,
            "cache_after": cache_after,
            "quality": {
                "valid": quality_result.get("valid"),
                "issues": quality_result.get("issues", []),
                "stats": quality_result.get("stats", {}),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"同步日线 Parquet 缓存失败: {str(e)}")


# ========== 批量下载API ==========

@router.post("/batch-download")
async def batch_download_data(
    request: BatchDataDownloadRequest,
    background_tasks: BackgroundTasks,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """批量下载数据 - 自动取消同类型的旧任务"""
    try:
        task_ids = []
        
        # 为每种数据类型创建下载任务
        for data_type in request.data_types:
            # 取消同类型的pending/running任务
            cancel_query = text("""
                UPDATE backtest_data_tasks 
                SET status = 'cancelled', error_message = '被新任务取代', updated_at = NOW()
                WHERE user_id = :user_id 
                  AND task_type = :task_type 
                  AND status IN ('pending', 'running')
            """)
            db.execute(cancel_query, {
                "user_id": current_user.id,
                "task_type": data_type
            })
            
            # 创建新任务
            query = text("""
                INSERT INTO backtest_data_tasks 
                (user_id, task_type, data_source, date_range_start, date_range_end, symbols, status)
                VALUES (:user_id, :task_type, :data_source, :date_range_start, :date_range_end, :symbols, 'pending')
                RETURNING id
            """)
            
            result = db.execute(query, {
                "user_id": current_user.id,
                "task_type": data_type,
                "data_source": request.data_source,
                "date_range_start": request.date_range_start,
                "date_range_end": request.date_range_end,
                "symbols": request.symbols or []
            })
            task_id = result.fetchone()[0]
            task_ids.append(task_id)
        
        db.commit()
        
        # 在后台启动下载任务
        background_tasks.add_task(_process_batch_download, task_ids, current_user.id)
        
        return {
            "message": "批量下载任务已创建",
            "task_ids": task_ids,
            "total_tasks": len(task_ids)
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建批量下载任务失败: {str(e)}")


# ========== 数据源配置API ==========

@router.get("/data-sources")
async def list_data_sources(
    db: Session = Depends(get_db)
):
    """获取数据源配置列表"""
    try:
        query = text("""
            SELECT * FROM data_source_configs 
            WHERE is_active = TRUE 
            ORDER BY priority DESC, source_name
        """)
        result = db.execute(query)
        
        sources = []
        for row in result:
            sources.append({
                "id": row.id,
                "source_name": row.source_name,
                "source_type": row.source_type,
                "description": row.description,
                "rate_limit_per_minute": row.rate_limit_per_minute,
                "priority": row.priority,
                "requires_api_key": bool(row.api_key)
            })
        
        return {"sources": sources, "total": len(sources)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取数据源列表失败: {str(e)}")


# ========== 辅助函数 ==========

async def _process_batch_download(task_ids: List[int], user_id: str):
    """处理批量下载任务 - 使用AKShare真实数据"""
    from api.database import get_db_ctx
    import logging
    
    logger = logging.getLogger(__name__)
    
    for task_id in task_ids:
        try:
            # 获取任务信息
            with get_db_ctx() as db:
                task_query = text("SELECT * FROM backtest_data_tasks WHERE id = :task_id")
                task_result = db.execute(task_query, {"task_id": task_id})
                task = task_result.fetchone()
                
                if not task:
                    logger.error(f"任务 {task_id} 不存在")
                    continue
                
                # ✅ 验证数据源兼容性
                compatible_sources = DATA_SOURCE_COMPATIBILITY.get(task.task_type, [])
                if task.data_source not in compatible_sources:
                    logger.warning(f"数据类型 {task.task_type} 不支持数据源 {task.data_source}")
                    # 自动切换到兼容的数据源
                    if compatible_sources:
                        old_source = task.data_source
                        new_source = compatible_sources[0]
                        logger.info(f"已自动切换数据源: {old_source} -> {new_source}")
                        # 更新数据库
                        db.execute(text("UPDATE backtest_data_tasks SET data_source = :source WHERE id = :task_id"), 
                                   {"source": new_source, "task_id": task_id})
                        db.commit()
                        # 重新查询任务以获取更新后的数据源
                        task_result = db.execute(task_query, {"task_id": task_id})
                        task = task_result.fetchone()
                
                # 更新任务状态为运行中
                db.execute(text("""
                    UPDATE backtest_data_tasks
                    SET status = 'running',
                        error_message = '任务已启动，等待下载器执行',
                        updated_at = NOW()
                    WHERE id = :task_id
                """), {"task_id": task_id})
                db.commit()
                
                logger.info(f"开始处理任务 {task_id}: {task.task_type} (数据源: {task.data_source})")
            
            # 创建下载器
            with get_db_ctx() as db:
                downloader = DataDownloader(db)
                
                total_records = 0
                success_count = 0
                error_count = 0
                
                # 根据数据类型下载
                if task.task_type == 'daily_kline':
                    # 检查数据源
                    if task.data_source == 'quantclass':
                        # 使用量化课堂数据源
                        logger.info("使用量化课堂数据源下载股票日K线")
                        
                        try:
                            # 量化课堂配置
                            quantclass_api_key = '2HUTNZYOSRA8X5Z7TY2VZGKNTX5UN28B'
                            quantclass_hid = '1ad9e296ad8d3816b9bce5cba86b1ff6'
                            
                            # 创建下载器
                            qc_downloader = QuantClassDownloader(quantclass_api_key, quantclass_hid)
                            
                            # 下载数据
                            download_result = qc_downloader.download_product('stock-trading-data-pro')
                            
                            if download_result['success']:
                                # 导入数据库
                                import_result = import_stock_daily_from_quantclass(db, download_result['data_path'])
                                
                                if import_result['success']:
                                    total_records = import_result['records_imported']
                                    success_count = import_result['stocks_count']
                                    cache_refresh = _refresh_daily_kline_cache_from_db(
                                        db,
                                        start_date=import_result.get('min_trade_date'),
                                        end_date=import_result.get('max_trade_date'),
                                    )
                                    logger.info(
                                        "量化课堂日K缓存刷新: updated=%s records=%s range=%s~%s",
                                        cache_refresh.get("updated"),
                                        cache_refresh.get("records"),
                                        cache_refresh.get("date_range_start"),
                                        cache_refresh.get("date_range_end"),
                                    )
                                    logger.info(f"量化课堂导入成功: {total_records}条记录, {success_count}只股票")
                                else:
                                    error_count = 1
                                    logger.error(f"量化课堂导入失败: {import_result.get('error')}")
                            else:
                                error_count = 1
                                logger.error(f"量化课堂下载失败: {download_result.get('error')}")
                        except Exception as e:
                            error_count = 1
                            logger.error(f"量化课堂处理异常: {e}")
                        
                        # ✅ 量化课堂下载完成，跳过AKShare下载流程
                        pass
                    
                    else:
                        # 使用AKShare数据源
                        logger.info("使用AKShare数据源下载股票日K线")
                        
                        # 获取股票列表
                        symbols = downloader.get_all_stock_symbols()
                        if task.symbols:
                            # 如果指定了股票代码，只下载指定的
                            symbols = [s for s in symbols if s in task.symbols]
                        
                        total_stocks = len(symbols)
                        logger.info(f"准备下载 {total_stocks} 只股票的日K线数据 (使用AKShare)")
                    
                        # 并行下载（每次处理30只股票，优化性能）
                        batch_size = 10  # ✅ 优化：从30降到10，避免卡顿
                        for i in range(0, len(symbols), batch_size):
                            batch = symbols[i:i+batch_size]
                        
                        # 并行下载这一批股票
                        download_tasks = [
                            downloader.download_daily_kline(
                                symbol, task.date_range_start, task.date_range_end
                            )
                            for symbol in batch
                        ]
                        results = await asyncio.gather(*download_tasks, return_exceptions=True)
                        
                        # 统计结果
                        for symbol, result in zip(batch, results):
                            if isinstance(result, Exception):
                                logger.error(f"股票 {symbol} 下载异常: {result}")
                                error_count += 1
                            elif result['success']:
                                total_records += result['records']
                                success_count += 1
                            else:
                                logger.error(f"股票 {symbol} 下载失败: {result.get('error', '未知错误')}")
                                error_count += 1
                        
                        # 更新进度
                        progress = int((i + batch_size) / len(symbols) * 100)
                        with get_db_ctx() as db_update:
                            db_update.execute(text("""
                                UPDATE backtest_data_tasks 
                                SET progress = :progress, 
                                    downloaded_records = :records,
                                    updated_at = NOW()
                                WHERE id = :task_id
                            """), {
                                "task_id": task_id,
                                "progress": min(progress, 100),
                                "records": total_records
                            })
                            db_update.commit()
                        
                        # 批次间延迟，优化后减少延迟
                        await asyncio.sleep(2)  # ✅ 优化：从0.1秒增加到2秒，避免卡顿

                        if success_count > 0:
                            cache_refresh = _refresh_daily_kline_cache_from_db(
                                db,
                                start_date=task.date_range_start,
                                end_date=task.date_range_end,
                                symbols=task.symbols or None,
                            )
                            logger.info(
                                "AKShare日K缓存刷新: updated=%s records=%s range=%s~%s",
                                cache_refresh.get("updated"),
                                cache_refresh.get("records"),
                                cache_refresh.get("date_range_start"),
                                cache_refresh.get("date_range_end"),
                            )
                elif task.task_type == 'index_data':
                    # 检查数据源
                    if task.data_source == 'quantclass':
                        # 使用量化课堂数据源
                        logger.info("使用量化课堂数据源下载指数数据")
                        
                        try:
                            # 量化课堂配置
                            quantclass_api_key = '2HUTNZYOSRA8X5Z7TY2VZGKNTX5UN28B'
                            quantclass_hid = '1ad9e296ad8d3816b9bce5cba86b1ff6'
                            
                            # 创建下载器
                            qc_downloader = QuantClassDownloader(quantclass_api_key, quantclass_hid)
                            
                            # 下载指数数据
                            download_result = qc_downloader.download_product('stock-main-index-data')
                            
                            if download_result['success']:
                                # 导入数据库
                                from api.generic_importer import import_generic_data
                                import_result = import_generic_data(db, download_result['data_path'], 'index_daily')
                                
                                if import_result['success']:
                                    total_records = import_result['records_imported']
                                    success_count = 1
                                    logger.info(f"量化课堂指数数据导入成功: {total_records}条记录")
                                else:
                                    error_count = 1
                                    logger.error(f"量化课堂指数数据导入失败: {import_result.get('error')}")
                            else:
                                error_count = 1
                                logger.error(f"量化课堂指数数据下载失败: {download_result.get('error')}")
                        except Exception as e:
                            error_count = 1
                            logger.error(f"量化课堂指数数据下载异常: {e}")
                    
                    else:
                        # 使用AKShare数据源
                        logger.info("使用AKShare数据源下载指数数据")
                        
                        # 下载主要指数数据
                        symbols = downloader.get_main_index_symbols()
                        if task.symbols:
                            symbols = [s for s in symbols if s in task.symbols]
                        
                        logger.info(f"准备下载 {len(symbols)} 个指数数据")
                        
                        for symbol in symbols:
                            result = await downloader.download_index_data(
                                symbol, task.date_range_start, task.date_range_end
                            )
                            
                            if result['success']:
                                total_records += result['records']
                                success_count += 1
                            else:
                                error_count += 1
                            
                            await asyncio.sleep(1.5)
                
                elif task.task_type == 'minute_kline':
                    if task.data_source == 'qmt':
                        symbols = task.symbols or []
                        total_stocks = len(symbols)
                        logger.info(f"准备下载 {total_stocks} 只股票的1分钟K线数据 (使用QMT)")
                        async def qmt_progress_callback(progress: int, message: str):
                            with get_db_ctx() as db_update:
                                db_update.execute(text("""
                                    UPDATE backtest_data_tasks
                                    SET progress = :progress,
                                        error_message = :error_message,
                                        updated_at = NOW()
                                    WHERE id = :task_id
                                """), {
                                    "task_id": task_id,
                                    "progress": max(0, min(int(progress), 100)),
                                    "error_message": message[:500] if message else None,
                                })
                                db_update.commit()

                        await qmt_progress_callback(5, "QMT 连接检查通过，准备启动历史分钟线同步脚本（固定通道：paper_sim / 8710）")

                        result = await downloader.download_minute_kline_from_qmt(
                            start_date=task.date_range_start,
                            end_date=task.date_range_end,
                            symbols=task.symbols or [],
                            progress_callback=qmt_progress_callback,
                        )
                        if result.get('success'):
                            total_records += int(result.get('records') or 0)
                            success_count += total_stocks if total_stocks > 0 else 1
                        else:
                            error_count += 1
                            logger.error(f"QMT 1分钟K线下载失败: {result.get('error', '未知错误')}")

                        with get_db_ctx() as db_update:
                            db_update.execute(text("""
                                UPDATE backtest_data_tasks
                                SET progress = :progress,
                                    downloaded_records = :records,
                                    error_message = :error_message,
                                    updated_at = NOW()
                                WHERE id = :task_id
                            """), {
                                "task_id": task_id,
                                "progress": 100 if result.get('success') else 0,
                                "records": total_records,
                                "error_message": (
                                    f"QMT 分钟线同步完成，区间记录约 {total_records} 条；通道：{result.get('account_key') or 'paper_sim'}；bridge：{result.get('bridge') or '8710'}"
                                    if result.get('success')
                                    else result.get('error')
                                )
                            })
                            db_update.commit()
                    else:
                        symbols = downloader.get_all_stock_symbols()
                        if task.symbols:
                            symbols = [s for s in symbols if s in task.symbols]
                        total_stocks = len(symbols)
                        logger.info(f"准备下载 {total_stocks} 只股票的1分钟K线数据 (使用AKShare)")

                        batch_size = 10
                        for i in range(0, len(symbols), batch_size):
                            batch = symbols[i:i+batch_size]

                            download_tasks = [
                                downloader.download_minute_kline(
                                    symbol, task.date_range_start, task.date_range_end
                                )
                                for symbol in batch
                            ]
                            results = await asyncio.gather(*download_tasks, return_exceptions=True)

                            for symbol, result in zip(batch, results):
                                if isinstance(result, Exception):
                                    logger.error(f"股票 {symbol} 1分钟K线下载异常: {result}")
                                    error_count += 1
                                elif result['success']:
                                    total_records += result['records']
                                    success_count += 1
                                else:
                                    logger.error(f"股票 {symbol} 1分钟K线下载失败: {result.get('error', '未知错误')}")
                                    error_count += 1

                            progress = int((i + batch_size) / len(symbols) * 100)
                            with get_db_ctx() as db_update:
                                db_update.execute(text("""
                                    UPDATE backtest_data_tasks
                                    SET progress = :progress,
                                        downloaded_records = :records,
                                        error_message = :error_message,
                                        updated_at = NOW()
                                    WHERE id = :task_id
                                """), {
                                    "task_id": task_id,
                                    "progress": min(progress, 100),
                                    "records": total_records,
                                    "error_message": f"AKShare 批次 {i // batch_size + 1}/{max((len(symbols) + batch_size - 1) // batch_size, 1)}，已处理 {min(i + len(batch), len(symbols))}/{len(symbols)} 只股票"
                                })
                                db_update.commit()

                            await asyncio.sleep(2)
                
                elif task.task_type == 'chip_data':
                    # 筹码数据
                    if task.data_source == 'quantclass':
                        logger.info("使用量化课堂数据源下载筹码数据")
                        
                        try:
                            quantclass_api_key = '2HUTNZYOSRA8X5Z7TY2VZGKNTX5UN28B'
                            quantclass_hid = '1ad9e296ad8d3816b9bce5cba86b1ff6'
                            
                            qc_downloader = QuantClassDownloader(quantclass_api_key, quantclass_hid)
                            download_result = qc_downloader.download_product('stock-chip-distribution')
                            
                            if download_result['success']:
                                from api.generic_importer import import_generic_data
                                import_result = import_generic_data(db, download_result['data_path'], 'chip_data')
                                
                                if import_result['success']:
                                    total_records = import_result['records_imported']
                                    success_count = 1
                                    logger.info(f"筹码数据导入成功: {total_records}条记录")
                                else:
                                    error_count = 1
                                    logger.error(f"筹码数据导入失败: {import_result.get('error')}")
                            else:
                                error_count = 1
                                logger.error(f"筹码数据下载失败: {download_result.get('error')}")
                        except Exception as e:
                            error_count = 1
                            logger.error(f"筹码数据下载异常: {e}")
                    else:
                        logger.warning("AKShare不支持筹码数据下载")
                        error_count = 1
                
                elif task.task_type == 'financial_data':
                    # 财务数据
                    if task.data_source == 'quantclass':
                        logger.info("使用量化课堂数据源下载财务数据")
                        
                        try:
                            quantclass_api_key = '2HUTNZYOSRA8X5Z7TY2VZGKNTX5UN28B'
                            quantclass_hid = '1ad9e296ad8d3816b9bce5cba86b1ff6'
                            
                            qc_downloader = QuantClassDownloader(quantclass_api_key, quantclass_hid)
                            download_result = qc_downloader.download_product('stock-fin-pre-data-sina')
                            
                            if download_result['success']:
                                from api.generic_importer import import_generic_data
                                import_result = import_generic_data(db, download_result['data_path'], 'financial_data')
                                
                                if import_result['success']:
                                    total_records = import_result['records_imported']
                                    success_count = 1
                                    logger.info(f"财务数据导入成功: {total_records}条记录")
                                else:
                                    error_count = 1
                                    logger.error(f"财务数据导入失败: {import_result.get('error')}")
                            else:
                                error_count = 1
                                logger.error(f"财务数据下载失败: {download_result.get('error')}")
                        except Exception as e:
                            error_count = 1
                            logger.error(f"财务数据下载异常: {e}")
                    else:
                        logger.warning("AKShare财务数据下载功能待实现")
                        error_count = 1
                
                elif task.task_type == 'research_reports':
                    # 研报数据
                    logger.warning("研报数据下载功能待实现")
                    error_count = 1
                
                else:
                    logger.warning(f"未知的数据类型: {task.task_type}")
                    error_count = 1
                
                final_status = 'completed'
                clear_error_message = True
                final_error_message = None
                if error_count > 0 and success_count == 0:
                    final_status = 'failed'
                    clear_error_message = False
                    final_error_message = f"任务执行失败，成功 {success_count}，失败 {error_count}"
                elif error_count > 0:
                    final_status = 'completed'
                    clear_error_message = False
                    final_error_message = f"任务部分成功，成功 {success_count}，失败 {error_count}"

                # 更新任务状态
                with get_db_ctx() as db:
                    actual_coverage = _get_actual_table_coverage(db, task_type=task.task_type)
                    actual_last_data_date = actual_coverage.get("date_range_end") if actual_coverage else None
                    actual_start_date = actual_coverage.get("date_range_start") if actual_coverage else None
                    actual_total_records = actual_coverage.get("total_records") if actual_coverage else total_records

                    db.execute(text("""
                        UPDATE backtest_data_tasks 
                        SET status = :final_status, 
                            progress = 100, 
                            total_records = :total_records,
                            downloaded_records = :total_records,
                            error_message = CASE
                                WHEN :clear_error_message THEN NULL
                                ELSE COALESCE(error_message, :final_error_message)
                            END,
                            completed_at = NOW(),
                            updated_at = NOW()
                        WHERE id = :task_id
                    """), {
                        "task_id": task_id,
                        "total_records": total_records,
                        "final_status": final_status,
                        "clear_error_message": clear_error_message,
                        "final_error_message": final_error_message,
                    })

                    subscription_config_id = getattr(task, "subscription_config_id", None)
                    trigger_mode = str(getattr(task, "trigger_mode", None) or "").strip().lower()
                    if subscription_config_id:
                        scope_key = "all"
                        task_symbols = list(task.symbols or [])
                        if task_symbols:
                            scope_key = "symbols:" + ",".join(sorted({str(item).strip().upper() for item in task_symbols if str(item).strip()})[:200])

                        watermark_existing = db.execute(text("""
                            SELECT id
                            FROM backtest_data_watermarks
                            WHERE user_id = :user_id
                              AND config_id = :config_id
                              AND data_type = :data_type
                              AND COALESCE(data_source, '') = :data_source
                              AND scope_key = :scope_key
                            LIMIT 1
                        """), {
                            "user_id": str(task.user_id),
                            "config_id": int(subscription_config_id),
                            "data_type": task.task_type,
                            "data_source": str(task.data_source or ""),
                            "scope_key": scope_key,
                        }).fetchone()
                        watermark_payload = {
                            "user_id": str(task.user_id),
                            "config_id": int(subscription_config_id),
                            "data_type": task.task_type,
                            "data_source": str(task.data_source or ""),
                            "scope_key": scope_key,
                            "last_run_started_at": datetime.utcnow(),
                            "last_data_date": actual_last_data_date if final_status == "completed" else None,
                            "last_success_at": datetime.utcnow() if final_status == "completed" else None,
                            "last_status": final_status,
                            "last_error": final_error_message if final_status != "completed" else None,
                        }
                        if watermark_existing:
                            db.execute(text("""
                                UPDATE backtest_data_watermarks
                                SET last_run_started_at = :last_run_started_at,
                                    last_data_date = COALESCE(:last_data_date, last_data_date),
                                    last_success_at = COALESCE(:last_success_at, last_success_at),
                                    last_status = :last_status,
                                    last_error = :last_error,
                                    updated_at = NOW()
                                WHERE id = :id
                            """), {**watermark_payload, "id": watermark_existing.id})
                        else:
                            db.execute(text("""
                                INSERT INTO backtest_data_watermarks
                                (user_id, config_id, data_type, data_source, scope_key, last_run_started_at, last_data_date, last_success_at, last_status, last_error, created_at, updated_at)
                                VALUES (:user_id, :config_id, :data_type, :data_source, :scope_key, :last_run_started_at, :last_data_date, :last_success_at, :last_status, :last_error, NOW(), NOW())
                            """), watermark_payload)

                        if final_status == "completed" and trigger_mode == "scheduled":
                            db.execute(text("""
                                UPDATE backtest_data_configs
                                SET last_success_at = NOW(),
                                    last_updated_at = NOW(),
                                    updated_at = NOW()
                                WHERE id = :config_id
                            """), {"config_id": int(subscription_config_id)})
                    
                    # 更新数据统计（先删除旧记录，再插入新记录，避免PostgreSQL NULL值问题）
                    db.execute(text("""
                        DELETE FROM backtest_data_stats 
                        WHERE data_type = :data_type AND (symbol = :symbol OR (symbol IS NULL AND :symbol IS NULL))
                    """), {
                        "data_type": task.task_type,
                        "symbol": None
                    })
                    
                    db.execute(text("""
                        INSERT INTO backtest_data_stats 
                        (data_type, symbol, total_records, date_range_start, date_range_end, data_quality_score, last_updated_date)
                        VALUES (:data_type, NULL, :total_records, :date_range_start, :date_range_end, 95, :last_updated_date)
                    """), {
                        "data_type": task.task_type,
                        "total_records": actual_total_records,
                        "date_range_start": actual_start_date,
                        "date_range_end": actual_last_data_date,
                        "last_updated_date": actual_last_data_date,
                    })
                    db.commit()
                    
                    # 数据质量检查（质量优先原则）
                    try:
                        quality_manager = DataQualityManager()
                        
                        # 确定表名
                        table_name = 'stock_daily_kline'
                        if task.task_type == 'index_data':
                            table_name = 'index_daily_data'
                        elif task.task_type == 'minute_kline':
                            table_name = 'stock_minute_kline'
                        
                        # 执行质量检查
                        quality_result = quality_manager.validate_database_integrity(
                            db, table_name, task.task_type
                        )
                        
                        if quality_result['valid']:
                            logger.info(f"✅ 数据质量检查通过: {quality_result['stats']}")
                        else:
                            logger.warning(f"⚠️ 数据质量问题: {quality_result['issues']}")
                    except Exception as e:
                        logger.error(f"数据质量检查异常: {e}")
                    
                    # 记录数据源使用统计
                    try:
                        monitor = get_data_source_monitor()
                        monitor.record_download(
                            source=task.data_source or 'quantclass',
                            data_type=task.task_type,
                            records=total_records,
                            success=(error_count == 0)
                        )
                        logger.info(f"✅ 使用统计已记录: {task.data_source} - {task.task_type}")
                    except Exception as e:
                        logger.error(f"使用统计记录异常: {e}")
                    
                    logger.info(f"任务 {task_id} 完成: 成功 {success_count}, 失败 {error_count}, 总记录 {total_records}")
                
        except Exception as e:
            logger.error(f"任务 {task_id} 执行失败: {e}")
            # 更新任务状态为失败
            with get_db_ctx() as db:
                db.execute(text("""
                    UPDATE backtest_data_tasks 
                    SET status = 'failed', 
                        error_message = :error,
                        updated_at = NOW()
                    WHERE id = :task_id
                """), {"task_id": task_id, "error": str(e)})
                db.commit()




# ========== 数据下载状态检查 ==========

@router.get("/download-status")
async def get_download_status(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取数据下载状态概览"""
    try:
        # 统计各种状态的任务数量
        status_query = text("""
            SELECT status, COUNT(*) as count 
            FROM backtest_data_tasks 
            WHERE user_id = :user_id 
            GROUP BY status
        """)
        status_result = db.execute(status_query, {"user_id": current_user.id})
        
        status_counts = {}
        for row in status_result:
            status_counts[row.status] = row.count
        
        # 获取最近的任务
        recent_query = text("""
            SELECT * FROM backtest_data_tasks 
            WHERE user_id = :user_id 
            ORDER BY created_at DESC 
            LIMIT 5
        """)
        recent_result = db.execute(recent_query, {"user_id": current_user.id})
        
        recent_tasks = []
        for row in recent_result:
            recent_tasks.append({
                "id": row.id,
                "task_type": row.task_type,
                "status": row.status,
                "progress": row.progress or 0,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "completed_at": row.completed_at.isoformat() if row.completed_at else None
            })
        
        return {
            "status_counts": status_counts,
            "recent_tasks": recent_tasks,
            "total_tasks": sum(status_counts.values())
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取下载状态失败: {str(e)}")


# ========== 数据质量检查API ==========

@router.get("/quality-check/{table_name}")
async def check_data_quality(
    table_name: str,
    data_type: str = "daily_kline",
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    检查数据质量
    
    Args:
        table_name: 表名（如 stock_daily_kline）
        data_type: 数据类型（daily_kline, index_data等）
    """
    try:
        quality_manager = DataQualityManager()
        
        # 执行数据库完整性检查
        db_result = quality_manager.validate_database_integrity(db, table_name, data_type)
        
        return {
            "success": True,
            "table_name": table_name,
            "data_type": data_type,
            "valid": db_result['valid'],
            "issues": db_result['issues'],
            "stats": db_result['stats']
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"数据质量检查失败: {str(e)}")


@router.get("/quality-report")
async def generate_quality_report(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    生成完整的数据质量报告
    
    包括：
    - 股票日K线数据质量
    - 指数数据质量
    - 数据库完整性
    """
    try:
        quality_manager = DataQualityManager()
        
        report = {
            "generated_at": datetime.now().isoformat(),
            "tables": {}
        }
        
        # 检查股票日K线
        daily_kline_result = quality_manager.validate_database_integrity(
            db, "stock_daily_kline", "daily_kline"
        )
        report["tables"]["stock_daily_kline"] = {
            "valid": daily_kline_result['valid'],
            "issues": daily_kline_result['issues'],
            "stats": daily_kline_result['stats']
        }
        
        # 检查指数数据（如果表存在）
        try:
            index_result = quality_manager.validate_database_integrity(
                db, "index_daily_data", "index_data"
            )
            report["tables"]["index_daily_data"] = {
                "valid": index_result['valid'],
                "issues": index_result['issues'],
                "stats": index_result['stats']
            }
        except:
            report["tables"]["index_daily_data"] = {
                "valid": False,
                "issues": ["表不存在"],
                "stats": {}
            }
        
        return {
            "success": True,
            "report": report
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成质量报告失败: {str(e)}")


# ========== 数据源使用统计API ==========

@router.get("/source-usage")
async def get_data_source_usage(
    current_user: UserDB = Depends(get_current_user)
):
    """
    获取数据源使用统计
    
    包括：
    - 量化课堂使用次数和剩余次数
    - AKShare使用统计
    - 每日下载记录
    """
    try:
        monitor = get_data_source_monitor()
        
        return {
            "success": True,
            "sources": monitor.get_all_sources_status(),
            "daily_report": monitor.get_daily_report()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取使用统计失败: {str(e)}")


@router.get("/source-status/{source}")
async def get_source_status(
    source: str,
    current_user: UserDB = Depends(get_current_user)
):
    """
    获取指定数据源状态
    
    Args:
        source: 数据源名称（quantclass, akshare）
    """
    try:
        monitor = get_data_source_monitor()
        status = monitor.get_usage_status(source)
        
        if 'error' in status:
            raise HTTPException(status_code=400, detail=status['error'])
        
        return {
            "success": True,
            "status": status
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取数据源状态失败: {str(e)}")

"""
回测管理API路由

提供回测相关的REST API。
包含完整的回测任务管理。
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, timedelta
import logging
import threading
import os
import time

from api.models.strategy_models import StrategyDB, BacktestJobDB, BacktestResultDB
from sqlalchemy.orm import Session
from sqlalchemy import create_engine

from api.core.strategy_db import StrategySessionLocal, get_strategy_db

logger = logging.getLogger(__name__)

class BacktestConfig(BaseModel):
    commission_rate: float = Field(default=0.0003, ge=0, le=0.1, description="手续费率")
    slippage_rate: float = Field(default=0.001, ge=0, le=0.1, description="滑点率")
    stamp_duty: float = Field(default=0.001, ge=0, le=0.1, description="印花税")


class BacktestCreateRequest(BaseModel):
    strategy_id: str = Field(..., description="策略ID")
    backtest_mode: str = Field(
        default="indicator_driven",
        pattern="^(fixed_period|indicator_driven|walk_forward|monte_carlo|sensitivity)$",
        description="回测模式"
    )
    start_date: datetime = Field(..., description="开始日期")
    end_date: datetime = Field(..., description="结束日期")
    initial_capital: float = Field(default=1000000.0, ge=10000, description="初始资金")
    benchmark: str = Field(default="hs300", description="基准指数")
    config: BacktestConfig = Field(default_factory=BacktestConfig)
    enable_optimization: bool = Field(default=False, description="启用参数优化")
    optimization_params: Optional[dict] = None
    symbols: List[str] = Field(default_factory=list, description="可选股票池；为空时尝试读取策略参数")
    max_symbols: int = Field(default=200, ge=1, le=2000, description="最大股票数量保护阈值")


class BacktestJobResponse(BaseModel):
    id: str
    strategy_id: str
    backtest_mode: str
    start_date: str
    end_date: str
    initial_capital: float
    benchmark: str
    status: str
    progress: float
    error_message: Optional[str]
    result: Optional[dict]
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class BacktestListResponse(BaseModel):
    total: int
    jobs: List[BacktestJobResponse]


router = APIRouter(prefix="/api/v1/backtest", tags=["Backtest"])


def _resolve_symbols(request_symbols: List[str], strategy: StrategyDB, max_symbols: int) -> List[str]:
    parameters = strategy.parameters or {}
    candidate_lists = [
        request_symbols or [],
        parameters.get('symbols') or [],
        parameters.get('stock_pool') or [],
        parameters.get('symbol_list') or [],
        parameters.get('universe') or [],
    ]

    symbols: List[str] = []
    for source in candidate_lists:
        if source:
            symbols = [str(s).strip() for s in source if str(s).strip()]
            if symbols:
                break

    seen = set()
    deduped = []
    for symbol in symbols:
        if symbol not in seen:
            seen.add(symbol)
            deduped.append(symbol)

    if len(deduped) > max_symbols:
        raise ValueError(f"Symbol universe too large: {len(deduped)} > max_symbols={max_symbols}")

    return deduped


def _load_kline_data(start_date: datetime, end_date: datetime, symbols: List[str]):
    import pandas as pd

    database_url = os.getenv("DATABASE_URL", "postgresql://localhost/trading_agents")
    pg_engine = create_engine(database_url)

    if symbols:
        query = """
        SELECT symbol, trade_date as date, open, high, low, close, volume
        FROM stock_daily_kline
        WHERE trade_date >= %(start_date)s AND trade_date <= %(end_date)s
          AND symbol = ANY(%(symbols)s)
        ORDER BY trade_date, symbol
        """
        params = {"start_date": start_date, "end_date": end_date, "symbols": symbols}
    else:
        query = """
        SELECT symbol, trade_date as date, open, high, low, close, volume
        FROM stock_daily_kline
        WHERE trade_date >= %(start_date)s AND trade_date <= %(end_date)s
        ORDER BY trade_date, symbol
        LIMIT 50000
        """
        params = {"start_date": start_date, "end_date": end_date}

    kline_df = pd.read_sql(query, pg_engine, params=params)
    if kline_df.empty:
        universe_desc = f"symbols={symbols}" if symbols else "default limited universe"
        raise ValueError(f"No real kline data found for date range {start_date.date()} to {end_date.date()} with {universe_desc}")
    if kline_df['symbol'].nunique() == 0:
        raise ValueError("Kline data loaded but symbol universe is empty")
    logger.info(
        "Loaded %s real kline rows covering %s symbols",
        len(kline_df),
        kline_df['symbol'].nunique(),
    )
    return kline_df.to_dict('records')


def _update_strategy_performance_snapshot(db: Session, strategy: StrategyDB, result: dict):
    metrics = (result or {}).get('metrics', {})
    strategy.total_return = metrics.get('total_return')
    strategy.sharpe_ratio = metrics.get('sharpe_ratio')
    strategy.max_drawdown = metrics.get('max_drawdown')
    strategy.win_rate = metrics.get('win_rate')
    strategy.run_count = (strategy.run_count or 0) + 1
    strategy.last_run_time = datetime.now()
    strategy.updated_at = datetime.now()


def _persist_backtest_result(db: Session, job: BacktestJobDB, result: dict):
    metrics = (result or {}).get('metrics', {})
    detail = (result or {}).get('details', {})
    row = BacktestResultDB(
        job_id=job.id,
        total_return=metrics.get('total_return'),
        annual_return=metrics.get('annual_return'),
        max_drawdown=metrics.get('max_drawdown'),
        sharpe_ratio=metrics.get('sharpe_ratio'),
        sortino_ratio=metrics.get('sortino_ratio'),
        calmar_ratio=metrics.get('calmar_ratio'),
        volatility=metrics.get('volatility'),
        total_trades=metrics.get('total_trades'),
        winning_trades=metrics.get('winning_trades'),
        losing_trades=metrics.get('losing_trades'),
        win_rate=metrics.get('win_rate'),
        profit_factor=metrics.get('profit_factor'),
        avg_win=metrics.get('avg_win'),
        avg_loss=metrics.get('avg_loss'),
        avg_holding_period=metrics.get('avg_holding_days'),
        equity_curve=detail.get('equity_curve') or result.get('equity_curve'),
        drawdown_curve=detail.get('drawdown_curve') or result.get('drawdown_curve'),
        position_history=detail.get('position_history'),
        trade_list=detail.get('trade_list') or result.get('trade_list'),
        monthly_returns=detail.get('monthly_returns'),
    )
    db.add(row)


@router.post("/run", response_model=BacktestJobResponse, summary="创建回测任务")
async def create_backtest_job(request: BacktestCreateRequest, db: Session = Depends(get_strategy_db)):
    try:
        strategy = db.query(StrategyDB).filter(StrategyDB.id == request.strategy_id).first()
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")

        if request.end_date <= request.start_date:
            raise HTTPException(status_code=400, detail="End date must be after start date")

        resolved_symbols = _resolve_symbols(request.symbols, strategy, request.max_symbols)
        kline_data = _load_kline_data(request.start_date, request.end_date, resolved_symbols)

        job = BacktestJobDB(
            strategy_id=request.strategy_id,
            backtest_mode=request.backtest_mode,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
            benchmark=request.benchmark,
            commission_rate=request.config.commission_rate,
            slippage_rate=request.config.slippage_rate,
            stamp_duty=request.config.stamp_duty,
            status="pending",
            progress=0.0,
            result={
                "meta": {
                    "requested_symbols": resolved_symbols,
                    "requested_symbol_count": len(resolved_symbols),
                    "data_row_count": len(kline_data),
                }
            },
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        logger.info(f"Created backtest job: {job.id} for strategy {request.strategy_id}")

        thread = threading.Thread(target=run_backtest_thread, args=(job.id, kline_data), daemon=True)
        thread.start()
        return BacktestJobResponse(**job.to_dict())

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Backtest request rejected: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating backtest job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs", response_model=BacktestListResponse, summary="获取回测任务列表")
async def list_backtest_jobs(
    strategy_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, pattern="^(pending|running|completed|failed|cancelled)$"),
    days: int = Query(30, ge=1, le=365),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_strategy_db),
):
    try:
        query = db.query(BacktestJobDB)
        if strategy_id:
            query = query.filter(BacktestJobDB.strategy_id == strategy_id)
        if status:
            query = query.filter(BacktestJobDB.status == status)
        start_time = datetime.now() - timedelta(days=days)
        query = query.filter(BacktestJobDB.created_at >= start_time)
        query = query.order_by(BacktestJobDB.created_at.desc())
        total = query.count()
        jobs = query.offset(skip).limit(limit).all()
        return BacktestListResponse(total=total, jobs=[BacktestJobResponse(**j.to_dict()) for j in jobs])
    except Exception as e:
        logger.error(f"Error listing backtest jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}", response_model=BacktestJobResponse, summary="获取回测任务详情")
async def get_backtest_job(job_id: str, db: Session = Depends(get_strategy_db)):
    try:
        job = db.query(BacktestJobDB).filter(BacktestJobDB.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Backtest job not found")

        if job.status == 'running' and job.started_at:
            elapsed = (datetime.now() - job.started_at).total_seconds()
            if elapsed > 300:
                job.status = 'failed'
                job.progress = 1.0
                job.error_message = f'Backtest job timeout after {int(elapsed)} seconds'
                job.completed_at = datetime.now()
                db.commit()
                db.refresh(job)

        return BacktestJobResponse(**job.to_dict())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting backtest job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}/result", summary="获取回测结果详情")
async def get_backtest_result(job_id: str, db: Session = Depends(get_strategy_db)):
    try:
        job = db.query(BacktestJobDB).filter(BacktestJobDB.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Backtest job not found")
        if job.status != "completed":
            raise HTTPException(status_code=400, detail=f"Backtest job is {job.status}, not completed")
        return {
            "job_id": job_id,
            "strategy_id": job.strategy_id,
            "backtest_mode": job.backtest_mode,
            "config": {
                "start_date": job.start_date.isoformat(),
                "end_date": job.end_date.isoformat(),
                "initial_capital": job.initial_capital,
                "benchmark": job.benchmark,
            },
            "result": job.result,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting backtest result {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobs/{job_id}/cancel", summary="取消回测任务")
async def cancel_backtest_job(job_id: str, db: Session = Depends(get_strategy_db)):
    try:
        job = db.query(BacktestJobDB).filter(BacktestJobDB.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Backtest job not found")
        if job.status not in ["pending", "running"]:
            raise HTTPException(status_code=400, detail=f"Cannot cancel job with status {job.status}")
        job.status = "cancelled"
        db.commit()
        return {"success": True, "job_id": job_id, "message": "Backtest job cancelled successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error cancelling backtest job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/jobs/{job_id}", summary="删除回测任务")
async def delete_backtest_job(job_id: str, db: Session = Depends(get_strategy_db)):
    try:
        job = db.query(BacktestJobDB).filter(BacktestJobDB.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Backtest job not found")
        db.query(BacktestResultDB).filter(BacktestResultDB.job_id == job_id).delete()
        db.delete(job)
        db.commit()
        return {"success": True, "message": "Backtest job deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting backtest job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/compare", summary="多策略对比")
async def compare_strategies(job_ids: List[str] = Query(..., min_length=2, max_length=5), db: Session = Depends(get_strategy_db)):
    try:
        jobs = []
        for job_id in job_ids:
            job = db.query(BacktestJobDB).filter(BacktestJobDB.id == job_id).first()
            if not job:
                raise HTTPException(status_code=404, detail=f"Backtest job {job_id} not found")
            if job.status != "completed":
                raise HTTPException(status_code=400, detail=f"Job {job_id} is not completed")
            jobs.append(job)

        comparison = {"jobs": [j.to_dict() for j in jobs], "metrics_comparison": {}}
        for job in jobs:
            if job.result and "metrics" in job.result:
                comparison["metrics_comparison"][job.id] = job.result["metrics"]
        return comparison
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error comparing strategies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def run_backtest_thread(job_id: str, kline_data: list):
    try:
        run_backtest_sync(job_id, kline_data)
    except Exception as e:
        logger.error(f"Thread error for backtest job {job_id}: {e}")


def run_backtest_sync(job_id: str, kline_data: list):
    from tradingagents.backtest.engine_v2 import BacktestEngine
    import pandas as pd

    started_ts = time.time()
    db = StrategySessionLocal()
    try:
        job = db.query(BacktestJobDB).filter(BacktestJobDB.id == job_id).first()
        if not job:
            return
        if job.status == 'cancelled':
            return

        job.status = 'running'
        job.started_at = datetime.now()
        job.progress = 0.1
        db.commit()

        if not kline_data:
            raise ValueError('No real kline data provided to backtest engine')

        data = pd.DataFrame(kline_data)
        if data.empty:
            raise ValueError('Kline dataframe is empty')
        data['date'] = pd.to_datetime(data['date'])

        if len(data) > 300000:
            raise ValueError(f'Backtest dataset too large: {len(data)} rows > 300000 protection threshold')

        job.progress = 0.3
        db.commit()

        backtest_engine = BacktestEngine(
            initial_capital=job.initial_capital,
            commission_rate=job.commission_rate,
            slippage_rate=job.slippage_rate,
            stamp_duty=job.stamp_duty,
        )

        result_obj = backtest_engine.run_backtest(
            strategy=job.strategy.to_dict(),
            data=data,
            start_date=job.start_date,
            end_date=job.end_date,
            backtest_mode=job.backtest_mode,
        )
        self_trades = list(backtest_engine.trades)
        self_pending_orders = list(backtest_engine.pending_orders)

        result = {
            'metrics': {
                'total_return': result_obj.total_return,
                'annual_return': result_obj.annual_return,
                'benchmark_return': result_obj.benchmark_return,
                'max_drawdown': result_obj.max_drawdown,
                'max_drawdown_duration': result_obj.max_drawdown_duration,
                'volatility': result_obj.volatility,
                'sharpe_ratio': result_obj.sharpe_ratio,
                'sortino_ratio': result_obj.sortino_ratio,
                'calmar_ratio': result_obj.calmar_ratio,
                'win_rate': result_obj.win_rate,
                'total_trades': result_obj.total_trades,
                'profit_factor': result_obj.profit_factor,
                'winning_trades': result_obj.winning_trades,
                'losing_trades': result_obj.losing_trades,
                'avg_win': result_obj.avg_win,
                'avg_loss': result_obj.avg_loss,
                'avg_holding_days': result_obj.avg_holding_days,
                'final_capital': result_obj.final_capital,
            },
            'details': {
                'equity_curve': result_obj.equity_curve[:500],
                'drawdown_curve': result_obj.drawdown_curve[:500],
                'trade_list': result_obj.trade_list[:200],
                'position_history': result_obj.position_history[:500],
            },
            'summary': {
                'strategy_name': result_obj.strategy_name,
                'start_date': result_obj.start_date.isoformat(),
                'end_date': result_obj.end_date.isoformat(),
                'initial_capital': result_obj.initial_capital,
                'final_capital': result_obj.final_capital,
                'elapsed_seconds': round(time.time() - started_ts, 3),
                'data_row_count': len(data),
                'symbol_count': int(data['symbol'].nunique()),
            },
            'diagnostics': {
                'buy_trade_count': len([t for t in self_trades if t.direction == 'buy']),
                'sell_trade_count': len([t for t in self_trades if t.direction == 'sell']),
                'pending_order_count_end': len(self_pending_orders),
                'has_any_trade': len(self_trades) > 0,
                'zero_trade_reason': 'no_signal_or_no_executable_orders' if len(self_trades) == 0 else None,
            }
        }

        job.progress = 0.9
        db.commit()

        job.result = result
        job.status = 'completed'
        job.progress = 1.0
        job.error_message = None
        job.completed_at = datetime.now()

        _persist_backtest_result(db, job, result)
        _update_strategy_performance_snapshot(db, job.strategy, result)
        db.commit()
        logger.info(f"Completed backtest job {job_id}")

    except Exception as e:
        logger.error(f"Error running backtest job {job_id}: {e}")
        db.rollback()
        try:
            job = db.query(BacktestJobDB).filter(BacktestJobDB.id == job_id).first()
            if job:
                job.status = 'failed'
                job.progress = 1.0
                job.error_message = str(e)
                job.completed_at = datetime.now()
                db.commit()
        except Exception as inner:
            logger.error(f"Failed to persist backtest failure state for {job_id}: {inner}")
    finally:
        db.close()

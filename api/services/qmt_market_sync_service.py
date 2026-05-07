from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time as dtime, timezone

from sqlalchemy import text

from api.backtest_data_api import _refresh_daily_kline_cache_from_db
from api.core.settings import settings
from api.database import SessionLocal
from api.services.qmt_market_data_service import (
    build_market_integrity_report,
    capture_intraday_symbols,
    get_index_presets,
    is_index_symbol,
    sync_major_index_daily,
)
from api.services.market_data_pipeline_service import preferred_daily_kline_table
from api.services.qmt_minute_subscription_service import _resolve_capture_symbols
from tradingagents.dataflows.trade_calendar import CN_TZ, is_cn_trading_day


logger = logging.getLogger(__name__)
_TASK: asyncio.Task | None = None
_STOP_EVENT: asyncio.Event | None = None
_POLL_SECONDS = 60
_LAST_EOD_SYNC_DATE: date | None = None
_LAST_REPAIR_SYNC_DATE: date | None = None


async def start_background_worker() -> None:
    global _TASK, _STOP_EVENT
    if _TASK and not _TASK.done():
        return
    _STOP_EVENT = asyncio.Event()
    _TASK = asyncio.create_task(_run_loop(), name="qmt-market-sync")


async def stop_background_worker() -> None:
    global _TASK, _STOP_EVENT
    if _STOP_EVENT is not None:
        _STOP_EVENT.set()
    if _TASK is not None:
        try:
            await _TASK
        except Exception:
            logger.exception("[qmt-market-sync] stop worker failed")
    _TASK = None
    _STOP_EVENT = None


async def _run_loop() -> None:
    logger.info("[qmt-market-sync] background worker started")
    while _STOP_EVENT is not None and not _STOP_EVENT.is_set():
        try:
            await asyncio.to_thread(_scan_and_run_once)
        except Exception:
            logger.exception("[qmt-market-sync] loop iteration failed")
        try:
            await asyncio.wait_for(_STOP_EVENT.wait(), timeout=_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass
    logger.info("[qmt-market-sync] background worker stopped")


def _scan_and_run_once() -> None:
    global _LAST_EOD_SYNC_DATE, _LAST_REPAIR_SYNC_DATE
    local_now = datetime.now(timezone.utc).astimezone(CN_TZ)
    if not _is_trading_day(local_now):
        return

    trade_date = local_now.date().isoformat()
    account_key = str(settings.qmt_history_account_key or "paper_sim").strip() or "paper_sim"
    symbols = _load_active_market_symbols(account_key)

    if _is_trading_session(local_now):
        capture_result = capture_intraday_symbols(symbols, trade_date=trade_date, period="1m", account_key=account_key)
        logger.info(
            "[qmt-market-sync] intraday capture rows=%s symbols=%s success=%s",
            capture_result.get("rows", 0),
            len(symbols),
            capture_result.get("success"),
        )

    if _should_run_eod_sync(local_now, _LAST_EOD_SYNC_DATE):
        _run_eod_sync(local_now, symbols, account_key=account_key)
        _LAST_EOD_SYNC_DATE = local_now.date()

    if _should_run_repair_sync(local_now, _LAST_REPAIR_SYNC_DATE):
        _run_repair_sync(local_now, symbols, account_key=account_key)
        _LAST_REPAIR_SYNC_DATE = local_now.date()


def _run_eod_sync(local_now: datetime, symbols: list[str], *, account_key: str) -> None:
    trade_date = local_now.date().isoformat()
    intraday_result = capture_intraday_symbols(symbols, trade_date=trade_date, period="1m", account_key=account_key)
    stock_daily_result = _run_stock_daily_sync(local_now, symbols)
    index_daily_result = sync_major_index_daily(start_date=trade_date, end_date=trade_date, account_key=account_key)
    with SessionLocal() as db:
        latest_trade_date = _load_latest_stock_daily_trade_date(db)
        cache_result = _refresh_daily_kline_cache_from_db(
            db,
            start_date=latest_trade_date,
            end_date=latest_trade_date,
        ) if latest_trade_date else {"updated": False, "records": 0}
        integrity = build_market_integrity_report(db, target_date=trade_date)
    logger.info(
        "[qmt-market-sync] eod sync trade_date=%s intraday_rows=%s stock_daily_mode=%s stock_daily_records=%s index_daily_rows=%s cache_updated=%s integrity_tables=%s",
        trade_date,
        intraday_result.get("rows", 0),
        stock_daily_result.get("mode"),
        stock_daily_result.get("records", 0),
        index_daily_result.get("rows", 0),
        cache_result.get("updated", False),
        ",".join(sorted((integrity.get("tables") or {}).keys())),
    )


def _run_repair_sync(local_now: datetime, symbols: list[str], *, account_key: str) -> None:
    trade_date = local_now.date().isoformat()
    stock_daily_result = _run_stock_daily_sync(local_now, symbols)
    index_daily_result = sync_major_index_daily(start_date=trade_date, end_date=trade_date, account_key=account_key)
    with SessionLocal() as db:
        latest_trade_date = _load_latest_stock_daily_trade_date(db)
        cache_result = _refresh_daily_kline_cache_from_db(
            db,
            start_date=latest_trade_date,
            end_date=latest_trade_date,
        ) if latest_trade_date else {"updated": False, "records": 0}
        integrity = build_market_integrity_report(db, target_date=trade_date)
    logger.info(
        "[qmt-market-sync] repair sync trade_date=%s stock_daily_mode=%s stock_daily_records=%s index_daily_rows=%s cache_updated=%s integrity_tables=%s",
        trade_date,
        stock_daily_result.get("mode"),
        stock_daily_result.get("records", 0),
        index_daily_result.get("rows", 0),
        cache_result.get("updated", False),
        ",".join(sorted((integrity.get("tables") or {}).keys())),
    )


def _run_stock_daily_sync(local_now: datetime, symbols: list[str]) -> dict[str, object]:
    task_ids = _trigger_stock_daily_auto_updates()
    if task_ids:
        return {
            "success": True,
            "mode": "backtest_auto_update",
            "task_ids": task_ids,
            "records": 0,
        }

    stock_codes = _extract_stock_codes(symbols)
    if not stock_codes:
        return {
            "success": False,
            "mode": "skipped_no_stock_symbols",
            "task_ids": [],
            "records": 0,
        }

    return _run_targeted_stock_daily_sync(local_now.date(), stock_codes)


def _trigger_stock_daily_auto_updates() -> list[int]:
    from api.services import backtest_data_auto_update_service

    task_ids: list[int] = []
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT id, enabled_data_types
            FROM backtest_data_configs
            WHERE auto_download = TRUE
            ORDER BY updated_at DESC, id DESC
        """)).fetchall()
    for row in rows:
        enabled = {str(item).strip() for item in (row.enabled_data_types or []) if str(item).strip()}
        if "daily_kline" not in enabled:
            continue
        try:
            task_ids.extend(backtest_data_auto_update_service.trigger_config_now(int(row.id)))
        except Exception:
            logger.exception("[qmt-market-sync] trigger stock daily auto update failed config_id=%s", row.id)
    return task_ids


def _run_targeted_stock_daily_sync(trade_day: date, stock_codes: list[str]) -> dict[str, object]:
    from api.data_downloader import DataDownloader

    success_symbols = 0
    error_symbols = 0
    total_records = 0
    samples: list[str] = []
    with SessionLocal() as db:
        downloader = DataDownloader(db)
        for code in stock_codes[:200]:
            try:
                result = asyncio.run(downloader.download_daily_kline(code, trade_day, trade_day, force=True))
            except Exception as exc:
                logger.warning("[qmt-market-sync] targeted stock daily sync failed symbol=%s error=%s", code, exc)
                error_symbols += 1
                continue
            if result.get("success"):
                success_symbols += 1
                total_records += int(result.get("records") or 0)
                if len(samples) < 10:
                    samples.append(code)
            else:
                error_symbols += 1
    return {
        "success": success_symbols > 0,
        "mode": "targeted_daily_sync",
        "records": total_records,
        "success_symbols": success_symbols,
        "error_symbols": error_symbols,
        "sample_symbols": samples,
    }


def _extract_stock_codes(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    codes: list[str] = []
    for symbol in symbols:
        normalized = str(symbol or "").strip().upper()
        if not normalized or is_index_symbol(normalized):
            continue
        code = normalized.split(".", 1)[0]
        if len(code) == 6 and code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def _load_latest_stock_daily_trade_date(db) -> date | None:
    table_name = preferred_daily_kline_table()
    return db.execute(text(f"SELECT MAX(trade_date) FROM {table_name}")).scalar()


def _load_active_market_symbols(account_key: str) -> list[str]:
    seen: set[str] = set()
    symbols: list[str] = []

    def _add_many(values: list[str]) -> None:
        for item in values:
            symbol = str(item or "").strip().upper()
            if symbol and symbol not in seen:
                seen.add(symbol)
                symbols.append(symbol)

    _add_many([item["symbol"] for item in get_index_presets()])
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT *
            FROM backtest_data_configs
            WHERE auto_download = TRUE
              AND data_source_preference = 'qmt'
            ORDER BY updated_at DESC, id DESC
        """)).fetchall()
        for row in rows:
            enabled = {str(item).strip() for item in (row.enabled_data_types or []) if str(item).strip()}
            if "minute_kline" not in enabled:
                continue
            resolved = _resolve_capture_symbols(db, str(row.user_id), row.default_symbols or [], account_key=account_key)
            _add_many(resolved)
    return symbols[:400]


def _is_trading_day(local_now: datetime) -> bool:
    try:
        return is_cn_trading_day(local_now.date().isoformat())
    except Exception:
        return local_now.weekday() < 5


def _is_trading_session(local_now: datetime) -> bool:
    current = local_now.time()
    return dtime(9, 30) <= current <= dtime(11, 30) or dtime(13, 0) <= current <= dtime(15, 0)


def _should_run_eod_sync(local_now: datetime, last_sync_date: date | None) -> bool:
    if last_sync_date == local_now.date():
        return False
    if not _is_trading_day(local_now):
        return False
    return local_now.time() >= dtime(15, 35)


def _should_run_repair_sync(local_now: datetime, last_sync_date: date | None) -> bool:
    if last_sync_date == local_now.date():
        return False
    if not _is_trading_day(local_now):
        return False
    return local_now.time() >= dtime(18, 30)

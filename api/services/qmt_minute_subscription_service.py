from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone, time as dtime

from sqlalchemy import text

from api.core.settings import settings
from api.database import SessionLocal
from api.services import qmt_virtual_account_service, watchlist_service
from api.services.qmt_realtime_minute_capture_service import capture_today_minute_bars
from tradingagents.dataflows.trade_calendar import is_cn_trading_day


logger = logging.getLogger(__name__)
_TASK: asyncio.Task | None = None
_STOP_EVENT: asyncio.Event | None = None
_POLL_SECONDS = 60
_CAPTURE_SCOPE_PREFIX = "intraday_capture:"


async def start_background_worker() -> None:
    global _TASK, _STOP_EVENT
    if _TASK and not _TASK.done():
        return
    _STOP_EVENT = asyncio.Event()
    _TASK = asyncio.create_task(_run_loop(), name="qmt-minute-subscription")


async def stop_background_worker() -> None:
    global _TASK, _STOP_EVENT
    if _STOP_EVENT is not None:
        _STOP_EVENT.set()
    if _TASK is not None:
        try:
            await _TASK
        except Exception:
            logger.exception("[qmt-minute-subscription] stop worker failed")
    _TASK = None
    _STOP_EVENT = None


async def _run_loop() -> None:
    logger.info("[qmt-minute-subscription] background worker started")
    while _STOP_EVENT is not None and not _STOP_EVENT.is_set():
        try:
            await asyncio.to_thread(_scan_and_run_once)
        except Exception:
            logger.exception("[qmt-minute-subscription] loop iteration failed")
        try:
            await asyncio.wait_for(_STOP_EVENT.wait(), timeout=_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass
    logger.info("[qmt-minute-subscription] background worker stopped")


def _scan_and_run_once() -> None:
    now = datetime.now(timezone.utc)
    local_now = now.astimezone()
    if not _is_trading_day(local_now) or not _is_trading_session(local_now):
        return
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
            if not _should_capture(db, row, now):
                continue
            _capture_single_config(db, row, now)


def _should_capture(db, row, now: datetime) -> bool:
    scope_key = _capture_scope_key(row.default_symbols or [])
    watermark = db.execute(text("""
        SELECT *
        FROM backtest_data_watermarks
        WHERE user_id = :user_id
          AND config_id = :config_id
          AND data_type = 'minute_kline_intraday'
          AND scope_key = :scope_key
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
    """), {
        "user_id": row.user_id,
        "config_id": int(row.id),
        "scope_key": scope_key,
    }).fetchone()
    last_run = getattr(watermark, "last_run_started_at", None)
    if last_run is None:
        return True
    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=timezone.utc)
    return (now - last_run) >= timedelta(seconds=55)


def _capture_single_config(db, row, now: datetime) -> None:
    account_key = str(settings.qmt_history_account_key or "paper_sim").strip() or "paper_sim"
    symbols = _resolve_capture_symbols(db, str(row.user_id), row.default_symbols or [], account_key=account_key)
    scope_key = _capture_scope_key(symbols)
    trade_date = now.astimezone().date().isoformat()
    if not symbols:
        _touch_intraday_watermark(
            db,
            user_id=str(row.user_id),
            config_id=int(row.id),
            scope_key=scope_key,
            trade_date=trade_date,
            last_run_started_at=now,
            last_status="skipped",
            last_error="未配置分钟采集股票池；请在订阅配置中设置股票池，或使用自选/持仓自动补充",
        )
        db.commit()
        return

    result = capture_today_minute_bars(
        account_key=account_key,
        symbols=symbols,
        trade_date=trade_date,
    )
    _touch_intraday_watermark(
        db,
        user_id=str(row.user_id),
        config_id=int(row.id),
        scope_key=scope_key,
        trade_date=trade_date,
        last_run_started_at=now,
        last_success_at=now if result.get("success") else None,
        last_status="success" if result.get("success") else ("no_data" if result.get("rows", 0) == 0 else "failed"),
        last_error=None if result.get("success") else str(result.get("message") or "minute capture failed"),
    )
    db.execute(text("""
        UPDATE backtest_data_configs
        SET last_updated_at = NOW(),
            updated_at = NOW()
        WHERE id = :config_id
    """), {"config_id": int(row.id)})
    db.commit()
    logger.info(
        "[qmt-minute-subscription] config=%s symbols=%s rows=%s status=%s",
        row.id,
        len(symbols),
        result.get("rows", 0),
        result.get("success"),
    )


def _resolve_capture_symbols(db, user_id: str, configured_symbols: list[str], *, account_key: str) -> list[str]:
    seen: set[str] = set()
    symbols: list[str] = []

    def _add_many(items: list[str]) -> None:
        for item in items:
            symbol = _normalize_symbol(item)
            if symbol and symbol not in seen:
                seen.add(symbol)
                symbols.append(symbol)

    _add_many([str(item) for item in configured_symbols if str(item).strip()])
    try:
        watchlist_items = watchlist_service.list_watchlist(db, user_id)
        _add_many([str(item.get("symbol") or "") for item in watchlist_items])
    except Exception as exc:
        logger.warning("[qmt-minute-subscription] load watchlist failed user=%s error=%s", user_id, exc)
    try:
        overview = qmt_virtual_account_service.get_qmt_virtual_account_overview(
            db,
            user_id,
            account_key=account_key,
            sync_to_imports=False,
        )
        _add_many([str(item.get("symbol") or "") for item in (overview.get("positions") or [])])
    except Exception as exc:
        logger.warning("[qmt-minute-subscription] load qmt positions failed user=%s account=%s error=%s", user_id, account_key, exc)
    return symbols[:200]


def _capture_scope_key(symbols: list[str]) -> str:
    normalized = sorted({_normalize_symbol(item) for item in symbols if _normalize_symbol(item)})
    if not normalized:
        return _CAPTURE_SCOPE_PREFIX + "auto"
    return _CAPTURE_SCOPE_PREFIX + ",".join(normalized[:200])


def _touch_intraday_watermark(
    db,
    *,
    user_id: str,
    config_id: int,
    scope_key: str,
    trade_date: str,
    last_run_started_at: datetime,
    last_success_at: datetime | None = None,
    last_status: str | None = None,
    last_error: str | None = None,
) -> None:
    existing = db.execute(text("""
        SELECT id
        FROM backtest_data_watermarks
        WHERE user_id = :user_id
          AND config_id = :config_id
          AND data_type = 'minute_kline_intraday'
          AND scope_key = :scope_key
        LIMIT 1
    """), {
        "user_id": user_id,
        "config_id": config_id,
        "scope_key": scope_key,
    }).fetchone()
    payload = {
        "user_id": user_id,
        "config_id": config_id,
        "data_source": "qmt",
        "scope_key": scope_key,
        "last_run_started_at": last_run_started_at,
        "last_data_date": trade_date,
        "last_success_at": last_success_at,
        "last_status": last_status,
        "last_error": last_error,
    }
    if existing is None:
        db.execute(text("""
            INSERT INTO backtest_data_watermarks
            (user_id, config_id, data_type, data_source, scope_key, last_run_started_at, last_data_date, last_success_at, last_status, last_error, created_at, updated_at)
            VALUES (:user_id, :config_id, 'minute_kline_intraday', :data_source, :scope_key, :last_run_started_at, :last_data_date, :last_success_at, :last_status, :last_error, NOW(), NOW())
        """), payload)
        return
    db.execute(text("""
        UPDATE backtest_data_watermarks
        SET data_source = :data_source,
            last_run_started_at = :last_run_started_at,
            last_data_date = :last_data_date,
            last_success_at = COALESCE(:last_success_at, last_success_at),
            last_status = :last_status,
            last_error = :last_error,
            updated_at = NOW()
        WHERE id = :id
    """), {**payload, "id": existing.id})


def _normalize_symbol(value: str) -> str:
    text_value = str(value or "").strip().upper()
    if not text_value:
        return ""
    if "." in text_value:
        return text_value
    if len(text_value) == 6 and text_value.isdigit():
        if text_value.startswith("6"):
            return f"{text_value}.SH"
        if text_value.startswith(("0", "3")):
            return f"{text_value}.SZ"
        if text_value.startswith(("4", "8")):
            return f"{text_value}.BJ"
    return text_value


def _is_trading_day(local_now: datetime) -> bool:
    try:
        return is_cn_trading_day(local_now.date().isoformat())
    except Exception:
        return True


def _is_trading_session(local_now: datetime) -> bool:
    current = local_now.time()
    return dtime(9, 30) <= current <= dtime(11, 30) or dtime(13, 0) <= current <= dtime(15, 0)

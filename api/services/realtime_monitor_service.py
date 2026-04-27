from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
from sqlalchemy import and_
from sqlalchemy.orm import Session

from api.core.strategy_db import get_strategy_db_ctx, strategy_engine
from api.database import get_db_ctx
from api.models.strategy_models import (
    Base,
    RealtimeApprovalDB,
    RealtimeEventDB,
    RealtimeMonitorDB,
)
from api.services import qmt_virtual_account_service, watchlist_service
from api.services.minute_data_service import evaluate_first_day_band_signals, evaluate_intraday_confirmation
from api.services.qmt_realtime_minute_capture_service import _fetch_minute_bars, _upsert_minute_records, capture_today_minute_bars
from api.services.strategy_dsl_compiler import compile_strategy_dsl
from api.services.strategy_platform_repository import get_platform_strategy


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
REALTIME_LOG_PATH = PROJECT_ROOT / "realtime_monitor.runtime.log"

_WORKER_TASK: asyncio.Task | None = None
_STOP_EVENT: asyncio.Event | None = None
_POLL_SECONDS = 5


def create_monitor(strategy_db: Session, main_db: Session, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    Base.metadata.create_all(strategy_engine)
    strategy = _require_strategy(strategy_db, str(payload.get("strategy_id") or ""))
    compiled = _compile_strategy_payload(strategy)
    if compiled.status != "passed":
        raise ValueError("策略 DSL 编译未通过，不能创建实时监控实例：" + "；".join(compiled.errors))

    account_key = str(payload.get("account_key") or "paper_sim").strip() or "paper_sim"
    account_role = _account_role(account_key)
    live_trading_enabled = bool(payload.get("live_trading_enabled", False))
    execution_mode = str(payload.get("execution_mode") or "auto").strip() or "auto"
    if account_role == "live" and live_trading_enabled and not bool(payload.get("live_confirmed")):
        raise ValueError("实盘自动交易必须显式确认 live_confirmed=true")

    pool_config = dict(payload.get("monitor_pool") or {})
    pool_config.setdefault("mode", "strategy_positions_watchlist")
    pool_config["resolved_symbols"] = _resolve_monitor_symbols(main_db, user_id, account_key, strategy, pool_config)

    monitor = RealtimeMonitorDB(
        id=uuid4().hex,
        user_id=user_id,
        name=str(payload.get("name") or f"实时监控-{strategy['name']}").strip(),
        account_key=account_key,
        account_role=account_role,
        strategy_id=strategy["id"],
        strategy_version_id=payload.get("strategy_version_id") or strategy.get("current_version_id"),
        status="ready",
        execution_mode=execution_mode,
        auto_trade_enabled=execution_mode == "auto",
        live_trading_enabled=live_trading_enabled,
        quote_source="qmt",
        monitor_pool_json=pool_config,
        config_json=_default_config(payload.get("config") or {}),
        risk_config_json=_default_risk_config(strategy, payload.get("risk_config") or {}),
        state_json={
            "compiled_status": compiled.status,
            "timeframes_required": compiled.timeframes_required,
            "minute_requirements": compiled.minute_requirements,
            "latest_cycle": None,
            "stats": {"signals": 0, "orders": 0, "rejections": 0, "approvals": 0},
        },
        created_at=_now_dt(),
        updated_at=_now_dt(),
    )
    strategy_db.add(monitor)
    strategy_db.commit()
    strategy_db.refresh(monitor)
    _append_event(strategy_db, monitor, "monitor_created", payload={"monitor": monitor.to_dict()})
    strategy_db.commit()
    return _monitor_payload(monitor)


def list_monitors(db: Session, user_id: str) -> list[dict[str, Any]]:
    Base.metadata.create_all(strategy_engine)
    rows = (
        db.query(RealtimeMonitorDB)
        .filter(RealtimeMonitorDB.user_id == user_id)
        .order_by(RealtimeMonitorDB.updated_at.desc(), RealtimeMonitorDB.created_at.desc())
        .all()
    )
    return [_monitor_payload(row) for row in rows]


def get_monitor(db: Session, user_id: str, monitor_id: str) -> dict[str, Any]:
    return _monitor_payload(_require_monitor(db, user_id, monitor_id))


def delete_monitor(db: Session, user_id: str, monitor_id: str) -> dict[str, Any]:
    monitor = _require_monitor(db, user_id, monitor_id)
    payload = _monitor_payload(monitor)
    db.query(RealtimeApprovalDB).filter(
        RealtimeApprovalDB.monitor_id == monitor.id,
        RealtimeApprovalDB.user_id == user_id,
    ).delete(synchronize_session=False)
    db.query(RealtimeEventDB).filter(
        RealtimeEventDB.monitor_id == monitor.id,
        RealtimeEventDB.user_id == user_id,
    ).delete(synchronize_session=False)
    db.delete(monitor)
    db.commit()
    return {
        "message": "实时监控实例已删除",
        "monitor": payload,
    }


def start_monitor(db: Session, user_id: str, monitor_id: str) -> dict[str, Any]:
    monitor = _require_monitor(db, user_id, monitor_id)
    strategy = _require_strategy(db, monitor.strategy_id)
    compiled = _compile_strategy_payload(strategy)
    if compiled.status != "passed":
        monitor.status = "error"
        monitor.fused_reason = "策略 DSL 编译未通过"
        monitor.updated_at = _now_dt()
        db.add(monitor)
        _append_event(db, monitor, "monitor_error", error_payload={"errors": compiled.errors})
        db.commit()
        raise ValueError("策略 DSL 编译未通过，不能启动实时监控：" + "；".join(compiled.errors))

    if monitor.account_role == "live" and monitor.auto_trade_enabled and not monitor.live_trading_enabled:
        _append_event(db, monitor, "live_readonly_guard", payload={"message": "实盘未进入白名单，启动为只读监控"})
        monitor.auto_trade_enabled = False
        monitor.execution_mode = "monitor_only"

    monitor.status = "running"
    monitor.fused_reason = None
    monitor.updated_at = _now_dt()
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    _append_event(db, monitor, "monitor_started", payload={"status": monitor.status})
    db.commit()
    return _monitor_payload(monitor)


def pause_monitor(db: Session, user_id: str, monitor_id: str) -> dict[str, Any]:
    monitor = _require_monitor(db, user_id, monitor_id)
    monitor.status = "paused"
    monitor.updated_at = _now_dt()
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    _append_event(db, monitor, "monitor_paused", payload={"status": monitor.status})
    db.commit()
    return _monitor_payload(monitor)


def stop_monitor(db: Session, user_id: str, monitor_id: str) -> dict[str, Any]:
    monitor = _require_monitor(db, user_id, monitor_id)
    monitor.status = "halted"
    monitor.updated_at = _now_dt()
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    _append_event(db, monitor, "monitor_stopped", payload={"status": monitor.status})
    db.commit()
    return _monitor_payload(monitor)


def resume_monitor(db: Session, user_id: str, monitor_id: str) -> dict[str, Any]:
    monitor = _require_monitor(db, user_id, monitor_id)
    if monitor.status not in {"paused", "halted", "ready"}:
        raise ValueError("只有 ready/paused/halted 状态可以恢复运行")
    monitor.status = "running"
    monitor.updated_at = _now_dt()
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    _append_event(db, monitor, "monitor_resumed", payload={"status": monitor.status})
    db.commit()
    return _monitor_payload(monitor)


def fuse_reset_monitor(db: Session, user_id: str, monitor_id: str) -> dict[str, Any]:
    monitor = _require_monitor(db, user_id, monitor_id)
    if monitor.status != "fused":
        raise ValueError("当前实例未处于熔断状态")
    monitor.status = "paused"
    monitor.fused_reason = None
    monitor.updated_at = _now_dt()
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    _append_event(db, monitor, "fuse_reset", payload={"status": monitor.status})
    db.commit()
    return _monitor_payload(monitor)


def run_monitor_once(strategy_db: Session, main_db: Session, user_id: str, monitor_id: str) -> dict[str, Any]:
    monitor = _require_monitor(strategy_db, user_id, monitor_id)
    if monitor.status not in {"ready", "paused", "running"}:
        raise ValueError("只有 ready/paused/running 状态可以立即执行一轮监控")
    if monitor.status == "fused":
        raise ValueError("当前实例已熔断，请先解除熔断后再执行")
    _append_event(strategy_db, monitor, "manual_cycle_requested", payload={"source": "manual_run_once"})
    strategy_db.commit()
    _run_monitor_cycle(monitor_id, force=True, trigger_source="manual")
    strategy_db.expire_all()
    refreshed = _require_monitor(strategy_db, user_id, monitor_id)
    return {
        "monitor": _monitor_payload(refreshed),
        "events": list_events(strategy_db, user_id, monitor_id, limit=30),
    }


def list_events(db: Session, user_id: str, monitor_id: str, *, limit: int = 200, after_id: str | None = None) -> list[dict[str, Any]]:
    _require_monitor(db, user_id, monitor_id)
    query = db.query(RealtimeEventDB).filter(
        RealtimeEventDB.monitor_id == monitor_id,
        RealtimeEventDB.user_id == user_id,
    )
    if after_id:
        cursor = db.query(RealtimeEventDB).filter(RealtimeEventDB.id == after_id).first()
        if cursor and cursor.created_at:
            query = query.filter(RealtimeEventDB.created_at > cursor.created_at)
    rows = query.order_by(RealtimeEventDB.created_at.desc()).limit(max(min(limit, 1000), 1)).all()
    return [row.to_dict() for row in reversed(rows)]


def list_orders(db: Session, user_id: str, monitor_id: str) -> list[dict[str, Any]]:
    _require_monitor(db, user_id, monitor_id)
    order_event_types = [
        "order_intent",
        "order_submitted",
        "order_snapshot_refreshed",
        "order_status_changed",
        "order_cancel_requested",
        "order_cancelled",
        "order_cancel_error",
        "order_replace_requested",
        "order_rejected",
        "order_error",
    ]
    rows = (
        db.query(RealtimeEventDB)
        .filter(
            RealtimeEventDB.user_id == user_id,
            RealtimeEventDB.monitor_id == monitor_id,
            RealtimeEventDB.event_type.in_(order_event_types),
        )
        .order_by(RealtimeEventDB.created_at.desc())
        .limit(200)
        .all()
    )
    return [row.to_dict() for row in rows]


def list_trades(db: Session, user_id: str, monitor_id: str) -> list[dict[str, Any]]:
    _require_monitor(db, user_id, monitor_id)
    rows = (
        db.query(RealtimeEventDB)
        .filter(
            RealtimeEventDB.user_id == user_id,
            RealtimeEventDB.monitor_id == monitor_id,
            RealtimeEventDB.event_type.in_(["trade_confirmed", "position_changed", "order_submitted"]),
        )
        .order_by(RealtimeEventDB.created_at.desc())
        .limit(200)
        .all()
    )
    return [row.to_dict() for row in rows]


def get_positions(db: Session, main_db: Session, user_id: str, monitor_id: str) -> dict[str, Any]:
    monitor = _require_monitor(db, user_id, monitor_id)
    overview = qmt_virtual_account_service.get_qmt_virtual_account_overview(main_db, user_id, account_key=monitor.account_key)
    return {
        "monitor_id": monitor.id,
        "account_key": monitor.account_key,
        "positions": overview.get("positions") or [],
        "account": overview.get("account"),
        "connection": overview.get("connection"),
        "fetched_at": overview.get("fetched_at"),
    }


def list_approvals(db: Session, user_id: str, status: str | None = None) -> list[dict[str, Any]]:
    query = db.query(RealtimeApprovalDB).filter(RealtimeApprovalDB.user_id == user_id)
    if status:
        query = query.filter(RealtimeApprovalDB.status == status)
    rows = query.order_by(RealtimeApprovalDB.created_at.desc()).limit(200).all()
    return [row.to_dict() for row in rows]


def approve_task(db: Session, main_db: Session, user_id: str, approval_id: str, decision: dict[str, Any] | None = None) -> dict[str, Any]:
    approval = _require_approval(db, user_id, approval_id)
    monitor = _require_monitor(db, user_id, approval.monitor_id)
    if approval.status != "pending":
        raise ValueError("该确认任务已处理")
    intent = dict(approval.order_intent_json or {})
    result = _execute_order_intent(db, main_db, monitor, intent, reason="manual_approval")
    approval.status = "executed" if result.get("success") else "approved"
    approval.decision_json = dict(decision or {}) | {"broker_result": result}
    approval.decided_at = _now_dt()
    approval.updated_at = _now_dt()
    db.add(approval)
    db.commit()
    db.refresh(approval)
    _append_event(db, monitor, "approval_executed", symbol=approval.symbol, order_payload=intent, broker_result=result)
    db.commit()
    return approval.to_dict()


def reject_task(db: Session, user_id: str, approval_id: str, decision: dict[str, Any] | None = None) -> dict[str, Any]:
    approval = _require_approval(db, user_id, approval_id)
    monitor = _require_monitor(db, user_id, approval.monitor_id)
    if approval.status != "pending":
        raise ValueError("该确认任务已处理")
    approval.status = "rejected"
    approval.decision_json = dict(decision or {})
    approval.decided_at = _now_dt()
    approval.updated_at = _now_dt()
    db.add(approval)
    db.commit()
    db.refresh(approval)
    _append_event(db, monitor, "approval_rejected", symbol=approval.symbol, payload={"approval_id": approval.id})
    db.commit()
    return approval.to_dict()


async def start_background_worker() -> None:
    global _WORKER_TASK, _STOP_EVENT
    if _WORKER_TASK and not _WORKER_TASK.done():
        return
    _STOP_EVENT = asyncio.Event()
    _WORKER_TASK = asyncio.create_task(_worker_loop(), name="realtime-monitor-worker")


async def stop_background_worker() -> None:
    global _WORKER_TASK, _STOP_EVENT
    if _STOP_EVENT is not None:
        _STOP_EVENT.set()
    if _WORKER_TASK is not None:
        try:
            await _WORKER_TASK
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("[realtime-monitor] stop worker failed")
    _WORKER_TASK = None
    _STOP_EVENT = None


async def _worker_loop() -> None:
    _runtime_log("实时监控后台 worker 已启动")
    while _STOP_EVENT is not None and not _STOP_EVENT.is_set():
        try:
            await asyncio.to_thread(_scan_and_run_once)
        except Exception:
            logger.exception("[realtime-monitor] scan loop failed")
            _runtime_log("实时监控后台扫描异常", level="ERROR")
        try:
            await asyncio.wait_for(_STOP_EVENT.wait(), timeout=_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass
    _runtime_log("实时监控后台 worker 已停止")


def _scan_and_run_once() -> None:
    Base.metadata.create_all(strategy_engine)
    with get_strategy_db_ctx() as db:
        rows = db.query(RealtimeMonitorDB).filter(RealtimeMonitorDB.status == "running").all()
        due_ids = [row.id for row in rows if _monitor_due(row)]
    for monitor_id in due_ids:
        try:
            _run_monitor_cycle(monitor_id)
        except Exception as exc:
            logger.exception("[realtime-monitor] run cycle failed monitor=%s", monitor_id)
            with get_strategy_db_ctx() as db:
                monitor = db.query(RealtimeMonitorDB).filter(RealtimeMonitorDB.id == monitor_id).first()
                if monitor:
                    _fuse_monitor(db, monitor, f"实时监控循环异常：{exc}")


def _run_monitor_cycle(monitor_id: str, *, force: bool = False, trigger_source: str = "worker") -> None:
    with get_strategy_db_ctx() as strategy_db, get_db_ctx() as main_db:
        monitor = strategy_db.query(RealtimeMonitorDB).filter(RealtimeMonitorDB.id == monitor_id).first()
        if monitor is None:
            return
        if force:
            if monitor.status not in {"ready", "paused", "running"}:
                return
        elif monitor.status != "running":
            return
        cycle_id = uuid4().hex
        now = _now_dt()
        strategy = _require_strategy(strategy_db, monitor.strategy_id)
        compiled = _compile_strategy_payload(strategy)
        if compiled.status != "passed":
            _fuse_monitor(strategy_db, monitor, "策略 DSL 编译失败")
            return

        pool = dict(monitor.monitor_pool_json or {})
        symbols = _resolve_monitor_symbols(main_db, monitor.user_id, monitor.account_key, strategy, pool)
        pool["resolved_symbols"] = symbols
        monitor.monitor_pool_json = pool
        monitor.last_heartbeat_at = now
        monitor.updated_at = now
        _append_event(
            strategy_db,
            monitor,
            "cycle_started",
            payload={"cycle_id": cycle_id, "symbol_count": len(symbols), "trigger_source": trigger_source},
            correlation_id=cycle_id,
        )
        if not symbols:
            _append_event(
                strategy_db,
                monitor,
                "cycle_skipped",
                payload={"reason": "empty_universe", "trigger_source": trigger_source},
                correlation_id=cycle_id,
            )
            strategy_db.add(monitor)
            strategy_db.commit()
            return

        overview = qmt_virtual_account_service.get_qmt_virtual_account_overview(main_db, monitor.user_id, account_key=monitor.account_key)
        _refresh_execution_state(strategy_db, main_db, monitor, overview, correlation_id=cycle_id)
        quotes = qmt_virtual_account_service._fetch_live_quotes(symbols)
        if not quotes:
            _fuse_monitor(strategy_db, monitor, "QMT/实时行情不可用，已立即熔断")
            return
        quote_sample = {symbol: quotes.get(symbol) for symbol in symbols[:10]}
        _append_event(strategy_db, monitor, "market_snapshot", payload={"cycle_id": cycle_id, "quotes": quote_sample}, correlation_id=cycle_id)

        minute_capture = capture_today_minute_bars(account_key=monitor.account_key, symbols=symbols, trade_date=now.date().isoformat())
        _append_event(
            strategy_db,
            monitor,
            "minute_capture",
            payload={
                "cycle_id": cycle_id,
                "success": bool(minute_capture.get("success")),
                "rows": int(minute_capture.get("rows") or 0),
                "trade_date": minute_capture.get("trade_date"),
                "source": minute_capture.get("source"),
                "message": minute_capture.get("message"),
            },
            correlation_id=cycle_id,
        )

        minute_features = _build_minute_features(monitor, symbols)
        _append_event(
            strategy_db,
            monitor,
            "minute_features",
            payload={"cycle_id": cycle_id, "source": minute_features.get("source"), "timeframe": minute_features.get("timeframe"), "items": minute_features.get("items", [])[:20]},
            correlation_id=cycle_id,
        )

        signals = _generate_signals(monitor, strategy, overview, quotes, minute_features)
        if not signals:
            _append_event(
                strategy_db,
                monitor,
                "no_signal",
                payload={"cycle_id": cycle_id, "trigger_source": trigger_source},
                correlation_id=cycle_id,
            )
            _update_state_stats(monitor, latest_cycle=cycle_id)
            strategy_db.add(monitor)
            strategy_db.commit()
            return

        for signal in signals:
            _append_event(
                strategy_db,
                monitor,
                "signal_generated",
                symbol=signal["symbol"],
                signal_payload=signal,
                correlation_id=cycle_id,
            )
            intent = _build_order_intent(monitor, overview, signal)
            risk = _risk_check(strategy_db, monitor, intent, signal)
            if not risk["passed"]:
                _append_event(
                    strategy_db,
                    monitor,
                    "order_rejected",
                    symbol=signal["symbol"],
                    signal_payload=signal,
                    risk_payload=risk,
                    order_payload=intent,
                    correlation_id=cycle_id,
                )
                _bump_stat(monitor, "rejections")
                continue

            if _needs_manual_approval(strategy_db, monitor, intent, signal):
                approval = _create_approval(strategy_db, monitor, intent, "同票多策略冲突，暂停自动执行")
                _append_event(
                    strategy_db,
                    monitor,
                    "approval_created",
                    symbol=signal["symbol"],
                    signal_payload=signal,
                    risk_payload=risk,
                    order_payload=intent,
                    payload={"approval_id": approval.id, "reason": approval.reason},
                    correlation_id=cycle_id,
                )
                _bump_stat(monitor, "approvals")
                continue

            _append_event(strategy_db, monitor, "order_intent", symbol=signal["symbol"], signal_payload=signal, risk_payload=risk, order_payload=intent, correlation_id=cycle_id)
            broker_result = _execute_order_intent(strategy_db, main_db, monitor, intent, reason="auto_monitor")
            _append_event(
                strategy_db,
                monitor,
                "order_submitted" if broker_result.get("success") else "order_error",
                symbol=signal["symbol"],
                signal_payload=signal,
                risk_payload=risk,
                order_payload=intent,
                broker_result=broker_result if broker_result.get("success") else {},
                error_payload={} if broker_result.get("success") else broker_result,
                correlation_id=cycle_id,
            )
            if broker_result.get("success"):
                _bump_stat(monitor, "orders")
                _register_pending_order(monitor, broker_result, intent)
                _append_broker_followup_events(strategy_db, monitor, signal["symbol"], broker_result, correlation_id=cycle_id)

        _bump_stat(monitor, "signals", len(signals))
        _update_state_stats(monitor, latest_cycle=cycle_id)
        strategy_db.add(monitor)
        strategy_db.commit()


def _monitor_due(monitor: RealtimeMonitorDB) -> bool:
    interval = int((monitor.config_json or {}).get("poll_interval_seconds") or 20)
    if monitor.last_heartbeat_at is None:
        return True
    return (_now_dt() - _ensure_utc(monitor.last_heartbeat_at)) >= timedelta(seconds=max(interval, 5))


def _compile_strategy_payload(strategy: dict[str, Any]):
    version = strategy.get("current_version") or {}
    dsl = version.get("dsl") or {}
    return compile_strategy_dsl(dsl)


def _resolve_monitor_symbols(main_db: Session, user_id: str, account_key: str, strategy: dict[str, Any], pool: dict[str, Any]) -> list[str]:
    mode = str(pool.get("mode") or "strategy_positions_watchlist").strip().lower()
    symbols: set[str] = set()
    if mode not in {"qmt_positions_only", "positions_only"}:
        for raw in pool.get("symbols") or pool.get("manual_symbols") or []:
            normalized = _normalize_symbol(raw)
            if normalized:
                symbols.add(normalized)
        if mode not in {"manual_only"}:
            dsl = (strategy.get("current_version") or {}).get("dsl") or {}
            universe = dsl.get("universe") or {}
            for raw in universe.get("symbols") or []:
                normalized = _normalize_symbol(raw)
                if normalized:
                    symbols.add(normalized)
    try:
        overview = qmt_virtual_account_service.get_qmt_virtual_account_overview(main_db, user_id, account_key=account_key)
        for position in overview.get("positions") or []:
            normalized = _normalize_symbol(position.get("symbol"))
            if normalized:
                symbols.add(normalized)
    except Exception as exc:
        logger.warning("[realtime-monitor] resolve qmt positions failed: %s", exc)
    if mode not in {"qmt_positions_only", "positions_only", "manual_only"}:
        try:
            for item in watchlist_service.list_watchlist(main_db, user_id):
                normalized = _normalize_symbol(item.get("symbol"))
                if normalized:
                    symbols.add(normalized)
        except Exception as exc:
            logger.warning("[realtime-monitor] resolve watchlist failed: %s", exc)
    return sorted(symbols)


def _build_minute_features(monitor: RealtimeMonitorDB, symbols: list[str]) -> dict[str, Any]:
    trade_date = datetime.now().date().isoformat()
    config = dict(monitor.config_json or {})
    signal_mode = str(config.get("signal_mode") or "intraday_confirmation").strip().lower()
    timeframe = str(config.get("signal_timeframe") or "30m").strip().lower() or "30m"
    try:
        if signal_mode == "first_day_band":
            result = evaluate_first_day_band_signals(symbols=symbols, trade_date=trade_date, timeframe=timeframe)
            if not _minute_result_covers_trade_date(result.items, trade_date):
                supplemented = _supplement_first_day_band_result(
                    account_key=monitor.account_key,
                    symbols=symbols,
                    trade_date=trade_date,
                    timeframe=timeframe,
                )
                if supplemented is not None:
                    result = supplemented
        else:
            result = evaluate_intraday_confirmation(symbols=symbols, trade_date=trade_date, timeframe=timeframe)
        return {"timeframe": result.timeframe, "source": result.source, "items": result.items, "missing_symbols": result.missing_symbols}
    except Exception as exc:
        return {"timeframe": timeframe, "source": "unavailable", "items": [], "missing_symbols": symbols, "error": str(exc), "signal_mode": signal_mode}


def _minute_result_covers_trade_date(items: list[dict[str, Any]], trade_date: str) -> bool:
    for item in items or []:
        bar_end = str(item.get("bar_end") or "")
        if bar_end[:10] == trade_date:
            return True
    return False


def _supplement_first_day_band_result(
    *,
    account_key: str,
    symbols: list[str],
    trade_date: str,
    timeframe: str,
):
    config = qmt_virtual_account_service._resolve_runtime_config(account_key)
    live_records = _fetch_minute_bars(config, symbols, trade_date)
    if not live_records:
        return None
    try:
        _upsert_minute_records(live_records)
    except Exception as exc:
        logger.warning("[realtime-monitor] minute supplement upsert failed trade_date=%s symbols=%s error=%s", trade_date, len(symbols), exc)
    supplement_frame = pd.DataFrame(live_records)
    if supplement_frame.empty:
        return None
    return evaluate_first_day_band_signals(
        symbols=symbols,
        trade_date=trade_date,
        timeframe=timeframe,
        supplement_frame=supplement_frame,
        supplement_source="qmt_bridge_live",
    )


def _generate_signals(
    monitor: RealtimeMonitorDB,
    strategy: dict[str, Any],
    overview: dict[str, Any],
    quotes: dict[str, dict[str, Any]],
    minute_features: dict[str, Any],
) -> list[dict[str, Any]]:
    config = monitor.config_json or {}
    signal_mode = str(config.get("signal_mode") or "intraday_confirmation").strip().lower()
    signal_timeframe = str(config.get("signal_timeframe") or minute_features.get("timeframe") or "30m").strip().lower()
    max_signals = int(config.get("max_signals_per_cycle") or 3)
    positions = {item.get("symbol"): item for item in (overview.get("positions") or []) if item.get("symbol")}
    signals: list[dict[str, Any]] = []
    risk = dict(monitor.risk_config_json or {})
    stop_loss_pct = float(risk.get("stop_loss_pct") or 0.0)
    for symbol, position in positions.items():
        quote = quotes.get(symbol) or {}
        price = _to_float(quote.get("price"), position.get("current_price"))
        avg_cost = _to_float(position.get("average_cost"))
        if stop_loss_pct > 0 and price and avg_cost and price <= avg_cost * (1 - stop_loss_pct):
            signals.append(
                {
                    "symbol": symbol,
                    "side": "sell",
                    "price": price,
                    "reason": f"stop_loss_{stop_loss_pct:.2%}",
                    "target_position_pct": 0.0,
                    "strategy_id": strategy["id"],
                    "source": "risk_stop_loss",
                }
            )
    if signal_mode == "first_day_band":
        for item in minute_features.get("items") or []:
            if len(signals) >= max_signals:
                break
            symbol = item.get("symbol")
            action = str(item.get("signal") or "hold").lower()
            if not symbol or action not in {"buy", "sell"}:
                continue
            quote = quotes.get(symbol) or {}
            price = _to_float(quote.get("price"), item.get("close"), quote.get("close"))
            if not price:
                continue
            if action == "buy" and symbol not in positions:
                signals.append(
                    {
                        "symbol": symbol,
                        "side": "buy",
                        "price": price,
                        "reason": f"first_day_band_{signal_timeframe}_golden_cross",
                        "target_position_pct": _target_position_pct(strategy),
                        "strategy_id": strategy["id"],
                        "source": "first_day_band_realtime",
                        "timeframe": signal_timeframe,
                    }
                )
            if action == "sell" and symbol in positions:
                signals.append(
                    {
                        "symbol": symbol,
                        "side": "sell",
                        "price": price,
                        "reason": f"first_day_band_{signal_timeframe}_death_cross",
                        "target_position_pct": 0.0,
                        "strategy_id": strategy["id"],
                        "source": "first_day_band_realtime",
                        "timeframe": signal_timeframe,
                    }
                )
    else:
        confirmed_symbols = {
            item.get("symbol")
            for item in minute_features.get("items") or []
            if item.get("confirmed") is True
        }
        for symbol in confirmed_symbols:
            if len(signals) >= max_signals:
                break
            if symbol in positions:
                continue
            quote = quotes.get(symbol) or {}
            price = _to_float(quote.get("price"), quote.get("close"))
            if not price:
                continue
            signals.append(
                {
                    "symbol": symbol,
                    "side": "buy",
                    "price": price,
                    "reason": "multi_timeframe_confirmed",
                    "target_position_pct": _target_position_pct(strategy),
                    "strategy_id": strategy["id"],
                    "source": "dsl_realtime_ir",
                }
            )
    return signals[:max_signals]


def _build_order_intent(monitor: RealtimeMonitorDB, overview: dict[str, Any], signal: dict[str, Any]) -> dict[str, Any]:
    account = overview.get("account") or {}
    positions = {item.get("symbol"): item for item in (overview.get("positions") or []) if item.get("symbol")}
    side = signal["side"]
    symbol = signal["symbol"]
    price = float(signal.get("price") or 0)
    lot_size = int((monitor.config_json or {}).get("lot_size") or 100)
    reentry_anchor_quantity = None
    if side == "sell":
        available = float((positions.get(symbol) or {}).get("available_position") or 0.0)
        quantity = int(available // lot_size) * lot_size
    else:
        total_asset = float(account.get("total_asset") or account.get("available_cash") or 0.0)
        available_cash = float(account.get("available_cash") or account.get("cash") or total_asset)
        reentry_anchor_quantity = _resolve_reentry_buy_quantity(
            monitor,
            overview,
            symbol=symbol,
            price=price,
            lot_size=lot_size,
        )
        if reentry_anchor_quantity is not None:
            quantity = reentry_anchor_quantity
        else:
            target_pct = float(signal.get("target_position_pct") or 0.02)
            target_cash = min(total_asset * target_pct, available_cash)
            quantity = int((target_cash / max(price, 0.01)) // lot_size) * lot_size
    intent = {
        "account_key": monitor.account_key,
        "symbol": symbol,
        "side": side,
        "quantity": max(quantity, 0),
        "price": None,
        "reference_price": price,
        "price_type": (monitor.config_json or {}).get("price_type") or "opponent",
        "strategy_name": f"RealtimeMonitor-{monitor.id[:8]}",
        "order_remark": signal.get("reason") or "realtime_monitor",
        "target_position_pct": signal.get("target_position_pct"),
    }
    if reentry_anchor_quantity is not None:
        intent["reentry_anchor_quantity"] = reentry_anchor_quantity
    return intent


def _risk_check(db: Session, monitor: RealtimeMonitorDB, intent: dict[str, Any], signal: dict[str, Any]) -> dict[str, Any]:
    if monitor.account_role == "live" and not monitor.live_trading_enabled:
        return {"passed": False, "reason": "live_readonly_not_whitelisted"}
    if monitor.status == "fused":
        return {"passed": False, "reason": "monitor_fused"}
    if not _is_trading_session(_now_dt()) and not bool((monitor.config_json or {}).get("allow_outside_session")):
        return {"passed": False, "reason": "outside_continuous_auction_session"}
    if int(intent.get("quantity") or 0) < int((monitor.config_json or {}).get("lot_size") or 100):
        return {"passed": False, "reason": "quantity_below_lot_size"}
    if _already_ordered_today(db, monitor, intent):
        return {"passed": False, "reason": "duplicate_order_today"}
    max_daily_orders = int((monitor.risk_config_json or {}).get("max_daily_orders") or 20)
    if _today_order_count(db, monitor) >= max_daily_orders:
        return {"passed": False, "reason": "max_daily_orders_reached"}
    return {"passed": True, "reason": "passed", "signal_source": signal.get("source")}


def _needs_manual_approval(db: Session, monitor: RealtimeMonitorDB, intent: dict[str, Any], signal: dict[str, Any]) -> bool:
    recent_cutoff = _now_dt() - timedelta(minutes=5)
    rows = (
        db.query(RealtimeEventDB)
        .filter(
            RealtimeEventDB.account_key == monitor.account_key,
            RealtimeEventDB.symbol == intent["symbol"],
            RealtimeEventDB.event_type == "signal_generated",
            RealtimeEventDB.created_at >= recent_cutoff,
            RealtimeEventDB.monitor_id != monitor.id,
        )
        .all()
    )
    for row in rows:
        other_side = (row.signal_payload or {}).get("side")
        if other_side and other_side != intent["side"]:
            return True
    return bool(
        db.query(RealtimeApprovalDB)
        .filter(
            RealtimeApprovalDB.account_key == monitor.account_key,
            RealtimeApprovalDB.symbol == intent["symbol"],
            RealtimeApprovalDB.status == "pending",
        )
        .first()
    )


def _create_approval(db: Session, monitor: RealtimeMonitorDB, intent: dict[str, Any], reason: str) -> RealtimeApprovalDB:
    approval = RealtimeApprovalDB(
        id=uuid4().hex,
        monitor_id=monitor.id,
        user_id=monitor.user_id,
        account_key=monitor.account_key,
        strategy_id=monitor.strategy_id,
        symbol=intent.get("symbol"),
        side=intent.get("side"),
        status="pending",
        reason=reason,
        order_intent_json=dict(intent),
        created_at=_now_dt(),
        updated_at=_now_dt(),
    )
    db.add(approval)
    return approval


def _execute_order_intent(db: Session, main_db: Session, monitor: RealtimeMonitorDB, intent: dict[str, Any], *, reason: str) -> dict[str, Any]:
    if monitor.account_role == "live" and not monitor.live_trading_enabled:
        return {"success": False, "error": "live_readonly_not_whitelisted"}
    if not monitor.auto_trade_enabled and reason != "manual_approval":
        return {"success": False, "error": "auto_trade_disabled"}
    try:
        result = qmt_virtual_account_service.submit_qmt_order(
            main_db,
            monitor.user_id,
            account_key=monitor.account_key,
            symbol=intent["symbol"],
            side=intent["side"],
            quantity=int(intent["quantity"]),
            price=intent.get("price"),
            price_type=str(intent.get("price_type") or "opponent"),
            strategy_name=str(intent.get("strategy_name") or "RealtimeMonitor"),
            order_remark=str(intent.get("order_remark") or reason),
        )
        return _normalize_broker_result(result)
    except Exception as exc:
        _fuse_monitor(db, monitor, f"QMT 交易接口异常：{exc}")
        return {"success": False, "error": str(exc)}


def _fuse_monitor(db: Session, monitor: RealtimeMonitorDB, reason: str) -> None:
    monitor.status = "fused"
    monitor.fused_reason = reason
    monitor.updated_at = _now_dt()
    db.add(monitor)
    _append_event(db, monitor, "monitor_fused", error_payload={"reason": reason})
    db.commit()
    _runtime_log(f"监控实例熔断 monitor={monitor.id} reason={reason}", level="ERROR")


def _append_event(
    db: Session,
    monitor: RealtimeMonitorDB,
    event_type: str,
    *,
    symbol: str | None = None,
    payload: dict[str, Any] | None = None,
    signal_payload: dict[str, Any] | None = None,
    risk_payload: dict[str, Any] | None = None,
    order_payload: dict[str, Any] | None = None,
    broker_result: dict[str, Any] | None = None,
    error_payload: dict[str, Any] | None = None,
    request_id: str | None = None,
    correlation_id: str | None = None,
) -> RealtimeEventDB:
    event = RealtimeEventDB(
        id=uuid4().hex,
        monitor_id=monitor.id,
        user_id=monitor.user_id,
        event_type=event_type,
        account_key=monitor.account_key,
        strategy_id=monitor.strategy_id,
        strategy_version_id=monitor.strategy_version_id,
        symbol=symbol,
        trade_time=_now_dt(),
        payload=_json_safe(payload or {}),
        signal_payload=_json_safe(signal_payload or {}),
        risk_payload=_json_safe(risk_payload or {}),
        order_payload=_json_safe(order_payload or {}),
        broker_result=_json_safe(broker_result or {}),
        error_payload=_json_safe(error_payload or {}),
        request_id=request_id or uuid4().hex,
        correlation_id=correlation_id,
        created_at=_now_dt(),
    )
    db.add(event)
    db.flush()
    _runtime_log(
        f"event={event_type} monitor={monitor.id} account={monitor.account_key} strategy={monitor.strategy_id} symbol={symbol or '-'}"
    )
    return event


def _append_broker_followup_events(
    db: Session,
    monitor: RealtimeMonitorDB,
    symbol: str,
    broker_result: dict[str, Any],
    *,
    correlation_id: str | None = None,
) -> None:
    latest_order = broker_result.get("latest_order")
    if isinstance(latest_order, dict) and latest_order:
        _append_event(
            db,
            monitor,
            "order_snapshot_refreshed",
            symbol=symbol,
            order_payload=latest_order,
            broker_result={"order_id": broker_result.get("order_id")},
            correlation_id=correlation_id,
        )
    latest_trade = broker_result.get("latest_trade")
    if isinstance(latest_trade, dict) and latest_trade:
        _append_event(
            db,
            monitor,
            "trade_confirmed",
            symbol=symbol,
            broker_result=latest_trade,
            correlation_id=correlation_id,
        )


def _refresh_execution_state(
    db: Session,
    main_db: Session,
    monitor: RealtimeMonitorDB,
    overview: dict[str, Any],
    *,
    correlation_id: str | None = None,
) -> None:
    tracker = _get_execution_tracker(monitor)
    current_orders = _current_order_map(overview)
    current_trades = _current_trade_map(overview)
    current_positions = _current_position_map(overview)
    if not tracker.get("initialized"):
        tracker["initialized"] = True
        tracker["last_orders"] = _json_safe(current_orders)
        tracker["seen_trade_ids"] = sorted(current_trades.keys())[-300:]
        tracker["last_positions"] = _json_safe(current_positions)
        _append_event(
            db,
            monitor,
            "execution_tracker_initialized",
            payload={
                "orders": len(current_orders),
                "trades": len(current_trades),
                "positions": len(current_positions),
            },
            correlation_id=correlation_id,
        )
    else:
        _emit_order_status_updates(db, monitor, tracker, current_orders, correlation_id=correlation_id)
        _emit_trade_updates(db, monitor, tracker, current_trades, correlation_id=correlation_id)
        _emit_position_updates(db, monitor, tracker, current_positions, correlation_id=correlation_id)
    _handle_pending_orders(db, main_db, monitor, tracker, current_orders, current_trades, correlation_id=correlation_id)
    _set_execution_tracker(monitor, tracker)


def _current_order_map(overview: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for item in overview.get("orders") or []:
        if not isinstance(item, dict):
            continue
        order_id = str(item.get("order_id") or item.get("entrust_no") or "").strip()
        if not order_id:
            continue
        rows[order_id] = _json_safe(item)
    return rows


def _current_trade_map(overview: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for item in overview.get("trades") or []:
        if not isinstance(item, dict):
            continue
        trade_id = _trade_identity(item)
        if not trade_id:
            continue
        rows[trade_id] = _json_safe(item)
    return rows


def _current_position_map(overview: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for item in overview.get("positions") or []:
        if not isinstance(item, dict):
            continue
        symbol = _normalize_symbol(item.get("symbol"))
        if not symbol:
            continue
        rows[symbol] = _json_safe(
            {
                "symbol": symbol,
                "name": item.get("name"),
                "current_position": item.get("current_position"),
                "available_position": item.get("available_position"),
                "market_value": item.get("market_value"),
                "average_cost": item.get("average_cost"),
            }
        )
    return rows


def _emit_order_status_updates(
    db: Session,
    monitor: RealtimeMonitorDB,
    tracker: dict[str, Any],
    current_orders: dict[str, dict[str, Any]],
    *,
    correlation_id: str | None = None,
) -> None:
    last_orders = dict(tracker.get("last_orders") or {})
    for order_id, item in current_orders.items():
        previous = last_orders.get(order_id)
        if previous != item:
            _append_event(
                db,
                monitor,
                "order_status_changed" if previous else "order_snapshot_refreshed",
                symbol=item.get("symbol"),
                payload={
                    "order_id": order_id,
                    "previous_status": (previous or {}).get("status"),
                    "current_status": item.get("status"),
                    "can_cancel": item.get("can_cancel"),
                    "filled_quantity": item.get("filled_quantity"),
                },
                order_payload=item,
                correlation_id=correlation_id,
            )
    tracker["last_orders"] = _json_safe(current_orders)


def _emit_trade_updates(
    db: Session,
    monitor: RealtimeMonitorDB,
    tracker: dict[str, Any],
    current_trades: dict[str, dict[str, Any]],
    *,
    correlation_id: str | None = None,
) -> None:
    seen_ids = set(str(item) for item in (tracker.get("seen_trade_ids") or []))
    for trade_id, item in current_trades.items():
        if trade_id in seen_ids:
            continue
        _append_event(
            db,
            monitor,
            "trade_confirmed",
            symbol=item.get("symbol"),
            payload={"trade_id": trade_id, "order_id": item.get("order_id")},
            broker_result=item,
            correlation_id=correlation_id,
        )
        seen_ids.add(trade_id)
        _complete_pending_order(tracker, item.get("order_id"))
    tracker["seen_trade_ids"] = sorted(seen_ids)[-500:]


def _emit_position_updates(
    db: Session,
    monitor: RealtimeMonitorDB,
    tracker: dict[str, Any],
    current_positions: dict[str, dict[str, Any]],
    *,
    correlation_id: str | None = None,
) -> None:
    last_positions = dict(tracker.get("last_positions") or {})
    changed_symbols = sorted(set(last_positions) | set(current_positions))
    for symbol in changed_symbols:
        previous = last_positions.get(symbol)
        current = current_positions.get(symbol)
        if previous == current:
            continue
        _sync_reentry_anchor_with_position_change(monitor, symbol, previous, current)
        _append_event(
            db,
            monitor,
            "position_changed",
            symbol=symbol,
            payload={"previous": previous, "current": current},
            correlation_id=correlation_id,
        )
    tracker["last_positions"] = _json_safe(current_positions)


def _handle_pending_orders(
    db: Session,
    main_db: Session,
    monitor: RealtimeMonitorDB,
    tracker: dict[str, Any],
    current_orders: dict[str, dict[str, Any]],
    current_trades: dict[str, dict[str, Any]],
    *,
    correlation_id: str | None = None,
) -> None:
    if monitor.account_role != "paper" or not monitor.auto_trade_enabled:
        return
    config = dict(monitor.config_json or {})
    if not bool(config.get("auto_cancel_replace_enabled", True)):
        return
    cancel_after_seconds = int(config.get("cancel_after_seconds") or 20)
    max_replace_attempts = int(config.get("max_replace_attempts") or 1)
    lot_size = int(config.get("lot_size") or 100)
    pending_orders = dict(tracker.get("pending_orders") or {})
    if not pending_orders:
        tracker["pending_orders"] = pending_orders
        return
    now = _now_dt()
    for order_id, entry in list(pending_orders.items()):
        current_order = current_orders.get(order_id)
        if _has_trade_for_order(current_trades, order_id):
            pending_orders.pop(order_id, None)
            continue
        if current_order is None:
            if _seconds_since(entry.get("submitted_at"), now) > cancel_after_seconds * 3:
                pending_orders.pop(order_id, None)
            continue
        if _is_terminal_order(current_order):
            pending_orders.pop(order_id, None)
            continue
        entry["last_status"] = current_order.get("status")
        entry["last_seen_at"] = now.isoformat()
        if _seconds_since(entry.get("submitted_at"), now) < cancel_after_seconds:
            continue
        if not bool(current_order.get("can_cancel")):
            continue
        replace_attempts = int(entry.get("replace_attempts") or 0)
        _append_event(
            db,
            monitor,
            "order_cancel_requested",
            symbol=current_order.get("symbol"),
            payload={"order_id": order_id, "age_seconds": _seconds_since(entry.get("submitted_at"), now), "replace_attempts": replace_attempts},
            order_payload=current_order,
            correlation_id=correlation_id,
        )
        cancel_payload = qmt_virtual_account_service.cancel_qmt_order(
            main_db,
            monitor.user_id,
            account_key=monitor.account_key,
            order_id=order_id,
        )
        cancel_result = _normalize_cancel_result(cancel_payload)
        _append_event(
            db,
            monitor,
            "order_cancelled" if cancel_result.get("success") else "order_cancel_error",
            symbol=current_order.get("symbol"),
            payload={"order_id": order_id, "replace_attempts": replace_attempts},
            order_payload=current_order,
            broker_result=cancel_result if cancel_result.get("success") else {},
            error_payload={} if cancel_result.get("success") else cancel_result,
            correlation_id=correlation_id,
        )
        pending_orders.pop(order_id, None)
        if not cancel_result.get("success") or replace_attempts >= max_replace_attempts:
            continue
        original_intent = dict(entry.get("order_intent") or {})
        replace_quantity = _remaining_quantity(current_order, original_intent, lot_size)
        if replace_quantity < lot_size:
            continue
        original_intent["quantity"] = replace_quantity
        original_intent["replace_attempts"] = replace_attempts + 1
        original_intent["order_remark"] = f"{original_intent.get('order_remark') or 'realtime_monitor'}|replace_{replace_attempts + 1}"
        _append_event(
            db,
            monitor,
            "order_replace_requested",
            symbol=original_intent.get("symbol"),
            payload={"parent_order_id": order_id, "replace_attempts": replace_attempts + 1},
            order_payload=original_intent,
            correlation_id=correlation_id,
        )
        replace_result = _execute_order_intent(db, main_db, monitor, original_intent, reason="auto_replace")
        _append_event(
            db,
            monitor,
            "order_submitted" if replace_result.get("success") else "order_error",
            symbol=original_intent.get("symbol"),
            payload={"parent_order_id": order_id, "replace_attempts": replace_attempts + 1},
            order_payload=original_intent,
            broker_result=replace_result if replace_result.get("success") else {},
            error_payload={} if replace_result.get("success") else replace_result,
            correlation_id=correlation_id,
        )
        if replace_result.get("success"):
            _bump_stat(monitor, "orders")
            tracker["pending_orders"] = _json_safe(pending_orders)
            _set_execution_tracker(monitor, tracker)
            _register_pending_order(monitor, replace_result, original_intent)
            tracker.update(_get_execution_tracker(monitor))
            pending_orders = dict(tracker.get("pending_orders") or {})
            _append_broker_followup_events(db, monitor, str(original_intent.get("symbol") or ""), replace_result, correlation_id=correlation_id)
    tracker["pending_orders"] = _json_safe(pending_orders)


def _register_pending_order(monitor: RealtimeMonitorDB, broker_result: dict[str, Any], intent: dict[str, Any]) -> None:
    order_id = str(broker_result.get("order_id") or "").strip()
    if not order_id:
        return
    tracker = _get_execution_tracker(monitor)
    latest_trade = broker_result.get("latest_trade")
    if isinstance(latest_trade, dict) and latest_trade:
        trade_id = _trade_identity(latest_trade)
        seen_ids = set(str(item) for item in (tracker.get("seen_trade_ids") or []))
        if trade_id:
            seen_ids.add(trade_id)
            tracker["seen_trade_ids"] = sorted(seen_ids)[-500:]
        _complete_pending_order(tracker, order_id)
        _set_execution_tracker(monitor, tracker)
        return
    pending_orders = dict(tracker.get("pending_orders") or {})
    pending_orders[order_id] = _json_safe(
        {
            "order_id": order_id,
            "symbol": intent.get("symbol"),
            "side": intent.get("side"),
            "quantity": intent.get("quantity"),
            "submitted_at": _now_dt().isoformat(),
            "replace_attempts": int(intent.get("replace_attempts") or 0),
            "order_intent": dict(intent),
            "last_status": (broker_result.get("latest_order") or {}).get("status"),
            "last_seen_at": _now_dt().isoformat(),
        }
    )
    tracker["pending_orders"] = pending_orders
    last_orders = dict(tracker.get("last_orders") or {})
    latest_order = broker_result.get("latest_order")
    if isinstance(latest_order, dict) and latest_order:
        last_orders[order_id] = _json_safe(latest_order)
        tracker["last_orders"] = last_orders
    _set_execution_tracker(monitor, tracker)


def _complete_pending_order(tracker: dict[str, Any], order_id: Any) -> None:
    normalized_order_id = str(order_id or "").strip()
    if not normalized_order_id:
        return
    pending_orders = dict(tracker.get("pending_orders") or {})
    if normalized_order_id in pending_orders:
        pending_orders.pop(normalized_order_id, None)
        tracker["pending_orders"] = pending_orders


def _get_execution_tracker(monitor: RealtimeMonitorDB) -> dict[str, Any]:
    state = dict(monitor.state_json or {})
    tracker = dict(state.get("execution_tracker") or {})
    tracker.setdefault("initialized", False)
    tracker.setdefault("pending_orders", {})
    tracker.setdefault("last_orders", {})
    tracker.setdefault("seen_trade_ids", [])
    tracker.setdefault("last_positions", {})
    return tracker


def _set_execution_tracker(monitor: RealtimeMonitorDB, tracker: dict[str, Any]) -> None:
    state = dict(monitor.state_json or {})
    state["execution_tracker"] = _json_safe(tracker)
    state["execution_tracker_summary"] = {
        "pending_orders": len((tracker.get("pending_orders") or {})),
        "tracked_orders": len((tracker.get("last_orders") or {})),
        "tracked_trades": len((tracker.get("seen_trade_ids") or [])),
        "tracked_positions": len((tracker.get("last_positions") or {})),
    }
    monitor.state_json = _json_safe(state)


def _resolve_reentry_buy_quantity(
    monitor: RealtimeMonitorDB,
    overview: dict[str, Any],
    *,
    symbol: str,
    price: float,
    lot_size: int,
) -> int | None:
    anchor = _get_reentry_anchor(monitor, symbol)
    if not anchor:
        return None
    positions = {item.get("symbol"): item for item in (overview.get("positions") or []) if item.get("symbol")}
    if symbol in positions:
        return None
    available_cash = float((overview.get("account") or {}).get("available_cash") or (overview.get("account") or {}).get("cash") or 0.0)
    target_quantity = int(anchor.get("quantity") or 0)
    if target_quantity <= 0:
        return None
    if lot_size > 0:
        target_quantity = int(target_quantity // lot_size) * lot_size
    affordable_quantity = int((available_cash / max(price, 0.01)) // max(lot_size, 1)) * max(lot_size, 1)
    quantity = min(target_quantity, affordable_quantity) if affordable_quantity > 0 else 0
    return quantity if quantity > 0 else None


def _sync_reentry_anchor_with_position_change(
    monitor: RealtimeMonitorDB,
    symbol: str,
    previous: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> None:
    target_symbol = _single_symbol_reentry_target(monitor)
    if target_symbol != symbol:
        return
    previous_position = int(float((previous or {}).get("current_position") or 0))
    current_position = int(float((current or {}).get("current_position") or 0))
    if previous_position > 0 and current_position <= 0:
        _set_reentry_anchor(
            monitor,
            symbol,
            quantity=previous_position,
            previous_position=previous_position,
            current_position=current_position,
            source="position_changed_exit",
        )
        return
    if current_position > 0:
        _clear_reentry_anchor(monitor, symbol, reason="position_restored")


def _single_symbol_reentry_target(monitor: RealtimeMonitorDB) -> str | None:
    config = dict(monitor.config_json or {})
    if str(config.get("signal_mode") or "").strip().lower() != "first_day_band":
        return None
    pool = dict(monitor.monitor_pool_json or {})
    if str(pool.get("mode") or "").strip().lower() != "manual_only":
        return None
    candidates = pool.get("manual_symbols") or pool.get("symbols") or pool.get("resolved_symbols") or []
    normalized = []
    seen: set[str] = set()
    for item in candidates:
        normalized_symbol = _normalize_symbol(item)
        if normalized_symbol and normalized_symbol not in seen:
            seen.add(normalized_symbol)
            normalized.append(normalized_symbol)
    if len(normalized) != 1:
        return None
    return normalized[0]


def _get_reentry_anchor(monitor: RealtimeMonitorDB, symbol: str) -> dict[str, Any] | None:
    if _single_symbol_reentry_target(monitor) != symbol:
        return None
    state = dict(monitor.state_json or {})
    anchors = dict(state.get("reentry_anchors") or {})
    anchor = anchors.get(symbol)
    return dict(anchor) if isinstance(anchor, dict) else None


def _set_reentry_anchor(
    monitor: RealtimeMonitorDB,
    symbol: str,
    *,
    quantity: int,
    previous_position: int,
    current_position: int,
    source: str,
) -> None:
    if quantity <= 0:
        return
    state = dict(monitor.state_json or {})
    anchors = dict(state.get("reentry_anchors") or {})
    anchors[symbol] = {
        "symbol": symbol,
        "quantity": int(quantity),
        "previous_position": int(previous_position),
        "current_position": int(current_position),
        "source": source,
        "captured_at": _now_dt().isoformat(),
    }
    state["reentry_anchors"] = _json_safe(anchors)
    monitor.state_json = _json_safe(state)


def _clear_reentry_anchor(monitor: RealtimeMonitorDB, symbol: str, *, reason: str) -> None:
    state = dict(monitor.state_json or {})
    anchors = dict(state.get("reentry_anchors") or {})
    if symbol not in anchors:
        return
    anchors.pop(symbol, None)
    state["reentry_anchors"] = _json_safe(anchors)
    state["reentry_anchor_last_cleared"] = {
        "symbol": symbol,
        "reason": reason,
        "cleared_at": _now_dt().isoformat(),
    }
    monitor.state_json = _json_safe(state)


def _monitor_payload(monitor: RealtimeMonitorDB) -> dict[str, Any]:
    payload = monitor.to_dict()
    payload["circuit_breaker"] = {
        "active": monitor.status == "fused",
        "reason": monitor.fused_reason,
        "last_heartbeat_at": payload.get("last_heartbeat_at"),
    }
    return payload


def _normalize_broker_result(result: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(result or {})
    nested = payload.get("order_result")
    nested_result = nested if isinstance(nested, dict) else {}
    success = bool(payload.get("success"))
    if not success:
        success = bool(nested_result.get("success"))
    order_id = (
        payload.get("order_id")
        or nested_result.get("order_id")
        or nested_result.get("entrust_no")
    )
    overview = payload.get("overview") if isinstance(payload.get("overview"), dict) else {}
    latest_order = _find_matching_broker_item(overview.get("orders"), order_id=order_id)
    latest_trade = _find_matching_broker_item(overview.get("trades"), order_id=order_id)
    bridge = nested_result.get("bridge") if isinstance(nested_result.get("bridge"), dict) else payload.get("bridge")
    error = payload.get("error") or nested_result.get("error")
    if not success and not error and nested_result:
        error = nested_result.get("raw") or nested_result
    return {
        "success": success,
        "order_id": str(order_id) if order_id not in (None, "") else None,
        "request_id": payload.get("request_id"),
        "account_key": payload.get("account_key"),
        "bridge": _json_safe(bridge or {}),
        "order_result": _json_safe(nested_result),
        "overview": _json_safe(overview),
        "latest_order": _json_safe(latest_order or {}),
        "latest_trade": _json_safe(latest_trade or {}),
        "error": _json_safe(error),
        "raw": _json_safe(payload),
    }


def _normalize_cancel_result(result: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(result or {})
    nested = payload.get("cancel_result")
    nested_result = nested if isinstance(nested, dict) else {}
    success = bool(payload.get("success"))
    if not success:
        success = bool(nested_result.get("success"))
    order_id = payload.get("order_id") or nested_result.get("order_id")
    overview = payload.get("overview") if isinstance(payload.get("overview"), dict) else {}
    latest_order = _find_matching_broker_item(overview.get("orders"), order_id=order_id)
    latest_trade = _find_matching_broker_item(overview.get("trades"), order_id=order_id)
    error = payload.get("error") or nested_result.get("error")
    return {
        "success": success,
        "order_id": str(order_id) if order_id not in (None, "") else None,
        "request_id": payload.get("request_id"),
        "account_key": payload.get("account_key"),
        "cancel_result": _json_safe(nested_result),
        "overview": _json_safe(overview),
        "latest_order": _json_safe(latest_order or {}),
        "latest_trade": _json_safe(latest_trade or {}),
        "error": _json_safe(error),
        "raw": _json_safe(payload),
    }


def _find_matching_broker_item(items: Any, *, order_id: Any) -> dict[str, Any] | None:
    if not isinstance(items, list):
        return None
    normalized_order_id = str(order_id or "").strip()
    for item in items:
        if not isinstance(item, dict):
            continue
        item_order_id = str(item.get("order_id") or item.get("entrust_no") or "").strip()
        if normalized_order_id and item_order_id == normalized_order_id:
            return item
    if not normalized_order_id and items:
        first = items[0]
        return first if isinstance(first, dict) else None
    return None


def _trade_identity(item: dict[str, Any]) -> str | None:
    trade_id = str(item.get("trade_id") or item.get("business_no") or "").strip()
    if trade_id:
        return trade_id
    parts = [
        str(item.get("order_id") or "").strip(),
        str(item.get("symbol") or "").strip(),
        str(item.get("trade_time") or "").strip(),
        str(item.get("quantity") or "").strip(),
        str(item.get("price") or "").strip(),
    ]
    if any(parts):
        return "|".join(parts)
    return None


def _has_trade_for_order(current_trades: dict[str, dict[str, Any]], order_id: str) -> bool:
    normalized_order_id = str(order_id or "").strip()
    if not normalized_order_id:
        return False
    return any(str(item.get("order_id") or "").strip() == normalized_order_id for item in current_trades.values())


def _is_terminal_order(item: dict[str, Any]) -> bool:
    status_text = str(item.get("status") or "").strip().lower()
    if any(keyword in status_text for keyword in ("filled", "cancel", "rejected", "invalid", "done", "success_all")):
        return True
    return bool(item.get("can_cancel")) is False and float(item.get("filled_quantity") or 0) >= float(item.get("quantity") or 0)


def _seconds_since(value: Any, now: datetime) -> float:
    dt = _parse_datetime(value)
    if dt is None:
        return 0.0
    return max((now - dt).total_seconds(), 0.0)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _ensure_utc(value)
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    return _ensure_utc(parsed)


def _remaining_quantity(current_order: dict[str, Any], original_intent: dict[str, Any], lot_size: int) -> int:
    total_quantity = int(float(current_order.get("quantity") or original_intent.get("quantity") or 0))
    filled_quantity = int(float(current_order.get("filled_quantity") or 0))
    remaining = max(total_quantity - filled_quantity, 0)
    if lot_size <= 0:
        return remaining
    return int(remaining // lot_size) * lot_size


def _require_monitor(db: Session, user_id: str, monitor_id: str) -> RealtimeMonitorDB:
    row = (
        db.query(RealtimeMonitorDB)
        .filter(RealtimeMonitorDB.id == monitor_id, RealtimeMonitorDB.user_id == user_id)
        .first()
    )
    if row is None:
        raise KeyError("实时监控实例不存在")
    return row


def _require_approval(db: Session, user_id: str, approval_id: str) -> RealtimeApprovalDB:
    row = db.query(RealtimeApprovalDB).filter(RealtimeApprovalDB.id == approval_id, RealtimeApprovalDB.user_id == user_id).first()
    if row is None:
        raise KeyError("确认任务不存在")
    return row


def _require_strategy(db: Session, strategy_id: str) -> dict[str, Any]:
    strategy = get_platform_strategy(db, strategy_id)
    if strategy is None:
        raise KeyError("策略不存在")
    return strategy


def _default_config(raw: dict[str, Any]) -> dict[str, Any]:
    config = {
        "poll_interval_seconds": 20,
        "price_type": "opponent",
        "lot_size": 100,
        "max_signals_per_cycle": 3,
        "signal_mode": "intraday_confirmation",
        "signal_timeframe": "30m",
        "allow_outside_session": False,
        "auto_cancel_replace_enabled": True,
        "cancel_after_seconds": 20,
        "max_replace_attempts": 1,
    }
    config.update(raw or {})
    return config


def _default_risk_config(strategy: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    dsl = (strategy.get("current_version") or {}).get("dsl") or {}
    risk = dict(dsl.get("risk") or {})
    risk.update(raw or {})
    risk.setdefault("max_daily_orders", 20)
    return risk


def _target_position_pct(strategy: dict[str, Any]) -> float:
    dsl = (strategy.get("current_version") or {}).get("dsl") or {}
    position = dsl.get("position") or {}
    return float(position.get("initial_position_pct") or position.get("max_single_position_pct") or 0.02)


def _account_role(account_key: str) -> str:
    for account in qmt_virtual_account_service._runtime_configs():
        if account.key == account_key:
            return str(account.role or "paper").lower()
    return "paper" if "paper" in account_key else "live" if "live" in account_key else "paper"


def _is_trading_session(value: datetime) -> bool:
    local = value.astimezone().time()
    return dtime(9, 30) <= local <= dtime(11, 30) or dtime(13, 0) <= local <= dtime(15, 0)


def _already_ordered_today(db: Session, monitor: RealtimeMonitorDB, intent: dict[str, Any]) -> bool:
    start = _day_start()
    return (
        db.query(RealtimeEventDB)
        .filter(
            RealtimeEventDB.monitor_id == monitor.id,
            RealtimeEventDB.event_type == "order_submitted",
            RealtimeEventDB.symbol == intent["symbol"],
            RealtimeEventDB.created_at >= start,
        )
        .first()
        is not None
    )


def _today_order_count(db: Session, monitor: RealtimeMonitorDB) -> int:
    return (
        db.query(RealtimeEventDB)
        .filter(
            RealtimeEventDB.monitor_id == monitor.id,
            RealtimeEventDB.event_type == "order_submitted",
            RealtimeEventDB.created_at >= _day_start(),
        )
        .count()
    )


def _bump_stat(monitor: RealtimeMonitorDB, key: str, amount: int = 1) -> None:
    state = dict(monitor.state_json or {})
    stats = dict(state.get("stats") or {})
    stats[key] = int(stats.get(key) or 0) + amount
    state["stats"] = stats
    monitor.state_json = state


def _update_state_stats(monitor: RealtimeMonitorDB, *, latest_cycle: str) -> None:
    state = dict(monitor.state_json or {})
    state["latest_cycle"] = latest_cycle
    state["last_updated_at"] = _now_dt().isoformat()
    monitor.state_json = state


def _runtime_log(message: str, *, level: str = "INFO") -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {level}: {message}"
    try:
        with REALTIME_LOG_PATH.open("a", encoding="utf-8") as file:
            file.write(line + "\n")
    except Exception:
        logger.debug("[realtime-monitor] write runtime log failed", exc_info=True)
    if level == "ERROR":
        logger.error("[realtime-monitor] %s", message)
    else:
        logger.info("[realtime-monitor] %s", message)


def _normalize_symbol(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if not text:
        return None
    if "." in text:
        return text
    if len(text) == 6:
        if text.startswith("6"):
            return f"{text}.SH"
        if text.startswith(("0", "3")):
            return f"{text}.SZ"
        if text.startswith(("4", "8")):
            return f"{text}.BJ"
    return text


def _to_float(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except Exception:
            continue
    return None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except Exception:
            pass
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _json_safe(item())
        except Exception:
            pass
    return str(value)


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo or timezone.utc
        return value.replace(tzinfo=local_tz).astimezone(timezone.utc)
    return value.astimezone(timezone.utc)


def _day_start() -> datetime:
    now = _now_dt()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)

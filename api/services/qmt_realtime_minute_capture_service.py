from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import requests
from sqlalchemy import create_engine, inspect, text

from api.core.env import load_project_env
from api.services import qmt_virtual_account_service


logger = logging.getLogger(__name__)


def capture_today_minute_bars(*, account_key: str, symbols: list[str], trade_date: str | None = None) -> dict[str, Any]:
    normalized_symbols = _normalize_symbols(symbols)
    if not normalized_symbols:
        return {"success": False, "message": "empty symbols", "rows": 0, "symbols": []}

    effective_trade_date = trade_date or datetime.now().date().isoformat()
    try:
        config = qmt_virtual_account_service._resolve_runtime_config(account_key)
        records = _fetch_minute_bars(config, normalized_symbols, effective_trade_date)
        if not records:
            return {
                "success": False,
                "message": "no minute bars",
                "rows": 0,
                "symbols": normalized_symbols,
                "trade_date": effective_trade_date,
                "source": "qmt_bridge",
            }

        upserted = _upsert_minute_records(records)
        return {
            "success": True,
            "message": "minute bars captured",
            "rows": upserted,
            "symbols": normalized_symbols,
            "trade_date": effective_trade_date,
            "source": "qmt_bridge",
        }
    except Exception as exc:
        logger.warning("[qmt-minute-capture] capture failed account=%s symbols=%s error=%s", account_key, len(normalized_symbols), exc)
        return {
            "success": False,
            "message": str(exc),
            "rows": 0,
            "symbols": normalized_symbols,
            "trade_date": effective_trade_date,
            "source": "qmt_bridge",
        }


def _fetch_minute_bars(config: qmt_virtual_account_service.QmtRuntimeConfig, symbols: list[str], trade_date: str) -> list[dict[str, Any]]:
    if config.bridge_base_url:
        return _fetch_via_bridge(config, symbols, trade_date)
    return _fetch_via_local_xt(config, symbols, trade_date)


def _fetch_via_bridge(config: qmt_virtual_account_service.QmtRuntimeConfig, symbols: list[str], trade_date: str) -> list[dict[str, Any]]:
    base_url = str(config.bridge_base_url or "").rstrip("/")
    headers = {}
    if config.bridge_token:
        headers["Authorization"] = f"Bearer {config.bridge_token}"
    response = requests.post(
        f"{base_url}/market/minute-bars",
        json={"symbols": symbols, "trade_date": trade_date, "period": "1m"},
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return [dict(item) for item in (payload.get("items") or []) if isinstance(item, dict)]


def _fetch_via_local_xt(config: qmt_virtual_account_service.QmtRuntimeConfig, symbols: list[str], trade_date: str) -> list[dict[str, Any]]:
    del config
    try:
        from scripts.qmt_minute_history_sync import _download_history_window, _normalize_history_frame, _read_history_window
        from xtquant import xtdata
    except Exception as exc:
        logger.warning("[qmt-minute-capture] local xt unavailable: %s", exc)
        return []
    trade_day = str(trade_date).replace("-", "").strip()
    start_time = f"{trade_day}000000"
    end_time = f"{trade_day}235959"
    records: list[dict[str, Any]] = []
    for symbol in symbols:
        try:
            _download_history_window(xtdata, symbol, "1m", start_time, end_time)
            raw = _read_history_window(xtdata, symbol, "1m", start_time, end_time)
            frame = _normalize_history_frame(raw, symbol)
            if frame.empty:
                continue
            frame_to_dump = frame.copy()
            frame_to_dump["trade_time"] = frame_to_dump["trade_time"].astype(str)
            records.extend(frame_to_dump.to_dict("records"))
        except Exception as exc:
            logger.warning("[qmt-minute-capture] fetch symbol=%s failed: %s", symbol, exc)
    return records


def _upsert_minute_records(records: list[dict[str, Any]]) -> int:
    load_project_env()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL 未配置，无法写入 stock_minute_kline")
    engine = create_engine(database_url)
    available_columns = _load_table_columns(engine, "stock_minute_kline")
    has_created_at = "created_at" in available_columns
    has_updated_at = "updated_at" in available_columns
    rows: list[dict[str, Any]] = []
    now = datetime.now()
    for item in records:
        symbol = _normalize_symbol(item.get("symbol"))
        trade_time = _normalize_trade_time(item.get("trade_time"))
        if not symbol or not trade_time:
            continue
        row = {
            "symbol": symbol,
            "trade_time": trade_time,
            "open": _safe_float(item.get("open")),
            "high": _safe_float(item.get("high")),
            "low": _safe_float(item.get("low")),
            "close": _safe_float(item.get("close")),
            "volume": int(float(item.get("volume") or 0)),
            "amount": _safe_float(item.get("amount")),
        }
        if has_created_at:
            row["created_at"] = now
        if has_updated_at:
            row["updated_at"] = now
        rows.append(row)
    if not rows:
        return 0
    insert_columns = ["symbol", "trade_time", "open", "high", "low", "close", "volume", "amount"]
    if has_created_at:
        insert_columns.append("created_at")
    if has_updated_at:
        insert_columns.append("updated_at")
    update_clauses = [
        "open = EXCLUDED.open",
        "high = EXCLUDED.high",
        "low = EXCLUDED.low",
        "close = EXCLUDED.close",
        "volume = EXCLUDED.volume",
        "amount = EXCLUDED.amount",
    ]
    if has_updated_at:
        update_clauses.append("updated_at = EXCLUDED.updated_at")
    elif has_created_at:
        update_clauses.append("created_at = EXCLUDED.created_at")
    insert_columns_sql = ", ".join(insert_columns)
    value_placeholders_sql = ", ".join(f":{column}" for column in insert_columns)
    update_sql = ",\n                ".join(update_clauses)
    with engine.begin() as conn:
        conn.execute(text(f"""
            INSERT INTO stock_minute_kline (
                {insert_columns_sql}
            ) VALUES (
                {value_placeholders_sql}
            )
            ON CONFLICT (symbol, trade_time) DO UPDATE SET
                {update_sql}
        """), rows)
    return len(rows)


def _load_table_columns(engine, table_name: str) -> set[str]:
    try:
        return {str(column["name"]) for column in inspect(engine).get_columns(table_name)}
    except Exception:
        return set()


def _normalize_symbols(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for symbol in symbols:
        normalized = _normalize_symbol(symbol)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _normalize_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol:
        return ""
    if "." in symbol:
        return symbol
    if len(symbol) == 6 and symbol.isdigit():
        if symbol.startswith("6"):
            return f"{symbol}.SH"
        if symbol.startswith(("0", "3")):
            return f"{symbol}.SZ"
        if symbol.startswith(("4", "8")):
            return f"{symbol}.BJ"
    return symbol


def _normalize_trade_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None)
    except Exception:
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None

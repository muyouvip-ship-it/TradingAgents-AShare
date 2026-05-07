from __future__ import annotations

import concurrent.futures
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from api.core.stock_map import get_reverse_stock_map
from api.core.stock_utils import normalize_symbol, search_cn_stock_by_name
from api.database import get_db
from api.deps import require_api_user
from api.services.qmt_market_data_service import (
    build_market_integrity_report,
    fetch_daily_bars,
    fetch_intraday_bars,
    fetch_realtime_quotes,
    get_index_presets,
)
from api.services.data_source_governance import build_market_overview_governance
from api.services.market_data_pipeline_service import preferred_daily_kline_table

router = APIRouter(prefix="/v1/market", tags=["Market"])

INDEX_PRESETS = get_index_presets()
FAST_QUOTE_TIMEOUT_SECONDS = 2.5
FAST_INTRADAY_QUOTE_TIMEOUT_SECONDS = 2.0
SECTOR_FUND_FLOW_WAIT_SECONDS = 1.5
SECTOR_FUND_FLOW_TTL_SECONDS = 300
SECTOR_FUND_FLOW_STALE_SECONDS = 1800
_SECTOR_FUND_FLOW_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="market-fund-flow")
_SECTOR_FUND_FLOW_LOCK = threading.Lock()
_SECTOR_FUND_FLOW_FUTURE: concurrent.futures.Future[list[dict[str, Any]]] | None = None
_SECTOR_FUND_FLOW_STARTED_AT = 0.0
_SECTOR_FUND_FLOW_CACHE: dict[str, Any] = {"items": [], "updated_at": 0.0}


@router.get("/stock-search")
def search_stocks(
    q: str = Query("", min_length=1, max_length=20),
    db: Session = Depends(get_db),
    current_user=Depends(require_api_user),
):
    del current_user
    q = q.strip()
    if not q:
        return {"results": []}

    code_to_name = get_reverse_stock_map()
    results = []
    q_upper = q.upper()

    for code, name in code_to_name.items():
        if q in name or q_upper in code.upper() or q in code:
            results.append({"symbol": code, "name": name, "source": "cache"})

    if not results:
        found = search_cn_stock_by_name(q)
        if found:
            results.append({"symbol": found, "name": code_to_name.get(found, q), "source": "akshare"})

    quote_map = _load_quote_map([item["symbol"] for item in results[:20]])
    latest_map = _load_latest_stock_changes(db, [item["symbol"] for item in results[:20]])
    for item in results:
        quote = quote_map.get(item["symbol"]) or quote_map.get(item["symbol"].split(".", 1)[0]) or {}
        latest = latest_map.get(item["symbol"]) or {}
        price = _to_float(quote.get("price")) or latest.get("price")
        change_pct = _to_float(quote.get("change_pct")) or latest.get("change_pct")
        item.update(
            {
                "market": item["symbol"].split(".", 1)[-1] if "." in item["symbol"] else "",
                "exchange": item["symbol"].split(".", 1)[-1] if "." in item["symbol"] else "",
                "current_price": price,
                "change_pct": change_pct,
            }
        )

    return {"results": results[:20]}


@router.get("/kline")
def get_kline(symbol: str, start_date: str, end_date: str, db: Session = Depends(get_db)):
    normalized = normalize_symbol(symbol)
    code = normalized.split(".", 1)[0]
    index_codes = {item["code"] for item in INDEX_PRESETS}
    is_index = normalized in {item["symbol"] for item in INDEX_PRESETS} or code in index_codes
    rows = _load_kline_rows(db, code, start_date, end_date, prefer_index=is_index)
    if is_index and not rows:
        try:
            fetch_daily_bars(normalized, start_date=start_date, end_date=end_date)
            rows = _load_kline_rows(db, code, start_date, end_date, prefer_index=True)
        except Exception:
            rows = rows or []

    candles = []
    previous_close = None
    for row in rows:
        open_price = _to_float(row["open"])
        high = _to_float(row["high"])
        low = _to_float(row["low"])
        close = _to_float(row["close"])
        if open_price is None or high is None or low is None or close is None:
            continue
        pre_close = _to_float(row["pre_close"]) or previous_close
        change = round(close - pre_close, 4) if pre_close else None
        change_percent = round(change / pre_close * 100, 4) if change is not None and pre_close else None
        candles.append(
            {
                "date": row["trade_date"].isoformat(),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": _to_float(row["volume"]),
                "amount": _to_float(row["amount"]),
                "change": change,
                "change_percent": change_percent,
                "turnover_rate": _to_float(row["turnover_rate"]),
            }
        )
        previous_close = close

    _append_live_candle(candles, normalized, start_date, end_date)
    return {
        "symbol": normalized,
        "start_date": start_date,
        "end_date": end_date,
        "candles": candles,
        "source": "qmt_realtime+postgresql_daily" if candles else "empty",
    }


@router.get("/intraday")
def get_intraday(
    symbol: str,
    trade_date: str,
    period: str = Query("1m", pattern="^1m$"),
    include_latest_quote: bool = Query(True),
):
    normalized = normalize_symbol(symbol)
    payload = _fetch_intraday_bars_compat(
        normalized,
        trade_date=trade_date,
        period=period,
        include_latest_quote=include_latest_quote,
        account_key=None,
        persist=True,
        quote_timeout_seconds=FAST_INTRADAY_QUOTE_TIMEOUT_SECONDS,
    )
    return payload


@router.get("/quote")
def get_market_quote(symbol: str):
    normalized = normalize_symbol(symbol)
    quote = _fetch_realtime_quotes_compat([normalized], timeout_seconds=FAST_QUOTE_TIMEOUT_SECONDS).get(normalized)
    if not quote:
        raise HTTPException(status_code=404, detail=f"QMT quote unavailable for {normalized}")
    return {
        "symbol": normalized,
        "quote": quote,
        "source": "qmt_realtime",
    }


@router.get("/overview")
def get_market_overview(
    limit: int = Query(20, ge=5, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(require_api_user),
) -> Dict[str, Any]:
    del current_user
    index_symbols = [item["symbol"] for item in INDEX_PRESETS]
    quote_map = _load_quote_map(index_symbols, timeout_seconds=FAST_QUOTE_TIMEOUT_SECONDS)
    indices = []
    for item in INDEX_PRESETS:
        latest = _load_latest_index_item(db, item["code"])
        quote = quote_map.get(item["symbol"]) or quote_map.get(item["code"]) or {}
        merged = _merge_market_item(
            symbol=item["symbol"],
            name=item["name"],
            latest=latest,
            quote=quote,
            source="qmt_realtime" if quote else (latest.get("source") or "postgresql:index_daily_kline"),
        )
        indices.append(merged)

    top_gainers, top_losers = _load_stock_rankings(db, limit=limit)
    sector_gainers, sector_losers = _load_sector_rankings(db, limit=limit)
    sector_fund_inflows, sector_fund_outflows = _load_sector_fund_flow(limit=limit)
    payload = {
        "indices": indices,
        "top_gainers": top_gainers,
        "top_losers": top_losers,
        "sector_gainers": sector_gainers,
        "sector_losers": sector_losers,
        "sector_fund_inflows": sector_fund_inflows,
        "sector_fund_outflows": sector_fund_outflows,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "qmt_realtime+postgresql_fallback",
        "fallback": not bool(quote_map),
    }
    payload["data_governance"] = build_market_overview_governance(payload)
    return payload


@router.get("/integrity-report")
def get_market_integrity_report(
    target_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user=Depends(require_api_user),
):
    del current_user
    return build_market_integrity_report(db, target_date=target_date)


@router.get("/kline/chanlun")
def get_chanlun_overlay(symbol: str, start_date: str, end_date: str, db: Session = Depends(get_db)):
    normalized = normalize_symbol(symbol)
    code = normalized.split(".", 1)[0]
    index_codes = {item["code"] for item in INDEX_PRESETS}
    is_index = normalized in {item["symbol"] for item in INDEX_PRESETS} or code in index_codes
    rows = _load_kline_rows(db, code, start_date, end_date, prefer_index=is_index)
    candles = []
    previous_close = None
    for row in rows:
        open_price = _to_float(row["open"])
        high = _to_float(row["high"])
        low = _to_float(row["low"])
        close = _to_float(row["close"])
        if open_price is None or high is None or low is None or close is None:
            continue
        pre_close = _to_float(row.get("pre_close")) or previous_close
        candles.append(
            {
                "date": row["trade_date"].isoformat(),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "pre_close": pre_close,
            }
        )
        previous_close = close
    overlay = _calculate_chanlun_overlay(candles)
    overlay.update(
        {
            "symbol": normalized,
            "start_date": start_date,
            "end_date": end_date,
            "source": "postgresql_daily",
            "message": None if len(candles) >= 10 else "K线数量不足，缠论指标仅显示可确认部分。",
        }
    )
    return overlay


@router.get("/hot-stocks")
def get_hot_stocks(source: str = "em", limit: int = 30) -> Dict:
    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit must be positive")
    return {"source": source, "limit": limit, "items": [], "fallback": True}


def _load_kline_rows(db: Session, code: str, start_date: str, end_date: str, *, prefer_index: bool = False):
    table_candidates = ["index_daily_kline", "index_daily_data"] if prefer_index else [preferred_daily_kline_table(), "index_daily_kline", "index_daily_data"]
    symbol_candidates = [code]
    if not prefer_index and len(code) == 6 and code.isdigit():
        if code.startswith(("4", "8")) or code.startswith("92"):
            symbol_candidates.append(f"{code}.BJ")
        elif code.startswith(("5", "6", "9")):
            symbol_candidates.append(f"{code}.SH")
        else:
            symbol_candidates.append(f"{code}.SZ")
    if prefer_index:
        symbol_candidates = [code, f"sh{code}", f"sz{code}", f"{code}.SH", f"{code}.SZ"]
    placeholders = ", ".join(f":symbol_{index}" for index, _ in enumerate(symbol_candidates))
    params = {
        "start_date": start_date,
        "end_date": end_date,
        **{f"symbol_{index}": value for index, value in enumerate(symbol_candidates)},
    }
    for table_name in table_candidates:
        if not _has_table(db, table_name):
            continue
        pre_close_expr = "pre_close" if _has_column(db, table_name, "pre_close") else "NULL AS pre_close"
        turnover_expr = "turnover_rate" if _has_column(db, table_name, "turnover_rate") else "NULL AS turnover_rate"
        try:
            return db.execute(
                text(
                    f"""
                    SELECT trade_date, open, high, low, close, volume, amount, {turnover_expr}, {pre_close_expr}
                    FROM {table_name}
                    WHERE symbol IN ({placeholders}) AND trade_date >= :start_date AND trade_date <= :end_date
                    ORDER BY trade_date ASC
                    """
                ),
                params,
            ).mappings().all()
        except Exception:
            continue
    return []


def _has_table(db: Session, table_name: str) -> bool:
    try:
        return inspect(db.bind).has_table(table_name)
    except Exception:
        return False


def _has_column(db: Session, table_name: str, column_name: str) -> bool:
    try:
        return column_name in {column["name"] for column in inspect(db.bind).get_columns(table_name)}
    except Exception:
        return False


def _fetch_realtime_quotes_compat(symbols: list[str], *, timeout_seconds: float | None = None) -> dict[str, dict[str, Any]]:
    try:
        if timeout_seconds is None:
            parsed = fetch_realtime_quotes(symbols)
        else:
            parsed = fetch_realtime_quotes(symbols, timeout_seconds=timeout_seconds)
    except TypeError:
        parsed = fetch_realtime_quotes(symbols)
    return parsed if isinstance(parsed, dict) else {}


def _fetch_intraday_bars_compat(
    symbol: str,
    *,
    trade_date: str,
    period: str,
    include_latest_quote: bool,
    account_key: str | None,
    persist: bool,
    quote_timeout_seconds: float | None = None,
):
    kwargs = {
        "trade_date": trade_date,
        "period": period,
        "include_latest_quote": include_latest_quote,
        "account_key": account_key,
        "persist": persist,
    }
    if quote_timeout_seconds is not None:
        kwargs["quote_timeout_seconds"] = quote_timeout_seconds
    try:
        return fetch_intraday_bars(symbol, **kwargs)
    except TypeError:
        kwargs.pop("quote_timeout_seconds", None)
        return fetch_intraday_bars(symbol, **kwargs)


def _load_quote_map(symbols: list[str], *, timeout_seconds: float | None = None) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    normalized = [normalize_symbol(symbol) for symbol in symbols]
    try:
        parsed = _fetch_realtime_quotes_compat(normalized, timeout_seconds=timeout_seconds)
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for key, value in parsed.items():
        if isinstance(value, dict):
            result[str(key).upper()] = value
            result[str(key).split(".", 1)[0].upper()] = value
    return result


def _load_latest_stock_changes(db: Session, symbols: list[str]) -> dict[str, dict[str, float | None]]:
    daily_table = _preferred_market_latest_daily_table(db)
    if not symbols or not _has_table(db, daily_table):
        return {}
    codes = sorted({variant for symbol in symbols for variant in {normalize_symbol(symbol), normalize_symbol(symbol).split(".", 1)[0]} if variant})
    target_date = _load_latest_daily_trade_date(db, daily_table)
    if not target_date:
        return {}
    placeholders = ", ".join(f":symbol_{index}" for index, _ in enumerate(codes))
    params = {
        "target_date": target_date,
        **{f"symbol_{index}": value for index, value in enumerate(codes)},
    }
    try:
        rows = db.execute(
            text(
                f"""
                SELECT symbol, close, pre_close
                FROM {daily_table}
                WHERE trade_date = :target_date AND symbol IN ({placeholders})
                """
            ),
            params,
        ).mappings().all()
    except Exception:
        return {}
    code_to_name = get_reverse_stock_map()
    result = {}
    for row in rows:
        code = str(row["symbol"])
        symbol = _code_to_symbol(code)
        close = _to_float(row["close"])
        pre_close = _to_float(row["pre_close"])
        change_pct = round((close - pre_close) / pre_close * 100, 4) if close is not None and pre_close else None
        result[symbol] = {"price": close, "change_pct": change_pct, "name": code_to_name.get(symbol)}
    return result


def _load_latest_index_item(db: Session, code: str, trade_date: str | None = None) -> dict[str, Any]:
    symbol_candidates = [code, f"sh{code}", f"sz{code}", f"{code}.SH", f"{code}.SZ"]
    placeholders = ", ".join(f":symbol_{index}" for index, _ in enumerate(symbol_candidates))
    params = {f"symbol_{index}": value for index, value in enumerate(symbol_candidates)}
    date_clause = "AND trade_date <= :trade_date" if trade_date else ""
    if trade_date:
        params["trade_date"] = trade_date
    for table_name in ("index_daily_kline", "index_daily_data"):
        if not _has_table(db, table_name):
            continue
        try:
            rows = db.execute(
                text(
                    f"""
                    SELECT trade_date, open, high, low, close, volume, amount
                    FROM {table_name}
                    WHERE symbol IN ({placeholders})
                      {date_clause}
                    ORDER BY trade_date DESC
                    LIMIT 2
                    """
                ),
                params,
            ).mappings().all()
            if rows:
                latest = rows[0]
                previous = rows[1] if len(rows) > 1 else None
                close = _to_float(latest["close"])
                pre_close = _to_float(previous["close"]) if previous else None
                return {
                    "price": close,
                    "pre_close": pre_close,
                    "change": round(close - pre_close, 4) if close is not None and pre_close else None,
                    "change_pct": round((close - pre_close) / pre_close * 100, 4) if close is not None and pre_close else None,
                    "trade_date": latest["trade_date"].isoformat(),
                    "volume": _to_float(latest["volume"]),
                    "amount": _to_float(latest["amount"]),
                    "source": f"postgresql:{table_name}",
                }
        except Exception:
            continue
    return {}


def _merge_market_item(symbol: str, name: str, latest: dict[str, Any], quote: dict[str, Any], source: str) -> dict[str, Any]:
    price = _to_float(quote.get("price")) or latest.get("price")
    pre_close = _to_float(quote.get("previous_close")) or latest.get("pre_close")
    change = _to_float(quote.get("change")) or latest.get("change")
    change_pct = _to_float(quote.get("change_pct")) or latest.get("change_pct")
    if change is None and price is not None and pre_close:
        change = round(price - pre_close, 4)
    if change_pct is None and change is not None and pre_close:
        change_pct = round(change / pre_close * 100, 4)
    return {
        "symbol": symbol,
        "name": name,
        "price": price,
        "change": change,
        "change_pct": change_pct,
        "volume": _to_float(quote.get("volume")) or latest.get("volume"),
        "amount": _to_float(quote.get("amount")) or latest.get("amount"),
        "trade_time": quote.get("quote_time") or latest.get("trade_date"),
        "source": source,
    }


def _load_stock_rankings(db: Session, *, limit: int, trade_date: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    daily_table = _preferred_market_latest_daily_table(db)
    if not _has_table(db, daily_table):
        return [], []
    code_to_name = get_reverse_stock_map()
    target_date = _load_latest_daily_trade_date(db, daily_table, trade_date=trade_date)
    if not target_date:
        return [], []
    params = {"target_date": target_date, "limit": int(limit)}
    try:
        gainer_rows = _query_stock_ranking_rows(db, daily_table, params, direction="DESC")
        loser_rows = _query_stock_ranking_rows(db, daily_table, params, direction="ASC")
    except Exception:
        return [], []
    def build_items(rows: list[Any]) -> list[dict[str, Any]]:
        items = []
        for row in rows:
            code = str(row["symbol"])
            symbol = _code_to_symbol(code)
            close = _to_float(row["close"])
            pre_close = _to_float(row["pre_close"])
            if close is None or not pre_close:
                continue
            change = round(close - pre_close, 4)
            change_pct = round(change / pre_close * 100, 4)
            items.append(
                {
                    "symbol": symbol,
                    "name": code_to_name.get(symbol, code),
                    "price": close,
                    "change": change,
                    "change_pct": change_pct,
                    "volume": _to_float(row["volume"]),
                    "amount": _to_float(row["amount"]),
                    "trade_time": row["trade_date"].isoformat(),
                    "source": f"postgresql:{daily_table}",
                }
            )
        return items

    return build_items(gainer_rows), build_items(loser_rows)


def _query_stock_ranking_rows(db: Session, daily_table: str, params: dict[str, Any], *, direction: str):
    order_direction = "ASC" if direction.upper() == "ASC" else "DESC"
    return db.execute(
        text(
            f"""
            SELECT symbol, close, pre_close, volume, amount, trade_date
            FROM {daily_table}
            WHERE trade_date = :target_date
              AND close IS NOT NULL AND pre_close IS NOT NULL AND pre_close > 0
            ORDER BY ((close - pre_close) / NULLIF(pre_close, 0) * 100) {order_direction}
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()


def _preferred_market_latest_daily_table(db: Session) -> str:
    """Pick a fast physical table for latest-day market rankings.

    The incremental compatibility view is useful for historical reads, but it can
    force expensive anti-join scans over the legacy 10M+ row table when the market
    page only needs the latest trading day.
    """
    for table_name in ("pub_stock_daily_kline", "stock_daily_kline"):
        if not _has_table(db, table_name):
            continue
        if _load_latest_daily_trade_date(db, table_name):
            return table_name
    return preferred_daily_kline_table()


def _load_latest_daily_trade_date(db: Session, table_name: str, *, trade_date: str | None = None):
    if not _has_table(db, table_name):
        return None
    date_clause = "WHERE trade_date <= :trade_date" if trade_date else ""
    params = {"trade_date": trade_date} if trade_date else {}
    try:
        return db.execute(
            text(
                f"""
                SELECT trade_date
                FROM {table_name}
                {date_clause}
                ORDER BY trade_date DESC
                LIMIT 1
                """
            ),
            params,
        ).scalar()
    except Exception:
        return None


def _load_sector_rankings(db: Session, *, limit: int, trade_date: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    daily_table = _preferred_market_latest_daily_table(db)
    if not _has_table(db, daily_table) or not _has_column(db, daily_table, "sw_industry_l1"):
        return [], []
    target_date = _load_latest_daily_trade_date(db, daily_table, trade_date=trade_date)
    if not target_date:
        return [], []
    params = {"target_date": target_date, "limit": int(limit)}
    try:
        gainers = _query_sector_ranking_rows(db, daily_table, params, direction="DESC")
        losers = _query_sector_ranking_rows(db, daily_table, params, direction="ASC")
    except Exception:
        return [], []
    return gainers, losers


def _query_sector_ranking_rows(db: Session, daily_table: str, params: dict[str, Any], *, direction: str) -> list[dict[str, Any]]:
    order_direction = "ASC" if direction.upper() == "ASC" else "DESC"
    rows = db.execute(
        text(
            f"""
            SELECT sw_industry_l1 AS sector_name,
                   AVG((close - pre_close) / NULLIF(pre_close, 0) * 100) AS change_pct,
                   COUNT(*) AS member_count,
                   SUM(amount) AS amount
            FROM {daily_table}
            WHERE trade_date = :target_date
              AND sw_industry_l1 IS NOT NULL AND sw_industry_l1 <> ''
              AND close IS NOT NULL AND pre_close IS NOT NULL AND pre_close > 0
            GROUP BY sw_industry_l1
            HAVING COUNT(*) >= 2
            ORDER BY AVG((close - pre_close) / NULLIF(pre_close, 0) * 100) {order_direction}
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    return [
        {
            "sector_name": str(row["sector_name"]),
            "change_pct": _to_float(row["change_pct"]),
            "member_count": int(row["member_count"] or 0),
            "amount": _to_float(row["amount"]),
            "source": f"industry_aggregate:{daily_table}",
        }
        for row in rows
        if row["sector_name"] is not None
    ]


def _load_sector_fund_flow(*, limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = _load_sector_fund_flow_rows_fast()
    if not rows:
        return [], []
    inflows = sorted(rows, key=lambda item: item.get("net_inflow") or 0, reverse=True)[:limit]
    outflows = sorted(rows, key=lambda item: item.get("net_inflow") or 0)[:limit]
    return inflows, outflows


def _load_sector_fund_flow_rows_fast() -> list[dict[str, Any]]:
    cached_rows = _get_sector_fund_flow_cache(max_age_seconds=SECTOR_FUND_FLOW_TTL_SECONDS)
    if cached_rows:
        return cached_rows

    future, started_at = _ensure_sector_fund_flow_future()
    if future.done():
        return _finish_sector_fund_flow_future(future)
    if time.monotonic() - started_at > SECTOR_FUND_FLOW_WAIT_SECONDS:
        return _get_sector_fund_flow_cache(max_age_seconds=SECTOR_FUND_FLOW_STALE_SECONDS)
    try:
        rows = future.result(timeout=SECTOR_FUND_FLOW_WAIT_SECONDS)
        return _finish_sector_fund_flow_future(future, rows=rows)
    except concurrent.futures.TimeoutError:
        return _get_sector_fund_flow_cache(max_age_seconds=SECTOR_FUND_FLOW_STALE_SECONDS)
    except Exception:
        return _finish_sector_fund_flow_future(future)


def _ensure_sector_fund_flow_future() -> tuple[concurrent.futures.Future[list[dict[str, Any]]], float]:
    global _SECTOR_FUND_FLOW_FUTURE, _SECTOR_FUND_FLOW_STARTED_AT
    with _SECTOR_FUND_FLOW_LOCK:
        if _SECTOR_FUND_FLOW_FUTURE is None:
            _SECTOR_FUND_FLOW_FUTURE = _SECTOR_FUND_FLOW_EXECUTOR.submit(_fetch_sector_fund_flow_rows)
            _SECTOR_FUND_FLOW_STARTED_AT = time.monotonic()
        return _SECTOR_FUND_FLOW_FUTURE, _SECTOR_FUND_FLOW_STARTED_AT


def _get_sector_fund_flow_cache(*, max_age_seconds: int) -> list[dict[str, Any]]:
    with _SECTOR_FUND_FLOW_LOCK:
        updated_at = float(_SECTOR_FUND_FLOW_CACHE.get("updated_at") or 0)
        if not updated_at or time.monotonic() - updated_at > max_age_seconds:
            return []
        rows = _SECTOR_FUND_FLOW_CACHE.get("items") or []
        return [dict(item) for item in rows if isinstance(item, dict)]


def _finish_sector_fund_flow_future(
    future: concurrent.futures.Future[list[dict[str, Any]]],
    *,
    rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    global _SECTOR_FUND_FLOW_FUTURE
    if rows is None:
        try:
            rows = future.result()
        except Exception:
            rows = []
    with _SECTOR_FUND_FLOW_LOCK:
        if _SECTOR_FUND_FLOW_FUTURE is future:
            _SECTOR_FUND_FLOW_FUTURE = None
        if rows:
            _SECTOR_FUND_FLOW_CACHE["items"] = [dict(item) for item in rows]
            _SECTOR_FUND_FLOW_CACHE["updated_at"] = time.monotonic()
            return [dict(item) for item in rows]
    return _get_sector_fund_flow_cache(max_age_seconds=SECTOR_FUND_FLOW_STALE_SECONDS)


def _fetch_sector_fund_flow_rows() -> list[dict[str, Any]]:
    try:
        import akshare as ak
    except Exception:
        return []

    for loader in (_fetch_sector_fund_flow_rows_em, _fetch_sector_fund_flow_rows_ths):
        try:
            rows = loader(ak)
            if rows:
                return rows
        except Exception:
            continue
    return []


def _fetch_sector_fund_flow_rows_em(ak: Any) -> list[dict[str, Any]]:
    if hasattr(ak, "stock_sector_fund_flow_rank"):
        frame = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
        source = "akshare:stock_sector_fund_flow_rank"
    elif hasattr(ak, "stock_board_industry_fund_flow_em"):
        frame = ak.stock_board_industry_fund_flow_em(symbol="今日")
        source = "akshare:stock_board_industry_fund_flow_em"
    else:
        return []
    if frame is None or frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        sector_name = str(row.get("名称") or row.get("行业") or "").strip()
        if not sector_name:
            continue
        net_inflow = _to_float(
            row.get("今日主力净流入-净额")
            or row.get("主力净流入-净额")
            or row.get("今日主力净流入")
            or row.get("主力净流入")
        )
        change_pct = _to_float(row.get("今日涨跌幅") or row.get("涨跌幅"))
        rows.append(
            {
                "sector_name": sector_name,
                "change_pct": change_pct,
                "net_inflow": net_inflow,
                "source": source,
            }
        )
    return rows


def _fetch_sector_fund_flow_rows_ths(ak: Any) -> list[dict[str, Any]]:
    if not hasattr(ak, "stock_fund_flow_industry"):
        return []
    frame = ak.stock_fund_flow_industry(symbol="即时")
    if frame is None or frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        sector_name = str(row.get("行业") or row.get("名称") or "").strip()
        if not sector_name:
            continue
        net_inflow = _to_float(row.get("净额"))
        # 同花顺该接口以“亿元”为展示单位，统一转为元，便于前端按亿/万格式化。
        if net_inflow is not None and abs(net_inflow) < 1_000_000:
            net_inflow *= 100_000_000
        rows.append(
            {
                "sector_name": sector_name,
                "change_pct": _to_float(row.get("行业-涨跌幅") or row.get("涨跌幅")),
                "net_inflow": net_inflow,
                "member_count": int(row.get("公司家数") or 0),
                "source": "akshare:stock_fund_flow_industry",
            }
        )
    return rows


def _code_to_symbol(code: str) -> str:
    raw = str(code or "").strip().upper()
    if "." in raw:
        base, suffix = raw.split(".", 1)
        if base.isdigit() and suffix in {"SH", "SZ", "SS", "BJ"}:
            return f"{base}.{'SH' if suffix == 'SS' else suffix}"
    code = raw.split(".", 1)[0]
    if code.startswith(("4", "8")) or code.startswith("92"):
        return f"{code}.BJ"
    if code.startswith(("5", "6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


def _calculate_chanlun_overlay(candles: list[dict[str, Any]]) -> dict[str, Any]:
    if len(candles) < 3:
        return {"fractals": [], "bi": [], "segments": [], "zhongshu": [], "buy_sell_points": []}

    fractals: list[dict[str, Any]] = []
    for index in range(1, len(candles) - 1):
        prev_item = candles[index - 1]
        item = candles[index]
        next_item = candles[index + 1]
        if item["high"] > prev_item["high"] and item["high"] > next_item["high"]:
            fractals.append({"date": item["date"], "type": "top", "price": item["high"], "index": index})
        if item["low"] < prev_item["low"] and item["low"] < next_item["low"]:
            fractals.append({"date": item["date"], "type": "bottom", "price": item["low"], "index": index})

    normalized_fractals: list[dict[str, Any]] = []
    for fractal in sorted(fractals, key=lambda item: item["index"]):
        if not normalized_fractals:
            normalized_fractals.append(fractal)
            continue
        last = normalized_fractals[-1]
        if fractal["type"] == last["type"]:
            if (fractal["type"] == "top" and fractal["price"] >= last["price"]) or (
                fractal["type"] == "bottom" and fractal["price"] <= last["price"]
            ):
                normalized_fractals[-1] = fractal
            continue
        if fractal["index"] - last["index"] < 3:
            continue
        normalized_fractals.append(fractal)

    strokes: list[dict[str, Any]] = []
    for start, end in zip(normalized_fractals, normalized_fractals[1:]):
        direction = "up" if start["type"] == "bottom" and end["type"] == "top" else "down"
        strokes.append(
            {
                "start_date": start["date"],
                "end_date": end["date"],
                "start_price": start["price"],
                "end_price": end["price"],
                "direction": direction,
            }
        )

    segments: list[dict[str, Any]] = []
    for offset in range(0, max(len(strokes) - 2, 0), 2):
        part = strokes[offset : offset + 3]
        if len(part) < 3:
            continue
        segments.append(
            {
                "start_date": part[0]["start_date"],
                "end_date": part[-1]["end_date"],
                "start_price": part[0]["start_price"],
                "end_price": part[-1]["end_price"],
                "direction": part[-1]["direction"],
            }
        )

    zhongshu: list[dict[str, Any]] = []
    for offset in range(0, max(len(strokes) - 2, 0)):
        part = strokes[offset : offset + 3]
        ranges = [(min(item["start_price"], item["end_price"]), max(item["start_price"], item["end_price"])) for item in part]
        low = max(item[0] for item in ranges)
        high = min(item[1] for item in ranges)
        if low <= high:
            zhongshu.append(
                {
                    "start_date": part[0]["start_date"],
                    "end_date": part[-1]["end_date"],
                    "low": round(low, 4),
                    "high": round(high, 4),
                    "mid": round((low + high) / 2, 4),
                }
            )

    buy_sell_points = _derive_chanlun_points(normalized_fractals, zhongshu)
    return {
        "fractals": normalized_fractals,
        "bi": strokes,
        "segments": segments,
        "zhongshu": zhongshu,
        "buy_sell_points": buy_sell_points,
    }


def _derive_chanlun_points(fractals: list[dict[str, Any]], zhongshu: list[dict[str, Any]]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    latest_zone = zhongshu[-1] if zhongshu else None
    previous_bottom = None
    previous_top = None
    for fractal in fractals:
        if fractal["type"] == "bottom":
            point_type = "1_buy"
            reason = "底分型确认，疑似一类买点"
            if previous_bottom and fractal["price"] > previous_bottom["price"]:
                point_type = "2_buy"
                reason = "回调底高于前低，疑似二类买点"
            if latest_zone and fractal["price"] > latest_zone["high"]:
                point_type = "3_buy"
                reason = "中枢上方回踩不破，疑似三类买点"
            previous_bottom = fractal
            points.append({"date": fractal["date"], "price": fractal["price"], "type": point_type, "side": "buy", "reason": reason})
        else:
            point_type = "1_sell"
            reason = "顶分型确认，疑似一类卖点"
            if previous_top and fractal["price"] < previous_top["price"]:
                point_type = "2_sell"
                reason = "反弹顶低于前高，疑似二类卖点"
            if latest_zone and fractal["price"] < latest_zone["low"]:
                point_type = "3_sell"
                reason = "中枢下方反抽不回，疑似三类卖点"
            previous_top = fractal
            points.append({"date": fractal["date"], "price": fractal["price"], "type": point_type, "side": "sell", "reason": reason})
    return points


def _append_live_candle(candles: list[dict], symbol: str, start_date: str, end_date: str) -> None:
    quote = _fetch_realtime_quotes_compat([symbol], timeout_seconds=FAST_QUOTE_TIMEOUT_SECONDS).get(symbol) or {}
    quote_time = str(quote.get("quote_time") or "")
    quote_date = quote_time[:10]
    if not quote_date or quote_date < start_date or quote_date > end_date:
        return
    if candles and candles[-1].get("date") == quote_date:
        return

    price = _to_float(quote.get("price"))
    open_price = _to_float(quote.get("open")) or price
    high = _to_float(quote.get("high")) or price
    low = _to_float(quote.get("low")) or price
    previous_close = _to_float(quote.get("previous_close"))
    if price is None or open_price is None or high is None or low is None:
        return
    change = _to_float(quote.get("change"))
    change_percent = _to_float(quote.get("change_pct"))
    if change is None and previous_close:
        change = round(price - previous_close, 4)
    if change_percent is None and change is not None and previous_close:
        change_percent = round(change / previous_close * 100, 4)
    candles.append(
        {
            "date": quote_date,
            "open": open_price,
            "high": high,
            "low": low,
            "close": price,
            "volume": _to_float(quote.get("volume")),
            "amount": _to_float(quote.get("amount")),
            "change": change,
            "change_percent": change_percent,
            "turnover_rate": None,
        }
    )


def _to_float(value):
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except Exception:
        return None

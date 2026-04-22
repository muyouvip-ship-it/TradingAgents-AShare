from __future__ import annotations

import json
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.core.http_utils import get_real_ip
from api.core.stock_map import get_reverse_stock_map
from api.core.stock_utils import normalize_symbol, search_cn_stock_by_name
from api.database import get_db
from api.deps import require_api_user
from tradingagents.dataflows.interface import route_to_vendor

router = APIRouter(prefix="/v1/market", tags=["Market"])


@router.get("/stock-search")
def search_stocks(
    q: str = Query("", min_length=1, max_length=20),
    current_user=Depends(require_api_user),
):
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

    return {"results": results[:20]}


@router.get("/kline")
def get_kline(symbol: str, start_date: str, end_date: str, db: Session = Depends(get_db)):
    normalized = normalize_symbol(symbol)
    code = normalized.split(".", 1)[0]
    rows = db.execute(
        text(
            """
            SELECT trade_date, open, high, low, close, volume, amount, turnover_rate, pre_close
            FROM stock_daily_kline
            WHERE symbol = :code AND trade_date >= :start_date AND trade_date <= :end_date
            ORDER BY trade_date ASC
            """
        ),
        {"code": code, "start_date": start_date, "end_date": end_date},
    ).mappings().all()

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
        "source_ip": None,
    }


@router.get("/hot-stocks")
def get_hot_stocks(source: str = "em", limit: int = 30) -> Dict:
    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit must be positive")
    return {"source": source, "limit": limit, "items": [], "fallback": True}


def _append_live_candle(candles: list[dict], symbol: str, start_date: str, end_date: str) -> None:
    try:
        quote_payload = json.loads(route_to_vendor("get_realtime_quotes", [symbol]))
    except Exception:
        return
    quote = quote_payload.get(symbol) or {}
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

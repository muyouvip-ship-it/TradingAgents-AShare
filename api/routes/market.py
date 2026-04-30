from __future__ import annotations

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

router = APIRouter(prefix="/v1/market", tags=["Market"])

INDEX_PRESETS = get_index_presets()


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
    payload = fetch_intraday_bars(
        normalized,
        trade_date=trade_date,
        period=period,
        include_latest_quote=include_latest_quote,
        account_key=None,
        persist=True,
    )
    return payload


@router.get("/quote")
def get_market_quote(symbol: str):
    normalized = normalize_symbol(symbol)
    quote = fetch_realtime_quotes([normalized]).get(normalized)
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
    quote_map = _load_quote_map(index_symbols)
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
    return {
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
    table_candidates = ["index_daily_kline", "index_daily_data"] if prefer_index else ["stock_daily_kline", "index_daily_kline", "index_daily_data"]
    symbol_candidates = [code]
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


def _load_quote_map(symbols: list[str]) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    normalized = [normalize_symbol(symbol) for symbol in symbols]
    try:
        parsed = fetch_realtime_quotes(normalized)
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
    if not symbols or not _has_table(db, "stock_daily_kline"):
        return {}
    codes = [normalize_symbol(symbol).split(".", 1)[0] for symbol in symbols]
    try:
        rows = db.execute(
            text(
                """
                WITH latest AS (
                    SELECT MAX(trade_date) AS trade_date FROM stock_daily_kline
                )
                SELECT symbol, close, pre_close
                FROM stock_daily_kline
                WHERE trade_date = (SELECT trade_date FROM latest) AND symbol = ANY(:symbols)
                """
            ),
            {"symbols": codes},
        ).mappings().all()
    except Exception:
        try:
            rows = db.execute(
                text(
                    """
                    SELECT symbol, close, pre_close
                    FROM stock_daily_kline
                    WHERE trade_date = (SELECT MAX(trade_date) FROM stock_daily_kline)
                    """
                )
            ).mappings().all()
            rows = [row for row in rows if row["symbol"] in codes]
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


def _load_latest_index_item(db: Session, code: str) -> dict[str, Any]:
    symbol_candidates = [code, f"sh{code}", f"sz{code}", f"{code}.SH", f"{code}.SZ"]
    placeholders = ", ".join(f":symbol_{index}" for index, _ in enumerate(symbol_candidates))
    params = {f"symbol_{index}": value for index, value in enumerate(symbol_candidates)}
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


def _load_stock_rankings(db: Session, *, limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not _has_table(db, "stock_daily_kline"):
        return [], []
    code_to_name = get_reverse_stock_map()
    try:
        rows = db.execute(
            text(
                """
                SELECT symbol, close, pre_close, volume, amount, trade_date
                FROM stock_daily_kline
                WHERE trade_date = (SELECT MAX(trade_date) FROM stock_daily_kline)
                  AND close IS NOT NULL AND pre_close IS NOT NULL AND pre_close > 0
                """
            )
        ).mappings().all()
    except Exception:
        return [], []
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
                "source": "postgresql:stock_daily_kline",
            }
        )
    gainers = sorted(items, key=lambda item: item.get("change_pct") or 0, reverse=True)[:limit]
    losers = sorted(items, key=lambda item: item.get("change_pct") or 0)[:limit]
    return gainers, losers


def _load_sector_rankings(db: Session, *, limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not _has_table(db, "stock_daily_kline") or not _has_column(db, "stock_daily_kline", "sw_industry_l1"):
        return [], []
    try:
        rows = db.execute(
            text(
                """
                SELECT sw_industry_l1 AS sector_name,
                       AVG((close - pre_close) / NULLIF(pre_close, 0) * 100) AS change_pct,
                       COUNT(*) AS member_count,
                       SUM(amount) AS amount
                FROM stock_daily_kline
                WHERE trade_date = (SELECT MAX(trade_date) FROM stock_daily_kline)
                  AND sw_industry_l1 IS NOT NULL AND sw_industry_l1 <> ''
                  AND close IS NOT NULL AND pre_close IS NOT NULL AND pre_close > 0
                GROUP BY sw_industry_l1
                HAVING COUNT(*) >= 2
                """
            )
        ).mappings().all()
    except Exception:
        return [], []
    items = [
        {
            "sector_name": str(row["sector_name"]),
            "change_pct": _to_float(row["change_pct"]),
            "member_count": int(row["member_count"] or 0),
            "amount": _to_float(row["amount"]),
            "source": "industry_aggregate:stock_daily_kline",
        }
        for row in rows
        if row["sector_name"] is not None
    ]
    gainers = sorted(items, key=lambda item: item.get("change_pct") or 0, reverse=True)[:limit]
    losers = sorted(items, key=lambda item: item.get("change_pct") or 0)[:limit]
    return gainers, losers


def _load_sector_fund_flow(*, limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        import akshare as ak

        frame = ak.stock_board_industry_fund_flow_em(symbol="今日")
        if frame is None or frame.empty:
            return [], []
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
                    "source": "akshare:stock_board_industry_fund_flow_em",
                }
            )
        inflows = sorted(rows, key=lambda item: item.get("net_inflow") or 0, reverse=True)[:limit]
        outflows = sorted(rows, key=lambda item: item.get("net_inflow") or 0)[:limit]
        return inflows, outflows
    except Exception:
        return [], []


def _code_to_symbol(code: str) -> str:
    code = str(code).upper().split(".", 1)[0]
    if code.startswith(("5", "6", "9")):
        return f"{code}.SH"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
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
    quote = fetch_realtime_quotes([symbol]).get(symbol) or {}
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

#!/usr/bin/env python3
"""Sync audited pub_* K-line rows into the final business stock_* tables.

The script is dry-run by default. Add --apply to write rows.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import bindparam, text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.database import engine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-type", choices=["daily", "minute", "all"], default="all")
    parser.add_argument("--start-date", type=_parse_date, help="Inclusive trade date, YYYY-MM-DD.")
    parser.add_argument("--end-date", type=_parse_date, help="Inclusive trade date, YYYY-MM-DD.")
    parser.add_argument("--symbol", action="append", default=[], help="Limit to one symbol. Can be repeated.")
    parser.add_argument("--apply", action="store_true", help="Actually upsert into stock_* final tables.")
    return parser.parse_args()


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _symbol_variants(values: list[str]) -> list[str]:
    variants: set[str] = set()
    for raw in values:
        symbol = str(raw or "").strip().upper()
        if not symbol:
            continue
        variants.add(symbol)
        bare = symbol.split(".", 1)[0]
        variants.add(bare)
        if "." not in symbol and len(bare) == 6 and bare.isdigit():
            if bare.startswith(("4", "8")) or bare.startswith("92"):
                variants.add(f"{bare}.BJ")
            elif bare.startswith(("5", "6", "9")):
                variants.add(f"{bare}.SH")
            else:
                variants.add(f"{bare}.SZ")
    return sorted(variants)


def _date_filters(
    *,
    column: str,
    start_date: date | None,
    end_date: date | None,
    params: dict[str, Any],
) -> list[str]:
    filters: list[str] = []
    if start_date is not None:
        filters.append(f"{column} >= :start_date")
        params["start_date"] = start_date
    if end_date is not None:
        filters.append(f"{column} <= :end_date")
        params["end_date"] = end_date
    return filters


def sync_daily(*, start_date: date | None, end_date: date | None, symbols: list[str], apply: bool) -> dict[str, Any]:
    params: dict[str, Any] = {}
    filters = _date_filters(column="trade_date", start_date=start_date, end_date=end_date, params=params)
    if symbols:
        params["symbols"] = symbols
        filters.append("symbol IN :symbols")
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    count_sql = text(f"SELECT COUNT(*) FROM pub_stock_daily_kline {where_clause}")
    if symbols:
        count_sql = count_sql.bindparams(bindparam("symbols", expanding=True))
    with engine.begin() as conn:
        count = int(conn.execute(count_sql, params).scalar() or 0)
        if not apply or count == 0:
            return {"table": "stock_daily_kline", "source": "pub_stock_daily_kline", "matched": count, "written": 0}
        insert_sql = text(
            f"""
            INSERT INTO stock_daily_kline
            (symbol, trade_date, open, high, low, close, volume, amount, turnover_rate, pre_close,
             float_market_cap, total_market_cap, net_profit_ttm, sw_industry_l1, sw_industry_l2, sw_industry_l3,
             created_at, updated_at)
            SELECT symbol, trade_date, open, high, low, close, volume, amount, turnover_rate, pre_close,
                   float_market_cap, total_market_cap, net_profit_ttm, sw_industry_l1, sw_industry_l2, sw_industry_l3,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM pub_stock_daily_kline
            {where_clause}
            ON CONFLICT (symbol, trade_date) DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                amount = EXCLUDED.amount,
                turnover_rate = EXCLUDED.turnover_rate,
                pre_close = EXCLUDED.pre_close,
                float_market_cap = EXCLUDED.float_market_cap,
                total_market_cap = EXCLUDED.total_market_cap,
                net_profit_ttm = EXCLUDED.net_profit_ttm,
                sw_industry_l1 = EXCLUDED.sw_industry_l1,
                sw_industry_l2 = EXCLUDED.sw_industry_l2,
                sw_industry_l3 = EXCLUDED.sw_industry_l3,
                updated_at = CURRENT_TIMESTAMP
            """
        )
        if symbols:
            insert_sql = insert_sql.bindparams(bindparam("symbols", expanding=True))
        conn.execute(insert_sql, params)
    return {"table": "stock_daily_kline", "source": "pub_stock_daily_kline", "matched": count, "written": count}


def sync_minute(*, start_date: date | None, end_date: date | None, symbols: list[str], apply: bool) -> dict[str, Any]:
    params: dict[str, Any] = {}
    filters: list[str] = []
    if start_date is not None:
        params["start_dt"] = datetime.combine(start_date, time.min)
        filters.append("trade_time >= :start_dt")
    if end_date is not None:
        params["end_dt"] = datetime.combine(end_date + timedelta(days=1), time.min)
        filters.append("trade_time < :end_dt")
    if symbols:
        params["symbols"] = symbols
        filters.append("symbol IN :symbols")
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    count_sql = text(f"SELECT COUNT(*) FROM pub_stock_minute_kline {where_clause}")
    if symbols:
        count_sql = count_sql.bindparams(bindparam("symbols", expanding=True))
    with engine.begin() as conn:
        count = int(conn.execute(count_sql, params).scalar() or 0)
        if not apply or count == 0:
            return {"table": "stock_minute_kline", "source": "pub_stock_minute_kline", "matched": count, "written": 0}
        insert_sql = text(
            f"""
            INSERT INTO stock_minute_kline
            (symbol, trade_time, open, high, low, close, volume, amount, created_at, updated_at)
            SELECT symbol, trade_time, open, high, low, close, volume, amount, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM pub_stock_minute_kline
            {where_clause}
            ON CONFLICT (symbol, trade_time) DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                amount = EXCLUDED.amount,
                updated_at = CURRENT_TIMESTAMP
            """
        )
        if symbols:
            insert_sql = insert_sql.bindparams(bindparam("symbols", expanding=True))
        conn.execute(insert_sql, params)
    return {"table": "stock_minute_kline", "source": "pub_stock_minute_kline", "matched": count, "written": count}


def main() -> int:
    args = parse_args()
    symbols = _symbol_variants(args.symbol)
    results: list[dict[str, Any]] = []
    if args.data_type in {"daily", "all"}:
        results.append(sync_daily(start_date=args.start_date, end_date=args.end_date, symbols=symbols, apply=args.apply))
    if args.data_type in {"minute", "all"}:
        results.append(sync_minute(start_date=args.start_date, end_date=args.end_date, symbols=symbols, apply=args.apply))

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] published -> final sync")
    for result in results:
        print(
            f"- {result['source']} -> {result['table']}: matched={result['matched']} written={result['written']}"
        )
    if not args.apply:
        print("Add --apply to write these rows into the final business tables.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

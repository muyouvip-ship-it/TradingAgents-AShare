#!/usr/bin/env python3
"""Fast maintenance normalization for stock_minute_kline symbols.

This script is meant for maintenance windows after dropping symbol-dependent
indexes/constraints on stock_minute_kline. It discovers remaining legacy symbols
with one grouped scan, then updates one source symbol per transaction.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.database import engine


@dataclass(frozen=True)
class LegacySymbol:
    source_symbol: str
    target_symbol: str
    rows: int


def normalize_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol:
        return ""
    if symbol.startswith("BJ") and symbol[2:].isdigit():
        return f"{symbol[2:]}.BJ"
    if "." in symbol:
        return symbol
    if len(symbol) == 6 and symbol.isdigit():
        if symbol.startswith(("4", "8")) or symbol.startswith("92"):
            return f"{symbol}.BJ"
        if symbol.startswith(("5", "6", "9")):
            return f"{symbol}.SH"
        return f"{symbol}.SZ"
    return symbol


def free_gib(path: str) -> float:
    return shutil.disk_usage(path).free / (1024**3)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write updates. Default is dry-run.")
    parser.add_argument("--max-symbols", type=int, default=0, help="Limit discovered legacy symbols.")
    parser.add_argument("--start-symbol", help="Process source symbols >= this value.")
    parser.add_argument("--stop-symbol", help="Process source symbols <= this value.")
    parser.add_argument("--vacuum-after-updates", type=int, default=20_000_000)
    parser.add_argument("--min-free-gb", type=float, default=35)
    parser.add_argument("--disk-path", default="/System/Volumes/Data")
    return parser.parse_args()


def discover_symbols(*, start_symbol: str | None, stop_symbol: str | None, max_symbols: int) -> list[LegacySymbol]:
    filters = ["(symbol ~ '^[0-9]{6}$' OR lower(symbol) LIKE 'bj%')"]
    params: dict[str, Any] = {}
    if start_symbol:
        filters.append("upper(symbol) >= :start_symbol")
        params["start_symbol"] = start_symbol.strip().upper()
    if stop_symbol:
        filters.append("upper(symbol) <= :stop_symbol")
        params["stop_symbol"] = stop_symbol.strip().upper()
    limit_clause = "LIMIT :limit" if max_symbols > 0 else ""
    if max_symbols > 0:
        params["limit"] = max_symbols
    statement = text(
        f"""
        SELECT symbol, COUNT(*)::bigint AS rows
        FROM stock_minute_kline
        WHERE {' AND '.join(filters)}
        GROUP BY symbol
        ORDER BY symbol
        {limit_clause}
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(statement, params).mappings().all()
    return [
        LegacySymbol(str(row["symbol"]), normalize_symbol(row["symbol"]), int(row["rows"]))
        for row in rows
        if normalize_symbol(row["symbol"]) != str(row["symbol"])
    ]


def vacuum_table() -> None:
    conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        print("vacuum stock_minute_kline start", flush=True)
        conn.execute(text("VACUUM ANALYZE stock_minute_kline"))
        print("vacuum stock_minute_kline done", flush=True)
    finally:
        conn.close()


def apply_symbol(item: LegacySymbol) -> dict[str, int]:
    with engine.begin() as conn:
        deleted = int(
            conn.execute(
                text(
                    """
                    DELETE FROM stock_minute_kline source
                    WHERE source.symbol = :source_symbol
                      AND EXISTS (
                          SELECT 1
                          FROM stock_minute_kline target
                          WHERE target.symbol = :target_symbol
                            AND target.trade_time = source.trade_time
                      )
                    """
                ),
                {"source_symbol": item.source_symbol, "target_symbol": item.target_symbol},
            ).rowcount
            or 0
        )
        updated = int(
            conn.execute(
                text(
                    """
                    UPDATE stock_minute_kline
                    SET symbol = :target_symbol,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE symbol = :source_symbol
                    """
                ),
                {"source_symbol": item.source_symbol, "target_symbol": item.target_symbol},
            ).rowcount
            or 0
        )
    return {"updated": updated, "deleted_conflicts": deleted}


def main() -> int:
    args = parse_args()
    symbols = discover_symbols(
        start_symbol=args.start_symbol,
        stop_symbol=args.stop_symbol,
        max_symbols=args.max_symbols,
    )
    total_rows = sum(item.rows for item in symbols)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] fast stock_minute_kline symbol maintenance")
    print(f"symbols={len(symbols)} matched_rows={total_rows}")
    for item in symbols[:30]:
        print(f"- {item.source_symbol} -> {item.target_symbol}: rows={item.rows}")
    if len(symbols) > 30:
        print(f"... {len(symbols) - 30} more symbols omitted")
    if not args.apply:
        print("Add --apply to update rows.")
        return 0

    totals = {"updated": 0, "deleted_conflicts": 0}
    changed_since_vacuum = 0
    for index, item in enumerate(symbols, start=1):
        free = free_gib(args.disk_path)
        print(f"disk free at {args.disk_path}: {free:.1f} GiB", flush=True)
        if args.min_free_gb > 0 and free < args.min_free_gb:
            raise RuntimeError(f"free disk space {free:.1f} GiB below required {args.min_free_gb:.1f} GiB")
        result = apply_symbol(item)
        totals["updated"] += result["updated"]
        totals["deleted_conflicts"] += result["deleted_conflicts"]
        changed = result["updated"] + result["deleted_conflicts"]
        changed_since_vacuum += changed
        print(
            f"applied {index}/{len(symbols)} {item.source_symbol}->{item.target_symbol}: "
            f"updated={result['updated']} deleted_conflicts={result['deleted_conflicts']}",
            flush=True,
        )
        if args.vacuum_after_updates > 0 and changed_since_vacuum >= args.vacuum_after_updates:
            vacuum_table()
            changed_since_vacuum = 0

    print(f"done: updated={totals['updated']} deleted_conflicts={totals['deleted_conflicts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

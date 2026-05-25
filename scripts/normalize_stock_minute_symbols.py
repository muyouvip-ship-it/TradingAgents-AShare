#!/usr/bin/env python3
"""Normalize final K-line table symbols into the suffixed A-share format.

Dry-run is the default. Add --apply to update rows. The script works symbol by
symbol so large K-line tables are not rewritten in one transaction.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import bindparam, text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.database import engine


@dataclass(frozen=True)
class SymbolPlan:
    table_name: str
    source_symbol: str
    target_symbol: str
    estimated_rows: int
    conflict_rows: int
    safe_update_rows: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-type", choices=["daily", "minute", "all"], default="all")
    parser.add_argument("--symbol", action="append", default=[], help="Limit to a source symbol. Can be repeated.")
    parser.add_argument("--start-symbol", help="Process discovered source symbols greater than or equal to this symbol.")
    parser.add_argument("--stop-symbol", help="Process discovered source symbols less than or equal to this symbol.")
    parser.add_argument("--max-symbols", type=int, default=0, help="Limit number of source symbols processed.")
    parser.add_argument("--batch-size", type=int, default=20, help="Symbols per transaction when --apply is used.")
    parser.add_argument(
        "--bulk-update",
        action="store_true",
        help="Apply each batch with one DELETE and one UPDATE instead of one UPDATE per symbol.",
    )
    parser.add_argument(
        "--vacuum-after-updates",
        type=int,
        default=0,
        help="Run VACUUM ANALYZE on touched tables after this many updated/deleted rows. 0 disables it.",
    )
    parser.add_argument(
        "--min-free-gb",
        type=float,
        default=0,
        help="Stop before each apply batch when disk free space under --disk-path is below this many GiB. 0 disables it.",
    )
    parser.add_argument("--disk-path", default="/System/Volumes/Data", help="Path used by --min-free-gb checks.")
    parser.add_argument("--apply", action="store_true", help="Actually update/delete rows in final K-line tables.")
    return parser.parse_args()


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


def source_symbol_candidates(raw_symbols: list[str]) -> list[str]:
    candidates: set[str] = set()
    for raw in raw_symbols:
        source = str(raw or "").strip()
        if not source:
            continue
        normalized = normalize_symbol(source)
        if source != normalized:
            candidates.add(source)
        if source.startswith("bj") and len(source) == 8:
            candidates.add(source)
    return sorted(candidates)


def filter_symbol_range(source_symbols: list[str], *, start_symbol: str | None, stop_symbol: str | None) -> list[str]:
    start = str(start_symbol or "").strip().upper()
    stop = str(stop_symbol or "").strip().upper()
    filtered: list[str] = []
    for symbol in source_symbols:
        key = str(symbol or "").strip().upper()
        if start and key < start:
            continue
        if stop and key > stop:
            continue
        filtered.append(symbol)
    return filtered


def discover_minute_source_symbols(*, symbols: list[str], max_symbols: int) -> list[str]:
    if symbols:
        return source_symbol_candidates(symbols)

    daily_candidates = text(
        """
        SELECT DISTINCT split_part(upper(symbol), '.', 1) AS symbol
        FROM stock_daily_kline
        WHERE symbol IS NOT NULL
          AND split_part(upper(symbol), '.', 1) ~ '^[0-9]{6}$'
        ORDER BY symbol
        """
    )
    with engine.connect() as conn:
        rows = [str(row[0]) for row in conn.execute(daily_candidates).fetchall()]

    if rows:
        return source_symbol_candidates(rows)

    stats_limit_clause = "LIMIT :limit" if max_symbols > 0 else ""
    stats_params = {"limit": max_symbols} if max_symbols > 0 else {}
    stats_candidates = text(
        f"""
        SELECT trim(symbol) AS symbol
        FROM pg_stats,
             regexp_split_to_table(trim(both '{{}}' from most_common_vals::text), ',') AS symbol
        WHERE schemaname = ANY(current_schemas(false))
          AND tablename = 'stock_minute_kline'
          AND attname = 'symbol'
          AND symbol NOT LIKE '%.%'
        ORDER BY symbol
        {stats_limit_clause}
        """
    )
    with engine.connect() as conn:
        stats_rows = [str(row[0]) for row in conn.execute(stats_candidates, stats_params).fetchall()]

    if stats_rows:
        return source_symbol_candidates(stats_rows)

    fallback_limit = "LIMIT :limit" if max_symbols > 0 else "LIMIT 200"
    fallback_params = {"limit": max_symbols} if max_symbols > 0 else {}
    fallback = text(
        f"""
        SELECT DISTINCT symbol
        FROM stock_minute_kline
        WHERE symbol NOT LIKE '%.%'
        ORDER BY symbol
        {fallback_limit}
        """
    )
    with engine.connect() as conn:
        return source_symbol_candidates([str(row[0]) for row in conn.execute(fallback, fallback_params).fetchall()])


def discover_daily_source_symbols(*, symbols: list[str], max_symbols: int) -> list[str]:
    if symbols:
        return source_symbol_candidates(symbols)
    limit_clause = "LIMIT :limit" if max_symbols > 0 else ""
    params = {"limit": max_symbols} if max_symbols > 0 else {}
    statement = text(
        f"""
        SELECT DISTINCT symbol
        FROM stock_daily_kline
        WHERE symbol IS NOT NULL
          AND (
              symbol NOT LIKE '%.%'
              OR lower(symbol) LIKE 'bj%'
          )
        ORDER BY symbol
        {limit_clause}
        """
    )
    with engine.connect() as conn:
        return source_symbol_candidates([str(row[0]) for row in conn.execute(statement, params).fetchall()])


def build_plan(*, table_name: str, source_symbol: str) -> SymbolPlan:
    target_symbol = normalize_symbol(source_symbol)
    if not target_symbol or target_symbol == source_symbol:
        return SymbolPlan(table_name, source_symbol, target_symbol, 0, 0, 0)
    date_column = "trade_date" if table_name == "stock_daily_kline" else "trade_time"
    with engine.connect() as conn:
        estimated_rows = int(
            conn.execute(
                text(f"SELECT COUNT(*) FROM {table_name} WHERE symbol = :source_symbol"),
                {"source_symbol": source_symbol},
            ).scalar()
            or 0
        )
        has_target_rows = bool(
            conn.execute(
                text(f"SELECT 1 FROM {table_name} WHERE symbol = :target_symbol LIMIT 1"),
                {"target_symbol": target_symbol},
            ).scalar()
        )
        if not has_target_rows:
            return SymbolPlan(
                table_name=table_name,
                source_symbol=source_symbol,
                target_symbol=target_symbol,
                estimated_rows=estimated_rows,
                conflict_rows=0,
                safe_update_rows=estimated_rows,
            )
        conflict_rows = int(
            conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM {table_name} source
                    WHERE source.symbol = :source_symbol
                      AND EXISTS (
                          SELECT 1
                          FROM {table_name} target
                          WHERE target.symbol = :target_symbol
                            AND target.{date_column} = source.{date_column}
                      )
                    """.format(table_name=table_name, date_column=date_column)
                ),
                {"source_symbol": source_symbol, "target_symbol": target_symbol},
            ).scalar()
            or 0
        )
    return SymbolPlan(
        table_name=table_name,
        source_symbol=source_symbol,
        target_symbol=target_symbol,
        estimated_rows=estimated_rows,
        conflict_rows=conflict_rows,
        safe_update_rows=max(estimated_rows - conflict_rows, 0),
    )


def apply_plan_batch(plans: list[SymbolPlan]) -> dict[str, int]:
    updated = 0
    deleted = 0
    with engine.begin() as conn:
        for plan in plans:
            if not plan.target_symbol or plan.target_symbol == plan.source_symbol:
                continue
            date_column = "trade_date" if plan.table_name == "stock_daily_kline" else "trade_time"
            if plan.conflict_rows == 0:
                update_result = conn.execute(
                    text(
                        """
                        UPDATE {table_name}
                        SET symbol = :target_symbol,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE symbol = :source_symbol
                        """.format(table_name=plan.table_name)
                    ),
                    {"source_symbol": plan.source_symbol, "target_symbol": plan.target_symbol},
                )
            else:
                update_result = conn.execute(
                    text(
                        """
                        UPDATE {table_name} source
                        SET symbol = :target_symbol,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE source.symbol = :source_symbol
                          AND NOT EXISTS (
                              SELECT 1
                              FROM {table_name} target
                              WHERE target.symbol = :target_symbol
                                AND target.{date_column} = source.{date_column}
                          )
                        """.format(table_name=plan.table_name, date_column=date_column)
                    ),
                    {"source_symbol": plan.source_symbol, "target_symbol": plan.target_symbol},
                )
            updated += int(update_result.rowcount or 0)
            if plan.conflict_rows > 0:
                delete_result = conn.execute(
                    text(
                        """
                        DELETE FROM {table_name} source
                        WHERE source.symbol = :source_symbol
                          AND EXISTS (
                              SELECT 1
                              FROM {table_name} target
                              WHERE target.symbol = :target_symbol
                                AND target.{date_column} = source.{date_column}
                          )
                        """.format(table_name=plan.table_name, date_column=date_column)
                    ),
                    {"source_symbol": plan.source_symbol, "target_symbol": plan.target_symbol},
                )
                deleted += int(delete_result.rowcount or 0)
    return {"updated": updated, "deleted_conflicts": deleted}


def normalize_symbol_sql(symbol_expr: str) -> str:
    upper_expr = f"upper({symbol_expr})"
    return f"""
        CASE
            WHEN {upper_expr} ~ '^BJ[0-9]{{6}}$' THEN substring({upper_expr} from 3) || '.BJ'
            WHEN {upper_expr} ~ '^[0-9]{{6}}$'
                 AND ({upper_expr} LIKE '4%' OR {upper_expr} LIKE '8%' OR {upper_expr} LIKE '92%')
                THEN {upper_expr} || '.BJ'
            WHEN {upper_expr} ~ '^[0-9]{{6}}$'
                 AND ({upper_expr} LIKE '5%' OR {upper_expr} LIKE '6%' OR {upper_expr} LIKE '9%')
                THEN {upper_expr} || '.SH'
            WHEN {upper_expr} ~ '^[0-9]{{6}}$' THEN {upper_expr} || '.SZ'
            ELSE {upper_expr}
        END
    """


def apply_bulk_plan_batch(plans: list[SymbolPlan]) -> dict[str, int]:
    updated = 0
    deleted = 0
    grouped: dict[str, list[SymbolPlan]] = {}
    for plan in plans:
        if plan.target_symbol and plan.target_symbol != plan.source_symbol:
            grouped.setdefault(plan.table_name, []).append(plan)
    with engine.begin() as conn:
        for table_name, table_plans in grouped.items():
            source_symbols = [plan.source_symbol for plan in table_plans]
            date_column = "trade_date" if table_name == "stock_daily_kline" else "trade_time"
            normalized_symbol = normalize_symbol_sql("source.symbol")
            delete_sql = text(
                f"""
                DELETE FROM {table_name} source
                WHERE source.symbol IN :source_symbols
                  AND EXISTS (
                      SELECT 1
                      FROM {table_name} target
                      WHERE target.symbol = {normalized_symbol}
                        AND target.{date_column} = source.{date_column}
                  )
                """
            ).bindparams(bindparam("source_symbols", expanding=True))
            delete_result = conn.execute(delete_sql, {"source_symbols": source_symbols})
            deleted += int(delete_result.rowcount or 0)

            normalized_symbol = normalize_symbol_sql("symbol")
            update_sql = text(
                f"""
                UPDATE {table_name}
                SET symbol = {normalized_symbol},
                    updated_at = CURRENT_TIMESTAMP
                WHERE symbol IN :source_symbols
                """
            ).bindparams(bindparam("source_symbols", expanding=True))
            update_result = conn.execute(update_sql, {"source_symbols": source_symbols})
            updated += int(update_result.rowcount or 0)
    return {"updated": updated, "deleted_conflicts": deleted}


def free_gib(path: str) -> float:
    usage = shutil.disk_usage(path)
    return usage.free / (1024**3)


def vacuum_table(table_name: str) -> None:
    conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        print(f"vacuum {table_name} start", flush=True)
        conn.execute(text(f"VACUUM ANALYZE {table_name}"))
        print(f"vacuum {table_name} done", flush=True)
    finally:
        conn.close()


def ensure_disk_space(*, min_free_gb: float, disk_path: str) -> None:
    if min_free_gb <= 0:
        return
    free = free_gib(disk_path)
    print(f"disk free at {disk_path}: {free:.1f} GiB", flush=True)
    if free < min_free_gb:
        raise RuntimeError(
            f"free disk space at {disk_path} is {free:.1f} GiB, below required {min_free_gb:.1f} GiB"
        )


def apply_plans(
    plans: list[SymbolPlan],
    *,
    batch_size: int,
    bulk_update: bool = False,
    vacuum_after_updates: int = 0,
    min_free_gb: float = 0,
    disk_path: str = "/System/Volumes/Data",
) -> dict[str, int]:
    totals = {"updated": 0, "deleted_conflicts": 0}
    changed_since_vacuum: dict[str, int] = {}
    size = max(int(batch_size or 20), 1)
    for offset in range(0, len(plans), size):
        batch = plans[offset : offset + size]
        ensure_disk_space(min_free_gb=min_free_gb, disk_path=disk_path)
        result = apply_bulk_plan_batch(batch) if bulk_update else apply_plan_batch(batch)
        totals["updated"] += result["updated"]
        totals["deleted_conflicts"] += result["deleted_conflicts"]
        changed_rows = result["updated"] + result["deleted_conflicts"]
        for table_name in {plan.table_name for plan in batch}:
            changed_since_vacuum[table_name] = changed_since_vacuum.get(table_name, 0) + changed_rows
        print(
            f"applied batch {offset // size + 1}: "
            f"updated={result['updated']} deleted_conflicts={result['deleted_conflicts']}",
            flush=True,
        )
        if vacuum_after_updates > 0:
            for table_name, changed in list(changed_since_vacuum.items()):
                if changed >= vacuum_after_updates:
                    vacuum_table(table_name)
                    changed_since_vacuum[table_name] = 0
    return totals


def append_symbol_plans(
    plans: list[SymbolPlan],
    *,
    table_name: str,
    source_symbols: list[str],
    max_plans: int | None,
) -> None:
    """Append at most max_plans plans that actually match rows."""
    for symbol in source_symbols:
        if max_plans is not None and len(plans) >= max_plans:
            break
        plan = build_plan(table_name=table_name, source_symbol=symbol)
        if plan.estimated_rows > 0:
            plans.append(plan)


def main() -> int:
    args = parse_args()
    plans: list[SymbolPlan] = []
    has_range = bool(args.start_symbol or args.stop_symbol)
    discovery_max_symbols = 0 if has_range else args.max_symbols
    if args.data_type in {"daily", "all"}:
        daily_symbols = discover_daily_source_symbols(symbols=args.symbol, max_symbols=discovery_max_symbols)
        daily_symbols = filter_symbol_range(
            daily_symbols,
            start_symbol=args.start_symbol,
            stop_symbol=args.stop_symbol,
        )
        append_symbol_plans(
            plans,
            table_name="stock_daily_kline",
            source_symbols=daily_symbols,
            max_plans=args.max_symbols if args.max_symbols > 0 else None,
        )
    if args.data_type in {"minute", "all"}:
        minute_symbols = discover_minute_source_symbols(symbols=args.symbol, max_symbols=discovery_max_symbols)
        minute_symbols = filter_symbol_range(
            minute_symbols,
            start_symbol=args.start_symbol,
            stop_symbol=args.stop_symbol,
        )
        remaining_max_plans: int | None = None
        if args.max_symbols > 0:
            remaining_max_plans = max(args.max_symbols - len(plans), 0)
        append_symbol_plans(
            plans,
            table_name="stock_minute_kline",
            source_symbols=minute_symbols,
            max_plans=remaining_max_plans,
        )
    total_rows = sum(item.estimated_rows for item in plans)
    total_conflicts = sum(item.conflict_rows for item in plans)
    total_safe_updates = sum(item.safe_update_rows for item in plans)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] final K-line symbol normalization")
    print(
        f"plans={len(plans)} matched_rows={total_rows} "
        f"safe_update_rows={total_safe_updates} conflict_rows={total_conflicts}"
    )
    for plan in plans[:30]:
        print(
            f"- {plan.table_name}: {plan.source_symbol} -> {plan.target_symbol}: "
            f"rows={plan.estimated_rows} safe_update={plan.safe_update_rows} conflicts={plan.conflict_rows}"
        )
    if len(plans) > 30:
        print(f"... {len(plans) - 30} more symbols omitted")

    if not args.apply:
        print("Add --apply to update safe rows and delete old-symbol duplicates that conflict with target rows.")
        return 0

    totals = apply_plans(
        plans,
        batch_size=args.batch_size,
        bulk_update=args.bulk_update,
        vacuum_after_updates=args.vacuum_after_updates,
        min_free_gb=args.min_free_gb,
        disk_path=args.disk_path,
    )
    print(f"done: updated={totals['updated']} deleted_conflicts={totals['deleted_conflicts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

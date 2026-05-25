#!/usr/bin/env python3
"""Single-pass stock_minute_kline symbol normalization for maintenance windows.

Run this only after dropping symbol-dependent indexes/constraints. It scans the
minute table a small number of times, removes old-symbol duplicates, updates all
remaining legacy symbols in one statement, then reports the changed row counts.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.database import engine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write updates. Default is dry-run.")
    parser.add_argument("--skip-conflict-delete", action="store_true", help="Skip pre-update duplicate cleanup.")
    parser.add_argument("--min-free-gb", type=float, default=35)
    parser.add_argument("--disk-path", default="/System/Volumes/Data")
    return parser.parse_args()


NORMALIZED_SYMBOL_SQL = """
    CASE
        WHEN upper(symbol) ~ '^BJ[0-9]{6}$' THEN substring(upper(symbol) from 3) || '.BJ'
        WHEN upper(symbol) ~ '^[0-9]{6}$'
             AND (upper(symbol) LIKE '4%' OR upper(symbol) LIKE '8%' OR upper(symbol) LIKE '92%')
            THEN upper(symbol) || '.BJ'
        WHEN upper(symbol) ~ '^[0-9]{6}$'
             AND (upper(symbol) LIKE '5%' OR upper(symbol) LIKE '6%' OR upper(symbol) LIKE '9%')
            THEN upper(symbol) || '.SH'
        WHEN upper(symbol) ~ '^[0-9]{6}$' THEN upper(symbol) || '.SZ'
        ELSE upper(symbol)
    END
"""


LEGACY_FILTER = "(symbol ~ '^[0-9]{6}$' OR lower(symbol) LIKE 'bj%')"


def free_gib(path: str) -> float:
    return shutil.disk_usage(path).free / (1024**3)


def main() -> int:
    args = parse_args()
    free = free_gib(args.disk_path)
    print(f"disk free at {args.disk_path}: {free:.1f} GiB", flush=True)
    if args.min_free_gb > 0 and free < args.min_free_gb:
        raise RuntimeError(f"free disk space {free:.1f} GiB below required {args.min_free_gb:.1f} GiB")

    with engine.connect() as conn:
        matched = int(conn.execute(text(f"SELECT COUNT(*) FROM stock_minute_kline WHERE {LEGACY_FILTER}")).scalar() or 0)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] single-pass stock_minute_kline symbol normalization")
    print(f"matched_rows={matched}")
    if not args.apply or matched == 0:
        if not args.apply:
            print("Add --apply to update rows.")
        return 0

    conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        deleted = 0
        if not args.skip_conflict_delete:
            print("delete conflicts start", flush=True)
            delete_result = conn.execute(
                text(
                    f"""
                    DELETE FROM stock_minute_kline source
                    WHERE ({LEGACY_FILTER.replace('symbol', 'source.symbol')})
                      AND EXISTS (
                          SELECT 1
                          FROM stock_minute_kline target
                          WHERE target.symbol = {NORMALIZED_SYMBOL_SQL.replace('symbol', 'source.symbol')}
                            AND target.trade_time = source.trade_time
                      )
                    """
                )
            )
            deleted = int(delete_result.rowcount or 0)
            print(f"delete conflicts done: {deleted}", flush=True)
        else:
            print("delete conflicts skipped", flush=True)

        free = free_gib(args.disk_path)
        print(f"disk free at {args.disk_path}: {free:.1f} GiB", flush=True)
        if args.min_free_gb > 0 and free < args.min_free_gb:
            raise RuntimeError(f"free disk space {free:.1f} GiB below required {args.min_free_gb:.1f} GiB")

        print("update legacy symbols start", flush=True)
        update_result = conn.execute(
            text(
                f"""
                UPDATE stock_minute_kline
                SET symbol = {NORMALIZED_SYMBOL_SQL},
                    updated_at = CURRENT_TIMESTAMP
                WHERE {LEGACY_FILTER}
                """
            )
        )
        updated = int(update_result.rowcount or 0)
        print(f"update legacy symbols done: {updated}", flush=True)

        print("vacuum analyze start", flush=True)
        conn.execute(text("VACUUM ANALYZE stock_minute_kline"))
        print("vacuum analyze done", flush=True)
    finally:
        conn.close()

    print(f"done: updated={updated} deleted_conflicts={deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

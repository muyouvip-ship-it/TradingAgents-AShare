from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from api.core.env import load_project_env
except Exception:
    def load_project_env() -> None:
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成 stock_minute_kline 完整性与缺口报告。")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""), help="PostgreSQL 连接串，默认读取环境变量 DATABASE_URL")
    parser.add_argument("--limit-missing", type=int, default=200, help="缺失股票样本数量，默认 200")
    parser.add_argument("--limit-distribution", type=int, default=20, help="最新日期分布输出条数，默认 20")
    parser.add_argument("--limit-symbols", type=int, default=50, help="按股票输出明细条数，默认 50")
    parser.add_argument("--output", default="", help="可选，写出 JSON 报告文件")
    return parser.parse_args()


def main() -> int:
    load_project_env()
    args = parse_args()
    database_url = (args.database_url or "").strip()
    if not database_url:
        print("[minute-gap-report] 缺少 --database-url / DATABASE_URL", file=sys.stderr)
        return 2

    try:
        from sqlalchemy import create_engine, text
    except Exception as exc:
        print(f"[minute-gap-report] 缺少 sqlalchemy: {exc}", file=sys.stderr)
        return 2

    engine = create_engine(database_url)
    report = build_report(
        engine,
        limit_missing=max(args.limit_missing, 0),
        limit_distribution=max(args.limit_distribution, 1),
        limit_symbols=max(args.limit_symbols, 1),
    )

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")
    return 0


def build_report(engine, *, limit_missing: int, limit_distribution: int, limit_symbols: int) -> dict[str, Any]:
    from sqlalchemy import text

    with engine.connect() as conn:
        minute_overview_row = conn.execute(
            text(
                """
                SELECT
                    COUNT(*) AS row_count,
                    COUNT(DISTINCT symbol) AS symbol_count,
                    MIN(trade_time)::date AS min_date,
                    MAX(trade_time)::date AS max_date
                FROM stock_minute_kline
                """
            )
        ).mappings().one()
        daily_symbols_raw = conn.execute(text("SELECT DISTINCT symbol FROM stock_daily_kline ORDER BY symbol")).scalars().all()
        minute_symbols_raw = conn.execute(text("SELECT DISTINCT symbol FROM stock_minute_kline ORDER BY symbol")).scalars().all()
        symbol_rows = conn.execute(
            text(
                """
                SELECT
                    symbol,
                    COUNT(*) AS row_count,
                    MIN(trade_time)::date AS min_date,
                    MAX(trade_time)::date AS max_date
                FROM stock_minute_kline
                GROUP BY symbol
                ORDER BY max_date DESC NULLS LAST, row_count DESC, symbol
                """
            )
        ).mappings().all()

    daily_symbols = sorted({_normalize_symbol(symbol) for symbol in daily_symbols_raw if _normalize_symbol(symbol)})
    minute_symbols = sorted({_normalize_symbol(symbol) for symbol in minute_symbols_raw if _normalize_symbol(symbol)})
    minute_symbol_set = set(minute_symbols)
    missing_symbols_rows = [symbol for symbol in daily_symbols if symbol not in minute_symbol_set]
    max_date_distribution = Counter(
        (row["max_date"].isoformat() if hasattr(row["max_date"], "isoformat") else str(row["max_date"]))
        for row in symbol_rows
        if row["max_date"] is not None
    )
    minute_symbols_count = len(minute_symbols)
    daily_symbols_count = len(daily_symbols)
    missing_symbols_count = len(missing_symbols_rows)
    coverage_ratio = 0.0 if not daily_symbols_count else round(minute_symbols_count / daily_symbols_count, 6)

    top_symbols = []
    for row in symbol_rows[:limit_symbols]:
        top_symbols.append(
            {
                "symbol": row["symbol"],
                "row_count": int(row["row_count"] or 0),
                "min_date": row["min_date"].isoformat() if hasattr(row["min_date"], "isoformat") else row["min_date"],
                "max_date": row["max_date"].isoformat() if hasattr(row["max_date"], "isoformat") else row["max_date"],
            }
        )

    distribution_items = [
        {"max_date": max_date, "symbol_count": count}
        for max_date, count in max_date_distribution.most_common(limit_distribution)
    ]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "stock_minute_kline": {
            "row_count": int(minute_overview_row["row_count"] or 0),
            "symbol_count": minute_symbols_count,
            "min_date": minute_overview_row["min_date"].isoformat() if hasattr(minute_overview_row["min_date"], "isoformat") else minute_overview_row["min_date"],
            "max_date": minute_overview_row["max_date"].isoformat() if hasattr(minute_overview_row["max_date"], "isoformat") else minute_overview_row["max_date"],
        },
        "stock_daily_kline": {
            "symbol_count": daily_symbols_count,
        },
        "coverage": {
            "minute_symbols": minute_symbols_count,
            "daily_symbols": daily_symbols_count,
            "missing_symbols": missing_symbols_count,
            "coverage_ratio": coverage_ratio,
        },
        "missing_symbols_sample": missing_symbols_rows[:limit_missing],
        "latest_max_date_distribution": distribution_items,
        "top_symbol_summaries": top_symbols,
    }


def _normalize_symbol(raw: Any) -> str:
    text = str(raw or "").strip().upper()
    if not text:
        return ""
    if "." in text:
        return text
    if len(text) == 6:
        if text.startswith("6"):
            return f"{text}.SH"
        if text.startswith(("0", "3")):
            return f"{text}.SZ"
        if text.startswith(("4", "8", "9")):
            return f"{text}.BJ"
    return text


if __name__ == "__main__":
    raise SystemExit(main())

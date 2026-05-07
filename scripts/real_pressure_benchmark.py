from __future__ import annotations

import gc
import json
import os
import subprocess
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import duckdb
import pandas as pd
from sqlalchemy import func

from api.core.strategy_db import StrategySessionLocal
from api.models.strategy_models import RealtimeEventDB
from api.routes.strategy_platform import _default_dsl
from api.services.daily_kline_parquet_store import (
    get_daily_kline_parquet_root,
    load_daily_kline_slice_from_parquet,
)
from api.services.realtime_monitor_service import list_events
from api.services.strategy_compute_backend import compute_daily_features
from api.services.strategy_dsl_compiler import compile_strategy_dsl
from api.services.strategy_platform_engine import (
    ARTIFACT_ROOT,
    read_artifact_items,
    read_artifact_page,
    run_strategy_backtest,
)

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None


OUTPUT_DIR = ROOT / "eval_results"
DEFAULT_START = os.getenv("PRESSURE_START_DATE", "2025-01-01")
DEFAULT_END = os.getenv("PRESSURE_END_DATE", "2026-05-06")
FULL_SCAN_START = os.getenv("PRESSURE_FULL_SCAN_START", "2020-01-01")
FULL_SCAN_END = os.getenv("PRESSURE_FULL_SCAN_END", "2026-05-06")
SAMPLE_SYMBOLS = int(os.getenv("PRESSURE_SAMPLE_SYMBOLS", "1000"))


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_started = datetime.now().strftime("%Y%m%d_%H%M%S")
    report: dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "config": {
            "default_start": DEFAULT_START,
            "default_end": DEFAULT_END,
            "full_scan_start": FULL_SCAN_START,
            "full_scan_end": FULL_SCAN_END,
            "sample_symbols": SAMPLE_SYMBOLS,
        },
        "benchmarks": {},
    }

    parquet_root = get_daily_kline_parquet_root()
    parquet_files = sorted(parquet_root.glob("*.parquet"))
    report["dataset"] = inspect_daily_parquet(parquet_files)
    sample_symbols = sample_symbols_for_window(parquet_files, DEFAULT_START, DEFAULT_END, SAMPLE_SYMBOLS)
    report["dataset"]["sample_symbol_count"] = len(sample_symbols)

    frame_holder: dict[str, pd.DataFrame | None] = {"full_window": None}
    compiled = compile_strategy_dsl(_default_dsl("portfolio").model_dump())

    report["benchmarks"]["duckdb_metadata_count"] = benchmark(
        lambda: inspect_daily_parquet(parquet_files, detailed=False),
        metric_name="parquet files",
        metric_count=len(parquet_files),
    )

    report["benchmarks"]["daily_slice_sample_symbols"] = benchmark(
        lambda: load_daily_kline_slice_from_parquet(
            symbols=sample_symbols,
            start_date=DEFAULT_START,
            end_date=DEFAULT_END,
        ),
        metric_name="rows",
        count_result=lambda frame: 0 if frame is None else len(frame),
    )

    def load_full_window() -> pd.DataFrame | None:
        frame = load_daily_kline_slice_from_parquet(
            symbols=[],
            start_date=DEFAULT_START,
            end_date=DEFAULT_END,
        )
        frame_holder["full_window"] = frame
        return frame

    report["benchmarks"]["daily_slice_all_market_window"] = benchmark(
        load_full_window,
        metric_name="rows",
        count_result=lambda frame: 0 if frame is None else len(frame),
    )

    report["benchmarks"]["duckdb_full_scan_window_count"] = benchmark(
        lambda: duckdb.execute(
            """
            SELECT COUNT(*) AS row_count, COUNT(DISTINCT symbol) AS symbol_count
            FROM read_parquet(?, union_by_name=true)
            WHERE CAST(date AS DATE) >= CAST(? AS DATE)
              AND CAST(date AS DATE) <= CAST(? AS DATE)
            """,
            ([str(path) for path in parquet_files], FULL_SCAN_START, FULL_SCAN_END),
        ).fetchone(),
        metric_name="rows",
        count_result=lambda row: int(row[0] or 0),
        extra_result=lambda row: {"symbol_count": int(row[1] or 0)},
    )

    full_frame = frame_holder["full_window"]
    if full_frame is not None and not full_frame.empty:
        report["benchmarks"]["compute_daily_features_all_market_window"] = benchmark(
            lambda: compute_daily_features(full_frame, compiled),
            metric_name="rows",
            count_result=lambda result: len(result[0]),
            extra_result=lambda result: {"backend": result[1]},
        )
    else:
        report["benchmarks"]["compute_daily_features_all_market_window"] = {"skipped": "full frame unavailable"}

    run_id = f"pressure_{run_started}"
    report["benchmarks"]["run_strategy_backtest_all_market_window"] = benchmark(
        lambda: run_strategy_backtest(
            run_id=run_id,
            strategy_name="real_pressure_all_market",
            dsl=_default_dsl("portfolio").model_dump(),
            symbols=[],
            start_date=DEFAULT_START,
            end_date=DEFAULT_END,
            initial_capital=1_000_000,
            frequency="daily",
            benchmark="沪深300",
            use_minute_confirm=False,
        ),
        metric_name="watchlist rows",
        count_result=lambda result: len(result.watchlists),
        extra_result=lambda result: {
            "run_id": run_id,
            "equity_rows": len(result.equity),
            "trade_rows": len(result.trades),
            "order_rows": len(result.orders),
            "artifact_root": result.artifact_root,
            "data_source": result.summary.get("data_source"),
        },
    )

    report["benchmarks"]["artifact_page_watchlists_latest_run"] = benchmark(
        lambda: read_artifact_page(run_id, "watchlists", skip=0, limit=1000, sort_by="rank", sort_order="asc"),
        metric_name="rows",
        count_result=lambda page: len((page or {}).get("items") or []),
        extra_result=lambda page: {"total": (page or {}).get("total")},
    )

    report["benchmarks"]["artifact_full_json_watchlists_latest_run"] = benchmark(
        lambda: read_artifact_items(run_id, "watchlists"),
        metric_name="rows",
        count_result=len,
    )

    largest_existing = largest_existing_watchlist_artifact()
    if largest_existing:
        existing_run_id, existing_rows = largest_existing
        report["benchmarks"]["artifact_page_largest_existing_watchlists"] = benchmark(
            lambda: read_artifact_page(existing_run_id, "watchlists", skip=0, limit=1000, sort_by="rank", sort_order="asc"),
            metric_name="rows",
            count_result=lambda page: len((page or {}).get("items") or []),
            extra_result=lambda page: {"run_id": existing_run_id, "existing_total": existing_rows, "total": (page or {}).get("total")},
        )

    report["benchmarks"]["realtime_events_real_cursor"] = benchmark_realtime_events()

    report["finished_at"] = datetime.now().isoformat(timespec="seconds")
    json_path = OUTPUT_DIR / f"real_pressure_benchmark_{run_started}.json"
    latest_json_path = OUTPUT_DIR / "real_pressure_benchmark_latest.json"
    md_path = OUTPUT_DIR / f"real_pressure_benchmark_{run_started}.md"
    latest_md_path = OUTPUT_DIR / "real_pressure_benchmark_latest.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    latest_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    markdown = render_markdown(report)
    md_path.write_text(markdown, encoding="utf-8")
    latest_md_path.write_text(markdown, encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "summary": summarize(report)}, ensure_ascii=False, indent=2))


def rss_mb() -> float | None:
    if psutil is None:
        try:
            output = subprocess.check_output(
                ["ps", "-o", "rss=", "-p", str(os.getpid())],
                text=True,
            ).strip()
            return int(output) / 1024 if output else None
        except Exception:
            return None
    return psutil.Process().memory_info().rss / 1024 / 1024


def benchmark(
    fn: Callable[[], Any],
    *,
    metric_name: str,
    metric_count: int | None = None,
    count_result: Callable[[Any], int] | None = None,
    extra_result: Callable[[Any], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    gc.collect()
    rss_before = rss_mb()
    started = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - started
    rss_after = rss_mb()
    count = metric_count if metric_count is not None else count_result(result) if count_result else None
    payload: dict[str, Any] = {
        "elapsed_seconds": round(elapsed, 4),
        "metric_name": metric_name,
        "metric_count": count,
        "throughput_per_second": round(count / elapsed, 2) if count is not None and elapsed > 0 else None,
        "rss_before_mb": round(rss_before, 2) if rss_before is not None else None,
        "rss_after_mb": round(rss_after, 2) if rss_after is not None else None,
        "rss_delta_mb": round(rss_after - rss_before, 2) if rss_before is not None and rss_after is not None else None,
    }
    if extra_result:
        payload.update(extra_result(result))
    return payload


def inspect_daily_parquet(parquet_files: list[Path], *, detailed: bool = True) -> dict[str, Any]:
    row = duckdb.execute(
        """
        SELECT COUNT(*) AS row_count,
               COUNT(DISTINCT symbol) AS symbol_count,
               MIN(CAST(date AS DATE)) AS min_date,
               MAX(CAST(date AS DATE)) AS max_date
        FROM read_parquet(?, union_by_name=true)
        """,
        ([str(path) for path in parquet_files],),
    ).fetchone()
    result = {
        "root": str(get_daily_kline_parquet_root()),
        "file_count": len(parquet_files),
        "size_mb": round(sum(path.stat().st_size for path in parquet_files) / 1024 / 1024, 2),
        "row_count": int(row[0] or 0),
        "symbol_count": int(row[1] or 0),
        "min_date": str(row[2]),
        "max_date": str(row[3]),
    }
    if detailed:
        yearly = duckdb.execute(
            """
            SELECT year(CAST(date AS DATE)) AS year,
                   COUNT(*) AS row_count,
                   COUNT(DISTINCT symbol) AS symbol_count
            FROM read_parquet(?, union_by_name=true)
            GROUP BY 1 ORDER BY 1 DESC LIMIT 10
            """,
            ([str(path) for path in parquet_files],),
        ).fetchdf()
        result["latest_years"] = yearly.to_dict("records")
    return result


def sample_symbols_for_window(parquet_files: list[Path], start_date: str, end_date: str, limit: int) -> list[str]:
    frame = duckdb.execute(
        """
        SELECT symbol
        FROM (
            SELECT symbol, COUNT(*) AS rows
            FROM read_parquet(?, union_by_name=true)
            WHERE CAST(date AS DATE) >= CAST(? AS DATE)
              AND CAST(date AS DATE) <= CAST(? AS DATE)
            GROUP BY symbol
        )
        ORDER BY rows DESC, symbol
        LIMIT ?
        """,
        ([str(path) for path in parquet_files], start_date, end_date, limit),
    ).fetchdf()
    return [str(value) for value in frame["symbol"].tolist()]


def largest_existing_watchlist_artifact() -> tuple[str, int] | None:
    best: tuple[str, int] | None = None
    for path in ARTIFACT_ROOT.glob("*/watchlists.parquet"):
        try:
            rows = int(duckdb.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(path)]).fetchone()[0] or 0)
        except Exception:
            continue
        if best is None or rows > best[1]:
            best = (path.parent.name, rows)
    return best


def benchmark_realtime_events() -> dict[str, Any]:
    db = StrategySessionLocal()
    try:
        grouped = (
            db.query(
                RealtimeEventDB.user_id,
                RealtimeEventDB.monitor_id,
                func.count(RealtimeEventDB.id).label("event_count"),
            )
            .group_by(RealtimeEventDB.user_id, RealtimeEventDB.monitor_id)
            .order_by(func.count(RealtimeEventDB.id).desc())
            .first()
        )
        if grouped is None:
            return {"skipped": "no realtime events in strategy database"}
        user_id, monitor_id, event_count = grouped
        initial = benchmark(
            lambda: list_events(db, str(user_id), str(monitor_id), limit=1000),
            metric_name="events",
            count_result=len,
        )
        first_page = list_events(db, str(user_id), str(monitor_id), limit=1000)
        after_id = first_page[0]["id"] if first_page else None
        cursor = benchmark(
            lambda: list_events(db, str(user_id), str(monitor_id), limit=200, after_id=after_id),
            metric_name="events",
            count_result=len,
        )
        return {
            "user_id": str(user_id),
            "monitor_id": str(monitor_id),
            "event_count": int(event_count or 0),
            "initial_page": initial,
            "cursor_page": cursor,
        }
    finally:
        db.close()


def summarize(report: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "dataset_rows": report.get("dataset", {}).get("row_count"),
        "dataset_size_mb": report.get("dataset", {}).get("size_mb"),
    }
    for name, item in (report.get("benchmarks") or {}).items():
        if isinstance(item, dict) and "elapsed_seconds" in item:
            summary[name] = {
                "elapsed_seconds": item.get("elapsed_seconds"),
                "metric_count": item.get("metric_count"),
                "throughput_per_second": item.get("throughput_per_second"),
            }
    return summary


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Real Pressure Benchmark",
        "",
        f"- Started: {report.get('started_at')}",
        f"- Finished: {report.get('finished_at')}",
        "",
        "## Dataset",
    ]
    dataset = report.get("dataset") or {}
    for key in ["root", "file_count", "size_mb", "row_count", "symbol_count", "min_date", "max_date", "sample_symbol_count"]:
        lines.append(f"- {key}: {dataset.get(key)}")
    lines.extend(["", "## Benchmarks", ""])
    lines.append("| name | seconds | count | throughput/s | rss delta MB | notes |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for name, item in (report.get("benchmarks") or {}).items():
        if not isinstance(item, dict):
            continue
        if "skipped" in item:
            lines.append(f"| {name} | - | - | - | - | skipped: {item.get('skipped')} |")
            continue
        if name == "realtime_events_real_cursor":
            initial = item.get("initial_page") or {}
            cursor = item.get("cursor_page") or {}
            lines.append(
                f"| {name}: initial_page | {initial.get('elapsed_seconds')} | {initial.get('metric_count')} | "
                f"{initial.get('throughput_per_second')} | {initial.get('rss_delta_mb')} | total events={item.get('event_count')} |"
            )
            lines.append(
                f"| {name}: cursor_page | {cursor.get('elapsed_seconds')} | {cursor.get('metric_count')} | "
                f"{cursor.get('throughput_per_second')} | {cursor.get('rss_delta_mb')} | monitor={item.get('monitor_id')} |"
            )
            continue
        notes = []
        for key in ["backend", "run_id", "total", "symbol_count", "data_source"]:
            if item.get(key) is not None:
                notes.append(f"{key}={item.get(key)}")
        lines.append(
            f"| {name} | {item.get('elapsed_seconds')} | {item.get('metric_count')} | "
            f"{item.get('throughput_per_second')} | {item.get('rss_delta_mb')} | {'; '.join(notes)} |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()

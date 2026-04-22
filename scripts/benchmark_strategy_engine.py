from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.routes.strategy_platform import _default_dsl
from api.services.daily_kline_parquet_store import get_daily_kline_parquet_root, load_daily_kline_slice_from_parquet
from api.services.minute_data_service import load_aggregated_minute_bars
from api.services.strategy_compute_backend import compute_daily_features
from api.services.strategy_dsl_compiler import compile_strategy_dsl
from api.services.strategy_platform_engine import _generate_synthetic_daily_kline


OUTPUT_PATH = Path("eval_results/strategy_engine_benchmark.json")


def run_benchmark() -> dict:
    symbols = [f"{300000 + index:06d}.SZ" for index in range(200)]
    compiled = compile_strategy_dsl(_default_dsl("portfolio").model_dump())

    daily_started = time.perf_counter()
    daily = _generate_synthetic_daily_kline(symbols, "2020-01-01", "2024-12-31")
    features, backend = compute_daily_features(daily, compiled)
    daily_elapsed = time.perf_counter() - daily_started

    watchlist = symbols[:30]
    minute_started = time.perf_counter()
    minute_result = load_aggregated_minute_bars(
        symbols=watchlist,
        trade_date="2024-10-08",
        timeframe="30m",
    )
    minute_elapsed = time.perf_counter() - minute_started
    parquet_root = get_daily_kline_parquet_root()
    parquet_files = sorted(parquet_root.glob("*.parquet"))
    parquet_probe = None
    if parquet_files:
        probe_symbols = _sample_parquet_symbols(parquet_files, limit=20) or symbols[:20]
        probe_started = time.perf_counter()
        parquet_frame = load_daily_kline_slice_from_parquet(
            symbols=probe_symbols,
            start_date="2020-01-01",
            end_date="2024-12-31",
        )
        parquet_probe = {
            "file_count": len(parquet_files),
            "sample_symbol_count": len(probe_symbols),
            "row_count": int(len(parquet_frame)) if parquet_frame is not None else 0,
            "elapsed_seconds": round(time.perf_counter() - probe_started, 4),
        }

    report = {
        "daily": {
            "symbol_count": len(symbols),
            "row_count": int(len(features)),
            "backend": backend,
            "elapsed_seconds": round(daily_elapsed, 4),
            "rows_per_second": round(len(features) / daily_elapsed, 2) if daily_elapsed else None,
        },
        "minute_lazy_loading": {
            "requested_symbol_count": len(watchlist),
            "source": minute_result.source,
            "timeframe": minute_result.timeframe,
            "bar_count": len(minute_result.items),
            "elapsed_seconds": round(minute_elapsed, 4),
            "guardrail": "only watchlist symbols are loaded; no full-market minute preload",
        },
        "duckdb_parquet_probe": parquet_probe or {
            "file_count": 0,
            "row_count": 0,
            "elapsed_seconds": None,
            "root": str(parquet_root),
            "note": "no local daily kline parquet cache found",
        },
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _sample_parquet_symbols(parquet_files: list[Path], *, limit: int) -> list[str]:
    try:
        import duckdb

        frame = duckdb.execute(
            "SELECT DISTINCT symbol FROM read_parquet(?) WHERE date >= DATE '2020-01-01' LIMIT ?",
            ([str(path) for path in parquet_files], limit),
        ).fetchdf()
        return [str(symbol) for symbol in frame["symbol"].tolist()]
    except Exception:
        return []


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), ensure_ascii=False, indent=2))

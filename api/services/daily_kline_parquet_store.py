from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd


DAILY_KLINE_PARQUET_ROOT = Path("data/artifacts/market_cache/daily_kline")


def get_daily_kline_parquet_root() -> Path:
    return Path(os.getenv("DAILY_KLINE_PARQUET_ROOT") or DAILY_KLINE_PARQUET_ROOT)


def load_daily_kline_slice_from_parquet(
    *,
    symbols: list[str],
    start_date: str,
    end_date: str,
    root: Path | None = None,
) -> pd.DataFrame | None:
    if not _has_module("duckdb"):
        return None
    root = root or get_daily_kline_parquet_root()
    files = sorted(root.glob("*.parquet"))
    if not files:
        return None
    try:
        import duckdb

        symbol_list = list(symbols)
        if symbol_list:
            query = """
                SELECT symbol, CAST(date AS DATE) AS date, open, high, low, close, volume, amount,
                       turnover_rate, pre_close, float_market_cap, total_market_cap, net_profit_ttm
                FROM read_parquet(?, union_by_name=true)
                WHERE CAST(date AS DATE) >= CAST(? AS DATE)
                  AND CAST(date AS DATE) <= CAST(? AS DATE)
                  AND symbol IN (SELECT UNNEST(?))
                QUALIFY row_number() OVER (PARTITION BY symbol, date ORDER BY date DESC) = 1
                ORDER BY date, symbol
            """
            frame = duckdb.execute(
                query,
                ([str(path) for path in files], start_date, end_date, symbol_list),
            ).fetchdf()
        else:
            query = """
                SELECT symbol, CAST(date AS DATE) AS date, open, high, low, close, volume, amount,
                       turnover_rate, pre_close, float_market_cap, total_market_cap, net_profit_ttm
                FROM read_parquet(?, union_by_name=true)
                WHERE CAST(date AS DATE) >= CAST(? AS DATE)
                  AND CAST(date AS DATE) <= CAST(? AS DATE)
                QUALIFY row_number() OVER (PARTITION BY symbol, date ORDER BY date DESC) = 1
                ORDER BY date, symbol
            """
            frame = duckdb.execute(
                query,
                ([str(path) for path in files], start_date, end_date),
            ).fetchdf()
        if frame.empty:
            return None
        return frame
    except Exception:
        return None


def write_daily_kline_parquet_cache(
    frame: pd.DataFrame,
    *,
    root: Path | None = None,
) -> str | None:
    if frame.empty or not _has_module("pyarrow"):
        return None
    root = root or get_daily_kline_parquet_root()
    root.mkdir(parents=True, exist_ok=True)
    normalized = frame.copy()
    normalized["date"] = pd.to_datetime(normalized["date"]).dt.date
    normalized["year"] = pd.to_datetime(normalized["date"]).dt.year
    written_paths: list[str] = []
    for year, group in normalized.groupby("year"):
        path = root / f"daily_kline_{int(year)}.parquet"
        payload = group.drop(columns=["year"]).copy()
        if path.exists():
            existing = pd.read_parquet(path)
            payload = pd.concat([existing, payload], ignore_index=True)
        payload = payload.drop_duplicates(["symbol", "date"], keep="last").sort_values(["date", "symbol"])
        payload.to_parquet(path, index=False)
        written_paths.append(str(path))
    return ",".join(written_paths) if written_paths else None


def normalize_daily_kline_with_duckdb(frame: pd.DataFrame) -> pd.DataFrame | None:
    if frame.empty or not _has_module("duckdb"):
        return None
    try:
        import duckdb

        relation = duckdb.from_df(frame)
        normalized = relation.query(
            "daily_frame",
            """
            SELECT *
            FROM (
                SELECT *,
                       row_number() OVER (
                           PARTITION BY symbol, date
                           ORDER BY date DESC
                       ) AS row_num
                FROM daily_frame
            )
            WHERE row_num = 1
            ORDER BY date, symbol
            """,
        ).to_df()
        if "row_num" in normalized.columns:
            normalized = normalized.drop(columns=["row_num"])
        return normalized
    except Exception:
        return None


def _has_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False

from __future__ import annotations

import os
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd


DAILY_KLINE_PARQUET_ROOT = Path("data/artifacts/market_cache/daily_kline")
DAILY_KLINE_NUMERIC_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover_rate",
    "pre_close",
    "float_market_cap",
    "total_market_cap",
    "net_profit_ttm",
]


def normalize_daily_kline_symbol(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    text = re.sub(r"^(SH|SZ|BJ)", "", text)
    text = re.sub(r"\.(SH|SZ|BJ)$", "", text)
    match = re.search(r"(\d{6})", text)
    if match:
        return match.group(1)
    return text


def get_daily_kline_parquet_root() -> Path:
    return Path(os.getenv("DAILY_KLINE_PARQUET_ROOT") or DAILY_KLINE_PARQUET_ROOT)


def get_daily_kline_parquet_stats(
    *,
    root: Path | None = None,
) -> dict[str, Any] | None:
    root = root or get_daily_kline_parquet_root()
    files = sorted(root.glob("*.parquet"))
    if not files:
        return None

    latest_mtime = max(path.stat().st_mtime for path in files)
    last_updated_at = datetime.fromtimestamp(latest_mtime)

    try:
        if _has_module("duckdb"):
            import duckdb

            row = duckdb.execute(
                """
                WITH normalized AS (
                    SELECT
                        regexp_replace(
                            regexp_replace(upper(trim(symbol)), '^(SH|SZ|BJ)', ''),
                            '\\.(SH|SZ|BJ)$',
                            ''
                        ) AS normalized_symbol,
                        CAST(date AS DATE) AS trade_date
                    FROM read_parquet(?, union_by_name=true)
                    WHERE symbol IS NOT NULL
                      AND date IS NOT NULL
                ),
                deduped AS (
                    SELECT normalized_symbol AS symbol, trade_date AS date
                    FROM normalized
                    WHERE normalized_symbol <> ''
                    GROUP BY 1, 2
                )
                SELECT
                    COUNT(*) AS total_records,
                    COUNT(DISTINCT symbol) AS symbol_count,
                    COUNT(DISTINCT date) AS trading_days,
                    MIN(date) AS date_range_start,
                    MAX(date) AS date_range_end
                FROM deduped
                """,
                ([str(path) for path in files],),
            ).fetchone()
            if row is None or int(row[0] or 0) <= 0:
                return None
            return {
                "total_records": int(row[0] or 0),
                "symbol_count": int(row[1] or 0),
                "trading_days": int(row[2] or 0),
                "date_range_start": row[3],
                "date_range_end": row[4],
                "last_table_updated_at": last_updated_at,
            }

        if _has_module("pyarrow"):
            frames = [
                pd.read_parquet(path, columns=["symbol", "date"])
                for path in files
            ]
            merged = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            if merged.empty:
                return None
            merged["symbol"] = merged["symbol"].map(normalize_daily_kline_symbol)
            merged["date"] = pd.to_datetime(merged["date"]).dt.date
            merged = merged[merged["symbol"].astype(str).str.len() > 0].drop_duplicates(["symbol", "date"], keep="last")
            return {
                "total_records": int(len(merged)),
                "symbol_count": int(merged["symbol"].nunique()),
                "trading_days": int(merged["date"].nunique()),
                "date_range_start": merged["date"].min(),
                "date_range_end": merged["date"].max(),
                "last_table_updated_at": last_updated_at,
            }
    except Exception:
        return None

    return None


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
        normalized_symbols = [normalize_daily_kline_symbol(symbol) for symbol in symbol_list if normalize_daily_kline_symbol(symbol)]
        if symbol_list:
            query = """
                WITH normalized AS (
                    SELECT
                        regexp_replace(
                            regexp_replace(upper(trim(symbol)), '^(SH|SZ|BJ)', ''),
                            '\\.(SH|SZ|BJ)$',
                            ''
                        ) AS normalized_symbol,
                        CAST(date AS DATE) AS date,
                        open, high, low, close, volume, amount,
                        turnover_rate, pre_close, float_market_cap, total_market_cap, net_profit_ttm
                    FROM read_parquet(?, union_by_name=true)
                )
                SELECT normalized_symbol AS symbol, date, open, high, low, close, volume, amount,
                       turnover_rate, pre_close, float_market_cap, total_market_cap, net_profit_ttm
                FROM normalized
                WHERE date >= CAST(? AS DATE)
                  AND date <= CAST(? AS DATE)
                  AND normalized_symbol IN (SELECT UNNEST(?))
                QUALIFY row_number() OVER (PARTITION BY normalized_symbol, date ORDER BY date DESC) = 1
                ORDER BY date, symbol
            """
            frame = duckdb.execute(
                query,
                ([str(path) for path in files], start_date, end_date, normalized_symbols),
            ).fetchdf()
        else:
            query = """
                WITH normalized AS (
                    SELECT
                        regexp_replace(
                            regexp_replace(upper(trim(symbol)), '^(SH|SZ|BJ)', ''),
                            '\\.(SH|SZ|BJ)$',
                            ''
                        ) AS normalized_symbol,
                        CAST(date AS DATE) AS date,
                        open, high, low, close, volume, amount,
                        turnover_rate, pre_close, float_market_cap, total_market_cap, net_profit_ttm
                    FROM read_parquet(?, union_by_name=true)
                )
                SELECT normalized_symbol AS symbol, date, open, high, low, close, volume, amount,
                       turnover_rate, pre_close, float_market_cap, total_market_cap, net_profit_ttm
                FROM normalized
                WHERE date >= CAST(? AS DATE)
                  AND date <= CAST(? AS DATE)
                  AND normalized_symbol <> ''
                QUALIFY row_number() OVER (PARTITION BY normalized_symbol, date ORDER BY date DESC) = 1
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
    normalized = _normalize_daily_kline_frame_for_parquet(frame)
    normalized["year"] = pd.to_datetime(normalized["date"]).dt.year
    written_paths: list[str] = []
    for year, group in normalized.groupby("year"):
        path = root / f"daily_kline_{int(year)}.parquet"
        payload = group.drop(columns=["year"]).copy()
        if path.exists():
            existing = _normalize_daily_kline_frame_for_parquet(pd.read_parquet(path))
            payload = pd.concat([existing, payload], ignore_index=True)
        payload = _normalize_daily_kline_frame_for_parquet(payload)
        payload = payload.drop_duplicates(["symbol", "date"], keep="last").sort_values(["date", "symbol"])
        payload.to_parquet(path, index=False)
        written_paths.append(str(path))
    return ",".join(written_paths) if written_paths else None


def _normalize_daily_kline_frame_for_parquet(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    if "symbol" in normalized.columns:
        normalized["symbol"] = normalized["symbol"].map(normalize_daily_kline_symbol)
        normalized = normalized[normalized["symbol"].astype(str).str.len() > 0]
    if "date" in normalized.columns:
        normalized["date"] = pd.to_datetime(normalized["date"]).dt.date
    for column in DAILY_KLINE_NUMERIC_COLUMNS:
        if column not in normalized.columns:
            continue
        normalized[column] = normalized[column].map(_decimal_to_float) if normalized[column].dtype == "object" else normalized[column]
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    return normalized


def _decimal_to_float(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


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

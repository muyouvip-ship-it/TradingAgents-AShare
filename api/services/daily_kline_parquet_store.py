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
_DAILY_KLINE_SCHEMA_CACHE: dict[tuple[str, ...], set[str]] = {}


def normalize_daily_kline_symbol(value: Any) -> str:
    text = str(value or "").strip().upper()
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
    columns: list[str] | None = None,
) -> pd.DataFrame | None:
    root = root or get_daily_kline_parquet_root()
    files = _daily_kline_files_for_range(root, start_date, end_date)
    if not files:
        return None
    selected_columns = _resolve_daily_kline_columns(files, columns)
    duckdb_frame = _load_daily_kline_slice_with_duckdb(
        files=files,
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        columns=selected_columns,
    )
    if duckdb_frame is not None:
        return duckdb_frame
    try:
        frames = [_read_daily_kline_parquet_frame(path, selected_columns) for path in files]
        usable_frames = [frame for frame in frames if not frame.empty and not frame.dropna(how="all").empty]
        merged = pd.concat(usable_frames, ignore_index=True) if usable_frames else pd.DataFrame()
        if merged.empty:
            return None
        normalized = _normalize_daily_kline_frame_for_parquet(merged)
        normalized["date"] = pd.to_datetime(normalized["date"]).dt.date
        start = pd.to_datetime(start_date).date()
        end = pd.to_datetime(end_date).date()
        normalized = normalized[(normalized["date"] >= start) & (normalized["date"] <= end)]
        if normalized.empty:
            return None

        if symbols:
            exact_symbols = {normalize_daily_kline_symbol(symbol) for symbol in symbols if normalize_daily_kline_symbol(symbol)}
            symbol_codes = {symbol.split(".", 1)[0] for symbol in exact_symbols}
            symbol_series = normalized["symbol"].astype(str).str.upper()
            code_series = symbol_series.str.split(".", n=1).str[0]
            normalized = normalized[symbol_series.isin(exact_symbols) | code_series.isin(symbol_codes)]
            if normalized.empty:
                return None

        normalized = normalized.drop_duplicates(["symbol", "date"], keep="last").sort_values(["date", "symbol"]).reset_index(drop=True)
        return normalized
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


def _daily_kline_files_for_range(root: Path, start_date: str, end_date: str) -> list[Path]:
    files = sorted(root.glob("*.parquet"))
    if not files:
        return []
    try:
        start_year = pd.to_datetime(start_date).year
        end_year = pd.to_datetime(end_date).year
    except Exception:
        return files
    selected: list[Path] = []
    for path in files:
        match = re.search(r"(19|20)\d{2}", path.stem)
        if not match:
            selected.append(path)
            continue
        year = int(match.group(0))
        if start_year <= year <= end_year:
            selected.append(path)
    return selected


def _load_daily_kline_slice_with_duckdb(
    *,
    files: list[Path],
    symbols: list[str],
    start_date: str,
    end_date: str,
    columns: list[str] | None = None,
) -> pd.DataFrame | None:
    if not files or not _has_module("duckdb"):
        return None
    try:
        import duckdb

        exact_symbols = sorted({
            normalize_daily_kline_symbol(symbol)
            for symbol in symbols
            if normalize_daily_kline_symbol(symbol)
        })
        symbol_codes = sorted({symbol.split(".", 1)[0] for symbol in exact_symbols})

        symbol_filters: list[str] = []
        params: list[Any] = [[str(path) for path in files], start_date, end_date]
        if exact_symbols:
            symbol_filters.append(f"__symbol_upper IN ({','.join(['?'] * len(exact_symbols))})")
            params.extend(exact_symbols)
        if symbol_codes:
            symbol_filters.append(f"__symbol_code IN ({','.join(['?'] * len(symbol_codes))})")
            params.extend(symbol_codes)

        where_symbol = f"AND ({' OR '.join(symbol_filters)})" if symbol_filters else ""
        select_list = _daily_kline_duckdb_select_list(columns)
        frame = duckdb.execute(
            f"""
            SELECT *
            FROM (
                SELECT
                    {select_list},
                    upper(trim(CAST(source."symbol" AS VARCHAR))) AS __symbol_upper,
                    regexp_replace(
                        regexp_replace(upper(trim(CAST(source."symbol" AS VARCHAR))), '^(SH|SZ|BJ)', ''),
                        '\\.(SH|SZ|BJ)$',
                        ''
                    ) AS __symbol_code,
                    CAST(source."date" AS DATE) AS __trade_date,
                    row_number() OVER (
                        PARTITION BY upper(trim(CAST(source."symbol" AS VARCHAR))), CAST(source."date" AS DATE)
                        ORDER BY CAST(source."date" AS DATE) DESC
                    ) AS __row_num
                FROM read_parquet(?, union_by_name=true) AS source
                WHERE source."symbol" IS NOT NULL
                  AND source."date" IS NOT NULL
                  AND CAST(source."date" AS DATE) >= CAST(? AS DATE)
                  AND CAST(source."date" AS DATE) <= CAST(? AS DATE)
            )
            WHERE __row_num = 1
              {where_symbol}
            ORDER BY __trade_date, __symbol_upper
            """,
            params,
        ).fetchdf()
        if frame.empty:
            return None
        helper_columns = [column for column in frame.columns if column.startswith("__")]
        if helper_columns:
            frame = frame.drop(columns=helper_columns)
        normalized = _normalize_daily_kline_frame_for_parquet(frame)
        normalized = normalized.drop_duplicates(["symbol", "date"], keep="last").sort_values(["date", "symbol"]).reset_index(drop=True)
        return normalized if not normalized.empty else None
    except Exception:
        return None


def _resolve_daily_kline_columns(files: list[Path], columns: list[str] | None) -> list[str] | None:
    if columns is None:
        return None
    requested = _unique_keep_order(["symbol", "date", *[str(column) for column in columns if str(column).strip()]])
    existing = _daily_kline_existing_columns(files)
    if existing is None:
        return requested
    selected = [column for column in requested if column in existing]
    if "symbol" not in selected or "date" not in selected:
        return None
    return selected


def _daily_kline_existing_columns(files: list[Path]) -> set[str] | None:
    cache_key = tuple(sorted(str(path.resolve()) for path in files))
    if cache_key in _DAILY_KLINE_SCHEMA_CACHE:
        return _DAILY_KLINE_SCHEMA_CACHE[cache_key]
    if not files:
        return None
    try:
        if _has_module("duckdb"):
            import duckdb

            schema = duckdb.execute(
                "DESCRIBE SELECT * FROM read_parquet(?, union_by_name=true)",
                ([str(path) for path in files],),
            ).fetchdf()
            columns = set(schema["column_name"].astype(str).tolist())
            _DAILY_KLINE_SCHEMA_CACHE[cache_key] = columns
            return columns
        if _has_module("pyarrow"):
            import pyarrow.parquet as pq

            columns: set[str] = set()
            for path in files:
                columns.update(str(name) for name in pq.read_schema(path).names)
            _DAILY_KLINE_SCHEMA_CACHE[cache_key] = columns
            return columns
    except Exception:
        return None
    return None


def _read_daily_kline_parquet_frame(path: Path, columns: list[str] | None) -> pd.DataFrame:
    if columns is None:
        return pd.read_parquet(path)
    try:
        return pd.read_parquet(path, columns=columns)
    except Exception:
        existing = _daily_kline_existing_columns([path])
        if not existing:
            return pd.DataFrame()
        available_columns = [column for column in columns if column in existing]
        if "symbol" not in available_columns or "date" not in available_columns:
            return pd.DataFrame()
        frame = pd.read_parquet(path, columns=available_columns)
        for column in columns:
            if column not in frame.columns:
                frame[column] = pd.NA
        return frame[columns]


def _daily_kline_duckdb_select_list(columns: list[str] | None) -> str:
    if not columns:
        return "source.*"
    return ",\n                    ".join(
        f"source.{_quote_duckdb_identifier(column)} AS {_quote_duckdb_identifier(column)}"
        for column in columns
    )


def _quote_duckdb_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _unique_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


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

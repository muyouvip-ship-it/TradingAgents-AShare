from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import bindparam, create_engine, text

from api.core.env import load_project_env


MINUTE_CACHE_ROOT = Path("data/artifacts/minute_cache")


@dataclass
class MinuteAggregationResult:
    timeframe: str
    trade_date: str
    items: list[dict[str, Any]]
    source: str
    missing_symbols: list[str]
    cache_path: str | None = None
    parquet_cache_path: str | None = None


def get_minute_cache_root() -> Path:
    return Path(os.getenv("MINUTE_CACHE_ROOT") or MINUTE_CACHE_ROOT)


def load_aggregated_minute_bars(
    *,
    symbols: list[str],
    trade_date: str,
    timeframe: str,
) -> MinuteAggregationResult:
    normalized_symbols = _normalize_symbols(symbols)
    frame = _try_load_minute_frame(normalized_symbols, trade_date)
    source = "postgresql:stock_minute_kline"
    if frame is None or frame.empty:
        frame = _generate_synthetic_minute_frame(normalized_symbols, trade_date)
        source = "synthetic:fallback"
    aggregated = _aggregate_minute_frame(frame, timeframe)
    missing_symbols = sorted(set(normalized_symbols) - set(aggregated["symbol"].unique())) if not aggregated.empty else normalized_symbols
    cache_paths = _write_minute_cache(aggregated, trade_date=trade_date, timeframe=timeframe, source=source)
    return MinuteAggregationResult(
        timeframe=timeframe,
        trade_date=trade_date,
        items=aggregated.to_dict("records"),
        source=source,
        missing_symbols=missing_symbols,
        cache_path=cache_paths.get("json"),
        parquet_cache_path=cache_paths.get("parquet"),
    )


def evaluate_intraday_confirmation(
    *,
    symbols: list[str],
    trade_date: str,
    timeframe: str = "30m",
) -> MinuteAggregationResult:
    result = load_aggregated_minute_bars(symbols=symbols, trade_date=trade_date, timeframe=timeframe)
    frame = pd.DataFrame(result.items)
    if frame.empty:
        result.items = []
        return result
    frame = frame.sort_values(["symbol", "bar_end"]).reset_index(drop=True)
    grouped = frame.groupby("symbol", group_keys=False)
    prev_close = grouped["close"].shift(1)
    prev_vwap = grouped["vwap"].shift(1)
    cross_above = (frame["close"] >= frame["vwap"]) & ((prev_close < prev_vwap) | prev_close.isna() | prev_vwap.isna())
    confirmation_rows = grouped.apply(lambda group: _select_confirmation_row(group, cross_above.loc[group.index], group.name)).reset_index(drop=True)
    result.items = confirmation_rows.to_dict("records") if not confirmation_rows.empty else []
    return result


def _try_load_minute_frame(symbols: list[str], trade_date: str) -> pd.DataFrame | None:
    load_project_env()
    database_url = os.getenv("DATABASE_URL")
    if not database_url or not symbols:
        return None
    try:
        engine = create_engine(database_url)
        query_symbols = sorted({variant for symbol in symbols for variant in _symbol_variants(symbol)})
        statement = text(
            """
            SELECT symbol, trade_time, open, high, low, close, volume, amount
            FROM stock_minute_kline
            WHERE symbol IN :symbols
              AND DATE(trade_time) = :trade_date
            ORDER BY symbol, trade_time
            """
        ).bindparams(bindparam("symbols", expanding=True))
        frame = pd.read_sql_query(statement, engine, params={"symbols": query_symbols, "trade_date": trade_date})
        if frame.empty:
            return None
        frame["symbol"] = frame["symbol"].map(_normalize_symbol)
        frame["trade_time"] = pd.to_datetime(frame["trade_time"])
        return frame
    except Exception:
        return None


def _generate_synthetic_minute_frame(symbols: list[str], trade_date: str) -> pd.DataFrame:
    trading_day = pd.Timestamp(trade_date).date()
    session_one = pd.date_range(f"{trading_day} 09:30:00", f"{trading_day} 11:29:00", freq="1min")
    session_two = pd.date_range(f"{trading_day} 13:00:00", f"{trading_day} 14:59:00", freq="1min")
    timeline = session_one.append(session_two)
    rows: list[dict[str, Any]] = []
    for symbol_index, symbol in enumerate(symbols):
        seed = sum(ord(ch) for ch in symbol)
        base_price = 12 + (seed % 80)
        for idx, ts in enumerate(timeline):
            drift = 1 + idx * (0.00018 + symbol_index * 0.00002)
            wave = 1 + math.sin(idx / 18 + symbol_index) * 0.0035
            close = round(base_price * drift * wave, 2)
            open_price = round(close * (0.999 + ((idx + symbol_index) % 4) * 0.0007), 2)
            high = round(max(open_price, close) * 1.0015, 2)
            low = round(min(open_price, close) * 0.9985, 2)
            volume = float(2_000 + (idx % 25) * 120 + symbol_index * 200)
            amount = round(close * volume, 2)
            rows.append(
                {
                    "symbol": symbol,
                    "trade_time": ts,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "amount": amount,
                }
            )
    return pd.DataFrame(rows)


def _aggregate_minute_frame(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "bar_start", "bar_end", "open", "high", "low", "close", "volume", "amount", "vwap"])
    rule = _to_pandas_rule(timeframe)
    data = frame.copy()
    data["trade_time"] = pd.to_datetime(data["trade_time"])
    data = data.sort_values(["symbol", "trade_time"])
    aggregated_frames: list[pd.DataFrame] = []
    for symbol, group in data.groupby("symbol"):
        group = group.set_index("trade_time")
        resampled = group.resample(rule, label="right", closed="right").agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            amount=("amount", "sum"),
        ).dropna(subset=["open", "high", "low", "close"], how="any")
        if resampled.empty:
            continue
        resampled["symbol"] = symbol
        resampled["bar_end"] = resampled.index
        resampled["bar_start"] = resampled["bar_end"] - pd.to_timedelta(rule)
        resampled["vwap"] = (resampled["amount"] / resampled["volume"].replace(0, pd.NA)).fillna(resampled["close"])
        aggregated_frames.append(resampled.reset_index(drop=True))
    if not aggregated_frames:
        return pd.DataFrame(columns=["symbol", "bar_start", "bar_end", "open", "high", "low", "close", "volume", "amount", "vwap"])
    result = pd.concat(aggregated_frames, ignore_index=True)
    return result[["symbol", "bar_start", "bar_end", "open", "high", "low", "close", "volume", "amount", "vwap"]]


def _select_confirmation_row(group: pd.DataFrame, cross_mask: pd.Series, symbol: str) -> pd.DataFrame:
    hits = group[cross_mask.fillna(False)]
    if not hits.empty:
        row = hits.iloc[[0]].copy()
        row["confirmed"] = True
    else:
        row = group.iloc[[-1]].copy()
        row["confirmed"] = False
    row["symbol"] = symbol
    return row


def _write_minute_cache(frame: pd.DataFrame, *, trade_date: str, timeframe: str, source: str) -> dict[str, str | None]:
    if frame.empty:
        return {"json": None, "parquet": None}
    cache_dir = get_minute_cache_root() / trade_date / timeframe
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{source.replace(':', '_')}.json"
    frame_to_save = frame.copy()
    frame_to_save["bar_start"] = frame_to_save["bar_start"].astype(str)
    frame_to_save["bar_end"] = frame_to_save["bar_end"].astype(str)
    frame_to_save.to_json(path, orient="records", force_ascii=False, indent=2)
    parquet_path = None
    if _has_module("pyarrow"):
        try:
            parquet_path = cache_dir / f"{source.replace(':', '_')}.parquet"
            frame.to_parquet(parquet_path, index=False)
        except Exception:
            parquet_path = None
    return {"json": str(path), "parquet": str(parquet_path) if parquet_path else None}


def _to_pandas_rule(timeframe: str) -> str:
    mapping = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min"}
    return mapping.get(timeframe, "30min")


def _normalize_symbols(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for symbol in symbols:
        normalized = _normalize_symbol(symbol)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _normalize_symbol(raw: Any) -> str:
    value = str(raw or "").strip().upper()
    if not value:
        return ""
    code = value.split(".")[0]
    if "." in value:
        return value
    if code.startswith(("6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


def _symbol_variants(symbol: str) -> set[str]:
    normalized = _normalize_symbol(symbol)
    code = normalized.split(".")[0]
    return {str(symbol or "").strip().upper(), normalized, code}


def _has_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False

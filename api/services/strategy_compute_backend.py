from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from api.services.strategy_dsl_compiler import CompiledStrategy


def compute_daily_features(frame: pd.DataFrame, compiled: CompiledStrategy) -> tuple[pd.DataFrame, str]:
    if _has_module("polars"):
        try:
            return _compute_with_polars(frame, compiled), "polars"
        except Exception:
            pass
    return _compute_with_pandas(frame, compiled), "pandas_fallback"


def _compute_with_pandas(frame: pd.DataFrame, compiled: CompiledStrategy) -> pd.DataFrame:
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"])
    for column in ["open", "high", "low", "close", "volume", "amount"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.sort_values(["symbol", "date"]).reset_index(drop=True)
    grouped = data.groupby("symbol", group_keys=False)
    data["pre_close"] = pd.to_numeric(data.get("pre_close"), errors="coerce")
    data["pre_close"] = data["pre_close"].fillna(grouped["close"].shift(1))
    data["ma5"] = grouped["close"].transform(lambda series: series.rolling(5, min_periods=1).mean())
    data["ma20"] = grouped["close"].transform(lambda series: series.rolling(20, min_periods=1).mean())
    data["ma60"] = grouped["close"].transform(lambda series: series.rolling(60, min_periods=1).mean())
    data["momentum_20d"] = grouped["close"].transform(lambda series: series.pct_change(20).fillna(0.0))
    data["momentum_60d"] = grouped["close"].transform(lambda series: series.pct_change(60).fillna(0.0))
    data["volatility_20d"] = grouped["close"].transform(lambda series: series.pct_change().rolling(20, min_periods=2).std().fillna(0.0))
    data["rsi_14"] = grouped["close"].transform(_rsi)
    data["atr_14"] = grouped.apply(_atr).reset_index(level=0, drop=True)
    amount_ma = grouped["amount"].transform(lambda series: series.rolling(20, min_periods=1).mean())
    data["money_flow_strength_20d"] = (data["amount"] / amount_ma).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    amount_std = grouped["amount"].transform(lambda series: series.rolling(20, min_periods=2).std())
    data["amount_zscore_20d"] = ((data["amount"] - amount_ma) / amount_std.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    data["net_profit_ttm"] = pd.to_numeric(data.get("net_profit_ttm"), errors="coerce").fillna(0.0)
    data["turnover_rate"] = pd.to_numeric(data.get("turnover_rate"), errors="coerce").fillna(0.0)
    data["profit_growth_proxy"] = grouped["net_profit_ttm"].transform(lambda series: series.pct_change(60).fillna(0.0))
    data["ma_gap_5_20"] = ((data["ma5"] / data["ma20"].replace(0, np.nan)) - 1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    var8a = (2 * data["close"] + data["high"] + data["low"]) / 4
    var9a = grouped["low"].transform(lambda series: series.rolling(9, min_periods=1).min())
    var10a = grouped["high"].transform(lambda series: series.rolling(9, min_periods=1).max())
    band_raw = ((var8a - var9a) / (var10a - var9a).replace(0, np.nan) * 100).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    data["first_day_band"] = grouped.apply(lambda group: band_raw.loc[group.index].ewm(span=8, adjust=False).mean()).reset_index(level=0, drop=True)
    b1_source = grouped["first_day_band"].shift(1) * 0.667 + data["first_day_band"] * 0.333
    data["first_day_band_b1"] = grouped.apply(lambda group: b1_source.loc[group.index].ewm(span=2, adjust=False).mean()).reset_index(level=0, drop=True)
    previous_band = grouped["first_day_band"].shift(1)
    previous_b1 = grouped["first_day_band_b1"].shift(1)
    data["first_day_band_cross"] = (
        (data["first_day_band"] > data["first_day_band_b1"])
        & (previous_band <= previous_b1)
    ).fillna(False).astype(float)
    data["first_day_band_dead_cross"] = (
        (data["first_day_band"] < data["first_day_band_b1"])
        & (previous_band >= previous_b1)
    ).fillna(False).astype(float)
    data["momentum_rank_pct"] = data.groupby("date")["momentum_60d"].rank(pct=True).fillna(0.5)
    data["money_flow_rank_pct"] = data.groupby("date")["money_flow_strength_20d"].rank(pct=True).fillna(0.5)
    data["profit_growth_rank_pct"] = data.groupby("date")["profit_growth_proxy"].rank(pct=True).fillna(0.5)
    vol_rank = data.groupby("date")["volatility_20d"].rank(pct=True).fillna(0.5)
    data["volatility_rank_inverse"] = 1 - vol_rank
    data = _attach_weekly_features(data)
    data = _apply_compiled_factor_scores(data, compiled)
    return data.sort_values(["date", "symbol"]).reset_index(drop=True)


def _compute_with_polars(frame: pd.DataFrame, compiled: CompiledStrategy) -> pd.DataFrame:
    import polars as pl

    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"])
    pl_df = pl.from_pandas(data).sort(["symbol", "date"])
    close_shift = pl.col("close").shift(1).over("symbol")
    amount_mean_20 = pl.col("amount").rolling_mean(window_size=20, min_samples=1).over("symbol")
    net_profit_growth = pl.col("net_profit_ttm").pct_change(60).over("symbol").fill_null(0.0)
    returns_1d = pl.col("close").pct_change().over("symbol")

    pl_df = pl_df.with_columns(
        [
            pl.col("pre_close").fill_null(close_shift).alias("pre_close"),
            pl.col("close").rolling_mean(window_size=5, min_samples=1).over("symbol").alias("ma5"),
            pl.col("close").rolling_mean(window_size=20, min_samples=1).over("symbol").alias("ma20"),
            pl.col("close").rolling_mean(window_size=60, min_samples=1).over("symbol").alias("ma60"),
            pl.col("close").pct_change(20).over("symbol").fill_null(0.0).alias("momentum_20d"),
            pl.col("close").pct_change(60).over("symbol").fill_null(0.0).alias("momentum_60d"),
            returns_1d.rolling_std(window_size=20, min_samples=2).over("symbol").fill_null(0.0).alias("volatility_20d"),
            _polars_rsi_expr().alias("rsi_14"),
            _polars_atr_expr().alias("atr_14"),
            (pl.col("amount") / amount_mean_20).fill_nan(1.0).fill_null(1.0).alias("money_flow_strength_20d"),
            ((pl.col("amount") - amount_mean_20) / pl.col("amount").rolling_std(window_size=20, min_samples=2).over("symbol"))
                .fill_nan(0.0).fill_null(0.0).alias("amount_zscore_20d"),
            pl.col("net_profit_ttm").fill_null(0.0).alias("net_profit_ttm"),
            pl.col("turnover_rate").fill_null(0.0).alias("turnover_rate"),
            net_profit_growth.alias("profit_growth_proxy"),
        ]
    )
    band_seed = (
        ((((pl.col("close") * 2) + pl.col("high") + pl.col("low")) / 4) - pl.col("low").rolling_min(window_size=9, min_samples=1).over("symbol"))
        / (
            pl.col("high").rolling_max(window_size=9, min_samples=1).over("symbol")
            - pl.col("low").rolling_min(window_size=9, min_samples=1).over("symbol")
        ).replace(0, None)
        * 100
    ).fill_nan(0.0).fill_null(0.0)
    first_day_band = band_seed.ewm_mean(span=8, adjust=False).over("symbol").fill_null(0.0)
    first_day_band_b1_seed = (first_day_band.shift(1).over("symbol") * 0.667 + first_day_band * 0.333).fill_null(first_day_band)
    pl_df = pl_df.with_columns(
        [
            ((pl.col("ma5") / pl.col("ma20")) - 1).fill_nan(0.0).fill_null(0.0).alias("ma_gap_5_20"),
            first_day_band.alias("first_day_band"),
            first_day_band_b1_seed.ewm_mean(span=2, adjust=False).over("symbol").fill_null(0.0).alias("first_day_band_b1"),
            pl.col("momentum_60d").rank("average").over("date").truediv(pl.len().over("date")).fill_null(0.5).alias("momentum_rank_pct"),
            pl.col("money_flow_strength_20d").rank("average").over("date").truediv(pl.len().over("date")).fill_null(0.5).alias("money_flow_rank_pct"),
            pl.col("profit_growth_proxy").rank("average").over("date").truediv(pl.len().over("date")).fill_null(0.5).alias("profit_growth_rank_pct"),
            (1 - pl.col("volatility_20d").rank("average").over("date").truediv(pl.len().over("date"))).fill_null(0.5).alias("volatility_rank_inverse"),
        ]
    )
    pl_df = pl_df.with_columns(
        [
            (
                (pl.col("first_day_band") > pl.col("first_day_band_b1"))
                & (
                    pl.col("first_day_band").shift(1).over("symbol")
                    <= pl.col("first_day_band_b1").shift(1).over("symbol")
                )
            ).cast(pl.Float64).fill_null(0.0).alias("first_day_band_cross"),
            (
                (pl.col("first_day_band") < pl.col("first_day_band_b1"))
                & (
                    pl.col("first_day_band").shift(1).over("symbol")
                    >= pl.col("first_day_band_b1").shift(1).over("symbol")
                )
            ).cast(pl.Float64).fill_null(0.0).alias("first_day_band_dead_cross"),
        ]
    )
    data = pl_df.to_pandas()
    data = _attach_weekly_features(data)
    data = _apply_compiled_factor_scores(data, compiled)
    return data.sort_values(["date", "symbol"]).reset_index(drop=True)


def _apply_compiled_factor_scores(data: pd.DataFrame, compiled: CompiledStrategy) -> pd.DataFrame:
    score_components: list[pd.Series] = []
    total_weight = 0.0
    for factor in compiled.factor_definitions:
        source_column = str(factor.get("source_column") or factor.get("name") or "")
        if source_column not in data.columns:
            data[source_column] = 0.0
        raw = pd.to_numeric(data[source_column], errors="coerce").fillna(0.0)
        transform = str(factor.get("transform") or "rank_pct")
        direction = str(factor.get("direction") or "higher_better")
        if transform == "rank_pct":
            ranked = data.assign(_value=raw).groupby("date")["_value"].rank(pct=True).fillna(0.5)
            signal = 1 - ranked if direction == "lower_better" else ranked
        elif transform == "zscore":
            mean = data.assign(_value=raw).groupby("date")["_value"].transform("mean")
            std = data.assign(_value=raw).groupby("date")["_value"].transform("std").replace(0, np.nan)
            signal = ((raw - mean) / std).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            if direction == "lower_better":
                signal = -signal
        else:
            signal = raw
            if direction == "lower_better":
                signal = -signal
        factor_name = str(factor.get("name") or source_column)
        data[f"{factor_name}_signal"] = signal
        weight = float(factor.get("weight") or 0.0)
        if weight > 0:
            total_weight += weight
            score_components.append(signal * weight)
    if score_components and total_weight > 0:
        data["factor_score"] = pd.to_numeric(sum(score_components) / total_weight, errors="coerce").fillna(0.0)
    else:
        data["factor_score"] = 0.0
    return data


def _attach_weekly_features(data: pd.DataFrame) -> pd.DataFrame:
    weekly_frames: list[pd.DataFrame] = []
    for symbol, group in data.groupby("symbol"):
        weekly = group.set_index("date").resample("W-FRI").agg(
            weekly_open=("open", "first"),
            weekly_high=("high", "max"),
            weekly_low=("low", "min"),
            weekly_close=("close", "last"),
            weekly_volume=("volume", "sum"),
        ).dropna(subset=["weekly_close"], how="any")
        if weekly.empty:
            continue
        weekly["weekly_ma20"] = weekly["weekly_close"].rolling(20, min_periods=1).mean()
        weekly["week_end"] = weekly.index
        weekly["symbol"] = symbol
        weekly_frames.append(weekly.reset_index(drop=True))
    if not weekly_frames:
        data["weekly_close"] = data["close"]
        data["weekly_ma20"] = data["ma20"]
        data["weekly_trend_pass"] = data["close"] > data["ma20"]
        return data
    weekly_frame = pd.concat(weekly_frames, ignore_index=True)
    weekly_frame["week_end"] = pd.to_datetime(weekly_frame["week_end"])
    merged = data.copy()
    merged["week_end"] = merged["date"] + pd.offsets.Week(weekday=4)
    merged = merged.merge(
        weekly_frame[["symbol", "week_end", "weekly_close", "weekly_ma20"]],
        on=["symbol", "week_end"],
        how="left",
    )
    merged["weekly_close"] = merged["weekly_close"].fillna(merged["close"])
    merged["weekly_ma20"] = merged["weekly_ma20"].fillna(merged["ma20"])
    merged["weekly_trend_pass"] = merged["weekly_close"] >= merged["weekly_ma20"]
    return merged.drop(columns=["week_end"])


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period, min_periods=1).mean()
    loss = (-delta.clip(upper=0)).rolling(period, min_periods=1).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def _atr(group: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = group["high"] - group["low"]
    high_close = (group["high"] - group["close"].shift()).abs()
    low_close = (group["low"] - group["close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.rolling(period, min_periods=1).mean()


def _polars_rsi_expr():
    import polars as pl

    delta = pl.col("close").diff().over("symbol")
    gain = pl.when(delta > 0).then(delta).otherwise(0.0).rolling_mean(window_size=14, min_samples=1).over("symbol")
    loss = pl.when(delta < 0).then(-delta).otherwise(0.0).rolling_mean(window_size=14, min_samples=1).over("symbol")
    rs = gain / loss.replace(0, None)
    return (100 - 100 / (1 + rs)).fill_null(50.0)


def _polars_atr_expr():
    import polars as pl

    high_low = pl.col("high") - pl.col("low")
    high_close = (pl.col("high") - pl.col("close").shift(1).over("symbol")).abs()
    low_close = (pl.col("low") - pl.col("close").shift(1).over("symbol")).abs()
    true_range = pl.max_horizontal(high_low, high_close, low_close)
    return true_range.rolling_mean(window_size=14, min_samples=1).over("symbol")


def _has_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False

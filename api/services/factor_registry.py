from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from api.models.strategy_models import FactorDB


FACTOR_REGISTRY: dict[str, dict[str, Any]] = {
    "net_profit_growth_yoy": {
        "name": "net_profit_growth_yoy",
        "display_name": "净利润同比增速",
        "category": "growth",
        "description": "基于净利润 TTM 的同比增长代理，适合业绩高增筛选。",
        "formula": "net_profit_ttm.pct_change(60)",
        "source_column": "profit_growth_proxy",
        "required_fields": ["net_profit_ttm"],
        "transforms_supported": ["rank_pct", "raw", "zscore"],
        "default_transform": "rank_pct",
        "default_direction": "higher_better",
        "window": 60,
        "rank_scope": "cross_section:date",
        "backend_support": ["polars", "duckdb", "pandas_fallback"],
        "timeframes": ["1d"],
        "tags": ["业绩", "成长"],
        "polars_expr": "pl.col('net_profit_ttm').pct_change(60).over('symbol')",
        "duckdb_sql": "net_profit_ttm / lag(net_profit_ttm, 60) over(partition by symbol order by date) - 1",
    },
    "profit_growth_proxy": {
        "name": "profit_growth_proxy",
        "display_name": "利润增速代理",
        "category": "growth",
        "description": "净利润增速的兼容代理字段。",
        "formula": "net_profit_ttm.pct_change(60)",
        "source_column": "profit_growth_proxy",
        "required_fields": ["net_profit_ttm"],
        "transforms_supported": ["rank_pct", "raw", "zscore"],
        "default_transform": "rank_pct",
        "default_direction": "higher_better",
        "window": 60,
        "rank_scope": "cross_section:date",
        "backend_support": ["polars", "duckdb", "pandas_fallback"],
        "timeframes": ["1d"],
        "tags": ["业绩", "成长"],
        "polars_expr": "pl.col('net_profit_ttm').pct_change(60).over('symbol')",
        "duckdb_sql": "net_profit_ttm / lag(net_profit_ttm, 60) over(partition by symbol order by date) - 1",
    },
    "money_flow_strength_20d": {
        "name": "money_flow_strength_20d",
        "display_name": "20日资金强度",
        "category": "flow",
        "description": "近 20 日成交额相对均值的放大程度，用于识别资金关注度。",
        "formula": "amount / rolling_mean(amount, 20)",
        "source_column": "money_flow_strength_20d",
        "required_fields": ["amount"],
        "transforms_supported": ["rank_pct", "raw", "zscore"],
        "default_transform": "rank_pct",
        "default_direction": "higher_better",
        "window": 20,
        "rank_scope": "cross_section:date",
        "backend_support": ["polars", "duckdb", "pandas_fallback"],
        "timeframes": ["1d"],
        "tags": ["资金流", "活跃度"],
        "polars_expr": "pl.col('amount') / pl.col('amount').rolling_mean(20).over('symbol')",
        "duckdb_sql": "amount / avg(amount) over(partition by symbol order by date rows between 19 preceding and current row)",
    },
    "momentum_20d": {
        "name": "momentum_20d",
        "display_name": "20日动量",
        "category": "momentum",
        "description": "20 日价格涨幅，适合趋势和波段择时。",
        "formula": "close.pct_change(20)",
        "source_column": "momentum_20d",
        "required_fields": ["close"],
        "transforms_supported": ["rank_pct", "raw", "zscore"],
        "default_transform": "rank_pct",
        "default_direction": "higher_better",
        "window": 20,
        "rank_scope": "cross_section:date",
        "backend_support": ["polars", "duckdb", "pandas_fallback"],
        "timeframes": ["1d", "1w"],
        "tags": ["动量", "趋势"],
        "polars_expr": "pl.col('close').pct_change(20).over('symbol')",
        "duckdb_sql": "close / lag(close, 20) over(partition by symbol order by date) - 1",
    },
    "momentum_60d": {
        "name": "momentum_60d",
        "display_name": "60日动量",
        "category": "momentum",
        "description": "60 日价格涨幅，用于中期趋势强度判别。",
        "formula": "close.pct_change(60)",
        "source_column": "momentum_60d",
        "required_fields": ["close"],
        "transforms_supported": ["rank_pct", "raw", "zscore"],
        "default_transform": "rank_pct",
        "default_direction": "higher_better",
        "window": 60,
        "rank_scope": "cross_section:date",
        "backend_support": ["polars", "duckdb", "pandas_fallback"],
        "timeframes": ["1d", "1w"],
        "tags": ["动量", "趋势"],
        "polars_expr": "pl.col('close').pct_change(60).over('symbol')",
        "duckdb_sql": "close / lag(close, 60) over(partition by symbol order by date) - 1",
    },
    "volatility_20d": {
        "name": "volatility_20d",
        "display_name": "20日波动率",
        "category": "risk",
        "description": "20 日收益率波动率，用于风险约束与低波筛选。",
        "formula": "rolling_std(close.pct_change(), 20)",
        "source_column": "volatility_20d",
        "required_fields": ["close"],
        "transforms_supported": ["rank_pct", "raw", "zscore"],
        "default_transform": "rank_pct",
        "default_direction": "lower_better",
        "window": 20,
        "rank_scope": "cross_section:date",
        "backend_support": ["polars", "duckdb", "pandas_fallback"],
        "timeframes": ["1d"],
        "tags": ["风险", "低波"],
        "polars_expr": "pl.col('close').pct_change().rolling_std(20).over('symbol')",
        "duckdb_sql": "stddev_samp(close / lag(close) over(partition by symbol order by date) - 1) over(partition by symbol order by date rows between 19 preceding and current row)",
    },
    "rsi_14": {
        "name": "rsi_14",
        "display_name": "RSI14",
        "category": "indicator",
        "description": "14 周期 RSI，相对强弱指标。",
        "formula": "rsi(close, 14)",
        "source_column": "rsi_14",
        "required_fields": ["close"],
        "transforms_supported": ["raw", "rank_pct"],
        "default_transform": "raw",
        "default_direction": "higher_better",
        "window": 14,
        "rank_scope": "symbol_series",
        "backend_support": ["polars", "duckdb", "pandas_fallback"],
        "timeframes": ["1d", "30m"],
        "tags": ["指标", "超买超卖"],
        "polars_expr": "rsi(close, 14)",
        "duckdb_sql": "custom_udf_rsi(close, 14)",
    },
    "atr_14": {
        "name": "atr_14",
        "display_name": "ATR14",
        "category": "risk",
        "description": "14 周期 ATR，用于波动止损与仓位预算。",
        "formula": "atr(high, low, close, 14)",
        "source_column": "atr_14",
        "required_fields": ["high", "low", "close"],
        "transforms_supported": ["raw", "rank_pct"],
        "default_transform": "raw",
        "default_direction": "lower_better",
        "window": 14,
        "rank_scope": "symbol_series",
        "backend_support": ["polars", "duckdb", "pandas_fallback"],
        "timeframes": ["1d"],
        "tags": ["风险", "止损"],
        "polars_expr": "atr(high, low, close, 14)",
        "duckdb_sql": "custom_udf_atr(high, low, close, 14)",
    },
    "float_market_cap": {
        "name": "float_market_cap",
        "display_name": "流通市值",
        "category": "size",
        "description": "流通市值，适合中盘/小盘/大盘过滤。",
        "formula": "float_market_cap",
        "source_column": "float_market_cap",
        "required_fields": ["float_market_cap"],
        "transforms_supported": ["raw", "rank_pct"],
        "default_transform": "raw",
        "default_direction": "lower_better",
        "window": None,
        "rank_scope": "cross_section:date",
        "backend_support": ["polars", "duckdb", "pandas_fallback"],
        "timeframes": ["1d"],
        "tags": ["市值", "过滤"],
        "polars_expr": "pl.col('float_market_cap')",
        "duckdb_sql": "float_market_cap",
    },
    "turnover_rate": {
        "name": "turnover_rate",
        "display_name": "换手率",
        "category": "liquidity",
        "description": "换手率，反映活跃程度和流动性。",
        "formula": "turnover_rate",
        "source_column": "turnover_rate",
        "required_fields": ["turnover_rate"],
        "transforms_supported": ["raw", "rank_pct", "zscore"],
        "default_transform": "rank_pct",
        "default_direction": "higher_better",
        "window": None,
        "rank_scope": "cross_section:date",
        "backend_support": ["polars", "duckdb", "pandas_fallback"],
        "timeframes": ["1d"],
        "tags": ["流动性", "活跃度"],
        "polars_expr": "pl.col('turnover_rate')",
        "duckdb_sql": "turnover_rate",
    },
    "ma_gap_5_20": {
        "name": "ma_gap_5_20",
        "display_name": "5/20 均线乖离",
        "category": "momentum",
        "description": "5 日均线相对 20 日均线的乖离率。",
        "formula": "ma(close, 5) / ma(close, 20) - 1",
        "source_column": "ma_gap_5_20",
        "required_fields": ["close"],
        "transforms_supported": ["raw", "rank_pct", "zscore"],
        "default_transform": "raw",
        "default_direction": "higher_better",
        "window": 20,
        "rank_scope": "symbol_series",
        "backend_support": ["polars", "duckdb", "pandas_fallback"],
        "timeframes": ["1d"],
        "tags": ["均线", "趋势"],
        "polars_expr": "(pl.col('close').rolling_mean(5).over('symbol') / pl.col('close').rolling_mean(20).over('symbol')) - 1",
        "duckdb_sql": "(avg(close) over(partition by symbol order by date rows between 4 preceding and current row) / avg(close) over(partition by symbol order by date rows between 19 preceding and current row)) - 1",
    },
    "amount_zscore_20d": {
        "name": "amount_zscore_20d",
        "display_name": "20日成交额 ZScore",
        "category": "flow",
        "description": "成交额相对 20 日均值的标准化偏离，适合爆量识别。",
        "formula": "(amount - mean_20) / std_20",
        "source_column": "amount_zscore_20d",
        "required_fields": ["amount"],
        "transforms_supported": ["zscore", "raw", "rank_pct"],
        "default_transform": "zscore",
        "default_direction": "higher_better",
        "window": 20,
        "rank_scope": "symbol_series",
        "backend_support": ["polars", "duckdb", "pandas_fallback"],
        "timeframes": ["1d"],
        "tags": ["资金流", "放量"],
        "polars_expr": "(pl.col('amount') - pl.col('amount').rolling_mean(20).over('symbol')) / pl.col('amount').rolling_std(20).over('symbol')",
        "duckdb_sql": "(amount - avg(amount) over(partition by symbol order by date rows between 19 preceding and current row)) / nullif(stddev_samp(amount) over(partition by symbol order by date rows between 19 preceding and current row), 0)",
    },
    "first_day_band_cross": {
        "name": "first_day_band_cross",
        "display_name": "首日波段金叉",
        "category": "indicator",
        "description": "由同花顺波段公式改写：VAR8A=(2*C+H+L)/4，9日高低区间归一化后 EMA8 得到波段线，B1=EMA(0.667*REF(波段,1)+0.333*波段,2)，取 CROSS(波段,B1) 首日信号。",
        "formula": "CROSS(EMA(((2*close+high+low)/4-LLV(low,9))/(HHV(high,9)-LLV(low,9))*100,8), EMA(0.667*REF(band,1)+0.333*band,2))",
        "source_column": "first_day_band_cross",
        "required_fields": ["close", "high", "low"],
        "transforms_supported": ["raw", "rank_pct"],
        "default_transform": "raw",
        "default_direction": "higher_better",
        "window": 11,
        "rank_scope": "symbol_series",
        "backend_support": ["polars", "duckdb", "pandas_fallback"],
        "timeframes": ["1d"],
        "tags": ["同花顺", "波段", "金叉", "首日"],
        "polars_expr": "band_cross := cross_above(ema((((2*close+high+low)/4 - rolling_min(low,9)) / nullif(rolling_max(high,9)-rolling_min(low,9),0)) * 100, 8), ema(0.667*lag(band,1)+0.333*band, 2))",
        "duckdb_sql": "case when band > b1 and lag(band) over(partition by symbol order by date) <= lag(b1) over(partition by symbol order by date) then 1 else 0 end",
    },
}


def sync_factor_registry(db: Session) -> None:
    existing = {row.name: row for row in db.query(FactorDB).all()}
    for name, meta in FACTOR_REGISTRY.items():
        row = existing.get(name)
        if row is None:
            row = FactorDB(name=name)
            db.add(row)
        row.category = str(meta.get("category") or "custom")
        row.formula = str(meta.get("formula") or "")
        row.parameters = _factor_params(meta)
        row.is_active = True
        if row.current_weight is None:
            row.current_weight = 0.0
    db.commit()


def list_factor_registry(db: Session, *, active_only: bool = True) -> list[dict[str, Any]]:
    sync_factor_registry(db)
    query = db.query(FactorDB).order_by(FactorDB.category.asc(), FactorDB.name.asc())
    if active_only:
        query = query.filter(FactorDB.is_active.is_(True))
    return [_factor_to_payload(row) for row in query.all()]


def get_factor_registry_item(db: Session, name: str) -> dict[str, Any] | None:
    sync_factor_registry(db)
    row = db.query(FactorDB).filter(FactorDB.name == name).first()
    if row is None:
        return None
    return _factor_to_payload(row)


def get_factor_catalog_definition(name: str) -> dict[str, Any] | None:
    item = FACTOR_REGISTRY.get(name)
    return deepcopy(item) if item is not None else None


def _factor_params(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "display_name": meta.get("display_name"),
        "description": meta.get("description"),
        "source_column": meta.get("source_column"),
        "required_fields": list(meta.get("required_fields") or []),
        "transforms_supported": list(meta.get("transforms_supported") or []),
        "default_transform": meta.get("default_transform"),
        "default_direction": meta.get("default_direction"),
        "window": meta.get("window"),
        "rank_scope": meta.get("rank_scope"),
        "backend_support": list(meta.get("backend_support") or []),
        "timeframes": list(meta.get("timeframes") or []),
        "tags": list(meta.get("tags") or []),
        "polars_expr": meta.get("polars_expr"),
        "duckdb_sql": meta.get("duckdb_sql"),
    }


def _factor_to_payload(row: FactorDB) -> dict[str, Any]:
    params = deepcopy(row.parameters or {})
    return {
        "id": row.id,
        "name": row.name,
        "display_name": params.get("display_name") or row.name,
        "category": row.category,
        "description": params.get("description"),
        "formula": row.formula,
        "source_column": params.get("source_column"),
        "required_fields": list(params.get("required_fields") or []),
        "transforms_supported": list(params.get("transforms_supported") or []),
        "default_transform": params.get("default_transform"),
        "default_direction": params.get("default_direction"),
        "window": params.get("window"),
        "rank_scope": params.get("rank_scope"),
        "backend_support": list(params.get("backend_support") or []),
        "timeframes": list(params.get("timeframes") or []),
        "tags": list(params.get("tags") or []),
        "is_active": bool(row.is_active),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }

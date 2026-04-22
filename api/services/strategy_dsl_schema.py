from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictDslModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UniverseFilter(StrictDslModel):
    field: str
    op: Literal["between", "gt", "gte", "lt", "lte", "eq", "in", "not_in", "prefix_any"]
    value: Any
    unit: str | None = None


class UniverseConfig(StrictDslModel):
    market: Literal["A_SHARE"] = "A_SHARE"
    include_concepts: list[str] = Field(default_factory=list)
    exclude_st: bool = True
    exclude_suspended: bool = True
    min_listing_days: int | None = Field(default=None, ge=0)
    filters: list[UniverseFilter] = Field(default_factory=list)


class FactorConfig(StrictDslModel):
    name: str
    weight: float = Field(default=1.0, ge=0)
    direction: Literal["higher_better", "lower_better"] = "higher_better"
    transform: Literal["rank_pct", "zscore", "raw"] = "rank_pct"
    timeframe: str | None = None


class FactorSelect(StrictDslModel):
    top_n: int = Field(default=30, ge=1)
    min_score: float = Field(default=0.6, ge=0, le=1)


class FactorModelConfig(StrictDslModel):
    engine: Literal["polars_expr", "pandas_fallback"] | None = "polars_expr"
    score_method: Literal["weighted_sum"] = "weighted_sum"
    rebalance_frequency: Literal["daily", "weekly", "monthly"] = "weekly"
    factors: list[FactorConfig] = Field(default_factory=list)
    select: FactorSelect = Field(default_factory=FactorSelect)


class IntradaySubCondition(StrictDslModel):
    type: Literal["cross_above", "cross_below", "above", "below"]
    left: str
    right: str


class EntryCondition(StrictDslModel):
    type: Literal["trend", "alligator_opening", "breakout", "intraday_confirm", "cross_above", "atr_filter"]
    timeframe: str = "1d"
    field: str | None = None
    op: str | None = None
    indicator: str | None = None
    params: dict[str, Any] | None = None
    direction: Literal["bullish", "bearish"] | None = None
    lookback: int | None = Field(default=None, ge=1)
    conditions: list[IntradaySubCondition] | None = None
    left: str | None = None
    right: str | None = None
    max_rank_pct: float | None = Field(default=None, ge=0, le=1)


class ExitCondition(StrictDslModel):
    type: Literal["cross_below", "atr_trailing_stop", "factor_rank_drop"]
    timeframe: str = "1d"
    left: str | None = None
    right: str | None = None
    atr_period: int | None = Field(default=None, ge=1)
    atr_multiple: float | None = Field(default=None, gt=0)
    rank_below: float | None = Field(default=None, ge=0, le=1)


class EntryBlock(StrictDslModel):
    logic: Literal["all", "any"] = "all"
    conditions: list[EntryCondition] = Field(default_factory=list)


class ExitBlock(StrictDslModel):
    logic: Literal["all", "any"] = "any"
    conditions: list[ExitCondition] = Field(default_factory=list)


class PositionConfig(StrictDslModel):
    method: Literal["equal_weight", "factor_weight", "risk_budget", "volatility_target"] = "risk_budget"
    initial_position_pct: float | None = Field(default=None, ge=0, le=1)
    max_position_pct: float | None = Field(default=None, ge=0, le=1)
    max_single_position_pct: float | None = Field(default=None, ge=0, le=1)
    max_industry_position_pct: float | None = Field(default=None, ge=0, le=1)
    cash_reserve_pct: float | None = Field(default=None, ge=0, le=1)
    risk_per_trade_pct: float | None = Field(default=None, ge=0, le=1)
    sizing_basis: Literal["atr", "equal", "factor_score"] | None = None
    target_volatility_pct: float | None = Field(default=None, ge=0, le=1)
    pyramid_enabled: bool = False
    pyramid_max_adds: int | None = Field(default=None, ge=0, le=10)
    pyramid_trigger_pct: float | None = Field(default=None, ge=0, le=1)
    pyramid_scale_pct: float | None = Field(default=None, ge=0, le=1)


class RiskConfig(StrictDslModel):
    stop_loss_pct: float | None = Field(default=None, ge=0, le=1)
    take_profit_pct: float | None = Field(default=None, ge=0, le=5)
    trailing_stop_pct: float | None = Field(default=None, ge=0, le=1)
    max_drawdown_pct: float | None = Field(default=None, ge=0, le=1)
    max_daily_loss_pct: float | None = Field(default=None, ge=0, le=1)
    max_positions: int | None = Field(default=None, ge=1)
    cooldown_days_after_stop: int | None = Field(default=None, ge=0)


class DataEngineConfig(StrictDslModel):
    filter: Literal["duckdb", "sqlalchemy_fallback"] = "duckdb"
    factor_compute: Literal["polars", "pandas_fallback"] = "polars"


class MinuteLoadingConfig(StrictDslModel):
    mode: Literal["lazy_by_watchlist", "manual_requested"] = "lazy_by_watchlist"
    forbid_full_market_preload: bool = True
    missing_data_policy: Literal["skip", "fallback"] | None = "skip"
    execution_granularity: Literal["daily", "minute"] | None = "minute"
    confirm_timeframes: list[str] = Field(default_factory=list)


class SlippageModel(StrictDslModel):
    type: Literal["bps", "fixed"] = "bps"
    value: float = Field(default=10, ge=0)


class ExecutionConfig(StrictDslModel):
    market: Literal["A_SHARE"] = "A_SHARE"
    signal_timing: Literal["close"] = "close"
    fill_timing: Literal["next_open"] = "next_open"
    price_mode: Literal["open", "close", "vwap"] = "open"
    lot_size: int = Field(default=100, ge=1)
    tick_size: float = Field(default=0.01, gt=0)
    commission_rate: float | None = Field(default=None, ge=0, le=0.1)
    min_commission: float | None = Field(default=None, ge=0)
    stamp_duty_rate: float | None = Field(default=None, ge=0, le=0.1)
    slippage_model: SlippageModel | None = None
    volume_limit_pct: float | None = Field(default=None, ge=0, le=1)
    data_engine: DataEngineConfig = Field(default_factory=DataEngineConfig)
    minute_loading: MinuteLoadingConfig = Field(default_factory=MinuteLoadingConfig)


class EvolutionConfig(StrictDslModel):
    enabled: bool = False
    allowed_mutations: list[str] = Field(default_factory=list)
    objective: str | None = None
    max_complexity_score: int | None = Field(default=None, ge=1)
    require_user_confirmation: bool = True
    method: str | None = None
    ml_backend: Literal["scikit-learn", "lightgbm"] | None = None


class StrategyDslSchema(StrictDslModel):
    schema_version: str = "1.0"
    strategy_type: Literal["selection", "trading", "risk", "portfolio"]
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    factor_model: FactorModelConfig = Field(default_factory=FactorModelConfig)
    entry: EntryBlock = Field(default_factory=EntryBlock)
    exit: ExitBlock = Field(default_factory=ExitBlock)
    position: PositionConfig = Field(default_factory=PositionConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    evolution: EvolutionConfig = Field(default_factory=EvolutionConfig)

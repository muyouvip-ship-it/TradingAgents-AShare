from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AShareMarketRule:
    market: str
    board: str
    lot_size: int
    tick_size: float
    t_plus: int
    daily_limit_pct: float
    st_daily_limit_pct: float
    stamp_duty_side: str
    sell_allows_odd_lot: bool


DEFAULT_A_SHARE_RULE = AShareMarketRule(
    market="A_SHARE",
    board="main",
    lot_size=100,
    tick_size=0.01,
    t_plus=1,
    daily_limit_pct=0.10,
    st_daily_limit_pct=0.05,
    stamp_duty_side="sell",
    sell_allows_odd_lot=True,
)


BOARD_RULES: dict[str, AShareMarketRule] = {
    "main": DEFAULT_A_SHARE_RULE,
    "chinext": AShareMarketRule(
        market="A_SHARE",
        board="chinext",
        lot_size=100,
        tick_size=0.01,
        t_plus=1,
        daily_limit_pct=0.20,
        st_daily_limit_pct=0.05,
        stamp_duty_side="sell",
        sell_allows_odd_lot=True,
    ),
    "star": AShareMarketRule(
        market="A_SHARE",
        board="star",
        lot_size=100,
        tick_size=0.01,
        t_plus=1,
        daily_limit_pct=0.20,
        st_daily_limit_pct=0.05,
        stamp_duty_side="sell",
        sell_allows_odd_lot=True,
    ),
    "bse": AShareMarketRule(
        market="A_SHARE",
        board="bse",
        lot_size=100,
        tick_size=0.01,
        t_plus=1,
        daily_limit_pct=0.30,
        st_daily_limit_pct=0.05,
        stamp_duty_side="sell",
        sell_allows_odd_lot=True,
    ),
}


def resolve_a_share_board(symbol: str) -> str:
    code = str(symbol or "").split(".")[0]
    if code.startswith(("300", "301")):
        return "chinext"
    if code.startswith(("688", "689")):
        return "star"
    if code.startswith(("8", "4", "9")):
        return "bse"
    return "main"


def get_a_share_market_rule(symbol: str, *, is_st: bool = False, overrides: dict[str, Any] | None = None) -> AShareMarketRule:
    base = BOARD_RULES.get(resolve_a_share_board(symbol), DEFAULT_A_SHARE_RULE)
    daily_limit_pct = base.st_daily_limit_pct if is_st else base.daily_limit_pct
    if not overrides:
        return AShareMarketRule(**{**base.__dict__, "daily_limit_pct": daily_limit_pct})
    payload = {**base.__dict__, "daily_limit_pct": daily_limit_pct}
    for key in (
        "lot_size",
        "tick_size",
        "t_plus",
        "daily_limit_pct",
        "st_daily_limit_pct",
        "stamp_duty_side",
        "sell_allows_odd_lot",
    ):
        if key in overrides and overrides[key] is not None:
            payload[key] = overrides[key]
    return AShareMarketRule(**payload)


def round_to_tick(price: float, tick_size: float = 0.01) -> float:
    tick = tick_size if tick_size > 0 else 0.01
    return round(round(float(price) / tick) * tick, 4)

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class PortfolioOverviewResponse(BaseModel):
    total_market_value: float = 0.0


class WatchlistAddRequest(BaseModel):
    symbol: str = Field(default="")


class ScheduledBatchIdsRequest(BaseModel):
    ids: List[str]


class ScheduledBatchUpdateRequest(BaseModel):
    ids: List[str]
    status: Optional[str] = None


class PortfolioPositionItem(BaseModel):
    symbol: str
    name: Optional[str] = None
    current_position: Optional[float] = None
    available_position: Optional[float] = None
    average_cost: Optional[float] = None
    market_value: Optional[float] = None
    current_position_pct: Optional[float] = None


class PortfolioImportSyncRequest(BaseModel):
    positions: List[PortfolioPositionItem]
    source: str = "manual"
    auto_apply_scheduled: bool = True

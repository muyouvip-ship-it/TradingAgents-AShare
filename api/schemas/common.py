from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_serializer

from api.core.datetime_utils import serialize_datetime_utc


class UserContextInput(BaseModel):
    objective: Optional[str] = Field(None, description="用户目标动作，如建仓/加仓/减仓/止损/观察")
    risk_profile: Optional[str] = Field(None, description="风险偏好，如保守/平衡/激进")
    investment_horizon: Optional[str] = Field(None, description="持有周期，如短线/波段/中线")
    cash_available: Optional[float] = Field(None, description="可用资金")
    current_position: Optional[float] = Field(None, description="当前持仓数量")
    current_position_pct: Optional[float] = Field(None, description="当前仓位占比")
    average_cost: Optional[float] = Field(None, description="当前持仓成本")
    max_loss_pct: Optional[float] = Field(None, description="最大容忍亏损百分比")
    constraints: List[str] = Field(default_factory=list, description="用户的硬约束列表")
    user_notes: Optional[str] = Field(None, description="用户补充说明")


class AnalyzeResponse(BaseModel):
    pass


class BatchScheduledTriggerJob(BaseModel):
    pass


class BatchScheduledTriggerResponse(BaseModel):
    pass


class JobStatusResponse(BaseModel):
    pass


class ChatMessage(BaseModel):
    role: str
    content: str


class KlineResponse(BaseModel):
    pass


class ReportCreateRequest(BaseModel):
    pass


class ReportResponse(BaseModel):
    pass


class ReportListResponse(BaseModel):
    pass


class ReportBatchDeleteRequest(BaseModel):
    pass


class ReportBatchDeleteResponse(BaseModel):
    pass


class LatestReportsBySymbolsRequest(BaseModel):
    pass


class LatestReportsBySymbolsResponse(BaseModel):
    pass


class PortfolioOverviewResponse(BaseModel):
    pass


class WatchlistAddRequest(BaseModel):
    pass


class ScheduledBatchIdsRequest(BaseModel):
    pass


class ScheduledBatchUpdateRequest(BaseModel):
    pass


class AnnouncementItemResponse(BaseModel):
    pass


class AnnouncementResponse(BaseModel):
    pass


class LatestAnnouncementResponse(BaseModel):
    pass


class BacktestRequest(BaseModel):
    pass


class SponsorItem(BaseModel):
    pass


class SponsorsResponse(BaseModel):
    pass


class FeedbackCreateRequest(BaseModel):
    pass


class FeedbackItem(BaseModel):
    pass


class FeedbackListResponse(BaseModel):
    pass


class FeedbackUnreadResponse(BaseModel):
    pass

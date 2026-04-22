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
    job_id: str
    status: str


class BatchScheduledTriggerJob(BaseModel):
    job_id: str
    symbol: Optional[str] = None


class BatchScheduledTriggerResponse(BaseModel):
    jobs: List[BatchScheduledTriggerJob] = Field(default_factory=list)


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    error: Optional[str] = None


class ChatMessage(BaseModel):
    role: str
    content: str


class KlineResponse(BaseModel):
    symbol: str = ""
    items: List[dict] = Field(default_factory=list)


class ReportCreateRequest(BaseModel):
    symbol: str
    trade_date: str
    decision: Optional[str] = None
    result_data: Optional[dict] = None


class ReportResponse(BaseModel):
    id: str


class ReportListResponse(BaseModel):
    reports: List[dict] = Field(default_factory=list)


class ReportBatchDeleteRequest(BaseModel):
    report_ids: List[str] = Field(default_factory=list)


class ReportBatchDeleteResponse(BaseModel):
    deleted_ids: List[str] = Field(default_factory=list)
    missing_ids: List[str] = Field(default_factory=list)


class LatestReportsBySymbolsRequest(BaseModel):
    symbols: List[str] = Field(default_factory=list)


class LatestReportsBySymbolsResponse(BaseModel):
    reports: List[dict] = Field(default_factory=list)


class PortfolioOverviewResponse(BaseModel):
    watchlist: List[dict] = Field(default_factory=list)
    scheduled: List[dict] = Field(default_factory=list)
    latest_reports: List[dict] = Field(default_factory=list)
    portfolio_import: dict = Field(default_factory=dict)


class WatchlistAddRequest(BaseModel):
    text: str = ""
    symbol: str = ""


class ScheduledBatchIdsRequest(BaseModel):
    item_ids: List[str] = Field(default_factory=list)


class ScheduledBatchUpdateRequest(BaseModel):
    item_ids: List[str] = Field(default_factory=list)
    is_active: Optional[bool] = None
    horizon: Optional[str] = None
    trigger_time: Optional[str] = None


class AnnouncementItemResponse(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None


class AnnouncementResponse(BaseModel):
    announcement: Optional[AnnouncementItemResponse] = None


class LatestAnnouncementResponse(BaseModel):
    announcement: Optional[AnnouncementItemResponse] = None


class BacktestRequest(BaseModel):
    strategy_id: str = ""
    symbol: str = ""


class SponsorItem(BaseModel):
    id: str = ""
    sponsor_type: str = ""
    name: str = ""


class SponsorsResponse(BaseModel):
    sponsors: List[SponsorItem] = Field(default_factory=list)


class FeedbackCreateRequest(BaseModel):
    subject: str = ""
    content: str = ""


class FeedbackItem(BaseModel):
    id: str = ""
    subject: str = ""
    content: str = ""


class FeedbackListResponse(BaseModel):
    items: List[FeedbackItem] = Field(default_factory=list)


class FeedbackUnreadResponse(BaseModel):
    unread_count: int = 0

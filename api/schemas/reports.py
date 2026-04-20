from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class ReportCreateRequest(BaseModel):
    title: str


class ReportResponse(BaseModel):
    id: str


class ReportListResponse(BaseModel):
    items: List[ReportResponse]


class ReportBatchDeleteRequest(BaseModel):
    ids: List[str]


class ReportBatchDeleteResponse(BaseModel):
    deleted: int


class LatestReportsBySymbolsRequest(BaseModel):
    symbols: List[str]


class LatestReportsBySymbolsResponse(BaseModel):
    items: List[ReportResponse]


class LatestAnnouncementResponse(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None

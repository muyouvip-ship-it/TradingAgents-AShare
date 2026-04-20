from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from api.schemas.common import UserContextInput


class AnalyzeRequest(UserContextInput):
    symbol: str = Field(default="", description="股票代码，如 600519.SH（当 query 包含代码时可省略）")
    trade_date: str = Field(default="", description="交易日期 YYYY-MM-DD")
    selected_analysts: List[str] = Field(default_factory=list)


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

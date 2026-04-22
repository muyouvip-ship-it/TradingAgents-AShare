from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from api.schemas.common import UserContextInput


class AnalyzeRequest(UserContextInput):
    symbol: str = Field(default="")
    query: str | None = None
    dry_run: bool = False
    trade_date: str | None = None
    selected_analysts: List[str] = Field(default_factory=list)


class AnalyzeResponse(BaseModel):
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    error: str | None = None

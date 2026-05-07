from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.database import get_db
from api.deps import require_api_user
from api.schemas.news_eye import NewsEyeAnalyzeRequest, NewsEyeAnalyzeResponse, NewsEyeListResponse
from api.services import news_eye_service

router = APIRouter(prefix="/v1/news-eye", tags=["News Eye"])


@router.get("/items", response_model=NewsEyeListResponse)
def list_news_items(
    limit: int = Query(120, ge=1, le=500),
    offset: int = Query(0, ge=0, le=5000),
    source: str | None = Query(None),
    sentiment: str | None = Query(None),
    symbol: str | None = Query(None),
    sector: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_api_user),
) -> dict[str, Any]:
    del current_user
    return news_eye_service.list_news_items(
        db,
        limit=limit,
        offset=offset,
        source=source,
        sentiment=sentiment,
        symbol=symbol,
        sector=sector,
    )


@router.post("/refresh")
def refresh_news_items(
    limit: int = Query(160, ge=10, le=500),
    db: Session = Depends(get_db),
    current_user=Depends(require_api_user),
) -> dict[str, Any]:
    symbols = news_eye_service.load_user_focus_symbols(db, current_user.id)
    return news_eye_service.refresh_news_cache(
        db,
        limit=limit,
        symbols=symbols,
        trigger="manual",
    )


@router.post("/analyze", response_model=NewsEyeAnalyzeResponse)
def analyze_news_item(
    payload: NewsEyeAnalyzeRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_api_user),
) -> dict[str, Any]:
    return news_eye_service.analyze_news_item(
        db,
        user_id=current_user.id,
        payload=payload.model_dump(),
    )

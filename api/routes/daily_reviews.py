from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.database import get_db
from api.deps import require_api_user
from api.schemas.daily_review import (
    DailyReviewConfigResponse,
    DailyReviewConfigUpdateRequest,
    DailyReviewGenerateRequest,
    DailyReviewHistoryResponse,
    DailyReviewResponse,
)
from api.services import daily_review_service


router = APIRouter(prefix="/v1/daily-reviews", tags=["Daily Reviews"])


@router.get("", response_model=DailyReviewResponse | None)
def get_daily_review(
    trade_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user=Depends(require_api_user),
):
    return daily_review_service.get_review(db, current_user.id, trade_date=trade_date)


@router.get("/history", response_model=DailyReviewHistoryResponse)
def get_daily_review_history(
    limit: int = Query(default=60, ge=1, le=120),
    db: Session = Depends(get_db),
    current_user=Depends(require_api_user),
):
    return daily_review_service.list_history(db, current_user.id, limit=limit)


@router.post("/generate", response_model=DailyReviewResponse)
def generate_daily_review(
    payload: DailyReviewGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_api_user),
):
    try:
        return daily_review_service.generate_daily_review(
            db,
            user_id=current_user.id,
            trade_date=payload.trade_date,
            trigger="manual",
            push_after_generate=payload.push_after_generate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"生成每日复盘失败：{exc}") from exc


@router.get("/config", response_model=DailyReviewConfigResponse)
def get_daily_review_config(
    db: Session = Depends(get_db),
    current_user=Depends(require_api_user),
):
    return daily_review_service.get_config(db, current_user.id)


@router.patch("/config", response_model=DailyReviewConfigResponse)
def update_daily_review_config(
    payload: DailyReviewConfigUpdateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_api_user),
):
    try:
        return daily_review_service.update_config(
            db,
            current_user.id,
            enabled=payload.enabled,
            trigger_time=payload.trigger_time,
            push_enabled=payload.push_enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

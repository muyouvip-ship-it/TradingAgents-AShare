from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.database import get_db
from api.deps import require_web_user
from api.schemas.common import FeedbackCreateRequest
from api.services import feedback_service


router = APIRouter(prefix="/v1", tags=["Feedback"])


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:
        return None


def _serialize_feedback(item) -> dict:
    return {
        "id": item.id,
        "user_email": item.user_email,
        "subject": item.subject,
        "content": item.content,
        "admin_reply": item.admin_reply,
        "replied_at": _iso(item.replied_at),
        "is_read": bool(item.is_read),
        "created_at": _iso(item.created_at),
        "updated_at": _iso(item.updated_at),
    }


@router.post("/feedbacks")
def create_feedback(
    body: FeedbackCreateRequest = Body(...),
    current_user=Depends(require_web_user),
    db: Session = Depends(get_db),
):
    subject = body.subject.strip()
    content = body.content.strip()
    if not subject or not content:
        raise HTTPException(status_code=400, detail="subject 和 content 不能为空")
    item = feedback_service.create_feedback(db, current_user, subject, content)
    return _serialize_feedback(item)


@router.get("/feedbacks")
def list_feedbacks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user=Depends(require_web_user),
    db: Session = Depends(get_db),
):
    items, total = feedback_service.list_feedbacks(db, current_user.id, page=page, page_size=page_size)
    return {
        "total": total,
        "feedbacks": [_serialize_feedback(item) for item in items],
    }


@router.get("/feedbacks/unread-count")
def get_feedback_unread_count(
    current_user=Depends(require_web_user),
    db: Session = Depends(get_db),
):
    return {"unread_count": feedback_service.unread_count(db, current_user.id)}


@router.get("/feedbacks/{feedback_id}")
def get_feedback(
    feedback_id: str,
    current_user=Depends(require_web_user),
    db: Session = Depends(get_db),
):
    item = feedback_service.get_feedback(db, feedback_id)
    if not item or item.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return _serialize_feedback(item)


@router.post("/feedbacks/{feedback_id}/read")
def mark_feedback_read(
    feedback_id: str,
    current_user=Depends(require_web_user),
    db: Session = Depends(get_db),
):
    item = feedback_service.mark_read(db, feedback_id, current_user.id)
    if not item:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return _serialize_feedback(item)

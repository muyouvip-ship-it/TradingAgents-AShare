from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.database import get_db
from api.deps import require_api_user
from api.services import reports_service

router = APIRouter(prefix="/v1", tags=["Reports"])


@router.post("/reports")
def create_report(db: Session = Depends(get_db), current_user=Depends(require_api_user)):
    return reports_service.create_report(db, {"owner_id": current_user.id})


@router.get("/announcements/latest")
def latest_announcement():
    return {"title": "TradingAgents-AShare", "content": "No active announcement"}


@router.get("/reports")
def list_reports(db: Session = Depends(get_db), current_user=Depends(require_api_user)):
    return {"items": reports_service.list_reports(db)}


@router.post("/reports/latest-by-symbols")
def latest_reports_by_symbols():
    return {"items": []}


@router.get("/reports/{report_id}")
def get_report(report_id: str, db: Session = Depends(get_db), current_user=Depends(require_api_user)):
    report = reports_service.get_report(db, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.delete("/reports/{report_id}")
def delete_report(report_id: str, db: Session = Depends(get_db), current_user=Depends(require_api_user)):
    if not reports_service.delete_report(db, report_id):
        raise HTTPException(status_code=404, detail="Report not found")
    return {"deleted": report_id}


@router.post("/reports/batch/delete")
def batch_delete_reports():
    return {"deleted": 0}

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.database import get_db
from api.deps import require_api_user
from api.services import reports_service

router = APIRouter(prefix="/v1", tags=["Reports"])


@router.post("/reports")
def create_report(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user=Depends(require_api_user),
):
    body = {
        "user_id": current_user.id,
        "symbol": payload.get("symbol"),
        "trade_date": payload.get("trade_date"),
        "decision": payload.get("decision"),
        "result_data": payload.get("result_data"),
    }
    if not body["symbol"] or not body["trade_date"]:
        raise HTTPException(status_code=400, detail="symbol 和 trade_date 为必填项")
    return reports_service.create_report(db, body)


@router.get("/announcements/latest")
def latest_announcement():
    return {"announcement": {"title": "TradingAgents-AShare", "content": "No active announcement"}}


@router.get("/reports")
def list_reports(
    symbol: str | None = Query(default=None),
    skip: int = Query(default=0),
    limit: int = Query(default=100),
    db: Session = Depends(get_db),
    current_user=Depends(require_api_user),
):
    return {
        "reports": reports_service.list_reports(
            db,
            user_id=current_user.id,
            symbol=symbol,
            offset=skip,
            limit=limit,
        )
    }


@router.post("/reports/latest-by-symbols")
def latest_reports_by_symbols(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user=Depends(require_api_user),
):
    return {
        "reports": reports_service.get_latest_reports_by_symbols(
            db,
            user_id=current_user.id,
            symbols=payload.get("symbols") or [],
        )
    }


@router.get("/reports/{report_id}")
def get_report(report_id: str, db: Session = Depends(get_db), current_user=Depends(require_api_user)):
    report = reports_service.get_report(db, report_id, user_id=current_user.id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.delete("/reports/{report_id}")
def delete_report(report_id: str, db: Session = Depends(get_db), current_user=Depends(require_api_user)):
    if not reports_service.delete_report(db, report_id, user_id=current_user.id):
        raise HTTPException(status_code=404, detail="Report not found")
    return {"message": "deleted", "deleted": report_id}


@router.post("/reports/batch/delete")
def batch_delete_reports(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user=Depends(require_api_user),
):
    try:
        return reports_service.batch_delete_reports(
            db,
            payload.get("report_ids") or [],
            user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

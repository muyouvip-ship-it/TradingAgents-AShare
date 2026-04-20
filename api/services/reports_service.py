from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from api.database import ReportDB


def create_report(db: Session, payload: Dict[str, Any]) -> Dict[str, Any]:
    report = ReportDB(**payload)
    db.add(report)
    db.commit()
    db.refresh(report)
    return {"id": report.id}


def list_reports(db: Session, *, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    rows = db.query(ReportDB).offset(offset).limit(limit).all()
    return [{"id": row.id} for row in rows]


def get_report(db: Session, report_id: str) -> Optional[Dict[str, Any]]:
    row = db.query(ReportDB).filter(ReportDB.id == report_id).first()
    if not row:
        return None
    return {"id": row.id}


def delete_report(db: Session, report_id: str) -> bool:
    row = db.query(ReportDB).filter(ReportDB.id == report_id).first()
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True

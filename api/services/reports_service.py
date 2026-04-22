from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from api.database import ReportDB
from api.services import report_service


def create_report(db: Session, payload: Dict[str, Any]) -> Dict[str, Any]:
    report = report_service.create_report(
        db=db,
        symbol=payload["symbol"],
        trade_date=payload["trade_date"],
        decision=payload.get("decision"),
        result_data=payload.get("result_data"),
        user_id=payload.get("user_id"),
    )
    return _to_dict(report)


def list_reports(
    db: Session,
    *,
    user_id: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    rows = report_service.get_reports_by_user(db, user_id=user_id, symbol=symbol, skip=offset, limit=limit)
    return [_to_dict(row) for row in rows]


def get_report(db: Session, report_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    row = report_service.get_report(db, report_id, user_id=user_id)
    return _to_dict(row) if row else None


def delete_report(db: Session, report_id: str, user_id: Optional[str] = None) -> bool:
    return report_service.delete_report(db, report_id, user_id=user_id)


def get_latest_reports_by_symbols(
    db: Session,
    *,
    user_id: Optional[str] = None,
    symbols: List[str],
) -> List[Dict[str, Any]]:
    return [_to_dict(row) for row in report_service.get_latest_reports_by_symbols(db, symbols=symbols, user_id=user_id)]


def batch_delete_reports(db: Session, report_ids: Iterable[str], user_id: Optional[str] = None) -> dict:
    return report_service.batch_delete_reports(db, report_ids, user_id=user_id)


def recover_stale_active_reports(db: Session) -> Dict[str, int]:
    return report_service.recover_stale_active_reports(db)


def _to_dict(row: ReportDB) -> Dict[str, Any]:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "trade_date": row.trade_date,
        "status": row.status,
        "decision": row.decision,
        "direction": row.direction,
        "confidence": row.confidence,
        "target_price": row.target_price,
        "stop_loss_price": row.stop_loss_price,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }

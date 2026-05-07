from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from api.core.stock_map import get_reverse_stock_map_cached_only, get_reverse_stock_map
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
) -> Dict[str, Any]:
    rows = report_service.get_reports_by_user(db, user_id=user_id, symbol=symbol, skip=offset, limit=limit)
    total = report_service.count_reports_by_user(db, user_id=user_id, symbol=symbol)
    return {
        "total": total,
        "reports": [_to_dict(row) for row in rows],
    }


def get_report(db: Session, report_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    row = report_service.get_report(db, report_id, user_id=user_id)
    return _to_dict(row, include_detail=True) if row else None


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


def _to_dict(row: ReportDB, *, include_detail: bool = False) -> Dict[str, Any]:
    reverse_map = get_reverse_stock_map_cached_only() or get_reverse_stock_map()
    stock_name = reverse_map.get(str(row.symbol or "").upper())
    resolved = report_service.resolve_report_fields(
        result_data={
            "final_trade_decision": row.final_trade_decision,
            "trader_investment_plan": row.trader_investment_plan,
        },
        confidence_override=row.confidence,
        target_price_override=row.target_price,
        stop_loss_override=row.stop_loss_price,
    )
    return {
        "id": row.id,
        "symbol": row.symbol,
        "name": stock_name or row.symbol,
        "trade_date": row.trade_date,
        "status": row.status,
        "decision": row.decision,
        "direction": row.direction,
        "confidence": resolved.get("confidence"),
        "target_price": resolved.get("target_price"),
        "stop_loss_price": resolved.get("stop_loss_price"),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        **(
            {
                "error": row.error,
                "risk_items": row.risk_items,
                "key_metrics": row.key_metrics,
                "analyst_traces": row.analyst_traces,
                "market_report": row.market_report,
                "sentiment_report": row.sentiment_report,
                "news_report": row.news_report,
                "fundamentals_report": row.fundamentals_report,
                "macro_report": row.macro_report,
                "smart_money_report": row.smart_money_report,
                "volume_price_report": row.volume_price_report,
                "game_theory_report": row.game_theory_report,
                "investment_plan": row.investment_plan,
                "trader_investment_plan": row.trader_investment_plan,
                "final_trade_decision": row.final_trade_decision,
                "result_data": row.result_data,
            }
            if include_detail
            else {}
        ),
    }

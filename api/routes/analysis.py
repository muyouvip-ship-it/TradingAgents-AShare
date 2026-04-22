from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from api.database import get_db_ctx
from api.deps import require_api_user
from api.job_store import get_job_store
from api.schemas.analysis import AnalyzeRequest
from api.services import portfolio_import_service

router = APIRouter(tags=["Analysis"])


@router.post("/v1/analyze")
def analyze(request: AnalyzeRequest, current_user=Depends(require_api_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="请先登录")
    job_id = str(uuid4())
    store = get_job_store()
    user_context = {
        "objective": request.objective,
        "risk_profile": request.risk_profile,
        "investment_horizon": request.investment_horizon,
        "cash_available": request.cash_available,
        "current_position": request.current_position,
        "current_position_pct": request.current_position_pct,
        "average_cost": request.average_cost,
        "max_loss_pct": request.max_loss_pct,
        "constraints": list(request.constraints or []),
        "user_notes": request.user_notes,
    }
    with get_db_ctx() as db:
        imported_context = portfolio_import_service.build_scheduled_user_context(
            db,
            current_user.id,
            request.symbol,
        )
    merged_context = {k: v for k, v in imported_context.items() if v is not None}
    for key, value in user_context.items():
        if value not in (None, [], ""):
            merged_context[key] = value
    result_payload = {
        "status": "completed",
        "decision": "DRY_RUN",
        "job_id": job_id,
        "symbol": request.symbol,
        "query": request.query,
        "selected_analysts": list(request.selected_analysts or []),
        "user_context": merged_context,
    }
    if request.dry_run:
        store.set_job(
            job_id,
            user_id=current_user.id,
            status="completed",
            decision="DRY_RUN",
            symbol=request.symbol,
            trade_date=request.trade_date,
            result=result_payload,
        )
        return {"job_id": job_id, "status": "completed", "dry_run": True, "symbol": request.symbol, "query": request.query}
    store.set_job(
        job_id,
        user_id=current_user.id,
        status="queued",
        symbol=request.symbol,
        trade_date=request.trade_date,
    )
    return {"job_id": job_id, "status": "queued", "dry_run": False, "symbol": request.symbol, "query": request.query}

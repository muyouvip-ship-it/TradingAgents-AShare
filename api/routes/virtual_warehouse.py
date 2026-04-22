from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.database import get_db
from api.deps import require_api_user
from api.services import qmt_sync_scheduler_service, qmt_virtual_account_service


router = APIRouter(prefix="/v1/virtual-warehouse", tags=["Virtual Warehouse"])


class QmtOrderSubmitRequest(BaseModel):
    account_key: str | None = None
    symbol: str = Field(..., min_length=1)
    side: str = Field(..., min_length=1)
    quantity: int = Field(..., gt=0)
    price: float | None = Field(default=None, gt=0)
    price_type: str = Field(default="limit", min_length=1)
    strategy_name: str | None = None
    order_remark: str | None = None


@router.get("/qmt/overview")
def get_qmt_virtual_warehouse(
    account_key: str | None = Query(default=None),
    current_user=Depends(require_api_user),
    db: Session = Depends(get_db),
):
    return qmt_virtual_account_service.get_qmt_virtual_account_overview(db, current_user.id, account_key=account_key)


@router.get("/qmt/orders")
def get_qmt_orders(
    account_key: str | None = Query(default=None),
    current_user=Depends(require_api_user),
    db: Session = Depends(get_db),
):
    return qmt_virtual_account_service.list_qmt_orders(db, current_user.id, account_key=account_key)


@router.get("/qmt/trades")
def get_qmt_trades(
    account_key: str | None = Query(default=None),
    current_user=Depends(require_api_user),
    db: Session = Depends(get_db),
):
    return qmt_virtual_account_service.list_qmt_trades(db, current_user.id, account_key=account_key)


@router.post("/qmt/orders")
def submit_qmt_order(
    body: QmtOrderSubmitRequest,
    current_user=Depends(require_api_user),
    db: Session = Depends(get_db),
):
    try:
        return qmt_virtual_account_service.submit_qmt_order(
            db,
            current_user.id,
            account_key=body.account_key,
            symbol=body.symbol,
            side=body.side,
            quantity=body.quantity,
            price=body.price,
            price_type=body.price_type,
            strategy_name=body.strategy_name,
            order_remark=body.order_remark,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/qmt/orders/{order_id}/cancel")
def cancel_qmt_order(
    order_id: str,
    account_key: str | None = Query(default=None),
    current_user=Depends(require_api_user),
    db: Session = Depends(get_db),
):
    try:
        return qmt_virtual_account_service.cancel_qmt_order(
            db,
            current_user.id,
            account_key=account_key,
            order_id=order_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/qmt/sync")
def sync_qmt_virtual_warehouse(
    account_key: str | None = Query(default=None),
    current_user=Depends(require_api_user),
    db: Session = Depends(get_db),
):
    return qmt_virtual_account_service.sync_qmt_virtual_positions(db, current_user.id, account_key=account_key)


@router.get("/qmt/diagnostics")
def get_qmt_virtual_warehouse_diagnostics(
    account_key: str | None = Query(default=None),
    run_connect_test: bool = Query(default=False),
    current_user=Depends(require_api_user),
):
    del current_user
    return qmt_virtual_account_service.diagnose_qmt_accounts(account_key=account_key, run_connect_test=run_connect_test)


@router.get("/qmt/sync-profiles")
def list_qmt_sync_profiles(current_user=Depends(require_api_user), db: Session = Depends(get_db)):
    profiles = qmt_sync_scheduler_service.list_sync_profiles(db, current_user.id)
    return {"items": profiles}


@router.post("/qmt/sync-profiles/{account_key}")
def upsert_qmt_sync_profile(
    account_key: str,
    body: dict | None = Body(default=None),
    current_user=Depends(require_api_user),
    db: Session = Depends(get_db),
):
    payload = body or {}
    profile = qmt_sync_scheduler_service.upsert_sync_profile(
        db,
        current_user.id,
        account_key,
        is_active=bool(payload.get("is_active", False)),
        sync_interval_seconds=int(payload.get("sync_interval_seconds") or 30),
        sync_tracking_board=bool(payload.get("sync_tracking_board", True)),
        alert_on_disconnect=bool(payload.get("alert_on_disconnect", True)),
    )
    return profile

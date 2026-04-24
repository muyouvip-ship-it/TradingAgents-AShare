from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.core.strategy_db import get_strategy_db
from api.database import get_db
from api.deps import require_api_user
from api.services import realtime_monitor_service


router = APIRouter(tags=["Realtime Monitor"])


class RealtimeMonitorCreateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    account_key: str = Field(default="paper_sim", min_length=1)
    strategy_id: str = Field(..., min_length=1)
    strategy_version_id: str | None = None
    execution_mode: Literal["auto", "monitor_only"] = "auto"
    live_trading_enabled: bool = False
    live_confirmed: bool = False
    monitor_pool: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    risk_config: dict[str, Any] = Field(default_factory=dict)


class RealtimeApprovalDecisionRequest(BaseModel):
    decision: dict[str, Any] = Field(default_factory=dict)


def _as_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@router.post("/v1/realtime/monitors")
def create_realtime_monitor(
    body: RealtimeMonitorCreateRequest,
    current_user=Depends(require_api_user),
    strategy_db: Session = Depends(get_strategy_db),
    db: Session = Depends(get_db),
):
    try:
        return realtime_monitor_service.create_monitor(strategy_db, db, current_user.id, body.model_dump(exclude_none=True))
    except Exception as exc:
        raise _as_http_error(exc) from exc


@router.get("/v1/realtime/monitors")
def list_realtime_monitors(
    current_user=Depends(require_api_user),
    strategy_db: Session = Depends(get_strategy_db),
):
    try:
        return {"items": realtime_monitor_service.list_monitors(strategy_db, current_user.id)}
    except Exception as exc:
        raise _as_http_error(exc) from exc


@router.get("/v1/realtime/monitors/{monitor_id}")
def get_realtime_monitor(
    monitor_id: str,
    current_user=Depends(require_api_user),
    strategy_db: Session = Depends(get_strategy_db),
):
    try:
        return realtime_monitor_service.get_monitor(strategy_db, current_user.id, monitor_id)
    except Exception as exc:
        raise _as_http_error(exc) from exc


@router.delete("/v1/realtime/monitors/{monitor_id}")
def delete_realtime_monitor(
    monitor_id: str,
    current_user=Depends(require_api_user),
    strategy_db: Session = Depends(get_strategy_db),
):
    try:
        return realtime_monitor_service.delete_monitor(strategy_db, current_user.id, monitor_id)
    except Exception as exc:
        raise _as_http_error(exc) from exc


@router.post("/v1/realtime/monitors/{monitor_id}/start")
def start_realtime_monitor(
    monitor_id: str,
    current_user=Depends(require_api_user),
    strategy_db: Session = Depends(get_strategy_db),
):
    try:
        return realtime_monitor_service.start_monitor(strategy_db, current_user.id, monitor_id)
    except Exception as exc:
        raise _as_http_error(exc) from exc


@router.post("/v1/realtime/monitors/{monitor_id}/pause")
def pause_realtime_monitor(
    monitor_id: str,
    current_user=Depends(require_api_user),
    strategy_db: Session = Depends(get_strategy_db),
):
    try:
        return realtime_monitor_service.pause_monitor(strategy_db, current_user.id, monitor_id)
    except Exception as exc:
        raise _as_http_error(exc) from exc


@router.post("/v1/realtime/monitors/{monitor_id}/stop")
def stop_realtime_monitor(
    monitor_id: str,
    current_user=Depends(require_api_user),
    strategy_db: Session = Depends(get_strategy_db),
):
    try:
        return realtime_monitor_service.stop_monitor(strategy_db, current_user.id, monitor_id)
    except Exception as exc:
        raise _as_http_error(exc) from exc


@router.post("/v1/realtime/monitors/{monitor_id}/resume")
def resume_realtime_monitor(
    monitor_id: str,
    current_user=Depends(require_api_user),
    strategy_db: Session = Depends(get_strategy_db),
):
    try:
        return realtime_monitor_service.resume_monitor(strategy_db, current_user.id, monitor_id)
    except Exception as exc:
        raise _as_http_error(exc) from exc


@router.post("/v1/realtime/monitors/{monitor_id}/run-once")
def run_realtime_monitor_once(
    monitor_id: str,
    current_user=Depends(require_api_user),
    strategy_db: Session = Depends(get_strategy_db),
    db: Session = Depends(get_db),
):
    try:
        return realtime_monitor_service.run_monitor_once(strategy_db, db, current_user.id, monitor_id)
    except Exception as exc:
        raise _as_http_error(exc) from exc


@router.post("/v1/realtime/monitors/{monitor_id}/fuse-reset")
def reset_realtime_monitor_fuse(
    monitor_id: str,
    current_user=Depends(require_api_user),
    strategy_db: Session = Depends(get_strategy_db),
):
    try:
        return realtime_monitor_service.fuse_reset_monitor(strategy_db, current_user.id, monitor_id)
    except Exception as exc:
        raise _as_http_error(exc) from exc


@router.get("/v1/realtime/monitors/{monitor_id}/events")
def get_realtime_monitor_events(
    monitor_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    after_id: str | None = Query(default=None),
    current_user=Depends(require_api_user),
    strategy_db: Session = Depends(get_strategy_db),
):
    try:
        return {
            "items": realtime_monitor_service.list_events(
                strategy_db,
                current_user.id,
                monitor_id,
                limit=limit,
                after_id=after_id,
            )
        }
    except Exception as exc:
        raise _as_http_error(exc) from exc


@router.get("/v1/realtime/monitors/{monitor_id}/stream")
async def stream_realtime_monitor(
    monitor_id: str,
    initial_limit: int = Query(default=30, ge=0, le=200),
    current_user=Depends(require_api_user),
    strategy_db: Session = Depends(get_strategy_db),
):
    try:
        monitor = realtime_monitor_service.get_monitor(strategy_db, current_user.id, monitor_id)
    except Exception as exc:
        raise _as_http_error(exc) from exc

    def _pack(event: str, payload: dict[str, Any]) -> str:
        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def event_generator():
        last_event_id: str | None = None
        yield _pack(
            "ready",
            {
                "monitor_id": monitor_id,
                "status": monitor.get("status"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        if initial_limit > 0:
            initial_items = realtime_monitor_service.list_events(
                strategy_db,
                current_user.id,
                monitor_id,
                limit=initial_limit,
            )
            for item in initial_items:
                last_event_id = item.get("id") or last_event_id
                yield _pack("event", {"initial": True, "item": item})

        while True:
            try:
                fresh_items = realtime_monitor_service.list_events(
                    strategy_db,
                    current_user.id,
                    monitor_id,
                    limit=200,
                    after_id=last_event_id,
                )
                if fresh_items:
                    for item in fresh_items:
                        last_event_id = item.get("id") or last_event_id
                        yield _pack("event", {"initial": False, "item": item})
                    monitor_payload = realtime_monitor_service.get_monitor(strategy_db, current_user.id, monitor_id)
                    yield _pack("state", {"monitor": monitor_payload})
                else:
                    yield ": ping\n\n"
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                yield _pack(
                    "error",
                    {
                        "message": str(exc),
                        "monitor_id": monitor_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
                await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/v1/realtime/monitors/{monitor_id}/orders")
def get_realtime_monitor_orders(
    monitor_id: str,
    current_user=Depends(require_api_user),
    strategy_db: Session = Depends(get_strategy_db),
):
    try:
        return {"items": realtime_monitor_service.list_orders(strategy_db, current_user.id, monitor_id)}
    except Exception as exc:
        raise _as_http_error(exc) from exc


@router.get("/v1/realtime/monitors/{monitor_id}/trades")
def get_realtime_monitor_trades(
    monitor_id: str,
    current_user=Depends(require_api_user),
    strategy_db: Session = Depends(get_strategy_db),
):
    try:
        return {"items": realtime_monitor_service.list_trades(strategy_db, current_user.id, monitor_id)}
    except Exception as exc:
        raise _as_http_error(exc) from exc


@router.get("/v1/realtime/monitors/{monitor_id}/positions")
def get_realtime_monitor_positions(
    monitor_id: str,
    current_user=Depends(require_api_user),
    strategy_db: Session = Depends(get_strategy_db),
    db: Session = Depends(get_db),
):
    try:
        return realtime_monitor_service.get_positions(strategy_db, db, current_user.id, monitor_id)
    except Exception as exc:
        raise _as_http_error(exc) from exc


@router.get("/v1/realtime/approvals")
def list_realtime_approvals(
    status: str | None = Query(default=None),
    monitor_id: str | None = Query(default=None),
    current_user=Depends(require_api_user),
    strategy_db: Session = Depends(get_strategy_db),
):
    try:
        items = realtime_monitor_service.list_approvals(strategy_db, current_user.id, status=status)
        if monitor_id:
            items = [item for item in items if item.get("monitor_id") == monitor_id]
        return {"items": items}
    except Exception as exc:
        raise _as_http_error(exc) from exc


@router.post("/v1/realtime/approvals/{approval_id}/approve")
def approve_realtime_approval(
    approval_id: str,
    body: RealtimeApprovalDecisionRequest | None = Body(default=None),
    current_user=Depends(require_api_user),
    strategy_db: Session = Depends(get_strategy_db),
    db: Session = Depends(get_db),
):
    try:
        return realtime_monitor_service.approve_task(
            strategy_db,
            db,
            current_user.id,
            approval_id,
            decision=(body.decision if body else {}),
        )
    except Exception as exc:
        raise _as_http_error(exc) from exc


@router.post("/v1/realtime/approvals/{approval_id}/reject")
def reject_realtime_approval(
    approval_id: str,
    body: RealtimeApprovalDecisionRequest | None = Body(default=None),
    current_user=Depends(require_api_user),
    strategy_db: Session = Depends(get_strategy_db),
):
    try:
        return realtime_monitor_service.reject_task(
            strategy_db,
            current_user.id,
            approval_id,
            decision=(body.decision if body else {}),
        )
    except Exception as exc:
        raise _as_http_error(exc) from exc

from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from api.database import VersionStatsDB, get_db
from api.core.http_utils import get_real_ip
from api.services.data_source_governance import list_registered_sources, list_surface_registry
from api.services.market_data_pipeline_service import get_market_data_publish_status

router = APIRouter(tags=["System"])

_vs_rate_limit: Dict[str, float] = {}
_VS_RATE_INTERVAL = 3600


@router.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@router.get("/v1/system/data-sources")
async def list_system_data_sources() -> dict[str, Any]:
    return {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": list_registered_sources(),
        "surfaces": list_surface_registry(),
    }


@router.get("/v1/system/market-data-status")
async def get_system_market_data_status(
    trade_date: str | None = None,
    symbols: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    symbol_list = [item.strip() for item in str(symbols or "").split(",") if item.strip()]
    payload = get_market_data_publish_status(
        trade_date=trade_date,
        symbols=symbol_list,
        limit=limit,
    )
    payload["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return payload


@router.post("/api/version-stats")
def version_stats(payload: Dict[str, Any] = Body(...), request: Request = None, db: Session = Depends(get_db)):
    remote_ip = get_real_ip(request)
    now = time.time()
    if remote_ip:
        last = _vs_rate_limit.get(remote_ip, 0)
        if now - last < _VS_RATE_INTERVAL:
            return {"status": "ok"}
        _vs_rate_limit[remote_ip] = now

    record = VersionStatsDB(
        version=str(payload.get("v", ""))[:50],
        nonce=str(payload.get("nonce", ""))[:64],
        remote_ip=remote_ip,
    )
    db.add(record)
    db.commit()
    return {"status": "ok"}

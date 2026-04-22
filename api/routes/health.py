from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from api.database import VersionStatsDB, get_db
from api.core.http_utils import get_real_ip

router = APIRouter(tags=["System"])

_vs_rate_limit: Dict[str, float] = {}
_VS_RATE_INTERVAL = 3600


@router.get("/healthz")
def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok"})


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

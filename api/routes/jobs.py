from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.deps import require_api_user

from api.job_store import get_job_store

router = APIRouter(prefix="/v1/jobs", tags=["Jobs"])


@router.get("/{job_id}")
def get_job_status(job_id: str, current_user=Depends(require_api_user)):
    from api import main as compat

    job = compat._require_job_owner(job_id, current_user)
    return {
        "job_id": job.get("job_id", job_id),
        "status": job.get("status", "pending"),
        "error": job.get("error"),
        "current_agent": job.get("current_agent"),
        "current_stage": job.get("current_stage"),
        "analysis_stage": job.get("analysis_stage"),
        "progress": job.get("progress") or {},
    }


@router.get("/{job_id}/result")
def get_job_result(job_id: str, current_user=Depends(require_api_user)):
    from api import main as compat

    job = compat._require_job_owner(job_id, current_user)
    result = job.get("result") or {}
    return {
        "job_id": job_id,
        "status": job.get("status", result.get("status", "completed")),
        "decision": job.get("decision", result.get("decision", "DRY_RUN")),
        "result": result,
        **result,
    }

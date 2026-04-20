from __future__ import annotations

from typing import Any, Dict, Optional

_job_store: Dict[str, Dict[str, Any]] = {}


def set_job(job_key: str, **kwargs) -> None:
    _job_store.setdefault(job_key, {}).update(kwargs)


def get_job(job_key: str) -> Dict[str, Any]:
    return dict(_job_store.get(job_key, {}))


def emit_job_event(job_id: str, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {"job_id": job_id, "event": event, "data": data}


def attach_job_runtime_state(target: Any, job_id: Optional[str]) -> Any:
    setattr(target, "job_id", job_id)
    return target

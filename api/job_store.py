from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List

from api.core.datetime_utils import utcnow_iso

logger = logging.getLogger(__name__)


class InMemoryJobStore:
    def __init__(self):
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._events: Dict[str, List[Dict[str, Any]]] = {}

    def set_job(self, job_id: str, **kwargs):
        self._jobs.setdefault(job_id, {}).update(kwargs)

    def get_job(self, job_id: str) -> Dict[str, Any]:
        return dict(self._jobs.get(job_id, {}))

    def delete_job(self, job_id: str):
        self._jobs.pop(job_id, None)
        self._events.pop(job_id, None)

    def clear(self):
        self._jobs.clear()
        self._events.clear()

    def emit_event(self, job_id: str, event: str, data: Dict[str, Any]):
        self._events.setdefault(job_id, []).append({"event": event, "data": data, "timestamp": utcnow_iso()})
        if event == "job.completed":
            self.set_job(job_id, status="completed")
        elif event == "job.failed":
            self.set_job(job_id, status="failed")

    async def subscribe(self, job_id: str, poll_interval: float = 0.1):
        seen = 0
        while True:
            events = self._events.get(job_id, [])
            while seen < len(events):
                yield events[seen]
                seen += 1
            job = self._jobs.get(job_id, {})
            if job.get("status") in ("completed", "failed"):
                break
            await asyncio.sleep(poll_interval)
            if seen == len(events):
                ping_time = utcnow_iso()
                yield {"event": "ping", "data": {"job_id": job_id, "timestamp": ping_time}, "timestamp": ping_time}


_memory_job_store = InMemoryJobStore()
_job_store: Any | None = None
_job_store_signature: tuple[str, str, str] | None = None


def get_job_store() -> Any:
    global _job_store, _job_store_signature
    backend = os.getenv("JOB_STORE_BACKEND", "").strip().lower()
    redis_url = os.getenv("JOB_STORE_REDIS_URL") or os.getenv("REDIS_URL") or ""
    prefix = os.getenv("JOB_STORE_REDIS_PREFIX", "ta:")
    if not backend:
        backend = "redis" if redis_url else "memory"

    signature = (backend, redis_url, prefix)
    if _job_store is not None and _job_store_signature == signature:
        return _job_store

    if backend == "redis":
        if not redis_url:
            logger.warning("JOB_STORE_BACKEND=redis but no REDIS_URL/JOB_STORE_REDIS_URL is configured; using memory store")
        else:
            try:
                from api.job_store_redis import RedisJobStore

                _job_store = RedisJobStore(redis_url, prefix=prefix)
                _job_store_signature = signature
                return _job_store
            except Exception:
                logger.warning("Redis job store unavailable; falling back to in-memory store", exc_info=True)

    _job_store = _memory_job_store
    _job_store_signature = ("memory", "", "")
    return _job_store

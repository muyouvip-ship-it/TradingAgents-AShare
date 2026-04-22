from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from api.core.datetime_utils import utcnow_iso


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


_job_store = InMemoryJobStore()


def get_job_store() -> InMemoryJobStore:
    return _job_store

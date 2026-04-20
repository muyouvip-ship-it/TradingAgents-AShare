from __future__ import annotations

from typing import Any, Dict


class InMemoryJobStore:
    def __init__(self):
        self._jobs: Dict[str, Dict[str, Any]] = {}

    def clear(self):
        self._jobs.clear()

    def emit_event(self, job_id: str, event: str, data: Dict[str, Any]):
        self._jobs.setdefault(job_id, {}).setdefault("events", []).append((event, data))


_job_store = InMemoryJobStore()


def get_job_store() -> InMemoryJobStore:
    return _job_store

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, List, Set

_scheduled_analysis_max_concurrency = 2
_scheduled_analysis_semaphore = asyncio.Semaphore(_scheduled_analysis_max_concurrency)
_scheduled_analysis_queue_lock = asyncio.Lock()
_scheduled_analysis_waiting_job_ids: List[str] = []
_scheduled_analysis_running_job_ids: Set[str] = set()


@asynccontextmanager
async def scheduled_analysis_slot(job_id: str, symbol: str) -> AsyncIterator[None]:
    del symbol
    async with _scheduled_analysis_queue_lock:
        _scheduled_analysis_waiting_job_ids.append(job_id)
    await _scheduled_analysis_semaphore.acquire()
    async with _scheduled_analysis_queue_lock:
        if job_id in _scheduled_analysis_waiting_job_ids:
            _scheduled_analysis_waiting_job_ids.remove(job_id)
        _scheduled_analysis_running_job_ids.add(job_id)
    try:
        yield
    finally:
        async with _scheduled_analysis_queue_lock:
            _scheduled_analysis_running_job_ids.discard(job_id)
        _scheduled_analysis_semaphore.release()


def reset_scheduler_state(limit: int) -> None:
    global _scheduled_analysis_max_concurrency, _scheduled_analysis_semaphore
    _scheduled_analysis_max_concurrency = limit
    _scheduled_analysis_semaphore = asyncio.Semaphore(limit)
    _scheduled_analysis_waiting_job_ids.clear()
    _scheduled_analysis_running_job_ids.clear()

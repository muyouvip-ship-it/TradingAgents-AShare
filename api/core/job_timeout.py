from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JobTimeoutPolicy:
    stage_timeout_seconds: int = 600
    overall_timeout_seconds: int = 1800


policy = JobTimeoutPolicy()

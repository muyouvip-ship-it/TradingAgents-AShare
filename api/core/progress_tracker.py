from __future__ import annotations

from typing import Any, Dict


class AgentProgressTracker:
    def __init__(self):
        self.status: Dict[str, str] = {}
        self._completed_stages: set = set()
        self._writing_status_sent: set = set()

    def snapshot(self) -> Dict[str, Any]:
        return {"status": dict(self.status)}

    def _set_status(self, agent: str, status: str) -> None:
        prev = self.status.get(agent)
        self.status[agent] = status

    def _emit_milestone(self, stage: str, summary: str = "") -> None:
        return None

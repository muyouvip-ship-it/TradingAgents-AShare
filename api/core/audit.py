from __future__ import annotations

from typing import Any, Dict


def audit_event(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"action": action, "payload": payload}

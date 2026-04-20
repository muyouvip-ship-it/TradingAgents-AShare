from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def serialize_datetime_utc(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat()


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

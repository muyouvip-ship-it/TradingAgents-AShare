from __future__ import annotations

import os
from typing import Optional

from fastapi import Request


def get_real_ip(request: Request) -> Optional[str]:
    """Extract real client IP, preferring Cloudflare/proxy headers."""
    if request is None:
        return None
    ip = request.headers.get("CF-Connecting-IP")
    if ip:
        return ip.strip()
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def cors_allow_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
    default_origins = [
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:5175",
        "http://localhost:5175",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]
    if not raw:
        return default_origins
    return [item.strip() for item in raw.split(",") if item.strip()]


def cors_allow_origin_regex() -> str | None:
    raw = os.getenv("CORS_ALLOW_ORIGIN_REGEX", "").strip()
    return raw or None

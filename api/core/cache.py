from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=128)
def get_cached_value(key: str) -> str:
    return key

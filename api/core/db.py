from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from api.database import SessionLocal


@contextmanager
def get_session() -> Iterator[object]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

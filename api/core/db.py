from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.core.settings import settings

_engine = create_engine("sqlite:///app.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@contextmanager
def get_session() -> Iterator[object]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

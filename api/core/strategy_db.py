from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from api.core.env import load_project_env

load_project_env()

_database_url = os.getenv("STRATEGY_DATABASE_URL") or os.getenv("DATABASE_URL")
if not _database_url:
    raise RuntimeError("DATABASE_URL or STRATEGY_DATABASE_URL is required. PostgreSQL is the only supported database.")
if not (_database_url.startswith("postgresql://") or _database_url.startswith("postgresql+") or _database_url.startswith("postgres://")):
    raise RuntimeError("Strategy database URL must point to PostgreSQL.")

strategy_engine = create_engine(
    _database_url,
    echo=False,
)
StrategySessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=strategy_engine)
_strategy_schema_ready = False


def ensure_strategy_schema_ready() -> None:
    global _strategy_schema_ready
    if _strategy_schema_ready:
        return
    from api.models.strategy_models import Base

    Base.metadata.create_all(strategy_engine)
    _strategy_schema_ready = True


def get_strategy_db() -> Iterator[Session]:
    ensure_strategy_schema_ready()
    db = StrategySessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_strategy_db_ctx() -> Iterator[Session]:
    ensure_strategy_schema_ready()
    db = StrategySessionLocal()
    try:
        yield db
    finally:
        db.close()

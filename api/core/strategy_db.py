from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from api.core.env import load_project_env

load_project_env()

_database_url = os.getenv("STRATEGY_DATABASE_URL") or os.getenv("DATABASE_URL")
if not _database_url:
    if "pytest" in sys.modules:
        strategy_db_path = os.getenv("STRATEGY_DB_PATH", "data/strategy_management.db")
        _database_url = f"sqlite:///{strategy_db_path}"
    else:
        _database_url = "postgresql://localhost/trading_agents"

_is_sqlite = _database_url.startswith("sqlite")
strategy_engine = create_engine(
    _database_url,
    echo=False,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)
StrategySessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=strategy_engine)


def get_strategy_db() -> Iterator[Session]:
    db = StrategySessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_strategy_db_ctx() -> Iterator[Session]:
    db = StrategySessionLocal()
    try:
        yield db
    finally:
        db.close()

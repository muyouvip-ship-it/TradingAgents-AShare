from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from api.core.settings import settings
from api.core.strategy_db import strategy_engine
from api.database import init_db
from api.job_store import get_job_store
from api.models.strategy_models import Base
from api.services import qmt_sync_scheduler_service


def _log(msg: str):
    from api.core.logging import logger

    logger.info(msg)


@asynccontextmanager
async def lifespan(app):
    """Initialize resources on startup and cleanup on shutdown."""
    init_db()
    _log("Database initialized.")

    # 初始化策略管理数据库（优先复用 PostgreSQL）
    Base.metadata.create_all(strategy_engine)
    _log("Strategy management database initialized.")

    store = get_job_store()
    store.clear()

    if not os.getenv("TA_APP_SECRET_KEY"):
        _log("=" * 70)
        _log("WARNING: TA_APP_SECRET_KEY is not set!")
        _log("Using hardcoded default key. ALL encryption and JWT signing")
        _log("is INSECURE. Set TA_APP_SECRET_KEY env var before production use.")
        _log("=" * 70)

    from tradingagents.dataflows.trade_calendar import _load_cn_trade_dates
    from api.core.stock_map import load_cn_stock_map

    _load_cn_trade_dates()
    _log("Trade calendar pre-loaded.")
    await asyncio.to_thread(load_cn_stock_map)
    _log("Stock map pre-loaded on startup.")
    await qmt_sync_scheduler_service.start_background_worker()
    _log("QMT sync background worker started.")
    yield
    await qmt_sync_scheduler_service.stop_background_worker()
    _log("Shutting down: Cleaning up resources...")

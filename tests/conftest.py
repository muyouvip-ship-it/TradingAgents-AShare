from __future__ import annotations

import os

from dotenv import find_dotenv, load_dotenv


def pytest_configure() -> None:
    env_path = find_dotenv(usecwd=True)
    if env_path:
        load_dotenv(env_path, override=False)

    test_database_url = os.getenv("TEST_DATABASE_URL")
    if test_database_url:
        os.environ["DATABASE_URL"] = test_database_url
        os.environ.setdefault("STRATEGY_DATABASE_URL", test_database_url)
    elif os.getenv("DATABASE_URL"):
        os.environ.setdefault("STRATEGY_DATABASE_URL", os.getenv("DATABASE_URL", ""))

    os.environ.setdefault("TA_APP_SECRET_KEY", "tradingagents-test-secret")
    os.environ.setdefault("ENABLE_NEWS_EYE_WORKER", "0")
    os.environ.setdefault("ENABLE_DAILY_REVIEW_WORKER", "0")

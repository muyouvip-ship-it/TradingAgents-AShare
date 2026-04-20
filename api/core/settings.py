from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    env: str = os.getenv("ENV", "dev")
    app_version: str = os.getenv("APP_VERSION", "dev")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    cors_allow_origins: str = os.getenv("CORS_ALLOW_ORIGINS", "")
    cors_allow_origin_regex: str = os.getenv("CORS_ALLOW_ORIGIN_REGEX", "")
    allow_server_llm_fallback: bool = os.getenv("ALLOW_SERVER_LLM_FALLBACK", "1").lower() in {"1", "true", "yes", "on"}
    ta_job_timeout: int = int(os.getenv("TA_JOB_TIMEOUT", "600"))
    ta_app_secret_key: str = os.getenv("TA_APP_SECRET_KEY", "")
    strategy_db_path: str = os.getenv("STRATEGY_DB_PATH", "data/strategy_management.db")


settings = Settings()

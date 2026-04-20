from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.core.http_utils import cors_allow_origins, cors_allow_origin_regex
from api.core.versioning import get_version
from api.lifespan import lifespan


_is_prod = os.getenv("ENV", "").lower() == "prod"
APP_VERSION = get_version()

app = FastAPI(
    title="TradingAgents-AShare API",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url=None if _is_prod else "/docs",
    redoc_url=None if _is_prod else "/redoc",
    openapi_url=None if _is_prod else "/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins(),
    allow_origin_regex=cors_allow_origin_regex(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

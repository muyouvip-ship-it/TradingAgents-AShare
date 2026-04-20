# TradingAgents-AShare Architecture

## Overview
The project is organized into a FastAPI backend and a React frontend.

## Backend layers
- `api/app.py` application bootstrap
- `api/lifespan.py` startup/shutdown lifecycle
- `api/core/` shared utilities, config, security, cache, orchestration helpers
- `api/routes/` HTTP route handlers
- `api/services/` business logic
- `api/schemas/` request/response models

## Frontend layers
- `frontend/src/lib/` API client and shared helpers
- `frontend/src/store/` Zustand state
- `frontend/src/components/` reusable UI components

## Execution flow
1. HTTP request enters FastAPI app
2. Route validates input and auth dependency
3. Service handles business logic
4. Core utilities provide common helpers
5. Response returns via schema-defined payloads

## Key conventions
- Keep route files thin
- Put reusable logic in `core` or `services`
- Put typed payloads in `schemas`
- Use shared settings for runtime config

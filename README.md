# TradingAgents-AShare

## Quick Start

### Backend

```bash
uv sync --frozen --no-dev
uv run uvicorn api.app:app --reload --port 8500
```

### Scheduler

```bash
uv run tradingagents-scheduler
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### One-Command Startup

```bash
./scripts/start_services.sh
```

定时分析依赖独立调度器；如果只启动后端和前端，不启动 `tradingagents-scheduler`，定时任务不会按时间自动执行。

## Testing

```bash
pytest -q
cd frontend
npm test
```

## Architecture

See `architecture.md` for the backend/frontend layering and execution flow.

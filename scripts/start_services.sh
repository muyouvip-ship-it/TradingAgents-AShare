#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8500}"
FRONTEND_PORT="${FRONTEND_PORT:-5174}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
SCHEDULER_CMD_PATTERN="${SCHEDULER_CMD_PATTERN:-tradingagents-scheduler}"

cd "$ROOT"
mkdir -p .runtime

echo "[start] root=$ROOT"

if lsof -iTCP:"$BACKEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[start] backend already listening on :$BACKEND_PORT"
else
  echo "[start] starting backend on :$BACKEND_PORT"
  nohup uv run uvicorn api.app:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" \
    > .runtime/backend.log 2>&1 &
  echo $! > .runtime/backend.pid
fi

if [[ -f .runtime/scheduler.pid ]] && kill -0 "$(cat .runtime/scheduler.pid)" >/dev/null 2>&1; then
  echo "[start] scheduler already running with pid $(cat .runtime/scheduler.pid)"
elif pgrep -f "$SCHEDULER_CMD_PATTERN" >/dev/null 2>&1; then
  echo "[start] scheduler already running (matched pattern: $SCHEDULER_CMD_PATTERN)"
else
  echo "[start] starting scheduler"
  nohup uv run tradingagents-scheduler > .runtime/scheduler.log 2>&1 &
  echo $! > .runtime/scheduler.pid
fi

if lsof -iTCP:"$FRONTEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[start] frontend already listening on :$FRONTEND_PORT"
else
  echo "[start] starting frontend on :$FRONTEND_PORT"
  cd "$ROOT/frontend"
  nohup npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" \
    > "$ROOT/.runtime/frontend.log" 2>&1 &
  echo $! > "$ROOT/.runtime/frontend.pid"
  cd "$ROOT"
fi

sleep 3

echo "[check] backend"
curl -sS --max-time 8 "http://${BACKEND_HOST}:${BACKEND_PORT}/healthz" || \
  curl -sS --max-time 8 "http://${BACKEND_HOST}:${BACKEND_PORT}/health"

echo

echo "[check] frontend"
curl -I -sS --max-time 8 "http://${FRONTEND_HOST}:${FRONTEND_PORT}" | head -n 1

echo

if [[ -f .runtime/scheduler.pid ]] && kill -0 "$(cat .runtime/scheduler.pid)" >/dev/null 2>&1; then
  echo "[check] scheduler pid=$(cat .runtime/scheduler.pid)"
else
  echo "[check] scheduler not running"
fi

echo

echo "[done] frontend=http://${FRONTEND_HOST}:${FRONTEND_PORT} backend=http://${BACKEND_HOST}:${BACKEND_PORT}"

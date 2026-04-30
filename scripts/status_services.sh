#!/usr/bin/env bash
set -euo pipefail

BACKEND_PORT="${BACKEND_PORT:-8500}"
FRONTEND_PORT="${FRONTEND_PORT:-5174}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT"

echo "[status] listening ports"
lsof -nP -iTCP -sTCP:LISTEN | egrep ":(${BACKEND_PORT}|${FRONTEND_PORT})\\b" || true

echo

echo "[status] backend health"
curl -sS --max-time 5 "http://${BACKEND_HOST}:${BACKEND_PORT}/healthz" || \
  curl -sS --max-time 5 "http://${BACKEND_HOST}:${BACKEND_PORT}/health" || true

echo

echo "[status] frontend"
curl -I -sS --max-time 5 "http://${FRONTEND_HOST}:${FRONTEND_PORT}" | head -n 1 || true

echo

echo "[status] scheduler"
if [[ -f .runtime/scheduler.pid ]]; then
  pid="$(cat .runtime/scheduler.pid)"
  if kill -0 "$pid" >/dev/null 2>&1; then
    ps -p "$pid" -o pid=,etime=,command=
  else
    echo "stale pid file: $pid"
  fi
elif pgrep -f "tradingagents-scheduler|python -m scheduler.main" >/dev/null 2>&1; then
  pgrep -fal "tradingagents-scheduler|python -m scheduler.main"
else
  echo "scheduler pid file not found"
fi

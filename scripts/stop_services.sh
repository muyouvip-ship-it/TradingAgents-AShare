#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8500}"
FRONTEND_PORT="${FRONTEND_PORT:-5174}"

cd "$ROOT"

for pidfile in .runtime/backend.pid .runtime/frontend.pid .runtime/scheduler.pid; do
  if [[ -f "$pidfile" ]]; then
    pid="$(cat "$pidfile")"
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" || true
    fi
    rm -f "$pidfile"
  fi
done

for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN || true)"
  if [[ -n "$pids" ]]; then
    echo "$pids" | xargs kill || true
  fi
done

pgrep -f "tradingagents-scheduler|python -m scheduler.main" | xargs kill 2>/dev/null || true

echo "[done] stopped backend/frontend/scheduler if they were running"

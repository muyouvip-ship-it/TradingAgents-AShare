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

pid_is_running() {
  local pid="${1:-}"
  [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1
}

read_pidfile() {
  local pidfile="$1"
  [[ -f "$pidfile" ]] || return 1
  tr -d '[:space:]' < "$pidfile"
}

remove_stale_pidfile() {
  local pidfile="$1"
  local label="$2"
  local pid

  pid="$(read_pidfile "$pidfile" || true)"
  if [[ -n "$pid" ]] && ! pid_is_running "$pid"; then
    rm -f "$pidfile"
    echo "[start] removed stale ${label} pid file ($pid)"
  fi
}

write_pidfile_from_port() {
  local pidfile="$1"
  local port="$2"
  local pid

  pid="$(lsof -tiTCP:"$port" -sTCP:LISTEN | head -n 1 || true)"
  [[ -n "$pid" ]] && printf '%s\n' "$pid" > "$pidfile"
}

wait_for_port() {
  local host="$1"
  local port="$2"
  local timeout="${3:-15}"
  local elapsed=0

  while (( elapsed < timeout )); do
    if curl -sS --max-time 2 "http://${host}:${port}" >/dev/null 2>&1 || \
       lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    ((elapsed+=1))
  done

  return 1
}

wait_for_pid() {
  local pid="$1"
  local timeout="${2:-10}"
  local elapsed=0

  while (( elapsed < timeout )); do
    if pid_is_running "$pid"; then
      return 0
    fi
    sleep 1
    ((elapsed+=1))
  done

  return 1
}

tail_log() {
  local logfile="$1"
  if [[ -f "$logfile" ]]; then
    echo "[start] recent log: $logfile"
    tail -n 40 "$logfile" || true
  fi
}

echo "[start] root=$ROOT"
remove_stale_pidfile .runtime/backend.pid backend
remove_stale_pidfile .runtime/frontend.pid frontend
remove_stale_pidfile .runtime/scheduler.pid scheduler

status=0

if lsof -iTCP:"$BACKEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[start] backend already listening on :$BACKEND_PORT"
  write_pidfile_from_port .runtime/backend.pid "$BACKEND_PORT"
else
  echo "[start] starting backend on :$BACKEND_PORT"
  nohup uv run uvicorn api.app:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" \
    > .runtime/backend.log 2>&1 &
  echo $! > .runtime/backend.pid
  if ! wait_for_port "$BACKEND_HOST" "$BACKEND_PORT" 20; then
    echo "[start] backend failed to become ready on :$BACKEND_PORT"
    tail_log .runtime/backend.log
    status=1
  else
    write_pidfile_from_port .runtime/backend.pid "$BACKEND_PORT"
  fi
fi

if [[ -f .runtime/scheduler.pid ]] && pid_is_running "$(read_pidfile .runtime/scheduler.pid)"; then
  echo "[start] scheduler already running with pid $(read_pidfile .runtime/scheduler.pid)"
elif pgrep -f "$SCHEDULER_CMD_PATTERN" >/dev/null 2>&1; then
  echo "[start] scheduler already running (matched pattern: $SCHEDULER_CMD_PATTERN)"
  pgrep -fo "$SCHEDULER_CMD_PATTERN" > .runtime/scheduler.pid
else
  echo "[start] starting scheduler"
  nohup uv run tradingagents-scheduler > .runtime/scheduler.log 2>&1 &
  echo $! > .runtime/scheduler.pid
  if ! wait_for_pid "$(read_pidfile .runtime/scheduler.pid)" 10; then
    echo "[start] scheduler exited during startup"
    tail_log .runtime/scheduler.log
    rm -f .runtime/scheduler.pid
    status=1
  fi
fi

if lsof -iTCP:"$FRONTEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[start] frontend already listening on :$FRONTEND_PORT"
  write_pidfile_from_port .runtime/frontend.pid "$FRONTEND_PORT"
else
  echo "[start] starting frontend on :$FRONTEND_PORT"
  cd "$ROOT/frontend"
  nohup npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" \
    > "$ROOT/.runtime/frontend.log" 2>&1 &
  echo $! > "$ROOT/.runtime/frontend.pid"
  cd "$ROOT"
  if ! wait_for_port "$FRONTEND_HOST" "$FRONTEND_PORT" 20; then
    echo "[start] frontend failed to become ready on :$FRONTEND_PORT"
    tail_log .runtime/frontend.log
    rm -f .runtime/frontend.pid
    status=1
  else
    write_pidfile_from_port .runtime/frontend.pid "$FRONTEND_PORT"
  fi
fi

echo "[check] backend"
curl -sS --max-time 8 "http://${BACKEND_HOST}:${BACKEND_PORT}/healthz" || \
  curl -sS --max-time 8 "http://${BACKEND_HOST}:${BACKEND_PORT}/health"

echo

echo "[check] frontend"
curl -I -sS --max-time 8 "http://${FRONTEND_HOST}:${FRONTEND_PORT}" | head -n 1

echo

if [[ -f .runtime/scheduler.pid ]] && pid_is_running "$(read_pidfile .runtime/scheduler.pid)"; then
  echo "[check] scheduler pid=$(read_pidfile .runtime/scheduler.pid)"
else
  echo "[check] scheduler not running"
  tail_log .runtime/scheduler.log
  status=1
fi

echo

echo "[done] frontend=http://${FRONTEND_HOST}:${FRONTEND_PORT} backend=http://${BACKEND_HOST}:${BACKEND_PORT}"
exit "$status"

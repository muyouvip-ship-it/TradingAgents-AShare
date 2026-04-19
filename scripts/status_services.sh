#!/usr/bin/env bash
set -euo pipefail

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5174}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"

echo "[status] listening ports"
lsof -iTCP -sTCP:LISTEN | egrep ":(${BACKEND_PORT}|${FRONTEND_PORT})\\b" || true

echo

echo "[status] backend health"
curl -sS --max-time 5 "http://${BACKEND_HOST}:${BACKEND_PORT}/healthz" || \
  curl -sS --max-time 5 "http://${BACKEND_HOST}:${BACKEND_PORT}/health" || true

echo

echo "[status] frontend"
curl -I -sS --max-time 5 "http://${FRONTEND_HOST}:${FRONTEND_PORT}" | head -n 1 || true

#!/usr/bin/env bash
set -e
PORT="${PORT:-8000}"

exec gunicorn "app:app" \
  -k uvicorn.workers.UvicornWorker \
  --bind "0.0.0.0:${PORT}" \
  --workers 2 \
  --timeout 600
#!/bin/bash
# Production startup: Flask (gunicorn) + Node.js WhatsApp service.
# Usage: ./scripts/start.sh
# Both processes are managed as children; SIGTERM cleanly kills both.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

trap 'kill 0' EXIT SIGINT SIGTERM

echo "Starting DREAM-Chat (production mode)..."

# Build and start Node.js WhatsApp service
cd "$PROJECT_DIR/whatsapp" && npm run build && npm run start &
WA_PID=$!
echo "WhatsApp service started (PID $WA_PID)"

# Start Flask with gunicorn (production settings)
cd "$PROJECT_DIR"
gunicorn app:app \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers 1 \
  --worker-class gevent \
  --worker-connections 1000 \
  --timeout 300 \
  --access-logfile - \
  --error-logfile - &
FLASK_PID=$!
echo "Flask server started (PID $FLASK_PID)"

echo "DREAM-Chat is running."
wait

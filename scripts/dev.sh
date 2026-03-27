#!/bin/bash
# Development startup: Flask with hot-reload + Node.js WhatsApp with watch mode.
# Usage: ./scripts/dev.sh
# Both processes are managed as children; Ctrl+C cleanly kills both.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

trap 'kill 0' EXIT SIGINT SIGTERM

echo "Starting DREAM-Chat (development mode)..."

# Start Node.js WhatsApp service with file-watching
cd "$PROJECT_DIR/whatsapp" && npm run dev &
WA_PID=$!
echo "WhatsApp service started (PID $WA_PID)"

# Start Flask with gunicorn hot-reload
cd "$PROJECT_DIR"
gunicorn app:app \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers 1 \
  --timeout 300 \
  --reload \
  --access-logfile - \
  --error-logfile - &
FLASK_PID=$!
echo "Flask server started (PID $FLASK_PID)"

echo "DREAM-Chat is running. Press Ctrl+C to stop."
wait

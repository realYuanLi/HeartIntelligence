#!/bin/bash
set -e

# Set default port if not provided
PORT="${PORT:-8000}"

# Install dependencies if needed
pip install -r requirements.txt

# Start the application
exec gunicorn app:app \
  --bind 0.0.0.0:$PORT \
  --workers 1 \
  --timeout 600 \
  --worker-class sync \
  --access-logfile - \
  --error-logfile -
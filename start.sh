#!/bin/bash
# Startup script for Railway deployment

echo "Starting DREAM-Chat application..."

# Set environment variables if not set
export PORT=${PORT:-8000}
export SECRET_KEY=${SECRET_KEY:-"default-secret-key-change-in-production"}

# Start the application
echo "Starting gunicorn on port $PORT"
exec gunicorn app:app \
    --bind 0.0.0.0:$PORT \
    --workers 1 \
    --timeout 120 \
    --keep-alive 2 \
    --max-requests 1000 \
    --max-requests-jitter 100

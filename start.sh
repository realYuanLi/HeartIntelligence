#!/bin/bash
# Startup script for Railway deployment

echo "Starting DREAM-Chat application..."

# Set environment variables if not set
export PORT=${PORT:-8000}
export SECRET_KEY=${SECRET_KEY:-"default-secret-key-change-in-production"}

# Start the application with increased timeout for health data processing
echo "Starting gunicorn on port $PORT with 300s timeout"
exec gunicorn app:app \
    --bind 0.0.0.0:$PORT \
    --workers 1 \
    --worker-class gevent \
    --worker-connections 1000 \
    --timeout 300 \
    --keep-alive 5 \
    --max-requests 1000 \
    --max-requests-jitter 100

#!/bin/bash
set -e

echo "=== Starting VANI 2.0 Unified Service ==="

# 1. Start LiveKit Voice Agent in the background
echo "Starting LiveKit Voice Agent worker..."
python agent.py start &

# 2. Start FastAPI Backend in the foreground on Render's assigned $PORT
PORT=${PORT:-8000}
echo "Starting FastAPI Backend on port $PORT..."
exec uvicorn backend.app.main:app --host 0.0.0.0 --port "$PORT"

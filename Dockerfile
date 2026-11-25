# ========================================================
# VANI 2.0 - Production Dockerfile for Render Free Tier
# Runs both FastAPI Backend & LiveKit Voice Agent in 1 service
# ========================================================
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install build tools and C/audio libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    python3-dev \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download model weights (Silero VAD) during build
RUN python -m livekit.agents download-files || true

# Copy codebase
COPY . .

# Ensure startup script is executable
RUN chmod +x start.sh

# Render dynamically injects $PORT
EXPOSE 8000

CMD ["./start.sh"]

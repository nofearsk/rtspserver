#!/bin/bash

# RTSP to HLS Server - Startup Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check for FFmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "ERROR: FFmpeg is required but not installed."
    echo "Install with: sudo apt install ffmpeg"
    exit 1
fi

if ! command -v ffprobe &> /dev/null; then
    echo "ERROR: ffprobe is required but not installed."
    echo "Install with: sudo apt install ffmpeg"
    exit 1
fi

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is required but not installed."
    exit 1
fi

# Create virtual environment if needed
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install/upgrade dependencies
echo "Installing dependencies..."
pip install -q -r requirements.txt

# Create .env file if not exists
if [ ! -f ".env" ]; then
    echo "Creating default .env file..."
    cat > .env << 'EOF'
# RTSP to HLS Server Configuration

# Server settings
RTSP_HOST=0.0.0.0
RTSP_PORT=8000
RTSP_DEBUG=false

# Security - CHANGE THESE IN PRODUCTION!
RTSP_SECRET_KEY=change-this-to-a-secure-random-string
RTSP_API_KEY=your-api-key-here

# Token settings
RTSP_TOKEN_EXPIRY_HOURS=24

# HLS settings
RTSP_HLS_TIME=2
RTSP_HLS_LIST_SIZE=5

# Stream defaults
RTSP_DEFAULT_MODE=on_demand
RTSP_KEEP_ALIVE_SECONDS=60
RTSP_MAX_STREAMS=50
EOF
    echo "Please edit .env to set your API key and secret key!"
fi

echo ""
echo "Starting RTSP to HLS Server..."
echo "================================"
echo "Web UI:     http://localhost:8000"
echo "API Docs:   http://localhost:8000/docs (when debug=true)"
echo ""

# Run server
python main.py

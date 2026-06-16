#!/bin/bash
# K-Box local launcher script for macOS testing

echo "========================================="
echo "  K-Box Karaoke Transfer System (macOS)"
echo "========================================="
echo ""

if [ ! -d ".venv" ]; then
    echo "[ERROR] Virtual environment .venv not found. Please initialize first."
    exit 1
fi

# Activate venv and start backend
source .venv/bin/activate
python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8080 &
BACKEND_PID=$!

# Wait for backend to boot
sleep 2

# Open in browser
open http://localhost:8080/

# Trap Ctrl+C to stop backend process gracefully
trap "kill $BACKEND_PID" EXIT

echo "K-Box is running. Press Ctrl+C in this terminal to stop."
wait

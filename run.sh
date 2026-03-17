#!/bin/bash
# Start the AI Intake Widget server
# Usage: ./run.sh
# Then open http://localhost:8000 in your browser

if [ ! -f .env ]; then
    echo "⚠  No .env file found. Copying from .env.example..."
    cp .env.example .env
    echo "   Edit .env and add your ANTHROPIC_API_KEY, then re-run."
    exit 1
fi

source .env
if [ -z "$ANTHROPIC_API_KEY" ] || [ "$ANTHROPIC_API_KEY" = "your-api-key-here" ]; then
    echo "⚠  Set your ANTHROPIC_API_KEY in .env first."
    exit 1
fi

echo "Starting AI Intake Widget..."
echo "Open http://localhost:8000 to see the demo"
echo ""
cd backend && python3 -m uvicorn app:app --reload --host 0.0.0.0 --port 8000

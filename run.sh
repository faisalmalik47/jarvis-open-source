#!/bin/bash
# ==============================================================================
# J.A.R.V.I.S. Real-Time Assistant Launcher for macOS
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "======================================================"
echo "  🤖 J.A.R.V.I.S. Real-Time macOS Voice Assistant"
echo "======================================================"

# Check for .env file
if [ ! -f ".env" ]; then
    cp .env.example .env
fi

# Support resetting key via argument
if [ "$1" = "--reset-key" ] || [ "$1" = "-k" ]; then
    sed -i '' "s/^GEMINI_API_KEY=.*/GEMINI_API_KEY=your_gemini_api_key_here/" .env 2>/dev/null || true
fi

# Check for API key
API_KEY=$(grep -E "^GEMINI_API_KEY=" .env | cut -d '=' -f2- | tr -d ' "')
if [ -z "$API_KEY" ] || [ "$API_KEY" = "your_gemini_api_key_here" ]; then
    echo ""
    echo "⚠️  GEMINI_API_KEY is not configured."
    echo "Get a free API key at: https://aistudio.google.com/apikey"
    echo ""
    read -p "👉 Paste your Gemini API Key here: " USER_KEY
    if [ -n "$USER_KEY" ]; then
        # Replace or append key in .env
        sed -i '' "s/^GEMINI_API_KEY=.*/GEMINI_API_KEY=$USER_KEY/" .env 2>/dev/null || echo "GEMINI_API_KEY=$USER_KEY" >> .env
        echo "✅ API key saved to .env"
    fi
fi

# Ensure virtualenv exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
    CFLAGS="-I/opt/homebrew/include" LDFLAGS="-L/opt/homebrew/lib" ./venv/bin/pip install -r requirements.txt
fi

echo ""
echo "🚀 Starting JARVIS voice stream..."
exec ./venv/bin/python jarvis.py

#!/usr/bin/env bash
set -e

echo ""
echo "==================================="
echo "  ZOIA Patch Builder — Setup"
echo "==================================="
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "ERROR: Python 3 is required but not installed."
    echo "  Mac:   brew install python3"
    echo "  Linux: sudo apt install python3 python3-venv"
    exit 1
fi

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
else
    echo "Virtual environment already exists."
fi

echo "Installing dependencies..."
source venv/bin/activate
pip install -q -r requirements.txt

# Check for backends
echo ""
OLLAMA_OK=false
if command -v ollama &>/dev/null; then
    if curl -s http://localhost:11434/api/tags &>/dev/null; then
        MODELS=$(curl -s http://localhost:11434/api/tags | python3 -c "
import sys, json
data = json.load(sys.stdin)
names = [m['name'] for m in data.get('models', [])]
print(', '.join(names) if names else 'none')
" 2>/dev/null || echo "none")
        if [ "$MODELS" != "none" ]; then
            echo "Found Ollama with models: $MODELS"
            OLLAMA_OK=true
        else
            echo "Ollama is running but has no models."
            echo "  Pull one with: ollama pull gemma4:26b"
        fi
    else
        echo "Ollama is installed but not running. Start it first."
    fi
fi

# Gemini API key
if [ -z "$GEMINI_API_KEY" ]; then
    if [ "$OLLAMA_OK" = false ]; then
        echo ""
        echo "No local model found. You'll need a Gemini API key (free)."
        echo "  Get one at: https://aistudio.google.com/apikey"
        echo ""
        read -rp "Paste your Gemini API key (or press Enter to skip): " key
        if [ -n "$key" ]; then
            echo "GEMINI_API_KEY='$key'" > .env
            echo "Saved to .env"
        else
            echo "Skipped. You can set it later: export GEMINI_API_KEY='your-key'"
        fi
    fi
else
    echo "Gemini API key found in environment."
fi

echo ""
echo "==================================="
echo "  Setup complete!"
echo "==================================="
echo ""
echo "To start the app, run:"
echo ""
echo "  bash run.sh"
echo ""

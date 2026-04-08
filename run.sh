#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "Run setup first:  bash setup.sh"
    exit 1
fi

# Load saved API key if present
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

source venv/bin/activate
python app.py

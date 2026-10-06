#!/usr/bin/env bash
echo "========================================================"
echo "  SafeRoute - Intelligent Route & Hazard Platform"
echo "========================================================"
cd "$(dirname "$0")/Saferoute-backend/saferoute"

if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 is not installed or not in PATH."
    echo "Please install Python 3.10+ from https://www.python.org/"
    exit 1
fi

if [ ! -f "../venv/bin/python" ]; then
    echo "[*] First time setup: Creating Python virtual environment..."
    python3 -m venv ../venv
    echo "[*] Installing dependencies from requirements.txt..."
    ../venv/bin/pip install -r requirements.txt
    echo "[*] Environment ready!"
fi

echo "[*] Starting SafeRoute Server at http://127.0.0.1:5001 ..."
python3 -m webbrowser "http://127.0.0.1:5001" 2>/dev/null || open "http://127.0.0.1:5001" 2>/dev/null || xdg-open "http://127.0.0.1:5001" 2>/dev/null || true
../venv/bin/python run.py

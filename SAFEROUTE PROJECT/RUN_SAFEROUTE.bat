@echo off
title SafeRoute - Emergency Route and Hazard Information Platform
color 0A
echo ========================================================
echo   SafeRoute - Intelligent Route ^& Hazard Platform
echo ========================================================
echo.

cd /d "%~dp0Saferoute-backend\saferoute"

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in your PATH!
    echo Please install Python 3.10+ from https://www.python.org/
    echo Remember to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

if not exist "..\venv\Scripts\python.exe" (
    echo [*] First time setup: Creating Python virtual environment...
    python -m venv "..\venv"
    echo [*] Installing dependencies from requirements.txt...
    "..\venv\Scripts\pip.exe" install -r requirements.txt
    echo [*] Environment ready!
    echo.
)

echo [*] Launching SafeRoute at http://127.0.0.1:5001 ...
echo [*] Press Ctrl+C anytime to stop the server.
echo.

start "" "http://127.0.0.1:5001"
"..\venv\Scripts\python.exe" run.py


pause

@echo off
chcp 65001 > nul
title Product Collector

echo ============================================
echo   Product Collector - Run Script
echo ============================================
echo.

cd /d "%~dp0"

REM Check Python installation
python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed.
    echo Please install Python 3.10+: https://www.python.org/downloads/
    echo IMPORTANT: Check "Add Python to PATH" during installation!
    pause
    exit /b 1
)

REM Check dependencies
echo Checking dependencies...
python -c "import customtkinter" > nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    python -m pip install -r requirements.txt
    python -m playwright install chromium
)

echo Starting application...
echo.

REM Run GUI app
python app.py

pause

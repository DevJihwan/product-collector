@echo off
chcp 65001 > nul
echo ============================================
echo   Product Collector - Windows Build Script
echo ============================================
echo.

REM Change to script directory (handles spaces in path)
cd /d "%~dp0"
echo Current directory: %CD%
echo.

REM ============================================
REM Check Python Installation
REM ============================================
echo [1/6] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo.
    echo Please install Python from https://www.python.org/downloads/
    echo IMPORTANT: Check "Add Python to PATH" during installation!
    echo.
    pause
    exit /b 1
)
python --version
echo.

REM ============================================
REM Create Virtual Environment
REM ============================================
echo [2/6] Setting up virtual environment...
if exist "venv" (
    echo Virtual environment already exists.
) else (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        echo Try moving the project to a simpler path like C:\collector
        pause
        exit /b 1
    )
)
echo.

REM ============================================
REM Activate Virtual Environment
REM ============================================
echo [3/6] Activating virtual environment...
if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] venv activation script not found.
    echo Try deleting venv folder and run again.
    pause
    exit /b 1
)
call "venv\Scripts\activate.bat"
echo.

REM ============================================
REM Install Dependencies
REM ============================================
echo [4/6] Installing dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)
echo.

REM ============================================
REM Install Playwright Browsers
REM ============================================
echo [5/6] Installing Playwright browsers...
python -m playwright install chromium
if errorlevel 1 (
    echo [WARNING] Failed to install Playwright browsers.
    echo You may need to run: playwright install chromium
)
echo.

REM ============================================
REM Build EXE
REM ============================================
echo [6/6] Building exe file...
python -m PyInstaller --clean collector.spec
if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Build Complete!
echo ============================================
echo.
echo Output: dist\ProductCollector.exe
echo.
echo [IMPORTANT] Before running the exe:
echo   1. Install Chrome browser (if not installed)
echo   2. Run: playwright install chromium
echo      (Required for browser automation)
echo.

if exist "dist" explorer "dist"
pause

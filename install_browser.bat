@echo off
chcp 65001 > nul
echo ============================================
echo   Playwright Browser Installation
echo ============================================
echo.
echo This script installs the browser required
echo for the Product Collector program.
echo.
echo Please wait...
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed.
    echo.
    echo Please install Python first:
    echo https://www.python.org/downloads/
    echo.
    echo IMPORTANT: Check "Add Python to PATH" during installation!
    echo.
    pause
    exit /b 1
)

REM Install playwright
echo Installing Playwright...
python -m pip install playwright
if errorlevel 1 (
    echo [ERROR] Failed to install Playwright.
    pause
    exit /b 1
)

REM Install browser
echo.
echo Installing Chromium browser...
python -m playwright install chromium
if errorlevel 1 (
    echo [ERROR] Failed to install browser.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Installation Complete!
echo ============================================
echo.
echo You can now run ProductCollector.exe
echo.
pause

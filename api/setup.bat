@echo off
title Nexa Setup
color 0A
echo.
echo  ==========================================
echo   NEXA -- Automated Setup for Windows
echo  ==========================================
echo.

REM Step 1: Check Python
echo [1/7] Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Python not found. Install from python.org then re-run.
    pause
    exit /b 1
)
python --version
echo  Python OK.
echo.

REM Step 2: Create virtual environment
echo [2/7] Creating virtual environment...
if not exist "venv" (
    py -3.11 -m venv venv
    if %errorlevel% neq 0 (
        echo  ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo  Virtual environment created.
) else (
    echo  Virtual environment already exists.
)
echo.

REM Step 3: Install dependencies
echo [3/7] Installing Python dependencies...
echo  This takes 2-3 minutes. Please wait...
echo.

venv\Scripts\python.exe -m pip install --upgrade pip --quiet

venv\Scripts\pip.exe install -r requirements.txt --prefer-binary --quiet

if %errorlevel% neq 0 (
    echo  ERROR: Installation failed. Try running manually:
    echo    venv\Scripts\pip.exe install -r requirements.txt --prefer-binary
    pause
    exit /b 1
)
echo  Dependencies installed.
echo.

REM Step 4: Install Playwright browser
echo [4/7] Installing Playwright Chromium (~150MB)...
echo  This takes 3-5 minutes. Please wait...
echo.
venv\Scripts\python.exe -m playwright install chromium
if %errorlevel% neq 0 (
    echo  ERROR: Playwright failed. Try manually:
    echo    venv\Scripts\python.exe -m playwright install chromium
    pause
    exit /b 1
)
echo  Playwright ready.
echo.

REM Step 5: Check .env
echo [5/7] Checking configuration...
if not exist ".env" (
    echo  ERROR: .env file not found in this folder.
    pause
    exit /b 1
)
echo  .env file found.
echo.

REM Step 6: Test MongoDB
echo [6/7] Testing MongoDB connection...
venv\Scripts\python.exe test_mongo.py
echo.

REM Step 7: Start server
echo [7/7] Starting Nexa API server...
echo.
echo  API running at:  http://localhost:8000
echo  API docs at:     http://localhost:8000/docs
echo.
echo  ==========================================
echo   To run the scraper (separate window):
echo     venv\Scripts\activate
echo     python scraper\scheduler.py
echo  ==========================================
echo.
echo  Press Ctrl+C to stop the server.
echo.

venv\Scripts\uvicorn.exe api.main:app --host 0.0.0.0 --port 8000 --reload

pause

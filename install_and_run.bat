@echo off
setlocal enabledelayedexpansion

title AI Agent Project - Setup and Run
echo ===================================================
echo       AI Agent Project - One-Click Setup & Run
echo ===================================================
echo.

REM --- 1. Environment Check ---

echo [Checking Environment...]

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.10+ from https://www.python.org/
    echo.
    pause
    exit /b
) else (
    echo [OK] Python found.
)

REM Check Node.js
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js is not installed or not in PATH.
    echo Please install Node.js (LTS) from https://nodejs.org/
    echo.
    pause
    exit /b
) else (
    echo [OK] Node.js found.
)

echo.
echo ---------------------------------------------------
echo.

REM --- 2. Backend Setup ---

echo [1/4] Installing Backend Dependencies...
cd /d "%~dp0backend"
if exist "requirements.txt" (
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install backend dependencies.
        pause
        exit /b
    )
) else (
    echo [WARNING] requirements.txt not found in backend directory.
)

echo.
echo ---------------------------------------------------
echo.

REM --- 3. Frontend Setup ---

echo [2/4] Installing Frontend Dependencies...
cd /d "%~dp0frontend"
if exist "package.json" (
    call npm install
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install frontend dependencies.
        pause
        exit /b
    )
) else (
    echo [WARNING] package.json not found in frontend directory.
)

echo.
echo ---------------------------------------------------
echo.

REM --- 4. Start Services ---

echo [3/4] Starting Backend Service...
REM Start Backend in a new window. Using port 8000 as per current config.
start "AI Agent Backend" cmd /k "cd /d "%~dp0backend" && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

echo [4/4] Starting Frontend Service...
REM Start Frontend in a new window.
start "AI Agent Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo ===================================================
echo    All services are starting...
echo    Browser will open in 5 seconds.
echo ===================================================
echo.

timeout /t 5 >nul
start http://localhost:3000

echo You can minimize this window.
echo To stop servers, close the "AI Agent Backend" and "AI Agent Frontend" windows.
pause

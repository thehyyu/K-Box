@echo off
title K-Box Karaoke System Launcher

echo =======================================================
echo         K-Box Karaoke System Launcher
echo =======================================================
echo.

REM Check if virtual environment exists
if not exist ".venv" (
    echo [ERROR] Python virtual environment .venv not found.
    echo Please make sure you have run the initialization setup.
    echo.
    pause
    exit /b 1
)

REM Kill any stale processes running on Port 8080 to prevent conflicts and ensure code updates apply
echo 0. Cleaning up stale server instances on Port 8080...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr 8080') do taskkill /F /PID %%a 2>nul

REM Start FastAPI backend service
echo 1. Starting K-Box Backend Server...
start "K-Box Backend Server" cmd /c "call .venv\Scripts\activate && python -m uvicorn backend.main:app --host 127.0.0.1 --port 8080"

REM Wait 2 seconds for server to load
timeout /t 2 /nobreak > nul

REM Open Web Console in default browser
echo 2. Opening Web Application Console...
start http://localhost:8080/

echo.
echo =======================================================
echo   K-Box System Started Successfully!
echo   * Please KEEP this black console window open to use the web app.
echo   * To stop K-Box, simply close this console window.
echo =======================================================
echo.
pause

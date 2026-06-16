@echo off
title K-Box 卡拉OK伴唱整理系統
chcp 65001 > nul

echo =======================================================
echo         K-Box 卡拉OK伴唱整理系統 - 啟動主控台
echo ========================================================
echo.

:: 檢查虛擬環境是否存在
if not exist ".venv" (
    echo [錯誤] 找不到 Python 虛擬環境 (.venv)。
    echo 請確保您已經在專案根目錄下運行過初始化命令。
    echo.
    pause
    exit /b 1
)

:: 啟動 FastAPI 後端服務
echo 1. 正在啟動 K-Box 後端核心服務...
start "K-Box Backend Server" cmd /c "call .venv\Scripts\activate && python -m uvicorn backend.main:app --host 127.0.0.1 --port 8080"

:: 等待 2 秒鐘讓伺服器載入
timeout /t 2 /nobreak > nul

:: 用預設瀏覽器開啟網頁介面
echo 2. 正在開啟點歌與建庫網頁介面...
start http://localhost:8080/

echo.
echo ========================================================
echo   K-Box 系統已順利開啟！
echo   ※ 請保持此黑色主控台視窗開啟，才能正常使用網頁功能。
echo   ※ 結束歌唱與整理後，直接關閉此黑色視窗即可。
echo ========================================================
echo.
pause

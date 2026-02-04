@echo off
setlocal
chcp 65001 >nul
title Minecraft 伺服器管理器 - 程式碼格式化工具

echo ========================================================
echo   Minecraft 伺服器管理器 - 程式碼格式化工具
echo ========================================================
echo.

if not exist "pyproject.toml" (
    echo 錯誤: 找不到 pyproject.toml 檔案
    pause
    exit /b 1
)

echo [1/2] 執行 Ruff 全能優化 (Imports、格式化、靜態檢查)...
echo   - 步驟 1: 排序 Imports
uv run ruff check --select I --fix src
echo   - 步驟 2: 程式碼格式化
uv run ruff format src
echo   - 步驟 3: 靜態程式碼檢查與清理
uv run ruff check --fix --unsafe-fixes --select E,F,W,UP,B,C4,SIM,PIE,T20,RET,ARG,ERA,RUF100 --ignore E402,B023,E501 src
echo.

echo [2/2] 執行 Mypy 型別檢查...
uv run mypy src
echo.

echo ========================================================
echo   程式碼格式化完成！
echo ========================================================
pause

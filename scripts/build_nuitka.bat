@echo off
chcp 65001 > nul
setlocal
title Minecraft 伺服器管理器 - Nuitka 高效能打包腳本 (Dev)

echo ========================================================
echo   Minecraft 伺服器管理器 - Nuitka 高效能打包腳本
echo ========================================================

:: 1. 檢查是否安裝 uv (使用 py 啟動器)
py -m uv --version >nul 2>nul
if %errorlevel% neq 0 (
    echo [錯誤] 未檢測到 uv。請先安裝: py -m pip install uv
    pause
    exit /b 1
)

:: 2. 建立/同步 uv 虛擬環境
if not exist ".venv\Scripts\python.exe" (
    echo [資訊] 建立 .venv...
    py -m uv venv .venv
)

echo [資訊] 同步依賴 (uv sync)...
py -m uv lock
py -m uv sync

echo [資訊] 清理舊的建置檔案...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "main.dist" rmdir /s /q "main.dist"
if exist "main.build" rmdir /s /q "main.build"
if exist "main.onefile-build" rmdir /s /q "main.onefile-build"

echo [資訊] 開始 Nuitka 編譯...
echo        這可能需要幾分鐘時間，請耐心等待。

:: Nuitka 編譯命令 (Standalone 模式)
py -m uv run python -m nuitka ^
    --standalone ^
    --enable-plugin=tk-inter ^
    --include-package-data=customtkinter ^
    --include-package=src ^
    --python-flag=no_docstrings ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=assets/icon.ico ^
    --include-data-dir=assets=assets ^
    --include-data-file=README.md=README.md ^
    --include-data-file=LICENSE=LICENSE ^
    --include-data-file=pyproject.toml=pyproject.toml ^
    --include-data-file=uv.lock=uv.lock ^
    --nofollow-import-to=tkinter.test ^
    --nofollow-import-to=unittest ^
    --nofollow-import-to=pydoc ^
    --nofollow-import-to=distutils ^
    --output-dir=dist ^
    --output-filename=MinecraftServerManager.exe ^
    --assume-yes-for-downloads ^
    --msvc=latest ^
    src\main.py

if %errorlevel% neq 0 (
    echo [失敗] 編譯過程中發生錯誤。
    pause
    exit /b 1
)

:: 處理 Nuitka 輸出目錄名稱 (統一格式)
:: Nuitka 預設會產生 main.dist 或 MinecraftServerManager.dist
if exist "dist\main.dist" (
    move "dist\main.dist" "dist\MinecraftServerManager"
) else if exist "dist\MinecraftServerManager.dist" (
    move "dist\MinecraftServerManager.dist" "dist\MinecraftServerManager"
)

echo ========================================================
echo   打包完成！
echo   執行檔位置: dist\MinecraftServerManager\MinecraftServerManager.exe
echo ========================================================
pause

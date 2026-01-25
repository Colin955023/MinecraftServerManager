@echo off
setlocal
chcp 65001 >nul
title Minecraft 伺服器管理器 - Nuitka 打包與安裝檔建置
cd /d %~dp0..

REM 讀取版本資訊
for /f "delims=" %%A in ('py -c "from src.version_info import APP_VERSION; print(APP_VERSION)"') do set APP_VERSION=%%A
for /f "delims=" %%A in ('py -c "from src.version_info import APP_NAME; print(APP_NAME)"') do set APP_NAME=%%A

if "%APP_VERSION%"=="" set APP_VERSION=1.6
if "%APP_NAME%"=="" set APP_NAME=MinecraftServerManager

echo ========================================================
echo   正在建置 %APP_NAME% v%APP_VERSION% (Nuitka)
echo ========================================================

echo [1/4] 清除舊的建置檔案...
if exist build rmdir /S /Q build
if exist dist rmdir /S /Q dist
if exist main.dist rmdir /S /Q main.dist
if exist main.build rmdir /S /Q main.build

echo [2/4] 檢查並安裝依賴...
py -m uv --version >nul 2>nul
if errorlevel 1 (
    echo [錯誤] 未偵測到 uv。請先安裝: py -m pip install uv
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [資訊] 建立 .venv...
    py -m uv venv .venv
)

echo [資訊] 同步依賴 (uv sync)...
py -m uv sync
if errorlevel 1 (
    echo [錯誤] 依賴同步失敗。
    pause
    exit /b 1
)

echo [3/4] 執行 Nuitka 打包 (Standalone 模式)...
:: Nuitka 編譯命令 (Standalone = 資料夾模式)
:: 注意：我們需要將輸出資料夾重新命名為 MinecraftServerManager 以配合 Inno Setup 腳本
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

if errorlevel 1 (
    echo [失敗] Nuitka 打包失敗。
    pause
    exit /b 1
)

echo [資訊] 等待系統釋放檔案鎖定 (防止 Access denied)...
timeout /t 3 /nobreak >nul

:: 處理 Nuitka 輸出目錄名稱
:: Nuitka 預設會產生 main.dist 或 MinecraftServerManager.dist
:: 我們需要將其重新命名為 MinecraftServerManager
if exist "dist\main.dist" (
    if exist "dist\MinecraftServerManager" rmdir /S /Q "dist\MinecraftServerManager"
    move "dist\main.dist" "dist\MinecraftServerManager"
) else if exist "dist\MinecraftServerManager.dist" (
    if exist "dist\MinecraftServerManager" rmdir /S /Q "dist\MinecraftServerManager"
    move "dist\MinecraftServerManager.dist" "dist\MinecraftServerManager"
)

if not exist "dist\MinecraftServerManager\MinecraftServerManager.exe" (
    echo [錯誤] 找不到編譯後的執行檔，目錄結構可能不正確。
    pause
    exit /b 1
)

echo [4/4] 編譯 Inno Setup 安裝檔...
set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo [錯誤] 找不到 Inno Setup 編譯器。
  echo 路徑："%ISCC%"
  echo 請安裝 Inno Setup 6 - https://jrsoftware.org/isdl.php - 或調整此路徑。
  pause
  exit /b 1
)

"%ISCC%" /DAppVersion=%APP_VERSION% /DAppName="%APP_NAME%" scripts\installer.iss
if errorlevel 1 (
    echo [失敗] Inno Setup 編譯失敗。
    pause
    exit /b 1
)

echo ========================================================
echo   建置完成! (Build Complete)
echo   Installer Location: dist\installer\
echo ========================================================
pause

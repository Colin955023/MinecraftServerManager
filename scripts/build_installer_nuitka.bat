@echo off
setlocal
chcp 65001 >nul
title Minecraft 伺服器管理器 - Nuitka 打包與安裝檔建置
cd /d %~dp0..
REM 讀取版本資訊

echo [資訊] 正在讀取版本資訊...

for /f "delims=" %%A in ('py -c "from src.version_info import APP_VERSION; print(APP_VERSION)" 2^>nul') do set APP_VERSION=%%A
for /f "delims=" %%A in ('py -c "from src.version_info import APP_NAME; print(APP_NAME)" 2^>nul') do set APP_NAME=%%A

if "%APP_VERSION%"=="" (

    echo [警告] 無法讀取 APP_VERSION，使用預設值 1.6.2

    set APP_VERSION=1.6.2
) else (
    echo [成功] 版本號: %APP_VERSION%
)

if "%APP_NAME%"=="" (
    echo [警告] 無法讀取 APP_NAME，使用預設值 Minecraft Server Manager

    set APP_NAME=Minecraft Server Manager
) else (
    echo [成功] 應用程式名稱: %APP_NAME%
)

REM 設定用於檔案名稱的簡短 ID（無空格）
set APP_ID=MinecraftServerManager
echo [成功] 檔案 ID: %APP_ID%

echo.

echo ========================================================
echo   正在建置 %APP_NAME% v%APP_VERSION% (Nuitka)

echo   檔案 ID: %APP_ID%
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

echo [資訊] 清理虛擬環境...
if exist ".venv" rmdir /S /Q ".venv"

echo [資訊] 建立全新虛擬環境...
py -m uv venv .venv

echo [資訊] 安裝生產依賴（不含開發工具）...
py -m uv pip install --python .venv\Scripts\python.exe psutil toml customtkinter requests defusedxml
if errorlevel 1 (
    echo [錯誤] 依賴安裝失敗。

    pause
    exit /b 1
)

echo [資訊] 安裝 Nuitka（用於打包）...
py -m uv pip install --python .venv\Scripts\python.exe nuitka>=2.8.9
if errorlevel 1 (
    echo [錯誤] Nuitka 安裝失敗。

    pause
    exit /b 1
)

echo [3/4] 執行 Nuitka 打包 (Standalone 模式)...

REM Nuitka 編譯命令 (Standalone = 資料夾模式)
REM 注意：我們需要將輸出資料夾重新命名為 MinecraftServerManager 以配合 Inno Setup 腳本

.venv\Scripts\python.exe -m nuitka ^
    --standalone ^
    --enable-plugin=tk-inter ^
    --include-package-data=customtkinter ^
    --include-package=src ^
    --python-flag=no_docstrings ^
    --python-flag=no_asserts ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=assets/icon.ico ^
    --include-data-dir=assets=assets ^
    --include-data-file=README.md=README.md ^
    --include-data-file=LICENSE=LICENSE ^
    --nofollow-import-to=tkinter.test ^
    --nofollow-import-to=unittest ^
    --nofollow-import-to=test ^
    --nofollow-import-to=pydoc ^
    --nofollow-import-to=pydoc_data ^
    --nofollow-import-to=distutils ^
    --nofollow-import-to=setuptools ^
    --nofollow-import-to=pip ^
    --nofollow-import-to=email ^
    --nofollow-import-to=html.parser ^
    --nofollow-import-to=xml.dom ^
    --nofollow-import-to=xml.sax ^
    --nofollow-import-to=xmlrpc ^
    --nofollow-import-to=multiprocessing ^
    --nofollow-import-to=concurrent.futures ^
    --nofollow-import-to=asyncio ^
    --lto=yes ^
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

REM 處理 Nuitka 輸出目錄名稱
REM Nuitka 預設會產生 main.dist 或 MinecraftServerManager.dist
REM 我們需要將其重新命名為 MinecraftServerManager

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

    echo 請安裝 Inno Setup 6: https://jrsoftware.org/isdl.php

    pause
    exit /b 1
)

REM 建立 dist\installer 目錄
if not exist "dist\installer" mkdir "dist\installer"

REM 編譯 Inno Setup 安裝檔 (傳遞版本、應用程式名稱與檔案 ID)
"%ISCC%" /DAppVersion="%APP_VERSION%" /DAppName="%APP_NAME%" /DAppId="%APP_ID%" /O"dist\installer" "scripts\installer.iss"
if errorlevel 1 (

    echo [失敗] Inno Setup 編譯失敗。

    pause
    exit /b 1
)

echo ========================================================
echo   安裝檔建置完成!
echo   安裝檔位置: dist\installer\%APP_ID%-Setup-%APP_VERSION%.exe
echo ========================================================
pause
endlocal

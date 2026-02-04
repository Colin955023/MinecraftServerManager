@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
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
REM 讀取目前路徑
set CURRENT_DIR=%cd%
if "%CURRENT_DIR%"=="" (
    echo [錯誤] 無法讀取目前路徑。
    pause
    exit /b 1
) else (
    echo [成功] 目前路徑: !CURRENT_DIR!
)
REM 設定用於檔案名稱的簡短 ID（無空格）
set APP_ID=MinecraftServerManager
echo [成功] 檔案 ID: %APP_ID%

echo.

echo ========================================================
echo   正在建置 %APP_NAME% v%APP_VERSION% (Nuitka)

echo   檔案 ID: %APP_ID%
echo ========================================================

echo [1/5] 清除舊的建置檔案...

REM 強制關閉正在執行的程式以避免 Access is denied
taskkill /F /IM MinecraftServerManager.exe >nul 2>nul
timeout /t 1 /nobreak >nul

if exist build rmdir /S /Q build
if exist dist rmdir /S /Q dist
if exist main.dist rmdir /S /Q main.dist
if exist main.build rmdir /S /Q main.build

echo [2/5] 檢查並安裝依賴...

uv --version >nul 2>nul
if errorlevel 1 (
    echo [錯誤] 未偵測到 uv。正在安裝 uv...
    py -m pip install uv
    uv --version >nul 2>nul
    if errorlevel 1 (
        echo [錯誤] uv 安裝失敗，請手動安裝 uv。
        pause
        exit /b 1
    ) else (
        echo [成功] uv 安裝完成。
    )
) else (
    echo [成功] 已偵測到 uv。
)

echo [資訊] 清理虛擬環境...
REM 終止所有 python 進程，並特別嘗試停止使用 .venv 的進程（分開執行以降低引號解析風險）
powershell -NoProfile -Command "Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force" 2>nul
powershell -NoProfile -Command "Get-Process python* -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*\\.venv\\*' } | Stop-Process -Force" 2>nul
timeout /t 1 /nobreak >nul

REM 嘗試使用 PowerShell 刪除 .venv，若仍存在則以 takeown/icacls + rmdir 強制刪除
powershell -NoProfile -Command "Remove-Item -LiteralPath '.venv' -Recurse -Force -ErrorAction SilentlyContinue" 2>nul
if exist ".venv" (
    echo [警告] 刪除 .venv 失敗，嘗試取得擁有權並強制刪除...
    takeown /f .venv /r /d y >nul 2>nul
    icacls .venv /grant %USERNAME%:F /t >nul 2>nul
    rmdir /S /Q ".venv" 2>nul
    if exist ".venv" (
        echo [錯誤] 無法刪除 .venv，請以系統管理員身分執行或關閉使用該資料夾的程式。
    )
)
powershell -NoProfile -Command "Remove-Item -LiteralPath 'dist' -Recurse -Force -ErrorAction SilentlyContinue" 2>nul
timeout /t 1 /nobreak >nul

echo [資訊] 建立全新虛擬環境...
REM 若 .venv 尚存會導致建立失敗，使用 --clear 以取代現有目錄（參考 uv 建議）
uv venv .venv --clear

echo [資訊] 安裝生產依賴（不含開發工具）...
uv pip install --python .venv\Scripts\python.exe psutil toml customtkinter requests defusedxml markdown
if errorlevel 1 (
    echo [錯誤] 依賴安裝失敗。

    pause
    exit /b 1
)

echo [資訊] 安裝 Nuitka（用於打包）...
uv pip install --python .venv\Scripts\python.exe "nuitka>=2.8.9"
if errorlevel 1 (
    echo [錯誤] Nuitka 安裝失敗。

    pause
    exit /b 1
)

echo [3/5] 執行 Nuitka 打包 (Standalone 模式)...

REM Nuitka 編譯命令 (Standalone = 資料夾模式)
REM 注意：我們需要將輸出資料夾重新命名為 MinecraftServerManager 以配合 Inno Setup 腳本

.venv\Scripts\python.exe -m nuitka ^
    --remove-output ^
    --standalone ^
    --enable-plugin=tk-inter ^
    --include-package-data=customtkinter ^
    --include-package=src ^
    --python-flag=no_docstrings ^
    --python-flag=no_asserts ^
    --windows-console-mode=attach ^
    --windows-icon-from-ico=assets/icon.ico ^
    --include-data-dir=assets=assets ^
    --include-data-file=README.md=README.md ^
    --include-data-file=LICENSE=LICENSE ^
    --nofollow-import-to=unittest ^
    --nofollow-import-to=test ^
    --nofollow-import-to=pydoc ^
    --nofollow-import-to=pydoc_data ^
    --nofollow-import-to=tkinter.test ^
    --nofollow-import-to=distutils ^
    --nofollow-import-to=setuptools ^
    --nofollow-import-to=pip ^
    --nofollow-import-to=html.parser ^
    --nofollow-import-to=xml.dom ^
    --nofollow-import-to=xml.sax ^
    --nofollow-import-to=xmlrpc ^
    --nofollow-import-to=asyncio ^
    --lto=yes ^
    --jobs=%NUMBER_OF_PROCESSORS% ^
    --output-dir=dist ^
    --output-filename=MinecraftServerManager.exe ^
    --company-name=MinecraftServerManager ^
    --product-name="Minecraft Server Manager" ^
    --file-version=%APP_VERSION% ^
    --product-version=%APP_VERSION% ^
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
) else (
    if exist "dist\MinecraftServerManager.dist" (
        if exist "dist\MinecraftServerManager" rmdir /S /Q "dist\MinecraftServerManager"
        move "dist\MinecraftServerManager.dist" "dist\MinecraftServerManager"
    )
)

if not exist "dist\MinecraftServerManager\MinecraftServerManager.exe" (
    echo [錯誤] 找不到編譯後的執行檔，目錄結構可能不正確。

    pause
    exit /b 1
)

echo [資訊] 確保 CustomTkinter 資源文件被正確包含...
REM 手動複製 CustomTkinter 的 assets（確保 themes 存在）
if exist ".venv\Lib\site-packages\customtkinter\assets" (
    if not exist "dist\MinecraftServerManager\customtkinter\assets" mkdir "dist\MinecraftServerManager\customtkinter\assets"
    powershell -NoProfile -Command "Copy-Item -Path '.venv\Lib\site-packages\customtkinter\assets\*' -Destination 'dist\MinecraftServerManager\customtkinter\assets' -Recurse -Force" >nul 2>&1
)

if not exist "dist\MinecraftServerManager\customtkinter\assets\themes\blue.json" (
    echo [警告] CustomTkinter theme 檔案仍缺失，請重新執行建置或檢查權限。
)

echo [4/5] 編譯 Inno Setup 安裝檔...

set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo [錯誤] 找不到 Inno Setup 編譯器。

    echo 請安裝 Inno Setup 6: https://jrsoftware.org/isdl.php

    pause
    exit /b 1
)

REM 編譯 Inno Setup 安裝檔 (傳遞版本、應用程式名稱與檔案 ID)
"%ISCC%" /DAppVersion="%APP_VERSION%" /DAppName="%APP_NAME%" /DAppId="%APP_ID%" "scripts\installer.iss"
if errorlevel 1 (

    echo [失敗] Inno Setup 編譯失敗。

    pause
    exit /b 1
)

echo [5/5] 建立可攜版 (portable)...
REM 優先使用 pwsh (PowerShell Core) 執行腳本以獲得較一致的 UTF-8 支援，找不到再回退到 powershell
where pwsh >nul 2>nul
if not errorlevel 1 (
    pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0package-portable.ps1"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0package-portable.ps1"
)
if errorlevel 1 (
    echo [錯誤] 可攜版打包失敗。
    pause
    exit /b 1
)

echo ========================================================
echo   所有檔案已建置完成!
echo   安裝檔位置: !CURRENT_DIR!\dist\%APP_ID%-Setup-%APP_VERSION%.exe
echo   可攜版位置: !CURRENT_DIR!\dist\MinecraftServerManager-v%APP_VERSION%-portable.zip
echo   注意：SHA256 檔案由 GitHub Actions 自動產生
echo ========================================================
pause
endlocal

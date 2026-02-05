@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
title Minecraft 伺服器管理器 - Nuitka 打包與安裝檔建置
cd /d %~dp0..

REM ============================================================
REM 步驟 0: 讀取版本資訊與初始化
REM ============================================================

echo [資訊] 正在讀取版本資訊...

for /f "delims=" %%A in ('py -c "from src.version_info import APP_VERSION; print(APP_VERSION)" 2^>nul') do set APP_VERSION=%%A
for /f "delims=" %%A in ('py -c "from src.version_info import APP_NAME; print(APP_NAME)" 2^>nul') do set APP_NAME=%%A

if "%APP_VERSION%"=="" (

    echo [警告] 無法讀取 APP_VERSION，使用預設值 1.6.4

    set APP_VERSION=1.6.4
) else (
    echo [成功] 版本號: %APP_VERSION%
)

if "%APP_NAME%"=="" (
    echo [警告] 無法讀取 APP_NAME，使用預設值 Minecraft Server Manager

    set APP_NAME=Minecraft Server Manager
) else (
    echo [成功] 應用程式名稱: %APP_NAME%
)

set CURRENT_DIR=%cd%
if "%CURRENT_DIR%"=="" (
    echo [錯誤] 無法讀取目前路徑
    pause
    exit /b 1
)
echo [成功] 目前路徑: !CURRENT_DIR!

set APP_ID=MinecraftServerManager
echo [成功] 檔案 ID: %APP_ID%

echo.

echo ========================================================
echo   正在建置 %APP_NAME% v%APP_VERSION% (Nuitka)

echo   檔案 ID: %APP_ID%
echo ========================================================
echo.

REM ============================================================
REM 步驟 1: 清除舊的建置檔案
REM ============================================================

echo [1/5] 清除舊的建置檔案...

REM 強制關閉程式
taskkill /F /IM MinecraftServerManager.exe >nul 2>nul
timeout /t 1 /nobreak >nul 2>nul

REM 使用 PowerShell 強力刪除，忽略錯誤
powershell -NoProfile -Command "Get-ChildItem -Path 'build','dist','main.dist','main.build' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue" 2>nul

REM 再次確認刪除（如果 PowerShell 失敗，使用傳統方式）
if exist build rmdir /S /Q build 2>nul
if exist dist rmdir /S /Q dist 2>nul
if exist main.dist rmdir /S /Q main.dist 2>nul
if exist main.build rmdir /S /Q main.build 2>nul

echo [完成] 舊的建置檔案已清除

echo.

REM ============================================================
REM 步驟 2: 準備虛擬環境與依賴
REM ============================================================

echo [2/5] 準備虛擬環境與依賴...

REM 檢查 uv 工具
uv --version >nul 2>nul
if errorlevel 1 (
    echo [資訊] 正在安裝 uv 套件管理工具...

    py -m pip install uv
    if errorlevel 1 (
        echo [錯誤] uv 安裝失敗，請手動安裝 uv

        pause
        exit /b 1
    )
    echo [成功] uv 安裝完成

) else (
    echo [成功] uv 已就緒

)

REM 虛擬環境處理邏輯
REM CI 環境（GitHub Actions）每次都是全新環境，直接建立即可
REM 本地環境需要手動清理舊虛擬環境，確保乾淨

if "%CI%"=="true" (
    echo [CI] 跳過虛擬環境清理（全新環境）
    echo [資訊] 建立虛擬環境...
    uv venv .venv
) else (
    if exist ".venv" (
        echo [資訊] 清理舊的虛擬環境...

        powershell -NoProfile -Command "Remove-Item -Path '.venv' -Recurse -Force -ErrorAction SilentlyContinue" 2>nul
        timeout /t 1 /nobreak 2>nul
        echo [成功] 舊虛擬環境已清理
    )
    echo [資訊] 建立全新的虛擬環境...
    
uv venv .venv --clear
)

if errorlevel 1 (
    echo [錯誤] 虛擬環境建立失敗
    pause
    exit /b 1
)
echo [成功] 虛擬環境已準備完畢

REM 安裝依賴
echo [資訊] 安裝生產依賴...

uv pip install --python .venv\Scripts\python.exe toml customtkinter requests defusedxml markdown
if errorlevel 1 (
    echo [錯誤] 依賴安裝失敗

    pause
    exit /b 1
)

echo [資訊] 安裝 Nuitka...

uv pip install --python .venv\Scripts\python.exe "nuitka>=2.8.9"
if errorlevel 1 (
    echo [錯誤] Nuitka 安裝失敗

    pause
    exit /b 1
)

echo [完成] 虛擬環境與依賴準備完成

echo.

REM ============================================================
REM 步驟 3: 執行 Nuitka 編譯
REM ============================================================

echo [3/5] 執行 Nuitka 編譯（Standalone 模式）...

.venv\Scripts\python.exe -m nuitka ^
    --standalone ^
    --assume-yes-for-downloads ^
    --remove-output ^
    --output-dir=dist ^
    --output-filename=MinecraftServerManager.exe ^
    --enable-plugin=tk-inter ^
    --include-package=src ^
    --include-module=src.core.version_manager ^
    --include-module=src.utils.http_utils ^
    --include-module=src.utils.java_downloader ^
    --include-module=src.utils.java_utils ^
    --include-module=src.utils.path_utils ^
    --include-module=src.utils.subprocess_utils ^
    --include-package=certifi ^
    --include-package-data=certifi ^
    --include-package-data=customtkinter ^
    --include-distribution-metadata=customtkinter ^
    --include-distribution-metadata=requests ^
    --include-distribution-metadata=Markdown ^
    --follow-import-to=markdown ^
    --include-data-dir=assets=assets ^
    --include-data-file=README.md=README.md ^
    --include-data-file=LICENSE=LICENSE ^
    --python-flag=no_docstrings ^
    --python-flag=no_asserts ^
    --windows-console-mode=attach ^
    --windows-icon-from-ico=assets/icon.ico ^
    --company-name=MinecraftServerManager ^
    --product-name="Minecraft Server Manager" ^
    --file-version=%APP_VERSION% ^
    --product-version=%APP_VERSION% ^
    --msvc=latest ^
    --nofollow-import-to=tests ^
    --nofollow-import-to=pytest ^
    --nofollow-import-to=test ^
    --nofollow-import-to=tests ^
    --nofollow-import-to=pytest ^
    --nofollow-import-to=pip ^
    --nofollow-import-to=pydoc ^
    --nofollow-import-to=pydoc_data ^
    --nofollow-import-to=doctest ^
    --nofollow-import-to=pdb ^
    --nofollow-import-to=profile ^
    --nofollow-import-to=cProfile ^
    --nofollow-import-to=trace ^
    --nofollow-import-to=timeit ^
    --nofollow-import-to=optparse ^
    --nofollow-import-to=lib2to3 ^
    --nofollow-import-to=calendar ^
    --nofollow-import-to=fractions ^
    --nofollow-import-to=statistics ^
    --nofollow-import-to=pickletools ^
    --nofollow-import-to=shelve ^
    --nofollow-import-to=dbm ^
    --nofollow-import-to=mailbox ^
    --nofollow-import-to=smtplib ^
    --nofollow-import-to=poplib ^
    --nofollow-import-to=imaplib ^
    --nofollow-import-to=ftplib ^
    --nofollow-import-to=telnetlib ^
    --nofollow-import-to=cgi ^
    --nofollow-import-to=cgitb ^
    --nofollow-import-to=wsgiref ^
    --nofollow-import-to=quopri ^
    --nofollow-import-to=uu ^
    --nofollow-import-to=tkinter.colorchooser ^
    --nofollow-import-to=tkinter.dnd ^
    --nofollow-import-to=turtle ^
    --nofollow-import-to=audioop ^
    --nofollow-import-to=wave ^
    --nofollow-import-to=numpy ^
    --nofollow-import-to=pandas ^
    --nofollow-import-to=matplotlib ^
    --nofollow-import-to=scipy ^
    --lto=yes ^
    --jobs=%NUMBER_OF_PROCESSORS% ^
    src\main.py

if errorlevel 1 (
    echo [錯誤] Nuitka 編譯失敗

    pause
    exit /b 1
)

echo [成功] Nuitka 編譯完成

echo.

REM ============================================================
REM 步驟 3.5: 整理 Nuitka 輸出
REM ============================================================

echo [資訊] 整理編譯輸出...

REM 在本地環境等待檔案鎖定釋放
if not "%CI%"=="true" (
    timeout /t 2 /nobreak >nul
)

REM 處理 Nuitka 輸出目錄名稱（main.dist 或 MinecraftServerManager.dist）
if exist "dist\main.dist" (
    if exist "dist\MinecraftServerManager" rmdir /S /Q "dist\MinecraftServerManager" 2>nul
    move "dist\main.dist" "dist\MinecraftServerManager" >nul
) else if exist "dist\MinecraftServerManager.dist" (
    if exist "dist\MinecraftServerManager" rmdir /S /Q "dist\MinecraftServerManager" 2>nul
    move "dist\MinecraftServerManager.dist" "dist\MinecraftServerManager" >nul
)

REM 驗證執行檔
if not exist "dist\MinecraftServerManager\MinecraftServerManager.exe" (
    echo [錯誤] 找不到編譯後的執行檔

    pause
    exit /b 1
)

REM 確保 CustomTkinter 資源檔案完整
if exist ".venv\Lib\site-packages\customtkinter\assets" (
    if not exist "dist\MinecraftServerManager\customtkinter\assets" mkdir "dist\MinecraftServerManager\customtkinter\assets"
    powershell -NoProfile -Command "Copy-Item -Path '.venv\Lib\site-packages\customtkinter\assets\*' -Destination 'dist\MinecraftServerManager\customtkinter\assets' -Recurse -Force" >nul 2>&1
)

if not exist "dist\MinecraftServerManager\customtkinter\assets\themes\blue.json" (
    echo [警告] CustomTkinter 主題檔案可能遺失

)

echo [完成] 編譯輸出整理完成

echo.

REM ============================================================
REM 步驟 4: 建立安裝檔（Inno Setup）
REM ============================================================

echo [4/5] 建立安裝檔...

set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo [錯誤] 找不到 Inno Setup 6 編譯器

    echo [提示] 請安裝 Inno Setup 6: https://jrsoftware.org/isdl.php

    pause
    exit /b 1
)

"%ISCC%" /DAppVersion="%APP_VERSION%" /DAppName="%APP_NAME%" /DAppId="%APP_ID%" "scripts\installer.iss"
if errorlevel 1 (
    echo [錯誤] Inno Setup 編譯失敗

    pause
    exit /b 1
)

echo [完成] 安裝檔建立完成

echo.

REM ============================================================
REM 步驟 5: 建立可攜版
REM ============================================================

echo [5/5] 建立可攜版...

REM 優先使用 PowerShell Core (pwsh)，否則使用 Windows PowerShell
where pwsh >nul 2>nul
if not errorlevel 1 (
    pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0package-portable.ps1"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0package-portable.ps1"
)

if errorlevel 1 (
    echo [錯誤] 可攜版打包失敗

    pause
    exit /b 1
)

echo [完成] 可攜版建立完成

echo.

REM ============================================================
REM 完成
REM ============================================================

echo ========================================================
echo                       建置成功完成！
echo ========================================================
echo.
echo 安裝檔: dist\%APP_ID%-Setup-%APP_VERSION%.exe

echo 可攜版: dist\MinecraftServerManager-v%APP_VERSION%-portable.zip

echo.
echo 提示: SHA256 檢查碼由 GitHub Actions 自動產生

echo ========================================================
echo.
endlocal

@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Minecraft 伺服器管理器 - 可攜式版本自動更新工具

echo ========================================================
echo   Minecraft 伺服器管理器 - 自動更新工具
echo ========================================================
echo.

REM 獲取當前目錄（應該是可攜式版本的根目錄）
set "CURRENT_DIR=%~dp0.."
cd /d "%CURRENT_DIR%"

REM GitHub 資訊
set "GITHUB_OWNER=Colin955023"
set "GITHUB_REPO=MinecraftServerManager"
set "GITHUB_API=https://api.github.com/repos/%GITHUB_OWNER%/%GITHUB_REPO%/releases/latest"

REM 取得當前版本
echo [1/5] 取得當前版本資訊...
for /f "delims=" %%A in ('py -c "from src.version_info import APP_VERSION; print(APP_VERSION)" 2^>nul') do set CURRENT_VERSION=%%A

if "!CURRENT_VERSION!"=="" (
    echo [錯誤] 無法讀取當前版本，更新中止。
    pause
    exit /b 1
)
echo [成功] 當前版本: !CURRENT_VERSION!
echo.

REM 建立臨時目錄
set "TEMP_DIR=%TEMP%\MSM_Update_%RANDOM%"
if not exist "!TEMP_DIR!" mkdir "!TEMP_DIR!"

REM 使用 PowerShell 獲取最新版本資訊
echo [2/5] 檢查 GitHub 最新版本...
powershell -NoProfile -ExecutionPolicy Bypass -Command "^
    try {^
        $response = Invoke-RestMethod -Uri '%GITHUB_API%' -Headers @{'User-Agent'='MinecraftServerManager'} -TimeoutSec 30;^
        $latestTag = $response.tag_name -replace '^v', '';^
        Write-Output $latestTag;^
    } catch {^
        Write-Output 'ERROR';^
    }^
" > "!TEMP_DIR!\latest_version.txt"

if errorlevel 1 (
    echo [錯誤] 無法連接到 GitHub API，請檢查網路連接。
    rmdir /S /Q "!TEMP_DIR!" >nul 2>&1
    pause
    exit /b 1
)

set /p LATEST_VERSION=<"!TEMP_DIR!\latest_version.txt"

if "!LATEST_VERSION!"=="ERROR" (
    echo [錯誤] 無法取得最新版本資訊。
    rmdir /S /Q "!TEMP_DIR!" >nul 2>&1
    pause
    exit /b 1
)

echo [成功] 最新版本: !LATEST_VERSION!
echo.

REM 比較版本
if "!CURRENT_VERSION!"=="!LATEST_VERSION!" (
    echo [資訊] 您已使用最新版本，無須更新。
    rmdir /S /Q "!TEMP_DIR!" >nul 2>&1
    echo.
    pause
    exit /b 0
)

echo [提示] 發現新版本！將從 !CURRENT_VERSION! 更新至 !LATEST_VERSION!
echo.

REM 備份當前版本
echo [3/5] 建立備份...
set "BACKUP_DIR=.\MinecraftServerManager_backup_!CURRENT_VERSION!"
if exist "!BACKUP_DIR!" rmdir /S /Q "!BACKUP_DIR!" >nul 2>&1
if exist ".\MinecraftServerManager" (
    move ".\MinecraftServerManager" "!BACKUP_DIR!" >nul 2>&1
    echo [成功] 原版本已備份至: !BACKUP_DIR!
) else (
    echo [警告] 找不到 MinecraftServerManager 資料夾。
)
echo.

REM 下載新版本
echo [4/5] 下載新版本 (!LATEST_VERSION!)...
set "ZIP_URL=https://github.com/%GITHUB_OWNER%/%GITHUB_REPO%/releases/download/v!LATEST_VERSION!/MinecraftServerManager-v!LATEST_VERSION!-portable.zip"
set "ZIP_FILE=!TEMP_DIR!\MinecraftServerManager-v!LATEST_VERSION!-portable.zip"

powershell -NoProfile -ExecutionPolicy Bypass -Command "^
    try {^
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;^
        $ProgressPreference = 'SilentlyContinue';^
        Invoke-WebRequest -Uri '%ZIP_URL%' -OutFile '%ZIP_FILE%' -TimeoutSec 300;^
        Write-Output 'SUCCESS';^
    } catch {^
        Write-Output 'ERROR: ' + $_.Exception.Message;^
    }^
" > "!TEMP_DIR!\download_status.txt"

set /p DOWNLOAD_STATUS=<"!TEMP_DIR!\download_status.txt"
if not "!DOWNLOAD_STATUS!"=="SUCCESS" (
    echo [錯誤] 下載失敗: !DOWNLOAD_STATUS!
    echo [資訊] 正在還原備份...
    if exist "!BACKUP_DIR!" (
        move "!BACKUP_DIR!" ".\MinecraftServerManager" >nul 2>&1
        echo [成功] 已還原至原版本。
    )
    rmdir /S /Q "!TEMP_DIR!" >nul 2>&1
    pause
    exit /b 1
)

if not exist "!ZIP_FILE!" (
    echo [錯誤] 找不到下載的檔案或檔案損毀。
    echo [資訊] 正在還原備份...
    if exist "!BACKUP_DIR!" (
        move "!BACKUP_DIR!" ".\MinecraftServerManager" >nul 2>&1
        echo [成功] 已還原至原版本。
    )
    rmdir /S /Q "!TEMP_DIR!" >nul 2>&1
    pause
    exit /b 1
)

echo [成功] 下載完成！
echo.

REM 解壓新版本
echo [5/5] 安裝新版本...
powershell -NoProfile -ExecutionPolicy Bypass -Command "^
    try {^
        Expand-Archive -Path '%ZIP_FILE%' -DestinationPath '%CURRENT_DIR%' -Force;^
        Write-Output 'SUCCESS';^
    } catch {^
        Write-Output 'ERROR: ' + $_.Exception.Message;^
    }^
" > "!TEMP_DIR!\extract_status.txt"

set /p EXTRACT_STATUS=<"!TEMP_DIR!\extract_status.txt"
if not "!EXTRACT_STATUS!"=="SUCCESS" (
    echo [錯誤] 解壓失敗: !EXTRACT_STATUS!
    echo [資訊] 正在還原備份...
    if exist ".\MinecraftServerManager" rmdir /S /Q ".\MinecraftServerManager" >nul 2>&1
    if exist "!BACKUP_DIR!" (
        move "!BACKUP_DIR!" ".\MinecraftServerManager" >nul 2>&1
        echo [成功] 已還原至原版本。
    )
    rmdir /S /Q "!TEMP_DIR!" >nul 2>&1
    pause
    exit /b 1
)

echo [成功] 新版本已安裝！
echo.

REM 清理備份和臨時檔案
echo [清理] 移除備份和臨時檔案...
if exist "!BACKUP_DIR!" rmdir /S /Q "!BACKUP_DIR!" >nul 2>&1
rmdir /S /Q "!TEMP_DIR!" >nul 2>&1

echo ========================================================
echo   更新完成！
echo   !CURRENT_VERSION! ==^> !LATEST_VERSION!
echo ========================================================
echo.
echo 按任意鍵關閉此視窗...
echo.

endlocal
pause

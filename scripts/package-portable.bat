@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Minecraft 伺服器管理器 - 可攜式版本打包工具

echo ========================================================
echo   Minecraft 伺服器管理器 - 可攜式版本打包
echo ========================================================
echo.

pushd "%~dp0.." >nul

if not exist "dist\MinecraftServerManager" (
    echo 錯誤: 找不到 dist\MinecraftServerManager 資料夾。
    echo 請先執行 build_installer_nuitka.bat 來生成可攜式版本。
    popd >nul
    pause
    exit /b 1
)

echo [1/4] 建立便攜模式標記檔...
REM 建立 .portable 標記檔，讓程式知道這是便攜版
echo. 2> "dist\MinecraftServerManager\.portable"
echo [成功] 已建立 .portable 標記檔

echo.
echo [2/4] 複製更新工具到可攜式版本...
copy /Y "scripts\update-portable.bat" "dist\MinecraftServerManager\update-portable.bat" >nul
if errorlevel 1 (
    echo 錯誤: 無法複製 update-portable.bat
    popd >nul
    pause
    exit /b 1
)
echo [成功] 已複製 update-portable.bat

echo.
echo [3/4] 建立可攜式版本壓縮檔...

REM 取得版本號
for /f "delims=" %%A in ('py -c "from src.version_info import APP_VERSION; print(APP_VERSION)" 2^>nul') do set APP_VERSION=%%A
if "!APP_VERSION!"=="" set APP_VERSION=1.0.0

set ZIP_FILE=MinecraftServerManager-v!APP_VERSION!-portable.zip

cd dist
if exist "!ZIP_FILE!" del "!ZIP_FILE!" >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path MinecraftServerManager -DestinationPath '!ZIP_FILE!' -Force" >nul
cd ..

if not exist "dist\!ZIP_FILE!" (
    echo 錯誤: 壓縮檔建立失敗
    popd >nul
    pause
    exit /b 1
)

echo [成功] 已建立 !ZIP_FILE!

echo.
echo [4/4] 建立 README 說明檔...

REM 建立使用說明檔
set README_FILE=dist\MinecraftServerManager\README_PORTABLE.txt
(
    echo Minecraft 伺服器管理器 - 可攜式版本
    echo ============================================
    echo.
    echo 歡迎使用可攜式版本！以下是使用說明：
    echo.
    echo 【第一次使用】
    echo 1. 雙擊 MinecraftServerManager.exe 執行程式
    echo 2. 程式會引導您選擇「伺服器主資料夾」的位置
    echo 3. 所有伺服器資料將存儲於您指定的位置
    echo.
    echo 【檢查更新】
    echo 1. 雙擊 update-portable.bat 即可自動檢查更新
    echo 2. 若有新版本，程式會自動下載並安裝
    echo 3. 備份會自動建立，失敗時可還原
    echo.
    echo 【資料儲存】
    echo - 程式設定： .config\user_settings.json
    echo - 日誌檔案： .log\ 資料夾
    echo - 伺服器資料： 您指定的「伺服器主資料夾」
    echo.
    echo 【需要幫助】
    echo 訪問官方 GitHub：
    echo https://github.com/Colin955023/MinecraftServerManager
    echo.
    echo 祝您使用愉快！
) > "!README_FILE!"

echo [成功] 已建立說明檔

echo.
echo ========================================================
echo   打包完成！
echo ========================================================
echo.
echo 可攜式版本檔案：dist\!ZIP_FILE!
echo 解壓後即可在任何地方使用。
echo.

popd >nul
endlocal
pause

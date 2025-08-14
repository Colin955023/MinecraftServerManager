@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Minecraft 伺服器管理器 - 建置腳本
cd /d %~dp0..
echo Minecraft 伺服器管理器 - 建置腳本
echo ================================================
echo 正在建置可執行檔（exe + 依賴資料夾結構）...
echo.

REM 檢查 Python 環境
echo [1/8] 檢查 Python 環境...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 錯誤: 未找到 Python！
    echo    請先安裝 Python 3.7 或更新版本
    echo    下載地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 取得並顯示 Python 版本
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo ✅ Python %PYTHON_VERSION% 已安裝

REM 檢查並升級 pip
echo.
echo [2/8] 檢查並升級 pip...
python -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ pip 不可用
    pause
    exit /b 1
)
python -m pip install --upgrade pip >nul 2>&1
echo ✅ pip 已更新至最新版本

REM 檢查並安裝 PyInstaller
echo.
echo [3/8] 檢查並安裝 PyInstaller...
python -m pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo    正在安裝 PyInstaller...
    python -m pip install pyinstaller>=6.0
    if %errorlevel% neq 0 (
        echo ❌ PyInstaller 安裝失敗！
        echo    請檢查網路連線或嘗試手動安裝: pip install pyinstaller
        pause
        exit /b 1
    )
    echo ✅ PyInstaller 安裝完成
) else (
    echo ✅ PyInstaller 已安裝
)

REM 安裝專案依賴
echo.
echo [4/8] 安裝專案依賴...
if not exist "requirements.txt" (
    echo ❌ 找不到 requirements.txt 檔案！
    pause
    exit /b 1
)
python -m pip install -r requirements.txt >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 依賴安裝失敗！
    echo    請檢查 requirements.txt 檔案或網路連線
    pause
    exit /b 1
)
echo ✅ 專案依賴安裝完成

REM 清理舊的建置檔案
echo.
echo [5/8] 清理舊的建置檔案...
if exist "dist" (
    echo    正在清理 dist 資料夾...
    rmdir /s /q "dist" 2>nul
)
if exist "build" (
    echo    正在清理 build 資料夾...
    rmdir /s /q "build" 2>nul
)
if exist "*.spec.bak" (
    echo    正在清理備份檔案...
    del "*.spec.bak" 2>nul
)
echo ✅ 舊檔案清理完成

REM 驗證建置配置
echo.
echo [6/8] 驗證建置配置...
if not exist "build.spec" (
    echo ❌ 找不到 build.spec 配置檔案！
    pause
    exit /b 1
)
if not exist "minecraft_server_manager.py" (
    echo ❌ 找不到主程式檔案！
    pause
    exit /b 1
)
echo ✅ 建置配置檢查通過

REM 執行 PyInstaller 建置
echo.
echo [7/8] 執行 PyInstaller 建置...
echo    這可能需要數分鐘時間，請耐心等待...
echo    建置模式: 資料夾結構（exe + 依賴檔案）
echo.

python -m PyInstaller --clean --noconfirm build.spec

if %errorlevel% neq 0 (
    echo.
    echo ❌ 建置失敗！
    echo   請檢查上述錯誤訊息或嘗試以下解決方案：
    echo   1. 確保所有依賴正確安裝
    echo   2. 檢查 build.spec 配置檔案
    echo   3. 嘗試以管理員身分執行
    echo   4. 暫時關閉防毒軟體
    echo.
    pause
    exit /b 1
)

REM 驗證建置結果
echo.
echo [8/8] 驗證建置結果...
if exist "dist\MinecraftServerManager\MinecraftServerManager.exe" (
    echo ✅ 主程式建置成功
    
    REM 使用 PowerShell 獲取並格式化檔案大小
    for /f %%A in ('powershell -command "$size = (Get-Item 'dist\MinecraftServerManager\MinecraftServerManager.exe').Length; '{0:N2}' -f ($size / 1MB)"') do set "exe_size_mb=%%A"
    for /f %%B in ('powershell -command "$size = (Get-ChildItem -Recurse 'dist\MinecraftServerManager' | Measure-Object -Property Length -Sum).Sum; '{0:N2}' -f ($size / 1MB)"') do set "total_size_mb=%%B"

    echo.
    echo ======================================
    echo 🎉 建置完成！
    echo ======================================
    echo.
    echo 📁 輸出位置: dist\MinecraftServerManager\
    echo 📄 主程式: MinecraftServerManager.exe
    echo 📊 程式大小: !exe_size_mb! MB
    echo 📦 總計大小: !total_size_mb! MB
    echo.
    echo 📋 建置內容:
    dir "dist\MinecraftServerManager" /b | findstr /v "^$"
    echo.
    echo 💡 使用說明:
    echo  - 可直接執行 MinecraftServerManager.exe
    echo  - 不需要安裝 Python 或任何依賴

    echo  - 可複製整個目錄到其他 Windows 電腦使用
    echo  - 首次啟動可能較慢，後續會加快
    echo  - 建議將整個資料夾加入防毒軟體白名單
    echo.
    echo 🚀 立即測試執行？
    echo.
    choice /c yn /m "立即測試執行?"
    if errorlevel 1 if not errorlevel 2 (
        echo.
        echo 正在啟動測試...
        echo 注意: 測試視窗將在背景開啟
        dist\MinecraftServerManager\MinecraftServerManager.exe
        echo ✅ 測試啟動完成，請檢查是否正常開啟
    ) else (
        echo 跳過測試執行
    )
    echo ======================================
) else (
    echo.
    echo ❌ 建置驗證失敗: 找不到主程式檔案
    echo 可能的原因:
    echo - PyInstaller 建置過程中出現錯誤
    echo - 輸出路徑不正確
    echo - 檔案被防毒軟體隔離
    echo 請重新執行建置或檢查錯誤訊息
    echo.
)

echo.
echo 建置程序完成
pause

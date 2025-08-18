@echo off
setlocal
chcp 65001 >nul
title Minecraft 伺服器管理器 - 建置安裝包
cd /d %~dp0..

REM 允許從外部傳入版本號，未指定則預設 1.2
if "%APP_VERSION%"=="" set APP_VERSION=1.2
if "%APP_NAME%"=="" set APP_NAME=MinecraftServerManager

echo [0/3] 清除舊的 build/ 與 dist/ ...
if exist build (
  rmdir /S /Q build
)
if exist dist (
  rmdir /S /Q dist
)

echo [1/3] 安裝依賴並使用 PyInstaller 產生 one-folder ...
where python >nul 2>nul
if errorlevel 1 (
  echo 未偵測到 Python，請先安裝 Python 3 並確保加入 PATH。
  exit /b 1
)

python -m pip install --upgrade pip
python -m pip install -r requirements.txt || exit /b 1
python -m pip install pyinstaller || exit /b 1

REM 以 build.spec 進行打包（輸出 dist\MinecraftServerManager\*）
pyinstaller build.spec || exit /b 1

echo [2/3] 編譯 Inno Setup 安裝檔 ...
set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (
  echo 找不到 Inno Setup 編譯器：%ISCC%
  echo 請安裝 Inno Setup 6 或調整此路徑。 https://jrsoftware.org/isdl.php
  exit /b 1
)

for /f "delims=" %%A in ('python -c "from src.version_info import APP_VERSION; print(APP_VERSION)"') do set APP_VERSION=%%A
for /f "delims=" %%A in ('python -c "from src.version_info import APP_NAME; print(APP_NAME)"') do set APP_NAME=%%A


REM 將版本與名稱傳入 .iss，可在 .iss 內用 {#AppVersion}、{#AppName}
%ISCC% /DAppVersion=%APP_VERSION% /DAppName="%APP_NAME%" scripts\installer.iss || exit /b 1

echo [3/3] 完成。安裝包位於 dist\installer\
endlocal
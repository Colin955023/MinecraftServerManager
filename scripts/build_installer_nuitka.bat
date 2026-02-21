@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "UV_VENV_CLEAR=1"
title Minecraft Server Manager - Nuitka Packaging and Installer Build
cd /d %~dp0..
if /I "%GITHUB_ACTIONS%"=="true" set "CI=true"

REM ============================================================
REM Step 0: Load version info and initialize
REM ============================================================
echo [INFO] Reading version info...
for /f "delims=" %%A in ('python -c "from src.version_info import APP_VERSION; print(APP_VERSION)" 2^>nul') do set APP_VERSION=%%A
for /f "delims=" %%A in ('python -c "from src.version_info import APP_NAME; print(APP_NAME)" 2^>nul') do set APP_NAME=%%A

if "%APP_VERSION%"=="" (
    echo [ERROR] Could not read APP_VERSION from src.version_info
    exit /b 1
) else (
    echo [SUCCESS] Version: %APP_VERSION%
)

if "%APP_NAME%"=="" (
    echo [ERROR] Could not read APP_NAME from src.version_info
    exit /b 1
) else (
    echo [SUCCESS] Application name: %APP_NAME%
)

set CURRENT_DIR=%cd%
if "%CURRENT_DIR%"=="" (
    echo [ERROR] Could not read current path
    exit /b 1
)
echo [SUCCESS] Current path: !CURRENT_DIR!
set "APP_ID={{B8E0E6D1-2B7E-4A73-9D5A-8C3F8B3E0F11}"
echo [SUCCESS] File ID: %APP_ID%
echo.
echo ========================================================
echo   Building %APP_NAME% v%APP_VERSION% (Nuitka)
echo   File ID: %APP_ID%
echo ========================================================
echo.
REM ============================================================
REM Step 1: Clean old build artifacts
REM ============================================================
echo [1/5] Cleaning old build artifacts...
REM Force close the application
taskkill /F /IM MinecraftServerManager.exe >nul 2>nul
timeout /t 1 /nobreak >nul 2>nul
REM Force-delete with PowerShell, ignore errors
powershell -NoProfile -Command "Get-ChildItem -Path 'build','dist','main.dist','main.build' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue" 2>nul
REM Verify deletion again (fallback to classic commands if PowerShell fails)
if exist build rmdir /S /Q build 2>nul
if exist dist rmdir /S /Q dist 2>nul
if exist main.dist rmdir /S /Q main.dist 2>nul
if exist main.build rmdir /S /Q main.build 2>nul
echo [DONE] Old build artifacts cleaned
echo.
REM ============================================================
REM Step 2: Prepare virtual environment and dependencies
REM ============================================================
echo [2/5] Preparing virtual environment and dependencies...
REM Check uv tool
uv --version >nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing uv package manager...
    py -m pip install uv
    if errorlevel 1 (
        echo [ERROR] uv installation failed, please install uv manually
        exit /b 1
    )
    uv --version >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] uv installed but command is unavailable in PATH
        echo [TIP] Add uv to PATH or preinstall uv in the CI environment
        exit /b 1
    )
    echo [SUCCESS] uv installation completed
) else (
    echo [SUCCESS] uv is ready
)
REM Virtual environment handling logic
REM CI (GitHub Actions) is always a fresh environment; create directly
REM Local environments should clean old venv manually to ensure a clean state
if /I "%CI%"=="true" (
    echo [CI] Skipping virtual environment cleanup (fresh environment)
    echo [INFO] Creating virtual environment (non-interactive clear mode)...
    uv venv .venv --clear
) else (
    if exist ".venv" (
        echo [INFO] Cleaning old virtual environment...
        powershell -NoProfile -Command "Remove-Item -Path '.venv' -Recurse -Force -ErrorAction SilentlyContinue" 2>nul
        timeout /t 1 /nobreak 2>nul
        echo [SUCCESS] Old virtual environment cleaned
    )
    echo [INFO] Creating a fresh virtual environment...
    uv venv .venv --clear
)

if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment
    exit /b 1
)
echo [SUCCESS] Virtual environment is ready
REM Install dependencies
echo [INFO] Installing build dependencies...
echo [INFO] Syncing dependencies from pyproject.toml via uv...
uv sync --group build --frozen
if errorlevel 1 (
    echo [ERROR] Dependency installation failed
    exit /b 1
)

echo [DONE] Virtual environment and dependencies are ready
echo.
REM ============================================================
REM Step 3: Run Nuitka compilation
REM ============================================================
REM Support overriding Nuitka cache dir via environment variable NUITKA_CACHE_DIR
if defined NUITKA_CACHE_DIR (
    if /I "%NUITKA_CACHE_HIT%"=="true" (
        echo [INFO] Reusing restored Nuitka cache at %NUITKA_CACHE_DIR%
    ) else (
        echo [INFO] No restored Nuitka cache detected; this build will seed %NUITKA_CACHE_DIR%
    )
    if not exist "%NUITKA_CACHE_DIR%" mkdir "%NUITKA_CACHE_DIR%"
    echo [INFO] Nuitka cache directory ready: %NUITKA_CACHE_DIR%
)
if not defined NUITKA_CACHE_DIR (
    echo [INFO] Nuitka cache dir not set; running with Nuitka defaults.
)

echo [3/5] Running Nuitka compilation (standalone mode)...
.venv\Scripts\python.exe -m nuitka ^
    --standalone ^
    --assume-yes-for-downloads ^
    --remove-output ^
    --output-dir=dist ^
    --output-filename=MinecraftServerManager.exe ^
    --enable-plugin=tk-inter ^
    --include-package=src ^
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
    --lto=yes ^
    --jobs=%NUMBER_OF_PROCESSORS% ^
    src\main.py

if errorlevel 1 (
    echo [ERROR] Nuitka compilation failed
    exit /b 1
)

echo [SUCCESS] Nuitka compilation completed
echo.
REM ============================================================
REM Step 3.5: Organize Nuitka output
REM ============================================================
echo [INFO] Organizing build output...
REM Wait for file locks to release in local environments
if /I not "%CI%"=="true" (
    timeout /t 2 /nobreak >nul
)

REM Normalize Nuitka output directory name (main.dist or MinecraftServerManager.dist)
if exist "dist\main.dist" (
    if exist "dist\MinecraftServerManager" rmdir /S /Q "dist\MinecraftServerManager" 2>nul
    move "dist\main.dist" "dist\MinecraftServerManager" >nul
) else if exist "dist\MinecraftServerManager.dist" (
    if exist "dist\MinecraftServerManager" rmdir /S /Q "dist\MinecraftServerManager" 2>nul
    move "dist\MinecraftServerManager.dist" "dist\MinecraftServerManager" >nul
)

REM Verify executable
if not exist "dist\MinecraftServerManager\MinecraftServerManager.exe" (
    echo [ERROR] Compiled executable not found
    exit /b 1
)
REM Ensure CustomTkinter asset files are complete
if exist ".venv\Lib\site-packages\customtkinter\assets" (
    if not exist "dist\MinecraftServerManager\customtkinter\assets" mkdir "dist\MinecraftServerManager\customtkinter\assets"
    powershell -NoProfile -Command "Copy-Item -Path '.venv\Lib\site-packages\customtkinter\assets\*' -Destination 'dist\MinecraftServerManager\customtkinter\assets' -Recurse -Force" >nul 2>&1
)

if not exist "dist\MinecraftServerManager\customtkinter\assets\themes\blue.json" (
    echo [WARN] CustomTkinter theme file may be missing
)
echo [DONE] Build output organization completed
echo.
REM ============================================================
REM Step 4: Build installer (Inno Setup)
REM ============================================================
echo [4/5] Building installer...
REM Prefer ISCC in PATH; otherwise use default path
set "ISCC_PATH="
where iscc >nul 2>nul
if not errorlevel 1 set "ISCC_PATH=iscc"

if defined ISCC_PATH goto ISCC_READY
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if defined ISCC_PATH goto ISCC_READY

echo [ERROR] Inno Setup 6 compiler (ISCC.exe) not found
echo [TIP] Ensure Inno Setup 6 is installed and added to PATH
exit /b 1

:ISCC_READY

REM Ensure Inno Setup Traditional Chinese language file exists (workspace-local)
set "INNO_LANG_DIR=scripts\inno"
set "INNO_LANG_FILE=%INNO_LANG_DIR%\ChineseTraditional.isl"
if exist "%INNO_LANG_FILE%" goto INNO_LANG_READY

echo [ERROR] Missing Inno language file: %INNO_LANG_FILE%
echo [TIP] Please commit scripts\inno\ChineseTraditional.isl to the repository to avoid external downloads
exit /b 1

:INNO_LANG_READY

echo [INFO] Using ISCC: %ISCC_PATH%
"%ISCC_PATH%" /DAppVersion="%APP_VERSION%" /DAppName="%APP_NAME%" /DAppId="%APP_ID%" "scripts\installer.iss"
if errorlevel 1 (
    echo [ERROR] Inno Setup compilation failed
    exit /b 1
)

echo [DONE] Installer build completed
echo.
REM ============================================================
REM Step 5: Build portable package
REM ============================================================
echo [5/5] Building portable package...
REM Prefer PowerShell Core (pwsh), otherwise use Windows PowerShell
where pwsh >nul 2>nul
if not errorlevel 1 (
    pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0package-portable.ps1" -Version "%APP_VERSION%"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0package-portable.ps1" -Version "%APP_VERSION%"
)

if errorlevel 1 (
    echo [ERROR] Portable package build failed
    exit /b 1
)
echo [DONE] Portable package build completed
echo.
REM ============================================================
REM Complete
REM ============================================================
echo ========================================================
echo               Build completed successfully!
echo ========================================================
echo.
echo Installer: dist\%APP_NAME%-Setup-%APP_VERSION%.exe
echo Portable: dist\MinecraftServerManager-v%APP_VERSION%-portable.zip
echo.
echo TIP: SHA256 checksum is generated automatically by GitHub Actions
echo ========================================================
echo.
endlocal

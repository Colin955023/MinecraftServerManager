@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
title Minecraft Server Manager - Nuitka Packaging and Installer Build
cd /d %~dp0..

REM ============================================================
REM Step 0: Load version info and initialize
REM ============================================================
echo [INFO] Reading version info...
for /f "delims=" %%A in ('py -c "from src.version_info import APP_VERSION; print(APP_VERSION)" 2^>nul') do set APP_VERSION=%%A
for /f "delims=" %%A in ('py -c "from src.version_info import APP_NAME; print(APP_NAME)" 2^>nul') do set APP_NAME=%%A

if "%APP_VERSION%"=="" (
    echo [WARN] Could not read APP_VERSION, using default value 1.6.6
    set APP_VERSION=1.6.6
) else (
    echo [SUCCESS] Version: %APP_VERSION%
)

if "%APP_NAME%"=="" (
    echo [WARN] Could not read APP_NAME, using default value Minecraft Server Manager
    set APP_NAME=Minecraft Server Manager
) else (
    echo [SUCCESS] Application name: %APP_NAME%
)

set CURRENT_DIR=%cd%
if "%CURRENT_DIR%"=="" (
    echo [ERROR] Could not read current path
    exit /b 1
)
echo [SUCCESS] Current path: !CURRENT_DIR!
set APP_ID=MinecraftServerManager
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
    echo [SUCCESS] uv installation completed
) else (
    echo [SUCCESS] uv is ready
)
REM Virtual environment handling logic
REM CI (GitHub Actions) is always a fresh environment; create directly
REM Local environments should clean old venv manually to ensure a clean state
if "%CI%"=="true" (
    echo [CI] Skipping virtual environment cleanup (fresh environment)
    echo [INFO] Creating virtual environment...
    uv venv .venv
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
echo [INFO] Installing production dependencies...
uv pip install --python .venv\Scripts\python.exe toml customtkinter requests defusedxml markdown
if errorlevel 1 (
    echo [ERROR] Dependency installation failed
    exit /b 1
)

echo [INFO] Installing Nuitka...
uv pip install --python .venv\Scripts\python.exe "nuitka>=2.8.9"
if errorlevel 1 (
    echo [ERROR] Nuitka installation failed
    exit /b 1
)

echo [DONE] Virtual environment and dependencies are ready
echo.
REM ============================================================
REM Step 3: Run Nuitka compilation
REM ============================================================
echo [3/5] Running Nuitka compilation (standalone mode)...
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
if not "%CI%"=="true" (
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
set "ISCC=iscc"
where iscc >nul 2>nul
if %errorlevel% neq 0 (
    set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)

if not exist "%ISCC%" (
    where "%ISCC%" >nul 2>nul
    if %errorlevel% neq 0 (
        echo [ERROR] Inno Setup 6 compiler (ISCC.exe) not found
        echo [TIP] Ensure Inno Setup 6 is installed and added to PATH
        exit /b 1
    )
)

"%ISCC%" /DAppVersion="%APP_VERSION%" /DAppName="%APP_NAME%" /DAppId="%APP_ID%" "scripts\installer.iss"
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
    pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0package-portable.ps1"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0package-portable.ps1"
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
echo Installer: dist\%APP_ID%-Setup-%APP_VERSION%.exe
echo Portable: dist\MinecraftServerManager-v%APP_VERSION%-portable.zip
echo.
echo TIP: SHA256 checksum is generated automatically by GitHub Actions
echo ========================================================
echo.
endlocal

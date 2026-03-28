@echo off
setlocal
title Minecraft Server Manager - Format and Lint Check

echo ========================================================
echo   Minecraft Server Manager - Format and Lint Check
echo ========================================================
echo.

if not exist "pyproject.toml" (
    echo ERROR: pyproject.toml not found
    exit /b 1
)

echo === Sync Dependencies ===
uv sync --all-groups
if errorlevel 1 exit /b 1

echo === Ruff Format ===
uv run ruff format src tests quick_test.py
if errorlevel 1 exit /b 1

echo === Ruff Lint ===
uv run ruff check src tests quick_test.py --unsafe-fixes --fix
if errorlevel 1 exit /b 1
echo.

echo === Type Check ===
uv run mypy src tests quick_test.py
if errorlevel 1 exit /b 1
echo.

echo === Compile Check ===
uv run python -m compileall -q src
if errorlevel 1 exit /b 1
echo.

echo === Run Tests (smoke) ===
uv run pytest -m smoke -q
if errorlevel 1 exit /b 1

echo === Run Tests (integration) ===
uv run pytest -m integration -q
if errorlevel 1 exit /b 1
echo.
echo ========================================================
echo   All checks passed
echo ========================================================

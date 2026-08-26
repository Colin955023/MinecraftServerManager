@echo off
setlocal
title Minecraft Server Manager - Format and Quality Check

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PY_SCOPE=src tests scripts report"

echo ========================================================
echo   Minecraft Server Manager - Format and Quality Check
echo ========================================================
echo.

if not exist "pyproject.toml" (
    echo ERROR: pyproject.toml not found
    exit /b 1
)

echo === Validate Lockfile + Sync Dependencies ===
uv sync --group lint --group typecheck --group test --group security --locked
if errorlevel 1 exit /b 1

echo === Ruff Format ===
uv run ruff format %PY_SCOPE%
if errorlevel 1 exit /b 1

echo === Ruff Lint ===
uv run ruff check %PY_SCOPE% --fix
if errorlevel 1 exit /b 1
echo.

echo === Mypy Type Check ===
uv run mypy
if errorlevel 1 exit /b 1
echo.

echo === Pylint Cyclic Import Check (runtime package) ===
uv run pylint --disable=all --enable=cyclic-import src
if errorlevel 1 exit /b 1
echo.

echo === Import Architecture Check (runtime package) ===
uv run lint-imports
if errorlevel 1 exit /b 1
uv run scripts/check_import_boundaries.py
if errorlevel 1 exit /b 1
echo.

echo === Secret Scan ===
powershell -NoProfile -Command "$files = git ls-files; uv run detect-secrets-hook --baseline scripts/.secrets.baseline --exclude-files 'scripts[\\/]\.secrets\.baseline' -- $files; exit $LASTEXITCODE"
if errorlevel 1 (
    echo.
    echo [WARNING] Detected a potential secret. Please inspect the output above.
    exit /b 1
)
echo No new secrets detected.
echo.
echo === Compile Check ===
uv run python -m compileall -q src
if errorlevel 1 exit /b 1
echo.

echo === Run Tests ===
uv run pytest -q
if errorlevel 1 exit /b 1
echo.
echo ========================================================
echo   All hard-gate checks passed
echo ========================================================

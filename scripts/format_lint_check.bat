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

choice /c YN /m "Run secret scan? (Y/N)" /t 5 /d N
if errorlevel 2 (
    echo Skipping secret scan.
) else (
    echo === Secret Scan ===
    uv run detect-secrets scan --only-verified --all-files --exclude-files "(\.git|\.venv|\.pytest_cache|__pycache__|\.mypy_cache|\.ruff_cache|\.import_linter_cache|build|dist)" > secrets_report.json
    uv run python -c "import json,sys; data=json.load(open('secrets_report.json', encoding='utf-8')); sys.exit(1 if data.get('results') else 0)"
    if errorlevel 1 (
        type secrets_report.json
        echo.
        echo [WARNING] Detected potential secrets! Please check before pushing.
        del secrets_report.json
        exit /b 1
    ) else (
        echo No secrets detected.
        del secrets_report.json
    )
)

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

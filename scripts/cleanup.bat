@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo 正在清理 Minecraft 伺服器管理器暫存檔案...
echo.
echo 開始清理...

REM 清理 Python 快取檔案
echo 正在清理 Python 快取檔案...
for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"
del /s /q *.pyc 2>nul
del /s /q *.pyo 2>nul

REM 清理臨時檔案
echo 正在清理臨時檔案...
del /q *.tmp 2>nul
del /s /q *.log 2>nul

REM 清理建置檔案
echo 正在清理建置檔案...
if exist "dist" rd /s /q "dist"
if exist "build" rd /s /q "build"

REM 清理測試檔案
echo 正在清理測試檔案...


echo.
echo 清理操作完成！

REM 告知使用者清理了哪些檔案
echo 已清理：Python快取、臨時檔案、建置檔案、測試檔案
echo.
:end

@echo off
chcp 65001 >nul
cd /d "%~dp0"
title ASR + Translate

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

rem 不带文件参数时 workflow.py 自动进入队列模式。
"%PY%" "%~dp0src\workflow.py" %*
echo.
pause

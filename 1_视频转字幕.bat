@echo off
chcp 65001 >nul
cd /d "%~dp0"
title asr2srt

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" "%~dp0src\asr2srt.py" %*
echo.
pause

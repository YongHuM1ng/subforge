@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem Drag an already translated SRT onto this BAT file.
rem Double-click without files to enter queue mode (drag files into the window).
set "SCRIPT_DIR=%~dp0"
set "PS1=%SCRIPT_DIR%src\start_polish.ps1"
set "PY=%SCRIPT_DIR%runtime\python\python.exe"
if not exist "%PY%" set "PY=%SCRIPT_DIR%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

if not exist "%PS1%" (
    echo ERROR: start_polish.ps1 not found.
    pause
    exit /b 1
)

if "%~1"=="" (
    "%PY%" "%SCRIPT_DIR%src\queue_srt.py" polish
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
)

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo Polisher exited with code %EXIT_CODE%.
)
pause
exit /b %EXIT_CODE%

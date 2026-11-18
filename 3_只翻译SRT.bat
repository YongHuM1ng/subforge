@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem Translate SRT files. Drag one or more SRT files onto this BAT file;
rem every file becomes an independent task and runs in turn.
rem Double-click without files to enter queue mode (drag files into the window).
set "SCRIPT_DIR=%~dp0"
set "PY=%SCRIPT_DIR%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" "%SCRIPT_DIR%src\queue_srt.py" translate %*

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo Translator exited with code %EXIT_CODE%.
)
pause
exit /b %EXIT_CODE%

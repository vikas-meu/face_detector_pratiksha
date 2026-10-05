@echo off
REM Opens the app menu. Extra arguments are passed through,
REM e.g.  run_windows.bat 3   starts Robot Mimic straight away.
cd /d "%~dp0"

if not exist venv\Scripts\activate.bat (
    echo Please run setup_windows.bat first.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
python main.py %*
pause

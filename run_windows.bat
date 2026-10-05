@echo off
REM Starts the webcam face detector. Extra arguments are passed through,
REM e.g.  run_windows.bat --image photo.jpg
cd /d "%~dp0"

if not exist venv\Scripts\activate.bat (
    echo Please run setup_windows.bat first.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
python face_detector.py %*
pause

@echo off
REM One-click setup for Windows: creates a virtual environment, installs the packages and downloads the models.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install it from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)

echo Creating virtual environment...
python -m venv venv
if errorlevel 1 (
    echo Failed to create the virtual environment.
    pause
    exit /b 1
)

echo Installing packages...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo Package installation failed. Check your internet connection and try again.
    pause
    exit /b 1
)

echo.
echo Downloading face models...
python main.py --download-models
if errorlevel 1 (
    echo Model download failed. Check your internet connection and run setup again.
    pause
    exit /b 1
)

echo.
echo Setup complete! Double-click run_windows.bat to open the app menu.
pause

@echo off
echo PlugTrack Setup Script
echo =====================
echo.

echo Creating virtual environment...
python -m venv venv
if errorlevel 1 (
    echo Error: Failed to create virtual environment
    pause
    exit /b 1
)

echo Activating virtual environment...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo Error: Failed to activate virtual environment
    pause
    exit /b 1
)

echo Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo Error: Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo Setup completed successfully!
echo.
echo Next steps:
echo 1. Copy env_example.txt to .env
echo 2. Edit .env with your configuration
echo 3. Run: python test_basic.py
echo 4. Run: python start.py
echo.
echo Press any key to exit...
pause > nul

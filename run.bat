@echo off
setlocal enabledelayedexpansion

echo ==============================================================================
echo   AICTE INTEGRATED INSTITUTION COMPLAINT MONITORING SYSTEM
echo   Government Tech Administrative Portal -- Windows Auto Startup
echo ==============================================================================
echo.

:: 1. Navigate to script directory
cd /d "%~dp0"

:: 2. Check for Python installation
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not found on your PATH.
    echo Please install Python 3.10+ from https://www.python.org/ and check "Add Python to PATH".
    pause
    exit /b 1
)

:: 3. Setup Virtual Environment if not present
if not exist "venv\Scripts\activate.bat" (
    echo [*] Creating virtual environment in .\venv...
    python -m venv venv
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [*] Installing required dependencies (first-time launch)...
    call venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to install dependencies from requirements.txt.
        pause
        exit /b 1
    )
) else (
    call venv\Scripts\activate.bat
)

:: 4. Seed Database if database does not exist
if not exist "instance\aicte_monitoring.db" (
    echo [*] Database instance not found. Initializing schema and demonstration data...
    python scripts\seed_demo_data.py
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Database initialization failed.
        pause
        exit /b 1
    )
    echo [*] Database successfully initialized and seeded with demonstration records.
)

:: 5. Launch Browser in background after a brief delay
echo [*] Server will be available at: http://127.0.0.1:5000
start "" powershell -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:5000/login'"

:: 6. Start Flask server
echo [*] Starting AICTE Complaint Monitoring Server on 127.0.0.1:5000...
echo [*] Press Ctrl+C to stop the server at any time.
echo.
python app.py

pause

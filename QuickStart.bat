@echo off
setlocal enabledelayedexpansion
title Remote Gamepad - 1-Click Launcher
echo =======================================================
echo           Remote Gamepad - Easy Launcher
echo =======================================================
echo.

cd /d "%~dp0"

:: 1. Check for Python
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [!] Python is not detected on your system.
    echo [*] Attempting automated installation via winget...
    winget install Python.Python.3.11 --accept-package-agreements --accept-source-agreements
    if %ERRORLEVEL% neq 0 (
        echo [!] Automated installation failed. Opening Python download page...
        start https://www.python.org/downloads/
        echo Please install Python and make sure to check "Add Python to PATH".
        pause
        exit /b 1
    )
    echo [+] Python installed! Please close and re-run QuickStart.bat.
    pause
    exit /b 0
)

:: 2. Set up Virtual Environment if missing
if not exist ".venv" (
    echo [*] Creating virtual environment (.venv)...
    python -m venv .venv
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: 3. Install / Verify Dependencies
echo [*] Checking dependencies...
.venv\Scripts\python -m pip install --quiet --upgrade pip
.venv\Scripts\pip install --quiet -r pc\requirements.txt
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
)

:: 4. Launch Application
echo [+] Launching Remote Gamepad Receiver...
start "" ".venv\Scripts\pythonw.exe" pc\app.py
if %ERRORLEVEL% neq 0 (
    :: Fallback to normal python if pythonw has an issue
    start "" ".venv\Scripts\python.exe" pc\app.py
)
exit /b 0

@echo off
setlocal
echo ====================================================
echo   Building Remote Gamepad Receiver Standalone .EXE
echo ====================================================

cd /d "%~dp0"

echo [1/3] Checking / installing dependencies...
pip install pyinstaller -r requirements.txt

echo [2/3] Cleaning previous build folders...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

echo [3/3] Compiling standalone one-file executable...
pyinstaller --noconfirm --onefile --windowed ^
    --name "RemoteGamepadReceiver" ^
    --add-data "../static;static" ^
    --hidden-import="aiohttp" ^
    --hidden-import="qrcode" ^
    --hidden-import="PIL" ^
    --hidden-import="PIL.ImageTk" ^
    --hidden-import="updater" ^
    app.py

if %ERRORLEVEL% equ 0 (
    echo.
    echo ====================================================
    echo [SUCCESS] Executable built:
    echo %~dp0dist\RemoteGamepadReceiver.exe
    echo ====================================================
) else (
    echo.
    echo [ERROR] Build failed with exit code %ERRORLEVEL%.
)

pause

@echo off
TITLE SD Runner
python "%~dp0app_gui.py"
if %ERRORLEVEL% neq 0 (
    echo.
    echo Application exited with error code %ERRORLEVEL%
    pause
)

@echo off
TITLE SD Runner (Qt)
python "%~dp0app_qt.py"
if %ERRORLEVEL% neq 0 (
    echo.
    echo Application exited with error code %ERRORLEVEL%
    pause
)

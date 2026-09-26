@echo off
setlocal

REM ============================================================
REM INOUTX - Daily Excel Report Mailer
REM ============================================================

set "FRONTEND_DIR=%~dp0"
cd /d "%FRONTEND_DIR%"

REM Prefer the project's virtual environments.
if exist "%FRONTEND_DIR%..\.venv313\Scripts\python.exe" (
    set "PYTHON_EXE=%FRONTEND_DIR%..\.venv313\Scripts\python.exe"
) else if exist "%FRONTEND_DIR%..\venv313\Scripts\python.exe" (
    set "PYTHON_EXE=%FRONTEND_DIR%..\venv313\Scripts\python.exe"
) else if exist "%FRONTEND_DIR%venv\Scripts\python.exe" (
    set "PYTHON_EXE=%FRONTEND_DIR%venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo ============================================================
echo INOUTX Daily Report Mailer
echo ============================================================
echo Python: %PYTHON_EXE%
echo.

"%PYTHON_EXE%" "%FRONTEND_DIR%daily_report_email.py"

if errorlevel 1 (
    echo.
    echo [ERROR] Daily report email failed.
    exit /b 1
)

echo.
echo [OK] Daily report email completed successfully.
exit /b 0

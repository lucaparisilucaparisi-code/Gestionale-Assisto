@echo off
chcp 65001 >nul
REM Reimposta la password del gestionale senza cancellare i dati.
REM Doppio click su questo file se hai dimenticato la password.
cd /d "%~dp0"

set "VENV_PY=%CD%\.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    "%VENV_PY%" reset_password.py
) else (
    python reset_password.py
)

echo.
pause

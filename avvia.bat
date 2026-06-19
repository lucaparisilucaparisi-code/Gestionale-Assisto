@echo off
chcp 65001 >nul
title Assisto - Gestionale OEPAC
echo ================================================
echo   ASSISTO - Gestionale OEPAC
echo   Avvio automatico
echo ================================================
echo.

REM Vai nella cartella dello script
cd /d "%~dp0"

REM ----- 1. Verifica Python -----
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRORE] Python non trovato sul sistema.
    echo.
    echo    Scarica e installa Python 3.9 o superiore da:
    echo    https://www.python.org/downloads/
    echo.
    echo    IMPORTANTE: durante l'installazione spunta la casella
    echo    "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

REM ----- 2. Verifica file app.py -----
if not exist "app.py" (
    echo [ERRORE] app.py non trovato in questa cartella.
    echo    Directory corrente: %CD%
    echo.
    pause
    exit /b 1
)

REM ----- 3. Installazione / aggiornamento dipendenze -----
REM Usa un flag file per evitare di reinstallare ad ogni avvio.
if not exist ".deps_installed" (
    echo Installazione dipendenze in corso...
    echo (potrebbe richiedere qualche minuto al primo avvio^)
    echo.
    python -m pip install --upgrade pip >nul 2>&1
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERRORE] Installazione dipendenze fallita.
        echo Controlla la connessione internet e riprova.
        pause
        exit /b 1
    )
    echo done > .deps_installed
    echo.
    echo Dipendenze installate correttamente.
    echo.
) else (
    REM Controlla silenziosamente che flask sia disponibile
    python -m pip show flask >nul 2>&1
    if errorlevel 1 (
        echo Reinstallo dipendenze mancanti...
        python -m pip install -r requirements.txt
    )
)

REM ----- 4. Avvia l'applicazione -----
echo.
echo ------------------------------------------------
echo  Avvio server Assisto su http://localhost:5000
echo  Il browser si aprira' automaticamente.
echo  Premi CTRL+C in questa finestra per chiudere.
echo ------------------------------------------------
echo.

REM Apri browser dopo 2 secondi
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:5000"

python app.py

if errorlevel 1 (
    echo.
    echo [ERRORE] L'applicazione si e' chiusa con errore.
    pause
)

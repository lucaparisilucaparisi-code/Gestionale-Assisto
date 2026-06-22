@echo off
chcp 65001 >nul
title Assisto - Gestionale OEPAC
echo ================================================
echo   ASSISTO - Gestionale OEPAC
echo   Avvio automatico
echo ================================================
echo.

REM Vai nella cartella dello script (funziona anche da percorsi di rete)
pushd "%~dp0"

if not exist "app.py" (
    echo [ERRORE] app.py non trovato in questa cartella.
    echo    Cartella corrente: %CD%
    echo.
    pause
    popd
    exit /b 1
)

REM ============================================================
REM  1) Trova Python (py launcher, python su PATH, installazioni note)
REM ============================================================
set "PYEXE="
call :TrovaPython
if defined PYEXE goto PythonOK

REM ----- Python non trovato: installazione automatica -----
echo Python non risulta installato su questo computer.
echo Lo installo automaticamente adesso: serve la connessione a internet.
echo Attendi qualche minuto e NON chiudere questa finestra...
echo.
call :InstallaPython

REM Dopo l'installazione cerca Python piu' volte (l'installer puo' impiegare un po')
set /a TENTATIVI=0
:RiprovaPython
call :TrovaPython
if defined PYEXE goto PythonOK
set /a TENTATIVI+=1
if %TENTATIVI% GEQ 20 goto PythonAssente
timeout /t 3 /nobreak >nul
goto RiprovaPython

:PythonAssente
echo.
echo [ERRORE] Non sono riuscito a installare Python automaticamente.
echo Installa Python 3.12 manualmente da https://www.python.org/downloads/
echo (spunta la casella "Add Python to PATH") e riavvia avvia.bat.
echo.
pause
popd
exit /b 1

:PythonOK
echo Python disponibile:
"%PYEXE%" --version
echo.

REM ============================================================
REM  2) Ambiente isolato (.venv) nella cartella - auto-riparante
REM ============================================================
set "VENV_PY=%CD%\.venv\Scripts\python.exe"
set "RICREA=0"
if not exist "%VENV_PY%" set "RICREA=1"
if exist "%VENV_PY%" "%VENV_PY%" --version >nul 2>&1 || set "RICREA=1"

if "%RICREA%"=="1" (
    echo Preparazione ambiente dell'applicazione...
    if exist ".venv" rmdir /s /q ".venv"
    "%PYEXE%" -m venv ".venv"
    if errorlevel 1 (
        echo.
        echo [ERRORE] Creazione dell'ambiente non riuscita.
        pause
        popd
        exit /b 1
    )
    if exist ".venv\.deps_ok" del ".venv\.deps_ok" >nul 2>&1
)

REM ============================================================
REM  3) Componenti necessari (installati una volta per ambiente)
REM ============================================================
if not exist ".venv\.deps_ok" (
    echo Installazione dei componenti necessari in corso...
    echo (puo' richiedere qualche minuto al primo avvio^)
    echo.
    "%VENV_PY%" -m pip install --upgrade pip >nul 2>&1
    "%VENV_PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERRORE] Installazione dei componenti non riuscita.
        echo Controlla la connessione a internet e riprova.
        pause
        popd
        exit /b 1
    )
    echo ok > ".venv\.deps_ok"
    echo.
    echo Componenti installati correttamente.
    echo.
) else (
    "%VENV_PY%" -m pip show flask >nul 2>&1 || "%VENV_PY%" -m pip install -r requirements.txt
)

REM ============================================================
REM  4) Avvio applicazione
REM ============================================================
echo ------------------------------------------------
echo  Avvio server Assisto su http://localhost:5000
echo  Il browser si aprira' automaticamente.
echo  Premi CTRL+C in questa finestra per chiudere.
echo ------------------------------------------------
echo.

start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:5000"

"%VENV_PY%" app.py

if errorlevel 1 (
    echo.
    echo [ERRORE] L'applicazione si e' chiusa con un errore.
    pause
)
popd
exit /b 0


REM ==================== SUBROUTINE ====================

:TrovaPython
set "PYEXE="
REM Prova il py launcher e ricava il percorso reale dell'eseguibile
for /f "delims=" %%p in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%p"
if defined PYEXE if exist "%PYEXE%" exit /b 0
set "PYEXE="
REM Prova "python" su PATH (escludendo lo stub del Microsoft Store)
for /f "delims=" %%p in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%p"
if defined PYEXE echo %PYEXE% | find /i "WindowsApps" >nul && set "PYEXE="
if defined PYEXE if exist "%PYEXE%" exit /b 0
set "PYEXE="
REM Cerca installazioni note (per-utente e di sistema)
for /d %%d in ("%LocalAppData%\Programs\Python\Python3*") do if exist "%%d\python.exe" set "PYEXE=%%d\python.exe"
if defined PYEXE exit /b 0
for /d %%d in ("%ProgramFiles%\Python3*") do if exist "%%d\python.exe" set "PYEXE=%%d\python.exe"
if defined PYEXE exit /b 0
exit /b 1

:InstallaPython
set "PYVER=3.12.7"
REM Architettura: usa amd64 (gira nativo su x64 e in emulazione su ARM64,
REM con la massima compatibilita' dei pacchetti). Solo per Windows a 32 bit usa x86.
set "ARCHSUF=-amd64"
if /i "%PROCESSOR_ARCHITECTURE%"=="x86" if not defined PROCESSOR_ARCHITEW6432 set "ARCHSUF="
set "PYURL=https://www.python.org/ftp/python/%PYVER%/python-%PYVER%%ARCHSUF%.exe"
set "PYINST=%TEMP%\python-%PYVER%%ARCHSUF%-assisto.exe"

echo Scarico Python %PYVER%...
if exist "%PYINST%" del "%PYINST%" >nul 2>&1
REM curl e' incluso in Windows 10/11
curl -L --fail -o "%PYINST%" "%PYURL%" 2>nul
if not exist "%PYINST%" (
    echo Riprovo il download...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PYURL%' -OutFile '%PYINST%' -UseBasicParsing } catch { exit 1 }"
)
if not exist "%PYINST%" (
    echo [ERRORE] Download di Python non riuscito.
    exit /b 1
)

REM Verifica che il file scaricato sia valido (almeno ~1 MB)
for %%A in ("%PYINST%") do if %%~zA LSS 1000000 (
    echo [ERRORE] Il download di Python sembra incompleto.
    del "%PYINST%" >nul 2>&1
    exit /b 1
)

echo Installazione di Python in corso (per l'utente corrente, senza amministratore)...
"%PYINST%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=0 Include_pip=1 Include_test=0 Include_tcltk=0 Shortcuts=0 AssociateFiles=0
del "%PYINST%" >nul 2>&1
exit /b 0

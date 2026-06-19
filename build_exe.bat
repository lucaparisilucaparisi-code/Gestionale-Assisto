@echo off
echo ================================================
echo   Gestionale OEPAC - Build Eseguibile
echo ================================================
echo.

REM Verifica se Python e installato
python --version >nul 2>&1
if errorlevel 1 (
    echo ERRORE: Python non trovato. Installa Python 3.9+ da python.org
    pause
    exit /b 1
)

REM Installa dipendenze
echo Installazione dipendenze...
pip install -r requirements.txt

REM Build con PyInstaller
echo.
echo Creazione eseguibile...
pyinstaller --noconfirm --onefile --windowed ^
    --name "GestionaleOEPAC" ^
    --icon "static/icon.ico" ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    --hidden-import "pandas" ^
    --hidden-import "openpyxl" ^
    --hidden-import "xlsxwriter" ^
    app.py

echo.
echo ================================================
if exist "dist\GestionaleOEPAC.exe" (
    echo BUILD COMPLETATO!
    echo.
    echo L'eseguibile si trova in: dist\GestionaleOEPAC.exe
    echo.
    echo Per avviare: esegui dist\GestionaleOEPAC.exe
    echo Il browser si aprira automaticamente su http://localhost:5000
) else (
    echo ERRORE durante la build. Controlla i messaggi sopra.
)
echo ================================================
pause

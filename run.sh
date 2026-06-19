#!/bin/bash
# ==========================================================
# Assisto - Gestionale OEPAC
# Script di avvio per macOS / Linux
# ==========================================================

set -e

cd "$(dirname "$0")"

echo "=========================================="
echo "  ASSISTO - Gestionale OEPAC"
echo "  Avvio automatico"
echo "=========================================="

# ----- 1. Verifica Python -----
if ! command -v python3 >/dev/null 2>&1; then
    echo ""
    echo "[ERRORE] python3 non trovato."
    echo "Installa Python 3.9+ da https://www.python.org/downloads/"
    exit 1
fi

# ----- 2. Installazione dipendenze (una sola volta) -----
if [ ! -f ".deps_installed" ]; then
    echo ""
    echo "Installazione dipendenze in corso..."
    echo "(potrebbe richiedere qualche minuto al primo avvio)"
    echo ""
    python3 -m pip install --upgrade pip >/dev/null 2>&1 || true
    python3 -m pip install -r requirements.txt
    echo "done" > .deps_installed
    echo ""
    echo "Dipendenze installate correttamente."
fi

# ----- 3. Avvia l'applicazione -----
echo ""
echo "------------------------------------------------"
echo " Avvio server Assisto su http://localhost:5000"
echo " Apri il browser su questo indirizzo."
echo " Premi CTRL+C per chiudere."
echo "------------------------------------------------"
echo ""

# Prova ad aprire il browser su macOS/Linux
(sleep 2 && (xdg-open http://localhost:5000 >/dev/null 2>&1 || open http://localhost:5000 >/dev/null 2>&1 || true)) &

python3 app.py

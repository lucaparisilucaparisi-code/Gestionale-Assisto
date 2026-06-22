#!/bin/bash
# ==========================================================
# Assisto - Gestionale OEPAC
# Script di avvio per macOS / Linux
# Prepara automaticamente un ambiente isolato (.venv) nella
# cartella e installa i componenti necessari al primo avvio.
# ==========================================================

set -e
cd "$(dirname "$0")"

echo "=========================================="
echo "  ASSISTO - Gestionale OEPAC"
echo "  Avvio automatico"
echo "=========================================="

if [ ! -f "app.py" ]; then
    echo ""
    echo "[ERRORE] app.py non trovato in questa cartella."
    exit 1
fi

# ----- 1. Verifica Python -----
PY=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        PY="$cand"
        break
    fi
done

if [ -z "$PY" ]; then
    echo ""
    echo "[ERRORE] Python 3 non trovato."
    echo "Installa Python 3.9 o superiore, poi riavvia ./run.sh"
    echo "  - macOS:  brew install python   (oppure da https://www.python.org/downloads/)"
    echo "  - Linux:  sudo apt install python3 python3-venv   (Debian/Ubuntu)"
    exit 1
fi

# ----- 2. Ambiente isolato (.venv), auto-riparante -----
VENV_PY=".venv/bin/python"
RICREA=0
if [ ! -x "$VENV_PY" ]; then
    RICREA=1
elif ! "$VENV_PY" --version >/dev/null 2>&1; then
    RICREA=1
fi

if [ "$RICREA" = "1" ]; then
    echo ""
    echo "Preparazione ambiente dell'applicazione..."
    rm -rf .venv
    "$PY" -m venv .venv
    rm -f .venv/.deps_ok
fi

# ----- 3. Componenti necessari (una volta per ambiente) -----
if [ ! -f ".venv/.deps_ok" ]; then
    echo ""
    echo "Installazione dei componenti necessari in corso..."
    echo "(puo' richiedere qualche minuto al primo avvio)"
    echo ""
    "$VENV_PY" -m pip install --upgrade pip >/dev/null 2>&1 || true
    "$VENV_PY" -m pip install -r requirements.txt
    echo "ok" > .venv/.deps_ok
    echo ""
    echo "Componenti installati correttamente."
else
    "$VENV_PY" -m pip show flask >/dev/null 2>&1 || "$VENV_PY" -m pip install -r requirements.txt
fi

# ----- 4. Avvia l'applicazione -----
echo ""
echo "------------------------------------------------"
echo " Avvio server Assisto su http://localhost:5000"
echo " Il browser si aprira' automaticamente."
echo " Premi CTRL+C per chiudere."
echo "------------------------------------------------"
echo ""

(sleep 2 && (xdg-open http://localhost:5000 >/dev/null 2>&1 || open http://localhost:5000 >/dev/null 2>&1 || true)) &

exec "$VENV_PY" app.py

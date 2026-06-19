# Gestionale OEPAC - Istruzioni per Creare l'Eseguibile

## Requisiti
- Windows 10/11
- Python 3.9 o superiore (scaricalo da https://python.org)
- Durante l'installazione di Python, seleziona "Add Python to PATH"

## Come Creare l'Eseguibile

### Metodo 1: Script Automatico (Consigliato)
1. Apri la cartella `gestionale-oepac` in Esplora File
2. Fai doppio click su `build_exe.bat`
3. Attendi il completamento (circa 2-3 minuti)
4. L'eseguibile sarà in `dist/GestionaleOEPAC.exe`

### Metodo 2: Manuale
1. Apri il Prompt dei comandi (cmd)
2. Naviga nella cartella del progetto:
   ```
   cd percorso/alla/cartella/gestionale-oepac
   ```
3. Installa le dipendenze:
   ```
   pip install -r requirements.txt
   ```
4. Crea l'eseguibile:
   ```
   pyinstaller --onefile --windowed --name "GestionaleOEPAC" --add-data "templates;templates" --add-data "static;static" app.py
   ```

## Come Usare l'Eseguibile

1. Copia `dist/GestionaleOEPAC.exe` dove preferisci
2. Fai doppio click per avviarlo
3. Si aprirà automaticamente il browser su http://localhost:5000
4. Per chiudere: chiudi la finestra del terminale o premi Ctrl+C

## Note Importanti

- **Database**: Il file `gestionale.db` viene creato nella stessa cartella dell'eseguibile
- **Prima esecuzione**: Al primo avvio vengono create le tabelle e i dati predefiniti
- **Backup**: Fai regolarmente backup del file `gestionale.db`
- **Antivirus**: Alcuni antivirus potrebbero segnalare l'eseguibile come sospetto (falso positivo). Aggiungi un'eccezione se necessario.

## Problemi Comuni

### "Python non trovato"
- Installa Python da https://python.org
- Assicurati di selezionare "Add Python to PATH" durante l'installazione

### "pip non riconosciuto"
- Apri cmd come amministratore
- Esegui: `python -m pip install --upgrade pip`

### L'eseguibile non si avvia
- Prova ad eseguirlo da cmd per vedere eventuali errori
- Verifica che la porta 5000 non sia già in uso

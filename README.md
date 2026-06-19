# Assisto - Gestionale OEPAC

Sistema web locale per la gestione e rendicontazione del servizio OEPAC
(Operatore Educativo per l'Autonomia e la Comunicazione).

---

## Avvio rapido (per utenti non tecnici)

### Windows

1. **Scarica** il pacchetto ZIP da GitHub ed estrailo in una cartella.
2. Entra nella cartella `gestionale-oepac`.
3. **Fai doppio click su `avvia.bat`**.
4. La prima volta attendi qualche minuto: il sistema installa automaticamente tutto il necessario.
5. Il browser si aprirà da solo su `http://localhost:5000`.
6. Al primo avvio crea username e password nella pagina di setup.
   Se hai Windows Hello, puoi aggiungere anche l'impronta digitale dal menu
   **Profilo** (in alto a destra).

### macOS / Linux

1. Apri il Terminale nella cartella `gestionale-oepac`.
2. Esegui:
   ```bash
   ./run.sh
   ```
3. Apri il browser su `http://localhost:5000`.

---

## Requisiti

- **Python 3.9 o superiore** installato sul sistema
  ([scarica da python.org](https://www.python.org/downloads/))
  - Su Windows: durante l'installazione spunta **"Add Python to PATH"**
- Connessione internet al primo avvio (per installare le dipendenze)

Tutte le dipendenze Python (`flask`, `pandas`, `openpyxl`, `xlsxwriter`,
`python-docx`, `pillow`, `webauthn`) vengono installate **automaticamente** da
`avvia.bat` / `run.sh` la prima volta.

---

## Funzionalità

- **Autenticazione**: username + password, con opzione impronta digitale (Windows Hello / WebAuthn)
- **Import Excel**: carica dati utenti da file Excel (Commessa, Scuola, Nome, Monte Ore)
- **Rendicontazione mensile**: inserimento ore lavorate e pasti per ogni utente, con salvataggio automatico
- **Calcoli automatici**:
  - Conversione ore 60' ↔ 100'
  - Media mensile basata su giorni lavorativi
  - Tasso assenza 11%
  - Imponibile, IVA 5%, Totali
  - Credito/Debito
- **Calendario scolastico**: giorni lavorativi per mese (Settembre-Giugno)
- **Statistiche avanzate**: heatmap presenze, confronto annuale, top utenti
- **Export report**: Excel e PDF con opzione privacy (nomi puntati)
- **Reportistica DD**: report dedicati per Direttore di Dipartimento

## Parametri di calcolo

| Parametro | Valore |
|-----------|--------|
| Costo orario | 24,07 € (su ore in 100') |
| IVA | 5% |
| Tasso assenza medio | 11% |
| Coefficiente giornaliero | 0,2 |

### Formule

- **Media Mensile** = Monte Ore Settimanale × (Giorni Lavorativi × 0,2)
- **Media con Assenza** = Media Mensile × 0,89
- **Ore 100'** = Ore 60' × 100 / 60
- **Imponibile** = Ore 100' × 24,07 €
- **Totale** = Imponibile + (Imponibile × 5%)
- **Credito/Debito** = Ore Lavorate - Media con Assenza

---

## Struttura file Excel per import

Il file Excel deve contenere le seguenti colonne:

- **Commessa**: "OEPAC IV" o "OEPAC V"
- **Scuola** (o IC, Plesso): nome completo IC-plesso-indirizzo
- **Nome** e **Cognome** (separati) oppure **Utente/Nominativo** (combinato)
- **Monte Ore** (o Ore): monte ore settimanale

## Struttura progetto

```
gestionale-oepac/
├── avvia.bat           # Avvio per Windows (doppio click)
├── run.sh              # Avvio per macOS/Linux
├── app.py              # Applicazione Flask principale
├── database.py         # Gestione database SQLite
├── config.py           # Configurazione
├── requirements.txt    # Dipendenze Python
├── gestionale.db       # Database (creato al primo avvio)
├── static/             # CSS, JS, icone
├── templates/          # Pagine HTML
├── uploads/            # File caricati
└── exports/            # File esportati
```

## Commesse supportate

- **OEPAC IV**: Municipio IV
- **OEPAC V**: Municipio V

---

## FAQ

**Dove sono salvati i miei dati?**
Tutto è salvato localmente nel file `gestionale.db` dentro la cartella del
gestionale. Fai una copia di quel file per avere un backup.

**Come reimposto la password?**
Cancella il file `gestionale.db` (perderai i dati!) oppure apri la pagina
**Profilo** dal menu.

**L'impronta non funziona / dice "WebAuthn non disponibile"**
Assicurati di avere Windows Hello configurato e chiudi/riapri `avvia.bat` così
da installare il pacchetto `webauthn`. In ogni caso puoi sempre accedere con
username e password.

**Posso usarlo da un altro PC?**
No, il gestionale è pensato per girare in locale sul tuo PC. I dati restano sul
tuo computer.

## Test (per sviluppatori)

Il progetto include una suite di test (`tests/`) che copre i calcoli core
(media prevista, variazioni monte ore, liste di attesa) e gli endpoint API
principali. I test usano un database temporaneo e **non toccano** `gestionale.db`.

```bash
pip install -r requirements-dev.txt
pytest
```

## Note tecniche

- Il database SQLite viene creato automaticamente al primo avvio.
- I dati importati vengono aggiunti/aggiornati, mai cancellati automaticamente.
- L'anno scolastico va da Settembre a Giugno.
- Il calendario scolastico segue le date della Regione Lazio.

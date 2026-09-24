# Assisto - Gestionale OEPAC

Sistema web locale per la gestione e rendicontazione del servizio OEPAC
(Operatore Educativo per l'Autonomia e la Comunicazione).

---

## Avvio rapido (per utenti non tecnici)

> **Scarico più facile:** vai alla pagina
> [**Releases**](https://github.com/lucaparisilucaparisi-code/Gestionale-Assisto/releases/latest)
> e scarica **Source code (zip)** dall'ultima versione. È il modo più immediato per
> avere sempre la versione aggiornata con un solo clic.

### Windows

1. **Scarica** il pacchetto ZIP da GitHub ed estrailo in una cartella.
2. Entra nella cartella creata dallo ZIP: si chiama `Gestionale-Assisto-` seguito dal
   numero di versione (per esempio `Gestionale-Assisto-1.20.0`).
3. **Fai doppio click su `avvia.bat`**.
4. La prima volta attendi qualche minuto: il sistema installa automaticamente
   tutto il necessario, **incluso Python** se non è già presente sul computer
   (serve la connessione a internet). Non serve essere amministratore.
5. Il browser si aprirà da solo su `http://localhost:5000`.
6. Al primo avvio crea username e password nella pagina di setup.
   Se hai Windows Hello, puoi aggiungere anche l'impronta digitale dal menu
   **Profilo** (in alto a destra).

> Puoi spostare la cartella dove vuoi (anche su un altro PC): al doppio click
> `avvia.bat` ricontrolla cosa manca e lo reinstalla da solo.

### macOS / Linux

1. Apri il Terminale nella cartella `Gestionale-Assisto-…` estratta dallo ZIP.
2. Esegui:
   ```bash
   ./run.sh
   ```
3. Apri il browser su `http://localhost:5000`.

> Su macOS/Linux Python di solito è già presente; se manca, lo script ti dice
> il comando esatto per installarlo. Le dipendenze vengono comunque gestite da solo.

---

## Aggiornare a una nuova versione

I tuoi dati sono tutti nel file **`gestionale.db`**, nella cartella del programma.
Aggiornare vuol dire: mettere la versione nuova in una cartella nuova e copiarci
dentro quel file **prima** di avviarla. Segui i passi nell'ordine.

1. **Chiudi il programma.** Chiudi la finestra nera di Assisto e controlla che non
   ce ne sia un'altra aperta, nemmeno ridotta a icona nella barra in basso.
   (Se due versioni restano aperte insieme, la nuova non parte e lo dice.)
2. **Controlla il file `gestionale.db-wal`.** Nella cartella vecchia guarda accanto a
   `gestionale.db` (con le estensioni nascoste può comparire come `gestionale`).
   Se c'è un file `gestionale.db-wal` **più grande di 0 KB**, riapri la versione
   vecchia, aspetta che si apra il browser e richiudila: il file sparisce o diventa
   di 0 KB. In alternativa, al passo 5 copia insieme tutti e tre i file
   `gestionale.db`, `gestionale.db-wal` e `gestionale.db-shm`.
3. **Per sicurezza**, copia `gestionale.db` anche su una chiavetta o in un'altra
   cartella, e non toccare quella copia.
4. **Scarica la nuova versione** (Source code zip dalla pagina Releases) ed
   estraila **in una cartella nuova**, accanto a quella vecchia (non dentro la
   cartella Download, che a volte si svuota). Si crea una cartella
   `Gestionale-Assisto-` con il numero della versione.
5. **Prima del primo avvio** copia nella cartella nuova, accanto ad `avvia.bat`:
   - il file `gestionale.db`;
   - le cartelle `backups` e `uploads`, se ci sono.

   Non copiare la cartella `.venv`: `avvia.bat` la ricrea con i componenti giusti.
   Se hai già avviato la nuova versione per sbaglio, chiudila e nella cartella nuova
   cancella `gestionale.db`, `gestionale.db-wal` e `gestionale.db-shm` prima di copiare.
6. **Avvia** con doppio click su `avvia.bat` nella cartella nuova. La prima volta
   serve internet e ci vogliono alcuni minuti. All'avvio viene fatto da solo un
   backup del database com'era prima dell'aggiornamento (cartella `backups`).
7. **Controlla**: entra con lo stesso nome utente e la stessa password di prima e
   verifica che ci siano tutti gli utenti, le ore dell'ultimo mese, le determine
   nella Reportistica DD e l'ultima cosa che avevi fatto.
8. **Tieni la cartella vecchia** per qualche settimana, senza cancellarla: se
   qualcosa non ti convince, chiudi la nuova e riapri la vecchia, il suo file non è
   stato toccato.

> **Non usare il "Trasloco" con file JSON per aggiornare** (Esporta dalla vecchia,
> Importa nella nuova): un file esportato da una versione precedente alla 1.10.0 non
> contiene determine, recuperi, correzioni dei report, date di inizio e fine servizio
> e storico. Il trasloco JSON serve per spostarsi su un altro PC con la **stessa**
> versione. Non usare nemmeno "Ripristina backup" come metodo di aggiornamento.

---

## Requisiti

- **Connessione internet al primo avvio** (per scaricare Python e/o le dipendenze).
- Su **Windows** non serve installare nulla a mano: `avvia.bat` installa Python
  automaticamente se manca. In alternativa puoi installarlo da
  [python.org](https://www.python.org/downloads/) spuntando **"Add Python to PATH"**.
- Su **macOS/Linux** serve **Python 3.9 o superiore** (quasi sempre già presente).

Python e tutte le dipendenze (`flask`, `pandas`, `openpyxl`, `xlsxwriter`,
`python-docx`, `pillow`, `webauthn`) vengono predisposti **automaticamente** in un
ambiente isolato dentro la cartella (`.venv`) da `avvia.bat` / `run.sh` al primo avvio.

---

## Funzionalità

- **Autenticazione**: username + password, con opzione impronta digitale (Windows Hello / WebAuthn)
- **Import Excel anagrafica**: carica dati utenti da file Excel (Commessa, Scuola, Nome, Monte Ore)
- **Import Excel rendicontazione**: carica ore e pasti mensili dalla prefattura (un foglio per mese), con abbinamento automatico agli utenti già in anagrafica e anteprima prima del salvataggio
- **Rendicontazione mensile**: inserimento ore lavorate e pasti per ogni utente, con salvataggio automatico,
  navigazione da tastiera come in un foglio di calcolo (Invio/frecce, incolla di una colonna da Excel) e
  ogni modifica registrata nel registro attività
- **Report con filtri avanzati** (scuola, ricerca, ore erogate) validi per tutti i download e l'anteprima
- **Trasloco su un altro PC**: esporta/importa un file JSON con *tutti* i dati (anche variazioni, personale,
  turni, note) in modalità Unisci, Solo nuovi o Sostituisci tutto (con backup automatico). È completo solo
  con file esportati dalla versione 1.10.0 in poi (il registro attività non viene trasferito); per aggiornare il programma vedi
  [Aggiornare a una nuova versione](#aggiornare-a-una-nuova-versione)
- **Chiusura mese guidata**: procedura in 4 passi (completezza → anomalie → riepilogo → export);
  un mese chiuso **non accetta più modifiche alle ore** (né a mano, né da import) finché non viene riaperto
- **Variazioni monte ore** con mese di inizio e, se serve, di fine: aumenti temporanei che non si trascinano
- **Nuovo anno scolastico** (wizard in Dashboard, da giugno a ottobre): calendario automatico + revisione
  degli utenti in un'unica tabella (chiusura al 31/8 delle variazioni dell'anno prima, monte ore di partenza,
  archiviazione di chi ha lasciato il servizio)
- **Archiviazione utenti**: chi esce dal servizio sparisce da elenchi e rendicontazione ma conserva tutto lo
  storico (filtro "Archiviati" e ripristino con un click)
- **Dashboard "Stato del mese"**: avanzamento rendicontazione, avvisi e validazione dati in evidenza
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
- **Credito/Debito** = Media con Assenza − Ore Lavorate
  - valore **positivo** = **debito** di ore (ha lavorato meno del previsto, ore da recuperare)
  - valore **negativo** = **credito** di ore (ha lavorato più del previsto)

---

## Struttura file Excel per import

Il file Excel deve contenere le seguenti colonne:

- **Commessa**: "OEPAC IV" o "OEPAC V"
- **Scuola** (o IC, Plesso): nome completo IC-plesso-indirizzo
- **Nome** e **Cognome** (separati) oppure **Utente/Nominativo** (combinato)
- **Monte Ore** (o Ore): monte ore settimanale

## Struttura progetto

```
Gestionale-Assisto-<versione>/
├── avvia.bat           # Avvio per Windows (doppio click)
├── run.sh              # Avvio per macOS/Linux
├── app.py              # Applicazione Flask principale
├── routes_export.py    # Route export/report (Excel, Word)
├── database.py         # Gestione database SQLite
├── config.py           # Configurazione
├── requirements.txt    # Dipendenze Python
├── gestionale.db       # Database (creato al primo avvio)
├── static/             # CSS, JS, icone
├── templates/          # Pagine HTML
├── uploads/            # File caricati
└── exports/            # File esportati
```

### Organizzazione del menu

- **Principale**: Dashboard
- **Lavoro mensile**: Rendicontazione · Utenti (assistiti) · Chiusura Mese
- **Personale**: Dipendenti (operatori OEPAC, con assegnazione agli assistiti)
- **Analisi**: Report e Statistiche (tab: Export report, Reportistica DD, Statistiche)
- **Dati**: Import Excel
- **Configurazione**: Impostazioni (Commesse, Calendario, Profilo)

## Commesse supportate

- **OEPAC IV**: Municipio IV
- **OEPAC V**: Municipio V

---

## FAQ

**Dove sono salvati i miei dati?**
Tutto è salvato localmente nel file `gestionale.db` dentro la cartella del
gestionale. Fai una copia di quel file (a programma chiuso) per avere un backup.
Per passare a una nuova versione vedi
[Aggiornare a una nuova versione](#aggiornare-a-una-nuova-versione).

**Come reimposto la password?**
Se sei loggato, cambiala dalla pagina **Profilo** dal menu.
Se l'hai **dimenticata**, NON serve cancellare i dati: fai doppio click su
**`reimposta_password.bat`** (Windows) oppure esegui `python reset_password.py`
(macOS/Linux) nella cartella del gestionale, e imposta una nuova password. I tuoi
dati restano intatti.

**Come salvo un backup dove voglio (chiavetta, cloud)?**
Dal gestionale ogni backup può essere **scaricato** come file `.db` e messo dove
preferisci. In più, prima di ogni import viene creato automaticamente un backup
di sicurezza, così puoi sempre tornare indietro ripristinandolo.

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

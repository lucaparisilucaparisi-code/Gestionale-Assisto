# Architettura & guida sviluppatore — Gestionale OEPAC

Nota tecnica per chi sviluppa. Per l'uso e l'installazione vedi il `README.md`.

## Struttura dei moduli

| File | Responsabilità |
|------|----------------|
| `app.py` | Applicazione Flask: route pagine e molte API, autenticazione (sessione + WebAuthn), import. Registra i blueprint sotto. |
| `database.py` | Tutto l'accesso ai dati SQLite: schema/migrazioni, CRUD, calcoli di dominio. |
| `napoli_schema.py` | Solo lo schema della sezione Napoli (tabelle `napoli_*`): le migrazioni 2 e 3 di `database.py` (vedi "Sezione Napoli"). |
| `napoli_calcoli.py` | Calcoli di Napoli, solo funzioni pure (niente database, Flask o `config` di Roma): letture delle ore, ore riconosciute, settimane e PEI, regole con data, fattura. |
| `config_napoli.py` | Valori predefiniti di Napoli: regole con data (`REGOLE_PREDEFINITE`), modelli dei testi della fattura, tariffe solo *proposte*. |
| `routes_export.py` | Blueprint export (Excel, PDF, Word). |
| `routes_backup.py` | Blueprint backup/ripristino (`/api/backup...`). |
| `routes_migrazione.py` | Blueprint migrazione dati JSON e audit log (`/api/migrazione`, `/api/audit`). Formato v3.0: tutte le tabelle di dominio (`TABELLE_DOMINIO`), import merge/skip/replace con rimappatura delle FK (`TABELLE_MERGE`). |
| `routes_report_locale.py` | Blueprint reportistica DD, recuperi, override (`/reportistica-locale`, `/api/dd`, `/api/recuperi`, override). |
| `validators.py` | Validazione input condivisa (`validate_string/number/integer`). |
| `config.py` | Costanti economiche, parametri, logging e l'helper `calcola_fatturazione`. |
| `import_*.py` | Parsing dei file Excel (anagrafica e rendicontazione). |
| `templates/`, `static/` | UI (Jinja2, CSS, JS, PWA). |
| `tests/` | Suite pytest su DB temporaneo (non tocca `gestionale.db`). |
| `strumenti/` | Solo per chi sviluppa, fuori dal programma: fotografia delle uscite di Roma e confronto fra due versioni (vedi "Protezioni per Roma"). |

## Regole di dominio da NON duplicare

Queste logiche hanno una **sola** implementazione condivisa: usarla sempre, mai
reimplementarla inline (a schermo, in SQL o negli export).

- **Fatturazione** → `config.calcola_fatturazione(ore)` ritorna `(imponibile, iva, totale)`.
  Arrotonda una sola volta sull'aggregato: **non** sommare valori già arrotondati,
  e **non** hardcodare la tariffa o il moltiplicatore IVA nelle query.
- **Media prevista** → `database.calcola_media_prevista(monte_ore, giorni)`.
- **Giorni lavorativi effettivi** → `database.risolvi_giorni_lavorativi(giorni_calendario)`
  (regola unica: calendario → `GIORNI_LAVORATIVI_DEFAULT`). Deve valere identica in
  vista mensile, storico e aggregati.
- **Anno scolastico** → `config.anno_scolastico_di(anno, mese, sep)` (mese ≥ 9 →
  anno/anno+1). `sep='-'` è il formato chiave del DB, `sep='/'` quello dei report.
  L'anno di oggi è `config.anno_scolastico_corrente()`: mai anni scritti a mano.
- **Mese precedente** → `config.mese_scolastico_precedente(anno, mese)` (settembre →
  giugno, gennaio → dicembre): "Copia Mese Prec.", scostamenti e "Confronto Mese".
- **Monte ore effettivo** → `database.risolvi_monte_ore(base, variazioni, 'YYYY-MM')`
  (singolo utente) e `get_monte_ore_effettivo_bulk(anno, mese)` (vista mensile): vale
  l'ultima variazione iniziata entro il mese e non terminata (`mese_fine` NULL o ≥ mese).
  Il wizard di nuovo anno chiude al 31/8 quelle aperte (`prepara_utenti_nuovo_anno`).
  Le colonne "Monte Ore" di tutti gli export mostrano `monte_ore_effettivo` del mese
  (l'annuale: la media dei mesi attivi), mai la base di oggi.
- **Variazioni del wizard (monte ore nuovo anno)** → quando il passo Utenti cambia il
  monte ore BASE di chi ha ore nei mesi passati, `_conserva_monte_ore_passato` registra
  prima una variazione CHIUSA ad agosto con il valore vecchio: inizio = il piu' vecchio tra
  prima riga, `data_inizio` e primo mese con dati del gestionale (questo SEMPRE, anche con
  `data_inizio`: il Municipale confronta ogni mese con settembre per la colonna "Di cui
  hanno ricevuto incremento ore" e partendo da `data_inizio` una diminuzione diventava un
  falso incremento) e comunque prima di ogni variazione esistente (che continua a
  vincere nei suoi mesi). Cosi' i mesi passati non cambiano e il nuovo valore vale da
  settembre. Anche i controlli di validazione usano il monte ore del mese
  (`get_monte_ore_effettivo_bulk`), non la base di oggi. Cambiare la base
  dalla finestra "Modifica utente" vale invece per TUTTI i mesi: la pagina lo chiede
  (con la via "Variazioni") se l'utente ha gia' mesi rendicontati.
- **Archiviati (attivo = 0)** → regola unica `database.sql_utente_nel_mese(anno, mese)`
  (e `sql_utente_nell_anno` per gli elenchi di un anno, es. heatmap): un archiviato conta
  in un mese se ha una riga di rendicontazione in quel mese, OPPURE se il mese e' prima
  del mese dell'archiviazione (`utenti.archiviato_dal` 'YYYY-MM': allora era attivo e
  conta come tale, anche senza riga; se manca, archiviato da una versione precedente, si
  ripiega sull'ultimo mese con una riga), OPPURE se il mese, non futuro, e' nel suo
  periodo di servizio con `data_fine` valorizzata. `archiviato_dal` lo scrive solo il
  passaggio da attivo ad archiviato (PUT utente e `delete_utente`: mese di oggi,
  `mese_archiviazione()`; passo Utenti del nuovo anno: settembre di quell'anno se piu'
  avanti di oggi), lo toglie il ripristino, lo riportano Ctrl+Z e il trasloco JSON. Va
  usata al posto di `u.attivo = 1` in ogni calcolo mensile/annuale (vista mensile e
  quindi tutti gli export, statistiche, "da completare", validazione, classifica del
  mese, e `num_utenti` di `/api/stats/filtered` con anno e mese, cioe' lo "Stato del
  mese"); le somme che partono dalle righe di rendicontazione non filtrano su `attivo`.
  Anche i totali mostrati accanto a un elenco del passato vengono dalla stessa regola,
  non dagli attivi di oggi: la heatmap delle Statistiche restituisce `totale` (utenti
  dell'anno scelto, archiviati compresi) e la pagina lo usa per "Mostrati N su M" e come
  limite di "Mostra tutti".
  Restano su `attivo = 1` solo gli elenchi e i conteggi "di oggi" (pagina Utenti, utenti
  attivi, wizard, assegnazioni, ricerca). "Copia Mese Prec." e "Compila con media" non
  scrivono righe per gli archiviati.
- **Lista d'attesa per anno scolastico** → `utenti.lista_attesa_as` ('2025-2026') e
  `database.lista_attesa_dell_anno(lista, anno_lista, anno_scolastico)`: un'etichetta conta
  solo nei mesi del suo anno scolastico (`get_rendicontazione_completa` la azzera negli
  altri, quindi tutti i report la rispettano; l'etichetta della scheda resta in
  `lista_attesa_scheda`). Ogni scrittura di `lista_attesa` imposta anche l'anno (quello
  corrente o quello passato); quelle senza anno (DB vecchi, trasloco JSON, undo di
  azioni vecchie) le completa `completa_anno_liste_attesa` con l'anno dell'ULTIMO mese con
  una riga dell'utente (o l'anno corrente), anche a ogni `init_db`. Le pagine mostrano
  un'etichetta di un anno passato attenuata e con l'anno ("Marzo 25/26",
  `info_lista_attesa`).
- **Mese chiuso** → `_risposta_mese_chiuso(anno, mese)` in `app.py`: ogni route che
  scrive ore (singola, batch, copia, compila, import) deve passarci e rispondere 409.
  Il trasloco JSON "Unisci"/"Solo nuovi" salta le righe dei mesi chiusi che le
  cambierebbero e le riporta nell'esito (`saltate_mese_chiuso`, `avvisi`).
- **Limiti di ore e pasti** → `config.MAX_ORE_MENSILI` (200) e `MAX_PASTI_MENSILI` (62,
  due pasti al giorno per 31 giorni), letti da `_valida_riga_rendicontazione` (che dice
  anche il campo sbagliato: il batch risponde con utente, `utente_id` e `campo`),
  dall'import Excel (`import_rendicontazione.motivo_fuori_limite`: righe fuori limite non
  scritte e riportate) e dalla pagina (`APP_CONFIG`). In Rendicontazione ogni casella si
  controlla PRIMA di inviarla (`controllaCasella`): una non valida resta in rosso con il
  motivo e non entra nel pacchetto, cosi' non blocca le altre ("o tutto o niente" del
  server). Piu' pasti dei giorni di scuola e' solo un avviso (`pasti_oltre_giorni` in
  `/api/stats/validazione`, quindi in Da fare e Chiusura Mese).
- **Totali per plesso** → sempre per `scuola_id`, mai per nome: piu' plessi possono avere lo
  stesso nome in commesse diverse (vista "Tutte"). `get_totali_per_scuola` restituisce
  `scuola_id`; la pagina (renderTable, `calculateTotaliScuola`, filtro Scuola) e il foglio
  "Dettaglio per Scuola" dell'Excel raggruppano per id (`scuola_id` anche come filtro
  degli export).
- **Giorni di scuola per tipo** → infanzia / altri ordini con `get_calendario_full` +
  `is_scuola_infanzia` + `risolvi_giorni_lavorativi`, come la vista mensile: anche la
  heatmap delle Statistiche e l'anteprima di "Copia Mese Prec." (`GET .../copia-precedente`:
  oltre `config.SOGLIA_GIORNI_COPIA_PERCENTUALE` di differenza la pagina avvisa e
  propone "Compila con media").
- **Annulla (Ctrl+Z)** → si annullano solo le azioni piu' recenti di
  `config.UNDO_VALIDITA_ORE` (limite calcolato in Python, `database.limite_undo`, in ora
  locale come i timestamp). Le piu' vecchie restano in memoria ma non sono annullabili
  (`DELETE /api/undo/scadute` le toglie). La pagina chiede sempre conferma con
  `GET /api/undo/ultima` (descrizione e data) e manda l'`id` mostrato: se nel frattempo
  l'ultima azione e' un'altra, 409. Dopo l'annullamento si ricarica la vista
  (`window.ricaricaDopoAnnulla` se la pagina lo definisce).
- **Cancellazione utente** → `database.elimina_utente_completo(cursor, id)` +
  `raccogli_snapshot_utente` per l'undo: mai DELETE diretti (le FK sono applicate).
- **Match nominativi** → sempre `COLLATE NOCASE` su nome/cognome (evita duplicati
  da differenze di maiuscole negli import).

## Convenzioni

- **Suffissi `_60` / `_100`**: `_60` = ore in formato sessagesimale (base 60'),
  `_100` = ore in formato centesimale/decimale (base 100'). Nel dataset attuale i due
  valori coincidono (i dati sono importati già in centesimale); le colonne restano
  distinte per compatibilità con i report.
- **Naming**: verbi tecnici/CRUD in inglese (`get_`, `update_`, `delete_`), concetti di
  dominio in italiano (`calcola_media_prevista`, `commessa`, `rendicontazione`). Le
  colonne DB sono in italiano. Mantenere questa coerenza nelle nuove funzioni.
- **Credito/Debito**: `media_con_assenza - ore_lavorate`. Positivo = **debito** (ore da
  recuperare), negativo = **credito**.

## Database

- Connessioni tramite `database.get_db_context()` (context manager con commit su
  uscita pulita e rollback su errore). La factory unica `_connect()` imposta
  `foreign_keys=ON`, `busy_timeout` e `journal_mode=WAL`.
- Le FOREIGN KEY sono **applicate**: le cancellazioni con `ON DELETE CASCADE`
  funzionano (niente righe orfane). Attenzione a inserire sempre i parent prima dei figli.
- Migrazioni: attualmente `ALTER TABLE` idempotenti in `init_db`, con
  `PRAGMA user_version` come baseline. Le nuove migrazioni vanno numerate a partire da lì.
- Backup/restore usano l'API `sqlite3.backup()` (consistente con WAL). Il ripristino
  (`restore_backup`): valida il nome del file (no path traversal) e il contenuto
  (`verifica_file_database`: non vuoto, tabelle `utenti` e `auth_config`, `quick_check`)
  PRIMA di toccare il DB attivo; fa il backup di sicurezza e senza quello non ripristina;
  la pulizia dei vecchi backup non cancella mai il file scelto (`escludi`); legge il file
  in sola lettura (`_SolaLettura`, URI costruito con pathlib); poi esegue `init_db()` in
  un try a parte, cosi' un backup di una versione precedente si aggiorna senza riavvio.
- All'avvio il backup automatico si fa PRIMA di `init_db()` (copia "com'era prima
  dell'aggiornamento"), solo se il DB esiste gia'.
- Un solo Assisto per porta: nel blocco `__main__` di `app.py` `assisto_gia_aperto()`
  controlla 127.0.0.1:5000 prima di `app.run` ed esce con un messaggio (su Windows il
  server partirebbe lo stesso sulla porta occupata e due versioni si mescolerebbero).
- Trasloco JSON "Unisci": di un utente gia' presente si aggiornano solo i campi presenti
  nel file (`CAMPI_UTENTE_DAL_FILE`): un file 2.0 non azzera date di servizio e budget.
  L'anteprima di un file senza `tabelle` elenca cosa manca (`mancanti`) e consiglia la
  copia di `gestionale.db`.

## Front-end

- Gli asset statici si includono con `static_url('css/style.css')` (context processor
  in `app.py`): aggiunge `?v=<VERSION>` così browser e service worker scaricano i file
  nuovi ad ogni release. Il service worker (`static/sw.js`) è registrato con la stessa
  versione, mette in cache **solo** `/static/*` e non intercetta mai pagine e API
  (nessun dato dell'operatore in cache; svuotamento al logout).
- I parametri di calcolo arrivano alle pagine da `app_config` (Jinja) e
  `window.APP_CONFIG` (JS): mai tariffe o percentuali scritte a mano.
- Le conferme usano `showConfirmDialog` (app.js), mai `confirm()`/`prompt()` nativi:
  un test lo verifica. Le chiamate API passano da `apiCall` (errori con `code`/`status`).
- I token di colore (un solo blu primario, `--primary`, con `--accent` come alias)
  vivono in `static/css/style.css`; `refine.css` è il layer finale e non ridefinisce colori.
- I grafici passano da `ChartManager` (app.js): colori dai token del tema attivo
  (`getColors()`: blu `--primary` per le ore erogate, grigio `neutro` per le previste,
  `commessa.colore` per le fette per commessa), tela liberata prima di ridisegnare e
  ridisegno automatico al cambio di tema. Niente tavolozze scritte a mano.
  I colori delle commesse in grafici e Dashboard passano da `coloriCommesseDistinti(voci)`
  (app.js): chi ha un colore suo non ripetuto lo tiene, le altre prendono il primo libero
  della tavolozza di Impostazioni > Commesse (nel DB di una versione precedente erano
  tutte dello stesso indaco). I dati salvati non cambiano.
- Rendicontazione: il salvataggio automatico parte 2 s dopo l'ultimo tasto; uscendo
  prima (menu, Ctrl+K, F5, chiusura, scheda nascosta) `inviaModificheInUscita` manda le
  caselle modificate con `fetch keepalive` al batch del mese mostrato (`periodoCaricato`).
  Lo stesso pacchetto non parte due volte (firma `ultimoInvioUscita`: scheda nascosta e
  poi chiusa), ma `markChanged` azzera la firma a ogni nuova modifica: un valore uguale a
  quello già inviato torna a partire se nel frattempo il salvataggio automatico ne ha
  scritto un altro. `loadData` scarta le risposte superate (`seqCaricamento`). Il Riepilogo somma il numero
  della casella (`data-ore`), non il testo HH:MM, con gli arrotondamenti del server
  (`calcolaFatturazione`, come `config.calcola_fatturazione`). Tutto cio' che la pagina
  ricalcola dopo una modifica deve coincidere al centesimo con la pagina ricaricata:
  `arrotonda2` = `round(x, 2)` di Python (toFixed sul valore binario, pareggi esatti al
  centesimo pari; mai `Math.round(v * 100) / 100`); importi della riga da
  `calcolaFatturazione(ore60)` con le ore NON arrotondate (come
  `get_rendicontazione_completa`), le ore in 100' arrotondate solo per la colonna e le
  somme; Riepilogo con `sommaComePython` nell'ordine del server (`ordine_server`,
  `data-ordine`): `sum()` di Python e' compensata dalla 3.12 e semplice prima, e il
  server lo dice in `APP_CONFIG.somma_compensata` (`config.SOMMA_COMPENSATA`); totali
  per plesso con `+=` come `get_totali_per_scuola`. Un valore che parte col salvataggio
  prima dell'evento `change` (stesso testo riscritto) passa da `handleOreChange`, e la
  riga in memoria (`allData`) segue le caselle, cosi' il filtro Scuola non ridisegna i
  valori del caricamento.
- Finestre: la X di chiusura si scrive con la macro `modal_close(on_click)` di
  `templates/_macros.html` (`{% from '_macros.html' import modal_close %}`), mai a mano.
  Angoli: 6px etichette, 8px pulsanti e campi, 12px riquadri e finestre (`--r-*` in
  `refine.css`). Numeri nel carattere del testo (`--font-mono` = `--font-sans`, cifre
  incolonnate con `tabular-nums`); `--font-code` solo per i tasti (`kbd`).
- Fogli di stile in `static/css/`; l'ordine di caricamento conta per la cascata:
  - pagine dell'app (`base.html`): `style.css` → `components.css` → `refine.css`;
  - accesso e prima configurazione (`login.html`, `setup.html`): `style.css` → `auth.css` → `refine.css`.

  | Foglio | Dove | Cosa contiene |
  |---|---|---|
  | `style.css` | tutte le pagine | token (colori, caratteri, raggi, ombre) e tema chiaro, reset, layout (menu laterale, barra in alto), componenti di base (card, riquadri numerici, pulsanti, campi, tabelle, filtri, badge, avvisi, finestre, toast, ricerca Ctrl+K, schede), utilità |
  | `components.css` | solo app | tre parti, nell'ordine in cui erano caricate: 1) effetti su card, pulsanti, campi, menu, toast, finestre e filtri (ex `premium-effects.css`); 2) tooltip, barre di avanzamento, focus da tastiera, conferme, errori dei campi, telefono e tablet (ex `ux-enhancements.css`); 3) stampa, report rapidi, filtri avanzati, validazione, heatmap, Rendicontazione e Calendario (ex `components.css`) |
  | `auth.css` | login e setup | la scheda di accesso |
  | `refine.css` | tutte le pagine, per ultimo | due parti: 1) sfondo, titoli, bordi, badge, pagina di accesso e riduzioni per le prestazioni (ex `theme-premium.css`); 2) il design system "calmo & premium" con le correzioni per pagina |

  Dove mettere le regole nuove: prima cercare il selettore in tutti i fogli e correggere
  la regola d'origine (non aggiungere un `!important` in coda che la scavalchi); le regole
  nuove di una pagina vanno nella sezione di quella pagina in `refine.css`. Non spostare
  regole tra fogli o tra le parti di un foglio: cambierebbe la cascata. `components.css`
  non vale per login e setup, quindi non va unito a `style.css`.
- Prima di togliere o rinominare CSS: il test `tests/test_css_integrita.py` segnala le
  classi usate dalle pagine rimaste senza stile, ma confronta comunque gli stili calcolati
  e le schermate prima/dopo (il test non vede i problemi di cascata). Le classi costruite
  a runtime (`badge-${…}`, `btn-${…}`, `toast ${tipo}`, `toast-${…}`, `alert-…`,
  `da-fare-${…}`, `priorita-${…}`) non compaiono intere nel codice: le loro regole non
  vanno tolte solo perché il nome completo non si trova cercandolo.

## Sviluppo

```bash
pip install -r requirements-dev.txt
pytest                 # test
ruff check .           # lint
ruff check . --fix     # lint con fix automatici
```

La CI (`.github/workflows/ci.yml`) esegue ruff + pytest su Python 3.9 e 3.12 ad ogni push/PR, poi
la suite una seconda volta con `ASSISTO_TEST_CON_NAPOLI=1` (vedi sotto).

## Protezioni per Roma (prima della sezione Napoli)

Napoli diventa una sezione con tabelle `napoli_*` proprie: Roma deve restare
identica (numeri, pagine, report, export). Lo controllano, a ogni passo e solo con
dati inventati:

- **Fotografia golden** (`tests/test_roma_golden.py`). `strumenti/fotografa_roma.py`
  fotografa tutte le rotte GET di Roma: JSON (valori, con date-ora del momento,
  versione e nomi casuali dei file mascherati), Excel (celle, formule, celle unite),
  Word (paragrafi e tabelle), pagine (titolo, id, intestazioni e impronta del
  contenuto di `<main>`, quindi senza il menu laterale). L'archivio inventato
  (`tests/roma_sintetico.py`, due anni scolastici scritti solo con le API) deve dare
  `tests/golden/roma_v1_20_1.json`, creata sul codice della v1.20.1. Le date "di
  oggi" passano da `orologio_fermo` (sostituisce `datetime`/`date` nei moduli del
  programma): niente `date('now')` di SQLite nelle uscite nuove di Roma, che non si
  potrebbe fermare. Ore in quarti d'ora: la fotografia e' la stessa su Python 3.9 e
  3.12 (somme con `sum()` diverse). Si rigenera solo per un cambiamento di Roma
  voluto, sul codice di riferimento:
  `python strumenti/fotografa_roma.py --sintetico --codice CARTELLA_VERSIONE --uscita tests/golden/roma_v1_20_1.json`.
- **Invarianza** (`tests/test_roma_invariata.py`): fotografia, poi i dati di Napoli
  (`tests/seme_napoli.py`, `carica_seme_napoli`: riempie tutte le tabelle `napoli_*`,
  per ora scrivendole direttamente; ogni passo di Napoli ci aggiunge i suoi dati
  tramite le sue API), poi di nuovo la fotografia, che deve essere uguale;
  tabelle di Roma (schema e righe; del registro attivita' le voci non `napoli%`)
  intatte. **Doppio giro**: con `ASSISTO_TEST_CON_NAPOLI=1 pytest` il seme si carica
  anche nel database della sessione e nell'archivio della fotografia, e tutta la
  suite deve restare verde.
- **Inventario delle rotte** (`test_inventario_rotte`): ogni rotta sta in
  `ROTTE_ROMA` (le GET in `FOTOGRAFIE`, con gli indirizzi da fotografare),
  `ROTTE_NAPOLI` (solo `/napoli` e `/api/napoli`) o `ESCLUSE` con il motivo
  (`/static`, `/api/audit*`, `/api/backup*`), in `strumenti/fotografa_roma.py`.
  Una rotta nuova non classificata fa fallire il test.
- **Separazione statica** (`tests/test_separazione_napoli.py`): nei moduli di Napoli
  (`napoli_*.py`, `routes_napoli.py`, `import_napoli.py`, `export_napoli.py`,
  `config_napoli.py`) lo SQL nomina solo tabelle `napoli_*`, niente tariffe e calcoli
  di Roma, di `database.py` e `routes_export.py` solo le funzioni comuni elencate
  (`DATABASE_AMMESSI`, `EXPORT_AMMESSI`). Nei file di Roma la parola "napoli"
  compare solo nei punti dichiarati in `OCCORRENZE_AMMESSE`, con il numero esatto.
- **Confronto sul database vero** (`strumenti/confronta_roma.py`), prima di un
  rilascio, sul PC dell'utente e con il suo consenso:
  `python strumenti/confronta_roma.py --db gestionale.db --vecchia CARTELLA_VERSIONE_VECCHIA`.
  Lavora su due copie temporanee (il file indicato non cambia), avvia ogni versione
  sulla sua copia con lo stesso orologio fermo e stampa solo "N rotte identiche / M
  diverse" con i nomi delle rotte, mai dati. Esce con 0 (identiche), 1 (differenze)
  o 2 (errore). Con molti mesi e utenti puo' durare alcuni minuti.

## Sezione Napoli

Il servizio di Napoli sta in tabelle `napoli_*` proprie, nello stesso database:
nessuna tabella di Roma cambia schema e nessuna chiave esterna punta a Roma.

- **Schema**: `napoli_schema.py` contiene solo il DDL (non importa `database`).
  `database.py` lo registra nel runner delle migrazioni: `SCHEMA_VERSION = 3`,
  `MIGRAZIONI = {2: napoli_schema.crea_v2, 3: napoli_schema.crea_v3}`; e' l'unica
  modifica dello schema dal lato di Roma. `crea_v2` crea le 22 tabelle della fase 1
  (lotti, scuole, alunni, operatori, PEI, coppie operatore-alunno, contratti
  applicativi, tariffe e regole con data, calendario, orari, fogli firma, import,
  presenze e fasce, ore del coordinatore, mesi chiusi per lotto, prospetti fattura,
  annullamenti) con i valori iniziali (figure professionali, grafie delle
  qualifiche). `crea_v3` corregge la fase 1 prima del rilascio: le ore del
  coordinatore sono un totale mensile per lotto, grado e contratto applicativo
  (una riga per mese, operatore facoltativo e mai in fattura, come la riga
  "Coordinatore" della fattura reale) e il prospetto fattura congela anche oggetto,
  nota, destinatario, testo della ritenuta, scadenza e regole usate. La banca ore
  della fase 2 (PROGETTO §4.3, la' chiamata v3) sara' quindi la migrazione 4
  (`crea_v4`).
- **Migrazioni gia' pubblicate non si cambiano**: un database puo' essere gia' a
  quella versione e rieseguirla non lo correggerebbe. `test_la_migrazione_2_pubblicata_non_cambia`
  fissa l'impronta di `crea_v2`; ogni correzione e' una migrazione nuova, sicura
  anche su un database gia' aggiornato e con dati: `crea_v3` ricostruisce
  `napoli_coordinamento` (nuova tabella, copia, `DROP`, `RENAME`, nella stessa
  transazione; le righe della v2, una per operatore, diventano il totale del mese)
  solo se ha ancora la forma della v2, e aggiunge le colonne di `napoli_fatture`
  solo se mancano (`PRAGMA table_info`).
- **Aggiornamento**: all'avvio, dopo il backup "pre-aggiornamento", un database con
  `user_version` 1 (v1.20.1 e precedenti) o 2 passa a 3. Le migrazioni mancanti
  girano in un'unica transazione (se si interrompe non resta nulla a meta') e si
  possono rieseguire senza danni (`IF NOT EXISTS`, `INSERT OR IGNORE`, controlli
  sulla forma delle tabelle). Il ripristino di un backup della v1.20.1 aggiorna
  subito lo schema (tabelle di Napoli vuote): ripristinare un backup fatto prima di
  Napoli cancella i dati di Napoli, come per ogni ripristino. Una versione vecchia
  che apre un database piu' nuovo non lo tocca e ignora le tabelle `napoli_*`.
- **Date e orari**: i CHECK dello schema controllano solo la forma ('AAAA-MM-GG',
  'HH:MM': accettano anche 2025-19-39 e 29:59); il controllo vero e' in Python
  (`napoli_calcoli.valida_data`, `valida_orario`, `valida_fascia`,
  `valida_periodo`, `valida_mese`), da usare in ogni API di Napoli prima di
  scrivere.
- **Unita'**: ore delle presenze in minuti interi, tariffe e importi in centesimi,
  ore del coordinatore in centesimi di ora; tariffe sempre IVA esclusa. La
  municipalita' e' quella della scuola: lo stesso codice meccanografico in due
  municipalita' sono due plessi.
- **Calcoli** (`napoli_calcoli.py`, funzioni pure: ricevono righe gia' lette come
  dict e non importano `database`, Flask o `config`):
  - letture: `leggi_ore_griglia` (ore decimali; "1,30", "1,3" e gli altri decimali che
    non sono quarti d'ora vanno confermati: si rilegge con `conferma`; se le cifre non
    possono essere minuti, come "1,7", vale il decimale con un avviso), `leggi_ore_foglio`
    (totale scritto sul foglio firma: ",15/,30/,45" ore e minuti, ",25/,5/,75"
    decimali), `leggi_cella_master`; sigle F, M, F perm (e varianti), A;
  - `esito_giorno` / `minuti_riconosciuti`: tabella del PROGETTO §5.2 (precedenza
    calendario > evento > operatore > alunno; meta' del programmato per l'alunno
    assente col contratto attuale, niente meta' se l'assenza e' recuperata; mezzo
    minuto per eccesso); `stato='programmato'` vale 0, mai "come programmato";
  - `settimane_mese` (lun-sab tagliate al mese), `verifica_settimane` (oltre il PEI
    giallo, oltre il tetto PEI x 1,2 rosso; settimane numerate come le colonne
    VERIFICA), `tetto_settimanale`;
  - `regola` / `regole_alla_data`: riga del lotto, poi di tutti i lotti, poi il
    predefinito di `config_napoli.REGOLE_PREDEFINITE` (che ha le sue date: fuori da
    queste vale lo stesso ma `regola_dettaglio` lo segnala);
  - fattura: `periodo_fattura` (mese tagliato al contratto applicativo),
    `tariffa_alla_data` (livello dell'operatore, poi senza livello), `righe_fattura`
    (per figura e tariffa: ore = minuti / 60 al centesimo; il coordinatore dalle sue
    ore; una riga per tratto di tariffa se cambia nel periodo; grado vuoto o "misto" =
    da decidere, blocca le fatture di tutti e due i gradi), `totali_fattura` (importo di riga
    al centesimo, ritenuta 0,50% sulla somma, IVA 5% sull'imponibile, split payment:
    si paga l'imponibile), `prospetto_fattura` (con testi, scadenza e bloccanti),
    `ore_fuori_contratto` (presenze fuori da ogni contratto applicativo: il prospetto
    guarda un contratto alla volta, questo controllo il mese intero).
    Tutto in `Decimal` con ROUND_HALF_UP; le tariffe sono sempre quelle del lotto
    (`napoli_tariffe`): `config_napoli.TARIFFE_PROPOSTE` servono solo a precompilare.
- **Test**: `tests/test_napoli_schema.py` (migrazione su un database v1.20.1 con
  l'archivio Roma inventato confrontato con il gemello riaperto dalla versione
  vecchia; da un database gia' alla v2 con dati alla v3; rieseguibilita',
  interruzione, ripristino, impronta della migrazione 2, vincoli);
  `tests/test_napoli_calcoli.py` (con soli dati inventati: le quantita' e le tariffe
  della fattura reale di giugno ricalcolate al centesimo, i due fogli firma ricostruiti
  con orari equivalenti, letture ambigue, regole, tariffe, bloccanti).

## Refactoring pianificati (da fare come interventi dedicati e revisionati)

Non vanno affrontati "di corsa" perché toccano molte route con copertura di test
ancora parziale; ognuno merita una PR isolata con test aggiuntivi prima del merge:

1. **Split di `app.py` in blueprint per dominio** — *in corso*. Estratti finora:
   backup, migrazione/audit, reportistica/override (+ `validators.py` condiviso).
   Da estrarre: statistiche (route sparse), documenti/note/assenze, dipendenti/turni,
   auth. Regola seguita: spostare solo gruppi le cui route NON sono referenziate da
   `url_for` (endpoint API chiamati via fetch), così i nomi endpoint possono cambiare
   senza rompere i template; verificare ogni estrazione con lo smoke test di tutte le
   route GET + la suite.
2. **Layer di servizio**: estrarre lo SQL grezzo ancora presente in alcune route
   "grasse" (es. `api_migrazione_importa`) in funzioni di dominio in `database.py`.
3. **Type hints progressivi** sulle funzioni più riusate + `mypy` non bloccante in CI.
4. **Consolidamento tabelle override legacy** (`get_report_locale_commessa`): unificare
   la doppia lettura vecchia/nuova con una migrazione dati versionata.

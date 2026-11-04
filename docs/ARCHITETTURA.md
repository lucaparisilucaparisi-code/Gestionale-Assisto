# Architettura & guida sviluppatore — Gestionale OEPAC

Nota tecnica per chi sviluppa. Per l'uso e l'installazione vedi il `README.md`.

## Struttura dei moduli

| File | Responsabilità |
|------|----------------|
| `app.py` | Applicazione Flask: route pagine e molte API, autenticazione (sessione + WebAuthn), import. Registra i blueprint sotto. |
| `database.py` | Tutto l'accesso ai dati SQLite: schema/migrazioni, CRUD, calcoli di dominio. |
| `napoli_schema.py` | Solo lo schema della sezione Napoli (tabelle `napoli_*`): le migrazioni 2, 3 e 4 di `database.py` (vedi "Sezione Napoli"). |
| `napoli_db.py` | Accesso ai dati di Napoli (solo tabelle `napoli_*`): Impostazioni, controlli che guardano il database (nomi doppi, date sovrapposte), Ctrl+Z di Napoli (`napoli_annullamenti`). |
| `routes_napoli.py` | Blueprint della sezione Napoli: pagine `/napoli` e API `/api/napoli/...`. |
| `import_napoli.py` | Import del foglio presenze mensile di Napoli (master del coordinatore): lettura del file, anteprima senza scritture, conferma, reimport, annulla import, solo confronto (vedi "Sezione Napoli"). |
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
  Word (paragrafi e tabelle), pagine (titolo, id, intestazioni, impronta del
  contenuto di `<main>`, impronta della cornice, cioe' `<head>`, menu laterale,
  finestre comuni e script della pagina, e i file caricati, stili, script e icone,
  ciascuno con l'impronta del contenuto a fine riga Linux). Dalla cornice si toglie
  il blocco di Napoli: gli elementi con `data-sezione="napoli"`, con tutto il loro
  contenuto, sono l'unica parte delle pagine di Roma che Napoli puo' aggiungere
  (PROGETTO §4.5): la voce "Napoli" del menu laterale e della ricerca rapida (Alt+8)
  ha questo attributo su ogni elemento; `test_cornice_senza_il_blocco_di_napoli`
  controlla che con la voce la cornice resti quella della v1.20.1 e che senza
  l'attributo cambierebbe. Dei file `STATICI_MODIFICABILI` (`app.js`, che cambia per
  Alt+8 e l'annulla della pagina di Napoli) si annota solo che la pagina li carica.
  La fotografia non deve contenere errori 4xx/5xx (`test_la_fotografia_non_contiene_errori`).
  L'archivio inventato
  (`tests/roma_sintetico.py`, due anni scolastici scritti solo con le API) deve dare
  `tests/golden/roma_v1_20_1.json`, creata sul codice della v1.20.1. Le date "di
  oggi" passano da `orologio_fermo` (sostituisce `datetime`/`date` nei moduli del
  programma): niente `date('now')` di SQLite nelle uscite nuove di Roma, che non si
  potrebbe fermare. Ore in quarti d'ora: la fotografia e' la stessa su Python 3.9 e
  3.12 (somme con `sum()` diverse). Si rigenera solo per un cambiamento di Roma
  voluto, o per un cambiamento dello strumento (`VERSIONE_FOTOGRAFIA`), sempre sul
  codice di riferimento (la v1.20.1 e' il commit a0249a2), e la parte che c'era
  gia' deve restare uguale:
  `python strumenti/fotografa_roma.py --sintetico --codice CARTELLA_VERSIONE --uscita tests/golden/roma_v1_20_1.json`.
- **Invarianza** (`tests/test_roma_invariata.py`): fotografia, poi i dati di Napoli
  (`tests/seme_napoli.py`, `carica_seme_napoli`: riempie tutte le tabelle `napoli_*`;
  con un client i dati che hanno gia' le loro API passano da li', dal passo 1.3
  cooperativa, destinatario, lotto con le tariffe dalla procedura guidata,
  contratti, regole e qualifiche, il resto si scrive direttamente; dai passi 1.4-1.5,
  dopo le righe scritte direttamente, l'import con anteprima e conferma del master di
  marzo 2026 inventato con alunni e un operatore omonimi di quelli di Roma; ogni passo di
  Napoli sposta i suoi dati sulle sue API), poi di nuovo la fotografia, che deve
  essere uguale; tabelle di Roma (schema e righe; del registro attivita' le voci non
  `napoli%`, nel loro ordine e senza il loro `id`, che le voci di Napoli scritte prima
  fanno crescere: `seme_napoli.MASCHERATE_SEMPRE`) intatte. **Scritture su due gemelli** (`test_scritture_di_roma_uguali_con_e_senza_napoli`):
  lo stesso archivio Roma con e senza il seme Napoli; chiusura e riapertura del
  mese, compila con media, copia del mese precedente, import della prefattura,
  dell'anagrafica utenti e dei dipendenti (anche omonimi di operatori di Napoli),
  wizard del nuovo anno e i tre reset, con lo stesso orologio, devono dare le
  stesse risposte e le stesse tabelle di Roma nei due gemelli e lasciare intatte
  quelle di Napoli: il reset di Roma non cancella Napoli. Le colonne che scrive
  l'orologio di SQLite (`import_cronologia.data`) si confrontano solo come
  presenti. **Doppio giro**: con `ASSISTO_TEST_CON_NAPOLI=1 pytest` il seme si carica
  anche nel database della sessione e nell'archivio della fotografia, e tutta la
  suite deve restare verde.
- **Inventario delle rotte** (`test_inventario_rotte`): ogni rotta sta in
  `ROTTE_ROMA` (le GET in `FOTOGRAFIE`, con gli indirizzi da fotografare),
  `ROTTE_NAPOLI` (solo `/napoli` e `/api/napoli`) o `ESCLUSE` con il motivo
  (`/static`, `/api/audit*`, `/api/backup*`), in `strumenti/fotografa_roma.py`.
  Una rotta nuova non classificata fa fallire il test.
- **Separazione statica** (`tests/test_separazione_napoli.py`): nei moduli di Napoli
  (`napoli_*.py`, `routes_napoli.py`, `import_napoli.py`, `export_napoli.py`,
  `config_napoli.py`) lo SQL nomina solo tabelle `napoli_*` (anche quando e'
  costruito con f-string, `+`, `%`, `.format` o `join`: un nome di tabella calcolato
  che non comincia per `napoli_` e' un errore; `sqlite_sequence` solo con
  `name = 'napoli_...'`), niente tariffe e calcoli di Roma, di `database.py`,
  `routes_export.py` e `validators.py` solo le funzioni comuni elencate
  (`DATABASE_AMMESSI`, `EXPORT_AMMESSI`, `VALIDATORS_AMMESSI`), nessun altro modulo
  di Roma (`app`, `routes_*`, `import_*`, `strumenti`...), niente `import *`, import
  per nome o `getattr` che non si possono verificare. Nei file di Roma la parola "napoli"
  compare solo nei punti dichiarati in `OCCORRENZE_AMMESSE`, con il numero esatto.
- **Confronto sul database vero** (`strumenti/confronta_roma.py`), prima di un
  rilascio, sul PC dell'utente e con il suo consenso:
  `python strumenti/confronta_roma.py --db gestionale.db --vecchia CARTELLA_VERSIONE_VECCHIA`.
  Fa una copia temporanea (il file indicato non cambia: anche
  `fotografa_roma.py --db` lavora sempre su una sua copia), avvia ogni versione su
  una copia di quella con lo stesso orologio fermo e stampa solo "N rotte identiche
  / M diverse" con i nomi delle rotte, mai dati. Esce con 0 (identiche), 1 (differenze)
  o 2 (errore). Con molti mesi e utenti puo' durare alcuni minuti.

## Sezione Napoli

Il servizio di Napoli sta in tabelle `napoli_*` proprie, nello stesso database:
nessuna tabella di Roma cambia schema e nessuna chiave esterna punta a Roma.

- **Schema**: `napoli_schema.py` contiene solo il DDL (non importa `database`).
  `database.py` lo registra nel runner delle migrazioni: `SCHEMA_VERSION = 4`,
  `MIGRAZIONI = {2: napoli_schema.crea_v2, 3: napoli_schema.crea_v3, 4: napoli_schema.crea_v4}`;
  e' l'unica modifica dello schema dal lato di Roma. `crea_v2` crea le 22 tabelle della fase 1
  (lotti, scuole, alunni, operatori, PEI, coppie operatore-alunno, contratti
  applicativi, tariffe e regole con data, calendario, orari, fogli firma, import,
  presenze e fasce, ore del coordinatore, mesi chiusi per lotto, prospetti fattura,
  annullamenti) con i valori iniziali (figure professionali, grafie delle
  qualifiche). `crea_v3` corregge la fase 1 prima del rilascio: le ore del
  coordinatore sono un totale mensile per lotto, grado e contratto applicativo
  (una riga per mese, operatore facoltativo e mai in fattura, come la riga
  "Coordinatore" della fattura reale) e il prospetto fattura congela anche oggetto,
  nota, destinatario, testo della ritenuta, scadenza e regole usate. `crea_v4`
  (passo 1.3, Impostazioni) aggiunge a `napoli_contratti` il servizio della determina
  (`dd_servizio`: "D.D. 1093 N.31 DEL ..." nella nota della fattura; vuoto = il
  riferimento amministrativo del lotto). La banca ore della fase 2 (PROGETTO §4.3,
  la' chiamata v3) sara' quindi la migrazione 5 (`crea_v5`).
- **Migrazioni gia' pubblicate non si cambiano**: un database puo' essere gia' a
  quella versione e rieseguirla non lo correggerebbe. `test_la_migrazione_2_pubblicata_non_cambia`
  e `test_la_migrazione_3_pubblicata_non_cambia` fissano le impronte di `crea_v2` e
  `crea_v3`; ogni correzione e' una migrazione nuova, sicura anche su un database gia'
  aggiornato e con dati (`crea_v4` aggiunge la colonna solo se manca): `crea_v3` ricostruisce
  `napoli_coordinamento` (nuova tabella, copia, `DROP`, `RENAME`, nella stessa
  transazione; le righe della v2, una per operatore, diventano il totale del mese)
  solo se ha ancora la forma della v2, e aggiunge le colonne di `napoli_fatture`
  solo se mancano (`PRAGMA table_info`).
- **Aggiornamento**: all'avvio, dopo il backup "pre-aggiornamento", un database con
  `user_version` 1 (v1.20.1 e precedenti), 2 o 3 passa a 4. Le migrazioni mancanti
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
  - dati in ingresso: `valida_data` ('AAAA-MM-GG' o 'GG/MM/AAAA', rifiuta le date che
    non esistono), `valida_orario` (00:00-23:59), `valida_fascia`, `valida_fasce` (niente
    sovrapposizioni), `valida_periodo`, `valida_mese`: restituiscono il valore nella forma
    del database e, se sbagliato, un messaggio semplice da mostrare (ValueError);
  - letture: `leggi_ore_griglia` (ore decimali; "1,30", "1,3" e gli altri decimali che
    non sono quarti d'ora vanno confermati: si rilegge con `conferma`; se le cifre non
    possono essere minuti, come "1,7", vale il decimale con un avviso), `leggi_ore_foglio`
    (totale scritto sul foglio firma: ",15/,30/,45" ore e minuti, ",25/,5/,75"
    decimali), `leggi_cella_master` (anche orari e durate [h]:mm di Excel, con avviso);
    sigle F, M, F perm (e varianti), A;
  - `esito_giorno` / `minuti_riconosciuti`: tabella del PROGETTO §5.2 (precedenza
    calendario > evento/attivita' esterna > operatore > alunno, con la causale che
    vince riportata; meta' del programmato per l'alunno assente col contratto attuale,
    niente meta' se l'assenza e' recuperata; mezzo minuto per eccesso);
    `stato='programmato'` vale 0, mai "come programmato";
  - `settimane_mese` (lun-sab tagliate al mese), `verifica_settimane` (oltre il PEI
    giallo, oltre il tetto PEI x 1,2 rosso; settimane numerate e sommate come le colonne
    VERIFICA del master, cioe' solo i giorni di servizio: le ore di una domenica sono una
    voce a parte `ore_in_giorno_non_di_servizio`), `tetto_settimanale`;
  - `regola` / `regole_alla_data`: riga del lotto, poi di tutti i lotti, poi il
    predefinito di `config_napoli.REGOLE_PREDEFINITE` (che ha le sue date: fuori da
    queste vale lo stesso ma `regola_dettaglio` lo segnala);
  - fattura: `periodo_fattura` (mese tagliato al contratto applicativo),
    `tariffa_alla_data` (livello dell'operatore, poi senza livello), `righe_fattura`
    (solo giorni con stato 'registrato', ogni altro stato blocca; per figura e tariffa:
    ore = minuti / 60 al centesimo; il coordinatore solo dal totale mensile, al
    centesimo, e le sue eventuali presenze fuori con l'avviso
    `ore_coordinatore_nelle_presenze`; una riga per tratto di tariffa se cambia nel
    periodo, con il sotto-periodo dei giorni in cui vale davvero; grado vuoto o "misto"
    = da decidere, blocca le fatture di tutti e due i gradi), `totali_fattura` (importo
    di riga al centesimo, ritenuta 0,50% sulla somma, IVA 5% sull'imponibile, split
    payment: si paga l'imponibile), `prospetto_fattura` (con testi, destinatario,
    scadenza, regole usate, bloccanti e avvisi) e `testi_da_congelare` (le colonne dei
    testi di `napoli_fatture`), `ore_fuori_contratto` e `presenze_in_piu_contratti`
    (presenze fuori da ogni contratto applicativo o in due contratti: il prospetto
    guarda un contratto alla volta, questi controlli il mese intero);
    `tariffe_sovrapposte` e `contratti_sovrapposti` (per le Impostazioni del passo
    1.3, che le rifiutano: la fattura non saprebbe quale tariffa usare e le stesse ore
    finirebbero in due fatture).
    Tutto in `Decimal` con ROUND_HALF_UP; le tariffe sono sempre quelle del lotto
    (`napoli_tariffe`): `config_napoli.TARIFFE_PROPOSTE` servono solo a precompilare.
- **Pagine e API** (`routes_napoli.py`, blueprint registrato in `app.py`; dati da
  `napoli_db.py`). Il menu ha la voce "Napoli" (Alt+8) che porta a `/napoli`, nella
  sezione "Principale" sotto la Dashboard e senza una sezione sua (PROGETTO §4.5
  prevedeva una sezione "Napoli" con una voce: con l'intestazione in piu' a 1366x768 il
  menu scorreva e "Impostazioni" restava tagliata a meta' su tutte le pagine di Roma);
  le schede
  comuni (`templates/_napoli_tabs.html`, con il lotto scelto ricordato nel browser) per
  ora sono **Mese** (`/napoli`: senza lotti la procedura "Crea il primo lotto", poi cosa
  manca per le fatture, `GET /api/napoli/lotti/<id>/controlli`), **Importa**
  (`/napoli/import`, il foglio presenze del mese) e **Impostazioni**
  (`/napoli/impostazioni`, una parte alla volta, `#lotto`, `#contratti`...): dati della
  cooperativa e destinatario (`napoli_impostazioni`), lotti, contratti applicativi per
  lotto e grado, tariffe e regole con data, qualifiche. Pagine e script
  (`static/js/napoli.js`, `static/css/napoli.css`) solo di Napoli: le pagine di Roma non
  li caricano. Le API controllano tutto lato server e rispondono con un messaggio
  semplice e il campo sbagliato (`{error, code, campo}`: 400 dati non validi, 404, 409):
  - procedura guidata (`GET /api/napoli/lotti/proposta`, `POST /api/napoli/lotti/procedura`):
    nome "NAPOLI LOTTO n" con il primo numero libero, modelli dell'oggetto e della nota
    della fattura, codice univoco e riferimento amministrativo del capitolato, tariffe
    del contratto attuale dal 01/09/2025 al 31/01/2027 (`config_napoli.LOTTO_PROPOSTO`,
    `tariffe_proposte`; LIS vuota), tutto in un'azione sola;
  - lotti: nome e numero (1-5) unici, CIG di 10 caratteri, CUP di 15, codice univoco di
    6, segnaposto dei modelli fra quelli ammessi (`napoli_calcoli.segnaposto_sconosciuti`);
    un lotto si elimina solo senza dati (con i suoi contratti, tariffe e regole);
  - contratti applicativi: date obbligatorie; due contratti dello stesso lotto che
    coprono gli stessi giorni per lo stesso grado (senza grado = tutti e due) sono
    rifiutati (409 `CONTRATTI_SOVRAPPOSTI`, `napoli_calcoli.contratti_sovrapposti`); un
    contratto con ore del coordinatore o fatture non si elimina;
  - tariffe (IVA esclusa, `valida_euro`) e regole con data: date sovrapposte della
    stessa figura e livello (della stessa regola e dello stesso ambito, lotto o tutti i
    lotti) rifiutate (409 `TARIFFE_SOVRAPPOSTE` / `REGOLE_SOVRAPPOSTE`); se quelle di
    prima cominciano prima, la risposta propone come fare posto alla nuova senza
    lasciare giorni scoperti (`chiudibili`): quella di prima finisce il giorno prima
    della nuova (`nuova_fine`) e, se andava oltre la fine della nuova, riprende il giorno
    dopo (`riprende_da`, `riprende_a`: la riga si divide in due, con la stessa fonte);
    con `chiudi_precedenti` la proposta si applica nella stessa azione (un solo Ctrl+Z)
    e il messaggio dice le date nuove della precedente. Senza la divisione, una tariffa
    nuova per tre mesi avrebbe lasciato senza tariffa i mesi dopo, e una regola sarebbe
    tornata in silenzio al valore predefinito. Le regole hanno spiegazione, gruppo,
    limiti e (per gli elenchi di codici, come gli usi A, B, D) le voci ammesse in
    `config_napoli.ETICHETTE_REGOLE`;
  - valori stretti: un si'/no accetta solo si'/no, vero/falso, 1/0 (ogni altro valore e'
    400, non un "no"); i numeri si scrivono per esteso (23,44 o 23.44): 1e2, Infinity e
    simili sono rifiutati (`valida_euro`, `NUMERO_SCRITTO`); un elenco vuoto o con un
    codice che non esiste e' rifiutato con il suo messaggio;
  - cooperativa: partita IVA e codice fiscale con la cifra di controllo, IBAN con le
    cifre di controllo e la lunghezza del paese (`valida_iban`), salvato senza spazi e
    mostrato solo mascherato (`maschera_iban`: alla pagina non torna mai intero); un
    campo che non arriva resta com'e'. Destinatario: proposto dalla fattura reale
    (`config_napoli.DESTINATARIO_PROPOSTO`), vale per tutti i lotti
    (`napoli_calcoli.destinatario_fattura`: quello del lotto, se c'e', vince);
  - **Ctrl+Z di Napoli** (`/api/napoli/annulla/ultima`, `POST /api/napoli/annulla`):
    `napoli_annullamenti`, separato da quello di Roma; ogni azione salva le righe
    toccate com'erano (`{"versione": 1, "righe": [{tabella, chiave, prima}]}`), si
    annulla solo l'ultima, entro 24 ore, con l'id mostrato nella conferma. Le azioni
    scadute restano solo con la descrizione (senza valori): le righe di prima, IBAN
    compreso, si tolgono (`dati = '{}'`) a ogni nuova azione, a Ctrl+Z e all'apertura
    delle pagine di Napoli (`napoli_db.pulisci_annullamenti`). In `app.js`
    Ctrl+Z chiama `window.annullaPagina` se la pagina lo definisce (solo le pagine di
    Napoli), altrimenti l'annulla di Roma;
  - registro attivita': voci `napoli_*` senza valori (mai IBAN o codici fiscali);
  - **import del foglio presenze** (scheda **Importa**, `/napoli/import`; passi 1.4-1.5,
    `import_napoli.py`): vedi il punto seguente.
- **Import del foglio presenze mensile** (master del coordinatore, PROGETTO §7.1):
  - lettura (`import_napoli.leggi_master`, solo il file): colonne riconosciute
    dall'intestazione, giorni dalla data, scuola per posizione (nel file del Comune
    l'intestazione e' "2"), foglio "master" o il primo con le colonne giuste, mese e anno
    dalle date. **Le ore si ricalcolano dalle celle dei giorni** con
    `napoli_calcoli.leggi_cella_master`: la VERIFICA e il foglio "riepilogo" servono solo da
    controllo (nel file vero la VERIFICA perde ore). Un numero con la virgola che non e'
    un quarto d'ora e le cui cifre possono essere minuti ("1,30") e' **da confermare**
    nell'anteprima (`napoli_calcoli.letture_possibili`): nessuna lettura e' gia' scelta,
    finche' non si sceglie conta come decimale (la regola del master, PROGETTO §5.1) e
    non si importa; reimportando lo stesso file vale la scelta dell'import di prima
    (stessa cella, stesso testo). Le note "Alunno assente: ..." e le celle colorate sono
    solo promemoria (proposte nella fase 2). Ogni interpretazione e' un avviso con riga,
    colonna e un dettaglio che non e' mai un dato personale (testo della cella accorciato,
    un codice fiscale scritto per errore in una cella arriva mascherato:
    `nascondi_codici_fiscali`, applicato anche a tutti i testi della risposta).
    Messaggi semplici per file vuoto, file temporaneo di Excel (`~$...`), formato .xls o
    file con password, file che non e' Excel, foglio sbagliato (con i fogli trovati); se il
    file e' aperto in Excel su Windows il browser non lo legge e la pagina lo dice
    (il file si legge appena scelto). Le righe vuote dopo 200 di fila non si leggono;
  - anteprima (`POST /api/napoli/import/anteprima`, multipart: file, lotto, modo,
    scelte): **non scrive nulla**. Abbina solo dentro Napoli:
    - scuole per codice meccanografico e **municipalita' della scuola** (REGOLE 12):
      municipalita' mancante presa dalla stessa scuola se ne ha una sola (nel file o in
      Assisto); se la scuola in Assisto c'e' una volta sola e senza municipalita', quella
      del file si aggiunge allo stesso plesso (avviso, l'annullamento la toglie). La stessa
      scuola con municipalita' diverse, nel file o fra il file e Assisto, va confermata con
      "Ho controllato": una municipalita' nuova diventa un altro plesso se serve a una
      coppia nuova; le righe di coppie gia' in Assisto restano nel plesso della coppia.
      Una scuola nuova si crea solo se una coppia nuova la usa (niente scuole vuote; una
      coppia gia' in Assisto con un'altra scuola resta nella sua, con un avviso);
    - alunni per codice fiscale (mancante o di forma sbagliata = bloccante) o, se non
      c'e', per la radice (i primi 15 caratteri: un codice con l'ultimo carattere sbagliato
      e' la stessa persona); se il file porta il codice giusto e Assisto quello sbagliato,
      si corregge in Assisto. Omonimo con un altro codice: alunno nuovo con un avviso;
    - operatori per codice fiscale, per radice, poi per nome (PROGETTO §7.1, da
      confermare; fra omonimi vale quello con coppie nella stessa scuola): per nome si
      cerca se il codice del file non e' giusto, o se e' giusto ma in Assisto la persona ha
      un codice sbagliato o nessun codice (il mese dopo il codice arriva corretto: niente
      doppioni, e il codice si corregge in Assisto se differisce di al massimo due
      caratteri). Un omonimo con un altro codice giusto e' un operatore nuovo, con un
      avviso; un operatore con figure diverse (fra le righe o rispetto ad Assisto) ha
      l'avviso `operatore_con_piu_figure`;
    - qualifiche con `napoli_alias_qualifiche`: una nuova si sceglie sempre nella pagina
      (la figura di `figura_proposta` e' indicata nella tendina, non gia' scelta) e si
      salva come grafia 'utente';
    - coppie per alunno, operatore, figura e ruolo, valide nel mese o finite nel mese
      prima: un sostituto che continua resta la stessa coppia (finisce piu' tardi), un
      titolare chiuso che ha di nuovo ore si riapre (avviso). SI = sostituto, collegato al
      titolare; un sostituto con la data di inizio nel mese propone il **subentro**: il
      titolare finisce il giorno prima.

    Grado delle scuole nuove proposto dal codice (`napoli_calcoli.grado_da_codice_meccanografico`,
    PROGETTO §4.2) e scelto nella pagina. Le coppie del mese prima che nel file non ci
    sono si possono chiudere (proposta non spuntata); contano i giorni che restano dopo
    l'import, quindi nel reimport anche quella di una riga tolta dal file. Una coppia che
    comincia nel mese e nel file non c'e' resta senza ore e si mostra (se viene da una
    riga sbagliata dell'import di prima: annullarlo e importare di nuovo). Bloccanti (`SPIEGAZIONI`, livello
    'bloccante'): mese chiuso, righe di un altro lotto, qualifica senza figura, codice
    fiscale dell'alunno, scritte che non sono ore, piu' di 12 ore, stessa coppia su due
    righe. Risponde con conteggi, ore per figura e per grado, cosa cambia, avvisi
    raggruppati e spiegati, codici fiscali solo mascherati (`maschera_codice_fiscale`),
    `sha256` del file e `versione_dati` (impronta dei dati di Napoli guardati);
  - conferma (`POST /api/napoli/import/conferma`): stesso file (sha256, 409
    `FILE_CAMBIATO`), stessi dati (409 `ANTEPRIMA_SUPERATA`), mese aperto (409
    `MESE_CHIUSO_LOTTO`), nessun bloccante (400 `IMPORT_BLOCCATO`), conferme date (400
    `DA_CONFERMARE`, anche per le ore da confermare non scelte); se il file non cambia
    niente non scrive nulla. Poi
    `database.create_backup()` (senza copia niente import, 503) e **un'unica transazione**
    (`BEGIN IMMEDIATE`, dati riletti e confrontati di nuovo): anagrafiche nuove, coppie,
    PEI del mese per alunno e figura (dalle righe NO), fogli del mese con la nota della
    riga, e ogni cella con ore o sigla diventa un giorno registrato con calcolo
    'manuale', origine 'import_excel', testo originale e il numero dell'import (sigle:
    causale dell'operatore, 0 ore);
  - reimport dello stesso mese: si sostituiscono solo le ore importate (cambiate o tolte
    se nel file non ci sono piu'); i giorni registrati a mano diversi dal file si mostrano
    e restano, salvo la scelta "Sostituisci anche queste ore"; i giorni solo programmati
    si completano;
  - annulla import (`POST /api/napoli/import/<id>/annulla`, e Ctrl+Z subito dopo:
    `napoli_annullamenti` ha solo `{"versione": 1, "import_id": n}` e `napoli_db.annulla`
    passa a `import_napoli.annulla_import`): solo l'ultimo import del lotto, mese aperto,
    nessun giorno dell'import cambiato a mano dopo; copia di sicurezza, poi in una
    transazione si tolgono le righe create e tornano le righe cambiate o tolte
    (`napoli_import.sostituite_json`: id e valori di prima; delle anagrafiche si cambiano
    solo campi vuoti, come le ore di contratto e la municipalita' della scuola, e i codici
    fiscali sbagliati corretti dal file, dei quali si salva solo la differenza, al piu'
    due caratteri e la loro posizione: mai un codice fiscale);
  - solo confronto (modo 'confronto'): differenze coppia per coppia e giorno per giorno
    con i giorni registrati, righe del file che in Assisto non ci sono e coppie solo in
    Assisto, senza scrivere;
  - elenco degli import del lotto (`GET /api/napoli/lotti/<id>/import`): solo conteggi;
  - privacy: codici fiscali solo nelle anagrafiche; mai nelle risposte (mascherati), nel
    registro attivita', in `napoli_import` (esito e registro dell'annullamento), in
    `napoli_annullamenti` o nel log.
- **Test**: `tests/test_napoli_schema.py` (migrazione su un database v1.20.1 con
  l'archivio Roma inventato confrontato con il gemello riaperto dalla versione
  vecchia; da un database gia' alla v2 con dati alla v3 e alla v4, da uno alla v3
  alla v4; rieseguibilita', interruzione, ripristino, impronte delle migrazioni 2 e 3,
  vincoli);
  `tests/test_napoli_calcoli.py` (con soli dati inventati: le quantita' e le tariffe
  della fattura reale di giugno ricalcolate al centesimo, i due fogli firma ricostruiti
  con orari equivalenti, letture ambigue, date e orari che non esistono, precedenza
  delle causali, domeniche, regole, tariffe e contratti sovrapposti, coordinatore,
  testi congelati, bloccanti; IBAN, partita IVA, codici fiscali, euro, destinatario e
  servizio della determina); `tests/test_napoli_impostazioni.py` (procedura guidata,
  controlli lato server, sovrapposizioni, IBAN mascherato, Ctrl+Z separato, Roma intatta,
  voce di menu marcata); `tests/test_napoli_import.py` e `tests/test_napoli_privacy.py`
  (passi 1.4-1.5, sul master inventato di `tests/napoli_sintetico.py`, generato durante
  i test: 41 righe, 1.554 ore, codici fiscali con il comune Z999; totali per figura,
  VERIFICA ignorata, ore da confermare (scelta obbligatoria), grado, plessi, sostituti e
  subentro, reimport, ore scritte a mano, annullamento anche con Ctrl+Z, solo confronto,
  mese chiuso, errori del file, copia di sicurezza, Roma intatta con alunni omonimi; il
  mese dopo (aprile, stesse righe: `napoli_sintetico.genera(anno=, mese=)`): coppie che
  continuano, municipalita' diversa da Assisto o mancante, codici fiscali corretti di
  operatori e alunni senza doppioni, omonimi, reimport senza una riga; nessun codice
  fiscale in risposte, registro, import, Ctrl+Z e log, nemmeno se scritto in una cella).

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

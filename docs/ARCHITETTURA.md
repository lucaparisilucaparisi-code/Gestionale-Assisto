# Architettura & guida sviluppatore — Gestionale OEPAC

Nota tecnica per chi sviluppa. Per l'uso e l'installazione vedi il `README.md`.

## Struttura dei moduli

| File | Responsabilità |
|------|----------------|
| `app.py` | Applicazione Flask: route pagine e molte API, autenticazione (sessione + WebAuthn), import. Registra i blueprint sotto. |
| `database.py` | Tutto l'accesso ai dati SQLite: schema/migrazioni, CRUD, calcoli di dominio. |
| `napoli_schema.py` | Solo lo schema della sezione Napoli (tabelle `napoli_*`): le migrazioni 2, 3, 4 e 5 di `database.py` (vedi "Sezione Napoli"). |
| `napoli_db.py` | Accesso ai dati di Napoli (solo tabelle `napoli_*`): Impostazioni, controlli che guardano il database (nomi doppi, date sovrapposte), Ctrl+Z di Napoli (`napoli_annullamenti`, senza dati personali). |
| `napoli_anagrafiche.py` | Anagrafiche di Napoli (passo 1.6): elenchi con ricerca e filtri, schede, creazione e modifica a mano, archiviazione di alunni, operatori, scuole e plessi, coppie e PEI. |
| `routes_napoli.py` | Blueprint della sezione Napoli: pagine `/napoli` e API `/api/napoli/...`. |
| `import_napoli.py` | Import del file Excel "master" di Napoli (del coordinatore): l'anagrafica (azione principale) o anche le ore di un mese; lettura del file, anteprima senza scritture, conferma, reimport, annulla import, solo confronto (vedi "Sezione Napoli"). |
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
  (l'annuale: la media dei mesi attivi), mai la base di oggi. Lo stesso nelle pagine:
  tabella e storico dell'utente in Rendicontazione (con la base tra parentesi se e'
  diversa), elenco "senza ore" di Chiusura mese e anteprima dei Report, da
  `monte_ore_effettivo` di `/api/rendicontazione/<anno>/<mese>`; l'elenco "senza ore"
  dello "Stato del mese" della Dashboard da `monte_ore` di
  `/api/stats/utenti-da-completare/<anno>/<mese>` (`get_monte_ore_effettivo_bulk`);
  il bilancio della scheda dell'utente (scheda Assegnazioni: monte ore contro ore
  assegnate agli operatori) da `/api/utente/<id>/assegnazioni?mese=YYYY-MM` con il mese
  di oggi (`get_bilancio_assegnazioni_utente(id, periodo)`, `risolvi_monte_ore`, con la
  base sotto se una variazione la cambia; senza `mese` l'API resta sulla base, come
  nella fotografia). Le due somme "di oggi", "monte ore a
  settimana" della Dashboard e "Monte ore settimanale oggi" delle Statistiche, hanno
  una sola funzione, `monteOreSettimanaleOggi` di `static/js/app.js` (utenti attivi,
  ognuno col monte ore del mese di oggi; chi non e' nella vista del mese resta con la
  base): prima la Dashboard dava 59 h e le Statistiche 57 con una variazione in corso.
  `monte_ore_totale` di `/api/stats/advanced` resta la somma delle basi (e' nella
  fotografia) e le Statistiche lo mostrano solo se la vista del mese non risponde.
- **Confronto annuale** → Statistiche (`/api/stats/confronto-annuale-dettaglio`) e
  Report (`variazioniConfrontoAnnuale` nella pagina) seguono la stessa regola: anni dal
  piu' recente, variazione nella riga dell'anno piu' recente rispetto all'anno prima,
  sulle ore erogate; nessuna variazione con "dati non ancora inseriti" se nel mese
  nessun utente ha la riga (ore o pasti, anche a zero) o con "mese non ancora
  concluso"; un mese con le righe ma 0 ore da' -100% in tutte e due. La percentuale si
  arrotonda una volta sola, al decimo e come il server (`round` di Python: ore al
  centesimo, poi la variazione; a meta' esatta la cifra pari, 6,25% -> 6,2%): nel Report
  con `arrotondaComePython`, perche' Intl scriverebbe 6,3%; il "+" solo sopra zero. I conteggi sono
  diversi e lo dicono le etichette: "Utenti con dati" (righe del mese) in Statistiche,
  "Utenti in servizio" (tutti quelli del mese) nel Report, "utenti con ore" (ore > 0)
  nel Confronto mese, che confronta le ore per giorno di scuola.
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
  Un cambiamento di Roma voluto si fotografa invece sul codice nuovo, dichiarandolo
  nel commit e confrontando la fotografia vecchia con la nuova: nessun numero e
  nessuna struttura (chiavi, righe) diversi, solo i testi attesi. Cambiamenti voluti
  finora (stessi numeri della v1.20.1): **passo roma-visualizzazione**, testi al
  singolare con 1 (titoli di `/api/alerts`, messaggi di `/api/stats/validazione`,
  tre frasi della Relazione Word), impronte della cornice di otto pagine (script:
  monte ore del mese, plurali, etichette dei confronti) e di `dashboard.js`; con la
  revisione del passo, le impronte della cornice di Import, Report, Statistiche e
  Utenti (plurali, monte ore di oggi, "Utenti con dati", regola del Confronto annuale),
  del contenuto di Import (l'anteprima scrive "1 riga valida trovata su 1 riga
  totale") e di nuovo di `dashboard.js`; **passo minori-1.8**, solo l'impronta della
  cornice del Report (la percentuale del Confronto annuale arrotondata come il server).
  Il bilancio della scheda dell'utente (Assegnazioni) col monte ore del mese non cambia la
  fotografia: `/api/utente/<id>/assegnazioni` senza `mese` resta sulla base, e lo script
  della pagina sta dentro `<main>`, di cui la fotografia guarda id, intestazioni e testo
  ma non gli script (lo controlla `test_le_pagine_mostrano_il_monte_ore_del_mese_nel_comportamento`).
  `app.js` non ha impronta (`STATICI_MODIFICABILI`): le
  sue funzioni di Roma nuove (`quanti`, `monteOreSettimanaleOggi`) e quelle del Report
  le esegue con node `tests/test_roma_visualizzazione.py`, sulle risposte del server.
- **Invarianza** (`tests/test_roma_invariata.py`): fotografia, poi i dati di Napoli
  (`tests/seme_napoli.py`, `carica_seme_napoli`: riempie tutte le tabelle `napoli_*`;
  con un client i dati che hanno gia' le loro API passano da li', dal passo 1.3
  cooperativa, destinatario, lotto con le tariffe dalla procedura guidata,
  contratti, regole e qualifiche, il resto si scrive direttamente; dai passi 1.4-1.5,
  dopo le righe scritte direttamente, il master di marzo 2026 inventato con alunni e un
  operatore omonimi di quelli di Roma, con anteprima e conferma: prima l'anagrafica, poi le
  ore del mese; dal passo 1.6 le Anagrafiche scritte a mano con le loro API, con un alunno e
  un operatore omonimi di Roma: scuola, PEI con il cambio da una data, coppia, sostituto,
  subentro, chiusura, modifiche, archiviazione e ripristino; dal passo 1.8 le ore del
  coordinatore di ottobre 2025, scritte, cambiate e annullate con le loro API prima che il
  mese si chiuda; dal passo 1.7 la griglia presenze di novembre 2025 (ore, sigle, alunno
  assente con la meta' dalla programmazione, "1,30" da confermare, ritardo con l'orario,
  uscita didattica, assenza recuperata, Ctrl+Z) e la chiusura del mese del lotto (chiuso,
  scrittura rifiutata, riaperto con il motivo, richiuso); dal passo 1.9, prima di quella
  chiusura, il prospetto fattura di novembre 2025 (ore del coordinatore scritte, fattura del
  grado inferiore definitiva, casella del periodo rifiutata, riapertura con il motivo, di nuovo
  definitiva, Excel, stampa, ritenute) e la chiusura che, senza la fattura del grado superiore,
  va confermata (`senza_fattura`); ogni passo di
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
  `database.py` lo registra nel runner delle migrazioni: `SCHEMA_VERSION = 7`,
  `MIGRAZIONI = {2: napoli_schema.crea_v2, 3: napoli_schema.crea_v3, 4: napoli_schema.crea_v4,
  5: napoli_schema.crea_v5, 6: napoli_schema.crea_v6, 7: napoli_schema.crea_v7}`;
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
  riferimento amministrativo del lotto). `crea_v5` (passo 1.6, Anagrafiche) aggiunge
  `modificato_il` a scuole, alunni, operatori, coppie e PEI (l'ultima scrittura a mano
  nella scheda Anagrafiche; vuoto = mai toccata a mano, l'import non la riempie) e
  `archiviato_dal` agli operatori, solo se mancano. `crea_v6` (passo 1.7, griglia presenze)
  aggiunge a `napoli_presenze` il tipo della nota del giorno (`nota_tipo`: `evento`,
  `attivita_esterna`, `ritardo`, `uscita_anticipata`, controllato in Python come le causali,
  `napoli_calcoli.TIPI_NOTA_GIORNO`) e l'orario del ritardo o dell'uscita (`nota_ora`), solo se
  mancano; la descrizione libera resta in `nota`. `crea_v7` (passo 1.9, prospetto fattura)
  aggiunge a `napoli_fatture` la testata congelata della fattura definitiva (`testata_json`:
  nome e numero del lotto, CIG, CUP, codice univoco ufficio, numero e accordo quadro del
  contratto applicativo, ragione sociale, partita IVA e codice fiscale della cooperativa, IBAN
  solo mascherato), quando e' stata resa definitiva (`definitiva_il`) e l'ultima riapertura
  (`riaperta_il`), solo se mancano. La banca ore della fase 2 (PROGETTO §4.3, la' chiamata
  v3) sara' quindi la migrazione 8 (`crea_v8`).
- **Migrazioni gia' pubblicate non si cambiano**: un database puo' essere gia' a
  quella versione e rieseguirla non lo correggerebbe. `test_la_migrazione_2_pubblicata_non_cambia`,
  `test_la_migrazione_3_pubblicata_non_cambia`, `test_la_migrazione_4_pubblicata_non_cambia`,
  `test_la_migrazione_5_pubblicata_non_cambia`, `test_la_migrazione_6_pubblicata_non_cambia` e
  `test_la_migrazione_7_pubblicata_non_cambia` fissano le impronte di `crea_v2`, `crea_v3`,
  `crea_v4`, `crea_v5`, `crea_v6` e `crea_v7`; ogni correzione e' una migrazione nuova, sicura anche su un database gia'
  aggiornato e con dati (`crea_v4` aggiunge la colonna solo se manca): `crea_v3` ricostruisce
  `napoli_coordinamento` (nuova tabella, copia, `DROP`, `RENAME`, nella stessa
  transazione; le righe della v2, una per operatore, diventano il totale del mese)
  solo se ha ancora la forma della v2, e aggiunge le colonne di `napoli_fatture`
  solo se mancano (`PRAGMA table_info`).
- **Aggiornamento**: all'avvio, dopo il backup "pre-aggiornamento", un database con
  `user_version` 1 (v1.20.1 e precedenti), 2, 3, 4, 5 o 6 passa a 7. Le migrazioni mancanti
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
  manca per le fatture, `GET /api/napoli/lotti/<id>/controlli`: la determina mancante con
  numero e grado del contratto, per esempio «XI (grado inferiore)»; una tariffa lasciata
  vuota apposta, senza proposta come quella dell'interprete LIS, e' un avviso solo se nel
  lotto ci sono coppie o ore di quella figura; sotto, le **ore del coordinatore**, passo
  1.8: vedi il punto "Ore del coordinatore"), **Presenze** (`/napoli/presenze`, passo 1.7:
  vedi il punto "Griglia presenze"), **Anagrafiche** (`/napoli/anagrafiche`,
  passo 1.6: vedi il punto "Anagrafiche"), **Fattura** (`/napoli/fattura`, passo 1.9: vedi il
  punto "Prospetto fattura"), **Importa**
  (`/napoli/import`, l'anagrafica dal file Excel "master") e **Impostazioni**
  (`/napoli/impostazioni`, una parte alla volta, `#lotto`, `#contratti`...): dati della
  cooperativa e destinatario (`napoli_impostazioni`), lotti, contratti applicativi per
  lotto e grado, tariffe e regole con data, qualifiche (una nuova si salva solo con la
  figura scelta, nessuna e' gia' scelta; cambiare la figura di una grafia predefinita non
  la rende eliminabile, perche' serve a leggere il file master). Pagine e script
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
    annulla solo l'ultima, entro 24 ore, con l'id mostrato nella conferma. Delle righe di
    alunni e operatori non si salvano mai i dati personali (`napoli_db.COLONNE_PERSONALI`:
    cognome, nome, codice fiscale, note; PROGETTO D11): Ctrl+Z rimette solo le altre
    colonne, e un'azione che cambia quei dati o elimina una persona si registra come non
    annullabile (`registra_non_annullabile`, `{"versione": 1, "non_annullabile": motivo}`),
    cosi' Ctrl+Z non annulla in silenzio l'azione di prima e dice perche' (`non_annullabile`
    in `/api/napoli/annulla/ultima`, 400 `NON_ANNULLABILE`). Allo stesso modo il testo
    libero di coppie e PEI (`COLONNE_TESTO_LIBERO`: le note della coppia, la nota "da dove
    viene" del PEI, dove potrebbe finire per sbaglio un nome o un dato sanitario): non si
    salva, cambiarlo non si annulla (`MOTIVO_TESTO_LIBERO`) e una coppia o un PEI eliminati
    tornano con Ctrl+Z senza (la risposta lo dice); lo stesso per la descrizione libera della
    nota del giorno delle presenze. Ctrl+Z non cambia le righe di un mese chiuso del lotto
    (`TABELLE_DEL_MESE`: le ore del coordinatore, con anno e mese, e le presenze, con la data:
    409 `MESE_CHIUSO_LOTTO`). Le descrizioni non hanno nomi
    ("Modifica di un alunno (scheda n. 12): grado"); il nome per la finestra di conferma si
    legge al momento dalle anagrafiche (`chi`, solo di persone, coppie e PEI, e dei giorni della
    griglia se sono tutti della stessa coppia: il nome di una scuola e' gia' nella
    descrizione), mai salvato. Prima di chiedere conferma la pagina
    salva le caselle ancora in sospeso (`NapoliComune.primaDiAnnullare`). Le azioni
    scadute restano solo con la descrizione (senza valori): le righe di prima, IBAN
    compreso, si tolgono (`dati = '{}'`) a ogni nuova azione, a Ctrl+Z e all'apertura
    delle pagine di Napoli (`napoli_db.pulisci_annullamenti`). In `app.js`
    Ctrl+Z chiama `window.annullaPagina` se la pagina lo definisce (solo le pagine di
    Napoli), altrimenti l'annulla di Roma;
  - registro attivita': voci `napoli_*` senza valori (mai IBAN o codici fiscali);
  - **import del file Excel "master"** (scheda **Importa**, `/napoli/import`; passi 1.4-1.5,
    `import_napoli.py`): vedi il punto seguente.
- **Anagrafiche** (scheda **Anagrafiche**, `/napoli/anagrafiche`; passo 1.6,
  `napoli_anagrafiche.py`): una parte alla volta, `#alunni`, `#operatori`, `#scuole`,
  `#coppie`, e la scheda di un alunno o di un operatore (`#alunno-12`, `#operatore-7`). I
  dati arrivano soprattutto dal caricamento dell'anagrafica (REGOLE 14): con l'anagrafica
  del lotto vuota la pagina invita a «Carica l'anagrafica dal file Excel» (o ad aggiungere
  a mano, dalle scuole).
  - elenchi (`GET /api/napoli/lotti/<id>/alunni|operatori|scuole|coppie`) con i filtri
    nell'indirizzo: scuola, municipalita' (della scuola, REGOLE 12), figura, grado
    (dell'alunno, altrimenti della scuola; `da_decidere`), stato (in servizio, da
    sistemare, archiviati, tutti; per le coppie in corso, da cominciare, finite), ruolo e
    nome; mai la ricerca nell'indirizzo, che finisce nei log (anche un codice fiscale
    scritto a meta' o sbagliato): la pagina chiede gli elenchi con
    `POST /api/napoli/lotti/<id>/anagrafiche/elenco` (`parte`, filtri e `cerca` nel corpo),
    la GET con `?cerca=` e' 400 `RICERCA_NELL_INDIRIZZO`; la ricerca di un codice fiscale
    intero e' `POST /api/napoli/anagrafiche/codice-fiscale` e la risposta non lo ripete.
    `GET /api/napoli/lotti/<id>/anagrafiche`: conteggi, cosa c'e' da sistemare (scuole con
    il grado da decidere o senza municipalita', alunni senza PEI o senza coppie in corso,
    operatori con il codice fiscale da controllare o con piu' ore del contratto, coppie
    con una figura diversa da quella dell'operatore...), scuole e municipalita' per i
    filtri, `vuota` (senza scuole, alunni e coppie del lotto: la pagina invita a caricare
    l'anagrafica anche se c'e' gia' un operatore, che e' della cooperativa). Gli operatori
    non sono di un lotto: un lotto mostra quelli con coppie nel lotto e quelli senza nessuna
    coppia. "Oggi" decide cosa e' in corso;
  - schede (`GET /api/napoli/alunni/<id>`, `GET /api/napoli/operatori/<id>?lotto_id=`):
    dati con il codice fiscale mascherato, da dove vengono (il caricamento che li ha
    creati o "aggiunto in Assisto"), PEI per figura con lo storico e la riga in vigore,
    coppie (con titolare dei sostituti, ore della coppia o del PEI, ore, fogli e orari
    collegati); nella scheda dell'alunno lo spazio del **credito/debito** di Napoli
    (REGOLE 15): dal passo 1.7 il credito/debito del mese di ogni coppia e' nella griglia
    presenze e nel dettaglio della coppia, e lo spazio lo dice; il riepilogo per figura, nel
    mese e dall'inizio dell'anno, arriva con un passo successivo;
  - scritture con i controlli lato server e `{error, code, campo}`: scuole (nome,
    codice meccanografico di 10 caratteri, municipalita' 1-10, grado o da decidere; lo
    stesso codice o, senza codice, lo stesso nome nella stessa municipalita' e' 409
    `SCUOLA_GIA_PRESENTE`, in un'altra municipalita' e' un altro plesso; avviso se il grado
    non e' quello del codice), alunni (codice fiscale di 16 caratteri con il carattere di
    controllo, unico: 409 `ALUNNO_GIA_PRESENTE`; scuola attiva del lotto; il grado
    obbligatorio se la scuola e' mista; esami; note con i codici fiscali mascherati come
    quelle del file), operatori (figura dall'elenco chiuso, livello, ore di contratto 0-40,
    codice fiscale facoltativo ma giusto e unico), PEI (`POST /api/napoli/alunni/<id>/pei`:
    il valore nuovo da un giorno chiude quello di prima il giorno prima e, se il nuovo ha una
    fine, quello di prima riprende il giorno dopo; uno che comincia lo stesso giorno o dopo
    e' 409 `PEI_SOVRAPPOSTI`; il coordinatore non ha PEI ne' coppie), coppie (alunno,
    operatore, figura e ruolo si scelgono quando nascono; sostituto con il titolare dello
    stesso alunno e figura; la stessa coppia negli stessi giorni e' 409
    `COPPIA_GIA_PRESENTE`; le date devono comprendere i giorni con ore, 409
    `ORE_FUORI_DATE`; avvisi per figura diversa, PEI mancante, due titolari),
    **chiusura** (`/chiudi`) e **subentro** (`/subentro`: la coppia finisce il giorno prima
    e ne nasce una con l'altro operatore, la stessa scuola e le stesse ore, in un'azione; i
    sostituti della coppia di prima che cominciano dal giorno del subentro passano alla
    coppia nuova, uno gia' cominciato resta dov'e' con un avviso). Allungare o riaprire la
    coppia di un operatore o di un alunno archiviato e' 409 `ARCHIVIATO`, come crearla;
  - **archiviazione al posto della cancellazione**: si elimina solo cio' che non ha dati
    collegati (una scuola senza alunni, coppie e giorni del calendario; un alunno senza ore,
    fogli firma e orari, con i suoi PEI e coppie; un operatore senza coppie e ore del
    coordinatore; una coppia senza ore, fogli, orari e sostituti; un PEI senza ore nel suo
    periodo), altrimenti 409 `*_CON_DATI`. L'alunno si archivia da un giorno (`archiviato_dal`):
    coppie e PEI ancora aperti finiscono il giorno prima, nella stessa azione, ma non da un
    giorno con ore registrate (409 `ORE_DOPO_LA_DATA`); un operatore o una scuola con coppie
    ancora aperte non si archivia (409 `OPERATORE_CON_COPPIE`, `SCUOLA_IN_USO`: prima la
    chiusura o il subentro). Il ripristino rimette in servizio, coppie e PEI chiusi restano
    chiusi;
  - ogni scrittura riempie `modificato_il` e passa da Ctrl+Z di Napoli; registro
    attivita' con il numero della scheda, mai nomi o codici fiscali.
- **Ore del coordinatore** (scheda **Mese**, riquadro sotto i controlli; passo 1.8,
  `napoli_coordinamento.py`, REGOLE 9 e 12): il coordinatore si fattura a ore con un
  **totale mensile per lotto, grado e contratto applicativo** (`napoli_coordinamento` nella
  forma della migrazione 3: una riga per mese, operatore facoltativo che la pagina non
  chiede e mai in fattura, nota facoltativa con i codici fiscali mascherati, `modificato_il`).
  - `GET /api/napoli/lotti/<id>/coordinamento`: i mesi dei contratti del lotto fino al mese
    di oggi (dal piu' recente; le ore si scrivono da ora in avanti, REGOLE 14), per ogni mese
    i contratti che lo toccano e i loro gradi (senza grado = tutti e due), con il periodo
    tagliato al contratto (`periodo_fattura`: «dal 08/06/2026 al 30/06/2026»), le ore
    salvate («71,55»), la nota, il mese chiuso; i contratti che cominciano dopo (`futuri`).
    La pagina mostra gli ultimi sei mesi e, a richiesta, gli altri;
  - `PUT /api/napoli/lotti/<id>/coordinamento` (anno, mese, contratto, grado, `ore` e/o
    `nota`: un campo che non arriva resta com'e'): ore in decimale al centesimo con
    `napoli_calcoli.leggi_ore_coordinatore` («71,55»; «71.55» vale 71,55 e la risposta lo
    dice in `lettura`; «71,555» ha troppi decimali, «71:33» sono ore e minuti con il loro
    decimale, «7155» propone «71,55», oltre 744 ore o negative: 400 sul campo `ore` con il
    messaggio da mostrare); casella vuota = ore tolte; una nota senza ore no. Il contratto
    deve essere del lotto, del grado e del mese (400 `FUORI_CONTRATTO`), il mese gia'
    cominciato (400 `MESE_FUTURO`) e aperto (409 `MESE_CHIUSO_LOTTO`);
  - Ctrl+Z di Napoli (`coordinamento` in `TABELLE_ANNULLABILI`, la nota compresa: e' del
    lotto e del mese, non di un alunno) e registro attivita' (`napoli_coordinamento`, senza
    nomi: «ottobre 2026, contratto XI (grado inferiore), 71,55»);
  - un contratto con ore del coordinatore non si elimina e non cambia date o grado che le
    lascerebbero fuori (409 `CONTRATTO_USATO`, `_ore_coordinatore_fuori`);
  - la pagina (`NapoliCoordinatore` in `napoli.js`): una casella per riga con il
    salvataggio automatico dopo 2 secondi o uscendo dalla casella (solo i campi cambiati,
    "Salvato alle ..." accanto al titolo, `fetch keepalive` se si lascia la pagina), Invio
    e frecce come in Rendicontazione, il messaggio del server sotto la riga, le caselle di
    un mese chiuso bloccate. Le ore entrano nella riga «Coordinatore» della fattura
    (`righe_fattura`, con la tariffa COORDINATORE del periodo) della scheda Fattura, che le
    mostra e le fa scrivere anche li'; con la fattura definitiva di quel mese, contratto e grado
    la riga e' bloccata (badge «Fattura definitiva», 409 `FATTURA_DEFINITIVA`).
- **Griglia presenze** (scheda **Presenze**, `/napoli/presenze`; passo 1.7, `napoli_presenze.py`,
  PROGETTO §5-§6, REGOLE 1-3, 12, 14, 15): il mese del lotto come il foglio "master" del
  Comune. Le ore si scrivono qui da ora in avanti (REGOLE 14: nessuno storico); ogni casella e'
  un giorno di `napoli_presenze` (l'unica fonte delle ore), con le ore riconosciute calcolate
  e salvate (`minuti_riconosciuti`: la fattura legge quelle).
  - `GET /api/napoli/lotti/<id>/presenze?anno=&mese=`: intestazione (mese chiuso con data e
    nota, `finito` dall'ultimo giorno, lo stesso per la chiusura e per l'avviso `coppia_senza_ore`,
    oggi, `avviso_vacanze`), colonne (`napoli_calcoli.colonne_mese`: i giorni di servizio
    lun-sab, senza domeniche, con le chiusure del calendario del lotto e le festivita'
    (`festivo`), gli eventi e i giorni futuri, e la VERIFICA dopo ogni settimana), una riga per coppia valida nel mese
    o con ore nel mese (alunno, operatore, figura, ore PEI o quota della coppia, SI/NO del
    sostituto, scuola e municipalita' della scuola, grado), le caselle in forma corta (`t`
    testo come nel master, `k` tipo, `r` minuti riconosciuti, `c` riconosciute nell'angolo se
    diverse dal testo, `p` programmati, nota, avvisi, `bl` registrato dal foglio firma con gli
    orari), i giorni fuori dalle date della coppia e le chiusure della scuola, le settimane, il
    totale, il credito/debito, gli avvisi spiegati e i filtri. Con 330 coppie per 27 giorni la
    risposta e' di circa 0,3 s e la pagina e' pronta in meno di un secondo e mezzo
    (`test_330_coppie_si_caricano_in_meno_di_2_secondi`);
  - caselle (`napoli_calcoli.giorno_da_griglia`, funzione pura): come `leggi_ore_griglia`
    (ore decimali, ore e minuti, sigle F, M, P/F perm dell'operatore a 0 ore, A alunno
    assente; "1,30" e gli altri decimali che non sono quarti d'ora tornano `da_confermare` con
    le due letture, e si salvano con `conferma`); A vale `quota_assenza_alunno` x il
    programmato del giorno (dalla presenza o dalla programmazione settimanale della coppia;
    se non si conosce torna `servono_programmati` e la pagina chiede le ore programmate); vuoto
    = la presenza si cancella, nota del giorno compresa (un giorno preparato dalla
    programmazione torna "programmato"; la risposta dice `tolta_nota` e `tolta_descrizione`, e
    la pagina avverte che Ctrl+Z rimette il giorno con il tipo e l'orario della nota ma senza la
    descrizione libera). Una nota scritta dalla sua finestra su una casella vuota (arriva con
    `nota_tipo`) vale invece un giorno con 0 ore, che la casella mostra come «0».
    La **nota del giorno** (`TIPI_NOTA_GIORNO`): assemblea o evento ed uscita didattica
    contano le ore svolte (REGOLE 2, causali `evento` e `attivita_esterna`, che vincono
    sull'assenza dell'alunno), ritardo e uscita anticipata con l'orario contano le ore svolte
    piu' `quota_assenza_parziale` della parte persa (REGOLE 12, causale `alunno_parziale`; le
    svolte non possono superare il programmato), "assenza recuperata" toglie la meta'
    (REGOLE 1, trattamento `recupero`); una descrizione libera facoltativa (100 caratteri,
    codici fiscali mascherati). Una nota senza ore vale un giorno registrato con 0 ore svolte.
    Scrivendo **solo nella casella** (come in Excel, senza la finestra della nota), la parte
    della nota del giorno che con il nuovo valore non vale piu' si toglie da sola: il ritardo
    o l'uscita con «A» (`assente_e_parziale`) o con F, M, P (`operatore_e_parziale`), «assenza
    recuperata» con le ore svolte o con l'operatore assente (`recupero_senza_assenza`); la
    risposta lo dice (`tolte`, frasi da mostrare) e Ctrl+Z rimette il giorno com'era. Le ore
    oltre il programmato con un ritardo gia' scritto non si indovinano: errore
    `svolte_oltre_il_programmato` con il messaggio che rimanda a «Nota del giorno». Quello che
    arriva dalla finestra della nota (con `nota_tipo` o `recuperata`) non si tocca.
    La casella si mostra come nel master (`testo_ore_cella`: 90 -> "1,5", 80 -> "1:20", che si
    rilegge uguale); i totali in ore decimali (`ore_brevi`);
  - `POST /api/napoli/lotti/<id>/presenze` (anno, mese, `celle`: coppia, data e i campi che
    cambiano: `testo`, `conferma`, `programmati`, `nota_tipo`, `nota_ora`, `nota`,
    `recuperata`; un campo che non arriva resta com'e'; al massimo 2.000 caselle): il
    salvataggio a gruppi. Le caselle che non si salvano tornano con il loro esito e il
    messaggio da mostrare (`errore` con il codice, `da_confermare`, `servono_programmati`) e
    le altre si salvano lo stesso; si rifiutano i giorni non di servizio, futuri
    (`GIORNO_FUTURO`), fuori dalle date della coppia (`FUORI_DALLE_DATE`), registrati dal
    foglio firma con gli orari (`DAL_FOGLIO`), oltre 12 ore, le sigle sconosciute; il mese
    chiuso del lotto rifiuta tutto (409 `MESE_CHIUSO_LOTTO`). Ogni salvataggio con cambiamenti
    e' un'azione di Ctrl+Z di Napoli («Griglia presenze di ottobre 2026: 2 caselle (1 scritta,
    1 cambiata)», `presenze` in `TABELLE_ANNULLABILI`; la descrizione libera non resta in
    memoria: cambiarne una che c'era non si annulla, una casella cancellata torna senza) e una
    voce del registro attivita' senza nomi. La risposta ha le righe ricalcolate dello stesso
    alunno (la VERIFICA e il credito/debito cambiano anche nelle righe del titolare e dei
    sostituti);
  - **festivita'** (`napoli_calcoli.festivita`, funzione pura: le nazionali fisse, il 4
    ottobre dal 2026, il 19 settembre San Gennaro patrono di Napoli, Pasqua e Pasquetta con
    `pasqua`): giorni chiusi di tutto il lotto, come le chiusure del calendario (una chiusura
    scritta nello stesso giorno tiene la sua descrizione); le vacanze di Natale e di Pasqua del
    calendario regionale non si calcolano (nessuna data inventata): finche' il calendario del
    mese non ha chiusure, nei mesi in cui cadono (`vacanze_da_calendario`) l'intestazione ha
    `avviso_vacanze` e la pagina lo mostra sotto la griglia e nel dettaglio
    (`test_festivita_tolte_dalle_previste_e_grigie`). Il passo 1.12 (scheda Calendario)
    aggiunge le chiusure;
  - **giorni di chiusura del calendario** (del lotto o della scuola, `napoli_calendario`):
    grigi nella griglia. Scelta dichiarata (PROGETTO §5.5, dove e' un avviso e non un blocco):
    le ore scritte a mano in un giorno chiuso contano come ore svolte (`minuti_riconosciuti` =
    svolte), con l'avviso `ore_in_giorno_di_chiusura` («contano lo stesso: se il servizio non
    c'era, svuota la casella»); quindi entrano nel totale, nella VERIFICA, nel credito/debito e
    nella fattura (passo 1.9). La causale `calendario` del §5.2 (0 ore) vale per i giorni
    preparati dalla programmazione (passi 1.10-1.12), che nei giorni chiusi non si preparano.
    Le previste del credito/debito non contano i giorni chiusi
    (`test_ore_in_un_giorno_di_chiusura_contano_con_l_avviso`);
  - **VERIFICA** per alunno e figura (titolari piu' sostituti, `verifica_settimane`): gialla
    oltre il PEI, rossa oltre il tetto (PEI x 1,2); ogni riga mostra le sue ore della
    settimana, il colore e' quello del gruppo;
  - **credito/debito** (REGOLE 15, `napoli_calcoli.minuti_previsti` e `credito_debito`):
    previste = la programmazione settimanale della coppia nei giorni di servizio validi (senza
    festivita', chiusure e giorni fuori dalle date) oppure, se manca, il PEI (o la quota della coppia)
    diviso per i 6 giorni di servizio della settimana per ogni giorno, con l'avviso "stima dal
    PEI" (≈); erogate = ore riconosciute della coppia e dei suoi sostituti (le righe dei
    sostituti rimandano a quella del titolare); credito_debito = previste - erogate, con la
    convenzione e i colori della Rendicontazione di Roma (positivo verde = ore ancora dovute
    all'alunno, negativo rosso). Senza PEI e senza programmazione non si calcola (avviso
    `pei_mancante`). Due (o piu') titolari della stessa figura per lo stesso alunno negli stessi
    giorni, con le previste dal PEI intero (senza le ore della coppia): le previste si sommano
    due volte, il programma non divide il PEI da solo e le due righe hanno l'avviso
    `pei_su_piu_titolari` (barra arancione, suggerimento sul nome e sul credito/debito, che e'
    sottolineato);
  - `GET /api/napoli/lotti/<id>/presenze/coppie/<coppia>?anno=&mese=`: il dettaglio della
    coppia nel mese (giorni con la spiegazione del calcolo, «Alunno assente: meta' delle 3:00
    programmate = 1:30 (1,50)», settimane con PEI e tetto, previste ed erogate, sostituti);
  - **chiusura del mese del lotto** (`POST /api/napoli/lotti/<id>/mesi/chiudi`, nota
    facoltativa): dall'ultimo giorno del mese (prima 400 `MESE_NON_FINITO`), una volta sola
    (409 `MESE_GIA_CHIUSO`), con le fatture del mese definitive (PROGETTO §9): se una fattura
    del mese con ore non lo e', 409 `FATTURE_NON_DEFINITIVE` con l'elenco (`fatture`), e la
    finestra chiede «Chiudi lo stesso: per questa la fattura non si fa adesso» (`senza_fattura`);
    da li' ore, note e ore del coordinatore del mese non cambiano, ne'
    con le API ne' con Ctrl+Z. **Riapertura** (`/mesi/riapri`) con il motivo obbligatorio, che
    resta nel registro attivita'; la chiusura e la riapertura non si annullano con Ctrl+Z. Il
    mese chiuso di Roma (`mesi_chiusi`) e quello di un lotto di Napoli sono indipendenti;
  - la pagina (`NapoliPresenze` in `napoli.js`): colonne fisse a sinistra (alunno, operatore,
    figura, PEI, sostituzione) e a destra (totale, credito/debito), intestazione fissa, la
    griglia che prende l'altezza che resta e scorre da sola (REGOLE 13: a 1366x768 e 1536x864
    la pagina non scorre, anche con il mese chiuso e il lotto grande: la testata sta su una
    riga anche con «Modifiche non salvate» o una casella da correggere, perche' sotto i 1500 px
    «Nota del giorno» diventa «Nota», «Riprova a salvare» diventa «Riprova» (senza «N coppie»,
    che e' anche nel riepilogo) e «Salvato alle ..., tranne 1 casella da correggere» diventa
    «1 casella da correggere» (per esteso nel suggerimento); il mese chiuso e' una riga dentro
    la scheda, e un `ResizeObserver` rimisura la griglia quando la testata cambia altezza); la
    barra sopra la griglia descrive per esteso la casella scelta; caselle come in Excel (un clic
    sceglie tutto il valore; la casella scelta con Tab, Invio o le frecce si seleziona subito,
    senza `setTimeout`, come in Rendicontazione: una selezione rimandata cadeva dopo i tasti gia'
    in coda e "1,5" diventava "5"), frecce, Invio e Tab come in
    Rendicontazione, Esc rimette il valore salvato, Ctrl+Z (mentre si scrive toglie le
    lettere, a casella salvata annulla l'ultima azione di Napoli), Maiusc+F2 la nota del
    giorno, incolla di un blocco da Excel; salvataggio automatico 2 secondi dopo l'ultimo tasto
    (Ctrl+S subito) a gruppi di al massimo 2.000 caselle per richiesta, una dopo l'altra (un
    incolla di 100 righe per 27 giorni, 2.700 caselle, parte in due), con lo stato accanto al
    mese ("Modifiche in sospeso…", "Salvataggio…", "Salvato alle ...", "tranne 1 casella da
    correggere"). Se non riesce, come in Rendicontazione: "Modifiche non salvate" (classe
    `errore`, il motivo nel suggerimento), il pulsante «Riprova a salvare» e un avviso in
    italiano (mai «Failed to fetch»); se il collegamento o il programma non rispondono (niente
    risposta o 5xx) riprova da solo dopo 5, 10, 20 e poi ogni 30 secondi; cambiare mese o lotto,
    annullare o chiudere il mese con caselle non salvate resta sul mese mostrato. Le caselle
    **da correggere** (in rosso: sigla sconosciuta, «A» o «1,30» lasciati da sistemare) non sono
    salvate: prima di cambiare mese o lotto, annullare o chiudere il mese la pagina chiede
    («Resta e correggi», anche con Invio, Esc o un clic fuori, torna sulla prima; «Continua
    senza salvarle»). Uscendo dalla
    pagina le caselle in sospeso partono con `fetch keepalive` (al massimo 64 KB in tutto: un
    gruppo di circa 60 KB); se ci sono caselle da correggere, se il salvataggio non riesce o se
    le caselle non ci stanno il browser chiede prima di uscire (`beforeunload`); le domande
    una alla volta ("1,30": un'ora e trenta minuti o 1,30 ore, anche per le caselle dopo; le
    ore programmate che mancano per la meta'), con il fuoco sul campo delle ore o sulla prima
    lettura (un Invio nei primi 600 ms, premuto per la griglia, non sceglie niente); la nota
    del giorno manda anche il valore che si vede in una casella non salvata, in sospeso o da
    sistemare (una «A» lasciata senza le ore programmate si salva con le ore scritte nella
    nota); le parti della nota tolte dal server si leggono in un avviso; filtri per scuola, operatore, figura, grado,
    municipalita' della scuola, ricerca per nome e «N con avvisi»; riepilogo delle righe
    mostrate; clic sul nome per il dettaglio della coppia; il mese scelto ricordato nel
    browser.
- **Prospetto fattura** (scheda **Fattura**, `/napoli/fattura`; passo 1.9, `napoli_fattura.py`,
  `export_napoli.py`, PROGETTO §5.4, §5.5 e §9, REGOLE 9, 10 e 12): una fattura per lotto, grado
  (inferiore o superiore), contratto applicativo e periodo, cioe' il mese tagliato alle date del
  contratto (il contratto XI dall'08/06 da' «dal 08/06/2026 al 30/06/2026»). I numeri sono quelli
  di `napoli_calcoli.prospetto_fattura` (righe per figura e tariffa valida, sotto-periodo se la
  tariffa cambia, riga «Coordinatore» dal totale mensile del passo 1.8, ritenuta 0,50% con il
  testo della fattura reale, imponibile, IVA 5%, totale, da pagare = imponibile con lo split
  payment; oggetto, nota con la D.D., destinatario, scadenza a 30 giorni dalla data della
  fattura): la fattura reale di giugno (71,55 h coordinatore x 29,66; 292,75 h educatore x 24,28;
  6 h psicologo x 29,66; 654,25 h asacom x 23,44) da' 24.743,72 / -123,72 / 24.620,00 / 1.231,00 /
  25.851,00, da pagare 24.620,00 (`test_giugno_come_la_fattura_reale`).
  - `GET /api/napoli/lotti/<id>/fatture?anno=&mese=`: un prospetto per contratto che tocca il
    mese e per grado (senza grado = tutti e due), con righe e totali (centesimi e testo
    «24.743,72»), testi, testata (CIG, codice univoco, contratto, cooperativa, IBAN mascherato),
    ore del coordinatore (con `modificabile`), dettaglio per scuola e per operatore (mai alunni),
    stato (`da_fare`, `definitiva`, `riaperta`), `impronta` e i **controlli** spiegati con titolo,
    testo semplice e dove sistemarli (`link`): bloccanti (§5.5) grado da decidere, figura con ore e
    senza tariffa, tariffa del coordinatore che cambia nel periodo, ore fuori da ogni contratto
    applicativo o in due contratti (del grado, nel mese intero), giorni preparati e non
    registrati, dati mancanti (CIG, destinatario, oggetto, numero e data della D.D. — insieme se
    mancano tutti e due —, IBAN), periodo non ancora finito; avvisi: ore del coordinatore non
    scritte, ore con la figura Coordinatore nella griglia (non contate), nessuna ora, dati
    cambiati dopo la definitiva (`cambiata_dopo`, con l'imponibile che darebbe oggi). Le ore che
    nessun contratto copre sono anche in testa alla pagina (`ore_senza_contratto`);
  - **Rendi definitiva** (`POST /api/napoli/lotti/<id>/fatture/definitiva`: anno, mese,
    contratto, grado, numero e data della fattura emessa dal programma di fatturazione, D9, e
    `impronta` del prospetto mostrato): senza bloccanti (400 `FATTURA_BLOCCATA` con l'elenco),
    con ore (400 `NESSUNA_RIGA`), periodo finito, data fra l'inizio del periodo e oggi, numero
    non gia' usato nello stesso anno (409 `NUMERO_GIA_USATO`), prospetto non cambiato nel
    frattempo (409 `PROSPETTO_CAMBIATO`). In una transazione (`BEGIN IMMEDIATE`) congela in
    `napoli_fatture` (stato `definitiva`) righe senza nomi, totali, testi (`testi_da_congelare`,
    con la scadenza) e testata (`testata_json`, migrazione 7): da li' pagina, Excel e stampa
    mostrano la fattura congelata, anche se poi cambiano tariffe, regole, modelli dei testi,
    CIG o cooperativa. Azione «non annullabile» di Ctrl+Z (come la chiusura del mese) e voce
    del registro attivita' con numeri e mai nomi o IBAN;
  - **ore bloccate**: finche' la fattura e' definitiva, le ore del suo periodo e del suo grado
    non cambiano (409 `FATTURA_DEFINITIVA`, con il messaggio che dice quale fattura e di
    riaprirla): caselle della griglia (esito `errore` per casella, giorni in `definitiva` della
    riga e in grigio-verde nella pagina; con il grado da decidere vale una fattura di un grado
    qualsiasi), ore del coordinatore di quel mese, contratto e grado, import delle ore di quel
    mese e il suo annullamento, Ctrl+Z (`napoli_db._controlla_fatture_definitive`), e i dati che
    sposterebbero quelle ore in un'altra fattura: grado della scuola (delle coppie con il grado
    della scuola) e dell'alunno, scuola della coppia, date o grado del contratto che
    cambierebbero il periodo congelato (`napoli_db.controlla_ore_in_fatture_definitive`);
  - **Riapri** (`POST /api/napoli/fatture/<id>/riapri`, motivo obbligatorio che resta nel
    registro attivita', codici fiscali mascherati): stato di nuovo `bozza` (`riaperta_il`), numero
    e data restano e la pagina li propone; il prospetto si ricalcola dai dati e le ore si
    cambiano. Si riapre anche a mese chiuso (le ore restano bloccate dal mese);
  - **ritenute cumulate** (`GET /api/napoli/lotti/<id>/fatture/ritenute`): per contratto
    applicativo le fatture definitive, la somma delle righe e delle ritenute dello 0,50% (si
    svincolano alla fine del contratto), il totale del lotto;
  - **Excel** (`GET /api/napoli/fatture/excel?lotto_id=&anno=&mese=&contratto_id=&grado=`,
    `export_napoli.prospetto_excel`, xlsxwriter con `routes_export.get_excel_brand_styles`):
    fogli «Prospetto» (dati della fattura, righe, ritenuta, totali, da pagare; nessun nominativo),
    «Per scuola», «Per operatore», «Controlli», «Ritenute»; numeri veri con il formato di Excel,
    A4 su una pagina di larghezza; il nome del file dice lotto, contratto, grado e mese;
  - **stampa** (`/napoli/fattura/stampa?...`, `napoli_fattura_stampa.html`, pagina a se' con il
    CSS di stampa): A4 verticale con margini di 14 mm, una pagina sola (provata con il PDF di
    Chromium), cooperativa e destinatario, stato (definitiva con numero e data, o «Non ancora
    definitiva»), dati, oggetto, righe, totali, nota, pagamento con l'IBAN mascherato; con
    `stampa=1` (pulsante Stampa della pagina, in una scheda nuova) chiede subito di stampare o
    salvare in PDF;
  - la pagina (`NapoliFattura` in `napoli.js`): il mese (lo stesso della scheda Presenze, ricordato
    nel browser) con le frecce, un riquadro per prospetto (righe e totali a sinistra; ore del
    coordinatore e controlli a destra; sotto i testi con «Copia» per oggetto e nota, Excel,
    Stampa, «Rendi definitiva» o «Riapri la fattura», il dettaglio per scuola e operatore), i
    prospetti senza ore in fondo, piu' piccoli; le ore del coordinatore si salvano da sole (2
    secondi dopo l'ultimo tasto, uscendo dalla casella, con Invio; frecce ↑ ↓ e Invio come in
    Rendicontazione, Esc rimette il valore salvato; `fetch keepalive` uscendo dalla pagina) e i
    prospetti si ricalcolano; le finestre di definitiva (numero, data, scadenza calcolata) e di
    riapertura (motivo) si confermano con Invio; Ctrl+Z annulla l'ultima azione di Napoli. In
    Presenze, «Chiudi il mese» con una fattura non definitiva mostra l'elenco e la casella
    «Chiudi lo stesso». Provata a 1366x768 e 1536x864, chiaro e scuro.
- **Import del file Excel "master"** (del coordinatore, PROGETTO §7.1):
  - **tre modi** (REGOLE 14: lo storico delle ore di Napoli non si carica, le ore si
    scriveranno in Assisto). `anagrafica`, l'azione principale della pagina («Carica
    l'anagrafica dal file Excel») e il modo predefinito delle API: alunni, operatori con
    qualifica e ore di contratto, scuole e plessi con la municipalita', coppie con la data
    di inizio, PEI; le celle dei giorni servono solo alle date delle coppie (un sostituto
    vale dal primo all'ultimo giorno con ore), niente giorni registrati, niente fogli del
    mese, nessuna ora da confermare e nessun controllo sulle ore (`SOLO_ORE`: non si
    mostrano e non bloccano). `ore` (anche `import`, il nome di prima): anche le ore dei
    giorni del mese, in una parte secondaria e chiusa della pagina («Altro: le ore dei
    giorni di un mese»), insieme al solo confronto (`confronto`). Il modo si salva in
    `napoli_import.esito_json` (`modo`; gli import di prima sono 'ore'): nessuna
    migrazione, lo schema resta alla 4. La `versione_dati` dell'anteprima comprende il
    modo: una conferma in un modo diverso dall'anteprima e' 409 `ANTEPRIMA_SUPERATA`;
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
    (il file si legge appena scelto). Il messaggio rosso, come la rotellina di attesa e
    l'anteprima, sta sotto la scheda di scelta: la pagina lo porta in vista (a 1366x768
    sarebbe fuori dallo schermo, REGOLE 13), con il pulsante «Scegli di nuovo il file».
    Le righe vuote dopo 200 di fila non si leggono;
  - anteprima (`POST /api/napoli/import/anteprima`, multipart: file, lotto, modo,
    scelte): **non scrive nulla**. Abbina solo dentro Napoli:
    - scuole per codice meccanografico e **municipalita' della scuola** (REGOLE 12):
      municipalita' mancante presa dalla stessa scuola se ne ha una sola (nel file o in
      Assisto). Se la scuola ne ha piu' di una (piu' plessi) non si crea mai un plesso
      "senza municipalita'" in piu': vale quella del plesso della coppia gia' in Assisto
      (nota `municipalita_presa_dalla_coppia`), altrimenti il plesso si sceglie nella pagina
      («Plessi da scegliere», scelta `plessi`: riga e scuola -> municipalita', solo fra
      quelle della scuola; finche' non si sceglie e' il bloccante
      `municipalita_da_scegliere` e la riga non si carica; il solo confronto non la chiede,
      e nemmeno una riga che non si carica comunque, per esempio con l'alunno o l'operatore
      da correggere: si chiede quando la riga e' corretta).
      Se la scuola in Assisto c'e' una volta sola e senza municipalita', quella del file si
      aggiunge allo stesso plesso (avviso, l'annullamento la toglie). La stessa scuola con
      municipalita' diverse, nel file o fra il file e Assisto, va confermata con "Ho
      controllato": una municipalita' nuova diventa un altro plesso se serve a una coppia
      nuova; le righe di coppie gia' in Assisto restano nel plesso della coppia, salvo
      quelle in un plesso **senza municipalita'** (lasciato da un import di prima), che
      passano al plesso della municipalita' del file: se tutte le coppie di quel plesso sono
      nel file e una municipalita' non ha ancora un plesso in Assisto, il plesso prende
      quella (la piu' frequente fra le righe); le altre coppie (con l'alunno, se la sua
      scuola era quel plesso e nessuna sua coppia ci resta) passano al plesso della loro
      municipalita', e il plesso senza municipalita' rimasto vuoto (senza coppie, alunni o
      giorni del calendario) si toglie (`tolti.scuole`; l'annullamento lo rimette con lo
      stesso id). Una scuola nuova si crea solo se una coppia nuova (o spostata) la usa
      (niente scuole vuote; una coppia gia' in Assisto con un'altra scuola resta nella
      sua, con un avviso);
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

    Un file di un mese **precedente** all'ultimo caricamento del lotto (marzo dopo aprile, in
    tutti e due i modi) aggiungerebbe le coppie di quel mese e porterebbe indietro i PEI: si
    carica solo con la conferma `mese_precedente` («Ho controllato»).
    Grado delle scuole nuove proposto dal codice (`napoli_calcoli.grado_da_codice_meccanografico`,
    PROGETTO §4.2), cambiabile nella pagina e **da confermare** («Ho controllato i gradi»,
    conferma `gradi`: il grado decide fattura e fondo, REGOLE 9; i codici con la forma delle
    paritarie, NA1x, sono segnati). Le coppie del mese prima che nel file non ci
    sono si possono chiudere (proposta non spuntata); contano i giorni che restano dopo
    l'import, quindi nel reimport anche quella di una riga tolta dal file. Una coppia che
    comincia nel mese e nel file non c'e' resta senza ore e si mostra (se viene da una
    riga sbagliata dell'import di prima: annullarlo e importare di nuovo). Bloccanti (`SPIEGAZIONI`, livello
    'bloccante'): mese chiuso, righe di un altro lotto, qualifica senza figura, codice
    fiscale dell'alunno, scritte che non sono ore, piu' di 12 ore (queste due solo nel
    modo 'ore'), stessa coppia su due righe, qualifica con dentro un codice fiscale (si
    salverebbe fra le grafie delle Impostazioni). Risponde con conteggi, ore (nel modo
    'ore': quelle che Assisto avra' dopo l'import, quindi per un giorno scritto a mano che
    resta contano le ore di Assisto) o coppie e ore PEI (nel modo 'anagrafica') per figura
    e per grado, cosa cambia, avvisi raggruppati e spiegati, codici fiscali solo mascherati
    (`maschera_codice_fiscale`), `sha256` del file e `versione_dati` (impronta dei dati di
    Napoli guardati e modo). Se il file non cambia niente, le conferme restano solo come
    avvisi (senza la casella "Ho controllato") e la conferma risponde "niente da cambiare"
    senza chiederle;
  - conferma (`POST /api/napoli/import/conferma`): stesso file (sha256, 409
    `FILE_CAMBIATO`), stessi dati (409 `ANTEPRIMA_SUPERATA`), mese aperto (409
    `MESE_CHIUSO_LOTTO`), nessun bloccante (400 `IMPORT_BLOCCATO`: il messaggio distingue
    le scelte della pagina, `SCELTE_BLOCCANTI` cioe' qualifiche nuove e plessi, dagli
    errori del file, e dice «caricare l'anagrafica» o «importare» come la pagina; la pagina
    intitola «Da scegliere prima di caricare» i soli bloccanti da scegliere), conferme date (400
    `DA_CONFERMARE`, anche per le ore da confermare non scelte); se il file non cambia
    niente non scrive nulla. Poi
    `database.create_backup()` (senza copia niente import, 503) e **un'unica transazione**
    (`BEGIN IMMEDIATE`, dati riletti e confrontati di nuovo): anagrafiche nuove, coppie,
    PEI del mese per alunno e figura (dalle righe NO); nel modo 'ore' anche i fogli del
    mese con la nota della riga (testo libero: i codici fiscali si salvano mascherati, anche
    nella copia per l'annullamento; un dato sanitario non si riconosce da solo, art. 12.3
    CSA, e la pagina ricorda di non scriverne) e ogni cella con ore o sigla diventa un
    giorno registrato con calcolo 'manuale', origine 'import_excel', testo originale e il
    numero dell'import (sigle: causale dell'operatore, 0 ore);
  - reimport: nel modo 'ore', dello stesso mese, si sostituiscono solo le ore importate
    (cambiate o tolte se nel file non ci sono piu'); i giorni registrati a mano diversi dal
    file si mostrano e restano, salvo la scelta "Sostituisci anche queste ore"; i giorni
    solo programmati si completano. Nel modo 'anagrafica' si aggiunge o si aggiorna solo
    l'anagrafica (l'avviso dice quando e da quale file e' stata caricata l'ultima volta);
  - annulla import (`POST /api/napoli/import/<id>/annulla`, e Ctrl+Z subito dopo:
    `napoli_annullamenti` ha solo `{"versione": 1, "import_id": n}` e `napoli_db.annulla`
    passa a `import_napoli.annulla_import`; nella pagina e nei messaggi «Annulla il
    caricamento» per l'anagrafica, «Annulla l'import» per le ore): solo l'ultimo import del lotto, mese aperto,
    niente di quello che l'import ha scritto cambiato a mano dopo (409
    `IMPORT_CAMBIATO_DOPO`: giorni dell'import, campi cambiati dall'import confrontati con i
    valori di dopo, grafie delle qualifiche create confrontate con la figura scelta); copia
    di sicurezza, poi in una transazione si tolgono le righe create e tornano le righe
    cambiate o tolte (`napoli_import.sostituite_json`: id, valori di prima e di dopo; delle
    anagrafiche si cambiano solo campi vuoti, come le ore di contratto e la municipalita'
    della scuola, le date delle coppie, i PEI e i codici fiscali sbagliati corretti dal
    file, dei quali si salva solo la differenza, al piu' due caratteri e la loro posizione:
    mai un codice fiscale; il plesso di coppie e alunni spostati da un plesso senza
    municipalita', che torna con la riga intera se era stato tolto). Le righe create
    dall'import (alunni, operatori, scuole, coppie, PEI) si cancellano annullando: se una e'
    stata cambiata a mano nelle Anagrafiche dopo (`modificato_il` pieno, migrazione 5) e'
    409 `IMPORT_CAMBIATO_DOPO` (Ctrl+Z della modifica la rimette vuota e si puo' di nuovo);
    una riga aggiunta a mano e collegata a una creata dall'import (per esempio una coppia
    con un alunno del caricamento) la blocca con il vincolo delle chiavi esterne;
  - solo confronto (modo 'confronto'): differenze coppia per coppia e giorno per giorno
    con i giorni registrati, righe del file che in Assisto non ci sono e coppie solo in
    Assisto, senza scrivere;
  - elenco degli import del lotto (`GET /api/napoli/lotti/<id>/import`): modo e conteggi
    (nuovi, aggiornati, tolti: la colonna «Cosa» dice anche i dati solo aggiornati, per
    esempio le coppie dei sostituti che continuano);
  - privacy: codici fiscali solo nelle anagrafiche; mai nelle risposte (mascherati), nel
    registro attivita', in `napoli_import` (esito e registro dell'annullamento), in
    `napoli_annullamenti` o nel log.
- **Test**: `tests/test_napoli_schema.py` (migrazione su un database v1.20.1 con
  l'archivio Roma inventato confrontato con il gemello riaperto dalla versione
  vecchia; da un database gia' alla v2 con dati alla v3 e alle successive, da uno alla v3
  alla v4, da uno alla v4 alla v5, da uno alla v5 alla v6, da uno alla v6 alla v7;
  rieseguibilita', interruzione, ripristino, impronte delle migrazioni 2-7, vincoli);
  `tests/test_napoli_fattura.py` (passo 1.9: la fattura reale di giugno riprodotta da ore
  scritte nella griglia e dal totale del coordinatore, uguale alle funzioni pure; Excel riletto
  con openpyxl con gli stessi numeri; stampa A4; definitiva congelata, che non cambia con
  tariffe, CIG e modelli cambiati, e ore del periodo bloccate anche per Ctrl+Z, coordinatore,
  import, grado di scuola e alunno, scuola della coppia, date del contratto; riapertura con il
  motivo; numero gia' usato; prospetto cambiato nel frattempo; bloccanti spiegati; ritenute
  cumulate; chiusura del mese con le fatture definitive o la conferma);
  `tests/test_napoli_calcoli.py` (con soli dati inventati: le quantita' e le tariffe
  della fattura reale di giugno ricalcolate al centesimo, i due fogli firma ricostruiti
  con orari equivalenti, letture ambigue, date e orari che non esistono, precedenza
  delle causali, domeniche, regole, tariffe e contratti sovrapposti, coordinatore,
  testi congelati, bloccanti; IBAN, partita IVA, codici fiscali, euro, destinatario e
  servizio della determina); `tests/test_napoli_anagrafiche.py` (passo 1.6: elenchi uguali al
  master inventato caricato, anagrafica vuota, filtri e ricerca per codice fiscale, controlli
  lato server, PEI con le date, coppie, sostituti, subentro e chiusura, archiviazione al posto
  della cancellazione, Ctrl+Z senza dati personali e senza le note di coppie e PEI, ricerca
  sempre in POST, sostituti spostati dal subentro, coppie di persone archiviate che non si
  riaprono, annullamento del caricamento bloccato
  dalle modifiche a mano, Roma intatta con omonimi); `tests/test_napoli_coordinamento.py`
  (passo 1.8: lettura delle ore scritte, mesi e contratti fino a oggi, scrivere, cambiare,
  togliere e Ctrl+Z, mese chiuso anche per Ctrl+Z, contratto con le ore, registro senza
  nomi, riga «Coordinatore» della fattura); `tests/test_napoli_presenze_api.py` (passo 1.7:
  caselle, sigle, A, note e "1,30" confrontati con le funzioni pure, compresi i casi della
  tabella §5.2; totali, VERIFICA con i colori e credito/debito della griglia uguali a
  `napoli_calcoli` ricaricando la pagina; giorni futuri, fuori dalle date e non di servizio;
  mese chiuso anche per Ctrl+Z, chiusura e riapertura con il motivo, indipendente da quello di
  Roma; Ctrl+Z solo di Napoli e senza le descrizioni libere; dettaglio della coppia; codici
  fiscali mascherati; la parte della nota tolta scrivendo nella casella; festivita' tolte dalle
  previste e avviso delle vacanze; l'ultimo giorno del mese; 330 coppie in meno di 2 secondi;
  la pagina eseguita in node con un DOM finto sulle risposte vere del server: la nota del
  giorno su una casella da sistemare, la selezione subito, le caselle da correggere uscendo, il
  fuoco delle domande, lo stato corto della testata); `tests/test_napoli_impostazioni.py` (procedura guidata,
  controlli lato server, sovrapposizioni, IBAN mascherato, Ctrl+Z separato, Roma intatta,
  voce di menu marcata); `tests/test_napoli_import.py` e `tests/test_napoli_privacy.py`
  (passi 1.4-1.5, sul master inventato di `tests/napoli_sintetico.py`, generato durante
  i test: 41 righe, 1.554 ore, codici fiscali con il comune Z999; l'anagrafica senza ore
  (modo predefinito, senza scritture nell'anteprima, non bloccata dalle celle sbagliate,
  le stesse coppie dell'import delle ore, reimport e annullamento, conferma solo nel modo
  dell'anteprima), gradi e conferme solo avvisi senza niente da cambiare, dati
  dell'import cambiati a mano che impediscono di annullare, nota senza codici fiscali;
  totali per figura,
  VERIFICA ignorata, ore da confermare (scelta obbligatoria), grado, plessi, sostituti e
  subentro, reimport, ore scritte a mano, annullamento anche con Ctrl+Z, solo confronto,
  mese chiuso, errori del file, copia di sicurezza, Roma intatta con alunni omonimi; il
  mese dopo (aprile, stesse righe: `napoli_sintetico.genera(anno=, mese=)`): coppie che
  continuano, municipalita' diversa da Assisto o mancante, codici fiscali corretti di
  operatori e alunni senza doppioni, omonimi, reimport senza una riga, file di un mese
  precedente da confermare; la municipalita' mancante di una scuola con piu' plessi da
  scegliere (mai un plesso senza municipalita' in piu'), le coppie di un plesso senza
  municipalita' che passano al plesso del file, quel plesso che prende la municipalita' o
  si toglie, e l'annullamento che rimette tutto; nessun codice
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

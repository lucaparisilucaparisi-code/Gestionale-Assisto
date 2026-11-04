"""Schema della sezione Napoli: tabelle napoli_* e valori iniziali.

Solo DDL: il modulo non importa database (niente import circolari) e nomina
soltanto tabelle napoli_* (controllo statico in tests/test_separazione_napoli.py).
database.py registra le funzioni nel suo runner delle migrazioni (MIGRAZIONI),
che le esegue una volta sola, in ordine, e poi imposta PRAGMA user_version:

- crea_v2 (fase 1): lotti, anagrafiche (scuole, alunni, operatori), PEI per
  figura, coppie operatore-alunno, contratti applicativi, tariffe e regole con
  data, calendario, orari settimanali, fogli firma, import del master, presenze
  (unica fonte delle ore), ore del coordinatore, mesi chiusi per lotto, prospetti
  fattura congelati, annullamenti (Ctrl+Z) delle pagine Napoli.

Regole dello schema:
- Roma non cambia: nessuna tabella di Roma viene toccata e nessuna chiave esterna
  punta a tabelle di Roma (anche alunni, operatori, scuole e lotti sono qui);
- ogni funzione si puo' rieseguire senza danni (CREATE ... IF NOT EXISTS,
  INSERT OR IGNORE) e lavora in un'unica transazione, che il runner conferma
  insieme al nuovo user_version: se qualcosa va storto non resta nulla a meta';
- ore delle presenze in minuti interi, importi e tariffe in centesimi, ore del
  coordinatore in centesimi di ora; date 'AAAA-MM-GG', orari 'HH:MM';
- tariffe sempre IVA esclusa (ritenuta, IVA e split payment sono regole con data);
- valori che cambieranno nelle fasi successive (causale, trattamento) non hanno
  CHECK: SQLite non permette di cambiarli dopo, li controlla il codice Python;
- la municipalita' e' quella della scuola (del plesso), non dell'alunno: lo stesso
  codice meccanografico in due municipalita' sono due plessi (due righe).
"""

# Figure professionali del capitolato: (codice, descrizione, ordine, ore_di_lotto).
# ore_di_lotto = 1: ore non legate alle coppie operatore-alunno (il coordinatore,
# fatturato a ore per lotto, grado e contratto applicativo).
FIGURE = (
    ('ASACOM', "Assistente all'autonomia e alla comunicazione", 1, 0),
    ('EDUCATORE', 'Educatore professionale', 2, 0),
    ('LIS', 'Interprete LIS', 3, 0),
    ('TIFLOLOGO', 'Tiflologo', 4, 0),
    ('PSICOLOGO', 'Psicologo', 5, 0),
    ('COORDINATORE', 'Coordinatore', 6, 1),
)

# Grafie della qualifica viste nel foglio master -> figura (origine 'sistema').
# Le scelte confermate dall'utente nell'anteprima dell'import si aggiungono con
# origine 'utente'.
ALIAS_QUALIFICHE = (
    ('ASACOM', 'ASACOM'),
    ('ASACM', 'ASACOM'),
    ('EDUCATORE PROFESSIONALE', 'EDUCATORE'),
    ('EDUCATRICE PROFESSIONALE', 'EDUCATORE'),
    ('EDUCATICE PROFESSIONALE', 'EDUCATORE'),
    ('EDUCATORE', 'EDUCATORE'),
    ('EDUCATRICE', 'EDUCATORE'),
    ('PSICOLOGO', 'PSICOLOGO'),
    ('PSICOLOGA', 'PSICOLOGO'),
    ('TIFLOLOGO', 'TIFLOLOGO'),
    ('TIFLOLOGA', 'TIFLOLOGO'),
    ('INTERPRETE LIS', 'LIS'),
    ('COORDINATORE', 'COORDINATORE'),
    ('COORDINATRICE', 'COORDINATORE'),
)

DDL_V2 = (
    # Dati della cooperativa per i prospetti (denominazione, CF/P.IVA, IBAN):
    # li inserisce l'utente, mai nel codice.
    '''CREATE TABLE IF NOT EXISTS napoli_impostazioni (
        chiave TEXT PRIMARY KEY,
        valore TEXT
    )''',

    # Il lotto e' la "commessa di Napoli" vista dall'utente.
    '''CREATE TABLE IF NOT EXISTS napoli_lotti (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL UNIQUE,
        numero_lotto INTEGER NOT NULL UNIQUE CHECK (numero_lotto BETWEEN 1 AND 5),
        municipalita TEXT NOT NULL,                 -- municipalita' del lotto, es. "1 e 2"
        colore TEXT,
        attivo INTEGER NOT NULL DEFAULT 1,
        cig TEXT,
        cup TEXT,
        oggetto_fattura TEXT,                       -- modello con {lotto} {grado} {dal} {al} {mese} {anno} {contratto}
        nota_fattura TEXT,                          -- modello con {dd_numero} {dd_data} + testo dello split payment
        destinatario TEXT,                          -- ente destinatario (testo inserito dall'utente)
        codice_univoco_ufficio TEXT,
        riferimento_amministrativo TEXT,
        intestazione_foglio TEXT,                   -- titolo del foglio firma
        logo_file TEXT,                             -- stemma caricato dall'utente, mai nel repository
        data_creazione TEXT NOT NULL
    )''',

    '''CREATE TABLE IF NOT EXISTS napoli_figure (
        codice TEXT PRIMARY KEY,
        descrizione TEXT NOT NULL,
        ordine INTEGER NOT NULL,
        ore_di_lotto INTEGER NOT NULL DEFAULT 0
    )''',

    '''CREATE TABLE IF NOT EXISTS napoli_alias_qualifiche (
        testo TEXT PRIMARY KEY,
        figura TEXT NOT NULL REFERENCES napoli_figure(codice),
        origine TEXT NOT NULL DEFAULT 'sistema' CHECK (origine IN ('sistema', 'utente'))
    )''',

    # Un plesso: lo stesso codice meccanografico in due municipalita' sono due righe.
    '''CREATE TABLE IF NOT EXISTS napoli_scuole (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lotto_id INTEGER NOT NULL REFERENCES napoli_lotti(id),
        nome TEXT NOT NULL,
        codice_meccanografico TEXT,
        grado TEXT CHECK (grado IN ('inferiore', 'superiore', 'misto')),   -- NULL = da decidere (blocca la fattura)
        municipalita INTEGER,
        attiva INTEGER NOT NULL DEFAULT 1,
        data_inserimento TEXT NOT NULL
    )''',
    '''CREATE UNIQUE INDEX IF NOT EXISTS ux_napoli_scuole_mecc
        ON napoli_scuole(lotto_id, codice_meccanografico, COALESCE(municipalita, 0))
        WHERE codice_meccanografico IS NOT NULL''',

    '''CREATE TABLE IF NOT EXISTS napoli_alunni (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lotto_id INTEGER NOT NULL REFERENCES napoli_lotti(id),
        cognome TEXT NOT NULL,
        nome TEXT NOT NULL,
        codice_fiscale TEXT NOT NULL UNIQUE CHECK (length(codice_fiscale) = 16),
        scuola_id INTEGER REFERENCES napoli_scuole(id),     -- scuola attuale (quella del foglio sta nella coppia)
        grado TEXT CHECK (grado IN ('inferiore', 'superiore')),   -- NULL = quello della scuola
        esami INTEGER NOT NULL DEFAULT 0,                   -- servizio fino alla fine degli esami (luglio)
        attivo INTEGER NOT NULL DEFAULT 1,
        archiviato_dal TEXT,
        note TEXT,
        data_inserimento TEXT NOT NULL
    )''',
    'CREATE INDEX IF NOT EXISTS ix_napoli_alunni_scuola ON napoli_alunni(scuola_id)',

    '''CREATE TABLE IF NOT EXISTS napoli_operatori (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cognome TEXT NOT NULL,
        nome TEXT NOT NULL,
        codice_fiscale TEXT,
        cf_valido INTEGER NOT NULL DEFAULT 1,               -- nel master non tutti i CF sono validi
        figura TEXT NOT NULL REFERENCES napoli_figure(codice),
        livello_ccnl TEXT,
        qualifica_originale TEXT,
        ore_contratto REAL,
        attivo INTEGER NOT NULL DEFAULT 1,
        note TEXT,
        data_inserimento TEXT NOT NULL
    )''',
    'CREATE INDEX IF NOT EXISTS ix_napoli_operatori_cf ON napoli_operatori(codice_fiscale)',

    # Fabbisogno settimanale per alunno e figura (ore da progetto del master).
    '''CREATE TABLE IF NOT EXISTS napoli_pei (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alunno_id INTEGER NOT NULL REFERENCES napoli_alunni(id),
        figura TEXT NOT NULL REFERENCES napoli_figure(codice),
        ore_settimanali REAL NOT NULL CHECK (ore_settimanali > 0 AND ore_settimanali <= 40),
        valido_da TEXT NOT NULL,
        valido_a TEXT,
        stato TEXT NOT NULL DEFAULT 'definitivo' CHECK (stato IN ('provvisorio', 'definitivo', 'sospeso')),
        fonte TEXT,
        data_inserimento TEXT NOT NULL,
        UNIQUE (alunno_id, figura, valido_da),
        CHECK (valido_a IS NULL OR valido_da <= valido_a)
    )''',

    # Una riga del master = una coppia operatore-alunno = un foglio firma al mese.
    '''CREATE TABLE IF NOT EXISTS napoli_coppie (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lotto_id INTEGER NOT NULL REFERENCES napoli_lotti(id),
        alunno_id INTEGER NOT NULL REFERENCES napoli_alunni(id),
        operatore_id INTEGER NOT NULL REFERENCES napoli_operatori(id),
        scuola_id INTEGER NOT NULL REFERENCES napoli_scuole(id),
        figura TEXT NOT NULL REFERENCES napoli_figure(codice),
        ruolo TEXT NOT NULL DEFAULT 'titolare' CHECK (ruolo IN ('titolare', 'sostituto')),
        titolare_coppia_id INTEGER REFERENCES napoli_coppie(id),
        ore_settimanali REAL,                               -- quota della coppia; NULL = tutto il PEI della figura
        valido_da TEXT NOT NULL,
        valido_a TEXT,
        note TEXT,
        origine TEXT,
        data_inserimento TEXT NOT NULL,
        CHECK (valido_a IS NULL OR valido_da <= valido_a)
    )''',
    'CREATE INDEX IF NOT EXISTS ix_napoli_coppie_lotto ON napoli_coppie(lotto_id, valido_da, valido_a)',
    'CREATE INDEX IF NOT EXISTS ix_napoli_coppie_alunno ON napoli_coppie(alunno_id)',
    'CREATE INDEX IF NOT EXISTS ix_napoli_coppie_operatore ON napoli_coppie(operatore_id)',

    # Contratti applicativi (es. "XI"): la fattura si fa per lotto, grado, contratto e periodo.
    '''CREATE TABLE IF NOT EXISTS napoli_contratti (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lotto_id INTEGER NOT NULL REFERENCES napoli_lotti(id),
        grado TEXT CHECK (grado IN ('inferiore', 'superiore')),   -- NULL = vale per entrambi i gradi
        numero TEXT NOT NULL,
        accordo_quadro TEXT,
        repertorio TEXT,
        data_contratto TEXT,
        dd_numero TEXT,                                     -- determina di impegno
        dd_data TEXT,
        valido_da TEXT NOT NULL,
        valido_a TEXT NOT NULL,
        importo_cent INTEGER,
        note TEXT,
        data_inserimento TEXT NOT NULL,
        CHECK (valido_da <= valido_a)
    )''',
    'CREATE INDEX IF NOT EXISTS ix_napoli_contratti_lotto ON napoli_contratti(lotto_id, valido_da)',

    # Tariffe orarie IVA esclusa, con validita'.
    '''CREATE TABLE IF NOT EXISTS napoli_tariffe (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lotto_id INTEGER NOT NULL REFERENCES napoli_lotti(id),
        figura TEXT NOT NULL REFERENCES napoli_figure(codice),
        livello_ccnl TEXT,                                  -- NULL = tutti i livelli
        tariffa_cent INTEGER NOT NULL CHECK (tariffa_cent > 0),
        valido_da TEXT NOT NULL,
        valido_a TEXT,
        fonte TEXT,
        data_inserimento TEXT NOT NULL,
        CHECK (valido_a IS NULL OR valido_da <= valido_a)
    )''',
    '''CREATE UNIQUE INDEX IF NOT EXISTS ux_napoli_tariffe
        ON napoli_tariffe(lotto_id, figura, COALESCE(livello_ccnl, ''), valido_da)''',

    # Eccezioni con data ai valori predefiniti delle regole (valore in JSON).
    '''CREATE TABLE IF NOT EXISTS napoli_regole (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lotto_id INTEGER REFERENCES napoli_lotti(id),       -- NULL = tutti i lotti
        chiave TEXT NOT NULL,
        valore TEXT NOT NULL,
        valido_da TEXT NOT NULL,
        valido_a TEXT,
        fonte TEXT,
        data_inserimento TEXT NOT NULL,
        CHECK (valido_a IS NULL OR valido_da <= valido_a)
    )''',
    'CREATE UNIQUE INDEX IF NOT EXISTS ux_napoli_regole ON napoli_regole(COALESCE(lotto_id, 0), chiave, valido_da)',

    # Chiusure ed eventi per data: diventano le note del foglio firma.
    '''CREATE TABLE IF NOT EXISTS napoli_calendario (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lotto_id INTEGER REFERENCES napoli_lotti(id),       -- NULL = tutti i lotti
        scuola_id INTEGER REFERENCES napoli_scuole(id),     -- NULL = tutte le scuole
        data TEXT NOT NULL,
        tipo TEXT NOT NULL CHECK (tipo IN ('chiusura', 'evento')),
        descrizione TEXT NOT NULL
    )''',
    '''CREATE UNIQUE INDEX IF NOT EXISTS ux_napoli_cal
        ON napoli_calendario(COALESCE(lotto_id, 0), COALESCE(scuola_id, 0), data)''',

    # Programmazione settimanale della coppia: due fasce nello stesso giorno = due righe.
    '''CREATE TABLE IF NOT EXISTS napoli_orari (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        coppia_id INTEGER NOT NULL REFERENCES napoli_coppie(id) ON DELETE CASCADE,
        giorno INTEGER NOT NULL CHECK (giorno BETWEEN 0 AND 5),   -- lunedi'..sabato
        ora_inizio TEXT NOT NULL CHECK (ora_inizio GLOB '[0-2][0-9]:[0-5][0-9]'),
        ora_fine TEXT NOT NULL CHECK (ora_fine GLOB '[0-2][0-9]:[0-5][0-9]'),
        valido_da TEXT,
        valido_a TEXT,
        data_inserimento TEXT NOT NULL,
        CHECK (ora_inizio < ora_fine),
        CHECK (valido_a IS NULL OR valido_da IS NULL OR valido_da <= valido_a)
    )''',
    'CREATE INDEX IF NOT EXISTS ix_napoli_orari_coppia ON napoli_orari(coppia_id)',

    # Coppia + mese = un foglio firma.
    '''CREATE TABLE IF NOT EXISTS napoli_fogli (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        coppia_id INTEGER NOT NULL REFERENCES napoli_coppie(id),
        anno INTEGER NOT NULL,
        mese INTEGER NOT NULL CHECK (mese BETWEEN 1 AND 12),
        stato TEXT NOT NULL DEFAULT 'preparato'
            CHECK (stato IN ('preparato', 'stampato', 'ricevuto', 'registrato', 'verificato')),
        totale_scritto_min INTEGER,                         -- totale scritto a mano, per il confronto
        note TEXT,                                          -- colonna NOTE del master
        data_ricezione TEXT,
        UNIQUE (coppia_id, anno, mese)
    )''',

    '''CREATE TABLE IF NOT EXISTS napoli_import (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lotto_id INTEGER NOT NULL REFERENCES napoli_lotti(id),
        anno INTEGER,
        mese INTEGER CHECK (mese BETWEEN 1 AND 12),
        nome_file TEXT,
        sha256 TEXT,
        n_righe INTEGER,
        esito_json TEXT,                                    -- solo conteggi e id: mai nomi o codici fiscali
        sostituite_json TEXT,                               -- righe sostituite, per "Annulla import"
        annullato INTEGER NOT NULL DEFAULT 0,
        data TEXT NOT NULL
    )''',

    # UNICA fonte delle ore di Napoli: coppia x giorno.
    '''CREATE TABLE IF NOT EXISTS napoli_presenze (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        coppia_id INTEGER NOT NULL REFERENCES napoli_coppie(id),
        lotto_id INTEGER NOT NULL REFERENCES napoli_lotti(id),   -- copiato dalla coppia
        data TEXT NOT NULL CHECK (data GLOB '[12][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]'),
        figura TEXT NOT NULL,                               -- copiata dalla coppia
        stato TEXT NOT NULL DEFAULT 'programmato' CHECK (stato IN ('programmato', 'registrato')),
        minuti_programmati INTEGER NOT NULL DEFAULT 0 CHECK (minuti_programmati BETWEEN 0 AND 720),
        minuti_svolti INTEGER CHECK (minuti_svolti BETWEEN 0 AND 720),         -- NULL = non noto (import)
        minuti_extra INTEGER NOT NULL DEFAULT 0 CHECK (minuti_extra >= 0),     -- parte di "svolti" in recupero
        tipo_extra TEXT CHECK (tipo_extra IN ('recupero', 'uso_C')),
        minuti_riconosciuti INTEGER NOT NULL DEFAULT 0 CHECK (minuti_riconosciuti BETWEEN 0 AND 720),
        calcolo TEXT NOT NULL DEFAULT 'auto' CHECK (calcolo IN ('auto', 'manuale')),
        causale TEXT,
        trattamento TEXT,
        sigla TEXT,
        nota TEXT,
        testo_originale TEXT,
        origine TEXT NOT NULL CHECK (origine IN ('programmazione', 'foglio', 'griglia', 'import_excel', 'piattaforma')),
        import_id INTEGER REFERENCES napoli_import(id),
        modificato_il TEXT NOT NULL,
        UNIQUE (coppia_id, data)
    )''',
    'CREATE INDEX IF NOT EXISTS ix_napoli_presenze_mese ON napoli_presenze(lotto_id, data)',
    'CREATE INDEX IF NOT EXISTS ix_napoli_presenze_import ON napoli_presenze(import_id)',

    # Fasce P (programmate) ed E (effettive) del giorno.
    '''CREATE TABLE IF NOT EXISTS napoli_presenze_fasce (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        presenza_id INTEGER NOT NULL REFERENCES napoli_presenze(id) ON DELETE CASCADE,
        tipo TEXT NOT NULL CHECK (tipo IN ('P', 'E')),
        ordine INTEGER NOT NULL,
        ora_inizio TEXT NOT NULL CHECK (ora_inizio GLOB '[0-2][0-9]:[0-5][0-9]'),
        ora_fine TEXT NOT NULL CHECK (ora_fine GLOB '[0-2][0-9]:[0-5][0-9]'),
        UNIQUE (presenza_id, tipo, ordine),
        CHECK (ora_inizio < ora_fine)
    )''',

    # Ore del coordinatore, fatturate a ore (71,55 h = 7155).
    '''CREATE TABLE IF NOT EXISTS napoli_coordinamento (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lotto_id INTEGER NOT NULL REFERENCES napoli_lotti(id),
        grado TEXT NOT NULL CHECK (grado IN ('inferiore', 'superiore')),
        contratto_id INTEGER NOT NULL REFERENCES napoli_contratti(id),
        anno INTEGER NOT NULL,
        mese INTEGER NOT NULL CHECK (mese BETWEEN 1 AND 12),
        operatore_id INTEGER NOT NULL REFERENCES napoli_operatori(id),
        ore_cent INTEGER NOT NULL CHECK (ore_cent >= 0),
        nota TEXT,
        UNIQUE (lotto_id, grado, contratto_id, anno, mese, operatore_id)
    )''',

    # Chiusura del mese per lotto, separata dalla chiusura del mese di Roma.
    '''CREATE TABLE IF NOT EXISTS napoli_mesi_chiusi (
        lotto_id INTEGER NOT NULL REFERENCES napoli_lotti(id),
        anno INTEGER NOT NULL,
        mese INTEGER NOT NULL CHECK (mese BETWEEN 1 AND 12),
        data_chiusura TEXT NOT NULL,
        nota TEXT,
        PRIMARY KEY (lotto_id, anno, mese)
    )''',

    # Prospetto fattura congelato: righe per figura e tariffa, SENZA nominativi.
    '''CREATE TABLE IF NOT EXISTS napoli_fatture (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lotto_id INTEGER NOT NULL REFERENCES napoli_lotti(id),
        grado TEXT NOT NULL CHECK (grado IN ('inferiore', 'superiore')),
        contratto_id INTEGER NOT NULL REFERENCES napoli_contratti(id),
        periodo_dal TEXT NOT NULL,
        periodo_al TEXT NOT NULL,
        numero TEXT,                                        -- della fattura emessa dal programma contabile
        data TEXT,
        righe_json TEXT NOT NULL,
        somma_righe_cent INTEGER NOT NULL,
        ritenuta_cent INTEGER NOT NULL,
        imponibile_cent INTEGER NOT NULL,
        iva_cent INTEGER NOT NULL,
        totale_cent INTEGER NOT NULL,
        da_pagare_cent INTEGER NOT NULL,
        stato TEXT NOT NULL DEFAULT 'bozza' CHECK (stato IN ('bozza', 'definitiva')),
        data_creazione TEXT NOT NULL,
        UNIQUE (lotto_id, grado, contratto_id, periodo_dal),
        CHECK (periodo_dal <= periodo_al)
    )''',

    # Ctrl+Z delle pagine Napoli, separato da quello di Roma.
    '''CREATE TABLE IF NOT EXISTS napoli_annullamenti (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        tipo TEXT NOT NULL,
        descrizione TEXT NOT NULL,                          -- senza nominativi
        dati TEXT NOT NULL                                  -- JSON con id e valori precedenti
    )''',
)


def crea_v2(conn):
    """Migrazione 2 (fase 1): crea le tabelle napoli_* e i valori iniziali.

    Rieseguibile: non tocca tabelle o righe che esistono gia'. Apre la transazione
    se non c'e' (anche il DDL ne fa parte); la conferma chi chiama, il runner di
    database.py dopo aver impostato user_version."""
    if not conn.in_transaction:
        conn.execute('BEGIN')
    for istruzione in DDL_V2:
        conn.execute(istruzione)
    conn.executemany('INSERT OR IGNORE INTO napoli_figure (codice, descrizione, ordine, ore_di_lotto) '
                     'VALUES (?, ?, ?, ?)', FIGURE)
    conn.executemany('INSERT OR IGNORE INTO napoli_alias_qualifiche (testo, figura) VALUES (?, ?)',
                     ALIAS_QUALIFICHE)

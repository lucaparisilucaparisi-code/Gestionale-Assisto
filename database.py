import sqlite3
import os
import re
import json
from datetime import datetime

import config

DATABASE_PATH = config.DATABASE_PATH
logger = config.setup_logging()

def _connect():
    """Factory UNICA di connessione SQLite con impostazioni sicure comuni.

    - row_factory=Row per accesso per nome colonna;
    - PRAGMA foreign_keys=ON: in SQLite l'enforcement e' OFF di default, quindi
      le FOREIGN KEY ... ON DELETE CASCADE dichiarate non verrebbero applicate
      (lasciando righe orfane, es. in sostituzioni alla cancellazione di un turno);
    - busy_timeout: attende invece di fallire subito con 'database is locked';
    - journal_mode=WAL: piu' robusto a interruzioni e a letture/scritture concorrenti.
    """
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA busy_timeout = 5000')
    conn.execute('PRAGMA journal_mode = WAL')
    return conn


class DBConnection:
    """Context manager per connessioni database sicure"""
    def __init__(self):
        self.conn = None

    def __enter__(self):
        self.conn = _connect()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            if exc_type is None:
                self.conn.commit()
            else:
                # Su errore annulla esplicitamente la transazione parziale
                self.conn.rollback()
            self.conn.close()
        return False


def get_db():
    """Ottiene connessione al database (legacy, preferire DBConnection context manager)"""
    return _connect()


def get_db_context():
    """Restituisce il context manager per connessioni sicure"""
    return DBConnection()

def init_db():
    """Inizializza il database con le tabelle necessarie"""
    conn = get_db()
    cursor = conn.cursor()

    # Tabella Commesse (ora dinamica)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS commesse (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT UNIQUE NOT NULL,
            descrizione TEXT,
            colore TEXT DEFAULT '#6366f1',
            attiva INTEGER DEFAULT 1,
            data_creazione TEXT NOT NULL
        )
    ''')

    # Migrazione: aggiungi colonne mancanti alla tabella commesse
    try:
        cursor.execute("ALTER TABLE commesse ADD COLUMN attiva INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass  # Colonna già esistente

    try:
        cursor.execute("ALTER TABLE commesse ADD COLUMN colore TEXT DEFAULT '#6366f1'")
    except sqlite3.OperationalError:
        pass  # Colonna già esistente

    try:
        cursor.execute("ALTER TABLE commesse ADD COLUMN descrizione TEXT")
    except sqlite3.OperationalError:
        pass  # Colonna già esistente

    try:
        cursor.execute("ALTER TABLE commesse ADD COLUMN data_creazione TEXT")
    except sqlite3.OperationalError:
        pass  # Colonna già esistente

    # Aggiorna valori NULL
    cursor.execute("UPDATE commesse SET attiva = 1 WHERE attiva IS NULL")
    cursor.execute("UPDATE commesse SET colore = '#6366f1' WHERE colore IS NULL")
    cursor.execute("UPDATE commesse SET data_creazione = ? WHERE data_creazione IS NULL", (datetime.now().isoformat(),))

    # Inserisce le commesse predefinite se non esistono
    cursor.execute("SELECT COUNT(*) FROM commesse")
    if cursor.fetchone()[0] == 0:
        now = datetime.now().isoformat()
        cursor.execute("INSERT INTO commesse (nome, descrizione, colore, data_creazione) VALUES (?, ?, ?, ?)",
                      ('OEPAC IV', 'Commessa OEPAC IV Municipio', '#6366f1', now))
        cursor.execute("INSERT INTO commesse (nome, descrizione, colore, data_creazione) VALUES (?, ?, ?, ?)",
                      ('OEPAC V', 'Commessa OEPAC V Municipio', '#8b5cf6', now))

    # Tabella Scuole
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scuole (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commessa_id INTEGER NOT NULL,
            nome_completo TEXT NOT NULL,
            FOREIGN KEY (commessa_id) REFERENCES commesse(id),
            UNIQUE(commessa_id, nome_completo)
        )
    ''')

    # Tabella Utenti (con lista_attesa)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS utenti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scuola_id INTEGER NOT NULL,
            nome TEXT NOT NULL,
            cognome TEXT NOT NULL,
            nome_puntato TEXT NOT NULL,
            monte_ore_settimanale REAL NOT NULL,
            lista_attesa TEXT,
            attivo INTEGER DEFAULT 1,
            data_inserimento TEXT NOT NULL,
            FOREIGN KEY (scuola_id) REFERENCES scuole(id)
        )
    ''')

    # Migrazione: aggiungi colonna lista_attesa a utenti se non esiste
    try:
        cursor.execute("ALTER TABLE utenti ADD COLUMN lista_attesa TEXT")
    except sqlite3.OperationalError:
        pass  # Colonna già esistente

    # Migrazione: aggiungi colonne data_inizio e data_fine per periodo di validità
    try:
        cursor.execute("ALTER TABLE utenti ADD COLUMN data_inizio TEXT")
    except sqlite3.OperationalError:
        pass  # Colonna già esistente

    try:
        cursor.execute("ALTER TABLE utenti ADD COLUMN data_fine TEXT")
    except sqlite3.OperationalError:
        pass  # Colonna già esistente

    # Migrazione: aggiungi colonne per budget ore utente
    try:
        cursor.execute("ALTER TABLE utenti ADD COLUMN budget_ore_mensile REAL")
    except sqlite3.OperationalError:
        pass  # Colonna già esistente

    try:
        cursor.execute("ALTER TABLE utenti ADD COLUMN budget_ore_annuale REAL")
    except sqlite3.OperationalError:
        pass  # Colonna già esistente

    try:
        cursor.execute("ALTER TABLE utenti ADD COLUMN stato TEXT DEFAULT 'attivo'")
    except sqlite3.OperationalError:
        pass  # Colonna già esistente

    # Tabella Variazioni Monte Ore (incrementi/decrementi nel tempo)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS variazioni_monte_ore (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            utente_id INTEGER NOT NULL,
            monte_ore REAL NOT NULL,
            mese_inizio TEXT NOT NULL,
            nota TEXT,
            data_inserimento TEXT NOT NULL,
            FOREIGN KEY (utente_id) REFERENCES utenti(id) ON DELETE CASCADE
        )
    ''')

    # Tabella Rendicontazione Mensile
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rendicontazione (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            utente_id INTEGER NOT NULL,
            anno INTEGER NOT NULL,
            mese INTEGER NOT NULL,
            ore_lavorate_60 REAL DEFAULT 0,
            pasti INTEGER DEFAULT 0,
            giorni_lavorativi INTEGER NOT NULL,
            note TEXT,
            data_inserimento TEXT NOT NULL,
            data_modifica TEXT,
            FOREIGN KEY (utente_id) REFERENCES utenti(id),
            UNIQUE(utente_id, anno, mese)
        )
    ''')

    # Tabella Calendario Scolastico (giorni lavorativi per mese)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS calendario_scolastico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            anno_scolastico TEXT NOT NULL,
            mese INTEGER NOT NULL,
            anno INTEGER NOT NULL,
            giorni_lavorativi INTEGER NOT NULL,
            UNIQUE(anno_scolastico, mese, anno)
        )
    ''')

    # Migrazione: giorni lavorativi dedicati al non-infanzia (tipicamente solo giugno).
    # NULL = usa lo stesso valore di giorni_lavorativi (retrocompatibile).
    try:
        cursor.execute("ALTER TABLE calendario_scolastico ADD COLUMN giorni_lavorativi_altri INTEGER")
    except sqlite3.OperationalError:
        pass  # Colonna già esistente

    # Tabella Audit Trail
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            azione TEXT NOT NULL,
            entita TEXT NOT NULL,
            entita_id INTEGER,
            dettagli TEXT,
            dati_precedenti TEXT,
            dati_nuovi TEXT
        )
    ''')

    # Tabella Undo Actions (persistente)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS undo_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            action_type TEXT NOT NULL,
            data TEXT NOT NULL
        )
    ''')

    # ==================== NUOVE TABELLE FUNZIONALITA' ====================

    # Tabella Documenti Utente
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS documenti_utente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            utente_id INTEGER NOT NULL,
            nome_file TEXT NOT NULL,
            nome_originale TEXT NOT NULL,
            tipo_documento TEXT NOT NULL,
            descrizione TEXT,
            data_scadenza TEXT,
            data_caricamento TEXT NOT NULL,
            dimensione INTEGER,
            FOREIGN KEY (utente_id) REFERENCES utenti(id)
        )
    ''')

    # Tabella Note Utente
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS note_utente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            utente_id INTEGER NOT NULL,
            tipo TEXT DEFAULT 'generale',
            anno INTEGER,
            mese INTEGER,
            contenuto TEXT NOT NULL,
            priorita TEXT DEFAULT 'normale',
            data_creazione TEXT NOT NULL,
            data_modifica TEXT,
            FOREIGN KEY (utente_id) REFERENCES utenti(id)
        )
    ''')

    # Tabella Assenze
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS assenze (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            utente_id INTEGER NOT NULL,
            data_inizio TEXT NOT NULL,
            data_fine TEXT,
            tipo TEXT NOT NULL,
            motivazione TEXT,
            note TEXT,
            data_registrazione TEXT NOT NULL,
            FOREIGN KEY (utente_id) REFERENCES utenti(id)
        )
    ''')

    # Tabella Notifiche/Promemoria
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifiche (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,
            titolo TEXT NOT NULL,
            messaggio TEXT,
            entita TEXT,
            entita_id INTEGER,
            letta INTEGER DEFAULT 0,
            archiviata INTEGER DEFAULT 0,
            priorita TEXT DEFAULT 'normale',
            data_creazione TEXT NOT NULL,
            data_scadenza TEXT
        )
    ''')

    # Tabella Widget Dashboard (preferenze utente)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS dashboard_widgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            widget_id TEXT UNIQUE NOT NULL,
            titolo TEXT NOT NULL,
            tipo TEXT NOT NULL,
            attivo INTEGER DEFAULT 1,
            ordine INTEGER DEFAULT 0,
            configurazione TEXT
        )
    ''')

    # ==================== TABELLE REPORTISTICA LOCALE ====================

    # Tabella Determine Dirigenziali (DD)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS determine_dirigenziali (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commessa_id INTEGER NOT NULL,
            anno_scolastico TEXT NOT NULL,
            mese_inizio INTEGER NOT NULL,
            anno_inizio INTEGER NOT NULL,
            ore_settimanali REAL NOT NULL,
            ore_annuali REAL NOT NULL,
            numero_dd TEXT,
            data_dd TEXT,
            note TEXT,
            data_inserimento TEXT NOT NULL,
            FOREIGN KEY (commessa_id) REFERENCES commesse(id)
        )
    ''')

    # Tabella Recuperi Ore
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS recuperi_ore (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commessa_id INTEGER NOT NULL,
            anno_scolastico TEXT NOT NULL,
            mese INTEGER NOT NULL,
            anno INTEGER NOT NULL,
            ore_recupero REAL NOT NULL,
            note TEXT,
            data_inserimento TEXT NOT NULL,
            FOREIGN KEY (commessa_id) REFERENCES commesse(id)
        )
    ''')

    # Tabella Override Progettato (per modifiche manuali al progettato mensile)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS progettato_override (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commessa_id INTEGER NOT NULL,
            anno_scolastico TEXT NOT NULL,
            mese INTEGER NOT NULL,
            anno INTEGER NOT NULL,
            ore_progettate REAL NOT NULL,
            data_modifica TEXT NOT NULL,
            FOREIGN KEY (commessa_id) REFERENCES commesse(id),
            UNIQUE(commessa_id, anno_scolastico, mese, anno)
        )
    ''')

    # Tabella Override Report (per modifiche manuali a qualsiasi campo del report mensile)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS report_override (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commessa_id INTEGER NOT NULL,
            anno_scolastico TEXT NOT NULL,
            mese INTEGER NOT NULL,
            anno INTEGER NOT NULL,
            campo TEXT NOT NULL,
            valore REAL NOT NULL,
            data_modifica TEXT NOT NULL,
            FOREIGN KEY (commessa_id) REFERENCES commesse(id),
            UNIQUE(commessa_id, anno_scolastico, mese, anno, campo)
        )
    ''')

    # ==================== AUTENTICAZIONE (single-user) ====================
    # Tabella configurazione auth: riga unica (id=1) con credenziali utente
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS auth_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            username TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            data_creazione TEXT NOT NULL,
            ultimo_accesso TEXT,
            ultimo_accesso_metodo TEXT
        )
    ''')

    # Tabella credenziali WebAuthn (impronta/biometria) - possono essere multiple
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS webauthn_credentials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            credential_id BLOB NOT NULL UNIQUE,
            public_key BLOB NOT NULL,
            sign_count INTEGER NOT NULL DEFAULT 0,
            nome TEXT NOT NULL,
            transports TEXT,
            data_registrazione TEXT NOT NULL,
            ultimo_utilizzo TEXT
        )
    ''')

    # ==================== MODULO PERSONALE (dipendenti OEPAC) ====================

    # Anagrafica dipendenti (operatori OEPAC). I campi non previsti dall'Excel
    # finiscono in dati_extra (JSON) per non dover cambiare schema ad ogni import.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS dipendenti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            cognome TEXT NOT NULL,
            codice_fiscale TEXT,
            email TEXT,
            telefono TEXT,
            qualifica TEXT,
            sede TEXT,
            commessa_id INTEGER,
            ore_contrattuali_settimanali REAL,
            data_assunzione TEXT,
            data_cessazione TEXT,
            attivo INTEGER DEFAULT 1,
            note TEXT,
            dati_extra TEXT,
            data_inserimento TEXT NOT NULL,
            FOREIGN KEY (commessa_id) REFERENCES commesse(id)
        )
    ''')

    # Assegnazione assistito (utente) -> operatore (dipendente) con ore settimanali.
    # Le assegnazioni possono essere miste (piu' operatori per utente). Vincolo
    # applicativo: la somma delle ore per un utente deve eguagliare il suo monte ore.
    # valido_da / valido_a gestiscono variazioni nel tempo (NULL = sempre valida).
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS assegnazioni (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            utente_id INTEGER NOT NULL,
            dipendente_id INTEGER NOT NULL,
            ore_settimanali REAL NOT NULL DEFAULT 0,
            valido_da TEXT,
            valido_a TEXT,
            note TEXT,
            data_inserimento TEXT NOT NULL,
            FOREIGN KEY (utente_id) REFERENCES utenti(id) ON DELETE CASCADE,
            FOREIGN KEY (dipendente_id) REFERENCES dipendenti(id) ON DELETE CASCADE
        )
    ''')

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_dipendenti_attivo ON dipendenti(attivo)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_dipendenti_nome ON dipendenti(cognome, nome)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_assegnazioni_utente ON assegnazioni(utente_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_assegnazioni_dipendente ON assegnazioni(dipendente_id)')

    # Turni settimanali ricorrenti degli operatori. giorno: 0=Lun .. 6=Dom.
    # ora_inizio/ora_fine in 'HH:MM'. valido_da/valido_a (date) gestiscono le
    # variazioni nel tempo (NULL = sempre valido).
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS turni (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dipendente_id INTEGER NOT NULL,
            giorno INTEGER NOT NULL,
            ora_inizio TEXT NOT NULL,
            ora_fine TEXT NOT NULL,
            scuola_id INTEGER,
            utente_id INTEGER,
            valido_da TEXT,
            valido_a TEXT,
            note TEXT,
            data_inserimento TEXT NOT NULL,
            FOREIGN KEY (dipendente_id) REFERENCES dipendenti(id) ON DELETE CASCADE,
            FOREIGN KEY (scuola_id) REFERENCES scuole(id),
            FOREIGN KEY (utente_id) REFERENCES utenti(id)
        )
    ''')

    # Assenze degli operatori (per la gestione delle sostituzioni)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS assenze_dipendenti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dipendente_id INTEGER NOT NULL,
            data_inizio TEXT NOT NULL,
            data_fine TEXT,
            tipo TEXT,
            motivazione TEXT,
            note TEXT,
            data_registrazione TEXT NOT NULL,
            FOREIGN KEY (dipendente_id) REFERENCES dipendenti(id) ON DELETE CASCADE
        )
    ''')

    # Sostituzioni: copertura di un turno in una data specifica da parte di un
    # altro operatore (per coprire un'assenza).
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sostituzioni (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            turno_id INTEGER,
            data TEXT NOT NULL,
            assente_id INTEGER NOT NULL,
            sostituto_id INTEGER,
            assenza_id INTEGER,
            stato TEXT DEFAULT 'da_coprire',
            note TEXT,
            data_inserimento TEXT NOT NULL,
            FOREIGN KEY (turno_id) REFERENCES turni(id) ON DELETE CASCADE,
            FOREIGN KEY (assente_id) REFERENCES dipendenti(id),
            FOREIGN KEY (sostituto_id) REFERENCES dipendenti(id),
            FOREIGN KEY (assenza_id) REFERENCES assenze_dipendenti(id) ON DELETE CASCADE
        )
    ''')

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_turni_dipendente ON turni(dipendente_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_turni_giorno ON turni(giorno)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_turni_scuola ON turni(scuola_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_assenze_dip ON assenze_dipendenti(dipendente_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sostituzioni_data ON sostituzioni(data)')

    # ==================== INDICI PER PERFORMANCE ====================
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_utenti_scuola ON utenti(scuola_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_utenti_attivo ON utenti(attivo)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_utenti_nome_cognome ON utenti(nome, cognome)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_scuole_commessa ON scuole(commessa_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_rend_utente ON rendicontazione(utente_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_rend_anno_mese ON rendicontazione(anno, mese)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_rend_utente_anno_mese ON rendicontazione(utente_id, anno, mese)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_calendario_as_mese ON calendario_scolastico(anno_scolastico, mese, anno)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_audit_entita ON audit_log(entita)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_commesse_attiva ON commesse(attiva)')

    # Indici per nuove tabelle
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_documenti_utente ON documenti_utente(utente_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_documenti_scadenza ON documenti_utente(data_scadenza)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_note_utente ON note_utente(utente_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_note_tipo ON note_utente(tipo)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_assenze_utente ON assenze(utente_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_assenze_data ON assenze(data_inizio)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_variazioni_utente ON variazioni_monte_ore(utente_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_variazioni_utente_mese ON variazioni_monte_ore(utente_id, mese_inizio)')

    # Migrazione: rimuovi tabelle tipologie intervento (funzionalita' eliminata)
    try:
        cursor.execute('DROP TABLE IF EXISTS ore_tipologia')
        cursor.execute('DROP TABLE IF EXISTS tipologie_intervento')
    except sqlite3.OperationalError:
        pass

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_notifiche_letta ON notifiche(letta)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_notifiche_tipo ON notifiche(tipo)')

    # Indici per reportistica locale
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_dd_commessa ON determine_dirigenziali(commessa_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_dd_anno_scolastico ON determine_dirigenziali(anno_scolastico)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_recuperi_commessa ON recuperi_ore(commessa_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_recuperi_anno_scolastico ON recuperi_ore(anno_scolastico)')

    # Inserisce calendario default 2025-2026
    calendario_default = [
        ('2025-2026', 9, 2025, 17),   # Settembre 2025
        ('2025-2026', 10, 2025, 23),  # Ottobre 2025
        ('2025-2026', 11, 2025, 19),  # Novembre 2025
        ('2025-2026', 12, 2025, 16),  # Dicembre 2025
        ('2025-2026', 1, 2026, 18),   # Gennaio 2026
        ('2025-2026', 2, 2026, 20),   # Febbraio 2026
        ('2025-2026', 3, 2026, 22),   # Marzo 2026
        ('2025-2026', 4, 2026, 17),   # Aprile 2026
        ('2025-2026', 5, 2026, 21),   # Maggio 2026
        ('2025-2026', 6, 2026, 8),    # Giugno 2026
    ]

    for cal in calendario_default:
        cursor.execute('''
            INSERT OR IGNORE INTO calendario_scolastico
            (anno_scolastico, mese, anno, giorni_lavorativi)
            VALUES (?, ?, ?, ?)
        ''', cal)

    # Bonifica orfani storici creati quando l'enforcement FK era spento (es. righe
    # in sostituzioni che puntano a un turno cancellato): vanno rimosse prima che
    # l'enforcement (ora attivo) le faccia emergere.
    cursor.execute('''
        DELETE FROM sostituzioni
        WHERE turno_id IS NOT NULL AND turno_id NOT IN (SELECT id FROM turni)
    ''')

    # Versione schema: baseline per future migrazioni numerate (PRAGMA user_version).
    cursor.execute('PRAGMA user_version = 1')

    conn.commit()
    conn.close()

def punteggia_nome(nome, cognome):
    """Converte nome e cognome in formato puntato per privacy (es. Mario Rossi -> M. R.)"""
    nome_iniziale = nome[0].upper() + '.' if nome else ''
    cognome_iniziale = cognome[0].upper() + '.' if cognome else ''
    return f"{nome_iniziale} {cognome_iniziale}".strip()


def calcola_media_prevista(monte_ore, giorni_lavorativi):
    """Calcola la media mensile prevista di ore a partire dal monte ore settimanale.

    Formula unica usata in tutta l'applicazione:
      media_lorda = monte_ore * giorni * COEFFICIENTE_GIORNALIERO
      media_con_assenza = media_lorda * (1 - TASSO_ASSENZA)

    Ritorna una tupla (media_lorda, media_con_assenza).
    """
    media_lorda = (monte_ore or 0) * (giorni_lavorativi or 0) * config.COEFFICIENTE_GIORNALIERO
    media_con_assenza = media_lorda * (1 - config.TASSO_ASSENZA)
    return media_lorda, media_con_assenza

# ==================== CRUD COMMESSE ====================

def get_all_commesse(only_active=True):
    """Ottiene tutte le commesse"""
    with get_db_context() as conn:
        cursor = conn.cursor()

        query = "SELECT * FROM commesse"
        if only_active:
            query += " WHERE attiva = 1"
        query += " ORDER BY nome"

        cursor.execute(query)
        return [dict(r) for r in cursor.fetchall()]

def get_commessa_by_id(commessa_id):
    """Ottiene una commessa per ID"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM commesse WHERE id = ?", (commessa_id,))
        result = cursor.fetchone()
        return dict(result) if result else None

def get_commessa_by_nome(nome):
    """Ottiene una commessa per nome"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM commesse WHERE nome = ?", (nome,))
        result = cursor.fetchone()
        return dict(result) if result else None

def create_commessa(nome, descrizione=None, colore='#6366f1'):
    """Crea una nuova commessa"""
    try:
        with get_db_context() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO commesse (nome, descrizione, colore, data_creazione)
                VALUES (?, ?, ?, ?)
            ''', (nome, descrizione, colore, datetime.now().isoformat()))
            return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None

def update_commessa(commessa_id, nome=None, descrizione=None, colore=None, attiva=None):
    """Aggiorna una commessa"""
    updates = []
    params = []

    if nome is not None:
        updates.append("nome = ?")
        params.append(nome)
    if descrizione is not None:
        updates.append("descrizione = ?")
        params.append(descrizione)
    if colore is not None:
        updates.append("colore = ?")
        params.append(colore)
    if attiva is not None:
        updates.append("attiva = ?")
        params.append(1 if attiva else 0)

    if updates:
        params.append(commessa_id)
        with get_db_context() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE commesse SET {', '.join(updates)} WHERE id = ?", params)

def delete_commessa(commessa_id):
    """Elimina una commessa (soft delete)"""
    update_commessa(commessa_id, attiva=False)

# ==================== CRUD SCUOLE ====================

def get_or_create_scuola(commessa_nome, nome_completo):
    """Ottiene o crea una scuola (e la commessa se non esiste)"""
    with get_db_context() as conn:
        cursor = conn.cursor()

        # Trova commessa o creala se non esiste
        cursor.execute("SELECT id FROM commesse WHERE nome = ?", (commessa_nome,))
        commessa = cursor.fetchone()

        if not commessa:
            # Crea la commessa automaticamente
            cursor.execute('''
                INSERT INTO commesse (nome, descrizione, colore, attiva, data_creazione)
                VALUES (?, ?, ?, 1, ?)
            ''', (commessa_nome, f'Commessa {commessa_nome}', '#6366f1', datetime.now().isoformat()))
            commessa_id = cursor.lastrowid
        else:
            commessa_id = commessa['id']

        # Cerca scuola esistente
        cursor.execute(
            "SELECT id FROM scuole WHERE commessa_id = ? AND nome_completo = ?",
            (commessa_id, nome_completo)
        )
        scuola = cursor.fetchone()

        if scuola:
            return scuola['id']

        # Crea nuova scuola
        cursor.execute(
            "INSERT INTO scuole (commessa_id, nome_completo) VALUES (?, ?)",
            (commessa_id, nome_completo)
        )
        return cursor.lastrowid

# ==================== CRUD UTENTI ====================

def get_or_create_utente(scuola_id, nome, cognome, monte_ore):
    """Ottiene o crea un utente"""
    with get_db_context() as conn:
        cursor = conn.cursor()

        # Cerca utente esistente
        cursor.execute(
            "SELECT id FROM utenti WHERE scuola_id = ? AND nome = ? AND cognome = ?",
            (scuola_id, nome, cognome)
        )
        utente = cursor.fetchone()

        if utente:
            # Aggiorna monte ore se diverso
            cursor.execute(
                "UPDATE utenti SET monte_ore_settimanale = ? WHERE id = ?",
                (monte_ore, utente['id'])
            )
            return utente['id']

        # Crea nuovo utente
        nome_puntato = punteggia_nome(nome, cognome)
        cursor.execute('''
            INSERT INTO utenti (scuola_id, nome, cognome, nome_puntato, monte_ore_settimanale, data_inserimento)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (scuola_id, nome, cognome, nome_puntato, monte_ore, datetime.now().isoformat()))

        return cursor.lastrowid

def get_all_utenti(commessa=None, scuola_id=None, include_inactive_period=True, page=None, limit=50):
    """
    Ottiene tutti gli utenti, con filtri opzionali e paginazione.
    include_inactive_period: se True, include anche utenti fuori dal periodo di validità
    page: numero pagina (1-based), se None restituisce tutti
    limit: numero elementi per pagina (default 50)
    """
    with get_db_context() as conn:
        cursor = conn.cursor()

        query = '''
            SELECT u.*, s.nome_completo as scuola, c.nome as commessa
            FROM utenti u
            JOIN scuole s ON u.scuola_id = s.id
            JOIN commesse c ON s.commessa_id = c.id
            WHERE u.attivo = 1
        '''
        params = []

        if commessa:
            query += " AND c.nome = ?"
            params.append(commessa)

        if scuola_id:
            query += " AND s.id = ?"
            params.append(scuola_id)

        query += " ORDER BY c.nome, s.nome_completo, u.cognome, u.nome"

        # Paginazione
        if page is not None and page > 0:
            offset = (page - 1) * limit
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def count_utenti(commessa=None, scuola_id=None, attivo=True):
    """
    Conta gli utenti con filtri opzionali.
    Helper function per evitare duplicazione di query COUNT.
    """
    with get_db_context() as conn:
        cursor = conn.cursor()

        query = "SELECT COUNT(*) FROM utenti u"
        joins = []
        conditions = []
        params = []

        if commessa:
            joins.append("JOIN scuole s ON u.scuola_id = s.id")
            joins.append("JOIN commesse c ON s.commessa_id = c.id")
            conditions.append("c.nome = ?")
            params.append(commessa)

        if scuola_id:
            conditions.append("u.scuola_id = ?")
            params.append(scuola_id)

        if attivo is not None:
            conditions.append("u.attivo = ?")
            params.append(1 if attivo else 0)

        if joins:
            query += " " + " ".join(joins)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        cursor.execute(query, params)
        return cursor.fetchone()[0]

def delete_utente(utente_id):
    """Elimina un utente (soft delete)"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE utenti SET attivo = 0 WHERE id = ?", (utente_id,))


def update_utente_lista_attesa(utente_id, lista_attesa):
    """Aggiorna la lista attesa di un utente"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE utenti SET lista_attesa = ? WHERE id = ?",
                       (lista_attesa if lista_attesa else None, utente_id))


def update_utente_periodo(utente_id, data_inizio=None, data_fine=None):
    """
    Aggiorna il periodo di validità di un utente.
    data_inizio: formato 'YYYY-MM' (es. '2026-02' per febbraio 2026)
    data_fine: formato 'YYYY-MM' (es. '2026-01' per gennaio 2026)
    """
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE utenti
            SET data_inizio = ?, data_fine = ?
            WHERE id = ?
        """, (data_inizio if data_inizio else None,
              data_fine if data_fine else None,
              utente_id))


def get_utente_by_id(utente_id):
    """Ottiene un utente per ID"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.*, s.nome_completo as scuola, c.nome as commessa
            FROM utenti u
            JOIN scuole s ON u.scuola_id = s.id
            JOIN commesse c ON s.commessa_id = c.id
            WHERE u.id = ?
        """, (utente_id,))
        result = cursor.fetchone()
        return dict(result) if result else None

def is_utente_attivo_nel_mese(utente, anno, mese):
    """
    Verifica se un utente è attivo in un dato mese.

    Un utente è attivo nel mese se:
    - data_inizio è NULL o il mese è >= data_inizio
    - data_fine è NULL o il mese è <= data_fine

    Le date sono in formato 'YYYY-MM'
    """
    periodo_corrente = f"{anno:04d}-{mese:02d}"

    data_inizio = utente.get('data_inizio')
    data_fine = utente.get('data_fine')

    # Se data_inizio è impostata, verifica che il mese sia >= data_inizio
    if data_inizio and periodo_corrente < data_inizio:
        return False

    # Se data_fine è impostata, verifica che il mese sia <= data_fine
    if data_fine and periodo_corrente > data_fine:
        return False

    return True

# ==================== CALENDARIO ====================

def get_calendario(anno_scolastico, mese, anno):
    """Ottiene i giorni lavorativi per un mese specifico (default/infanzia)"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT giorni_lavorativi FROM calendario_scolastico
            WHERE anno_scolastico = ? AND mese = ? AND anno = ?
        ''', (anno_scolastico, mese, anno))
        result = cursor.fetchone()
        return result['giorni_lavorativi'] if result else 0


def risolvi_giorni_lavorativi(giorni_calendario):
    """Regola UNICA per i giorni lavorativi effettivi di un mese.

    Usa il valore da calendario (per tipo scuola) se presente e > 0, altrimenti
    il fallback config.GIORNI_LAVORATIVI_DEFAULT. Il valore eventualmente salvato
    in rendicontazione e' solo una cache potenzialmente obsoleta e non viene usato
    come fonte. Va richiamata da TUTTI i percorsi (vista mensile, storico utente,
    aggregati) affinche' mostrino lo stesso numero ed evitino incoerenze
    (es. vista mensile a 0 giorni e storico a 22 per un mese senza calendario)."""
    return giorni_calendario if giorni_calendario else config.GIORNI_LAVORATIVI_DEFAULT


def get_calendario_full(anno_scolastico, mese, anno):
    """Ottiene (giorni_lavorativi, giorni_lavorativi_altri) per un mese.
    Il secondo e' None se non impostato -> si usa lo stesso di giorni_lavorativi."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT giorni_lavorativi, giorni_lavorativi_altri FROM calendario_scolastico
            WHERE anno_scolastico = ? AND mese = ? AND anno = ?
        ''', (anno_scolastico, mese, anno))
        result = cursor.fetchone()
        if not result:
            return (0, None)
        return (result['giorni_lavorativi'], result['giorni_lavorativi_altri'])


def is_scuola_infanzia(scuola_nome):
    """True se la scuola e' dell'infanzia (cerca 'INFANZIA' nel nome, case-insensitive).
    Coerente con la classificazione in app.classifica_livello_scolastico."""
    if not scuola_nome:
        return False
    return 'INFANZIA' in scuola_nome.upper()


def get_giorni_per_scuola(anno_scolastico, mese, anno, scuola_nome):
    """Ritorna i giorni lavorativi applicabili a una specifica scuola.
    - Infanzia: sempre giorni_lavorativi (calendario standard lun-ven/festivita')
    - Non infanzia: giorni_lavorativi_altri se presente, altrimenti giorni_lavorativi
    """
    giorni_default, giorni_altri = get_calendario_full(anno_scolastico, mese, anno)
    if is_scuola_infanzia(scuola_nome):
        return giorni_default
    return giorni_altri if giorni_altri is not None else giorni_default


def set_calendario(anno_scolastico, mese, anno, giorni, giorni_altri=None):
    """Imposta i giorni lavorativi per un mese.
    - giorni: default (infanzia + tutti i mesi tranne giugno)
    - giorni_altri: opzionale, usato dal non-infanzia (tipicamente solo giugno)"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO calendario_scolastico
            (anno_scolastico, mese, anno, giorni_lavorativi, giorni_lavorativi_altri)
            VALUES (?, ?, ?, ?, ?)
        ''', (anno_scolastico, mese, anno, giorni, giorni_altri))

# ==================== RENDICONTAZIONE ====================

def get_or_create_rendicontazione(utente_id, anno, mese):
    """Ottiene o crea una rendicontazione mensile"""
    # Determina anno scolastico
    if mese >= 9:
        anno_scolastico = f"{anno}-{anno+1}"
    else:
        anno_scolastico = f"{anno-1}-{anno}"

    with get_db_context() as conn:
        cursor = conn.cursor()

        # Ottieni giorni lavorativi per la scuola dell'utente (distinzione infanzia/altri)
        cursor.execute('''
            SELECT s.nome_completo FROM utenti u
            JOIN scuole s ON u.scuola_id = s.id
            WHERE u.id = ?
        ''', (utente_id,))
        r = cursor.fetchone()
        scuola_nome = r['nome_completo'] if r else None
        giorni = get_giorni_per_scuola(anno_scolastico, mese, anno, scuola_nome)

        cursor.execute(
            "SELECT * FROM rendicontazione WHERE utente_id = ? AND anno = ? AND mese = ?",
            (utente_id, anno, mese)
        )
        rend = cursor.fetchone()

        if rend:
            return dict(rend)

        # Crea nuova rendicontazione
        cursor.execute('''
            INSERT INTO rendicontazione (utente_id, anno, mese, giorni_lavorativi, data_inserimento)
            VALUES (?, ?, ?, ?, ?)
        ''', (utente_id, anno, mese, giorni, datetime.now().isoformat()))

        rend_id = cursor.lastrowid
        cursor.execute("SELECT * FROM rendicontazione WHERE id = ?", (rend_id,))
        return dict(cursor.fetchone())

def update_rendicontazione(utente_id, anno, mese, ore_lavorate=None, pasti=None, note=None):
    """Aggiorna una rendicontazione esistente"""
    updates = ["data_modifica = ?"]
    params = [datetime.now().isoformat()]

    if ore_lavorate is not None:
        updates.append("ore_lavorate_60 = ?")
        params.append(ore_lavorate)

    if pasti is not None:
        updates.append("pasti = ?")
        params.append(pasti)

    if note is not None:
        updates.append("note = ?")
        params.append(note)

    params.extend([utente_id, anno, mese])

    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute(f'''
            UPDATE rendicontazione
            SET {', '.join(updates)}
            WHERE utente_id = ? AND anno = ? AND mese = ?
        ''', params)


def update_rendicontazione_batch(anno, mese, updates):
    """Aggiorna la rendicontazione di più utenti in una SINGOLA transazione.

    updates: lista di dict con chiavi 'utente_id' e, opzionali,
    'ore_lavorate', 'pasti', 'note'. Le righe mancanti vengono create.
    In caso di errore nessuna modifica viene applicata (rollback).
    Ritorna il numero di utenti aggiornati.
    """
    if mese >= 9:
        anno_scolastico = f"{anno}-{anno+1}"
    else:
        anno_scolastico = f"{anno-1}-{anno}"

    aggiornati = 0
    conn = get_db()
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        for upd in updates:
            utente_id = upd.get('utente_id')
            if not utente_id:
                continue

            # Crea la riga se mancante (equivalente di get_or_create_rendicontazione)
            cursor.execute(
                "SELECT 1 FROM rendicontazione WHERE utente_id = ? AND anno = ? AND mese = ?",
                (utente_id, anno, mese)
            )
            if not cursor.fetchone():
                cursor.execute('''
                    SELECT s.nome_completo FROM utenti u
                    JOIN scuole s ON u.scuola_id = s.id
                    WHERE u.id = ?
                ''', (utente_id,))
                r = cursor.fetchone()
                scuola_nome = r['nome_completo'] if r else None
                giorni = get_giorni_per_scuola(anno_scolastico, mese, anno, scuola_nome)
                cursor.execute('''
                    INSERT INTO rendicontazione (utente_id, anno, mese, giorni_lavorativi, data_inserimento)
                    VALUES (?, ?, ?, ?, ?)
                ''', (utente_id, anno, mese, giorni, now))

            sets = ["data_modifica = ?"]
            params = [now]
            for campo, colonna in (('ore_lavorate', 'ore_lavorate_60'),
                                   ('pasti', 'pasti'),
                                   ('note', 'note')):
                if upd.get(campo) is not None:
                    sets.append(f"{colonna} = ?")
                    params.append(upd[campo])
            params.extend([utente_id, anno, mese])

            cursor.execute(f'''
                UPDATE rendicontazione
                SET {', '.join(sets)}
                WHERE utente_id = ? AND anno = ? AND mese = ?
            ''', params)
            aggiornati += 1

        conn.commit()
        return aggiornati
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_rendicontazione_completa(anno, mese, commessa=None):
    """Ottiene la rendicontazione completa per un mese con tutti i calcoli"""
    # Determina anno scolastico
    if mese >= 9:
        anno_scolastico = f"{anno}-{anno+1}"
    else:
        anno_scolastico = f"{anno-1}-{anno}"

    # Calcola il periodo corrente per il filtro date
    periodo_corrente = f"{anno:04d}-{mese:02d}"

    query = '''
        SELECT
            u.id as utente_id,
            u.nome,
            u.cognome,
            u.nome_puntato,
            u.monte_ore_settimanale,
            u.lista_attesa,
            u.data_inizio,
            u.data_fine,
            s.id as scuola_id,
            s.nome_completo as scuola,
            c.nome as commessa,
            r.ore_lavorate_60,
            r.pasti,
            r.giorni_lavorativi,
            r.note
        FROM utenti u
        JOIN scuole s ON u.scuola_id = s.id
        JOIN commesse c ON s.commessa_id = c.id
        LEFT JOIN rendicontazione r ON u.id = r.utente_id AND r.anno = ? AND r.mese = ?
        WHERE u.attivo = 1
        AND (u.data_inizio IS NULL OR u.data_inizio <= ?)
        AND (u.data_fine IS NULL OR u.data_fine >= ?)
    '''
    params = [anno, mese, periodo_corrente, periodo_corrente]

    if commessa:
        query += " AND c.nome = ?"
        params.append(commessa)

    query += " ORDER BY c.nome, s.nome_completo, u.cognome, u.nome"

    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()

    risultati = []
    # Cache del calendario per non rifare la query ad ogni riga
    giorni_default_cal, giorni_altri_cal = get_calendario_full(anno_scolastico, mese, anno)

    # Cache variazioni monte ore per il mese corrente
    variazioni_effettive = get_monte_ore_effettivo_bulk(anno, mese)

    for row in rows:
        row_dict = dict(row)

        # Giorni lavorativi: calcolati sempre dal calendario in base al tipo di scuola
        # (infanzia vs altri). Ignoriamo il valore salvato in rendicontazione, che era
        # solo una cache e potrebbe essere obsoleto rispetto al calendario aggiornato.
        if is_scuola_infanzia(row_dict.get('scuola')):
            giorni_cal = giorni_default_cal
        else:
            giorni_cal = giorni_altri_cal if giorni_altri_cal is not None else giorni_default_cal

        # Regola unica condivisa (calendario -> default), coerente con lo storico
        giorni = risolvi_giorni_lavorativi(giorni_cal)

        # Monte ore: usa variazione se presente, altrimenti valore base
        utente_id = row_dict['utente_id']
        monte_ore_base = row_dict['monte_ore_settimanale'] or 0
        monte_ore = variazioni_effettive.get(utente_id, monte_ore_base)
        row_dict['monte_ore_effettivo'] = monte_ore
        row_dict['monte_ore_variato'] = utente_id in variazioni_effettive
        ore_lavorate_60 = row_dict['ore_lavorate_60'] or 0

        # Calcoli (formula centralizzata)
        coefficiente = giorni * config.COEFFICIENTE_GIORNALIERO
        media_mensile, media_con_assenza = calcola_media_prevista(monte_ore, giorni)

        # In formato decimale/centesimale sono lo stesso valore
        ore_lavorate_100 = ore_lavorate_60
        media_mensile_100 = media_mensile
        media_con_assenza_100 = media_con_assenza

        # Calcoli economici (helper unico: stessa formula ovunque)
        imponibile_100, iva_100, totale_100 = config.calcola_fatturazione(ore_lavorate_100)
        imponibile_60, iva_60, totale_60 = config.calcola_fatturazione(ore_lavorate_60)

        # Credito/Debito = Media -11% MENO Ore lavorate
        credito_debito = media_con_assenza - ore_lavorate_60

        row_dict.update({
            'giorni_lavorativi': giorni,
            'coefficiente': coefficiente,
            'media_mensile_60': round(media_mensile, 2),
            'media_con_assenza_60': round(media_con_assenza, 2),
            'ore_lavorate_100': round(ore_lavorate_100, 2),
            'media_mensile_100': round(media_mensile_100, 2),
            'media_con_assenza_100': round(media_con_assenza_100, 2),
            'imponibile_100': round(imponibile_100, 2),
            'iva_100': round(iva_100, 2),
            'totale_100': round(totale_100, 2),
            'imponibile_60': round(imponibile_60, 2),
            'iva_60': round(iva_60, 2),
            'totale_60': round(totale_60, 2),
            'credito_debito': round(credito_debito, 2)
        })

        risultati.append(row_dict)

    return risultati

def get_totali_per_scuola(anno, mese, commessa=None):
    """Ottiene i totali aggregati per scuola con calcolo fatturazione corretto"""
    dati = get_rendicontazione_completa(anno, mese, commessa)

    totali = {}
    for row in dati:
        scuola_id = row['scuola_id']
        if scuola_id not in totali:
            totali[scuola_id] = {
                'scuola': row['scuola'],
                'commessa': row['commessa'],
                'num_utenti': 0,
                'ore_lavorate_60': 0,
                'ore_lavorate_100': 0,
                'pasti': 0,
                'credito_debito': 0
            }

        totali[scuola_id]['num_utenti'] += 1
        totali[scuola_id]['ore_lavorate_60'] += row['ore_lavorate_60'] or 0
        totali[scuola_id]['ore_lavorate_100'] += row['ore_lavorate_100'] or 0
        totali[scuola_id]['pasti'] += row['pasti'] or 0
        totali[scuola_id]['credito_debito'] += row['credito_debito'] or 0

    # Calcola imponibile, iva e totale sul totale delle ore (metodo contabile corretto)
    for scuola_id in totali:
        ore = totali[scuola_id]['ore_lavorate_100']
        imponibile, iva, totale = config.calcola_fatturazione(ore)
        totali[scuola_id]['imponibile_100'] = imponibile
        totali[scuola_id]['iva_100'] = iva
        totali[scuola_id]['totale_100'] = totale

    return list(totali.values())

def get_all_scuole(commessa=None):
    """Ottiene tutte le scuole"""
    with get_db_context() as conn:
        cursor = conn.cursor()

        query = '''
            SELECT s.*, c.nome as commessa
            FROM scuole s
            JOIN commesse c ON s.commessa_id = c.id
            WHERE c.attiva = 1
        '''
        params = []

        if commessa:
            query += " AND c.nome = ?"
            params.append(commessa)

        query += " ORDER BY c.nome, s.nome_completo"

        cursor.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]


def get_anni_scolastici():
    """Ottiene tutti gli anni scolastici disponibili"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT anno_scolastico FROM calendario_scolastico ORDER BY anno_scolastico DESC")
        return [r['anno_scolastico'] for r in cursor.fetchall()]

def create_anno_scolastico(anno_inizio):
    """Crea un nuovo anno scolastico con giorni default"""
    anno_scolastico = f"{anno_inizio}-{anno_inizio+1}"

    # Giorni default (da personalizzare)
    mesi = [
        (9, anno_inizio, 20),    # Settembre
        (10, anno_inizio, 22),   # Ottobre
        (11, anno_inizio, 20),   # Novembre
        (12, anno_inizio, 15),   # Dicembre
        (1, anno_inizio+1, 18),  # Gennaio
        (2, anno_inizio+1, 20),  # Febbraio
        (3, anno_inizio+1, 22),  # Marzo
        (4, anno_inizio+1, 17),  # Aprile
        (5, anno_inizio+1, 21),  # Maggio
        (6, anno_inizio+1, 10),  # Giugno
    ]

    for mese, anno, giorni in mesi:
        set_calendario(anno_scolastico, mese, anno, giorni)

    return anno_scolastico

# ==================== STATISTICHE AVANZATE ====================

def get_statistiche_avanzate(anno=None, mese=None, commessa=None):
    """Ottiene statistiche avanzate per dashboard"""
    with get_db_context() as conn:
        cursor = conn.cursor()

        stats = {}

        # Conteggi base con filtro commessa opzionale
        # NOTA: utenti.commessa non esiste, dobbiamo fare JOIN attraverso scuole -> commesse
        if commessa:
            cursor.execute("""
                SELECT COUNT(*) FROM utenti u
                JOIN scuole s ON u.scuola_id = s.id
                JOIN commesse c ON s.commessa_id = c.id
                WHERE u.attivo = 1 AND c.nome = ?
            """, (commessa,))
        else:
            cursor.execute("SELECT COUNT(*) FROM utenti WHERE attivo = 1")
        stats['num_utenti'] = cursor.fetchone()[0]

        if commessa:
            cursor.execute("""
                SELECT COUNT(DISTINCT s.id) FROM scuole s
                JOIN commesse c ON s.commessa_id = c.id
                WHERE c.nome = ?
            """, (commessa,))
        else:
            cursor.execute("SELECT COUNT(*) FROM scuole")
        stats['num_scuole'] = cursor.fetchone()[0]

        if commessa:
            cursor.execute("SELECT COUNT(*) FROM commesse WHERE attiva = 1 AND nome = ?", (commessa,))
        else:
            cursor.execute("SELECT COUNT(*) FROM commesse WHERE attiva = 1")
        stats['num_commesse'] = cursor.fetchone()[0]

        # Utenti per commessa
        if commessa:
            cursor.execute('''
                SELECT c.nome, c.colore, COUNT(u.id) as count
                FROM commesse c
                LEFT JOIN scuole s ON c.id = s.commessa_id
                LEFT JOIN utenti u ON s.id = u.scuola_id AND u.attivo = 1
                WHERE c.attiva = 1 AND c.nome = ?
                GROUP BY c.id
                ORDER BY c.nome
            ''', (commessa,))
        else:
            cursor.execute('''
                SELECT c.nome, c.colore, COUNT(u.id) as count
                FROM commesse c
                LEFT JOIN scuole s ON c.id = s.commessa_id
                LEFT JOIN utenti u ON s.id = u.scuola_id AND u.attivo = 1
                WHERE c.attiva = 1
                GROUP BY c.id
                ORDER BY c.nome
            ''')
        stats['utenti_per_commessa'] = [dict(r) for r in cursor.fetchall()]

        # Monte ore totale
        if commessa:
            cursor.execute("""
                SELECT SUM(u.monte_ore_settimanale) FROM utenti u
                JOIN scuole s ON u.scuola_id = s.id
                JOIN commesse c ON s.commessa_id = c.id
                WHERE u.attivo = 1 AND c.nome = ?
            """, (commessa,))
        else:
            cursor.execute("SELECT SUM(monte_ore_settimanale) FROM utenti WHERE attivo = 1")
        stats['monte_ore_totale'] = cursor.fetchone()[0] or 0

        # Se specificato anno/mese, calcola statistiche mensili
        if anno and mese:
            if commessa:
                cursor.execute('''
                    SELECT
                        SUM(r.ore_lavorate_60) as ore_totali,
                        COUNT(DISTINCT r.utente_id) as utenti_con_ore
                    FROM rendicontazione r
                    JOIN utenti u ON r.utente_id = u.id
                    JOIN scuole s ON u.scuola_id = s.id
                    JOIN commesse c ON s.commessa_id = c.id
                    WHERE r.anno = ? AND r.mese = ? AND u.attivo = 1 AND c.nome = ?
                ''', (anno, mese, commessa))
            else:
                cursor.execute('''
                    SELECT
                        SUM(r.ore_lavorate_60) as ore_totali,
                        COUNT(DISTINCT r.utente_id) as utenti_con_ore
                    FROM rendicontazione r
                    JOIN utenti u ON r.utente_id = u.id
                    WHERE r.anno = ? AND r.mese = ? AND u.attivo = 1
                ''', (anno, mese))
            row = cursor.fetchone()
            stats['ore_mese_corrente'] = row['ore_totali'] or 0
            stats['utenti_con_ore'] = row['utenti_con_ore'] or 0

        # Trend ultimi 6 mesi
        if commessa:
            cursor.execute('''
                SELECT r.anno, r.mese, SUM(r.ore_lavorate_60) as ore_totali
                FROM rendicontazione r
                JOIN utenti u ON r.utente_id = u.id
                JOIN scuole s ON u.scuola_id = s.id
                JOIN commesse c ON s.commessa_id = c.id
                WHERE u.attivo = 1 AND c.nome = ?
                GROUP BY r.anno, r.mese
                ORDER BY r.anno DESC, r.mese DESC
                LIMIT 6
            ''', (commessa,))
        else:
            cursor.execute('''
                SELECT r.anno, r.mese, SUM(r.ore_lavorate_60) as ore_totali
                FROM rendicontazione r
                JOIN utenti u ON r.utente_id = u.id
                WHERE u.attivo = 1
                GROUP BY r.anno, r.mese
                ORDER BY r.anno DESC, r.mese DESC
                LIMIT 6
            ''')
        stats['trend_mensile'] = [dict(r) for r in cursor.fetchall()][::-1]  # Inverti per ordine cronologico

        # Top 5 scuole per utenti (mantenuto per retrocompatibilità)
        if commessa:
            cursor.execute('''
                SELECT s.nome_completo, COUNT(u.id) as num_utenti
                FROM scuole s
                JOIN utenti u ON s.id = u.scuola_id AND u.attivo = 1
                JOIN commesse c ON s.commessa_id = c.id
                WHERE c.nome = ?
                GROUP BY s.id
                ORDER BY num_utenti DESC
                LIMIT 5
            ''', (commessa,))
        else:
            cursor.execute('''
                SELECT s.nome_completo, COUNT(u.id) as num_utenti
                FROM scuole s
                JOIN utenti u ON s.id = u.scuola_id AND u.attivo = 1
                GROUP BY s.id
                ORDER BY num_utenti DESC
                LIMIT 5
            ''')
        stats['top_scuole'] = [dict(r) for r in cursor.fetchall()]

        return stats


def get_utenti_meno_ore(anno, mese, limit=10):
    """Ottiene gli utenti con meno ore erogate (maggior debito) per un mese specifico.

    credito_debito = media_con_assenza - ore_lavorate_60
    - debito_credito > 0 -> utente in DEBITO (ha lavorato meno del previsto)
    - debito_credito < 0 -> utente in CREDITO (ha lavorato più del previsto)
    Vogliamo i 10 con il debito maggiore (credito_debito più alto), quindi ordine DESC.
    """
    dati = get_rendicontazione_completa(anno, mese)

    # Filtra solo utenti con monte ore previsto > 0 (quelli per cui ha senso parlare di debito)
    # e ordina per credito_debito DECRESCENTE (debito più alto = meno ore erogate rispetto alle previste)
    utenti_ordinati = sorted(
        [d for d in dati if d.get('media_con_assenza_60', 0) > 0],
        key=lambda x: x.get('credito_debito', 0),
        reverse=True
    )

    # Prendi i primi 10 (quelli con il debito maggiore = meno ore erogate rispetto alle previste)
    risultati = []
    for u in utenti_ordinati[:limit]:
        risultati.append({
            'utente_id': u['utente_id'],
            'nome': u['nome'],
            'cognome': u['cognome'],
            'scuola': u['scuola'],
            'commessa': u['commessa'],
            'ore_previste': round(u['media_con_assenza_60'], 2),
            'ore_erogate': round(u['ore_lavorate_60'] or 0, 2),
            'differenza': round(u['credito_debito'], 2)
        })

    return risultati


def get_ore_erogate_vs_previste(anno_scolastico, commessa=None):
    """Ottiene il confronto ore erogate vs previste per ogni mese dell'anno scolastico"""
    with get_db_context() as conn:
        cursor = conn.cursor()

        # Parse anno scolastico
        anni = anno_scolastico.split('-')
        anno_inizio = int(anni[0])
        anno_fine = int(anni[1])

        mesi_scolastici = [
            (9, anno_inizio), (10, anno_inizio), (11, anno_inizio), (12, anno_inizio),
            (1, anno_fine), (2, anno_fine), (3, anno_fine), (4, anno_fine),
            (5, anno_fine), (6, anno_fine)
        ]

        MESI_NOME = {
            1: 'Gen', 2: 'Feb', 3: 'Mar', 4: 'Apr',
            5: 'Mag', 6: 'Giu', 7: 'Lug', 8: 'Ago',
            9: 'Set', 10: 'Ott', 11: 'Nov', 12: 'Dic'
        }

        risultati = []
        for mese, anno in mesi_scolastici:
            # Calcola ore erogate con filtro commessa opzionale
            # NOTA: utenti.commessa non esiste, dobbiamo fare JOIN attraverso scuole -> commesse
            if commessa:
                cursor.execute('''
                    SELECT SUM(r.ore_lavorate_60) as ore_erogate
                    FROM rendicontazione r
                    JOIN utenti u ON r.utente_id = u.id
                    JOIN scuole s ON u.scuola_id = s.id
                    JOIN commesse cm ON s.commessa_id = cm.id
                    WHERE r.anno = ? AND r.mese = ? AND u.attivo = 1 AND cm.nome = ?
                ''', (anno, mese, commessa))
            else:
                cursor.execute('''
                    SELECT SUM(r.ore_lavorate_60) as ore_erogate
                    FROM rendicontazione r
                    JOIN utenti u ON r.utente_id = u.id
                    WHERE r.anno = ? AND r.mese = ? AND u.attivo = 1
                ''', (anno, mese))
            row = cursor.fetchone()
            ore_erogate = row['ore_erogate'] or 0

            # Calcola ore previste (media -11%)
            # Formula: monte_ore_settimanale * giorni_lavorativi * coeff giornaliero * (1 - tasso assenza)
            # Per non-infanzia usa giorni_lavorativi_altri se presente (tipicamente solo giugno)
            coeff_previste = config.COEFFICIENTE_GIORNALIERO * (1 - config.TASSO_ASSENZA)
            if commessa:
                cursor.execute('''
                    SELECT
                        SUM(u.monte_ore_settimanale * COALESCE(
                            CASE
                                WHEN UPPER(COALESCE(s.nome_completo, '')) LIKE '%INFANZIA%' THEN cal.giorni_lavorativi
                                ELSE COALESCE(cal.giorni_lavorativi_altri, cal.giorni_lavorativi)
                            END, 0) * ?) as ore_previste
                    FROM utenti u
                    JOIN scuole s ON u.scuola_id = s.id
                    JOIN commesse cm ON s.commessa_id = cm.id
                    LEFT JOIN calendario_scolastico cal ON cal.anno_scolastico = ? AND cal.mese = ? AND cal.anno = ?
                    WHERE u.attivo = 1 AND cm.nome = ?
                ''', (coeff_previste, anno_scolastico, mese, anno, commessa))
            else:
                cursor.execute('''
                    SELECT
                        SUM(u.monte_ore_settimanale * COALESCE(
                            CASE
                                WHEN UPPER(COALESCE(s.nome_completo, '')) LIKE '%INFANZIA%' THEN c.giorni_lavorativi
                                ELSE COALESCE(c.giorni_lavorativi_altri, c.giorni_lavorativi)
                            END, 0) * ?) as ore_previste
                    FROM utenti u
                    JOIN scuole s ON u.scuola_id = s.id
                    LEFT JOIN calendario_scolastico c ON c.anno_scolastico = ? AND c.mese = ? AND c.anno = ?
                    WHERE u.attivo = 1
                ''', (coeff_previste, anno_scolastico, mese, anno))
            ore_previste_row = cursor.fetchone()
            ore_previste = ore_previste_row['ore_previste'] or 0

            risultati.append({
                'mese': mese,
                'mese_nome': MESI_NOME.get(mese, ''),
                'anno': anno,
                'ore_erogate': round(ore_erogate, 2),
                'ore_previste': round(ore_previste, 2)
            })

        return risultati


def get_statistiche_mensili_anno(anno_scolastico):
    """Ottiene le statistiche mensili per un anno scolastico"""
    with get_db_context() as conn:
        cursor = conn.cursor()

        # Parse anno scolastico
        anni = anno_scolastico.split('-')
        anno_inizio = int(anni[0])
        anno_fine = int(anni[1])

        mesi_scolastici = [
            (9, anno_inizio), (10, anno_inizio), (11, anno_inizio), (12, anno_inizio),
            (1, anno_fine), (2, anno_fine), (3, anno_fine), (4, anno_fine),
            (5, anno_fine), (6, anno_fine)
        ]

        risultati = []
        for mese, anno in mesi_scolastici:
            cursor.execute('''
                SELECT
                    SUM(r.ore_lavorate_60) as ore_erogate,
                    COUNT(DISTINCT CASE WHEN r.ore_lavorate_60 > 0 THEN r.utente_id END) as utenti_attivi
                FROM rendicontazione r
                JOIN utenti u ON r.utente_id = u.id
                WHERE r.anno = ? AND r.mese = ? AND u.attivo = 1
            ''', (anno, mese))
            row = cursor.fetchone()

            # Calcola ore previste (distinzione infanzia vs altri).
            # Coefficiente = COEFFICIENTE_GIORNALIERO * (1 - TASSO_ASSENZA), dal config.
            coeff_previste = config.COEFFICIENTE_GIORNALIERO * (1 - config.TASSO_ASSENZA)
            cursor.execute('''
                SELECT SUM(u.monte_ore_settimanale *
                    CASE
                        WHEN UPPER(COALESCE(s.nome_completo, '')) LIKE '%INFANZIA%' THEN c.giorni_lavorativi
                        ELSE COALESCE(c.giorni_lavorativi_altri, c.giorni_lavorativi)
                    END
                    * ?) as ore_previste
                FROM utenti u
                JOIN scuole s ON u.scuola_id = s.id
                JOIN calendario_scolastico c ON c.anno_scolastico = ? AND c.mese = ? AND c.anno = ?
                WHERE u.attivo = 1
            ''', (coeff_previste, anno_scolastico, mese, anno))
            ore_previste_row = cursor.fetchone()

            risultati.append({
                'mese': mese,
                'anno': anno,
                'ore_erogate': row['ore_erogate'] or 0,
                'ore_previste': ore_previste_row['ore_previste'] or 0,
                'utenti_attivi': row['utenti_attivi'] or 0
            })

        return risultati

# ==================== CONFRONTO ANNO SU ANNO ====================

def get_confronto_annuale(anno_scolastico_1, anno_scolastico_2):
    """Confronta i dati di due anni scolastici mese per mese"""
    with get_db_context() as conn:
        cursor = conn.cursor()

        MESI_NOME_SHORT = {
            1: 'Gen', 2: 'Feb', 3: 'Mar', 4: 'Apr',
            5: 'Mag', 6: 'Giu', 9: 'Set', 10: 'Ott', 11: 'Nov', 12: 'Dic'
        }

        def parse_anno(as_str):
            anni = as_str.split('-')
            return int(anni[0]), int(anni[1])

        def get_dati_anno(anno_scolastico):
            anno_inizio, anno_fine = parse_anno(anno_scolastico)
            mesi_scolastici = [
                (9, anno_inizio), (10, anno_inizio), (11, anno_inizio), (12, anno_inizio),
                (1, anno_fine), (2, anno_fine), (3, anno_fine), (4, anno_fine),
                (5, anno_fine), (6, anno_fine)
            ]
            risultati = []
            for mese, anno in mesi_scolastici:
                cursor.execute('''
                    SELECT
                        SUM(r.ore_lavorate_60) as ore_erogate,
                        COUNT(DISTINCT CASE WHEN r.ore_lavorate_60 > 0 THEN r.utente_id END) as utenti_attivi,
                        SUM(r.pasti) as pasti
                    FROM rendicontazione r
                    JOIN utenti u ON r.utente_id = u.id
                    WHERE r.anno = ? AND r.mese = ? AND u.attivo = 1
                ''', (anno, mese))
                row = cursor.fetchone()

                cursor.execute("SELECT COUNT(*) FROM utenti WHERE attivo = 1")
                tot_utenti = cursor.fetchone()[0]

                risultati.append({
                    'mese': mese,
                    'mese_nome': MESI_NOME_SHORT.get(mese, ''),
                    'anno': anno,
                    'ore_erogate': round(row['ore_erogate'] or 0, 2),
                    'utenti_attivi': row['utenti_attivi'] or 0,
                    'pasti': row['pasti'] or 0,
                    'tot_utenti': tot_utenti
                })
            return risultati

        dati_1 = get_dati_anno(anno_scolastico_1)
        dati_2 = get_dati_anno(anno_scolastico_2)

        # Calcola variazioni percentuali
        confronto = []
        for d1, d2 in zip(dati_1, dati_2):
            var_ore = None
            if d1['ore_erogate'] > 0:
                var_ore = round(((d2['ore_erogate'] - d1['ore_erogate']) / d1['ore_erogate']) * 100, 1)

            confronto.append({
                'mese': d1['mese'],
                'mese_nome': d1['mese_nome'],
                'anno_1': {
                    'anno_scolastico': anno_scolastico_1,
                    'ore': d1['ore_erogate'],
                    'utenti': d1['utenti_attivi'],
                    'pasti': d1['pasti']
                },
                'anno_2': {
                    'anno_scolastico': anno_scolastico_2,
                    'ore': d2['ore_erogate'],
                    'utenti': d2['utenti_attivi'],
                    'pasti': d2['pasti']
                },
                'variazione_ore': var_ore
            })

        return confronto


# ==================== DOCUMENTI UTENTE ====================

def get_documenti_utente(utente_id):
    """Ottiene tutti i documenti di un utente"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM documenti_utente
            WHERE utente_id = ?
            ORDER BY data_caricamento DESC
        ''', (utente_id,))
        return [dict(r) for r in cursor.fetchall()]


def add_documento_utente(utente_id, nome_file, nome_originale, tipo_documento,
                          descrizione=None, data_scadenza=None, dimensione=None):
    """Aggiunge un documento per un utente"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO documenti_utente
            (utente_id, nome_file, nome_originale, tipo_documento, descrizione,
             data_scadenza, data_caricamento, dimensione)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (utente_id, nome_file, nome_originale, tipo_documento,
              descrizione, data_scadenza, datetime.now().isoformat(), dimensione))
        return cursor.lastrowid


def delete_documento_utente(documento_id):
    """Elimina un documento"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        # Prima ottieni il nome file per eliminarlo dal filesystem
        cursor.execute('SELECT nome_file FROM documenti_utente WHERE id = ?', (documento_id,))
        doc = cursor.fetchone()
        cursor.execute('DELETE FROM documenti_utente WHERE id = ?', (documento_id,))
        return doc['nome_file'] if doc else None


def get_documenti_in_scadenza(giorni=30):
    """Ottiene i documenti in scadenza entro N giorni"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT d.*, u.nome, u.cognome, u.nome_puntato
            FROM documenti_utente d
            JOIN utenti u ON d.utente_id = u.id
            WHERE d.data_scadenza IS NOT NULL
            AND date(d.data_scadenza) <= date('now', '+' || ? || ' days')
            AND date(d.data_scadenza) >= date('now')
            ORDER BY d.data_scadenza ASC
        ''', (giorni,))
        return [dict(r) for r in cursor.fetchall()]


def get_documenti_scaduti():
    """Ottiene i documenti scaduti"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT d.*, u.nome, u.cognome, u.nome_puntato
            FROM documenti_utente d
            JOIN utenti u ON d.utente_id = u.id
            WHERE d.data_scadenza IS NOT NULL
            AND date(d.data_scadenza) < date('now')
            ORDER BY d.data_scadenza DESC
        ''')
        return [dict(r) for r in cursor.fetchall()]


# ==================== NOTE UTENTE ====================

def get_note_utente(utente_id, tipo=None):
    """Ottiene le note di un utente"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        query = 'SELECT * FROM note_utente WHERE utente_id = ?'
        params = [utente_id]
        if tipo:
            query += ' AND tipo = ?'
            params.append(tipo)
        query += ' ORDER BY data_creazione DESC'
        cursor.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]


def get_note_mensili(utente_id, anno, mese):
    """Ottiene le note di un utente per un mese specifico"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM note_utente
            WHERE utente_id = ? AND anno = ? AND mese = ?
            ORDER BY data_creazione DESC
        ''', (utente_id, anno, mese))
        return [dict(r) for r in cursor.fetchall()]


def add_nota_utente(utente_id, contenuto, tipo='generale', priorita='normale',
                    anno=None, mese=None):
    """Aggiunge una nota per un utente"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO note_utente
            (utente_id, tipo, anno, mese, contenuto, priorita, data_creazione)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (utente_id, tipo, anno, mese, contenuto, priorita,
              datetime.now().isoformat()))
        return cursor.lastrowid


def update_nota_utente(nota_id, contenuto=None, priorita=None):
    """Aggiorna una nota"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        updates = ['data_modifica = ?']
        params = [datetime.now().isoformat()]
        if contenuto is not None:
            updates.append('contenuto = ?')
            params.append(contenuto)
        if priorita is not None:
            updates.append('priorita = ?')
            params.append(priorita)
        params.append(nota_id)
        cursor.execute(f'UPDATE note_utente SET {", ".join(updates)} WHERE id = ?', params)


def delete_nota_utente(nota_id):
    """Elimina una nota"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM note_utente WHERE id = ?', (nota_id,))


# ==================== ASSENZE ====================

def get_assenze_utente(utente_id, anno=None):
    """Ottiene le assenze di un utente"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        query = 'SELECT * FROM assenze WHERE utente_id = ?'
        params = [utente_id]
        if anno:
            query += ' AND (strftime("%Y", data_inizio) = ? OR strftime("%Y", data_fine) = ?)'
            params.extend([str(anno), str(anno)])
        query += ' ORDER BY data_inizio DESC'
        cursor.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]


def get_assenze_periodo(data_inizio, data_fine):
    """Ottiene tutte le assenze in un periodo"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT a.*, u.nome, u.cognome, u.nome_puntato,
                   s.nome_completo as scuola, c.nome as commessa
            FROM assenze a
            JOIN utenti u ON a.utente_id = u.id
            JOIN scuole s ON u.scuola_id = s.id
            JOIN commesse c ON s.commessa_id = c.id
            WHERE (a.data_inizio BETWEEN ? AND ?)
               OR (a.data_fine BETWEEN ? AND ?)
               OR (a.data_inizio <= ? AND (a.data_fine >= ? OR a.data_fine IS NULL))
            ORDER BY a.data_inizio DESC
        ''', (data_inizio, data_fine, data_inizio, data_fine, data_inizio, data_fine))
        return [dict(r) for r in cursor.fetchall()]


def add_assenza(utente_id, data_inizio, tipo, data_fine=None, motivazione=None, note=None):
    """Registra un'assenza"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO assenze
            (utente_id, data_inizio, data_fine, tipo, motivazione, note, data_registrazione)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (utente_id, data_inizio, data_fine, tipo, motivazione, note,
              datetime.now().isoformat()))
        return cursor.lastrowid


def update_assenza(assenza_id, data_inizio=None, data_fine=None, tipo=None,
                   motivazione=None, note=None):
    """Aggiorna un'assenza"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        updates = []
        params = []
        if data_inizio is not None:
            updates.append('data_inizio = ?')
            params.append(data_inizio)
        if data_fine is not None:
            updates.append('data_fine = ?')
            params.append(data_fine)
        if tipo is not None:
            updates.append('tipo = ?')
            params.append(tipo)
        if motivazione is not None:
            updates.append('motivazione = ?')
            params.append(motivazione)
        if note is not None:
            updates.append('note = ?')
            params.append(note)
        if updates:
            params.append(assenza_id)
            cursor.execute(f'UPDATE assenze SET {", ".join(updates)} WHERE id = ?', params)


def delete_assenza(assenza_id):
    """Elimina un'assenza"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM assenze WHERE id = ?', (assenza_id,))


def get_report_assenze(anno, mese=None, commessa=None):
    """Report assenze per periodo"""
    with get_db_context() as conn:
        cursor = conn.cursor()

        if mese:
            # Calcola primo e ultimo giorno del mese
            data_inizio = f"{anno}-{mese:02d}-01"
            if mese == 12:
                data_fine = f"{anno+1}-01-01"
            else:
                data_fine = f"{anno}-{mese+1:02d}-01"
        else:
            data_inizio = f"{anno}-01-01"
            data_fine = f"{anno+1}-01-01"

        query = '''
            SELECT a.tipo, COUNT(*) as count,
                   COUNT(DISTINCT a.utente_id) as utenti_distinti
            FROM assenze a
            JOIN utenti u ON a.utente_id = u.id
            JOIN scuole s ON u.scuola_id = s.id
            JOIN commesse c ON s.commessa_id = c.id
            WHERE a.data_inizio >= ? AND a.data_inizio < ?
        '''
        params = [data_inizio, data_fine]

        if commessa:
            query += ' AND c.nome = ?'
            params.append(commessa)

        query += ' GROUP BY a.tipo ORDER BY count DESC'
        cursor.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]


# ==================== BUDGET ORE UTENTE ====================

def update_budget_utente(utente_id, budget_mensile=None, budget_annuale=None):
    """Aggiorna il budget ore di un utente"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        updates = []
        params = []
        if budget_mensile is not None:
            updates.append('budget_ore_mensile = ?')
            params.append(budget_mensile)
        if budget_annuale is not None:
            updates.append('budget_ore_annuale = ?')
            params.append(budget_annuale)
        if updates:
            params.append(utente_id)
            cursor.execute(f'UPDATE utenti SET {", ".join(updates)} WHERE id = ?', params)


def get_budget_status_utente(utente_id, anno_scolastico):
    """Ottiene lo stato del budget ore di un utente per l'anno scolastico"""
    with get_db_context() as conn:
        cursor = conn.cursor()

        # Ottieni dati utente
        cursor.execute('''
            SELECT id, nome, cognome, monte_ore_settimanale,
                   budget_ore_mensile, budget_ore_annuale
            FROM utenti WHERE id = ?
        ''', (utente_id,))
        utente = cursor.fetchone()
        if not utente:
            return None

        utente = dict(utente)

        # Calcola ore erogate nell'anno scolastico
        anni = anno_scolastico.split('-')
        anno_inizio = int(anni[0])
        anno_fine = int(anni[1])

        cursor.execute('''
            SELECT SUM(ore_lavorate_60) as ore_erogate
            FROM rendicontazione
            WHERE utente_id = ?
            AND ((anno = ? AND mese >= 9) OR (anno = ? AND mese <= 6))
        ''', (utente_id, anno_inizio, anno_fine))
        row = cursor.fetchone()
        ore_erogate = row['ore_erogate'] or 0

        budget_annuale = utente.get('budget_ore_annuale') or 0
        percentuale = (ore_erogate / budget_annuale * 100) if budget_annuale > 0 else 0

        return {
            'utente': utente,
            'ore_erogate': round(ore_erogate, 2),
            'budget_annuale': budget_annuale,
            'ore_rimanenti': round(budget_annuale - ore_erogate, 2),
            'percentuale_utilizzata': round(percentuale, 1)
        }


def get_utenti_budget_critico(anno_scolastico, soglia_percentuale=80):
    """Ottiene utenti che hanno superato la soglia del budget"""
    with get_db_context() as conn:
        cursor = conn.cursor()

        # Ottieni tutti gli utenti con budget definito
        cursor.execute('''
            SELECT u.id, u.nome, u.cognome, u.budget_ore_annuale,
                   s.nome_completo as scuola, c.nome as commessa
            FROM utenti u
            JOIN scuole s ON u.scuola_id = s.id
            JOIN commesse c ON s.commessa_id = c.id
            WHERE u.attivo = 1 AND u.budget_ore_annuale > 0
        ''')
        utenti = cursor.fetchall()

        anni = anno_scolastico.split('-')
        anno_inizio = int(anni[0])
        anno_fine = int(anni[1])

        risultati = []
        for u in utenti:
            u = dict(u)
            cursor.execute('''
                SELECT SUM(ore_lavorate_60) as ore_erogate
                FROM rendicontazione
                WHERE utente_id = ?
                AND ((anno = ? AND mese >= 9) OR (anno = ? AND mese <= 6))
            ''', (u['id'], anno_inizio, anno_fine))
            row = cursor.fetchone()
            ore_erogate = row['ore_erogate'] or 0

            percentuale = (ore_erogate / u['budget_ore_annuale'] * 100)
            if percentuale >= soglia_percentuale:
                risultati.append({
                    **u,
                    'ore_erogate': round(ore_erogate, 2),
                    'percentuale': round(percentuale, 1),
                    'ore_rimanenti': round(u['budget_ore_annuale'] - ore_erogate, 2)
                })

        return sorted(risultati, key=lambda x: x['percentuale'], reverse=True)


# ==================== NOTIFICHE ====================

def create_notifica(tipo, titolo, messaggio=None, entita=None, entita_id=None,
                    priorita='normale', data_scadenza=None):
    """Crea una nuova notifica"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO notifiche
            (tipo, titolo, messaggio, entita, entita_id, priorita, data_creazione, data_scadenza)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (tipo, titolo, messaggio, entita, entita_id, priorita,
              datetime.now().isoformat(), data_scadenza))
        return cursor.lastrowid


def get_notifiche(solo_non_lette=True, limit=50):
    """Ottiene le notifiche"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        query = 'SELECT * FROM notifiche WHERE archiviata = 0'
        if solo_non_lette:
            query += ' AND letta = 0'
        query += ' ORDER BY priorita DESC, data_creazione DESC LIMIT ?'
        cursor.execute(query, (limit,))
        return [dict(r) for r in cursor.fetchall()]


def mark_notifica_letta(notifica_id):
    """Segna una notifica come letta"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE notifiche SET letta = 1 WHERE id = ?', (notifica_id,))


def mark_all_notifiche_lette():
    """Segna tutte le notifiche come lette"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE notifiche SET letta = 1 WHERE letta = 0')


def archivia_notifica(notifica_id):
    """Archivia una notifica"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE notifiche SET archiviata = 1 WHERE id = ?', (notifica_id,))


def count_notifiche_non_lette():
    """Conta le notifiche non lette"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM notifiche WHERE letta = 0 AND archiviata = 0')
        return cursor.fetchone()[0]


def genera_notifiche_automatiche():
    """Genera notifiche automatiche per documenti in scadenza, budget critici, etc."""
    notifiche_generate = []

    # Documenti in scadenza (prossimi 7 giorni)
    docs_scadenza = get_documenti_in_scadenza(giorni=7)
    for doc in docs_scadenza:
        # Verifica se esiste già una notifica per questo documento
        with get_db_context() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id FROM notifiche
                WHERE entita = 'documento' AND entita_id = ? AND archiviata = 0
            ''', (doc['id'],))
            if not cursor.fetchone():
                notifica_id = create_notifica(
                    tipo='scadenza_documento',
                    titolo=f"Documento in scadenza: {doc['tipo_documento']}",
                    messaggio=f"Il documento '{doc['nome_originale']}' di {doc['nome']} {doc['cognome']} "
                              f"scade il {doc['data_scadenza']}",
                    entita='documento',
                    entita_id=doc['id'],
                    priorita='alta',
                    data_scadenza=doc['data_scadenza']
                )
                notifiche_generate.append(notifica_id)

    # Documenti scaduti
    docs_scaduti = get_documenti_scaduti()
    for doc in docs_scaduti:
        with get_db_context() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id FROM notifiche
                WHERE entita = 'documento_scaduto' AND entita_id = ? AND archiviata = 0
            ''', (doc['id'],))
            if not cursor.fetchone():
                notifica_id = create_notifica(
                    tipo='documento_scaduto',
                    titolo=f"Documento SCADUTO: {doc['tipo_documento']}",
                    messaggio=f"Il documento '{doc['nome_originale']}' di {doc['nome']} {doc['cognome']} "
                              f"e' scaduto il {doc['data_scadenza']}",
                    entita='documento_scaduto',
                    entita_id=doc['id'],
                    priorita='critica'
                )
                notifiche_generate.append(notifica_id)

    # Rendicontazione incompleta: dal giorno 20 del mese segnala gli utenti
    # ancora senza ore registrate (una sola notifica per mese)
    oggi = datetime.now()
    if oggi.day >= 20:
        anno, mese = oggi.year, oggi.month
        dati = get_rendicontazione_completa(anno, mese)
        senza_ore = [d for d in dati if not (d.get('ore_lavorate_60') or 0) > 0]
        if senza_ore:
            entita_id = anno * 100 + mese  # chiave univoca per il mese
            with get_db_context() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id FROM notifiche
                    WHERE entita = 'rendicontazione_incompleta' AND entita_id = ? AND archiviata = 0
                ''', (entita_id,))
                if not cursor.fetchone():
                    notifica_id = create_notifica(
                        tipo='rendicontazione_incompleta',
                        titolo=f"Rendicontazione incompleta: {len(senza_ore)} utenti senza ore",
                        messaggio=f"Il mese sta per chiudersi e {len(senza_ore)} utenti "
                                  f"non hanno ancora ore registrate ({oggi.strftime('%m/%Y')})",
                        entita='rendicontazione_incompleta',
                        entita_id=entita_id,
                        priorita='alta'
                    )
                    notifiche_generate.append(notifica_id)

    return notifiche_generate


# ==================== DASHBOARD WIDGETS ====================

def get_dashboard_widgets():
    """Ottiene la configurazione dei widget dashboard"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM dashboard_widgets ORDER BY ordine')
        return [dict(r) for r in cursor.fetchall()]


def update_widget_config(widget_id, attivo=None, ordine=None, configurazione=None):
    """Aggiorna la configurazione di un widget"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        updates = []
        params = []
        if attivo is not None:
            updates.append('attivo = ?')
            params.append(1 if attivo else 0)
        if ordine is not None:
            updates.append('ordine = ?')
            params.append(ordine)
        if configurazione is not None:
            updates.append('configurazione = ?')
            params.append(configurazione)
        if updates:
            params.append(widget_id)
            cursor.execute(f'UPDATE dashboard_widgets SET {", ".join(updates)} WHERE widget_id = ?', params)


def init_default_widgets():
    """Inizializza i widget di default"""
    default_widgets = [
        ('stats_generali', 'Statistiche Generali', 'stats', 1, 0),
        ('utenti_commessa', 'Utenti per Commessa', 'chart', 1, 1),
        ('trend_ore', 'Trend Ore Mensili', 'chart', 1, 2),
        ('alerts', 'Alert e Notifiche', 'alerts', 1, 3),
        ('documenti_scadenza', 'Documenti in Scadenza', 'list', 1, 4),
        ('budget_critico', 'Budget Critici', 'list', 1, 5),
        ('ultimi_accessi', 'Attivita Recente', 'list', 0, 6),
    ]

    with get_db_context() as conn:
        cursor = conn.cursor()
        for widget_id, titolo, tipo, attivo, ordine in default_widgets:
            cursor.execute('''
                INSERT OR IGNORE INTO dashboard_widgets
                (widget_id, titolo, tipo, attivo, ordine)
                VALUES (?, ?, ?, ?, ?)
            ''', (widget_id, titolo, tipo, attivo, ordine))


# ==================== STORICO ORE UTENTE ====================

def get_storico_ore_utente(utente_id, anno_scolastico=None):
    """Ottiene lo storico completo delle ore di un utente"""
    with get_db_context() as conn:
        cursor = conn.cursor()

        query = '''
            SELECT r.*,
                CASE
                    WHEN UPPER(COALESCE(s.nome_completo, '')) LIKE '%INFANZIA%' THEN c.giorni_lavorativi
                    ELSE COALESCE(c.giorni_lavorativi_altri, c.giorni_lavorativi)
                END as giorni_calendario
            FROM rendicontazione r
            JOIN utenti u ON u.id = r.utente_id
            JOIN scuole s ON s.id = u.scuola_id
            LEFT JOIN calendario_scolastico c ON
                c.anno = r.anno AND c.mese = r.mese
            WHERE r.utente_id = ?
        '''
        params = [utente_id]

        if anno_scolastico:
            anni = anno_scolastico.split('-')
            anno_inizio = int(anni[0])
            anno_fine = int(anni[1])
            query += '''
                AND ((r.anno = ? AND r.mese >= 9) OR (r.anno = ? AND r.mese <= 6))
            '''
            params.extend([anno_inizio, anno_fine])

        query += ' ORDER BY r.anno DESC, r.mese DESC'
        cursor.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]


def get_totali_utente(utente_id, anno_scolastico=None):
    """Ottiene i totali cumulativi di un utente"""
    storico = get_storico_ore_utente(utente_id, anno_scolastico)

    totale_ore = sum(r.get('ore_lavorate_60') or 0 for r in storico)
    totale_pasti = sum(r.get('pasti') or 0 for r in storico)
    mesi_attivi = len([r for r in storico if (r.get('ore_lavorate_60') or 0) > 0])

    return {
        'totale_ore': round(totale_ore, 2),
        'totale_pasti': totale_pasti,
        'mesi_attivi': mesi_attivi,
        'media_ore_mese': round(totale_ore / mesi_attivi, 2) if mesi_attivi > 0 else 0
    }


# ==================== REPORT CENTRATI SUGLI UTENTI ====================

def get_classifica_utenti_ore(anno, mese=None, limit=20, order='desc'):
    """Classifica utenti per ore ricevute"""
    with get_db_context() as conn:
        cursor = conn.cursor()

        query = '''
            SELECT u.id, u.nome, u.cognome, u.nome_puntato,
                   s.nome_completo as scuola, c.nome as commessa,
                   SUM(r.ore_lavorate_60) as ore_totali,
                   SUM(r.pasti) as pasti_totali,
                   COUNT(DISTINCT r.mese) as mesi_attivi
            FROM utenti u
            JOIN scuole s ON u.scuola_id = s.id
            JOIN commesse c ON s.commessa_id = c.id
            LEFT JOIN rendicontazione r ON u.id = r.utente_id AND r.anno = ?
        '''
        params = [anno]

        if mese:
            query += ' AND r.mese = ?'
            params.append(mese)

        query += '''
            WHERE u.attivo = 1
            GROUP BY u.id
            ORDER BY ore_totali ''' + ('DESC' if order == 'desc' else 'ASC') + '''
            LIMIT ?
        '''
        params.append(limit)

        cursor.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]


def get_confronto_utenti(utente_ids, anno_scolastico):
    """Confronta ore tra più utenti"""
    risultati = []
    for utente_id in utente_ids:
        utente = get_utente_by_id(utente_id)
        if utente:
            totali = get_totali_utente(utente_id, anno_scolastico)
            risultati.append({
                **utente,
                **totali
            })
    return risultati


def get_andamento_utente(utente_id, ultimi_mesi=12):
    """Ottiene l'andamento ore di un utente negli ultimi N mesi"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT anno, mese, ore_lavorate_60, pasti, giorni_lavorativi
            FROM rendicontazione
            WHERE utente_id = ?
            ORDER BY anno DESC, mese DESC
            LIMIT ?
        ''', (utente_id, ultimi_mesi))
        return [dict(r) for r in cursor.fetchall()][::-1]  # Inverti per ordine cronologico


# ==================== ALERT AUTOMATICI ====================

def get_alerts(anno, mese):
    """Genera alert automatici basati sui dati del mese"""
    alerts = []
    dati = get_rendicontazione_completa(anno, mese)

    for d in dati:
        ore_previste = d.get('media_con_assenza_60', 0) or 0
        ore_erogate = d.get('ore_lavorate_60', 0) or 0

        if ore_previste > 0:
            tasso = (ore_erogate / ore_previste) * 100

            # Alert: erogazione sotto il 30%
            if 0 < tasso < 30:
                alerts.append({
                    'tipo': 'danger',
                    'categoria': 'erogazione_bassa',
                    'titolo': f'Erogazione critica: {d["nome"]} {d["cognome"]}',
                    'dettaglio': f'{tasso:.0f}% delle ore previste ({ore_erogate:.1f}/{ore_previste:.1f}h)',
                    'utente_id': d['utente_id'],
                    'scuola': d.get('scuola', ''),
                    'commessa': d.get('commessa', '')
                })
            # Alert: erogazione tra 30% e 60%
            elif 30 <= tasso < 60:
                alerts.append({
                    'tipo': 'warning',
                    'categoria': 'erogazione_bassa',
                    'titolo': f'Erogazione sotto media: {d["nome"]} {d["cognome"]}',
                    'dettaglio': f'{tasso:.0f}% delle ore previste ({ore_erogate:.1f}/{ore_previste:.1f}h)',
                    'utente_id': d['utente_id'],
                    'scuola': d.get('scuola', ''),
                    'commessa': d.get('commessa', '')
                })

            # Alert: erogazione oltre il 110%
            if tasso > 110:
                alerts.append({
                    'tipo': 'info',
                    'categoria': 'erogazione_alta',
                    'titolo': f'Superamento ore: {d["nome"]} {d["cognome"]}',
                    'dettaglio': f'{tasso:.0f}% delle ore previste ({ore_erogate:.1f}/{ore_previste:.1f}h)',
                    'utente_id': d['utente_id'],
                    'scuola': d.get('scuola', ''),
                    'commessa': d.get('commessa', '')
                })

        # Alert: utente senza ore (ma con monte ore assegnato)
        if ore_erogate == 0 and (d.get('monte_ore_settimanale', 0) or 0) > 0:
            alerts.append({
                'tipo': 'warning',
                'categoria': 'zero_ore',
                'titolo': f'Nessuna ora registrata: {d["nome"]} {d["cognome"]}',
                'dettaglio': f'Monte ore settimanale: {d["monte_ore_settimanale"]}h - Scuola: {d.get("scuola", "")}',
                'utente_id': d['utente_id'],
                'scuola': d.get('scuola', ''),
                'commessa': d.get('commessa', '')
            })

    # Ordina: danger prima, poi warning, poi info
    priority = {'danger': 0, 'warning': 1, 'info': 2}
    alerts.sort(key=lambda x: priority.get(x['tipo'], 3))

    return alerts


# ==================== AUDIT TRAIL ====================

def log_audit(azione, entita, entita_id=None, dettagli=None, dati_precedenti=None, dati_nuovi=None):
    """Registra un'azione nell'audit trail"""
    try:
        with get_db_context() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO audit_log (timestamp, azione, entita, entita_id, dettagli, dati_precedenti, dati_nuovi)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(),
                azione,
                entita,
                entita_id,
                dettagli,
                str(dati_precedenti) if dati_precedenti else None,
                str(dati_nuovi) if dati_nuovi else None
            ))
    except Exception as e:
        logger.error(f"Errore audit log: {e}")


def get_audit_log(limit=100, entita=None):
    """Ottiene le ultime azioni dall'audit trail"""
    with get_db_context() as conn:
        cursor = conn.cursor()

        query = "SELECT * FROM audit_log"
        params = []

        if entita:
            query += " WHERE entita = ?"
            params.append(entita)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]


# ==================== DIPENDENTI (operatori OEPAC) ====================

# Campi "core" della tabella dipendenti; tutto il resto va in dati_extra (JSON).
DIPENDENTE_CAMPI = [
    'nome', 'cognome', 'codice_fiscale', 'email', 'telefono', 'qualifica',
    'sede', 'commessa_id', 'ore_contrattuali_settimanali',
    'data_assunzione', 'data_cessazione', 'note',
]


def _dipendente_to_dict(row):
    d = dict(row)
    extra = d.pop('dati_extra', None)
    try:
        d['extra'] = json.loads(extra) if extra else {}
    except (ValueError, TypeError):
        d['extra'] = {}
    return d


def get_all_dipendenti(include_inactive=False, search=None, commessa_id=None):
    """Elenco dipendenti, con ricerca opzionale per nome/cognome/CF."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        query = '''
            SELECT d.*, c.nome as commessa
            FROM dipendenti d
            LEFT JOIN commesse c ON d.commessa_id = c.id
            WHERE 1=1
        '''
        params = []
        if not include_inactive:
            query += ' AND d.attivo = 1'
        if commessa_id:
            query += ' AND d.commessa_id = ?'
            params.append(commessa_id)
        if search:
            query += ' AND (LOWER(d.nome) LIKE ? OR LOWER(d.cognome) LIKE ? OR LOWER(d.codice_fiscale) LIKE ?)'
            s = f"%{search.lower()}%"
            params += [s, s, s]
        query += ' ORDER BY d.cognome, d.nome'
        cursor.execute(query, params)
        return [_dipendente_to_dict(r) for r in cursor.fetchall()]


def get_dipendente(dipendente_id):
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT d.*, c.nome as commessa
            FROM dipendenti d
            LEFT JOIN commesse c ON d.commessa_id = c.id
            WHERE d.id = ?
        ''', (dipendente_id,))
        r = cursor.fetchone()
        return _dipendente_to_dict(r) if r else None


def create_dipendente(data):
    """Crea un dipendente. data: dict con i campi core + 'extra' (dict) opzionale."""
    campi = {k: data.get(k) for k in DIPENDENTE_CAMPI}
    if not (campi.get('nome') and campi.get('cognome')):
        raise ValueError('Nome e cognome sono obbligatori')
    extra = data.get('extra') or {}
    with get_db_context() as conn:
        cursor = conn.cursor()
        cols = list(campi.keys()) + ['dati_extra', 'attivo', 'data_inserimento']
        vals = list(campi.values()) + [json.dumps(extra, ensure_ascii=False), 1, datetime.now().isoformat()]
        placeholders = ', '.join('?' * len(cols))
        cursor.execute(f"INSERT INTO dipendenti ({', '.join(cols)}) VALUES ({placeholders})", vals)
        return cursor.lastrowid


def update_dipendente(dipendente_id, data):
    sets, params = [], []
    for k in DIPENDENTE_CAMPI:
        if k in data:
            sets.append(f"{k} = ?")
            params.append(data[k])
    if 'extra' in data:
        sets.append("dati_extra = ?")
        params.append(json.dumps(data['extra'] or {}, ensure_ascii=False))
    if 'attivo' in data:
        sets.append("attivo = ?")
        params.append(1 if data['attivo'] else 0)
    if not sets:
        return
    params.append(dipendente_id)
    with get_db_context() as conn:
        conn.cursor().execute(f"UPDATE dipendenti SET {', '.join(sets)} WHERE id = ?", params)


def delete_dipendente(dipendente_id):
    """Disattiva un dipendente (soft delete)."""
    with get_db_context() as conn:
        conn.cursor().execute("UPDATE dipendenti SET attivo = 0 WHERE id = ?", (dipendente_id,))


# ==================== ASSEGNAZIONI (utente <-> operatore) ====================

def get_assegnazioni_utente(utente_id):
    """Operatori assegnati a un assistito, con nome operatore."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT a.*, d.nome as dip_nome, d.cognome as dip_cognome,
                   d.attivo as dip_attivo
            FROM assegnazioni a
            JOIN dipendenti d ON a.dipendente_id = d.id
            WHERE a.utente_id = ?
            ORDER BY d.cognome, d.nome
        ''', (utente_id,))
        return [dict(r) for r in cursor.fetchall()]


def get_assistiti_dipendente(dipendente_id):
    """Assistiti seguiti da un operatore, con scuola e ore assegnate."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT a.*, u.nome as ut_nome, u.cognome as ut_cognome,
                   s.nome_completo as scuola, c.nome as commessa
            FROM assegnazioni a
            JOIN utenti u ON a.utente_id = u.id
            LEFT JOIN scuole s ON u.scuola_id = s.id
            LEFT JOIN commesse c ON s.commessa_id = c.id
            WHERE a.dipendente_id = ? AND u.attivo = 1
            ORDER BY u.cognome, u.nome
        ''', (dipendente_id,))
        return [dict(r) for r in cursor.fetchall()]


def get_bilancio_assegnazioni_utente(utente_id):
    """Confronta il monte ore settimanale dell'assistito con la somma delle ore
    assegnate agli operatori. Ritorna monte_ore, assegnate, differenza, stato."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT monte_ore_settimanale FROM utenti WHERE id = ?", (utente_id,))
        r = cursor.fetchone()
        monte = (r['monte_ore_settimanale'] if r else 0) or 0
        cursor.execute("SELECT COALESCE(SUM(ore_settimanali), 0) as tot FROM assegnazioni WHERE utente_id = ?", (utente_id,))
        assegnate = cursor.fetchone()['tot'] or 0
    diff = round(assegnate - monte, 2)
    if abs(diff) < 0.01:
        stato = 'ok'
    elif diff < 0:
        stato = 'sotto'   # mancano ore da assegnare
    else:
        stato = 'sopra'   # assegnate piu' ore del monte
    return {'monte_ore': round(monte, 2), 'assegnate': round(assegnate, 2),
            'differenza': diff, 'stato': stato}


def create_assegnazione(utente_id, dipendente_id, ore_settimanali, valido_da=None, valido_a=None, note=None):
    if (ore_settimanali or 0) < 0:
        raise ValueError('Le ore settimanali non possono essere negative')
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO assegnazioni (utente_id, dipendente_id, ore_settimanali, valido_da, valido_a, note, data_inserimento)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (utente_id, dipendente_id, ore_settimanali, valido_da or None, valido_a or None,
              note, datetime.now().isoformat()))
        return cursor.lastrowid


def update_assegnazione(assegnazione_id, ore_settimanali=None, valido_da=None, valido_a=None, note=None):
    sets, params = [], []
    if ore_settimanali is not None:
        if ore_settimanali < 0:
            raise ValueError('Le ore settimanali non possono essere negative')
        sets.append("ore_settimanali = ?"); params.append(ore_settimanali)
    # valido_da/valido_a/note: passa stringa per impostare, '' per azzerare
    if valido_da is not None:
        sets.append("valido_da = ?"); params.append(valido_da or None)
    if valido_a is not None:
        sets.append("valido_a = ?"); params.append(valido_a or None)
    if note is not None:
        sets.append("note = ?"); params.append(note)
    if not sets:
        return
    params.append(assegnazione_id)
    with get_db_context() as conn:
        conn.cursor().execute(f"UPDATE assegnazioni SET {', '.join(sets)} WHERE id = ?", params)


def delete_assegnazione(assegnazione_id):
    with get_db_context() as conn:
        conn.cursor().execute("DELETE FROM assegnazioni WHERE id = ?", (assegnazione_id,))


def importa_dipendenti(records):
    """Importa/aggiorna dipendenti da una lista di record (vedi import_dipendenti).
    Abbina per Codice Fiscale, altrimenti per nome+cognome. Idempotente.
    Ritorna {'creati', 'aggiornati', 'errori': [...]}."""
    import import_dipendenti as imp_mod
    creati = aggiornati = 0
    errori = []

    with get_db_context() as conn:
        cursor = conn.cursor()
        # Indici degli esistenti
        cursor.execute("SELECT id, nome, cognome, codice_fiscale FROM dipendenti")
        per_cf, per_nome = {}, {}
        for row in cursor.fetchall():
            if row['codice_fiscale']:
                per_cf[imp_mod.chiave_cf(row['codice_fiscale'])] = row['id']
            per_nome[imp_mod.chiave_nome(row['nome'], row['cognome'])] = row['id']

        now = datetime.now().isoformat()
        for rec in records:
            try:
                cf = imp_mod.chiave_cf(rec.get('codice_fiscale'))
                # Con CF presente abbiniamo SOLO per CF (due persone possono avere
                # lo stesso nome): il fallback per nome vale solo senza CF.
                if cf:
                    esistente = per_cf.get(cf)
                else:
                    esistente = per_nome.get(imp_mod.chiave_nome(rec.get('nome', ''), rec.get('cognome', '')))

                campi = {k: rec.get(k) for k in DIPENDENTE_CAMPI if k in rec}
                extra_json = json.dumps(rec.get('extra') or {}, ensure_ascii=False)

                if esistente:
                    sets = [f"{k} = ?" for k in campi] + ['dati_extra = ?']
                    params = list(campi.values()) + [extra_json, esistente]
                    cursor.execute(f"UPDATE dipendenti SET {', '.join(sets)} WHERE id = ?", params)
                    aggiornati += 1
                else:
                    cols = list(campi.keys()) + ['dati_extra', 'attivo', 'data_inserimento']
                    vals = list(campi.values()) + [extra_json, 1, now]
                    ph = ', '.join('?' * len(cols))
                    cursor.execute(f"INSERT INTO dipendenti ({', '.join(cols)}) VALUES ({ph})", vals)
                    nuovo_id = cursor.lastrowid
                    creati += 1
                    if cf:
                        per_cf[cf] = nuovo_id
                    per_nome[imp_mod.chiave_nome(rec.get('nome', ''), rec.get('cognome', ''))] = nuovo_id
            except Exception as e:
                errori.append(f"{rec.get('cognome','')} {rec.get('nome','')}: {e}")

    return {'creati': creati, 'aggiornati': aggiornati, 'errori': errori}


def count_assegnazioni_dipendente(dipendente_id):
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) as n, COALESCE(SUM(ore_settimanali), 0) as ore
            FROM assegnazioni a JOIN utenti u ON a.utente_id = u.id
            WHERE a.dipendente_id = ? AND u.attivo = 1
        ''', (dipendente_id,))
        r = cursor.fetchone()
        return {'assistiti': r['n'], 'ore_assegnate': round(r['ore'] or 0, 2)}


def count_assegnazioni_bulk():
    """Conteggio assistiti e ore assegnate per TUTTI i dipendenti in una query.
    Ritorna {dipendente_id: {'assistiti': n, 'ore_assegnate': ore}}."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT a.dipendente_id, COUNT(*) as n, COALESCE(SUM(a.ore_settimanali), 0) as ore
            FROM assegnazioni a JOIN utenti u ON a.utente_id = u.id
            WHERE u.attivo = 1
            GROUP BY a.dipendente_id
        ''')
        return {r['dipendente_id']: {'assistiti': r['n'], 'ore_assegnate': round(r['ore'] or 0, 2)}
                for r in cursor.fetchall()}


# ==================== TURNI (planner settimanale) ====================

GIORNI_NOMI = ['Lunedì', 'Martedì', 'Mercoledì', 'Giovedì', 'Venerdì', 'Sabato', 'Domenica']


def _norm_ora(s):
    """Normalizza un orario in 'HH:MM' (così il confronto fra stringhe è corretto)."""
    s = (str(s) if s is not None else '').strip()
    m = re.match(r'^(\d{1,2}):(\d{2})', s)
    if not m:
        return s
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _turno_valido_in_data(t, data_str):
    """Il turno è valido nella data (YYYY-MM-DD) data la finestra valido_da/valido_a?"""
    if t.get('valido_da') and data_str < t['valido_da']:
        return False
    if t.get('valido_a') and data_str > t['valido_a']:
        return False
    return True


def _overlap(a_in, a_fin, b_in, b_fin):
    """True se gli intervalli [a_in,a_fin) e [b_in,b_fin) si sovrappongono (orari 'HH:MM')."""
    return a_in < b_fin and b_in < a_fin


def _ora_valida(s):
    return bool(re.match(r'^([01]\d|2[0-3]):[0-5]\d$', _norm_ora(s)))


def _periodi_sovrapposti(da1, a1, da2, a2):
    """Due finestre di validità (date 'YYYY-MM-DD', None = aperta) si sovrappongono?"""
    da1, a1 = da1 or '0000-00-00', a1 or '9999-99-99'
    da2, a2 = da2 or '0000-00-00', a2 or '9999-99-99'
    return da1 <= a2 and da2 <= a1


def _verifica_turno(cursor, dipendente_id, giorno, ora_inizio, ora_fine,
                    valido_da, valido_a, escludi_id=None):
    """Valida orari e segnala sovrapposizioni con altri turni dello stesso
    operatore nello stesso giorno (con finestre di validità sovrapposte).
    Solleva ValueError con messaggio chiaro."""
    oi, of = _norm_ora(ora_inizio), _norm_ora(ora_fine)
    if not _ora_valida(oi) or not _ora_valida(of):
        raise ValueError('Orario non valido')
    if oi >= of:
        raise ValueError("L'ora di fine deve essere successiva a quella di inizio")
    if valido_da and valido_a and valido_da > valido_a:
        raise ValueError('La data "valido da" deve precedere "valido a"')
    cursor.execute('SELECT id, ora_inizio, ora_fine, valido_da, valido_a FROM turni WHERE dipendente_id = ? AND giorno = ?',
                   (dipendente_id, int(giorno)))
    for r in cursor.fetchall():
        if escludi_id and r['id'] == escludi_id:
            continue
        if _overlap(oi, of, r['ora_inizio'], r['ora_fine']) and \
           _periodi_sovrapposti(valido_da, valido_a, r['valido_da'], r['valido_a']):
            raise ValueError(f"Si sovrappone a un turno esistente ({r['ora_inizio']}–{r['ora_fine']})")


def get_turni_dipendente(dipendente_id, data=None):
    """Turni settimanali di un operatore (opzionalmente validi in una data)."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT t.*, s.nome_completo as scuola, u.nome as ut_nome, u.cognome as ut_cognome
            FROM turni t
            LEFT JOIN scuole s ON t.scuola_id = s.id
            LEFT JOIN utenti u ON t.utente_id = u.id
            WHERE t.dipendente_id = ?
            ORDER BY t.giorno, t.ora_inizio
        ''', (dipendente_id,))
        turni = [dict(r) for r in cursor.fetchall()]
    if data:
        turni = [t for t in turni if _turno_valido_in_data(t, data)]
    return turni


def get_turni_giorno(giorno, data=None, scuola_id=None):
    """Tutti i turni in un giorno della settimana (vista giornaliera)."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        q = '''
            SELECT t.*, s.nome_completo as scuola,
                   d.nome as dip_nome, d.cognome as dip_cognome,
                   u.nome as ut_nome, u.cognome as ut_cognome
            FROM turni t
            JOIN dipendenti d ON t.dipendente_id = d.id
            LEFT JOIN scuole s ON t.scuola_id = s.id
            LEFT JOIN utenti u ON t.utente_id = u.id
            WHERE t.giorno = ? AND d.attivo = 1
        '''
        params = [giorno]
        if scuola_id:
            q += ' AND t.scuola_id = ?'
            params.append(scuola_id)
        q += ' ORDER BY t.ora_inizio, d.cognome'
        cursor.execute(q, params)
        turni = [dict(r) for r in cursor.fetchall()]
    if data:
        turni = [t for t in turni if _turno_valido_in_data(t, data)]
    return turni


def create_turno(dipendente_id, giorno, ora_inizio, ora_fine, scuola_id=None,
                 utente_id=None, valido_da=None, valido_a=None, note=None):
    with get_db_context() as conn:
        cursor = conn.cursor()
        _verifica_turno(cursor, dipendente_id, giorno, ora_inizio, ora_fine,
                        valido_da or None, valido_a or None)
        cursor.execute('''
            INSERT INTO turni (dipendente_id, giorno, ora_inizio, ora_fine, scuola_id,
                               utente_id, valido_da, valido_a, note, data_inserimento)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (dipendente_id, int(giorno), _norm_ora(ora_inizio), _norm_ora(ora_fine),
              scuola_id or None, utente_id or None, valido_da or None, valido_a or None,
              note, datetime.now().isoformat()))
        return cursor.lastrowid


def update_turno(turno_id, **campi):
    consentiti = ['giorno', 'ora_inizio', 'ora_fine', 'scuola_id', 'utente_id',
                  'valido_da', 'valido_a', 'note']
    sets, params = [], []
    for k in consentiti:
        if k in campi:
            v = campi[k]
            if k in ('ora_inizio', 'ora_fine'):
                v = _norm_ora(v)
            if k in ('scuola_id', 'utente_id', 'valido_da', 'valido_a'):
                v = v or None
            sets.append(f"{k} = ?")
            params.append(v)
    if not sets:
        return
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM turni WHERE id = ?", (turno_id,))
        cur = cursor.fetchone()
        if not cur:
            return
        m = dict(cur)
        m.update({k: campi[k] for k in consentiti if k in campi})
        _verifica_turno(cursor, m['dipendente_id'], m['giorno'], m['ora_inizio'],
                        m['ora_fine'], m['valido_da'] or None, m['valido_a'] or None,
                        escludi_id=turno_id)
        params.append(turno_id)
        cursor.execute(f"UPDATE turni SET {', '.join(sets)} WHERE id = ?", params)


def delete_turno(turno_id):
    with get_db_context() as conn:
        conn.cursor().execute("DELETE FROM turni WHERE id = ?", (turno_id,))


def ore_settimanali_pianificate(dipendente_id):
    """Somma (in ore) della durata dei turni settimanali di un operatore."""
    tot = 0.0
    for t in get_turni_dipendente(dipendente_id):
        try:
            hi, mi = map(int, t['ora_inizio'].split(':'))
            hf, mf = map(int, t['ora_fine'].split(':'))
            tot += max(0, (hf * 60 + mf) - (hi * 60 + mi)) / 60.0
        except (ValueError, AttributeError):
            pass
    return round(tot, 2)


# ==================== ASSENZE DIPENDENTI ====================

def get_assenze_dipendente(dipendente_id):
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''SELECT * FROM assenze_dipendenti WHERE dipendente_id = ?
                          ORDER BY data_inizio DESC''', (dipendente_id,))
        return [dict(r) for r in cursor.fetchall()]


def dipendente_assente_in_data(dipendente_id, data_str):
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 1 FROM assenze_dipendenti
            WHERE dipendente_id = ? AND data_inizio <= ?
              AND (data_fine IS NULL OR data_fine >= ?) LIMIT 1
        ''', (dipendente_id, data_str, data_str))
        return cursor.fetchone() is not None


def create_assenza_dipendente(dipendente_id, data_inizio, data_fine=None, tipo=None,
                              motivazione=None, note=None):
    if data_fine and data_fine < data_inizio:
        raise ValueError('La data di fine non può precedere quella di inizio')
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO assenze_dipendenti (dipendente_id, data_inizio, data_fine, tipo,
                                            motivazione, note, data_registrazione)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (dipendente_id, data_inizio, data_fine or None, tipo, motivazione, note,
              datetime.now().isoformat()))
        return cursor.lastrowid


def delete_assenza_dipendente(assenza_id):
    with get_db_context() as conn:
        conn.cursor().execute("DELETE FROM assenze_dipendenti WHERE id = ?", (assenza_id,))


def get_turni_occorrenze(dipendente_id, data_inizio, data_fine):
    """Espande i turni settimanali di un operatore nelle occorrenze concrete
    (date) comprese nel periodo [data_inizio, data_fine]. Utile per sapere quali
    turni vanno coperti durante un'assenza."""
    from datetime import timedelta
    d0 = datetime.strptime(data_inizio, '%Y-%m-%d').date()
    d1 = datetime.strptime(data_fine, '%Y-%m-%d').date()
    turni = get_turni_dipendente(dipendente_id)
    occorrenze = []
    giorno_corr = d0
    while giorno_corr <= d1:
        ds = giorno_corr.isoformat()
        wd = giorno_corr.weekday()  # 0=Lun
        for t in turni:
            if t['giorno'] == wd and _turno_valido_in_data(t, ds):
                occ = dict(t)
                occ['data'] = ds
                occorrenze.append(occ)
        giorno_corr += timedelta(days=1)
    return occorrenze


# ==================== SOSTITUZIONI ====================

def _scuole_operatore(dipendente_id):
    """Insieme degli id-scuola dove l'operatore opera (da turni o assegnazioni)."""
    scuole = set()
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT scuola_id FROM turni WHERE dipendente_id = ? AND scuola_id IS NOT NULL", (dipendente_id,))
        scuole.update(r['scuola_id'] for r in cursor.fetchall())
        cursor.execute('''SELECT DISTINCT u.scuola_id FROM assegnazioni a
                          JOIN utenti u ON a.utente_id = u.id
                          WHERE a.dipendente_id = ? AND u.scuola_id IS NOT NULL''', (dipendente_id,))
        scuole.update(r['scuola_id'] for r in cursor.fetchall())
    return scuole


def suggerisci_sostituti(scuola_id, giorno, ora_inizio, ora_fine, data, escludi_id):
    """Operatori candidati a sostituire, ordinati per criterio:
    1) liberi in quella fascia E che operano in quella scuola
    2) liberi in quella fascia (altrove)
    'libero' = nessun turno sovrapposto valido in quella data e non assente.
    Tutti i dati vengono caricati in blocco (poche query) e filtrati in memoria."""
    ora_inizio, ora_fine = _norm_ora(ora_inizio), _norm_ora(ora_fine)
    with get_db_context() as conn:
        cursor = conn.cursor()
        # Assenti nella data (1 query)
        cursor.execute('''SELECT dipendente_id FROM assenze_dipendenti
                          WHERE data_inizio <= ? AND (data_fine IS NULL OR data_fine >= ?)''',
                       (data, data))
        assenti = {r['dipendente_id'] for r in cursor.fetchall()}

        # Turni di quel giorno validi nella data, per dipendente (1 query)
        cursor.execute('''SELECT dipendente_id, ora_inizio, ora_fine FROM turni
                          WHERE giorno = ?
                            AND (valido_da IS NULL OR valido_da <= ?)
                            AND (valido_a IS NULL OR valido_a >= ?)''',
                       (giorno, data, data))
        turni_per_dip = {}
        for r in cursor.fetchall():
            turni_per_dip.setdefault(r['dipendente_id'], []).append((r['ora_inizio'], r['ora_fine']))

        # Scuole di ogni operatore (turni + assegnazioni) in 1 query
        cursor.execute('''
            SELECT dipendente_id, scuola_id FROM turni WHERE scuola_id IS NOT NULL
            UNION
            SELECT a.dipendente_id, u.scuola_id FROM assegnazioni a
            JOIN utenti u ON a.utente_id = u.id WHERE u.scuola_id IS NOT NULL
        ''')
        scuole_per_dip = {}
        for r in cursor.fetchall():
            scuole_per_dip.setdefault(r['dipendente_id'], set()).add(r['scuola_id'])

    candidati = []
    for d in get_all_dipendenti():
        if d['id'] == escludi_id or d['id'] in assenti:
            continue
        occupato = any(_overlap(ora_inizio, ora_fine, oi, of)
                       for oi, of in turni_per_dip.get(d['id'], []))
        if occupato:
            continue
        stessa_scuola = bool(scuola_id) and scuola_id in scuole_per_dip.get(d['id'], set())
        candidati.append({
            'id': d['id'],
            'nome': f"{d['cognome']} {d['nome']}",
            'stessa_scuola': stessa_scuola,
            'priorita': 1 if stessa_scuola else 2,
        })
    candidati.sort(key=lambda c: (c['priorita'], c['nome']))
    return candidati


def get_sostituzioni(data_inizio=None, data_fine=None, solo_da_coprire=False):
    with get_db_context() as conn:
        cursor = conn.cursor()
        q = '''
            SELECT so.*, t.giorno, t.ora_inizio, t.ora_fine, t.scuola_id,
                   sc.nome_completo as scuola,
                   da.cognome as assente_cognome, da.nome as assente_nome,
                   ds.cognome as sost_cognome, ds.nome as sost_nome
            FROM sostituzioni so
            LEFT JOIN turni t ON so.turno_id = t.id
            LEFT JOIN scuole sc ON t.scuola_id = sc.id
            LEFT JOIN dipendenti da ON so.assente_id = da.id
            LEFT JOIN dipendenti ds ON so.sostituto_id = ds.id
            WHERE 1=1
        '''
        params = []
        if data_inizio:
            q += ' AND so.data >= ?'; params.append(data_inizio)
        if data_fine:
            q += ' AND so.data <= ?'; params.append(data_fine)
        if solo_da_coprire:
            q += " AND so.stato = 'da_coprire'"
        q += ' ORDER BY so.data, t.ora_inizio'
        cursor.execute(q, params)
        return [dict(r) for r in cursor.fetchall()]


def crea_sostituzioni_per_assenza(assenza_id):
    """Per ogni occorrenza di turno coperta dall'assenza crea una riga
    sostituzione 'da_coprire' (se non esiste già). Ritorna quante create."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM assenze_dipendenti WHERE id = ?", (assenza_id,))
        a = cursor.fetchone()
        if not a:
            return 0
        a = dict(a)
    data_fine = a['data_fine'] or a['data_inizio']
    occ = get_turni_occorrenze(a['dipendente_id'], a['data_inizio'], data_fine)
    create = 0
    with get_db_context() as conn:
        cursor = conn.cursor()
        for o in occ:
            cursor.execute('''SELECT 1 FROM sostituzioni WHERE turno_id = ? AND data = ? LIMIT 1''',
                           (o['id'], o['data']))
            if cursor.fetchone():
                continue
            cursor.execute('''
                INSERT INTO sostituzioni (turno_id, data, assente_id, assenza_id, stato, data_inserimento)
                VALUES (?, ?, ?, ?, 'da_coprire', ?)
            ''', (o['id'], o['data'], a['dipendente_id'], assenza_id, datetime.now().isoformat()))
            create += 1
    return create


def assegna_sostituto(sostituzione_id, sostituto_id):
    """Assegna un sostituto, ma solo se è davvero disponibile in quella fascia
    (non assente, nessun turno sovrapposto). Solleva ValueError altrimenti."""
    s = get_sostituzione(sostituzione_id)
    if not s:
        raise ValueError('Sostituzione non trovata')
    if s.get('giorno') is not None:
        disponibili = {c['id'] for c in suggerisci_sostituti(
            s.get('scuola_id'), s['giorno'], s['ora_inizio'], s['ora_fine'],
            s['data'], escludi_id=s['assente_id'])}
        if sostituto_id not in disponibili:
            raise ValueError('Operatore non disponibile in quella fascia (occupato o assente)')
    with get_db_context() as conn:
        conn.cursor().execute(
            "UPDATE sostituzioni SET sostituto_id = ?, stato = 'coperta' WHERE id = ?",
            (sostituto_id, sostituzione_id))


def annulla_sostituto(sostituzione_id):
    with get_db_context() as conn:
        conn.cursor().execute(
            "UPDATE sostituzioni SET sostituto_id = NULL, stato = 'da_coprire' WHERE id = ?",
            (sostituzione_id,))


def get_sostituzione(sostituzione_id):
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''SELECT so.*, t.giorno, t.ora_inizio, t.ora_fine, t.scuola_id
                          FROM sostituzioni so LEFT JOIN turni t ON so.turno_id = t.id
                          WHERE so.id = ?''', (sostituzione_id,))
        r = cursor.fetchone()
        return dict(r) if r else None


# ==================== BACKUP ====================

def create_backup():
    """Crea un backup del database"""
    os.makedirs(config.BACKUP_FOLDER, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f"gestionale_backup_{timestamp}.db"
    backup_path = os.path.join(config.BACKUP_FOLDER, backup_name)

    try:
        # API di backup online di SQLite: produce una copia consistente anche
        # con DB in uso e journal WAL (a differenza di copiare solo il file .db,
        # che potrebbe perdere le modifiche ancora nel -wal).
        if not os.path.exists(DATABASE_PATH):
            logger.warning("Backup saltato: database non ancora presente")
            return None
        src = sqlite3.connect(DATABASE_PATH)
        try:
            dst = sqlite3.connect(backup_path)
            try:
                with dst:
                    src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        logger.info(f"Backup creato: {backup_name}")

        # Pulizia backup vecchi
        cleanup_old_backups()

        return backup_name
    except Exception as e:
        logger.error(f"Errore creazione backup: {e}")
        return None


def cleanup_old_backups():
    """Rimuove i backup piu' vecchi oltre il limite"""
    backup_dir = config.BACKUP_FOLDER
    if not os.path.exists(backup_dir):
        return

    backups = sorted([
        f for f in os.listdir(backup_dir)
        if f.startswith('gestionale_backup_') and f.endswith('.db')
    ])

    while len(backups) > config.MAX_BACKUPS:
        old_backup = backups.pop(0)
        os.remove(os.path.join(backup_dir, old_backup))
        logger.info(f"Backup rimosso (pulizia): {old_backup}")


def get_backups_list():
    """Ottiene la lista dei backup disponibili"""
    backup_dir = config.BACKUP_FOLDER
    if not os.path.exists(backup_dir):
        return []

    backups = []
    for f in sorted(os.listdir(backup_dir), reverse=True):
        if f.startswith('gestionale_backup_') and f.endswith('.db'):
            filepath = os.path.join(backup_dir, f)
            stat = os.stat(filepath)
            backups.append({
                'nome': f,
                'dimensione': round(stat.st_size / 1024, 1),  # KB
                'data': datetime.fromtimestamp(stat.st_mtime).strftime('%d/%m/%Y %H:%M')
            })

    return backups


def restore_backup(backup_name):
    """Ripristina un backup.

    Valida il nome per prevenire path traversal: deve essere un semplice basename
    (nessun '..' o percorso) e corrispondere a un backup realmente presente nella
    cartella dei backup, cosi' da non poter caricare come DB un file arbitrario."""
    if not backup_name or backup_name != os.path.basename(backup_name):
        logger.warning(f"Nome backup non valido (possibile path traversal): {backup_name!r}")
        return False
    # get_backups_list() filtra gia' per pattern 'gestionale_backup_*.db': la
    # verifica di appartenenza vincola quindi anche il naming atteso.
    if backup_name not in [b['nome'] for b in get_backups_list()]:
        logger.warning(f"Backup inesistente o non riconosciuto: {backup_name!r}")
        return False

    backup_path = os.path.join(config.BACKUP_FOLDER, backup_name)
    if not os.path.exists(backup_path):
        return False

    try:
        # Crea backup del db corrente prima di ripristinare
        create_backup()
        # Ripristino via API di backup: copia il contenuto del backup nel DB
        # attivo in modo consistente con WAL (evita di lasciare un -wal orfano).
        src = sqlite3.connect(backup_path)
        try:
            dst = sqlite3.connect(DATABASE_PATH)
            try:
                with dst:
                    src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        logger.info(f"Backup ripristinato: {backup_name}")
        return True
    except Exception as e:
        logger.error(f"Errore ripristino backup: {e}")
        return False


# ==================== UNDO STACK PERSISTENTE ====================

MAX_UNDO_ACTIONS = 20

def push_undo_action(action_type, data):
    """Salva un'azione nello stack undo persistente"""
    import json
    with get_db_context() as conn:
        cursor = conn.cursor()

        # Inserisce nuova azione
        cursor.execute('''
            INSERT INTO undo_actions (timestamp, action_type, data)
            VALUES (?, ?, ?)
        ''', (datetime.now().isoformat(), action_type, json.dumps(data)))

        # Mantiene solo le ultime MAX_UNDO_ACTIONS
        cursor.execute('''
            DELETE FROM undo_actions
            WHERE id NOT IN (
                SELECT id FROM undo_actions
                ORDER BY id DESC
                LIMIT ?
            )
        ''', (MAX_UNDO_ACTIONS,))


def pop_undo_action():
    """Rimuove e restituisce l'ultima azione dallo stack undo"""
    import json
    with get_db_context() as conn:
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, action_type, data FROM undo_actions
            ORDER BY id DESC
            LIMIT 1
        ''')
        row = cursor.fetchone()

        if row:
            cursor.execute('DELETE FROM undo_actions WHERE id = ?', (row['id'],))
            return {
                'type': row['action_type'],
                'data': json.loads(row['data'])
            }
        return None


def get_undo_stack():
    """Ottiene lo stack undo completo"""
    import json
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT action_type, data, timestamp FROM undo_actions
            ORDER BY id DESC
        ''')
        return [{
            'type': row['action_type'],
            'data': json.loads(row['data']),
            'timestamp': row['timestamp']
        } for row in cursor.fetchall()]


def clear_undo_stack():
    """Svuota lo stack undo"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM undo_actions')


# ==================== DETERMINE DIRIGENZIALI (DD) ====================

def get_dd_by_commessa(commessa_id, anno_scolastico):
    """Ottiene tutte le DD per una commessa e anno scolastico"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM determine_dirigenziali
            WHERE commessa_id = ? AND anno_scolastico = ?
            ORDER BY anno_inizio, mese_inizio
        ''', (commessa_id, anno_scolastico))
        return [dict(r) for r in cursor.fetchall()]


def add_dd(commessa_id, anno_scolastico, mese_inizio, anno_inizio, ore_settimanali,
           ore_annuali, numero_dd=None, data_dd=None, note=None):
    """Aggiunge una nuova DD"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO determine_dirigenziali
            (commessa_id, anno_scolastico, mese_inizio, anno_inizio, ore_settimanali,
             ore_annuali, numero_dd, data_dd, note, data_inserimento)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (commessa_id, anno_scolastico, mese_inizio, anno_inizio, ore_settimanali,
              ore_annuali, numero_dd, data_dd, note, datetime.now().isoformat()))
        return cursor.lastrowid


def update_dd(dd_id, ore_settimanali=None, ore_annuali=None, numero_dd=None,
              data_dd=None, note=None):
    """Aggiorna una DD esistente"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        updates = []
        params = []

        if ore_settimanali is not None:
            updates.append("ore_settimanali = ?")
            params.append(ore_settimanali)
        if ore_annuali is not None:
            updates.append("ore_annuali = ?")
            params.append(ore_annuali)
        if numero_dd is not None:
            updates.append("numero_dd = ?")
            params.append(numero_dd)
        if data_dd is not None:
            updates.append("data_dd = ?")
            params.append(data_dd)
        if note is not None:
            updates.append("note = ?")
            params.append(note)

        if updates:
            params.append(dd_id)
            cursor.execute(f'''
                UPDATE determine_dirigenziali
                SET {', '.join(updates)}
                WHERE id = ?
            ''', params)


def delete_dd(dd_id):
    """Elimina una DD"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM determine_dirigenziali WHERE id = ?', (dd_id,))


# ==================== RECUPERI ORE ====================

def get_recuperi_by_commessa(commessa_id, anno_scolastico):
    """Ottiene tutti i recuperi per una commessa e anno scolastico"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM recuperi_ore
            WHERE commessa_id = ? AND anno_scolastico = ?
            ORDER BY anno, mese
        ''', (commessa_id, anno_scolastico))
        return [dict(r) for r in cursor.fetchall()]


def add_recupero(commessa_id, anno_scolastico, mese, anno, ore_recupero, note=None):
    """Aggiunge un nuovo recupero"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO recuperi_ore
            (commessa_id, anno_scolastico, mese, anno, ore_recupero, note, data_inserimento)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (commessa_id, anno_scolastico, mese, anno, ore_recupero, note,
              datetime.now().isoformat()))
        return cursor.lastrowid


def update_recupero(recupero_id, ore_recupero=None, note=None):
    """Aggiorna un recupero esistente"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        updates = []
        params = []

        if ore_recupero is not None:
            updates.append("ore_recupero = ?")
            params.append(ore_recupero)
        if note is not None:
            updates.append("note = ?")
            params.append(note)

        if updates:
            params.append(recupero_id)
            cursor.execute(f'''
                UPDATE recuperi_ore
                SET {', '.join(updates)}
                WHERE id = ?
            ''', params)


def delete_recupero(recupero_id):
    """Elimina un recupero"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM recuperi_ore WHERE id = ?', (recupero_id,))


# ==================== OVERRIDE PROGETTATO ====================

def get_progettato_override(commessa_id, anno_scolastico, mese, anno):
    """Ottiene l'override del progettato per un mese specifico"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT ore_progettate FROM progettato_override
            WHERE commessa_id = ? AND anno_scolastico = ? AND mese = ? AND anno = ?
        ''', (commessa_id, anno_scolastico, mese, anno))
        result = cursor.fetchone()
        return result['ore_progettate'] if result else None


def get_all_progettato_override(commessa_id, anno_scolastico):
    """Ottiene tutti gli override del progettato per una commessa"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT mese, anno, ore_progettate FROM progettato_override
            WHERE commessa_id = ? AND anno_scolastico = ?
        ''', (commessa_id, anno_scolastico))
        return {(r['mese'], r['anno']): r['ore_progettate'] for r in cursor.fetchall()}


def set_progettato_override(commessa_id, anno_scolastico, mese, anno, ore_progettate):
    """Imposta o aggiorna l'override del progettato per un mese"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO progettato_override (commessa_id, anno_scolastico, mese, anno, ore_progettate, data_modifica)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(commessa_id, anno_scolastico, mese, anno)
            DO UPDATE SET ore_progettate = ?, data_modifica = ?
        ''', (commessa_id, anno_scolastico, mese, anno, ore_progettate, datetime.now().isoformat(),
              ore_progettate, datetime.now().isoformat()))


def delete_progettato_override(commessa_id, anno_scolastico, mese, anno):
    """Rimuove l'override del progettato per un mese (torna al calcolo automatico)"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM progettato_override
            WHERE commessa_id = ? AND anno_scolastico = ? AND mese = ? AND anno = ?
        ''', (commessa_id, anno_scolastico, mese, anno))


# ==================== OVERRIDE REPORT GENERICO ====================

def get_all_report_override(commessa_id, anno_scolastico):
    """Ottiene tutti gli override del report per una commessa/anno scolastico"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT mese, anno, campo, valore FROM report_override
            WHERE commessa_id = ? AND anno_scolastico = ?
        ''', (commessa_id, anno_scolastico))
        # Ritorna un dizionario: {(mese, anno, campo): valore}
        return {(r['mese'], r['anno'], r['campo']): r['valore'] for r in cursor.fetchall()}


def set_report_override(commessa_id, anno_scolastico, mese, anno, campo, valore):
    """Imposta o aggiorna l'override di un campo per un mese"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO report_override (commessa_id, anno_scolastico, mese, anno, campo, valore, data_modifica)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(commessa_id, anno_scolastico, mese, anno, campo)
            DO UPDATE SET valore = ?, data_modifica = ?
        ''', (commessa_id, anno_scolastico, mese, anno, campo, valore, datetime.now().isoformat(),
              valore, datetime.now().isoformat()))


def delete_report_override(commessa_id, anno_scolastico, mese, anno, campo):
    """Rimuove l'override di un campo (torna al calcolo automatico)"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM report_override
            WHERE commessa_id = ? AND anno_scolastico = ? AND mese = ? AND anno = ? AND campo = ?
        ''', (commessa_id, anno_scolastico, mese, anno, campo))


# ==================== REPORTISTICA LOCALE ====================

def get_giorni_lavorativi_anno(anno_scolastico):
    """Ottiene i giorni lavorativi totali per anno scolastico"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT SUM(giorni_lavorativi) as totale
            FROM calendario_scolastico
            WHERE anno_scolastico = ?
        ''', (anno_scolastico,))
        result = cursor.fetchone()
        return result['totale'] if result and result['totale'] else 0


def get_calendario_completo(anno_scolastico):
    """Ottiene il calendario completo per anno scolastico"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT mese, anno, giorni_lavorativi
            FROM calendario_scolastico
            WHERE anno_scolastico = ?
            ORDER BY anno, mese
        ''', (anno_scolastico,))
        return [dict(r) for r in cursor.fetchall()]


def calcola_ore_progettate_mese(commessa_id, anno_scolastico, mese, anno):
    """
    Calcola le ore progettate per un mese specifico.
    Le ore delle DD vengono distribuite proporzionalmente ai giorni lavorativi.
    """
    # Ottieni le DD attive per questo mese
    dd_list = get_dd_by_commessa(commessa_id, anno_scolastico)

    # Ottieni calendario completo
    calendario = get_calendario_completo(anno_scolastico)
    giorni_totali = sum(c['giorni_lavorativi'] for c in calendario)

    if giorni_totali == 0:
        return 0

    # Giorni lavorativi del mese corrente
    giorni_mese = 0
    for c in calendario:
        if c['mese'] == mese and c['anno'] == anno:
            giorni_mese = c['giorni_lavorativi']
            break

    # Calcola le ore progettate sommando le DD attive
    ore_progettate = 0

    for dd in dd_list:
        # Calcola i mesi di validità della DD (da mese_inizio a giugno)
        mesi_validita = []

        # Costruisci la lista dei mesi dell'anno scolastico
        mesi_anno_scolastico = []
        anno_start = int(anno_scolastico.split('-')[0])
        for m in [9, 10, 11, 12]:
            mesi_anno_scolastico.append((m, anno_start))
        for m in [1, 2, 3, 4, 5, 6]:
            mesi_anno_scolastico.append((m, anno_start + 1))

        # Trova l'indice del mese di inizio DD
        dd_start_idx = None
        for i, (m, a) in enumerate(mesi_anno_scolastico):
            if m == dd['mese_inizio'] and a == dd['anno_inizio']:
                dd_start_idx = i
                break

        if dd_start_idx is None:
            continue

        # Mesi di validità: da mese_inizio a giugno
        mesi_validita = mesi_anno_scolastico[dd_start_idx:]

        # Verifica se il mese corrente è nel periodo di validità della DD
        if (mese, anno) not in mesi_validita:
            continue

        # Calcola i giorni lavorativi totali nel periodo di validità
        giorni_validita = 0
        for c in calendario:
            if (c['mese'], c['anno']) in mesi_validita:
                giorni_validita += c['giorni_lavorativi']

        if giorni_validita == 0:
            continue

        # Distribuisci le ore annuali proporzionalmente
        quota_mese = (giorni_mese / giorni_validita) * dd['ore_annuali']
        ore_progettate += quota_mese

    return round(ore_progettate, 2)


def get_ore_erogate_mese(commessa_id, anno, mese):
    """Ottiene le ore erogate per una commessa in un mese specifico"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COALESCE(SUM(r.ore_lavorate_60), 0) as ore_erogate
            FROM rendicontazione r
            JOIN utenti u ON r.utente_id = u.id
            JOIN scuole s ON u.scuola_id = s.id
            WHERE s.commessa_id = ? AND r.anno = ? AND r.mese = ?
        ''', (commessa_id, anno, mese))
        result = cursor.fetchone()
        return result['ore_erogate'] if result else 0


def get_recupero_mese(commessa_id, anno_scolastico, anno, mese):
    """Ottiene le ore di recupero per un mese specifico"""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COALESCE(SUM(ore_recupero), 0) as ore
            FROM recuperi_ore
            WHERE commessa_id = ? AND anno_scolastico = ? AND anno = ? AND mese = ?
        ''', (commessa_id, anno_scolastico, anno, mese))
        result = cursor.fetchone()
        return result['ore'] if result else 0


def get_report_locale_commessa(commessa_id, anno_scolastico):
    """
    Genera il report locale completo per una commessa.
    Include: DD, ore progettate per mese, ore erogate, recuperi, importi con IVA.
    Supporta override manuali per tutti i campi.
    """
    import config

    TARIFFA = config.TARIFFA_ORARIA
    IVA = config.IVA_PERCENTUALE

    # Ottieni dati base
    dd_list = get_dd_by_commessa(commessa_id, anno_scolastico)
    calendario = get_calendario_completo(anno_scolastico)
    get_recuperi_by_commessa(commessa_id, anno_scolastico)

    # Ottieni tutti gli override del progettato (tabella legacy)
    progettato_overrides = get_all_progettato_override(commessa_id, anno_scolastico)

    # Ottieni tutti gli override generici (nuova tabella)
    report_overrides = get_all_report_override(commessa_id, anno_scolastico)

    # Calcola ore annuali totali (somma di tutte le DD già decurtate dell'11%)
    ore_annuali_totali = sum(dd['ore_annuali'] for dd in dd_list)

    # Costruisci il report per ogni mese
    mesi_report = []
    totale_progettato = 0
    totale_erogato = 0
    totale_recuperi = 0
    totale_max_imponibile = 0
    totale_effettivo = 0

    for cal in calendario:
        mese = cal['mese']
        anno = cal['anno']

        # Giorni lavorativi - può essere override
        giorni_auto = cal['giorni_lavorativi']
        giorni_override_key = (mese, anno, 'giorni_lavorativi')
        giorni_is_override = giorni_override_key in report_overrides
        giorni = report_overrides[giorni_override_key] if giorni_is_override else giorni_auto

        # Calcola ore progettate (automatico)
        ore_progettate_auto = calcola_ore_progettate_mese(commessa_id, anno_scolastico, mese, anno)

        # Usa override progettato se presente (prima dalla tabella legacy, poi dalla nuova)
        progettato_override_key = (mese, anno)
        progettato_new_key = (mese, anno, 'ore_progettate')
        is_progettato_override = progettato_override_key in progettato_overrides or progettato_new_key in report_overrides
        if progettato_new_key in report_overrides:
            ore_progettate = report_overrides[progettato_new_key]
        elif progettato_override_key in progettato_overrides:
            ore_progettate = progettato_overrides[progettato_override_key]
        else:
            ore_progettate = ore_progettate_auto

        # Ore erogate - può essere override
        ore_erogate_auto = get_ore_erogate_mese(commessa_id, anno, mese)
        erogate_override_key = (mese, anno, 'ore_erogate')
        erogate_is_override = erogate_override_key in report_overrides
        ore_erogate = report_overrides[erogate_override_key] if erogate_is_override else ore_erogate_auto

        # Ore recupero - può essere override
        ore_recupero_auto = get_recupero_mese(commessa_id, anno_scolastico, anno, mese)
        recupero_override_key = (mese, anno, 'ore_recupero')
        recupero_is_override = recupero_override_key in report_overrides
        ore_recupero = report_overrides[recupero_override_key] if recupero_is_override else ore_recupero_auto

        # Calcola importi con IVA (automatici)
        max_imponibile_auto = ore_progettate * TARIFFA * (1 + IVA)
        effettivo_auto = ore_erogate * TARIFFA * (1 + IVA)

        # Max imponibile - può essere override
        max_imp_override_key = (mese, anno, 'max_imponibile')
        max_imp_is_override = max_imp_override_key in report_overrides
        max_imponibile = report_overrides[max_imp_override_key] if max_imp_is_override else max_imponibile_auto

        # Effettivo - può essere override
        effettivo_override_key = (mese, anno, 'effettivo')
        effettivo_is_override = effettivo_override_key in report_overrides
        effettivo = report_overrides[effettivo_override_key] if effettivo_is_override else effettivo_auto

        saldo = ore_progettate - ore_erogate

        mesi_report.append({
            'mese': mese,
            'anno': anno,
            'giorni_lavorativi': int(giorni) if giorni == int(giorni) else giorni,
            'giorni_lavorativi_auto': giorni_auto,
            'giorni_is_override': giorni_is_override,
            'ore_progettate': round(ore_progettate, 2),
            'ore_progettate_auto': round(ore_progettate_auto, 2),
            'is_override': is_progettato_override,
            'ore_erogate': round(ore_erogate, 2),
            'ore_erogate_auto': round(ore_erogate_auto, 2),
            'erogate_is_override': erogate_is_override,
            'ore_recupero': round(ore_recupero, 2),
            'ore_recupero_auto': round(ore_recupero_auto, 2),
            'recupero_is_override': recupero_is_override,
            'max_imponibile': round(max_imponibile, 2),
            'max_imponibile_auto': round(max_imponibile_auto, 2),
            'max_imp_is_override': max_imp_is_override,
            'effettivo': round(effettivo, 2),
            'effettivo_auto': round(effettivo_auto, 2),
            'effettivo_is_override': effettivo_is_override,
            'saldo': round(saldo, 2)
        })

        totale_progettato += ore_progettate
        totale_erogato += ore_erogate
        totale_recuperi += ore_recupero
        totale_max_imponibile += max_imponibile
        totale_effettivo += effettivo

    return {
        'commessa_id': commessa_id,
        'anno_scolastico': anno_scolastico,
        'dd_list': dd_list,
        'ore_annuali_totali': round(ore_annuali_totali, 2),
        'mesi': mesi_report,
        'totali': {
            'progettato': round(totale_progettato, 2),
            'erogato': round(totale_erogato, 2),
            'recuperi': round(totale_recuperi, 2),
            'max_imponibile': round(totale_max_imponibile, 2),
            'effettivo': round(totale_effettivo, 2),
            'saldo': round(totale_progettato - totale_erogato, 2)
        },
        'tariffa': TARIFFA,
        'iva': IVA
    }


# ==================== VARIAZIONI MONTE ORE ====================

def get_variazioni_monte_ore(utente_id):
    """Ritorna tutte le variazioni monte ore di un utente, ordinate per mese_inizio."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, utente_id, monte_ore, mese_inizio, nota, data_inserimento
            FROM variazioni_monte_ore
            WHERE utente_id = ?
            ORDER BY mese_inizio ASC
        ''', (utente_id,))
        return [dict(r) for r in cursor.fetchall()]


def add_variazione_monte_ore(utente_id, monte_ore, mese_inizio, nota=None):
    """Aggiunge una variazione monte ore per un utente.
    mese_inizio in formato 'YYYY-MM'.
    """
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO variazioni_monte_ore (utente_id, monte_ore, mese_inizio, nota, data_inserimento)
            VALUES (?, ?, ?, ?, ?)
        ''', (utente_id, monte_ore, mese_inizio, nota, datetime.now().isoformat()))
        conn.commit()
        return cursor.lastrowid


def update_variazione_monte_ore(variazione_id, monte_ore=None, mese_inizio=None, nota=None):
    """Aggiorna una variazione monte ore esistente."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        parts = []
        params = []
        if monte_ore is not None:
            parts.append('monte_ore = ?')
            params.append(monte_ore)
        if mese_inizio is not None:
            parts.append('mese_inizio = ?')
            params.append(mese_inizio)
        if nota is not None:
            parts.append('nota = ?')
            params.append(nota)
        if not parts:
            return False
        params.append(variazione_id)
        cursor.execute(f"UPDATE variazioni_monte_ore SET {', '.join(parts)} WHERE id = ?", params)
        conn.commit()
        return cursor.rowcount > 0


def delete_variazione_monte_ore(variazione_id):
    """Elimina una variazione monte ore."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM variazioni_monte_ore WHERE id = ?", (variazione_id,))
        conn.commit()
        return cursor.rowcount > 0


def get_monte_ore_effettivo_bulk(anno, mese):
    """Ritorna un dict {utente_id: monte_ore_effettivo} per tutti gli utenti
    che hanno una variazione attiva nel mese specificato.
    La variazione attiva e' quella con mese_inizio <= 'YYYY-MM' piu' recente.
    Utenti non presenti nel dict usano il valore base da utenti.monte_ore_settimanale.
    """
    periodo = f"{anno:04d}-{mese:02d}"
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT v.utente_id, v.monte_ore
            FROM variazioni_monte_ore v
            INNER JOIN (
                SELECT utente_id, MAX(mese_inizio) as max_mese
                FROM variazioni_monte_ore
                WHERE mese_inizio <= ?
                GROUP BY utente_id
            ) latest ON v.utente_id = latest.utente_id AND v.mese_inizio = latest.max_mese
        ''', (periodo,))
        return {r['utente_id']: r['monte_ore'] for r in cursor.fetchall()}


# ==================== AUTENTICAZIONE (single-user) ====================

def auth_is_configured():
    """Ritorna True se esiste gia' una configurazione utente."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM auth_config WHERE id = 1")
        return cursor.fetchone()[0] > 0


def auth_create_user(username, password_hash):
    """Crea la configurazione utente iniziale (solo al primo setup)."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO auth_config (id, username, password_hash, data_creazione)
            VALUES (1, ?, ?, ?)
        ''', (username, password_hash, datetime.now().isoformat()))


def auth_get_user():
    """Ritorna i dati dell'utente configurato (o None)."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM auth_config WHERE id = 1")
        row = cursor.fetchone()
        return dict(row) if row else None


def auth_update_credentials(username=None, password_hash=None):
    """Aggiorna username e/o password dell'utente."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        updates = []
        params = []
        if username is not None:
            updates.append("username = ?")
            params.append(username)
        if password_hash is not None:
            updates.append("password_hash = ?")
            params.append(password_hash)
        if updates:
            params.append(1)
            cursor.execute(f'UPDATE auth_config SET {", ".join(updates)} WHERE id = ?', params)


def auth_record_login(metodo):
    """Registra l'ultimo accesso e il metodo ('password' | 'webauthn')."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE auth_config
            SET ultimo_accesso = ?, ultimo_accesso_metodo = ?
            WHERE id = 1
        ''', (datetime.now().isoformat(), metodo))


# ---------- WebAuthn credentials ----------

def webauthn_add_credential(credential_id, public_key, sign_count, nome, transports=None):
    """Registra una nuova credenziale WebAuthn."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO webauthn_credentials
            (credential_id, public_key, sign_count, nome, transports, data_registrazione)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (credential_id, public_key, sign_count, nome, transports,
              datetime.now().isoformat()))
        return cursor.lastrowid


def webauthn_get_credentials():
    """Ritorna tutte le credenziali WebAuthn registrate."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, credential_id, public_key, sign_count, nome, transports,
                   data_registrazione, ultimo_utilizzo
            FROM webauthn_credentials
            ORDER BY data_registrazione DESC
        ''')
        return [dict(r) for r in cursor.fetchall()]


def webauthn_get_credential_by_id(credential_id):
    """Ritorna una credenziale dato il suo credential_id binario."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM webauthn_credentials WHERE credential_id = ?
        ''', (credential_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def webauthn_update_sign_count(credential_id, sign_count):
    """Aggiorna il counter e il timestamp di ultimo utilizzo."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE webauthn_credentials
            SET sign_count = ?, ultimo_utilizzo = ?
            WHERE credential_id = ?
        ''', (sign_count, datetime.now().isoformat(), credential_id))


def webauthn_delete_credential(cred_pk):
    """Elimina una credenziale dato il suo ID interno (PK)."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM webauthn_credentials WHERE id = ?", (cred_pk,))


# Inizializza il database all'import
if __name__ == '__main__':
    init_db()
    logger.info("Database inizializzato con successo!")

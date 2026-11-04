"""Schema v2 della sezione Napoli (napoli_schema.crea_v2, migrazione 2 di database.py).

- Un database della v1.20.1 con l'archivio Roma inventato si aggiorna all'avvio:
  user_version 2, le 22 tabelle napoli_* con i valori iniziali; tabelle, indici e
  righe di Roma uguali a quelle del gemello riaperto dalla v1.20.1 (a ogni avvio
  anche _init_schema di Roma sistema qualche riga, uguale nelle due versioni).
- La migrazione si riesegue senza danni; se si interrompe non lascia nulla a meta'.
- Il ripristino di un backup della v1.20.1 funziona e aggiorna subito lo schema;
  Roma risulta come dopo lo stesso ripristino fatto dalla v1.20.1 e il backup di
  sicurezza fatto prima conserva i dati di Napoli.
- Una versione vecchia apre un database v2 senza toccarlo.
- Vincoli (CHECK, UNIQUE, chiavi esterne) e nessuna chiave esterna verso Roma.
- Il seme Napoli dei test di invarianza riempie tutte le tabelle napoli_*.

"Versione vecchia" = questo programma con il runner delle migrazioni fermo alla
versione 1: e' la v1.20.1, perche' lo schema di Roma (_init_schema) non e' cambiato
e la v2 aggiunge solo la migrazione (docs/ARCHITETTURA.md, "Sezione Napoli").

Solo dati inventati.
"""
import contextlib
import datetime
import hashlib
import os
import sqlite3

import pytest

import config
import napoli_schema
import roma_sintetico
import seme_napoli
from strumenti import fotografa_roma
from strumenti.confronta_roma import copia_database

TABELLE_V2 = {
    'napoli_impostazioni', 'napoli_lotti', 'napoli_figure', 'napoli_alias_qualifiche', 'napoli_scuole',
    'napoli_alunni', 'napoli_operatori', 'napoli_pei', 'napoli_coppie', 'napoli_contratti', 'napoli_tariffe',
    'napoli_regole', 'napoli_calendario', 'napoli_orari', 'napoli_fogli', 'napoli_import', 'napoli_presenze',
    'napoli_presenze_fasce', 'napoli_coordinamento', 'napoli_mesi_chiusi', 'napoli_fatture', 'napoli_annullamenti',
}
VALORI_INIZIALI = {'napoli_figure': len(napoli_schema.FIGURE),
                   'napoli_alias_qualifiche': len(napoli_schema.ALIAS_QUALIFICHE)}
ORA_RIPRISTINO = datetime.datetime(2026, 11, 4, 10, 0)


def _connetti(percorso):
    conn = sqlite3.connect(percorso)
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def _user_version(percorso):
    conn = sqlite3.connect(percorso)
    try:
        return conn.execute('PRAGMA user_version').fetchone()[0]
    finally:
        conn.close()


def _oggetti(percorso, di_napoli):
    """Tabelle, indici e trigger (tipo, nome, tabella, sql) di Napoli o di Roma."""
    conn = sqlite3.connect(percorso)
    try:
        righe = conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master "
                             "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name").fetchall()
    finally:
        conn.close()
    return [r for r in righe if r[2].startswith(seme_napoli.PREFISSO_NAPOLI) == di_napoli]


def _tabelle_napoli(percorso):
    return {r[1] for r in _oggetti(percorso, di_napoli=True) if r[0] == 'table'}


def _conteggi(percorso):
    conn = sqlite3.connect(percorso)
    try:
        return {t: conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in sorted(TABELLE_V2)}
    finally:
        conn.close()


def _hash(percorso):
    with open(percorso, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


@contextlib.contextmanager
def _versione_vecchia(db_mod, monkeypatch, percorso):
    """Il programma come la v1.20.1 (runner delle migrazioni fermo alla versione 1),
    al lavoro sul database `percorso`; all'uscita si torna al database di prima."""
    with monkeypatch.context() as m:
        m.setattr(db_mod, 'SCHEMA_VERSION', 1)
        m.setattr(db_mod, 'MIGRAZIONI', {})
        m.setattr(db_mod, 'DATABASE_PATH', percorso)
        m.setattr(config, 'DATABASE_PATH', percorso)
        db_mod.invalida_cache_auth()
        yield
    db_mod.invalida_cache_auth()


def _crea_database_v1_20_1(db_mod, monkeypatch, percorso, flask_app):
    """Database creato dalla v1.20.1 con l'archivio Roma inventato (scritto con le API)."""
    with _versione_vecchia(db_mod, monkeypatch, percorso):
        db_mod.init_db()
        client = fotografa_roma.client_fotografia(flask_app, db_mod)     # configura anche l'accesso
        roma_sintetico.costruisci_archivio(client, fotografa_roma.orologio_fermo)
    assert _user_version(percorso) == 1
    assert _oggetti(percorso, di_napoli=True) == []
    return percorso


@pytest.fixture
def database_v1_20_1(database_isolato, app_module, db_mod, monkeypatch, tmp_path):
    """Un database v1.20.1 con l'archivio Roma inventato e il suo gemello (copia).
    Il programma lavora sul primo finche' dura il test, come dopo l'aggiornamento."""
    percorso = _crea_database_v1_20_1(db_mod, monkeypatch, str(tmp_path / 'v1_20_1.db'), app_module.app)
    gemello = str(tmp_path / 'gemello_v1_20_1.db')
    copia_database(percorso, gemello)
    monkeypatch.setattr(db_mod, 'DATABASE_PATH', percorso)
    monkeypatch.setattr(config, 'DATABASE_PATH', percorso)
    db_mod.invalida_cache_auth()
    return percorso, gemello


# ==================== migrazione dalla v1.20.1 ====================

def test_migrazione_da_un_database_v1_20_1(database_v1_20_1, db_mod, monkeypatch):
    percorso, gemello = database_v1_20_1
    with _versione_vecchia(db_mod, monkeypatch, gemello):
        db_mod.init_db()                                # il gemello riaperto dalla v1.20.1

    db_mod.init_db()                                    # avvio della versione nuova

    assert _user_version(percorso) == 2 and _user_version(gemello) == 1
    assert _tabelle_napoli(percorso) == TABELLE_V2
    assert _oggetti(percorso, di_napoli=False) == _oggetti(gemello, di_napoli=False), \
        'la migrazione ha cambiato tabelle, indici o trigger di Roma'
    assert seme_napoli.impronta_roma(percorso) == seme_napoli.impronta_roma(gemello), \
        'la migrazione ha toccato le righe di Roma'
    assert {t: n for t, n in _conteggi(percorso).items() if n} == VALORI_INIZIALI
    conn = _connetti(percorso)
    try:
        assert conn.execute('SELECT codice, descrizione, ordine, ore_di_lotto FROM napoli_figure '
                            'ORDER BY ordine').fetchall() == list(napoli_schema.FIGURE)
        assert sorted(conn.execute('SELECT testo, figura FROM napoli_alias_qualifiche '
                                   "WHERE origine = 'sistema'").fetchall()) == sorted(napoli_schema.ALIAS_QUALIFICHE)
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        conn.close()


def test_migrazione_rieseguibile(database_v1_20_1, db_mod):
    percorso, _ = database_v1_20_1
    db_mod.init_db()
    seme_napoli.carica_seme_napoli(None, percorso)
    oggetti, righe = _oggetti(percorso, di_napoli=True), seme_napoli.impronta_napoli(percorso)
    roma = seme_napoli.impronta_roma(percorso)

    db_mod.init_db()                                    # secondo avvio: niente da fare
    conn = _connetti(percorso)
    try:
        napoli_schema.crea_v2(conn)                     # la migrazione stessa, rieseguita a mano
        napoli_schema.crea_v2(conn)
        conn.commit()
    finally:
        conn.close()

    assert _user_version(percorso) == 2
    assert _oggetti(percorso, di_napoli=True) == oggetti
    assert seme_napoli.impronta_napoli(percorso) == righe, 'rieseguire la migrazione ha cambiato i dati di Napoli'
    assert seme_napoli.impronta_roma(percorso) == roma


def test_migrazione_interrotta_non_lascia_nulla_a_meta(database_v1_20_1, db_mod, monkeypatch):
    percorso, _ = database_v1_20_1
    with monkeypatch.context() as m:
        m.setattr(napoli_schema, 'DDL_V2', napoli_schema.DDL_V2 + ('CREATE TABLE napoli_rotta (',))
        with pytest.raises(sqlite3.OperationalError):
            db_mod.init_db()
    assert _user_version(percorso) == 1
    assert _oggetti(percorso, di_napoli=True) == [], 'la migrazione interrotta ha lasciato tabelle a meta\''

    db_mod.init_db()                                    # all'avvio successivo riesce
    assert _user_version(percorso) == 2
    assert _tabelle_napoli(percorso) == TABELLE_V2


def test_versione_vecchia_apre_un_database_v2_senza_toccarlo(database_isolato, db_mod, monkeypatch):
    seme_napoli.carica_seme_napoli(None, database_isolato)
    napoli, roma = seme_napoli.impronta_napoli(database_isolato), seme_napoli.impronta_roma(database_isolato)
    with _versione_vecchia(db_mod, monkeypatch, database_isolato):
        db_mod.init_db()
    assert _user_version(database_isolato) == 2
    assert seme_napoli.impronta_napoli(database_isolato) == napoli
    assert seme_napoli.impronta_roma(database_isolato) == roma


# ==================== ripristino di un backup della v1.20.1 ====================

def _ripristina(client, nome):
    with fotografa_roma.orologio_fermo(ORA_RIPRISTINO):     # stessa ora nel registro attivita'
        r = client.post('/api/backup/restore', json={'backup': nome, 'confirm': 'CONFERMA'})
    assert r.status_code == 200, r.data


def test_ripristino_di_un_backup_v1_20_1(database_isolato, app_module, db_mod, monkeypatch, tmp_path):
    cartella = config.BACKUP_FOLDER
    origine = _crea_database_v1_20_1(db_mod, monkeypatch, str(tmp_path / 'origine_v1_20_1.db'), app_module.app)
    nome = 'gestionale_backup_20260301_080000.db'
    backup = os.path.join(cartella, nome)
    copia_database(origine, backup)
    impronta_file = _hash(backup)
    # il database attuale e' gia' v2 e ha dati di Napoli
    client = fotografa_roma.client_fotografia(app_module.app, db_mod)
    seme_napoli.carica_seme_napoli(client, database_isolato)
    napoli_attuale = seme_napoli.impronta_napoli(database_isolato)
    prima = set(os.listdir(cartella))

    _ripristina(client, nome)

    assert _user_version(database_isolato) == 2, 'lo schema non e\' stato aggiornato dopo il ripristino'
    assert _tabelle_napoli(database_isolato) == TABELLE_V2
    assert {t: n for t, n in _conteggi(database_isolato).items() if n} == VALORI_INIZIALI
    assert _hash(backup) == impronta_file, 'il backup scelto e\' stato modificato'
    assert client.get('/api/commesse').status_code == 200
    # il backup di sicurezza fatto prima del ripristino conserva i dati di Napoli
    nuovi = [f for f in set(os.listdir(cartella)) - prima if f.endswith('.db')]
    assert any(seme_napoli.impronta_napoli(os.path.join(cartella, f)) == napoli_attuale for f in nuovi), nuovi

    # Roma come dopo lo stesso ripristino fatto dalla v1.20.1 (su un gemello)
    gemello = str(tmp_path / 'gemello.db')
    copia_database(origine, gemello)
    with _versione_vecchia(db_mod, monkeypatch, gemello):
        _ripristina(client, nome)
    assert _user_version(gemello) == 1
    assert _oggetti(database_isolato, di_napoli=False) == _oggetti(gemello, di_napoli=False)
    assert seme_napoli.impronta_roma(database_isolato) == seme_napoli.impronta_roma(gemello)


# ==================== vincoli ====================

@pytest.fixture
def napoli_db(tmp_path):
    """Solo le tabelle di Napoli, senza quelle di Roma (lo schema non dipende da
    Roma), con un lotto, una scuola, un alunno, un operatore e una coppia."""
    conn = _connetti(str(tmp_path / 'solo_napoli.db'))
    napoli_schema.crea_v2(conn)
    conn.commit()
    conn.executescript('''
        INSERT INTO napoli_lotti (id, nome, numero_lotto, municipalita, data_creazione)
            VALUES (1, 'LOTTO DI PROVA', 1, '1 e 2', '2025-09-01');
        INSERT INTO napoli_scuole (id, lotto_id, nome, codice_meccanografico, grado, municipalita, data_inserimento)
            VALUES (1, 1, 'IC Prova', 'NAIC8ZZ001', 'inferiore', 1, '2025-09-01');
        INSERT INTO napoli_alunni (id, lotto_id, cognome, nome, codice_fiscale, scuola_id, data_inserimento)
            VALUES (1, 1, 'Prova', 'Alunna', 'PRVLNA15C50Z999X', 1, '2025-09-01');
        INSERT INTO napoli_operatori (id, cognome, nome, figura, data_inserimento)
            VALUES (1, 'Prova', 'Operatore', 'ASACOM', '2025-09-01');
        INSERT INTO napoli_coppie (id, lotto_id, alunno_id, operatore_id, scuola_id, figura, valido_da,
                                   data_inserimento)
            VALUES (1, 1, 1, 1, 1, 'ASACOM', '2025-09-15', '2025-09-15');
        INSERT INTO napoli_presenze (id, coppia_id, lotto_id, data, figura, origine, modificato_il)
            VALUES (1, 1, 1, '2025-10-06', 'ASACOM', 'foglio', '2025-10-06');
        INSERT INTO napoli_contratti (id, lotto_id, numero, valido_da, valido_a, data_inserimento)
            VALUES (1, 1, 'X', '2025-09-01', '2026-06-30', '2025-09-01');
    ''')
    yield conn
    conn.close()


RIFIUTATE = {
    'cf_corto': "INSERT INTO napoli_alunni (lotto_id, cognome, nome, codice_fiscale, data_inserimento) "
                "VALUES (1, 'A', 'B', 'PRVLNA15C50Z999', 'x')",
    'cf_doppio': "INSERT INTO napoli_alunni (lotto_id, cognome, nome, codice_fiscale, data_inserimento) "
                 "VALUES (1, 'A', 'B', 'PRVLNA15C50Z999X', 'x')",
    'lotto_6': "INSERT INTO napoli_lotti (nome, numero_lotto, municipalita, data_creazione) VALUES ('L6', 6, '9', 'x')",
    'lotto_stesso_numero': "INSERT INTO napoli_lotti (nome, numero_lotto, municipalita, data_creazione) "
                           "VALUES ('ALTRO', 1, '3', 'x')",
    'grado_scuola': "INSERT INTO napoli_scuole (lotto_id, nome, grado, data_inserimento) VALUES (1, 'S', 'medio', 'x')",
    'plesso_doppio': "INSERT INTO napoli_scuole (lotto_id, nome, codice_meccanografico, municipalita, "
                     "data_inserimento) VALUES (1, 'IC Prova bis', 'NAIC8ZZ001', 1, 'x')",
    'grado_alunno_misto': "UPDATE napoli_alunni SET grado = 'misto' WHERE id = 1",
    'figura_inesistente': "INSERT INTO napoli_operatori (cognome, nome, figura, data_inserimento) "
                          "VALUES ('A', 'B', 'BIDELLO', 'x')",
    'alias_figura_inesistente': "INSERT INTO napoli_alias_qualifiche (testo, figura) VALUES ('BIDELLO', 'BIDELLO')",
    'pei_41_ore': "INSERT INTO napoli_pei (alunno_id, figura, ore_settimanali, valido_da, data_inserimento) "
                  "VALUES (1, 'ASACOM', 41, '2025-09-01', 'x')",
    'pei_date_invertite': "INSERT INTO napoli_pei (alunno_id, figura, ore_settimanali, valido_da, valido_a, "
                          "data_inserimento) VALUES (1, 'ASACOM', 10, '2025-09-01', '2025-08-31', 'x')",
    'coppia_alunno_inesistente': "INSERT INTO napoli_coppie (lotto_id, alunno_id, operatore_id, scuola_id, figura, "
                                 "valido_da, data_inserimento) VALUES (1, 99, 1, 1, 'ASACOM', '2025-09-15', 'x')",
    'coppia_date_invertite': "UPDATE napoli_coppie SET valido_a = '2025-09-14' WHERE id = 1",
    'coppia_ruolo': "UPDATE napoli_coppie SET ruolo = 'supplente' WHERE id = 1",
    'contratto_date_invertite': "UPDATE napoli_contratti SET valido_a = '2025-08-01' WHERE id = 1",
    'tariffa_zero': "INSERT INTO napoli_tariffe (lotto_id, figura, tariffa_cent, valido_da, data_inserimento) "
                    "VALUES (1, 'ASACOM', 0, '2025-09-01', 'x')",
    'tariffa_doppia': "INSERT INTO napoli_tariffe (lotto_id, figura, tariffa_cent, valido_da, data_inserimento) "
                      "VALUES (1, 'EDUCATORE', 100, '2025-09-01', 'x'), (1, 'EDUCATORE', 200, '2025-09-01', 'x')",
    'regola_doppia_tutti_i_lotti': "INSERT INTO napoli_regole (chiave, valore, valido_da, data_inserimento) "
                                   "VALUES ('q', '1', '2025-09-01', 'x'), ('q', '2', '2025-09-01', 'x')",
    'calendario_doppio': "INSERT INTO napoli_calendario (data, tipo, descrizione) "
                         "VALUES ('2025-12-25', 'chiusura', 'a'), ('2025-12-25', 'evento', 'b')",
    'calendario_tipo': "INSERT INTO napoli_calendario (data, tipo, descrizione) VALUES ('2025-12-25', 'sciopero', 'a')",
    'orario_sabato_dopo': "INSERT INTO napoli_orari (coppia_id, giorno, ora_inizio, ora_fine, data_inserimento) "
                          "VALUES (1, 6, '08:00', '10:00', 'x')",
    'orario_formato': "INSERT INTO napoli_orari (coppia_id, giorno, ora_inizio, ora_fine, data_inserimento) "
                      "VALUES (1, 0, '9:00', '10:00', 'x')",
    'orario_invertito': "INSERT INTO napoli_orari (coppia_id, giorno, ora_inizio, ora_fine, data_inserimento) "
                        "VALUES (1, 0, '10:00', '08:00', 'x')",
    'foglio_mese_13': "INSERT INTO napoli_fogli (coppia_id, anno, mese) VALUES (1, 2025, 13)",
    'foglio_stato': "INSERT INTO napoli_fogli (coppia_id, anno, mese, stato) VALUES (1, 2025, 10, 'perso')",
    'presenza_doppia': "INSERT INTO napoli_presenze (coppia_id, lotto_id, data, figura, origine, modificato_il) "
                       "VALUES (1, 1, '2025-10-06', 'ASACOM', 'griglia', 'x')",
    'presenza_data_formato': "INSERT INTO napoli_presenze (coppia_id, lotto_id, data, figura, origine, modificato_il) "
                             "VALUES (1, 1, '07/10/2025', 'ASACOM', 'griglia', 'x')",
    'presenza_oltre_12_ore': "UPDATE napoli_presenze SET minuti_riconosciuti = 721 WHERE id = 1",
    'presenza_minuti_negativi': "UPDATE napoli_presenze SET minuti_svolti = -1 WHERE id = 1",
    'presenza_origine': "UPDATE napoli_presenze SET origine = 'telefono' WHERE id = 1",
    'presenza_stato': "UPDATE napoli_presenze SET stato = 'forse' WHERE id = 1",
    'presenza_tipo_extra': "UPDATE napoli_presenze SET tipo_extra = 'uso_A' WHERE id = 1",
    'presenza_lotto_inesistente': "UPDATE napoli_presenze SET lotto_id = 9 WHERE id = 1",
    'fascia_tipo': "INSERT INTO napoli_presenze_fasce (presenza_id, tipo, ordine, ora_inizio, ora_fine) "
                   "VALUES (1, 'X', 1, '08:00', '10:00')",
    'fascia_invertita': "INSERT INTO napoli_presenze_fasce (presenza_id, tipo, ordine, ora_inizio, ora_fine) "
                        "VALUES (1, 'E', 1, '10:00', '09:59')",
    'coordinamento_grado': "INSERT INTO napoli_coordinamento (lotto_id, grado, contratto_id, anno, mese, "
                           "operatore_id, ore_cent) VALUES (1, 'misto', 1, 2025, 10, 1, 100)",
    'coordinamento_ore_negative': "INSERT INTO napoli_coordinamento (lotto_id, grado, contratto_id, anno, mese, "
                                  "operatore_id, ore_cent) VALUES (1, 'inferiore', 1, 2025, 10, 1, -1)",
    'mese_chiuso_doppio': "INSERT INTO napoli_mesi_chiusi (lotto_id, anno, mese, data_chiusura) "
                          "VALUES (1, 2025, 10, 'x'), (1, 2025, 10, 'y')",
    'fattura_periodo_invertito': "INSERT INTO napoli_fatture (lotto_id, grado, contratto_id, periodo_dal, periodo_al, "
                                 "righe_json, somma_righe_cent, ritenuta_cent, imponibile_cent, iva_cent, totale_cent, "
                                 "da_pagare_cent, data_creazione) "
                                 "VALUES (1, 'inferiore', 1, '2025-10-31', '2025-10-01', '[]', 0, 0, 0, 0, 0, 0, 'x')",
    'fattura_stato': "INSERT INTO napoli_fatture (lotto_id, grado, contratto_id, periodo_dal, periodo_al, righe_json, "
                     "somma_righe_cent, ritenuta_cent, imponibile_cent, iva_cent, totale_cent, da_pagare_cent, stato, "
                     "data_creazione) VALUES (1, 'inferiore', 1, '2025-10-01', '2025-10-31', '[]', 0, 0, 0, 0, 0, 0, "
                     "'pagata', 'x')",
}


@pytest.mark.parametrize('caso', sorted(RIFIUTATE))
def test_vincoli_rifiutano_le_righe_sbagliate(napoli_db, caso):
    with pytest.raises(sqlite3.IntegrityError):
        napoli_db.execute(RIFIUTATE[caso])


def test_vincoli_ammettono_i_casi_previsti(napoli_db):
    c = napoli_db
    # lo stesso codice meccanografico in un'altra municipalita' e' un altro plesso; senza codice nessun limite
    c.execute("INSERT INTO napoli_scuole (lotto_id, nome, codice_meccanografico, municipalita, data_inserimento) "
              "VALUES (1, 'IC Prova', 'NAIC8ZZ001', 2, 'x')")
    c.execute("INSERT INTO napoli_scuole (lotto_id, nome, data_inserimento) VALUES (1, 'Senza codice', 'x'), "
              "(1, 'Senza codice', 'x')")
    # tariffe: stessa figura con livelli diversi o con un'altra data di inizio
    c.execute("INSERT INTO napoli_tariffe (lotto_id, figura, livello_ccnl, tariffa_cent, valido_da, data_inserimento) "
              "VALUES (1, 'EDUCATORE', NULL, 2428, '2025-09-01', 'x'), "
              "(1, 'EDUCATORE', 'D2', 2500, '2025-09-01', 'x'), (1, 'EDUCATORE', NULL, 2544, '2027-02-01', 'x')")
    # due fasce nello stesso giorno; sabato ammesso
    c.execute("INSERT INTO napoli_orari (coppia_id, giorno, ora_inizio, ora_fine, data_inserimento) "
              "VALUES (1, 0, '08:00', '10:00', 'x'), (1, 0, '12:00', '14:00', 'x'), (1, 5, '08:00', '09:00', 'x')")
    c.execute("INSERT INTO napoli_presenze_fasce (presenza_id, tipo, ordine, ora_inizio, ora_fine) "
              "VALUES (1, 'P', 1, '08:00', '10:00'), (1, 'P', 2, '12:00', '14:00'), (1, 'E', 1, '08:00', '10:00')")
    # stessa regola: per tutti i lotti e per un lotto
    c.execute("INSERT INTO napoli_regole (lotto_id, chiave, valore, valido_da, data_inserimento) "
              "VALUES (NULL, 'q', '0.5', '2025-09-01', 'x'), (1, 'q', '0', '2025-09-01', 'x')")
    # minuti svolti non noti (import), contratto per entrambi i gradi, coppia sostituta
    c.execute('UPDATE napoli_presenze SET minuti_svolti = NULL, minuti_riconosciuti = 720 WHERE id = 1')
    c.execute("INSERT INTO napoli_coppie (lotto_id, alunno_id, operatore_id, scuola_id, figura, ruolo, "
              "titolare_coppia_id, valido_da, valido_a, data_inserimento) "
              "VALUES (1, 1, 1, 1, 'ASACOM', 'sostituto', 1, '2025-10-13', '2025-10-13', 'x')")
    c.commit()
    assert c.execute('PRAGMA foreign_key_check').fetchall() == []


def test_cancellare_coppia_e_presenza_cancella_orari_e_fasce(napoli_db):
    c = napoli_db
    c.execute("INSERT INTO napoli_orari (coppia_id, giorno, ora_inizio, ora_fine, data_inserimento) "
              "VALUES (1, 0, '08:00', '10:00', 'x')")
    c.execute("INSERT INTO napoli_presenze_fasce (presenza_id, tipo, ordine, ora_inizio, ora_fine) "
              "VALUES (1, 'P', 1, '08:00', '10:00')")
    with pytest.raises(sqlite3.IntegrityError):        # la coppia ha presenze: non si cancella
        c.execute('DELETE FROM napoli_coppie WHERE id = 1')
    c.execute('DELETE FROM napoli_presenze WHERE id = 1')
    assert c.execute('SELECT COUNT(*) FROM napoli_presenze_fasce').fetchone()[0] == 0
    c.execute('DELETE FROM napoli_coppie WHERE id = 1')
    assert c.execute('SELECT COUNT(*) FROM napoli_orari').fetchone()[0] == 0


def test_nessuna_chiave_esterna_verso_tabelle_di_roma(napoli_db):
    tabelle = [r[0] for r in napoli_db.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                               "AND name NOT LIKE 'sqlite_%'")]
    assert set(tabelle) == TABELLE_V2, 'lo schema v2 crea solo tabelle napoli_*'
    riferite = {r[2] for t in tabelle for r in napoli_db.execute(f'PRAGMA foreign_key_list({t})')}
    assert riferite and all(t.startswith('napoli_') for t in riferite), riferite


# ==================== seme Napoli dei test di invarianza ====================

def test_il_seme_napoli_riempie_tutte_le_tabelle(database_isolato, app_module, db_mod):
    client = fotografa_roma.client_fotografia(app_module.app, db_mod)
    roma = seme_napoli.impronta_roma(database_isolato)
    caricate = seme_napoli.carica_seme_napoli(client, database_isolato)

    conteggi = _conteggi(database_isolato)
    assert [t for t, n in conteggi.items() if n == 0] == [], 'tabelle di Napoli vuote nel seme'
    for t, n in caricate.items():
        assert conteggi[t] == n + VALORI_INIZIALI.get(t, 0), t
    assert seme_napoli.impronta_roma(database_isolato) == roma
    conn = _connetti(database_isolato)
    try:
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
        codici = [r[0] for r in conn.execute('SELECT codice_fiscale FROM napoli_alunni')]
    finally:
        conn.close()
    # codici fiscali inventati: carattere di controllo corretto, comune Z999 inesistente
    assert len(codici) == 4
    for cf in codici:
        assert len(cf) == 16 and cf[11:15] == 'Z999' and cf[15] == seme_napoli.carattere_di_controllo(cf[:15]), cf

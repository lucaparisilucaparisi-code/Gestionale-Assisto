"""Seme Napoli: i dati di Napoli caricati nei database di prova (VR3 e VR5).

Serve a provare che Roma non cambia quando nel database ci sono anche dati di
Napoli:
- tests/test_roma_invariata.py fotografa Roma, carica il seme e la rifotografa;
- con ASSISTO_TEST_CON_NAPOLI=1 conftest.py carica il seme nel database della
  sessione e nell'archivio Roma inventato, e tutta la suite gira di nuovo.

Per ora la sezione Napoli non esiste e il seme e' vuoto. Ogni passo che aggiunge
una funzione di Napoli aggiunge qui i suoi dati, SOLO tramite le API di Napoli
(lotto, tariffe, import del master sintetico con alunni omonimi di utenti di Roma,
orari, mese preparato, fogli, fattura definitiva, mese chiuso...). Solo dati
inventati.
"""
import hashlib
import pathlib
import sqlite3

PREFISSO_NAPOLI = 'napoli_'


def carica_seme_napoli(client):
    """Carica i dati di Napoli con il client di prova (sessione autenticata).

    Ritorna {tabella: righe caricate}; vuoto finche' la sezione Napoli non c'e'."""
    return {}


def _tabelle(conn):
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _impronta_righe(conn, tabella, dove=''):
    h = hashlib.sha256()
    for riga in conn.execute(f'SELECT * FROM "{tabella}" {dove} ORDER BY rowid'):
        h.update(repr(tuple(riga)).encode('utf-8'))
    return h.hexdigest()


def _connetti(percorso):
    return sqlite3.connect(pathlib.Path(percorso).resolve().as_uri() + '?mode=ro', uri=True)


def impronta_roma(percorso):
    """Schema e righe di tutte le tabelle che non sono di Napoli. Del registro
    attivita' (audit_log, condiviso) contano solo le voci che non sono di Napoli."""
    conn = _connetti(percorso)
    try:
        esito = {}
        for t in _tabelle(conn):
            if t.startswith(PREFISSO_NAPOLI):
                continue
            schema = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (t,)).fetchone()[0]
            dove = "WHERE COALESCE(entita, '') NOT LIKE 'napoli%'" if t == 'audit_log' else ''
            esito[t] = (schema, _impronta_righe(conn, t, dove))
        return esito
    finally:
        conn.close()


def impronta_napoli(percorso):
    """Righe delle tabelle di Napoli (napoli_*)."""
    conn = _connetti(percorso)
    try:
        return {t: _impronta_righe(conn, t) for t in _tabelle(conn) if t.startswith(PREFISSO_NAPOLI)}
    finally:
        conn.close()

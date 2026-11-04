"""VR7: lo strumento di confronto fra due versioni (strumenti/confronta_roma.py).

Prova su copie di un piccolo database inventato: con la stessa versione le
uscite di Roma sono identiche; con una versione che cambia la tariffa lo
strumento lo dice. In entrambi i casi stampa solo conteggi e nomi delle rotte
(nessun nome di persona o di scuola) e non modifica il database indicato.
Anche strumenti/fotografa_roma.py --db lavora su una copia: il file indicato non
cambia, nemmeno se la versione fotografata deve aggiornarne lo schema.
"""
import glob
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys

from strumenti import fotografa_roma

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFRONTA = os.path.join(ROOT, 'strumenti', 'confronta_roma.py')
DATI_RISERVATI = ('Riservata', 'Segretissima', 'Plesso Nascosto')


def _impronta(percorso):
    with open(percorso, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def _confronta(db, vecchia, nuova):
    r = subprocess.run([sys.executable, CONFRONTA, '--db', db, '--vecchia', vecchia, '--nuova', nuova,
                        '--oggi', '2026-03-20'], capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


def _versione_con_tariffa_diversa(cartella):
    os.makedirs(cartella)
    for f in glob.glob(os.path.join(ROOT, '*.py')) + [os.path.join(ROOT, 'VERSION')]:
        shutil.copy(f, cartella)
    for d in ('templates', 'static'):
        shutil.copytree(os.path.join(ROOT, d), os.path.join(cartella, d))
    percorso = os.path.join(cartella, 'config.py')
    with open(percorso, encoding='utf-8') as f:
        testo = f.read()
    assert 'TARIFFA_ORARIA = 24.07' in testo
    with open(percorso, 'w', encoding='utf-8') as f:
        f.write(testo.replace('TARIFFA_ORARIA = 24.07', 'TARIFFA_ORARIA = 24.08'))
    return cartella


def test_confronto_fra_versioni_stampa_solo_conteggi(database_isolato, app_module, db_mod, tmp_path):
    client = fotografa_roma.client_fotografia(app_module.app, db_mod)
    client.post('/api/commesse', json={'nome': 'COMMESSA CONFRONTO'})
    for nome, ore in (('Riservata', 30.5), ('Segretissima', 12.25)):
        r = client.post('/api/utenti', json={'commessa': 'COMMESSA CONFRONTO', 'scuola': 'IC Plesso Nascosto',
                                             'nome': nome, 'cognome': 'Prova', 'monte_ore': 10})
        uid = r.get_json()['utente_id']
        client.post('/api/rendicontazione/2026/2/batch', json={'updates': [{'utente_id': uid, 'ore_lavorate_60': ore}]})
    prima = _impronta(database_isolato)

    codice, uscita = _confronta(database_isolato, ROOT, ROOT)
    assert codice == 0, uscita
    assert 'Diverse: 0.' in uscita

    nuova = _versione_con_tariffa_diversa(str(tmp_path / 'nuova'))
    codice, uscita = _confronta(database_isolato, ROOT, nuova)
    assert codice == 1, uscita
    assert 'diversa: /api/config (1 indirizzi)' in uscita
    assert 'diversa: /api/export/excel/<int:anno>/<int:mese>' in uscita

    for dato in DATI_RISERVATI:
        assert dato not in uscita
    assert _impronta(database_isolato) == prima, 'il database indicato e\' stato modificato'
    assert not os.path.exists(os.path.join(nuova, '__pycache__'))


def test_fotografia_di_un_database_lavora_su_una_copia(database_isolato, app_module, db_mod, tmp_path):
    client = fotografa_roma.client_fotografia(app_module.app, db_mod)
    client.post('/api/commesse', json={'nome': 'COMMESSA COPIA'})
    r = client.post('/api/utenti', json={'commessa': 'COMMESSA COPIA', 'scuola': 'IC Plesso Nascosto',
                                         'nome': 'Riservata', 'cognome': 'Prova', 'monte_ore': 10})
    client.post('/api/rendicontazione/2026/2/batch',
                json={'updates': [{'utente_id': r.get_json()['utente_id'], 'ore_lavorate_60': 12.5}]})
    # un database "vecchio" (user_version 1): la versione fotografata lo aggiornerebbe
    conn = sqlite3.connect(database_isolato)
    conn.execute('PRAGMA user_version = 1')
    conn.commit()
    conn.close()
    prima = _impronta(database_isolato)
    uscita = str(tmp_path / 'foto.json')
    esito = subprocess.run([sys.executable, os.path.join(ROOT, 'strumenti', 'fotografa_roma.py'), '--db',
                            database_isolato, '--uscita', uscita, '--oggi', '2026-03-20'],
                           capture_output=True, text=True, timeout=300)
    assert esito.returncode == 0, esito.stderr[-2000:]
    assert _impronta(database_isolato) == prima, 'il database indicato e\' stato modificato'
    conn = sqlite3.connect(database_isolato)
    try:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == 1
    finally:
        conn.close()
    foto = fotografa_roma.leggi(uscita)
    assert foto['rotte']['/api/commesse'] and foto['oggi'] == '2026-03-20T10:00:00'
    assert esito.stdout == ''

"""Regressione: eliminazione utente con FK enforcement attivo.

Con PRAGMA foreign_keys=ON, cancellare un utente con note/documenti/assenze/turni
falliva con 'FOREIGN KEY constraint failed' e lasciava un'azione undo fantasma.
"""


def _utente_con_correlati(db, suffix):
    db.create_commessa(f'OEPAC DEL {suffix}')
    sid = db.get_or_create_scuola(f'OEPAC DEL {suffix}', f'IC Del {suffix} - Primaria')
    uid = db.get_or_create_utente(sid, 'Test', f'Delete{suffix}', 10)
    db.add_nota_utente(uid, 'una nota', tipo='osservazione')
    with db.get_db_context() as conn:
        conn.execute('''INSERT INTO documenti_utente
            (utente_id, nome_file, nome_originale, tipo_documento, data_caricamento)
            VALUES (?, 'x.pdf', 'doc.pdf', 'certificato', '2026-01-01')''', (uid,))
        conn.execute('''INSERT INTO assenze
            (utente_id, data_inizio, tipo, data_registrazione)
            VALUES (?, '2026-03-01', 'malattia', '2026-03-01')''', (uid,))
    db.get_or_create_rendicontazione(uid, 2026, 3)
    db.update_rendicontazione(uid, 2026, 3, ore_lavorate=12)
    dip = db.create_dipendente({'nome': 'Op', 'cognome': f'Del{suffix}'})
    db.create_turno(dip, 0, '09:00', '11:00', scuola_id=sid, utente_id=uid)
    return uid, sid


def _conta(db, tabella, uid):
    with db.get_db_context() as conn:
        return conn.execute(
            f'SELECT COUNT(*) FROM {tabella} WHERE utente_id = ?', (uid,)).fetchone()[0]


def test_delete_utente_con_correlati_funziona(client, db_mod):
    """DELETE non deve piu' fallire; correlati rimossi, turno scollegato."""
    uid, _ = _utente_con_correlati(db_mod, 'A')

    r = client.delete(f'/api/utenti/{uid}')
    assert r.status_code == 200, r.get_json()

    for tab in ['note_utente', 'documenti_utente', 'assenze', 'rendicontazione']:
        assert _conta(db_mod, tab, uid) == 0
    # il turno sopravvive ma senza riferimento all'utente
    with db_mod.get_db_context() as conn:
        assert conn.execute('SELECT COUNT(*) FROM turni WHERE utente_id = ?',
                            (uid,)).fetchone()[0] == 0
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []


def test_undo_ripristina_utente_e_correlati(client, db_mod):
    """L'undo dopo la cancellazione ripristina utente, ore, note, documenti, assenze."""
    uid, _ = _utente_con_correlati(db_mod, 'B')

    assert client.delete(f'/api/utenti/{uid}').status_code == 200
    r = client.post('/api/undo')
    assert r.status_code == 200, r.get_json()

    with db_mod.get_db_context() as conn:
        assert conn.execute('SELECT COUNT(*) FROM utenti WHERE id = ?', (uid,)).fetchone()[0] == 1
    assert _conta(db_mod, 'rendicontazione', uid) == 1
    assert _conta(db_mod, 'note_utente', uid) == 1
    assert _conta(db_mod, 'documenti_utente', uid) == 1
    assert _conta(db_mod, 'assenze', uid) == 1


def test_bulk_delete_con_correlati(client, db_mod):
    uid, _ = _utente_con_correlati(db_mod, 'C')
    r = client.delete('/api/utenti/bulk', json={'ids': [uid]})
    assert r.status_code == 200
    assert r.get_json()['eliminati'] == 1


def test_reset_utenti_con_turni_e_documenti(client, db_mod):
    """Il reset non deve fallire con FK enforcement e tabelle figlie popolate."""
    _utente_con_correlati(db_mod, 'D')
    r = client.post('/api/reset', json={'type': 'utenti', 'confirm': 'CONFERMA'})
    assert r.status_code == 200, r.get_json()
    with db_mod.get_db_context() as conn:
        assert conn.execute('SELECT COUNT(*) FROM utenti').fetchone()[0] == 0
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
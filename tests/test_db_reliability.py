"""Test di affidabilita' del layer dati: enforcement FOREIGN KEY, cascata,
error handler HTTP.
"""


def test_foreign_keys_enforcement_attivo(db_mod):
    """Ogni connessione deve avere l'enforcement delle FOREIGN KEY attivo."""
    with db_mod.get_db_context() as conn:
        assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1


def _setup_turno_con_sostituzione(db):
    db.create_commessa('OEPAC REL')
    sc = db.get_or_create_scuola('OEPAC REL', 'IC REL - Primaria')
    u = db.get_or_create_utente(sc, 'Luca', 'Bianchi', 10)
    dip = db.create_dipendente({'nome': 'Anna', 'cognome': 'Verdi'})
    db.create_assegnazione(u, dip, 10)
    # Lunedi' (giorno=0); 2026-06-22 e' un lunedi'
    db.create_turno(dip, 0, '09:00', '12:00', scuola_id=sc, utente_id=u)
    ass = db.create_assenza_dipendente(dip, '2026-06-22', '2026-06-22', 'malattia')
    db.crea_sostituzioni_per_assenza(ass)
    return dip


def _turno_id_sostituzioni(db):
    with db.get_db_context() as conn:
        rows = conn.execute(
            'SELECT id, turno_id FROM sostituzioni WHERE turno_id IS NOT NULL'
        ).fetchall()
        return [dict(r) for r in rows]


def test_delete_turno_non_lascia_sostituzioni_orfane(db_mod):
    """Cancellare un turno non deve lasciare sostituzioni orfane (ON DELETE CASCADE
    effettivo grazie all'enforcement FK)."""
    db = db_mod
    _setup_turno_con_sostituzione(db)

    sost = _turno_id_sostituzioni(db)
    assert sost, "setup non ha prodotto sostituzioni collegate a un turno"
    turno_id = sost[0]['turno_id']

    db.delete_turno(turno_id)

    # Nessuna sostituzione deve puntare a un turno inesistente
    with db.get_db_context() as conn:
        orfani = conn.execute(
            'SELECT COUNT(*) FROM sostituzioni WHERE turno_id = ?', (turno_id,)
        ).fetchone()[0]
        # E il controllo integrita' globale deve essere pulito
        violazioni = conn.execute('PRAGMA foreign_key_check').fetchall()
    assert orfani == 0
    assert violazioni == []


def test_api_404_json(client):
    """Una risorsa API inesistente risponde 404 JSON strutturato."""
    r = client.get('/api/questo-endpoint-non-esiste')
    assert r.status_code == 404
    assert r.get_json().get('code') == 'NOT_FOUND'

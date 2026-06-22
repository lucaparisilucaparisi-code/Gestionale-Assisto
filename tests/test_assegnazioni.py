"""Test del modulo Personale: dipendenti e assegnazioni utente<->operatore."""


def test_crea_e_leggi_dipendente(db_mod):
    db = db_mod
    did = db.create_dipendente({
        'nome': 'Mario', 'cognome': 'Bianchi', 'qualifica': 'OEPAC',
        'ore_contrattuali_settimanali': 30,
        'extra': {'matricola': 'A123', 'sede_legale': 'Roma'},
    })
    d = db.get_dipendente(did)
    assert d['nome'] == 'Mario' and d['cognome'] == 'Bianchi'
    assert d['ore_contrattuali_settimanali'] == 30
    # i campi non-core finiscono in extra (JSON) e tornano come dict
    assert d['extra']['matricola'] == 'A123'


def test_dipendente_nome_obbligatorio(db_mod):
    import pytest
    with pytest.raises(ValueError):
        db_mod.create_dipendente({'nome': '', 'cognome': ''})


def test_bilancio_assegnazioni(db_mod, sample_data):
    """Il bilancio deve confrontare monte ore (15) con la somma delle assegnazioni."""
    db = db_mod
    utente_id = sample_data['utente_id']
    d1 = db.create_dipendente({'nome': 'A', 'cognome': 'Uno'})
    d2 = db.create_dipendente({'nome': 'B', 'cognome': 'Due'})

    # Nessuna assegnazione: mancano tutte le ore -> stato 'sotto'
    b = db.get_bilancio_assegnazioni_utente(utente_id)
    assert b['monte_ore'] == 15 and b['assegnate'] == 0 and b['stato'] == 'sotto'

    # Assegno 10h: ancora sotto (-5)
    a1 = db.create_assegnazione(utente_id, d1, 10)
    b = db.get_bilancio_assegnazioni_utente(utente_id)
    assert b['assegnate'] == 10 and b['differenza'] == -5 and b['stato'] == 'sotto'

    # Assegno altre 5h: bilanciato esatto
    db.create_assegnazione(utente_id, d2, 5)
    b = db.get_bilancio_assegnazioni_utente(utente_id)
    assert b['assegnate'] == 15 and b['differenza'] == 0 and b['stato'] == 'ok'

    # Porto la prima assegnazione da 10 a 12 -> totale 17, 2h di troppo -> 'sopra'
    db.update_assegnazione(a1, ore_settimanali=12)
    b = db.get_bilancio_assegnazioni_utente(utente_id)
    assert b['stato'] == 'sopra' and b['differenza'] == 2

    # L'operatore vede i suoi assistiti
    assistiti = db.get_assistiti_dipendente(d1)
    assert any(a['utente_id'] == utente_id for a in assistiti)

    # Pulizia
    for a in db.get_assegnazioni_utente(utente_id):
        db.delete_assegnazione(a['id'])

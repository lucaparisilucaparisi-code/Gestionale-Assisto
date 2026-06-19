"""Test della logica delle variazioni monte ore (incrementi/decrementi)."""


def test_crud_variazioni(db_mod, sample_data):
    db = db_mod
    uid = sample_data['utente_id']

    # Inizialmente nessuna variazione
    assert db.get_variazioni_monte_ore(uid) == []

    # Aggiunta
    vid = db.add_variazione_monte_ore(uid, 18, '2026-03', 'Incremento')
    assert vid is not None
    variazioni = db.get_variazioni_monte_ore(uid)
    assert len(variazioni) == 1
    assert variazioni[0]['monte_ore'] == 18
    assert variazioni[0]['mese_inizio'] == '2026-03'
    assert variazioni[0]['nota'] == 'Incremento'

    # Modifica
    assert db.update_variazione_monte_ore(vid, monte_ore=20) is True
    assert db.get_variazioni_monte_ore(uid)[0]['monte_ore'] == 20

    # Eliminazione
    assert db.delete_variazione_monte_ore(vid) is True
    assert db.get_variazioni_monte_ore(uid) == []


def test_monte_ore_effettivo_bulk(db_mod, sample_data):
    """La variazione attiva è la più recente con mese_inizio <= mese richiesto."""
    db = db_mod
    uid = sample_data['utente_id']

    db.add_variazione_monte_ore(uid, 15, '2025-09', 'Inizio AS')
    db.add_variazione_monte_ore(uid, 18, '2026-03', 'Incremento')

    # Prima di Settembre: nessuna variazione attiva
    assert uid not in db.get_monte_ore_effettivo_bulk(2025, 8)

    # Settembre-Febbraio: 15h
    assert db.get_monte_ore_effettivo_bulk(2025, 9).get(uid) == 15
    assert db.get_monte_ore_effettivo_bulk(2025, 12).get(uid) == 15
    assert db.get_monte_ore_effettivo_bulk(2026, 2).get(uid) == 15

    # Da Marzo in poi: 18h
    assert db.get_monte_ore_effettivo_bulk(2026, 3).get(uid) == 18
    assert db.get_monte_ore_effettivo_bulk(2026, 6).get(uid) == 18


def test_rendicontazione_usa_monte_ore_effettivo(db_mod, sample_data):
    """get_rendicontazione_completa deve riflettere la variazione nel mese."""
    db = db_mod
    uid = sample_data['utente_id']

    # Senza variazioni: monte_ore_effettivo == base, non variato
    dati = db.get_rendicontazione_completa(2025, 10)
    riga = next((d for d in dati if d['utente_id'] == uid), None)
    assert riga is not None, "utente di test non presente in rendicontazione"
    assert riga['monte_ore_variato'] is False
    assert riga['monte_ore_effettivo'] == riga['monte_ore_settimanale']

    # Con variazione attiva da Ottobre: il valore effettivo cambia
    db.add_variazione_monte_ore(uid, 25, '2025-10', 'Incremento')
    dati = db.get_rendicontazione_completa(2025, 10)
    riga = next(d for d in dati if d['utente_id'] == uid)
    assert riga['monte_ore_variato'] is True
    assert riga['monte_ore_effettivo'] == 25
    # La media prevista deve essere calcolata sul valore effettivo (25), non sul base (15)
    assert riga['media_mensile_60'] > 0


def test_validazione_input_variazioni(client, sample_data):
    """L'API deve rifiutare input non validi."""
    uid = sample_data['utente_id']

    # Monte ore negativo
    r = client.post(f'/api/utenti/{uid}/variazioni-monte-ore',
                    json={'monte_ore': -5, 'mese_inizio': '2026-01'})
    assert r.status_code == 400

    # Mese mancante
    r = client.post(f'/api/utenti/{uid}/variazioni-monte-ore',
                    json={'monte_ore': 10, 'mese_inizio': ''})
    assert r.status_code == 400

    # Oltre il massimo consentito
    r = client.post(f'/api/utenti/{uid}/variazioni-monte-ore',
                    json={'monte_ore': 999, 'mese_inizio': '2026-01'})
    assert r.status_code == 400

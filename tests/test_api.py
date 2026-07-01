"""Smoke test degli endpoint API principali (autenticazione, CRUD, export)."""


def test_auth_richiesta_su_api(app_module):
    """Senza sessione autenticata, le API devono rispondere 401."""
    flask_app = app_module.app
    with flask_app.test_client() as c:
        r = c.get('/api/utenti')
        assert r.status_code == 401
        assert r.get_json().get('code') == 'AUTH_REQUIRED'


def test_lista_utenti(client, sample_data):
    r = client.get('/api/utenti')
    assert r.status_code == 200


def test_variazioni_crud_via_api(client, sample_data):
    uid = sample_data['utente_id']

    # Lista vuota
    r = client.get(f'/api/utenti/{uid}/variazioni-monte-ore')
    assert r.status_code == 200
    assert r.get_json()['variazioni'] == []

    # Crea
    r = client.post(f'/api/utenti/{uid}/variazioni-monte-ore',
                    json={'monte_ore': 18, 'mese_inizio': '2026-03', 'nota': 'Test'})
    assert r.status_code == 200
    vid = r.get_json()['id']

    # Rilegge
    r = client.get(f'/api/utenti/{uid}/variazioni-monte-ore')
    assert len(r.get_json()['variazioni']) == 1

    # Aggiorna
    r = client.put(f'/api/variazioni-monte-ore/{vid}', json={'monte_ore': 20})
    assert r.status_code == 200

    # Elimina
    r = client.delete(f'/api/variazioni-monte-ore/{vid}')
    assert r.status_code == 200
    r = client.get(f'/api/utenti/{uid}/variazioni-monte-ore')
    assert r.get_json()['variazioni'] == []


def test_export_municipale(client, sample_data):
    r = client.get('/api/export/municipale/2025/10')
    assert r.status_code == 200
    assert 'spreadsheetml' in r.mimetype
    assert len(r.data) > 3000  # un xlsx valido non è vuoto


def test_export_dipartimentale(client, sample_data):
    r = client.get('/api/export/dipartimentale/2025/10')
    assert r.status_code == 200
    assert 'spreadsheetml' in r.mimetype


def test_export_word(client, sample_data):
    r = client.get('/api/export/word/2025/10')
    assert r.status_code == 200
    assert 'wordprocessingml' in r.mimetype
    assert len(r.data) > 10000


def test_rendicontazione_endpoint(client, sample_data):
    r = client.get('/api/rendicontazione/2025/10')
    assert r.status_code == 200
    body = r.get_json()
    assert 'dati' in body
    assert 'totale_generale' in body


def test_profilo_page_con_pannello_backup(client):
    """La pagina Profilo si renderizza e include il pannello backup."""
    r = client.get('/profilo')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'Backup e sicurezza dati' in html
    assert 'btn-create-backup' in html

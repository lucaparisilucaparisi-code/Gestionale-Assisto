"""Test del flusso di autenticazione: login, logout, cambio password, whitelist."""


def test_login_password_corretta(app_module):
    flask_app = app_module.app
    with flask_app.test_client() as c:
        r = c.post('/api/auth/login', json={'username': 'tester', 'password': 'secret'})
        assert r.status_code == 200, r.get_json()
        # ora le API rispondono
        assert c.get('/api/commesse').status_code == 200


def test_login_password_errata(app_module):
    flask_app = app_module.app
    with flask_app.test_client() as c:
        r = c.post('/api/auth/login', json={'username': 'tester', 'password': 'sbagliata'})
        assert r.status_code in (400, 401)
        assert c.get('/api/utenti').status_code == 401


def test_logout_invalida_sessione(app_module):
    flask_app = app_module.app
    with flask_app.test_client() as c:
        c.post('/api/auth/login', json={'username': 'tester', 'password': 'secret'})
        assert c.get('/api/commesse').status_code == 200
        c.post('/api/auth/logout')
        assert c.get('/api/utenti').status_code == 401


def test_pagine_pubbliche_accessibili_senza_login(app_module):
    flask_app = app_module.app
    with flask_app.test_client() as c:
        assert c.get('/login').status_code == 200
        assert c.get('/api/auth/status').status_code == 200


def test_pagina_protetta_redirige_al_login(app_module):
    flask_app = app_module.app
    with flask_app.test_client() as c:
        r = c.get('/rendicontazione')
        assert r.status_code == 302
        assert '/login' in r.headers['Location']


def test_cambio_password(client, db_mod):
    # password corrente errata -> rifiutato
    r = client.post('/api/auth/change-password',
                    json={'current_password': 'sbagliata', 'new_password': 'nuovissima1'})
    assert r.status_code == 401

    # cambio riuscito; poi ripristino dell'hash originale via DB (la password
    # della fixture, 'secret', e' sotto gli 8 caratteri minimi dell'endpoint)
    hash_originale = db_mod.auth_get_user()['password_hash']
    r = client.post('/api/auth/change-password',
                    json={'current_password': 'secret', 'new_password': 'nuovissima1'})
    assert r.status_code == 200, r.get_json()
    from werkzeug.security import check_password_hash
    assert check_password_hash(db_mod.auth_get_user()['password_hash'], 'nuovissima1')
    db_mod.auth_update_credentials(password_hash=hash_originale)

"""Test degli endpoint statistici (heatmap) dopo l'ottimizzazione delle query."""


def _set_ore(db, uid, anno, mese, ore):
    db.get_or_create_rendicontazione(uid, anno, mese)
    db.update_rendicontazione(uid, anno, mese, ore_lavorate=ore)


def test_heatmap_ore_corrette(client, db_mod, sample_data):
    """La heatmap deve riportare le ore erogate nei mesi giusti dell'anno scolastico
    (settembre-dicembre sull'anno di inizio, gennaio-giugno sull'anno di fine)."""
    uid = sample_data['utente_id']
    _set_ore(db_mod, uid, 2025, 10, 30)  # ottobre 2025
    _set_ore(db_mod, uid, 2026, 2, 20)   # febbraio 2026

    body = client.get('/api/stats/heatmap/2025-2026').get_json()
    riga = next(u for u in body['heatmap'] if u['id'] == uid)
    per_mese = {(m['mese'], m['anno']): m['ore'] for m in riga['mesi']}

    assert per_mese[(10, 2025)] == 30
    assert per_mese[(2, 2026)] == 20
    assert per_mese[(5, 2026)] == 0  # maggio 2026: mese senza dati in questo test
    # Deve coprire i 10 mesi scolastici
    assert len(riga['mesi']) == 10


def test_scuole_dettaglio_senza_parametri(client, sample_data):
    """Senza anno/mese l'ordinamento non deve riferire una colonna assente (no 500)."""
    r = client.get('/api/stats/scuole-dettaglio')
    assert r.status_code == 200
    assert 'scuole' in r.get_json()


def test_audit_endpoint_dopo_estrazione_blueprint(client):
    """L'endpoint audit (spostato nel blueprint migrazione) risponde ancora."""
    r = client.get('/api/audit')
    assert r.status_code == 200


def test_endpoint_dettaglio_utente_dopo_estrazione(client, sample_data):
    """Gli endpoint utente spostati nel blueprint utenti_dettaglio rispondono."""
    uid = sample_data['utente_id']
    for url in [f'/api/utente/{uid}/documenti',
                f'/api/utente/{uid}/note',
                f'/api/utente/{uid}/assenze']:
        assert client.get(url).status_code == 200

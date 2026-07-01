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

"""Test del wizard 'nuovo anno scolastico': finestra del banner, preparazione
del calendario, idempotenza e validazione.
"""
from datetime import datetime


def test_finestra_banner(app_module, db_mod):
    """Il banner e' proposto solo da giugno a ottobre, per l'anno giusto."""
    f = app_module._prossimo_anno_da_preparare

    # luglio 2027 -> propone il 2027-2028
    anno, pronto = f(datetime(2027, 7, 15))
    assert anno == '2027-2028'
    assert pronto is False  # non ancora preparato

    # marzo -> fuori finestra
    anno, pronto = f(datetime(2027, 3, 15))
    assert anno is None

    # settembre 2025 -> propone il 2025-2026 (che il seed ha gia' creato)
    anno, pronto = f(datetime(2025, 9, 20))
    assert anno == '2025-2026'
    assert pronto is True


def test_prepara_anno_crea_calendario(client, db_mod):
    """La preparazione crea i 10 mesi con giorni calcolati e coerenti."""
    r = client.post('/api/anno-scolastico/prepara',
                    json={'anno_scolastico': '2031-2032'})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert len(body['mesi']) == 10

    per_mese = {m['mese']: m for m in body['mesi']}
    # settembre parte a meta' mese: meno giorni di ottobre
    assert 0 < per_mese[9]['giorni'] < per_mese[10]['giorni']
    # giugno ha la variante non-infanzia (fine scuola 8/6), piu' corta
    assert per_mese[6]['giorni_altri'] is not None
    assert per_mese[6]['giorni_altri'] < per_mese[6]['giorni']

    # il calendario e' davvero salvato e usato dal resto dell'app
    giorni_ott, _ = db_mod.get_calendario_full('2031-2032', 10, 2031)
    assert giorni_ott == per_mese[10]['giorni']

    # ora l'anno risulta 'pronto' per il banner
    import app as A
    anno, pronto = A._prossimo_anno_da_preparare(datetime(2031, 7, 1))
    assert anno == '2031-2032' and pronto is True


def test_prepara_anno_validazione(client):
    for bad in ['2026', '2026/2027', '2026-2029', 'prossimo']:
        r = client.post('/api/anno-scolastico/prepara', json={'anno_scolastico': bad})
        assert r.status_code == 400, f'accettato: {bad}'


def test_prepara_anno_idempotente(client, db_mod):
    """Rieseguire la preparazione ricalcola senza duplicare righe."""
    for _ in range(2):
        r = client.post('/api/anno-scolastico/prepara',
                        json={'anno_scolastico': '2032-2033'})
        assert r.status_code == 200
    with db_mod.get_db_context() as conn:
        n = conn.execute("SELECT COUNT(*) FROM calendario_scolastico WHERE anno_scolastico = '2032-2033'").fetchone()[0]
    assert n == 10

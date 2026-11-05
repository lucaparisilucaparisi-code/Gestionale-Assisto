"""Lotto 2 "settembre": fine validita' delle variazioni monte ore, archiviazione
degli utenti e passo "Utenti" del wizard di nuovo anno scolastico."""
from datetime import datetime


def _utente(db, commessa, scuola, nome, monte=10):
    db.create_commessa(commessa)
    sid = db.get_or_create_scuola(commessa, scuola)
    return db.get_or_create_utente(sid, nome, 'Test', monte)


def _riga(db, anno, mese, commessa, uid):
    return [d for d in db.get_rendicontazione_completa(anno, mese, commessa) if d['utente_id'] == uid][0]


def test_variazione_con_fine_non_si_trascina_al_nuovo_anno(db_mod):
    db = db_mod
    uid = _utente(db, 'L2 FINE', 'IC Fine - Primaria', 'Fine')
    db.add_variazione_monte_ore(uid, 15, '2025-11', 'aumento', mese_fine='2026-08')

    assert db.get_monte_ore_effettivo_bulk(2026, 3).get(uid) == 15   # dentro il periodo
    assert db.get_monte_ore_effettivo_bulk(2026, 8).get(uid) == 15   # ultimo mese incluso
    assert uid not in db.get_monte_ore_effettivo_bulk(2026, 9)       # settembre: torna alla base
    vs = db.get_variazioni_monte_ore(uid)
    assert db.risolvi_monte_ore(10, vs, '2026-03') == 15
    assert db.risolvi_monte_ore(10, vs, '2026-09') == 10
    # la vista mensile usa la stessa regola
    assert _riga(db, 2026, 3, 'L2 FINE', uid)['monte_ore_effettivo'] == 15
    assert _riga(db, 2026, 9, 'L2 FINE', uid)['monte_ore_effettivo'] == 10


def test_variazione_terminata_riprende_la_precedente_ancora_aperta(db_mod):
    db = db_mod
    uid = _utente(db, 'L2 STACK', 'IC Stack - Primaria', 'Stack')
    db.add_variazione_monte_ore(uid, 12, '2025-10')                        # aperta
    db.add_variazione_monte_ore(uid, 15, '2026-02', mese_fine='2026-04')   # temporanea
    vs = db.get_variazioni_monte_ore(uid)
    assert db.risolvi_monte_ore(10, vs, '2026-03') == 15
    assert db.risolvi_monte_ore(10, vs, '2026-05') == 12
    assert db.get_monte_ore_effettivo_bulk(2026, 5).get(uid) == 12


def test_api_variazioni_mese_fine(client, db_mod):
    db = db_mod
    uid = _utente(db, 'L2 API', 'IC Api - Primaria', 'Api')
    r = client.post(f'/api/utenti/{uid}/variazioni-monte-ore',
                    json={'monte_ore': 14, 'mese_inizio': '2026-01', 'mese_fine': '2025-12'})
    assert r.status_code == 400
    r = client.post(f'/api/utenti/{uid}/variazioni-monte-ore',
                    json={'monte_ore': 14, 'mese_inizio': '2026-01', 'mese_fine': '2026-06'})
    assert r.status_code == 200, r.data
    vid = r.get_json()['id']
    lista = client.get(f'/api/utenti/{uid}/variazioni-monte-ore').get_json()['variazioni']
    assert lista[0]['mese_fine'] == '2026-06'
    # riapertura (mese_fine null) e azzeramento della nota (prima rispondeva 404)
    assert client.put(f'/api/variazioni-monte-ore/{vid}', json={'mese_fine': None}).status_code == 200
    assert client.put(f'/api/variazioni-monte-ore/{vid}', json={'nota': ''}).status_code == 200
    assert db.get_variazioni_monte_ore(uid)[0]['mese_fine'] is None


def test_archiviazione_utente_e_ripristino(client, db_mod):
    db = db_mod
    uid = _utente(db, 'L2 ARCH', 'IC Arch - Primaria', 'Arch')
    assert client.put(f'/api/utenti/{uid}', json={'attivo': False}).status_code == 200

    attivi = [u['id'] for u in client.get('/api/utenti?commessa=L2%20ARCH').get_json()]
    archiviati = [u['id'] for u in client.get('/api/utenti?commessa=L2%20ARCH&attivi=0').get_json()]
    assert uid not in attivi and uid in archiviati
    # sparisce dai mesi futuri senza righe (nei mesi prima dell'archiviazione resta,
    # come quando era attivo: vedi tests/test_db_reale_storico.py)
    anno_futuro = datetime.now().year + 1
    assert not any(d['utente_id'] == uid for d in db.get_rendicontazione_completa(anno_futuro, 3, 'L2 ARCH'))

    # l'undo della modifica riporta l'utente tra gli attivi
    assert client.post('/api/undo').status_code == 200
    assert db.get_utente_by_id(uid)['attivo'] == 1

    # ripristino esplicito
    client.put(f'/api/utenti/{uid}', json={'attivo': False})
    assert client.put(f'/api/utenti/{uid}', json={'attivo': True}).status_code == 200
    assert db.get_utente_by_id(uid)['attivo'] == 1


def test_wizard_utenti_anteprima_e_applicazione(client, db_mod):
    db = db_mod
    db.create_commessa('L2 WIZ')
    sid = db.get_or_create_scuola('L2 WIZ', 'IC Wiz - Primaria')
    resta = db.get_or_create_utente(sid, 'Resta', 'Test', 10)
    db.add_variazione_monte_ore(resta, 14, '2026-02', "aumento in corso d'anno")   # aperta
    cambia = db.get_or_create_utente(sid, 'Cambia', 'Test', 8)
    esce = db.get_or_create_utente(sid, 'Esce', 'Test', 12)
    client.put(f'/api/utenti/{esce}', json={'data_fine': '2026-06'})
    futuro = db.get_or_create_utente(sid, 'Futuro', 'Test', 9)
    db.add_variazione_monte_ore(futuro, 11, '2026-10')   # gia' del nuovo anno: non va chiusa

    anno = '2026-2027'
    r = client.get(f'/api/anno-scolastico/utenti-anteprima?anno_scolastico={anno}')
    assert r.status_code == 200
    ant = {u['id']: u for u in r.get_json()['utenti']}
    assert ant[resta]['monte_ore_base'] == 10 and ant[resta]['effettivo_giugno'] == 14
    assert ant[resta]['variazioni_aperte'] == 1
    # chi e' uscito e' solo indicato, mai proposto gia' spuntato per l'archivio
    # (archiviare non serve: la data di fine lo esclude gia' dal nuovo anno)
    assert ant[esce]['uscito'] is True and ant[esce]['proposta_archivio'] is False
    assert ant[cambia]['uscito'] is False and ant[cambia]['proposta_archivio'] is False
    assert ant[futuro]['variazioni_aperte'] == 0

    r = client.post('/api/anno-scolastico/prepara-utenti', json={
        'anno_scolastico': anno, 'chiudi_variazioni': True,
        'monte_ore': {str(cambia): 12.5}, 'archivia': [esce]})
    assert r.status_code == 200, r.data
    body = r.get_json()
    assert body['monte_ore_modificati'] == 1 and body['archiviati'] == 1
    assert body['variazioni_chiuse'] >= 1

    # da settembre "Resta" torna alla base; a giugno aveva ancora 14
    vs = db.get_variazioni_monte_ore(resta)
    assert db.risolvi_monte_ore(10, vs, '2026-09') == 10
    assert db.risolvi_monte_ore(10, vs, '2026-06') == 14
    # la variazione gia' del nuovo anno resta aperta
    assert db.get_variazioni_monte_ore(futuro)[0]['mese_fine'] is None
    # monte ore aggiornato e tracciato nello storico dell'utente
    assert db.get_utente_by_id(cambia)['monte_ore_settimanale'] == 12.5
    storico = client.get(f'/api/utenti/{cambia}/storico-monte-ore').get_json()['storico']
    assert any(float(s['monte_ore_nuovo']) == 12.5 for s in storico)
    # archiviato: fuori dalla rendicontazione del nuovo anno
    assert db.get_utente_by_id(esce)['attivo'] == 0
    assert not any(d['utente_id'] == esce for d in db.get_rendicontazione_completa(2026, 10, 'L2 WIZ'))
    # stato del wizard e idempotenza
    assert client.get(f'/api/anno-scolastico/utenti-anteprima?anno_scolastico={anno}').get_json()['gia_preparato']
    r = client.post('/api/anno-scolastico/prepara-utenti', json={'anno_scolastico': anno, 'archivia': [esce]})
    assert r.get_json()['variazioni_chiuse'] == 0 and r.get_json()['archiviati'] == 0


def test_wizard_utenti_validazione(client):
    url = '/api/anno-scolastico/prepara-utenti'
    assert client.post(url, json={'anno_scolastico': '2026'}).status_code == 400
    assert client.post(url, json={'anno_scolastico': '2026-2027', 'monte_ore': {'x': 5}}).status_code == 400
    assert client.post(url, json={'anno_scolastico': '2026-2027', 'monte_ore': {'1': 99}}).status_code == 400
    assert client.post(url, json={'anno_scolastico': '2026-2027', 'archivia': 'no'}).status_code == 400

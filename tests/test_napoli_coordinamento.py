"""Ore del coordinatore (passo 1.8, REGOLE 9 e 12): un totale mensile per lotto, grado e
contratto applicativo, in ore decimali al centesimo (71,55), senza una persona, con una
nota facoltativa; il mese chiuso del lotto non si cambia; Ctrl+Z di Napoli.

Solo dati inventati: lotto con la procedura guidata, contratti scritti con le API.
"""
import datetime
import json
import sqlite3

import pytest

import napoli_calcoli as nc
import napoli_db
from strumenti import fotografa_roma

OGGI = datetime.date(2026, 11, 5)


def _ok(r):
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _errore(r, stato, codice=None, campo=None):
    assert r.status_code == stato, r.get_data(as_text=True)
    dati = r.get_json()
    assert dati['error'] and (codice is None or dati['code'] == codice), dati
    assert campo is None or dati.get('campo') == campo, dati
    return dati


def _righe(percorso, sql, parametri=()):
    conn = sqlite3.connect(percorso)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, parametri)]
    finally:
        conn.close()


def _scrivi(percorso, sql, parametri=()):
    conn = sqlite3.connect(percorso)
    try:
        with conn:
            conn.execute(sql, parametri)
    finally:
        conn.close()


@pytest.fixture
def napoli(database_isolato, app_module, db_mod, monkeypatch):
    """NAPOLI LOTTO 1 con i contratti X (grado inferiore, giugno-agosto 2026), XI (tutti e
    due i gradi, settembre 2026 - gennaio 2027) e XII (inferiore, da febbraio 2027); oggi e'
    il 5 novembre 2026."""
    monkeypatch.setattr(napoli_db, '_oggi', lambda: OGGI)
    client = fotografa_roma.client_fotografia(app_module.app, db_mod)
    proposta = _ok(client.get('/api/napoli/lotti/proposta'))
    lotto = _ok(client.post('/api/napoli/lotti/procedura', json={
        'lotto': dict(proposta['lotto'], municipalita='1 e 2', cig='ZZ00000000'), 'tariffe': proposta['tariffe'],
        'valido_da': proposta['valido_da'], 'valido_a': proposta['valido_a']}))['lotto']
    client.lotto_id, client.percorso = lotto['id'], database_isolato
    client.contratti = {}
    for numero, grado, dal, al in (('X', 'inferiore', '2026-06-08', '2026-08-31'),
                                   ('XI', '', '2026-09-01', '2027-01-31'),
                                   ('XII', 'inferiore', '2027-02-01', '2027-06-30')):
        c = _ok(client.post(f'/api/napoli/lotti/{lotto["id"]}/contratti', json={
            'numero': numero, 'grado': grado, 'valido_da': dal, 'valido_a': al}))['contratto']
        client.contratti[numero] = c['id']
    return client


def _salva(client, numero='XI', grado='inferiore', anno=2026, mese=11, **campi):
    return client.put(f'/api/napoli/lotti/{client.lotto_id}/coordinamento', json=dict(
        anno=anno, mese=mese, contratto_id=client.contratti[numero], grado=grado, **campi))


def _elenco(client):
    return _ok(client.get(f'/api/napoli/lotti/{client.lotto_id}/coordinamento'))


def _riga(elenco, anno, mese, numero, grado):
    m = next(x for x in elenco['mesi'] if (x['anno'], x['mese']) == (anno, mese))
    return next(r for r in m['righe'] if (r['numero'], r['grado']) == (numero, grado))


# ==================== lettura delle ore scritte ====================

@pytest.mark.parametrize('scritto, cent', [('71,55', 7155), ('71,5', 7150), ('0', 0), ('12', 1200), (',5', 50),
                                           (' 71,55 h', 7155), ('744', 74400), (7155 / 100, 7155)])
def test_ore_scritte_che_si_leggono(scritto, cent):
    assert nc.leggi_ore_coordinatore(scritto) == (cent, None)


def test_ore_con_il_punto_valgono_e_lo_dicono():
    cent, nota = nc.leggi_ore_coordinatore('71.55')
    assert cent == 7155 and nota == 'Hai scritto "71.55" con il punto: vale 71,55 ore (i decimali si scrivono dopo ' \
                                      'la virgola).'
    assert nc.leggi_ore_coordinatore('') == (None, None) and nc.leggi_ore_coordinatore(None) == (None, None)


@pytest.mark.parametrize('scritto, messaggio', [
    ('71,555', '"71,555" ha 3 cifre dopo la virgola: le ore si scrivono con al massimo due decimali, per esempio 71,55.'),
    ('71.555', '"71.555" ha 3 cifre dopo il punto: le ore si scrivono con al massimo due decimali, per esempio 71,55.'),
    ('71:33', '"71:33" sono ore e minuti: in decimale fanno 71,55. Le ore del coordinatore si scrivono in decimale, '
              'con la virgola.'),
    ('71:75', '"71:75" non è un numero di ore: scrivi le ore in decimale, con la virgola (per esempio 71,55).'),
    ('7155', '7.155 ore in un mese sono troppe (al massimo 744). Forse volevi scrivere 71,55?'),
    ('744,01', '744,01 ore in un mese sono troppe (al massimo 744).'),
    ('-3', 'Le ore non possono essere negative.'),
    ('abc', '"abc" non è un numero di ore: scrivi per esempio 71,55.'),
    ('1e2', '"1e2" non è un numero di ore: scrivi per esempio 71,55.'),
    ('12,3,4', '"12,3,4" non è un numero di ore: scrivi per esempio 71,55.'),
])
def test_ore_scritte_rifiutate_con_un_messaggio_chiaro(scritto, messaggio):
    with pytest.raises(ValueError) as e:
        nc.leggi_ore_coordinatore(scritto)
    assert str(e.value) == messaggio


# ==================== elenco dei mesi e dei contratti ====================

def test_mesi_e_contratti_fino_a_oggi(napoli):
    e = _elenco(napoli)
    assert [m['testo'] for m in e['mesi']] == ['Novembre 2026', 'Ottobre 2026', 'Settembre 2026', 'Agosto 2026',
                                               'Luglio 2026', 'Giugno 2026']
    novembre = e['mesi'][0]
    assert [(r['numero'], r['grado'], r['ore'], r['periodo_testo']) for r in novembre['righe']] == [
        ('XI', 'inferiore', '', 'dal 01/11/2026 al 30/11/2026'), ('XI', 'superiore', '', 'dal 01/11/2026 al 30/11/2026')]
    giugno = e['mesi'][-1]['righe']
    assert [(r['numero'], r['grado'], r['periodo_testo'], r['mese_intero']) for r in giugno] == [
        ('X', 'inferiore', 'dal 08/06/2026 al 30/06/2026', False)]
    assert e['futuri'] == [{'numero': 'XII', 'grado_testo': 'grado inferiore', 'dal': '2027-02-01',
                            'dal_testo': '01/02/2027'}]
    assert e['contratti'] == 3 and e['max_ore'] == 744 and not any(m['chiuso'] for m in e['mesi'])


def test_senza_contratti_niente_mesi(database_isolato, app_module, db_mod, monkeypatch):
    monkeypatch.setattr(napoli_db, '_oggi', lambda: OGGI)
    client = fotografa_roma.client_fotografia(app_module.app, db_mod)
    proposta = _ok(client.get('/api/napoli/lotti/proposta'))
    lotto = _ok(client.post('/api/napoli/lotti/procedura', json={
        'lotto': dict(proposta['lotto'], municipalita='3'), 'tariffe': proposta['tariffe'],
        'valido_da': proposta['valido_da'], 'valido_a': proposta['valido_a']}))['lotto']
    e = _ok(client.get(f'/api/napoli/lotti/{lotto["id"]}/coordinamento'))
    assert (e['contratti'], e['mesi'], e['futuri']) == (0, [], [])
    _errore(client.get('/api/napoli/lotti/999/coordinamento'), 404)


# ==================== scrivere, cambiare, togliere, Ctrl+Z ====================

def test_ore_scritte_cambiate_tolte_e_annullate_con_ctrl_z(napoli):
    r = _ok(_salva(napoli, ore='71,55', nota='Dal riepilogo del coordinatore'))
    assert (r['riga']['ore'], r['riga']['ore_cent'], r['lettura']) == ('71,55', 7155, None)
    assert r['messaggio'] == 'Salvate le ore del coordinatore di novembre 2026, contratto XI (grado inferiore): 71,55'
    righe = _righe(napoli.percorso, 'SELECT * FROM napoli_coordinamento')
    assert [(x['grado'], x['contratto_id'], x['anno'], x['mese'], x['ore_cent'], x['operatore_id'], x['nota'])
            for x in righe] == [('inferiore', napoli.contratti['XI'], 2026, 11, 7155, None,
                                 'Dal riepilogo del coordinatore')]
    assert righe[0]['modificato_il']
    assert _riga(_elenco(napoli), 2026, 11, 'XI', 'inferiore')['ore'] == '71,55'
    # lo stesso valore scritto con il punto: niente da cambiare, ma la risposta dice come l'ha letto
    r = _ok(_salva(napoli, ore='71.55'))
    assert r['messaggio'] == 'Nessun cambiamento da salvare' and 'con il punto' in r['lettura']
    # cambiare le ore; Ctrl+Z torna a 71,55 (con la descrizione nella conferma)
    r = _ok(_salva(napoli, ore='80'))
    assert r['messaggio'] == ('Ore del coordinatore di novembre 2026, contratto XI (grado inferiore): 80 '
                              '(prima 71,55)')
    ultima = _ok(napoli.get('/api/napoli/annulla/ultima'))['azione']
    assert ultima['descrizione'] == ('Ore del coordinatore cambiate: novembre 2026, contratto XI (grado inferiore), '
                                     'da 71,55 a 80')
    _ok(napoli.post('/api/napoli/annulla', json={'id': ultima['id']}))
    assert _righe(napoli.percorso, 'SELECT ore_cent, nota FROM napoli_coordinamento') == [
        {'ore_cent': 7155, 'nota': 'Dal riepilogo del coordinatore'}]
    # la nota si cambia da sola (le ore restano)
    r = _ok(_salva(napoli, nota='Riepilogo corretto'))
    assert r['riga']['ore'] == '71,55' and r['messaggio'].startswith('Nota salvata')
    _ok(napoli.post('/api/napoli/annulla', json={}))
    assert _righe(napoli.percorso, 'SELECT nota FROM napoli_coordinamento')[0]['nota'] == \
        'Dal riepilogo del coordinatore'
    # Ctrl+Z della prima scrittura: la riga sparisce
    _ok(napoli.post('/api/napoli/annulla', json={}))
    assert _righe(napoli.percorso, 'SELECT * FROM napoli_coordinamento') == []
    # la casella vuota toglie le ore (senza ore non c'e' niente da togliere); Ctrl+Z le rimette
    assert _ok(_salva(napoli, ore=''))['messaggio'] == 'Nessun cambiamento da salvare'
    _ok(_salva(napoli, grado='superiore', ore='3,75'))
    r = _ok(_salva(napoli, grado='superiore', ore=''))
    assert r['riga']['ore'] == '' and r['messaggio'] == ('Tolte le ore del coordinatore di novembre 2026, contratto XI '
                                                         '(grado superiore)')
    assert _righe(napoli.percorso, 'SELECT * FROM napoli_coordinamento') == []
    _ok(napoli.post('/api/napoli/annulla', json={}))
    assert _righe(napoli.percorso, 'SELECT grado, ore_cent FROM napoli_coordinamento') == [
        {'grado': 'superiore', 'ore_cent': 375}]
    # zero ore e' un valore (nessuna ora di coordinamento nel mese), non una casella vuota
    assert _ok(_salva(napoli, mese=10, ore='0'))['riga']['ore'] == '0,00'


def test_ore_scritte_male_rifiutate_dal_server(napoli):
    for scritto, pezzo in (('71,555', 'al massimo due decimali'), ('71.555', 'al massimo due decimali'),
                           ('71:33', 'in decimale fanno 71,55'), ('7155', 'Forse volevi scrivere 71,55?'),
                           ('-2', 'negative'), ('tante', 'non è un numero di ore')):
        dati = _errore(_salva(napoli, ore=scritto), 400, 'DATI_NON_VALIDI', campo='ore')
        assert pezzo in dati['error'], (scritto, dati)
    assert _righe(napoli.percorso, 'SELECT * FROM napoli_coordinamento') == []
    r = _ok(_salva(napoli, ore='71.55'))
    assert r['riga']['ore'] == '71,55' and r['lettura'].startswith('Hai scritto "71.55" con il punto: vale 71,55')
    # una nota senza ore no; un codice fiscale scritto nella nota si salva mascherato
    _errore(_salva(napoli, grado='superiore', nota='Solo una nota'), 400, campo='ore')
    _errore(_salva(napoli, grado='superiore', ore='1', nota='x' * 201), 400, campo='nota')
    _ok(_salva(napoli, nota='Visto con RSSMRA80A01Z999X'))
    nota = _righe(napoli.percorso, 'SELECT nota FROM napoli_coordinamento')[0]['nota']
    assert 'RSSMRA80A01Z999X' not in nota and nota.startswith('Visto con RSS')


def test_contratto_grado_e_mese_controllati(napoli):
    url = f'/api/napoli/lotti/{napoli.lotto_id}/coordinamento'
    # il contratto X e' del grado inferiore; il mese deve essere nelle sue date e gia' cominciato
    dati = _errore(_salva(napoli, numero='X', grado='superiore', mese=7, ore='5'), 400, campo='grado')
    assert 'grado inferiore' in dati['error']
    _errore(_salva(napoli, numero='X', mese=9, ore='5'), 400, 'FUORI_CONTRATTO', campo='mese')
    _errore(_salva(napoli, numero='XI', mese=12, ore='5'), 400, 'MESE_FUTURO', campo='mese')
    _errore(_salva(napoli, numero='XI', grado='medio', ore='5'), 400, campo='grado')
    _errore(_salva(napoli, numero='XI', mese=13, ore='5'), 400, campo='mese')
    _errore(napoli.put(url, json={'anno': 2026, 'mese': 11, 'contratto_id': 'x', 'grado': 'inferiore', 'ore': '1'}),
            400, campo='contratto_id')
    _errore(napoli.put(url, json={'anno': 2026, 'mese': 11, 'contratto_id': 9999, 'grado': 'inferiore', 'ore': '1'}),
            404)
    _errore(napoli.put(url, json={'anno': 2026, 'mese': 11, 'contratto_id': napoli.contratti['XI'],
                                  'grado': 'inferiore'}), 400, campo='ore')
    _errore(napoli.put(url, data='non json', content_type='application/json'), 400)
    # un contratto di un altro lotto
    proposta = _ok(napoli.get('/api/napoli/lotti/proposta'))
    altro = _ok(napoli.post('/api/napoli/lotti/procedura', json={
        'lotto': dict(proposta['lotto'], municipalita='3'), 'tariffe': proposta['tariffe'],
        'valido_da': proposta['valido_da'], 'valido_a': proposta['valido_a']}))['lotto']['id']
    _errore(napoli.put(f'/api/napoli/lotti/{altro}/coordinamento', json={
        'anno': 2026, 'mese': 11, 'contratto_id': napoli.contratti['XI'], 'grado': 'inferiore', 'ore': '1'}),
        400, campo='contratto_id')
    assert _righe(napoli.percorso, 'SELECT * FROM napoli_coordinamento') == []
    # giugno del contratto X (dall'08): si scrive, con il periodo tagliato
    assert _ok(_salva(napoli, numero='X', mese=6, ore='12,25'))['riga']['periodo_testo'] == \
        'dal 08/06/2026 al 30/06/2026'
    # ore rimaste fuori dalle date del contratto (scritte prima, per esempio da un database di
    # sviluppo): si vedono, si possono togliere, non cambiare
    _scrivi(napoli.percorso, "INSERT INTO napoli_coordinamento (lotto_id, grado, contratto_id, anno, mese, ore_cent) "
                             "VALUES (?, 'inferiore', ?, 2026, 9, 500)", (napoli.lotto_id, napoli.contratti['X']))
    fuori = _riga(_elenco(napoli), 2026, 9, 'X', 'inferiore')
    assert (fuori['fuori_contratto'], fuori['ore'], fuori['periodo_testo']) == (True, '5,00',
                                                                                 'fuori dalle date del contratto')
    _errore(_salva(napoli, numero='X', mese=9, ore='6'), 400, 'FUORI_CONTRATTO')
    _ok(_salva(napoli, numero='X', mese=9, ore=''))
    assert _righe(napoli.percorso, 'SELECT mese FROM napoli_coordinamento') == [{'mese': 6}]


# ==================== mese chiuso ====================

def test_mese_chiuso_del_lotto(napoli):
    _ok(_salva(napoli, mese=10, ore='20'))
    _scrivi(napoli.percorso, "INSERT INTO napoli_mesi_chiusi (lotto_id, anno, mese, data_chiusura) "
                             "VALUES (?, 2026, 10, '2026-11-04T10:00:00')", (napoli.lotto_id,))
    dati = _errore(_salva(napoli, mese=10, ore='25'), 409, 'MESE_CHIUSO_LOTTO', campo='ore')
    assert dati['error'].startswith('Ottobre 2026 di ') and 'è chiuso' in dati['error']
    _errore(_salva(napoli, mese=10, grado='superiore', ore='5'), 409, 'MESE_CHIUSO_LOTTO')
    _errore(_salva(napoli, mese=10, ore=''), 409, 'MESE_CHIUSO_LOTTO')
    ottobre = next(m for m in _elenco(napoli)['mesi'] if m['mese'] == 10)
    assert ottobre['chiuso'] is True and ottobre['righe'][0]['ore'] == '20,00'
    # Ctrl+Z di una modifica del mese, chiuso dopo: non si annulla
    _ok(_salva(napoli, mese=9, ore='30'))
    _scrivi(napoli.percorso, "INSERT INTO napoli_mesi_chiusi (lotto_id, anno, mese, data_chiusura) "
                             "VALUES (?, 2026, 9, '2026-11-05T10:00:00')", (napoli.lotto_id,))
    dati = _errore(napoli.post('/api/napoli/annulla', json={}), 409, 'MESE_CHIUSO_LOTTO')
    assert 'settembre 2026 è stato chiuso' in dati['error']
    assert {(r['mese'], r['ore_cent']) for r in _righe(napoli.percorso, 'SELECT * FROM napoli_coordinamento')} == {
        (10, 2000), (9, 3000)}


# ==================== contratti, registro, fattura ====================

def test_il_contratto_con_le_ore_non_le_lascia_fuori(napoli):
    _ok(_salva(napoli, mese=9, grado='superiore', ore='4'))
    url = f'/api/napoli/contratti/{napoli.contratti["XI"]}'
    dati = _errore(napoli.put(url, json={'numero': 'XI', 'grado': '', 'valido_da': '2026-10-01',
                                         'valido_a': '2027-01-31'}), 409, 'CONTRATTO_USATO')
    assert 'settembre 2026 (grado superiore)' in dati['error']
    _errore(napoli.put(url, json={'numero': 'XI', 'grado': 'inferiore', 'valido_da': '2026-09-01',
                                  'valido_a': '2027-01-31'}), 409, 'CONTRATTO_USATO')
    _errore(napoli.delete(url), 409, 'CONTRATTO_USATO')
    # le date che comprendono ancora il mese si possono cambiare
    _ok(napoli.put(url, json={'numero': 'XI', 'grado': '', 'valido_da': '2026-09-15', 'valido_a': '2027-01-31'}))


def test_registro_attivita_senza_nomi_e_fattura_con_le_ore(napoli):
    _ok(_salva(napoli, ore='71,55', nota='Riepilogo di prova'))
    voci = _righe(napoli.percorso, "SELECT * FROM audit_log WHERE entita = 'napoli_coordinamento'")
    assert [v['dettagli'] for v in voci] == [
        'Napoli, NAPOLI LOTTO 1: Ore del coordinatore: novembre 2026, contratto XI (grado inferiore), 71,55']
    memoria = [json.loads(a['dati']) for a in _righe(napoli.percorso, 'SELECT dati FROM napoli_annullamenti')]
    assert {'tabella': 'coordinamento', 'chiave': 1, 'prima': None} in memoria[-1]['righe']
    # le ore salvate entrano nella riga "Coordinatore" della fattura, come la fattura reale di giugno
    righe = _righe(napoli.percorso, 'SELECT ore_cent FROM napoli_coordinamento')
    tariffe = _righe(napoli.percorso, 'SELECT * FROM napoli_tariffe WHERE lotto_id = ?', (napoli.lotto_id,))
    calcolo = nc.righe_fattura([], tariffe, 'inferiore', '2026-11-01', '2026-11-30', righe)
    coordinatore = [r for r in calcolo['righe'] if r['figura'] == 'COORDINATORE']
    assert [(str(r['ore']), r['tariffa_cent'], r['importo_cent']) for r in coordinatore] == [('71.55', 2966, 212217)]


def test_la_scheda_mese_ha_il_riquadro(napoli):
    pagina = napoli.get('/napoli').get_data(as_text=True)
    assert 'id="napoli-coordinatore"' in pagina and 'Ore del coordinatore' in pagina
    assert 'id="coord-salvataggio"' in pagina and 'NapoliMese.avvia()' in pagina

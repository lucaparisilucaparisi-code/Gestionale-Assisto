"""Sezione Napoli, passo 1.3: Impostazioni (routes_napoli, napoli_db) e pagine.

- Procedura "Crea il primo lotto": NAPOLI LOTTO 1 con le tariffe proposte (IVA
  esclusa, dal 01/09/2025 al 31/01/2027, interprete LIS senza tariffa), un solo Ctrl+Z.
- Controlli lato server con messaggi semplici e il campo sbagliato: lotti (nome e
  numero doppi, CIG, segnaposto), tariffe e contratti con date sovrapposte (rifiutati;
  per le tariffe la proposta "chiudi la precedente"), regole con data, IBAN e partita
  IVA, qualifiche.
- Ctrl+Z di Napoli separato da quello di Roma; l'IBAN non torna mai intero alla
  pagina e non finisce nel registro attivita'.
- Le scritture di Napoli non toccano le tabelle di Roma; le pagine si aprono.

Ogni test lavora su un database vuoto (database_isolato): anche con
ASSISTO_TEST_CON_NAPOLI=1 il lotto 1 e' libero. Solo dati inventati.
"""
import datetime
import html.parser
import json
import sqlite3

import pytest

import seme_napoli
from strumenti import fotografa_roma

VUOTI = frozenset({'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track',
                   'wbr'})
TARIFFE_PROPOSTE = {'ASACOM': 2344, 'EDUCATORE': 2428, 'TIFLOLOGO': 2428, 'PSICOLOGO': 2966, 'COORDINATORE': 2966}


@pytest.fixture
def napoli(database_isolato, app_module, db_mod):
    """Client autenticato sul database vuoto del test."""
    return fotografa_roma.client_fotografia(app_module.app, db_mod)


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


def crea_lotto_proposto(client, **cambi):
    """La procedura guidata con i valori proposti (piu' le municipalita')."""
    proposta = _ok(client.get('/api/napoli/lotti/proposta'))
    lotto = dict(proposta['lotto'], municipalita='1 e 2', cig='ZZ00000000')
    lotto.update(cambi)
    return _ok(client.post('/api/napoli/lotti/procedura', json={
        'lotto': lotto, 'tariffe': proposta['tariffe'],
        'valido_da': proposta['valido_da'], 'valido_a': proposta['valido_a']}))['lotto']


# ==================== procedura "Crea il primo lotto" ====================

def test_la_procedura_crea_napoli_lotto_1_con_le_tariffe_proposte(napoli, database_isolato):
    proposta = _ok(napoli.get('/api/napoli/lotti/proposta'))
    assert proposta['lotto']['nome'] == 'NAPOLI LOTTO 1' and proposta['lotto']['numero_lotto'] == 1
    assert proposta['numeri_liberi'] == [1, 2, 3, 4, 5]
    assert (proposta['valido_da'], proposta['valido_a']) == ('2025-09-01', '2027-01-31')
    assert {t['figura']: t['tariffa'] for t in proposta['tariffe']} == {
        'ASACOM': '23,44', 'EDUCATORE': '24,28', 'LIS': '', 'TIFLOLOGO': '24,28', 'PSICOLOGO': '29,66',
        'COORDINATORE': '29,66'}
    assert '{contratto} APPLICATIVO' in proposta['lotto']['oggetto_fattura']

    lotto = crea_lotto_proposto(napoli)
    assert lotto['nome'] == 'NAPOLI LOTTO 1' and lotto['municipalita'] == '1 e 2' and lotto['cig'] == 'ZZ00000000'
    tariffe = _ok(napoli.get(f'/api/napoli/lotti/{lotto["id"]}/tariffe'))
    assert {t['figura']: t['tariffa_cent'] for t in tariffe} == TARIFFE_PROPOSTE   # LIS vuota: nessuna riga
    assert {(t['valido_da'], t['valido_a'], t['livello_ccnl']) for t in tariffe} == {('2025-09-01', '2027-01-31', None)}
    assert [t['tariffa'] for t in tariffe][:2] == ['23,44', '24,28']

    # un'unica azione per Ctrl+Z: annullandola spariscono lotto e tariffe
    ultima = _ok(napoli.get('/api/napoli/annulla/ultima'))['azione']
    assert ultima['descrizione'] == 'Nuovo lotto NAPOLI LOTTO 1 con 5 tariffe'
    _ok(napoli.post('/api/napoli/annulla', json={'id': ultima['id']}))
    assert _ok(napoli.get('/api/napoli/lotti')) == []
    assert _righe(database_isolato, 'SELECT * FROM napoli_tariffe') == []
    assert _ok(napoli.get('/api/napoli/annulla/ultima'))['azione'] is None


def test_la_procedura_controlla_tutto_e_non_scrive_niente_se_sbaglia(napoli, database_isolato):
    proposta = _ok(napoli.get('/api/napoli/lotti/proposta'))
    base = {'lotto': dict(proposta['lotto'], municipalita='1 e 2'), 'tariffe': proposta['tariffe'],
            'valido_da': '2025-09-01', 'valido_a': '2027-01-31'}
    casi = (
        (dict(base, lotto=dict(base['lotto'], municipalita='')), 'municipalita', 'municipalità'),
        (dict(base, lotto=dict(base['lotto'], nome='  ')), 'nome', 'nome del lotto'),
        (dict(base, lotto=dict(base['lotto'], cig='12345')), 'cig', '10 caratteri'),
        (dict(base, lotto=dict(base['lotto'], numero_lotto=6)), 'numero_lotto', 'da 1 a 5'),
        (dict(base, lotto=dict(base['lotto'], oggetto_fattura='Lotto {lotto} {mesi}')), 'oggetto_fattura', '{mesi}'),
        (dict(base, valido_da='31/02/2026'), 'valido_da', 'non esiste'),
        (dict(base, valido_a='2025-08-31'), 'valido_a', 'viene prima'),
        (dict(base, tariffe=[{'figura': 'ASACOM', 'tariffa': '23,445'}]), 'tariffe.0', 'due decimali'),
        (dict(base, tariffe=[{'figura': 'ASACOM', 'tariffa': 'tanto'}]), 'tariffe.0', 'non è un numero'),
        (dict(base, tariffe=[{'figura': 'BIDELLO', 'tariffa': '10'}]), 'figura', 'non esiste'),
    )
    for dati, campo, testo in casi:
        errore = _errore(napoli.post('/api/napoli/lotti/procedura', json=dati), 400, 'DATI_NON_VALIDI', campo)
        assert testo in errore['error'], errore
    assert _righe(database_isolato, 'SELECT id FROM napoli_lotti') == []
    assert _righe(database_isolato, 'SELECT id FROM napoli_annullamenti') == []
    _errore(napoli.post('/api/napoli/lotti/procedura', data='niente', content_type='text/plain'), 400)


def test_nome_e_numero_del_lotto_non_si_ripetono(napoli):
    primo = crea_lotto_proposto(napoli)
    assert _ok(napoli.get('/api/napoli/lotti/proposta'))['lotto']['nome'] == 'NAPOLI LOTTO 2'
    _errore(napoli.post('/api/napoli/lotti', json={'nome': 'napoli lotto 1', 'numero_lotto': 2, 'municipalita': '3'}),
            409, 'LOTTO_GIA_PRESENTE', 'nome')
    errore = _errore(napoli.post('/api/napoli/lotti', json={'nome': 'ALTRO', 'numero_lotto': 1, 'municipalita': '3'}),
                     409, 'LOTTO_GIA_PRESENTE', 'numero_lotto')
    assert 'NAPOLI LOTTO 1' in errore['error']
    secondo = _ok(napoli.post('/api/napoli/lotti', json={'nome': 'NAPOLI LOTTO 2', 'numero_lotto': '2',
                                                         'municipalita': '3', 'codice_univoco_ufficio': 'zz zz zz'}))
    assert secondo['lotto']['codice_univoco_ufficio'] == 'ZZZZZZ'
    # la modifica cambia solo i campi mandati e controlla di nuovo tutto
    cambiato = _ok(napoli.put(f'/api/napoli/lotti/{primo["id"]}', json={'cig': 'aa11bb22cc', 'attivo': False}))['lotto']
    assert (cambiato['cig'], cambiato['attivo'], cambiato['nome']) == ('AA11BB22CC', 0, 'NAPOLI LOTTO 1')
    _errore(napoli.put(f'/api/napoli/lotti/{primo["id"]}', json={'numero_lotto': 2}), 409, 'LOTTO_GIA_PRESENTE')
    _errore(napoli.put('/api/napoli/lotti/999', json={'cig': ''}), 404, 'NON_TROVATO')
    _errore(napoli.get(f'/api/napoli/lotti/{primo["id"]}/controlli?giorno=2026-02-30'), 400, None, 'giorno')
    _errore(napoli.get('/api/napoli/regole?giorno=domani'), 400, None, 'giorno')
    _errore(napoli.get('/api/napoli/regole?lotto_id=uno'), 400, None, 'lotto_id')


def test_un_lotto_si_elimina_solo_senza_dati(napoli, database_isolato):
    lotto = crea_lotto_proposto(napoli)
    _ok(napoli.post(f'/api/napoli/lotti/{lotto["id"]}/contratti', json={
        'numero': 'XI', 'grado': 'inferiore', 'valido_da': '2026-06-08', 'valido_a': '2026-07-31'}))
    _ok(napoli.delete(f'/api/napoli/lotti/{lotto["id"]}'))
    assert _ok(napoli.get('/api/napoli/lotti')) == []
    _ok(napoli.post('/api/napoli/annulla', json={}))        # Ctrl+Z: tornano lotto, contratto e tariffe
    assert [r['nome'] for r in _ok(napoli.get('/api/napoli/lotti'))] == ['NAPOLI LOTTO 1']
    assert len(_ok(napoli.get(f'/api/napoli/lotti/{lotto["id"]}/tariffe'))) == 5
    assert len(_ok(napoli.get(f'/api/napoli/lotti/{lotto["id"]}/contratti'))) == 1

    conn = sqlite3.connect(database_isolato)
    with conn:
        conn.execute("INSERT INTO napoli_scuole (lotto_id, nome, data_inserimento) VALUES (?, 'Scuola di prova', 'x')",
                     (lotto['id'],))
    conn.close()
    _errore(napoli.delete(f'/api/napoli/lotti/{lotto["id"]}'), 409, 'LOTTO_CON_DATI')


# ==================== tariffe ====================

def test_tariffe_con_date_sovrapposte_rifiutate(napoli, database_isolato):
    lotto = crea_lotto_proposto(napoli)['id']
    url = f'/api/napoli/lotti/{lotto}/tariffe'
    errore = _errore(napoli.post(url, json={'figura': 'ASACOM', 'tariffa': '24', 'valido_da': '2026-01-01'}),
                     409, 'TARIFFE_SOVRAPPOSTE', 'valido_da')
    assert 'Asacom 23,44 euro dal 01/09/2025 al 31/01/2027' in errore['error']
    assert 'non si possono avere' in errore['error']
    # la precedente comincia prima: si puo' chiudere il giorno prima della nuova
    assert [c['nuova_fine'] for c in errore['chiudibili']] == ['2025-12-31']
    # una tariffa che comincia prima di quella che c'e' non la puo' chiudere
    errore = _errore(napoli.post(url, json={'figura': 'ASACOM', 'tariffa': '24', 'valido_da': '2025-01-01',
                                            'valido_a': '2025-09-01'}), 409, 'TARIFFE_SOVRAPPOSTE')
    assert errore['chiudibili'] == []
    # stessa figura dopo la fine, un livello diverso, un'altra figura: si'
    _ok(napoli.post(url, json={'figura': 'ASACOM', 'tariffa': '24,08', 'valido_da': '2027-02-01'}))
    _ok(napoli.post(url, json={'figura': 'EDUCATORE', 'livello_ccnl': 'd2', 'tariffa': '25', 'valido_da': '2026-01-01'}))
    _ok(napoli.post(url, json={'figura': 'LIS', 'tariffa': '25,44', 'valido_da': '2025-09-01'}))
    # ora la nuova ASACOM 2027 e' senza fine: una dal 2028 si accetta solo chiudendo quella
    _errore(napoli.post(url, json={'figura': 'ASACOM', 'tariffa': '25', 'valido_da': '2028-01-01'}), 409)
    nuova = _ok(napoli.post(url, json={'figura': 'ASACOM', 'tariffa': '25', 'valido_da': '2028-01-01',
                                       'chiudi_precedenti': True}))['tariffa']
    asacom = _righe(database_isolato, "SELECT valido_da, valido_a, tariffa_cent FROM napoli_tariffe "
                                      "WHERE figura = 'ASACOM' ORDER BY valido_da")
    assert asacom == [{'valido_da': '2025-09-01', 'valido_a': '2027-01-31', 'tariffa_cent': 2344},
                      {'valido_da': '2027-02-01', 'valido_a': '2027-12-31', 'tariffa_cent': 2408},
                      {'valido_da': '2028-01-01', 'valido_a': None, 'tariffa_cent': 2500}]
    # Ctrl+Z della nuova rimette anche la fine di prima
    _ok(napoli.post('/api/napoli/annulla', json={}))
    assert [r['valido_a'] for r in _righe(database_isolato, "SELECT valido_a FROM napoli_tariffe "
                                                            "WHERE figura = 'ASACOM' ORDER BY valido_da")] == [
        '2027-01-31', None]
    # la modifica di una tariffa controlla le sovrapposizioni con le altre, non con se stessa
    prima = _righe(database_isolato, "SELECT id FROM napoli_tariffe WHERE figura = 'ASACOM' ORDER BY valido_da")[0]
    _ok(napoli.put(f'/api/napoli/tariffe/{prima["id"]}', json={'figura': 'ASACOM', 'tariffa': '23,50',
                                                               'valido_da': '2025-09-01', 'valido_a': '2027-01-31'}))
    _errore(napoli.put(f'/api/napoli/tariffe/{prima["id"]}', json={'figura': 'ASACOM', 'tariffa': '23,50',
                                                                   'valido_da': '2025-09-01', 'valido_a': '2027-03-01'}),
            409, 'TARIFFE_SOVRAPPOSTE')
    _errore(napoli.delete(f'/api/napoli/tariffe/{nuova["id"]}'), 404, 'NON_TROVATO')   # annullata con Ctrl+Z
    _errore(napoli.post(url, json={'figura': 'ASACOM', 'tariffa': '0', 'valido_da': '2030-01-01'}), 400,
            'DATI_NON_VALIDI', 'tariffa')
    _errore(napoli.post(url, json={'figura': '', 'tariffa': '10', 'valido_da': '2030-01-01'}), 400, None, 'figura')


def test_una_tariffa_o_una_regola_per_pochi_mesi_non_lascia_giorni_scoperti(napoli, database_isolato):
    """La nuova finisce prima della precedente: la proposta non chiude soltanto la
    precedente (dopo la nuova non varrebbe piu' niente: una tariffa che manca, una regola
    che torna in silenzio al valore predefinito) ma la divide, prima e dopo la nuova.
    Un solo Ctrl+Z rimette tutto com'era."""
    lotto = crea_lotto_proposto(napoli)['id']
    url = f'/api/napoli/lotti/{lotto}/tariffe'
    sql = "SELECT valido_da, valido_a, tariffa_cent, fonte FROM napoli_tariffe WHERE figura = 'ASACOM' ORDER BY valido_da"
    breve = {'figura': 'ASACOM', 'tariffa': '24', 'valido_da': '2026-01-01', 'valido_a': '2026-03-31'}
    errore = _errore(napoli.post(url, json=breve), 409, 'TARIFFE_SOVRAPPOSTE', 'valido_da')
    assert [(c['nuova_fine'], c['riprende_da'], c['riprende_a']) for c in errore['chiudibili']] == [
        ('2025-12-31', '2026-04-01', '2027-01-31')]
    assert 'chiudi la tariffa precedente' not in errore['error']
    assert ('fai valere la nuova tariffa solo in questi giorni: la tariffa precedente varrà dal 01/09/2025 al '
            '31/12/2025 e di nuovo dal 01/04/2026 al 31/01/2027') in errore['error']
    assert _righe(database_isolato, sql)[0]['valido_a'] == '2027-01-31'       # il rifiuto non cambia niente
    r = _ok(napoli.post(url, json=dict(breve, chiudi_precedenti=True)))
    assert r['messaggio'] == ('Tariffa aggiunta. La tariffa precedente ora vale dal 01/09/2025 al 31/12/2025 e di '
                              'nuovo dal 01/04/2026 al 31/01/2027.')
    assert 'nota' not in r['tariffa']
    asacom = _righe(database_isolato, sql)
    assert [(a['valido_da'], a['valido_a'], a['tariffa_cent']) for a in asacom] == [
        ('2025-09-01', '2025-12-31', 2344), ('2026-01-01', '2026-03-31', 2400), ('2026-04-01', '2027-01-31', 2344)]
    assert asacom[2]['fonte'] == asacom[0]['fonte'] and asacom[0]['fonte']
    controlli = {c['codice']: c for c in _ok(napoli.get(f'/api/napoli/lotti/{lotto}/controlli?giorno=2026-06-15'))}
    assert controlli['tariffa_ASACOM']['stato'] == 'ok' and '23,44' in controlli['tariffa_ASACOM']['testo']
    _ok(napoli.post('/api/napoli/annulla', json={}))
    assert [(a['valido_da'], a['valido_a'], a['tariffa_cent']) for a in _righe(database_isolato, sql)] == [
        ('2025-09-01', '2027-01-31', 2344)]
    # la nuova arriva fino alla fine della precedente (o oltre, o senza fine): la si chiude e basta
    for fine in ('2027-01-31', '2027-06-30', ''):
        errore = _errore(napoli.post(url, json=dict(breve, valido_a=fine)), 409, 'TARIFFE_SOVRAPPOSTE')
        assert errore['chiudibili'] == [{'id': errore['chiudibili'][0]['id'], 'valido_da': '2025-09-01',
                                         'nuova_fine': '2025-12-31'}]
        assert 'chiudi la tariffa precedente al 31/12/2025' in errore['error']

    # regole: la ritenuta cambiata per un solo mese, su un valore senza fine
    _ok(napoli.post('/api/napoli/regole', json={'chiave': 'ritenuta_percento', 'valore': '0,5',
                                                'valido_da': '2025-09-01'}))
    mese = {'chiave': 'ritenuta_percento', 'valore': '1', 'valido_da': '2026-02-01', 'valido_a': '2026-02-28'}
    errore = _errore(napoli.post('/api/napoli/regole', json=mese), 409, 'REGOLE_SOVRAPPOSTE')
    assert [(c['nuova_fine'], c['riprende_da'], c['riprende_a']) for c in errore['chiudibili']] == [
        ('2026-01-31', '2026-03-01', None)]
    assert 'di nuovo dal 01/03/2026 (senza data di fine)' in errore['error']
    r = _ok(napoli.post('/api/napoli/regole', json=dict(mese, chiudi_precedenti=True)))
    assert 'Il valore precedente ora vale dal 01/09/2025 al 31/01/2026 e di nuovo dal 01/03/2026' in r['messaggio']
    for giorno, atteso in (('2026-01-31', '0,5'), ('2026-02-15', '1'), ('2026-03-01', '0,5'), ('2030-01-01', '0,5')):
        elenco = {x['chiave']: x for x in _ok(napoli.get(f'/api/napoli/regole?giorno={giorno}'))['regole']}
        assert (elenco['ritenuta_percento']['valore'], elenco['ritenuta_percento']['origine']) == (atteso, 'tutti'), giorno
    marzo = _righe(database_isolato, "SELECT id FROM napoli_regole WHERE valido_da = '2026-03-01'")[0]['id']
    _ok(napoli.post('/api/napoli/annulla', json={}))
    sql = "SELECT valore, valido_da, valido_a FROM napoli_regole ORDER BY valido_da"
    assert _righe(database_isolato, sql) == [{'valore': '0.5', 'valido_da': '2025-09-01', 'valido_a': None}]
    _errore(napoli.delete(f'/api/napoli/regole/{marzo}'), 404, 'NON_TROVATO')     # la copia se n'e' andata
    # anche la modifica di un valore salvato: una regola dal 2040 spostata a febbraio 2026
    dal_2040 = _ok(napoli.post('/api/napoli/regole', json={'chiave': 'ritenuta_percento', 'valore': '2',
                                                           'valido_da': '2040-01-01', 'chiudi_precedenti': True}))
    assert dal_2040['messaggio'] == 'Regola salvata. Il valore precedente ora vale dal 01/09/2025 al 31/12/2039.'
    _ok(napoli.put(f'/api/napoli/regole/{dal_2040["regola"]["id"]}', json=dict(mese, chiudi_precedenti=True)))
    assert _righe(database_isolato, sql) == [
        {'valore': '0.5', 'valido_da': '2025-09-01', 'valido_a': '2026-01-31'},
        {'valore': '1', 'valido_da': '2026-02-01', 'valido_a': '2026-02-28'},
        {'valore': '0.5', 'valido_da': '2026-03-01', 'valido_a': '2039-12-31'}]
    # una nuova che comincia lo stesso giorno della precedente: niente da proporre
    errore = _errore(napoli.post('/api/napoli/regole', json={'chiave': 'ritenuta_percento', 'valore': '2',
                                                             'valido_da': '2025-09-01', 'chiudi_precedenti': True}), 409)
    assert errore['chiudibili'] == [] and errore['error'].endswith('cambia le date.')


# ==================== contratti applicativi ====================

def test_contratti_sovrapposti_dello_stesso_lotto_e_grado_rifiutati(napoli, database_isolato):
    lotto = crea_lotto_proposto(napoli)['id']
    url = f'/api/napoli/lotti/{lotto}/contratti'
    xi = _ok(napoli.post(url, json={'numero': 'xi', 'grado': 'inferiore', 'valido_da': '08/06/2026',
                                    'valido_a': '31/07/2026', 'dd_servizio': '1093', 'dd_numero': '31',
                                    'dd_data': '12/06/2026', 'importo': '1.234,50'}))['contratto']
    assert (xi['numero'], xi['valido_da'], xi['dd_data'], xi['dd_servizio'], xi['importo_cent']) == (
        'XI', '2026-06-08', '2026-06-12', '1093', 123450)
    errore = _errore(napoli.post(url, json={'numero': 'XII', 'grado': 'inferiore', 'valido_da': '2026-07-01',
                                            'valido_a': '2026-12-31'}), 409, 'CONTRATTI_SOVRAPPOSTI', 'valido_da')
    assert 'XI (grado inferiore, dal 08/06/2026 al 31/07/2026)' in errore['error']
    assert 'due fatture' in errore['error']
    # un contratto senza grado vale per tutti e due: si sovrappone anche lui
    _errore(napoli.post(url, json={'numero': 'XII', 'grado': '', 'valido_da': '2026-07-01', 'valido_a': '2026-12-31'}),
            409, 'CONTRATTI_SOVRAPPOSTI')
    # l'altro grado e i giorni dopo vanno bene
    _ok(napoli.post(url, json={'numero': 'XI', 'grado': 'superiore', 'valido_da': '2026-06-08',
                               'valido_a': '2026-07-31'}))
    xii = _ok(napoli.post(url, json={'numero': 'XII', 'grado': 'inferiore', 'valido_da': '2026-08-01',
                                     'valido_a': '2026-12-31'}))['contratto']
    _errore(napoli.post(url, json={'numero': 'XI', 'grado': 'inferiore', 'valido_da': '2027-01-01',
                                   'valido_a': '2027-06-30'}), 409, 'CONTRATTO_GIA_PRESENTE', 'numero')
    # date: la fine e' obbligatoria e viene dopo l'inizio
    _errore(napoli.post(url, json={'numero': 'XIII', 'grado': 'inferiore', 'valido_da': '2027-01-01'}), 400, None,
            'valido_a')
    _errore(napoli.post(url, json={'numero': 'XIII', 'grado': 'inferiore', 'valido_da': '2027-01-01',
                                   'valido_a': '2026-12-31'}), 400, None, 'valido_a')
    _errore(napoli.post(url, json={'numero': 'XIII', 'grado': 'medio', 'valido_da': '2027-01-01',
                                   'valido_a': '2027-02-01'}), 400, None, 'grado')
    # spostare XII sopra XI e' rifiutato; un contratto con ore del coordinatore non si elimina
    _errore(napoli.put(f'/api/napoli/contratti/{xii["id"]}', json={'numero': 'XII', 'grado': 'inferiore',
                                                                  'valido_da': '2026-07-15', 'valido_a': '2026-12-31'}),
            409, 'CONTRATTI_SOVRAPPOSTI')
    conn = sqlite3.connect(database_isolato)
    with conn:
        conn.execute("INSERT INTO napoli_coordinamento (lotto_id, grado, contratto_id, anno, mese, ore_cent) "
                     "VALUES (?, 'inferiore', ?, 2026, 6, 7155)", (lotto, xi['id']))
    conn.close()
    _errore(napoli.delete(f'/api/napoli/contratti/{xi["id"]}'), 409, 'CONTRATTO_USATO')
    assert [c['usato'] for c in _ok(napoli.get(url))] == [True, False, False]
    _ok(napoli.delete(f'/api/napoli/contratti/{xii["id"]}'))


# ==================== cooperativa e destinatario ====================

IBAN_DI_PROVA = seme_napoli.iban_inventato('000000004321')


def test_iban_sbagliato_rifiutato_e_mostrato_solo_mascherato(napoli, database_isolato):
    url = '/api/napoli/impostazioni/cooperativa'
    sbagliato = IBAN_DI_PROVA[:-1] + ('2' if IBAN_DI_PROVA[-1] != '2' else '3')
    for iban, testo in ((sbagliato, 'cifre di controllo'), (IBAN_DI_PROVA[:-1], 'ne ha 27'),
                        ('IT60 X054 28!', 'IT e poi 25'), ('12345', 'due lettere del paese')):
        errore = _errore(napoli.put(url, json={'cooperativa_iban': iban}), 400, 'DATI_NON_VALIDI', 'cooperativa_iban')
        assert testo in errore['error'], errore
    assert _righe(database_isolato, 'SELECT * FROM napoli_impostazioni') == []

    con_spazi = ' '.join(IBAN_DI_PROVA[i:i + 4] for i in range(0, 27, 4)).lower()
    r = _ok(napoli.put(url, json={'cooperativa_iban': con_spazi, 'cooperativa_denominazione': ' Cooperativa  di prova ',
                                  'cooperativa_partita_iva': '12345678903', 'cooperativa_provincia': 'na',
                                  'cooperativa_cap': '80100'}))
    assert sorted(r['cambiati']) == ['CAP', 'IBAN', 'Partita IVA', 'Provincia', 'Ragione sociale']
    salvate = {x['chiave']: x['valore'] for x in _righe(database_isolato, 'SELECT * FROM napoli_impostazioni')}
    assert salvate['cooperativa_iban'] == IBAN_DI_PROVA and salvate['cooperativa_provincia'] == 'NA'
    assert salvate['cooperativa_denominazione'] == 'Cooperativa di prova'
    pagina = napoli.get('/api/napoli/impostazioni').get_data(as_text=True)
    assert IBAN_DI_PROVA not in pagina and IBAN_DI_PROVA[4:-4] not in pagina
    cooperativa = json.loads(pagina)['cooperativa']
    assert cooperativa['iban_salvato'] and cooperativa['iban_mascherato'].endswith(IBAN_DI_PROVA[-4:])
    assert 'cooperativa_iban' not in cooperativa
    # un campo che non arriva resta com'e'; uno vuoto si toglie
    assert _ok(napoli.put(url, json={'cooperativa_banca': 'Banca di prova'}))['cambiati'] == ['Banca']
    assert _ok(napoli.put(url, json={'cooperativa_cap': ''}))['cambiati'] == ['CAP']
    salvate = {x['chiave']: x['valore'] for x in _righe(database_isolato, 'SELECT * FROM napoli_impostazioni')}
    assert salvate['cooperativa_iban'] == IBAN_DI_PROVA and 'cooperativa_cap' not in salvate
    # partita IVA, codice fiscale, CAP e provincia controllati
    for campo, valore in (('cooperativa_partita_iva', '12345678901'), ('cooperativa_partita_iva', '1234'),
                          ('cooperativa_codice_fiscale', '12345678901'), ('cooperativa_codice_fiscale', 'ABC'),
                          ('cooperativa_cap', '8013'), ('cooperativa_provincia', 'Napoli')):
        _errore(napoli.put(url, json={campo: valore}), 400, 'DATI_NON_VALIDI', campo)
    # mai l'IBAN nel registro attivita' o nelle descrizioni di Ctrl+Z
    audit = json.dumps(_righe(database_isolato, "SELECT * FROM audit_log WHERE entita LIKE 'napoli%'"))
    descrizioni = json.dumps(_righe(database_isolato, 'SELECT descrizione FROM napoli_annullamenti'))
    assert 'napoli_impostazioni' in audit and IBAN_DI_PROVA not in audit and IBAN_DI_PROVA not in descrizioni


def test_destinatario_proposto_e_usato_dalla_fattura(napoli, database_isolato):
    dati = _ok(napoli.get('/api/napoli/impostazioni'))
    assert not dati['destinatario_salvato'] and dati['destinatario_testo'] == ''
    proposto = dati['destinatario_proposto']
    assert proposto['destinatario_denominazione'].startswith('Comune di Napoli')
    _ok(napoli.put('/api/napoli/impostazioni/destinatario', json=dict(proposto, destinatario_denominazione='ENTE DI PROVA')))
    dati = _ok(napoli.get('/api/napoli/impostazioni'))
    assert dati['destinatario_salvato'] and dati['destinatario_testo'].startswith('ENTE DI PROVA, ')
    # senza un destinatario del lotto vale quello delle impostazioni
    lotto = crea_lotto_proposto(napoli)
    controlli = {c['codice']: c for c in _ok(napoli.get(f'/api/napoli/lotti/{lotto["id"]}/controlli'))}
    assert controlli['destinatario']['stato'] == 'ok' and 'ENTE DI PROVA' in controlli['destinatario']['testo']
    _errore(napoli.put('/api/napoli/impostazioni/destinatario', json={'destinatario_codice_fiscale': '80000000000'}),
            400, 'DATI_NON_VALIDI', 'destinatario_codice_fiscale')
    _errore(napoli.put('/api/napoli/impostazioni/altro', json={}), 404)


# ==================== regole con data ====================

def test_regole_con_data_controllate_e_senza_sovrapposizioni(napoli, database_isolato):
    lotto = crea_lotto_proposto(napoli)['id']
    elenco = _ok(napoli.get(f'/api/napoli/regole?lotto_id={lotto}&giorno=2026-11-04'))
    regole = {r['chiave']: r for r in elenco['regole']}
    assert regole['quota_assenza_alunno']['valore'] == '0,5' and regole['quota_assenza_alunno']['origine'] == 'predefinita'
    assert regole['ritenuta_percento']['valore_testo'] == '0,50%' and regole['max_minuti_giorno_avviso']['valore_testo'] == '5 ore'
    assert regole['split_payment']['valore_testo'] == 'Sì'
    assert {g['codice'] for g in elenco['gruppi']} >= {'ore', 'fattura', 'fase_2'}

    _ok(napoli.post('/api/napoli/regole', json={'chiave': 'quota_assenza_alunno', 'valore': '0,5',
                                                'valido_da': '2025-09-01', 'fonte': 'contratto attuale'}))
    errore = _errore(napoli.post('/api/napoli/regole', json={'chiave': 'quota_assenza_alunno', 'valore': '0',
                                                             'valido_da': '2027-02-01'}), 409, 'REGOLE_SOVRAPPOSTE')
    assert errore['chiudibili'][0]['nuova_fine'] == '2027-01-31'
    _ok(napoli.post('/api/napoli/regole', json={'chiave': 'quota_assenza_alunno', 'valore': '0',
                                                'valido_da': '2027-02-01', 'chiudi_precedenti': True}))
    # una regola solo per il lotto non si sovrappone a quella di tutti i lotti
    _ok(napoli.post('/api/napoli/regole', json={'chiave': 'quota_assenza_alunno', 'valore': '0,25', 'lotto_id': lotto,
                                                'valido_da': '2026-01-01', 'valido_a': '2026-01-31'}))
    elenco = {r['chiave']: r for r in _ok(napoli.get(f'/api/napoli/regole?lotto_id={lotto}&giorno=2026-01-15'))['regole']}
    assert (elenco['quota_assenza_alunno']['valore'], elenco['quota_assenza_alunno']['origine']) == ('0,25', 'lotto')
    elenco = {r['chiave']: r for r in _ok(napoli.get(f'/api/napoli/regole?lotto_id={lotto}&giorno=2027-03-01'))['regole']}
    assert (elenco['quota_assenza_alunno']['valore'], elenco['quota_assenza_alunno']['origine']) == ('0', 'tutti')
    assert len(elenco['quota_assenza_alunno']['salvate']) == 3
    salvate = _righe(database_isolato, "SELECT lotto_id, valore, valido_da, valido_a FROM napoli_regole ORDER BY id")
    assert salvate == [{'lotto_id': None, 'valore': '0.5', 'valido_da': '2025-09-01', 'valido_a': '2027-01-31'},
                       {'lotto_id': None, 'valore': '0', 'valido_da': '2027-02-01', 'valido_a': None},
                       {'lotto_id': lotto, 'valore': '0.25', 'valido_da': '2026-01-01', 'valido_a': '2026-01-31'}]

    casi = ((dict(chiave='quota_assenza_alunno', valore='2'), 'fra 0 e 1'),
            (dict(chiave='max_minuti_giorno_avviso', valore=900), 'fra 0 e 12 ore'),
            (dict(chiave='giorni_pagamento', valore='30,5'), 'numero intero'),
            (dict(chiave='ritenuta_testo', valore='RITENUTA {percentuale}'), '{percentuale}'),
            (dict(chiave='arrotondamento_mezzo_minuto', valore='a caso'), 'non è tra quelli ammessi'),
            (dict(chiave='giorni_servizio', valore=[]), 'almeno un giorno'),
            (dict(chiave='regola_inventata', valore='1'), 'non esiste'))
    for dati, testo in casi:
        errore = _errore(napoli.post('/api/napoli/regole', json=dict(dati, valido_da='2030-01-01')), 400)
        assert testo in errore['error'], (dati, errore)
    for chiave, valore, atteso in (('split_payment', False, 'false'), ('giorni_servizio', [5, 0, 1], '[0, 1, 5]'),
                                   ('iva_percento', '4,5', '4.5'), ('ritenuta_testo', 'RITENUTA {percento}%',
                                                                    '"RITENUTA {percento}%"')):
        regola = _ok(napoli.post('/api/napoli/regole', json={'chiave': chiave, 'valore': valore,
                                                             'valido_da': '2030-01-01'}))['regola']
        assert regola['valore'] == atteso, chiave
    _errore(napoli.post('/api/napoli/regole', json={'chiave': 'iva_percento', 'valore': '5', 'valido_da': '2030-01-01',
                                                    'lotto_id': 999}), 404)
    # eliminare un valore: torna quello di prima
    ultima = _righe(database_isolato, "SELECT id FROM napoli_regole WHERE lotto_id = ?", (lotto,))[0]
    _ok(napoli.delete(f'/api/napoli/regole/{ultima["id"]}'))
    elenco = {r['chiave']: r for r in _ok(napoli.get(f'/api/napoli/regole?lotto_id={lotto}&giorno=2026-01-15'))['regole']}
    assert elenco['quota_assenza_alunno']['origine'] == 'tutti'


def test_le_api_rifiutano_i_valori_non_validi_invece_di_indovinarli(napoli, database_isolato):
    """Un si'/no che non e' ne' si' ne' no, un uso che non esiste, un elenco vuoto, un numero
    scritto come 1e2: 400 con un messaggio chiaro sul campo, niente di salvato."""
    lotto = crea_lotto_proposto(napoli)['id']
    casi = ((dict(chiave='split_payment', valore='forse'), 'scegli sì o no'),
            (dict(chiave='split_payment', valore=2), 'scegli sì o no'),
            (dict(chiave='split_payment', valore=[True]), 'scegli sì o no'),
            (dict(chiave='split_payment', valore=None), 'scegli sì o no'),
            (dict(chiave='usi_fatturabili', valore=['A', 'Z']), '"Z" non c\'è (si possono scegliere: A, B, D)'),
            (dict(chiave='usi_fatturabili', valore=['C']), '"C" non c\'è'),
            (dict(chiave='usi_fatturabili', valore=[]), 'scegli almeno un uso'),
            (dict(chiave='usi_fatturabili', valore=[' ', '']), 'scegli almeno un uso'),
            (dict(chiave='usi_fatturabili', valore=[1]), 'non è tra quelli ammessi'),
            (dict(chiave='giorni_pagamento', valore='1e1'), 'scrivi un numero intero'),
            (dict(chiave='quota_assenza_alunno', valore='5e-1'), 'scrivi un numero'),
            (dict(chiave='iva_percento', valore='Infinity'), 'scrivi un numero'),
            (dict(chiave='max_minuti_giorno_avviso', valore='3e2'), 'scrivi un numero intero'))
    for dati, testo in casi:
        errore = _errore(napoli.post('/api/napoli/regole', json=dict(dati, valido_da='2030-01-01')), 400,
                         'DATI_NON_VALIDI', 'valore')
        assert testo in errore['error'], (dati, errore)
    errore = _errore(napoli.post('/api/napoli/regole', json={'chiave': 'iva_percento', 'valore': '5',
                                                             'valido_da': '2030-01-01', 'chiudi_precedenti': 'boh'}),
                     400, 'DATI_NON_VALIDI', 'chiudi_precedenti')
    assert _righe(database_isolato, 'SELECT * FROM napoli_regole') == []
    # i modi giusti di dire si' o no, e gli usi in qualunque ordine e grafia
    for i, (chiave, valore, atteso) in enumerate((('split_payment', 'Sì', 'true'), ('split_payment', ' no ', 'false'),
                                                  ('split_payment', 0, 'false'), ('split_payment', True, 'true'),
                                                  ('usi_fatturabili', ['d', 'A', 'a'], '["A", "D"]'),
                                                  ('usi_fatturabili', 'B, a', '["A", "B"]'),
                                                  ('quota_assenza_alunno', ',5', '0.5'),
                                                  ('giorni_pagamento', ' 45 ', '45'))):
        anno = 2030 + i
        regola = _ok(napoli.post('/api/napoli/regole', json={'chiave': chiave, 'valore': valore,
                                                             'valido_da': f'{anno}-01-01',
                                                             'valido_a': f'{anno}-12-31'}))['regola']
        assert regola['valore'] == atteso, (chiave, valore)
    elenco = {r['chiave']: r for r in _ok(napoli.get('/api/napoli/regole?giorno=2034-06-01'))['regole']}
    assert elenco['usi_fatturabili']['valore_testo'] == 'A, D'
    assert [v['valore'] for v in elenco['usi_fatturabili']['voci']] == ['A', 'B', 'D']
    # numeri delle tariffe, dei contratti e della procedura; lo stato del lotto
    url = f'/api/napoli/lotti/{lotto}/tariffe'
    for scritto in ('1e2', '2E1', 'inf', 'NaN', '0x10', '24,28,1'):
        errore = _errore(napoli.post(url, json={'figura': 'LIS', 'tariffa': scritto, 'valido_da': '2030-01-01'}),
                         400, 'DATI_NON_VALIDI', 'tariffa')
        assert 'non è un numero' in errore['error'], scritto
    _errore(napoli.post(f'/api/napoli/lotti/{lotto}/contratti', json={
        'numero': 'XI', 'valido_da': '2025-09-01', 'valido_a': '2026-06-30', 'importo': '1e6'}), 400, None, 'importo')
    _errore(napoli.put(f'/api/napoli/lotti/{lotto}', json={'attivo': 'forse'}), 400, 'DATI_NON_VALIDI', 'attivo')
    assert _ok(napoli.put(f'/api/napoli/lotti/{lotto}', json={'attivo': False}))['lotto']['attivo'] == 0
    proposta = _ok(napoli.get('/api/napoli/lotti/proposta'))
    _errore(napoli.post('/api/napoli/lotti/procedura', json={
        'lotto': dict(proposta['lotto'], municipalita='3'), 'valido_da': '2025-09-01',
        'tariffe': [{'figura': 'ASACOM', 'tariffa': '2.3e1'}]}), 400, 'DATI_NON_VALIDI', 'tariffe.0')
    assert _righe(database_isolato, 'SELECT COUNT(*) AS n FROM napoli_lotti') == [{'n': 1}]
    assert _righe(database_isolato, "SELECT COUNT(*) AS n FROM napoli_tariffe WHERE figura = 'LIS'") == [{'n': 0}]


# ==================== qualifiche ====================

def test_qualifiche_aggiunte_cambiate_e_predefinite(napoli, database_isolato):
    _ok(napoli.post('/api/napoli/qualifiche', json={'testo': ' educatrice  prof.le ', 'figura': 'educatore'}))
    _errore(napoli.post('/api/napoli/qualifiche', json={'testo': 'EDUCATRICE PROF.LE', 'figura': 'ASACOM'}), 409,
            'QUALIFICA_GIA_PRESENTE', 'testo')
    _ok(napoli.put('/api/napoli/qualifiche', json={'testo': 'ASACM', 'figura': 'EDUCATORE'}))
    righe = {r['testo']: r for r in _ok(napoli.get('/api/napoli/qualifiche'))}
    assert righe['EDUCATRICE PROF.LE']['figura'] == 'EDUCATORE' and righe['EDUCATRICE PROF.LE']['origine'] == 'utente'
    assert (righe['ASACM']['figura'], righe['ASACM']['origine']) == ('EDUCATORE', 'utente')
    _errore(napoli.delete('/api/napoli/qualifiche', json={'testo': 'PSICOLOGA'}), 409, 'QUALIFICA_PREDEFINITA')
    _ok(napoli.delete('/api/napoli/qualifiche', json={'testo': 'educatrice prof.le'}))
    _errore(napoli.put('/api/napoli/qualifiche', json={'testo': 'NON ESISTE', 'figura': 'ASACOM'}), 404)
    # Ctrl+Z: l'eliminazione e poi il cambio di figura
    _ok(napoli.post('/api/napoli/annulla', json={}))
    _ok(napoli.post('/api/napoli/annulla', json={}))
    righe = {r['testo']: r for r in _ok(napoli.get('/api/napoli/qualifiche'))}
    assert 'EDUCATRICE PROF.LE' in righe and (righe['ASACM']['figura'], righe['ASACM']['origine']) == ('ASACOM', 'sistema')


# ==================== Ctrl+Z ====================

def test_ctrl_z_di_napoli_separato_da_roma(napoli, database_isolato, monkeypatch):
    assert _ok(napoli.get('/api/napoli/annulla/ultima')) == {'azione': None, 'scadute': 0, 'ore_validita': 24}
    _errore(napoli.post('/api/napoli/annulla', json={}), 400, 'NIENTE_DA_ANNULLARE')
    roma_prima = _ok(napoli.get('/api/undo/ultima'))
    lotto = crea_lotto_proposto(napoli)
    _ok(napoli.put('/api/napoli/impostazioni/cooperativa', json={'cooperativa_denominazione': 'Prova'}))
    assert _ok(napoli.get('/api/undo/ultima')) == roma_prima, 'Napoli ha scritto nella memoria di Ctrl+Z di Roma'
    ultima = _ok(napoli.get('/api/napoli/annulla/ultima'))['azione']
    assert ultima['descrizione'] == 'Dati della cooperativa: Ragione sociale'
    _errore(napoli.post('/api/napoli/annulla', json={'id': ultima['id'] + 1}), 409, 'ANNULLA_CAMBIATO')
    _ok(napoli.post('/api/napoli/annulla', json={'id': ultima['id']}))
    assert _righe(database_isolato, 'SELECT * FROM napoli_impostazioni') == []
    assert _ok(napoli.get('/api/napoli/annulla/ultima'))['azione']['descrizione'].startswith('Nuovo lotto')

    # le azioni piu' vecchie di 24 ore non si annullano piu', e i valori di prima (qui un IBAN
    # tolto) non restano nel database: resta solo la descrizione, per il messaggio
    _ok(napoli.put('/api/napoli/impostazioni/cooperativa', json={'cooperativa_iban': IBAN_DI_PROVA}))
    _ok(napoli.put('/api/napoli/impostazioni/cooperativa', json={'cooperativa_iban': ''}))
    assert any(IBAN_DI_PROVA in r['dati'] for r in _righe(database_isolato, 'SELECT dati FROM napoli_annullamenti'))
    conn = sqlite3.connect(database_isolato)
    with conn:
        vecchia = (datetime.datetime.now() - datetime.timedelta(hours=25)).isoformat(timespec='seconds')
        conn.execute('UPDATE napoli_annullamenti SET timestamp = ?', (vecchia,))
    conn.close()
    assert _ok(napoli.get('/api/napoli/annulla/ultima')) == {'azione': None, 'scadute': 3, 'ore_validita': 24}
    rimaste = _righe(database_isolato, 'SELECT descrizione, dati FROM napoli_annullamenti ORDER BY id')
    assert [r['dati'] for r in rimaste] == ['{}'] * 3 and rimaste[-1]['descrizione'] == 'Dati della cooperativa: IBAN'
    _errore(napoli.post('/api/napoli/annulla', json={}), 400, 'NIENTE_DA_ANNULLARE')
    assert _ok(napoli.get(f'/api/napoli/lotti/{lotto["id"]}'))['nome'] == 'NAPOLI LOTTO 1'
    # anche aprire una pagina di Napoli svuota le scadute; quelle recenti restano intere
    _ok(napoli.put('/api/napoli/impostazioni/cooperativa', json={'cooperativa_iban': IBAN_DI_PROVA}))
    conn = sqlite3.connect(database_isolato)
    with conn:
        conn.execute("UPDATE napoli_annullamenti SET timestamp = ? WHERE dati <> '{}'", (vecchia,))
    conn.close()
    assert napoli.get('/napoli/impostazioni').status_code == 200
    assert _righe(database_isolato, "SELECT COUNT(*) AS n FROM napoli_annullamenti WHERE dati <> '{}'") == [{'n': 0}]
    _ok(napoli.put('/api/napoli/impostazioni/cooperativa', json={'cooperativa_iban': ''}))
    assert napoli.get('/napoli').status_code == 200
    assert IBAN_DI_PROVA in _righe(database_isolato, 'SELECT dati FROM napoli_annullamenti ORDER BY id DESC')[0]['dati']

    # un formato che questa versione non conosce non si annulla e non si perde
    conn = sqlite3.connect(database_isolato)
    with conn:
        conn.execute("INSERT INTO napoli_annullamenti (timestamp, tipo, descrizione, dati) VALUES (?, 'griglia', "
                     "'Griglia: 1 cella', ?)", (datetime.datetime.now().isoformat(timespec='seconds'),
                                                json.dumps({'presenze': [{'id': 1}]})))
    conn.close()
    _errore(napoli.post('/api/napoli/annulla', json={}), 400, 'NON_ANNULLABILE')
    assert [r['tipo'] for r in _righe(database_isolato, 'SELECT tipo FROM napoli_annullamenti ORDER BY id')] == [
        'lotto', 'impostazioni', 'impostazioni', 'impostazioni', 'impostazioni', 'griglia']


# ==================== controlli del lotto (scheda Mese) ====================

def test_controlli_del_lotto_dicono_cosa_manca(napoli):
    lotto = crea_lotto_proposto(napoli, cig='')['id']
    controlli = {c['codice']: c for c in _ok(napoli.get(f'/api/napoli/lotti/{lotto}/controlli?giorno=2026-06-15'))}
    assert {k: c['stato'] for k, c in controlli.items() if c['stato'] != 'ok'} == {
        'cooperativa': 'manca', 'destinatario': 'manca', 'cig': 'manca', 'contratti': 'manca', 'tariffa_LIS': 'avviso'}
    assert controlli['cooperativa']['testo'] == ("Dati della cooperativa: mancano la ragione sociale, la partita IVA "
                                                 "e l'IBAN")
    assert all(c['sezione'] in ('cooperativa', 'destinatario', 'lotto', 'contratti', 'tariffe')
               for c in controlli.values())
    _ok(napoli.put('/api/napoli/impostazioni/cooperativa', json={
        'cooperativa_denominazione': 'Prova', 'cooperativa_partita_iva': '12345678903', 'cooperativa_iban': IBAN_DI_PROVA}))
    _ok(napoli.put('/api/napoli/impostazioni/destinatario', json={'destinatario_denominazione': 'ENTE DI PROVA'}))
    _ok(napoli.put(f'/api/napoli/lotti/{lotto}', json={'cig': 'ZZ00000000'}))
    _ok(napoli.post(f'/api/napoli/lotti/{lotto}/contratti', json={
        'numero': 'XI', 'grado': '', 'valido_da': '2026-06-08', 'valido_a': '2026-07-31'}))
    controlli = {c['codice']: c for c in _ok(napoli.get(f'/api/napoli/lotti/{lotto}/controlli?giorno=2026-06-15'))}
    assert {k: c['stato'] for k, c in controlli.items() if c['stato'] != 'ok'} == {
        'determine': 'manca', 'tariffa_LIS': 'avviso'}
    assert 'XI' in controlli['contratto_inferiore']['testo'] and 'XI' in controlli['contratto_superiore']['testo']
    # le tariffe che finiscono entro due mesi si segnalano
    controlli = {c['codice']: c for c in _ok(napoli.get(f'/api/napoli/lotti/{lotto}/controlli?giorno=2027-01-10'))}
    assert controlli['tariffa_ASACOM']['stato'] == 'avviso' and '31/01/2027' in controlli['tariffa_ASACOM']['testo']


# ==================== Roma non cambia, pagine ====================

def test_le_impostazioni_di_napoli_non_toccano_roma(database_isolato, app_module, db_mod):
    client = fotografa_roma.client_fotografia(app_module.app, db_mod)
    import roma_sintetico
    roma_sintetico.costruisci_archivio(client, fotografa_roma.orologio_fermo)
    roma = seme_napoli.impronta_roma(database_isolato)
    lotto = crea_lotto_proposto(client)['id']
    _ok(client.post(f'/api/napoli/lotti/{lotto}/contratti', json={
        'numero': 'XI', 'grado': 'inferiore', 'valido_da': '2026-06-08', 'valido_a': '2026-07-31'}))
    _ok(client.put('/api/napoli/impostazioni/cooperativa', json={'cooperativa_iban': IBAN_DI_PROVA}))
    _ok(client.post('/api/napoli/regole', json={'chiave': 'iva_percento', 'valore': '5', 'valido_da': '2030-01-01'}))
    _ok(client.post('/api/napoli/annulla', json={}))
    assert seme_napoli.impronta_roma(database_isolato) == roma
    voci = _righe(database_isolato, "SELECT entita FROM audit_log WHERE entita LIKE 'napoli%'")
    assert {v['entita'] for v in voci} == {'napoli_lotto', 'napoli_contratto', 'napoli_impostazioni', 'napoli_regola',
                                           'napoli_annullamento'}


def test_le_pagine_di_napoli_si_aprono(napoli):
    for url in ('/napoli', '/napoli/impostazioni'):
        r = napoli.get(url)
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert 'js/napoli.js' in html and 'css/napoli.css' in html and 'napoli-modal-procedura' in html
        assert 'class="tab active"' in html and 'aria-current="page"' in html
    assert 'id="form-cooperativa"' in napoli.get('/napoli/impostazioni').get_data(as_text=True)
    # le pagine di Roma non caricano lo script e lo stile di Napoli
    roma = napoli.get('/commesse').get_data(as_text=True)
    assert 'js/napoli.js' not in roma and 'css/napoli.css' not in roma


def test_la_voce_di_menu_di_napoli_e_ogni_suo_elemento_sono_marcati(napoli):
    """Nelle pagine di Roma c'e' la voce Napoli (menu e ricerca rapida, Alt+8), e ogni suo
    elemento ha data-sezione="napoli": la fotografia di Roma la toglie dalla cornice."""
    pagina = napoli.get('/commesse').get_data(as_text=True)
    assert pagina.count('href="/napoli"') == 1 and 'data-url="/napoli"' in pagina

    class Lettore(html.parser.HTMLParser):
        def __init__(self):
            super().__init__()
            self.pila, self.non_marcati = [], []

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            marcato = a.get('data-sezione') == 'napoli'
            dentro = any(self.pila)
            testo = ' '.join(str(v) for v in a.values())
            if 'napoli' in testo.lower() and not (marcato or dentro):
                self.non_marcati.append(tag)
            if tag not in VUOTI:
                self.pila.append(marcato or dentro)

        def handle_endtag(self, tag):
            if tag not in VUOTI and self.pila:
                self.pila.pop()

        def handle_data(self, data):
            if 'napoli' in data.lower() and not any(self.pila):
                self.non_marcati.append(data.strip())

    lettore = Lettore()
    lettore.feed(pagina.split('<main', 1)[0] + pagina.split('</main>', 1)[1].split('<script>window.APP_CONFIG', 1)[0])
    assert lettore.non_marcati == []

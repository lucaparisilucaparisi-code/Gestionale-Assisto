"""Sezione Napoli, passo 1.6: Anagrafiche (napoli_anagrafiche, routes_napoli).

- Dopo il caricamento dell'anagrafica dal master inventato (tests/napoli_sintetico.py) gli
  elenchi hanno gli alunni, gli operatori, le scuole e plessi e le coppie del file, con le
  ore del PEI; l'anagrafica vuota lo dice (la pagina invita a caricarla dal file Excel).
- Creazione e modifica a mano con i controlli lato server (messaggi semplici e il campo
  sbagliato): codici fiscali, scuole doppie, municipalita', grado, coppie doppie, sostituti,
  PEI con le date (il PEI di prima finisce il giorno prima), subentro, chiusura.
- Codici fiscali mai in chiaro nelle risposte; nomi e codici mai nel registro attivita' e
  nella memoria di Ctrl+Z (le modifiche dei dati personali non si annullano e lo dicono).
- Archiviazione al posto della cancellazione quando ci sono dati collegati (ore, fogli,
  orari); si elimina solo cio' che non ne ha.
- Annullare il caricamento non cancella righe cambiate a mano dopo (Ctrl+Z della modifica
  lo rende di nuovo possibile).
- Ricerca e filtri (scuola, municipalita', figura, grado, stato, nome; codice fiscale con
  una POST); Roma non cambia.

Ogni test lavora su un database vuoto (database_isolato). Solo dati inventati.
"""
import collections
import datetime
import io
import json
import sqlite3

import pytest

import napoli_calcoli as calc
import napoli_sintetico as ns
import seme_napoli
from strumenti import fotografa_roma

OGGI = datetime.date.today().isoformat()


@pytest.fixture
def napoli(database_isolato, app_module, db_mod):
    """Client autenticato sul database vuoto del test, con NAPOLI LOTTO 1."""
    client = fotografa_roma.client_fotografia(app_module.app, db_mod)
    proposta = _ok(client.get('/api/napoli/lotti/proposta'))
    lotto = _ok(client.post('/api/napoli/lotti/procedura', json={
        'lotto': dict(proposta['lotto'], municipalita='1 e 2', cig='ZZ00000000'), 'tariffe': proposta['tariffe'],
        'valido_da': proposta['valido_da'], 'valido_a': proposta['valido_a']}))['lotto']
    client.lotto_id = lotto['id']
    client.percorso = database_isolato
    return client


@pytest.fixture
def caricata(napoli, tmp_path):
    """Il lotto con l'anagrafica del master inventato caricata (l'azione principale)."""
    dati = ns.leggi_bytes(str(tmp_path / 'master'))[0]
    a = _ok(_import(napoli, '/api/napoli/import/anteprima', dati, scelte='{}', modo='anagrafica'))
    esito = _ok(_import(napoli, '/api/napoli/import/conferma', dati, sha256=a['file']['sha256'],
                        versione_dati=a['versione_dati'], scelte=json.dumps({'conferme': a['conferme_richieste']}),
                        modo='anagrafica'))
    napoli.anteprima, napoli.import_id = a, esito['import_id']
    return napoli


def _import(client, url, dati, **campi):
    return client.post(url, content_type='multipart/form-data', data=dict(
        campi, file=(io.BytesIO(dati), 'master_marzo.xlsx'), lotto_id=str(client.lotto_id)))


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


def _elenco(client, cosa, **filtri):
    """L'elenco come lo chiede la pagina: filtri e ricerca nel corpo di una POST (mai
    nell'indirizzo); senza ricerca anche con la GET, che deve dare lo stesso."""
    r = _ok(client.post(f'/api/napoli/lotti/{client.lotto_id}/anagrafiche/elenco', json=dict(filtri, parte=cosa)))
    if 'cerca' not in filtri:
        assert _ok(client.get(f'/api/napoli/lotti/{client.lotto_id}/{cosa}', query_string=filtri)) == r
    return r


def _cf(cognome, nome, anno=2015, sesso='F'):
    return seme_napoli.codice_fiscale_inventato(cognome, nome, datetime.date(anno, 3, 10), sesso)


def _scuola(client, **campi):
    dati = dict({'nome': 'IC FANTASIA - PLESSO PROVA', 'codice_meccanografico': 'NAIC8ZZ901', 'municipalita': 3,
                 'grado': 'inferiore'}, **campi)
    return _ok(client.post(f'/api/napoli/lotti/{client.lotto_id}/scuole', json=dati))['scuola_id']


def _alunno(client, scuola_id, cognome='PROVETTA', nome='ALBA', **campi):
    dati = dict({'cognome': cognome, 'nome': nome, 'codice_fiscale': _cf(cognome, nome), 'scuola_id': scuola_id},
                **campi)
    return _ok(client.post(f'/api/napoli/lotti/{client.lotto_id}/alunni', json=dati))['alunno_id']


def _operatore(client, cognome='MANUALE', nome='PRIMA', figura='ASACOM', **campi):
    dati = dict({'cognome': cognome, 'nome': nome, 'figura': figura, 'ore_contratto': '25',
                 'codice_fiscale': _cf(cognome, nome, 1985)}, **campi)
    return _ok(client.post('/api/napoli/operatori', json=dati))['operatore_id']


def _coppia(client, alunno_id, operatore_id, **campi):
    dati = dict({'alunno_id': alunno_id, 'operatore_id': operatore_id, 'valido_da': '2026-09-14'}, **campi)
    return _ok(client.post(f'/api/napoli/lotti/{client.lotto_id}/coppie', json=dati))


def _codici_del_file():
    righe, _attese = ns.costruisci()
    return {r['cf_alunno'] for r in righe} | {r['cf_operatore'] for r in righe if r['cf_operatore']}


# ==================== dopo il caricamento dell'anagrafica ====================

def test_l_anagrafica_vuota_invita_a_caricarla_dal_file_excel(napoli):
    r = _ok(napoli.get(f'/api/napoli/lotti/{napoli.lotto_id}/anagrafiche'))
    assert r['vuota'] is True and r['conteggi']['alunni'] == 0 and r['ultimo_caricamento'] is None
    pagina = napoli.get('/napoli/anagrafiche').get_data(as_text=True)
    assert 'Carica l&#39;anagrafica dal file Excel' in pagina or "Carica l'anagrafica dal file Excel" in pagina
    assert 'href="/napoli/import"' in pagina and 'id="anagrafiche-vuota"' in pagina


def test_dopo_il_caricamento_gli_elenchi_sono_quelli_del_file(caricata):
    righe, _attese = ns.costruisci()
    r = _ok(caricata.get(f'/api/napoli/lotti/{caricata.lotto_id}/anagrafiche'))
    assert r['vuota'] is False and r['ultimo_caricamento']['mese_testo'] == 'marzo 2026'
    assert r['conteggi'] == {'alunni': 34, 'alunni_archiviati': 0, 'operatori': 22, 'operatori_archiviati': 0,
                             'scuole': 6, 'scuole_archiviate': 0, 'coppie': 41,
                             'coppie_in_corso': r['conteggi']['coppie_in_corso']}

    alunni = _elenco(caricata, 'alunni')['righe']
    assert collections.Counter(a['cf'] for a in alunni) == collections.Counter(
        calc.maschera_codice_fiscale(cf) for cf in {x['cf_alunno'] for x in righe})
    operatori = _elenco(caricata, 'operatori')['righe']
    assert len(operatori) == 22
    figure_file = {x['cf_operatore'][:15]: ns._figura(x['qualifica']) for x in righe}
    assert collections.Counter(o['figura'] for o in operatori) == collections.Counter(figure_file.values())

    scuole = _elenco(caricata, 'scuole')['righe']
    assert {(s['codice_meccanografico'], s['municipalita']) for s in scuole} == {
        ('NAIC8ZZ001', 2), ('NA1C8ZZ002', 2), ('NAIS0ZZ003', 1), ('NAPC0ZZ004', 1), ('NAVC0ZZ005', 2), (None, 1)}
    senza_grado = {s['codice_meccanografico'] for s in scuole if s['grado'] is None}
    assert senza_grado == {s['codice_meccanografico'] for s in scuole if 'grado_da_decidere' in s['da_sistemare']}
    assert senza_grado, 'il master inventato ha scuole con il grado da decidere (convitto, codici sospetti)'
    assert sum(s['alunni'] for s in scuole) == 34

    coppie = _elenco(caricata, 'coppie', stato='tutte')['righe']
    assert len(coppie) == 41
    assert collections.Counter(c['figura'] for c in coppie) == collections.Counter(
        ns._figura(x['qualifica']) for x in righe)
    assert sum(1 for c in coppie if c['ruolo'] == 'sostituto') == sum(
        1 for x in righe if str(x['sostituzione'] or '').strip().upper() == 'SI')
    assert all(c['titolare'] for c in coppie if c['ruolo'] == 'sostituto')
    assert {c['alunno']['nome'] for c in coppie} == {a['nome_completo'] for a in alunni}

    # le ore del PEI degli elenchi sono quelle dell'anteprima (per figura)
    pei = collections.Counter()
    for a in alunni:
        for p in a['pei']:
            pei[p['figura']] += p['ore']
    def numero(testo):                       # '2.119,00' -> 2119.0
        return round(float(str(testo).replace('.', '').replace(',', '.')), 2)
    attese = {x['figura']: numero(x['pei_ore']) for x in caricata.anteprima['ore_per_figura']}
    assert {f: round(v, 2) for f, v in pei.items()} == {f: v for f, v in attese.items() if v}

    # la scheda di un alunno: PEI con lo storico, coppie, da dove viene, spazio del credito/debito
    alunno = next(a for a in alunni if len(a['operatori']) >= 2)
    scheda = _ok(caricata.get(f'/api/napoli/alunni/{alunno["id"]}'))
    assert scheda['origine']['tipo'] == 'import' and 'marzo 2026' in scheda['origine']['testo']
    assert {c['operatore']['id'] for c in scheda['coppie']} >= {o['id'] for o in alunno['operatori']}
    assert scheda['credito_debito']['disponibile'] is False
    assert 'quando inserirai le ore' in scheda['credito_debito']['testo']
    operatore = _ok(caricata.get(f'/api/napoli/operatori/{operatori[0]["id"]}',
                                 query_string={'lotto_id': caricata.lotto_id}))
    assert operatore['coppie'] and operatore['origine']['tipo'] == 'import'

    # nessun codice fiscale in chiaro nelle risposte
    testo = json.dumps([alunni, operatori, scuole, coppie, scheda, operatore], ensure_ascii=False)
    assert not [cf for cf in _codici_del_file() if cf and cf in testo]


def test_ricerca_e_filtri(caricata):
    tutti = _elenco(caricata, 'alunni')['righe']
    scuole = _elenco(caricata, 'scuole')['righe']
    s = next(x for x in scuole if x['codice_meccanografico'] == 'NAIS0ZZ003')
    per_scuola = _elenco(caricata, 'alunni', scuola_id=s['id'])['righe']
    assert per_scuola and all(a['scuola']['id'] == s['id'] or any(
        o['coppia_id'] for o in a['operatori']) for a in per_scuola)
    assert len(per_scuola) < len(tutti)
    municipalita_1 = _elenco(caricata, 'alunni', municipalita=1)['righe']
    municipalita_2 = _elenco(caricata, 'alunni', municipalita=2)['righe']
    assert municipalita_1 and municipalita_2 and len({a['id'] for a in municipalita_1 + municipalita_2}) == 34
    assert all(a['municipalita'] == 1 for a in municipalita_1 if not a['operatori'] or a['scuola'])
    educatori = _elenco(caricata, 'alunni', figura='EDUCATORE')['righe']
    assert educatori and all('EDUCATORE' in {p['figura'] for p in a['pei']} | {o['figura'] for o in a['operatori']}
                             for a in educatori)
    superiori = _elenco(caricata, 'alunni', grado='superiore')['righe']
    da_decidere = _elenco(caricata, 'alunni', grado='da_decidere')['righe']
    assert superiori and da_decidere and all(a['grado'] == 'superiore' for a in superiori)
    assert all(a['grado'] is None for a in da_decidere)
    cercati = _elenco(caricata, 'alunni', cerca='di prova')['righe']
    assert cercati and all('DI PROVA' in a['nome_completo'] for a in cercati)
    # la ricerca non va mai nell'indirizzo (finirebbe nei log): anche un codice fiscale scritto
    # a meta' o sbagliato si manda con la POST, e la GET con ?cerca= e' rifiutata
    for testo in ('di prova', cercati[0]['cf'][:6], 'RSSMRA80A01Z99'):
        _errore(caricata.get(f'/api/napoli/lotti/{caricata.lotto_id}/alunni', query_string={'cerca': testo}), 400,
                'RICERCA_NELL_INDIRIZZO', campo='cerca')
    assert _elenco(caricata, 'alunni', cerca='RSSMRA80A01Z99')['totale'] == 0
    assert _elenco(caricata, 'coppie', stato='tutte', cerca='di prova')['totale'] >= len(cercati)
    _errore(caricata.post(f'/api/napoli/lotti/{caricata.lotto_id}/anagrafiche/elenco', json={'parte': 'pei'}), 400,
            campo='parte')
    assert _elenco(caricata, 'alunni', stato='da_sistemare')['totale'] == _ok(caricata.get(
        f'/api/napoli/lotti/{caricata.lotto_id}/anagrafiche'))['da_sistemare']['alunni']
    assert _elenco(caricata, 'operatori', figura='PSICOLOGO')['totale'] == 3
    assert _elenco(caricata, 'operatori', municipalita=1)['totale'] < 22
    assert _elenco(caricata, 'scuole', grado='da_decidere')['totale'] >= 1
    assert _elenco(caricata, 'scuole', municipalita=1)['totale'] == 3
    assert _elenco(caricata, 'coppie', stato='tutte', ruolo='sostituto')['totale'] == 5
    assert _elenco(caricata, 'coppie', stato='tutte', figura='TIFLOLOGO')['totale'] == 1
    _errore(caricata.get(f'/api/napoli/lotti/{caricata.lotto_id}/alunni', query_string={'grado': 'medio'}), 400)
    _errore(caricata.get(f'/api/napoli/lotti/{caricata.lotto_id}/alunni', query_string={'scuola_id': 'x'}), 400)

    # ricerca per codice fiscale: nel corpo della richiesta, la risposta non lo ripete
    righe, _attese = ns.costruisci()
    cf = righe[0]['cf_alunno']
    trovati = _ok(caricata.post('/api/napoli/anagrafiche/codice-fiscale', json={'codice_fiscale': cf.lower()}))
    assert [t['tipo'] for t in trovati['trovati']] == ['alunno'] and cf not in json.dumps(trovati)
    _errore(caricata.post('/api/napoli/anagrafiche/codice-fiscale', json={'codice_fiscale': 'ABC'}), 400,
            campo='codice_fiscale')


# ==================== creazione e modifica a mano ====================

def test_scuole_controllate_lato_server(napoli):
    url = f'/api/napoli/lotti/{napoli.lotto_id}/scuole'
    _errore(napoli.post(url, json={'municipalita': 3}), 400, campo='nome')
    _errore(napoli.post(url, json={'nome': 'X', 'codice_meccanografico': 'NA12', 'municipalita': 3}), 400,
            campo='codice_meccanografico')
    _errore(napoli.post(url, json={'nome': 'X', 'municipalita': 11}), 400, campo='municipalita')
    _errore(napoli.post(url, json={'nome': 'X'}), 400, campo='municipalita')
    _errore(napoli.post(url, json={'nome': 'X', 'municipalita': 3, 'grado': 'medio'}), 400, campo='grado')
    s = _scuola(napoli)
    _errore(napoli.post(url, json={'nome': 'ALTRO NOME', 'codice_meccanografico': 'naic8zz901', 'municipalita': 3}),
            409, 'SCUOLA_GIA_PRESENTE')
    altro_plesso = _scuola(napoli, municipalita=4)       # stesso codice in un'altra municipalita' = altro plesso
    assert altro_plesso != s
    r = _ok(napoli.post(url, json={'nome': 'Scuola senza codice', 'municipalita': 5}))
    assert any('da decidere' in a for a in r['avvisi'])
    _errore(napoli.post(url, json={'nome': 'SCUOLA  SENZA CODICE', 'municipalita': 5}), 409, 'SCUOLA_GIA_PRESENTE')
    # un grado diverso da quello del codice e' un avviso, non un errore
    r = _ok(napoli.put(f'/api/napoli/scuole/{s}', json={'grado': 'superiore'}))
    assert any('controlla il grado' in a for a in r['avvisi']) and 'fatture non ancora definitive' in r['messaggio']
    _errore(napoli.put(f'/api/napoli/scuole/{s}', json={'municipalita': 4}), 409, 'SCUOLA_GIA_PRESENTE')
    assert _ok(napoli.put(f'/api/napoli/scuole/{s}', json={'grado': 'superiore'}))['messaggio'] == \
        'Nessun cambiamento da salvare'


def test_alunni_controllati_lato_server(napoli):
    url = f'/api/napoli/lotti/{napoli.lotto_id}/alunni'
    s = _scuola(napoli)
    misto = _scuola(napoli, nome='CONVITTO FANTASIA', codice_meccanografico='NAVC0ZZ905', grado='misto')
    base = {'cognome': 'PROVETTA', 'nome': 'ALBA', 'scuola_id': s}
    _errore(napoli.post(url, json=dict(base, cognome='')), 400, campo='cognome')
    _errore(napoli.post(url, json=base), 400, campo='codice_fiscale')
    giusto = _cf('PROVETTA', 'ALBA')
    sbagliato = giusto[:15] + ('A' if giusto[15] != 'A' else 'B')
    dati = _errore(napoli.post(url, json=dict(base, codice_fiscale=sbagliato)), 400, campo='codice_fiscale')
    assert sbagliato not in dati['error']
    _errore(napoli.post(url, json=dict(base, codice_fiscale='12345678901')), 400, campo='codice_fiscale')
    _errore(napoli.post(url, json=dict(base, codice_fiscale=giusto, scuola_id=None)), 400, campo='scuola_id')
    _errore(napoli.post(url, json=dict(base, codice_fiscale=giusto, scuola_id=999)), 400, campo='scuola_id')
    _errore(napoli.post(url, json=dict(base, codice_fiscale=giusto, scuola_id=misto)), 400, campo='grado')
    _errore(napoli.post(url, json=dict(base, codice_fiscale=giusto, esami='forse')), 400)
    alunno = _ok(napoli.post(url, json=dict(base, codice_fiscale=' ' + giusto.lower() + ' ', esami=True,
                                            note=f'Scritto per errore: {giusto}')))['alunno_id']
    salvato = _righe(napoli.percorso, 'SELECT * FROM napoli_alunni WHERE id = ?', (alunno,))[0]
    assert salvato['codice_fiscale'] == giusto and salvato['esami'] == 1 and giusto not in salvato['note']
    dati = _errore(napoli.post(url, json=dict(base, nome='ALTRA', codice_fiscale=giusto)), 409, 'ALUNNO_GIA_PRESENTE')
    assert dati['alunno_id'] == alunno and giusto not in dati['error']
    # in una modifica il codice fiscale vuoto resta quello salvato (alla pagina arriva solo mascherato)
    scheda = _ok(napoli.get(f'/api/napoli/alunni/{alunno}'))
    assert scheda['alunno']['cf'] == calc.maschera_codice_fiscale(giusto) and giusto not in json.dumps(scheda)
    _ok(napoli.put(f'/api/napoli/alunni/{alunno}', json={'codice_fiscale': '', 'grado': 'superiore'}))
    salvato = _righe(napoli.percorso, 'SELECT codice_fiscale, grado FROM napoli_alunni WHERE id = ?', (alunno,))[0]
    assert salvato == {'codice_fiscale': giusto, 'grado': 'superiore'}


def test_operatori_controllati_lato_server(napoli):
    _errore(napoli.post('/api/napoli/operatori', json={'cognome': 'X', 'nome': 'Y'}), 400, campo='figura')
    _errore(napoli.post('/api/napoli/operatori', json={'cognome': 'X', 'nome': 'Y', 'figura': 'MAGO'}), 400,
            campo='figura')
    for ore in ('41', '0', '-3', '1e2', 'tante', '12,345'):
        _errore(napoli.post('/api/napoli/operatori', json={'cognome': 'X', 'nome': 'Y', 'figura': 'ASACOM',
                                                           'ore_contratto': ore}), 400, campo='ore_contratto')
    _errore(napoli.post('/api/napoli/operatori', json={'cognome': 'X', 'nome': 'Y', 'figura': 'ASACOM',
                                                       'livello_ccnl': 'D-2!'}), 400, campo='livello_ccnl')
    senza_cf = _ok(napoli.post('/api/napoli/operatori', json={'cognome': 'SENZA', 'nome': 'CODICE',
                                                              'figura': 'EDUCATORE', 'ore_contratto': '24,5',
                                                              'livello_ccnl': 'd2'}))['operatore_id']
    riga = _righe(napoli.percorso, 'SELECT * FROM napoli_operatori WHERE id = ?', (senza_cf,))[0]
    assert (riga['codice_fiscale'], riga['cf_valido'], riga['ore_contratto'], riga['livello_ccnl']) == \
        (None, 0, 24.5, 'D2')
    o = _operatore(napoli)
    _errore(napoli.post('/api/napoli/operatori', json={'cognome': 'ALTRO', 'nome': 'NOME', 'figura': 'ASACOM',
                                                       'codice_fiscale': _cf('MANUALE', 'PRIMA', 1985)}),
            409, 'OPERATORE_GIA_PRESENTE')
    # l'operatore senza coppie compare nell'elenco del lotto, da sistemare
    righe = {x['id']: x for x in _elenco(napoli, 'operatori')['righe']}
    assert 'senza_coppie' in righe[o]['da_sistemare'] and 'codice_fiscale_mancante' in righe[senza_cf]['da_sistemare']


def test_coppie_pei_subentro_e_chiusura(napoli):
    s = _scuola(napoli)
    alunno = _alunno(napoli, s)
    primo = _operatore(napoli)
    secondo = _operatore(napoli, 'MANUALE', 'SECONDA')
    educatore = _operatore(napoli, 'MANUALE', 'TERZA', figura='EDUCATORE')
    url = f'/api/napoli/lotti/{napoli.lotto_id}/coppie'

    # PEI: il valore nuovo da un giorno chiude quello di prima il giorno prima
    pei = f'/api/napoli/alunni/{alunno}/pei'
    _errore(napoli.post(pei, json={'figura': 'COORDINATORE', 'ore_settimanali': 5, 'valido_da': '2026-09-14'}), 400,
            campo='figura')
    _errore(napoli.post(pei, json={'figura': 'ASACOM', 'ore_settimanali': 0, 'valido_da': '2026-09-14'}), 400,
            campo='ore_settimanali')
    _errore(napoli.post(pei, json={'figura': 'ASACOM', 'ore_settimanali': 10, 'valido_da': '2026-02-30'}), 400,
            campo='valido_da')
    _ok(napoli.post(pei, json={'figura': 'ASACOM', 'ore_settimanali': '10', 'valido_da': '2026-09-14'}))
    r = _ok(napoli.post(pei, json={'figura': 'ASACOM', 'ore_settimanali': '12,5', 'valido_da': '2026-10-01'}))
    assert 'valgono fino al 30/09/2026' in r['messaggio']
    _errore(napoli.post(pei, json={'figura': 'ASACOM', 'ore_settimanali': 9, 'valido_da': '2026-10-01'}), 409,
            'PEI_SOVRAPPOSTI')
    # un aumento per un mese: dopo torna il valore di prima
    r = _ok(napoli.post(pei, json={'figura': 'ASACOM', 'ore_settimanali': 15, 'valido_da': '2026-11-02',
                                   'valido_a': '2026-11-30'}))
    assert 'di nuovo dal 01/12/2026' in r['messaggio']
    storico = _righe(napoli.percorso, 'SELECT ore_settimanali, valido_da, valido_a FROM napoli_pei WHERE alunno_id = ? '
                                      'ORDER BY valido_da', (alunno,))
    assert [(x['ore_settimanali'], x['valido_da'], x['valido_a']) for x in storico] == [
        (10, '2026-09-14', '2026-09-30'), (12.5, '2026-10-01', '2026-11-01'), (15, '2026-11-02', '2026-11-30'),
        (12.5, '2026-12-01', None)]
    scheda = _ok(napoli.get(f'/api/napoli/alunni/{alunno}'))
    assert [len(p['righe']) for p in scheda['pei']] == [4]
    ultima = max(scheda['pei'][0]['righe'], key=lambda p: p['valido_da'])
    _errore(napoli.put(f'/api/napoli/pei/{ultima["id"]}', json={'valido_da': '2026-11-15'}), 409, 'PEI_SOVRAPPOSTI')

    # coppie
    _errore(napoli.post(url, json={'alunno_id': alunno, 'valido_da': '2026-09-14'}), 400, campo='operatore_id')
    _errore(napoli.post(url, json={'alunno_id': alunno, 'operatore_id': primo, 'valido_da': '2026-09-14',
                                   'figura': 'COORDINATORE'}), 400, campo='figura')
    _errore(napoli.post(url, json={'alunno_id': alunno, 'operatore_id': primo, 'valido_da': '2026-09-14',
                                   'valido_a': '2026-09-01'}), 400, campo='valido_a')
    titolare = _coppia(napoli, alunno, primo)
    assert titolare['avvisi'] == []                     # figura dell'operatore, PEI presente, scuola dell'alunno
    _errore(napoli.post(url, json={'alunno_id': alunno, 'operatore_id': primo, 'valido_da': '2026-10-01'}), 409,
            'COPPIA_GIA_PRESENTE')
    _errore(napoli.post(url, json={'alunno_id': alunno, 'operatore_id': secondo, 'ruolo': 'sostituto',
                                   'valido_da': '2026-10-05'}), 400, campo='titolare_coppia_id')
    sostituto = _coppia(napoli, alunno, secondo, ruolo='sostituto', titolare_coppia_id=titolare['coppia_id'],
                        valido_da='2026-10-05', valido_a='2026-10-09')
    r = _coppia(napoli, alunno, educatore)
    assert any('PEI di Educatore' in a for a in r['avvisi'])
    righe = {c['id']: c for c in _elenco(napoli, 'coppie', stato='tutte')['righe']}
    assert righe[sostituto['coppia_id']]['titolare']['id'] == titolare['coppia_id']
    assert righe[titolare['coppia_id']]['ore_da'] == 'pei'

    # subentro: un altro operatore dal 2 novembre, la coppia di prima finisce il giorno prima
    _errore(napoli.post(f'/api/napoli/coppie/{titolare["coppia_id"]}/subentro',
                        json={'operatore_id': primo, 'dal': '2026-11-02'}), 400, campo='operatore_id')
    _errore(napoli.post(f'/api/napoli/coppie/{titolare["coppia_id"]}/subentro',
                        json={'operatore_id': secondo, 'dal': '2026-09-14'}), 400, campo='dal')
    r = _ok(napoli.post(f'/api/napoli/coppie/{titolare["coppia_id"]}/subentro',
                        json={'operatore_id': secondo, 'dal': '2026-11-02'}))
    assert 'MANUALE SECONDA' in r['messaggio'] and '01/11/2026' in r['messaggio']
    assert r['avvisi'] == []           # la coppia di prima, chiusa dal subentro, non e' un altro titolare
    nuove = {c['id']: c for c in _righe(napoli.percorso, 'SELECT * FROM napoli_coppie')}
    assert nuove[titolare['coppia_id']]['valido_a'] == '2026-11-01'
    assert (nuove[r['coppia_id']]['operatore_id'], nuove[r['coppia_id']]['valido_da']) == (secondo, '2026-11-02')

    # chiusura: non prima di un giorno con ore registrate
    conn = sqlite3.connect(napoli.percorso)
    with conn:
        conn.execute("INSERT INTO napoli_presenze (coppia_id, lotto_id, data, figura, stato, minuti_riconosciuti, "
                     "origine, modificato_il) VALUES (?, ?, '2026-11-20', 'ASACOM', 'registrato', 120, 'griglia', "
                     "'2026-11-20T10:00:00')", (r['coppia_id'], napoli.lotto_id))
    conn.close()
    dati = _errore(napoli.post(f'/api/napoli/coppie/{r["coppia_id"]}/chiudi', json={'valido_a': '2026-11-10'}), 409,
                   'ORE_FUORI_DATE')
    assert '20/11/2026' in dati['error']
    assert 'ultimo giorno è il 30/11/2026' in _ok(napoli.post(f'/api/napoli/coppie/{r["coppia_id"]}/chiudi',
                                                               json={'valido_a': '2026-11-30'}))['messaggio']
    _errore(napoli.delete(f'/api/napoli/coppie/{r["coppia_id"]}'), 409, 'COPPIA_CON_DATI')
    _errore(napoli.delete(f'/api/napoli/coppie/{titolare["coppia_id"]}'), 409, 'COPPIA_CON_DATI')   # ha un sostituto
    _ok(napoli.delete(f'/api/napoli/coppie/{sostituto["coppia_id"]}'))


# ==================== archiviazione al posto della cancellazione ====================

def test_archiviazione_invece_della_cancellazione(napoli):
    s = _scuola(napoli)
    alunno = _alunno(napoli, s)
    operatore = _operatore(napoli)
    _ok(napoli.post(f'/api/napoli/alunni/{alunno}/pei', json={'figura': 'ASACOM', 'ore_settimanali': 10,
                                                               'valido_da': '2026-09-14'}))
    coppia = _coppia(napoli, alunno, operatore)['coppia_id']
    conn = sqlite3.connect(napoli.percorso)
    with conn:
        conn.execute("INSERT INTO napoli_presenze (coppia_id, lotto_id, data, figura, stato, minuti_riconosciuti, "
                     "origine, modificato_il) VALUES (?, ?, '2026-10-05', 'ASACOM', 'registrato', 120, 'griglia', "
                     "'2026-10-05T10:00:00')", (coppia, napoli.lotto_id))
    conn.close()
    # con le ore non si elimina niente: alunno, operatore, coppia, scuola
    _errore(napoli.delete(f'/api/napoli/alunni/{alunno}'), 409, 'ALUNNO_CON_DATI')
    _errore(napoli.delete(f'/api/napoli/operatori/{operatore}'), 409, 'OPERATORE_CON_DATI')
    _errore(napoli.delete(f'/api/napoli/coppie/{coppia}'), 409, 'COPPIA_CON_DATI')
    _errore(napoli.delete(f'/api/napoli/scuole/{s}'), 409, 'SCUOLA_CON_DATI')
    # non si archiviano operatore e scuola con coppie aperte; l'alunno non da un giorno con ore
    _errore(napoli.post(f'/api/napoli/operatori/{operatore}/archivia', json={'dal': '2026-11-01'}), 409,
            'OPERATORE_CON_COPPIE')
    _errore(napoli.post(f'/api/napoli/scuole/{s}/archivia', json={}), 409, 'SCUOLA_IN_USO')
    dati = _errore(napoli.post(f'/api/napoli/alunni/{alunno}/archivia', json={'dal': '2026-10-01'}), 409,
                   'ORE_DOPO_LA_DATA')
    assert '06/10/2026' in dati['error']
    r = _ok(napoli.post(f'/api/napoli/alunni/{alunno}/archivia', json={'dal': '2026-11-01'}))
    assert 'chiusi al 31/10/2026 1 coppia e 1 PEI' in r['messaggio']
    assert _righe(napoli.percorso, 'SELECT valido_a FROM napoli_coppie WHERE id = ?', (coppia,))[0]['valido_a'] == \
        '2026-10-31'
    assert _elenco(napoli, 'alunni')['totale'] == 0 and _elenco(napoli, 'alunni', stato='archiviati')['totale'] == 1
    _errore(napoli.post(f'/api/napoli/alunni/{alunno}/pei', json={'figura': 'ASACOM', 'ore_settimanali': 8,
                                                                   'valido_da': '2026-12-01'}), 409, 'ARCHIVIATO')
    # Ctrl+Z rimette tutto (coppia e PEI aperti, alunno in servizio) in un colpo
    ultima = _ok(napoli.get('/api/napoli/annulla/ultima'))['azione']
    assert ultima['chi'] == 'PROVETTA ALBA' and 'Archiviazione di un alunno' in ultima['descrizione']
    _ok(napoli.post('/api/napoli/annulla', json={'id': ultima['id']}))
    assert _righe(napoli.percorso, 'SELECT valido_a FROM napoli_coppie WHERE id = ?', (coppia,))[0]['valido_a'] is None
    assert _elenco(napoli, 'alunni')['totale'] == 1
    # ora l'operatore si archivia dopo la chiusura della coppia
    _ok(napoli.post(f'/api/napoli/coppie/{coppia}/chiudi', json={'valido_a': '2026-10-31'}))
    _ok(napoli.post(f'/api/napoli/operatori/{operatore}/archivia', json={'dal': '2026-11-01'}))
    assert _elenco(napoli, 'operatori', stato='archiviati')['righe'][0]['archiviato_dal'] == '2026-11-01'
    _ok(napoli.post(f'/api/napoli/operatori/{operatore}/ripristina', json={}))
    # senza dati collegati si elimina
    vuota = _scuola(napoli, nome='SCUOLA PER SBAGLIO', codice_meccanografico='', municipalita=7)
    nuovo = _alunno(napoli, s, 'SBAGLIATO', 'ALUNNO')
    _ok(napoli.delete(f'/api/napoli/scuole/{vuota}'))
    _ok(napoli.delete(f'/api/napoli/alunni/{nuovo}'))
    assert not _righe(napoli.percorso, 'SELECT 1 FROM napoli_alunni WHERE id = ?', (nuovo,))
    # eliminare una persona non si annulla con Ctrl+Z (i dati personali non restano in memoria) e lo dice
    info = _ok(napoli.get('/api/napoli/annulla/ultima'))
    assert info['azione'] is None and 'riservatezza' in info['non_annullabile']['motivo']
    _errore(napoli.post('/api/napoli/annulla', json={}), 400, 'NON_ANNULLABILE')


def test_scuola_archiviata_e_ripristinata(napoli):
    s = _scuola(napoli)
    _ok(napoli.post(f'/api/napoli/scuole/{s}/archivia', json={}))
    _errore(napoli.post(f'/api/napoli/scuole/{s}/archivia', json={}), 409, 'GIA_ARCHIVIATA')
    assert _elenco(napoli, 'scuole')['totale'] == 0 and _elenco(napoli, 'scuole', stato='archiviate')['totale'] == 1
    _errore(napoli.post(f'/api/napoli/lotti/{napoli.lotto_id}/alunni', json={
        'cognome': 'A', 'nome': 'B', 'codice_fiscale': _cf('A', 'B'), 'scuola_id': s}), 400, campo='scuola_id')
    _ok(napoli.post(f'/api/napoli/scuole/{s}/ripristina', json={}))
    assert _elenco(napoli, 'scuole')['totale'] == 1


# ==================== Ctrl+Z e privacy ====================

def test_ctrl_z_delle_anagrafiche_senza_dati_personali(napoli):
    s = _scuola(napoli)
    alunno = _alunno(napoli, s)
    operatore = _operatore(napoli)
    _ok(napoli.put(f'/api/napoli/alunni/{alunno}', json={'esami': True, 'grado': 'superiore'}))
    ultima = _ok(napoli.get('/api/napoli/annulla/ultima'))['azione']
    assert ultima['descrizione'] == f'Modifica di un alunno (scheda n. {alunno}): grado e esami'
    assert ultima['chi'] == 'PROVETTA ALBA'
    _ok(napoli.post('/api/napoli/annulla', json={'id': ultima['id']}))
    riga = _righe(napoli.percorso, 'SELECT esami, grado, modificato_il FROM napoli_alunni WHERE id = ?', (alunno,))[0]
    assert (riga['esami'], riga['grado']) == (0, None) and riga['modificato_il']
    # i dati personali cambiati non si annullano: la risposta lo dice e Ctrl+Z pure
    r = _ok(napoli.put(f'/api/napoli/alunni/{alunno}', json={'cognome': 'PROVETTI', 'note': 'Nota di prova'}))
    assert 'Ctrl+Z non annulla' in r['messaggio']
    info = _ok(napoli.get('/api/napoli/annulla/ultima'))
    assert info['azione'] is None and info['non_annullabile']['descrizione'].endswith('cognome e note')
    _errore(napoli.post('/api/napoli/annulla', json={}), 400, 'NON_ANNULLABILE')
    nuovo_cf = _cf('PROVETTI', 'ALBA', 2014)
    _ok(napoli.put(f'/api/napoli/alunni/{alunno}', json={'codice_fiscale': nuovo_cf}))
    _ok(napoli.put(f'/api/napoli/operatori/{operatore}', json={'nome': 'PRIMISSIMA', 'livello_ccnl': 'D2'}))
    _ok(napoli.put(f'/api/napoli/operatori/{operatore}', json={'ore_contratto': '30'}))
    _ok(napoli.post('/api/napoli/annulla', json={}))
    assert _righe(napoli.percorso, 'SELECT ore_contratto FROM napoli_operatori WHERE id = ?',
                  (operatore,))[0]['ore_contratto'] == 25
    # nella memoria di Ctrl+Z e nel registro attivita' niente nomi e codici fiscali
    codici = {_cf('PROVETTA', 'ALBA'), nuovo_cf, _cf('MANUALE', 'PRIMA', 1985)}
    nomi = {'PROVETTA', 'PROVETTI', 'MANUALE', 'PRIMISSIMA', 'Nota di prova'}
    azioni = _righe(napoli.percorso, 'SELECT * FROM napoli_annullamenti')
    memoria = json.dumps(azioni, ensure_ascii=False)
    registro = json.dumps(_righe(napoli.percorso, "SELECT * FROM audit_log WHERE entita LIKE 'napoli%'"),
                          ensure_ascii=False)
    for dove, testo in (('memoria di Ctrl+Z', memoria), ('registro attivita', registro)):
        assert not [x for x in codici | nomi if x in testo], dove
    assert any('"tabella": "alunni"' in a['dati'] for a in azioni) and 'napoli_alunno' in registro


def test_subentro_sposta_i_sostituti_che_cominciano_dopo(napoli):
    """I sostituti della coppia di prima che cominciano dal giorno del subentro in poi
    sostituiscono il nuovo operatore: passano alla coppia nuova (Ctrl+Z li rimette). Uno gia'
    cominciato e che continua resta sulla coppia di prima, con un avviso."""
    s = _scuola(napoli)
    alunno = _alunno(napoli, s)
    primo, secondo = _operatore(napoli), _operatore(napoli, 'MANUALE', 'SECONDA')
    sost_a, sost_b = _operatore(napoli, 'MANUALE', 'TERZA'), _operatore(napoli, 'MANUALE', 'QUARTA')
    _ok(napoli.post(f'/api/napoli/alunni/{alunno}/pei', json={'figura': 'ASACOM', 'ore_settimanali': 10,
                                                               'valido_da': '2026-09-14'}))
    titolare = _coppia(napoli, alunno, primo)['coppia_id']
    prima = _coppia(napoli, alunno, sost_a, ruolo='sostituto', titolare_coppia_id=titolare,
                    valido_da='2026-10-05', valido_a='2026-10-09')['coppia_id']
    a_cavallo = _coppia(napoli, alunno, sost_b, ruolo='sostituto', titolare_coppia_id=titolare,
                        valido_da='2026-10-26', valido_a='2026-11-06')['coppia_id']
    dopo = _coppia(napoli, alunno, sost_a, ruolo='sostituto', titolare_coppia_id=titolare,
                   valido_da='2026-11-16', valido_a='2026-11-20')['coppia_id']
    r = _ok(napoli.post(f'/api/napoli/coppie/{titolare}/subentro', json={'operatore_id': secondo, 'dal': '2026-11-02'}))
    nuova = r['coppia_id']
    assert r['sostituti_spostati'] == 1
    assert 'il sostituto che comincia dal 02/11/2026 in poi passa alla coppia nuova' in r['messaggio']
    assert len(r['avvisi']) == 1 and 'MANUALE QUARTA' in r['avvisi'][0] and 'resta collegato' in r['avvisi'][0]
    collegati = {c['id']: c['titolare_coppia_id'] for c in _righe(napoli.percorso, 'SELECT * FROM napoli_coppie')}
    assert (collegati[prima], collegati[a_cavallo], collegati[dopo]) == (titolare, titolare, nuova)
    # un solo Ctrl+Z: la coppia nuova sparisce e il sostituto torna alla coppia di prima
    _ok(napoli.post('/api/napoli/annulla', json={}))
    collegati = {c['id']: c for c in _righe(napoli.percorso, 'SELECT * FROM napoli_coppie')}
    assert nuova not in collegati and collegati[dopo]['titolare_coppia_id'] == titolare
    assert collegati[titolare]['valido_a'] is None


def test_non_si_riapre_la_coppia_di_una_persona_archiviata(napoli):
    """Allungare o riaprire la coppia di un operatore (o di un alunno) archiviato e' bloccato
    come crearla; accorciarla si puo'."""
    s = _scuola(napoli)
    alunno = _alunno(napoli, s)
    operatore = _operatore(napoli)
    coppia = _coppia(napoli, alunno, operatore)['coppia_id']
    _ok(napoli.post(f'/api/napoli/coppie/{coppia}/chiudi', json={'valido_a': '2026-10-31'}))
    _ok(napoli.post(f'/api/napoli/operatori/{operatore}/archivia', json={'dal': '2026-11-01'}))
    for dati in ({'valido_a': ''}, {'valido_a': '2026-12-31'}):
        dati = _errore(napoli.put(f'/api/napoli/coppie/{coppia}', json=dati), 409, 'ARCHIVIATO', campo='valido_a')
        assert "L'operatore è archiviato" in dati['error']
    _ok(napoli.put(f'/api/napoli/coppie/{coppia}', json={'valido_a': '2026-10-30'}))      # accorciare: si'
    _ok(napoli.post(f'/api/napoli/operatori/{operatore}/ripristina', json={}))
    _ok(napoli.post(f'/api/napoli/alunni/{alunno}/archivia', json={'dal': '2026-11-01'}))
    dati = _errore(napoli.put(f'/api/napoli/coppie/{coppia}', json={'valido_a': ''}), 409, 'ARCHIVIATO')
    assert "L'alunno è archiviato" in dati['error']
    _ok(napoli.post(f'/api/napoli/alunni/{alunno}/ripristina', json={}))
    assert _ok(napoli.put(f'/api/napoli/coppie/{coppia}', json={'valido_a': ''}))['messaggio'] == 'Coppia salvata'


def test_ctrl_z_senza_le_note_di_coppie_e_pei(napoli):
    """Le note delle coppie e la nota del PEI (testo libero: un nome o un dato sanitario
    scritto per sbaglio) non restano nella memoria di Ctrl+Z: cambiarle non si annulla e lo
    dice; una riga eliminata torna senza; il nome della scuola non si ripete nella conferma."""
    s = _scuola(napoli)
    alunno = _alunno(napoli, s)
    operatore = _operatore(napoli)
    coppia = _coppia(napoli, alunno, operatore, note='Nota libera della coppia')['coppia_id']
    pei = _ok(napoli.post(f'/api/napoli/alunni/{alunno}/pei', json={
        'figura': 'ASACOM', 'ore_settimanali': 10, 'valido_da': '2026-09-14', 'fonte': 'Verbale di prova'}))['pei_id']
    # cambiare le ore e le date si annulla, e la nota resta quella di adesso
    _ok(napoli.put(f'/api/napoli/coppie/{coppia}', json={'ore_settimanali': '8'}))
    _ok(napoli.put(f'/api/napoli/pei/{pei}', json={'ore_settimanali': '12'}))
    _ok(napoli.post('/api/napoli/annulla', json={}))
    _ok(napoli.post('/api/napoli/annulla', json={}))
    riga = _righe(napoli.percorso, 'SELECT ore_settimanali, note FROM napoli_coppie WHERE id = ?', (coppia,))[0]
    assert (riga['ore_settimanali'], riga['note']) == (None, 'Nota libera della coppia')
    riga = _righe(napoli.percorso, 'SELECT ore_settimanali, fonte FROM napoli_pei WHERE id = ?', (pei,))[0]
    assert (riga['ore_settimanali'], riga['fonte']) == (10, 'Verbale di prova')
    # cambiare le note non si annulla, e la risposta e Ctrl+Z lo dicono
    r = _ok(napoli.put(f'/api/napoli/coppie/{coppia}', json={'note': 'Altra nota della coppia'}))
    assert 'Ctrl+Z non annulla le modifiche alle note' in r['messaggio']
    info = _ok(napoli.get('/api/napoli/annulla/ultima'))
    assert info['azione'] is None and 'le note di prima non restano' in info['non_annullabile']['motivo']
    r = _ok(napoli.put(f'/api/napoli/pei/{pei}', json={'fonte': 'Altro verbale'}))
    assert 'Ctrl+Z non annulla le modifiche alla nota' in r['messaggio']
    _errore(napoli.post('/api/napoli/annulla', json={}), 400, 'NON_ANNULLABILE')
    # eliminata, la coppia torna con Ctrl+Z senza le note
    r = _ok(napoli.delete(f'/api/napoli/coppie/{coppia}'))
    assert 'torna senza le note' in r['messaggio']
    _ok(napoli.post('/api/napoli/annulla', json={}))
    riga = _righe(napoli.percorso, 'SELECT operatore_id, note FROM napoli_coppie WHERE id = ?', (coppia,))[0]
    assert (riga['operatore_id'], riga['note']) == (operatore, None)
    memoria = json.dumps(_righe(napoli.percorso, 'SELECT * FROM napoli_annullamenti'), ensure_ascii=False)
    for testo in ('Nota libera', 'Altra nota', 'Verbale di prova', 'Altro verbale'):
        assert testo not in memoria, testo
    # la conferma di Ctrl+Z di una scuola: il nome sta gia' nella descrizione, non si ripete
    _ok(napoli.put(f'/api/napoli/scuole/{s}', json={'grado': 'superiore'}))
    azione = _ok(napoli.get('/api/napoli/annulla/ultima'))['azione']
    assert azione['descrizione'].count('IC FANTASIA - PLESSO PROVA') == 1 and azione['chi'] == ''


def test_annullare_il_caricamento_non_cancella_le_modifiche_a_mano(caricata):
    alunno = _elenco(caricata, 'alunni')['righe'][0]
    _ok(caricata.put(f'/api/napoli/alunni/{alunno["id"]}', json={'esami': True}))
    _errore(caricata.post(f'/api/napoli/import/{caricata.import_id}/annulla', json={}), 409, 'IMPORT_CAMBIATO_DOPO')
    _ok(caricata.post('/api/napoli/annulla', json={}))                 # Ctrl+Z della modifica
    coppia = _elenco(caricata, 'coppie')['righe'][0]
    _ok(caricata.post(f'/api/napoli/coppie/{coppia["id"]}/chiudi', json={'valido_a': '2026-10-31'}))
    _errore(caricata.post(f'/api/napoli/import/{caricata.import_id}/annulla', json={}), 409, 'IMPORT_CAMBIATO_DOPO')
    _ok(caricata.post('/api/napoli/annulla', json={}))
    # una coppia aggiunta a mano con un alunno del caricamento: annullare lo direbbe
    operatore = _operatore(caricata)
    _coppia(caricata, alunno['id'], operatore)
    _errore(caricata.post(f'/api/napoli/import/{caricata.import_id}/annulla', json={}), 409, 'IMPORT_CAMBIATO_DOPO')
    _ok(caricata.post('/api/napoli/annulla', json={}))
    _ok(caricata.post('/api/napoli/annulla', json={}))                 # anche l'operatore aggiunto
    _ok(caricata.post(f'/api/napoli/import/{caricata.import_id}/annulla', json={}))
    assert _ok(caricata.get(f'/api/napoli/lotti/{caricata.lotto_id}/anagrafiche'))['vuota'] is True


# ==================== pagina e Roma ====================

def test_la_pagina_delle_anagrafiche_si_apre(napoli):
    r = napoli.get('/napoli/anagrafiche')
    assert r.status_code == 200
    pagina = r.get_data(as_text=True)
    assert 'js/napoli.js' in pagina and 'css/napoli.css' in pagina and 'NapoliAnagrafiche.avvia()' in pagina
    assert 'href="/napoli/anagrafiche" class="tab active"' in pagina and 'id="napoli-modal-anagrafica"' in pagina
    for scheda in ('alunni', 'operatori', 'scuole', 'coppie'):
        assert f'data-parte-link="{scheda}"' in pagina
    for url in ('/napoli', '/napoli/import', '/napoli/impostazioni'):
        assert 'href="/napoli/anagrafiche"' in napoli.get(url).get_data(as_text=True)


def test_le_anagrafiche_di_napoli_non_toccano_roma(database_isolato, app_module, db_mod):
    client = fotografa_roma.client_fotografia(app_module.app, db_mod)
    import roma_sintetico
    roma_sintetico.costruisci_archivio(client, fotografa_roma.orologio_fermo)
    roma = seme_napoli.impronta_roma(database_isolato)
    proposta = _ok(client.get('/api/napoli/lotti/proposta'))
    client.lotto_id = _ok(client.post('/api/napoli/lotti/procedura', json={
        'lotto': dict(proposta['lotto'], municipalita='1 e 2'), 'tariffe': proposta['tariffe'],
        'valido_da': proposta['valido_da'], 'valido_a': proposta['valido_a']}))['lotto']['id']
    s = _scuola(client)
    # omonimi di un utente e di un operatore di Roma
    alunno = _alunno(client, s, 'Esempio', 'Alba')
    operatore = _operatore(client, 'Operatore', 'Primo')
    _ok(client.post(f'/api/napoli/alunni/{alunno}/pei', json={'figura': 'ASACOM', 'ore_settimanali': 10,
                                                               'valido_da': '2026-09-14'}))
    coppia = _coppia(client, alunno, operatore)['coppia_id']
    _ok(client.post(f'/api/napoli/coppie/{coppia}/chiudi', json={'valido_a': '2026-12-31'}))
    _ok(client.post(f'/api/napoli/alunni/{alunno}/archivia', json={'dal': '2027-01-01'}))
    _ok(client.post('/api/napoli/annulla', json={}))
    assert seme_napoli.impronta_roma(database_isolato) == roma

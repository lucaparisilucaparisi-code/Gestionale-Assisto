"""Sezione Napoli: privacy dei codici fiscali nell'import del foglio presenze (PROGETTO D11).

I codici fiscali di alunni (minori) e operatori stanno solo nelle anagrafiche di
Napoli. Dopo anteprima, conferma, reimport, solo confronto, annulla import e Ctrl+Z:
- nessun codice fiscale in chiaro nelle risposte delle API e nella pagina (solo
  mascherati, "DSM••••••••Z99");
- nessun codice fiscale (e nessun nome di alunno) nel registro attivita' (audit_log),
  nella memoria di Ctrl+Z (napoli_annullamenti), negli esiti e nei registri degli
  import (napoli_import) e nei messaggi del log del programma.
Solo dati inventati (tests/napoli_sintetico.py, codici fiscali con comune Z999).
"""
import datetime
import io
import json
import logging
import sqlite3

import pytest

import napoli_calcoli as calc
import napoli_sintetico as ns
from strumenti import fotografa_roma


class _Raccolta(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.messaggi = []

    def emit(self, record):
        self.messaggi.append(record.getMessage())


@pytest.fixture
def raccolta_log():
    gestore = _Raccolta()
    loggers = [logging.getLogger(), logging.getLogger('oepac'), logging.getLogger('oepac.napoli')]
    for lg in loggers:
        lg.addHandler(gestore)
    try:
        yield gestore
    finally:
        for lg in loggers:
            lg.removeHandler(gestore)


def _ok(r):
    assert r.status_code == 200, r.get_data(as_text=True)
    return r


def _codici_e_nomi():
    """Tutti i codici fiscali del master inventato (anche quelli sbagliati) e i cognomi degli alunni."""
    righe, _attese = ns.costruisci()
    codici = {r['cf_operatore'] for r in righe} | {r['cf_alunno'] for r in righe}
    cognomi = {r['alunno'].split(' ')[0] for r in righe}
    return {c for c in codici if c}, cognomi


def test_maschera_codice_fiscale():
    assert calc.maschera_codice_fiscale('RSSMRA80A01Z999X') == 'RSS••••••••••99X'
    assert calc.maschera_codice_fiscale('') == '' and calc.maschera_codice_fiscale(None) == ''
    assert calc.maschera_codice_fiscale('ABC') == '•••'
    assert calc.esito_codice_fiscale(' rss mra ') == ('RSSMRA', 'formato')


def test_codici_fiscali_mai_in_chiaro_fuori_dalle_anagrafiche(database_isolato, app_module, db_mod, tmp_path,
                                                             raccolta_log):
    client = fotografa_roma.client_fotografia(app_module.app, db_mod)
    proposta = client.get('/api/napoli/lotti/proposta').get_json()
    lotto = _ok(client.post('/api/napoli/lotti/procedura', json={
        'lotto': dict(proposta['lotto'], municipalita='1 e 2'), 'tariffe': proposta['tariffe'],
        'valido_da': proposta['valido_da'], 'valido_a': proposta['valido_a']})).get_json()['lotto']
    risposte = []

    def chiama(url, dati, scelte=None, **campi):
        r = client.post(url, content_type='multipart/form-data', data=dict(
            {'file': (io.BytesIO(dati), 'master_marzo.xlsx'), 'lotto_id': str(lotto['id']),
             'scelte': json.dumps(scelte or {})}, **campi))
        risposte.append(r.get_data(as_text=True))
        return r.get_json()

    def importa(dati, scelte=None):
        a = chiama('/api/napoli/import/anteprima', dati, scelte)
        scelte = dict(scelte or {}, ore_ambigue={x['chiave']: 'ore_e_minuti' for x in a['ore_ambigue']})
        a = chiama('/api/napoli/import/anteprima', dati, scelte)
        scelte = dict(scelte, conferme=a['conferme_richieste'])
        return chiama('/api/napoli/import/conferma', dati, scelte, sha256=a['file']['sha256'],
                      versione_dati=a['versione_dati'])

    dati = ns.leggi_bytes(str(tmp_path / 'a'))[0]
    primo = importa(dati)
    assert primo['import_id']
    chiama('/api/napoli/import/anteprima', dati, modo='confronto')

    def altri(r):
        r[0]['giorni'][datetime.date(2026, 3, 3)] = 1
        for x in r:                                  # operatore con un altro codice sbagliato: riconosciuto dal nome
            if x['operatore'] == 'DI ESEMPIO ALFA MARIA':
                x['cf_operatore'] = 'DSMLMR84A71Z99'
    diverso = ns.leggi_bytes(str(tmp_path / 'b'), modifica=altri)[0]
    anteprima_b = chiama('/api/napoli/import/anteprima', diverso)
    assert '•' in json.dumps(anteprima_b, ensure_ascii=False)            # i codici si vedono solo mascherati
    secondo = importa(diverso)
    for url in (f'/api/napoli/lotti/{lotto["id"]}/import', '/api/napoli/annulla/ultima', '/napoli/import'):
        risposte.append(_ok(client.get(url)).get_data(as_text=True))
    risposte.append(_ok(client.post(f'/api/napoli/import/{secondo["import_id"]}/annulla', json={})).get_data(
        as_text=True))
    ultima = client.get('/api/napoli/annulla/ultima').get_json()['azione']
    risposte.append(_ok(client.post('/api/napoli/annulla', json={'id': ultima['id']})).get_data(as_text=True))

    codici, cognomi = _codici_e_nomi()
    codici.add('DSMLMR84A71Z99')
    conn = sqlite3.connect(database_isolato)
    try:
        assert conn.execute('SELECT COUNT(*) FROM napoli_import').fetchone()[0] == 2
        luoghi = {
            'risposte delle API': '\n'.join(risposte),
            'registro attivita': json.dumps(conn.execute('SELECT * FROM audit_log').fetchall()),
            'memoria di Ctrl+Z': json.dumps(conn.execute('SELECT * FROM napoli_annullamenti').fetchall()),
            'registro degli import': json.dumps(conn.execute(
                'SELECT nome_file, esito_json, sostituite_json FROM napoli_import').fetchall()),
            'log del programma': '\n'.join(raccolta_log.messaggi),
        }
        # i codici ci sono davvero nelle anagrafiche (il controllo non e' vuoto)
        assert conn.execute('SELECT COUNT(*) FROM napoli_alunni').fetchone()[0] == 0          # import annullato
    finally:
        conn.close()
    assert any('napoli_import' in v for v in (luoghi['registro attivita'],))
    for dove, testo in luoghi.items():
        trovati = sorted(c for c in codici if c in testo)
        assert not trovati, f'codici fiscali in chiaro in: {dove}'
    for dove in ('registro attivita', 'memoria di Ctrl+Z', 'registro degli import', 'log del programma'):
        assert not [c for c in cognomi if c in luoghi[dove]], f'nomi di alunni in: {dove}'


def test_le_anagrafiche_hanno_i_codici_e_la_pagina_no(database_isolato, app_module, db_mod, tmp_path):
    """Dopo un import i codici fiscali sono nelle anagrafiche (servono per abbinare),
    ma l'anteprima e l'elenco degli import non li restituiscono."""
    client = fotografa_roma.client_fotografia(app_module.app, db_mod)
    proposta = client.get('/api/napoli/lotti/proposta').get_json()
    lotto = client.post('/api/napoli/lotti/procedura', json={
        'lotto': dict(proposta['lotto'], municipalita='1 e 2'), 'tariffe': proposta['tariffe'],
        'valido_da': proposta['valido_da'], 'valido_a': proposta['valido_a']}).get_json()['lotto']
    dati = ns.leggi_bytes(str(tmp_path / 'a'))[0]
    campi = {'lotto_id': str(lotto['id']), 'scelte': '{}'}
    a = client.post('/api/napoli/import/anteprima', content_type='multipart/form-data',
                    data=dict(campi, file=(io.BytesIO(dati), 'm.xlsx'))).get_json()
    campi['scelte'] = json.dumps({'ore_ambigue': {x['chiave']: 'decimale' for x in a['ore_ambigue']}})
    r = client.post('/api/napoli/import/conferma', content_type='multipart/form-data', data=dict(
        campi, file=(io.BytesIO(dati), 'm.xlsx'), sha256=a['file']['sha256'], versione_dati=a['versione_dati']))
    assert r.status_code == 200
    conn = sqlite3.connect(database_isolato)
    try:
        salvati = {x[0] for x in conn.execute('SELECT codice_fiscale FROM napoli_alunni')}
    finally:
        conn.close()
    assert len(salvati) == 34
    ancora = client.post('/api/napoli/import/anteprima', content_type='multipart/form-data',
                         data=dict(campi, file=(io.BytesIO(dati), 'm.xlsx'))).get_data(as_text=True)
    storico = client.get(f'/api/napoli/lotti/{lotto["id"]}/import').get_data(as_text=True)
    assert not [c for c in salvati if c in ancora or c in storico]


def test_nascondi_codici_fiscali_nei_testi():
    import import_napoli as imp
    cf = 'RSSMRA80A01Z999X'
    assert imp.nascondi_codici_fiscali(cf) == 'RSS••••••••••99X'
    assert imp.nascondi_codici_fiscali(f'assente {cf.lower()} ieri') == 'assente RSS••••••••••99X ieri'
    assert imp.nascondi_codici_fiscali('RSS MRA 80A01 Z999X') == 'RSS••••••••••99X'
    assert imp.nascondi_codici_fiscali('DSMLMR84A71Z99') == 'DSM••••••••Z99'            # scritto male, 14 caratteri
    # niente da nascondere: ore, sigle, date, codici meccanografici, testo normale
    for testo in ('1,30', 'F perm', '24/03/2026', 'NAIC8ZZ001', 'Alunno assente il 5 e il 6', 'settimana 2: 16 ore'):
        assert imp.nascondi_codici_fiscali(testo) == testo
    assert imp.nascondi_codici_fiscali(None) is None


def test_un_codice_fiscale_scritto_in_una_cella_non_arriva_in_chiaro(database_isolato, app_module, db_mod, tmp_path):
    """Un codice fiscale scritto per errore in una cella dei giorni, nelle ore di contratto,
    nella sostituzione, nella municipalita' o nella qualifica: nella risposta dell'anteprima
    (avvisi e testi) arriva solo mascherato."""
    client = fotografa_roma.client_fotografia(app_module.app, db_mod)
    proposta = client.get('/api/napoli/lotti/proposta').get_json()
    lotto = client.post('/api/napoli/lotti/procedura', json={
        'lotto': dict(proposta['lotto'], municipalita='1 e 2'), 'tariffe': proposta['tariffe'],
        'valido_da': proposta['valido_da'], 'valido_a': proposta['valido_a']}).get_json()['lotto']
    righe, _attese = ns.costruisci()
    codici = [r['cf_alunno'] for r in righe[:5]]

    def nelle_celle(r):
        r[0]['giorni'][datetime.date(2026, 3, 3)] = codici[0]
        r[1]['ore_contratto'] = f'26 {codici[1]}'
        r[2]['sostituzione'] = codici[2]
        r[3]['municipalita'] = f'mun. {codici[3]}'
        r[4]['qualifica'] = f'ASACOM {codici[4]}'
    dati = ns.leggi_bytes(str(tmp_path / 'celle'), modifica=nelle_celle)[0]
    for modo in ('import', 'confronto'):
        r = client.post('/api/napoli/import/anteprima', content_type='multipart/form-data', data={
            'file': (io.BytesIO(dati), 'm.xlsx'), 'lotto_id': str(lotto['id']), 'modo': modo, 'scelte': '{}'})
        assert r.status_code == 200, r.get_data(as_text=True)
        testo = r.get_data(as_text=True)
        assert not [c for c in codici if c in testo], f'codici fiscali in chiaro nella risposta ({modo})'
        assert calc.maschera_codice_fiscale(codici[0]) in json.dumps(r.get_json(), ensure_ascii=False)

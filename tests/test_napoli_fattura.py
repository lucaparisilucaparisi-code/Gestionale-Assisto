"""Prospetto fattura di Napoli (passo 1.9, PROGETTO §5.4, §5.5 e §9; REGOLE 9, 10, 12).

La fattura reale di giugno si riproduce da ore scritte nella griglia presenze e dal totale del
coordinatore, con dati inventati equivalenti: contratto XI del grado inferiore dall'08/06/2026,
71,55 ore del coordinatore x 29,66, 292,75 ore di educatore x 24,28, 6 di psicologo x 29,66,
654,25 di asacom x 23,44 -> 24.743,72 / -123,72 / 24.620,00 / 1.231,00 / 25.851,00, da pagare
24.620,00 (split payment). L'Excel riletto con openpyxl ha gli stessi numeri; la definitiva
congela righe, totali e testi e blocca le ore del periodo finche' non si riapre; i bloccanti
fermano la definitiva; il mese si chiude con le fatture definitive (o con la conferma).

Solo dati inventati: codici fiscali con il comune Z999, IBAN con ABI e CAB 00000, CIG di prova;
oggi e' il 5 novembre 2026 (napoli_db._oggi).
"""
import datetime
import io
import json
import sqlite3

import openpyxl
import pytest

import napoli_calcoli as nc
import napoli_db
import seme_napoli
from strumenti import fotografa_roma

OGGI = datetime.date(2026, 11, 5)
GIUGNO = dict(anno=2026, mese=6)
OGGETTO_GIUGNO = ("Servizio di assistenza specialistica all'integrazione scolastica - Lotto 1 - Scuole di grado "
                  "inferiore - Competenze dal 08 al 30 Giugno 2026. XI APPLICATIVO")


def _ok(r):
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _errore(r, stato, codice=None, campo=None):
    assert r.status_code == stato, r.get_data(as_text=True)
    dati = r.get_json()
    assert dati['error'] and (codice is None or dati['code'] == codice), dati
    assert campo is None or dati.get('campo') == campo, dati
    return dati


def _righe_db(percorso, sql, parametri=()):
    conn = sqlite3.connect(percorso)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, parametri)]
    finally:
        conn.close()


def _giorni_giugno():
    """I giorni di servizio del contratto XI in giugno 2026: dall'8 al 30, da lunedi' a sabato (20)."""
    return [g for g in nc.giorni_mese(2026, 6) if g.day >= 8]


@pytest.fixture
def napoli(database_isolato, app_module, db_mod, monkeypatch):
    """NAPOLI LOTTO 1 con le tariffe proposte (IVA esclusa, dal 01/09/2025 al 31/01/2027), la
    cooperativa con un IBAN inventato, il destinatario proposto (Comune di Napoli - AREA
    WELFARE), il contratto XI del grado inferiore dall'08/06/2026 al 31/07/2026 (D.D. 1093
    N.31 del 12/06/2026) e il contratto XI del grado superiore negli stessi giorni (senza D.D.),
    due scuole (inferiore e superiore) e le coppie di giugno: 4 educatori, 1 psicologo, 8 asacom
    nella scuola inferiore e un educatore nella superiore. Nessuna ora scritta."""
    monkeypatch.setattr(napoli_db, '_oggi', lambda: OGGI)
    c = fotografa_roma.client_fotografia(app_module.app, db_mod)
    proposta = _ok(c.get('/api/napoli/lotti/proposta'))
    lotto = _ok(c.post('/api/napoli/lotti/procedura', json={
        'lotto': dict(proposta['lotto'], municipalita='1 e 2', cig='ZZ00000000'), 'tariffe': proposta['tariffe'],
        'valido_da': proposta['valido_da'], 'valido_a': proposta['valido_a']}))['lotto']['id']
    _ok(c.put('/api/napoli/impostazioni/cooperativa', json={
        'cooperativa_denominazione': 'COOPERATIVA DI FANTASIA', 'cooperativa_iban': seme_napoli.iban_inventato()}))
    _ok(c.put('/api/napoli/impostazioni/destinatario',
              json=_ok(c.get('/api/napoli/impostazioni'))['destinatario_proposto']))
    url = f'/api/napoli/lotti/{lotto}'
    c.contratti = {}
    for grado, dd in (('inferiore', {'dd_servizio': '1093', 'dd_numero': '31', 'dd_data': '2026-06-12'}),
                      ('superiore', {})):
        c.contratti[grado] = _ok(c.post(f'{url}/contratti', json=dict(
            numero='XI', grado=grado, valido_da='2026-06-08', valido_a='2026-07-31', **dd)))['contratto']['id']
    inf = _ok(c.post(f'{url}/scuole', json={'nome': 'IC Fantasia', 'codice_meccanografico': 'NAIC8ZZ001',
                                            'municipalita': 1, 'grado': 'inferiore'}))['scuola_id']
    sup = _ok(c.post(f'{url}/scuole', json={'nome': 'IS Immaginario', 'codice_meccanografico': 'NAIS0ZZ002',
                                            'municipalita': 2, 'grado': 'superiore'}))['scuola_id']
    c.coppie = {}

    def coppia(chiave, figura, scuola, n):
        alunno = _ok(c.post(f'{url}/alunni', json={
            'cognome': f'Esempio{chr(65 + n)}', 'nome': 'Alunno', 'scuola_id': scuola,
            'codice_fiscale': seme_napoli._cf(f'Esempio{chr(65 + n)}', 'Alunno', 2014, 3, 1 + n, 'M')}))['alunno_id']
        operatore = _ok(c.post('/api/napoli/operatori', json={'cognome': f'Operatore{chr(65 + n)}', 'nome': 'Prova',
                                                              'figura': figura}))['operatore_id']
        c.coppie[chiave] = _ok(c.post(f'{url}/coppie', json={'alunno_id': alunno, 'operatore_id': operatore,
                                                              'valido_da': '2026-06-01'}))['coppia_id']
        c.alunni = getattr(c, 'alunni', {})
        c.alunni[chiave] = alunno

    n = 0
    for chiave, figura in ([(f'E{i}', 'EDUCATORE') for i in range(1, 5)] + [('P1', 'PSICOLOGO')]
                           + [(f'A{i}', 'ASACOM') for i in range(1, 9)]):
        coppia(chiave, figura, inf, n)
        n += 1
    coppia('S1', 'EDUCATORE', sup, n)
    c.lotto_id, c.percorso, c.url, c.scuole = lotto, database_isolato, url, (inf, sup)
    return c


def _salva(c, celle, anno=2026, mese=6):
    return c.post(f'{c.url}/presenze', json={'anno': anno, 'mese': mese, 'celle': celle})


def _ore_di_giugno(c):
    """Le ore della fattura di giugno nella griglia: educatore 292,75, psicologo 6, asacom 654,25."""
    giorni = [g.isoformat() for g in _giorni_giugno()]
    assert len(giorni) == 20
    celle = []
    for k in ('E1', 'E2', 'E3'):
        celle += [{'coppia_id': c.coppie[k], 'data': g, 'testo': '4,75'} for g in giorni]      # 3 x 95 = 285
    celle += [{'coppia_id': c.coppie['E4'], 'data': giorni[0], 'testo': '4'},
              {'coppia_id': c.coppie['E4'], 'data': giorni[1], 'testo': '3,75'}]                  # 7,75
    celle += [{'coppia_id': c.coppie['P1'], 'data': g, 'testo': '2'} for g in giorni[:3]]       # 6
    for k in range(1, 8):
        celle += [{'coppia_id': c.coppie[f'A{k}'], 'data': g, 'testo': '4,5'} for g in giorni]  # 7 x 90 = 630
    celle += [{'coppia_id': c.coppie['A8'], 'data': g, 'testo': '5'} for g in giorni[:4]]       # 20
    celle.append({'coppia_id': c.coppie['A8'], 'data': giorni[4], 'testo': '4,25'})             # 4,25
    esito = _ok(_salva(c, celle))
    assert esito['salvate'] == len(celle) and all(e['esito'] == 'salvata' for e in esito['celle']), esito


def _coordinatore(c, ore='71,55', grado='inferiore'):
    return c.put(f'{c.url}/coordinamento', json={'anno': 2026, 'mese': 6, 'contratto_id': c.contratti[grado],
                                                  'grado': grado, 'ore': ore})


def _fatture(c, anno=2026, mese=6):
    return _ok(c.get(f'{c.url}/fatture?anno={anno}&mese={mese}'))


def _prospetto(elenco, grado='inferiore'):
    return next(p for p in elenco['prospetti'] if p['grado'] == grado)


def _definitiva(c, p, numero='37A2/2026', data='2026-07-31', **altro):
    return c.post(f'{c.url}/fatture/definitiva', json=dict(
        anno=2026, mese=6, contratto_id=p['contratto_id'], grado=p['grado'], numero=numero, data=data,
        impronta=p['impronta'], **altro))


@pytest.fixture
def giugno(napoli):
    _ore_di_giugno(napoli)
    _ok(_coordinatore(napoli))
    return napoli


# ==================== la fattura reale di giugno ====================

def test_giugno_come_la_fattura_reale(giugno):
    p = _prospetto(_fatture(giugno))
    assert (p['numero'], p['grado'], p['dal'], p['al']) == ('XI', 'inferiore', '2026-06-08', '2026-06-30')
    assert p['periodo_testo'] == 'dal 08/06/2026 al 30/06/2026' and not p['mese_intero']
    assert [(r['descrizione'], r['ore'], r['tariffa'], r['importo']) for r in p['righe']] == [
        ('Coordinatore', '71,55', '29,66', '2.122,17'), ('Educatore', '292,75', '24,28', '7.107,97'),
        ('Psicologo', '6,00', '29,66', '177,96'), ('Asacom', '654,25', '23,44', '15.335,62')]
    t = p['totali']
    assert (t['somma'], t['ritenuta'], t['imponibile'], t['iva'], t['totale'], t['da_pagare']) == (
        '24.743,72', '123,72', '24.620,00', '1.231,00', '25.851,00', '24.620,00')
    assert p['oggetto'] == OGGETTO_GIUGNO
    assert p['ritenuta_testo'] == 'RITENUTA dello 0,50% ex art. 30, c.5 bis, del D.lgs. 50/2016'
    assert p['nota'].startswith('D.D. 1093 N.31 DEL 12/06/2026 - Scissione dei pagamenti (split payment)')
    assert p['destinatario'] == ('Comune di Napoli - AREA WELFARE, Via Salvatore Tommasi 19, 80133 Napoli (NA), '
                                 'CF 80014890638')
    assert p['split_payment'] and p['iva_percento'] == '5' and p['scadenza_testo'] == \
        'a 30 giorni dalla data della fattura'
    assert p['testata']['cig'] == 'ZZ00000000' and p['testata']['iban'].startswith('IT') and '•' in p['testata']['iban']
    assert p['bloccanti'] == [] and p['puo_rendere_definitiva'] and p['stato'] == 'da_fare'
    # il dettaglio per scuola e per operatore torna con le righe (senza il coordinatore)
    assert sum(x['minuti'] for x in p['dettaglio']['scuole']) == 17565 + 360 + 39255
    assert len(p['dettaglio']['operatori']) == 13
    # il grado superiore del contratto XI ha solo l'educatore della scuola superiore (nessuna ora)
    sup = _prospetto(_fatture(giugno), 'superiore')
    assert sup['vuoto'] and not sup['puo_rendere_definitiva'] and sup['righe'] == []


def test_le_ore_di_giugno_sono_quelle_delle_funzioni_pure(giugno):
    """Il prospetto della pagina e' quello di napoli_calcoli.prospetto_fattura sulle righe del database."""
    presenze = _righe_db(giugno.percorso, '''
        SELECT p.data, p.figura, p.stato, p.minuti_riconosciuti, COALESCE(a.grado, s.grado) AS grado,
               o.livello_ccnl FROM napoli_presenze p JOIN napoli_coppie c ON c.id = p.coppia_id
        JOIN napoli_alunni a ON a.id = c.alunno_id JOIN napoli_scuole s ON s.id = c.scuola_id
        JOIN napoli_operatori o ON o.id = c.operatore_id''')
    tariffe = _righe_db(giugno.percorso, 'SELECT * FROM napoli_tariffe')
    coord = _righe_db(giugno.percorso, 'SELECT * FROM napoli_coordinamento')
    contratto = _righe_db(giugno.percorso, 'SELECT * FROM napoli_contratti WHERE id = ?',
                          (giugno.contratti['inferiore'],))[0]
    puro = nc.prospetto_fattura(2026, 6, 'inferiore', contratto, presenze, tariffe, coord)
    p = _prospetto(_fatture(giugno))
    assert [r['importo_cent'] for r in p['righe']] == [r['importo_cent'] for r in puro['righe']]
    assert p['totali']['imponibile_cent'] == puro['totali']['imponibile_cent'] == 2462000


# ==================== Excel e stampa ====================

def test_excel_riletto_con_gli_stessi_numeri(giugno):
    p = _prospetto(_fatture(giugno))
    r = giugno.get(f'/api/napoli/fatture/excel?lotto_id={giugno.lotto_id}&anno=2026&mese=6'
                   f'&contratto_id={p["contratto_id"]}&grado=inferiore')
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.headers['Content-Type'].startswith('application/vnd.openxmlformats-officedocument.spreadsheetml')
    assert 'Napoli_Fattura_Lotto1_XI_inferiore_Giugno_2026.xlsx' in r.headers['Content-Disposition']
    wb = openpyxl.load_workbook(io.BytesIO(r.data))
    assert wb.sheetnames == ['Prospetto', 'Per scuola', 'Per operatore', 'Controlli', 'Ritenute']
    ws = wb['Prospetto']
    righe = {}
    for riga in ws.iter_rows(values_only=True):
        if riga[0] is not None:
            righe[str(riga[0])] = riga
    assert righe['Oggetto'][1] == OGGETTO_GIUGNO
    attese = {'Coordinatore': (71.55, 29.66, 2122.17), 'Educatore': (292.75, 24.28, 7107.97),
              'Psicologo': (6, 29.66, 177.96), 'Asacom': (654.25, 23.44, 15335.62)}
    for descrizione, (ore, tariffa, importo) in attese.items():
        assert righe[descrizione][1:4] == pytest.approx((ore, tariffa, importo), abs=0.001), descrizione
    assert righe['RITENUTA dello 0,50% ex art. 30, c.5 bis, del D.lgs. 50/2016'][3] == pytest.approx(-123.72)
    assert righe['Totale delle righe'][3] == pytest.approx(24743.72)
    assert righe['Imponibile'][3] == pytest.approx(24620.00)
    assert righe['IVA 5%'][3] == pytest.approx(1231.00)
    assert righe['Totale documento'][3] == pytest.approx(25851.00)
    assert righe['Da pagare (split payment)'][3] == pytest.approx(24620.00)
    # numeri veri (non testo) con il formato all'italiana di Excel
    cella = next(c for c in ws['D'] if c.value == pytest.approx(24620.00))
    assert isinstance(cella.value, (int, float)) and '0.00' in cella.number_format
    # nessun nome di alunno o codice fiscale nel file; gli operatori solo nel foglio «Per operatore»
    testo = ' '.join(str(v) for f in wb for riga in f.iter_rows(values_only=True) for v in riga if v is not None)
    assert 'Alunno' not in testo.replace('alunno', '') and 'Z999' not in testo
    assert 'OperatoreA' not in ' '.join(str(v) for riga in ws.iter_rows(values_only=True) for v in riga if v)
    assert ws.page_setup.paperSize == 9 and ws.sheet_properties.pageSetUpPr.fitToPage
    per_operatore = wb['Per operatore']
    totale = next(r for r in per_operatore.iter_rows(values_only=True) if r[0] == 'Totale')
    assert totale[2] == pytest.approx(292.75 + 6 + 654.25)


def test_stampa_a4_del_prospetto(giugno):
    p = _prospetto(_fatture(giugno))
    pagina = giugno.get(f'/napoli/fattura/stampa?lotto_id={giugno.lotto_id}&anno=2026&mese=6'
                        f'&contratto_id={p["contratto_id"]}&grado=inferiore').get_data(as_text=True)
    assert '@page' in pagina and 'A4' in pagina
    for testo in (OGGETTO_GIUGNO.replace("'", '&#39;'), '2.122,17', '7.107,97', '177,96', '15.335,62', '24.743,72',
                  '-123,72', '24.620,00', '1.231,00', '25.851,00', 'Non ancora definitiva'):
        assert testo in pagina, testo
    assert 'Esempio' not in pagina and 'Z999' not in pagina
    errore = giugno.get(f'/napoli/fattura/stampa?lotto_id={giugno.lotto_id}&anno=2026&mese=6&contratto_id=999'
                        '&grado=inferiore')
    assert errore.status_code == 404 and 'Il contratto applicativo non esiste' in errore.get_data(as_text=True)


# ==================== rendi definitiva e riapri ====================

def test_definitiva_congelata_e_ore_bloccate(giugno):
    p = _prospetto(_fatture(giugno))
    _errore(_definitiva(giugno, p, numero=''), 400, campo='numero')
    _errore(_definitiva(giugno, p, data='2026-12-01'), 400, campo='data')
    _errore(_definitiva(giugno, p, data='2026-05-31'), 400, campo='data')
    esito = _ok(_definitiva(giugno, p))
    assert 'definitiva' in esito['messaggio']
    f = _righe_db(giugno.percorso, 'SELECT * FROM napoli_fatture')[0]
    assert (f['stato'], f['numero'], f['data'], f['periodo_dal'], f['periodo_al']) == (
        'definitiva', '37A2/2026', '2026-07-31', '2026-06-08', '2026-06-30')
    assert (f['somma_righe_cent'], f['ritenuta_cent'], f['imponibile_cent'], f['iva_cent'], f['totale_cent'],
            f['da_pagare_cent']) == (2474372, 12372, 2462000, 123100, 2585100, 2462000)
    assert f['oggetto'] == OGGETTO_GIUGNO and f['scadenza'] == '2026-08-30' and f['definitiva_il']
    testata = json.loads(f['testata_json'])
    assert testata['cig'] == 'ZZ00000000' and testata['contratto'] == 'XI' and '•' in testata['iban']
    assert seme_napoli.iban_inventato() not in json.dumps(f)
    righe = json.loads(f['righe_json'])
    assert [(r['figura'], r['ore_cent'], r['importo_cent']) for r in righe] == [
        ('COORDINATORE', 7155, 212217), ('EDUCATORE', 29275, 710797), ('PSICOLOGO', 600, 17796),
        ('ASACOM', 65425, 1533562)]
    assert 'Esempio' not in f['righe_json'] and 'Operatore' not in f['righe_json']
    _errore(_definitiva(giugno, p, numero='37A3/2026'), 409, 'GIA_DEFINITIVA')

    # le ore del periodo e del grado non cambiano: griglia, coordinatore, Ctrl+Z
    giorno = _giorni_giugno()[0].isoformat()
    esito = _ok(_salva(giugno, [{'coppia_id': giugno.coppie['E1'], 'data': giorno, 'testo': '5'}]))
    assert (esito['celle'][0]['esito'], esito['celle'][0]['codice']) == ('errore', 'FATTURA_DEFINITIVA')
    assert 'fattura definitiva di giugno 2026, contratto XI (grado inferiore), n. 37A2/2026' in \
        esito['celle'][0]['messaggio']
    _errore(_coordinatore(giugno, '70'), 409, 'FATTURA_DEFINITIVA', campo='ore')
    annulla = giugno.post('/api/napoli/annulla', json={})
    _errore(annulla, 400, 'NON_ANNULLABILE')
    # il grado superiore dello stesso periodo resta libero
    _ok(_salva(giugno, [{'coppia_id': giugno.coppie['S1'], 'data': giorno, 'testo': '2'}]))
    # e i giorni prima del contratto (fuori dalla fattura) anche
    _ok(_salva(giugno, [{'coppia_id': giugno.coppie['E1'], 'data': '2026-06-05', 'testo': '1'}]))
    griglia = _ok(giugno.get(f'{giugno.url}/presenze?anno=2026&mese=6'))
    riga_e1 = next(r for r in griglia['righe'] if r['id'] == giugno.coppie['E1'])
    riga_s1 = next(r for r in griglia['righe'] if r['id'] == giugno.coppie['S1'])
    assert len(riga_e1['definitiva']) == 20 and riga_s1['definitiva'] == []
    assert griglia['definitive'][0]['testo'].startswith('giugno 2026, contratto XI (grado inferiore)')

    # la pagina mostra la fattura congelata
    p2 = _prospetto(_fatture(giugno))
    assert p2['stato'] == 'definitiva' and p2['fattura']['numero'] == '37A2/2026'
    assert p2['totali']['imponibile'] == '24.620,00' and p2['scadenza_testo'] == '30/08/2026'
    assert not p2['puo_rendere_definitiva'] and not p2['coordinatore']['modificabile']
    coord = _ok(giugno.get(f'{giugno.url}/coordinamento'))
    riga = next(r for m in coord['mesi'] if (m['anno'], m['mese']) == (2026, 6) for r in m['righe']
                if r['grado'] == 'inferiore')
    assert riga['definitiva'].startswith('giugno 2026, contratto XI')


def test_la_definitiva_non_cambia_se_cambiano_tariffe_e_testi(giugno):
    p = _prospetto(_fatture(giugno))
    _ok(_definitiva(giugno, p))
    tariffa = next(t for t in _ok(giugno.get(f'{giugno.url}/tariffe')) if t['figura'] == 'ASACOM')
    _ok(giugno.put(f'/api/napoli/tariffe/{tariffa["id"]}', json=dict(tariffa, tariffa='25,00')))
    _ok(giugno.put(f'{giugno.url}', json={'cig': 'ZZ11111111', 'oggetto_fattura': 'Altro {lotto} {grado}'}))
    p2 = _prospetto(_fatture(giugno))
    assert p2['totali']['imponibile'] == '24.620,00' and p2['oggetto'] == OGGETTO_GIUGNO
    assert p2['testata']['cig'] == 'ZZ00000000'
    assert [a['codice'] for a in p2['avvisi']] == ['cambiata_dopo']
    # l'Excel e la stampa della definitiva hanno i numeri congelati
    wb = openpyxl.load_workbook(io.BytesIO(giugno.get(
        f'/api/napoli/fatture/excel?lotto_id={giugno.lotto_id}&anno=2026&mese=6&contratto_id={p["contratto_id"]}'
        '&grado=inferiore').data))
    valori = [r for r in wb['Prospetto'].iter_rows(values_only=True) if r[0] == 'Asacom']
    assert valori[0][3] == pytest.approx(15335.62)
    assert str(wb['Prospetto']['A1'].value).startswith('FATTURA DEFINITIVA N. 37A2/2026 DEL 31/07/2026')


def test_un_contratto_con_la_definitiva_non_cambia_periodo(giugno):
    p = _prospetto(_fatture(giugno))
    _ok(_definitiva(giugno, p))
    contratto = _righe_db(giugno.percorso, 'SELECT * FROM napoli_contratti WHERE id = ?',
                          (giugno.contratti['inferiore'],))[0]
    _errore(giugno.put(f'/api/napoli/contratti/{contratto["id"]}', json=dict(contratto, valido_da='2026-06-01')),
            409, 'FATTURA_DEFINITIVA')
    # la fine si puo' spostare dopo giugno: il periodo di giugno resta dal 08 al 30
    _ok(giugno.put(f'/api/napoli/contratti/{contratto["id"]}', json=dict(contratto, valido_a='2026-08-31')))
    # il grado della scuola o dell'alunno e la scuola della coppia non cambiano
    _errore(giugno.put(f'/api/napoli/scuole/{giugno.scuole[0]}', json={'grado': 'superiore'}), 409,
            'FATTURA_DEFINITIVA')
    _errore(giugno.put(f'/api/napoli/alunni/{giugno.alunni["E1"]}', json={'grado': 'superiore'}), 409,
            'FATTURA_DEFINITIVA')
    _errore(giugno.put(f'/api/napoli/coppie/{giugno.coppie["E1"]}', json={'scuola_id': giugno.scuole[1]}), 409,
            'FATTURA_DEFINITIVA')


def test_riapri_con_il_motivo(giugno):
    p = _prospetto(_fatture(giugno))
    _ok(_definitiva(giugno, p))
    fattura_id = _prospetto(_fatture(giugno))['fattura']['id']
    _errore(giugno.post(f'/api/napoli/fatture/{fattura_id}/riapri', json={}), 400, campo='motivo')
    _errore(giugno.post(f'/api/napoli/fatture/{fattura_id}/riapri', json={'motivo': 'no'}), 400, campo='motivo')
    _ok(giugno.post(f'/api/napoli/fatture/{fattura_id}/riapri', json={'motivo': 'Correzione delle ore di prova'}))
    _errore(giugno.post(f'/api/napoli/fatture/{fattura_id}/riapri', json={'motivo': 'di nuovo, di prova'}), 409,
            'NON_DEFINITIVA')
    p2 = _prospetto(_fatture(giugno))
    assert p2['stato'] == 'riaperta' and p2['fattura']['numero'] == '37A2/2026' and p2['fattura']['riaperta_il']
    # le ore si cambiano di nuovo e il prospetto si ricalcola
    giorno = _giorni_giugno()[0].isoformat()
    _ok(_salva(giugno, [{'coppia_id': giugno.coppie['E1'], 'data': giorno, 'testo': '5'}]))
    p3 = _prospetto(_fatture(giugno))
    assert next(r for r in p3['righe'] if r['figura'] == 'EDUCATORE')['ore'] == '293,00'
    # di nuovo definitiva con lo stesso numero (la riga riaperta si aggiorna)
    _ok(_definitiva(giugno, p3))
    righe = _righe_db(giugno.percorso, 'SELECT * FROM napoli_fatture')
    assert len(righe) == 1 and righe[0]['stato'] == 'definitiva' and righe[0]['imponibile_cent'] != 2462000
    voci = _righe_db(giugno.percorso, "SELECT azione, dettagli FROM audit_log WHERE entita = 'napoli_fattura' "
                                      "ORDER BY id")
    assert [v['azione'] for v in voci] == ['definitiva', 'riapertura', 'definitiva']
    assert voci[0]['dettagli'] == ('Napoli, NAPOLI LOTTO 1: Fattura definitiva di giugno 2026, contratto XI (grado '
                                   'inferiore), n. 37A2/2026: imponibile 24.620,00 euro')
    assert voci[1]['dettagli'] == ('Napoli, NAPOLI LOTTO 1: Riapertura della fattura di giugno 2026, contratto XI '
                                   '(grado inferiore), n. 37A2/2026. Motivo: Correzione delle ore di prova')
    assert all('Esempio' not in v['dettagli'] and 'IT' not in v['dettagli'].split('Motivo')[0] for v in voci)


def test_numero_gia_usato(giugno):
    p = _prospetto(_fatture(giugno))
    _ok(_definitiva(giugno, p))
    _ok(_salva(giugno, [{'coppia_id': giugno.coppie['S1'], 'data': _giorni_giugno()[0].isoformat(), 'testo': '2'}]))
    _ok(giugno.put(f'/api/napoli/contratti/{giugno.contratti["superiore"]}', json={
        'numero': 'XI', 'grado': 'superiore', 'valido_da': '2026-06-08', 'valido_a': '2026-07-31',
        'dd_numero': '32', 'dd_data': '2026-06-12'}))
    _ok(_coordinatore(giugno, '3', 'superiore'))
    sup = _prospetto(_fatture(giugno), 'superiore')
    assert sup['puo_rendere_definitiva'], sup['bloccanti']
    _errore(_definitiva(giugno, sup), 409, 'NUMERO_GIA_USATO', campo='numero')
    _ok(_definitiva(giugno, sup, numero='38A2/2026'))


def test_prospetto_cambiato_nel_frattempo(giugno):
    p = _prospetto(_fatture(giugno))
    _ok(_salva(giugno, [{'coppia_id': giugno.coppie['E4'], 'data': _giorni_giugno()[2].isoformat(), 'testo': '1'}]))
    _errore(_definitiva(giugno, p), 409, 'PROSPETTO_CAMBIATO')


# ==================== bloccanti ====================

def _codici(p):
    return [b['codice'] for b in p['bloccanti']]


def test_bloccanti_spiegati(napoli):
    """Grado da decidere, figura con ore e senza tariffa, dati mancanti (IBAN, D.D.), ore fuori dai
    contratti: ognuno con il suo testo e dove sistemarlo, e la definitiva rifiutata."""
    giorno = _giorni_giugno()[0].isoformat()
    _ok(_salva(napoli, [{'coppia_id': napoli.coppie['E1'], 'data': giorno, 'testo': '3'}]))
    _ok(_coordinatore(napoli))
    p = _prospetto(_fatture(napoli))
    assert _codici(p) == [] and p['puo_rendere_definitiva']

    # grado da decidere: la scuola senza grado blocca tutti e due i gradi
    _ok(napoli.put(f'/api/napoli/scuole/{napoli.scuole[0]}', json={'grado': ''}))
    elenco = _fatture(napoli)
    for grado in ('inferiore', 'superiore'):
        assert 'grado_da_decidere' in _codici(_prospetto(elenco, grado))
    b = next(b for b in _prospetto(elenco)['bloccanti'] if b['codice'] == 'grado_da_decidere')
    assert b['titolo'] == 'Grado da decidere' and b['testo'].startswith('Educatore: 3 ore (1 giorno) di alunni')
    assert b['link'] == '/napoli/anagrafiche#scuole'
    _errore(_definitiva(napoli, _prospetto(elenco)), 400, 'FATTURA_BLOCCATA')
    _ok(napoli.put(f'/api/napoli/scuole/{napoli.scuole[0]}', json={'grado': 'inferiore'}))

    # figura con ore e senza tariffa: l'interprete LIS
    lis = _ok(napoli.post('/api/napoli/operatori', json={'cognome': 'Lis', 'nome': 'Prova', 'figura': 'LIS'}))
    alunno = napoli.alunni['E2']
    coppia = _ok(napoli.post(f'{napoli.url}/coppie', json={'alunno_id': alunno, 'operatore_id': lis['operatore_id'],
                                                           'valido_da': '2026-06-01'}))['coppia_id']
    _ok(_salva(napoli, [{'coppia_id': coppia, 'data': giorno, 'testo': '2'}]))
    p = _prospetto(_fatture(napoli))
    b = next(b for b in p['bloccanti'] if b['codice'] == 'tariffa_mancante')
    assert b['titolo'] == 'Manca la tariffa Interprete LIS' and b['testo'].startswith('Interprete LIS: 2 ore (1 giorno)')
    assert b['link'] == '/napoli/impostazioni#tariffe'
    _ok(_salva(napoli, [{'coppia_id': coppia, 'data': giorno, 'testo': ''}]))

    # dati obbligatori mancanti: IBAN della cooperativa e numero della D.D.
    _ok(napoli.put('/api/napoli/impostazioni/cooperativa', json={'cooperativa_iban': ''}))
    contratto = _righe_db(napoli.percorso, 'SELECT * FROM napoli_contratti WHERE id = ?',
                          (napoli.contratti['inferiore'],))[0]
    _ok(napoli.put(f'/api/napoli/contratti/{contratto["id"]}', json=dict(contratto, dd_numero='')))
    p = _prospetto(_fatture(napoli))
    mancanti = {b['campo']: b for b in p['bloccanti'] if b['codice'] == 'dato_mancante'}
    assert set(mancanti) == {'iban', 'dd_numero'}
    assert mancanti['iban']['titolo'] == "Manca l'IBAN della cooperativa"
    assert mancanti['iban']['link'] == '/napoli/impostazioni#cooperativa'
    assert mancanti['dd_numero']['link'] == '/napoli/impostazioni#contratti'
    _ok(napoli.put('/api/napoli/impostazioni/cooperativa', json={'cooperativa_iban': seme_napoli.iban_inventato()}))
    _ok(napoli.put(f'/api/napoli/contratti/{contratto["id"]}', json=dict(contratto, dd_numero='31')))

    # ore fuori dai contratti: il 5 giugno nessun contratto copre il grado inferiore
    _ok(_salva(napoli, [{'coppia_id': napoli.coppie['E2'], 'data': '2026-06-05', 'testo': '2'}]))
    elenco = _fatture(napoli)
    p = _prospetto(elenco)
    b = next(b for b in p['bloccanti'] if b['codice'] == 'presenza_fuori_contratto')
    assert b['testo'].startswith('Educatore: 2 ore (1 giorno) del grado inferiore in date di giugno 2026')
    assert elenco['ore_senza_contratto'] == '2'
    assert _codici(_prospetto(elenco, 'superiore')) == []
    _ok(_salva(napoli, [{'coppia_id': napoli.coppie['E2'], 'data': '2026-06-05', 'testo': ''}]))
    assert _codici(_prospetto(_fatture(napoli))) == []


def test_periodo_non_finito_e_coordinatore_non_scritto(napoli, monkeypatch):
    monkeypatch.setattr(napoli_db, '_oggi', lambda: datetime.date(2026, 6, 20))
    _ok(_salva(napoli, [{'coppia_id': napoli.coppie['E1'], 'data': '2026-06-15', 'testo': '3'}]))
    p = _prospetto(_fatture(napoli))
    assert _codici(p) == ['periodo_non_finito'] and 'finisce il 30/06/2026' in p['bloccanti'][0]['testo']
    assert [a['codice'] for a in p['avvisi']] == ['coordinatore_non_scritto']


def test_giorni_non_registrati_bloccano(giugno):
    conn = sqlite3.connect(giugno.percorso)
    with conn:
        conn.execute("UPDATE napoli_presenze SET stato = 'programmato' WHERE id = (SELECT MIN(id) FROM napoli_presenze)")
    conn.close()
    p = _prospetto(_fatture(giugno))
    b = next(b for b in p['bloccanti'] if b['codice'] == 'giorni_non_registrati')
    assert b['testo'] == ('Educatore: 1 giorno è preparato ma non ancora registrato e vale 0 ore. Scrivi le ore '
                          '(anche 0) nella griglia.')
    assert not p['puo_rendere_definitiva']


# ==================== ritenute cumulate e chiusura del mese ====================

def test_ritenute_cumulate_per_contratto(giugno):
    _ok(_definitiva(giugno, _prospetto(_fatture(giugno))))
    r = _ok(giugno.get(f'{giugno.url}/fatture/ritenute'))
    assert r['totale'] == '123,72' and len(r['contratti']) == 1
    c = r['contratti'][0]
    assert (c['numero'], c['n'], c['somma'], c['ritenuta']) == ('XI', 1, '24.743,72', '123,72')
    assert c['fatture'][0]['numero'] == '37A2/2026'
    wb = openpyxl.load_workbook(io.BytesIO(giugno.get(
        f'/api/napoli/fatture/excel?lotto_id={giugno.lotto_id}&anno=2026&mese=6'
        f'&contratto_id={giugno.contratti["inferiore"]}&grado=inferiore').data))
    totale = next(x for x in wb['Ritenute'].iter_rows(values_only=True) if str(x[0]).startswith('Ritenute del'))
    assert totale[-2:] == pytest.approx((24743.72, 123.72))


def test_il_mese_si_chiude_con_le_fatture_definitive(giugno):
    url = f'{giugno.url}/mesi/chiudi'
    e = _errore(giugno.post(url, json=GIUGNO), 409, 'FATTURE_NON_DEFINITIVE')
    assert e['fatture'] == ['contratto XI (grado inferiore), dal 08/06/2026 al 30/06/2026']
    _ok(_definitiva(giugno, _prospetto(_fatture(giugno))))
    _ok(giugno.post(url, json=GIUGNO))
    # riaperto, con un'ora del grado superiore senza fattura: si chiude solo con la conferma
    _ok(giugno.post(f'{giugno.url}/mesi/riapri', json=dict(GIUGNO, motivo='Correzione di prova')))
    _ok(_salva(giugno, [{'coppia_id': giugno.coppie['S1'], 'data': _giorni_giugno()[0].isoformat(), 'testo': '2'}]))
    e = _errore(giugno.post(url, json=GIUGNO), 409, 'FATTURE_NON_DEFINITIVE')
    assert e['fatture'] == ['contratto XI (grado superiore), dal 08/06/2026 al 30/06/2026']
    _ok(giugno.post(url, json=dict(GIUGNO, senza_fattura=True)))
    # a mese chiuso la fattura definitiva si riapre lo stesso (le ore restano bloccate dal mese)
    fattura_id = _prospetto(_fatture(giugno))['fattura']['id']
    _ok(giugno.post(f'/api/napoli/fatture/{fattura_id}/riapri', json={'motivo': 'Correzione di prova'}))


def test_import_delle_ore_bloccato_dalla_definitiva(giugno):
    import import_napoli
    _ok(_definitiva(giugno, _prospetto(_fatture(giugno))))
    with pytest.raises(napoli_db.Conflitto) as e:
        import_napoli._controlla_fatture_definitive(giugno.lotto_id, 2026, 6, 'le ore di quel mese non si importano')
    assert e.value.codice == 'FATTURA_DEFINITIVA' and 'riaprila prima' in e.value.messaggio
    import_napoli._controlla_fatture_definitive(giugno.lotto_id, 2026, 9, 'x')     # un altro mese: niente


def test_la_pagina_fattura(napoli):
    pagina = napoli.get('/napoli/fattura').get_data(as_text=True)
    assert 'NapoliFattura.avvia()' in pagina and 'id="fattura-contenuto"' in pagina
    assert 'href="/napoli/fattura"' in napoli.get('/napoli').get_data(as_text=True)


def test_ctrl_z_non_cambia_le_ore_di_una_fattura_definitiva(giugno):
    """La memoria di Ctrl+Z ha una casella del periodo (com'era prima): con la fattura definitiva
    non si rimette (anche se l'azione non fosse dietro la definitiva, che non si annulla)."""
    p = _prospetto(_fatture(giugno))
    _ok(_definitiva(giugno, p))
    riga = _righe_db(giugno.percorso, 'SELECT * FROM napoli_presenze WHERE coppia_id = ? ORDER BY data LIMIT 1',
                     (giugno.coppie['E1'],))[0]
    coord = _righe_db(giugno.percorso, 'SELECT * FROM napoli_coordinamento')[0]
    conn = sqlite3.connect(giugno.percorso)
    conn.row_factory = sqlite3.Row
    try:
        for voce in ({'tabella': 'presenze', 'chiave': riga['id'], 'prima': dict(riga, minuti_riconosciuti=0)},
                     {'tabella': 'coordinamento', 'chiave': coord['id'], 'prima': dict(coord, ore_cent=1)}):
            with pytest.raises(napoli_db.Conflitto) as e:
                napoli_db._controlla_fatture_definitive(conn, [voce])
            assert e.value.codice == 'FATTURA_DEFINITIVA'
        # una casella di prima del contratto (fuori dalla fattura) si rimette
        napoli_db._controlla_fatture_definitive(conn, [{'tabella': 'presenze', 'chiave': None,
                                                        'prima': dict(riga, data='2026-06-05')}])
    finally:
        conn.close()


def test_stampa_della_definitiva(giugno):
    p = _prospetto(_fatture(giugno))
    _ok(_definitiva(giugno, p))
    pagina = giugno.get(f'/napoli/fattura/stampa?lotto_id={giugno.lotto_id}&anno=2026&mese=6'
                        f'&contratto_id={p["contratto_id"]}&grado=inferiore&stampa=1').get_data(as_text=True)
    assert 'Definitiva · fattura n. 37A2/2026 del 31/07/2026' in pagina and 'scadenza 30/08/2026' in pagina
    assert 'window.print()' in pagina and seme_napoli.iban_inventato() not in pagina

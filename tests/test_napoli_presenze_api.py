"""Griglia presenze di Napoli (passo 1.7, PROGETTO §5-§6; REGOLE 1, 2, 3, 12, 14, 15).

Le caselle si scrivono come nel §5.1 (ore decimali, ore e minuti, sigle F, M, P, A), con la
nota del giorno (assemblea, uscita didattica, ritardo o uscita anticipata con l'orario,
assenza recuperata); i totali, le VERIFICA e il credito/debito della pagina coincidono con le
funzioni pure di napoli_calcoli; "1,30" chiede conferma; un mese chiuso del lotto rifiuta
tutto (anche Ctrl+Z); Ctrl+Z annulla solo l'ultima azione di Napoli e mai una di Roma; 330
coppie si caricano in meno di 2 secondi.

Solo dati inventati: lotto con la procedura guidata, anagrafiche con le API, codici fiscali
con il comune Z999; oggi e' il 5 novembre 2026 (napoli_db._oggi).
"""
import datetime
import json
import re
import sqlite3
import time
from pathlib import Path

import pytest

import napoli_calcoli as nc
import napoli_db
import seme_napoli
from strumenti import fotografa_roma

OGGI = datetime.date(2026, 11, 5)
OTTOBRE = dict(anno=2026, mese=10)


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


def _scrivi(percorso, sql, parametri=()):
    conn = sqlite3.connect(percorso)
    try:
        with conn:
            return conn.execute(sql, parametri).lastrowid
    finally:
        conn.close()


@pytest.fixture
def napoli(database_isolato, app_module, db_mod, monkeypatch):
    """NAPOLI LOTTO 1 con due scuole, tre alunni e tre operatori inventati:
    - Alba (PEI ASACOM 12 h dal 01/09/2026): titolare Primo dal 14/09/2026, sostituta Nona dal
      05/10 al 09/10/2026;
    - Bruno (PEI EDUCATORE 10 h, scuola superiore): titolare Seconda dal 01/10/2026;
    - Ciro (senza PEI): titolare Primo dal 01/10/2026."""
    monkeypatch.setattr(napoli_db, '_oggi', lambda: OGGI)
    c = fotografa_roma.client_fotografia(app_module.app, db_mod)
    proposta = _ok(c.get('/api/napoli/lotti/proposta'))
    lotto = _ok(c.post('/api/napoli/lotti/procedura', json={
        'lotto': dict(proposta['lotto'], municipalita='1 e 2', cig='ZZ00000000'), 'tariffe': proposta['tariffe'],
        'valido_da': proposta['valido_da'], 'valido_a': proposta['valido_a']}))['lotto']['id']
    url = f'/api/napoli/lotti/{lotto}'
    s1 = _ok(c.post(f'{url}/scuole', json={'nome': 'IC Fantasia', 'codice_meccanografico': 'NAIC8ZZ001',
                                           'municipalita': 1, 'grado': 'inferiore'}))['scuola_id']
    s2 = _ok(c.post(f'{url}/scuole', json={'nome': 'IS Immaginario', 'codice_meccanografico': 'NAIS0ZZ002',
                                           'municipalita': 2, 'grado': 'superiore'}))['scuola_id']

    def alunno(cognome, nome, scuola, nascita):
        return _ok(c.post(f'{url}/alunni', json={'cognome': cognome, 'nome': nome, 'scuola_id': scuola,
                                                 'codice_fiscale': seme_napoli._cf(cognome, nome, *nascita)}))['alunno_id']

    def operatore(cognome, nome, figura):
        return _ok(c.post('/api/napoli/operatori', json={'cognome': cognome, 'nome': nome, 'figura': figura}))[
            'operatore_id']

    def coppia(**dati):
        return _ok(c.post(f'{url}/coppie', json=dati))['coppia_id']

    alba = alunno('Esempio', 'Alba', s1, (2016, 5, 2, 'F'))
    bruno = alunno('Fittizio', 'Bruno', s2, (2009, 7, 22, 'M'))
    ciro = alunno('Inventato', 'Ciro', s1, (2015, 1, 30, 'M'))
    primo = operatore('Operatore', 'Primo', 'ASACOM')
    nona = operatore('Sostituta', 'Nona', 'ASACOM')
    seconda = operatore('Operatrice', 'Seconda', 'EDUCATORE')
    _ok(c.post(f'/api/napoli/alunni/{alba}/pei', json={'figura': 'ASACOM', 'ore_settimanali': '12',
                                                        'valido_da': '2026-09-01'}))
    _ok(c.post(f'/api/napoli/alunni/{bruno}/pei', json={'figura': 'EDUCATORE', 'ore_settimanali': '10',
                                                         'valido_da': '2026-09-01'}))
    c.lotto_id, c.percorso, c.url = lotto, database_isolato, url
    c.titolare = coppia(alunno_id=alba, operatore_id=primo, valido_da='2026-09-14')
    c.sostituto = coppia(alunno_id=alba, operatore_id=nona, ruolo='sostituto', titolare_coppia_id=c.titolare,
                         valido_da='2026-10-05', valido_a='2026-10-09')
    c.bruno = coppia(alunno_id=bruno, operatore_id=seconda, valido_da='2026-10-01')
    c.ciro = coppia(alunno_id=ciro, operatore_id=primo, valido_da='2026-10-01')
    c.scuole = (s1, s2)
    return c


def _griglia(c, anno=2026, mese=10):
    return _ok(c.get(f'{c.url}/presenze?anno={anno}&mese={mese}'))


def _salva(c, *celle, anno=2026, mese=10):
    return c.post(f'{c.url}/presenze', json={'anno': anno, 'mese': mese, 'celle': list(celle)})


def _cella(coppia, data, **campi):
    return dict(coppia_id=coppia, data=data, **campi)


def _riga(griglia, coppia):
    return next(r for r in griglia['righe'] if r['id'] == coppia)


def _ottobre_di_servizio():
    return nc.giorni_mese(2026, 10)


# ==================== funzioni pure (napoli_calcoli) ====================

@pytest.mark.parametrize('testo, attesi, causale, sigla', [
    ('2', 120, None, None), ('1,5', 90, None, None), ('1.5', 90, None, None), ('0,75', 45, None, None),
    ('1:30', 90, None, None), ('0', 0, None, None),
    ('F', 0, 'operatore_ferie', 'F'), ('f', 0, 'operatore_ferie', 'F'), ('M', 0, 'operatore_malattia', 'M'),
    ('P', 0, 'operatore_permesso', 'F perm'), ('F perm', 0, 'operatore_permesso', 'F perm'),
    ('F (PERM)', 0, 'operatore_permesso', 'F perm'),
])
def test_giorno_da_griglia_ore_e_sigle(testo, attesi, causale, sigla):
    esito = nc.giorno_da_griglia(testo)
    assert esito['esito'] == 'ore', esito
    assert esito['campi']['minuti_riconosciuti'] == attesi
    assert (esito['campi']['causale'], esito['campi']['sigla']) == (causale, sigla)
    assert esito['campi']['stato'] == 'registrato' and esito['campi']['calcolo'] == 'auto'


@pytest.mark.parametrize('programmati, attesi', [
    (180, 90),     # 10-13 assente -> 1,5 (REGOLE 1)
    (240, 120),    # 10-14 assente -> 2
    (120, 60),     # 12-14 assente -> 1
    (105, 53),     # 8:00-9:45: meta' di 105 = 52,5, per eccesso (Q12)
])
def test_alunno_assente_vale_meta_del_programmato(programmati, attesi):
    esito = nc.giorno_da_griglia('A', minuti_programmati=programmati)
    assert esito['campi']['minuti_riconosciuti'] == attesi
    assert esito['campi']['causale'] == 'alunno_assente' and esito['campi']['trattamento'] == 'meta'
    assert esito['campi']['sigla'] == 'A' and esito['campi']['minuti_svolti'] == 0


def test_alunno_assente_senza_programmato_e_recuperato():
    assert nc.giorno_da_griglia('A')['esito'] == 'servono_programmati'
    # recuperata: niente meta' e niente domanda (REGOLE 1)
    esito = nc.giorno_da_griglia('A', recuperata=True)
    assert esito['esito'] == 'ore' and esito['campi']['minuti_riconosciuti'] == 0
    assert esito['campi']['trattamento'] == 'recupero'
    # con la quota 0 (nuovo accordo, CSA) la meta' non c'e' piu': il programmato non serve
    esito = nc.giorno_da_griglia('A', regole={'quota_assenza_alunno': 0})
    assert esito['esito'] == 'ore' and esito['campi']['minuti_riconosciuti'] == 0


def test_note_del_giorno_come_la_tabella_5_2():
    # 8-9 + 10-12, entrato alle 9, svolto 10-12: 2 h + meta' di 1 h = 2 h 30
    ritardo = nc.giorno_da_griglia('2', minuti_programmati=180, nota_tipo='ritardo')
    assert ritardo['campi']['minuti_riconosciuti'] == 150 and ritardo['campi']['causale'] == 'alunno_parziale'
    uscita = nc.giorno_da_griglia('1', minuti_programmati=180, nota_tipo='uscita_anticipata')
    assert uscita['campi']['minuti_riconosciuti'] == 120
    assert nc.giorno_da_griglia('2', minuti_programmati=180, nota_tipo='ritardo', recuperata=True)[
        'campi']['minuti_riconosciuti'] == 120
    assert nc.giorno_da_griglia('2', nota_tipo='ritardo')['esito'] == 'servono_programmati'
    # assemblea 10-13 su 10-14: 3; cineforum 8-11 su 10-14: 3 (REGOLE 2)
    assert nc.giorno_da_griglia('3', minuti_programmati=240, nota_tipo='evento')['campi']['minuti_riconosciuti'] == 180
    assert nc.giorno_da_griglia('3', minuti_programmati=240, nota_tipo='attivita_esterna')[
        'campi']['minuti_riconosciuti'] == 180
    # alunno assente + lectio brevis: vince l'evento, 0; assemblea senza ore svolte: 0
    assente_evento = nc.giorno_da_griglia('A', minuti_programmati=120, nota_tipo='evento')
    assert assente_evento['campi']['minuti_riconosciuti'] == 0 and assente_evento['campi']['causale'] == 'evento'
    assert nc.giorno_da_griglia('', nota_tipo='evento')['campi']['minuti_riconosciuti'] == 0
    # ferie senza sostituto: 0
    assert nc.giorno_da_griglia('F', minuti_programmati=240)['campi']['minuti_riconosciuti'] == 0


@pytest.mark.parametrize('argomenti, codice', [
    (dict(testo='X'), 'sigla_sconosciuta'),
    (dict(testo='13'), 'ore_giorno_oltre_12'),
    (dict(testo='A', minuti_programmati=120, nota_tipo='ritardo'), 'assente_e_parziale'),
    (dict(testo='F', minuti_programmati=120, nota_tipo='ritardo'), 'operatore_e_parziale'),
    (dict(testo='2', recuperata=True), 'recupero_senza_assenza'),
    (dict(testo='2', nota_tipo='boh'), 'nota_sconosciuta'),
    (dict(testo='4', minuti_programmati=180, nota_tipo='ritardo'), 'svolte_oltre_il_programmato'),
    (dict(testo='A', minuti_programmati=800), 'programmati_non_validi'),
])
def test_giorno_da_griglia_errori(argomenti, codice):
    esito = nc.giorno_da_griglia(**argomenti)
    assert (esito['esito'], esito['codice']) == ('errore', codice)


def test_valori_ambigui_e_vuoto():
    esito = nc.giorno_da_griglia('1,30')
    assert esito['esito'] == 'da_confermare'
    assert {a['lettura']: a['minuti'] for a in esito['lettura']['alternative']} == {'ore_e_minuti': 90,
                                                                                    'decimale': 78}
    assert nc.giorno_da_griglia('1,30', conferma='ore_e_minuti')['campi']['minuti_riconosciuti'] == 90
    assert nc.giorno_da_griglia('1,30', conferma='decimale')['campi']['minuti_riconosciuti'] == 78
    assert nc.giorno_da_griglia('')['esito'] == 'vuoto' and nc.giorno_da_griglia('  ')['esito'] == 'vuoto'


def test_testi_delle_caselle_e_dei_totali():
    assert [nc.testo_ore_cella(m) for m in (0, 45, 90, 120, 600, 80, 78)] == [
        '0', '0,75', '1,5', '2', '10', '1:20', '1:18']
    assert [nc.ore_brevi(m) for m in (0, 750, 80, 90, -90, 3240)] == ['0', '12,5', '1,33', '1,5', '-1,5', '54']
    # ogni testo di una casella si rilegge uguale (niente "1,33" da confermare)
    for m in range(0, 721, 7):
        assert nc.leggi_ore_griglia(nc.testo_ore_cella(m))['minuti'] == m


def test_minuti_previsti_dalla_programmazione_o_dal_pei():
    giorni = _ottobre_di_servizio()                       # 27 giorni, lunedi'-sabato
    assert len(giorni) == 27
    # PEI 12 h ripartito su 6 giorni: 2 h al giorno
    assert nc.minuti_previsti(giorni, (), 12) == {'minuti': 27 * 120, 'fonte': 'pei', 'stima': True}
    # PEI che cambia il 15: 10 h fino al 14, 13 h dopo
    pei = [{'ore_settimanali': 10, 'valido_da': '2026-09-01', 'valido_a': '2026-10-14'},
           {'ore_settimanali': 13, 'valido_da': '2026-10-15', 'valido_a': None}]
    prima = sum(1 for g in giorni if g.day <= 14)
    attese = int((nc.decimale(600 * prima + 780 * (27 - prima)) / 6).quantize(nc.UNO, rounding='ROUND_HALF_UP'))
    assert nc.minuti_previsti(giorni, (), pei)['minuti'] == attese
    # programmazione: lunedi' 8-10 e 12-14, mercoledi' 10-13
    orari = [{'giorno': 0, 'ora_inizio': '08:00', 'ora_fine': '10:00', 'valido_da': None, 'valido_a': None},
             {'giorno': 0, 'ora_inizio': '12:00', 'ora_fine': '14:00', 'valido_da': None, 'valido_a': None},
             {'giorno': 2, 'ora_inizio': '10:00', 'ora_fine': '13:00', 'valido_da': None, 'valido_a': None}]
    lunedi = sum(1 for g in giorni if g.weekday() == 0)
    mercoledi = sum(1 for g in giorni if g.weekday() == 2)
    assert nc.minuti_previsti(giorni, orari, 12) == {'minuti': 240 * lunedi + 180 * mercoledi,
                                                     'fonte': 'programmazione', 'stima': False}
    assert nc.minuti_previsti(giorni, (), None) == {'minuti': None, 'fonte': None, 'stima': False}
    assert nc.minuti_previsti([], (), 12)['minuti'] == 0
    assert nc.credito_debito(3240, 660) == 2580 and nc.credito_debito(100, 160) == -60
    assert nc.credito_debito(None, 10) is None


# ==================== la griglia del mese ====================

def test_griglia_del_mese_senza_ore(napoli):
    g = _griglia(napoli)
    giorni = _ottobre_di_servizio()
    assert g['giorni'] == [d.isoformat() for d in giorni]
    assert not any(datetime.date.fromisoformat(d).weekday() == 6 for d in g['giorni'])     # niente domeniche
    verifiche = [c for c in g['colonne'] if c['tipo'] == 'verifica']
    assert [c['settimana'] for c in verifiche] == [1, 2, 3, 4, 5]
    assert [c['tipo'] for c in g['colonne']] == [t for t, _ in nc.colonne_mese(2026, 10)]
    assert (g['chiuso'], g['finito'], g['testo']) == (False, True, 'Ottobre 2026')
    assert {r['id'] for r in g['righe']} == {napoli.titolare, napoli.sostituto, napoli.bruno, napoli.ciro}
    alba = _riga(g, napoli.titolare)
    assert alba['previste'] == nc.minuti_previsti(giorni, (), 12)['minuti'] == 3240
    assert (alba['fonte'], alba['stima'], alba['erogate'], alba['credito_debito']) == ('pei', True, 0, 3240)
    assert alba['pei'] == '12' and alba['sostituto'] is False and alba['grado'] == 'inferiore'
    sostituto = _riga(g, napoli.sostituto)
    assert sostituto['sostituto'] and sostituto['cd_nel_titolare'] == napoli.titolare
    # i giorni fuori dalle date del sostituto (prima del 5 e dopo il 9) sono bloccati
    fuori = {g['giorni'][i] for i in sostituto['fuori']}
    assert '2026-10-02' in fuori and '2026-10-12' in fuori and '2026-10-05' not in fuori
    ciro = _riga(g, napoli.ciro)
    assert ciro['previste'] is None and ciro['credito_debito'] is None and 'pei_mancante' in ciro['avvisi']
    # mese finito e nessuna ora: da controllare
    assert 'coppia_senza_ore' in alba['avvisi']
    assert {s['id'] for s in g['filtri']['scuole']} == set(napoli.scuole)
    assert g['filtri']['gradi'] == ['inferiore', 'superiore'] and g['filtri']['municipalita'] == [1, 2]


def test_caselle_totali_verifica_e_credito_coincidono_con_napoli_calcoli(napoli):
    t, s = napoli.titolare, napoli.sostituto
    scritte = [
        (t, '2026-10-01', dict(testo='2')), (t, '2026-10-02', dict(testo='1,5')), (t, '2026-10-03', dict(testo='1:30')),
        (t, '2026-10-05', dict(testo='F')), (s, '2026-10-05', dict(testo='2')),
        (t, '2026-10-06', dict(testo='A', programmati='3')),
        (t, '2026-10-07', dict(testo='1,30', conferma='ore_e_minuti')),
        (t, '2026-10-08', dict(testo='2', programmati='3', nota_tipo='ritardo', nota_ora='9:00')),
        (t, '2026-10-09', dict(testo='3', programmati='4', nota_tipo='evento', nota='assemblea di istituto')),
        (t, '2026-10-12', dict(testo='M')), (t, '2026-10-13', dict(testo='P')),
        (t, '2026-10-14', dict(testo='A', recuperata=True)),
        (t, '2026-10-15', dict(testo='2,5')), (t, '2026-10-16', dict(testo='4')), (t, '2026-10-17', dict(testo='4')),
        (t, '2026-10-19', dict(testo='5')),
    ]
    esito = _ok(_salva(napoli, *[_cella(c, d, **campi) for c, d, campi in scritte]))
    assert [e['esito'] for e in esito['celle']] == ['salvata'] * len(scritte), esito['celle']
    assert esito['salvate'] == len(scritte)
    # le stesse ore calcolate senza il database
    attese = {}
    for c, d, campi in scritte:
        p = campi.get('programmati')
        nota = campi.get('nota_tipo')
        calcolo = nc.giorno_da_griglia(campi['testo'], campi.get('conferma'),
                                       nc.leggi_ore_griglia(p)['minuti'] if p else None, nota,
                                       campi.get('recuperata', False))
        attese[(c, d)] = calcolo['campi']['minuti_riconosciuti']
    assert attese[(t, '2026-10-06')] == 90 and attese[(t, '2026-10-08')] == 150 and attese[(t, '2026-10-14')] == 0
    salvate = {(p['coppia_id'], p['data']): p for p in _righe_db(napoli.percorso, 'SELECT * FROM napoli_presenze')}
    assert {k: p['minuti_riconosciuti'] for k, p in salvate.items()} == attese
    assert all(p['origine'] == 'griglia' and p['stato'] == 'registrato' for p in salvate.values())
    assert salvate[(t, '2026-10-08')]['nota_tipo'] == 'ritardo' and salvate[(t, '2026-10-08')]['nota_ora'] == '09:00'

    g = _griglia(napoli)              # "ricaricando la pagina i totali coincidono al minuto"
    giorni = g['giorni']
    for (c, d), minuti in attese.items():
        assert _riga(g, c)['celle'][str(giorni.index(d))]['r'] == minuti, (c, d)
    alba, sost = _riga(g, t), _riga(g, s)
    assert alba['totale'] == sum(m for (c, _), m in attese.items() if c == t)
    assert sost['totale'] == 120
    # VERIFICA: per alunno e figura (titolare + sostituto), con i colori del PEI (12 h, tetto 14 h)
    minuti_gruppo = {}
    for (c, d), m in attese.items():
        minuti_gruppo[d] = minuti_gruppo.get(d, 0) + m
    attesa = [v for v in nc.verifica_settimane(minuti_gruppo, 2026, 10, [{'ore_settimanali': 12,
                                                                         'valido_da': '2026-09-01', 'valido_a': None}])
              if v['settimana'] is not None]
    assert [(v['n'], v['gruppo'], v['colore']) for v in alba['settimane']] == [
        (v['settimana'], v['minuti'], v['colore']) for v in attesa]
    assert [v['minuti'] for v in alba['settimane']] == [
        sum(m for (c, d), m in attese.items() if c == t and v['dal'] <= datetime.date.fromisoformat(d) <= v['al'])
        for v in attesa]
    # settimana 2: titolare 1,5 + 1,5 + 2,5 + 3 piu' il sostituto 2 = 10,5 h, sotto il PEI di 12 h
    assert [(v['n'], v['minuti'], v['gruppo'], v['colore']) for v in alba['settimane'][:3]] == [
        (1, 300, 300, None), (2, 510, 630, None), (3, 630, 630, None)]
    assert [v['minuti'] for v in sost['settimane'][:2]] == [0, 120]
    # credito/debito: previste dal PEI ripartito - (ore del titolare + ore del sostituto)
    previste = nc.minuti_previsti(_ottobre_di_servizio(), (), 12)['minuti']
    assert alba['erogate'] == alba['totale'] + sost['totale']
    assert alba['credito_debito'] == nc.credito_debito(previste, alba['erogate'])
    assert alba['cd_testo'] == nc.ore_brevi(alba['credito_debito']) and sost['credito_debito'] is None
    # le caselle: testo, angolo con le riconosciute, nota, sigle
    celle = alba['celle']
    i = giorni.index
    assert celle[str(i('2026-10-06'))] == dict(celle[str(i('2026-10-06'))], k='A', t='A', c='1,5', r=90, p=180)
    assert celle[str(i('2026-10-08'))]['c'] == '2,5' and celle[str(i('2026-10-08'))]['nt'] == 'ritardo'
    assert celle[str(i('2026-10-09'))]['nx'] == 'assemblea di istituto'
    assert [celle[str(i(d))]['t'] for d in ('2026-10-05', '2026-10-12', '2026-10-13')] == ['F', 'M', 'P']
    assert celle[str(i('2026-10-07'))]['t'] == '1,5' and celle[str(i('2026-10-03'))]['t'] == '1,5'
    assert celle[str(i('2026-10-14'))]['rec'] is True
    assert 'ore_giorno_oltre_5' not in celle[str(i('2026-10-19'))].get('a', [])


def test_colori_della_verifica_giallo_e_rosso(napoli):
    b = napoli.bruno            # PEI 10 h: tetto 12 h (10 x 1,2)
    settimana_2 = ['2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08', '2026-10-09']
    settimana_3 = ['2026-10-12', '2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16']
    _ok(_salva(napoli, *[_cella(b, d, testo='2,25') for d in settimana_2]))      # 11,25 h: oltre il PEI
    _ok(_salva(napoli, *[_cella(b, d, testo='2,75') for d in settimana_3]))      # 13,75 h: oltre il tetto
    _ok(_salva(napoli, _cella(b, '2026-10-19', testo='5,5')))                      # piu' di 5 ore in un giorno
    g = _griglia(napoli)
    riga = _riga(g, b)
    colori = {v['n']: (v['minuti'], v['colore']) for v in riga['settimane']}
    assert colori[2] == (675, 'giallo') and colori[3] == (825, 'rosso') and colori[1] == (0, None)
    assert {'settimana_oltre_pei', 'settimana_oltre_pei_piu_20', 'ore_giorno_oltre_5'} <= set(riga['avvisi'])
    assert riga['celle'][str(g['giorni'].index('2026-10-19'))]['a'] == ['ore_giorno_oltre_5']
    assert all(codice in g['spiegazioni'] for codice in riga['avvisi'])


def test_casi_della_tabella_5_2_dalla_griglia(napoli):
    c = napoli.bruno
    casi = [
        ('2026-10-01', dict(testo='A', programmati='3'), 90),                    # 10-13 assente: 1,5
        ('2026-10-02', dict(testo='A', programmati='4'), 120),                   # 10-14 assente: 2
        ('2026-10-03', dict(testo='A', programmati='2'), 60),                    # 12-14 assente: 1
        ('2026-10-05', dict(testo='2', programmati='3', nota_tipo='ritardo', nota_ora='09:00'), 150),
        ('2026-10-06', dict(testo='3', programmati='4', nota_tipo='evento'), 180),            # assemblea 10-13
        ('2026-10-07', dict(testo='3', programmati='4', nota_tipo='attivita_esterna'), 180),  # cineforum 8-11
        ('2026-10-08', dict(testo='A', programmati='2', nota_tipo='evento'), 0),              # lectio brevis
        ('2026-10-09', dict(testo='F', programmati='4'), 0),                                  # ferie
        ('2026-10-10', dict(testo='0', nota_tipo='evento'), 0),                               # nulla svolto
    ]
    esito = _ok(_salva(napoli, *[_cella(c, d, **campi) for d, campi, _ in casi]))
    assert [e.get('minuti') for e in esito['celle']] == [m for *_, m in casi]
    riga = _riga(_griglia(napoli), c)
    assert riga['totale'] == sum(m for *_, m in casi) == 780


def test_1_30_chiede_conferma_e_non_scrive_niente(napoli):
    esito = _ok(_salva(napoli, _cella(napoli.bruno, '2026-10-01', testo='1,30')))
    cella = esito['celle'][0]
    assert cella['esito'] == 'da_confermare' and esito['salvate'] == 0
    assert {a['lettura']: a['minuti'] for a in cella['alternative']} == {'ore_e_minuti': 90, 'decimale': 78}
    assert '1 h 30 min' in cella['domanda']
    assert _righe_db(napoli.percorso, 'SELECT * FROM napoli_presenze') == []
    assert _ok(_salva(napoli, _cella(napoli.bruno, '2026-10-01', testo='1,30', conferma='decimale')))[
        'celle'][0]['minuti'] == 78
    assert _ok(_salva(napoli, _cella(napoli.bruno, '2026-10-01', testo='1,30', conferma='ore_e_minuti')))[
        'celle'][0]['minuti'] == 90
    assert _ok(_salva(napoli, _cella(napoli.bruno, '2026-10-02', testo='1,30', conferma='boh')))['celle'][0][
        'esito'] == 'errore'


def test_A_chiede_le_ore_programmate_se_mancano(napoli):
    esito = _ok(_salva(napoli, _cella(napoli.bruno, '2026-10-01', testo='A')))
    assert esito['celle'][0]['esito'] == 'servono_programmati' and esito['salvate'] == 0
    assert _righe_db(napoli.percorso, 'SELECT * FROM napoli_presenze') == []
    bad = _ok(_salva(napoli, _cella(napoli.bruno, '2026-10-01', testo='A', programmati='1,30')))['celle'][0]
    assert bad['esito'] == 'errore' and 'due modi' in bad['messaggio']
    assert _ok(_salva(napoli, _cella(napoli.bruno, '2026-10-01', testo='A', programmati='3')))['celle'][0][
        'minuti'] == 90
    # con la programmazione settimanale il programmato si legge da li' (giovedi' 10-13)
    _scrivi(napoli.percorso, "INSERT INTO napoli_orari (coppia_id, giorno, ora_inizio, ora_fine, data_inserimento) "
                             "VALUES (?, 3, '10:00', '13:00', '2026-09-01')", (napoli.bruno,))
    esito = _ok(_salva(napoli, _cella(napoli.bruno, '2026-10-08', testo='A')))
    assert esito['celle'][0]['esito'] == 'salvata' and esito['celle'][0]['minuti'] == 90
    # e le previste vengono dalla programmazione: 3 h ogni giovedi', niente stima
    riga = _riga(_griglia(napoli), napoli.bruno)
    giovedi = sum(1 for g in _ottobre_di_servizio() if g.weekday() == 3)
    assert (riga['previste'], riga['fonte'], riga['stima']) == (180 * giovedi, 'programmazione', False)
    # gia' saputo il programmato del giorno, cambiare la nota non lo richiede
    esito = _ok(_salva(napoli, _cella(napoli.bruno, '2026-10-01', nota_tipo='evento')))
    assert esito['celle'][0]['minuti'] == 0           # alunno assente + evento: vince l'evento


def test_vuoto_cancella_e_nota_da_sola(napoli):
    c = napoli.bruno
    _ok(_salva(napoli, _cella(c, '2026-10-01', testo='2')))
    esito = _ok(_salva(napoli, _cella(c, '2026-10-01', testo='')))
    assert esito['celle'][0]['esito'] == 'cancellata'
    assert _righe_db(napoli.percorso, 'SELECT * FROM napoli_presenze') == []
    assert _ok(_salva(napoli, _cella(c, '2026-10-01', testo='')))['celle'][0]['esito'] == 'invariata'
    # una nota su una casella vuota: giorno registrato con 0 ore svolte
    esito = _ok(_salva(napoli, _cella(c, '2026-10-02', nota_tipo='evento', nota='sciopero')))
    assert esito['celle'][0]['esito'] == 'salvata'
    p = _righe_db(napoli.percorso, 'SELECT * FROM napoli_presenze')[0]
    assert (p['minuti_svolti'], p['minuti_riconosciuti'], p['causale'], p['nota']) == (0, 0, 'evento', 'sciopero')
    # stesso valore: nessun cambiamento
    assert _ok(_salva(napoli, _cella(c, '2026-10-02', testo='0')))['celle'][0]['esito'] == 'invariata'
    # la descrizione senza ore e senza tipo non basta
    msg = _ok(_salva(napoli, _cella(c, '2026-10-03', nota='solo testo')))['celle'][0]
    assert msg['esito'] == 'errore'
    # ritardo senza orario
    msg = _ok(_salva(napoli, _cella(c, '2026-10-05', testo='2', programmati='3', nota_tipo='ritardo')))['celle'][0]
    assert msg['esito'] == 'errore' and msg['campo'] == 'nota_ora'
    msg = _ok(_salva(napoli, _cella(c, '2026-10-05', testo='2', programmati='3', nota_tipo='ritardo',
                                    nota_ora='25:00')))['celle'][0]
    assert msg['esito'] == 'errore'


def test_casella_svuotata_cancella_anche_la_nota_del_giorno(napoli):
    """Vuoto = il giorno si cancella, anche con la nota del giorno (la pagina e il README lo
    dicono); Ctrl+Z lo rimette con il tipo della nota ma senza la descrizione libera."""
    c = napoli.bruno
    _ok(_salva(napoli, _cella(c, '2026-10-01', testo='3', nota_tipo='evento', nota='assemblea di istituto')))
    esito = _ok(_salva(napoli, _cella(c, '2026-10-01', testo='')))['celle'][0]
    assert esito == dict(esito, esito='cancellata', tolta_nota=True, tolta_descrizione=True), esito
    assert _righe_db(napoli.percorso, 'SELECT * FROM napoli_presenze') == []
    assert '0' not in json.dumps(_riga(_griglia(napoli), c)['celle'])
    _ok(napoli.post('/api/napoli/annulla', json={}))
    p = _righe_db(napoli.percorso, 'SELECT * FROM napoli_presenze')[0]
    assert (p['minuti_riconosciuti'], p['nota_tipo'], p['causale'], p['nota']) == (180, 'evento', 'evento', None)
    # solo il tipo della nota, senza descrizione: Ctrl+Z la rimette tutta
    esito = _ok(_salva(napoli, _cella(c, '2026-10-01', testo='')))['celle'][0]
    assert (esito['tolta_nota'], esito['tolta_descrizione']) == (True, False)
    # un giorno senza nota: niente da dire
    _ok(_salva(napoli, _cella(c, '2026-10-02', testo='2')))
    esito = _ok(_salva(napoli, _cella(c, '2026-10-02', testo='')))['celle'][0]
    assert (esito['tolta_nota'], esito['tolta_descrizione']) == (False, False)
    # la nota scritta dalla sua finestra su una casella vuota resta un giorno con 0 ore
    esito = _ok(_salva(napoli, _cella(c, '2026-10-05', testo='', nota_tipo='evento', nota='sciopero')))['celle'][0]
    assert esito['esito'] == 'salvata' and esito['minuti'] == 0
    # la casella mostra «0»: togliendo la nota dalla sua finestra resta lo 0 scritto, svuotandola si cancella
    assert _riga(_griglia(napoli), c)['celle'][str(nc.giorni_mese(2026, 10).index(datetime.date(2026, 10, 5)))]['t'] == '0'
    esito = _ok(_salva(napoli, _cella(c, '2026-10-05', nota_tipo='', nota='')))['celle'][0]
    assert esito['esito'] == 'salvata' and esito['minuti'] == 0
    assert _ok(_salva(napoli, _cella(c, '2026-10-05', testo='')))['celle'][0]['esito'] == 'cancellata'
    assert _righe_db(napoli.percorso, "SELECT * FROM napoli_presenze WHERE data = '2026-10-05'") == []


def test_ore_in_un_giorno_di_chiusura_contano_con_l_avviso(napoli):
    """Scelta dichiarata (PROGETTO 5.5, README, ARCHITETTURA): le ore scritte a mano in un giorno
    di chiusura del calendario contano (come ore svolte) con l'avviso arancione; il giorno chiuso
    non entra nelle previste del credito/debito. La causale 'calendario' (0 ore, 5.2) vale per i
    giorni preparati dalla programmazione, che nei giorni chiusi non si preparano."""
    _scrivi(napoli.percorso, "INSERT INTO napoli_calendario (lotto_id, data, tipo, descrizione) VALUES "
                             "(?, '2026-10-02', 'chiusura', 'chiusura della scuola')", (napoli.lotto_id,))
    c = napoli.bruno
    prima = _riga(_griglia(napoli), c)
    esito = _ok(_salva(napoli, _cella(c, '2026-10-02', testo='3')))['celle'][0]
    assert esito['esito'] == 'salvata' and esito['minuti'] == 180
    g = _griglia(napoli)
    colonna = next(x for x in g['colonne'] if x.get('data') == '2026-10-02')
    riga = _riga(g, c)
    assert colonna['chiuso'] == 'chiusura della scuola'
    assert riga['totale'] == 180 and 'ore_in_giorno_di_chiusura' in riga['avvisi']
    assert 'contano lo stesso' in g['spiegazioni']['ore_in_giorno_di_chiusura']
    assert riga['previste'] == prima['previste'] and riga['credito_debito'] == prima['previste'] - 180


def test_due_titolari_senza_quota_della_coppia_hanno_l_avviso(napoli):
    """Due titolari della stessa figura per lo stesso alunno negli stessi giorni, con le previste
    dal PEI intero: la riga lo segnala (le previste si sommerebbero due volte)."""
    altro = _ok(napoli.post('/api/napoli/operatori', json={'cognome': 'Operatore', 'nome': 'Terzo',
                                                           'figura': 'ASACOM'}))['operatore_id']
    alba = _riga(_griglia(napoli), napoli.titolare)['alunno_id']
    doppia = _ok(napoli.post(f'{napoli.url}/coppie', json={'alunno_id': alba, 'operatore_id': altro,
                                                          'valido_da': '2026-10-01'}))['coppia_id']
    g = _griglia(napoli)
    for coppia in (napoli.titolare, doppia):
        riga = _riga(g, coppia)
        assert 'pei_su_piu_titolari' in riga['avvisi'] and riga['fonte'] == 'pei', riga['avvisi']
    assert 'pei_su_piu_titolari' in g['spiegazioni']
    assert 'pei_su_piu_titolari' not in _riga(g, napoli.sostituto)['avvisi']
    assert 'pei_su_piu_titolari' not in _riga(g, napoli.bruno)['avvisi']
    # dopo un salvataggio le righe ricalcolate lo hanno ancora
    righe = {r['id']: r for r in _ok(_salva(napoli, _cella(doppia, '2026-10-01', testo='2')))['righe']}
    assert 'pei_su_piu_titolari' in righe[napoli.titolare]['avvisi']
    # con le ore della coppia (quota) le previste non sono piu' il PEI intero: niente avviso
    _scrivi(napoli.percorso, 'UPDATE napoli_coppie SET ore_settimanali = 6 WHERE id = ?', (doppia,))
    g = _griglia(napoli)
    assert 'pei_su_piu_titolari' not in _riga(g, napoli.titolare)['avvisi']
    assert 'pei_su_piu_titolari' not in _riga(g, doppia)['avvisi']


@pytest.mark.parametrize('cella, parola', [
    (dict(data='2026-11-06', testo='2'), 'non è di ottobre'),
    (dict(data='2026-10-04', testo='2'), 'non è un giorno di servizio'),      # domenica
    (dict(data='2026-10-01', testo='X'), 'non è un numero di ore'),
    (dict(data='2026-10-01', testo='13'), 'Più di 12 ore'),
    (dict(data='2026-10-01', testo='2' * 30), 'troppo lungo'),
])
def test_caselle_rifiutate_con_un_messaggio(napoli, cella, parola):
    esito = _ok(_salva(napoli, dict(cella, coppia_id=napoli.bruno)))
    assert esito['celle'][0]['esito'] == 'errore' and parola in esito['celle'][0]['messaggio'], esito
    assert esito['salvate'] == 0


def test_giorni_futuri_e_fuori_dalle_date(napoli):
    futuro = _ok(_salva(napoli, _cella(napoli.bruno, '2026-11-06', testo='2'), mese=11))['celle'][0]
    assert futuro['esito'] == 'errore' and futuro['codice'] == 'GIORNO_FUTURO'
    oggi = _ok(_salva(napoli, _cella(napoli.bruno, '2026-11-05', testo='2'), mese=11))['celle'][0]
    assert oggi['esito'] == 'salvata'
    fuori = _ok(_salva(napoli, _cella(napoli.sostituto, '2026-10-12', testo='2')))['celle'][0]
    assert fuori['esito'] == 'errore' and fuori['codice'] == 'FUORI_DALLE_DATE'
    altro = _ok(_salva(napoli, _cella(99999, '2026-10-01', testo='2')))['celle'][0]
    assert altro['esito'] == 'errore'
    g = _griglia(napoli, 2026, 11)
    colonne = {c['data']: c for c in g['colonne'] if c['tipo'] == 'giorno'}
    assert colonne['2026-11-05']['futuro'] is False and colonne['2026-11-06']['futuro'] is True
    assert g['finito'] is False


def test_richieste_sbagliate(napoli):
    _errore(napoli.post(f'{napoli.url}/presenze', json={'anno': 2026, 'mese': 13, 'celle': []}), 400, campo='mese')
    _errore(napoli.post(f'{napoli.url}/presenze', json={'anno': 2026, 'mese': 10, 'celle': []}), 400, campo='celle')
    _errore(napoli.post(f'{napoli.url}/presenze', json={'anno': 2026, 'mese': 10, 'celle': ['x']}), 400)
    _errore(_salva(napoli, _cella(napoli.bruno, '2026-10-01', testo='2'), _cella(napoli.bruno, '2026-10-01',
                                                                                 testo='3')), 400)
    _errore(_salva(napoli, _cella(napoli.bruno, '2026-02-30', testo='2')), 400)
    _errore(napoli.get(f'{napoli.url}/presenze?anno=2026&mese=x'), 400)
    _errore(napoli.get('/api/napoli/lotti/999/presenze?anno=2026&mese=10'), 404)
    troppe = [_cella(napoli.bruno, '2026-10-01', testo='2')] * 2001
    _errore(_salva(napoli, *troppe), 400, campo='celle')


# ==================== mese chiuso, chiusura e riapertura ====================

def test_mese_chiuso_rifiuta_scritture_e_ctrl_z(napoli, db_mod):
    _ok(_salva(napoli, _cella(napoli.bruno, '2026-10-01', testo='2')))
    # novembre non e' finito: non si chiude
    _errore(napoli.post(f'{napoli.url}/mesi/chiudi', json={'anno': 2026, 'mese': 11}), 400, 'MESE_NON_FINITO')
    esito = _ok(napoli.post(f'{napoli.url}/mesi/chiudi', json={'anno': 2026, 'mese': 10, 'nota': 'fatturato'}))
    assert 'chiuso' in esito['messaggio']
    _errore(napoli.post(f'{napoli.url}/mesi/chiudi', json={'anno': 2026, 'mese': 10}), 409, 'MESE_GIA_CHIUSO')
    g = _griglia(napoli)
    assert g['chiuso'] and g['chiusura']['nota'] == 'fatturato'
    _errore(_salva(napoli, _cella(napoli.bruno, '2026-10-02', testo='2')), 409, 'MESE_CHIUSO_LOTTO')
    # Ctrl+Z: l'ultima azione e' la chiusura, che non si annulla con Ctrl+Z (si riapre con il motivo)
    ultima = _ok(napoli.get('/api/napoli/annulla/ultima'))
    assert ultima['non_annullabile'] and 'Riapri il mese' in ultima['non_annullabile']['motivo']
    _errore(napoli.post('/api/napoli/annulla', json={}), 400, 'NON_ANNULLABILE')
    # il mese chiuso di Roma (lo stesso ottobre) non c'entra: e' un'altra chiusura
    assert _ok(napoli.get('/api/mese-chiuso/2026/10'))['chiuso'] is False
    # riapertura: il motivo e' obbligatorio e resta nel registro
    _errore(napoli.post(f'{napoli.url}/mesi/riapri', json={'anno': 2026, 'mese': 10}), 400, campo='motivo')
    _errore(napoli.post(f'{napoli.url}/mesi/riapri', json={'anno': 2026, 'mese': 10, 'motivo': 'ok'}), 400)
    _ok(napoli.post(f'{napoli.url}/mesi/riapri', json={'anno': 2026, 'mese': 10, 'motivo': 'correzione di prova'}))
    _errore(napoli.post(f'{napoli.url}/mesi/riapri', json={'anno': 2026, 'mese': 10, 'motivo': 'di nuovo'}), 409,
            'MESE_NON_CHIUSO')
    registro = [r['dettagli'] for r in _righe_db(napoli.percorso, "SELECT dettagli FROM audit_log WHERE entita = "
                                                                  "'napoli_mese' ORDER BY id")]
    assert registro[-1].endswith('Motivo: correzione di prova') and 'chiuso il mese di ottobre 2026' in registro[0]
    assert _ok(_salva(napoli, _cella(napoli.bruno, '2026-10-02', testo='2')))['salvate'] == 1


def test_mese_chiuso_di_roma_non_blocca_napoli(napoli):
    _ok(napoli.post('/api/mese-chiuso/2026/10'))
    assert _ok(_salva(napoli, _cella(napoli.bruno, '2026-10-01', testo='2')))['salvate'] == 1
    assert _griglia(napoli)['chiuso'] is False
    _ok(napoli.delete('/api/mese-chiuso/2026/10'))


def test_ctrl_z_su_un_mese_chiuso_nel_frattempo(napoli):
    _ok(_salva(napoli, _cella(napoli.bruno, '2026-10-01', testo='2')))
    _scrivi(napoli.percorso, "INSERT INTO napoli_mesi_chiusi (lotto_id, anno, mese, data_chiusura) VALUES "
                             "(?, 2026, 10, '2026-11-05T10:00:00')", (napoli.lotto_id,))
    _errore(napoli.post('/api/napoli/annulla', json={}), 409, 'MESE_CHIUSO_LOTTO')
    assert len(_righe_db(napoli.percorso, 'SELECT * FROM napoli_presenze')) == 1


# ==================== Ctrl+Z ====================

def test_ctrl_z_annulla_solo_l_ultima_azione_di_napoli(napoli):
    c = napoli.bruno
    _ok(_salva(napoli, _cella(c, '2026-10-01', testo='2'), _cella(c, '2026-10-02', testo='3')))
    _ok(_salva(napoli, _cella(c, '2026-10-01', testo='4'), _cella(c, '2026-10-05', testo='A', programmati='2')))
    ultima = _ok(napoli.get('/api/napoli/annulla/ultima'))['azione']
    assert ultima['descrizione'] == 'Griglia presenze di ottobre 2026: 2 caselle (1 scritta, 1 cambiata)'
    assert ultima['chi'] == 'Fittizio Bruno con Operatrice Seconda'           # letto adesso, mai salvato
    _ok(napoli.post('/api/napoli/annulla', json={'id': ultima['id']}))
    ore = {p['data']: p['minuti_riconosciuti'] for p in _righe_db(napoli.percorso, 'SELECT * FROM napoli_presenze')}
    assert ore == {'2026-10-01': 120, '2026-10-02': 180}
    # una casella cancellata torna con Ctrl+Z
    _ok(_salva(napoli, _cella(c, '2026-10-02', testo='')))
    _ok(napoli.post('/api/napoli/annulla', json={}))
    assert len(_righe_db(napoli.percorso, 'SELECT * FROM napoli_presenze')) == 2
    # caselle di due coppie: nessun nome nella conferma
    _ok(_salva(napoli, _cella(c, '2026-10-06', testo='1'), _cella(napoli.ciro, '2026-10-06', testo='1')))
    assert _ok(napoli.get('/api/napoli/annulla/ultima'))['azione']['chi'] == ''
    memoria = _righe_db(napoli.percorso, 'SELECT descrizione, dati FROM napoli_annullamenti')
    assert not any('Bruno' in m['descrizione'] or 'Bruno' in m['dati'] for m in memoria)


def test_ctrl_z_e_la_descrizione_libera_della_nota(napoli):
    c = napoli.bruno
    _ok(_salva(napoli, _cella(c, '2026-10-01', testo='2')))
    # la prima descrizione si annulla (prima non c'era niente da ricordare)
    _ok(_salva(napoli, _cella(c, '2026-10-01', nota_tipo='evento', nota='uscita anticipata della classe')))
    _ok(napoli.post('/api/napoli/annulla', json={}))
    p = _righe_db(napoli.percorso, 'SELECT * FROM napoli_presenze')[0]
    assert (p['nota'], p['nota_tipo'], p['causale']) == (None, None, None)
    # cambiare una descrizione che c'era: quella di prima non resta in memoria, Ctrl+Z non la rimette
    _ok(_salva(napoli, _cella(c, '2026-10-01', nota_tipo='evento', nota='prima descrizione')))
    _ok(_salva(napoli, _cella(c, '2026-10-01', nota='seconda descrizione')))
    ultima = _ok(napoli.get('/api/napoli/annulla/ultima'))
    assert ultima['non_annullabile'] and 'note di prima' in ultima['non_annullabile']['motivo']
    _errore(napoli.post('/api/napoli/annulla', json={}), 400, 'NON_ANNULLABILE')
    memoria = ' '.join(m['dati'] for m in _righe_db(napoli.percorso, 'SELECT dati FROM napoli_annullamenti'))
    assert 'prima descrizione' not in memoria and 'seconda descrizione' not in memoria


def test_ctrl_z_di_roma_non_annulla_napoli(napoli):
    roma_prima = _ok(napoli.get('/api/undo/ultima'))
    _ok(_salva(napoli, _cella(napoli.bruno, '2026-10-01', testo='2')))
    assert _ok(napoli.get('/api/undo/ultima')) == roma_prima, 'la griglia ha scritto nella memoria di Ctrl+Z di Roma'
    napoli.post('/api/undo', json={})                     # Ctrl+Z su una pagina di Roma
    assert len(_righe_db(napoli.percorso, 'SELECT * FROM napoli_presenze')) == 1


# ==================== dettaglio, privacy, pagina ====================

def test_dettaglio_della_coppia_nel_mese(napoli):
    t = napoli.titolare
    _ok(_salva(napoli, _cella(t, '2026-10-06', testo='A', programmati='3'),
               _cella(t, '2026-10-08', testo='2', programmati='3', nota_tipo='ritardo', nota_ora='9:00'),
               _cella(napoli.sostituto, '2026-10-05', testo='2')))
    d = _ok(napoli.get(f'{napoli.url}/presenze/coppie/{t}?anno=2026&mese=10'))
    spiegazioni = {g['data']: g['spiegazione'] for g in d['giorni']}
    assert spiegazioni['2026-10-06'] == 'Alunno assente: metà delle 3:00 programmate = 1:30 (1,50)'
    assert spiegazioni['2026-10-08'].startswith('Alunno entrato in ritardo (alle 09:00): 2:00 svolte')
    assert spiegazioni['2026-10-08'].endswith('= 2:30 (2,50)')
    assert d['credito']['stima'] and d['credito']['erogate'] == 90 + 150 + 120
    assert d['credito']['giorni_servizio'] == 27 and [s['operatore'] for s in d['sostituti']] == ['Sostituta Nona']
    s = _ok(napoli.get(f'{napoli.url}/presenze/coppie/{napoli.sostituto}?anno=2026&mese=10'))
    assert s['credito']['nel_titolare']['id'] == t
    _errore(napoli.get(f'{napoli.url}/presenze/coppie/99999?anno=2026&mese=10'), 404)


def test_privacy_codici_fiscali_e_registro(napoli, db_mod):
    cf = seme_napoli._cf('Esempio', 'Alba', 2016, 5, 2, 'F')
    _ok(_salva(napoli, _cella(napoli.bruno, '2026-10-01', testo='2', nota_tipo='evento', nota=f'cf {cf}')))
    p = _righe_db(napoli.percorso, 'SELECT nota FROM napoli_presenze')[0]
    assert cf not in p['nota'] and '•' in p['nota']
    registro = [r['dettagli'] for r in _righe_db(napoli.percorso, "SELECT dettagli FROM audit_log WHERE entita = "
                                                                  "'napoli_presenze'")]
    assert registro and not any('Bruno' in r or 'Fittizio' in r or cf in r for r in registro)
    assert 'NAPOLI LOTTO 1' in registro[0] and '1 casella' in registro[0]
    g = json.dumps(_griglia(napoli))
    assert cf not in g


def test_pagina_presenze(napoli):
    r = napoli.get('/napoli/presenze')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'NapoliPresenze.avvia()' in html and 'id="presenze-griglia"' in html
    assert 'href="/napoli/presenze"' in _ok_testo(napoli.get('/napoli'))


def _ok_testo(r):
    assert r.status_code == 200
    return r.get_data(as_text=True)


# ==================== prestazioni ====================

def _lotto_grande(percorso, lotto_id, n=330):
    """n coppie inventate con un PEI e le ore di tutti i giorni di ottobre 2026 (scritte
    direttamente, come farebbe un mese intero di griglia)."""
    conn = sqlite3.connect(percorso)
    ora = '2026-09-01T08:00:00'
    try:
        with conn:
            scuole = [conn.execute('INSERT INTO napoli_scuole (lotto_id, nome, codice_meccanografico, grado, '
                                   'municipalita, data_inserimento) VALUES (?, ?, ?, ?, ?, ?)',
                                   (lotto_id, f'IC Grande {k:02d}', f'NAIC9ZZ{k:03d}', 'inferiore', 1 + k % 2,
                                    ora)).lastrowid for k in range(30)]
            operatori = [conn.execute('INSERT INTO napoli_operatori (cognome, nome, figura, data_inserimento) '
                                      'VALUES (?, ?, ?, ?)', (f'Grande{k:03d}', 'Prova', 'ASACOM', ora)).lastrowid
                         for k in range(150)]
            for k in range(n):
                cf = seme_napoli.codice_fiscale_inventato(f'Grande{k:03d}', 'Alunno',
                                                          datetime.date(2013, 1 + k % 12, 1 + (k // 12) % 28), 'F')
                alunno = conn.execute('INSERT INTO napoli_alunni (lotto_id, cognome, nome, codice_fiscale, scuola_id, '
                                      'data_inserimento) VALUES (?, ?, ?, ?, ?, ?)',
                                      (lotto_id, f'Grande{k:03d}', 'Alunno', cf, scuole[k % 30], ora)).lastrowid
                conn.execute('INSERT INTO napoli_pei (alunno_id, figura, ore_settimanali, valido_da, data_inserimento) '
                             "VALUES (?, 'ASACOM', 10, '2026-09-01', ?)", (alunno, ora))
                coppia = conn.execute('INSERT INTO napoli_coppie (lotto_id, alunno_id, operatore_id, scuola_id, figura, '
                                      "valido_da, data_inserimento) VALUES (?, ?, ?, ?, 'ASACOM', '2026-09-01', ?)",
                                      (lotto_id, alunno, operatori[k % 150], scuole[k % 30], ora)).lastrowid
                conn.executemany('INSERT INTO napoli_presenze (coppia_id, lotto_id, data, figura, stato, '
                                 'minuti_programmati, minuti_svolti, minuti_riconosciuti, origine, modificato_il) VALUES '
                                 "(?, ?, ?, 'ASACOM', 'registrato', 0, ?, ?, 'griglia', ?)",
                                 [(coppia, lotto_id, g.isoformat(), 90 + 30 * (g.day % 3), 90 + 30 * (g.day % 3), ora)
                                  for g in nc.giorni_mese(2026, 10)])
    finally:
        conn.close()


def test_un_incolla_grande_parte_a_gruppi_accettati_dal_server(napoli):
    """La pagina manda al massimo NAPOLI_PRESENZE_GRUPPO caselle per richiesta: e' il limite del
    server (MAX_CELLE), e un gruppo pieno si salva in una volta (un incolla da Excel di 100 righe
    per 27 giorni = 2.700 caselle parte in due richieste)."""
    import napoli_presenze
    js = (Path(__file__).resolve().parent.parent / 'static' / 'js' / 'napoli.js').read_text(encoding='utf-8')
    gruppo = int(re.search(r'const NAPOLI_PRESENZE_GRUPPO = (\d+);', js).group(1))
    assert gruppo == napoli_presenze.MAX_CELLE == 2000
    _lotto_grande(napoli.percorso, napoli.lotto_id, n=80)
    g = _griglia(napoli)
    grandi = [r for r in g['righe'] if r['alunno'].startswith('Grande')]
    celle = [_cella(r['id'], d, testo='2') for r in grandi for d in g['giorni']][:gruppo]
    assert len(celle) == gruppo
    inizio = time.perf_counter()
    esito = _ok(_salva(napoli, *celle))
    assert all(e['esito'] in ('salvata', 'invariata') for e in esito['celle'])
    assert time.perf_counter() - inizio < 5.0
    _errore(_salva(napoli, *(celle + [_cella(napoli.bruno, '2026-10-01', testo='2')])), 400, campo='celle')


def test_330_coppie_si_caricano_in_meno_di_2_secondi(napoli):
    _lotto_grande(napoli.percorso, napoli.lotto_id)
    inizio = time.perf_counter()
    g = _griglia(napoli)
    durata = time.perf_counter() - inizio
    assert len(g['righe']) == 330 + 4
    assert durata < 2.0, f'griglia di 330 coppie in {durata:.2f} s'
    riga = next(r for r in g['righe'] if r['alunno'].startswith('Grande000'))
    assert len(riga['celle']) == 27 and riga['totale'] == sum(90 + 30 * (d.day % 3) for d in nc.giorni_mese(2026, 10))
    # un salvataggio nel lotto grande resta veloce
    inizio = time.perf_counter()
    _ok(_salva(napoli, _cella(riga['id'], '2026-10-01', testo='2')))
    assert time.perf_counter() - inizio < 2.0

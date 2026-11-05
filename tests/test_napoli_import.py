"""Sezione Napoli, passi 1.4-1.5: import del foglio presenze mensile (master).

Sul master inventato (tests/napoli_sintetico.py, 41 righe, 1.554 ore):
- anteprima senza scritture: totali attesi per figura dalle celle dei giorni (la
  VERIFICA non conta), avvisi per codice, ore da confermare ("1,30"), grado proposto
  dal codice meccanografico, la stessa scuola in due municipalita' = due plessi da
  confermare, la municipalita' mancante di una scuola con piu' plessi da scegliere (mai un
  plesso senza municipalita' in piu'), le coppie di un plesso senza municipalita' che
  passano al plesso del file; un file di un mese precedente all'ultimo caricamento da
  confermare;
- conferma: stesso file (sha256) e stessi dati dell'anteprima, copia di sicurezza,
  un'unica transazione; coppie titolari e sostituti, subentro, PEI, fogli, giorni
  registrati con calcolo 'manuale' e origine 'import_excel';
- reimport dello stesso mese: lo stesso file non cambia nulla; un file diverso cambia
  solo le ore importate, quelle scritte a mano restano (salvo "sovrascrivi");
- annulla import (anche con Ctrl+Z): lo stato torna quello di prima; solo l'ultimo;
- solo confronto: differenze senza scrivere; mese chiuso -> 409; errori del file con
  messaggi semplici; Roma non cambia (alunni omonimi di utenti di Roma).

Ogni test lavora su un database vuoto (database_isolato). Solo dati inventati.
"""
import datetime
import io
import json
import os
import sqlite3
import zipfile

import openpyxl
import pytest

import config
import import_napoli
import napoli_calcoli as calc
import napoli_sintetico as ns
import seme_napoli
from strumenti import fotografa_roma

MARZO = datetime.date(2026, 3, 1)
TABELLE_REGISTRO = ('napoli_import', 'napoli_annullamenti')   # cambiano con ogni azione, anche annullata


@pytest.fixture
def napoli(database_isolato, app_module, db_mod):
    """Client autenticato sul database vuoto del test, con NAPOLI LOTTO 1 (procedura guidata)."""
    client = fotografa_roma.client_fotografia(app_module.app, db_mod)
    proposta = _ok(client.get('/api/napoli/lotti/proposta'))
    lotto = _ok(client.post('/api/napoli/lotti/procedura', json={
        'lotto': dict(proposta['lotto'], municipalita='1 e 2', cig='ZZ00000000'), 'tariffe': proposta['tariffe'],
        'valido_da': proposta['valido_da'], 'valido_a': proposta['valido_a']}))['lotto']
    client.lotto_id = lotto['id']
    client.percorso = database_isolato
    return client


@pytest.fixture
def master(tmp_path):
    """Il master inventato (bytes) e i valori attesi."""
    return ns.leggi_bytes(str(tmp_path / 'master'))


def variante(tmp_path, modifica, nome='variante.xlsx', omonimi=False):
    return ns.leggi_bytes(str(tmp_path / nome.replace('.', '_')), omonimi, nome, modifica)[0]


def _ok(r):
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _errore(r, stato, codice=None):
    assert r.status_code == stato, r.get_data(as_text=True)
    dati = r.get_json()
    assert dati['error'] and (codice is None or dati['code'] == codice), dati
    return dati


def anteprima(client, dati, scelte=None, modo='import', nome='master_marzo.xlsx', lotto_id=None):
    return client.post('/api/napoli/import/anteprima', content_type='multipart/form-data', data={
        'file': (io.BytesIO(dati), nome), 'lotto_id': str(lotto_id or client.lotto_id), 'modo': modo,
        'scelte': json.dumps(scelte or {})})


def conferma(client, dati, a, scelte=None, nome='master_marzo.xlsx', sha=None, versione=None, modo=None):
    """La conferma dell'anteprima `a`, nello stesso modo dell'anteprima (salvo `modo`)."""
    return client.post('/api/napoli/import/conferma', content_type='multipart/form-data', data={
        'file': (io.BytesIO(dati), nome), 'lotto_id': str(client.lotto_id), 'sha256': sha or a['file']['sha256'],
        'versione_dati': versione or a['versione_dati'], 'scelte': json.dumps(scelte or {}),
        'modo': modo or a['modo']})


def con_ore_scelte(client, dati, scelte=None, lettura='ore_e_minuti'):
    """(anteprima, scelte) con le ore da confermare scelte (nel master inventato "1,30" e'
    1 h 30 min, come nei valori attesi), salvo quelle gia' scelte o ricordate."""
    scelte = dict(scelte or {})
    a = _ok(anteprima(client, dati, scelte))
    if a['ore_ambigue_da_scegliere']:
        scelte['ore_ambigue'] = dict(scelte.get('ore_ambigue') or {})
        for x in a['ore_ambigue']:
            scelte['ore_ambigue'].setdefault(x['chiave'], x['scelta'] or lettura)
        a = _ok(anteprima(client, dati, scelte))
    return a, scelte


def importa(client, dati, scelte=None):
    """Anteprima e conferma con le proposte, le ore da confermare scelte e le conferme richieste."""
    a, scelte = con_ore_scelte(client, dati, scelte)
    scelte = dict(scelte, conferme=a['conferme_richieste'])
    return a, _ok(conferma(client, dati, a, scelte))


def carica_anagrafica(client, dati, scelte=None):
    """Anteprima e conferma dell'anagrafica (l'azione principale), con le conferme richieste."""
    a = _ok(anteprima(client, dati, scelte, modo='anagrafica'))
    return a, _ok(conferma(client, dati, a, dict(scelte or {}, conferme=a['conferme_richieste'])))


def righe(percorso, sql, parametri=()):
    conn = sqlite3.connect(percorso)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, parametri)]
    finally:
        conn.close()


def esegui(percorso, sql, parametri=()):
    conn = sqlite3.connect(percorso)
    try:
        with conn:
            conn.execute(sql, parametri)
    finally:
        conn.close()


def impronta_dati(percorso):
    """Impronta delle tabelle di Napoli senza il registro degli import e di Ctrl+Z."""
    return {t: v for t, v in seme_napoli.impronta_napoli(percorso).items() if t not in TABELLE_REGISTRO}


def copie(percorso_backup=None):
    cartella = percorso_backup or config.BACKUP_FOLDER
    return sorted(os.listdir(cartella))


def cella(riga, giorno, valore):
    """Variante con una cella diversa: riga del foglio (dalla 2), giorno di marzo, valore."""
    def modifica(r):
        r[riga - 2]['giorni'][datetime.date(2026, 3, giorno)] = valore
    return modifica


def minuti_presenze(percorso):
    return righe(percorso, 'SELECT COALESCE(SUM(minuti_riconosciuti), 0) AS m, COUNT(*) AS n FROM napoli_presenze')[0]


# ==================== anteprima ====================

def test_anteprima_del_sintetico_ha_i_totali_attesi_e_non_scrive(napoli, master):
    dati, atteso = master
    prima, backup_prima = seme_napoli.impronta_napoli(napoli.percorso), copie()
    a = _ok(anteprima(napoli, dati))
    # "1,30" non e' ancora scelto: finche' non si sceglie conta in decimale (1,30 ore = 78 minuti)
    assert a['ore_ambigue_da_scegliere'] == 1 and a['totale']['minuti'] == atteso['totale_minuti'] - 12
    a, _scelte = con_ore_scelte(napoli, dati)
    assert seme_napoli.impronta_napoli(napoli.percorso) == prima, "l'anteprima ha scritto nel database"
    assert copie() == backup_prima
    c = a['conteggi']
    assert (c['righe'], c['operatori'], c['alunni']) == (atteso['righe'], atteso['operatori'], atteso['alunni'])
    assert a['totale']['minuti'] == atteso['totale_minuti'] == 1554 * 60
    assert a['totale']['ore'] == '1.554,00'
    per_figura = {x['figura']: x for x in a['ore_per_figura']}
    for figura, valori in atteso['per_figura'].items():
        assert per_figura[figura]['minuti'] == valori['minuti'], figura
        assert per_figura[figura]['righe'] == valori['righe'], figura
    assert {f: x['minuti'] / 60 for f, x in per_figura.items()} == {
        'ASACOM': 858, 'EDUCATORE': 554.5, 'PSICOLOGO': 92.5, 'TIFLOLOGO': 49}
    assert c['sigle'] == atteso['sigle']
    assert a['bloccanti'] == [] and a['puo_importare'] and not a['nessun_cambiamento']
    assert a['reimport'] is None and a['file']['mese_testo'] == 'marzo 2026'
    assert c['nuovi']['alunni'] == 34 and c['nuovi']['operatori'] == 22 and c['nuovi']['coppie'] == 41
    assert a['segnalazioni']['celle_colorate'] == atteso['celle_colorate']


def test_le_ore_si_contano_dai_giorni_non_dalla_verifica(master):
    dati, atteso = master
    lettura = import_napoli.leggi_master(dati, 'master.xlsx')
    # la riga 10 ha "1,30": finche' non si sceglie conta in decimale (78 minuti invece di 90)
    attesi = list(atteso['minuti_per_riga'])
    attesi[10 - 2] -= 12
    assert [r['minuti'] for r in lettura['righe']] == attesi
    [ambigua] = [c for r in lettura['righe'] for c in r['celle'].values() if c['esito'] == 'da_confermare']
    assert ambigua['testo'] == '1,30' and ambigua['minuti'] == 78 and 'proposta' not in ambigua
    codici = {a['codice'] for a in lettura['anomalie']}
    # VERIFICA scritta a mano e VERIFICA che non somma i numeri scritti come testo: le ore restano quelle dei giorni
    assert {'verifica_senza_formula', 'verifica_esclude_numeri_come_testo', 'verifica_diversa_dalla_somma',
            'numero_come_testo'} <= codici
    assert lettura['colonne']['scuola'] == 'L'          # intestazione "2"
    assert [len(s) for s in lettura['settimane']] == [6, 6, 6, 6, 2]
    r = next(x for x in lettura['righe'] if x['riga'] == atteso['separazione_cognome_nome']['riga'])
    assert (r['operatore']['cognome'], r['operatore']['nome'], r['operatore']['separazione']) == (
        'DE PROVA', 'DELTA', 'cf')


def test_avvisi_del_sintetico_per_codice(napoli, master):
    dati, _atteso = master
    a = _ok(anteprima(napoli, dati))
    codici = {g['codice']: g for g in a['avvisi'] + a['note']}
    for codice in ('intestazione_scuola_errata', 'numero_come_testo', 'sigla_scritta_in_variante',
                   'data_inizio_scritta_male', 'data_inizio_anno_errato', 'data_inizio_futura_con_ore',
                   'riga_senza_attivita', 'cf_operatore_controllo', 'cf_operatore_formato',
                   'operatore_stesso_cf_nomi_diversi', 'alunno_stesso_cf_nomi_diversi', 'lotto_mancante',
                   'municipalita_mancante', 'municipalita_presa_dalla_scuola', 'sostituzione_mancante',
                   'scuola_codice_sospetto', 'scuola_senza_codice', 'assenza_operatore_parziale',
                   'ore_giorno_oltre_5', 'settimana_oltre_pei', 'settimana_oltre_pei_piu_20',
                   'riepilogo_non_allineato'):
        assert codice in codici, codice
    g = codici['ore_giorno_oltre_5']
    assert g['livello'] == 'avviso' and g['titolo'] and g['righe'][0]['riga'] and g['righe'][0]['colonna']
    assert codici['numero_come_testo']['livello'] == 'nota'


def test_ore_da_confermare_scelta_obbligatoria(napoli, master):
    """"1,30": nessuna lettura gia' scelta (nel master le ore sono decimali, ma sul foglio
    firma "1,30" e' 1 h 30 min): senza la scelta non si importa."""
    dati, atteso = master
    a = _ok(anteprima(napoli, dati))
    [x] = a['ore_ambigue']
    assert (x['testo'], x['scelta'], x['ricordata']) == ('1,30', None, False) and 'proposta' not in x
    assert {alt['lettura']: alt['minuti'] for alt in x['alternative']} == {'ore_e_minuti': 90, 'decimale': 78}
    assert a['ore_ambigue_da_scegliere'] == 1 and a['puo_importare']
    e = _errore(conferma(napoli, dati, a, {'conferme': a['conferme_richieste']}), 400, 'DA_CONFERMARE')
    assert e['mancano'] == ['ore_ambigue'] and 'Ore da confermare' in e['error']
    assert righe(napoli.percorso, 'SELECT COUNT(*) AS n FROM napoli_import')[0]['n'] == 0
    b = _ok(anteprima(napoli, dati, {'ore_ambigue': {x['chiave']: 'decimale'}}))
    assert b['totale']['minuti'] == atteso['totale_minuti'] - 12 and b['ore_ambigue_da_scegliere'] == 0
    assert b['ore_ambigue'][0]['scelta'] == 'decimale'
    _errore(anteprima(napoli, dati, {'ore_ambigue': {x['chiave']: 'forse'}}), 400, 'SCELTE_NON_VALIDE')
    # importato con "1 h 30 min": reimportando lo stesso file la scelta di prima si ricorda
    importa(napoli, dati)
    c = _ok(anteprima(napoli, dati))
    assert (c['ore_ambigue'][0]['scelta'], c['ore_ambigue'][0]['ricordata']) == ('ore_e_minuti', True)
    assert c['ore_ambigue_da_scegliere'] == 0 and c['nessun_cambiamento']


def test_grado_proposto_dal_codice_meccanografico(napoli, master):
    dati, _atteso = master
    a = _ok(anteprima(napoli, dati))
    gradi = {s['codice']: s['grado_proposto'] for s in a['scuole_nuove']}
    assert gradi == {'NAIC8ZZ001': 'inferiore', 'NA1C8ZZ002': '', 'NAIS0ZZ003': 'superiore',
                     'NAPC0ZZ004': 'superiore', 'NAVC0ZZ005': '', '': ''}
    assert calc.grado_da_codice_meccanografico('NA1E000001') == 'inferiore'      # paritaria
    assert calc.grado_da_codice_meccanografico('NATD000001') == 'superiore'
    per_grado = {x['figura']: x['per_grado'] for x in a['ore_per_figura']}
    assert per_grado['TIFLOLOGO'] == {'inferiore': 0, 'superiore': 49 * 60, 'da_decidere': 0}
    # il grado scelto per una scuola sposta le sue ore
    convitto = next(s for s in a['scuole_nuove'] if s['codice'] == 'NAVC0ZZ005')
    b = _ok(anteprima(napoli, dati, {'gradi': {convitto['chiave']: 'superiore'}}))
    assert sum(x['per_grado']['superiore'] for x in b['ore_per_figura']) > \
        sum(x['per_grado']['superiore'] for x in a['ore_per_figura'])
    importa(napoli, dati, {'gradi': {convitto['chiave']: 'superiore'}})
    scuole = {s['codice_meccanografico']: s['grado'] for s in righe(napoli.percorso, 'SELECT * FROM napoli_scuole')}
    assert scuole['NAVC0ZZ005'] == 'superiore' and scuole['NAIC8ZZ001'] == 'inferiore' and scuole['NA1C8ZZ002'] is None


def test_la_stessa_scuola_in_due_municipalita_sono_due_plessi_da_confermare(napoli, tmp_path):
    def due_municipalita(r):
        r[0]['municipalita'] = 1               # NAIC8ZZ001 anche in municipalita' 1 (nelle altre righe e' 2)
    dati = variante(tmp_path, due_municipalita)
    a, scelte = con_ore_scelte(napoli, dati)
    assert a['conferme_richieste'] == ['plessi', 'gradi']
    [conf] = a['conferme']
    testo = conf['voci'][0]['testo']
    assert 'NAIC8ZZ001' in testo and 'nel file municipalità 1 e 2' in testo and 'plessi' in testo
    assert conf['voci'][0]['righe'][0] == 2 and not conf['solo_avviso']
    _errore(conferma(napoli, dati, a, dict(scelte, conferme=['gradi'])), 400, 'DA_CONFERMARE')
    assert righe(napoli.percorso, 'SELECT COUNT(*) AS n FROM napoli_scuole')[0]['n'] == 0
    _ok(conferma(napoli, dati, a, dict(scelte, conferme=['plessi', 'gradi'])))
    plessi = righe(napoli.percorso, "SELECT municipalita FROM napoli_scuole WHERE codice_meccanografico = 'NAIC8ZZ001' "
                                    'ORDER BY municipalita')
    assert [p['municipalita'] for p in plessi] == [1, 2]


def test_municipalita_mancante_presa_dalla_scuola(napoli, master):
    dati, _atteso = master
    importa(napoli, dati)
    # riga 7 (DE PROVA DELTA con NOVIZIO ZETA, LICEO ZETA ETA senza municipalita'): il plesso e' quello
    # della municipalita' 1, come nelle altre righe della stessa scuola
    [c] = righe(napoli.percorso, "SELECT s.municipalita FROM napoli_coppie c JOIN napoli_operatori o ON o.id = c.operatore_id "
                                 "JOIN napoli_scuole s ON s.id = c.scuola_id JOIN napoli_alunni a ON a.id = c.alunno_id "
                                 "WHERE o.cognome = 'DE PROVA' AND a.cognome = 'NOVIZIO' AND a.nome = 'ZETA'")
    assert c['municipalita'] == 1


# ==================== anagrafica (l'azione principale, REGOLE 14) ====================

def test_anteprima_dell_anagrafica_senza_ore_e_senza_scritture(napoli, master):
    """Senza modo l'anteprima e' quella dell'anagrafica: alunni, operatori, scuole, coppie
    e PEI, nessun giorno, nessun foglio del mese, nessuna ora da confermare e nessun
    controllo sulle ore."""
    dati, atteso = master
    prima, backup_prima = seme_napoli.impronta_napoli(napoli.percorso), copie()
    r = napoli.post('/api/napoli/import/anteprima', content_type='multipart/form-data', data={
        'file': (io.BytesIO(dati), 'master_marzo.xlsx'), 'lotto_id': str(napoli.lotto_id), 'scelte': '{}'})
    a = _ok(r)
    assert seme_napoli.impronta_napoli(napoli.percorso) == prima and copie() == backup_prima
    assert a['modo'] == 'anagrafica' and a['reimport'] is None
    assert a['ore_ambigue'] == [] and a['ore_ambigue_da_scegliere'] == 0 and a['manuali_diverse'] == []
    c = a['conteggi']
    assert (c['righe'], c['operatori'], c['alunni']) == (atteso['righe'], atteso['operatori'], atteso['alunni'])
    assert {k: c['nuovi'][k] for k in ('scuole', 'alunni', 'operatori', 'coppie', 'pei', 'fogli')} == {
        'scuole': 6, 'alunni': 34, 'operatori': 22, 'coppie': 41, 'pei': 36, 'fogli': 0}
    assert not any(c['presenze'].values()) and c['minuti'] == 0 and a['totale_importato']['minuti'] == 0
    assert c['sigle'] == {} and not any(a['segnalazioni'].values())
    # niente controlli sulle ore (VERIFICA, piu' di 5 ore, settimane oltre il PEI...)
    tutti = {g['codice'] for g in a['bloccanti'] + a['avvisi'] + a['note']}
    assert not tutti & import_napoli.SOLO_ORE
    assert {'cf_operatore_formato', 'data_inizio_scritta_male', 'municipalita_presa_dalla_scuola'} <= tutti
    # coppie e PEI per figura e per grado (le ore restano a zero)
    per_figura = {x['figura']: x for x in a['ore_per_figura']}
    assert {f: x['righe'] for f, x in per_figura.items()} == {f: v['righe'] for f, v in atteso['per_figura'].items()}
    assert all(x['minuti'] == 0 for x in per_figura.values())
    assert per_figura['TIFLOLOGO']['righe_per_grado'] == {'inferiore': 0, 'superiore': per_figura['TIFLOLOGO']['righe'],
                                                          'da_decidere': 0}
    assert a['totale_tabella']['pei_ore'] == calc.numero_it(sum(calc.decimale(x['pei_ore'].replace(',', '.'))
                                                                for x in a['ore_per_figura']))
    assert a['conferme_richieste'] == ['gradi'] and not a['nessun_cambiamento']


def test_l_anagrafica_non_si_blocca_per_le_ore(napoli, tmp_path):
    """Una cella sbagliata blocca l'import delle ore, non l'anagrafica (le ore non si caricano)."""
    def problemi(r):
        r[7]['giorni'][datetime.date(2026, 3, 4)] = 'X'
        r[8]['giorni'][datetime.date(2026, 3, 6)] = 13
    dati = variante(tmp_path, problemi)
    assert {g['codice'] for g in _ok(anteprima(napoli, dati))['bloccanti']} == {'sigla_sconosciuta',
                                                                               'ore_giorno_oltre_12'}
    a, esito = carica_anagrafica(napoli, dati)
    assert a['bloccanti'] == [] and esito['import_id']
    assert righe(napoli.percorso, 'SELECT COUNT(*) AS n FROM napoli_presenze')[0]['n'] == 0


def test_caricare_l_anagrafica_scrive_solo_l_anagrafica(napoli, master, tmp_path):
    """La conferma dell'anagrafica: scuole, alunni, operatori (qualifica, ore di contratto),
    coppie con le stesse date dell'import delle ore e PEI; nessun giorno e nessun foglio.
    Ricaricare lo stesso file non cambia nulla; poi le ore dello stesso mese trovano tutto."""
    dati, _atteso = master
    backup_prima = copie()
    a, esito = carica_anagrafica(napoli, dati)
    assert esito['modo'] == 'anagrafica' and esito['copia'] and len(copie()) == len(backup_prima) + 1
    assert esito['messaggio'] == 'Anagrafica caricata dal file di marzo 2026: 41 righe'
    conteggi = {t: righe(napoli.percorso, f'SELECT COUNT(*) AS n FROM napoli_{t}')[0]['n']
                for t in ('scuole', 'alunni', 'operatori', 'coppie', 'fogli', 'pei', 'presenze')}
    assert conteggi == {'scuole': 6, 'alunni': 34, 'operatori': 22, 'coppie': 41, 'fogli': 0, 'pei': 36,
                        'presenze': 0}
    ore_contratto = {o['ore_contratto'] for o in righe(napoli.percorso, 'SELECT ore_contratto FROM napoli_operatori')}
    assert ore_contratto - {None}
    [imp] = righe(napoli.percorso, 'SELECT * FROM napoli_import')
    assert json.loads(imp['esito_json'])['modo'] == 'anagrafica'
    storico = _ok(napoli.get(f'/api/napoli/lotti/{napoli.lotto_id}/import'))
    assert storico[0]['modo'] == 'anagrafica' and storico[0]['ore'] == '' and storico[0]['annullabile']
    assert storico[0]['nuovi']['alunni'] == 34
    ultima = _ok(napoli.get('/api/napoli/annulla/ultima'))['azione']
    assert ultima['descrizione'].startswith('Anagrafica dal file di marzo 2026: 41 righe')
    coppie_anagrafica = {k: (c['valido_da'], c['valido_a'], c['scuola_id']) for k, c in
                         coppie_per_nome(napoli.percorso).items()}
    # lo stesso file di nuovo: niente da cambiare (senza conferme)
    b = _ok(anteprima(napoli, dati, modo='anagrafica'))
    assert b['nessun_cambiamento'] and b['reimport']['stesso_file'] and b['conferme_richieste'] == []
    r = _ok(conferma(napoli, dati, b))
    assert r['nessun_cambiamento'] and r['import_id'] is None
    # poi le ore dello stesso mese: l'anagrafica c'e' gia', si aggiungono giorni e fogli
    c, scelte = con_ore_scelte(napoli, dati)
    assert c['reimport'] is None and c['conferme_richieste'] == []
    assert not any(c['conteggi']['nuovi'][k] for k in ('scuole', 'alunni', 'operatori', 'coppie', 'pei'))
    assert c['conteggi']['presenze']['nuove'] == 681 and c['conteggi']['nuovi']['fogli'] == 40
    _ok(conferma(napoli, dati, c, scelte))
    assert {k: (x['valido_da'], x['valido_a'], x['scuola_id']) for k, x in
            coppie_per_nome(napoli.percorso).items()} == coppie_anagrafica


def test_le_coppie_dell_anagrafica_sono_quelle_dell_import_delle_ore(napoli, master):
    dati, _atteso = master
    _a, esito = carica_anagrafica(napoli, dati)
    anagrafica = {k: (c['valido_da'], c['valido_a']) for k, c in coppie_per_nome(napoli.percorso).items()}
    _ok(napoli.post(f'/api/napoli/import/{esito["import_id"]}/annulla', json={}))
    importa(napoli, dati)
    assert {k: (c['valido_da'], c['valido_a']) for k, c in coppie_per_nome(napoli.percorso).items()} == anagrafica


def test_annullare_l_anagrafica_ripristina_lo_stato_di_prima(napoli, master):
    dati, _atteso = master
    prima = impronta_dati(napoli.percorso)
    _a, esito = carica_anagrafica(napoli, dati)
    r = _ok(napoli.post(f'/api/napoli/import/{esito["import_id"]}/annulla', json={}))
    assert r['messaggio'].startswith('Annullato il caricamento dell\'anagrafica dal file di marzo 2026')
    assert impronta_dati(napoli.percorso) == prima
    # i messaggi parlano di «caricamento», come la pagina
    e = _errore(napoli.post(f'/api/napoli/import/{esito["import_id"]}/annulla', json={}), 409, 'IMPORT_GIA_ANNULLATO')
    assert e['error'] == 'Il caricamento è già stato annullato.'
    # anche con Ctrl+Z
    carica_anagrafica(napoli, dati)
    ultima = _ok(napoli.get('/api/napoli/annulla/ultima'))['azione']
    _ok(napoli.post('/api/napoli/annulla', json={'id': ultima['id']}))
    assert impronta_dati(napoli.percorso) == prima


def test_un_file_di_un_mese_precedente_all_ultimo_caricamento_va_confermato(napoli, master, tmp_path):
    """Il file di marzo dopo l'anagrafica di aprile aggiungerebbe le coppie di marzo e
    porterebbe indietro i PEI: si carica solo dopo aver spuntato «Ho controllato»."""
    dati, _atteso = master
    carica_anagrafica(napoli, aprile(tmp_path))
    for modo in ('anagrafica', 'import'):
        a = _ok(anteprima(napoli, dati, modo=modo))
        assert a['conferme_richieste'][0] == 'mese_precedente' and not a['nessun_cambiamento']
        conf = a['conferme'][0]
        assert conf['codice'] == 'mese_precedente' and conf['voci'] == [] and not conf['solo_avviso']
        assert conf['testo'].startswith('Questo file è di marzo 2026, ma il lotto ha già un caricamento di aprile 2026 '
                                        '(fatto il ')
    a = _ok(anteprima(napoli, dati, modo='anagrafica'))
    altre = [c for c in a['conferme_richieste'] if c != 'mese_precedente']
    e = _errore(conferma(napoli, dati, a, {'conferme': altre}), 400, 'DA_CONFERMARE')
    assert e['mancano'] == ['mese_precedente']
    _ok(conferma(napoli, dati, a, {'conferme': a['conferme_richieste']}))
    # aprile di nuovo (il mese piu' recente): niente da confermare per il mese
    assert 'mese_precedente' not in _ok(anteprima(napoli, aprile(tmp_path), modo='anagrafica'))['conferme_richieste']


def test_la_conferma_vale_solo_nel_modo_dell_anteprima(napoli, master):
    """Dopo l'anteprima dell'anagrafica non si importano le ore (e viceversa): l'anteprima
    va rifatta. Il solo confronto non salva."""
    dati, _atteso = master
    a = _ok(anteprima(napoli, dati, modo='anagrafica'))
    scelte = {'conferme': a['conferme_richieste']}
    _errore(conferma(napoli, dati, a, scelte, modo='ore'), 409, 'ANTEPRIMA_SUPERATA')
    _errore(conferma(napoli, dati, a, scelte, modo='confronto'), 400, 'MODO_NON_VALIDO')
    _errore(conferma(napoli, dati, a, scelte, modo='tutto'), 400, 'MODO_NON_VALIDO')
    b, scelte_ore = con_ore_scelte(napoli, dati)
    _errore(conferma(napoli, dati, b, dict(scelte_ore, conferme=b['conferme_richieste']), modo='anagrafica'), 409,
            'ANTEPRIMA_SUPERATA')
    assert righe(napoli.percorso, 'SELECT COUNT(*) AS n FROM napoli_import')[0]['n'] == 0


def test_il_grado_delle_scuole_nuove_va_confermato(napoli, master):
    """Il grado proposto dal codice meccanografico decide la fattura (REGOLE 9): si
    conferma con "Ho controllato i gradi", in tutti e due i modi."""
    dati, _atteso = master
    for modo in ('anagrafica', 'import'):
        a, scelte = con_ore_scelte(napoli, dati) if modo == 'import' else \
            (_ok(anteprima(napoli, dati, modo=modo)), {})
        assert a['conferme_richieste'] == ['gradi']
        paritarie = {s['codice']: s['paritaria'] for s in a['scuole_nuove']}
        assert paritarie['NA1C8ZZ002'] and not paritarie['NAIC8ZZ001']
        e = _errore(conferma(napoli, dati, a, scelte), 400, 'DA_CONFERMARE')
        assert e['mancano'] == ['gradi']
    assert righe(napoli.percorso, 'SELECT COUNT(*) AS n FROM napoli_scuole')[0]['n'] == 0


def test_senza_niente_da_cambiare_le_conferme_sono_solo_avvisi(napoli, master, tmp_path):
    """Reimport di marzo con I.C. ALFA scritta nella municipalita' 3: le coppie restano nel
    loro plesso e il file non cambia niente. La stessa scuola in due municipalita' si
    mostra come avviso, senza la casella "Ho controllato" (l'import non serve)."""
    dati, _atteso = master
    importa(napoli, dati)
    diverso = variante(tmp_path, municipalita_di('I.C. ALFA', 3))
    for modo in ('import', 'anagrafica'):
        a = _ok(anteprima(napoli, diverso, modo=modo))
        assert a['nessun_cambiamento'] and a['conferme_richieste'] == []
        [conf] = a['conferme']
        assert conf['codice'] == 'plessi' and conf['solo_avviso']
        r = _ok(conferma(napoli, diverso, a))
        assert r['nessun_cambiamento']


# ==================== conferma ====================

def test_conferma_scrive_tutto_in_una_volta_dopo_la_copia(napoli, master):
    dati, atteso = master
    backup_prima = copie()
    a, esito = importa(napoli, dati)
    assert esito['import_id'] and esito['copia'] and len(copie()) == len(backup_prima) + 1
    assert esito['messaggio'] == 'Importato marzo 2026: 41 righe, 1.554,00 ore'
    p = righe(napoli.percorso, 'SELECT * FROM napoli_presenze')
    assert sum(x['minuti_riconosciuti'] for x in p) == atteso['totale_minuti']
    assert {(x['stato'], x['calcolo'], x['origine'], x['import_id']) for x in p} == {
        ('registrato', 'manuale', 'import_excel', esito['import_id'])}
    sigle = [x for x in p if x['sigla']]
    assert len(sigle) == sum(atteso['sigle'].values())
    assert {x['causale'] for x in sigle} == {'operatore_ferie', 'operatore_malattia', 'operatore_permesso'}
    assert all(x['minuti_riconosciuti'] == 0 for x in sigle)
    assert all(x['testo_originale'] for x in p)
    conteggi = {t: righe(napoli.percorso, f'SELECT COUNT(*) AS n FROM napoli_{t}')[0]['n']
                for t in ('scuole', 'alunni', 'operatori', 'coppie', 'fogli', 'pei')}
    assert conteggi == {'scuole': 6, 'alunni': 34, 'operatori': 22, 'coppie': 41, 'fogli': 40, 'pei': 36}
    # la nota della riga va nel foglio del mese
    note = {f['note'] for f in righe(napoli.percorso, 'SELECT note FROM napoli_fogli')}
    assert 'Alunno assente: 11,17,18. Il giorno 2 il plesso è stato chiuso per lavori idraulici' in note
    # operatore con il codice fiscale sbagliato: salvato com'e', segnato come non valido
    assert {o['cf_valido'] for o in righe(napoli.percorso, "SELECT cf_valido FROM napoli_operatori "
                                                           "WHERE cognome = 'DI ESEMPIO'")} == {0}
    [imp] = righe(napoli.percorso, 'SELECT * FROM napoli_import')
    assert (imp['anno'], imp['mese'], imp['n_righe'], imp['annullato']) == (2026, 3, 41, 0)
    assert json.loads(imp['esito_json'])['minuti'] == atteso['totale_minuti']
    storico = _ok(napoli.get(f'/api/napoli/lotti/{napoli.lotto_id}/import'))
    assert storico[0]['annullabile'] and storico[0]['ore'] == '1.554,00' and storico[0]['righe'] == 41


def test_sostituti_titolari_e_subentro(napoli, master):
    dati, _atteso = master
    a, _esito = importa(napoli, dati)
    assert len(a['subentri']) == 2 and all(s['scelto'] for s in a['subentri'])
    coppie = righe(napoli.percorso, 'SELECT c.*, o.cognome AS operatore, a.cognome || \' \' || a.nome AS alunno '
                                    'FROM napoli_coppie c JOIN napoli_operatori o ON o.id = c.operatore_id '
                                    'JOIN napoli_alunni a ON a.id = c.alunno_id')
    per = {(c['operatore'], c['alunno']): c for c in coppie}
    titolare = per[('CAMPIONE', 'STUDENTE LAMBDA')]
    sostituto = per[('IPOTESI', 'STUDENTE LAMBDA')]
    assert titolare['ruolo'] == 'titolare' and titolare['valido_a'] == '2026-03-23'      # subentro dal 24
    assert sostituto['ruolo'] == 'sostituto' and sostituto['titolare_coppia_id'] == titolare['id']
    assert (sostituto['valido_da'], sostituto['valido_a']) == ('2026-03-24', '2026-03-31')
    # sostituto nei giorni di malattia della titolare: valido dal primo all'ultimo giorno con ore
    sost = per[('FORMATO', 'NOVIZIO ZETA')]
    assert (sost['valido_da'], sost['valido_a'], sost['ruolo']) == ('2026-03-16', '2026-03-19', 'sostituto')
    assert sost['titolare_coppia_id'] == per[('DE PROVA', 'NOVIZIO ZETA')]['id']
    # data di inizio corretta (O3/11/2025) e titolare aperta
    assert per[('FITTIZIO', 'STUDENTE DELTA')]['valido_da'] == '2025-11-03'
    assert per[('FITTIZIO', 'STUDENTE DELTA')]['valido_a'] is None
    # PEI della riga NO: alunno e figura, dal primo del mese
    pei = righe(napoli.percorso, 'SELECT p.* FROM napoli_pei p JOIN napoli_alunni a ON a.id = p.alunno_id '
                                 "WHERE a.cognome = 'STUDENTE' AND a.nome = 'LAMBDA'")
    assert [(p['figura'], p['ore_settimanali'], p['valido_da']) for p in pei] == [('EDUCATORE', 10.0, '2026-03-01')]


def test_qualifica_nuova_scelta_nell_anteprima(napoli, tmp_path):
    def qualifica(r):
        r[3]['qualifica'] = 'ASS. ALLA COMUNICAZIONE'
        r[5]['qualifica'] = 'OPERATORE SOCIALE'
    dati = variante(tmp_path, qualifica)
    a = _ok(anteprima(napoli, dati))
    q = {x['testo']: x for x in a['qualifiche']}
    # la figura proposta si mostra, ma non e' scelta: tutte e due le qualifiche bloccano finche' non si sceglie
    assert q['ASS. ALLA COMUNICAZIONE']['proposta'] == 'ASACOM' and q['OPERATORE SOCIALE']['proposta'] is None
    assert q['ASS. ALLA COMUNICAZIONE']['figura'] is None and q['OPERATORE SOCIALE']['figura'] is None
    [bloccante] = a['bloccanti']
    assert bloccante['codice'] == 'qualifica_non_collegata' and bloccante['n'] == 2
    assert a['conteggi']['nuovi']['qualifiche'] == 0
    _errore(conferma(napoli, dati, a), 400, 'IMPORT_BLOCCATO')
    b = _ok(anteprima(napoli, dati, {'qualifiche': {'OPERATORE SOCIALE': 'EDUCATORE'}}))
    assert [(g['codice'], g['n']) for g in b['bloccanti']] == [('qualifica_non_collegata', 1)]
    _a, esito = importa(napoli, dati, {'qualifiche': {'OPERATORE SOCIALE': 'EDUCATORE',
                                                      'ASS. ALLA COMUNICAZIONE': 'ASACOM'}})
    alias = {r['testo']: (r['figura'], r['origine']) for r in righe(napoli.percorso,
                                                                     'SELECT * FROM napoli_alias_qualifiche')}
    assert alias['OPERATORE SOCIALE'] == ('EDUCATORE', 'utente')
    assert alias['ASS. ALLA COMUNICAZIONE'] == ('ASACOM', 'utente')
    _ok(napoli.post(f'/api/napoli/import/{esito["import_id"]}/annulla', json={}))
    alias = {r['testo'] for r in righe(napoli.percorso, 'SELECT testo FROM napoli_alias_qualifiche')}
    assert 'OPERATORE SOCIALE' not in alias and 'ASS. ALLA COMUNICAZIONE' not in alias


def test_bloccanti_impediscono_l_import(napoli, tmp_path):
    def problemi(r):
        r[7]['giorni'][datetime.date(2026, 3, 4)] = 'X'         # scritta sconosciuta
        r[8]['giorni'][datetime.date(2026, 3, 6)] = 13          # 13 ore
        r[9]['lotto'] = 2                                       # riga di un altro lotto
        r[10]['cf_alunno'] = ''                                 # alunno senza codice fiscale
    dati = variante(tmp_path, problemi)
    a = _ok(anteprima(napoli, dati))
    assert {g['codice'] for g in a['bloccanti']} == {'sigla_sconosciuta', 'ore_giorno_oltre_12',
                                                     'riga_di_altro_lotto', 'cf_alunno_non_valido'}
    assert not a['puo_importare']
    assert {g['righe'][0]['riga'] for g in a['bloccanti']} == {9, 10, 11, 12}
    e = _errore(conferma(napoli, dati, a), 400, 'IMPORT_BLOCCATO')
    assert e['bloccanti']
    assert righe(napoli.percorso, 'SELECT COUNT(*) AS n FROM napoli_presenze')[0]['n'] == 0


def test_mese_chiuso_del_lotto(napoli, master, tmp_path):
    dati, _atteso = master
    _a, esito = importa(napoli, dati)
    esegui(napoli.percorso, 'INSERT INTO napoli_mesi_chiusi (lotto_id, anno, mese, data_chiusura) VALUES (?, 2026, 3, ?)',
           (napoli.lotto_id, '2026-04-05T10:00:00'))
    diverso = variante(tmp_path, cella(2, 2, 3))
    a = _ok(anteprima(napoli, diverso))
    assert a['mese_chiuso'] and [g['codice'] for g in a['bloccanti']] == ['mese_chiuso']
    _errore(conferma(napoli, diverso, a), 409, 'MESE_CHIUSO_LOTTO')
    _errore(napoli.post(f'/api/napoli/import/{esito["import_id"]}/annulla', json={}), 409, 'MESE_CHIUSO_LOTTO')
    assert not _ok(napoli.get(f'/api/napoli/lotti/{napoli.lotto_id}/import'))[0]['annullabile']


def test_file_cambiato_o_dati_cambiati_dopo_l_anteprima(napoli, master, tmp_path):
    dati, _atteso = master
    a = _ok(anteprima(napoli, dati))
    diverso = variante(tmp_path, cella(2, 2, 3))
    _errore(conferma(napoli, diverso, a), 409, 'FILE_CAMBIATO')
    _errore(conferma(napoli, dati, a, sha='0' * 64), 409, 'FILE_CAMBIATO')
    _ok(napoli.post('/api/napoli/qualifiche', json={'testo': 'ASSISTENTE DI PROVA', 'figura': 'ASACOM'}))
    _errore(conferma(napoli, dati, a), 409, 'ANTEPRIMA_SUPERATA')
    assert righe(napoli.percorso, 'SELECT COUNT(*) AS n FROM napoli_import')[0]['n'] == 0


def test_senza_copia_di_sicurezza_non_si_scrive(napoli, master, monkeypatch, db_mod):
    dati, _atteso = master
    a, scelte = con_ore_scelte(napoli, dati)
    prima = seme_napoli.impronta_napoli(napoli.percorso)
    monkeypatch.setattr(db_mod, 'create_backup', lambda *x, **k: None)
    e = _errore(conferma(napoli, dati, a, dict(scelte, conferme=a['conferme_richieste'])), 503, 'COPIA_NON_RIUSCITA')
    assert 'copia di sicurezza' in e['error']
    assert seme_napoli.impronta_napoli(napoli.percorso) == prima


# ==================== reimport, annulla, confronto ====================

def test_reimportare_lo_stesso_file_non_cambia_nulla(napoli, master):
    dati, _atteso = master
    importa(napoli, dati)
    prima, backup_prima = seme_napoli.impronta_napoli(napoli.percorso), copie()
    a = _ok(anteprima(napoli, dati))
    assert a['reimport']['stesso_file'] and a['nessun_cambiamento']
    assert a['conteggi']['presenze']['uguali'] == 681 and a['conteggi']['presenze']['nuove'] == 0
    assert not any(a['conteggi']['nuovi'].values()) and not any(a['conteggi']['aggiornati'].values())
    r = _ok(conferma(napoli, dati, a))
    assert r['nessun_cambiamento'] and r['import_id'] is None
    assert seme_napoli.impronta_napoli(napoli.percorso) == prima and copie() == backup_prima


def test_reimport_cambia_solo_le_ore_importate_e_annulla_ripristina(napoli, master, tmp_path):
    dati, atteso = master
    importa(napoli, dati)
    dopo_primo = seme_napoli.impronta_napoli(napoli.percorso)

    def due_celle(r):
        r[0]['giorni'][datetime.date(2026, 3, 3)] = 1          # era 2
        r[0]['giorni'][datetime.date(2026, 3, 4)] = None       # era 3: il giorno si toglie
    diverso = variante(tmp_path, due_celle)
    a = _ok(anteprima(napoli, diverso))
    p = a['conteggi']['presenze']
    assert (p['cambiate'], p['da_togliere'], p['nuove'], p['uguali']) == (1, 1, 0, 679)
    assert a['reimport'] and not a['reimport']['stesso_file']
    _a, esito = importa(napoli, diverso)
    assert minuti_presenze(napoli.percorso) == {'m': atteso['totale_minuti'] - 60 - 180, 'n': 680}
    assert righe(napoli.percorso, 'SELECT COUNT(*) AS n FROM napoli_import')[0]['n'] == 2
    # annullare il secondo import rimette il primo com'era
    r = _ok(napoli.post(f'/api/napoli/import/{esito["import_id"]}/annulla', json={}))
    assert 'Annullato' in r['messaggio']
    assert seme_napoli.impronta_napoli(napoli.percorso) != dopo_primo          # napoli_import: annullato = 1
    assert impronta_dati(napoli.percorso) == {t: v for t, v in dopo_primo.items() if t not in TABELLE_REGISTRO}
    assert minuti_presenze(napoli.percorso) == {'m': atteso['totale_minuti'], 'n': 681}


def test_solo_l_ultimo_import_si_annulla(napoli, master, tmp_path):
    dati, _atteso = master
    _a, primo = importa(napoli, dati)
    importa(napoli, variante(tmp_path, cella(2, 2, 3)))
    _errore(napoli.post(f'/api/napoli/import/{primo["import_id"]}/annulla', json={}), 409, 'IMPORT_NON_ULTIMO')
    _errore(napoli.post('/api/napoli/import/999/annulla', json={}), 404)


def test_annullare_l_import_ripristina_lo_stato_di_prima(napoli, master):
    dati, _atteso = master
    prima = impronta_dati(napoli.percorso)
    _a, esito = importa(napoli, dati)
    assert impronta_dati(napoli.percorso) != prima
    _ok(napoli.post(f'/api/napoli/import/{esito["import_id"]}/annulla', json={}))
    assert impronta_dati(napoli.percorso) == prima
    [imp] = righe(napoli.percorso, 'SELECT annullato FROM napoli_import')
    assert imp['annullato'] == 1
    assert not righe(napoli.percorso, "SELECT * FROM napoli_annullamenti WHERE tipo = 'import'")
    storico = _ok(napoli.get(f'/api/napoli/lotti/{napoli.lotto_id}/import'))
    assert storico[0]['annullato'] and not storico[0]['annullabile']
    _errore(napoli.post(f'/api/napoli/import/{esito["import_id"]}/annulla', json={}), 409, 'IMPORT_GIA_ANNULLATO')
    # dopo l'annullamento lo stesso file si importa di nuovo come la prima volta
    a = _ok(anteprima(napoli, dati))
    assert a['reimport'] is None and a['conteggi']['presenze']['nuove'] == 681


def test_ctrl_z_subito_dopo_annulla_l_import(napoli, master):
    dati, _atteso = master
    prima = impronta_dati(napoli.percorso)
    importa(napoli, dati)
    ultima = _ok(napoli.get('/api/napoli/annulla/ultima'))['azione']
    assert ultima['descrizione'].startswith('Import del foglio presenze di marzo 2026: 41 righe')
    _ok(napoli.post('/api/napoli/annulla', json={'id': ultima['id']}))
    assert impronta_dati(napoli.percorso) == prima
    # la memoria di Ctrl+Z torna alla creazione del lotto
    assert _ok(napoli.get('/api/napoli/annulla/ultima'))['azione']['descrizione'].startswith('Nuovo lotto')


def test_ore_scritte_a_mano_restano_se_non_si_sceglie_di_sostituirle(napoli, master):
    dati, atteso = master
    importa(napoli, dati)
    [p] = righe(napoli.percorso, "SELECT * FROM napoli_presenze WHERE data = '2026-03-03' ORDER BY id LIMIT 1")
    esegui(napoli.percorso, "UPDATE napoli_presenze SET origine = 'foglio', minuti_riconosciuti = 45, import_id = NULL "
                            'WHERE id = ?', (p['id'],))
    a = _ok(anteprima(napoli, dati))
    assert a['conteggi']['presenze']['manuali_diverse'] == 1 and len(a['manuali_diverse']) == 1
    m = a['manuali_diverse'][0]
    assert m['data'] == '2026-03-03' and m['assisto'] == '0:45 (0,75)' and m['alunno'] and m['operatore']
    assert a['nessun_cambiamento']           # se non si sceglie, il file non cambia niente
    # le ore per figura e per grado sono quelle che Assisto avra' dopo l'import: per il giorno
    # scritto a mano, che resta, contano le ore di Assisto
    dopo_l_import = atteso['totale_minuti'] - p['minuti_riconosciuti'] + 45
    assert a['totale_tabella']['minuti'] == sum(x['minuti'] for x in a['ore_per_figura']) == dopo_l_import
    assert a['totale_importato']['minuti'] == dopo_l_import and a['totale']['minuti'] == atteso['totale_minuti']
    b = _ok(anteprima(napoli, dati, {'sovrascrivi_manuali': True}))
    assert not b['nessun_cambiamento'] and b['conteggi']['presenze']['sovrascritte'] == 1
    assert b['totale_tabella']['minuti'] == atteso['totale_minuti']
    _a, esito = importa(napoli, dati, {'sovrascrivi_manuali': True})
    [dopo] = righe(napoli.percorso, 'SELECT * FROM napoli_presenze WHERE id = ?', (p['id'],))
    assert (dopo['minuti_riconosciuti'], dopo['origine']) == (p['minuti_riconosciuti'], 'import_excel')
    _ok(napoli.post(f'/api/napoli/import/{esito["import_id"]}/annulla', json={}))
    [ripristinata] = righe(napoli.percorso, 'SELECT * FROM napoli_presenze WHERE id = ?', (p['id'],))
    assert (ripristinata['minuti_riconosciuti'], ripristinata['origine']) == (45, 'foglio')


def test_ore_cambiate_a_mano_dopo_l_import_impediscono_di_annullarlo(napoli, master):
    dati, _atteso = master
    _a, esito = importa(napoli, dati)
    esegui(napoli.percorso, "UPDATE napoli_presenze SET origine = 'griglia' WHERE id = "
                            '(SELECT MIN(id) FROM napoli_presenze)')
    _errore(napoli.post(f'/api/napoli/import/{esito["import_id"]}/annulla', json={}), 409, 'IMPORT_CAMBIATO_DOPO')


def test_dati_dell_import_cambiati_a_mano_impediscono_di_annullarlo(napoli, master, tmp_path):
    """Annullare rimetterebbe i valori di prima sopra una modifica fatta a mano dopo
    l'import: non si annulla (come per le ore cambiate a mano)."""
    dati, _atteso = master
    importa(napoli, dati)
    _a, esito = importa(napoli, aprile(tmp_path))               # aprile: il sostituto continua (data di fine)
    chiave = ('FORMATO TAU', 'NOVIZIO ZETA', 'sostituto')
    coppia = coppie_per_nome(napoli.percorso)[chiave]
    assert coppia['valido_a'] == '2026-04-17'
    esegui(napoli.percorso, "UPDATE napoli_coppie SET valido_a = '2026-04-10' WHERE id = ?", (coppia['id'],))
    e = _errore(napoli.post(f'/api/napoli/import/{esito["import_id"]}/annulla', json={}), 409,
                'IMPORT_CAMBIATO_DOPO')
    assert 'un dato scritto dall\'import' in e['error']
    esegui(napoli.percorso, "UPDATE napoli_coppie SET valido_a = '2026-04-17' WHERE id = ?", (coppia['id'],))
    _ok(napoli.post(f'/api/napoli/import/{esito["import_id"]}/annulla', json={}))
    assert coppie_per_nome(napoli.percorso)[chiave]['valido_a'] == '2026-03-19'


def test_qualifica_dell_import_cambiata_nelle_impostazioni_impedisce_di_annullarlo(napoli, tmp_path):
    def qualifica(r):
        r[5]['qualifica'] = 'OPERATORE SOCIALE'
    dati = variante(tmp_path, qualifica)
    _a, esito = carica_anagrafica(napoli, dati, {'qualifiche': {'OPERATORE SOCIALE': 'EDUCATORE'}})
    _ok(napoli.put('/api/napoli/qualifiche', json={'testo': 'OPERATORE SOCIALE', 'figura': 'ASACOM'}))
    _errore(napoli.post(f'/api/napoli/import/{esito["import_id"]}/annulla', json={}), 409, 'IMPORT_CAMBIATO_DOPO')
    _ok(napoli.put('/api/napoli/qualifiche', json={'testo': 'OPERATORE SOCIALE', 'figura': 'EDUCATORE'}))
    _ok(napoli.post(f'/api/napoli/import/{esito["import_id"]}/annulla', json={}))
    assert not righe(napoli.percorso, "SELECT * FROM napoli_alias_qualifiche WHERE testo = 'OPERATORE SOCIALE'")


def test_la_nota_della_riga_si_salva_senza_codici_fiscali(napoli, master):
    """La colonna NOTE e' testo libero: un codice fiscale (anche gia' salvato, per esempio
    da una versione di prima) non arriva in chiaro nel registro per "Annulla import"."""
    dati, _atteso = master
    importa(napoli, dati)
    cf = 'RSSMRA80A01Z999X'
    [foglio] = righe(napoli.percorso, 'SELECT id FROM napoli_fogli ORDER BY id LIMIT 1')
    esegui(napoli.percorso, 'UPDATE napoli_fogli SET note = ? WHERE id = ?', (f'Assente, codice {cf}', foglio['id']))
    a, scelte = con_ore_scelte(napoli, dati)
    assert a['conteggi']['aggiornati']['fogli'] == 1
    esito = _ok(conferma(napoli, dati, a, dict(scelte, conferme=a['conferme_richieste'])))
    [imp] = righe(napoli.percorso, 'SELECT sostituite_json FROM napoli_import WHERE id = ?', (esito['import_id'],))
    assert cf not in imp['sostituite_json'] and calc.maschera_codice_fiscale(cf) in imp['sostituite_json']
    _ok(napoli.post(f'/api/napoli/import/{esito["import_id"]}/annulla', json={}))
    [nota] = righe(napoli.percorso, 'SELECT note FROM napoli_fogli WHERE id = ?', (foglio['id'],))
    assert nota['note'] == f'Assente, codice {calc.maschera_codice_fiscale(cf)}'


def test_solo_confronto_non_scrive_e_mostra_le_differenze(napoli, master):
    dati, _atteso = master
    prima = seme_napoli.impronta_napoli(napoli.percorso)
    a = _ok(anteprima(napoli, dati, modo='confronto'))
    assert len(a['confronto']['righe_non_in_assisto']) == 41 and a['confronto']['coppie_uguali'] == 0
    assert seme_napoli.impronta_napoli(napoli.percorso) == prima
    importa(napoli, dati)
    esegui(napoli.percorso, "UPDATE napoli_presenze SET minuti_riconosciuti = 15, origine = 'foglio' WHERE id = "
                            "(SELECT MIN(id) FROM napoli_presenze WHERE data = '2026-03-03')")
    dopo = seme_napoli.impronta_napoli(napoli.percorso)
    c = _ok(anteprima(napoli, dati, modo='confronto'))['confronto']
    assert seme_napoli.impronta_napoli(napoli.percorso) == dopo
    assert c['coppie_uguali'] == 40 and len(c['differenze']) == 1 and not c['righe_non_in_assisto']
    [g] = c['differenze'][0]['giorni']
    assert g['data'] == '2026-03-03' and g['assisto'] == '0:15 (0,25)'
    _errore(anteprima(napoli, dati, modo='scrivi'), 400)


def test_operatore_riconosciuto_dal_nome_va_confermato(napoli, master, tmp_path):
    dati, _atteso = master
    importa(napoli, dati)
    n_operatori = righe(napoli.percorso, 'SELECT COUNT(*) AS n FROM napoli_operatori')[0]['n']

    def altro_codice(r):
        for x in r:
            if x['operatore'] == 'DI ESEMPIO ALFA MARIA':
                x['cf_operatore'] = 'DSMLMR84A71Z99'            # di nuovo sbagliato, ma diverso
        r[0]['giorni'][datetime.date(2026, 3, 3)] = 1
    diverso = variante(tmp_path, altro_codice)
    a = _ok(anteprima(napoli, diverso))
    assert a['conferme_richieste'] == ['operatori_per_nome']
    testo = a['conferme'][0]['voci'][0]['testo']
    assert 'DI ESEMPIO ALFA MARIA' in testo and '•' in testo and 'DSMLMR84A71Z99' not in testo
    _errore(conferma(napoli, diverso, a), 400, 'DA_CONFERMARE')
    _ok(conferma(napoli, diverso, a, {'conferme': ['operatori_per_nome']}))
    assert righe(napoli.percorso, 'SELECT COUNT(*) AS n FROM napoli_operatori')[0]['n'] == n_operatori


# ==================== il mese dopo ====================

def aprile(tmp_path, modifica=None, nome='master_aprile.xlsx'):
    """Il master inventato di aprile 2026: le stesse righe di marzo, il mese dopo."""
    return ns.leggi_bytes(str(tmp_path / nome.replace('.', '_')), nome_file=nome, modifica=modifica,
                          anno=2026, mese=4)[0]


def coppie_per_nome(percorso):
    """Le coppie per (operatore, alunno, ruolo), con i nomi delle anagrafiche."""
    return {(c['operatore'], c['alunno'], c['ruolo']): c for c in righe(
        percorso, "SELECT c.*, o.cognome || ' ' || o.nome AS operatore, a.cognome || ' ' || a.nome AS alunno "
                  'FROM napoli_coppie c JOIN napoli_operatori o ON o.id = c.operatore_id '
                  'JOIN napoli_alunni a ON a.id = c.alunno_id')}


def municipalita_di(inizio_scuola, municipalita):
    def modifica(r):
        for x in r:
            if x['scuola'].startswith(inizio_scuola):
                x['municipalita'] = municipalita
    return modifica


def codice_giusto(operatore):
    cog, nom, sesso, nascita, _q = next(v for v in ns.OPERATORI.values() if f'{v[0]} {v[1]}' == operatore)
    return seme_napoli.codice_fiscale_inventato(cog, nom, nascita, sesso)


def codici(a, livello='avvisi'):
    return {g['codice']: g for g in a[livello]}


def test_il_mese_dopo_le_coppie_continuano(napoli, master, tmp_path):
    """Aprile con le stesse righe di marzo: nessuna coppia nuova. Un sostituto che continua
    resta la stessa coppia (finisce piu' tardi); il titolare chiuso con il subentro del 24
    marzo che in aprile ha di nuovo ore si riapre, con un avviso."""
    dati, _atteso = master
    importa(napoli, dati)
    marzo = coppie_per_nome(napoli.percorso)
    apr = aprile(tmp_path)
    a, _scelte = con_ore_scelte(napoli, apr)
    c = a['conteggi']
    assert a['file']['mese_testo'] == 'aprile 2026' and a['reimport'] is None
    assert {k: c['nuovi'][k] for k in ('coppie', 'alunni', 'operatori', 'pei', 'scuole')} == {
        'coppie': 0, 'alunni': 0, 'operatori': 0, 'pei': 0, 'scuole': 0}
    assert c['aggiornati']['coppie'] == 7                     # 5 sostituti che continuano, 2 titolari che tornano
    assert codici(a)['coppia_riaperta']['n'] == 2
    assert not a['chiusure'] and not a['coppie_del_mese'] and not a['conferme_richieste']
    _a, esito = importa(napoli, apr)
    dopo = coppie_per_nome(napoli.percorso)
    assert set(dopo) == set(marzo) and len(dopo) == 41
    chiave = ('FORMATO TAU', 'NOVIZIO ZETA', 'sostituto')
    assert dopo[chiave]['id'] == marzo[chiave]['id'] and dopo[chiave]['valido_da'] == '2026-03-16'
    assert (marzo[chiave]['valido_a'], dopo[chiave]['valido_a']) == ('2026-03-19', '2026-04-17')
    chiave = ('CAMPIONE ZETA', 'STUDENTE LAMBDA', 'titolare')
    assert (marzo[chiave]['valido_a'], dopo[chiave]['valido_a']) == ('2026-03-23', None)
    # l'elenco dei caricamenti dice anche i dati solo aggiornati (non solo «nessun dato nuovo»)
    ultimo = _ok(napoli.get(f'/api/napoli/lotti/{napoli.lotto_id}/import'))[0]
    assert ultimo['id'] == esito['import_id'] and ultimo['aggiornati']['coppie'] == 7
    assert not any(ultimo['nuovi'][k] for k in ('coppie', 'alunni', 'operatori', 'scuole', 'pei'))
    assert ultimo['tolti'] == {'scuole': 0}
    # annullare aprile rimette le coppie di marzo com'erano
    _ok(napoli.post(f'/api/napoli/import/{esito["import_id"]}/annulla', json={}))
    assert coppie_per_nome(napoli.percorso) == marzo


def test_il_mese_dopo_una_municipalita_diversa_da_assisto_va_confermata(napoli, master, tmp_path):
    """NAIC8ZZ001 in Assisto e' nella municipalita' 2; in aprile e' scritta 3. Non si crea
    una scuola vuota e la municipalita' del file non si ignora in silenzio (REGOLE 12): le
    coppie gia' in Assisto restano nel loro plesso, con la conferma "Ho controllato"."""
    dati, _atteso = master
    importa(napoli, dati)
    apr = aprile(tmp_path, municipalita_di('I.C. ALFA', 3))
    a, scelte = con_ore_scelte(napoli, apr)
    assert a['conferme_richieste'] == ['plessi'] and a['scuole_nuove'] == []
    assert a['conteggi']['nuovi']['scuole'] == 0
    [voce] = a['conferme'][0]['voci']
    assert voce['testo'] == ('I.C. ALFA CENTAURI - PLESSO NORD (NAIC8ZZ001): nel file municipalità 3, in Assisto 2: '
                             'le coppie già in Assisto restano nel plesso della municipalità 2')
    assert voce['righe'] == [2, 3, 14, 23, 24, 38]
    _errore(conferma(napoli, apr, a, scelte), 400, 'DA_CONFERMARE')
    _ok(conferma(napoli, apr, a, dict(scelte, conferme=['plessi'])))
    plessi = righe(napoli.percorso, "SELECT municipalita FROM napoli_scuole WHERE codice_meccanografico = 'NAIC8ZZ001'")
    assert [p['municipalita'] for p in plessi] == [2]
    ore = righe(napoli.percorso, 'SELECT s.municipalita, COUNT(*) AS n FROM napoli_presenze p '
                                 'JOIN napoli_coppie c ON c.id = p.coppia_id JOIN napoli_scuole s ON s.id = c.scuola_id '
                                 "WHERE s.codice_meccanografico = 'NAIC8ZZ001' AND p.data >= '2026-04-01' "
                                 'GROUP BY s.municipalita')
    assert [x['municipalita'] for x in ore] == [2] and ore[0]['n'] > 0


def test_il_mese_dopo_un_plesso_nuovo_serve_a_una_coppia_nuova(napoli, master, tmp_path):
    """Un operatore nuovo con un alunno della stessa scuola scritta nella municipalita' 3:
    la coppia e' nuova, quindi si aggiunge il plesso della municipalita' 3 (due plessi della
    stessa scuola), da confermare."""
    dati, _atteso = master
    importa(napoli, dati)

    def operatore_nuovo(r):
        x = dict(r[0], giorni=dict(r[0]['giorni']), colorati=set())
        x.update(operatore='NUOVA PROVA', cf_operatore=seme_napoli.codice_fiscale_inventato(
            'NUOVA', 'PROVA', datetime.date(1990, 1, 1), 'F'), municipalita=3, note=None)
        r.append(x)
    apr = aprile(tmp_path, operatore_nuovo)
    a, scelte = con_ore_scelte(napoli, apr)
    assert a['conferme_richieste'] == ['plessi', 'gradi']
    assert [(s['codice'], s['municipalita']) for s in a['scuole_nuove']] == [('NAIC8ZZ001', 3)]
    [voce] = a['conferme'][0]['voci']
    assert 'nel file municipalità 2 e 3, in Assisto 2: si aggiunge il plesso della municipalità 3' in voce['testo']
    assert voce['righe'] == [43]
    _ok(conferma(napoli, apr, a, dict(scelte, conferme=['plessi', 'gradi'])))
    plessi = righe(napoli.percorso, "SELECT s.municipalita, COUNT(c.id) AS coppie FROM napoli_scuole s "
                                    'LEFT JOIN napoli_coppie c ON c.scuola_id = s.id '
                                    "WHERE s.codice_meccanografico = 'NAIC8ZZ001' GROUP BY s.id ORDER BY s.municipalita")
    assert [(p['municipalita'], p['coppie']) for p in plessi] == [(2, 6), (3, 1)]


def test_il_mese_dopo_una_coppia_con_un_altra_scuola_resta_nella_sua(napoli, master, tmp_path):
    """Una coppia gia' in Assisto la cui riga ha un'altra scuola (che in Assisto non c'e'):
    avviso, la coppia resta nella sua scuola e la scuola nuova non si crea vuota."""
    dati, _atteso = master
    importa(napoli, dati)

    def altra_scuola(r):
        r[0]['scuola'] = 'I.C. OMEGA (COD.MECC. NAIC8ZZ099)'
    a, _scelte = con_ore_scelte(napoli, aprile(tmp_path, altra_scuola))
    assert codici(a)['coppia_scuola_diversa']['righe'][0]['riga'] == 2
    assert a['scuole_nuove'] == [] and a['conteggi']['nuovi']['scuole'] == 0 and not a['conferme_richieste']
    importa(napoli, aprile(tmp_path, altra_scuola))
    assert not righe(napoli.percorso, "SELECT id FROM napoli_scuole WHERE codice_meccanografico = 'NAIC8ZZ099'")


def test_il_mese_dopo_la_municipalita_mancante_si_aggiunge_alla_scuola(napoli, tmp_path):
    """Una scuola salvata senza municipalita' (mancava nel file di marzo): in aprile la
    municipalita' c'e' e si aggiunge allo stesso plesso (non un plesso nuovo, vuoto)."""
    marzo = variante(tmp_path, municipalita_di('I.C. ALFA', None), nome='marzo_senza.xlsx')
    importa(napoli, marzo)
    [plesso] = righe(napoli.percorso, "SELECT id, municipalita FROM napoli_scuole "
                                      "WHERE codice_meccanografico = 'NAIC8ZZ001'")
    assert plesso['municipalita'] is None
    prima = impronta_dati(napoli.percorso)
    apr = aprile(tmp_path)                                    # municipalita' 2
    a, _scelte = con_ore_scelte(napoli, apr)
    assert a['conteggi']['nuovi']['scuole'] == 0 and a['conteggi']['aggiornati']['scuole'] == 1
    g = codici(a)['municipalita_completata_in_assisto']
    assert g['n'] == 1 and g['righe'][0]['dettaglio'] == 'municipalità 2'
    assert not a['conferme_richieste'] and not a['scuole_nuove']
    _a, esito = importa(napoli, apr)
    assert righe(napoli.percorso, "SELECT id, municipalita FROM napoli_scuole "
                                  "WHERE codice_meccanografico = 'NAIC8ZZ001'") == [{'id': plesso['id'], 'municipalita': 2}]
    _ok(napoli.post(f'/api/napoli/import/{esito["import_id"]}/annulla', json={}))
    assert impronta_dati(napoli.percorso) == prima


RIGA_7, RIGA_41 = 5, 39          # indici delle righe 7 (DE PROVA DELTA con NOVIZIO ZETA) e 41 del foglio


def un_plesso_nella_2(r):
    """LICEO ZETA ETA (NAPC0ZZ004) e' nella municipalita' 1, la riga 41 nella 2: due plessi.
    La riga 7 non ha la municipalita'."""
    r[RIGA_41]['municipalita'] = 2


def plessi_zeta(percorso):
    """(municipalita', coppie) dei plessi di LICEO ZETA ETA."""
    return [(p['municipalita'], p['coppie']) for p in righe(
        percorso, 'SELECT s.municipalita, COUNT(c.id) AS coppie FROM napoli_scuole s '
                  'LEFT JOIN napoli_coppie c ON c.scuola_id = s.id '
                  "WHERE s.codice_meccanografico = 'NAPC0ZZ004' GROUP BY s.id ORDER BY s.municipalita")]


def coppia_riga_7(percorso):
    return righe(percorso, 'SELECT c.id, c.scuola_id, c.alunno_id, a.scuola_id AS scuola_alunno FROM napoli_coppie c '
                           'JOIN napoli_operatori o ON o.id = c.operatore_id JOIN napoli_alunni a ON a.id = c.alunno_id '
                           "WHERE o.cognome = 'DE PROVA' AND a.cognome = 'NOVIZIO' AND a.nome = 'ZETA'")[0]


def test_municipalita_mancante_in_una_scuola_con_piu_plessi_si_sceglie(napoli, tmp_path):
    """REGOLE 12: la municipalita' e' della scuola. Se la scuola ha piu' plessi e la riga non
    la scrive, non si crea un plesso "senza municipalita'" in piu': la riga non si carica
    finche' non si sceglie il plesso nella pagina (o si scrive nel file). Ricaricando lo stesso
    file la municipalita' e' quella del plesso della coppia gia' in Assisto."""
    dati = variante(tmp_path, un_plesso_nella_2)
    a = _ok(anteprima(napoli, dati, modo='anagrafica'))
    g = codici(a, 'bloccanti')['municipalita_da_scegliere']
    assert [(x['riga'], x['dettaglio']) for x in g['righe']] == [(7, 'municipalità 1 o 2')]
    [x] = a['plessi_da_scegliere']
    assert (x['riga'], x['codice'], x['possibili'], x['scelta']) == (7, 'NAPC0ZZ004', [1, 2], None)
    assert (x['operatore'], x['alunno'], x['figura']) == ('DE PROVA DELTA', 'NOVIZIO ZETA', 'Educatore')
    assert 'municipalita_presa_dalla_scuola' not in codici(a, 'note')
    _errore(conferma(napoli, dati, a, {'conferme': a['conferme_richieste']}), 400, 'IMPORT_BLOCCATO')
    # una municipalita' che la scuola non ha non vale come scelta
    a = _ok(anteprima(napoli, dati, {'plessi': {x['chiave']: '5'}}, modo='anagrafica'))
    assert 'municipalita_da_scegliere' in codici(a, 'bloccanti')
    _errore(anteprima(napoli, dati, {'plessi': {x['chiave']: 'senza'}}, modo='anagrafica'), 400, 'SCELTE_NON_VALIDE')
    a, _esito = carica_anagrafica(napoli, dati, {'plessi': {x['chiave']: '1'}})
    assert not a['bloccanti'] and a['plessi_da_scegliere'][0]['scelta'] == 1
    assert plessi_zeta(napoli.percorso) == [(1, 5), (2, 1)]
    c = coppia_riga_7(napoli.percorso)
    assert c['scuola_id'] == c['scuola_alunno']
    assert righe(napoli.percorso, 'SELECT municipalita FROM napoli_scuole WHERE id = ?', (c['scuola_id'],)) == [
        {'municipalita': 1}]
    # lo stesso file di nuovo: niente da scegliere (la municipalita' e' quella del plesso della coppia)
    for modo in ('anagrafica', 'import'):
        a = _ok(anteprima(napoli, dati, modo=modo))
        assert a['plessi_da_scegliere'] == [] and not a['bloccanti']
        assert [x['riga'] for x in codici(a, 'note')['municipalita_presa_dalla_coppia']['righe']] == [7]
    assert _ok(anteprima(napoli, dati, modo='anagrafica'))['nessun_cambiamento']


def test_coppie_in_un_plesso_senza_municipalita_passano_al_plesso_del_file(napoli, tmp_path):
    """Dati lasciati da un import di prima: la riga 7 senza municipalita' aveva creato un terzo
    plesso di LICEO ZETA ETA, "senza municipalita'", con la coppia e l'alunno. Con il file
    corretto (la riga 7 nella municipalita' 1) la coppia e l'alunno passano al plesso della
    municipalita' 1 (da confermare) e il plesso senza municipalita', rimasto vuoto, si toglie.
    Annullare rimette tutto com'era."""
    dati = variante(tmp_path, un_plesso_nella_2)
    a = _ok(anteprima(napoli, dati, modo='anagrafica'))
    carica_anagrafica(napoli, dati, {'plessi': {a['plessi_da_scegliere'][0]['chiave']: '1'}})
    esegui(napoli.percorso, 'INSERT INTO napoli_scuole (lotto_id, nome, codice_meccanografico, grado, municipalita, '
                            'data_inserimento) SELECT lotto_id, nome, codice_meccanografico, grado, NULL, data_inserimento '
                            "FROM napoli_scuole WHERE codice_meccanografico = 'NAPC0ZZ004' AND municipalita = 1")
    [senza] = righe(napoli.percorso, "SELECT id FROM napoli_scuole WHERE codice_meccanografico = 'NAPC0ZZ004' "
                                     'AND municipalita IS NULL')
    c = coppia_riga_7(napoli.percorso)
    esegui(napoli.percorso, 'UPDATE napoli_coppie SET scuola_id = ? WHERE id = ?', (senza['id'], c['id']))
    esegui(napoli.percorso, 'UPDATE napoli_alunni SET scuola_id = ? WHERE id = ?', (senza['id'], c['alunno_id']))
    assert plessi_zeta(napoli.percorso) == [(None, 1), (1, 4), (2, 1)]
    prima = impronta_dati(napoli.percorso)

    def corretto(r):
        un_plesso_nella_2(r)
        r[RIGA_7]['municipalita'] = 1
    file_corretto = variante(tmp_path, corretto, nome='corretto.xlsx')
    a = _ok(anteprima(napoli, file_corretto, modo='anagrafica'))
    assert not a['nessun_cambiamento'] and a['conferme_richieste'] == ['plessi']
    assert a['conteggi']['tolti'] == {'scuole': 1} and a['conteggi']['nuovi']['scuole'] == 0
    assert (a['conteggi']['aggiornati']['coppie'], a['conteggi']['aggiornati']['alunni']) == (1, 1)
    [voce] = a['conferme'][0]['voci']
    assert voce['testo'] == ('LICEO ZETA ETA (NAPC0ZZ004): nel file municipalità 1 e 2, in Assisto 1 e 2 e senza '
                             'municipalità: le coppie già in Assisto nel plesso senza municipalità passano al plesso '
                             'della municipalità 1; il plesso senza municipalità, rimasto vuoto, si toglie')
    assert (voce['righe'], voce['n_righe']) == ([7], 1)          # la pagina scrive «riga 7»
    _errore(conferma(napoli, file_corretto, a), 400, 'DA_CONFERMARE')
    _a, esito = carica_anagrafica(napoli, file_corretto)
    assert plessi_zeta(napoli.percorso) == [(1, 5), (2, 1)]
    dopo = coppia_riga_7(napoli.percorso)
    assert dopo['scuola_id'] == dopo['scuola_alunno'] != senza['id']
    # la copia per l'annullamento ha la riga del plesso tolto, senza codici fiscali
    [imp] = righe(napoli.percorso, 'SELECT esito_json, sostituite_json FROM napoli_import WHERE id = ?',
                  (esito['import_id'],))
    registro = json.loads(imp['sostituite_json'])
    assert [r['id'] for r in registro['tolte_scuole']] == [senza['id']]
    for testo in (imp['esito_json'], imp['sostituite_json'], json.dumps(a)):
        assert import_napoli.nascondi_codici_fiscali(testo) == testo
    # ricaricarlo non cambia piu' niente
    assert _ok(anteprima(napoli, file_corretto, modo='anagrafica'))['nessun_cambiamento']
    _ok(napoli.post(f'/api/napoli/import/{esito["import_id"]}/annulla', json={}))
    assert impronta_dati(napoli.percorso) == prima


def test_il_mese_dopo_il_plesso_senza_municipalita_la_prende_dal_file(napoli, tmp_path):
    """Marzo senza la municipalita' di LICEO ZETA ETA (un plesso senza municipalita'), aprile
    con la scuola nella 1 e una riga nella 2: il plesso prende la municipalita' 1 (quella
    della maggior parte delle righe, le sue coppie restano li'), la coppia della riga 41 e il
    suo alunno passano al plesso nuovo della municipalita' 2."""
    importa(napoli, variante(tmp_path, municipalita_di('LICEO ZETA', None), nome='marzo_senza.xlsx'))
    [plesso] = righe(napoli.percorso, "SELECT id, municipalita FROM napoli_scuole WHERE codice_meccanografico = 'NAPC0ZZ004'")
    assert plessi_zeta(napoli.percorso) == [(None, 6)]
    prima = impronta_dati(napoli.percorso)

    def nella_1_e_nella_2(r):
        municipalita_di('LICEO ZETA', 1)(r)
        un_plesso_nella_2(r)
    apr = aprile(tmp_path, nella_1_e_nella_2)
    a, scelte = con_ore_scelte(napoli, apr)
    assert a['conferme_richieste'] == ['plessi', 'gradi'] and a['plessi_da_scegliere'] == []
    assert [(s['codice'], s['municipalita']) for s in a['scuole_nuove']] == [('NAPC0ZZ004', 2)]
    [voce] = a['conferme'][0]['voci']
    assert voce['testo'] == ('LICEO ZETA ETA (NAPC0ZZ004): nel file municipalità 1 e 2, in Assisto senza '
                             'municipalità: si aggiunge il plesso della municipalità 2; il plesso senza municipalità '
                             'prende la municipalità 1; le coppie già in Assisto nel plesso senza municipalità '
                             'passano al plesso della municipalità 2')
    _a, esito = importa(napoli, apr)
    assert plessi_zeta(napoli.percorso) == [(1, 5), (2, 1)]
    assert righe(napoli.percorso, 'SELECT municipalita FROM napoli_scuole WHERE id = ?', (plesso['id'],)) == [
        {'municipalita': 1}]
    assert righe(napoli.percorso, 'SELECT COUNT(*) AS n FROM napoli_alunni a JOIN napoli_scuole s ON s.id = a.scuola_id '
                                  "WHERE s.codice_meccanografico = 'NAPC0ZZ004' AND s.municipalita = 2")[0]['n'] == 1
    _ok(napoli.post(f'/api/napoli/import/{esito["import_id"]}/annulla', json={}))
    assert impronta_dati(napoli.percorso) == prima


@pytest.mark.parametrize('sbagliato,codice', [
    ({'cf_alunno': 'ABC123'}, 'cf_alunno_non_valido'),
    ({'operatore': '', 'cf_operatore': ''}, 'riga_senza_operatore'),
])
def test_il_plesso_si_chiede_solo_se_il_resto_della_riga_va_bene(napoli, tmp_path, sbagliato, codice):
    """La riga 7 non ha la municipalita' (la scuola ha due plessi) e ha l'alunno o
    l'operatore da correggere: la riga non si carica comunque, quindi il plesso non si
    chiede (niente voce «Plessi da scegliere» con il nome vuoto); si chiede quando la riga
    e' corretta."""
    def riga_sbagliata(r):
        un_plesso_nella_2(r)
        r[RIGA_7].update(sbagliato)
    dati = variante(tmp_path, riga_sbagliata)
    for modo in ('anagrafica', 'import'):
        a = _ok(anteprima(napoli, dati, modo=modo))
        assert a['plessi_da_scegliere'] == []
        assert codice in codici(a, 'bloccanti') and 'municipalita_da_scegliere' not in codici(a, 'bloccanti')
        assert [x['riga'] for x in codici(a, 'bloccanti')[codice]['righe']] == [7]
    assert set(codici(_ok(anteprima(napoli, dati, modo='anagrafica')), 'bloccanti')) == {codice}
    [x] = _ok(anteprima(napoli, variante(tmp_path, un_plesso_nella_2, nome='corretto.xlsx'),
                        modo='anagrafica'))['plessi_da_scegliere']
    assert (x['riga'], x['operatore'], x['alunno']) == (7, 'DE PROVA DELTA', 'NOVIZIO ZETA')


def test_la_conferma_bloccata_dice_cosa_fare_con_le_parole_della_pagina(napoli, tmp_path):
    """Si arriva alla conferma con dei bloccanti solo aggirando il pulsante disattivato: il
    messaggio distingue le scelte della pagina (plessi, qualifiche nuove) dagli errori del
    file e dice «caricare l'anagrafica» o «importare» come la pagina."""
    def con(*modifiche):
        def modifica(r):
            for m in modifiche:
                m(r)
        return modifica

    def qualifica_nuova(r):
        r[3]['qualifica'] = 'OPERATORE SOCIALE'

    def alunno_senza_codice(r):
        r[10]['cf_alunno'] = ''
    casi = [
        (con(un_plesso_nella_2), 'anagrafica',
         'Prima di caricare l\'anagrafica scegli i plessi nella parte «Da confermare» dell\'anteprima.'),
        (con(un_plesso_nella_2), 'import',
         'Prima di importare scegli i plessi nella parte «Da confermare» dell\'anteprima.'),
        (con(un_plesso_nella_2, qualifica_nuova), 'anagrafica',
         'Prima di caricare l\'anagrafica scegli le figure delle qualifiche nuove e i plessi nella parte «Da '
         'confermare» dell\'anteprima.'),
        (con(un_plesso_nella_2, alunno_senza_codice), 'anagrafica',
         'Prima di caricare l\'anagrafica scegli i plessi nella parte «Da confermare» e correggi il file (guarda la '
         'parte «Da correggere» dell\'anteprima).'),
        (con(alunno_senza_codice), 'anagrafica',
         'Prima di caricare l\'anagrafica bisogna correggere il file: guarda la parte «Da correggere» '
         'dell\'anteprima.'),
        (con(alunno_senza_codice), 'import',
         'Prima di importare bisogna correggere il file: guarda la parte «Da correggere» dell\'anteprima.'),
    ]
    for i, (modifica, modo, messaggio) in enumerate(casi):
        dati = variante(tmp_path, modifica, nome=f'caso{i}.xlsx')
        a = _ok(anteprima(napoli, dati, modo=modo))
        e = _errore(conferma(napoli, dati, a), 400, 'IMPORT_BLOCCATO')
        assert e['error'] == messaggio, (i, e['error'])
    # le conferme da spuntare, nel modo dell'anagrafica (aprile cambia qualcosa: non sono solo avvisi)
    importa(napoli, variante(tmp_path, municipalita_di('I.C. ALFA', 2), nome='prima.xlsx'))
    dati = aprile(tmp_path, municipalita_di('I.C. ALFA', 3))
    a = _ok(anteprima(napoli, dati, modo='anagrafica'))
    assert 'plessi' in a['conferme_richieste']
    e = _errore(conferma(napoli, dati, a), 400, 'DA_CONFERMARE')
    assert e['error'] == 'Prima di caricare l\'anagrafica spunta le caselle «Ho controllato» nella parte «Da confermare».'


def test_il_mese_dopo_i_codici_fiscali_corretti_non_creano_doppioni(napoli, master, tmp_path):
    """Marzo con due codici sbagliati (SCHEMA SIGMA: l'ultimo carattere; DI ESEMPIO ALFA
    MARIA: 17 caratteri); aprile con quelli giusti. Sono le stesse persone (nessun operatore
    o coppia nuova): il codice si corregge anche in Assisto. Annullando aprile tornano i
    codici di prima; nel registro dell'import non c'e' mai un codice fiscale."""
    dati, _atteso = master
    importa(napoli, dati)
    prima = impronta_dati(napoli.percorso)

    def giusti(r):
        for x in r:
            if x['operatore'] in ('SCHEMA SIGMA', 'SCHEMA SIGMMA'):
                x['cf_operatore'] = codice_giusto('SCHEMA SIGMA')
            elif x['operatore'] == 'DI ESEMPIO ALFA MARIA':
                x['cf_operatore'] = codice_giusto('DI ESEMPIO ALFA MARIA')
    apr = aprile(tmp_path, giusti)
    a, scelte = con_ore_scelte(napoli, apr)
    c = a['conteggi']
    assert c['nuovi']['operatori'] == 0 and c['nuovi']['coppie'] == 0 and not a['chiusure']
    assert c['aggiornati']['operatori'] == 2
    assert codici(a)['cf_operatore_corretto_in_assisto']['n'] == 1        # SCHEMA SIGMA: cambia l'ultimo carattere
    assert a['conferme_richieste'] == ['operatori_per_nome']               # DI ESEMPIO ALFA MARIA: dal nome
    [voce] = a['conferme'][0]['voci']
    assert voce['testo'].startswith('DI ESEMPIO ALFA MARIA: nel file DSM') and 'si corregge anche in Assisto' in voce['testo']
    _errore(conferma(napoli, apr, a, scelte), 400, 'DA_CONFERMARE')
    _ok(conferma(napoli, apr, a, dict(scelte, conferme=['operatori_per_nome'])))
    operatori = {f"{o['cognome']} {o['nome']}": o for o in righe(napoli.percorso, 'SELECT * FROM napoli_operatori')}
    assert len(operatori) == 22
    for nome in ('SCHEMA SIGMA', 'DI ESEMPIO ALFA MARIA'):
        assert (operatori[nome]['codice_fiscale'], operatori[nome]['cf_valido']) == (codice_giusto(nome), 1)
    registro = json.dumps(righe(napoli.percorso, 'SELECT esito_json, sostituite_json FROM napoli_import'))
    tutti = {r['cf_operatore'] for r in ns.costruisci()[0]} | {codice_giusto(n) for n in operatori}
    assert not [cf for cf in tutti if cf in registro], 'codici fiscali nel registro degli import'
    [imp] = [i for i in righe(napoli.percorso, 'SELECT * FROM napoli_import') if i['mese'] == 4]
    _ok(napoli.post(f'/api/napoli/import/{imp["id"]}/annulla', json={}))
    assert impronta_dati(napoli.percorso) == prima


def test_il_mese_dopo_il_codice_dell_alunno_con_l_ultimo_carattere_corretto(napoli, master, tmp_path):
    """L'alunno salvato con il codice sbagliato nell'ultimo carattere: in aprile il codice
    giusto e' lo stesso alunno (niente alunno o PEI nuovi) e si corregge in Assisto. Al
    contrario, un codice giusto in Assisto e sbagliato nel file: si usa quello di Assisto."""
    def sbagliato(r):
        cf = r[0]['cf_alunno']
        r[0]['cf_alunno'] = cf[:15] + ('A' if cf[15] != 'A' else 'B')
    importa(napoli, variante(tmp_path, sbagliato, nome='marzo_cf.xlsx'))
    prima = impronta_dati(napoli.percorso)
    giusto = ns.costruisci()[0][0]['cf_alunno']
    a, _scelte = con_ore_scelte(napoli, aprile(tmp_path))
    c = a['conteggi']
    assert (c['nuovi']['alunni'], c['nuovi']['pei'], c['nuovi']['coppie'], c['aggiornati']['alunni']) == (0, 0, 0, 1)
    assert codici(a)['cf_alunno_corretto_in_assisto']['n'] == 1
    _a, esito = importa(napoli, aprile(tmp_path))
    assert giusto in {x['codice_fiscale'] for x in righe(napoli.percorso, 'SELECT codice_fiscale FROM napoli_alunni')}
    assert righe(napoli.percorso, 'SELECT COUNT(*) AS n FROM napoli_alunni')[0]['n'] == 34
    _ok(napoli.post(f'/api/napoli/import/{esito["import_id"]}/annulla', json={}))
    assert impronta_dati(napoli.percorso) == prima
    # al contrario: in Assisto il codice giusto, nel file di nuovo quello sbagliato
    _ok(napoli.post(f'/api/napoli/import/{_ultimo_import(napoli)}/annulla', json={}))
    importa(napoli, master[0])
    b, _scelte = con_ore_scelte(napoli, aprile(tmp_path, sbagliato, nome='aprile_cf.xlsx'))
    assert (b['conteggi']['nuovi']['alunni'], b['conteggi']['aggiornati']['alunni']) == (0, 0)
    assert 'cf_alunno_giusto_in_assisto' in codici(b, 'note')


def _ultimo_import(client):
    return next(i['id'] for i in _ok(client.get(f'/api/napoli/lotti/{client.lotto_id}/import')) if i['annullabile'])


def test_omonimo_con_un_altro_codice_giusto_e_una_persona_nuova_con_avviso(napoli, master, tmp_path):
    dati, _atteso = master
    importa(napoli, dati)

    def altro_codice(r):
        for x in r:
            if x['operatore'] == 'PROVA ALFA':
                x['cf_operatore'] = seme_napoli.codice_fiscale_inventato('PROVA', 'ALFA', datetime.date(1970, 1, 1), 'F')
    a, _scelte = con_ore_scelte(napoli, aprile(tmp_path, altro_codice))
    assert a['conteggi']['nuovi']['operatori'] == 1
    assert codici(a)['operatore_omonimo_in_assisto']['righe'][0]['riga'] == 2
    assert not a['conferme_richieste'] and len(a['chiusure']) == 2       # le coppie dell'altra PROVA ALFA


def test_operatore_con_piu_figure(napoli, master, tmp_path):
    def educatrice(r):
        r[1]['qualifica'] = 'EDUCATORE PROFESSIONALE'          # PROVA ALFA: Asacom alla riga 2, Educatore alla 3
    a = _ok(anteprima(napoli, variante(tmp_path, educatrice)))
    g = codici(a)['operatore_con_piu_figure']
    assert [x['riga'] for x in g['righe']] == [2, 3] and g['righe'][0]['dettaglio'] == 'nel file Asacom e Educatore'
    # gia' in Assisto con un'altra figura
    importa(napoli, master[0])

    def tutta_educatrice(r):
        for x in r[:2]:
            x['qualifica'] = 'EDUCATORE PROFESSIONALE'
    b, _scelte = con_ore_scelte(napoli, aprile(tmp_path, tutta_educatrice))
    g = codici(b)['operatore_con_piu_figure']
    assert g['n'] == 2 and g['righe'][0]['dettaglio'] == 'nel file Educatore, in Assisto Asacom'


def test_reimport_senza_una_riga_propone_di_chiudere_la_sua_coppia(napoli, master, tmp_path):
    """Reimport di marzo senza due righe: le loro ore importate si tolgono. La coppia che
    c'era gia' prima di marzo si propone da chiudere (fine febbraio); quella che comincia a
    marzo (subentro dal 24) non si puo' chiudere prima e si mostra."""
    dati, _atteso = master
    importa(napoli, dati)

    def senza(r):
        del r[30 - 2]                                     # IPOTESI PHI con STUDENTE LAMBDA, dal 24 marzo
        del r[0]                                          # PROVA ALFA con SCOLARO ALFA, dal 1/10/2025
    meno = variante(tmp_path, senza, nome='marzo_meno.xlsx')
    a, scelte = con_ore_scelte(napoli, meno)
    [chiusura] = a['chiusure']
    assert chiusura['testo'].startswith('PROVA ALFA con SCOLARO ALFA (Asacom)') and not chiusura['scelto']
    assert chiusura['chiudi_al'] == '2026-02-28'
    [del_mese] = a['coppie_del_mese']
    assert del_mese['testo'] == 'IPOTESI PHI con STUDENTE LAMBDA (Educatore, sostituto): comincia il 24/03/2026'
    assert codici(a)['coppia_del_mese_non_nel_file']['n'] == 1
    assert a['conteggi']['presenze']['da_togliere'] > 0
    importa(napoli, meno, dict(scelte, chiusure=[chiusura['id']]))
    coppie = coppie_per_nome(napoli.percorso)
    assert coppie[('PROVA ALFA', 'SCOLARO ALFA', 'titolare')]['valido_a'] == '2026-02-28'


# ==================== errori del file ====================

def _cartella_senza_master():
    wb = openpyxl.Workbook()
    wb.active.title = 'Prefattura'
    wb.active.append(['Commessa', 'Scuola', 'Nome', 'Ore'])
    wb.active.append(['ROMA', 'Scuola', 'Prova', 3])
    uscita = io.BytesIO()
    wb.save(uscita)
    return uscita.getvalue()


def _zip_qualsiasi():
    uscita = io.BytesIO()
    with zipfile.ZipFile(uscita, 'w') as z:
        z.writestr('leggimi.txt', 'non e un file Excel')
    return uscita.getvalue()


@pytest.mark.parametrize('dati,nome,codice,parola', [
    (b'', 'master.xlsx', 'FILE_VUOTO', 'vuoto'),
    (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + b'\0' * 100, 'master.xls', 'FILE_XLS', '.xls'),
    (b'questo non e un file excel', 'master.xlsx', 'FILE_NON_LEGGIBILE', 'aperto in Excel'),
    (_zip_qualsiasi(), 'master.xlsx', 'FILE_NON_LEGGIBILE', 'aperto in Excel'),
    (b'utente di prova', '~$master.xlsx', 'FILE_TEMPORANEO_EXCEL', '~$'),
    (_cartella_senza_master(), 'prefattura.xlsx', 'FOGLIO_NON_RICONOSCIUTO', 'Prefattura'),
])
def test_file_sbagliati_messaggi_semplici(napoli, dati, nome, codice, parola):
    e = _errore(anteprima(napoli, dati, nome=nome), 400, codice)
    assert e['campo'] == 'file' and parola in e['error']
    for tecnico in ('Traceback', 'zip', 'openpyxl', 'Exception', 'Error', 'None'):
        assert tecnico not in e['error'], (tecnico, e['error'])


def test_richieste_incomplete(napoli, master):
    dati, _atteso = master
    _errore(napoli.post('/api/napoli/import/anteprima', content_type='multipart/form-data',
                        data={'lotto_id': str(napoli.lotto_id)}), 400, 'FILE_MANCANTE')
    _errore(napoli.post('/api/napoli/import/anteprima', content_type='multipart/form-data',
                        data={'file': (io.BytesIO(dati), 'm.xlsx')}), 400)
    _errore(anteprima(napoli, dati, lotto_id=999), 404)
    r = napoli.post('/api/napoli/import/anteprima', content_type='multipart/form-data', data={
        'file': (io.BytesIO(dati), 'm.xlsx'), 'lotto_id': str(napoli.lotto_id), 'scelte': '{non json'})
    _errore(r, 400, 'SCELTE_NON_VALIDE')


# ==================== pagina e Roma ====================

def test_pagina_di_import(napoli):
    """L'azione principale e' "Carica l'anagrafica dal file Excel" (REGOLE 14); le ore dei
    giorni di un mese sono in una parte secondaria, chiusa."""
    r = napoli.get('/napoli/import')
    assert r.status_code == 200
    testo = r.get_data(as_text=True)
    assert 'Carica l&#39;anagrafica dal file Excel' in testo or "Carica l'anagrafica dal file Excel" in testo
    assert 'NapoliImport.avvia()' in testo
    principale = testo.index('id="btn-import-anteprima"')
    altre = testo.index('<details class="napoli-altre-azioni"')
    assert principale < altre < testo.index('id="btn-import-ore"') and altre < testo.index('id="btn-import-confronta"')
    assert 'btn btn-primary" id="btn-import-anteprima"' in testo
    assert '<details class="napoli-altre-azioni" id="import-altre">' in testo           # chiusa (senza open)
    assert 'href="/napoli/import"' in napoli.get('/napoli').get_data(as_text=True)


def test_import_con_alunni_omonimi_non_tocca_roma(archivio_roma, app_module, db_mod, tmp_path):
    client = archivio_roma.client
    roma_prima = seme_napoli.impronta_roma(archivio_roma.percorso)
    proposta = _ok(client.get('/api/napoli/lotti/proposta'))
    lotto = next((x for x in _ok(client.get('/api/napoli/lotti')) if x['numero_lotto'] == 1), None)
    if lotto is None:
        lotto = _ok(client.post('/api/napoli/lotti/procedura', json={
            'lotto': dict(proposta['lotto'], municipalita='1 e 2'), 'tariffe': proposta['tariffe'],
            'valido_da': proposta['valido_da'], 'valido_a': proposta['valido_a']}))['lotto']
    client.lotto_id = lotto['id']
    dati = ns.leggi_bytes(str(tmp_path / 'omonimi'), omonimi=True)[0]
    a, esito = importa(client, dati)
    assert esito['import_id'] or esito['nessun_cambiamento']
    nomi = {(r['cognome'], r['nome']) for r in righe(archivio_roma.percorso, 'SELECT cognome, nome FROM napoli_alunni')}
    assert ('ESEMPIO', 'ALBA') in nomi and ('CAMPIONE', 'GAIA') in nomi
    assert seme_napoli.impronta_roma(archivio_roma.percorso) == roma_prima, "l'import di Napoli ha toccato Roma"

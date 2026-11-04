"""Sezione Napoli, passi 1.4-1.5: import del foglio presenze mensile (master).

Sul master inventato (tests/napoli_sintetico.py, 41 righe, 1.554 ore):
- anteprima senza scritture: totali attesi per figura dalle celle dei giorni (la
  VERIFICA non conta), avvisi per codice, ore da confermare ("1,30"), grado proposto
  dal codice meccanografico, la stessa scuola in due municipalita' = due plessi da
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


def conferma(client, dati, a, scelte=None, nome='master_marzo.xlsx', sha=None, versione=None):
    return client.post('/api/napoli/import/conferma', content_type='multipart/form-data', data={
        'file': (io.BytesIO(dati), nome), 'lotto_id': str(client.lotto_id), 'sha256': sha or a['file']['sha256'],
        'versione_dati': versione or a['versione_dati'], 'scelte': json.dumps(scelte or {})})


def importa(client, dati, scelte=None):
    """Anteprima e conferma con le proposte e le conferme richieste."""
    a = _ok(anteprima(client, dati, scelte))
    scelte = dict(scelte or {}, conferme=a['conferme_richieste'])
    return a, _ok(conferma(client, dati, a, scelte))


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
    assert [r['minuti'] for r in lettura['righe']] == atteso['minuti_per_riga']
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


def test_ore_da_confermare_proposta_e_scelta(napoli, master):
    dati, atteso = master
    a = _ok(anteprima(napoli, dati))
    [x] = a['ore_ambigue']
    assert (x['testo'], x['proposta'], x['scelta']) == ('1,30', 'ore_e_minuti', 'ore_e_minuti')
    assert {alt['lettura']: alt['minuti'] for alt in x['alternative']} == {'ore_e_minuti': 90, 'decimale': 78}
    b = _ok(anteprima(napoli, dati, {'ore_ambigue': {x['chiave']: 'decimale'}}))
    assert b['totale']['minuti'] == atteso['totale_minuti'] - 12
    _errore(anteprima(napoli, dati, {'ore_ambigue': {x['chiave']: 'forse'}}), 400, 'SCELTE_NON_VALIDE')


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
    a = _ok(anteprima(napoli, dati))
    assert a['conferme_richieste'] == ['plessi']
    [conf] = a['conferme']
    assert 'NAIC8ZZ001' in conf['voci'][0]['testo'] and '1 e 2' in conf['voci'][0]['testo']
    _errore(conferma(napoli, dati, a), 400, 'DA_CONFERMARE')
    assert righe(napoli.percorso, 'SELECT COUNT(*) AS n FROM napoli_scuole')[0]['n'] == 0
    _ok(conferma(napoli, dati, a, {'conferme': ['plessi']}))
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
    assert q['ASS. ALLA COMUNICAZIONE']['proposta'] == 'ASACOM' and q['OPERATORE SOCIALE']['proposta'] is None
    assert [g['codice'] for g in a['bloccanti']] == ['qualifica_non_collegata']
    _errore(conferma(napoli, dati, a), 400, 'IMPORT_BLOCCATO')
    _a, esito = importa(napoli, dati, {'qualifiche': {'OPERATORE SOCIALE': 'EDUCATORE'}})
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
    a = _ok(anteprima(napoli, dati))
    prima = seme_napoli.impronta_napoli(napoli.percorso)
    monkeypatch.setattr(db_mod, 'create_backup', lambda *x, **k: None)
    e = _errore(conferma(napoli, dati, a), 503, 'COPIA_NON_RIUSCITA')
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
    dati, _atteso = master
    importa(napoli, dati)
    [p] = righe(napoli.percorso, "SELECT * FROM napoli_presenze WHERE data = '2026-03-03' ORDER BY id LIMIT 1")
    esegui(napoli.percorso, "UPDATE napoli_presenze SET origine = 'foglio', minuti_riconosciuti = 45, import_id = NULL "
                            'WHERE id = ?', (p['id'],))
    a = _ok(anteprima(napoli, dati))
    assert a['conteggi']['presenze']['manuali_diverse'] == 1 and len(a['manuali_diverse']) == 1
    m = a['manuali_diverse'][0]
    assert m['data'] == '2026-03-03' and m['assisto'] == '0:45 (0,75)' and m['alunno'] and m['operatore']
    assert a['nessun_cambiamento']           # se non si sceglie, il file non cambia niente
    b = _ok(anteprima(napoli, dati, {'sovrascrivi_manuali': True}))
    assert not b['nessun_cambiamento'] and b['conteggi']['presenze']['sovrascritte'] == 1
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
    r = napoli.get('/napoli/import')
    assert r.status_code == 200
    testo = r.get_data(as_text=True)
    assert 'Importa il foglio presenze del mese' in testo and 'NapoliImport.avvia()' in testo
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

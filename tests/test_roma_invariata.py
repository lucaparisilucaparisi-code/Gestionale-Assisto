"""VR3 e VR4: Roma non cambia quando nel database c'e' anche Napoli; ogni rotta e' classificata.

- Invarianza: sull'archivio Roma inventato si fotografa Roma, si carica il seme
  Napoli (tests/seme_napoli.py) e si rifotografa: le due fotografie devono essere
  uguali, le tabelle di Roma (schema e righe) intatte e le letture di Roma non
  devono toccare le tabelle di Napoli. Il seme riempie tutte le tabelle napoli_*
  (tests/test_napoli_schema.py lo controlla): ogni passo di Napoli lo arricchisce e
  il test resta questo.
- Scritture di Roma su due database gemelli, con e senza Napoli (stesso archivio
  Roma, stesso orologio): chiusura e riapertura del mese, copia del mese
  precedente, compila con media, import della prefattura, dell'anagrafica utenti e
  dei dipendenti, wizard del nuovo anno, reset (anche "tutto"). Dopo ogni
  scrittura le risposte e le tabelle di Roma dei due gemelli sono uguali e quelle
  di Napoli non sono cambiate: il reset di Roma non cancella Napoli.
- Inventario: ogni rotta di app.url_map sta in ROTTE_ROMA, ROTTE_NAPOLI o ESCLUSE
  (strumenti/fotografa_roma.py); una rotta nuova non classificata fa fallire il test.

Solo dati inventati.
"""
import contextlib
import datetime
import io
import os
import sqlite3

import openpyxl

import config
import roma_sintetico
import seme_napoli
from strumenti import fotografa_roma

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_roma_non_cambia_con_i_dati_di_napoli(database_isolato, app_module, db_mod):
    client = fotografa_roma.client_fotografia(app_module.app, db_mod)
    roma_sintetico.costruisci_archivio(client, fotografa_roma.orologio_fermo)
    versione = fotografa_roma.leggi_versione(ROOT)

    prima = fotografa_roma.fotografa_sintetico(client, database_isolato, roma_sintetico, versione)
    tabelle_roma = seme_napoli.impronta_roma(database_isolato)

    seme_napoli.carica_seme_napoli(client, database_isolato)
    assert seme_napoli.impronta_roma(database_isolato) == tabelle_roma, 'il seme Napoli ha toccato Roma'
    tabelle_napoli = seme_napoli.impronta_napoli(database_isolato)

    dopo = fotografa_roma.fotografa_sintetico(client, database_isolato, roma_sintetico, versione)
    assert dopo == prima, fotografa_roma.descrivi_differenze(prima, dopo)
    assert seme_napoli.impronta_napoli(database_isolato) == tabelle_napoli, 'le letture di Roma hanno toccato Napoli'


def test_inventario_rotte(app_module):
    regole = fotografa_roma.regole_applicazione(app_module.app)
    problemi = fotografa_roma.controlla_inventario(regole)
    assert problemi == [], '\n'.join(problemi)


def test_inventario_segnala_una_rotta_nuova(app_module):
    """Il controllo stesso: una rotta in piu' (di Roma o di Napoli) non classificata
    e una classificata che non esiste piu' vengono segnalate."""
    regole = fotografa_roma.regole_applicazione(app_module.app)
    nuove = dict(regole, **{'/api/prova-non-classificata': {'GET'}, '/api/napoli/prova': {'POST'}})
    problemi = fotografa_roma.controlla_inventario(nuove)
    assert any(p.startswith('/api/prova-non-classificata: rotta non classificata') for p in problemi)
    assert any(p.startswith('/api/napoli/prova: rotta non classificata') for p in problemi)
    senza = {r: m for r, m in regole.items() if r != '/api/stats'}
    assert any(p.startswith("/api/stats: in ROTTE_ROMA ma non esiste piu'") for p in
               fotografa_roma.controlla_inventario(senza))


# ==================== scritture di Roma su due gemelli (VR3, seconda parte) ====================

# Colonne scritte dall'orologio di SQLite (DEFAULT CURRENT_TIMESTAMP), che
# l'orologio fermo non ferma: due gemelli scritti in due secondi diversi le hanno
# diverse. Si confronta solo che ci siano.
COLONNE_OROLOGIO_SQLITE = {'import_cronologia': ('data',)}


def _tabelle_roma(percorso):
    return seme_napoli.impronta_roma(percorso, COLONNE_OROLOGIO_SQLITE)


def _conta(percorso, tabella):
    conn = sqlite3.connect(percorso)
    try:
        return conn.execute(f'SELECT COUNT(*) FROM {tabella}').fetchone()[0]
    finally:
        conn.close()


@contextlib.contextmanager
def _sul_database(monkeypatch, db_mod, percorso, cartella):
    """Il programma al lavoro sul database `percorso`, con backup e file caricati in
    `cartella` (i due gemelli fanno backup con lo stesso nome, all'ora ferma)."""
    with monkeypatch.context() as m:
        for nome in ('BACKUP_FOLDER', 'UPLOAD_FOLDER'):
            sotto = os.path.join(cartella, nome.lower())
            os.makedirs(sotto, exist_ok=True)
            m.setattr(config, nome, sotto)
        m.setattr(config, 'DATABASE_PATH', percorso)
        m.setattr(db_mod, 'DATABASE_PATH', percorso)
        db_mod.invalida_cache_auth()
        yield
    db_mod.invalida_cache_auth()


# Le scritture rifiutate di proposito: l'ora di un mese chiuso.
STATI_ATTESI = {'/api/rendicontazione/2026/3/batch': 409}


def _excel(righe, titolo=None, a1=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    if titolo:
        ws.title = titolo
    if a1:
        ws.append([a1])
    for r in righe:
        ws.append(r)
    dati = io.BytesIO()
    wb.save(dati)
    dati.seek(0)
    return dati


def _carica(client, url, dati, nome, **campi):
    return client.post(url, data=dict(campi, file=(dati, nome)), content_type='multipart/form-data')


def _prefattura():
    """Estratto prefattura di marzo 2026 (formato di import_rendicontazione): utenti
    dell'archivio, uno sconosciuto e la riga del totale."""
    righe = [['Commessa', 'Scuola', 'Utenti', "Totale ore lavorate in 100'", 'Pasti']]
    for _, commessa, scuola, nome, cognome, monte in roma_sintetico.UTENTI[:6]:
        righe.append([commessa, scuola, f'{cognome} {nome}', monte * 4 + 0.25, 3])
    righe += [[roma_sintetico.SUD, roma_sintetico.STELLA, 'Sconosciuta Persona', 12, None],
              ['Totale', None, None, 999, 9]]
    return _excel(righe, 'Estratto Marzo', 'ESTRATTO MARZO 2026')


def _anagrafica():
    return _excel([['Commessa', 'Albero Attività', 'Attività', 'Monte Ore Sett.'],
                   [roma_sintetico.NORD, roma_sintetico.GALILEO, 'Gemella Prova', 7.5],
                   [roma_sintetico.NORD, roma_sintetico.ARCOBALENO, 'Esempio Alba', 12],      # gia' presente
                   [roma_sintetico.SUD, 'IC Nuovo - Primaria Gemelli', 'Nuova Gemella', 9]])


def _dipendenti():
    # 'Operatore Primo' c'e' anche fra gli operatori di Napoli: l'import di Roma non li tocca
    return _excel([['Cognome', 'Nome', 'Qualifica', 'Monte ore contrattuale', 'Sede'],
                   ['Operatore', 'Primo', 'OEPAC', 26, 'Sede di prova'],
                   ['Gemello', 'Nuovo', 'OEPAC', 18, 'Sede di prova']])


def _scritture(ids):
    """[(nome, [(metodo, url, argomenti)])]: le scritture di Roma, nell'ordine."""
    u = ids['utenti']

    def json_(dati):
        return {'json': dati}

    return [
        ('chiusura del mese', [
            ('post', '/api/mese-chiuso/2026/3', {}),
            ('post', '/api/rendicontazione/2026/3/batch', json_({'updates': [{'utente_id': u['alba'],
                                                                                'ore_lavorate_60': 1}]})),
            ('get', '/api/mese-chiuso/2026/3', {}),
            ('delete', '/api/mese-chiuso/2026/3', {})]),
        ('compila con media', [
            ('post', '/api/rendicontazione/2026/4/compila-media', json_({})),
            ('post', '/api/rendicontazione/2026/5/compila-media', json_({'utente_ids': [u['dalia'], u['ivo']]}))]),
        ('copia del mese precedente', [
            ('post', '/api/rendicontazione/2026/5/copia-precedente', json_({'solo_vuoti': True})),
            ('post', '/api/rendicontazione/2026/6/copia-precedente', json_({'solo_vuoti': False}))]),
        ('import della prefattura', [
            ('carica', '/api/import-rendicontazione/preview', (_prefattura, 'prefattura_marzo.xlsx', {})),
            ('carica', '/api/import-rendicontazione', (_prefattura, 'prefattura_marzo.xlsx',
                                                       {'modalita': 'overwrite'}))]),
        ("import dell'anagrafica", [
            ('carica', '/api/import-excel/preview', (_anagrafica, 'anagrafica_gemelli.xlsx', {})),
            ('carica', '/api/import-excel', (_anagrafica, 'anagrafica_gemelli.xlsx', {'mode': 'update'})),
            ('carica', '/api/import-dipendenti/preview', (_dipendenti, 'dipendenti_gemelli.xlsx', {})),
            ('carica', '/api/import-dipendenti', (_dipendenti, 'dipendenti_gemelli.xlsx', {}))]),
        ('wizard del nuovo anno', [
            ('post', '/api/anno-scolastico/prepara', json_({'anno_scolastico': '2026-2027'})),
            ('get', '/api/anno-scolastico/utenti-anteprima?anno_scolastico=2026-2027', {}),
            ('post', '/api/anno-scolastico/prepara-utenti',
             json_({'anno_scolastico': '2026-2027', 'chiudi_variazioni': True,
                    'monte_ore': {str(u['gaia']): 20}, 'archivia': [u['bruno']]}))]),
        ('reset delle rendicontazioni', [('post', '/api/reset', json_({'type': 'rendicontazioni',
                                                                        'confirm': 'CONFERMA'}))]),
        ('reset degli utenti', [('post', '/api/reset', json_({'type': 'utenti', 'confirm': 'CONFERMA'}))]),
        ('reset di tutto', [('post', '/api/reset', json_({'type': 'all', 'confirm': 'CONFERMA'}))]),
    ]


def _esegui(client, passi, norm):
    esiti = []
    for metodo, url, argomenti in passi:
        if metodo == 'carica':
            crea, nome, campi = argomenti
            r = _carica(client, url, crea(), nome, **campi)
        else:
            r = getattr(client, metodo)(url, **argomenti)
        esiti.append((url, fotografa_roma.leggi_risposta(r, norm)))
    return esiti


def test_scritture_di_roma_uguali_con_e_senza_napoli(database_isolato, app_module, db_mod, tmp_path, monkeypatch):
    client = fotografa_roma.client_fotografia(app_module.app, db_mod)
    ids = roma_sintetico.costruisci_archivio(client, fotografa_roma.orologio_fermo)
    gemelli = {'con': database_isolato, 'senza': str(tmp_path / 'senza_napoli.db')}
    fotografa_roma.copia_database(database_isolato, gemelli['senza'])
    seme_napoli.carica_seme_napoli(client, gemelli['con'])
    napoli = seme_napoli.impronta_napoli(gemelli['con'])
    assert _tabelle_roma(gemelli['con']) == _tabelle_roma(gemelli['senza'])
    norm = fotografa_roma.Normalizzatore(fotografa_roma.leggi_versione(ROOT))

    for n, (nome, passi) in enumerate(_scritture(ids)):
        quando = datetime.datetime(2026, 5, 4, 9, 0) + datetime.timedelta(hours=n)
        esiti = {}
        for gemello, percorso in gemelli.items():
            with _sul_database(monkeypatch, db_mod, percorso, str(tmp_path / gemello)):
                with fotografa_roma.orologio_fermo(quando):
                    esiti[gemello] = _esegui(client, passi, norm)
        assert esiti['con'] == esiti['senza'], f'{nome}: risposte diverse con i dati di Napoli'
        stati = [(url, esito['stato']) for url, esito in esiti['con']]
        assert stati == [(url, STATI_ATTESI.get(url, 200)) for url, _ in stati], (nome, stati)
        assert _tabelle_roma(gemelli['con']) == _tabelle_roma(gemelli['senza']), \
            f'{nome}: le tabelle di Roma sono diverse con i dati di Napoli'
        assert seme_napoli.impronta_napoli(gemelli['con']) == napoli, f'{nome}: ha toccato i dati di Napoli'

    # le scritture hanno fatto davvero qualcosa, e il reset ha svuotato Roma ma non Napoli
    for gemello in gemelli.values():
        assert [_conta(gemello, t) for t in ('utenti', 'rendicontazione', 'scuole')] == [0, 0, 0]
        assert _conta(gemello, 'dipendenti') == len(roma_sintetico.OPERATORI) + 2
        assert _conta(gemello, 'import_cronologia') == 1 + 3          # quello dell'archivio e i tre di qui
    assert _conta(gemelli['con'], 'napoli_presenze') > 0 and _conta(gemelli['con'], 'napoli_alunni') == 4
    assert _conta(gemelli['senza'], 'napoli_presenze') == 0

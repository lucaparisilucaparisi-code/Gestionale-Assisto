"""Grafica, lotto 3 (Rendicontazione, Chiusura Mese, Calendario, stampa).

Guardie su cio' che le schermate non ricontrollano da sole:
- lo scostamento dal mese precedente si confronta PER GIORNO LAVORATIVO (a giugno,
  con 8 giorni contro i ~20 di maggio, tutte le righe risultavano in calo del 60%)
  e a settembre il mese precedente e' giugno, come per "Copia Mese Prec.";
- la riga "Totale" di ogni scuola non deve tornare a spostarsi di una colonna
  (uno pseudo-elemento con content su un <tr> diventa una cella in piu');
- chiudere e riaprire un mese chiede conferma e il testo non dice piu' il contrario
  del vero ("non blocca eventuali correzioni").
"""
import os
import re

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _leggi(path):
    with open(os.path.join(PROJECT_DIR, path), encoding='utf-8') as f:
        return f.read()


def _prepara_utente(db, commessa, scuola, nome):
    db.create_commessa(commessa)
    sid = db.get_or_create_scuola(commessa, scuola)
    return db.get_or_create_utente(sid, nome, 'Confronto', 10)


def test_scostamento_confrontato_per_giorno_lavorativo(client, db_mod):
    db = db_mod
    uid = _prepara_utente(db, 'L3 CONFRONTO', 'IC Confronto - Scuola Primaria', 'Giorni')
    # maggio 20 giorni, giugno 8: stesse ore al giorno (2 h), ore grezze -60%
    db.set_calendario('2029-2030', 5, 2030, 20)
    db.set_calendario('2029-2030', 6, 2030, 8, 8)
    for mese, ore in ((5, 40), (6, 16)):
        db.get_or_create_rendicontazione(uid, 2030, mese)
        db.update_rendicontazione(uid, 2030, mese, ore_lavorate=ore)

    r = client.get('/api/rendicontazione/2030/6/confronto-precedente?commessa=L3%20CONFRONTO')
    assert r.status_code == 200
    d = r.get_json()['differenze'][str(uid)]
    assert d['differenza_perc'] == -60.0            # ore grezze: invariato per compatibilita'
    assert d['giorni_precedente'] == 20 and d['giorni_corrente'] == 8
    assert d['ore_giorno_precedente'] == 2.0 and d['ore_giorno_corrente'] == 2.0
    assert d['scostamento_giornaliero_perc'] == 0.0  # nessun allarme: stesse ore al giorno


def test_scostamento_assente_sulle_righe_vuote(client, db_mod):
    db = db_mod
    uid = _prepara_utente(db, 'L3 VUOTO', 'IC Vuoto - Scuola Primaria', 'Vuoto')
    db.set_calendario('2029-2030', 3, 2030, 20)
    db.set_calendario('2029-2030', 4, 2030, 15)
    db.get_or_create_rendicontazione(uid, 2030, 3)
    db.update_rendicontazione(uid, 2030, 3, ore_lavorate=30)
    db.get_or_create_rendicontazione(uid, 2030, 4)   # aprile ancora senza ore

    d = client.get('/api/rendicontazione/2030/4/confronto-precedente?commessa=L3%20VUOTO') \
        .get_json()['differenze'][str(uid)]
    assert d['scostamento_giornaliero_perc'] is None  # niente "-100%" sulle righe vuote


def test_confronto_di_settembre_usa_giugno(client, db_mod):
    db = db_mod
    uid = _prepara_utente(db, 'L3 SETTEMBRE', 'IC Settembre - Scuola Primaria', 'Settembre')
    db.set_calendario('2029-2030', 6, 2030, 10, 10)
    db.set_calendario('2030-2031', 9, 2030, 20)
    db.get_or_create_rendicontazione(uid, 2030, 6)
    db.update_rendicontazione(uid, 2030, 6, ore_lavorate=20)
    db.get_or_create_rendicontazione(uid, 2030, 9)
    db.update_rendicontazione(uid, 2030, 9, ore_lavorate=60)

    dati = client.get('/api/rendicontazione/2030/9/confronto-precedente?commessa=L3%20SETTEMBRE').get_json()
    assert (dati['mese_precedente']['anno'], dati['mese_precedente']['mese']) == (2030, 6)
    d = dati['differenze'][str(uid)]
    assert d['ore_precedente'] == 20                 # prima confrontava con agosto (vuoto)
    assert d['scostamento_giornaliero_perc'] == 50.0  # 3 h/giorno contro 2


def test_riga_totale_scuola_senza_cella_in_piu():
    # premium-effects.css ha ancora .scuola-totale::before con content: refine.css
    # deve annullarlo, altrimenti gli importi scalano di una colonna.
    refine = re.sub(r'/\*.*?\*/', '', _leggi('static/css/refine.css'), flags=re.S)
    assert re.search(r'\.scuola-totale::before\s*\{[^}]*content:\s*none\s*!important', refine)
    tpl = _leggi('templates/rendicontazione.html')
    riga = re.search(r'<tr class="scuola-totale">(.*?)</tr>', tpl, re.S).group(1)
    colonne = sum(int(c or 1) for c in re.findall(r'<td(?:[^>]*colspan="(\d+)")?[^>]*>', riga))
    intestazioni = re.search(r'<table class="table tabella-rend">.*?<tr>(.*?)</tr>', tpl, re.S).group(1)
    assert colonne == intestazioni.count('<th'), 'la riga Totale deve avere tante celle quante colonne'


def test_chiusura_mese_chiede_conferma_e_dice_il_vero():
    tpl = _leggi('templates/chiusura_mese.html')
    corpo = re.search(r'async function toggleMeseChiuso\(\)\s*\{(.*?)\n\}', tpl, re.S).group(1)
    assert 'showConfirmDialog' in corpo, 'chiudere/riaprire il mese deve chiedere conferma'
    assert 'non blocca eventuali correzioni' not in tpl

"""Grafica, lotto 4 (Dashboard, Statistiche, Report).

Guardie su cio' che le schermate non ricontrollano da sole:
- Avvisi e Validazione della Dashboard seguono il filtro commessa, come lo Stato
  del mese (prima con 'OEPAC V' lo Stato diceva 16 utenti e gli avvisi 35);
- ogni avviso ha una 'categoria' fissa, con cui la Dashboard evita di ripetere
  cio' che lo Stato del mese dice gia';
- la Dashboard non disegna piu' due volte gli stessi grafici (app.js li creava
  prima di dashboard.js e il secondo 'new Chart' andava in errore);
- i link dello Stato del mese non aprono in silenzio un mese diverso quando
  quello chiesto non ha ancora il calendario.
"""
import os
import re

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _leggi(path):
    with open(os.path.join(PROJECT_DIR, path), encoding='utf-8') as f:
        return f.read()


def _due_commesse(db):
    """Due commesse con un utente senza ore ciascuna (anno lontano: nessun altro dato)."""
    ids = {}
    for nome, persona in (('L4 ALFA', 'Alfa'), ('L4 BETA', 'Beta')):
        db.create_commessa(nome)
        sid = db.get_or_create_scuola(nome, f'IC {persona} - Scuola Primaria')
        ids[nome] = db.get_or_create_utente(sid, persona, 'Lotto4', 10)
    return ids


def test_avvisi_seguono_la_commessa(client, db_mod):
    _due_commesse(db_mod)
    tutti = client.get('/api/alerts?anno=2031&mese=10').get_json()
    solo_alfa = client.get('/api/alerts?anno=2031&mese=10&commessa=L4%20ALFA').get_json()

    def senza_ore(dati):
        return next(a for a in dati['alerts'] if a['categoria'] == 'senza_ore')['count']

    # l'utente di L4 BETA non conta piu' quando il filtro e' su L4 ALFA
    assert senza_ore(solo_alfa) == 1
    assert senza_ore(tutti) > senza_ore(solo_alfa)
    assert solo_alfa['commessa'] == 'L4 ALFA'


def test_avvisi_hanno_una_categoria(client, db_mod):
    _due_commesse(db_mod)
    dati = client.get('/api/alerts?anno=2031&mese=10').get_json()
    categorie = {a['categoria'] for a in dati['alerts']}
    assert {'senza_ore', 'completamento'} <= categorie


def test_validazione_segue_la_commessa(client, db_mod):
    _due_commesse(db_mod)
    tutti = client.get('/api/stats/validazione?anno=2031&mese=10').get_json()
    solo_beta = client.get('/api/stats/validazione?anno=2031&mese=10&commessa=L4%20BETA').get_json()

    def mancanti(dati):
        return next(a for a in dati['anomalie'] if a['categoria'] == 'ore_mancanti')

    assert mancanti(solo_beta)['conteggio'] == 1
    assert [d['nome'] for d in mancanti(solo_beta)['dettagli']] == ['Beta Lotto4']
    assert mancanti(tutti)['conteggio'] > 1


def test_dashboard_disegna_i_grafici_una_volta_sola():
    app_js = _leggi('static/js/app.js')
    # la vecchia funzione disegnava ciambella e linea prima di dashboard.js
    assert 'loadDashboardStats' not in app_js
    dash = _leggi('static/js/dashboard.js')
    # ogni grafico libera prima la tela (Chart.getChart) invece di andare in errore
    for m in re.finditer(r'new Chart\(\s*(\w+)', dash):
        prima = dash[:m.start()]
        funzione = prima[prima.rfind('function '):]   # corpo della funzione fin qui
        assert f'Chart.getChart({m.group(1)})' in funzione, m.group(0)


def test_link_a_un_mese_senza_calendario_non_apre_in_silenzio_un_altro_mese():
    """Settembre, prima di preparare il calendario: le righe dello Stato del mese
    portavano a /rendicontazione?anno=2026&mese=9&cerca=..., che apriva settembre
    dell'anno prima gia' filtrato su quel nome (dove l'utente aveva le ore)."""
    rend = _leggi('templates/rendicontazione.html')
    corpo = rend[rend.index('function impostaMenuPeriodo'):]
    corpo = corpo[:corpo.index('\n}\n')]
    assert 'return false' in corpo and 'return true' in corpo
    # ?cerca= e ?senza_ore=1 valgono solo se si e' aperto proprio il mese chiesto
    avvio = rend[rend.index('const qAnno'):rend.index("getElementById('btn-load')")]
    guardia = avvio.index('if (meseChiestoAperto)')
    assert avvio.index('cercaIniziale =') > guardia
    assert avvio.index('soloSenzaOre =') > guardia
    assert 'avvisaMeseNonApribile' in avvio
    # la Dashboard sa quali anni hanno il calendario (stesso elenco del menu della Rendicontazione)
    dash = _leggi('static/js/dashboard.js')
    stato = dash[dash.index('async function loadStatoMese'):dash.index('// ==================== DA FARE')]
    assert "/api/anni-scolastici" in stato and 'apribile' in stato


def test_confronto_mese_per_giorno_lavorativo(client, db_mod):
    """Giugno (8 giorni) contro maggio (20): stesse ore al giorno, nessun calo."""
    db = db_mod
    db.create_commessa('L4 CONFRONTO')
    sid = db.get_or_create_scuola('L4 CONFRONTO', 'IC Confronto L4 - Scuola Primaria')
    uid = db.get_or_create_utente(sid, 'Giorni', 'Lotto4', 10)
    db.set_calendario('2031-2032', 5, 2032, 20)
    db.set_calendario('2031-2032', 6, 2032, 8, 8)
    for mese, ore in ((5, 40), (6, 16)):
        db.get_or_create_rendicontazione(uid, 2032, mese)
        db.update_rendicontazione(uid, 2032, mese, ore_lavorate=ore)

    d = client.get('/api/stats/confronto-mese?anno=2032&mese=6&commessa=L4%20CONFRONTO').get_json()
    assert d['variazione']['percentuale'] == -60.0          # ore totali: invariato
    assert d['mese_corrente']['giorni_lavorativi'] == 8
    assert d['mese_precedente']['giorni_lavorativi'] == 20
    assert d['variazione']['percentuale_giornaliera'] == 0.0  # 2 h al giorno in entrambi


def test_confronto_mese_di_settembre_usa_giugno(client, db_mod):
    d = client.get('/api/stats/confronto-mese?anno=2032&mese=9').get_json()
    assert (d['mese_precedente']['anno'], d['mese_precedente']['mese']) == (2032, 6)


def test_utenti_meno_ore_seguono_la_commessa(client, db_mod):
    """Statistiche: '10 utenti con meno ore' segue il filtro commessa come gli altri riquadri."""
    db = db_mod
    ids = _due_commesse(db)
    db.set_calendario('2031-2032', 10, 2031, 20)
    for uid in ids.values():
        db.get_or_create_rendicontazione(uid, 2031, 10)
        db.update_rendicontazione(uid, 2031, 10, ore_lavorate=5)
    solo_alfa = client.get('/api/stats/utenti-meno-ore/2031/10?commessa=L4%20ALFA').get_json()
    assert [u['commessa'] for u in solo_alfa] == ['L4 ALFA']
    solo_beta = client.get('/api/stats/utenti-meno-ore/2031/10?commessa=L4%20BETA').get_json()
    assert [u['nome'] for u in solo_beta] == ['Beta']

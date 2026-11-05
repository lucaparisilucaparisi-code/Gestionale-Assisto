"""Roma: difetti di visualizzazione (passo roma-visualizzazione). Nessun calcolo cambia.

- Monte ore del MESE (variazioni comprese) dove una pagina lo mostra per un mese:
  Chiusura mese, anteprima dei Report e dettaglio (storico) della Rendicontazione
  lo prendono da monte_ore_effettivo di /api/rendicontazione, come la tabella della
  Rendicontazione; Dashboard e Statistiche sommano quello del mese di oggi con la
  stessa funzione (monteOreSettimanaleOggi di app.js), eseguita qui con node.
- Plurali: "1 utente senza ore registrate", "1 documento in scadenza", "1 utente non
  ha ore registrate questo mese"... (avvisi della Dashboard, controlli di Chiusura
  mese, notifica di fine mese, Relazione Word, annulla della modifica massiva,
  registro attivita', messaggi delle pagine, "e un altro" dopo i primi nomi).
- Confronti: "Utenti con dati" (Statistiche) e "Utenti in servizio" (Report) nei due
  confronti annuali, con la variazione nella stessa riga (l'anno piu' recente,
  rispetto all'anno prima) e le stesse note: la funzione del Report, eseguita con
  node, da' le variazioni di /api/stats/confronto-annuale-dettaglio; il Confronto
  mese dice che e' per giorno di scuola.

Solo dati inventati.
"""
import datetime as dt
import io
import json
import os
import re
import shutil
import subprocess

import pytest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _leggi(path):
    with open(os.path.join(PROJECT_DIR, path), encoding='utf-8') as f:
        return f.read()


def _utenti(db, n, monte=12, commessa='VIS PROVA', scuola='IC Vis - Primaria Prova'):
    db.create_commessa(commessa)
    sid = db.get_or_create_scuola(commessa, scuola)
    return [db.get_or_create_utente(sid, f'Nome{i}', f'Prova{i}', monte) for i in range(n)]


@pytest.fixture
def cliente(database_isolato, app_module, db_mod):
    """Client autenticato su un database vuoto del test (accesso configurato)."""
    from strumenti.fotografa_roma import client_fotografia
    return client_fotografia(app_module.app, db_mod)


def _scrivi_ore(client, anno, mese, ore_per_utente):
    r = client.post(f'/api/rendicontazione/{anno}/{mese}/batch', json={
        'updates': [{'utente_id': u, 'ore_lavorate_60': o} for u, o in ore_per_utente.items()]})
    assert r.status_code == 200, r.get_json()


def _funzione_js(testo, nome):
    """Il sorgente di `function nome(` (anche async) di una pagina, fino alla graffa di
    chiusura a inizio riga."""
    inizio = testo.index(f'function {nome}(')
    if testo[max(0, inizio - 6):inizio] == 'async ':
        inizio -= 6
    return testo[inizio:testo.index('\n}\n', inizio) + 2]


def _mesi_js():
    app_js = _leggi('static/js/app.js')
    inizio = app_js.index('const MESI = {')
    return app_js[inizio:app_js.index('};', inizio) + 2]


# apiCall finto: risponde con le risposte vere del server (DATI.risposte), raccolte prima
# dal client del test; null = il server risponde con un errore
_API_FINTA = """
async function apiCall(url) {
    if (!(url in DATI.risposte)) throw new Error('indirizzo non previsto: ' + url);
    if (DATI.risposte[url] === null) throw new Error('errore del server');
    return DATI.risposte[url];
}
"""


def _node(codice, dati):
    """Esegue `codice` (che definisce `async function prova()`) in node con DATI e
    stampa il risultato di prova() in JSON."""
    node = shutil.which('node')
    if not node:
        pytest.skip("node non disponibile: le funzioni della pagina non si possono eseguire qui")
    programma = ("const DATI = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n" + codice +
                 "\nprova().then(x => process.stdout.write(JSON.stringify(x)))"
                 ".catch(e => { console.error(e); process.exit(1); });")
    r = subprocess.run([node, '-e', programma], input=json.dumps(dati), capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ==================== 1. MONTE ORE DEL MESE ====================

def test_monte_ore_del_mese_con_una_variazione_da_12_a_14(cliente, db_mod):
    """Variazione da 12 a 14 h da novembre 2025: la vista mensile (da cui leggono
    Chiusura mese, anteprima dei Report e storico della Rendicontazione) da' 12 a
    settembre e ottobre, 14 da novembre in poi; la base resta 12."""
    db = db_mod
    db.create_anno_scolastico(2025)
    (uid,) = _utenti(db, 1, monte=12)
    r = cliente.post(f'/api/utenti/{uid}/variazioni-monte-ore', json={'monte_ore': 14, 'mese_inizio': '2025-11'})
    assert r.status_code == 200, r.get_json()
    for anno, mese, atteso, variato in ((2025, 9, 12, False), (2025, 10, 12, False), (2025, 11, 14, True),
                                        (2025, 12, 14, True), (2026, 3, 14, True)):
        riga = next(d for d in cliente.get(f'/api/rendicontazione/{anno}/{mese}').get_json()['dati']
                    if d['utente_id'] == uid)
        assert (riga['monte_ore_effettivo'], riga['monte_ore_variato'], riga['monte_ore_settimanale']) == (
            atteso, variato, 12), (anno, mese)


def test_le_pagine_mostrano_il_monte_ore_del_mese():
    """Le tre pagine e la Dashboard mostrano monte_ore_effettivo, non la base."""
    chiusura = _leggi('templates/chiusura_mese.html')
    assert 'const monte = u.monte_ore_effettivo ?? u.monte_ore_settimanale;' in chiusura
    assert '${formatNumero(monte)} h/sett.' in chiusura
    assert '${formatNumero(u.monte_ore_settimanale)} h/sett.' not in chiusura

    report = _leggi('templates/report.html')
    anteprima = report[report.index('async function mostraAnteprima'):report.index('function chiudiAnteprima')]
    assert '${formatNumero(d.monte_ore_effettivo)}' in anteprima
    assert 'formatNumero(d.monte_ore_effettivo ?? d.monte_ore_settimanale)' in anteprima
    assert '<td class="text-right">${formatNumero(d.monte_ore_settimanale)}</td>' not in anteprima

    rend = _leggi('templates/rendicontazione.html')
    storico = rend[rend.index('async function showStoricoUtente'):rend.index('function filterByScuola')]
    assert 'allData.find(d => d.utente_id === utenteId)' in storico
    assert '${formatNumero(riga.monte_ore_effettivo)} h' in storico and '(base: ' in storico

    # Dashboard e Statistiche: la stessa funzione (app.js), nessuna somma fatta in casa
    dash = _leggi('static/js/dashboard.js')
    numeri = _funzione_js(dash, 'loadNumeri')
    assert 'monteOreSettimanaleOggi(filters.commessa)' in numeri
    assert "animateCounter(document.getElementById('stat-monte-ore'), Math.round(monte.totale), 1000);" in numeri
    assert 'monte_ore_settimanale' not in numeri and 'monte_ore_effettivo' not in numeri
    stat = _leggi('templates/statistiche.html')
    kpi = _funzione_js(stat, 'loadStatistiche')
    assert 'monteOreSettimanaleOggi(filters.commessa)' in kpi
    assert "getElementById('kpi-monte-ore'), Math.round(monte ? monte.totale : (stats.monte_ore_totale || 0))" in kpi
    app_js = _leggi('static/js/app.js')
    assert 'window.monteOreSettimanaleOggi = monteOreSettimanaleOggi;' in app_js


def _monte_ore_nella_pagina(cliente, oggi, commessa=''):
    """monteOreSettimanaleOggi di app.js eseguita in node, con l'orologio della pagina
    fermo a `oggi` e le risposte vere del server per gli indirizzi che chiede."""
    qs = f'?commessa={commessa.replace(" ", "%20")}' if commessa else ''
    utenti = f'/api/utenti{qs}'
    vista = f'/api/rendicontazione/{oggi.year}/{oggi.month}{qs}'
    risposte = {u: cliente.get(u).get_json() for u in (utenti, vista)}
    codice = '\n'.join([
        'const _DataVera = Date;',
        'globalThis.Date = class extends _DataVera { constructor(...a) { super(...(a.length ? a : [DATI.oggi])); } };',
        _mesi_js(), _API_FINTA,
        _funzione_js(_leggi('static/js/app.js'), 'sommaMonteOreDelMese'),
        _funzione_js(_leggi('static/js/app.js'), 'monteOreSettimanaleOggi'),
        'async function prova() {',
        '    const giusto = await monteOreSettimanaleOggi(DATI.commessa);',
        '    DATI.risposte[DATI.vista] = null;          // la vista del mese non risponde',
        '    const senzaVista = await monteOreSettimanaleOggi(DATI.commessa);',
        '    return { giusto, senzaVista };',
        '}',
    ])
    return _node(codice, {'oggi': oggi.isoformat(), 'commessa': commessa, 'vista': vista, 'risposte': risposte})


def test_dashboard_e_statistiche_sommano_il_monte_ore_del_mese_di_oggi(cliente, db_mod):
    """Marzo 2026: 12 -> 14 da marzo (conta 14), 10 -> 20 da maggio (ancora 10), chi
    comincia a maggio (non e' nella vista del mese: la base), un archiviato (fuori).
    La somma delle pagine e' 38, la base di /api/stats/advanced 36 (resta com'e')."""
    db = db_mod
    db.create_anno_scolastico(2025)
    a, b, c = _utenti(db, 3, commessa='VIS MONTE A', scuola='IC Vis - Primaria Monte A')
    (d,) = _utenti(db, 1, commessa='VIS MONTE B', scuola='IC Vis - Primaria Monte B')
    (archiviato,) = _utenti(db, 1, commessa='VIS MONTE B', scuola='IC Vis - Primaria Monte B2')
    with db.get_db_context() as conn:
        conn.execute('UPDATE utenti SET monte_ore_settimanale = 10 WHERE id = ?', (b,))
        conn.execute("UPDATE utenti SET monte_ore_settimanale = 8, data_inizio = '2026-05' WHERE id = ?", (c,))
        conn.execute('UPDATE utenti SET monte_ore_settimanale = 6 WHERE id = ?', (d,))
        conn.execute('UPDATE utenti SET monte_ore_settimanale = 30, attivo = 0 WHERE id = ?', (archiviato,))
        conn.execute("UPDATE commesse SET attiva = 0 WHERE nome NOT LIKE 'VIS %'")
    for uid, monte, da in ((a, 14, '2026-03'), (b, 20, '2026-05')):
        r = cliente.post(f'/api/utenti/{uid}/variazioni-monte-ore', json={'monte_ore': monte, 'mese_inizio': da})
        assert r.status_code == 200, r.get_json()

    oggi = dt.datetime(2026, 3, 10, 10, 0)
    tutte = _monte_ore_nella_pagina(cliente, oggi)
    assert tutte['giusto'] == {'totale': 38, 'delMese': True, 'titolo':
                               'Somma del monte ore settimanale degli utenti attivi a Marzo 2026, variazioni comprese'}
    assert tutte['senzaVista']['totale'] == 36 and tutte['senzaVista']['delMese'] is False
    assert cliente.get('/api/stats/advanced').get_json()['monte_ore_totale'] == 36    # base: invariata

    sola_a = _monte_ore_nella_pagina(cliente, oggi, 'VIS MONTE A')
    assert sola_a['giusto']['totale'] == 32 and sola_a['senzaVista']['totale'] == 30
    assert cliente.get('/api/stats/advanced?commessa=VIS%20MONTE%20A').get_json()['monte_ore_totale'] == 30
    # a febbraio la variazione di a non vale ancora: la somma e' quella delle basi
    assert _monte_ore_nella_pagina(cliente, dt.datetime(2026, 2, 10, 10, 0))['giusto']['totale'] == 36


# ==================== 2. PLURALI ====================

def test_quanti():
    import app as app_mod
    assert app_mod._quanti(0, 'utente', 'utenti') == '0 utenti'
    assert app_mod._quanti(1, 'utente', 'utenti') == '1 utente'
    assert app_mod._quanti(2, 'utente', 'utenti') == '2 utenti'


@pytest.mark.parametrize('n', [1, 2])
def test_avvisi_e_controlli_al_singolare_e_al_plurale(cliente, db_mod, n):
    """Con 1 e con 2: utenti senza ore, utenti sotto il 50% della media, documenti in
    scadenza (avvisi della Dashboard) e i controlli di Chiusura mese."""
    db = db_mod
    db.create_anno_scolastico(2025)
    senza = _utenti(db, n, commessa='VIS SENZA', scuola='IC Vis - Primaria Senza')
    sotto = _utenti(db, n, commessa='VIS SOTTO', scuola='IC Vis - Primaria Sotto')
    pieni = _utenti(db, 2, commessa='VIS PIENI', scuola='IC Vis - Primaria Pieni')
    righe = {u: 1 for u in sotto}                      # molto meno della media prevista
    previste = next(d for d in cliente.get('/api/rendicontazione/2025/10').get_json()['dati']
                    if d['utente_id'] == pieni[0])['media_con_assenza_60']
    righe.update({u: previste for u in pieni})
    _scrivi_ore(cliente, 2025, 10, righe)
    scadenza = (dt.date.today() + dt.timedelta(days=10)).isoformat()   # documenti: date('now') di SQLite
    for u in senza:
        db.add_documento_utente(u, f'vis_{u}.pdf', 'certificato.pdf', 'Certificato', data_scadenza=scadenza)
    with db.get_db_context() as conn:   # le commesse iniziali del database vuoto non contano
        conn.execute("UPDATE commesse SET attiva = 0 WHERE nome NOT LIKE 'VIS %'")
    db.create_commessa('VIS VUOTA 1')
    if n == 2:
        db.create_commessa('VIS VUOTA 2')

    titoli = [a['title'] for a in cliente.get('/api/alerts?anno=2025&mese=10').get_json()['alerts']]
    messaggi = [a['messaggio'] for a in cliente.get('/api/stats/validazione?anno=2025&mese=10').get_json()['anomalie']]
    if n == 1:
        attesi_titoli = ['1 utente senza ore registrate', '1 utente con ore < 50% della media',
                         '1 documento in scadenza']
        attesi_messaggi = ['1 utente non ha ore registrate questo mese',
                           '1 utente con differenza >50% tra ore erogate e previste',
                           '1 commessa attiva non ha utenti associati']
    else:
        attesi_titoli = ['2 utenti senza ore registrate', '2 utenti con ore < 50% della media',
                         '2 documenti in scadenza']
        attesi_messaggi = ['2 utenti non hanno ore registrate questo mese',
                           '2 utenti con differenza >50% tra ore erogate e previste',
                           '2 commesse attive non hanno utenti associati']
    for t in attesi_titoli:
        assert t in titoli, titoli
    for m in attesi_messaggi:
        assert m in messaggi, messaggi
    tutto = ' '.join(titoli + messaggi)
    assert not re.search(r'\b1 (utenti|documenti|commesse|registrazioni)\b', tutto)


def test_plurali_delle_pagine_con_1_e_con_2():
    """quanti() di app.js e "e un altro" della lista "Da fare" della Dashboard (prima
    "… e altri 1"), eseguiti con node."""
    codice = '\n'.join([
        _funzione_js(_leggi('static/js/app.js'), 'quanti'),
        _funzione_js(_leggi('static/js/dashboard.js'), '_eAltri'),
        'async function prova() {',
        "    return [quanti(1, 'nuovo', 'nuovi'), quanti(2, 'nuovo', 'nuovi'), quanti(0, 'utente', 'utenti'),",
        "            _eAltri(1, false), _eAltri(2, false), _eAltri(1, true), _eAltri(3, true)];",
        '}',
    ])
    assert _node(codice, {}) == ['1 nuovo', '2 nuovi', '0 utenti', 'e un altro', 'e altri 2', "e un'altra", 'e altre 3']
    dash = _leggi('static/js/dashboard.js')
    assert ' … ${_eAltri(altri, v.femminile)}' in dash and ' … e altri ${altri}' not in dash
    assert "a.categoria === 'commesse_vuote'" in _funzione_js(dash, 'loadDaFare')


# Un numero seguito da una parola al plurale, senza scegliere il singolare per 1
_PLURALE_FISSO = re.compile(r'\$\{[^{}]+\} (nuovi|aggiornati|saltati|saltate|creati|importati|ambigui|ambigue|'
                            r'non abbinati|rendicontazioni|operatori|utenti|documenti|commesse|scuole|errori)\b')
_PLURALE_FISSO_CONCAT = re.compile(r"\+ ' (nuovi|aggiornati)\b|variazione/i")


@pytest.mark.parametrize('pagina', ['templates/import.html', 'templates/utenti.html', 'templates/report.html',
                                    'templates/statistiche.html', 'templates/chiusura_mese.html',
                                    'templates/rendicontazione.html', 'templates/commesse.html',
                                    'templates/calendario.html', 'templates/sostituzioni.html',
                                    'static/js/dashboard.js'])
def test_messaggi_delle_pagine_con_il_singolare(pagina):
    """Import (prima "1 operatori nel file", "1 nuovi", "1 creati, 1 aggiornati", "1
    rendicontazioni salvate"...), Utenti ("Importati: 1 nuovi"), e le altre pagine di Roma."""
    testo = _leggi(pagina)
    # il ramo "tanti" di una scelta gia' fatta per 1 (`n === 1 ? '1 utente' : `${n} utenti``) va bene
    fissi = [m.group(0) for m in _PLURALE_FISSO.finditer(testo)
             if not re.search(r'={2,3} 1 \?', testo[testo.rfind('\n', 0, m.start()) + 1:m.start()])]
    assert not fissi, fissi
    assert not _PLURALE_FISSO_CONCAT.findall(testo)
    if pagina == 'templates/import.html':
        assert "${d.totale === 1 ? 'operatore' : 'operatori'} nel file" in testo
        assert "quanti(data.totale_scritti, 'rendicontazione salvata', 'rendicontazioni salvate')" in testo
        assert "${data.totale_match === 1 ? 'rendicontazione pronta' : 'rendicontazioni pronte'} da importare" in testo
        # anteprima dell'anagrafica: prima "1 righe valide trovate su 1 righe totali"
        assert '<span id="preview-count"></span> su <span id="preview-total"></span>.' in testo
        assert "quanti(data.righe_valide, 'riga valida trovata', 'righe valide trovate')" in testo
        assert "quanti(data.totale_righe, 'riga totale', 'righe totali')" in testo


@pytest.mark.parametrize('n', [1, 2])
def test_registro_attivita_e_annulla_al_singolare(cliente, db_mod, n):
    """Registro attivita' (ore salvate, modifica massiva) e Ctrl+Z della modifica
    massiva: "1 utente aggiornato", "Modifica di 1 utente" (prima "1 utenti aggiornati",
    "Modifica di 1 utente insieme")."""
    db = db_mod
    db.create_anno_scolastico(2025)
    uids = _utenti(db, n)
    _scrivi_ore(cliente, 2025, 10, {u: 5 for u in uids})
    r = cliente.put('/api/utenti/bulk', json={'updates': [{'id': u, 'monte_ore': 15} for u in uids]})
    assert r.status_code == 200, r.get_json()
    voci = [a['dettagli'] or '' for a in cliente.get('/api/audit?limit=100').get_json()]
    undo = [a['descrizione'] for a in cliente.get('/api/undo').get_json() if a['tipo'] == 'bulk_update_utenti']
    if n == 1:
        assert 'Ottobre 2025: 1 utente aggiornato' in voci, voci
        assert '1 utente aggiornato in bulk' in voci
        assert undo == ["Modifica di 1 utente (monte ore e lista d'attesa)"]
    else:
        assert 'Ottobre 2025: 2 utenti aggiornati' in voci, voci
        assert '2 utenti aggiornati in bulk' in voci
        assert undo == ["Modifica di 2 utenti insieme (monte ore e lista d'attesa)"]
    assert not re.search(r'\b1 utenti\b', ' '.join(voci + undo))


def test_notifica_di_fine_mese_al_singolare(db_mod, database_isolato):
    from strumenti.fotografa_roma import orologio_fermo
    db = db_mod
    db.create_anno_scolastico(2025)
    _utenti(db, 1)
    with orologio_fermo(dt.datetime(2025, 10, 25, 9, 0)):
        db.genera_notifiche_automatiche()
    notifiche = [n for n in db.get_notifiche(solo_non_lette=False) if n['entita'] == 'rendicontazione_incompleta']
    assert [n['titolo'] for n in notifiche] == ['Rendicontazione incompleta: 1 utente senza ore']
    assert notifiche[0]['messaggio'].startswith('Il mese sta per chiudersi e 1 utente non ha ancora ore registrate')


def test_relazione_word_al_singolare(cliente, db_mod):
    import docx
    db = db_mod
    db.create_anno_scolastico(2025)
    (uid,) = _utenti(db, 1)
    _scrivi_ore(cliente, 2025, 10, {uid: 1})
    r = cliente.get('/api/export/word/2025/10')
    assert r.status_code == 200
    testo = '\n'.join(p.text for p in docx.Document(io.BytesIO(r.data)).paragraphs)
    assert 'un totale di 1 utente distribuito su 1 scuola.' in testo
    assert 'Si segnala 1 utente con un tasso di erogazione inferiore al 50%' in testo
    assert 'ore di assistenza a 1 utente, ' in testo
    assert not re.search(r'\b1 (utenti|scuole)\b', testo)


# ==================== 4. CONFRONTI ====================

def test_etichette_dei_confronti():
    stat = _leggi('templates/statistiche.html')
    annuale = stat[stat.index('async function loadConfrontoAnnualeDettaglio'):stat.index('async function loadUtentiMenoOre')]
    # conta le righe del mese, anche a 0 ore: non "con ore" come il Confronto mese
    assert '>Utenti con dati</th>' in annuale and '>Utenti</th>' not in annuale and '>Utenti con ore</th>' not in annuale
    assert 'il Confronto mese conta solo quelli con ore, Report › Confronto annuale tutti gli utenti in servizio' in annuale
    mese = stat[stat.index('async function loadConfrontoMese'):stat.index('async function loadTopScuole')]
    assert 'Ore per giorno di scuola' in mese and "${quanti(m.utenti_attivi, 'utente', 'utenti')} con ore</div>" in mese
    # i giorni di scuola su una riga loro: a 1366x768 il " ·" restava in fondo alla riga
    assert "${quanti(Math.round(m.giorni_lavorativi), 'giorno', 'giorni')} di scuola</div>" in mese
    assert ' · ${formatNumero(m.giorni_lavorativi' not in mese
    assert 'h al giorno</div>' in mese and 'Sulle ore totali: ' in mese
    assert 'giorno lavorativo' not in mese and 'giorni lav.' not in mese

    report = _leggi('templates/report.html')
    confronto = report[report.index('async function generaConfrontoAnnuale'):report.index('// Inizializza commessa')]
    assert '>Utenti in servizio</th>' in confronto and '>Utenti</th>' not in confronto
    assert 'Statistiche › Confronto annuale conta solo gli utenti con dati' in confronto
    assert 'variazioniConfrontoAnnuale(datiAnni, mese)' in confronto and 'datiAnni[i-1]' not in confronto


def _variazioni_del_report(cliente, mese, commessa, oggi):
    """datiConfrontoAnnuale e variazioniConfrontoAnnuale del Report eseguite in node,
    sulle risposte vere del server, con la data di oggi `oggi`."""
    report = _leggi('templates/report.html')
    anni = cliente.get('/api/anni-scolastici').get_json()
    qs = f'?commessa={commessa.replace(" ", "%20")}' if commessa else ''
    risposte = {'/api/anni-scolastici': anni}
    for a in anni[:5]:
        inizio, fine = map(int, a.split('-'))
        url = f'/api/rendicontazione/{inizio if mese >= 9 else fine}/{mese}{qs}'
        risposte[url] = cliente.get(url).get_json()
    codice = '\n'.join([
        _API_FINTA, _funzione_js(report, 'datiConfrontoAnnuale'), _funzione_js(report, 'variazioniConfrontoAnnuale'),
        'async function prova() {',
        "    const anni = await apiCall('/api/anni-scolastici');",
        '    const datiAnni = await datiConfrontoAnnuale(anni, String(DATI.mese), DATI.commessa);',
        '    const v = variazioniConfrontoAnnuale(datiAnni, String(DATI.mese), new Date(DATI.oggi));',
        '    return datiAnni.map((d, i) => [d.annoScolastico, d.oreTotal, v[i].diff, v[i].nota]);',
        '}',
    ])
    return _node(codice, {'mese': mese, 'commessa': commessa, 'oggi': oggi.isoformat(), 'risposte': risposte})


def test_report_e_statistiche_danno_le_stesse_variazioni(cliente, db_mod):
    """Confronto annuale del Report (calcolato nella pagina) e di Statistiche (dal
    server) sugli stessi anni: stessa riga (l'anno piu' recente), stesso segno, stesse
    note ("mese non ancora concluso", "dati non ancora inseriti") e -100% per un mese
    con le righe ma 0 ore (solo pasti), come gia' faceva Statistiche."""
    from strumenti.fotografa_roma import orologio_fermo
    db = db_mod
    for anno in range(2021, 2026):
        db.create_anno_scolastico(anno)
    a, b = _utenti(db, 2, commessa='VIS CONFRONTO', scuola='IC Vis - Primaria Confronto')
    (c,) = _utenti(db, 1, commessa='VIS ALTRA', scuola='IC Vis - Primaria Altra')
    # ottobre: +50% (45 contro 30), -25%, niente (anno prima a 0 ore), -100% (solo pasti)
    _scrivi_ore(cliente, 2025, 10, {a: 25, b: 20, c: 100})
    _scrivi_ore(cliente, 2024, 10, {a: 30})
    _scrivi_ore(cliente, 2023, 10, {a: 40})
    r = cliente.post('/api/rendicontazione/2022/10/batch', json={'updates': [{'utente_id': a, 'pasti': 4}]})
    assert r.status_code == 200, r.get_json()
    _scrivi_ore(cliente, 2021, 10, {a: 10})
    # marzo: mese in corso, niente (anno prima senza dati), senza dati, -20%
    _scrivi_ore(cliente, 2026, 3, {a: 50})
    _scrivi_ore(cliente, 2025, 3, {a: 30})
    _scrivi_ore(cliente, 2023, 3, {a: 20})
    _scrivi_ore(cliente, 2022, 3, {a: 25})

    oggi = dt.datetime(2026, 3, 10, 10, 0)
    attesi = {
        (10, 'VIS CONFRONTO'): [('2025-2026', 50.0, None), ('2024-2025', -25.0, None), ('2023-2024', None, None),
                                ('2022-2023', -100.0, None), ('2021-2022', None, None)],
        (3, ''): [('2025-2026', None, 'mese non ancora concluso'), ('2024-2025', None, None),
                  ('2023-2024', None, 'dati non ancora inseriti'), ('2022-2023', -20.0, None), ('2021-2022', None, None)],
    }
    with orologio_fermo(oggi):
        for (mese, commessa), attesa in attesi.items():
            qs = f'?mese={mese}' + (f'&commessa={commessa.replace(" ", "%20")}' if commessa else '')
            server = cliente.get(f'/api/stats/confronto-annuale-dettaglio{qs}').get_json()['confronto']
            assert [(r['anno_scolastico'], r['variazione'], r['nota']) for r in server] == attesa, (mese, server)
            pagina = _variazioni_del_report(cliente, mese, commessa, oggi)
            assert [(r[0], None if r[2] is None else round(r[2], 1), r[3]) for r in pagina] == attesa, (mese, pagina)
        # senza filtro ottobre 2025 conta anche l'altra commessa: (145 - 30) / 30
        tutte = _variazioni_del_report(cliente, 10, '', oggi)
        server = cliente.get('/api/stats/confronto-annuale-dettaglio?mese=10').get_json()['confronto']
        assert round(tutte[0][2], 1) == server[0]['variazione'] == 383.3


def test_confronto_annuale_di_statistiche_variazione_nella_riga_dell_anno_piu_recente(
        cliente, db_mod):
    """La regola che ora segue anche il Report: la variazione sta nella riga
    dell'anno piu' recente ed e' rispetto all'anno prima."""
    db = db_mod
    db.create_anno_scolastico(2023)
    db.create_anno_scolastico(2024)
    (uid,) = _utenti(db, 1)
    _scrivi_ore(cliente, 2023, 10, {uid: 40})
    _scrivi_ore(cliente, 2024, 10, {uid: 50})
    righe = cliente.get('/api/stats/confronto-annuale-dettaglio?mese=10').get_json()['confronto']
    assert [(r['anno_scolastico'], r['ore_erogate'], r['variazione']) for r in righe
            if r['anno_scolastico'] in ('2024-2025', '2023-2024')] == [('2024-2025', 50, 25.0), ('2023-2024', 40, None)]

"""Roma: difetti di visualizzazione (passo roma-visualizzazione). Nessun calcolo cambia.

- Monte ore del MESE (variazioni comprese) dove una pagina lo mostra per un mese:
  Chiusura mese, anteprima dei Report e dettaglio (storico) della Rendicontazione
  lo prendono da monte_ore_effettivo di /api/rendicontazione, come la tabella della
  Rendicontazione; la Dashboard somma quello del mese di oggi.
- Plurali: "1 utente senza ore registrate", "1 documento in scadenza", "1 utente non
  ha ore registrate questo mese"... (avvisi della Dashboard, controlli di Chiusura
  mese, notifica di fine mese, Relazione Word, annulla della modifica massiva).
- Confronti: "Utenti con ore" (Statistiche) e "Utenti in servizio" (Report) nei due
  confronti annuali, con la variazione nella stessa riga (l'anno piu' recente,
  rispetto all'anno prima); il Confronto mese dice che e' per giorno di scuola.

Solo dati inventati.
"""
import datetime as dt
import io
import os
import re

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

    dash = _leggi('static/js/dashboard.js')
    assert "apiCall(`/api/rendicontazione/${annoOggi}/${meseOggi}${qs}`)" in dash
    assert '.map(d => [d.utente_id, d.monte_ore_effettivo])' in dash
    assert 'sum + (u.monte_ore_settimanale || 0)' not in dash


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
    assert '>Utenti con ore</th>' in annuale and '>Utenti</th>' not in annuale
    assert 'conta tutti gli utenti in servizio, anche senza ore' in annuale
    mese = stat[stat.index('async function loadConfrontoMese'):stat.index('async function loadTopScuole')]
    assert 'Ore per giorno di scuola' in mese and "'utente' : 'utenti'} con ore" in mese
    assert 'h al giorno</div>' in mese and 'Sulle ore totali: ' in mese
    assert 'giorno lavorativo' not in mese and 'giorni lav.' not in mese

    report = _leggi('templates/report.html')
    confronto = report[report.index('async function generaConfrontoAnnuale'):report.index('// Inizializza commessa')]
    assert '>Utenti in servizio</th>' in confronto and '>Utenti</th>' not in confronto
    assert 'conta solo quelli con ore' in confronto
    # variazione nella riga dell'anno piu' recente rispetto all'anno prima (la riga sotto),
    # come Statistiche; prima era nella riga dell'anno prima, calcolata al contrario
    assert 'const prima = datiAnni[i + 1];' in confronto
    assert '(d.oreTotal - prima.oreTotal) / prima.oreTotal * 100' in confronto
    assert 'datiAnni[i-1]' not in confronto


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

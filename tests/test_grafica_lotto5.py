"""Grafica, lotto 5 (Utenti, Dipendenti, Turni, telefono).

Guardie su cio' che le schermate non ricontrollano da sole:
- il Profilo mostra la data di creazione dell'account e l'accesso in corso, che
  /api/auth/status ora restituisce (prima restavano sempre '—'), ma solo a chi
  ha gia' fatto l'accesso;
- una commessa nuova prende il blu dell'app, primo campione della tavolozza
  (prima un indaco fuori tavolozza: in 'Modifica' nessun colore risultava scelto);
- nella finestra 'Modifica commessa' scegliere un colore non sovrascrive piu' l'id
  della commessa (il campo nascosto preso era il primo, cioe' l'id);
- il menu laterale a pannello si chiude cliccando fuori e con Esc fino a 1024px;
- sul telefono i pulsanti non sono piu' tutti larghi quanto lo schermo;
- niente emoji come icone, niente cestini rossi pieni sulle righe, nomi delle
  scuole non tagliati nel codice;
- nelle schede i nomi delle persone restano su una riga, il Riepilogo ore e' 2x2
  e nel Profilo i valori sono allineati a destra anche quando vanno a capo.
"""
import os
import re

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _leggi(path):
    with open(os.path.join(PROJECT_DIR, path), encoding='utf-8') as f:
        return f.read()


def test_stato_auth_con_dati_dell_account(client):
    dati = client.get('/api/auth/status').get_json()
    assert dati['authenticated'] is True
    assert dati['data_creazione']            # data vera, non piu' il trattino
    assert 'ultimo_accesso' in dati and 'ultimo_accesso_metodo' in dati


def test_stato_auth_senza_accesso_non_mostra_i_dati(app_module):
    with app_module.app.test_client() as c:
        dati = c.get('/api/auth/status').get_json()
    assert dati['authenticated'] is False
    assert 'data_creazione' not in dati and 'ultimo_accesso' not in dati


def test_accesso_registrato_compare_nello_stato(app_module):
    with app_module.app.test_client() as c:
        assert c.post('/api/auth/login', json={'username': 'tester', 'password': 'secret'}).status_code == 200
        dati = c.get('/api/auth/status').get_json()
    assert dati['ultimo_accesso']
    assert dati['ultimo_accesso_metodo'] == 'password'


def test_colore_predefinito_della_commessa(client, db_mod):
    assert db_mod.COLORE_COMMESSA == '#3B82F6'
    r = client.post('/api/commesse', json={'nome': 'L5 SENZA COLORE'})
    assert r.status_code in (200, 201), r.get_json()
    commessa = next(c for c in client.get('/api/commesse').get_json() if c['nome'] == 'L5 SENZA COLORE')
    assert commessa['colore'].upper() == '#3B82F6'
    # stesso blu come primo campione della tavolozza (nuova e modifica)
    pagina = _leggi('templates/commesse.html')
    campioni = re.findall(r'class="color-btn[^"]*" data-color="(#[0-9A-Fa-f]{6})"', pagina)
    assert campioni[0].upper() == '#3B82F6' and campioni[6].upper() == '#3B82F6'
    assert '#6366f1' not in pagina.lower() and '#0a84ff' not in pagina.lower()


def test_scelta_colore_non_tocca_l_id_della_commessa():
    pagina = _leggi('templates/commesse.html')
    corpo = pagina[pagina.index("closest('.color-btn')"):]
    corpo = corpo[:corpo.index('});')]
    # il campo aggiornato e' quello del colore, mai il campo nascosto con l'id
    assert ":not(#edit-id)" in corpo


def test_menu_laterale_a_pannello_fino_a_1024():
    app_js = _leggi('static/js/app.js')
    sidebar = app_js[app_js.index('const SidebarManager'):app_js.index('// ==================== KEYBOARD SHORTCUTS')]
    assert 'innerWidth <= 768' not in sidebar
    assert "matchMedia('(max-width: 1024px)')" in sidebar
    assert "e.key === 'Escape'" in sidebar
    assert "'sidebar-open'" in sidebar
    refine = _leggi('static/css/refine.css')
    assert 'body.sidebar-open::after' in refine
    # fondo del menu pieno nel tema scuro (la pagina si leggeva attraverso)
    assert '--bg-sidebar: rgba(' not in _leggi('static/css/style.css')


def test_pulsanti_non_tutti_a_tutta_larghezza_sul_telefono():
    ux = re.sub(r'/\*.*?\*/', '', _leggi('static/css/ux-enhancements.css'), flags=re.S)
    # la regola generale '.btn { width: 100% }' (non quelle di un contenitore preciso)
    assert not re.search(r'(^|[{}])\s*\.btn\s*\{\s*width:\s*100%', ux)
    assert not re.search(r'\.btn\s*\+\s*\.btn\s*\{\s*margin-top', ux)


def test_niente_emoji_come_icone_e_niente_cestini_rossi_sulle_righe():
    for path in ('templates/utenti.html', 'templates/index.html'):
        pagina = _leggi(path)
        for emoji in ('👤', '✏️', '📈', '📦', '🗑', '♻️', '🎒', '👋'):
            assert emoji not in pagina, (path, emoji)
    turni = _leggi('templates/turni.html')
    assert "'>✎</button>" not in turni and "'>×</button>" not in turni
    # il rosso pieno resta solo ai pulsanti di conferma delle finestre
    for path in ('templates/utenti.html', 'templates/turni.html', 'templates/commesse.html',
                 'templates/utente_dettaglio.html'):
        assert 'btn btn-sm btn-danger' not in _leggi(path), path


def test_nomi_delle_scuole_non_tagliati_nel_codice():
    for path in ('templates/sostituzioni.html', 'templates/dipendente_dettaglio.html',
                 'templates/turni.html', 'templates/report.html'):
        pagina = _leggi(path)
        assert not re.search(r"scuola[^)]*\)\.substring\(0,\s*\d+\)", pagina), path
        assert 'cella-scuola' in pagina, path
    utenti = _leggi('templates/utenti.html')
    # i puntini solo se il nome e' davvero piu' lungo
    assert "+ '...</option>'" not in utenti and 'nomeBreve(' in utenti


def test_schede_senza_nomi_a_capo_e_riquadri_2x2():
    refine = _leggi('static/css/refine.css')
    # nomi su una riga accanto alla colonna Scuola (a 1366 'Barbieri / Alice')
    assert re.search(r"\.table td\.cella-nome\s*\{[^}]*white-space:\s*nowrap", refine)
    dip = _leggi('templates/dipendente_dettaglio.html')
    assert '<td class="cella-nome"><a href="/utente/' in dip
    # nelle card a meta' pagina la Scuola prende lo spazio che avanza, senza far
    # scorrere la tabella di lato a 1280-1366
    assert dip.count('class="table tabella-scheda"') == 2
    assert re.search(r"\.table\.tabella-scheda td\.cella-scuola\s*\{[^}]*max-width:\s*0", refine)
    # Riepilogo ore sempre 2x2 (con auto-fit a 1440 erano 3+1)
    assert re.search(r"\.ud-kpi-griglia\s*\{[^}]*repeat\(2,\s*minmax\(0,\s*1fr\)\)", refine)
    # Profilo: valori a destra anche quando vanno a capo
    profilo = _leggi('templates/profilo.html')
    assert re.search(r"\.info-value\s*\{[^}]*text-align:\s*right", profilo)


def test_elenco_utenti_non_usa_le_regole_della_rendicontazione():
    utenti = _leggi('templates/utenti.html')
    assert 'id="table-container"' not in utenti and "('table-container'" not in utenti
    assert 'prima-colonna-fissa' in utenti
    # una sola colonna 'Cognome e nome', come in Dipendenti
    assert '<th>Cognome e nome</th>' in utenti and "'<th>Nome</th>'" not in utenti

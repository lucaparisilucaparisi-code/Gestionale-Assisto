"""Grafica, lotto 6a (pulizia dello stile: le correzioni che si vedono).

Guardie su cio' che le schermate non ricontrollano da sole:
- niente piu' aloni, sfumature viola e movimenti su menu, barre dei filtri,
  caricamento, pagina di accesso, riquadri numerici, barre di avanzamento,
  riquadri vuoti e heatmap; una sola animazione d'ingresso delle pagine;
- ricerca rapida (Ctrl+K): scorciatoie indicate uguali a quelle vere (Alt+numero),
  nessun Ctrl+1..5 (in Chrome ed Edge cambia scheda), icone grigie e complete,
  Impostazioni e Profilo tra le voci;
- numeri nello stesso carattere del testo (niente 'JetBrains Mono' ne' monospace);
- pulsanti, tendine e caselle nel carattere della pagina;
- la X delle finestre e' una sola (macro modal_close) con il nome 'Chiudi';
- piccole rifiniture di testo e impaginazione (titoli senza spazi doppi, 'gia'').
"""
import os
import re

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _leggi(path):
    with open(os.path.join(PROJECT_DIR, path), encoding='utf-8') as f:
        return f.read()


def _blocchi(css, selettore):
    """Corpi delle regole il cui selettore e' esattamente `selettore`."""
    return re.findall(r'(?:^|\})\s*' + re.escape(selettore) + r'\s*\{([^}]*)\}', css, re.M)


def test_una_sola_animazione_d_ingresso_e_menu_senza_alone():
    premium = _leggi('static/css/premium-effects.css')
    assert 'animation: pageSlideIn' not in premium and '@keyframes pageSlideIn' not in premium
    style = _leggi('static/css/style.css')
    for sel in ('.nav-link.active', '[data-theme="light"] .nav-link.active'):
        for corpo in _blocchi(style, sel):
            assert 'box-shadow' not in corpo, sel
    refine = _leggi('static/css/refine.css')
    assert re.search(r'\.content-area > \* \{ animation: ds-fade-in', refine)
    assert '.filters::before { display: none !important; }' in refine
    assert '.nav-link::after, .nav-link span::after { display: none !important; }' in refine


def test_riquadri_barre_e_icone_senza_riflessi_ne_movimenti():
    """Gli effetti rimasti fuori dal menu: sottolineatura blu-viola e numero che si
    ingrandisce (Riepilogo Totali), riflesso che scorre sulle barre di avanzamento,
    anello attorno all'icona dei riquadri vuoti, icona del titolo che ruota, alone
    sulle caselle della heatmap, icona delle impronte sfumata."""
    refine = _leggi('static/css/refine.css')
    for regola in ('.stat-value::after { display: none !important; }',
                   '.stat-card:hover .stat-value { transform: none !important; }',
                   '.progress-bar-fill::after { display: none !important; }',
                   '.empty-state-icon-wrapper::before { display: none !important; }',
                   '.card:hover .card-title svg { transform: none !important; }'):
        assert regola in refine, regola
    heatmap = _blocchi(refine, '.heatmap-table .heatmap-cell:hover')
    assert heatmap and 'transform: none' in heatmap[0] and 'px var(--accent)' in heatmap[0]
    profilo = _leggi('templates/profilo.html')
    icona = re.search(r'\.credential-icon \{([^}]*)\}', profilo).group(1)
    assert 'gradient' not in icona and 'background: var(--accent)' in icona


def test_messaggi_info_col_bordo_come_gli_altri():
    style = _leggi('static/css/style.css')
    assert '.toast.info { border-left: 3px solid var(--primary); }' in style
    refine = _leggi('static/css/refine.css')
    assert '.toast-close { margin-left: auto; }' in refine


def test_pagina_di_accesso_senza_sfumature_ne_aloni():
    auth = _leggi('static/css/auth.css')
    assert 'linear-gradient' not in auth and 'radial-gradient' not in auth
    for sel in ('.auth-btn--primary', '.auth-btn--primary:hover:not(:disabled)'):
        for corpo in _blocchi(auth, sel):
            assert 'box-shadow' not in corpo and 'transform' not in corpo, sel
    # campi del login come quelli dell'app (grigio pieno = disattivato)
    assert re.search(r'\.auth-field input \{[^}]*background: var\(--bg-input\)', auth)
    premium = _leggi('static/css/theme-premium.css')
    titolo = _blocchi(premium, '.auth-title')
    assert titolo and all('gradient' not in c and 'background' not in c for c in titolo)


def test_ricerca_rapida_scorciatoie_vere_e_voci_complete():
    base = _leggi('templates/base.html')
    app = _leggi('static/js/app.js')
    # nessun Ctrl+1..5 (cambia scheda nel browser) e nessuna etichetta che lo indichi
    assert "e.key >= '1' && e.key <= '5'" not in app
    assert not re.search(r'<kbd class="command-kbd">⌘\d', base)
    # le etichette Alt+N portano alla stessa pagina della scorciatoia vera
    nav = dict(re.findall(r"'(\d)': '(/[a-z-]*)'", app.split('navMap:')[1].split('}')[0]))
    voci = re.findall(r'<div class="command-item" data-action="navigate" data-url="([^"]+)">(.*?)</div>\s*(?=<div class="command-item"|</div>)',
                      base, re.S)
    etichette = {url: re.search(r'<kbd class="command-kbd">Alt\+(\d)</kbd>', corpo) for url, corpo in voci}
    trovate = {m.group(1): url for url, m in etichette.items() if m}
    assert trovate and all(nav[n] == url for n, url in trovate.items()), trovate
    urls = [u for u, _ in voci]
    assert '/impostazioni' in urls and '/profilo' in urls
    # icone neutre: niente classi di colore sui riquadri delle icone
    assert not re.search(r'command-item-icon (blue|purple|green|orange|cyan)', base)
    # icona Dashboard completa (tre riquadri) e Sostituzioni a doppia freccia, nel
    # menu e nella ricerca
    assert base.count('M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13') == 2
    assert base.count('M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4') == 2
    assert 'm9 14v-1a4 4 0 00-4-4h-4' not in base


def test_numeri_nel_carattere_del_testo():
    for nome in os.listdir(os.path.join(PROJECT_DIR, 'static', 'css')):
        if nome.endswith('.css'):
            assert "'JetBrains Mono'" not in _leggi(f'static/css/{nome}'), nome
    style = _leggi('static/css/style.css')
    assert '--font-mono: var(--font-sans);' in style
    for nome in os.listdir(os.path.join(PROJECT_DIR, 'templates')):
        if nome.endswith('.html'):
            assert not re.search(r'font-family:\s*monospace', _leggi(f'templates/{nome}')), nome
    # KPI delle Statistiche con l'unita', come in Dashboard
    assert '<span id="kpi-monte-ore">0</span> h' in _leggi('templates/statistiche.html')


def test_controlli_nel_carattere_della_pagina():
    refine = _leggi('static/css/refine.css')
    assert 'button, input, select, textarea { font-family: inherit; }' in refine


def test_etichette_dei_filtri_come_quelle_dei_moduli():
    refine = _leggi('static/css/refine.css')
    corpo = re.search(r'\.filter-group label, \.filter-label \{([^}]*)\}', refine).group(1)
    assert 'text-transform: none' in corpo
    # larghezze standard al posto delle misure scritte a mano
    for pagina in ('utenti.html', 'dipendenti.html', 'turni.html'):
        html = _leggi(f'templates/{pagina}')
        assert not re.search(r'class="form-control"[^>]*style="(min-)?width:', html), pagina


def test_una_sola_x_per_chiudere_le_finestre(client):
    macro = _leggi('templates/_macros.html')
    assert 'aria-label="Chiudi"' in macro and 'type="button"' in macro
    for nome in os.listdir(os.path.join(PROJECT_DIR, 'templates')):
        if not nome.endswith('.html') or nome == '_macros.html':
            continue
        html = _leggi(f'templates/{nome}')
        assert 'class="modal-close"' not in html, nome
        if 'modal_close(' in html:
            assert "{% from '_macros.html' import modal_close %}" in html, nome
    pagina = client.get('/utenti').get_data(as_text=True)
    assert pagina.count('class="modal-close"') == 7
    assert pagina.count('class="modal-close" onclick="closeModal(&#39;modal-edit&#39;)" aria-label="Chiudi"') == 1
    assert '✕</button>' not in pagina


def test_finestre_conferme_e_ricerca_con_un_solo_aspetto():
    refine = _leggi('static/css/refine.css')
    corpo = re.search(r':root \.modal, :root \.confirm-dialog, :root \.command-palette \{([^}]*)\}', refine).group(1)
    assert 'var(--bg-card-solid)' in corpo and 'backdrop-filter: none' in corpo
    # guida alle scorciatoie con le classi delle finestre, non stili scritti a mano
    app = _leggi('static/js/app.js')
    guida = app.split('showShortcutsHelp() {')[1].split('\n    }\n')[0]
    assert 'class="modal"' in guida and 'cssText' not in guida and 'z-index: 9999' not in guida


def test_rifiniture_di_testo_e_impaginazione():
    assert 'già decurtate' in _leggi('templates/reportistica_locale.html')
    assert '<span>Stato del mese — <span id="stato-mese-nome">' in _leggi('templates/index.html')
    # 'Scarica Template Excel' nell'intestazione della card 'Carica File', non in una barra
    imp = _leggi('templates/import.html')
    testa = imp.split('<h2 class="card-title">Carica File</h2>')[1].split('</div>')[0]
    assert 'id="btn-scarica-template"' in testa
    # Stato budget della scheda utente: riquadro .ud-kpi, niente .stat-card ridefinite
    ud = _leggi('templates/utente_dettaglio.html')
    assert 'class="ud-kpi ud-budget' in ud
    assert not re.search(r'^\.stat-(card|value|label) \{', ud, re.M)
    # Profilo: angoli con una variabile che esiste
    assert 'var(--radius-md)' not in _leggi('templates/profilo.html')


def test_scheda_utente_senza_componenti_comuni_ridefiniti():
    ud = _leggi('templates/utente_dettaglio.html')
    stile = '\n'.join(re.findall(r'<style[^>]*>(.*?)</style>', ud, re.S))
    stile = re.sub(r'/\*.*?\*/', '', stile, flags=re.S)
    for classe in ('.progress-bar', '.progress-fill', '.empty-state', '.stat-card', '.badge', '.alert'):
        assert not re.search(re.escape(classe) + r'\b', stile), classe
    # binario della barra del budget visibile sul riquadro grigio anche nel tema chiaro
    refine = _leggi('static/css/refine.css')
    corpo = re.search(r'\.ud-budget \.progress-bar \{([^}]*)\}', refine).group(1)
    assert 'background: var(--bg-card-solid)' in corpo and 'height: 8px' in corpo
    assert '[data-theme="light"] .progress-fill' not in _leggi('static/css/ux-enhancements.css')
    # niente caratteri scritti a mano su avvisi ed etichette
    assert 'style="font-size:0.75rem;cursor:help;"' not in ud
    assert 'class="alert alert-info" style=' not in _leggi('templates/utenti.html')
    assert 'class="alert alert-info" style=' not in _leggi('templates/index.html')

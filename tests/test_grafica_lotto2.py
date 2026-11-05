"""Grafica, lotto 2 (leggibilita'): guardie su tema chiaro, contrasti e formati.

Sono difetti che nessun altro test vedrebbe: nel tema chiaro le etichette e i numeri
colorati tornerebbero a 1,2-2,2:1 di contrasto, i numeri all'inglese ('61.94')
tornerebbero accanto agli euro all'italiana ('1.490,90 €'), la casella 'Archivia'
del wizard tornerebbe un quadratino da colpire con precisione."""
import glob
import os
import re

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _leggi(path):
    with open(os.path.join(PROJECT_DIR, path), encoding='utf-8') as f:
        return f.read()


def _senza_commenti(css):
    return re.sub(r'/\*.*?\*/', '', css, flags=re.S)


def _contrasto(c1, c2):
    def lum(c):
        c = c.lstrip('#')
        rgb = [int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        lin = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    a, b = lum(c1), lum(c2)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def test_colori_di_stato_leggibili_nel_tema_chiaro():
    # --success/--warning/--danger colorano anche testi (crediti, totali, monte ore,
    # "Salvataggio automatico attivo"): nel tema chiaro vanno ridefiniti piu' scuri.
    css = _senza_commenti(_leggi('static/css/style.css'))
    blocco = re.search(r'\[data-theme="light"\]\s*\{([^}]*)\}', css)
    assert blocco, 'blocco [data-theme="light"] non trovato in style.css'
    for token in ('--success', '--warning', '--danger'):
        m = re.search(token + r'\s*:\s*(#[0-9A-Fa-f]{6})\s*;', blocco.group(1))
        assert m, f'{token} non ridefinito per il tema chiaro'
        assert _contrasto(m.group(1), '#FFFFFF') >= 4.5, f'{token} {m.group(1)} poco leggibile su bianco'


def test_etichette_colorate_leggibili_nel_tema_chiaro():
    # refine.css impone con !important i colori del tema scuro alle etichette: senza
    # le varianti chiare 'Attivo', 'Marzo', '12 senza ore', '0%' quasi spariscono.
    css = _senza_commenti(_leggi('static/css/refine.css'))
    for tipo in ('success', 'warning', 'danger'):
        m = re.search(r'\[data-theme="light"\]\s*\.badge-' + tipo + r'\s*\{([^}]*)\}', css)
        assert m, f'manca [data-theme="light"] .badge-{tipo} in refine.css'
        fondo = re.search(r'background:\s*(#[0-9A-Fa-f]{6})\s*!important', m.group(1))
        testo = re.search(r'(?<![-\w])color:\s*(#[0-9A-Fa-f]{6})\s*!important', m.group(1))
        assert fondo and testo, f'.badge-{tipo} (tema chiaro): servono fondo e testo con !important'
        assert _contrasto(testo.group(1), fondo.group(1)) >= 4.5, f'.badge-{tipo}: contrasto sotto 4,5:1'


def test_numeri_mostrati_all_italiana():
    # Un solo formato: formatNumber/formatOre di app.js ('61,94', '5.963,00').
    # toFixed() resta ammesso solo per il valore di un campo da modificare, o per un
    # calcolo che torna subito numero (Number(x.toFixed(2)): arrotonda2 della
    # Rendicontazione, lo stesso arrotondamento di round() del server), mai per il testo.
    app = _leggi('static/js/app.js')
    corpo = re.search(r'function formatNumber\([^)]*\)\s*\{(.*?)\n\}', app, re.S)
    assert corpo and "toLocaleString('it-IT'" in corpo.group(1), 'formatNumber deve usare il formato italiano'
    for nome in ('formatOre', 'formatDataIT', 'formatMeseIT', 'formatPeriodoIT', 'formatDataOraIT'):
        assert f'window.{nome} = {nome};' in app, f'{nome} non esportata da app.js'

    file = glob.glob(os.path.join(PROJECT_DIR, 'templates', '*.html')) + \
        glob.glob(os.path.join(PROJECT_DIR, 'static', 'js', '*.js'))
    for f in sorted(file):
        with open(f, encoding='utf-8') as fh:
            righe = fh.read().splitlines()
        for n, riga in enumerate(righe, 1):
            if '.toFixed(' in riga and not riga.lstrip().startswith('//'):
                assert re.search(r'\.value\s*=|Number\(\w+\.toFixed\(\d\)\)', riga), \
                    f'{os.path.basename(f)}:{n}: toFixed() nel testo mostrato, usa formatNumber/formatOre'


def test_date_mostrate_all_italiana():
    # Le date tecniche '2026-09-28' diventano '28/09/2026' (formatDataIT/formatPeriodoIT)
    attesi = {
        'templates/sostituzioni.html': 'formatDataIT(s.data)',
        'templates/dipendente_dettaglio.html': 'formatPeriodoIT(a.data_inizio, a.data_fine)',
        'templates/turni.html': 'formatPeriodoIT(t.valido_da, t.valido_a)',
        'templates/utente_dettaglio.html': 'formatDataIT(d.data_scadenza)',
        'templates/reportistica_locale.html': 'formatDataIT(dd.data_dd)',
    }
    for path, frammento in attesi.items():
        assert frammento in _leggi(path), f'{path}: data mostrata senza formato italiano ({frammento})'


def test_chiusura_mese_totali_dal_server():
    # Il passo 3 sommava le righe gia' arrotondate: il Totale con IVA differiva di un
    # centesimo da quello di Rendicontazione e dei documenti ufficiali.
    testo = _leggi('templates/chiusura_mese.html')
    passo3 = testo[testo.index('async function loadStep3'):]
    passo3 = passo3[:passo3.index('// ---------- STEP 4')]
    assert 'data.totale_generale' in passo3
    assert 'acc.totale +=' not in passo3


def test_casella_archivia_del_wizard_con_area_cliccabile():
    js = _leggi('static/js/dashboard.js')
    m = re.search(r'<label class="wizard-archivia-label">\s*<input type="checkbox" class="wizard-archivia"', js)
    assert m, 'la casella "Archivia" del wizard deve stare dentro un <label> che riempie la cella'


def test_focus_da_tastiera_uguale_su_tutti_i_campi():
    refine = _senza_commenti(_leggi('static/css/refine.css'))
    m = re.search(r'([^{}]*select:focus-visible[^{}]*)\{([^}]*)\}', refine)
    assert m and 'input:focus-visible' in m.group(1), 'manca la regola unica di focus per i campi'
    assert re.search(r'outline:\s*2px solid var\(--accent\)\s*!important', m.group(2))
    tutto = ''.join(_senza_commenti(_leggi(f)) for f in glob.glob(os.path.join(PROJECT_DIR, 'static', 'css', '*.css')))
    assert 'inputGlow' not in tutto, 'animazione inputGlow al focus: il campo non deve lampeggiare'
    for sel, corpo in re.findall(r'([^{}]+)\{([^{}]*)\}', tutto):
        if '.table-input' in sel and ':focus' in sel:
            assert 'scale(' not in corpo, f'"{sel.strip()}": il campo ore non deve ingrandirsi al focus'

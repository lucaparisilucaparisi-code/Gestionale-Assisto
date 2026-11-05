"""Grafica, lotto 1 (correzioni rapide su tutte le pagine): guardie sulle correzioni
che, se tornassero indietro, rovinerebbero il lavoro quotidiano senza errori visibili
nei test (finestre sotto il menu, etichette gialle che lampeggiano, versione sbagliata)."""
import glob
import os
import re

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _leggi(path):
    with open(os.path.join(PROJECT_DIR, path), encoding='utf-8') as f:
        return f.read()


def _regole_css():
    """Coppie (selettore, dichiarazioni) di tutti i fogli di stile, senza commenti."""
    regole = []
    for f in sorted(glob.glob(os.path.join(PROJECT_DIR, 'static', 'css', '*.css'))):
        with open(f, encoding='utf-8') as fh:
            css = re.sub(r'/\*.*?\*/', '', fh.read(), flags=re.S)
        for sel, corpo in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
            regole.append((' '.join(sel.split()), corpo))
    return regole


def test_versione_nel_menu_laterale_e_quella_della_release(client):
    versione = _leggi('VERSION').strip()
    html = client.get('/').get_data(as_text=True)
    assert f'Assisto v{versione}</p>' in html
    assert 'Assisto v2.0' not in html


def test_le_finestre_non_restano_sotto_menu_e_barra_in_alto():
    # .content-area contiene tutte le .modal-overlay: se crea un livello (z-index
    # numerico) le finestre finiscono sotto il menu laterale e la barra in alto.
    z = [corpo for sel, corpo in _regole_css()
         if '.content-area' in [x.strip() for x in sel.split(',')] and 'z-index' in corpo]
    assert z, 'nessuna regola z-index su .content-area: controlla il test'
    assert any(re.search(r'z-index:\s*auto\s*!important', c) for c in z), \
        '.content-area deve avere z-index:auto !important (finestre sopra il menu)'


def test_etichette_gialle_ferme():
    for sel, corpo in _regole_css():
        if re.search(r'\.badge-warning\b', sel):
            assert not re.search(r'animation\s*:\s*(?!none)', corpo), \
                f'"{sel}" riceve un\'animazione: le etichette gialle non devono lampeggiare'


def test_riquadri_informativi_con_il_testo_in_un_blocco_unico():
    # .alert e' display:flex: un <strong> figlio diretto diventa una colonna a se'
    # ("Formato richiesto:" su due righe, il resto diviso in altre colonne).
    # Il contenuto va dentro un <div>, dopo l'eventuale icona <svg>.
    apertura = re.compile(r'<div class="alert[ "$][^>]*>\s*(?:<svg\b.*?</svg>\s*)?<(\w+)', re.S)
    file = glob.glob(os.path.join(PROJECT_DIR, 'templates', '*.html')) + \
        glob.glob(os.path.join(PROJECT_DIR, 'static', 'js', '*.js'))
    trovati = 0
    for f in sorted(file):
        with open(f, encoding='utf-8') as fh:
            testo = fh.read()
        for m in apertura.finditer(testo):
            trovati += 1
            riga = testo.count('\n', 0, m.start()) + 1
            assert m.group(1) != 'strong', \
                f'{os.path.basename(f)}:{riga}: grassetto figlio diretto di .alert, mettilo in un <div>'
    assert trovati > 20, 'nessun riquadro .alert trovato: controlla il test'


def test_tabelle_sul_telefono_non_tagliate_dalla_scheda():
    # Sul telefono components.css (ex ux-enhancements.css) da' a ogni .table min-width:600px: fuori da un
    # riquadro che scorre, la .card (overflow:hidden) tagliava colonne e pulsanti
    # ("Trova sostituto", "Ore/sett.", Assegnazioni OEPAC). I 600px restano solo agli
    # elenchi in .table-container; le altre tabelle stanno nello schermo.
    css = re.sub(r'/\*.*?\*/', '', _leggi('static/css/refine.css'), flags=re.S)
    blocchi = re.findall(r'@media\s*\(max-width:\s*768px\)\s*\{((?:[^{}]*\{[^{}]*\})*[^{}]*)\}', css)
    regole = [(' '.join(s.split()), c) for b in blocchi for s, c in re.findall(r'([^{}]+)\{([^{}]*)\}', b)]
    assert any(s == '.table' and re.search(r'min-width:\s*0\s*;', c) for s, c in regole), \
        'in refine.css, sotto i 768px, .table deve avere min-width:0'
    assert not any('.table-responsive' in s and '600px' in c for s, c in regole), \
        '.table-responsive deve scorrere solo se serve, senza larghezza minima fissa'

    # Le tabelle generate in queste pagine stanno dentro un riquadro che scorre.
    for pagina in ['sostituzioni', 'turni', 'dipendente_dettaglio', 'import', 'report']:
        testo = _leggi(f'templates/{pagina}.html')
        tabelle = [m.start() for m in re.finditer(r'<table class="table\b', testo)]
        assert tabelle, f'{pagina}.html: nessuna tabella trovata, controlla il test'
        for pos in tabelle:
            prima = testo[:pos].rstrip()
            riga = testo.count('\n', 0, pos) + 1
            assert re.search(r'<div class="table-(?:responsive|container)\b[^>]*>$', prima), \
                f'{pagina}.html:{riga}: tabella senza <div class="table-responsive"> intorno'
    assert '<div class="table-responsive"><table class="table"><thead><tr>\n        <th>Operatore</th>' \
        in _leggi('templates/utente_dettaglio.html'), 'Assegnazioni OEPAC: tabella senza .table-responsive'

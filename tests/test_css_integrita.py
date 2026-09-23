"""Guardia sull'integrita' degli stili: ogni classe usata da template e JS deve
avere una regola CSS (in static/css/*.css o in un <style> dei template), salvo le
eccezioni elencate qui sotto.

Nasce da una regressione reale: nella v1.8.0 e' stato rimosso un foglio di stile
ritenuto inutilizzato che conteneva ancora le regole dei "report rapidi" della
Dashboard e dei filtri avanzati del Report; le icone sono diventate enormi e
nessun test se n'e' accorto. Se questo test fallisce dopo aver tolto o rinominato
del CSS, controlla le pagine elencate prima di aggiungere la classe alle eccezioni.
"""
import glob
import os
import re

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Classi usate SOLO come aggancio per JavaScript (selettori, toggle di stato):
# non hanno bisogno di una regola CSS.
AGGANCI_JS = {
    'btn-save-giorni', 'chiusura-panel', 'coefficiente', 'coefficiente-altri', 'diff-indicator',
    'edit-colors', 'giorni-altri-input', 'giorni-input', 'imponibile', 'iva', 'ore-100', 'totale',
    'wizard-archivia', 'wizard-nuovo-mo', 'alert-item', 'utente-link', 'wizard-passo-body',
    'page-header-content', 'top-scuole-list', 'import-tab-panel', 'has-results', 'no-results',
}

# Parole che il semplice parser raccoglie da espressioni Jinja/JS dentro
# l'attributo class (non sono classi vere).
RUMORE = {'if', 'in', 'path', 'request', 'type', 'data', 'stato', 'totale_match', 'archivia',
          'diverso', 'creditoDebito'}

# Eccezioni note da sistemare (elenco da SVUOTARE, non da allungare):
# - excel-filter-*: barra "Filtra" della Rendicontazione, il suo CSS non e' mai stato caricato
# - utility di spaziatura mai definite
DA_SISTEMARE = {
    'excel-filter-bar', 'excel-filter-clear', 'excel-filter-input', 'excel-filter-input-group',
    'excel-filter-results', 'py-3', 'py-4', 'mb-0', 'ml-2',
}


def _classi_definite():
    css = ''
    for f in glob.glob(os.path.join(PROJECT_DIR, 'static', 'css', '*.css')):
        with open(f, encoding='utf-8') as fh:
            css += fh.read()
    for f in glob.glob(os.path.join(PROJECT_DIR, 'templates', '*.html')):
        with open(f, encoding='utf-8') as fh:
            css += '\n'.join(re.findall(r'<style[^>]*>(.*?)</style>', fh.read(), re.S))
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    return set(re.findall(r'\.([a-zA-Z][\w-]*)', css))


def _classi_usate():
    usate = {}
    file = glob.glob(os.path.join(PROJECT_DIR, 'templates', '*.html')) + \
        glob.glob(os.path.join(PROJECT_DIR, 'static', 'js', '*.js'))
    for f in file:
        with open(f, encoding='utf-8') as fh:
            src = fh.read()
        for attr in re.findall(r'class(?:Name)?\s*=\s*["\'`]([^"\'`]+)["\'`]', src):
            attr = re.sub(r'\{[{%].*?[%}]\}', ' ', attr)     # espressioni Jinja
            attr = re.sub(r'\$\{[^}]*\}', ' ', attr)          # interpolazioni JS
            for c in re.findall(r'(?<![\w$-])([a-zA-Z][\w-]*[a-zA-Z0-9])(?![\w-])', attr):
                usate.setdefault(c, set()).add(os.path.basename(f))
    return usate


def test_ogni_classe_usata_ha_uno_stile():
    definite = _classi_definite()
    senza_stile = {
        c: sorted(pagine) for c, pagine in _classi_usate().items()
        if c not in definite and c not in AGGANCI_JS | RUMORE | DA_SISTEMARE
    }
    assert not senza_stile, (
        'Classi usate nelle pagine ma senza nessuna regola CSS (stile perso?): '
        + '; '.join(f'{c} ({", ".join(p)})' for c, p in sorted(senza_stile.items()))
    )


def test_le_eccezioni_da_sistemare_sono_ancora_attuali():
    """Quando una classe 'da sistemare' riceve finalmente uno stile, va tolta
    dall'elenco: cosi' l'elenco resta vero e non nasconde nulla."""
    definite = _classi_definite()
    gia_sistemate = sorted(c for c in DA_SISTEMARE if c in definite)
    assert not gia_sistemate, f'Togli da DA_SISTEMARE (ora hanno uno stile): {gia_sistemate}'

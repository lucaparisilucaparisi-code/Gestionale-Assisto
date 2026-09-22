"""Lotto 4 "sotto il cofano": asset versionati con la release, service worker che
non mette in cache pagine/API, tema applicato prima del CSS, un solo blu primario,
login con lo stesso design system dell'app."""
import json
import os
import re

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _leggi(path):
    with open(os.path.join(PROJECT_DIR, path), encoding='utf-8') as f:
        return f.read()


def _versione():
    return _leggi('VERSION').strip()


def test_asset_e_service_worker_versionati_con_la_release(client, app_module):
    v = _versione()
    html = client.get('/').get_data(as_text=True)
    assert f'css/style.css?v={v}' in html and f'js/app.js?v={v}' in html
    assert f'/static/sw.js?v={v}' in html
    assert "url_for('static'" not in _leggi('templates/base.html'), 'asset non versionato in base.html'

    # anche login e setup (non estendono base.html)
    anonimo = app_module.app.test_client()
    login = anonimo.get('/login').get_data(as_text=True)
    assert f'css/style.css?v={v}' in login


def test_service_worker_non_cachea_pagine_ne_api():
    sw = _leggi('static/sw.js')
    assert "searchParams.get('v')" in sw, 'la versione della cache deve arrivare dalla release'
    assert "request.mode === 'navigate'" in sw
    assert "startsWith('/api/')" not in sw and 'DYNAMIC_CACHE' not in sw and 'API_CACHE' not in sw
    for morto in ('indexedDB', "addEventListener('sync'", "addEventListener('push'"):
        assert morto not in sw, f'codice morto ancora presente: {morto}'
    assert 'CLEAR_CACHES' in sw and 'CLEAR_CACHES' in _leggi('templates/profilo.html')


def test_tema_applicato_prima_del_css_e_login_coerente():
    for t in ('base', 'login', 'setup'):
        src = _leggi(f'templates/{t}.html')
        pos_script = src.find("localStorage.getItem('theme')")
        pos_css = src.find('css/style.css')
        assert 0 < pos_script < pos_css, f'{t}.html: il tema va applicato prima del primo foglio di stile'
        assert 'refine.css' in src, f'{t}.html non carica il layer finale del design'
        assert 'content="#3B82F6"' in src, f'{t}.html: theme-color non allineato al blu primario'


def test_un_solo_blu_primario():
    style = _leggi('static/css/style.css')
    assert '--primary: #3B82F6;' in style and '--accent: var(--primary);' in style
    refine = _leggi('static/css/refine.css')
    assert re.search(r'^\s*--(primary|accent):', refine, re.M) is None, 'refine.css ridefinisce i colori'
    assert json.loads(_leggi('static/manifest.json'))['theme_color'] == '#3B82F6'
    for f in ('static/css/theme-premium.css', 'static/css/premium-effects.css', 'static/css/refine.css'):
        assert '0A84FF' not in _leggi(f).upper().replace('#', ''), f

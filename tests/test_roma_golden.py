"""VR2: le uscite di Roma sono quelle della v1.20.1.

L'archivio Roma inventato (tests/roma_sintetico.py) si fotografa con
strumenti/fotografa_roma.py: tutte le rotte GET di Roma (pagine, con il contenuto,
la cornice senza il blocco di Napoli del menu e i file caricati; API, statistiche,
report, export Excel e Word, trasloco JSON). La fotografia deve coincidere con
tests/golden/roma_v1_20_1.json, creata sul codice della v1.20.1 (commit a0249a2) con
i soli cambiamenti di Roma voluti e dichiarati (docs/ARCHITETTURA.md: per ora i testi
e le impronte del passo roma-visualizzazione, nessun numero). Una differenza qualsiasi (un numero, una colonna, un foglio, un id di pagina, una
voce del menu, un foglio di stile) fa fallire il test: o e' un errore, o e' un
cambiamento di Roma voluto e allora il file si rigenera di proposito
(docs/ARCHITETTURA.md, "Protezioni per Roma"). La fotografia non deve contenere
errori (risposte 4xx o 5xx): un indirizzo sbagliato fotograferebbe solo l'errore.

Solo dati inventati.
"""
import os
import re

import roma_sintetico
from strumenti import fotografa_roma

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN = os.path.join(ROOT, 'tests', 'golden', 'roma_v1_20_1.json')


def test_fotografia_di_roma_uguale_alla_v1_20_1(archivio_roma):
    attesa = fotografa_roma.leggi(GOLDEN)
    foto = fotografa_roma.fotografa_sintetico(archivio_roma.client, archivio_roma.percorso, roma_sintetico,
                                              fotografa_roma.leggi_versione(ROOT))
    assert foto == attesa, fotografa_roma.descrivi_differenze(attesa, foto)


def test_ogni_rotta_di_roma_e_fotografata():
    """Ogni GET di Roma ha almeno un indirizzo nella fotografia dell'archivio."""
    rotte = fotografa_roma.leggi(GOLDEN)['rotte']
    assert sorted(set(fotografa_roma.FOTOGRAFIE) - set(rotte)) == []
    assert all(rotte[r] for r in rotte)


def test_la_fotografia_contiene_solo_dati_inventati():
    with open(GOLDEN, encoding='utf-8') as f:
        testo = f.read()
    # nessun codice fiscale, nemmeno solo di forma, e nessun cognome fuori dall'archivio
    assert not re.search(r'[A-Z]{6}\d{2}[A-EHLMPR-T]\d{2}[A-Z]\d{3}[A-Z]', testo)
    cognomi = {u[4] for u in roma_sintetico.UTENTI + roma_sintetico.UTENTI_DOPO}
    cognomi |= {o[2] for o in roma_sintetico.OPERATORI} | {'', 'string'}   # 'string': schema di /api/docs
    trovati = set(re.findall(r'"(?:\w+_)?cognome":"([^"]*)"', testo))
    assert trovati and trovati <= cognomi, sorted(trovati - cognomi)


def test_la_fotografia_non_contiene_errori():
    """Ogni indirizzo fotografato risponde (200, o un rinvio per login e setup): un
    errore 4xx/5xx vorrebbe dire che si confronta la pagina d'errore, non Roma."""
    foto = fotografa_roma.leggi(GOLDEN)
    errori = sorted(u for urls in foto['rotte'].values() for u, r in urls.items() if r['stato'] >= 400)
    assert errori == [], errori
    rinvii = sorted(u for urls in foto['rotte'].values() for u, r in urls.items() if r['stato'] != 200)
    assert all(foto['rotte'][r][u]['stato'] in (301, 302, 303, 307, 308) for r in foto['rotte']
               for u in foto['rotte'][r] if u in rinvii)
    assert foto['versione_fotografia'] == fotografa_roma.VERSIONE_FOTOGRAFIA


def test_cornice_senza_il_blocco_di_napoli(archivio_roma):
    """L'impronta della cornice (menu laterale compreso) non vede il blocco di Napoli
    del menu (elementi con data-sezione="napoli", quello vero della pagina e uno di
    prova in piu'), ma vede ogni altra differenza; i file caricati hanno la loro impronta."""
    html = archivio_roma.client.get('/').get_data(as_text=True)
    norm = fotografa_roma.Normalizzatore(fotografa_roma.leggi_versione(ROOT))
    statici = fotografa_roma._Statici(archivio_roma.client)

    def pagina(testo):
        return fotografa_roma._leggi_pagina(testo, norm, statici)

    prima = pagina(html)
    assert '</nav>' in html and html.count('<main') == 1
    # la pagina vera ha il blocco di Napoli del passo 1.3 (voce del menu e della ricerca
    # rapida, Alt+8): la sua cornice resta quella della v1.20.1, che il blocco non l'aveva
    assert 'href="/napoli" class="nav-link' in html and 'data-url="/napoli"' in html
    assert html.count('data-sezione="napoli"') >= 2
    assert prima['impronta_cornice'] == fotografa_roma.leggi(GOLDEN)['rotte']['/']['/']['contenuto']['impronta_cornice']
    senza_attributo = pagina(html.replace(' data-sezione="napoli"', ''))
    assert senza_attributo['impronta_cornice'] != prima['impronta_cornice'], 'il blocco di Napoli non e\' marcato'
    blocco = ('<div class="nav-section" data-sezione="napoli"><div class="nav-section-title">Napoli</div></div>'
              '<a href="/napoli" class="nav-link" data-sezione="napoli"><svg viewBox="0 0 24 24"><path d="M1 1"/>'
              '</svg><span>Mese</span></a><hr data-sezione="napoli"><script src="/static/js/napoli.js" '
              'data-sezione="napoli"></script>')
    con_napoli = pagina(html.replace('</nav>', blocco + '</nav>', 1))
    assert con_napoli == prima
    for cambiato in (html.replace('<span>Dashboard</span>', '<span>Cruscotto</span>', 1),
                     html.replace('</nav>', '<a href="/altro" class="nav-link"><span>Altro</span></a></nav>', 1),
                     html.replace('</head>', '<meta name="robots" content="none"></head>', 1)):
        assert pagina(cambiato)['impronta_cornice'] != prima['impronta_cornice']
        assert pagina(cambiato)['impronta_contenuto'] == prima['impronta_contenuto']
    in_piu = pagina(html.replace('</body>', '<script src="/static/js/dashboard.js"></script></body>', 1))
    assert in_piu['risorse'][:len(prima['risorse'])] == prima['risorse'] and len(in_piu['risorse']) == len(
        prima['risorse']) + 1
    impronte = dict(prima['risorse'])
    assert impronte['/static/js/app.js?v=<versione>'] == 'modificabile'
    assert all(len(v) == 16 for k, v in impronte.items() if 'app.js' not in k)

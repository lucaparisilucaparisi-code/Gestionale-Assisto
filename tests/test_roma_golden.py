"""VR2: le uscite di Roma sono quelle della v1.20.1.

L'archivio Roma inventato (tests/roma_sintetico.py) si fotografa con
strumenti/fotografa_roma.py: tutte le rotte GET di Roma (pagine senza il menu
laterale, API, statistiche, report, export Excel e Word, trasloco JSON). La
fotografia deve coincidere con tests/golden/roma_v1_20_1.json, creata sul codice
della v1.20.1. Una differenza qualsiasi (un numero, una colonna, un foglio, un id
di pagina) fa fallire il test: o e' un errore, o e' un cambiamento di Roma voluto
e allora il file si rigenera di proposito (docs/ARCHITETTURA.md, "Protezioni per
Roma").

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

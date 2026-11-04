"""VR3 e VR4: Roma non cambia quando nel database c'e' anche Napoli; ogni rotta e' classificata.

- Invarianza: sull'archivio Roma inventato si fotografa Roma, si carica il seme
  Napoli (tests/seme_napoli.py) e si rifotografa: le due fotografie devono essere
  uguali, le tabelle di Roma (schema e righe) intatte e le letture di Roma non
  devono toccare le tabelle di Napoli. Finche' la sezione Napoli non c'e' il seme
  e' vuoto: ogni passo di Napoli lo arricchisce e il test resta questo.
- Inventario: ogni rotta di app.url_map sta in ROTTE_ROMA, ROTTE_NAPOLI o ESCLUSE
  (strumenti/fotografa_roma.py); una rotta nuova non classificata fa fallire il test.

Solo dati inventati.
"""
import os

import roma_sintetico
import seme_napoli
from strumenti import fotografa_roma

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_roma_non_cambia_con_i_dati_di_napoli(database_isolato, app_module, db_mod):
    client = fotografa_roma.client_fotografia(app_module.app, db_mod)
    roma_sintetico.costruisci_archivio(client, fotografa_roma.orologio_fermo)
    versione = fotografa_roma.leggi_versione(ROOT)

    prima = fotografa_roma.fotografa_sintetico(client, database_isolato, roma_sintetico, versione)
    tabelle_roma = seme_napoli.impronta_roma(database_isolato)

    seme_napoli.carica_seme_napoli(client)
    assert seme_napoli.impronta_roma(database_isolato) == tabelle_roma, 'il seme Napoli ha toccato Roma'
    tabelle_napoli = seme_napoli.impronta_napoli(database_isolato)

    dopo = fotografa_roma.fotografa_sintetico(client, database_isolato, roma_sintetico, versione)
    assert dopo == prima, fotografa_roma.descrivi_differenze(prima, dopo)
    assert seme_napoli.impronta_napoli(database_isolato) == tabelle_napoli, 'le letture di Roma hanno toccato Napoli'


def test_inventario_rotte(app_module):
    regole = fotografa_roma.regole_applicazione(app_module.app)
    problemi = fotografa_roma.controlla_inventario(regole)
    assert problemi == [], '\n'.join(problemi)


def test_inventario_segnala_una_rotta_nuova(app_module):
    """Il controllo stesso: una rotta in piu' (di Roma o di Napoli) non classificata
    e una classificata che non esiste piu' vengono segnalate."""
    regole = fotografa_roma.regole_applicazione(app_module.app)
    nuove = dict(regole, **{'/api/prova-non-classificata': {'GET'}, '/api/napoli/prova': {'POST'}})
    problemi = fotografa_roma.controlla_inventario(nuove)
    assert any(p.startswith('/api/prova-non-classificata: rotta non classificata') for p in problemi)
    assert any(p.startswith('/api/napoli/prova: rotta non classificata') for p in problemi)
    senza = {r: m for r, m in regole.items() if r != '/api/stats'}
    assert any(p.startswith("/api/stats: in ROTTE_ROMA ma non esiste piu'") for p in
               fotografa_roma.controlla_inventario(senza))

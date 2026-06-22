"""Test delle funzioni di calcolo pure (formule core del gestionale)."""
import config
import database as db


# ---------- calcola_media_prevista ----------

def test_media_prevista_valori_standard():
    """15h/sett * 22 giorni: lorda=66, con assenza 11% = 58.74."""
    lorda, con_assenza = db.calcola_media_prevista(15, 22)
    assert lorda == 15 * 22 * config.COEFFICIENTE_GIORNALIERO
    assert round(con_assenza, 2) == round(lorda * (1 - config.TASSO_ASSENZA), 2)
    assert round(con_assenza, 2) == 58.74


def test_media_prevista_zero_e_none():
    assert db.calcola_media_prevista(0, 22) == (0, 0)
    assert db.calcola_media_prevista(15, 0) == (0, 0)
    assert db.calcola_media_prevista(None, None) == (0, 0)


def test_media_prevista_segue_il_config(monkeypatch):
    """Se cambiano i coefficienti nel config, la formula si adegua."""
    monkeypatch.setattr(config, 'COEFFICIENTE_GIORNALIERO', 0.25)
    monkeypatch.setattr(config, 'TASSO_ASSENZA', 0.0)
    lorda, con_assenza = db.calcola_media_prevista(10, 20)
    assert lorda == 10 * 20 * 0.25  # 50
    assert con_assenza == 50  # tasso assenza azzerato


# ---------- punteggia_nome ----------

def test_punteggia_nome():
    assert db.punteggia_nome('Mario', 'Rossi') == 'M. R.'
    assert db.punteggia_nome('anna', 'bianchi') == 'A. B.'
    assert db.punteggia_nome('Luca', '') == 'L.'
    assert db.punteggia_nome('', '') == ''


# ---------- decimal_to_sessagesimal (in routes_export.py) ----------

def test_decimal_to_sessagesimal(app_module):
    import routes_export
    f = routes_export.decimal_to_sessagesimal
    assert f(0) == '0:00'
    assert f(None) == '0:00'
    assert f(1.5) == '1:30'
    assert f(2.25) == '2:15'
    assert f(0.75) == '0:45'
    # arrotondamento: 0.999h -> 60min -> 1:00
    assert f(0.999) == '1:00'


# ---------- get_liste_attesa_ordinate (in routes_export.py) ----------

def test_liste_attesa_ordinate_cronologiche(app_module):
    """L'ordine deve seguire l'anno scolastico (Set->Giu) con etichette corrette."""
    import routes_export
    dati = [
        {'lista_attesa': 'Marzo'},
        {'lista_attesa': 'Novembre'},
        {'lista_attesa': None},
        {'lista_attesa': 'Novembre'},  # duplicato
    ]
    # Report di Ottobre 2025 -> anno scolastico inizia nel 2025
    result = routes_export.get_liste_attesa_ordinate(dati, 2025, 10)
    valori = [r['valore'] for r in result]
    assert valori == ['Novembre', 'Marzo']  # cronologico
    labels = {r['valore']: r['label'] for r in result}
    assert labels['Novembre'] == 'Lista Nov 2025'  # autunno -> anno inizio
    assert labels['Marzo'] == 'Lista Mar 2026'     # primavera -> anno inizio+1


def test_liste_attesa_nessuna(app_module):
    import routes_export
    dati = [{'lista_attesa': None}, {'lista_attesa': ''}]
    assert routes_export.get_liste_attesa_ordinate(dati, 2025, 10) == []

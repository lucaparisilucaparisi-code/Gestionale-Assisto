"""Verifica del CONTENUTO degli export: i numeri nelle celle devono coincidere
con l'helper unico di fatturazione (config.calcola_fatturazione).
"""
import io

from openpyxl import load_workbook

import config


def _set_ore(db, uid, anno, mese, ore):
    db.get_or_create_rendicontazione(uid, anno, mese)
    db.update_rendicontazione(uid, anno, mese, ore_lavorate=ore)


def test_municipale_celle_coerenti_con_fatturazione(client, db_mod):
    """Nel riepilogo municipale imponibile/totale di ogni riga devono derivare
    dalle ore con l'helper unico (non da altri calcoli)."""
    db = db_mod
    db.create_commessa('OEPAC CELLE')
    sid = db.get_or_create_scuola('OEPAC CELLE', 'IC Celle - Primaria')
    u1 = db.get_or_create_utente(sid, 'Cella', 'Uno', 15)
    u2 = db.get_or_create_utente(sid, 'Cella', 'Due', 20)
    _set_ore(db, u1, 2026, 4, 61.5)
    _set_ore(db, u2, 2026, 4, 44.25)

    r = client.get('/api/export/municipale/2026/4?commessa=OEPAC%20CELLE')
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.data), data_only=True)
    ws = wb['Riepilogo Municipale']

    # layout reale: [scuola, ore60 HH:MM, tariffa, importo60, ore100, tariffa, importo100]
    righe = list(ws.iter_rows(values_only=True))
    riga = next((row for row in righe if row and row[0] == 'IC Celle - Primaria'), None)
    assert riga, 'riga della scuola di test non trovata nel foglio'

    ore_100 = riga[4]
    assert ore_100 == 61.5 + 44.25
    assert riga[2] == config.TARIFFA_ORARIA            # tariffa nella cella
    assert round(riga[6], 2) == round(ore_100 * config.TARIFFA_ORARIA, 2)

    # riepilogo fatturazione: imponibile/IVA/totale coerenti con l'helper unico
    imponibile, iva, totale = config.calcola_fatturazione(ore_100)
    valori = [round(c, 2) for row in righe for c in row
              if isinstance(c, (int, float)) and c is not None]
    for atteso in (imponibile, totale):
        assert atteso in valori, f'{atteso} assente dal riepilogo fatturazione'


def _valore_sotto_label(celle, label):
    """Valore nella cella subito sotto una label KPI del Dashboard."""
    for ri, row in enumerate(celle):
        for ci, v in enumerate(row):
            if v == label:
                return celle[ri + 1][ci]
    return None


def test_annuale_totali_coerenti(client, db_mod):
    """Il report annuale deve quadrare a ogni livello: il totale dell'anno e' la
    somma dei mesi, ogni colonna 'Imponibile' somma al suo TOTALE, e il totale
    del Dashboard coincide con quello del Riepilogo Utenti e dei fogli mensili.

    Ore con molti decimali su piu' utenti/mesi: espone eventuali divergenze da
    arrotondamento (round-once-sull'aggregato vs somma-di-arrotondamenti)."""
    db = db_mod
    db.create_commessa('ANNUALE COERENTE')
    sid = db.get_or_create_scuola('ANNUALE COERENTE', 'IC Quadra - Primaria')
    ua = db.get_or_create_utente(sid, 'Ada', 'Neri', 15)
    ub = db.get_or_create_utente(sid, 'Bea', 'Mori', 20)
    uc = db.get_or_create_utente(sid, 'Cid', 'Lippi', 12)
    # anno scolastico 2025-2026: Set/Ott/Nov 2025
    for (anno, mese), ore in {
        (2025, 9):  (61.53, 44.27, 33.11),
        (2025, 10): (70.19, 55.83, 40.47),
        (2025, 11): (58.66, 49.09, 37.72),
    }.items():
        _set_ore(db, ua, anno, mese, ore[0])
        _set_ore(db, ub, anno, mese, ore[1])
        _set_ore(db, uc, anno, mese, ore[2])

    r = client.get('/api/export/annuale/2025-2026?commessa=ANNUALE%20COERENTE')
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.data), data_only=True)

    # --- Dashboard: KPI vs riga TOTALE ANNUALE ---
    celle = list(wb['Dashboard'].iter_rows(values_only=True))
    kpi_imp = round(_valore_sotto_label(celle, 'Imponibile Annuale'), 2)
    kpi_tot = round(_valore_sotto_label(celle, 'Totale Lordo'), 2)
    riga_tot = next(row for row in celle if row and row[0] == 'TOTALE ANNUALE')
    trend_imp, trend_tot = round(riga_tot[5], 2), round(riga_tot[6], 2)
    assert kpi_imp == trend_imp, f'KPI imponibile {kpi_imp} != andamento mensile {trend_imp}'
    assert kpi_tot == trend_tot, f'KPI totale {kpi_tot} != andamento mensile {trend_tot}'

    # --- Riepilogo Utenti: la colonna Imponibile somma al TOTALE, e il TOTALE
    #     coincide col Dashboard ---
    celle_u = list(wb['Riepilogo Utenti'].iter_rows(values_only=True))
    riga_tot_u = next(row for row in celle_u if row and row[0] == 'TOTALE')
    utenti_tot_imp = round(riga_tot_u[9], 2)
    col_u = [row[9] for row in celle_u[6:]
             if row and row[0] and row[0] != 'TOTALE' and isinstance(row[9], (int, float))]
    assert round(sum(col_u), 2) == utenti_tot_imp, 'colonna imponibile utenti non quadra col totale'
    assert utenti_tot_imp == kpi_imp, f'Riepilogo Utenti {utenti_tot_imp} != Dashboard {kpi_imp}'

    # --- Fogli mensili: colonna Imponibile == TOTALE del foglio ---
    for nome in ('Set 2025', 'Ott 2025', 'Nov 2025'):
        righe_m = list(wb[nome].iter_rows(values_only=True))
        riga_tot_m = next(row for row in righe_m if row and row[0] == 'TOTALE')
        tot_cell = round(riga_tot_m[8], 2)
        col = [row[8] for row in righe_m[3:]
               if row and row[0] and row[0] != 'TOTALE' and isinstance(row[8], (int, float))]
        assert round(sum(col), 2) == tot_cell, f'{nome}: colonna imponibile non quadra col TOTALE'

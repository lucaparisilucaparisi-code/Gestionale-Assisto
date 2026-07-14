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


def _hhmm_to_min(s):
    """Converte 'H:MM' / '+H:MM' / '-H:MM' in minuti interi (con segno)."""
    s = str(s).strip()
    segno = -1 if s.startswith('-') else 1
    ore, minuti = s.lstrip('+-').split(':')
    return segno * (int(ore) * 60 + int(minuti))


def test_annuale_monte_ore_previsto_contrattuale(client, db_mod):
    """Nel report annuale il 'Monte Ore Previsto' per utente e' contrattuale:
    ore settimanali x SETTIMANE_ANNO_SCOLASTICO, meno l'11% (per un utente attivo
    tutto l'anno). Es. 8 ore -> 8 x 35 x 0,89 = 249,20 -> 249:12."""
    db = db_mod
    db.create_commessa('PREV CONTR')
    sid = db.get_or_create_scuola('PREV CONTR', 'IC Prev - Primaria')
    u8 = db.get_or_create_utente(sid, 'Otto', 'Ore', 8)
    u10 = db.get_or_create_utente(sid, 'Dieci', 'Ore', 10)
    # attivi tutti i 10 mesi scolastici 2025-2026
    mesi = [(2025, 9), (2025, 10), (2025, 11), (2025, 12), (2026, 1),
            (2026, 2), (2026, 3), (2026, 4), (2026, 5), (2026, 6)]
    for uid in (u8, u10):
        for anno, mese in mesi:
            _set_ore(db, uid, anno, mese, 20)

    r = client.get('/api/export/annuale/2025-2026?commessa=PREV%20CONTR')
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.data), data_only=True)
    righe = [row for row in wb['Riepilogo Utenti'].iter_rows(values_only=True)]

    def previsto_min(monte):
        atteso = monte * config.SETTIMANE_ANNO_SCOLASTICO * (1 - config.TASSO_ASSENZA)
        return round(atteso * 60)  # in minuti

    per_riga = {}
    for row in righe[6:]:
        if row and row[0] and row[0] != 'TOTALE':
            per_riga[row[0]] = _hhmm_to_min(row[5])

    # 8 ore -> 249:12 ; 10 ore -> 311:30 (tolleranza 1 minuto per arrotondamento)
    assert abs(per_riga['Otto Ore'] - previsto_min(8)) <= 1
    assert abs(per_riga['Dieci Ore'] - previsto_min(10)) <= 1

    # il TOTALE previsto e' la somma delle righe
    tot = next(row for row in righe[6:] if row and row[0] == 'TOTALE')
    tot_previsto_min = _hhmm_to_min(tot[5])
    assert abs(tot_previsto_min - sum(per_riga.values())) <= 1

    # lo stesso 'previsto' deve comparire IDENTICO nel Dashboard: sia il KPI
    # 'Ore Previste (-11%)' sia la riga TOTALE ANNUALE dell'andamento mensile.
    celle = list(wb['Dashboard'].iter_rows(values_only=True))

    def _valore_kpi(label):
        for ri, row in enumerate(celle):
            for ci, v in enumerate(row):
                if v == label:
                    return celle[ri + 1][ci]
        return None

    kpi_previste = _hhmm_to_min(_valore_kpi('Ore Previste (-11%)'))
    riga_tot = next(row for row in celle if row and row[0] == 'TOTALE ANNUALE')
    andamento_previste = _hhmm_to_min(riga_tot[3])
    assert abs(kpi_previste - tot_previsto_min) <= 1, 'KPI Dashboard != totale Riepilogo Utenti'
    assert abs(andamento_previste - tot_previsto_min) <= 1, 'Andamento Mensile != totale Riepilogo Utenti'


def test_annuale_credito_debito_ore_minuti(client, db_mod):
    """Nel Riepilogo Utenti, Credito/Debito e' in ore:minuti come Monte Ore
    Previsto e Ore Erogate, e i conti tornano a ogni riga E nel TOTALE:
    previsto - erogate == credito/debito (fino all'arrotondamento al minuto)."""
    db = db_mod
    db.create_commessa('CRED OM')
    sid = db.get_or_create_scuola('CRED OM', 'IC CredDeb - Primaria')
    # ore intere -> erogate a :00: la relazione previsto-erogate==cred/deb e' esatta
    profili = [('Uno', 'Aaa', 8, 25), ('Due', 'Bbb', 12, 10), ('Tre', 'Ccc', 6, 20)]
    mesi = [(2025, 9), (2025, 10), (2025, 11), (2025, 12), (2026, 1), (2026, 2)]
    for nome, cog, monte, ore in profili:
        uid = db.get_or_create_utente(sid, nome, cog, monte)
        for anno, mese in mesi:
            _set_ore(db, uid, anno, mese, ore)

    r = client.get('/api/export/annuale/2025-2026?commessa=CRED%20OM')
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.data), data_only=True)
    righe = [row for row in wb['Riepilogo Utenti'].iter_rows(values_only=True)]
    dati = [row for row in righe[6:] if row and row[0]]

    somma_cd = 0
    for row in dati:
        prev, erog, cd = _hhmm_to_min(row[5]), _hhmm_to_min(row[6]), _hhmm_to_min(row[7])
        assert ':' in str(row[7]), f'credito/debito non in ore:minuti: {row[7]!r}'
        if row[0] == 'TOTALE':
            # il TOTALE quadra: previsto - erogate == credito/debito
            assert abs((prev - erog) - cd) <= 1, f'TOTALE non quadra: {prev}-{erog} != {cd}'
            assert abs(somma_cd - cd) <= 1, f'somma righe cred/deb ({somma_cd}) != TOTALE ({cd})'
        else:
            assert abs((prev - erog) - cd) <= 1, f'{row[0]}: {prev}-{erog} != {cd}'
            somma_cd += cd


def _municipale_riepilogo_rows(client, db, anno, mese, commessa):
    """Genera il municipale e ritorna (header, 4 righe) della sezione lista attesa."""
    r = client.get(f'/api/export/municipale/{anno}/{mese}?commessa={commessa.replace(" ", "%20")}')
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.data), data_only=True)
    ws = wb['Riepilogo Municipale']
    righe = list(ws.iter_rows(values_only=True))
    start = next(i for i, row in enumerate(righe)
                 if row and row[0] and 'RIEPILOGATIVO PER LISTA' in str(row[0]))
    return righe[start + 1], righe[start + 2:start + 6]


def test_municipale_riepilogo_incremento_e_quadratura(client, db_mod):
    """La sezione lista attesa del municipale: colonna 4 = 'Di cui hanno ricevuto
    incremento ore', e in ogni riga Totale = Non in lista + somma delle liste
    (anche con un utente dal valore lista_attesa 'sporco' di soli spazi)."""
    db = db_mod
    db.create_commessa('MUNI RIEP')
    sid = db.get_or_create_scuola('MUNI RIEP', 'IC Riep - Primaria')

    def mk(nome, ore, monte=10, lista=None):
        uid = db.get_or_create_utente(sid, nome, 'R', monte)
        if lista is not None:
            db.update_utente_lista_attesa(uid, lista)
        _set_ore(db, uid, 2025, 11, ore)
        return uid

    mk('NL1', 20); mk('NL2', 0)
    mk('NovA', 15, lista='Novembre'); mk('NovB', 10, lista='Novembre')
    mk('MarA', 12, lista='Marzo')
    # utente con incremento monte ore (base 8 -> 12 da nov 2025)
    inc = db.get_or_create_utente(sid, 'IncA', 'R', 8)
    db.add_variazione_monte_ore(inc, 12, '2025-11', 'aumento')
    _set_ore(db, inc, 2025, 11, 18)
    # utente con lista_attesa di soli spazi (bypassa la normalizzazione via SQL)
    ghost = db.get_or_create_utente(sid, 'Ghost', 'R', 10)
    with db.get_db_context() as conn:
        conn.execute("UPDATE utenti SET lista_attesa = '   ' WHERE id = ?", (ghost,))
    _set_ore(db, ghost, 2025, 11, 5)
    # utente con aumento ereditato da un ANNO SCOLASTICO PRECEDENTE (base 10 -> 14
    # dal nov 2024): a settembre 2025 e' gia' a 14, quindi NON e' un incremento
    # dell'anno corrente e non deve comparire nella colonna incremento.
    old = db.get_or_create_utente(sid, 'OldInc', 'R', 10)
    db.add_variazione_monte_ore(old, 14, '2024-11', 'vecchio aumento')
    _set_ore(db, old, 2025, 11, 16)

    header, rows = _municipale_riepilogo_rows(client, db, 2025, 11, 'MUNI RIEP')
    assert header[3] == 'Di cui hanno ricevuto incremento ore'
    labels_lista = [h for h in header[4:] if h]
    n_liste = len(labels_lista)

    # quadratura: col1 (totale) == col2 (non in lista) + somma colonne-lista, ogni riga
    for row in rows:
        tot = row[1] or 0
        non_lista = row[2] or 0
        somma_liste = sum(row[4 + i] or 0 for i in range(n_liste))
        assert abs(tot - (non_lista + somma_liste)) < 0.02, \
            f"non quadra: {row[0]}: {tot} != {non_lista}+{somma_liste}"

    # colonna incremento: SOLO IncA (aumento nell'anno corrente, 18 ore).
    # OldInc (aumento ereditato dall'anno precedente) NON e' contato.
    riga_alunni, riga_ore = rows[0], rows[2]
    assert riga_alunni[3] == 1, f"incremento alunni atteso 1 (solo IncA), trovato {riga_alunni[3]}"
    assert abs((riga_ore[3] or 0) - 18) < 0.01, f"incremento ore atteso 18, trovato {riga_ore[3]}"
    # totale utenti = 8 (inclusi ghost e OldInc) e i totali quadrano
    assert riga_alunni[1] == 8


def test_lista_attesa_whitespace_normalizzata_in_scrittura(db_mod):
    """update_utente_lista_attesa deve azzerare (NULL) i valori di soli spazi."""
    db = db_mod
    db.create_commessa('WS NORM')
    sid = db.get_or_create_scuola('WS NORM', 'IC WS - Primaria')
    uid = db.get_or_create_utente(sid, 'Tizio', 'W', 10)
    db.update_utente_lista_attesa(uid, '   ')
    with db.get_db_context() as conn:
        val = conn.execute("SELECT lista_attesa FROM utenti WHERE id = ?", (uid,)).fetchone()[0]
    assert val is None, f"whitespace non normalizzato: {val!r}"
    db.update_utente_lista_attesa(uid, '  Novembre  ')
    with db.get_db_context() as conn:
        val = conn.execute("SELECT lista_attesa FROM utenti WHERE id = ?", (uid,)).fetchone()[0]
    assert val == 'Novembre', f"strip non applicato: {val!r}"

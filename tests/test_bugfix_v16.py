"""Regressioni corrette nella v1.6.0: import, previste, validazione chiusura,
sostituzioni, variazioni, storico.
"""
import io

import openpyxl


def _mk_xlsx(rows):
    """Crea un xlsx in memoria con header Commessa/Scuola/Nome/Cognome/Monte Ore."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['Commessa', 'Scuola', 'Nome', 'Cognome', 'Monte Ore'])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_preview_import_riconosce_esistenti(client, db_mod):
    """L'anteprima deve marcare 'esistente' un utente gia' in anagrafica
    (la query storica falliva sempre su una colonna inesistente)."""
    db_mod.create_commessa('OEPAC PREV')
    sid = db_mod.get_or_create_scuola('OEPAC PREV', 'IC Preview - Primaria Rossi')
    db_mod.get_or_create_utente(sid, 'Paola', 'Verdi', 10)

    buf = _mk_xlsx([
        ['OEPAC PREV', 'IC Preview - Primaria Rossi', 'Paola', 'Verdi', 10],   # esistente
        ['OEPAC PREV', 'IC Preview - Primaria Rossi', 'Nuovo', 'Utente', 12],  # nuovo
    ])
    r = client.post('/api/import-excel/preview',
                    data={'file': (buf, 'test.xlsx')},
                    content_type='multipart/form-data')
    assert r.status_code == 200, r.get_json()
    stati = {(p['nome'], p['cognome']): p['stato'] for p in r.get_json()['preview']}
    assert stati[('Paola', 'Verdi')] == 'esistente'
    assert stati[('Nuovo', 'Utente')] == 'nuovo'


def test_get_or_create_utente_case_insensitive(db_mod):
    """Stesso nominativo con casing diverso NON deve creare un duplicato."""
    db_mod.create_commessa('OEPAC CASE')
    sid = db_mod.get_or_create_scuola('OEPAC CASE', 'IC Case - Primaria')
    uid1 = db_mod.get_or_create_utente(sid, 'Mario', 'Rossi', 10)
    uid2 = db_mod.get_or_create_utente(sid, 'MARIO', 'ROSSI', 12)
    assert uid1 == uid2


def test_ore_previste_escludono_utenti_fuori_periodo(db_mod, sample_data):
    """Le previste del trend devono coincidere con la somma delle media_con_assenza
    della vista mensile (utenti fuori periodo esclusi)."""
    db = db_mod
    db.create_commessa('OEPAC PREVISTE')
    sid = db.get_or_create_scuola('OEPAC PREVISTE', 'IC Previste - Primaria')
    # utente attivo tutto l'anno
    db.get_or_create_utente(sid, 'Attivo', 'Sempre', 10)
    # utente uscito a ottobre 2025 (data_fine)
    uid_out = db.get_or_create_utente(sid, 'Uscito', 'Presto', 20)
    db.update_utente_periodo(uid_out, data_fine='2025-10')

    trend = db.get_ore_erogate_vs_previste('2025-2026', commessa='OEPAC PREVISTE')
    per_mese = {(t['mese'], t['anno']): t for t in trend}

    # novembre: l'utente uscito NON deve contribuire alle previste
    dati_nov = db.get_rendicontazione_completa(2025, 11, 'OEPAC PREVISTE')
    previste_attese_nov = round(sum(d['media_con_assenza_60'] or 0 for d in dati_nov), 2)
    assert per_mese[(11, 2025)]['ore_previste'] == previste_attese_nov
    ids_nov = [d['utente_id'] for d in dati_nov]
    assert uid_out not in ids_nov


def test_validazione_esclude_utenti_fuori_periodo(client, db_mod):
    """Un utente con data_fine passata non deve risultare 'senza ore' nel mese dopo."""
    db = db_mod
    db.create_commessa('OEPAC VAL')
    sid = db.get_or_create_scuola('OEPAC VAL', 'IC Val - Primaria')
    uid = db.get_or_create_utente(sid, 'Finito', 'Servizio', 15)
    db.update_utente_periodo(uid, data_fine='2026-01')

    r = client.get('/api/stats/validazione?anno=2026&mese=3')
    assert r.status_code == 200
    anomalie = r.get_json().get('anomalie', r.get_json())
    testo = str(anomalie)
    assert 'Finito' not in testo

    # e nemmeno in utenti-da-completare
    r2 = client.get('/api/stats/utenti-da-completare/2026/3')
    nomi = [u['nome_completo'] for u in r2.get_json()]
    assert 'Finito Servizio' not in nomi


def test_sostituto_non_prenotabile_due_volte(db_mod):
    """Un sostituto gia' assegnato a un turno nella stessa fascia non deve
    risultare disponibile per un secondo turno sovrapposto."""
    db = db_mod
    db.create_commessa('OEPAC SOST')
    sid = db.get_or_create_scuola('OEPAC SOST', 'IC Sost - Primaria')
    a1 = db.create_dipendente({'nome': 'Assente', 'cognome': 'Uno'})
    a2 = db.create_dipendente({'nome': 'Assente', 'cognome': 'Due'})
    libero = db.create_dipendente({'nome': 'Libero', 'cognome': 'Sostituto'})

    # 2026-06-22 e' lunedi' (giorno=0): stessi orari sovrapposti
    db.create_turno(a1, 0, '09:00', '12:00', scuola_id=sid)
    db.create_turno(a2, 0, '09:00', '12:00', scuola_id=sid)
    ass1 = db.create_assenza_dipendente(a1, '2026-06-22', '2026-06-22', 'malattia')
    ass2 = db.create_assenza_dipendente(a2, '2026-06-22', '2026-06-22', 'malattia')
    db.crea_sostituzioni_per_assenza(ass1)
    db.crea_sostituzioni_per_assenza(ass2)

    sost = [s for s in db.get_sostituzioni('2026-06-22', '2026-06-22')]
    s1 = next(s for s in sost if s['assente_id'] == a1)
    s2 = next(s for s in sost if s['assente_id'] == a2)

    # assegna 'libero' alla prima sostituzione (non solleva: disponibile)
    db.assegna_sostituto(s1['id'], libero)

    # per la seconda NON deve piu' essere tra i candidati...
    cand = db.suggerisci_sostituti(sid, 0, '09:00', '12:00', '2026-06-22', escludi_id=a2)
    assert libero not in [c['id'] for c in cand]

    # ...e l'assegnazione diretta deve essere rifiutata
    import pytest
    with pytest.raises(ValueError):
        db.assegna_sostituto(s2['id'], libero)


def test_variazione_mese_inizio_formato_invalido(client, db_mod, sample_data):
    uid = sample_data['utente_id']
    for bad in ['2026/03', '03-2026', 'gennaio', '2026-13']:
        r = client.post(f'/api/utenti/{uid}/variazioni-monte-ore',
                        json={'monte_ore': 18, 'mese_inizio': bad})
        assert r.status_code == 400, f"accettato formato invalido: {bad}"


def test_storico_usa_calendario_aggiornato(client, db_mod, sample_data):
    """Se il calendario cambia dopo la creazione della rendicontazione, lo storico
    deve riflettere il calendario (l'alias duplicato faceva usare la cache)."""
    db = db_mod
    uid = sample_data['utente_id']
    db.get_or_create_rendicontazione(uid, 2025, 10)
    db.update_rendicontazione(uid, 2025, 10, ore_lavorate=30)
    # aggiorna il calendario DOPO la creazione (la cache in rendicontazione resta vecchia)
    db.set_calendario('2025-2026', 10, 2025, 18)

    storico = client.get(f'/api/utente/{uid}/storico').get_json()['storico']
    voce = next(s for s in storico if s['anno'] == 2025 and s['mese'] == 10)
    # media attesa con i giorni del calendario aggiornato (18)
    _, attesa = db.calcola_media_prevista(
        db_mod.get_utente_by_id(uid)['monte_ore_settimanale'], 18)
    assert voce['media_prevista'] == round(attesa, 2)


def test_copia_precedente_settembre_usa_giugno(client, db_mod):
    """A settembre 'copia mese precedente' deve copiare da giugno, non da agosto."""
    db = db_mod
    db.create_commessa('OEPAC COPIA')
    sid = db.get_or_create_scuola('OEPAC COPIA', 'IC Copia - Primaria')
    uid = db.get_or_create_utente(sid, 'Copia', 'Giugno', 10)
    db.get_or_create_rendicontazione(uid, 2026, 6)
    db.update_rendicontazione(uid, 2026, 6, ore_lavorate=25)

    r = client.post('/api/rendicontazione/2026/9/copia-precedente', json={})
    assert r.status_code == 200, r.get_json()
    dati = db.get_rendicontazione_completa(2026, 9)
    riga = next(d for d in dati if d['utente_id'] == uid)
    assert riga['ore_lavorate_60'] == 25

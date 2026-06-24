"""Test del planner turni, delle assenze operatori e del motore di sostituzione."""


def _setup(db):
    db.create_commessa('OEPAC TEST')
    sc1 = db.get_or_create_scuola('OEPAC TEST', 'IC ALFA - Primaria')
    sc2 = db.get_or_create_scuola('OEPAC TEST', 'IC BETA - Infanzia')
    u1 = db.get_or_create_utente(sc1, 'Marco', 'Rossi', 10)
    A = db.create_dipendente({'nome': 'Anna', 'cognome': 'Verdi'})
    B = db.create_dipendente({'nome': 'Paolo', 'cognome': 'Neri'})
    C = db.create_dipendente({'nome': 'Sara', 'cognome': 'Gialli'})
    db.create_assegnazione(u1, A, 10)   # A opera nella scuola sc1
    db.create_assegnazione(u1, C, 0)    # anche C collegato a sc1
    return dict(sc1=sc1, sc2=sc2, u1=u1, A=A, B=B, C=C)


def test_turni_e_ore(db_mod):
    db = db_mod
    s = _setup(db)
    db.create_turno(s['A'], 0, '9:00', '12:00', scuola_id=s['sc1'], utente_id=s['u1'])
    db.create_turno(s['A'], 2, '09:00', '11:30')
    assert db.ore_settimanali_pianificate(s['A']) == 5.5   # 3 + 2.5
    turni = db.get_turni_dipendente(s['A'])
    assert turni[0]['ora_inizio'] == '09:00'  # orario normalizzato a HH:MM


def test_validita_temporale(db_mod):
    db = db_mod
    s = _setup(db)
    # turno valido solo da giugno
    db.create_turno(s['A'], 0, '09:00', '12:00', valido_da='2026-06-01')
    assert len(db.get_turni_dipendente(s['A'], data='2026-05-15')) == 0
    assert len(db.get_turni_dipendente(s['A'], data='2026-06-10')) == 1


def test_occorrenze_e_sostituzioni(db_mod):
    db = db_mod
    s = _setup(db)
    db.create_turno(s['A'], 0, '09:00', '12:00', scuola_id=s['sc1'], utente_id=s['u1'])  # lunedì
    # 2026-06-22 è lunedì, 06-23 martedì
    occ = db.get_turni_occorrenze(s['A'], '2026-06-22', '2026-06-23')
    assert len(occ) == 1 and occ[0]['data'] == '2026-06-22'

    ass = db.create_assenza_dipendente(s['A'], '2026-06-22', '2026-06-22', 'malattia')
    n = db.crea_sostituzioni_per_assenza(ass)
    assert n == 1
    # idempotente: non ricrea
    assert db.crea_sostituzioni_per_assenza(ass) == 0


def test_ranking_sostituti(db_mod):
    db = db_mod
    s = _setup(db)
    # B occupato in quella fascia (turno sovrapposto), C libero e nella stessa scuola
    db.create_turno(s['B'], 0, '09:00', '12:00', scuola_id=s['sc2'])
    cand = db.suggerisci_sostituti(s['sc1'], 0, '09:00', '12:00', '2026-06-22', escludi_id=s['A'])
    nomi = [c['id'] for c in cand]
    assert s['B'] not in nomi          # occupato -> escluso
    assert s['C'] in nomi              # libero -> incluso
    # C è collegato a sc1 -> priorità 1 (stessa scuola), in cima
    c_entry = next(c for c in cand if c['id'] == s['C'])
    assert c_entry['stessa_scuola'] is True
    assert cand[0]['stessa_scuola'] is True   # i "stessa scuola" stanno in cima

    # Se C si assenta in quella data, non deve comparire
    db.create_assenza_dipendente(s['C'], '2026-06-22', '2026-06-22', 'ferie')
    cand2 = db.suggerisci_sostituti(s['sc1'], 0, '09:00', '12:00', '2026-06-22', escludi_id=s['A'])
    assert s['C'] not in [c['id'] for c in cand2]


def test_validazioni(db_mod):
    import pytest
    db = db_mod
    s = _setup(db)
    # orario invertito
    with pytest.raises(ValueError):
        db.create_turno(s['A'], 0, '12:00', '09:00')
    # turno valido, poi uno sovrapposto stesso giorno -> errore
    db.create_turno(s['A'], 1, '09:00', '12:00')
    with pytest.raises(ValueError):
        db.create_turno(s['A'], 1, '11:00', '13:00')   # si sovrappone
    # stesso orario ma giorno diverso -> ok
    db.create_turno(s['A'], 3, '11:00', '13:00')
    # assenza con date invertite
    with pytest.raises(ValueError):
        db.create_assenza_dipendente(s['A'], '2026-06-10', '2026-06-01')
    # assegnazione con ore negative
    with pytest.raises(ValueError):
        db.create_assegnazione(s['u1'], s['B'], -3)


def test_assegna_sostituto_riverifica(db_mod):
    import pytest
    db = db_mod
    s = _setup(db)
    db.create_turno(s['A'], 0, '09:00', '12:00', scuola_id=s['sc1'], utente_id=s['u1'])
    db.create_turno(s['B'], 0, '09:00', '12:00')  # B occupato in quella fascia
    ass = db.create_assenza_dipendente(s['A'], '2026-06-22', '2026-06-22')
    db.crea_sostituzioni_per_assenza(ass)
    sost = db.get_sostituzioni(solo_da_coprire=True)
    sid = [x for x in sost if x['assente_id'] == s['A']][0]['id']
    # B è occupato -> assegnarlo deve fallire
    with pytest.raises(ValueError):
        db.assegna_sostituto(sid, s['B'])
    # C è libero -> ok
    db.assegna_sostituto(sid, s['C'])
    assert db.get_sostituzione(sid)['stato'] == 'coperta'

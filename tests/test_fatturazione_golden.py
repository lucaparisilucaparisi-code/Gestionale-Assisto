"""Golden test dei calcoli economici (fatturazione OEPAC).

Blocca regressioni sui numeri che finiscono nei documenti verso il committente:
imponibile, IVA, totale, credito/debito, e la coerenza degli arrotondamenti tra
vista mensile, aggregati e storico.
"""
import config
import database as db


# ---------- helper unico di fatturazione ----------

def test_calcola_fatturazione_valori_golden():
    """30 ore a 24,07 €/h + IVA 5% -> imponibile 722,10, IVA 36,11, totale 758,21."""
    assert config.calcola_fatturazione(30) == (722.10, 36.11, 758.21)
    assert config.calcola_fatturazione(0) == (0.0, 0.0, 0.0)
    assert config.calcola_fatturazione(None) == (0.0, 0.0, 0.0)


def test_calcola_fatturazione_segue_il_config(monkeypatch):
    monkeypatch.setattr(config, 'TARIFFA_ORARIA', 10.0)
    monkeypatch.setattr(config, 'IVA_PERCENTUALE', 0.10)
    assert config.calcola_fatturazione(100) == (1000.0, 100.0, 1100.0)


# ---------- pipeline completa get_rendicontazione_completa ----------

def _set_ore(db_mod, utente_id, anno, mese, ore):
    db_mod.get_or_create_rendicontazione(utente_id, anno, mese)
    db_mod.update_rendicontazione(utente_id, anno, mese, ore_lavorate=ore)


def test_rendicontazione_completa_golden(db_mod, sample_data):
    """Scenario deterministico: 15h/sett, 22 giorni da calendario, 30 ore erogate."""
    uid = sample_data['utente_id']
    db_mod.set_calendario('2025-2026', 10, 2025, 22)
    _set_ore(db_mod, uid, 2025, 10, 30)

    dati = db_mod.get_rendicontazione_completa(2025, 10)
    riga = next(d for d in dati if d['utente_id'] == uid)

    assert riga['giorni_lavorativi'] == 22
    assert riga['ore_lavorate_100'] == 30
    assert riga['imponibile_100'] == 722.10
    assert riga['iva_100'] == 36.11
    assert riga['totale_100'] == 758.21
    # media con assenza 11% su 15h*22g*0,2 = 58,74 ; credito/debito = 58,74 - 30
    assert riga['media_con_assenza_60'] == 58.74
    assert riga['credito_debito'] == 28.74


# ---------- coerenza aggregati (niente somma di arrotondamenti) ----------

def test_totali_per_scuola_niente_divergenza_arrotondamenti(db_mod, sample_data):
    """Il totale imponibile deve derivare dalle ore aggregate, non dalla somma
    dei per-riga arrotondati."""
    uid = sample_data['utente_id']
    # ore che, da sole, arrotondano in modo 'scomodo'
    _set_ore(db_mod, uid, 2025, 11, 12.33)

    totali = db_mod.get_totali_per_scuola(2025, 11)
    tot = totali[0]  # sample_data ha un'unica scuola

    ore = tot['ore_lavorate_100']
    atteso_imp, atteso_iva, atteso_tot = config.calcola_fatturazione(ore)
    assert tot['imponibile_100'] == atteso_imp
    assert tot['iva_100'] == atteso_iva
    assert tot['totale_100'] == atteso_tot


def test_api_totale_generale_coerente_con_totali_scuola(client, db_mod, sample_data):
    """Il totale generale a schermo deve coincidere col metodo contabile degli
    export (ricalcolo sulle ore), non con la somma dei per-riga arrotondati."""
    uid = sample_data['utente_id']
    _set_ore(db_mod, uid, 2025, 12, 17.77)

    body = client.get('/api/rendicontazione/2025/12').get_json()
    tg = body['totale_generale']
    atteso_imp, atteso_iva, atteso_tot = config.calcola_fatturazione(tg['ore_lavorate_100'])
    assert tg['imponibile_100'] == atteso_imp
    assert tg['iva_100'] == atteso_iva
    assert tg['totale_100'] == atteso_tot


# ---------- coerenza giorni: vista mensile vs storico ----------

def test_giorni_coerenti_mensile_vs_storico_senza_calendario(client, db_mod, sample_data):
    """Per un anno scolastico senza calendario, vista mensile e storico devono
    usare lo stesso numero di giorni (il default) e quindi la stessa previsione."""
    uid = sample_data['utente_id']
    # anno scolastico non popolato: nessun set_calendario per il 2030
    _set_ore(db_mod, uid, 2030, 10, 40)

    # Vista mensile
    dati = db_mod.get_rendicontazione_completa(2030, 10)
    riga = next(d for d in dati if d['utente_id'] == uid)

    # Storico dello stesso utente
    storico = client.get(f'/api/utente/{uid}/storico').get_json()['storico']
    voce = next(s for s in storico if s['anno'] == 2030 and s['mese'] == 10)

    assert riga['giorni_lavorativi'] == config.GIORNI_LAVORATIVI_DEFAULT
    # Stessa media prevista e stesso credito/debito nei due percorsi
    assert riga['media_con_assenza_60'] == voce['media_prevista']
    assert riga['credito_debito'] == voce['credito_debito']

"""Calcoli puri della sezione Napoli (napoli_calcoli, config_napoli; PROGETTO §5).

- Dati in ingresso: date e orari che non esistono (2025-19-39, 29:59), fasce,
  periodi e mesi, con messaggi semplici.
- Letture delle ore: griglia (ore decimali, "1,30" da confermare, sigle), totale
  scritto sul foglio firma, celle del master (anche durate [h]:mm).
- Ore riconosciute di un giorno: gli esempi del §5.2, le 33 righe dei due fogli
  firma ricostruite con orari inventati equivalenti (30 h 30 e 25 h), precedenza
  delle causali, quota 0 e 0,5, "o meta' o recupero", mezzo minuto per eccesso.
- Settimane lun-sab tagliate al mese e sommate come la VERIFICA del master (le
  domeniche a parte), tetto e avvisi del PEI.
- Regole con data e tariffe per data e livello.
- Fattura: le quantita' e le tariffe della fattura reale di giugno (non sono dati
  personali) ricalcolate al centesimo da presenze inventate; periodo parziale del
  contratto applicativo, cambio di tariffa nel periodo (anche di ritorno al valore di
  prima, e con tariffe sovrapposte), mezzo centesimo per eccesso, split payment, testi
  congelati, solo giorni registrati, coordinatore solo dal totale mensile, bloccanti
  (grado 'misto', presenze fuori da ogni contratto o in due contratti); il file
  sintetico del rapporto excel.

Solo dati inventati: nessun nome, nessun codice fiscale.
"""
import ast
import datetime
import json
import os
from decimal import Decimal as D

import pytest

import config_napoli
import napoli_calcoli as nc
import napoli_schema

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ==================== unita' ====================

def test_minuti_durata_e_forme():
    assert nc.minuti('08:30') == 510 and nc.minuti('8:30') == 510 and nc.minuti('24:00') == 1440
    for sbagliato in ('8', '8.30', '25:00', '08:60', '', None):
        with pytest.raises(ValueError):
            nc.minuti(sbagliato)
    assert nc.durata([('08:00', '10:00'), ('12:00', '14:00')]) == 240
    assert nc.durata([{'ora_inizio': '10:00', 'ora_fine': '13:00'}]) == 180
    assert nc.durata([]) == 0
    with pytest.raises(ValueError, match='sovrapposte'):
        nc.durata([('08:00', '10:00'), ('09:30', '11:00')])
    with pytest.raises(ValueError):
        nc.durata([('10:00', '09:00')])
    assert nc.ore_decimali(90) == D('1.50') and nc.ore_decimali(7291) == D('121.52')
    assert nc.ore_decimali(2) == D('0.03') and nc.ore_decimali(7292) == D('121.53') and nc.ore_decimali(1) == D('0.02')
    assert nc.hhmm(90) == '1:30' and nc.hhmm(1830) == '30:30' and nc.hhmm(-30) == '-0:30'
    assert nc.ore_due_forme(90) == '1:30 (1,50)'
    assert nc.numero_it(D('24743.72')) == '24.743,72' and nc.numero_it(D('0.5')) == '0,50'
    assert nc.minuti_da_ore(D('1.5')) == (90, True) and nc.minuti_da_ore('2,3333') == (140, False)
    assert nc.in_centesimi(D('24620.00')) == 2462000 and nc.da_centesimi(2966) == D('29.66')


# ==================== dati in ingresso ====================

@pytest.mark.parametrize('scritto, attesa', [
    ('2026-06-08', '2026-06-08'), ('2026-6-8', '2026-06-08'), ('08/06/2026', '2026-06-08'), ('8/6/2026', '2026-06-08'),
    ('08.06.2026', '2026-06-08'), (' 29/02/2028 ', '2028-02-29'), (datetime.date(2026, 6, 8), '2026-06-08'),
    (datetime.datetime(2026, 6, 8, 10, 30), '2026-06-08')])
def test_valida_data(scritto, attesa):
    assert nc.valida_data(scritto) == attesa


@pytest.mark.parametrize('scritto, messaggio', [
    ('2025-19-39', 'non esiste'), ('31/02/2026', 'non esiste'), ('29/02/2026', 'non esiste'), ('2026-06-31', 'non esiste'),
    ('0202-06-08', 'anno fuori'), ('08/06/26', 'non e\' scritta bene'), ('domani', 'non e\' scritta bene'),
    ('2026-06-08T10:00', 'non e\' scritta bene'), ('', 'manca'), (None, 'manca')])
def test_valida_data_rifiuta_le_date_che_non_esistono(scritto, messaggio):
    with pytest.raises(ValueError, match=messaggio):
        nc.valida_data(scritto)


def test_valida_orari_fasce_periodi_e_mesi():
    assert [nc.valida_orario(x) for x in ('8:30', '08:30', '08.30', '00:00', '23:59', datetime.time(9, 5))] == [
        '08:30', '08:30', '08:30', '00:00', '23:59', '09:05']
    for sbagliato, messaggio in (('29:59', 'non esiste'), ('24:00', 'non esiste'), ('10:75', 'non esiste'),
                                 ('10:7', 'non e\' scritto bene'), ('8', 'non e\' scritto bene'), ('', 'manca')):
        with pytest.raises(ValueError, match=messaggio):
            nc.valida_orario(sbagliato)
    assert nc.valida_fascia('8:00', '10:00') == ('08:00', '10:00')
    with pytest.raises(ValueError, match='deve venire dopo'):
        nc.valida_fascia('10:00', '10:00')
    assert nc.valida_fasce([('12:00', '14:00'), {'ora_inizio': '8:00', 'ora_fine': '10:00'}]) == [
        ('08:00', '10:00'), ('12:00', '14:00')]
    assert nc.valida_fasce([('08:00', '10:00'), ('10:00', '11:00')]) == [('08:00', '10:00'), ('10:00', '11:00')]
    with pytest.raises(ValueError, match='si sovrappongono'):
        nc.valida_fasce([('08:00', '10:00'), ('09:30', '11:00')])
    assert nc.valida_fasce([]) == []
    assert nc.valida_periodo('01/09/2025', '') == ('2025-09-01', None)
    assert nc.valida_periodo('2025-09-01', '31/01/2027') == ('2025-09-01', '2027-01-31')
    assert nc.valida_periodo('2026-06-08', '2026-06-08') == ('2026-06-08', '2026-06-08')
    with pytest.raises(ValueError, match='viene prima'):
        nc.valida_periodo('2026-06-08', '2026-06-07')
    with pytest.raises(ValueError, match='manca'):
        nc.valida_periodo('2026-06-08', None, fine_obbligatoria=True)
    with pytest.raises(ValueError, match='non esiste'):
        nc.valida_periodo('2026-06-08', '2026-13-01')
    assert nc.valida_mese(2026, 6) == (2026, 6) and nc.valida_mese('2026', ' 10 ') == (2026, 10)
    for anno, mese in ((2026, 13), (2026, 0), (1999, 5), (2026, 6.5), (2026, True), ('2026', 'giugno'), (None, 1)):
        with pytest.raises(ValueError):
            nc.valida_mese(anno, mese)
    # messaggi per l'utente: niente nomi tecnici
    try:
        nc.valida_data('2025-19-39')
    except ValueError as e:
        assert 'ValueError' not in str(e) and 'isoformat' not in str(e) and str(e).startswith('La data')


# ==================== letture (§5.1) ====================

@pytest.mark.parametrize('scritto, minuti', [
    ('2', 120), ('1,5', 90), ('1.5', 90), ('0,75', 45), ('1:30', 90), (' 3 ', 180), ('0,25', 15), (',5', 30)])
def test_griglia_ore_decimali_e_ore_minuti(scritto, minuti):
    esito = nc.leggi_ore_griglia(scritto)
    assert (esito['esito'], esito['minuti'], esito['causale']) == ('ore', minuti, None)


@pytest.mark.parametrize('scritto, ore_minuti, decimale', [
    ('1,30', 90, 78), ('1,15', 75, 69), ('1,45', 105, 87), ('1,20', 80, 72), ('1.30', 90, 78)])
def test_griglia_decimali_non_quarti_da_confermare(scritto, ore_minuti, decimale):
    esito = nc.leggi_ore_griglia(scritto)
    assert esito['esito'] == 'da_confermare' and esito['codice'] == 'ore_ambigue' and esito['minuti'] is None
    assert [(a['lettura'], a['minuti']) for a in esito['alternative']] == [
        ('ore_e_minuti', ore_minuti), ('decimale', decimale)]
    assert nc.leggi_ore_griglia(scritto, conferma='ore_e_minuti')['minuti'] == ore_minuti
    assert nc.leggi_ore_griglia(scritto, conferma='decimale')['minuti'] == decimale


def test_griglia_domanda_e_letture_senza_minuti():
    assert nc.leggi_ore_griglia('1,30')['domanda'] == '1 h 30 min oppure 1,30 ore decimali (1:18)?'
    # '1,3' e' il tipico "1,30" scritto senza lo zero (PROGETTO §1.4): le stesse due letture
    esito = nc.leggi_ore_griglia('1,3')
    assert esito['esito'] == 'da_confermare' and esito['domanda'] == '1 h 30 min oppure 1,3 ore decimali (1:18)?'
    assert [(a['lettura'], a['minuti']) for a in esito['alternative']] == [('ore_e_minuti', 90), ('decimale', 78)]
    assert nc.leggi_ore_griglia('1,3', conferma='ore_e_minuti')['minuti'] == 90
    assert nc.leggi_ore_griglia('1,3', conferma='decimale')['minuti'] == 78
    # cifre che non possono essere minuti: una lettura sola, niente domanda ma un avviso
    for scritto, conferma in (('1,7', None), ('1,7', 'ore_e_minuti'), ('1,70', None)):
        esito = nc.leggi_ore_griglia(scritto, conferma=conferma)
        assert (esito['esito'], esito['minuti'], esito['avvisi']) == ('ore', 102, ['letto_come_decimale']), scritto
    arrotondato = nc.leggi_ore_griglia('1,333')
    assert (arrotondato['minuti'], arrotondato['avvisi']) == (80, ['letto_come_decimale', 'ore_arrotondate_al_minuto'])


@pytest.mark.parametrize('scritto, causale', [
    ('F', 'operatore_ferie'), ('f', 'operatore_ferie'), ('F ', 'operatore_ferie'), ('M', 'operatore_malattia'),
    ('P', 'operatore_permesso'), ('Fperm', 'operatore_permesso'), ('F perm', 'operatore_permesso'),
    ('F (PERM)', 'operatore_permesso'), ('F (perm)', 'operatore_permesso'), ('F perm)', 'operatore_permesso'),
    ('F PERM', 'operatore_permesso')])
def test_griglia_sigle_operatore(scritto, causale):
    esito = nc.leggi_ore_griglia(scritto)
    assert (esito['esito'], esito['minuti'], esito['causale']) == ('sigla', 0, causale)
    assert esito['sigla'] == nc.SIGLE[causale]


def test_griglia_alunno_assente_vuoto_e_sconosciute():
    senza = nc.leggi_ore_griglia('A')
    assert senza['causale'] == 'alunno_assente' and senza['minuti'] is None
    assert senza['codice'] == 'servono_minuti_programmati' and senza['trattamento'] == 'meta'
    assert nc.leggi_ore_griglia('a', minuti_programmati=180)['minuti'] == 90
    assert nc.leggi_ore_griglia('A', minuti_programmati=105)['minuti'] == 53          # mezzo minuto per eccesso
    con_quota_zero = nc.leggi_ore_griglia('A', minuti_programmati=180, regole={'quota_assenza_alunno': D('0')})
    assert con_quota_zero['minuti'] == 0 and con_quota_zero['trattamento'] == 'banca'
    assert nc.leggi_ore_griglia('')['esito'] == 'vuoto' and nc.leggi_ore_griglia(None)['esito'] == 'vuoto'
    for sconosciuta in ('X', 'ferie?', '-1', '1,5h'):
        esito = nc.leggi_ore_griglia(sconosciuta)
        assert esito['esito'] == 'errore' and esito['codice'] == 'sigla_sconosciuta', sconosciuta


@pytest.mark.parametrize('scritto, minuti, lettura', [
    ('30', 1800, None), ('25', 1500, None), ('1,15', 75, 'letto_come_ore_e_minuti'),
    ('1,30', 90, 'letto_come_ore_e_minuti'), ('30,45', 1845, 'letto_come_ore_e_minuti'),
    ('1,25', 75, 'letto_come_decimale'), ('1,5', 90, 'letto_come_decimale'), ('1,50', 90, 'letto_come_decimale'),
    ('1,75', 105, 'letto_come_decimale'), ('2,00', 120, None), ('30:30', 1830, None)])
def test_totale_scritto_sul_foglio(scritto, minuti, lettura):
    esito = nc.leggi_ore_foglio(scritto)
    assert (esito['esito'], esito['minuti']) == ('ore', minuti)
    assert esito['avvisi'] == ([lettura] if lettura else [])


def test_totale_scritto_ambiguo_o_illeggibile():
    esito = nc.leggi_ore_foglio('1,20')
    assert esito['esito'] == 'da_confermare' and [a['minuti'] for a in esito['alternative']] == [80, 72]
    assert nc.leggi_ore_foglio('1,20', conferma='decimale')['minuti'] == 72
    # "30,30" scritto senza lo zero: si chiede, con tutte e due le letture
    trenta = nc.leggi_ore_foglio('30,3')
    assert [(a['lettura'], a['minuti']) for a in trenta['alternative']] == [('ore_e_minuti', 1830), ('decimale', 1818)]
    assert nc.leggi_ore_foglio('30,3', conferma='ore_e_minuti')['minuti'] == 1830
    uno_otto = nc.leggi_ore_foglio('1,8')           # le cifre non possono essere minuti: decimale
    assert (uno_otto['minuti'], uno_otto['avvisi']) == (108, ['letto_come_decimale'])
    assert nc.leggi_ore_foglio('trenta')['codice'] == 'totale_non_riconosciuto'
    assert nc.leggi_ore_foglio('  ')['esito'] == 'vuoto'


@pytest.mark.parametrize('valore, minuti, avvisi', [
    (1.5, 90, []), (2, 120, []), (D('0.75'), 45, []), ('1,5', 90, ['numero_come_testo']),
    ('2.25', 135, ['numero_come_testo']), ('1:30', 90, ['numero_come_testo']),
    (2.3333333, 140, ['ore_arrotondate_al_minuto', 'ore_non_multiple_di_un_quarto']),
    (1.3, 78, ['ore_non_multiple_di_un_quarto']), (datetime.time(1, 30), 90, ['cella_in_formato_orario']),
    # durata [h]:mm di Excel (openpyxl la legge come timedelta), anche con il rumore della virgola mobile
    (datetime.timedelta(hours=1, minutes=30), 90, ['cella_in_formato_orario']),
    (datetime.timedelta(hours=26, minutes=15), 1575, ['cella_in_formato_orario']),
    (datetime.timedelta(seconds=5399, microseconds=999999), 90, ['cella_in_formato_orario']),
    (datetime.timedelta(minutes=52, seconds=30), 53, ['cella_in_formato_orario', 'ore_arrotondate_al_minuto'])])
def test_cella_master_ore(valore, minuti, avvisi):
    esito = nc.leggi_cella_master(valore)
    assert (esito['esito'], esito['minuti'], esito['avvisi']) == ('ore', minuti, avvisi)


def test_cella_master_sigle_vuoti_ed_errori():
    assert nc.leggi_cella_master('F')['causale'] == 'operatore_ferie' and nc.leggi_cella_master('F')['avvisi'] == []
    variante = nc.leggi_cella_master('F (PERM)')
    assert (variante['causale'], variante['sigla'], variante['minuti']) == ('operatore_permesso', 'F perm', 0)
    assert variante['avvisi'] == ['sigla_scritta_in_variante']
    assert nc.leggi_cella_master('M')['causale'] == 'operatore_malattia'
    assert nc.leggi_cella_master(None)['esito'] == 'vuoto' and nc.leggi_cella_master('  ')['minuti'] == 0
    for valore, codice in (('ZZ', 'sigla_sconosciuta'), ('A', 'sigla_sconosciuta'), (-1, 'ore_negative'),
                           (True, 'cella_non_riconosciuta'), (datetime.date(2026, 3, 2), 'cella_non_riconosciuta'),
                           (float('nan'), 'cella_non_riconosciuta'), (float('inf'), 'cella_non_riconosciuta'),
                           (D('NaN'), 'cella_non_riconosciuta'), (datetime.timedelta(minutes=-30), 'ore_negative')):
        esito = nc.leggi_cella_master(valore)
        assert (esito['esito'], esito['codice']) == ('errore', codice), valore


# ==================== ore riconosciute di un giorno (§5.2) ====================

@pytest.mark.parametrize('programmato, effettivo, causale, minuti', [
    ([('10:00', '13:00')], [], 'alunno_assente', 90),                                  # 1 h 30 min (1,50)
    ([('10:00', '14:00')], [], 'alunno_assente', 120),
    ([('08:00', '10:00'), ('12:00', '14:00')], [], 'alunno_assente', 120),
    ([('12:00', '14:00')], [], 'alunno_assente', 60),
    ([('08:00', '09:00'), ('10:00', '12:00')], [('10:00', '12:00')], 'alunno_parziale', 150),   # entrato alle 9
    ([('10:00', '14:00')], [('10:00', '13:00')], 'evento', 180),                       # assemblea
    ([('10:00', '14:00')], [('08:00', '11:00')], 'attivita_esterna', 180),             # cineforum
    ([('12:00', '14:00')], [], ['alunno_assente', 'evento'], 0),                       # lectio brevis: vince l'evento
    ([('10:00', '14:00')], [], 'operatore_ferie', 0),                                  # nessun sostituto
    ([('10:00', '11:00'), ('12:00', '13:00')], [], 'evento', 0),                       # assemblea, nulla svolto
    ([('08:00', '09:45')], [], 'alunno_assente', 53),                                  # 52,5 -> per eccesso
])
def test_esempi_della_tabella(programmato, effettivo, causale, minuti):
    assert nc.minuti_riconosciuti(fasce_p=programmato, fasce_e=effettivo, causale=causale) == minuti


# Fogli firma ricostruiti con orari inventati: stesse durate e stesse causali delle
# righe compilate dei due fogli veri (programmato, effettivo, causale, attesi).
DUE_FASCE = [('08:30', '10:30'), ('11:30', '13:30')]
QUATTRO = [('09:00', '13:00')]
TRE = [('09:00', '12:00')]
FOGLIO_1 = [
    (DUE_FASCE, DUE_FASCE, None, 240), (DUE_FASCE, DUE_FASCE, None, 240), (QUATTRO, [], 'operatore_ferie', 0),
    (TRE, [], 'alunno_assente', 90), (QUATTRO, [], 'alunno_assente', 120), (DUE_FASCE, [], 'alunno_assente', 120),
    (QUATTRO, [], 'alunno_assente', 120), (TRE, [], 'alunno_assente', 90), (QUATTRO, [], 'alunno_assente', 120),
    (QUATTRO, [], 'alunno_assente', 120), (DUE_FASCE, [], 'alunno_assente', 120), (TRE, [], 'alunno_assente', 90),
    (QUATTRO, [('08:30', '11:30')], 'attivita_esterna', 180), (DUE_FASCE, [], 'operatore_malattia', 0),
    (QUATTRO, [('09:00', '12:00')], 'evento', 180),
]
DUE = [('11:00', '13:00')]
TRE_B = [('11:00', '14:00')]
MATTINA = [('07:45', '08:45'), ('09:45', '11:45')]
SPEZZATO = [('09:30', '10:30'), ('11:30', '12:30')]
FOGLIO_2 = [
    (DUE, [], ['alunno_assente', 'evento'], 0), (DUE, [], 'alunno_assente', 60), (SPEZZATO, [], 'operatore_ferie', 0),
    (TRE_B, TRE_B, None, 180), (TRE_B, [], 'alunno_assente', 90), (MATTINA, MATTINA, None, 180), (DUE, DUE, None, 120),
    (SPEZZATO, SPEZZATO, None, 120), (TRE_B, [], 'alunno_assente', 90), (TRE_B, TRE_B, None, 180),
    (MATTINA, [('09:45', '11:45')], 'alunno_parziale', 150), (DUE, DUE, None, 120), (SPEZZATO, SPEZZATO, None, 120),
    (TRE_B, [], 'alunno_assente', 90), (TRE_B, [], 'operatore_permesso', 0), (MATTINA, [], 'operatore_malattia', 0),
    (DUE, [], 'operatore_altro', 0), (SPEZZATO, [], 'evento', 0),
]


@pytest.mark.parametrize('foglio, totale, scritto, differenza', [
    (FOGLIO_1, 1830, '30', 30),      # 30 h 30 min; sul foglio "30": si segnala
    (FOGLIO_2, 1500, '25', None),    # 25 h: coincide
])
def test_fogli_firma(foglio, totale, scritto, differenza):
    righe = [nc.minuti_riconosciuti(fasce_p=p, fasce_e=e, causale=c) for p, e, c, _ in foglio]
    assert righe == [atteso for *_, atteso in foglio]
    assert sum(righe) == totale
    confronto = nc.confronta_totale_scritto(sum(righe), nc.leggi_ore_foglio(scritto)['minuti'])
    assert (confronto and confronto['differenza']) == differenza


def test_righe_dei_fogli_sono_33():
    assert len(FOGLIO_1) + len(FOGLIO_2) == 33


def test_precedenza_delle_causali():
    assert nc.causale_prevalente(['alunno_assente', 'operatore_ferie', 'evento', 'calendario']) == 'calendario'
    assert nc.causale_prevalente(['alunno_parziale', 'attivita_esterna']) == 'attivita_esterna'
    assert nc.causale_prevalente(('alunno_assente', 'operatore_malattia')) == 'operatore_malattia'
    assert nc.causale_prevalente(None) is None and nc.causale_prevalente(['', None]) is None
    with pytest.raises(ValueError):
        nc.causale_prevalente('sciopero')
    # alunno assente in un giorno di ferie dell'operatore: vale l'operatore (0, non la meta')
    assert nc.minuti_riconosciuti(fasce_p=QUATTRO, causale=['alunno_assente', 'operatore_ferie']) == 0
    # evento e attivita' esterna vincono sull'operatore: contano le ore svolte e la causale riportata e' la loro
    assert nc.causale_prevalente(['operatore_ferie', 'evento']) == 'evento'
    assert nc.causale_prevalente(('operatore_malattia', 'operatore_permesso', 'attivita_esterna')) == 'attivita_esterna'
    for causali, attesa in ((['operatore_malattia', 'evento'], 'evento'),
                            (['attivita_esterna', 'operatore_permesso', 'alunno_parziale'], 'attivita_esterna'),
                            (['alunno_assente', 'operatore_altro'], 'operatore_altro')):
        esito = nc.esito_giorno(fasce_p=QUATTRO, fasce_e=TRE, causale=causali)
        assert (esito['causale'], esito['minuti']) == (attesa, 180), causali
    chiuso = nc.esito_giorno(fasce_p=QUATTRO, fasce_e=TRE, causale=['evento', 'operatore_ferie', 'calendario'])
    assert (chiuso['causale'], chiuso['minuti']) == ('calendario', 0)


def test_quota_meta_o_recupero():
    meta = nc.esito_giorno(fasce_p=QUATTRO, causale='alunno_assente')
    assert (meta['minuti'], meta['trattamento']) == (120, 'meta')
    # o meta' o recupero: se l'assenza e' recuperata non si conta la meta'
    assert nc.minuti_riconosciuti(fasce_p=QUATTRO, causale='alunno_assente', trattamento='recupero') == 0
    assert nc.minuti_riconosciuti(fasce_p=MATTINA, fasce_e=[('09:45', '11:45')], causale='alunno_parziale',
                                  trattamento='recupero') == 120
    # quota 0 (nuovo accordo, CSA): niente meta', il trattamento predefinito diventa banca ore
    zero = nc.esito_giorno(fasce_p=QUATTRO, causale='alunno_assente', regole={'quota_assenza_alunno': D('0')})
    assert (zero['minuti'], zero['trattamento']) == (0, 'banca')
    assert nc.minuti_riconosciuti(fasce_p=QUATTRO, fasce_e=[('09:00', '10:00')], causale='alunno_parziale',
                                  regole={'quota_assenza_parziale': D('0')}) == 60
    # giorno di recupero: contano le ore svolte, compresi i minuti di recupero
    assert nc.minuti_riconosciuti(fasce_p=TRE, fasce_e=[('09:00', '13:00')], minuti_extra=60) == 240
    # ... anche con una causale dell'alunno: S, senza la meta' (altrimenti 180 e 120)
    assert nc.minuti_riconosciuti(fasce_p=QUATTRO, fasce_e=[('10:00', '12:00')], causale='alunno_parziale',
                                  minuti_extra=30) == 120
    assert nc.minuti_riconosciuti(fasce_p=QUATTRO, fasce_e=[('13:00', '14:00')], causale='alunno_assente',
                                  minuti_extra=60) == 60
    # mezzo minuto per difetto, se la regola cambia
    assert nc.minuti_riconosciuti(fasce_p=[('08:00', '09:45')], causale='alunno_assente',
                                  regole={'arrotondamento_mezzo_minuto': 'difetto'}) == 52
    with pytest.raises(ValueError):
        nc.esito_giorno(fasce_p=TRE, causale='alunno_assente', trattamento='mezzo')


def test_stato_calcolo_e_avvisi_del_giorno():
    preparato = nc.esito_giorno(fasce_p=QUATTRO, stato='programmato')
    assert preparato['minuti'] == 0 and preparato['avvisi'] == ['giorno_non_registrato']
    # numero scritto in griglia o importato: vale quello, si segnala la differenza dalla formula
    manuale = nc.esito_giorno(fasce_p=QUATTRO, fasce_e=QUATTRO, calcolo='manuale', minuti_scritti=180)
    assert manuale['minuti'] == 180 and manuale['formula'] == 240 and manuale['avvisi'] == ['diverso_dalla_formula']
    importato = nc.esito_giorno(calcolo='manuale', minuti_scritti=150)          # nessuna formula calcolabile
    assert importato['minuti'] == 150 and importato['avvisi'] == []
    assert nc.esito_giorno(minuti_programmati=240, minuti_svolti=200)['minuti'] == 200
    dimenticato = nc.esito_giorno(fasce_p=QUATTRO)        # registrato senza orario effettivo: mai "come programmato"
    assert dimenticato['minuti'] == 0 and dimenticato['avvisi'] == ['svolto_mancante']
    chiuso = nc.esito_giorno(fasce_p=QUATTRO, fasce_e=TRE, causale='calendario')
    assert chiuso['minuti'] == 0 and chiuso['avvisi'] == ['ore_in_giorno_di_chiusura']
    assert nc.esito_giorno(fasce_p=QUATTRO, causale='calendario')['avvisi'] == []
    permesso_a_ore = nc.esito_giorno(fasce_p=QUATTRO, fasce_e=[('09:00', '11:00')], causale='operatore_permesso')
    assert permesso_a_ore['minuti'] == 120
    con_ore = nc.esito_giorno(fasce_p=QUATTRO, fasce_e=TRE, causale='alunno_assente')
    assert con_ore['minuti'] == 120 and con_ore['avvisi'] == ['ore_svolte_con_alunno_assente']
    with pytest.raises(ValueError):
        nc.esito_giorno(calcolo='manuale')


def test_limiti_del_giorno():
    assert nc.controlla_minuti_giorno(300) == []
    assert nc.controlla_minuti_giorno(301) == [{'livello': 'avviso', 'codice': 'ore_giorno_oltre_5'}]
    assert nc.controlla_minuti_giorno(720)[0]['livello'] == 'avviso'
    assert nc.controlla_minuti_giorno(721) == [{'livello': 'bloccante', 'codice': 'ore_giorno_oltre_12'}]
    assert nc.controlla_minuti_giorno(400, {'max_minuti_giorno_avviso': 420}) == []


# ==================== settimane e PEI (§5.3) ====================

def test_settimane_lun_sab_tagliate_al_mese():
    giugno = nc.settimane_mese(2026, 6)             # inizia di lunedi'
    assert [(s[0].day, s[-1].day, len(s)) for s in giugno] == [(1, 6, 6), (8, 13, 6), (15, 20, 6), (22, 27, 6),
                                                              (29, 30, 2)]
    marzo = nc.settimane_mese(2026, 3)              # inizia di domenica: la domenica non c'e'
    assert [(s[0].day, s[-1].day) for s in marzo] == [(2, 7), (9, 14), (16, 21), (23, 28), (30, 31)]
    novembre = nc.settimane_mese(2026, 11, giorni_servizio=(0, 1, 2, 3, 4))
    assert [(s[0].day, s[-1].day) for s in novembre] == [(2, 6), (9, 13), (16, 20), (23, 27), (30, 30)]
    colonne = nc.colonne_mese(2026, 3)
    assert colonne[:7] == [('giorno', datetime.date(2026, 3, d)) for d in range(2, 8)] + [('verifica', 1)]
    assert colonne[-1] == ('verifica', 5) and len(colonne) == 26 + 5
    assert len(nc.giorni_mese(2026, 6)) == 26


@pytest.mark.parametrize('pei, vicino, eccesso', [(2, 2, 3), (7, 8, 9), (8, 10, 10), (12, 14, 15), (13, 16, 16),
                                                  (D('2.5'), 3, 3), (D('3.75'), 5, 5)])   # 4,5: il mezzo va su
def test_tetto_settimanale(pei, vicino, eccesso):
    assert nc.tetto_settimanale(pei) == vicino
    assert nc.tetto_settimanale(pei, modo='vicino') == vicino and nc.tetto_settimanale(pei, modo='eccesso') == eccesso


def test_verifica_settimane_contro_il_pei():
    # PEI 10 h (tetto 12): settimana 1 a 10 h, settimana 2 a 11 h (giallo), settimana 3 a 13 h (rosso)
    giorni = {'2026-06-01': 300, '2026-06-03': 300, '2026-06-08': 360, '2026-06-10': 300,
              '2026-06-15': 400, '2026-06-17': 380}
    esito = nc.verifica_settimane(giorni, 2026, 6, 10)
    assert [(v['settimana'], v['minuti'], v['codice'], v['colore']) for v in esito] == [
        (1, 600, None, None), (2, 660, 'settimana_oltre_pei', 'giallo'),
        (3, 780, 'settimana_oltre_pei_piu_20', 'rosso'), (4, 0, None, None), (5, 0, None, None)]
    assert esito[0]['pei_minuti'] == 600 and esito[0]['tetto_minuti'] == 720
    assert (esito[4]['dal'], esito[4]['al']) == (datetime.date(2026, 6, 29), datetime.date(2026, 6, 30))
    # titolare e sostituto nello stesso giorno si sommano (coppie di valori)
    doppio = nc.verifica_settimane([('2026-06-01', 300), ('2026-06-01', 360)], 2026, 6, 10)
    assert doppio[0]['minuti'] == 660 and doppio[0]['codice'] == 'settimana_oltre_pei'
    # PEI per periodi: dal 10/06 sale a 12 h; nella settimana del cambio vale il piu' alto
    periodi = [{'ore_settimanali': 10, 'valido_da': '2025-09-15', 'valido_a': '2026-06-09'},
               {'ore_settimanali': 12, 'valido_da': '2026-06-10', 'valido_a': None}]
    cambio = nc.verifica_settimane(giorni, 2026, 6, periodi)
    assert [v['pei_minuti'] for v in cambio] == [600, 720, 720, 720, 720]
    assert cambio[1]['codice'] is None and cambio[2]['codice'] == 'settimana_oltre_pei'
    senza_pei = nc.verifica_settimane(giorni, 2026, 6, None)
    assert all(v['codice'] is None and v['pei_minuti'] is None for v in senza_pei)
    with pytest.raises(ValueError):
        nc.verifica_settimane({'2026-07-01': 60}, 2026, 6, 10)


def test_verifica_settimane_numerate_come_le_colonne():
    # marzo 2026 inizia di domenica: la settimana 2-7 marzo resta la VERIFICA 1. Come la VERIFICA
    # del master (somma da lunedi' a sabato) le domeniche, all'inizio (01/03) o a meta' mese
    # (08/03), non entrano in nessuna settimana: sono voci a parte da correggere o spiegare
    esito = nc.verifica_settimane({'2026-03-01': 60, '2026-03-02': 120, '2026-03-08': 45, '2026-03-31': 30},
                                  2026, 3, 10)
    assert [(v['settimana'], v['dal'].day, v['al'].day, v['minuti'], v['codice']) for v in esito] == [
        (None, 1, 1, 60, 'ore_in_giorno_non_di_servizio'), (1, 2, 7, 120, None),
        (None, 8, 8, 45, 'ore_in_giorno_non_di_servizio'), (2, 9, 14, 0, None), (3, 16, 21, 0, None),
        (4, 23, 28, 0, None), (5, 30, 31, 30, None)]
    assert esito[0]['giorni'] == [] and esito[0]['pei_minuti'] is None
    verifiche = [n for tipo, n in nc.colonne_mese(2026, 3) if tipo == 'verifica']
    assert [v['settimana'] for v in esito if v['settimana'] is not None] == verifiche
    # la somma di ogni settimana e' quella della colonna VERIFICA: solo i giorni del master
    colonne = nc.colonne_mese(2026, 3)
    giorni = {'2026-03-01': 60, '2026-03-02': 120, '2026-03-08': 45, '2026-03-31': 30}
    for v in esito:
        if v['settimana'] is not None:
            assert v['minuti'] == sum(m for d, m in giorni.items()
                                      if ('giorno', datetime.date.fromisoformat(d)) in colonne
                                      and datetime.date.fromisoformat(d) in v['giorni'])
    # 10 h di PEI: con la domenica 08/03 la settimana sarebbe oltre il PEI, senza no
    oltre = nc.verifica_settimane({'2026-03-02': 600, '2026-03-08': 60}, 2026, 3, 10)
    assert [v['codice'] for v in oltre][:3] == [None, 'ore_in_giorno_non_di_servizio', None]
    # senza ore di domenica non compaiono voci a parte
    assert [v['settimana'] for v in nc.verifica_settimane({'2026-03-02': 60}, 2026, 3, 10)] == verifiche
    # con il servizio da lunedi' a venerdi' anche il sabato e' fuori servizio
    feriale = nc.verifica_settimane({'2026-06-06': 60}, 2026, 6, 10, {'giorni_servizio': (0, 1, 2, 3, 4)})
    assert [(v['settimana'], v['codice']) for v in feriale][:2] == [(1, None), (None, 'ore_in_giorno_non_di_servizio')]


def test_programmato_diverso_dal_pei():
    assert nc.confronta_programmazione(600, 10) is None
    assert nc.confronta_programmazione(540, D('9.5')) == {'codice': 'programmato_diverso_dal_pei',
                                                          'programmati': 540, 'attesi': 570, 'differenza': -30}


# ==================== regole con data (§5.6) ====================

REGOLE_DB = [
    {'lotto_id': None, 'chiave': 'quota_assenza_alunno', 'valore': '0.5', 'valido_da': '2025-09-01',
     'valido_a': '2027-01-31'},
    {'lotto_id': None, 'chiave': 'quota_assenza_alunno', 'valore': '0', 'valido_da': '2027-02-01', 'valido_a': None},
    {'lotto_id': 3, 'chiave': 'giorni_pagamento', 'valore': '60', 'valido_da': '2026-01-01', 'valido_a': None},
    {'lotto_id': 3, 'chiave': 'giorni_pagamento', 'valore': '45', 'valido_da': '2026-09-01', 'valido_a': None},
    {'lotto_id': None, 'chiave': 'giorni_pagamento', 'valore': '40', 'valido_da': '2026-01-01', 'valido_a': None},
]


def test_regola_valida_nella_data():
    assert nc.regola('quota_assenza_alunno', '2026-06-15', REGOLE_DB) == D('0.5')
    assert nc.regola('quota_assenza_alunno', '2027-02-01', REGOLE_DB) == 0
    # prima il lotto, poi tutti i lotti, poi il predefinito; sempre la riga piu' recente
    assert nc.regola('giorni_pagamento', '2026-10-01', REGOLE_DB, lotto_id=3) == 45
    assert nc.regola('giorni_pagamento', '2026-06-01', REGOLE_DB, lotto_id=3) == 60
    assert nc.regola('giorni_pagamento', '2026-06-01', REGOLE_DB, lotto_id=4) == 40
    assert nc.regola('giorni_pagamento', '2025-10-01', REGOLE_DB, lotto_id=3) == 30
    dettaglio = nc.regola_dettaglio('giorni_pagamento', '2026-10-01', REGOLE_DB, lotto_id=3)
    assert (dettaglio['origine'], dettaglio['valido_da']) == ('lotto', '2026-09-01')
    # lotto come testo (parametro di una richiesta) o righe con l'id come testo: e' lo stesso lotto
    assert nc.regola_dettaglio('giorni_pagamento', '2026-10-01', REGOLE_DB, lotto_id='3')['origine'] == 'lotto'
    come_testo = [dict(r, lotto_id=str(r['lotto_id'])) if r['lotto_id'] else r for r in REGOLE_DB]
    assert nc.regola('giorni_pagamento', '2026-10-01', come_testo, lotto_id=3) == 45
    assert nc.regola_dettaglio('giorni_pagamento', '2026-06-01', REGOLE_DB, lotto_id='')['origine'] == 'tutti'
    # il predefinito vale anche fuori dalle sue date, ma lo dice
    assert nc.regola_dettaglio('quota_assenza_alunno', '2026-06-15')['fuori_validita'] is False
    oltre = nc.regola_dettaglio('quota_assenza_alunno', datetime.date(2027, 3, 1))
    assert (oltre['valore'], oltre['origine'], oltre['fuori_validita']) == (D('0.5'), 'predefinita', True)
    tutte = nc.regole_alla_data('2027-03-01', REGOLE_DB, lotto_id=3)
    assert set(tutte) == set(config_napoli.REGOLE_PREDEFINITE)
    assert tutte['quota_assenza_alunno'] == 0 and tutte['giorni_pagamento'] == 45 and tutte['iva_percento'] == 5
    with pytest.raises(ValueError):
        nc.regola('regola_inventata', '2026-06-01')


def test_valore_regola_nel_suo_tipo():
    assert nc.valore_regola('ritenuta_percento', '0.50') == D('0.50')
    assert nc.valore_regola('iva_percento', 5) == D('5')
    assert nc.valore_regola('giorni_pagamento', '30') == 30
    assert nc.valore_regola('split_payment', 'false') is False and nc.valore_regola('split_payment', 1) is True
    assert nc.valore_regola('tetto_arrotondamento', '"eccesso"') == 'eccesso'
    assert nc.valore_regola('tetto_arrotondamento', 'eccesso') == 'eccesso'
    assert nc.valore_regola('giorni_servizio', '[5, 0, 1, 2, 3, 4]') == (0, 1, 2, 3, 4, 5)
    assert nc.valore_regola('ritenuta_testo', 'RITENUTA {percento}%') == 'RITENUTA {percento}%'
    assert nc.valore_regola('ritenuta_testo', '"Testo"') == 'Testo'
    assert nc.valore_regola('trattamento_alunno_predefinito', 'null') is None
    for chiave, sbagliato in (('ritenuta_percento', '-1'), ('ritenuta_percento', 'tanto'),
                              ('giorni_pagamento', '30.5'), ('giorni_pagamento', 'true'), ('split_payment', '2'),
                              ('tetto_arrotondamento', 'sempre'), ('giorni_servizio', '[7]'), ('mesi_uso_D', '4'),
                              ('ritenuta_testo', 5), ('chiave_inventata', '1')):
        with pytest.raises(ValueError):
            nc.valore_regola(chiave, sbagliato)


def test_regole_predefinite_coerenti():
    for chiave, p in config_napoli.REGOLE_PREDEFINITE.items():
        assert {'valore', 'tipo', 'dal', 'al', 'fonte', 'stato'} <= set(p), chiave
        assert p['stato'] in ('confermata', 'da_confermare', 'fase_2'), chiave
        assert nc.valore_regola(chiave, p['valore']) == p['valore'], chiave
        datetime.date.fromisoformat(p['dal'])
    p = config_napoli.REGOLE_PREDEFINITE
    assert (p['ritenuta_percento']['valore'], p['iva_percento']['valore'], p['split_payment']['valore']) == (
        D('0.50'), D('5'), True)
    assert p['quota_assenza_alunno']['al'] == '2027-01-31'


# ==================== tariffe ====================

TARIFFE = [
    {'figura': 'ASACOM', 'livello_ccnl': None, 'tariffa_cent': 2344, 'valido_da': '2025-09-01',
     'valido_a': '2027-01-31'},
    {'figura': 'EDUCATORE', 'livello_ccnl': None, 'tariffa_cent': 2428, 'valido_da': '2025-09-01',
     'valido_a': '2027-01-31'},
    {'figura': 'TIFLOLOGO', 'livello_ccnl': None, 'tariffa_cent': 2428, 'valido_da': '2025-09-01',
     'valido_a': '2027-01-31'},
    {'figura': 'PSICOLOGO', 'livello_ccnl': None, 'tariffa_cent': 2966, 'valido_da': '2025-09-01',
     'valido_a': '2027-01-31'},
    {'figura': 'COORDINATORE', 'livello_ccnl': None, 'tariffa_cent': 2966, 'valido_da': '2025-09-01',
     'valido_a': '2027-01-31'},
]


def test_tariffa_per_data_e_livello():
    tariffe = TARIFFE + [
        {'figura': 'ASACOM', 'livello_ccnl': None, 'tariffa_cent': 2408, 'valido_da': '2027-02-01', 'valido_a': None},
        {'figura': 'TIFLOLOGO', 'livello_ccnl': 'D2', 'tariffa_cent': 2544, 'valido_da': '2025-09-01',
         'valido_a': None}]
    assert nc.tariffa_alla_data(tariffe, 'ASACOM', '2027-01-31')['tariffa_cent'] == 2344
    assert nc.tariffa_alla_data(tariffe, 'ASACOM', '2027-02-01')['tariffa_cent'] == 2408
    assert nc.tariffa_alla_data(tariffe, 'TIFLOLOGO', '2026-06-10', livello='D2')['tariffa_cent'] == 2544
    assert nc.tariffa_alla_data(tariffe, 'TIFLOLOGO', '2026-06-10', livello='C3')['tariffa_cent'] == 2428
    assert nc.tariffa_alla_data(tariffe, 'TIFLOLOGO', '2026-06-10')['tariffa_cent'] == 2428
    assert nc.tariffa_alla_data(tariffe, 'LIS', '2026-06-10') is None
    assert nc.tariffa_alla_data(tariffe, 'ASACOM', '2025-08-31') is None


def test_tariffe_proposte_solo_da_confermare():
    proposte = config_napoli.tariffe_proposte()
    assert {(t['figura'], t['tariffa_cent'], t['valido_da'], t['valido_a']) for t in proposte} == {
        (t['figura'], t['tariffa_cent'], '2025-09-01', '2027-01-31') for t in TARIFFE}
    assert 'LIS' not in config_napoli.TARIFFE_PROPOSTE
    assert all('da confermare' in t['fonte'] for t in proposte)
    assert config_napoli.tariffe_proposte('2026-03-01')[0]['valido_da'] == '2026-03-01'
    # i calcoli non usano mai le proposte: senza tariffe del lotto la fattura e' bloccata
    esito = nc.righe_fattura([_presenza('2026-06-10', 'ASACOM', 120)], [], 'inferiore', '2026-06-01', '2026-06-30')
    assert esito['righe'] == [] and esito['bloccanti'][0]['codice'] == 'tariffa_mancante'


# ==================== fattura (§5.4) ====================

def _presenza(giorno, figura, minuti, grado='inferiore', stato='registrato', livello=None):
    return {'data': giorno, 'figura': figura, 'minuti_riconosciuti': minuti, 'stato': stato, 'grado': grado,
            'livello_ccnl': livello}


def _presenze_inventate(figura, minuti_totali, dal, al, per_giorno=240):
    """Presenze di coppie di fantasia nei giorni lun-sab del periodo, fino a minuti_totali."""
    dal, al = datetime.date.fromisoformat(dal), datetime.date.fromisoformat(al)
    giorni = [d for d in nc.giorni_mese(dal.year, dal.month) if dal <= d <= al]
    out, resto, i = [], minuti_totali, 0
    while resto > 0:
        m = min(per_giorno, resto)
        out.append(_presenza(giorni[i % len(giorni)].isoformat(), figura, m))
        resto -= m
        i += 1
    return out


CONTRATTO_XI = {'id': 11, 'numero': 'XI', 'grado': 'inferiore', 'valido_da': '2026-06-08', 'valido_a': '2026-07-31',
                'dd_numero': '77', 'dd_data': '2026-06-01'}
LOTTO = {'id': 1, 'numero_lotto': 1, 'cig': 'ZZ00000000', 'destinatario': 'Ente di fantasia',
         'riferimento_amministrativo': '9999', 'oggetto_fattura': None, 'nota_fattura': None}
IMPOSTAZIONI = {'cooperativa_iban': 'IT00A0000000000000000000000'}


def _presenze_giugno():
    """Le ore della fattura reale (292,75 / 6 / 654,25), da presenze inventate dal 08 al 30
    giugno, piu' presenze che non devono contare (altro contratto, altro grado, zero ore)."""
    presenze = (_presenze_inventate('EDUCATORE', 17565, '2026-06-08', '2026-06-30')
                + _presenze_inventate('PSICOLOGO', 360, '2026-06-08', '2026-06-30', per_giorno=90)
                + _presenze_inventate('ASACOM', 39255, '2026-06-08', '2026-06-30', per_giorno=285))
    presenze += [_presenza('2026-06-03', 'ASACOM', 240),                         # contratto X (fino al 07/06)
                 _presenza('2026-06-05', 'EDUCATORE', 120, stato='programmato'),  # fuori periodo: non blocca
                 _presenza('2026-06-10', 'ASACOM', 180, grado='superiore'),
                 _presenza('2026-06-11', 'ASACOM', 0)]                            # operatore assente
    return presenze


def test_fattura_reale_di_giugno_al_centesimo():
    coordinamento = [{'ore_cent': 4000}, {'ore_cent': 3155}]                     # 71,55 h in tutto
    p = nc.prospetto_fattura(2026, 6, 'inferiore', CONTRATTO_XI, _presenze_giugno(), TARIFFE, coordinamento,
                             LOTTO, impostazioni=IMPOSTAZIONI, data_fattura='2026-07-31')
    assert (p['dal'], p['al']) == (datetime.date(2026, 6, 8), datetime.date(2026, 6, 30))
    assert [(r['descrizione'], r['ore'], r['tariffa'], r['importo']) for r in p['righe']] == [
        ('Coordinatore', D('71.55'), D('29.66'), D('2122.17')),
        ('Educatore', D('292.75'), D('24.28'), D('7107.97')),
        ('Psicologo', D('6.00'), D('29.66'), D('177.96')),
        ('Asacom', D('654.25'), D('23.44'), D('15335.62'))]
    t = p['totali']
    assert (t['somma'], t['ritenuta'], t['imponibile'], t['iva'], t['totale'], t['da_pagare']) == (
        D('24743.72'), D('123.72'), D('24620.00'), D('1231.00'), D('25851.00'), D('24620.00'))
    assert (t['somma_cent'], t['ritenuta_cent'], t['imponibile_cent'], t['iva_cent'], t['totale_cent'],
            t['da_pagare_cent']) == (2474372, 12372, 2462000, 123100, 2585100, 2462000)
    assert [nc.numero_it(t[k]) for k in ('somma', 'ritenuta', 'imponibile', 'iva', 'totale', 'da_pagare')] == [
        '24.743,72', '123,72', '24.620,00', '1.231,00', '25.851,00', '24.620,00']
    assert p['oggetto'] == ("Servizio di assistenza specialistica all'integrazione scolastica - Lotto 1 - "
                            "Scuole di grado inferiore - Competenze dal 08 al 30 Giugno 2026. XI APPLICATIVO")
    assert p['nota'].startswith('D.D. 9999 N.77 DEL 01/06/2026 - ') and '17-ter' in p['nota']
    assert p['ritenuta_testo'] == 'RITENUTA dello 0,50% ex art. 30, c.5 bis, del D.lgs. 50/2016'
    assert p['scadenza'] == datetime.date(2026, 8, 30) and p['giorni_pagamento'] == 30
    assert p['bloccanti'] == [] and p['avvisi'] == []


def test_split_payment_e_percentuali_dalle_regole():
    righe = nc.righe_fattura(_presenze_giugno(), TARIFFE, 'inferiore', '2026-06-08', '2026-06-30')['righe']
    senza_split = nc.totali_fattura(righe, {'split_payment': False})
    assert senza_split['da_pagare'] == senza_split['totale'] == senza_split['imponibile'] + senza_split['iva']
    altre = nc.totali_fattura(righe, {'ritenuta_percento': D('0'), 'iva_percento': D('22')})
    assert altre['ritenuta'] == 0 and altre['iva'] == nc.arrotonda(altre['somma'] * D('0.22'))
    vuoto = nc.totali_fattura([])
    assert vuoto['somma'] == vuoto['da_pagare'] == D('0.00')
    regole = [{'lotto_id': None, 'chiave': 'split_payment', 'valore': 'false', 'valido_da': '2026-06-01'}]
    p = nc.prospetto_fattura(2026, 6, 'inferiore', CONTRATTO_XI, _presenze_giugno(), TARIFFE, (), LOTTO,
                             righe_regole=regole, impostazioni=IMPOSTAZIONI)
    assert p['totali']['da_pagare'] == p['totali']['totale'] and '17-ter' not in p['nota']


def test_periodo_parziale_del_contratto():
    assert nc.periodo_fattura(2026, 6, '2026-06-08', '2026-07-31') == (datetime.date(2026, 6, 8),
                                                                       datetime.date(2026, 6, 30))
    assert nc.periodo_fattura(2026, 6, '2025-09-01', '2026-06-07') == (datetime.date(2026, 6, 1),
                                                                       datetime.date(2026, 6, 7))
    assert nc.periodo_fattura(2026, 6, '2026-01-01', None) == (datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))
    assert nc.periodo_fattura(2026, 6, '2026-07-01', '2026-12-31') is None
    contratto_x = dict(CONTRATTO_XI, numero='X', valido_da='2025-09-01', valido_a='2026-06-07')
    p = nc.prospetto_fattura(2026, 6, 'inferiore', contratto_x, _presenze_giugno(), TARIFFE, (), LOTTO,
                             impostazioni=IMPOSTAZIONI)
    assert (p['dal'].day, p['al'].day) == (1, 7)
    assert [(r['figura'], r['minuti']) for r in p['righe']] == [('ASACOM', 240)]
    assert p['bloccanti'] == [{'codice': 'giorni_non_registrati', 'figura': 'EDUCATORE', 'presenze': 1,
                               'minuti': 0}]
    assert 'Competenze dal 01 al 07 Giugno 2026. X APPLICATIVO' in p['oggetto']


def test_cambio_di_tariffa_nel_periodo():
    tariffe = [dict(t, valido_a='2026-06-15') if t['figura'] == 'EDUCATORE' else t for t in TARIFFE]
    tariffe.append({'figura': 'EDUCATORE', 'livello_ccnl': None, 'tariffa_cent': 2544, 'valido_da': '2026-06-16',
                    'valido_a': None})
    presenze = [_presenza('2026-06-10', 'EDUCATORE', 120), _presenza('2026-06-15', 'EDUCATORE', 90),
                _presenza('2026-06-16', 'EDUCATORE', 60), _presenza('2026-06-30', 'EDUCATORE', 45),
                _presenza('2026-06-20', 'ASACOM', 60)]
    esito = nc.righe_fattura(presenze, tariffe, 'inferiore', '2026-06-08', '2026-06-30')
    assert [(r['descrizione'], r['minuti'], r['ore'], r['tariffa_cent'], r['importo']) for r in esito['righe']] == [
        ('Educatore (dal 08/06 al 15/06)', 210, D('3.50'), 2428, D('84.98')),
        ('Educatore (dal 16/06 al 30/06)', 105, D('1.75'), 2544, D('44.52')),
        ('Asacom', 60, D('1.00'), 2344, D('23.44'))]
    # le ore del coordinatore sono un totale del mese: con due tariffe nel periodo non si possono dividere
    coord = [dict(t, valido_a='2026-06-20') if t['figura'] == 'COORDINATORE' else t for t in TARIFFE]
    coord.append({'figura': 'COORDINATORE', 'livello_ccnl': None, 'tariffa_cent': 3045, 'valido_da': '2026-06-21'})
    bloccato = nc.righe_fattura([], coord, 'inferiore', '2026-06-08', '2026-06-30', [{'ore_cent': 1000}])
    assert bloccato['righe'] == [] and bloccato['bloccanti'][0]['codice'] == 'tariffa_cambia_nel_periodo'
    scoperto = [t for t in TARIFFE if t['figura'] != 'COORDINATORE'] + [
        dict(TARIFFE[4], valido_da='2026-06-10')]
    esito = nc.righe_fattura([], scoperto, 'inferiore', '2026-06-08', '2026-06-30', [{'ore_cent': 1000}])
    assert esito['bloccanti'] == [{'codice': 'tariffa_mancante', 'figura': 'COORDINATORE', 'presenze': 0,
                                   'minuti': 0}]


def _tariffe_educatore(*periodi):
    """TARIFFE con l'educatore sostituito da righe (tariffa_cent, valido_da, valido_a)."""
    return [t for t in TARIFFE if t['figura'] != 'EDUCATORE'] + [
        {'figura': 'EDUCATORE', 'livello_ccnl': None, 'tariffa_cent': c, 'valido_da': da, 'valido_a': a}
        for c, da, a in periodi]


def test_tariffa_che_torna_al_valore_di_prima():
    presenze = [_presenza('2026-06-09', 'EDUCATORE', 60), _presenza('2026-06-12', 'EDUCATORE', 120),
                _presenza('2026-06-22', 'EDUCATORE', 90), _presenza('2026-06-30', 'EDUCATORE', 30)]
    # A fino al 10, B dall'11 al 20, di nuovo A dal 21: i due tratti di A restano due righe col loro periodo
    aba = _tariffe_educatore((2428, '2025-09-01', '2026-06-10'), (2544, '2026-06-11', '2026-06-20'),
                             (2428, '2026-06-21', None))
    righe = nc.righe_fattura(presenze, aba, 'inferiore', '2026-06-08', '2026-06-30')['righe']
    assert [(r['descrizione'], r['minuti'], r['tariffa_cent'], r['dal'].day, r['al'].day) for r in righe] == [
        ('Educatore (dal 08/06 al 10/06)', 60, 2428, 8, 10), ('Educatore (dal 11/06 al 20/06)', 120, 2544, 11, 20),
        ('Educatore (dal 21/06 al 30/06)', 120, 2428, 21, 30)]
    # stessa tariffa su due righe una dopo l'altra (un rinnovo allo stesso prezzo): una riga sola
    rinnovo = _tariffe_educatore((2428, '2025-09-01', '2026-06-15'), (2428, '2026-06-16', None))
    righe = nc.righe_fattura(presenze, rinnovo, 'inferiore', '2026-06-08', '2026-06-30')['righe']
    assert [(r['descrizione'], r['minuti'], r['dal'].day, r['al'].day) for r in righe] == [('Educatore', 300, 8, 30)]


def test_tariffa_per_livello_fa_righe_separate():
    tariffe = TARIFFE + [{'figura': 'TIFLOLOGO', 'livello_ccnl': 'D2', 'tariffa_cent': 2544,
                          'valido_da': '2025-09-01', 'valido_a': None}]
    presenze = [_presenza('2026-06-10', 'TIFLOLOGO', 120, livello='D2'),
                _presenza('2026-06-11', 'TIFLOLOGO', 60, livello='C3')]
    righe = nc.righe_fattura(presenze, tariffe, 'inferiore', '2026-06-01', '2026-06-30')['righe']
    assert [(r['descrizione'], r['ore'], r['tariffa_cent']) for r in righe] == [
        ('Tiflologo', D('1.00'), 2428), ('Tiflologo - livello D2', D('2.00'), 2544)]


def test_file_sintetico_del_rapporto_excel():
    presenze = (_presenze_inventate('ASACOM', 858 * 60, '2026-03-02', '2026-03-31')
                + _presenze_inventate('EDUCATORE', 33270, '2026-03-02', '2026-03-31')
                + _presenze_inventate('PSICOLOGO', 5550, '2026-03-02', '2026-03-31')
                + _presenze_inventate('TIFLOLOGO', 49 * 60, '2026-03-02', '2026-03-31'))
    righe = nc.righe_fattura(presenze, TARIFFE, 'inferiore', '2026-03-01', '2026-03-31')['righe']
    assert [(r['figura'], r['ore'], r['importo']) for r in righe] == [
        ('EDUCATORE', D('554.50'), D('13463.26')), ('PSICOLOGO', D('92.50'), D('2743.55')),
        ('ASACOM', D('858.00'), D('20111.52')), ('TIFLOLOGO', D('49.00'), D('1189.72'))]
    t = nc.totali_fattura(righe)
    assert (t['somma'], t['ritenuta'], t['imponibile'], t['iva'], t['totale']) == (
        D('37508.05'), D('187.54'), D('37320.51'), D('1866.03'), D('39186.54'))


def test_ore_al_centesimo_sul_totale_della_figura():
    # 7291 minuti = 121,5166... ore -> 121,52 x 24,28 = 2.950,51 (si arrotonda la somma, non ogni giorno)
    presenze = [_presenza('2026-06-%02d' % g, 'EDUCATORE', m) for g, m in ((8, 7000), (9, 291))]
    riga = nc.righe_fattura(presenze, TARIFFE, 'inferiore', '2026-06-01', '2026-06-30')['righe'][0]
    assert (riga['minuti'], riga['ore'], riga['importo']) == (7291, D('121.52'), D('2950.51'))


def test_mezzo_centesimo_per_eccesso():
    # arrotondamento commerciale: il mezzo centesimo va su anche dopo una cifra pari (non "al pari")
    assert nc.arrotonda(D('0.125')) == D('0.13') and nc.arrotonda('2,665') == D('2.67')
    assert nc.in_centesimi(D('0.005')) == 1
    # riga: 45 minuti di psicologo = 0,75 x 29,66 = 22,245 -> 22,25
    psicologo = [_presenza('2026-06-10', 'PSICOLOGO', 45)]
    riga = nc.righe_fattura(psicologo, TARIFFE, 'inferiore', '2026-06-01', '2026-06-30')['righe'][0]
    assert (riga['ore'], riga['importo'], riga['importo_cent']) == (D('0.75'), D('22.25'), 2225)
    # ritenuta: 101,00 x 0,50% = 0,505 -> 0,51; IVA: 0,10 x 5% = 0,005 -> 0,01
    t = nc.totali_fattura([{'importo': D('101.00')}])
    assert (t['ritenuta'], t['imponibile'], t['iva'], t['totale']) == (D('0.51'), D('100.49'), D('5.02'), D('105.51'))
    assert nc.totali_fattura([{'importo': D('0.10')}])['iva'] == D('0.01')


def test_grado_misto_o_scritto_diverso():
    # scuola 'misto' con l'alunno senza grado (§4.2): le ore bloccano le fatture di tutti e due i gradi
    misto = [_presenza('2026-06-10', 'ASACOM', 120, grado='misto'), _presenza('2026-06-11', 'ASACOM', 60, grado='?')]
    for grado in nc.GRADI:
        esito = nc.righe_fattura(misto, TARIFFE, grado, '2026-06-01', '2026-06-30')
        assert esito['righe'] == [] and esito['bloccanti'] == [
            {'codice': 'grado_da_decidere', 'figura': 'ASACOM', 'presenze': 2, 'minuti': 180}], grado
    # maiuscole e spazi non cambiano il grado
    scritto = nc.righe_fattura([_presenza('2026-06-10', 'ASACOM', 120, grado=' Inferiore')], TARIFFE, 'inferiore',
                               '2026-06-01', '2026-06-30')
    assert [r['minuti'] for r in scritto['righe']] == [120] and scritto['bloccanti'] == []
    assert [nc.grado_fattura(g) for g in ('SUPERIORE', 'inferiore', 'misto', '', None)] == [
        'superiore', 'inferiore', None, None, None]
    with pytest.raises(ValueError):
        nc.righe_fattura([], TARIFFE, 'misto', '2026-06-01', '2026-06-30')


def test_presenze_fuori_da_ogni_contratto():
    contratti = [dict(CONTRATTO_XI, numero='X', valido_da='2025-09-01', valido_a='2026-06-07'), CONTRATTO_XI,
                 {'numero': 'S1', 'grado': 'superiore', 'valido_da': '2026-06-15', 'valido_a': '2026-07-31'}]
    presenze = [_presenza('2026-06-05', 'ASACOM', 120),                                  # contratto X
                _presenza('2026-06-10', 'ASACOM', 90),                                   # contratto XI
                _presenza('2026-06-10', 'EDUCATORE', 60, grado='superiore'),             # superiore prima di S1
                _presenza('2026-06-12', 'EDUCATORE', 0, grado='superiore', stato='programmato'),
                _presenza('2026-06-11', 'EDUCATORE', 0, grado='superiore'),              # zero ore: non conta
                _presenza('2026-06-16', 'EDUCATORE', 60, grado='superiore'),             # contratto S1
                _presenza('2026-06-10', 'PSICOLOGO', 45, grado='misto'),                 # da decidere: c'e' XI
                _presenza('2026-08-03', 'ASACOM', 30)]                                   # dopo tutti i contratti
    assert nc.ore_fuori_contratto(presenze, contratti) == [
        {'codice': 'presenza_fuori_contratto', 'figura': 'EDUCATORE', 'presenze': 2, 'minuti': 60},
        {'codice': 'presenza_fuori_contratto', 'figura': 'ASACOM', 'presenze': 1, 'minuti': 30}]
    # un contratto senza grado vale per tutti e due i gradi
    agosto = {'numero': 'XII', 'grado': None, 'valido_da': '2026-08-01', 'valido_a': '2026-08-31'}
    assert [b['figura'] for b in nc.ore_fuori_contratto(presenze, contratti + [agosto])] == ['EDUCATORE']
    assert nc.ore_fuori_contratto([], contratti) == []
    assert len(nc.ore_fuori_contratto(presenze, [])) == 3


def test_bloccanti_della_fattura():
    presenze = [_presenza('2026-06-10', 'ASACOM', 120), _presenza('2026-06-11', 'ASACOM', 60, grado=None),
                _presenza('2026-06-12', 'EDUCATORE', 0, stato='programmato'),
                _presenza('2026-06-13', 'EDUCATORE', 0, stato='programmato'),
                _presenza('2026-06-15', 'LIS', 120), _presenza('2026-06-16', 'LIS', 60)]
    esito = nc.righe_fattura(presenze, TARIFFE, 'inferiore', '2026-06-08', '2026-06-30')
    assert [r['figura'] for r in esito['righe']] == ['ASACOM']
    assert esito['bloccanti'] == [
        {'codice': 'grado_da_decidere', 'figura': 'ASACOM', 'presenze': 1, 'minuti': 60},
        {'codice': 'giorni_non_registrati', 'figura': 'EDUCATORE', 'presenze': 2, 'minuti': 0},
        {'codice': 'tariffa_mancante', 'figura': 'LIS', 'presenze': 2, 'minuti': 180}]
    # il grado da decidere blocca anche la fattura dell'altro grado
    assert nc.righe_fattura(presenze, TARIFFE, 'superiore', '2026-06-08', '2026-06-30')['bloccanti'][0][
        'codice'] == 'grado_da_decidere'
    # dati obbligatori del prospetto
    lotto = dict(LOTTO, cig='', destinatario=None)
    contratto = dict(CONTRATTO_XI, dd_numero=None)
    p = nc.prospetto_fattura(2026, 6, 'inferiore', contratto, [], TARIFFE, (), lotto)
    assert [b['campo'] for b in p['bloccanti']] == ['cig', 'destinatario', 'dd_numero', 'iban']
    assert p['avvisi'] == [{'codice': 'nessuna_riga'}]
    assert nc.dati_mancanti_fattura(LOTTO, CONTRATTO_XI, IMPOSTAZIONI, 'oggetto') == []
    assert nc.dati_mancanti_fattura({}, {}, None, ' ') == ['cig', 'destinatario', 'oggetto', 'contratto',
                                                           'dd_numero', 'dd_data', 'iban']
    altro = nc.prospetto_fattura(2026, 6, 'superiore', CONTRATTO_XI, [], TARIFFE, (), LOTTO)
    assert altro['bloccanti'] == [{'codice': 'contratto_di_altro_grado'}]
    fuori = nc.prospetto_fattura(2026, 5, 'inferiore', CONTRATTO_XI, [], TARIFFE, (), LOTTO)
    assert fuori['bloccanti'] == [{'codice': 'contratto_fuori_dal_mese'}] and fuori['righe'] == []
    with pytest.raises(ValueError):
        nc.prospetto_fattura(2026, 6, 'misto', CONTRATTO_XI, [], TARIFFE)


def test_contano_solo_i_giorni_registrati():
    # come il §5.4: stato 'registrato'; ogni altro stato, o nessuno, e' un giorno non registrato
    presenze = [_presenza('2026-06-10', 'ASACOM', 120), _presenza('2026-06-11', 'ASACOM', 60, stato='bozza'),
                _presenza('2026-06-12', 'ASACOM', 30, stato=None), _presenza('2026-06-13', 'ASACOM', 45)]
    del presenze[3]['stato']
    esito = nc.righe_fattura(presenze, TARIFFE, 'inferiore', '2026-06-01', '2026-06-30')
    assert [(r['figura'], r['minuti']) for r in esito['righe']] == [('ASACOM', 120)]
    assert esito['bloccanti'] == [{'codice': 'giorni_non_registrati', 'figura': 'ASACOM', 'presenze': 3,
                                   'minuti': 0}]
    contratti = [dict(CONTRATTO_XI, valido_da='2026-06-01')]
    fuori = [dict(p, data='2026-08-03') for p in presenze]
    assert nc.ore_fuori_contratto(fuori, contratti)[0]['presenze'] == 4


def test_ore_del_coordinatore_solo_dal_totale_mensile():
    # le presenze con la figura del coordinatore non entrano in fattura (sarebbero contate due volte)
    presenze = [_presenza('2026-06-10', 'ASACOM', 120), _presenza('2026-06-10', 'COORDINATORE', 240),
                _presenza('2026-06-11', 'COORDINATORE', 60, grado=None),
                _presenza('2026-06-12', 'COORDINATORE', 90, grado='superiore'),
                _presenza('2026-06-13', 'COORDINATORE', 0)]
    esito = nc.righe_fattura(presenze, TARIFFE, 'inferiore', '2026-06-01', '2026-06-30', [{'ore_cent': 1250}])
    assert [(r['figura'], r['ore']) for r in esito['righe']] == [('COORDINATORE', D('12.50')), ('ASACOM', D('2.00'))]
    assert esito['bloccanti'] == []         # niente "grado da decidere" per il coordinatore
    assert esito['avvisi'] == [{'codice': 'ore_coordinatore_nelle_presenze', 'figura': 'COORDINATORE',
                                'presenze': 2, 'minuti': 300}]
    # ore del coordinatore al centesimo come quelle degli operatori: 12,5 -> 12,50
    riga = esito['righe'][0]
    assert str(riga['ore']) == '12.50' and riga['ore_cent'] == 1250 and riga['importo'] == D('370.75')
    p = nc.prospetto_fattura(2026, 6, 'inferiore', CONTRATTO_XI, presenze, TARIFFE, [{'ore_cent': 1250}], LOTTO,
                             impostazioni=IMPOSTAZIONI)
    assert p['avvisi'] == esito['avvisi']
    # le figure "di lotto" sono quelle dello schema con ore_di_lotto = 1
    assert config_napoli.FIGURE_DI_LOTTO == tuple(f[0] for f in napoli_schema.FIGURE if f[3])


def test_tariffe_sovrapposte_sotto_periodo_dai_giorni_veri():
    # A dal 2025 (senza fine) e B dal 15/06: dal 15 vale B (inizia piu' tardi). Il tratto di A e' 08-14,
    # non "fino al 30" (le date della riga A)
    sovrapposte = _tariffe_educatore((2428, '2025-09-01', None), (2544, '2026-06-15', None))
    presenze = [_presenza('2026-06-09', 'EDUCATORE', 60), _presenza('2026-06-20', 'EDUCATORE', 120)]
    righe = nc.righe_fattura(presenze, sovrapposte, 'inferiore', '2026-06-08', '2026-06-30')['righe']
    assert [(r['descrizione'], r['minuti'], r['tariffa_cent'], r['dal'].day, r['al'].day) for r in righe] == [
        ('Educatore (dal 08/06 al 14/06)', 60, 2428, 8, 14), ('Educatore (dal 15/06 al 30/06)', 120, 2544, 15, 30)]
    # una tariffa di livello per pochi giorni dentro quella generale: il livello ha il suo tratto
    livello = TARIFFE + [{'figura': 'ASACOM', 'livello_ccnl': 'C3', 'tariffa_cent': 2400, 'valido_da': '2026-06-10',
                          'valido_a': '2026-06-12'}]
    righe = nc.righe_fattura([_presenza('2026-06-11', 'ASACOM', 60, livello='C3'),
                              _presenza('2026-06-20', 'ASACOM', 30, livello='C3')], livello, 'inferiore',
                             '2026-06-01', '2026-06-30')['righe']
    assert [(r['descrizione'], r['tariffa_cent'], r['dal'].day, r['al'].day, r['minuti']) for r in righe] == [
        ('Asacom - livello C3 (dal 10/06 al 12/06)', 2400, 10, 12, 60), ('Asacom (dal 13/06 al 30/06)', 2344, 13, 30, 30)]
    # le Impostazioni le rifiutano: tariffe_sovrapposte le trova (stesso livello, almeno un giorno in comune)
    assert [(a['tariffa_cent'], b['tariffa_cent']) for a, b in nc.tariffe_sovrapposte(sovrapposte)] == [(2428, 2544)]
    assert nc.tariffe_sovrapposte(TARIFFE) == [] and nc.tariffe_sovrapposte(livello) == []
    contigue = _tariffe_educatore((2428, '2025-09-01', '2026-06-15'), (2544, '2026-06-16', None))
    assert nc.tariffe_sovrapposte(contigue) == []
    un_giorno = _tariffe_educatore((2428, '2025-09-01', '2026-06-16'), (2544, '2026-06-16', None))
    assert len(nc.tariffe_sovrapposte(un_giorno)) == 1
    altri_lotti = [dict(t, lotto_id=1) for t in sovrapposte[:-1]] + [dict(sovrapposte[-1], lotto_id=2)]
    assert nc.tariffe_sovrapposte(altri_lotti) == []


def test_contratti_sovrapposti_e_presenze_in_due_contratti():
    x = {'lotto_id': 1, 'numero': 'X', 'grado': 'inferiore', 'valido_da': '2025-09-01', 'valido_a': '2026-06-10'}
    xi = {'lotto_id': 1, 'numero': 'XI', 'grado': 'inferiore', 'valido_da': '2026-06-08', 'valido_a': '2026-07-31'}
    sup = {'lotto_id': 1, 'numero': 'S', 'grado': 'superiore', 'valido_da': '2025-09-01', 'valido_a': '2026-07-31'}
    tutti = {'lotto_id': 1, 'numero': 'T', 'grado': None, 'valido_da': '2026-07-01', 'valido_a': '2026-07-31'}
    altro_lotto = dict(xi, lotto_id=2)
    contratti = [x, xi, sup, tutti, altro_lotto]
    assert [(a['numero'], b['numero']) for a, b in nc.contratti_sovrapposti(contratti)] == [
        ('X', 'XI'), ('XI', 'T'), ('S', 'T')]
    # 08-10 giugno: le ore del grado inferiore finirebbero nella fattura del X e in quella dell'XI
    presenze = [_presenza('2026-06-09', 'ASACOM', 120), _presenza('2026-06-10', 'ASACOM', 0, stato='programmato'),
                _presenza('2026-06-11', 'ASACOM', 60), _presenza('2026-06-09', 'EDUCATORE', 60, grado='superiore'),
                _presenza('2026-06-09', 'PSICOLOGO', 30, grado='misto'), _presenza('2026-06-09', 'ASACOM', 0)]
    assert nc.presenze_in_piu_contratti(presenze, [x, xi, sup]) == [
        {'codice': 'presenza_in_piu_contratti', 'figura': 'ASACOM', 'presenze': 2, 'minuti': 120}]
    assert nc.presenze_in_piu_contratti(presenze, [dict(x, valido_a='2026-06-07'), xi, sup]) == []
    assert nc.contratti_sovrapposti([dict(x, valido_a='2026-06-07'), xi, sup]) == []


def test_testi_congelati_del_prospetto():
    p = nc.prospetto_fattura(2026, 6, 'inferiore', CONTRATTO_XI, _presenze_giugno(), TARIFFE, [{'ore_cent': 7155}],
                             LOTTO, impostazioni=IMPOSTAZIONI, data_fattura='2026-07-31')
    assert p['destinatario'] == 'Ente di fantasia'
    assert p['regole'] == {'ritenuta_percento': D('0.50'), 'iva_percento': D('5'), 'split_payment': True,
                           'giorni_pagamento': 30}
    testi = nc.testi_da_congelare(p)
    assert set(testi) == {c for c, _ in napoli_schema.COLONNE_FATTURE_V3}
    assert testi['oggetto'] == p['oggetto'] and testi['nota'] == p['nota'] and testi['scadenza'] == '2026-08-30'
    assert testi['ritenuta_testo'].startswith('RITENUTA dello 0,50%') and testi['destinatario'] == 'Ente di fantasia'
    assert json.loads(testi['regole_json']) == {'giorni_pagamento': 30, 'iva_percento': '5',
                                                'ritenuta_percento': '0.50', 'split_payment': True}
    senza_data = nc.testi_da_congelare(nc.prospetto_fattura(2026, 6, 'inferiore', CONTRATTO_XI, [], TARIFFE, (),
                                                            LOTTO))
    assert senza_data['scadenza'] is None


def test_testi_e_scadenze():
    assert nc.testo_oggetto(3, 'superiore', '2026-10-01', '2026-10-31', 'IV') == (
        "Servizio di assistenza specialistica all'integrazione scolastica - Lotto 3 - Scuole di grado superiore - "
        "Competenze dal 01 al 31 Ottobre 2026. IV APPLICATIVO")
    assert nc.testo_oggetto(2, 'inferiore', '2026-10-01', '2026-10-31', 'V',
                            modello='Lotto {lotto} {grado} {mese}/{anno} contratto {contratto} {ignoto}') == (
        'Lotto 2 inferiore Ottobre/2026 contratto V {ignoto}')
    assert nc.testo_nota('9999', '12', '2026-05-04', {'split_payment': False}) == 'D.D. 9999 N.12 DEL 04/05/2026'
    assert nc.testo_ritenuta({'ritenuta_percento': D('0.5')}).startswith('RITENUTA dello 0,50% ')
    assert nc.riempi_modello('{a}{b}{0.__class__}', {'a': 1}) == '1{b}{0.__class__}'
    assert nc.scadenza_pagamento('2026-07-31', 30) == datetime.date(2026, 8, 30)
    assert nc.scadenza_invio(2026, 12, 10) == datetime.date(2027, 1, 10)


# ==================== indipendenza da database, Flask e Roma ====================

@pytest.mark.parametrize('modulo', ['napoli_calcoli.py', 'config_napoli.py'])
def test_calcoli_senza_database_ne_flask(modulo):
    with open(os.path.join(ROOT, modulo), encoding='utf-8') as f:
        albero = ast.parse(f.read())
    importati = {a.name.split('.')[0] for n in ast.walk(albero) if isinstance(n, ast.Import) for a in n.names}
    importati |= {n.module.split('.')[0] for n in ast.walk(albero) if isinstance(n, ast.ImportFrom)}
    assert importati <= {'datetime', 'decimal', 'json', 're', 'config_napoli'}, importati

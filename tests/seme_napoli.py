"""Seme Napoli: i dati di Napoli caricati nei database di prova (VR3 e VR5).

Serve a provare che Roma non cambia quando nel database ci sono anche dati di
Napoli:
- tests/test_roma_invariata.py fotografa Roma, carica il seme e la rifotografa;
- con ASSISTO_TEST_CON_NAPOLI=1 conftest.py carica il seme nel database della
  sessione e nell'archivio Roma inventato, e tutta la suite gira di nuovo.

Finche' la sezione non ha le sue API il seme scrive direttamente nelle tabelle
napoli_* (schema v2, napoli_schema.py), con una connessione SQLite a parte: mai
nelle tabelle di Roma. Ogni passo che aggiunge una funzione di Napoli porta qui i
suoi dati, tramite le API di Napoli quando ci sono (lotto, tariffe, import del
master sintetico, orari, mese preparato, fogli, fattura definitiva, mese chiuso...).

Solo dati inventati: alunni e operatori hanno di proposito gli stessi nomi di
utenti e operatori dell'archivio Roma (tests/roma_sintetico.py), una scuola ha lo
stesso nome di una scuola di Roma, e ottobre 2025 (un mese degli export di Roma)
ha ore, fogli, una fattura definitiva e il mese chiuso del lotto. I codici fiscali
hanno il carattere di controllo giusto ma il codice comune Z999, che non esiste.
"""
import datetime
import hashlib
import json
import pathlib
import sqlite3

PREFISSO_NAPOLI = 'napoli_'

_MESI_CF = 'ABCDEHLMPRST'
_DISPARI_CF = dict(zip('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                       [1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 1, 0, 5, 7, 9, 13, 15, 17,
                        19, 21, 2, 4, 18, 20, 11, 3, 6, 8, 12, 14, 16, 10, 22, 25, 24, 23]))


def _parte_cf(parole, nome=False):
    lettere = [c for c in parole.upper() if c.isalpha()]
    consonanti = [c for c in lettere if c not in 'AEIOU']
    vocali = [c for c in lettere if c in 'AEIOU']
    if nome and len(consonanti) >= 4:
        consonanti = [consonanti[0], consonanti[2], consonanti[3]]
    return ''.join(consonanti + vocali + ['X'] * 3)[:3]


def carattere_di_controllo(base):
    """Ultimo carattere del codice fiscale, dai primi 15."""
    somma = sum(_DISPARI_CF[c] if i % 2 == 0 else (int(c) if c.isdigit() else ord(c) - 65)
                for i, c in enumerate(base))
    return chr(65 + somma % 26)


def codice_fiscale_inventato(cognome, nome, nascita, sesso):
    """Codice fiscale con il carattere di controllo corretto e comune Z999
    (inesistente): non puo' coincidere con quello di una persona vera."""
    giorno = nascita.day + (40 if sesso == 'F' else 0)
    base = '%s%s%02d%s%02dZ999' % (_parte_cf(cognome), _parte_cf(nome, True), nascita.year % 100,
                                   _MESI_CF[nascita.month - 1], giorno)
    return base + carattere_di_controllo(base)


def _cf(cognome, nome, anno, mese, giorno, sesso):
    return codice_fiscale_inventato(cognome, nome, datetime.date(anno, mese, giorno), sesso)


class _Seme:
    """Scrive le righe e conta quante ne mette in ogni tabella."""

    def __init__(self, conn):
        self.conn = conn
        self.righe = {}

    def __call__(self, tabella, **valori):
        assert tabella.startswith(PREFISSO_NAPOLI), tabella
        colonne = ', '.join(valori)
        segnaposto = ', '.join('?' * len(valori))
        cur = self.conn.execute(f'INSERT INTO {tabella} ({colonne}) VALUES ({segnaposto})', tuple(valori.values()))
        self.righe[tabella] = self.righe.get(tabella, 0) + 1
        return cur.lastrowid


def _scrivi_seme(ins):
    ora = '2025-09-01T08:00:00'
    ins('napoli_impostazioni', chiave='cooperativa_denominazione', valore='COOPERATIVA DI FANTASIA')
    ins('napoli_impostazioni', chiave='cooperativa_iban', valore='IT00A0000000000000000000000')
    ins('napoli_alias_qualifiche', testo='EDUCATRICE PROF.LE', figura='EDUCATORE', origine='utente')

    lotto = ins('napoli_lotti', nome='NAPOLI LOTTO 1 (PROVA)', numero_lotto=1, municipalita='1 e 2',
                colore='#0EA5E9', cig='ZZ00000000',
                oggetto_fattura='Servizio di prova - Lotto {lotto} - Scuole di grado {grado} - '
                                'Competenze dal {dal} al {al} {mese} {anno}. {contratto} APPLICATIVO',
                nota_fattura='D.D. N.{dd_numero} DEL {dd_data}', destinatario='ENTE DI FANTASIA',
                codice_univoco_ufficio='ZZZZZZ', riferimento_amministrativo='0000',
                intestazione_foglio='FOGLIO FIRMA DI PROVA', data_creazione=ora)

    # stesso nome di una scuola di Roma; lo stesso codice in due municipalita' = due plessi
    s_arcobaleno = ins('napoli_scuole', lotto_id=lotto, nome='IC Fantasia - Primaria Arcobaleno',
                       codice_meccanografico='NAIC8ZZ001', grado='inferiore', municipalita=1, data_inserimento=ora)
    s_arcobaleno_2 = ins('napoli_scuole', lotto_id=lotto, nome='IC Fantasia - Primaria Arcobaleno',
                         codice_meccanografico='NAIC8ZZ001', grado='inferiore', municipalita=2, data_inserimento=ora)
    s_galileo = ins('napoli_scuole', lotto_id=lotto, nome='IS Immaginario Galileo', codice_meccanografico='NAIS0ZZ002',
                    grado='superiore', municipalita=2, data_inserimento=ora)
    s_senza_codice = ins('napoli_scuole', lotto_id=lotto, nome='Scuola di prova senza codice', data_inserimento=ora)

    # alunni omonimi di utenti di Roma
    alba = ins('napoli_alunni', lotto_id=lotto, cognome='Esempio', nome='Alba',
               codice_fiscale=_cf('Esempio', 'Alba', 2015, 3, 10, 'F'), scuola_id=s_arcobaleno, data_inserimento=ora)
    bruno = ins('napoli_alunni', lotto_id=lotto, cognome='Fittizio', nome='Bruno',
                codice_fiscale=_cf('Fittizio', 'Bruno', 2014, 7, 22, 'M'), scuola_id=s_arcobaleno_2,
                data_inserimento=ora)
    gaia = ins('napoli_alunni', lotto_id=lotto, cognome='Campione', nome='Gaia',
               codice_fiscale=_cf('Campione', 'Gaia', 2008, 11, 5, 'F'), scuola_id=s_galileo, esami=1,
               data_inserimento=ora)
    ciro = ins('napoli_alunni', lotto_id=lotto, cognome='Inventato', nome='Ciro',
               codice_fiscale=_cf('Inventato', 'Ciro', 2016, 1, 30, 'M'), scuola_id=s_senza_codice,
               grado='inferiore', attivo=0, archiviato_dal='2026-02-01', data_inserimento=ora)

    # operatori omonimi di operatori di Roma; uno con il codice fiscale di 17 caratteri
    primo = ins('napoli_operatori', cognome='Operatore', nome='Primo', figura='ASACOM', livello_ccnl='C3',
                codice_fiscale=_cf('Operatore', 'Primo', 1985, 4, 12, 'M'), qualifica_originale='ASACOM',
                ore_contratto=25, data_inserimento=ora)
    seconda = ins('napoli_operatori', cognome='Operatrice', nome='Seconda', figura='EDUCATORE', livello_ccnl='D2',
                  codice_fiscale=_cf('Operatrice', 'Seconda', 1990, 1, 25, 'F'),
                  qualifica_originale='EDUCATRICE PROFESSIONALE', ore_contratto=30, data_inserimento=ora)
    quinto = ins('napoli_operatori', cognome='Immaginario', nome='Quinto', figura='PSICOLOGO', livello_ccnl='E2',
                 codice_fiscale=_cf('Immaginario', 'Quinto', 1979, 11, 3, 'M'), qualifica_originale='PSICOLOGO',
                 ore_contratto=10, data_inserimento=ora)
    sesta = ins('napoli_operatori', cognome='Coordinatrice', nome='Sesta', figura='COORDINATORE', livello_ccnl='E2',
                codice_fiscale=_cf('Coordinatrice', 'Sesta', 1983, 2, 17, 'F'), qualifica_originale='COORDINATRICE',
                ore_contratto=38, data_inserimento=ora)
    settimo = ins('napoli_operatori', cognome='Sostituto', nome='Settimo', figura='ASACOM',
                  codice_fiscale=_cf('Sostituto', 'Settimo', 1994, 3, 8, 'M') + 'X', cf_valido=0,
                  qualifica_originale='ASACM', data_inserimento=ora)

    for alunno, figura, ore, dal, al, stato in (
            (alba, 'ASACOM', 10, '2025-09-15', None, 'definitivo'),
            (alba, 'EDUCATORE', 4, '2025-09-15', None, 'definitivo'),
            (bruno, 'ASACOM', 8, '2025-09-15', None, 'definitivo'),
            (gaia, 'EDUCATORE', 12, '2025-09-15', None, 'definitivo'),
            (gaia, 'PSICOLOGO', 2, '2025-09-15', None, 'definitivo'),
            (ciro, 'ASACOM', 6, '2025-10-01', '2026-01-31', 'provvisorio')):
        ins('napoli_pei', alunno_id=alunno, figura=figura, ore_settimanali=ore, valido_da=dal, valido_a=al,
            stato=stato, fonte='master', data_inserimento=ora)

    def coppia(alunno, operatore, scuola, figura, **altro):
        return ins('napoli_coppie', lotto_id=lotto, alunno_id=alunno, operatore_id=operatore, scuola_id=scuola,
                   figura=figura, origine='seme', data_inserimento=ora, **altro)

    c_alba_asacom = coppia(alba, primo, s_arcobaleno, 'ASACOM', ore_settimanali=10, valido_da='2025-09-15')
    c_alba_educ = coppia(alba, seconda, s_arcobaleno, 'EDUCATORE', valido_da='2025-09-15')
    coppia(bruno, primo, s_arcobaleno_2, 'ASACOM', valido_da='2025-09-15', valido_a='2026-06-30')
    c_gaia_educ = coppia(gaia, seconda, s_galileo, 'EDUCATORE', valido_da='2025-09-15')
    c_gaia_psico = coppia(gaia, quinto, s_galileo, 'PSICOLOGO', valido_da='2025-09-15')
    c_sostituto = coppia(alba, settimo, s_arcobaleno, 'ASACOM', ruolo='sostituto', titolare_coppia_id=c_alba_asacom,
                         valido_da='2025-10-13', valido_a='2025-10-13')

    inferiore_x = ins('napoli_contratti', lotto_id=lotto, grado='inferiore', numero='X', accordo_quadro='attuale',
                      dd_numero='DD-PROVA-1', dd_data='2025-08-20', valido_da='2025-09-01', valido_a='2026-06-07',
                      data_inserimento=ora)
    ins('napoli_contratti', lotto_id=lotto, grado='inferiore', numero='XI', accordo_quadro='attuale',
        valido_da='2026-06-08', valido_a='2026-07-31', data_inserimento=ora)
    ins('napoli_contratti', lotto_id=lotto, grado='superiore', numero='X', accordo_quadro='attuale',
        valido_da='2025-09-01', valido_a='2026-07-31', importo_cent=1000000, data_inserimento=ora)

    for figura, cent in (('ASACOM', 2344), ('EDUCATORE', 2428), ('TIFLOLOGO', 2428), ('PSICOLOGO', 2966),
                         ('COORDINATORE', 2966)):
        ins('napoli_tariffe', lotto_id=lotto, figura=figura, tariffa_cent=cent, valido_da='2025-09-01',
            valido_a='2027-01-31', fonte='prova', data_inserimento=ora)
    ins('napoli_tariffe', lotto_id=lotto, figura='ASACOM', tariffa_cent=2408, valido_da='2027-02-01',
        fonte='prova, nuovo accordo', data_inserimento=ora)

    ins('napoli_regole', chiave='quota_assenza_alunno', valore='0.5', valido_da='2025-09-01', valido_a='2027-01-31',
        fonte='prova', data_inserimento=ora)
    ins('napoli_regole', chiave='quota_assenza_alunno', valore='0', valido_da='2027-02-01', fonte='prova',
        data_inserimento=ora)
    ins('napoli_regole', lotto_id=lotto, chiave='giorni_pagamento', valore='30', valido_da='2025-09-01',
        data_inserimento=ora)

    ins('napoli_calendario', data='2025-12-25', tipo='chiusura', descrizione='Festivita\' di prova')
    ins('napoli_calendario', lotto_id=lotto, data='2025-11-01', tipo='chiusura', descrizione='Chiusura di prova')
    ins('napoli_calendario', lotto_id=lotto, scuola_id=s_galileo, data='2025-10-20', tipo='evento',
        descrizione='Assemblea di prova')

    for c, giorno, inizio, fine in ((c_alba_asacom, 0, '08:00', '10:00'), (c_alba_asacom, 0, '12:00', '14:00'),
                                    (c_alba_asacom, 2, '10:00', '13:00'), (c_alba_educ, 1, '09:00', '11:00'),
                                    (c_gaia_educ, 3, '08:30', '11:30'), (c_gaia_psico, 4, '10:00', '12:00')):
        ins('napoli_orari', coppia_id=c, giorno=giorno, ora_inizio=inizio, ora_fine=fine, valido_da='2025-09-15',
            data_inserimento=ora)

    ins('napoli_fogli', coppia_id=c_alba_asacom, anno=2025, mese=10, stato='registrato', totale_scritto_min=330,
        note='Alunno assente: 8')
    ins('napoli_fogli', coppia_id=c_alba_educ, anno=2025, mese=10, stato='stampato')
    ins('napoli_fogli', coppia_id=c_gaia_educ, anno=2025, mese=10, stato='verificato')
    ins('napoli_fogli', coppia_id=c_sostituto, anno=2025, mese=10, stato='ricevuto', data_ricezione='2025-11-03')

    imp = ins('napoli_import', lotto_id=lotto, anno=2025, mese=10, nome_file='master_prova_ottobre.xlsx',
              sha256=hashlib.sha256(b'master di prova').hexdigest(), n_righe=1,
              esito_json=json.dumps({'righe': 1, 'presenze': 1}), sostituite_json='[]', data='2025-11-04T09:00:00')

    def presenza(c, data, figura, fasce=(), **altro):
        pid = ins('napoli_presenze', coppia_id=c, lotto_id=lotto, data=data, figura=figura,
                  modificato_il='2025-11-04T09:00:00', **altro)
        for tipo, ordine, inizio, fine in fasce:
            ins('napoli_presenze_fasce', presenza_id=pid, tipo=tipo, ordine=ordine, ora_inizio=inizio, ora_fine=fine)
        return pid

    due_fasce = [('P', 1, '08:00', '10:00'), ('P', 2, '12:00', '14:00'),
                 ('E', 1, '08:00', '10:00'), ('E', 2, '12:00', '14:00')]
    presenza(c_alba_asacom, '2025-10-06', 'ASACOM', due_fasce, stato='registrato', minuti_programmati=240,
             minuti_svolti=240, minuti_riconosciuti=240, origine='foglio')
    presenza(c_alba_asacom, '2025-10-08', 'ASACOM', [('P', 1, '10:00', '13:00')], stato='registrato',
             minuti_programmati=180, minuti_svolti=0, minuti_riconosciuti=90, causale='alunno_assente',
             trattamento='meta', origine='foglio')
    presenza(c_alba_asacom, '2025-10-13', 'ASACOM', due_fasce[:2], stato='registrato', minuti_programmati=240,
             minuti_svolti=0, causale='operatore_malattia', sigla='M', origine='foglio')
    presenza(c_sostituto, '2025-10-13', 'ASACOM', due_fasce[2:], stato='registrato', minuti_programmati=240,
             minuti_svolti=240, minuti_riconosciuti=240, origine='foglio')
    presenza(c_alba_educ, '2025-10-07', 'EDUCATORE', [('P', 1, '09:00', '11:00')], minuti_programmati=120,
             origine='programmazione')
    presenza(c_gaia_educ, '2025-10-09', 'EDUCATORE', stato='registrato', minuti_riconosciuti=180, calcolo='manuale',
             testo_originale='3', origine='import_excel', import_id=imp)
    p_psico = presenza(c_gaia_psico, '2025-10-10', 'PSICOLOGO',
                       [('P', 1, '10:00', '12:00'), ('E', 1, '10:00', '11:00')], stato='registrato',
                       minuti_programmati=120, minuti_svolti=60, minuti_riconosciuti=60, causale='evento',
                       nota='Assemblea di prova', origine='griglia')

    ins('napoli_coordinamento', lotto_id=lotto, grado='inferiore', contratto_id=inferiore_x, anno=2025, mese=10,
        operatore_id=sesta, ore_cent=1250, nota='Ore di prova')
    ins('napoli_mesi_chiusi', lotto_id=lotto, anno=2025, mese=10, data_chiusura='2025-11-05T10:00:00',
        nota='Chiusura di prova')
    # ottobre, grado inferiore: ASACOM 570 minuti (9,50 h x 23,44) + coordinatore 12,50 h x 29,66
    righe = [{'figura': 'ASACOM', 'ore': '9.50', 'tariffa_cent': 2344, 'importo_cent': 22268},
             {'figura': 'COORDINATORE', 'ore': '12.50', 'tariffa_cent': 2966, 'importo_cent': 37075}]
    ins('napoli_fatture', lotto_id=lotto, grado='inferiore', contratto_id=inferiore_x, periodo_dal='2025-10-01',
        periodo_al='2025-10-31', numero='1/PROVA', data='2025-11-05', righe_json=json.dumps(righe),
        somma_righe_cent=59343, ritenuta_cent=297, imponibile_cent=59046, iva_cent=2952, totale_cent=61998,
        da_pagare_cent=59046, stato='definitiva', data_creazione='2025-11-05T10:00:00')
    ins('napoli_annullamenti', timestamp='2025-11-04T09:30:00', tipo='griglia',
        descrizione='Griglia: 1 cella, ottobre 2025',
        dati=json.dumps({'presenze': [{'id': p_psico, 'minuti_riconosciuti': 120}]}))


def carica_seme_napoli(client, percorso):
    """Carica i dati di Napoli nel database `percorso` (una volta per database).

    `client` (sessione autenticata) servira' ai passi che caricano il seme con le
    API di Napoli. Ritorna {tabella: righe caricate}."""
    conn = sqlite3.connect(percorso, timeout=30)
    try:
        conn.execute('PRAGMA foreign_keys = ON')
        ins = _Seme(conn)
        with conn:
            _scrivi_seme(ins)
        return ins.righe
    finally:
        conn.close()


def _tabelle(conn):
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _impronta_righe(conn, tabella, dove=''):
    h = hashlib.sha256()
    for riga in conn.execute(f'SELECT * FROM "{tabella}" {dove} ORDER BY rowid'):
        h.update(repr(tuple(riga)).encode('utf-8'))
    return h.hexdigest()


def _connetti(percorso):
    return sqlite3.connect(pathlib.Path(percorso).resolve().as_uri() + '?mode=ro', uri=True)


def impronta_roma(percorso):
    """Schema e righe di tutte le tabelle che non sono di Napoli. Del registro
    attivita' (audit_log, condiviso) contano solo le voci che non sono di Napoli."""
    conn = _connetti(percorso)
    try:
        esito = {}
        for t in _tabelle(conn):
            if t.startswith(PREFISSO_NAPOLI):
                continue
            schema = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (t,)).fetchone()[0]
            dove = "WHERE COALESCE(entita, '') NOT LIKE 'napoli%'" if t == 'audit_log' else ''
            esito[t] = (schema, _impronta_righe(conn, t, dove))
        return esito
    finally:
        conn.close()


def impronta_napoli(percorso):
    """Righe delle tabelle di Napoli (napoli_*)."""
    conn = _connetti(percorso)
    try:
        return {t: _impronta_righe(conn, t) for t in _tabelle(conn) if t.startswith(PREFISSO_NAPOLI)}
    finally:
        conn.close()

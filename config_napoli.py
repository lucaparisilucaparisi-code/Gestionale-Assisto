"""Valori predefiniti della sezione Napoli: regole con data, testi della fattura,
tariffe PROPOSTE.

Nessun import dei moduli di Roma (config.py resta di Roma: niente TARIFFA_ORARIA,
IVA_PERCENTUALE o calcola_fatturazione) e nessun accesso al database.

- REGOLE_PREDEFINITE: per ogni chiave il valore che vale quando in napoli_regole
  non c'e' una riga con data (napoli_calcoli.regola), con la sua validita' (dal, al)
  e la fonte. Fuori dalla sua validita' il predefinito vale lo stesso, perche'
  nessuna data resti senza regola, ma napoli_calcoli.regola_dettaglio lo segnala
  ("fuori_validita") cosi' le pagine possono chiedere di inserire la regola nuova.
- TARIFFE_PROPOSTE: NON sono tariffe in vigore. Servono solo a precompilare le
  tariffe alla creazione di un lotto, che l'utente conferma (napoli_tariffe); i
  calcoli usano sempre e solo le tariffe del lotto con la loro validita'.
"""
from decimal import Decimal

# Inizio del contratto attuale e fine delle tariffe attuali (REGOLE 10: valgono
# anche per marzo e aprile 2026, salvo diversa indicazione, e fino al 31/01/2027).
INIZIO_CONTRATTO_ATTUALE = '2025-09-01'
FINE_TARIFFE_ATTUALI = '2027-01-31'

# Tipi dei valori (napoli_regole.valore e' JSON): napoli_calcoli.valore_regola li controlla.
# decimale, intero, booleano, testo, scelta (con 'scelte'), giorni (0 = lunedi'),
# mesi (1-12), elenco (di testi).
REGOLE_PREDEFINITE = {
    # ---- ore riconosciute di un giorno (PROGETTO §5.2)
    'quota_assenza_alunno': {
        'valore': Decimal('0.5'), 'tipo': 'decimale', 'dal': INIZIO_CONTRATTO_ATTUALE, 'al': FINE_TARIFFE_ATTUALI,
        'fonte': 'REGOLE 1, contratto attuale (dal nuovo accordo CSA: 0, da inserire con la data, Q1)',
        'stato': 'confermata'},
    'quota_assenza_parziale': {
        'valore': Decimal('0.5'), 'tipo': 'decimale', 'dal': INIZIO_CONTRATTO_ATTUALE, 'al': FINE_TARIFFE_ATTUALI,
        'fonte': 'Fogli firma; risposta dell\'utente alla domanda Q2', 'stato': 'confermata'},
    'trattamento_alunno_predefinito': {
        'valore': None, 'tipo': 'scelta', 'scelte': (None, 'meta', 'recupero', 'banca'),
        'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None,
        'fonte': 'Vuoto = "meta" se la quota e\' maggiore di 0, altrimenti "banca" (fase 2)', 'stato': 'confermata'},
    'arrotondamento_mezzo_minuto': {
        'valore': 'eccesso', 'tipo': 'scelta', 'scelte': ('eccesso', 'difetto'),
        'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None, 'fonte': 'Q12 (8:00-9:45 assente = 52,5 -> 53 minuti)',
        'stato': 'da_confermare'},

    # ---- fattura (PROGETTO §5.4, fattura reale: REGOLE 9)
    'ritenuta_percento': {
        'valore': Decimal('0.50'), 'tipo': 'decimale', 'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None,
        'fonte': 'Fattura reale (oggi art. 11 c.6 D.lgs 36/2023)', 'stato': 'confermata'},
    'ritenuta_testo': {
        'valore': 'RITENUTA dello {percento}% ex art. 30, c.5 bis, del D.lgs. 50/2016', 'tipo': 'testo',
        'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None, 'fonte': 'Fattura reale ({percento} = ritenuta_percento)',
        'stato': 'confermata'},
    'iva_percento': {
        'valore': Decimal('5'), 'tipo': 'decimale', 'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None,
        'fonte': 'Fattura reale', 'stato': 'confermata'},
    'split_payment': {
        'valore': True, 'tipo': 'booleano', 'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None,
        'fonte': 'Fattura reale (art. 17-ter DPR 633/72): si paga l\'imponibile', 'stato': 'confermata'},
    'split_payment_testo': {
        'valore': ('Scissione dei pagamenti (split payment) ai sensi dell\'art. 17-ter del D.P.R. 633/1972: '
                   'l\'IVA e\' versata dall\'ente.'),
        'tipo': 'testo', 'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None,
        'fonte': 'Testo da ricopiare nella nota della fattura (modificabile)', 'stato': 'da_confermare'},
    'giorni_pagamento': {
        'valore': 30, 'tipo': 'intero', 'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None,
        'fonte': 'Fattura reale (31/07 -> 30/08)', 'stato': 'confermata'},
    'giorni_scadenza_invio': {
        'valore': 10, 'tipo': 'intero', 'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None,
        'fonte': 'CSA art. 15', 'stato': 'confermata'},

    # ---- giorni, limiti e stampa (PROGETTO §5.3, §5.5)
    'giorni_servizio': {
        'valore': (0, 1, 2, 3, 4, 5), 'tipo': 'giorni', 'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None,
        'fonte': 'CSA: da lunedi\' a sabato', 'stato': 'confermata'},
    'max_minuti_giorno_avviso': {
        'valore': 300, 'tipo': 'intero', 'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None,
        'fonte': 'Oltre 5 ore in un giorno: avviso', 'stato': 'confermata'},
    'max_minuti_giorno_blocco': {
        'valore': 720, 'tipo': 'intero', 'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None,
        'fonte': 'Oltre 12 ore in un giorno: errore di battitura', 'stato': 'confermata'},
    'formato_due_fasce': {
        'valore': 'come_coordinatore', 'tipo': 'scelta', 'scelte': ('come_coordinatore', 'impilato'),
        'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None,
        'fonte': 'Fogli firma: Entrata "8/10", Uscita "12/14" (Q7)', 'stato': 'da_confermare'},
    'tetto_coeff': {
        'valore': Decimal('1.2'), 'tipo': 'decimale', 'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None,
        'fonte': 'CSA 8.3: ore PEI settimanali + 20%', 'stato': 'confermata'},
    'tetto_arrotondamento': {
        'valore': 'vicino', 'tipo': 'scelta', 'scelte': ('vicino', 'eccesso'),
        'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None, 'fonte': 'CSA 8.3; Q15 (ora piu\' vicina)',
        'stato': 'da_confermare'},

    # ---- fase 2 (banca ore): solo valori, ancora nessun calcolo li usa
    'max_minuti_giorno_con_recupero': {
        'valore': 300, 'tipo': 'intero', 'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None,
        'fonte': 'CSA 8.2/8.3: ordinarie + recupero; Q15', 'stato': 'fase_2'},
    'soglia_pei_autorizzazione': {
        'valore': Decimal('18'), 'tipo': 'decimale', 'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None,
        'fonte': 'CSA 8.3', 'stato': 'fase_2'},
    'max_minuti_uso_B_anno': {
        'valore': 600, 'tipo': 'intero', 'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None,
        'fonte': 'CSA 8.3 B: per alunno e anno scolastico', 'stato': 'fase_2'},
    'mesi_uso_D': {
        'valore': (4, 5, 6, 7), 'tipo': 'mesi', 'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None,
        'fonte': 'CSA 8.3 D: aprile-luglio', 'stato': 'fase_2'},
    'usi_fatturabili': {
        'valore': ('A', 'B', 'D'), 'tipo': 'elenco', 'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None,
        'fonte': 'Q16', 'stato': 'fase_2'},
    'scadenza_banca': {
        'valore': 'fine_contratto_applicativo', 'tipo': 'scelta', 'scelte': ('fine_contratto_applicativo',),
        'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None, 'fonte': 'CSA 8.5; Q14', 'stato': 'fase_2'},
}

# ---- testi del prospetto fattura (modelli del lotto: napoli_lotti.oggetto_fattura / nota_fattura)
# Segnaposto dell'oggetto: {lotto} {grado} {dal} {al} {mese} {anno} {contratto}.
MODELLO_OGGETTO_FATTURA = ("Servizio di assistenza specialistica all'integrazione scolastica - Lotto {lotto} - "
                           "Scuole di grado {grado} - Competenze dal {dal} al {al} {mese} {anno}. "
                           "{contratto} APPLICATIVO")
# Segnaposto della nota: {servizio} (riferimento amministrativo del lotto) {dd_numero} {dd_data}
# (determina del contratto applicativo); il testo dello split payment si aggiunge dopo.
MODELLO_NOTA_FATTURA = 'D.D. {servizio} N.{dd_numero} DEL {dd_data}'

# Righe della fattura: descrizione e ordine come nella fattura reale; le figure
# che li' non compaiono vanno in coda.
DESCRIZIONI_FATTURA = {
    'COORDINATORE': 'Coordinatore', 'EDUCATORE': 'Educatore', 'PSICOLOGO': 'Psicologo', 'ASACOM': 'Asacom',
    'TIFLOLOGO': 'Tiflologo', 'LIS': 'Interprete LIS',
}
ORDINE_RIGHE_FATTURA = ('COORDINATORE', 'EDUCATORE', 'PSICOLOGO', 'ASACOM', 'TIFLOLOGO', 'LIS')

# ---- tariffe PROPOSTE alla creazione del lotto (da confermare: NON in vigore finche'
# l'utente non le salva in napoli_tariffe). Centesimi di euro all'ora, IVA esclusa.
# La tariffa LIS resta vuota (Q10): una figura con ore e senza tariffa blocca la fattura.
TARIFFE_PROPOSTE = {
    'ASACOM': 2344,
    'EDUCATORE': 2428,
    'TIFLOLOGO': 2428,
    'PSICOLOGO': 2966,
    'COORDINATORE': 2966,
}
TARIFFE_PROPOSTE_FONTE = 'Proposta: tariffe del contratto attuale (fattura reale, REGOLE 9-10), da confermare'

# Solo promemoria per il nuovo accordo quadro: basi d'asta del CSA (IVA esclusa),
# a cui si applica il ribasso dell'offerta (REGOLE 5). Mai usate nei calcoli.
TARIFFE_BASE_ASTA_CSA = {
    'ASACOM': 2408,
    'EDUCATORE': 2544,
    'LIS': 2544,
    'TIFLOLOGO': 2544,
    'PSICOLOGO': 3045,
    'COORDINATORE': 3045,
}


def tariffe_proposte(valido_da=INIZIO_CONTRATTO_ATTUALE, valido_a=FINE_TARIFFE_ATTUALI):
    """Righe da proporre (e far confermare) alla creazione di un lotto: stessa forma
    di napoli_tariffe, senza lotto. La data di inizio la sceglie l'utente."""
    return [{'figura': figura, 'livello_ccnl': None, 'tariffa_cent': cent, 'valido_da': valido_da,
             'valido_a': valido_a, 'fonte': TARIFFE_PROPOSTE_FONTE}
            for figura, cent in TARIFFE_PROPOSTE.items()]

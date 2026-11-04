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
- Impostazioni (passo 1.3): DESTINATARIO_PROPOSTO e LOTTO_PROPOSTO precompilano i
  moduli, ETICHETTE_REGOLE spiega le regole con parole semplici. I dati della
  cooperativa (ragione sociale, partita IVA, IBAN...) non hanno proposte: li scrive
  l'utente e stanno solo nel database (napoli_impostazioni).
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
        'fonte': 'Vuoto = "meta" se la quota è maggiore di 0, altrimenti "banca" (fase 2)', 'stato': 'confermata'},
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
                   'l\'IVA è versata dall\'ente.'),
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
        'fonte': 'CSA: da lunedì a sabato', 'stato': 'confermata'},
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
        'dal': INIZIO_CONTRATTO_ATTUALE, 'al': None, 'fonte': 'CSA 8.3; Q15 (ora più vicina)',
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
# Figure "di lotto" (napoli_schema.FIGURE con ore_di_lotto = 1): si fatturano dal totale
# mensile di napoli_coordinamento, mai dalle presenze (sarebbero contate due volte).
FIGURE_DI_LOTTO = ('COORDINATORE',)

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
# Nota salvata con le tariffe create dalla procedura guidata (si legge nelle Impostazioni).
TARIFFE_PROPOSTE_NOTA = 'Tariffe del contratto attuale, proposte alla creazione del lotto'

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


# ---- Impostazioni (passo 1.3): valori PROPOSTI nei moduli, che l'utente controlla e salva

# Destinatario delle fatture (fattura reale; dati pubblici dell'ente), uguale per tutti i
# lotti: chiavi di napoli_impostazioni (napoli_calcoli.CAMPI_DESTINATARIO).
DESTINATARIO_PROPOSTO = {
    'destinatario_denominazione': 'Comune di Napoli - AREA WELFARE',
    'destinatario_indirizzo': 'Via Salvatore Tommasi 19',
    'destinatario_cap': '80133',
    'destinatario_comune': 'Napoli',
    'destinatario_provincia': 'NA',
    'destinatario_codice_fiscale': '80014890638',
}

# Lotto proposto dalla procedura "Crea il primo lotto": {numero} = il primo numero libero.
# Codice univoco ufficio e riferimento amministrativo: quelli indicati dal capitolato
# (CSA art. 15), da controllare. Il CIG e le municipalita' li scrive l'utente.
LOTTO_PROPOSTO = {
    'nome': 'NAPOLI LOTTO {numero}',
    'codice_univoco_ufficio': 'C7XXWH',
    'riferimento_amministrativo': '1093',
    'oggetto_fattura': MODELLO_OGGETTO_FATTURA,
    'nota_fattura': MODELLO_NOTA_FATTURA,
}
NUMERI_LOTTO = (1, 2, 3, 4, 5)
SEGNAPOSTO_OGGETTO = ('lotto', 'grado', 'dal', 'al', 'mese', 'anno', 'contratto')
SEGNAPOSTO_NOTA = ('servizio', 'dd_numero', 'dd_data')

# Regole con data spiegate a schermo (stesse chiavi di REGOLE_PREDEFINITE).
# gruppo: dove compaiono nelle Impostazioni ('fase_2' = non ancora usate, in fondo);
# unita': 'quota' (da 0 a 1), 'percento', 'giorni', 'minuti' (a schermo in ore), None;
# min/max: limiti del valore (nell'unita' della regola).
GRUPPI_REGOLE = (
    ('ore', 'Ore riconosciute'),
    ('fattura', 'Fattura'),
    ('limiti', 'Giorni di servizio, limiti e settimana'),
    ('fogli', 'Fogli firma'),
    ('fase_2', 'Banca ore (non ancora usate)'),
)
ETICHETTE_REGOLE = {
    'quota_assenza_alunno': {
        'etichetta': 'Alunno assente: parte dell\'orario programmato che si rendiconta',
        'spiegazione': '0,5 = la metà (10:00-13:00 con l\'alunno assente vale 1 ora e 30). 0 = niente.',
        'gruppo': 'ore', 'unita': 'quota', 'min': 0, 'max': 1},
    'quota_assenza_parziale': {
        'etichetta': 'Alunno entrato dopo o uscito prima: parte delle ore perse che si rendiconta',
        'spiegazione': 'Si contano le ore svolte più questa parte di quelle perse (0,5 = la metà).',
        'gruppo': 'ore', 'unita': 'quota', 'min': 0, 'max': 1},
    'arrotondamento_mezzo_minuto': {
        'etichetta': 'Metà di un orario con i minuti dispari',
        'spiegazione': 'Per esempio la metà di 1 ora e 45 sono 52 minuti e mezzo.',
        'gruppo': 'ore', 'unita': None,
        'scelte': {'eccesso': 'per eccesso (53 minuti)', 'difetto': 'per difetto (52 minuti)'}},
    'ritenuta_percento': {
        'etichetta': 'Ritenuta in fattura (%)',
        'spiegazione': 'Si toglie dalla somma delle righe prima dell\'IVA (oggi 0,50%).',
        'gruppo': 'fattura', 'unita': 'percento', 'min': 0, 'max': 100},
    'ritenuta_testo': {
        'etichetta': 'Testo della riga della ritenuta',
        'spiegazione': '{percento} diventa la percentuale della ritenuta.',
        'gruppo': 'fattura', 'unita': None, 'segnaposto': ('percento',)},
    'iva_percento': {
        'etichetta': 'IVA (%)', 'spiegazione': 'Sull\'imponibile (le tariffe sono IVA esclusa).',
        'gruppo': 'fattura', 'unita': 'percento', 'min': 0, 'max': 100},
    'split_payment': {
        'etichetta': 'Scissione dei pagamenti (split payment)',
        'spiegazione': 'Si: l\'IVA la versa l\'ente e alla cooperativa si paga l\'imponibile.',
        'gruppo': 'fattura', 'unita': None},
    'split_payment_testo': {
        'etichetta': 'Testo dello split payment nella nota della fattura', 'spiegazione': '',
        'gruppo': 'fattura', 'unita': None},
    'giorni_pagamento': {
        'etichetta': 'Giorni per il pagamento', 'spiegazione': 'Dalla data della fattura (31/07 + 30 = 30/08).',
        'gruppo': 'fattura', 'unita': 'giorni', 'min': 0, 'max': 365},
    'giorni_scadenza_invio': {
        'etichetta': 'Giorni per inviare il rendiconto', 'spiegazione': 'Dopo la fine del mese.',
        'gruppo': 'fattura', 'unita': 'giorni', 'min': 0, 'max': 365},
    'giorni_servizio': {
        'etichetta': 'Giorni di servizio della settimana', 'spiegazione': 'Gli altri giorni non hanno ore.',
        'gruppo': 'limiti', 'unita': None},
    'max_minuti_giorno_avviso': {
        'etichetta': 'Avviso se in un giorno ci sono più ore di', 'spiegazione': 'Solo un avviso.',
        'gruppo': 'limiti', 'unita': 'minuti', 'min': 0, 'max': 720},
    'max_minuti_giorno_blocco': {
        'etichetta': 'Errore se in un giorno ci sono più ore di',
        'spiegazione': 'Quasi sempre un errore di battitura: non si salva.',
        'gruppo': 'limiti', 'unita': 'minuti', 'min': 0, 'max': 720},
    'tetto_coeff': {
        'etichetta': 'Tetto settimanale: ore del PEI moltiplicate per',
        'spiegazione': '1,2 = le ore del PEI più il 20%.', 'gruppo': 'limiti', 'unita': None, 'min': 1, 'max': 3},
    'tetto_arrotondamento': {
        'etichetta': 'Arrotondamento del tetto settimanale', 'spiegazione': '',
        'gruppo': 'limiti', 'unita': None,
        'scelte': {'vicino': 'all\'ora più vicina', 'eccesso': 'all\'ora successiva'}},
    'formato_due_fasce': {
        'etichetta': 'Due fasce nello stesso giorno sul foglio firma', 'spiegazione': '',
        'gruppo': 'fogli', 'unita': None,
        'scelte': {'come_coordinatore': 'come il coordinatore: Entrata "8/10", Uscita "12/14"',
                   'impilato': 'una fascia sotto l\'altra'}},
    'trattamento_alunno_predefinito': {
        'etichetta': 'Ore non svolte per l\'assenza dell\'alunno',
        'spiegazione': 'Vuoto = la metà finché la parte da rendicontare è maggiore di 0.',
        'gruppo': 'fase_2', 'unita': None,
        'scelte': {None: 'automatico', 'meta': 'la metà', 'recupero': 'recupero', 'banca': 'banca ore'}},
    'max_minuti_giorno_con_recupero': {
        'etichetta': 'Ore massime in un giorno con il recupero', 'spiegazione': '',
        'gruppo': 'fase_2', 'unita': 'minuti', 'min': 0, 'max': 720},
    'soglia_pei_autorizzazione': {
        'etichetta': 'Ore del PEI oltre le quali serve l\'autorizzazione', 'spiegazione': '',
        'gruppo': 'fase_2', 'unita': None, 'min': 0, 'max': 40},
    'max_minuti_uso_B_anno': {
        'etichetta': 'Ore massime di uso B in un anno scolastico', 'spiegazione': 'Per alunno.',
        'gruppo': 'fase_2', 'unita': 'minuti', 'min': 0, 'max': 60000},
    'mesi_uso_D': {
        'etichetta': 'Mesi dell\'uso D', 'spiegazione': '', 'gruppo': 'fase_2', 'unita': None},
    'usi_fatturabili': {
        'etichetta': 'Usi della banca ore che si fatturano', 'spiegazione': '', 'gruppo': 'fase_2', 'unita': None},
    'scadenza_banca': {
        'etichetta': 'Scadenza della banca ore', 'spiegazione': '', 'gruppo': 'fase_2', 'unita': None,
        'scelte': {'fine_contratto_applicativo': 'alla fine del contratto applicativo'}},
}

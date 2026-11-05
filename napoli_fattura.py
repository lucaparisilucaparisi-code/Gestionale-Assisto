"""Prospetto fattura della sezione Napoli (passo 1.9, PROGETTO §5.4, §5.5 e §9; REGOLE 9, 10, 12).

Una fattura per lotto, grado di scuola (inferiore o superiore), contratto applicativo e
periodo di competenza: il mese tagliato alle date del contratto (il contratto XI dall'08/06
da' "dal 08 al 30 giugno"). Le righe sono quelle della fattura reale: una per figura (ore x
tariffa del lotto valida nei giorni, con un sotto-periodo se la tariffa cambia), la riga
«Coordinatore» dal totale mensile scritto a mano (passo 1.8), la ritenuta dello 0,50% con il
testo della fattura reale, l'imponibile, l'IVA al 5% e, con lo split payment, "da pagare" =
imponibile. I calcoli sono le funzioni pure di napoli_calcoli (prospetto_fattura,
righe_fattura, totali_fattura); qui si leggono i dati e si aggiungono i controlli del mese.

Regole:
- controlli bloccanti (§5.5), spiegati con parole semplici e con dove sistemarli: grado da
  decidere, figura con ore e senza tariffa, ore fuori da ogni contratto applicativo o in due
  contratti, giorni preparati e non registrati, dati obbligatori mancanti (CIG, destinatario,
  oggetto, numero e data della determina, IBAN della cooperativa), periodo non ancora finito.
  Gli avvisi (ore del coordinatore non scritte, nessuna ora, ore del coordinatore nella
  griglia) non bloccano;
- «Rendi definitiva» (con il numero e la data della fattura emessa dal programma di
  contabilita', D9) congela righe, totali, testi e testata in napoli_fatture (stato
  'definitiva', senza nomi): da li' la fattura si mostra, si esporta e si stampa sempre
  uguale, e le ore del suo periodo e del suo grado non cambiano (napoli_db: griglia, ore del
  coordinatore, import delle ore, Ctrl+Z, grado di scuole e alunni, scuola della coppia, date
  del contratto). Si riapre con un motivo (resta nel registro attivita'): torna 'bozza' con il
  numero e la data di prima, e il prospetto si ricalcola dai dati;
- definitiva e riapertura non si annullano con Ctrl+Z (sono azioni "non annullabili", come la
  chiusura del mese); il registro attivita' ha solo numeri, mai nomi o IBAN;
- ritenute cumulate: lo 0,50% si svincola alla fine (oggi art. 11 c.6 D.lgs 36/2023): per
  ogni contratto applicativo la somma delle ritenute delle fatture definitive;
- il mese del lotto si chiude (napoli_presenze.chiudi_mese) solo con le fatture del mese
  definitive o con la conferma "senza fattura" (da_rendere_definitive).
"""
import datetime
import hashlib
import json
from decimal import Decimal

import config_napoli
import database as db
import import_napoli
import napoli_calcoli as calc
import napoli_db as ndb
from napoli_db import Conflitto, DatiNonValidi, NonTrovato

NUMERO_MAX = 30
MOTIVO_MAX = 200
NOMI_GRADO = {'inferiore': 'Grado inferiore', 'superiore': 'Grado superiore'}
SCUOLE_GRADO = {'inferiore': 'Scuole di grado inferiore', 'superiore': 'Scuole di grado superiore'}

# Dove si sistema ogni dato obbligatorio che manca (§5.5): etichetta, pagina.
DATI_OBBLIGATORI = {
    'cig': ('il CIG del lotto', '/napoli/impostazioni#lotto', 'Impostazioni, Lotto'),
    'destinatario': ('il destinatario della fattura', '/napoli/impostazioni#destinatario',
                     'Impostazioni, Destinatario'),
    'oggetto': ('il testo dell\'oggetto', '/napoli/impostazioni#lotto', 'Impostazioni, Lotto'),
    'contratto': ('il numero del contratto applicativo', '/napoli/impostazioni#contratti',
                  'Impostazioni, Contratti'),
    'dd_numero': ('il numero della determina (D.D.) del contratto', '/napoli/impostazioni#contratti',
                  'Impostazioni, Contratti'),
    'dd_data': ('la data della determina (D.D.) del contratto', '/napoli/impostazioni#contratti',
                'Impostazioni, Contratti'),
    'dd': ('il numero e la data della determina (D.D.) del contratto', '/napoli/impostazioni#contratti',
           'Impostazioni, Contratti'),
    'iban': ('l\'IBAN della cooperativa', '/napoli/impostazioni#cooperativa', 'Impostazioni, Cooperativa'),
}


# ==================== aiuti ====================

def _mese_testo(anno, mese):
    return f'{calc.MESI[mese - 1].lower()} {anno}'


def _euro(cent):
    return calc.numero_it(calc.da_centesimi(cent))


def _ore_cent_testo(ore_cent):
    return calc.numero_it(Decimal(int(ore_cent)) / 100)


def _plurale(n, uno, tanti):
    return f'1 {uno}' if n == 1 else f'{n} {tanti}'


def _valida_mese(anno, mese):
    try:
        return calc.valida_mese(anno, mese)
    except ValueError as e:
        raise DatiNonValidi(str(e), 'mese') from None


def _grado(valore):
    grado = str(valore or '').strip().lower()
    if grado not in calc.GRADI:
        raise DatiNonValidi('Il grado è inferiore o superiore: ricarica la pagina.', 'grado')
    return grado


def _id(valore, messaggio, campo):
    if isinstance(valore, bool):
        raise DatiNonValidi(messaggio, campo)
    try:
        return int(str(valore).strip())
    except (TypeError, ValueError):
        raise DatiNonValidi(messaggio, campo) from None


# ==================== lettura del mese ====================

class _Contesto:
    """Tutto quello che serve per i prospetti di un lotto in un mese, letto una volta."""

    def __init__(self, conn, lotto_id, anno, mese):
        self.lotto = ndb.lotto(lotto_id, conn)
        self.lotto_id, self.anno, self.mese = lotto_id, anno, mese
        self.dal, self.al = datetime.date(anno, mese, 1), calc.fine_mese(anno, mese)
        dal, al = self.dal.isoformat(), self.al.isoformat()
        self.oggi = ndb._oggi()
        self.impostazioni = ndb.leggi_impostazioni(conn)
        self.contratti = ndb._righe(conn, 'SELECT * FROM napoli_contratti WHERE lotto_id = ? ORDER BY valido_da, '
                                          'grado, id', (lotto_id,))
        self.tariffe = ndb._righe(conn, 'SELECT * FROM napoli_tariffe WHERE lotto_id = ?', (lotto_id,))
        self.righe_regole = ndb._righe(conn, 'SELECT * FROM napoli_regole')
        self.presenze = ndb._righe(conn, '''
            SELECT p.id, p.coppia_id, p.data, p.figura, p.stato, p.minuti_riconosciuti,
                   c.scuola_id, c.operatore_id, a.grado AS a_grado, s.grado AS s_grado,
                   s.nome AS scuola, s.municipalita, o.cognome, o.nome, o.livello_ccnl
            FROM napoli_presenze p
            JOIN napoli_coppie c ON c.id = p.coppia_id
            JOIN napoli_alunni a ON a.id = c.alunno_id
            JOIN napoli_scuole s ON s.id = c.scuola_id
            JOIN napoli_operatori o ON o.id = c.operatore_id
            WHERE p.lotto_id = ? AND p.data BETWEEN ? AND ?
            ORDER BY p.data, p.id''', (lotto_id, dal, al))
        for p in self.presenze:
            # il grado della presenza: quello dell'alunno, altrimenti quello della scuola (§4.2)
            p['grado'] = p['a_grado'] or p['s_grado']
        self.coordinamento = ndb._righe(conn, '''
            SELECT k.*, o.livello_ccnl FROM napoli_coordinamento k
            LEFT JOIN napoli_operatori o ON o.id = k.operatore_id
            WHERE k.lotto_id = ? AND k.anno = ? AND k.mese = ?''', (lotto_id, anno, mese))
        self.fatture = {(f['contratto_id'], f['grado']): f for f in ndb._righe(
            conn, 'SELECT f.*, c.numero AS contratto_numero FROM napoli_fatture f '
                  'JOIN napoli_contratti c ON c.id = f.contratto_id '
                  'WHERE f.lotto_id = ? AND substr(f.periodo_dal, 1, 7) = ? ORDER BY f.id',
            (lotto_id, f'{anno:04d}-{mese:02d}'))}
        self.chiuso = conn.execute('SELECT 1 FROM napoli_mesi_chiusi WHERE lotto_id = ? AND anno = ? AND mese = ?',
                                   (lotto_id, anno, mese)).fetchone() is not None

    def chiavi(self):
        """(contratto, grado, periodo) dei prospetti del mese: i contratti che toccano il mese,
        per il loro grado (senza grado: tutti e due)."""
        out = []
        for c in self.contratti:
            periodo = calc.periodo_fattura(self.anno, self.mese, c['valido_da'], c['valido_a'])
            if periodo is None:
                continue
            for grado in ([c['grado']] if c['grado'] else calc.GRADI):
                out.append((c, grado, periodo))
        return out

    def contratto(self, contratto_id):
        for c in self.contratti:
            if c['id'] == contratto_id:
                return c
        raise NonTrovato('Il contratto applicativo non esiste (forse è stato eliminato): ricarica la pagina.')


# ==================== un prospetto ====================

def _ore_testo(minuti):
    """'1 ora', '3 ore', '1,5 ore' (ore decimali al centesimo)."""
    return '1 ora' if int(minuti) == 60 else f'{calc.ore_brevi(minuti)} ore'


def _spiega(b, prospetto, ctx):
    """Un controllo con titolo, testo semplice e dove sistemarlo (link)."""
    codice = b['codice']
    figura = ndb.nome_figura(b['figura']) if b.get('figura') else ''
    ore = _ore_testo(b.get('minuti') or 0)
    n = b.get('presenze') or 0
    giorni = _plurale(n, 'giorno', 'giorni')
    grado = ndb.NOMI_GRADO[prospetto['grado']]
    periodo = prospetto['periodo_testo']
    out = {'codice': codice, 'link': None, 'link_testo': None}
    if codice == 'tariffa_mancante':
        if b.get('figura') == 'COORDINATORE':
            testo = ('Ci sono le ore del coordinatore, ma nel lotto manca la tariffa del coordinatore valida '
                     f'{periodo}: aggiungila.')
        else:
            testo = (f'{figura}: {ore} ({giorni}) senza una tariffa del lotto valida in quei giorni. Aggiungi la '
                     'tariffa: senza, quelle ore non si possono fatturare.')
        out.update(titolo=f'Manca la tariffa {figura}', testo=testo, link='/napoli/impostazioni#tariffe',
                   link_testo='Impostazioni, Tariffe')
    elif codice == 'tariffa_cambia_nel_periodo':
        out.update(titolo='La tariffa del coordinatore cambia nel periodo',
                   testo=(f'Le ore del coordinatore sono un totale del mese, ma la sua tariffa cambia {periodo}: '
                          'il programma non sa come dividerle. Controlla le date delle tariffe.'),
                   link='/napoli/impostazioni#tariffe', link_testo='Impostazioni, Tariffe')
    elif codice == 'grado_da_decidere':
        out.update(titolo='Grado da decidere',
                   testo=(f'{figura}: {ore} ({giorni}) di alunni o scuole con il grado da decidere (o di una scuola '
                          'mista con l\'alunno senza grado). Scegli il grado: finché manca, nessuna fattura del mese '
                          'si rende definitiva, perché quelle ore potrebbero andare in tutte e due.'),
                   link='/napoli/anagrafiche#scuole', link_testo='Anagrafiche, Scuole')
    elif codice == 'giorni_non_registrati':
        quanti = ('1 giorno è preparato ma non ancora registrato e vale' if n == 1 else
                  f'{n} giorni sono preparati ma non ancora registrati e valgono')
        out.update(titolo='Giorni non registrati',
                   testo=f'{figura}: {quanti} 0 ore. Scrivi le ore (anche 0) nella griglia.',
                   link='/napoli/presenze', link_testo='Presenze')
    elif codice == 'presenza_fuori_contratto':
        out.update(titolo='Ore fuori dai contratti applicativi',
                   testo=(f'{figura}: {ore} ({giorni}) del {grado} in date di {_mese_testo(ctx.anno, ctx.mese)} che '
                          'nessun contratto applicativo copre. Aggiungi il contratto (o correggi le sue date), '
                          'oppure controlla le ore.'),
                   link='/napoli/impostazioni#contratti', link_testo='Impostazioni, Contratti')
    elif codice == 'presenza_in_piu_contratti':
        out.update(titolo='Ore in due contratti applicativi',
                   testo=(f'{figura}: {ore} ({giorni}) in date coperte da due contratti dello stesso grado: '
                          'finirebbero in due fatture. Correggi le date dei contratti.'),
                   link='/napoli/impostazioni#contratti', link_testo='Impostazioni, Contratti')
    elif codice == 'dato_mancante':
        etichetta, link, link_testo = DATI_OBBLIGATORI.get(b.get('campo'), (b.get('campo'), None, None))
        manca = 'Mancano' if b.get('campo') == 'dd' else 'Manca'
        out.update(titolo=f'{manca} {etichetta}', campo=b.get('campo'),
                   testo=(f'Per la fattura {"servono" if manca == "Mancano" else "serve"} {etichetta}: '
                          f'{"scrivili" if manca == "Mancano" else "scrivilo"} nelle Impostazioni.'),
                   link=link, link_testo=link_testo)
    elif codice == 'periodo_non_finito':
        out.update(titolo='Il periodo non è ancora finito',
                   testo=(f'Il periodo finisce il {calc.data_it(prospetto["al"])}: la fattura si rende definitiva da '
                          'quel giorno, quando tutte le ore sono scritte.'))
    elif codice == 'nessuna_riga':
        out.update(titolo='Nessuna ora da fatturare',
                   testo=f'Nel periodo non ci sono ore registrate del {grado} né ore del coordinatore.')
    elif codice == 'coordinatore_non_scritto':
        out.update(titolo='Ore del coordinatore non scritte',
                   testo=('Le ore del coordinatore di questo periodo non sono scritte: scrivile nella casella «Ore del '
                          'coordinatore» (anche 0 se non ce ne sono).'))
    elif codice == 'ore_coordinatore_nelle_presenze':
        out.update(titolo='Ore del coordinatore nella griglia',
                   testo=(f'Nella griglia ci sono ore con la figura Coordinatore ({ore}): in fattura il coordinatore '
                          'va solo con il totale del mese, quindi quelle ore non sono contate.'),
                   link='/napoli/presenze', link_testo='Presenze')
    elif codice == 'cambiata_dopo':
        out.update(titolo='I dati sono cambiati dopo la definitiva',
                   testo=('Calcolata oggi dai dati (tariffe, livelli degli operatori o regole cambiati dopo), questa '
                          f'fattura darebbe un imponibile di {b["imponibile"]} euro invece di '
                          f'{prospetto["totali"]["imponibile"]}. La fattura definitiva resta com\'era: se va '
                          'corretta, riaprila.'))
    else:
        out.update(titolo=codice.replace('_', ' ').capitalize(), testo='')
    return out


def _dettaglio(ctx, grado, dal, al):
    """Ore della fattura per scuola e per operatore (con la figura): per controllare."""
    scuole, operatori = {}, {}
    for p in ctx.presenze:
        giorno = calc.data(p['data'])
        if (not dal <= giorno <= al or p['stato'] != 'registrato' or not p['minuti_riconosciuti']
                or calc.grado_fattura(p['grado']) != grado or p['figura'] in config_napoli.FIGURE_DI_LOTTO):
            continue
        s = scuole.setdefault((p['scuola'], p['municipalita'], p['figura']), 0)
        scuole[(p['scuola'], p['municipalita'], p['figura'])] = s + int(p['minuti_riconosciuti'])
        chiave = (f'{p["cognome"] or ""} {p["nome"] or ""}'.strip(), p['figura'])
        operatori[chiave] = operatori.get(chiave, 0) + int(p['minuti_riconosciuti'])
    ordine = {f: i for i, f in enumerate(config_napoli.ORDINE_RIGHE_FATTURA)}
    return {
        'scuole': [{'scuola': s, 'municipalita': m, 'figura': ndb.nome_figura(f), 'minuti': n,
                    'ore': calc.ore_brevi(n)}
                   for (s, m, f), n in sorted(scuole.items(), key=lambda x: (x[0][0] or '', x[0][1] or 0,
                                                                              ordine.get(x[0][2], 99)))],
        'operatori': [{'operatore': o, 'figura': ndb.nome_figura(f), 'minuti': n, 'ore': calc.ore_brevi(n)}
                      for (o, f), n in sorted(operatori.items(), key=lambda x: (x[0][0].lower(),
                                                                                 ordine.get(x[0][1], 99)))],
    }


def _testata(ctx, contratto):
    """La testata del prospetto con i dati di oggi (lotto, contratto, cooperativa): IBAN mascherato."""
    imp, lotto = ctx.impostazioni, ctx.lotto
    return {'lotto': lotto['nome'], 'numero_lotto': lotto['numero_lotto'], 'cig': lotto.get('cig') or '',
            'cup': lotto.get('cup') or '', 'codice_univoco_ufficio': lotto.get('codice_univoco_ufficio') or '',
            'contratto': contratto['numero'], 'accordo_quadro': contratto.get('accordo_quadro') or '',
            'cooperativa': imp.get('cooperativa_denominazione') or '',
            'partita_iva': imp.get('cooperativa_partita_iva') or '',
            'codice_fiscale': imp.get('cooperativa_codice_fiscale') or '',
            'iban': calc.maschera_iban(imp.get('cooperativa_iban') or '')}


def _riga_pagina(r):
    """Una riga della fattura per la pagina e per gli export (numeri come testo e come numero)."""
    ore_cent, tariffa_cent, importo_cent = int(r['ore_cent']), int(r['tariffa_cent']), int(r['importo_cent'])
    return {'figura': r['figura'], 'descrizione': r['descrizione'], 'livello_ccnl': r.get('livello_ccnl'),
            'dal': r.get('dal'), 'al': r.get('al'), 'minuti': r.get('minuti'),
            'ore_cent': ore_cent, 'tariffa_cent': tariffa_cent, 'importo_cent': importo_cent,
            'ore': _ore_cent_testo(ore_cent), 'tariffa': _euro(tariffa_cent), 'importo': _euro(importo_cent)}


def _totali_pagina(t):
    """Totali in centesimi e come testo ('24.743,72')."""
    out = {}
    for k in ('somma', 'ritenuta', 'imponibile', 'iva', 'totale', 'da_pagare'):
        out[k + '_cent'] = int(t[k + '_cent'])
        out[k] = _euro(t[k + '_cent'])
    return out


def _impronta(p):
    """Impronta di quello che si vede del prospetto (righe, totali, testi, testata): la definitiva
    si fa solo se nel frattempo non e' cambiato niente."""
    parti = {'righe': [(r['figura'], r['descrizione'], r['ore_cent'], r['tariffa_cent'], r['importo_cent'])
                       for r in p['righe']],
             'totali': {k: v for k, v in p['totali'].items() if k.endswith('_cent')},
             'testi': [p['oggetto'], p['nota'], p['destinatario'], p['ritenuta_testo']],
             'testata': p['testata'], 'periodo': [p['dal'], p['al']]}
    return hashlib.sha256(json.dumps(parti, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _calcola(ctx, contratto, grado):
    """Il prospetto calcolato oggi dai dati (non congelato)."""
    coordinamento = [c for c in ctx.coordinamento if c['contratto_id'] == contratto['id'] and c['grado'] == grado]
    p = calc.prospetto_fattura(ctx.anno, ctx.mese, grado, contratto, ctx.presenze, ctx.tariffe, coordinamento,
                               ctx.lotto, ctx.righe_regole, ctx.impostazioni)
    dal, al = p['dal'], p['al']
    regole = p['regole']
    out = {
        'contratto_id': contratto['id'], 'numero': contratto['numero'], 'grado': grado,
        'grado_testo': NOMI_GRADO[grado], 'scuole_grado': SCUOLE_GRADO[grado],
        'dal': dal.isoformat(), 'al': al.isoformat(),
        'periodo_testo': f'dal {calc.data_it(dal)} al {calc.data_it(al)}',
        'mese_intero': dal.day == 1 and al == calc.fine_mese(ctx.anno, ctx.mese),
        'righe': [_riga_pagina(r) for r in p['righe']],
        'totali': _totali_pagina(p['totali']),
        'ritenuta_testo': p['ritenuta_testo'], 'ritenuta_percento': calc.numero_it(regole['ritenuta_percento']),
        'iva_percento': calc.ore_it(regole['iva_percento']), 'split_payment': bool(regole['split_payment']),
        'giorni_pagamento': int(regole['giorni_pagamento']),
        'oggetto': p['oggetto'], 'nota': p['nota'], 'destinatario': p['destinatario'],
        'scadenza': None, 'scadenza_testo': f'a {int(regole["giorni_pagamento"])} giorni dalla data della fattura',
        'testata': _testata(ctx, contratto),
        'regole': {k: (str(v) if isinstance(v, Decimal) else v) for k, v in regole.items()},
    }
    pres_grado = [x for x in ctx.presenze if calc.grado_fattura(x['grado']) in (None, grado)
                  and x['figura'] not in config_napoli.FIGURE_DI_LOTTO]
    bloccanti = list(p['bloccanti'])
    bloccanti += calc.ore_fuori_contratto(pres_grado, ctx.contratti)
    bloccanti += calc.presenze_in_piu_contratti(pres_grado, ctx.contratti)
    if al > ctx.oggi:
        bloccanti.append({'codice': 'periodo_non_finito'})
    avvisi = list(p['avvisi'])
    if not coordinamento:
        avvisi.insert(0, {'codice': 'coordinatore_non_scritto'})
    out['bloccanti_grezzi'], out['avvisi_grezzi'] = bloccanti, avvisi
    out['dettaglio'] = _dettaglio(ctx, grado, dal, al)
    ore_coord = sum(int(c['ore_cent'] or 0) for c in coordinamento)
    out['coordinatore'] = {'anno': ctx.anno, 'mese': ctx.mese, 'contratto_id': contratto['id'], 'grado': grado,
                           'scritte': bool(coordinamento),
                           'ore': _ore_cent_testo(ore_coord) if coordinamento else ''}
    return out


def _congelato(ctx, f):
    """Il prospetto della fattura definitiva (o riaperta) come e' stato congelato."""
    try:
        righe = json.loads(f['righe_json'] or '[]')
    except ValueError:
        righe = []
    try:
        testata = json.loads(f.get('testata_json') or '{}') or {}
    except ValueError:
        testata = {}
    try:
        regole = json.loads(f.get('regole_json') or '{}') or {}
    except ValueError:
        regole = {}
    out_righe = []
    for r in righe if isinstance(righe, list) else []:
        ore_cent = r.get('ore_cent')
        if ore_cent is None:
            ore_cent = int(calc.arrotonda(calc.decimale(r.get('ore') or 0)) * 100)
        out_righe.append(_riga_pagina({
            'figura': r.get('figura'), 'livello_ccnl': r.get('livello_ccnl'), 'dal': r.get('dal'), 'al': r.get('al'),
            'minuti': r.get('minuti'),
            'descrizione': r.get('descrizione') or config_napoli.DESCRIZIONI_FATTURA.get(r.get('figura'),
                                                                                         str(r.get('figura'))),
            'ore_cent': ore_cent, 'tariffa_cent': r.get('tariffa_cent') or 0, 'importo_cent': r.get('importo_cent') or 0}))
    totali = _totali_pagina({'somma_cent': f['somma_righe_cent'], 'ritenuta_cent': f['ritenuta_cent'],
                             'imponibile_cent': f['imponibile_cent'], 'iva_cent': f['iva_cent'],
                             'totale_cent': f['totale_cent'], 'da_pagare_cent': f['da_pagare_cent']})
    contratto = next((c for c in ctx.contratti if c['id'] == f['contratto_id']), {'numero': f.get('contratto_numero')})
    if not testata:
        # fattura di prima della migrazione 7: la testata con i dati di oggi
        testata = _testata(ctx, dict(contratto, numero=f.get('contratto_numero') or contratto.get('numero')))
    giorni = regole.get('giorni_pagamento')
    return {
        'righe': out_righe, 'totali': totali,
        'ritenuta_testo': f.get('ritenuta_testo') or '',
        'ritenuta_percento': calc.numero_it(calc.decimale(regole.get('ritenuta_percento') or '0.50')),
        'iva_percento': calc.ore_it(calc.decimale(regole.get('iva_percento') or '5')),
        'split_payment': bool(regole.get('split_payment', f['da_pagare_cent'] == f['imponibile_cent'])),
        'giorni_pagamento': int(giorni) if giorni is not None else None,
        'oggetto': f.get('oggetto') or '', 'nota': f.get('nota') or '', 'destinatario': f.get('destinatario') or '',
        'scadenza': f.get('scadenza'),
        'scadenza_testo': calc.data_it(f['scadenza']) if f.get('scadenza') else '',
        'testata': testata, 'regole': regole,
    }


def _fattura_pagina(f):
    if not f:
        return None
    return {'id': f['id'], 'stato': f['stato'], 'numero': f.get('numero') or '', 'data': f.get('data') or '',
            'data_testo': calc.data_it(f['data']) if f.get('data') else '',
            'definitiva_il': f.get('definitiva_il') or (f.get('data_creazione') if f['stato'] == 'definitiva' else None),
            'riaperta_il': f.get('riaperta_il')}


def _prospetto(ctx, contratto, grado):
    """Il prospetto per la pagina: congelato se la fattura e' definitiva, altrimenti calcolato
    oggi; con i controlli spiegati e cosa si puo' fare."""
    vivo = _calcola(ctx, contratto, grado)
    f = ctx.fatture.get((contratto['id'], grado))
    stato = f['stato'] if f else 'da_fare'
    out = dict(vivo)
    out['chiave'] = f'{contratto["id"]}-{grado}'
    out['stato'] = 'riaperta' if stato == 'bozza' else stato
    out['fattura'] = _fattura_pagina(f)
    out['impronta'] = _impronta(vivo)
    if stato == 'definitiva':
        out.update(_congelato(ctx, f))
        out['dal'], out['al'] = f['periodo_dal'], f['periodo_al']
        out['periodo_testo'] = f'dal {calc.data_it(f["periodo_dal"])} al {calc.data_it(f["periodo_al"])}'
        bloccanti, avvisi = [], []
        if vivo['totali']['imponibile_cent'] != out['totali']['imponibile_cent'] or \
                [r['importo_cent'] for r in vivo['righe']] != [r['importo_cent'] for r in out['righe']]:
            avvisi.append({'codice': 'cambiata_dopo', 'imponibile': vivo['totali']['imponibile']})
    else:
        bloccanti, avvisi = vivo['bloccanti_grezzi'], vivo['avvisi_grezzi']
        if not vivo['righe']:
            bloccanti = [b for b in bloccanti if b['codice'] != 'dato_mancante']
    out.pop('bloccanti_grezzi', None)
    out.pop('avvisi_grezzi', None)
    campi = [b.get('campo') for b in bloccanti if b['codice'] == 'dato_mancante']
    if 'dd_numero' in campi and 'dd_data' in campi:
        # numero e data della determina mancano insieme: una voce sola
        bloccanti = [b for b in bloccanti if not (b['codice'] == 'dato_mancante' and b.get('campo') == 'dd_data')]
        for b in bloccanti:
            if b['codice'] == 'dato_mancante' and b.get('campo') == 'dd_numero':
                b['campo'] = 'dd'
    out['bloccanti'] = [_spiega(b, out, ctx) for b in bloccanti]
    out['avvisi'] = [_spiega(a, out, ctx) for a in avvisi]
    out['puo_rendere_definitiva'] = stato != 'definitiva' and bool(vivo['righe']) and not bloccanti
    out['coordinatore']['modificabile'] = (stato != 'definitiva' and not ctx.chiuso
                                           and (ctx.anno, ctx.mese) <= (ctx.oggi.year, ctx.oggi.month))
    out['vuoto'] = not out['righe']
    return out


def _intestazione(ctx):
    return {'lotto': {'id': ctx.lotto['id'], 'nome': ctx.lotto['nome']}, 'anno': ctx.anno, 'mese': ctx.mese,
            'testo': f'{calc.MESI[ctx.mese - 1]} {ctx.anno}', 'oggi': ctx.oggi.isoformat(), 'chiuso': ctx.chiuso,
            'finito': ctx.al <= ctx.oggi, 'contratti': len(ctx.contratti)}


def elenco(lotto_id, anno, mese):
    """I prospetti di un lotto in un mese: uno per contratto applicativo e grado che toccano il
    mese (in ordine di contratto, prima il grado inferiore), con i controlli, le fatture
    definitive e le ore che nessun contratto copre."""
    anno, mese = _valida_mese(anno, mese)
    with db.get_db_context() as conn:
        ctx = _Contesto(conn, lotto_id, anno, mese)
    prospetti = [_prospetto(ctx, c, g) for c, g, _p in ctx.chiavi()]
    senza_contratto = calc.ore_fuori_contratto(
        [p for p in ctx.presenze if p['figura'] not in config_napoli.FIGURE_DI_LOTTO], ctx.contratti)
    minuti_fuori = sum(b['minuti'] for b in senza_contratto)
    return dict(_intestazione(ctx), prospetti=prospetti,
                ore_senza_contratto=calc.ore_brevi(minuti_fuori) if minuti_fuori else '',
                definitive=sum(1 for p in prospetti if p['stato'] == 'definitiva'))


def prospetto(lotto_id, anno, mese, contratto_id, grado):
    """Un prospetto (per l'Excel e la stampa)."""
    anno, mese = _valida_mese(anno, mese)
    grado = _grado(grado)
    contratto_id = _id(contratto_id, 'Il contratto applicativo non è valido: ricarica la pagina.', 'contratto_id')
    with db.get_db_context() as conn:
        ctx = _Contesto(conn, lotto_id, anno, mese)
    contratto = ctx.contratto(contratto_id)
    if (contratto, grado) not in [(c, g) for c, g, _p in ctx.chiavi()]:
        raise NonTrovato(f'Il contratto {contratto["numero"]} non ha una fattura del {ndb.NOMI_GRADO[grado]} in '
                         f'{_mese_testo(anno, mese)}: ricarica la pagina.')
    return dict(_prospetto(ctx, contratto, grado), mese_info=_intestazione(ctx))


# ==================== rendi definitiva e riapri ====================

def _righe_da_congelare(prospetto_vivo):
    """Le righe senza nomi (figura, descrizione, ore, tariffa, importo, sotto-periodo)."""
    return [{'figura': r['figura'], 'descrizione': r['descrizione'], 'livello_ccnl': r['livello_ccnl'],
             'dal': r['dal'].isoformat() if isinstance(r['dal'], datetime.date) else r['dal'],
             'al': r['al'].isoformat() if isinstance(r['al'], datetime.date) else r['al'],
             'minuti': r['minuti'], 'ore': str(Decimal(r['ore_cent']) / 100), 'ore_cent': r['ore_cent'],
             'tariffa_cent': r['tariffa_cent'], 'importo_cent': r['importo_cent']}
            for r in prospetto_vivo['righe']]


def rendi_definitiva(lotto_id, dati):
    """Congela il prospetto di un mese, contratto e grado (napoli_fatture, stato 'definitiva'),
    con il numero e la data della fattura emessa. dati: anno, mese, contratto_id, grado, numero,
    data, impronta (quella del prospetto mostrato). Errori: bloccanti (400 FATTURA_BLOCCATA),
    nessuna ora (400 NESSUNA_RIGA), prospetto cambiato nel frattempo (409 PROSPETTO_CAMBIATO),
    gia' definitiva (409 GIA_DEFINITIVA), numero gia' usato nello stesso anno (409 NUMERO_GIA_USATO)."""
    anno, mese = _valida_mese(dati.get('anno'), dati.get('mese'))
    grado = _grado(dati.get('grado'))
    contratto_id = _id(dati.get('contratto_id'), 'Il contratto applicativo non è valido: ricarica la pagina.',
                       'contratto_id')
    numero = ndb._testo(dati, 'numero', 'Il numero della fattura', obbligatorio=True, massimo=NUMERO_MAX,
                        manca='Scrivi il numero della fattura emessa (per esempio 37A2/2026).')
    numero = import_napoli.nascondi_codici_fiscali(numero)
    if not str(dati.get('data') or '').strip():
        raise DatiNonValidi('Scrivi la data della fattura emessa.', 'data')
    data_fattura = calc.data(ndb._valida(calc.valida_data, 'data', dati.get('data'), 'La data della fattura'))
    with db.get_db_context() as conn:
        conn.execute('BEGIN IMMEDIATE')
        ctx = _Contesto(conn, lotto_id, anno, mese)
        contratto = ctx.contratto(contratto_id)
        if (contratto, grado) not in [(c, g) for c, g, _p in ctx.chiavi()]:
            raise DatiNonValidi(f'Il contratto {contratto["numero"]} non copre il {ndb.NOMI_GRADO[grado]} in '
                                f'{_mese_testo(anno, mese)}: ricarica la pagina.', 'contratto_id')
        attuale = ctx.fatture.get((contratto_id, grado))
        if attuale and attuale['stato'] == 'definitiva':
            raise Conflitto(f'La fattura di {ndb.descrivi_fattura(attuale)} è già definitiva.', codice='GIA_DEFINITIVA')
        p = _prospetto(ctx, contratto, grado)
        if dati.get('impronta') and str(dati.get('impronta')) != p['impronta']:
            raise Conflitto('Mentre guardavi il prospetto i dati sono cambiati (ore, tariffe o impostazioni): '
                            'ricontrolla i numeri e poi rendi definitiva.', codice='PROSPETTO_CAMBIATO')
        if p['vuoto']:
            raise DatiNonValidi('Nel periodo non ci sono ore da fatturare: non c\'è niente da rendere definitivo.',
                                codice='NESSUNA_RIGA')
        if p['bloccanti']:
            raise DatiNonValidi('Prima di rendere definitiva la fattura bisogna sistemare: '
                                + '; '.join(b['titolo'].lower() for b in p['bloccanti']) + '.',
                                codice='FATTURA_BLOCCATA', bloccanti=p['bloccanti'])
        if data_fattura < calc.data(p['dal']):
            raise DatiNonValidi(f'La data della fattura è prima dell\'inizio del periodo ({calc.data_it(p["dal"])}): '
                                'controlla la data.', 'data')
        if data_fattura > ctx.oggi:
            raise DatiNonValidi('La data della fattura non può essere dopo oggi: scrivi la data della fattura emessa.',
                                'data')
        doppio = ndb._riga(conn, "SELECT f.*, c.numero AS contratto_numero FROM napoli_fatture f "
                                 "JOIN napoli_contratti c ON c.id = f.contratto_id WHERE f.stato = 'definitiva' "
                                 "AND f.numero = ? AND substr(f.data, 1, 4) = ?", (numero, str(data_fattura.year)))
        if doppio:
            raise Conflitto(f'Il numero {numero} è già della fattura definitiva di {ndb.descrivi_fattura(doppio)}: '
                            'controlla il numero.', 'numero', codice='NUMERO_GIA_USATO')
        coordinamento = [c for c in ctx.coordinamento if c['contratto_id'] == contratto_id and c['grado'] == grado]
        completo = calc.prospetto_fattura(anno, mese, grado, contratto, ctx.presenze, ctx.tariffe, coordinamento,
                                          ctx.lotto, ctx.righe_regole, ctx.impostazioni, data_fattura=data_fattura)
        testi = calc.testi_da_congelare(completo)
        t = completo['totali']
        ora = ndb._ora()
        valori = dict(
            lotto_id=lotto_id, grado=grado, contratto_id=contratto_id, periodo_dal=completo['dal'].isoformat(),
            periodo_al=completo['al'].isoformat(), numero=numero, data=data_fattura.isoformat(),
            righe_json=json.dumps(_righe_da_congelare({'righe': completo['righe']}), ensure_ascii=False),
            somma_righe_cent=t['somma_cent'], ritenuta_cent=t['ritenuta_cent'], imponibile_cent=t['imponibile_cent'],
            iva_cent=t['iva_cent'], totale_cent=t['totale_cent'], da_pagare_cent=t['da_pagare_cent'],
            stato='definitiva', testata_json=json.dumps(_testata(ctx, contratto), ensure_ascii=False),
            definitiva_il=ora, **testi)
        if attuale:
            assegna = ', '.join(f'{k} = ?' for k in valori)
            conn.execute(f'UPDATE napoli_fatture SET {assegna} WHERE id = ?', tuple(valori.values()) + (attuale['id'],))
            fattura_id = attuale['id']
        else:
            valori['data_creazione'] = ora
            nomi = ', '.join(valori)
            cur = conn.execute(f'INSERT INTO napoli_fatture ({nomi}) VALUES ({", ".join("?" * len(valori))})',
                               tuple(valori.values()))
            fattura_id = cur.lastrowid
        descrizione = (f'Fattura definitiva di {_mese_testo(anno, mese)}, contratto {contratto["numero"]} '
                       f'({ndb.NOMI_GRADO[grado]}), n. {numero}: imponibile {_euro(t["imponibile_cent"])} euro')
        ndb.registra_non_annullabile(conn, 'fattura', descrizione,
                                     'una fattura definitiva si riapre con il pulsante «Riapri la fattura», '
                                     'scrivendo il motivo')
    db.log_audit('definitiva', 'napoli_fattura', fattura_id, dettagli=f'Napoli, {ctx.lotto["nome"]}: {descrizione}')
    return {'fattura_id': fattura_id,
            'messaggio': (f'Fattura n. {numero} definitiva: righe, totali e testi non cambiano più e le ore del '
                          f'periodo {p["periodo_testo"]} ({ndb.NOMI_GRADO[grado]}) sono bloccate')}


def riapri(fattura_id, dati):
    """Riapre una fattura definitiva (torna 'bozza', con il numero e la data di prima): il
    prospetto si ricalcola dai dati e le ore del periodo si possono di nuovo cambiare. Il motivo
    e' obbligatorio e resta nel registro attivita' (codici fiscali mascherati)."""
    motivo = ndb._testo(dati, 'motivo', 'Il motivo', obbligatorio=True, massimo=MOTIVO_MAX,
                        manca='Scrivi perché riapri la fattura: resta nel registro attività.')
    if len(motivo) < 5:
        raise DatiNonValidi('Scrivi il motivo con qualche parola in più: resta nel registro attività.', 'motivo')
    motivo = import_napoli.nascondi_codici_fiscali(motivo)
    with db.get_db_context() as conn:
        f = ndb._riga(conn, 'SELECT f.*, c.numero AS contratto_numero FROM napoli_fatture f '
                            'JOIN napoli_contratti c ON c.id = f.contratto_id WHERE f.id = ?', (fattura_id,))
        if not f:
            raise NonTrovato('La fattura non c\'è più: ricarica la pagina.')
        if f['stato'] != 'definitiva':
            raise Conflitto('La fattura non è definitiva: è già aperta.', codice='NON_DEFINITIVA')
        lotto = ndb.lotto(f['lotto_id'], conn)
        conn.execute("UPDATE napoli_fatture SET stato = 'bozza', riaperta_il = ? WHERE id = ?", (ndb._ora(), fattura_id))
        descrizione = f'Riapertura della fattura di {ndb.descrivi_fattura(f)}'
        ndb.registra_non_annullabile(conn, 'fattura', descrizione,
                                     'per rendere di nuovo definitiva la fattura usa «Rendi definitiva»')
    db.log_audit('riapertura', 'napoli_fattura', fattura_id,
                 dettagli=f'Napoli, {lotto["nome"]}: {descrizione}. Motivo: {motivo}')
    return {'messaggio': (f'La fattura di {ndb.descrivi_fattura(f)} è di nuovo aperta: il prospetto si ricalcola dai '
                          'dati e le ore del periodo si possono cambiare')}


# ==================== ritenute cumulate ====================

def ritenute(lotto_id):
    """Le ritenute dello 0,50% delle fatture definitive, per contratto applicativo (si svincolano
    alla fine del contratto, con la fattura di svincolo): {'contratti': [...], 'totale'}."""
    with db.get_db_context() as conn:
        lotto = ndb.lotto(lotto_id, conn)
        contratti = ndb._righe(conn, 'SELECT * FROM napoli_contratti WHERE lotto_id = ? ORDER BY valido_da, grado, id',
                               (lotto_id,))
        fatture = ndb._righe(conn, "SELECT * FROM napoli_fatture WHERE lotto_id = ? AND stato = 'definitiva' "
                                   "ORDER BY periodo_dal, grado, id", (lotto_id,))
    out, totale = [], 0
    for c in contratti:
        proprie = [f for f in fatture if f['contratto_id'] == c['id']]
        if not proprie:
            continue
        somma = sum(f['somma_righe_cent'] for f in proprie)
        ritenuta = sum(f['ritenuta_cent'] for f in proprie)
        totale += ritenuta
        out.append({
            'contratto_id': c['id'], 'numero': c['numero'], 'grado_testo': ndb.NOMI_GRADO[c.get('grado') or None],
            'accordo_quadro': c.get('accordo_quadro') or '', 'periodo_testo': ndb._periodo_it(c['valido_da'],
                                                                                              c['valido_a']),
            'finito': calc.data(c['valido_a']) < ndb._oggi(),
            'fatture': [{'id': f['id'], 'numero': f['numero'] or '', 'data_testo': calc.data_it(f['data'])
                         if f['data'] else '', 'grado_testo': NOMI_GRADO[f['grado']],
                         'periodo_testo': f'dal {calc.data_it(f["periodo_dal"])} al {calc.data_it(f["periodo_al"])}',
                         'somma': _euro(f['somma_righe_cent']), 'somma_cent': f['somma_righe_cent'],
                         'ritenuta': _euro(f['ritenuta_cent']), 'ritenuta_cent': f['ritenuta_cent']}
                        for f in proprie],
            'n': len(proprie), 'somma': _euro(somma), 'ritenuta': _euro(ritenuta), 'ritenuta_cent': ritenuta})
    return {'lotto': {'id': lotto['id'], 'nome': lotto['nome']}, 'contratti': out, 'totale': _euro(totale),
            'totale_cent': totale}


# ==================== chiusura del mese del lotto ====================

def da_rendere_definitive(conn, lotto_id, anno, mese):
    """Le fatture del mese con ore che non sono ancora definitive (§9: il mese si chiude con le
    fatture definitive, o confermando che per quei gradi non si fa la fattura adesso):
    ['contratto XI (grado inferiore), dal 08/06/2026 al 30/06/2026', ...]."""
    ctx = _Contesto(conn, lotto_id, anno, mese)
    out = []
    for c, grado, _periodo in ctx.chiavi():
        f = ctx.fatture.get((c['id'], grado))
        if f and f['stato'] == 'definitiva':
            continue
        vivo = _calcola(ctx, c, grado)
        if vivo['righe']:
            out.append(f'contratto {c["numero"]} ({ndb.NOMI_GRADO[grado]}), {vivo["periodo_testo"]}')
    return out

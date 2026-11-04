"""Calcoli della sezione Napoli (PROGETTO §5): solo funzioni pure.

Niente database, niente Flask e niente config di Roma: i valori arrivano come
argomenti (righe gia' lette, in forma di dict) e le regole predefinite da
config_napoli. Cosi' le stesse funzioni servono a griglia, foglio firma, import,
export e fattura, e si provano senza database (tests/test_napoli_calcoli.py).

Unita':
- ore delle presenze in MINUTI INTERI; a schermo "1:30 (1,50)";
- importi e tariffe in Decimal con arrotondamento commerciale (ROUND_HALF_UP)
  al centesimo; nel database in centesimi (in_centesimi);
- ore del coordinatore in centesimi di ora (71,55 h = 7155);
- date come datetime.date o testo 'AAAA-MM-GG', orari 'HH:MM'.

Dati in ingresso (valida_data, valida_orario, valida_fascia, valida_fasce,
valida_periodo, valida_mese): da usare nelle API prima di scrivere; un errore e' un
ValueError con un messaggio semplice da mostrare all'utente.

Esiti delle letture (leggi_ore_griglia, leggi_ore_foglio, leggi_cella_master):
un dict con 'esito' ('ore', 'vuoto', 'sigla', 'da_confermare', 'errore'),
'minuti', 'causale', 'sigla', 'trattamento', 'codice' (dell'errore), 'avvisi'
(codici) e 'alternative' (le letture possibili di un valore ambiguo).
"""
import datetime
import json
import re
from decimal import ROUND_CEILING, ROUND_HALF_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

import config_napoli

CENT = Decimal('0.01')
UNO = Decimal('1')
SESSANTA = Decimal('60')

GRADI = ('inferiore', 'superiore')
MESI = ('Gennaio', 'Febbraio', 'Marzo', 'Aprile', 'Maggio', 'Giugno', 'Luglio', 'Agosto', 'Settembre',
        'Ottobre', 'Novembre', 'Dicembre')

# Causali di un giorno (napoli_presenze.causale) e loro precedenza quando se ne
# applicano piu' d'una: calendario > evento/attivita' esterna > operatore > alunno.
PRECEDENZA_CAUSALI = {
    'calendario': 0,
    'evento': 1, 'attivita_esterna': 1,
    'operatore_ferie': 2, 'operatore_malattia': 2, 'operatore_permesso': 2, 'operatore_altro': 2,
    'alunno_assente': 3, 'alunno_parziale': 3,
}
CAUSALI = tuple(PRECEDENZA_CAUSALI)
# Trattamento delle ore non svolte (napoli_presenze.trattamento); 'banca' e' della fase 2.
TRATTAMENTI = ('meta', 'recupero', 'banca', 'scoperta', 'nessuno')

# Sigle dell'operatore assente: forma canonica (come nel master).
SIGLE = {'operatore_ferie': 'F', 'operatore_malattia': 'M', 'operatore_permesso': 'F perm'}
TIPO_SIGLA = {'operatore_ferie': 'ferie', 'operatore_malattia': 'malattia', 'operatore_permesso': 'permesso'}


# ==================== numeri, date e unita' ====================

def decimale(valore):
    """Decimal esatto da int, Decimal, testo ('1,5' o '1.5') o float (dalla sua forma
    piu' corta: 0.1 -> 0.1, non 0.1000000000000000055...)."""
    if isinstance(valore, bool):
        raise ValueError('valore non numerico')
    if isinstance(valore, Decimal):
        return valore
    if isinstance(valore, int):
        return Decimal(valore)
    if isinstance(valore, float):
        return Decimal(repr(valore))
    try:
        return Decimal(str(valore).strip().replace(',', '.'))
    except InvalidOperation:
        raise ValueError(f'valore non numerico: {valore!r}') from None


def arrotonda(valore, passo=CENT, modo=ROUND_HALF_UP):
    """Arrotondamento commerciale (per difetto sotto la meta', per eccesso dalla meta')."""
    return decimale(valore).quantize(passo, rounding=modo)


def in_centesimi(valore):
    """Euro (Decimal) -> centesimi interi, arrotondando al centesimo."""
    return int(arrotonda(valore) * 100)


def da_centesimi(cent):
    return (Decimal(int(cent)) / 100).quantize(CENT)


def numero_it(valore, decimali=2):
    """24743.72 -> '24.743,72'; 0.5 -> '0,50'."""
    q = arrotonda(valore, UNO.scaleb(-decimali))
    return f'{q:,.{decimali}f}'.replace(',', ' ').replace('.', ',').replace(' ', '.')


def data(valore):
    """datetime.date da una data, una data-ora o un testo 'AAAA-MM-GG'."""
    if isinstance(valore, datetime.datetime):
        return valore.date()
    if isinstance(valore, datetime.date):
        return valore
    return datetime.date.fromisoformat(str(valore)[:10])


def _data_o_none(valore):
    return None if valore in (None, '') else data(valore)


def data_it(valore):
    """'2026-06-12' -> '12/06/2026'."""
    return data(valore).strftime('%d/%m/%Y')


def fine_mese(anno, mese):
    return datetime.date(anno + mese // 12, mese % 12 + 1, 1) - datetime.timedelta(days=1)


def minuti(hhmm):
    """'08:30' -> 510; accetta anche '8:30' e '24:00'."""
    m = re.fullmatch(r'\s*(\d{1,2}):([0-5]\d)\s*', str(hhmm or ''))
    if not m or int(m.group(1)) * 60 + int(m.group(2)) > 24 * 60:
        raise ValueError(f'orario non valido: {hhmm!r} (atteso HH:MM)')
    return int(m.group(1)) * 60 + int(m.group(2))


def _estremi(fascia):
    if isinstance(fascia, dict):
        return fascia['ora_inizio'], fascia['ora_fine']
    inizio, fine = fascia
    return inizio, fine


def fasce_in_minuti(fasce):
    """Fasce [('08:00', '10:00'), ...] (o righe con ora_inizio/ora_fine) -> coppie di
    minuti in ordine. Errore se una fascia finisce prima di iniziare o se due fasce
    si sovrappongono (contarle due volte darebbe ore in piu')."""
    out = sorted((minuti(i), minuti(f)) for i, f in (_estremi(x) for x in (fasce or ())))
    for i, f in out:
        if f <= i:
            raise ValueError('una fascia finisce prima di iniziare')
    for (_, f1), (i2, _) in zip(out, out[1:]):
        if i2 < f1:
            raise ValueError('fasce sovrapposte nello stesso giorno')
    return out


def durata(fasce):
    """Somma (fine - inizio) delle fasce, in minuti."""
    return sum(f - i for i, f in fasce_in_minuti(fasce))


def ore_decimali(min_):
    """Minuti -> ore con due decimali (ROUND_HALF_UP): 90 -> 1.50, 7291 -> 121.52."""
    return arrotonda(Decimal(int(min_)) / SESSANTA)


def hhmm(min_):
    """90 -> '1:30'; -30 -> '-0:30'."""
    segno = '-' if min_ < 0 else ''
    h, m = divmod(abs(int(min_)), 60)
    return f'{segno}{h}:{m:02d}'


def ore_due_forme(min_):
    """Come si mostrano le ore a schermo: '1:30 (1,50)'."""
    return f'{hhmm(min_)} ({numero_it(ore_decimali(min_))})'


def minuti_da_ore(ore):
    """Ore decimali -> (minuti interi arrotondati, True se erano gia' minuti interi)."""
    esatti = decimale(ore) * SESSANTA
    interi = esatti.quantize(UNO, rounding=ROUND_HALF_UP)
    return int(interi), interi == esatti


# ==================== controllo dei dati in ingresso ====================
# I CHECK dello schema guardano solo la forma ('AAAA-MM-GG', 'HH:MM') e accettano
# anche date e orari che non esistono (2025-19-39, 29:59). Queste funzioni, da usare
# in ogni API di Napoli prima di scrivere, li rifiutano con un messaggio semplice da
# mostrare all'utente (ValueError) e restituiscono il valore nella forma del database.

ANNI_AMMESSI = (2000, 2099)
_RX_DATA_ISO = re.compile(r'(\d{4})-(\d{1,2})-(\d{1,2})')
_RX_DATA_IT = re.compile(r'(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})')
_RX_ORARIO = re.compile(r'(\d{1,2})[:.](\d{2})')


def valida_data(valore, nome='La data'):
    """'AAAA-MM-GG' da 'AAAA-MM-GG', 'GG/MM/AAAA' (anche con il punto o il trattino),
    una data o una data-ora. Errore se manca, se non esiste (31/02, 2025-19-39) o se
    l'anno e' fuori da ANNI_AMMESSI (un anno scritto male, come 0202)."""
    if isinstance(valore, datetime.datetime):
        valore = valore.date()
    if isinstance(valore, datetime.date):
        giorno, scritto = valore, valore.isoformat()
    else:
        scritto = '' if valore is None else str(valore).strip()
        if not scritto:
            raise ValueError(f'{nome} manca.')
        iso, italiana = _RX_DATA_ISO.fullmatch(scritto), _RX_DATA_IT.fullmatch(scritto)
        if iso:
            a, m, g = (int(x) for x in iso.groups())
        elif italiana:
            g, m, a = (int(x) for x in italiana.groups())
        else:
            raise ValueError(f'{nome} "{scritto}" non e\' scritta bene: scrivere giorno, mese e anno, '
                             'per esempio 08/06/2026.')
        try:
            giorno = datetime.date(a, m, g)
        except ValueError:
            raise ValueError(f'{nome} "{scritto}" non esiste nel calendario.') from None
    if not ANNI_AMMESSI[0] <= giorno.year <= ANNI_AMMESSI[1]:
        raise ValueError(f'{nome} "{scritto}" ha un anno fuori da quelli del servizio.')
    return giorno.isoformat()


def valida_orario(valore, nome="L'orario"):
    """'HH:MM' (con lo zero davanti) da 'H:MM', 'HH:MM', 'HH.MM' o un orario; da 00:00 a
    23:59. Errore se manca o se l'orario non esiste (29:59, 10:75)."""
    if isinstance(valore, datetime.time):
        return f'{valore.hour:02d}:{valore.minute:02d}'
    scritto = '' if valore is None else str(valore).strip()
    if not scritto:
        raise ValueError(f'{nome} manca.')
    m = _RX_ORARIO.fullmatch(scritto)
    if not m:
        raise ValueError(f'{nome} "{scritto}" non e\' scritto bene: scrivere ore e minuti, per esempio 08:30.')
    ore, min_ = int(m.group(1)), int(m.group(2))
    if ore > 23 or min_ > 59:
        raise ValueError(f'{nome} "{scritto}" non esiste: le ore vanno da 00:00 a 23:59.')
    return f'{ore:02d}:{min_:02d}'


def valida_fascia(inizio, fine):
    """(inizio, fine) in 'HH:MM'; errore se la fine non viene dopo l'inizio."""
    inizio, fine = valida_orario(inizio, "L'orario di inizio"), valida_orario(fine, "L'orario di fine")
    if fine <= inizio:
        raise ValueError(f"L'orario di fine ({fine}) deve venire dopo quello di inizio ({inizio}).")
    return inizio, fine


def valida_fasce(fasce):
    """Fasce di un giorno [(inizio, fine)] (o righe con ora_inizio/ora_fine) -> fasce in
    'HH:MM' in ordine; errore se una fascia non va o se due fasce si sovrappongono."""
    out = sorted(valida_fascia(*_estremi(f)) for f in (fasce or ()))
    for (i1, f1), (i2, f2) in zip(out, out[1:]):
        if i2 < f1:
            raise ValueError(f'Due fasce dello stesso giorno si sovrappongono ({i1}-{f1} e {i2}-{f2}).')
    return out


def valida_periodo(dal, al=None, fine_obbligatoria=False, nomi=('La data di inizio', 'La data di fine')):
    """(dal, al) in 'AAAA-MM-GG'; al vuoto = senza fine (None), se ammesso. Errore se la
    fine viene prima dell'inizio."""
    dal = valida_data(dal, nomi[0])
    if al in (None, '') and not fine_obbligatoria:
        return dal, None
    al = valida_data(al, nomi[1])
    if al < dal:
        raise ValueError(f'{nomi[1]} ({data_it(al)}) viene prima di quella di inizio ({data_it(dal)}).')
    return dal, al


def valida_mese(anno, mese):
    """(anno, mese) come interi (anche scritti come testo, '10'); errore se non sono numeri
    interi, se il mese non e' da 1 a 12 o se l'anno non e' ammesso."""
    def intero(x):
        if isinstance(x, int) and not isinstance(x, bool):
            return x
        if isinstance(x, str) and re.fullmatch(r'\s*\d{1,4}\s*', x):
            return int(x)
        raise ValueError('Il mese e l\'anno devono essere numeri interi.')
    anno, mese = intero(anno), intero(mese)
    if not 1 <= mese <= 12:
        raise ValueError('Il mese deve essere un numero da 1 a 12.')
    if not ANNI_AMMESSI[0] <= anno <= ANNI_AMMESSI[1]:
        raise ValueError(f"L'anno {anno} e' fuori da quelli del servizio.")
    return anno, mese


def quota_minuti(min_, quota, arrotondamento='eccesso'):
    """Parte dei minuti (es. meta'), al minuto: con 'eccesso' il mezzo minuto va su
    (52,5 -> 53), con 'difetto' va giu' (Q12)."""
    modo = {'eccesso': ROUND_HALF_UP, 'difetto': ROUND_HALF_DOWN}[arrotondamento]
    return int((Decimal(int(min_)) * decimale(quota)).quantize(UNO, rounding=modo))


# ==================== regole con data (§5.6) ====================

def valore_regola(chiave, valore):
    """Valore di una regola nel suo tipo (config_napoli.REGOLE_PREDEFINITE).
    `valore` puo' essere il JSON di napoli_regole.valore o il valore gia' letto.
    Errore (ValueError) se la chiave non esiste o il valore non e' ammesso."""
    if chiave not in config_napoli.REGOLE_PREDEFINITE:
        raise ValueError(f'regola sconosciuta: {chiave}')
    definizione = config_napoli.REGOLE_PREDEFINITE[chiave]
    tipo = definizione['tipo']
    if isinstance(valore, str):
        try:
            letto = json.loads(valore, parse_float=Decimal)
        except ValueError:
            if tipo not in ('testo', 'scelta'):
                raise ValueError(f'{chiave}: valore non leggibile') from None
            letto = valore              # testo semplice, non JSON
        valore = valore if tipo == 'testo' and not isinstance(letto, str) else letto
    if tipo in ('decimale', 'intero'):
        v = decimale(valore)
        if not v.is_finite() or v < 0 or (tipo == 'intero' and v != v.to_integral_value()):
            raise ValueError(f'{chiave}: serve un numero {"intero " if tipo == "intero" else ""}non negativo')
        return int(v) if tipo == 'intero' else v
    if tipo == 'booleano':
        if valore in (True, False, 0, 1):
            return bool(valore)
        raise ValueError(f'{chiave}: serve vero o falso')
    if tipo == 'testo':
        if not isinstance(valore, str):
            raise ValueError(f'{chiave}: serve un testo')
        return valore
    if tipo == 'scelta':
        if valore not in definizione['scelte']:
            raise ValueError(f'{chiave}: valori ammessi {definizione["scelte"]}')
        return valore
    if not isinstance(valore, (list, tuple)):
        raise ValueError(f'{chiave}: serve un elenco')
    limiti = {'giorni': range(0, 7), 'mesi': range(1, 13)}.get(tipo)
    if limiti is not None:
        if not all(isinstance(x, int) and not isinstance(x, bool) and x in limiti for x in valore):
            raise ValueError(f'{chiave}: valori fuori intervallo')
        return tuple(sorted(set(valore)))
    return tuple(str(x) for x in valore)


def _valida_nella_data(riga, giorno):
    dal, al = _data_o_none(riga.get('valido_da')), _data_o_none(riga.get('valido_a'))
    return (dal is None or dal <= giorno) and (al is None or giorno <= al)


def _id(valore):
    """Id di una riga come intero (3 e '3' sono lo stesso lotto); None se vuoto."""
    return None if valore in (None, '') else int(valore)


def regola_dettaglio(chiave, giorno, righe=(), lotto_id=None):
    """Regola valida in una data: prima la riga del lotto, poi quella di tutti i lotti
    (lotto_id vuoto), sempre la piu' recente con valido_da <= data <= valido_a;
    altrimenti il predefinito di config_napoli. Ritorna {'valore', 'origine'
    ('lotto' | 'tutti' | 'predefinita'), 'valido_da', 'valido_a', 'fuori_validita'}:
    fuori_validita = predefinito usato fuori dalle sue date (da segnalare).
    lotto_id puo' arrivare anche come testo (parametro di una richiesta)."""
    if chiave not in config_napoli.REGOLE_PREDEFINITE:
        raise ValueError(f'regola sconosciuta: {chiave}')
    giorno, lotto_id = data(giorno), _id(lotto_id)
    gruppi = (('lotto', lotto_id), ('tutti', None)) if lotto_id is not None else (('tutti', None),)
    for origine, lotto in gruppi:
        valide = [r for r in righe if r.get('chiave') == chiave and _id(r.get('lotto_id')) == lotto
                  and _valida_nella_data(r, giorno)]
        if valide:
            r = max(valide, key=lambda x: data(x['valido_da']))
            return {'valore': valore_regola(chiave, r['valore']), 'origine': origine, 'valido_da': r['valido_da'],
                    'valido_a': r.get('valido_a'), 'fuori_validita': False}
    p = config_napoli.REGOLE_PREDEFINITE[chiave]
    return {'valore': p['valore'], 'origine': 'predefinita', 'valido_da': p['dal'], 'valido_a': p['al'],
            'fuori_validita': not _valida_nella_data({'valido_da': p['dal'], 'valido_a': p['al']}, giorno)}


def regola(chiave, giorno, righe=(), lotto_id=None):
    """Solo il valore della regola valida in una data (vedi regola_dettaglio)."""
    return regola_dettaglio(chiave, giorno, righe, lotto_id)['valore']


def regole_alla_data(giorno, righe=(), lotto_id=None):
    """Tutte le regole valide in una data: {chiave: valore}."""
    return {k: regola(k, giorno, righe, lotto_id) for k in config_napoli.REGOLE_PREDEFINITE}


def _r(regole, chiave):
    """Valore da un dict di regole (regole_alla_data), con il predefinito se manca."""
    if regole and chiave in regole:
        return regole[chiave]
    return config_napoli.REGOLE_PREDEFINITE[chiave]['valore']


# ==================== lettura delle ore (§5.1) ====================

def _lettura(esito, testo, minuti_=None, **altro):
    out = {'esito': esito, 'minuti': minuti_, 'causale': None, 'sigla': None, 'trattamento': None,
           'codice': None, 'avvisi': [], 'alternative': [], 'testo': testo}
    out.update(altro)
    return out


def chiave_sigla(testo):
    return re.sub(r'[\s().]+', '', str(testo).upper())


def causale_sigla(testo):
    """Sigla dell'operatore assente -> causale, o None. Varianti viste: 'f', 'F ',
    'Fperm', 'F perm', 'F (PERM)', 'F (perm)', 'F perm)', 'F PERM', 'P'."""
    k = chiave_sigla(testo)
    if k in ('F', 'FERIE'):
        return 'operatore_ferie'
    if k in ('M', 'MAL', 'MALATTIA'):
        return 'operatore_malattia'
    if k in ('P', 'PERM', 'PERMESSO') or (k.startswith('F') and 'PERM' in k):
        return 'operatore_permesso'
    return None


_RX_HHMM = re.compile(r'(\d{1,3}):([0-5]\d)')
_RX_NUMERO = re.compile(r'(\d{1,3})?(?:[.,](\d+))?')


def _numero(testo):
    """'1,30' -> (1, '30'); '2' -> (2, None); altrimenti None."""
    m = _RX_NUMERO.fullmatch(testo)
    if not m or (m.group(1) is None and m.group(2) is None):
        return None
    return int(m.group(1) or 0), m.group(2)


def _alternative(ore, cifre):
    """Le letture di 'ore,cifre': ore e minuti, se le cifre possono essere minuti ('1,30'
    e anche '1,3', il tipico "1,30" scritto senza lo zero: 1 h 30), e ore decimali
    (arrotondate al minuto)."""
    alt = []
    if len(cifre) <= 2:
        minuti_scritti = int(cifre) * 10 if len(cifre) == 1 else int(cifre)
        if minuti_scritti < 60:
            alt.append({'lettura': 'ore_e_minuti', 'minuti': ore * 60 + minuti_scritti,
                        'testo': f'{ore} h {minuti_scritti} min'})
    m, esatto = minuti_da_ore(Decimal(f'{ore}.{cifre}'))
    alt.append({'lettura': 'decimale', 'minuti': m, 'testo': f'{ore},{cifre} ore decimali ({hhmm(m)})',
                'arrotondato': not esatto})
    return alt


def _da_confermare(testo, ore, cifre, conferma):
    """Valore con due letture possibili: si usa quella confermata, altrimenti si chiede.
    Con una lettura sola ('1,7', '1,333': le cifre non possono essere minuti) non c'e'
    niente da chiedere: vale come ore decimali, con l'avviso."""
    alt = _alternative(ore, cifre)
    scelta = alt[0] if len(alt) == 1 else next((a for a in alt if a['lettura'] == conferma), None)
    if scelta:
        avvisi = ['letto_come_' + scelta['lettura']]
        if scelta.get('arrotondato'):
            avvisi.append('ore_arrotondate_al_minuto')
        return _lettura('ore', testo, scelta['minuti'], avvisi=avvisi)
    domanda = ' oppure '.join(a['testo'] for a in alt) + '?'
    return _lettura('da_confermare', testo, codice='ore_ambigue', alternative=alt, domanda=domanda)


def leggi_ore_griglia(testo, conferma=None, minuti_programmati=None, regole=None):
    """Cella della griglia presenze (convenzione dell'Excel: ore decimali).

    '2', '1,5', '1.5', '0,75' -> ore decimali (120, 90, 90, 45); '1:30' -> 90;
    decimali che non sono un multiplo di 0,25 ('1,30', '1,20', '1,3'...) -> da confermare
    ("1 h 30 min oppure 1,30 ore decimali?"): si rilegge con conferma='ore_e_minuti'
    o 'decimale'; se le cifre non possono essere minuti ('1,7') vale la lettura decimale,
    con l'avviso letto_come_decimale. F/M/P (e varianti) -> operatore assente, 0.
    A -> alunno assente: meta' del programmato (servono i minuti programmati).
    Vuoto -> cancella la cella."""
    t = '' if testo is None else str(testo).strip()
    if t == '':
        return _lettura('vuoto', t)
    m = _RX_HHMM.fullmatch(t)
    if m:
        return _lettura('ore', t, int(m.group(1)) * 60 + int(m.group(2)))
    n = _numero(t)
    if n:
        ore, cifre = n
        if cifre is None or Decimal(f'0.{cifre}') * 4 % 1 == 0:
            return _lettura('ore', t, minuti_da_ore(Decimal(f'{ore}.{cifre or 0}'))[0])
        return _da_confermare(t, ore, cifre, conferma)
    if chiave_sigla(t) in ('A', 'ASSENTE'):
        quota = _r(regole, 'quota_assenza_alunno')
        tratt = trattamento_predefinito(quota, _r(regole, 'trattamento_alunno_predefinito'))
        if minuti_programmati is None:
            return _lettura('sigla', t, None, causale='alunno_assente', trattamento=tratt, sigla='A',
                            codice='servono_minuti_programmati')
        m_ = quota_minuti(minuti_programmati, quota, _r(regole, 'arrotondamento_mezzo_minuto')) \
            if tratt == 'meta' else 0
        return _lettura('sigla', t, m_, causale='alunno_assente', trattamento=tratt, sigla='A')
    causale = causale_sigla(t)
    if causale:
        return _lettura('sigla', t, 0, causale=causale, sigla=SIGLE[causale])
    return _lettura('errore', t, codice='sigla_sconosciuta')


def leggi_ore_foglio(testo, conferma=None):
    """"Totale scritto sul foglio" (convenzione del foglio firma): ',15' ',30' ',45'
    -> ore e minuti; ',25' ',5' ',50' ',75' -> ore decimali; '30' -> 30 ore;
    '30:30' -> 30 h 30 min; altri decimali -> da confermare come in leggi_ore_griglia
    ('30,3': 30 h 30 min oppure 30,3 ore decimali?)."""
    t = '' if testo is None else str(testo).strip()
    if t == '':
        return _lettura('vuoto', t)
    m = _RX_HHMM.fullmatch(t)
    if m:
        return _lettura('ore', t, int(m.group(1)) * 60 + int(m.group(2)))
    n = _numero(t)
    if not n:
        return _lettura('errore', t, codice='totale_non_riconosciuto')
    ore, cifre = n
    if cifre is None or int(cifre) == 0:
        return _lettura('ore', t, ore * 60)
    if cifre in ('15', '30', '45'):
        return _lettura('ore', t, ore * 60 + int(cifre), avvisi=['letto_come_ore_e_minuti'])
    if cifre in ('25', '5', '50', '75'):
        return _lettura('ore', t, minuti_da_ore(Decimal(f'{ore}.{cifre}'))[0], avvisi=['letto_come_decimale'])
    return _da_confermare(t, ore, cifre, conferma)


def leggi_cella_master(valore):
    """Cella giorno del foglio "master" del Comune (ore decimali o sigle dell'operatore).

    Numero -> ore decimali; numero scritto come testo -> avviso numero_come_testo;
    valori che non sono minuti interi -> arrotondati al minuto, avviso
    ore_arrotondate_al_minuto; valori che non sono un multiplo di 0,25 -> avviso
    ore_non_multiple_di_un_quarto (la lettura resta decimale); orario di Excel
    (1:30 come ora, o come durata [h]:mm, che openpyxl legge come timedelta) -> avviso
    cella_in_formato_orario. Sigle F, M, F perm (varianti -> avviso
    sigla_scritta_in_variante). Vuoto = nessuna attivita'."""
    if valore is None or (isinstance(valore, str) and valore.strip() == ''):
        return _lettura('vuoto', valore, 0)
    if isinstance(valore, datetime.time):
        return _lettura('ore', valore, valore.hour * 60 + valore.minute, avvisi=['cella_in_formato_orario'])
    if isinstance(valore, datetime.timedelta):
        # al secondo (Excel salva le durate come frazioni di giorno), poi al minuto
        secondi = (Decimal(valore.days * 86400 + valore.seconds) + Decimal(valore.microseconds) / 10 ** 6).quantize(
            UNO, rounding=ROUND_HALF_UP)
        if secondi < 0:
            return _lettura('errore', valore, codice='ore_negative')
        m_ = int((secondi / SESSANTA).quantize(UNO, rounding=ROUND_HALF_UP))
        avvisi = ['cella_in_formato_orario'] + ([] if secondi % 60 == 0 else ['ore_arrotondate_al_minuto'])
        return _lettura('ore', valore, m_, avvisi=avvisi)
    if isinstance(valore, (bool, datetime.date)):
        return _lettura('errore', valore, codice='cella_non_riconosciuta')
    avvisi = []
    if isinstance(valore, (int, float, Decimal)):
        ore = decimale(valore)
    else:
        s = str(valore).strip()
        m = _RX_HHMM.fullmatch(s)
        if m:
            return _lettura('ore', valore, int(m.group(1)) * 60 + int(m.group(2)), avvisi=['numero_come_testo'])
        if re.fullmatch(r'-?\d+(?:[.,]\d+)?', s):
            ore = decimale(s)
            avvisi.append('numero_come_testo')
        else:
            causale = causale_sigla(s)
            if causale:
                return _lettura('sigla', valore, 0, causale=causale, sigla=SIGLE[causale],
                                avvisi=[] if s == SIGLE[causale] else ['sigla_scritta_in_variante'])
            return _lettura('errore', valore, codice='sigla_sconosciuta')
    if not ore.is_finite():                 # NaN o infinito (float o Decimal)
        return _lettura('errore', valore, codice='cella_non_riconosciuta')
    if ore < 0:
        return _lettura('errore', valore, codice='ore_negative')
    m_, esatto = minuti_da_ore(ore)
    if not esatto:
        avvisi.append('ore_arrotondate_al_minuto')
    if ore * 4 % 1 != 0:
        avvisi.append('ore_non_multiple_di_un_quarto')
    return _lettura('ore', valore, m_, avvisi=avvisi)


# ==================== ore riconosciute di un giorno (§5.2) ====================

def causale_prevalente(causali):
    """Causale che vale fra quelle del giorno: calendario > evento/attivita' esterna >
    operatore > alunno. Accetta None, una causale o un elenco."""
    if not causali:
        return None
    elenco = [causali] if isinstance(causali, str) else [c for c in causali if c]
    for c in elenco:
        if c not in PRECEDENZA_CAUSALI:
            raise ValueError(f'causale sconosciuta: {c}')
    return min(elenco, key=PRECEDENZA_CAUSALI.get) if elenco else None


def trattamento_predefinito(quota, predefinito=None):
    """Trattamento dell'assenza dell'alunno se non e' indicato: quello della regola
    trattamento_alunno_predefinito o, se vuota, 'meta' con quota > 0 (contratto
    attuale) e 'banca' con quota 0 (CSA, fase 2)."""
    if predefinito:
        return predefinito
    return 'meta' if decimale(quota) > 0 else 'banca'


def _formula(p, s, causale, trattamento, minuti_extra, regole):
    """Minuti riconosciuti secondo la tabella del §5.2 e trattamento applicato.
    s None = svolto non noto: vale 0 se c'e' una causale, altrimenti non si calcola."""
    if causale is None:
        return s, None
    s0 = s or 0
    if causale == 'calendario':
        return 0, trattamento
    if minuti_extra:
        return s0, trattamento
    if not causale.startswith('alunno_'):
        return s0, trattamento
    quota_alunno = _r(regole, 'quota_assenza_alunno')
    tratt = trattamento or trattamento_predefinito(quota_alunno, _r(regole, 'trattamento_alunno_predefinito'))
    if tratt != 'meta':
        return s0, tratt
    arrot = _r(regole, 'arrotondamento_mezzo_minuto')
    if causale == 'alunno_assente':
        return quota_minuti(p, quota_alunno, arrot), tratt
    return s0 + quota_minuti(max(0, p - s0), _r(regole, 'quota_assenza_parziale'), arrot), tratt


def esito_giorno(fasce_p=(), fasce_e=(), causale=None, trattamento=None, minuti_programmati=None,
                 minuti_svolti=None, minuti_extra=0, stato='registrato', calcolo='auto', minuti_scritti=None,
                 regole=None):
    """Ore riconosciute (fatturabili) di un giorno di una coppia.

    P = durata delle fasce programmate (o minuti_programmati); S = durata delle fasce
    effettive (o minuti_svolti); regole = regole_alla_data della data (quota
    dell'assenza intera e parziale, arrotondamento del mezzo minuto).
    - stato 'programmato' (foglio non registrato): 0, avviso giorno_non_registrato;
    - calcolo 'manuale' (numero scritto o importato): minuti_scritti, avviso
      diverso_dalla_formula se la formula si puo' calcolare e da' altro;
    - nessuna causale: S; calendario: 0; evento, attivita' esterna, operatore_*: S;
    - alunno_assente con trattamento 'meta': quota x P; alunno_parziale con 'meta':
      S + quota_parziale x (P - S); alunno_* con 'recupero' o 'banca': S;
    - giorno con recupero (minuti_extra > 0): S, compresi i minuti di recupero.
    Ritorna {'minuti', 'causale', 'trattamento', 'formula', 'programmati', 'svolti', 'avvisi'}."""
    if trattamento is not None and trattamento not in TRATTAMENTI:
        raise ValueError(f'trattamento sconosciuto: {trattamento}')
    if stato not in ('programmato', 'registrato') or calcolo not in ('auto', 'manuale'):
        raise ValueError('stato o calcolo non validi')
    p = durata(fasce_p) if fasce_p else int(minuti_programmati or 0)
    s = durata(fasce_e) if fasce_e else (None if minuti_svolti is None else int(minuti_svolti))
    c = causale_prevalente(causale)
    out = {'minuti': 0, 'causale': c, 'trattamento': trattamento, 'formula': None, 'programmati': p,
           'svolti': s, 'avvisi': []}
    if stato == 'programmato':
        out['avvisi'].append('giorno_non_registrato')
        return out
    formula, out['trattamento'] = _formula(p, s, c, trattamento, int(minuti_extra or 0), regole)
    out['formula'] = formula
    if c == 'alunno_assente' and out['trattamento'] == 'meta' and s:
        out['avvisi'].append('ore_svolte_con_alunno_assente')
    if calcolo == 'manuale':
        if minuti_scritti is None:
            raise ValueError('calcolo manuale senza minuti scritti')
        out['minuti'] = int(minuti_scritti)
        if formula is not None and formula != out['minuti']:
            out['avvisi'].append('diverso_dalla_formula')
    elif formula is None:
        out['avvisi'].append('svolto_mancante')
    else:
        out['minuti'] = formula
    if c == 'calendario' and (s or out['minuti']):
        out['avvisi'].append('ore_in_giorno_di_chiusura')
    return out


def minuti_riconosciuti(**campi):
    """Solo i minuti di esito_giorno (stessi argomenti)."""
    return esito_giorno(**campi)['minuti']


# ==================== controlli del giorno e del foglio (§5.5) ====================

def controlla_minuti_giorno(min_, regole=None):
    """Oltre 12 ore in un giorno: bloccante; oltre 5: avviso (limiti dalle regole)."""
    if min_ > _r(regole, 'max_minuti_giorno_blocco'):
        return [{'livello': 'bloccante', 'codice': 'ore_giorno_oltre_12'}]
    if min_ > _r(regole, 'max_minuti_giorno_avviso'):
        return [{'livello': 'avviso', 'codice': 'ore_giorno_oltre_5'}]
    return []


def confronta_totale_scritto(calcolati, scritti):
    """Il totale scritto a mano sul foglio (in minuti) e' diverso da quello calcolato?
    Vale sempre il calcolato (Q11): l'avviso dice di correggere o annotare il foglio."""
    if scritti is None or int(scritti) == int(calcolati):
        return None
    return {'codice': 'totale_scritto_diverso', 'calcolati': int(calcolati), 'scritti': int(scritti),
            'differenza': int(calcolati) - int(scritti)}


# ==================== settimane e PEI (§5.3) ====================

def giorni_mese(anno, mese, giorni_servizio=None):
    """Giorni di servizio del mese (predefinito: da lunedi' a sabato)."""
    servizio = set(_r(None, 'giorni_servizio') if giorni_servizio is None else giorni_servizio)
    d, out = datetime.date(anno, mese, 1), []
    while d.month == mese:
        if d.weekday() in servizio:
            out.append(d)
        d += datetime.timedelta(days=1)
    return out


def _chiave_settimana(d):
    iso = d.isocalendar()
    return iso[0], iso[1]


def settimane_mese(anno, mese, giorni_servizio=None):
    """Settimane da lunedi' a sabato tagliate al mese, come le colonne VERIFICA del
    master: [[date della 1a settimana], [date della 2a], ...]."""
    out, chiavi = [], []
    for d in giorni_mese(anno, mese, giorni_servizio):
        k = _chiave_settimana(d)
        if not chiavi or chiavi[-1] != k:
            chiavi.append(k)
            out.append([])
        out[-1].append(d)
    return out


def colonne_mese(anno, mese, giorni_servizio=None):
    """Colonne del master: ('giorno', data) e ('verifica', n) dopo ogni settimana."""
    out = []
    for n, sett in enumerate(settimane_mese(anno, mese, giorni_servizio), start=1):
        out += [('giorno', d) for d in sett] + [('verifica', n)]
    return out


def minuti_pei(ore_settimanali):
    return minuti_da_ore(ore_settimanali)[0]


def tetto_settimanale(ore_pei, coeff=None, modo=None):
    """Tetto settimanale in ore intere: PEI x 1,2 arrotondato all'ora, alla piu' vicina
    ('vicino', il mezzo va su) o per eccesso ('eccesso'). PEI 7 -> 8,4 -> 8 o 9."""
    coeff = _r(None, 'tetto_coeff') if coeff is None else coeff
    modo = _r(None, 'tetto_arrotondamento') if modo is None else modo
    x = decimale(ore_pei) * decimale(coeff)
    return int(x.quantize(UNO, rounding={'vicino': ROUND_HALF_UP, 'eccesso': ROUND_CEILING}[modo]))


def pei_della_settimana(pei, giorni):
    """Ore PEI valide nella settimana: un numero, oppure periodi {'ore_settimanali',
    'valido_da', 'valido_a'} (napoli_pei). Se il PEI cambia dentro la settimana vale
    il piu' alto (sono solo avvisi: meglio non segnalare a torto). None se manca."""
    if pei is None or isinstance(pei, (int, float, Decimal, str)):
        return None if pei in (None, '') else decimale(pei)
    validi = [decimale(x['ore_settimanali']) for x in pei if any(_valida_nella_data(x, d) for d in giorni)]
    return max(validi) if validi else None


def verifica_settimane(minuti_giorni, anno, mese, pei, regole=None):
    """Somme settimanali di un alunno per una figura (titolari piu' sostituti) contro il
    PEI. minuti_giorni: {data: minuti} o coppie (data, minuti), solo date del mese.
    Per settimana: {'settimana', 'dal', 'al', 'giorni', 'minuti', 'pei_minuti',
    'tetto_minuti', 'codice', 'colore'}: oltre il PEI 'settimana_oltre_pei' (giallo),
    oltre il tetto 'settimana_oltre_pei_piu_20' (rosso). 'settimana' e' il numero della
    colonna VERIFICA (colonne_mese).
    Come la VERIFICA del master (=SOMMA dei giorni da lunedi' a sabato della settimana),
    la somma conta solo i giorni di servizio: le ore di un giorno fuori servizio (una
    domenica, a inizio o a meta' mese) non hanno una colonna nel master e non entrano
    in nessuna settimana; ognuno di questi giorni e' una voce a parte, con settimana
    None e codice 'ore_in_giorno_non_di_servizio', da correggere o spiegare."""
    coppie = minuti_giorni.items() if isinstance(minuti_giorni, dict) else minuti_giorni
    servizio = _r(regole, 'giorni_servizio')
    somme, fuori_servizio = {}, {}
    for giorno, m in coppie:
        giorno = data(giorno)
        if (giorno.year, giorno.month) != (anno, mese):
            raise ValueError(f'{giorno} non e\' nel mese {mese:02d}/{anno}')
        if giorno.weekday() in servizio:
            k = _chiave_settimana(giorno)
            somme[k] = somme.get(k, 0) + int(m or 0)
        elif int(m or 0) > 0:
            fuori_servizio[giorno] = fuori_servizio.get(giorno, 0) + int(m)
    out = [{'settimana': None, 'dal': d, 'al': d, 'giorni': [], 'minuti': m, 'pei_minuti': None,
            'tetto_minuti': None, 'codice': 'ore_in_giorno_non_di_servizio', 'colore': None}
           for d, m in fuori_servizio.items()]
    for n, lavorativi in enumerate(settimane_mese(anno, mese, servizio), start=1):
        k = _chiave_settimana(lavorativi[0])
        ore = pei_della_settimana(pei, lavorativi)
        voce = {'settimana': n, 'dal': lavorativi[0], 'al': lavorativi[-1], 'giorni': lavorativi,
                'minuti': somme.get(k, 0), 'pei_minuti': None, 'tetto_minuti': None, 'codice': None, 'colore': None}
        if ore is not None:
            voce['pei_minuti'] = minuti_pei(ore)
            voce['tetto_minuti'] = 60 * tetto_settimanale(ore, _r(regole, 'tetto_coeff'),
                                                          _r(regole, 'tetto_arrotondamento'))
            if voce['minuti'] > voce['tetto_minuti']:
                voce['codice'], voce['colore'] = 'settimana_oltre_pei_piu_20', 'rosso'
            elif voce['minuti'] > voce['pei_minuti']:
                voce['codice'], voce['colore'] = 'settimana_oltre_pei', 'giallo'
        out.append(voce)
    return sorted(out, key=lambda v: v['dal'])


def confronta_programmazione(minuti_settimana, ore_attese):
    """Avviso della Programmazione: ore programmate in una settimana della coppia
    diverse dal PEI (o dalla quota della coppia)."""
    attesi = minuti_pei(ore_attese)
    if int(minuti_settimana) == attesi:
        return None
    return {'codice': 'programmato_diverso_dal_pei', 'programmati': int(minuti_settimana), 'attesi': attesi,
            'differenza': int(minuti_settimana) - attesi}


# ==================== fattura (§5.4) ====================

def periodo_fattura(anno, mese, valido_da, valido_a):
    """Periodo di competenza: il mese tagliato alle date del contratto applicativo
    (il contratto XI dall'08/06 -> dal 08 al 30 giugno). None se non si toccano."""
    dal = max(datetime.date(anno, mese, 1), data(valido_da))
    al = fine_mese(anno, mese) if valido_a in (None, '') else min(fine_mese(anno, mese), data(valido_a))
    return (dal, al) if dal <= al else None


def tariffa_alla_data(tariffe, figura, giorno, livello=None):
    """Tariffa del lotto (righe di napoli_tariffe) per la figura valida nella data: quella
    del livello dell'operatore, altrimenti quella senza livello; None se non c'e'.
    Se due righe dello stesso livello valgono nella stessa data (tariffe sovrapposte, che
    le Impostazioni rifiutano: tariffe_sovrapposte) vale quella che inizia piu' tardi."""
    giorno = data(giorno)
    valide = [t for t in tariffe if t['figura'] == figura and _valida_nella_data(t, giorno)]
    for scelte in ([t for t in valide if livello and t.get('livello_ccnl') == livello],
                   [t for t in valide if not t.get('livello_ccnl')]):
        if scelte:
            return max(scelte, key=lambda t: data(t['valido_da']))
    return None


def grado_fattura(valore):
    """Grado per la fattura ('inferiore' o 'superiore'), o None se e' da decidere: vuoto,
    'misto' (scuola mista con l'alunno senza grado, §4.2) o un valore sconosciuto."""
    g = str(valore or '').strip().lower()
    return g if g in GRADI else None


def _giorni(dal, al):
    return [dal + datetime.timedelta(days=i) for i in range((al - dal).days + 1)]


def periodi_sovrapposti(righe, stessa_chiave=None):
    """Coppie (a, b) di righe con validita' (valido_da; valido_a vuoto = senza fine) che
    hanno almeno un giorno in comune, fra quelle con stessa_chiave(a, b) vera (tutte se
    None). Serve alle Impostazioni per rifiutare tariffe e contratti sovrapposti."""
    out = []
    for i, a in enumerate(righe):
        for b in righe[i + 1:]:
            if stessa_chiave is not None and not stessa_chiave(a, b):
                continue
            inizio = max(data(a['valido_da']), data(b['valido_da']))
            fini = [data(x['valido_a']) for x in (a, b) if x.get('valido_a') not in (None, '')]
            if not fini or inizio <= min(fini):
                out.append((a, b))
    return out


def tariffe_sovrapposte(tariffe):
    """Tariffe della stessa figura e dello stesso livello (vuoto = tutti i livelli) che
    valgono negli stessi giorni: la fattura non saprebbe quale usare (PROGETTO §15, 1.3:
    le Impostazioni le rifiutano)."""
    return periodi_sovrapposti(tariffe, lambda a, b: a['figura'] == b['figura'] and _id(a.get('lotto_id')) ==
                               _id(b.get('lotto_id')) and (a.get('livello_ccnl') or '') == (b.get('livello_ccnl') or ''))


def _gradi_compatibili(a, b):
    """Un contratto senza grado vale per tutti e due i gradi."""
    return a in (None, '') or b in (None, '') or a == b


def contratti_sovrapposti(contratti):
    """Contratti applicativi dello stesso lotto che coprono gli stessi giorni per lo stesso
    grado: le stesse ore finirebbero in due fatture (le Impostazioni li rifiutano)."""
    return periodi_sovrapposti(contratti, lambda a, b: _id(a.get('lotto_id')) == _id(b.get('lotto_id'))
                               and _gradi_compatibili(a.get('grado'), b.get('grado')))


def _tratti_tariffa(tariffe, figura, livello, dal, al):
    """[(inizio, fine, riga)]: i giorni del periodo, a tratti contigui, in cui vale davvero
    ciascuna riga di tariffa per la figura e il livello (riga None = nessuna tariffa).
    Il sotto-periodo scritto in fattura viene da qui, non dalle date della riga: con
    tariffe sovrapposte una riga puo' valere solo per una parte delle sue date."""
    out = []
    for d in _giorni(dal, al):
        t = tariffa_alla_data(tariffe, figura, d, livello)
        if out and out[-1][2] is t:
            out[-1] = (out[-1][0], d, t)
        else:
            out.append((d, d, t))
    return out


def _tratti(voci):
    """Voci (inizio, fine, livello, minuti) di una figura con la stessa tariffa (inizio e
    fine = giorni del periodo in cui vale quella riga di tariffa) -> tratti di date contigui
    {'dal', 'al', 'livelli', 'minuti'}. Se la tariffa torna a un valore gia' usato (A fino
    al 10, B dall'11 al 20, di nuovo A dal 21) i due tratti di A restano due righe."""
    tratti = []
    for inizio, fine, livello, min_ in sorted(voci, key=lambda v: (v[0], v[1])):
        if not tratti or inizio > tratti[-1]['al'] + datetime.timedelta(days=1):
            tratti.append({'dal': inizio, 'al': fine, 'livelli': set(), 'minuti': 0})
        t = tratti[-1]
        t['al'] = max(t['al'], fine)
        t['livelli'].add(livello)
        t['minuti'] += min_
    return tratti


def _aggiungi_bloccante(bloccanti, codice, figura=None, minuti_=0):
    for b in bloccanti:
        if b['codice'] == codice and b.get('figura') == figura:
            b['presenze'] += 1
            b['minuti'] += minuti_
            return
    bloccanti.append({'codice': codice, 'figura': figura, 'presenze': 1, 'minuti': minuti_})


def _riga(figura, tariffa_cent, livello, dal, al, ore, min_=None):
    tariffa = da_centesimi(tariffa_cent)
    ore = arrotonda(ore)
    importo = arrotonda(ore * tariffa)
    return {'figura': figura, 'descrizione': config_napoli.DESCRIZIONI_FATTURA.get(figura, figura.capitalize()),
            'livello_ccnl': livello, 'dal': dal, 'al': al, 'minuti': min_, 'ore': ore,
            'ore_cent': int(ore * 100), 'tariffa': tariffa, 'tariffa_cent': int(tariffa_cent),
            'importo': importo, 'importo_cent': in_centesimi(importo)}


def righe_fattura(presenze, tariffe, grado, dal, al, coordinamento=()):
    """Righe del prospetto di un lotto per un grado e un periodo (§5.4, passi 1-3).

    presenze: righe con 'data', 'figura', 'minuti_riconosciuti', 'stato', 'grado'
    (dell'alunno o della scuola, vedi grado_fattura: None o 'misto' = da decidere) e
    'livello_ccnl' dell'operatore; contano SOLO quelle con stato 'registrato' del grado,
    con data nel periodo e minuti > 0 (un giorno con un altro stato, anche senza stato, e'
    "non registrato" e blocca), raggruppate per (figura, tariffa valida nel giorno) e
    tratti di date contigui della tariffa: ore = minuti / 60 al centesimo.
    coordinamento: righe di napoli_coordinamento del lotto, grado, contratto e mese
    ('ore_cent', 'livello_ccnl'), con la tariffa COORDINATORE del periodo; ore al
    centesimo come quelle degli operatori. Le figure "di lotto" (il coordinatore) si
    fatturano solo da qui: le loro presenze non entrano in fattura (sarebbero contate
    due volte) e sono segnalate con l'avviso ore_coordinatore_nelle_presenze.
    Importo di riga = ore x tariffa al centesimo. Se la tariffa cambia nel periodo, la
    figura ha piu' righe, ciascuna con il suo sotto-periodo nella descrizione (i giorni in
    cui quella tariffa vale davvero, anche con tariffe sovrapposte).
    Bloccanti: tariffa_mancante, grado_da_decidere (blocca le fatture di tutti e due i
    gradi), giorni_non_registrati, tariffa_cambia_nel_periodo (solo coordinatore: le sue
    ore sono un totale del mese). Ritorna {'righe', 'bloccanti', 'avvisi'}."""
    if grado not in GRADI:
        raise ValueError(f'grado non valido: {grado}')
    dal, al = data(dal), data(al)
    gruppi, bloccanti, avvisi, tratti_tariffe = {}, [], [], {}
    for p in presenze:
        giorno = data(p['data'])
        if not dal <= giorno <= al:
            continue
        registrata = p.get('stato') == 'registrato'
        min_ = int(p.get('minuti_riconosciuti') or 0)
        grado_p = grado_fattura(p.get('grado'))
        if p['figura'] in config_napoli.FIGURE_DI_LOTTO:
            if grado_p in (None, grado) and min_ > 0:
                _aggiungi_bloccante(avvisi, 'ore_coordinatore_nelle_presenze', p['figura'], min_)
            continue
        if grado_p is None:
            if not registrata or min_ > 0:
                _aggiungi_bloccante(bloccanti, 'grado_da_decidere', p['figura'], min_)
            continue
        if grado_p != grado:
            continue
        if not registrata:
            _aggiungi_bloccante(bloccanti, 'giorni_non_registrati', p['figura'])
            continue
        if min_ <= 0:
            continue
        chiave = (p['figura'], p.get('livello_ccnl'))
        if chiave not in tratti_tariffe:
            tratti_tariffe[chiave] = _tratti_tariffa(tariffe, p['figura'], p.get('livello_ccnl'), dal, al)
        inizio, fine, t = next(x for x in tratti_tariffe[chiave] if x[0] <= giorno <= x[1])
        if t is None:
            _aggiungi_bloccante(bloccanti, 'tariffa_mancante', p['figura'], min_)
            continue
        gruppi.setdefault((p['figura'], t['tariffa_cent']), []).append((inizio, fine, t.get('livello_ccnl'), min_))
    righe = [_riga(f, cent, next(iter(g['livelli'])) if len(g['livelli']) == 1 else None, g['dal'], g['al'],
                   ore_decimali(g['minuti']), g['minuti'])
             for (f, cent), voci in gruppi.items() for g in _tratti(voci)]

    per_livello = {}
    for c in coordinamento:
        if int(c.get('ore_cent') or 0) > 0:
            liv = c.get('livello_ccnl')
            per_livello[liv] = per_livello.get(liv, 0) + int(c['ore_cent'])
    for liv, ore_cent in per_livello.items():
        trovate = [tariffa_alla_data(tariffe, 'COORDINATORE', d, liv) for d in _giorni(dal, al)]
        if any(t is None for t in trovate):
            bloccanti.append({'codice': 'tariffa_mancante', 'figura': 'COORDINATORE', 'presenze': 0, 'minuti': 0})
        elif len({t['tariffa_cent'] for t in trovate}) > 1:
            bloccanti.append({'codice': 'tariffa_cambia_nel_periodo', 'figura': 'COORDINATORE', 'presenze': 0,
                              'minuti': 0})
        else:
            righe.append(_riga('COORDINATORE', trovate[0]['tariffa_cent'], trovate[0].get('livello_ccnl'), dal, al,
                               Decimal(ore_cent) / 100))

    ordine = config_napoli.ORDINE_RIGHE_FATTURA
    righe.sort(key=lambda r: (ordine.index(r['figura']) if r['figura'] in ordine else len(ordine), r['figura'],
                              r['dal'], r['tariffa_cent']))
    for r in righe:
        stesse = [x for x in righe if x['figura'] == r['figura']]
        if len(stesse) > 1:
            if r['livello_ccnl'] and len({x['livello_ccnl'] for x in stesse}) > 1:
                r['descrizione'] += f' - livello {r["livello_ccnl"]}'
            if (r['dal'], r['al']) != (dal, al):
                r['descrizione'] += f' (dal {r["dal"]:%d/%m} al {r["al"]:%d/%m})'
    return {'righe': righe, 'bloccanti': bloccanti, 'avvisi': avvisi}


def totali_fattura(righe, regole=None):
    """Totali (§5.4, passo 3): somma delle righe; ritenuta = somma x 0,50% al
    centesimo; imponibile = somma - ritenuta; IVA = imponibile x 5% al centesimo;
    totale = imponibile + IVA; da pagare = imponibile con lo split payment (l'IVA la
    versa l'ente), altrimenti il totale. Percentuali e split payment dalle regole."""
    ritenuta_percento = decimale(_r(regole, 'ritenuta_percento'))
    iva_percento = decimale(_r(regole, 'iva_percento'))
    split = bool(_r(regole, 'split_payment'))
    somma = sum((r['importo'] for r in righe), Decimal('0.00'))
    ritenuta = arrotonda(somma * ritenuta_percento / 100)
    imponibile = somma - ritenuta
    iva = arrotonda(imponibile * iva_percento / 100)
    totale = imponibile + iva
    out = {'somma': somma, 'ritenuta': ritenuta, 'imponibile': imponibile, 'iva': iva, 'totale': totale,
           'da_pagare': imponibile if split else totale}
    out.update({k + '_cent': in_centesimi(v) for k, v in list(out.items())})
    out.update({'ritenuta_percento': ritenuta_percento, 'iva_percento': iva_percento, 'split_payment': split})
    return out


def riempi_modello(modello, valori):
    """Sostituisce i segnaposto {nome} noti; quelli sconosciuti restano come sono."""
    return re.sub(r'\{(\w+)\}', lambda m: str(valori[m.group(1)]) if m.group(1) in valori else m.group(0),
                  modello or '')


def testo_oggetto(numero_lotto, grado, dal, al, contratto, modello=None):
    """Oggetto della fattura dal modello del lotto (o quello predefinito):
    "... - Lotto 1 - Scuole di grado inferiore - Competenze dal 08 al 30 Giugno 2026. XI APPLICATIVO"."""
    dal, al = data(dal), data(al)
    return riempi_modello(modello or config_napoli.MODELLO_OGGETTO_FATTURA, {
        'lotto': numero_lotto, 'grado': grado, 'dal': f'{dal.day:02d}', 'al': f'{al.day:02d}',
        'mese': MESI[al.month - 1], 'anno': al.year, 'contratto': contratto})


def testo_nota(servizio, dd_numero, dd_data, regole=None, modello=None):
    """Nota della fattura: "D.D. {servizio} N.{dd_numero} DEL {dd_data}" piu' il testo
    dello split payment, se si applica."""
    nota = riempi_modello(modello or config_napoli.MODELLO_NOTA_FATTURA, {
        'servizio': servizio or '', 'dd_numero': dd_numero or '',
        'dd_data': data_it(dd_data) if dd_data else ''})
    if _r(regole, 'split_payment'):
        nota = f'{nota} - {_r(regole, "split_payment_testo")}'
    return nota


def testo_ritenuta(regole=None):
    return riempi_modello(_r(regole, 'ritenuta_testo'), {'percento': numero_it(_r(regole, 'ritenuta_percento'))})


def scadenza_pagamento(data_fattura, giorni):
    """Data della fattura + giorni di pagamento (31/07 + 30 -> 30/08)."""
    return data(data_fattura) + datetime.timedelta(days=int(giorni))


def scadenza_invio(anno, mese, giorni):
    """Termine di invio del rendiconto del mese: fine mese + giorni (CSA art. 15)."""
    return fine_mese(anno, mese) + datetime.timedelta(days=int(giorni))


def dati_mancanti_fattura(lotto, contratto, impostazioni=None, oggetto=None):
    """Dati obbligatori del prospetto che mancano (bloccano la fattura definitiva):
    CIG, destinatario, oggetto, contratto applicativo, DD (numero e data), IBAN."""
    impostazioni = impostazioni or {}
    controlli = (('cig', lotto.get('cig')), ('destinatario', lotto.get('destinatario')), ('oggetto', oggetto),
                 ('contratto', contratto.get('numero')), ('dd_numero', contratto.get('dd_numero')),
                 ('dd_data', contratto.get('dd_data')), ('iban', impostazioni.get('cooperativa_iban')))
    return [campo for campo, valore in controlli if not str(valore or '').strip()]


def _da_controllare(p):
    """Presenza che deve stare in un contratto: registrata con minuti > 0, oppure non
    registrata (preparata e non ancora compilata, o senza stato)."""
    return p.get('stato') != 'registrato' or int(p.get('minuti_riconosciuti') or 0) > 0


def _contratti_della_presenza(p, contratti):
    giorno, grado = data(p['data']), grado_fattura(p.get('grado'))
    return [c for c in contratti
            if _valida_nella_data(c, giorno) and (grado is None or _gradi_compatibili(c.get('grado'), grado))]


def ore_fuori_contratto(presenze, contratti):
    """Bloccante del §5.5 "presenza fuori da ogni contratto applicativo", che il prospetto
    non vede (guarda un contratto alla volta): presenze registrate con minuti > 0, o non
    registrate, la cui data non cade in nessun contratto del lotto (righe di
    napoli_contratti) del loro grado. Un contratto senza grado vale per tutti e due; con il
    grado da decidere basta un contratto qualsiasi (blocca gia' il grado).
    Ritorna i bloccanti {'codice': 'presenza_fuori_contratto', 'figura', 'presenze', 'minuti'}."""
    bloccanti = []
    for p in presenze:
        if _da_controllare(p) and not _contratti_della_presenza(p, contratti):
            _aggiungi_bloccante(bloccanti, 'presenza_fuori_contratto', p['figura'],
                                int(p.get('minuti_riconosciuti') or 0))
    return bloccanti


def presenze_in_piu_contratti(presenze, contratti):
    """Bloccante "presenza in due contratti applicativi": una presenza (come in
    ore_fuori_contratto) del suo grado in piu' contratti dello stesso lotto finirebbe in
    due fatture. Succede solo con contratti sovrapposti (contratti_sovrapposti), che le
    Impostazioni rifiutano; con il grado da decidere non si controlla (blocca gia').
    Ritorna i bloccanti {'codice': 'presenza_in_piu_contratti', 'figura', 'presenze', 'minuti'}."""
    bloccanti = []
    for p in presenze:
        if _da_controllare(p) and grado_fattura(p.get('grado')) and len(_contratti_della_presenza(p, contratti)) > 1:
            _aggiungi_bloccante(bloccanti, 'presenza_in_piu_contratti', p['figura'],
                                int(p.get('minuti_riconosciuti') or 0))
    return bloccanti


# Regole della fattura che si congelano con il prospetto (napoli_fatture.regole_json).
REGOLE_DELLA_FATTURA = ('ritenuta_percento', 'iva_percento', 'split_payment', 'giorni_pagamento')


def prospetto_fattura(anno, mese, grado, contratto, presenze, tariffe, coordinamento=(), lotto=None,
                      righe_regole=(), impostazioni=None, data_fattura=None):
    """Prospetto di un lotto per grado, contratto applicativo e mese (§5.4): periodo,
    righe, totali, testi (oggetto, nota, destinatario, ritenuta, scadenza), regole usate
    e controlli ('bloccanti' e 'avvisi', dict con 'codice'). Le regole della fattura
    (ritenuta, IVA, split payment, testi, giorni di pagamento) sono quelle valide il primo
    giorno del periodo. contratto: riga di napoli_contratti; lotto: riga di napoli_lotti.
    Le presenze fuori da ogni contratto o in due contratti si controllano a parte, sul
    mese intero (ore_fuori_contratto, presenze_in_piu_contratti). Per congelare il
    prospetto in napoli_fatture: testi_da_congelare."""
    if grado not in GRADI:
        raise ValueError(f'grado non valido: {grado}')
    lotto = lotto or {}
    out = {'grado': grado, 'contratto': contratto.get('numero'), 'dal': None, 'al': None, 'righe': [],
           'totali': totali_fattura([]), 'oggetto': '', 'nota': '', 'destinatario': lotto.get('destinatario') or '',
           'ritenuta_testo': '', 'giorni_pagamento': None, 'scadenza': None, 'regole': {}, 'bloccanti': [],
           'avvisi': []}
    if contratto.get('grado') not in (None, '', grado):
        out['bloccanti'].append({'codice': 'contratto_di_altro_grado'})
        return out
    periodo = periodo_fattura(anno, mese, contratto['valido_da'], contratto.get('valido_a'))
    if periodo is None:
        out['bloccanti'].append({'codice': 'contratto_fuori_dal_mese'})
        return out
    dal, al = periodo
    regole = regole_alla_data(dal, righe_regole, lotto.get('id'))
    calcolo = righe_fattura(presenze, tariffe, grado, dal, al, coordinamento)
    out.update(dal=dal, al=al, righe=calcolo['righe'], totali=totali_fattura(calcolo['righe'], regole),
               ritenuta_testo=testo_ritenuta(regole), giorni_pagamento=regole['giorni_pagamento'],
               regole={k: regole[k] for k in REGOLE_DELLA_FATTURA})
    out['oggetto'] = testo_oggetto(lotto.get('numero_lotto', ''), grado, dal, al, contratto.get('numero', ''),
                                   lotto.get('oggetto_fattura'))
    out['nota'] = testo_nota(lotto.get('riferimento_amministrativo'), contratto.get('dd_numero'),
                             contratto.get('dd_data'), regole, lotto.get('nota_fattura'))
    if data_fattura:
        out['scadenza'] = scadenza_pagamento(data_fattura, regole['giorni_pagamento'])
    out['bloccanti'] = calcolo['bloccanti'] + [
        {'codice': 'dato_mancante', 'campo': c} for c in dati_mancanti_fattura(lotto, contratto, impostazioni,
                                                                               out['oggetto'])]
    out['avvisi'] = calcolo['avvisi'] + ([] if out['righe'] else [{'codice': 'nessuna_riga'}])
    return out


def testi_da_congelare(prospetto):
    """Testi del prospetto per le colonne di napoli_fatture (schema v3): oggetto, nota,
    destinatario, ritenuta_testo, scadenza ('AAAA-MM-GG' o None) e regole_json (le regole
    usate, con i numeri come testo: 0.50, non 0.5000000001). Una fattura definitiva si
    ristampa da qui, anche se poi cambiano i modelli del lotto o le regole."""
    regole = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in prospetto.get('regole', {}).items()}
    scadenza = prospetto.get('scadenza')
    return {'oggetto': prospetto.get('oggetto') or '', 'nota': prospetto.get('nota') or '',
            'destinatario': prospetto.get('destinatario') or '', 'ritenuta_testo': prospetto.get('ritenuta_testo') or '',
            'scadenza': data(scadenza).isoformat() if scadenza else None,
            'regole_json': json.dumps(regole, sort_keys=True)}

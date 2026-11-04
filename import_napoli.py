"""Import del foglio presenze mensile "master" di Napoli (PROGETTO §7.1, passi 1.4-1.5).

Il master e' il file Excel che il coordinatore manda ogni mese: una riga per coppia
operatore-alunno (Lotto, Cooperativa, operatore e codice fiscale, qualifica, data di
inizio, ore di contratto, alunno e codice fiscale, ore da progetto, municipalita',
scuola), una colonna per ogni giorno da lunedi' a sabato con le ore in decimale o la
sigla dell'operatore assente (F, M, F perm), una VERIFICA dopo ogni settimana, la
sostituzione SI/NO e le note.

- Lettura (leggi_master): solo il file, niente database. Le colonne si riconoscono
  dall'intestazione, i giorni dalla data, la scuola per posizione (nel file del
  Comune l'intestazione e' "2"). Le ore si ricalcolano dalle CELLE DEI GIORNI con
  napoli_calcoli.leggi_cella_master: la VERIFICA serve solo da controllo (nel file vero
  perde ore, tra numeri scritti come testo e celle sovrascritte), il foglio "riepilogo"
  solo per un confronto. Note "Alunno assente: ..." e celle colorate sono solo
  segnalazioni (diventeranno proposte nella fase 2). Ogni interpretazione e' un avviso
  con riga e colonna, mai con nomi o codici fiscali.
- Anteprima (anteprima): non scrive nulla. Abbina il file ai dati di Napoli (scuole per
  codice meccanografico e municipalita' della SCUOLA: la stessa scuola con municipalita'
  diverse, nel file o fra il file e Assisto, si conferma, e un plesso nuovo si crea solo
  se serve a una coppia nuova; alunni per codice fiscale o per la sua radice, i primi 15
  caratteri; operatori per codice fiscale, radice o nome, da confermare, anche quando il
  mese dopo il codice arriva corretto; un codice giusto corregge quello sbagliato in
  Assisto; qualifiche con le grafie di napoli_alias_qualifiche, una nuova si sceglie
  sempre; coppie valide nel mese o finite nel mese prima, cosi' un sostituto che continua
  o un titolare che torna restano la stessa coppia) e prepara il piano: cosa si crea,
  cosa cambia, ore per figura e per grado, avvisi e bloccanti spiegati con parole
  semplici. Le ore da confermare ("1,30") si scelgono sempre: nessuna e' gia' scelta.
- Conferma (conferma): lo stesso file (sha256 dell'anteprima) e gli stessi dati di
  Napoli (versione_dati), copia di sicurezza del database, poi un'unica transazione.
  Ogni cella con ore o sigla e' un giorno registrato (calcolo 'manuale', origine
  'import_excel', testo originale); la nota della riga va nel foglio del mese.
- Reimport dello stesso mese: si sostituiscono solo le ore importate; le ore scritte a
  mano diverse dal file si mostrano e restano (salvo la scelta "sovrascrivi");
  un file uguale non cambia nulla.
- Annulla import (annulla_import, anche con Ctrl+Z subito dopo): solo l'ultimo import
  del lotto, rimette tutto com'era (napoli_import.sostituite_json: id delle righe
  create e valori di prima delle righe cambiate, mai codici fiscali).
- Solo confronto (modo 'confronto'): le differenze fra il file e Assisto, coppia per
  coppia e giorno per giorno, senza scrivere nulla.

Privacy: i codici fiscali stanno solo nelle anagrafiche di Napoli; alla pagina arrivano
mascherati (anche quelli scritti per errore in una cella), e non entrano mai negli
avvisi, nel registro attivita', nei log, in napoli_import (esito_json e sostituite_json:
di un codice corretto si salva solo la differenza) o in napoli_annullamenti.
Solo tabelle napoli_* (tests/test_separazione_napoli.py).
"""
import collections
import datetime
import difflib
import hashlib
import io
import json
import logging
import re
import sqlite3
import unicodedata
import zipfile

import openpyxl
from openpyxl.utils import get_column_letter

import config_napoli
import database as db
import napoli_calcoli as calc
import napoli_db
from napoli_db import Conflitto, DatiNonValidi, NonTrovato

logger = logging.getLogger('oepac.napoli')

MESI = ('gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio', 'agosto', 'settembre',
        'ottobre', 'novembre', 'dicembre')
GRADI_SCUOLA = ('inferiore', 'superiore', 'misto')
# Colonne senza le quali il foglio non e' il master, con il nome che hanno nel file.
COLONNE_OBBLIGATORIE = (
    ('operatore', 'Nome Cognome Operatore'), ('cf_operatore', 'Cf Operatore'),
    ('qualifica', 'Qualifica Professionale'), ('alunno', 'Nome Cognome alunno/a'),
    ('cf_alunno', 'Cf alunno/a'), ('ore_progetto', 'Ore settimanali da progetto'),
)
MAX_RIGHE_PER_AVVISO = 40           # righe elencate per ogni avviso (le altre si contano)
# Righe vuote di fila dopo le quali il foglio e' finito (un foglio formattato fino in
# fondo ha un milione di righe vuote: non si leggono).
RIGHE_VUOTE_FINE = 200


# ==================== utilita' di lettura ====================

def normalizza(testo):
    """Minuscolo, senza accenti, spazi singoli."""
    if testo is None:
        return ''
    s = str(testo).strip().lower()
    s = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', s)


def pulito(testo):
    """MAIUSCOLO con spazi singoli: la forma con cui si confrontano nomi, qualifiche e scuole."""
    return re.sub(r'\s+', ' ', str('' if testo is None else testo).strip()).upper()


def _lettere(parole):
    s = unicodedata.normalize('NFKD', pulito(parole))
    return [c for c in s if 'A' <= c <= 'Z']


def _codice_cognome(parole):
    s = _lettere(parole)
    consonanti = [c for c in s if c not in 'AEIOU']
    return ''.join(consonanti + [c for c in s if c in 'AEIOU'] + ['X'] * 3)[:3]


def _codice_nome(parole):
    s = _lettere(parole)
    consonanti = [c for c in s if c not in 'AEIOU']
    if len(consonanti) >= 4:
        consonanti = [consonanti[0], consonanti[2], consonanti[3]]
    return ''.join(consonanti + [c for c in s if c in 'AEIOU'] + ['X'] * 3)[:3]


def separa_cognome_nome(nome_completo, cf=None):
    """Divide "COGNOME NOME" con il codice fiscale (le prime 6 lettere vengono da cognome e
    nome). Nel file vero l'ordine e' quasi sempre COGNOME NOME anche se l'intestazione
    dice "Nome Cognome". Ritorna (cognome, nome, metodo): 'cf', 'cf_invertito' o
    'prima_parola' (senza codice fiscale utile: la prima parola e' il cognome)."""
    parole = [p for p in pulito(nome_completo).split(' ') if p]
    if len(parole) < 2:
        return ' '.join(parole), '', 'prima_parola'
    cf = re.sub(r'\s', '', str(cf or '')).upper()
    if len(cf) >= 6:
        for k in range(1, len(parole)):
            a, b = ' '.join(parole[:k]), ' '.join(parole[k:])
            if _codice_cognome(a) == cf[:3] and _codice_nome(b) == cf[3:6]:
                return a, b, 'cf'
        for k in range(1, len(parole)):
            a, b = ' '.join(parole[:k]), ' '.join(parole[k:])
            if _codice_nome(a) == cf[3:6] and _codice_cognome(b) == cf[:3]:
                return b, a, 'cf_invertito'
    return parole[0], ' '.join(parole[1:]), 'prima_parola'


# ==================== codici fiscali: abbinamento, correzione, privacy ====================

def radice_cf(cf):
    """I primi 15 caratteri di un codice fiscale di 16 (il sedicesimo e' il carattere di
    controllo, calcolato dagli altri): due codici con la stessa radice sono la stessa
    persona, scritta una volta con l'ultimo carattere sbagliato. None se non ha 16 caratteri."""
    return cf[:15] if cf and len(cf) == 16 else None


def differenza_cf(nuovo, vecchio):
    """Come tornare dal codice corretto dall'import a quello di prima, senza salvare il
    codice di prima (per "Annulla import"): {'vuoto': True} se prima non c'era, altrimenti
    {'modifiche': [[da, a, testo]]} con al piu' due caratteri del codice di prima. None se
    i due codici sono troppo diversi (allora l'import non corregge il codice)."""
    if not vecchio:
        return {'vuoto': True}
    modifiche = [[i1, i2, vecchio[j1:j2]] for tag, i1, i2, j1, j2
                 in difflib.SequenceMatcher(None, nuovo, vecchio, autojunk=False).get_opcodes() if tag != 'equal']
    if sum(len(t) for _a, _b, t in modifiche) > 2 or sum(b - a for a, b, _t in modifiche) > 2:
        return None
    return {'modifiche': modifiche}


def applica_differenza_cf(attuale, differenza):
    """Il codice di prima, dal codice attuale e dalla differenza di differenza_cf."""
    if differenza.get('vuoto'):
        return None
    s = attuale
    for da, a, testo in sorted(differenza['modifiche'], reverse=True):
        s = s[:da] + testo + s[a:]
    return s


_RX_PEZZO = re.compile(r'[A-Za-z0-9]+')
_RX_FORMA_CF = re.compile(r'[A-Z]{6}[0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z]')


def _sembra_codice(pezzo):
    cifre = sum(ch.isdigit() for ch in pezzo)
    return 11 <= len(pezzo) <= 20 and cifre >= 2 and len(pezzo) - cifre >= 4


def nascondi_codici_fiscali(testo):
    """Il testo con ogni possibile codice fiscale mascherato (come maschera_codice_fiscale):
    parole di 11-20 lettere e cifre con almeno 2 cifre e 4 lettere (anche un codice scritto
    male), e codici scritti a gruppi separati da spazi ('RSS MRA 80A01 Z999X'). Serve per
    il testo delle celle che arriva alla pagina: un codice scritto per errore in una cella
    dei giorni o delle ore non deve comparire in chiaro."""
    if not isinstance(testo, str) or not testo:
        return testo
    pezzi = list(_RX_PEZZO.finditer(testo))
    da_coprire, i = [], 0
    while i < len(pezzi):
        trovato = None
        for k in range(min(6, len(pezzi) - i), 1, -1):
            gruppo = pezzi[i:i + k]
            if all(testo[a.end():b.start()] in (' ', '-', '.') for a, b in zip(gruppo, gruppo[1:])) \
                    and _RX_FORMA_CF.fullmatch(''.join(p.group() for p in gruppo).upper()):
                trovato = (gruppo[0].start(), gruppo[-1].end(), k)
                break
        if trovato is None and _sembra_codice(pezzi[i].group()):
            trovato = (pezzi[i].start(), pezzi[i].end(), 1)
        if trovato:
            da_coprire.append(trovato[:2])
            i += trovato[2]
        else:
            i += 1
    for a, b in reversed(da_coprire):
        testo = testo[:a] + calc.maschera_codice_fiscale(testo[a:b]) + testo[b:]
    return testo


def _senza_codici(valore, chiave=None):
    """Una risposta per la pagina con i possibili codici fiscali nei testi mascherati
    (tranne le impronte del file e dei dati, che sono numeri esadecimali)."""
    if isinstance(valore, dict):
        return {k: (v if k in ('sha256', 'versione_dati') else _senza_codici(v, k)) for k, v in valore.items()}
    if isinstance(valore, (list, tuple)):
        return [_senza_codici(v, chiave) for v in valore]
    return nascondi_codici_fiscali(valore) if isinstance(valore, str) else valore


def figura_proposta(qualifica):
    """Figura proposta per una qualifica che non e' fra quelle conosciute (da confermare):
    EDUCATRICE PROF.LE -> EDUCATORE, ASS. COMUNICAZIONE -> ASACOM...; None se non si capisce."""
    q = re.sub(r'[^a-z ]', '', normalizza(qualifica))
    if not q:
        return None
    if q.startswith('asac') or q.startswith('assistente all') or 'comunicazione' in q:
        return 'ASACOM'
    if q.startswith('edu'):
        return 'EDUCATORE'
    if q.startswith('psicol'):
        return 'PSICOLOGO'
    if q.startswith('tiflo') or 'disabilita visiva' in q:
        return 'TIFLOLOGO'
    if 'lis' in q.split() or q.startswith('interpret'):
        return 'LIS'
    if q.startswith('coordinat'):
        return 'COORDINATORE'
    return None


def _numero_nel_testo(s):
    m = re.search(r'\d+(?:[.,]\d+)?', str(s))
    return calc.decimale(m.group()) if m else None


def leggi_ore_settimanali(valore):
    """Ore settimanali (di contratto o da progetto): 13, '13 var oraria', '23 var or',
    'con var 29', '34 CON VAR'. Ritorna (Decimal o None, con_variazione, era_testo)."""
    if valore is None or valore == '' or isinstance(valore, bool):
        return None, False, False
    if isinstance(valore, (int, float)):
        return calc.decimale(valore), False, False
    if isinstance(valore, (datetime.date, datetime.time, datetime.timedelta)):
        return None, False, True
    s = normalizza(valore)
    return _numero_nel_testo(s), ('var' in s), True


def leggi_data_inizio(valore, anno, mese):
    """Data di inizio attivita': (data o None, avviso o None, proposta o None). Corregge,
    segnalandolo, la lettera O al posto dello zero ('O3/11/2025') e lo spazio come
    separatore ('26/11 2025'); un anno di tre cifre ('06/10/205') da' solo una proposta."""
    if valore is None or valore == '':
        return None, None, None
    if isinstance(valore, datetime.datetime):
        return valore.date(), None, None
    if isinstance(valore, datetime.date):
        return valore, None, None
    s = str(valore).strip()
    t = re.sub(r'(?<![A-Za-z])[Oo](?=\d)|(?<=\d)[Oo]', '0', s)
    t = re.sub(r'[\s.\-]+', '/', t)
    m = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', t)
    if not m:
        return None, 'data_inizio_non_leggibile', None
    g, me, a = int(m.group(1)), int(m.group(2)), m.group(3)
    if len(a) == 3:
        inizio_as = anno if mese >= 9 else anno - 1
        candidati = sorted({int(a[:k] + c + a[k:]) for k in range(4) for c in '0123456789'})
        for c in (c for c in candidati if inizio_as - 1 <= c <= inizio_as + 1):
            try:
                return None, 'data_inizio_anno_errato', datetime.date(c, me, g)
            except ValueError:
                continue
        return None, 'data_inizio_anno_errato', None
    anno_scritto = int(a) + (2000 if len(a) == 2 else 0)
    try:
        d = datetime.date(anno_scritto, me, g)
    except ValueError:
        return None, 'data_inizio_non_leggibile', None
    return d, ('data_inizio_scritta_male' if t != s else None), (d if t != s else None)


def leggi_sostituzione(valore):
    s = normalizza(valore)
    if s in ('si', 's', 'x'):
        return True
    if s in ('no', 'n'):
        return False
    return None


_RX_COD_SCUOLA = re.compile(r'\b([A-Z]{2})\s?([A-Z0-9]{2})\s?([A-Z0-9]{6})\b')


def leggi_scuola(valore):
    """'I.C. NOME - PLESSO (COD.MECC. NAIC8XXXXX)' -> (nome, codice o None, avvisi)."""
    grezzo = '' if valore is None else str(valore)
    s = pulito(grezzo)
    avvisi = []
    if s.count('(') > s.count(')'):
        avvisi.append('scuola_parentesi_non_chiusa')
    m = re.search(r'MECC\.?\s*:?\s*([A-Z0-9 ]{10,12})', s)
    if m:
        candidati = [re.sub(r'\s', '', m.group(1))[:10]]
    else:
        candidati = [''.join(x.groups()) for x in _RX_COD_SCUOLA.finditer(s)
                     if sum(ch.isdigit() for ch in ''.join(x.groups())) >= 3]
    codice = candidati[0] if candidati else None
    if codice is None:
        avvisi.append('scuola_senza_codice')
    elif any(ch.isdigit() for ch in codice[:4]):
        avvisi.append('scuola_codice_sospetto')       # es. 'NA1C...': 1 al posto di I? (paritarie NA1A/1E/1M)
    nome = re.sub(r'\(\s*COD\.?\s*MECC.*$', '', s).strip(' -(')
    if grezzo != grezzo.strip() or '  ' in grezzo or '\n' in grezzo:
        avvisi.append('scuola_spazi_irregolari')
    return nome, codice, avvisi


def chiave_nome_scuola(nome):
    """Il nome di una scuola senza punteggiatura e spazi in piu', per riconoscerla senza codice."""
    return re.sub(r'[^a-z0-9]+', ' ', normalizza(nome)).strip()


def leggi_municipalita(valore):
    """Municipalita' (numero) da 2, 2.0, '2', 'Municipalità 2'; (numero o None, avviso)."""
    if valore is None or (isinstance(valore, str) and not valore.strip()):
        return None, None
    if isinstance(valore, bool):
        return None, 'municipalita_non_riconosciuta'
    if isinstance(valore, int) or (isinstance(valore, float) and valore.is_integer()):
        return (int(valore), None) if 0 < valore < 100 else (None, 'municipalita_non_riconosciuta')
    numeri = re.findall(r'\d+', str(valore))
    if len(numeri) == 1 and 0 < int(numeri[0]) < 100:
        return int(numeri[0]), None
    return None, 'municipalita_non_riconosciuta'


def _data_intestazione(v):
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    if isinstance(v, str):
        m = re.fullmatch(r'\s*(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\s*', v)
        if m:
            try:
                return datetime.date(int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0), int(m.group(2)),
                                     int(m.group(1)))
            except ValueError:
                return None
    return None


def trova_colonne(intestazione):
    """Nomi delle colonne -> indici (da 0). Ritorna (colonne, giorni [(indice, data)],
    verifiche [indice], avvisi)."""
    col, giorni, verifiche, avvisi = {}, [], [], []
    for j, v in enumerate(intestazione):
        d = _data_intestazione(v)
        if d:
            giorni.append((j, d))
            continue
        h = normalizza(v)
        if not h:
            continue
        if h.startswith('verifica'):
            verifiche.append(j)
        elif h == 'lotto':
            col.setdefault('lotto', j)
        elif 'cooperativa' in h or h == 'ente':
            col.setdefault('cooperativa', j)
        elif h.startswith('cf') or 'codice fiscale' in h:
            col.setdefault('cf_alunno' if 'alunn' in h else 'cf_operatore', j)
        elif 'operatore' in h and 'sostituz' not in h and ('nome' in h or 'cognome' in h):
            col.setdefault('operatore', j)
        elif 'alunn' in h and ('nome' in h or 'cognome' in h):
            col.setdefault('alunno', j)
        elif 'qualifica' in h:
            col.setdefault('qualifica', j)
        elif 'data inizio' in h:
            col.setdefault('data_inizio', j)
        elif 'contratto' in h:
            col.setdefault('ore_contratto', j)
        elif 'progetto' in h or 'pei' in h.split():
            col.setdefault('ore_progetto', j)
        elif 'municipal' in h:
            col.setdefault('municipalita', j)
        elif 'scuola' in h or 'istituto' in h or 'plesso' in h:
            col.setdefault('scuola', j)
        elif 'sostituz' in h:
            col.setdefault('sostituzione', j)
        elif h.startswith('note'):
            col.setdefault('note', j)
    if 'scuola' not in col and 'municipalita' in col:
        j = col['municipalita'] + 1
        primo_giorno = giorni[0][0] if giorni else len(intestazione)
        if j < primo_giorno and j not in col.values():
            col['scuola'] = j
            avvisi.append('intestazione_scuola_errata')     # nel file del Comune l'intestazione e' "2"
    return col, giorni, verifiche, avvisi


# ==================== apertura del file ====================

def _errore_file(messaggio, codice):
    return DatiNonValidi(messaggio, 'file', codice=codice)


MESSAGGIO_NON_LEGGIBILE = ('Il file non si riesce a leggere come file Excel (.xlsx). Se è aperto in Excel, '
                           'chiudilo e riprova; se è un altro tipo di file, aprilo in Excel e salvalo come '
                           '«Cartella di lavoro di Excel (.xlsx)».')


def _apri(dati, nome_file=''):
    """(cartella con i valori, cartella con le formule). Errori con messaggi semplici:
    file vuoto, file temporaneo di Excel (~$...), formato vecchio .xls o file protetto da
    password, file che non e' Excel."""
    nome = str(nome_file or '').replace('\\', '/').rsplit('/', 1)[-1]
    if nome.startswith('~$'):
        raise _errore_file('Hai scelto il file temporaneo che Excel crea mentre il foglio è aperto (il nome '
                           'comincia con ~$). Chiudi Excel e scegli il file vero, quello senza ~$ all\'inizio '
                           'del nome.', 'FILE_TEMPORANEO_EXCEL')
    if not dati:
        raise _errore_file('Il file è vuoto. Se è aperto in Excel, chiudilo e scegli di nuovo il file.',
                           'FILE_VUOTO')
    if dati[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
        raise _errore_file('Il file è nel formato vecchio di Excel (.xls) oppure è protetto da una password. '
                           'Aprilo in Excel, togli l\'eventuale password e salvalo come «Cartella di lavoro di '
                           'Excel (.xlsx)», poi riprova.', 'FILE_XLS')
    if not zipfile.is_zipfile(io.BytesIO(dati)):
        raise _errore_file(MESSAGGIO_NON_LEGGIBILE, 'FILE_NON_LEGGIBILE')
    try:
        valori = openpyxl.load_workbook(io.BytesIO(dati), data_only=True)
        formule = openpyxl.load_workbook(io.BytesIO(dati), data_only=False)
    except Exception as e:      # file rovinato o non Excel: openpyxl ha errori di tanti tipi
        logger.warning('Napoli, import: file non leggibile (%s)', type(e).__name__)
        raise _errore_file(MESSAGGIO_NON_LEGGIBILE, 'FILE_NON_LEGGIBILE') from None
    return valori, formule


def _intestazione_del_foglio(ws):
    """(indice della riga di intestazione, valori) fra le prime 10 righe, o None."""
    for i, riga in enumerate(ws.iter_rows(min_row=1, max_row=10, values_only=True)):
        celle = [normalizza(c) for c in riga]
        if 'lotto' in celle or any('operatore' in c for c in celle):
            return i, list(riga)
    return None


def _trova_foglio(wb):
    """Il foglio "master" o il primo con le colonne del master; altrimenti un errore che
    dice cosa manca e quali fogli ci sono."""
    fogli = sorted(wb.worksheets, key=lambda w: normalizza(w.title) != 'master')
    migliore = None
    for ws in fogli:
        trovata = _intestazione_del_foglio(ws)
        if not trovata:
            continue
        col, giorni, _v, _a = trova_colonne(trovata[1])
        mancanti = [nome for chiave, nome in COLONNE_OBBLIGATORIE if chiave not in col]
        if not mancanti and giorni:
            return ws, trovata
        if migliore is None or len(mancanti) < len(migliore[1]):
            migliore = (ws, mancanti + ([] if giorni else ['le colonne dei giorni (con la data)']))
    elenco = ', '.join(f'«{w.title}»' for w in wb.worksheets)
    if migliore:
        raise _errore_file(f'Il foglio «{migliore[0].title}» non sembra il foglio presenze del Comune: mancano '
                           f'le colonne {", ".join(migliore[1])}. Controlla di aver scelto il file giusto '
                           f'(fogli nel file: {elenco}).', 'FOGLIO_NON_RICONOSCIUTO')
    raise _errore_file('In questo file non c\'è il foglio presenze del Comune (con le colonne Lotto, Nome Cognome '
                       f'Operatore, Cf Operatore, ...). Fogli nel file: {elenco}. Controlla di aver scelto il '
                       'file giusto.', 'FOGLIO_NON_RICONOSCIUTO')


# ==================== lettura del master ====================

MAX_DETTAGLIO = 60          # caratteri del testo di una cella mostrati in un avviso


def _anomalia(lista, riga, colonna, codice, dettaglio=None):
    """Un avviso della lettura: riga e colonna del foglio, codice e un dettaglio che non
    e' mai un dato personale (valori di celle con ore o sigle, date, qualifiche; un codice
    fiscale scritto per errore in una cella arriva mascherato, il testo lungo accorciato)."""
    if dettaglio is not None:
        dettaglio = nascondi_codici_fiscali(re.sub(r'\s+', ' ', str(dettaglio)).strip())
        if len(dettaglio) > MAX_DETTAGLIO:
            dettaglio = dettaglio[:MAX_DETTAGLIO - 1].rstrip() + '…'
    lista.append({'riga': riga, 'colonna': colonna, 'codice': codice, 'dettaglio': dettaglio})


def _testo_cella(v):
    if v is None:
        return ''
    if isinstance(v, float):
        return repr(v) if not v.is_integer() else str(int(v))
    return str(v).strip()


def _colorata(cella):
    """La cella ha uno sfondo (nel master: giorno di alunno assente, o altri segni a mano)."""
    riempimento = getattr(cella, 'fill', None)
    if riempimento is None or riempimento.fill_type != 'solid':
        return False
    colore = riempimento.fgColor
    if colore is None:
        return False
    if colore.type == 'rgb':
        return str(colore.rgb).upper() not in ('00000000', 'FFFFFFFF')
    if colore.type == 'theme':                   # il primo colore del tema senza tinta e' il bianco dello sfondo
        return not (colore.theme == 0 and not colore.tint)
    if colore.type == 'indexed':                 # 9 = bianco, 64 = colore di sistema
        return colore.indexed not in (9, 64)
    return False


def _lettura_cella(valore):
    """La cella di un giorno: lettura di napoli_calcoli.leggi_cella_master piu', per i
    numeri che non sono quarti d'ora e le cui cifre possono essere minuti ('1,30'), le
    due letture possibili: la scelta si fa nell'anteprima ed e' obbligatoria (non ce n'e'
    una gia' scelta). Finche' non si sceglie, i minuti sono quelli della lettura decimale,
    la regola del master (PROGETTO §5.1)."""
    lettura = calc.leggi_cella_master(valore)
    lettura['alternative'] = []
    if lettura['esito'] == 'ore' and 'ore_non_multiple_di_un_quarto' in lettura['avvisi'] \
            and not isinstance(valore, (datetime.time, datetime.timedelta)):
        alternative = calc.letture_possibili(_testo_cella(valore))
        if alternative:
            lettura['alternative'] = alternative
            lettura['esito'] = 'da_confermare'
            lettura['minuti'] = next(a['minuti'] for a in alternative if a['lettura'] == 'decimale')
    return lettura


def leggi_master(dati, nome_file='', regole=None):
    """Legge il file (bytes) senza toccare il database. Ritorna:
    {'foglio', 'fogli', 'anno', 'mese', 'colonne' {nome: lettera}, 'giorni' [date],
     'settimane' [[date]], 'righe' [...], 'anomalie' [{riga, colonna, codice, dettaglio}],
     'riepilogo_foglio' {...}}.
    Ogni riga: riga del foglio, lotto, operatore e alunno ({nome_completo, cognome,
    nome, separazione, cf, cf_esito}), qualifica, data di inizio (e la proposta),
    ore di contratto e da progetto, municipalita', scuola {testo, nome, codice},
    sostituzione, note, celle {data: lettura con 'colonna'}, celle colorate.
    Errori (DatiNonValidi, campo 'file'): file non leggibile o foglio sbagliato."""
    wb, wbf = _apri(dati, nome_file)
    ws, (indice_intestazione, intestazione) = _trova_foglio(wb)
    wsf = wbf[ws.title]
    anomalie = []
    riga_intestazione = indice_intestazione + 1
    col, giorni_col, verifiche_col, avvisi = trova_colonne(intestazione)
    for a in avvisi:
        _anomalia(anomalie, riga_intestazione, get_column_letter(col['scuola'] + 1), a)
    ultima_colonna = max(j for j, v in enumerate(intestazione) if v not in (None, '')) + 1

    contati = collections.Counter((d.year, d.month) for _, d in giorni_col)
    anno, mese = contati.most_common(1)[0][0]
    giorni_mese = []
    for j, d in giorni_col:
        if (d.year, d.month) != (anno, mese):
            _anomalia(anomalie, riga_intestazione, get_column_letter(j + 1), 'giorno_di_altro_mese', calc.data_it(d))
        elif d in giorni_mese:
            _anomalia(anomalie, riga_intestazione, get_column_letter(j + 1), 'colonna_giorno_doppia', calc.data_it(d))
        else:
            giorni_mese.append(d)
            if d.weekday() == 6:
                _anomalia(anomalie, riga_intestazione, get_column_letter(j + 1), 'colonna_domenica',
                          calc.data_it(d))
    attesi = [d for t, d in calc.colonne_mese(anno, mese, (0, 1, 2, 3, 4, 5)) if t == 'giorno']
    if giorni_mese != attesi:
        _anomalia(anomalie, riga_intestazione, None, 'colonne_giorni_non_standard')
    colonne_giorno = [(j, d) for j, d in giorni_col if (d.year, d.month) == (anno, mese)]
    usate = set()
    colonne_giorno = [(j, d) for j, d in colonne_giorno if not (d in usate or usate.add(d))]
    altre_colonne = [(j, d) for j, d in giorni_col if (j, d) not in colonne_giorno]

    # settimane: i giorni prima di ogni VERIFICA
    settimane, corrente = [], []
    for j, tipo, d in sorted([(j, 'g', d) for j, d in colonne_giorno] + [(j, 'v', None) for j in verifiche_col],
                             key=lambda x: x[0]):
        if tipo == 'g':
            corrente.append((j, d))
        elif corrente:
            settimane.append({'verifica_col': j, 'giorni': corrente})
            corrente = []
    if corrente:
        settimane.append({'verifica_col': None, 'giorni': corrente})
        _anomalia(anomalie, riga_intestazione, None, 'settimana_senza_verifica')

    righe, vuote = [], 0
    for n_riga, celle_riga in enumerate(ws.iter_rows(min_row=riga_intestazione + 1, max_col=ultima_colonna),
                                        start=riga_intestazione + 1):
        valori = [c.value for c in celle_riga]

        def cella(chiave):
            j = col.get(chiave)
            return valori[j] if j is not None and j < len(valori) else None

        fisse = [cella(k) for k in ('operatore', 'cf_operatore', 'alunno', 'cf_alunno', 'qualifica')]
        valori_giorni = [valori[j] if j < len(valori) else None for j, _ in giorni_col]
        if all(v in (None, '') for v in fisse) and all(v in (None, '') for v in valori_giorni):
            vuote += 1
            if vuote > RIGHE_VUOTE_FINE:
                break
            continue
        vuote = 0
        if normalizza(cella('operatore')).startswith('total'):
            continue
        righe.append(_leggi_riga(n_riga, celle_riga, valori, cella, col, colonne_giorno, altre_colonne, settimane,
                                 wsf, anno, mese, regole, anomalie))

    _controlli_incrociati(righe, anno, mese, regole, anomalie)
    riepilogo = _confronta_riepilogo(wb, righe)
    if riepilogo['presente'] and riepilogo['non_allineati']:
        _anomalia(anomalie, None, None, 'riepilogo_non_allineato',
                  f'{riepilogo["non_allineati"]} operatori su {riepilogo["operatori"]}')
    return {
        'foglio': ws.title, 'fogli': [w.title for w in wb.worksheets], 'anno': anno, 'mese': mese,
        'colonne': {k: get_column_letter(j + 1) for k, j in col.items()},
        'giorni': [d for _, d in colonne_giorno],
        'settimane': [[d for _, d in s['giorni']] for s in settimane],
        'righe': righe, 'anomalie': anomalie, 'riepilogo_foglio': riepilogo,
    }


def _leggi_riga(n_riga, celle_riga, valori, cella, col, colonne_giorno, altre_colonne, settimane, wsf, anno, mese,
                regole, anomalie):
    def avviso(colonna, codice, dettaglio=None):
        j = col.get(colonna) if isinstance(colonna, str) else colonna
        _anomalia(anomalie, n_riga, get_column_letter(j + 1) if j is not None else None, codice, dettaglio)

    cf_op, esito_op = calc.esito_codice_fiscale(cella('cf_operatore'))
    cf_al, esito_al = calc.esito_codice_fiscale(cella('cf_alunno'))
    if esito_op != 'ok':
        avviso('cf_operatore', 'cf_operatore_' + esito_op)
    if esito_al == 'controllo':
        avviso('cf_alunno', 'cf_alunno_controllo')
    nome_op, nome_al = pulito(cella('operatore')), pulito(cella('alunno'))
    cog_op, nom_op, sep_op = separa_cognome_nome(nome_op, cf_op)
    cog_al, nom_al, sep_al = separa_cognome_nome(nome_al, cf_al)

    qualifica_scritta = cella('qualifica')
    qualifica = pulito(qualifica_scritta)
    if qualifica and qualifica != str(qualifica_scritta or ''):
        avviso('qualifica', 'qualifica_spazi_irregolari', qualifica)

    lotto, lotto_scritto = None, cella('lotto')
    if lotto_scritto in (None, ''):
        avviso('lotto', 'lotto_mancante')
    else:
        numeri = re.findall(r'\d+', str(lotto_scritto))
        lotto = int(numeri[0]) if len(numeri) == 1 else None
        if lotto is None:
            avviso('lotto', 'lotto_non_riconosciuto', lotto_scritto)
    municipalita, avviso_mun = leggi_municipalita(cella('municipalita'))
    if cella('municipalita') in (None, ''):
        avviso('municipalita', 'municipalita_mancante')
    elif avviso_mun:
        avviso('municipalita', avviso_mun, cella('municipalita'))

    data_inizio, avviso_data, proposta = leggi_data_inizio(cella('data_inizio'), anno, mese)
    if avviso_data:
        avviso('data_inizio', avviso_data, calc.data_it(proposta) if proposta else None)
    ore_contratto, contratto_var, contratto_testo = leggi_ore_settimanali(cella('ore_contratto'))
    if contratto_testo:
        avviso('ore_contratto', 'ore_contratto_con_testo' + ('_variazione' if contratto_var else ''),
               _testo_cella(cella('ore_contratto')))
    ore_progetto, _var, progetto_testo = leggi_ore_settimanali(cella('ore_progetto'))
    if progetto_testo:
        avviso('ore_progetto', 'ore_progetto_con_testo', _testo_cella(cella('ore_progetto')))
    if ore_progetto is None:
        avviso('ore_progetto', 'ore_progetto_mancanti')

    nome_scuola, codice_scuola, avvisi_scuola = leggi_scuola(cella('scuola'))
    for a in avvisi_scuola:
        avviso('scuola', a)
    sostituzione_scritta = cella('sostituzione')
    sostituzione = leggi_sostituzione(sostituzione_scritta)
    if sostituzione is None:
        avviso('sostituzione', 'sostituzione_mancante' if sostituzione_scritta in (None, '')
               else 'sostituzione_non_riconosciuta', None if sostituzione_scritta in (None, '')
               else _testo_cella(sostituzione_scritta))
    elif str(sostituzione_scritta) != str(sostituzione_scritta).strip():
        avviso('sostituzione', 'sostituzione_spazi_irregolari')

    celle, colorate = {}, 0
    for j, d in colonne_giorno:
        v = valori[j] if j < len(valori) else None
        lettura = _lettura_cella(v)
        lettura['colonna'] = get_column_letter(j + 1)
        lettura['testo'] = _testo_cella(v)
        celle[d] = lettura
        if j < len(celle_riga) and _colorata(celle_riga[j]):
            colorate += 1
        for a in lettura['avvisi']:
            if a != 'ore_non_multiple_di_un_quarto' or lettura['esito'] != 'da_confermare':
                avviso(j, a, lettura['testo'])
        if lettura['esito'] == 'errore':
            avviso(j, lettura['codice'], lettura['testo'])
        if lettura['minuti']:
            for c in calc.controlla_minuti_giorno(lettura['minuti'], regole):
                avviso(j, c['codice'], lettura['testo'])
        if d.weekday() == 5 and lettura['esito'] != 'vuoto':
            avviso(j, 'attivita_di_sabato', lettura['testo'])
    for j, d in altre_colonne:
        v = valori[j] if j < len(valori) else None
        if v not in (None, ''):
            avviso(j, 'ore_in_colonna_di_altro_mese', calc.data_it(d))

    verifiche = []
    for k, s in enumerate(settimane, start=1):
        minuti = sum(celle[d]['minuti'] or 0 for _, d in s['giorni'])
        vc = s['verifica_col']
        scritto = valori[vc] if vc is not None and vc < len(valori) else None
        formula = wsf.cell(n_riga, vc + 1).value if vc is not None else None
        verifiche.append({'settimana': k, 'minuti': minuti})
        if vc is None:
            continue
        if not (isinstance(formula, str) and formula.startswith('=')):
            avviso(vc, 'verifica_senza_formula' if formula is not None else 'verifica_vuota',
                   None if formula is None else _testo_cella(formula))
        if isinstance(scritto, (int, float)) and not isinstance(scritto, bool) \
                and calc.minuti_da_ore(scritto)[0] != minuti:
            solo_numeri = sum(calc.minuti_da_ore(valori[j])[0] for j, _ in s['giorni']
                              if j < len(valori) and isinstance(valori[j], (int, float))
                              and not isinstance(valori[j], bool))
            codice = ('verifica_esclude_numeri_come_testo' if calc.minuti_da_ore(scritto)[0] == solo_numeri
                      else 'verifica_diversa_dalla_somma')
            avviso(vc, codice, f'{calc.numero_it(scritto)} invece di {calc.numero_it(calc.ore_decimali(minuti))}')

    note = cella('note')
    return {
        'riga': n_riga, 'lotto': lotto,
        'operatore': {'nome_completo': nome_op, 'cognome': cog_op, 'nome': nom_op, 'separazione': sep_op,
                      'cf': cf_op, 'cf_esito': esito_op},
        'alunno': {'nome_completo': nome_al, 'cognome': cog_al, 'nome': nom_al, 'separazione': sep_al,
                   'cf': cf_al, 'cf_esito': esito_al},
        'qualifica': qualifica, 'data_inizio': data_inizio, 'data_inizio_proposta': proposta,
        'avviso_data_inizio': avviso_data,
        'ore_contratto': ore_contratto, 'ore_contratto_variazione': contratto_var, 'ore_progetto': ore_progetto,
        'municipalita': municipalita,
        'scuola': {'testo': pulito(cella('scuola')), 'nome': nome_scuola, 'codice': codice_scuola},
        'sostituzione': sostituzione,
        'note': str(note).strip() if note not in (None, '') else '',
        'giorni_assente_note': giorni_alunno_assente(note),
        'celle': celle, 'colorate': colorate, 'verifiche': verifiche,
        'minuti': sum(c['minuti'] or 0 for c in celle.values()),
    }


def giorni_alunno_assente(testo):
    """Giorni citati come assenza dell'alunno ('Alunno assente: 6,17,18', 'assente dal 4
    al 6'): solo una segnalazione (nella fase 2 diventeranno proposte da confermare)."""
    n = normalizza(testo)
    giorni = set()
    for m in re.finditer(r'(?:a+s+ent[ea]|assentat[oa])\b([^.;]*)', n):
        parte = re.split(r"\bl.op|\bha\b|\bil giorno \d+ ?,? ?l", m.group(1))[0]
        parte = re.sub(r'\([^)]*\)?', ' ', parte)
        for a, b in re.findall(r'dal\s*(\d{1,2})\s*al\s*(\d{1,2})', parte):
            giorni.update(range(int(a), int(b) + 1))
        parte = re.sub(r'dal\s*\d{1,2}\s*al\s*\d{1,2}', ' ', parte)
        giorni.update(int(d) for d in re.findall(r'(?<![/\d])(\d{1,2})(?![/\d])', parte))
    return sorted(g for g in giorni if 1 <= g <= 31)


def _chiave_operatore_file(r):
    """Lo stesso operatore nel file: stesso codice fiscale (anche se sbagliato; con 16
    caratteri basta la radice, cosi' un codice con l'ultimo carattere sbagliato e' la stessa
    persona del codice giusto) o, senza codice, stesso nome."""
    op = r['operatore']
    return ('cf', radice_cf(op['cf']) or op['cf']) if op['cf'] else ('nome', op['nome_completo'])


def _chiave_alunno_file(cf):
    return radice_cf(cf) or cf


def _controlli_incrociati(righe, anno, mese, regole, anomalie):
    fine = calc.fine_mese(anno, mese)
    inizio_as = datetime.date(anno if mese >= 9 else anno - 1, 9, 1)
    per_operatore, per_alunno = collections.defaultdict(list), collections.defaultdict(list)
    for r in righe:
        per_operatore[_chiave_operatore_file(r)].append(r)
        if r['alunno']['cf']:
            per_alunno[_chiave_alunno_file(r['alunno']['cf'])].append(r)
        con_ore = sorted(d for d, c in r['celle'].items() if c['minuti'])
        if not any(c['esito'] != 'vuoto' for c in r['celle'].values()):
            _anomalia(anomalie, r['riga'], None, 'riga_senza_attivita')
        di = r['data_inizio']
        if di and di > fine:
            _anomalia(anomalie, r['riga'], None, 'data_inizio_futura_con_ore' if con_ore else 'data_inizio_dopo_il_mese',
                      calc.data_it(di))
        elif di and con_ore and con_ore[0] < di:
            _anomalia(anomalie, r['riga'], None, 'ore_prima_della_data_inizio', calc.data_it(di))
        if di and di < inizio_as:
            _anomalia(anomalie, r['riga'], None, 'data_inizio_prima_dell_anno_scolastico', calc.data_it(di))
        if r['ore_progetto'] and not r['sostituzione']:
            minuti_giorni = {d: c['minuti'] or 0 for d, c in r['celle'].items()}
            for v in calc.verifica_settimane(minuti_giorni, anno, mese, r['ore_progetto'], regole):
                if v['codice'] in ('settimana_oltre_pei', 'settimana_oltre_pei_piu_20'):
                    _anomalia(anomalie, r['riga'], None, v['codice'],
                              f'settimana {v["settimana"]}: {calc.numero_it(calc.ore_decimali(v["minuti"]))} ore, '
                              f'PEI {calc.numero_it(r["ore_progetto"])}')
        dichiarati = set(r['giorni_assente_note'])
        for d, c in r['celle'].items():
            if d.day in dichiarati and c['esito'] == 'sigla':
                _anomalia(anomalie, r['riga'], c['colonna'], 'alunno_assente_e_operatore_assente', c['testo'])

    for lista in per_operatore.values():
        if len({x['operatore']['nome_completo'] for x in lista}) > 1:
            for x in lista:
                _anomalia(anomalie, x['riga'], None, 'operatore_stesso_cf_nomi_diversi')
        if len({x['qualifica'] for x in lista}) > 1:
            for x in lista:
                _anomalia(anomalie, x['riga'], None, 'operatore_qualifica_scritta_diversa')
        if all(x['ore_contratto'] is None for x in lista) and not all(x['sostituzione'] for x in lista):
            _anomalia(anomalie, lista[0]['riga'], None, 'operatore_senza_ore_contratto')
        for d in lista[0]['celle']:
            esiti = [x['celle'][d]['esito'] for x in lista]
            if 'sigla' in esiti and any(x['celle'][d]['minuti'] for x in lista):
                _anomalia(anomalie, lista[0]['riga'], None, 'assenza_operatore_parziale', calc.data_it(d))
    for lista in per_alunno.values():
        if len({x['alunno']['nome_completo'] for x in lista}) > 1:
            for x in lista:
                _anomalia(anomalie, x['riga'], None, 'alunno_stesso_cf_nomi_diversi')


def _confronta_riepilogo(wb, righe):
    """Il foglio 'riepilogo' (per operatore: somma delle ore di contratto e da progetto)
    confrontato con il master. Solo un controllo: nel file vero non e' aggiornato."""
    ws = next((w for w in wb.worksheets if normalizza(w.title).startswith('riepilog')), None)
    if ws is None:
        return {'presente': False, 'operatori': 0, 'allineati': 0, 'non_allineati': 0}
    attese = collections.defaultdict(lambda: [calc.decimale(0), calc.decimale(0)])
    for r in righe:
        k = r['operatore']['cf']
        if r['ore_contratto'] is not None and not r['ore_contratto_variazione']:
            attese[k][0] += r['ore_contratto']
        attese[k][1] += r['ore_progetto'] or 0
    trovati = allineati = 0
    c_cf = c_contratto = c_progetto = None
    for riga in ws.iter_rows(values_only=True):
        celle = [normalizza(c) for c in riga]
        if c_cf is None:
            for j, c in enumerate(celle):
                if c.startswith('cf'):
                    c_cf = j
                elif 'contratto' in c:
                    c_contratto = j
                elif 'progetto' in c:
                    c_progetto = j
            continue
        cf = re.sub(r'\s', '', str(riga[c_cf] or '')).upper() if c_cf < len(riga) else ''
        if not cf or 'total' in celle[c_cf]:
            continue
        trovati += 1
        a = attese.get(cf)

        def numero(j):
            v = riga[j] if j is not None and j < len(riga) else None
            return calc.decimale(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else calc.decimale(0)
        if a and numero(c_contratto) == a[0] and numero(c_progetto) == a[1]:
            allineati += 1
    return {'presente': True, 'operatori': trovati, 'allineati': allineati, 'non_allineati': trovati - allineati}


# ==================== spiegazioni degli avvisi (parole semplici) ====================

# codice -> (livello, titolo, cosa fare). Livelli: 'bloccante' (da correggere prima di
# importare), 'avviso' (da controllare), 'nota' (il programma ha gia' capito: niente da fare).
SPIEGAZIONI = {
    # ---- bloccanti
    'mese_chiuso': ('bloccante', 'Il mese del lotto è chiuso',
                    'Per importare di nuovo questo mese bisogna prima riaprirlo.'),
    'riga_di_altro_lotto': ('bloccante', 'Righe di un altro lotto',
                            'Nella colonna Lotto c\'è un numero diverso dal lotto scelto: scegli il lotto giusto '
                            'in alto, oppure correggi il numero nel file.'),
    'qualifica_non_collegata': ('bloccante', 'Qualifica da collegare a una figura',
                                'Scegli la figura professionale nella tabella «Qualifiche nuove» qui sotto.'),
    'qualifica_mancante': ('bloccante', 'Qualifica mancante', 'Scrivi la qualifica dell\'operatore nel file.'),
    'cf_alunno_non_valido': ('bloccante', 'Codice fiscale dell\'alunno mancante o sbagliato',
                             'L\'alunno si riconosce dal codice fiscale (16 caratteri): correggilo nel file.'),
    'riga_senza_alunno': ('bloccante', 'Riga senza alunno', 'Mancano nome e codice fiscale dell\'alunno.'),
    'alunno_senza_nome': ('bloccante', 'Alunno senza nome', 'Scrivi cognome e nome dell\'alunno nel file.'),
    'riga_senza_operatore': ('bloccante', 'Riga senza operatore', 'Mancano nome e codice fiscale dell\'operatore.'),
    'riga_senza_scuola': ('bloccante', 'Riga senza scuola', 'Scrivi la scuola (con il codice meccanografico).'),
    'coppia_doppia': ('bloccante', 'La stessa coppia operatore-alunno su due righe',
                      'Metti le ore della stessa coppia su una riga sola (o segna SI sulla riga del sostituto).'),
    'sigla_sconosciuta': ('bloccante', 'Scritte che non sono ore né sigle',
                          'Nei giorni si scrivono le ore (per esempio 2 o 1,5) o le sigle F, M, F perm: '
                          'correggi la cella.'),
    'cella_non_riconosciuta': ('bloccante', 'Celle che non si capiscono',
                               'Nella cella c\'è una data o un valore che non è un numero di ore: correggila.'),
    'ore_negative': ('bloccante', 'Ore negative', 'Correggi la cella.'),
    'ore_giorno_oltre_12': ('bloccante', 'Più di 12 ore in un giorno',
                            'Quasi certamente un errore di battitura: correggi la cella.'),
    'ore_in_colonna_di_altro_mese': ('bloccante', 'Ore in una colonna con la data di un altro mese',
                                     'Correggi la data in cima alla colonna o sposta le ore.'),
    'colonna_giorno_doppia': ('bloccante', 'Lo stesso giorno in due colonne',
                              'Correggi la data in cima a una delle due colonne.'),
    # ---- da controllare
    'cf_operatore_controllo': ('avviso', 'Codice fiscale dell\'operatore con l\'ultimo carattere sbagliato',
                               'L\'operatore si riconosce lo stesso. Correggi il codice nel file del mese '
                               'prossimo: quando arriva giusto, si corregge da solo anche in Assisto.'),
    'cf_operatore_formato': ('avviso', 'Codice fiscale dell\'operatore scritto male',
                             'L\'operatore si riconosce dal nome. Correggi il codice nel file del mese prossimo: '
                             'quando arriva giusto, si corregge anche in Assisto.'),
    'cf_operatore_vuoto': ('avviso', 'Codice fiscale dell\'operatore mancante', 'L\'operatore si riconosce dal nome.'),
    'cf_alunno_controllo': ('avviso', 'Codice fiscale dell\'alunno con l\'ultimo carattere sbagliato',
                            'Se in Assisto c\'è già lo stesso alunno con il codice giusto si usa quello; '
                            'altrimenti si salva come è scritto. Controllalo con la scuola e correggilo nel file '
                            'del mese prossimo: quando arriva giusto, si corregge da solo anche in Assisto.'),
    'cf_alunno_giusto_in_assisto': ('nota', 'Codice fiscale dell\'alunno giusto in Assisto',
                                    'Nel file l\'ultimo carattere è sbagliato, in Assisto c\'è lo stesso alunno con '
                                    'il codice giusto: si usa quello.'),
    'cf_alunno_corretto_in_assisto': ('avviso', 'Codice fiscale dell\'alunno corretto in Assisto',
                                      'In Assisto l\'alunno aveva il codice con l\'ultimo carattere sbagliato; nel '
                                      'file è giusto: si corregge anche in Assisto (è sempre lo stesso alunno).'),
    'cf_operatore_corretto_in_assisto': ('avviso', 'Codice fiscale dell\'operatore corretto in Assisto',
                                         'In Assisto l\'operatore aveva il codice con l\'ultimo carattere sbagliato; '
                                         'nel file è giusto: si corregge anche in Assisto.'),
    'alunno_omonimo_in_assisto': ('avviso', 'Alunno con lo stesso nome di uno già in Assisto, ma un altro codice fiscale',
                                  'Si crea un alunno nuovo. Se invece è lo stesso alunno, uno dei due codici fiscali è '
                                  'sbagliato: controllalo con la scuola.'),
    'operatore_omonimo_in_assisto': ('avviso', 'Operatore con lo stesso nome di uno già in Assisto, ma un altro '
                                     'codice fiscale',
                                     'Si crea un operatore nuovo. Se invece è la stessa persona, uno dei due codici '
                                     'fiscali è sbagliato: controllalo.'),
    'municipalita_mancante': ('avviso', 'Municipalità mancante',
                              'La municipalità è quella della scuola: se la scuola compare in una sola '
                              'municipalità si prende quella, altrimenti resta da completare.'),
    'municipalita_non_riconosciuta': ('avviso', 'Municipalità che non si capisce', 'Scrivi solo il numero.'),
    'municipalita_presa_dalla_scuola': ('nota', 'Municipalità presa dalla scuola',
                                        'Nella riga mancava: è quella della stessa scuola nelle altre righe o in '
                                        'Assisto.'),
    'municipalita_completata_in_assisto': ('avviso', 'Municipalità aggiunta a una scuola di Assisto',
                                           'In Assisto la scuola non aveva la municipalità: si aggiunge quella del '
                                           'file (indicata a fianco).'),
    'lotto_mancante': ('avviso', 'Numero del lotto mancante', 'Vale il lotto scelto in alto.'),
    'lotto_non_riconosciuto': ('avviso', 'Numero del lotto che non si capisce', 'Vale il lotto scelto in alto.'),
    'data_inizio_scritta_male': ('nota', 'Data di inizio scritta male, corretta',
                                 'Per esempio la lettera O al posto dello zero.'),
    'data_inizio_anno_errato': ('avviso', 'Data di inizio con l\'anno sbagliato',
                                'Si usa la data proposta (indicata a fianco).'),
    'data_inizio_non_leggibile': ('avviso', 'Data di inizio che non si capisce',
                                  'La coppia comincia dal primo giorno del mese.'),
    'data_inizio_futura_con_ore': ('avviso', 'Data di inizio dopo il mese, ma con ore nel mese',
                                   'La coppia comincia dal primo giorno del mese: correggi la data nel file.'),
    'data_inizio_dopo_il_mese': ('nota', 'Data di inizio dopo il mese, senza ore',
                                 'La coppia comincerà da quella data.'),
    'ore_prima_della_data_inizio': ('avviso', 'Ore prima della data di inizio',
                                    'La coppia comincia dal primo giorno del mese: controlla la data.'),
    'data_inizio_prima_dell_anno_scolastico': ('avviso', 'Data di inizio prima dell\'anno scolastico',
                                               'Controlla la data.'),
    'ore_progetto_mancanti': ('avviso', 'Ore da progetto (PEI) mancanti', 'Senza ore da progetto non si controllano '
                              'le settimane.'),
    'ore_progetto_fuori_limite': ('avviso', 'Ore da progetto oltre 40 alla settimana',
                                  'Non si salvano come PEI: controlla il numero.'),
    'ore_contratto_con_testo': ('nota', 'Ore di contratto scritte con del testo', 'Si legge il numero.'),
    'ore_contratto_con_testo_variazione': ('nota', 'Ore di contratto con una variazione («con var»)',
                                           'Si legge il numero scritto.'),
    'ore_progetto_con_testo': ('nota', 'Ore da progetto scritte con del testo', 'Si legge il numero.'),
    'sostituzione_mancante': ('avviso', 'Colonna Sostituzione vuota', 'La riga vale come titolare (NO).'),
    'sostituzione_non_riconosciuta': ('avviso', 'Sostituzione che non è SI o NO', 'La riga vale come titolare (NO).'),
    'ore_giorno_oltre_5': ('avviso', 'Più di 5 ore in un giorno', 'Succede con i recuperi: controlla che sia giusto.'),
    'ore_non_multiple_di_un_quarto': ('avviso', 'Ore che non sono quarti d\'ora', 'Si leggono come ore decimali.'),
    'ore_arrotondate_al_minuto': ('nota', 'Ore arrotondate al minuto', 'Il valore aveva dei secondi.'),
    'cella_in_formato_orario': ('avviso', 'Cella scritta come orario', 'Si legge come durata (per esempio 1:30 = '
                                'un\'ora e mezza).'),
    'attivita_di_sabato': ('nota', 'Ore di sabato', 'Il sabato è un giorno di servizio.'),
    'colonna_domenica': ('avviso', 'Colonna di domenica', 'Le ore di domenica non entrano nelle settimane.'),
    'giorno_di_altro_mese': ('avviso', 'Colonna con la data di un altro mese', 'Non si importa.'),
    'colonne_giorni_non_standard': ('nota', 'Colonne dei giorni diverse dal solito',
                                    'Mancano o ci sono in più alcuni giorni rispetto a lunedì-sabato.'),
    'riga_senza_attivita': ('avviso', 'Riga senza ore né sigle', 'La coppia si crea, senza ore nel mese.'),
    'settimana_oltre_pei': ('avviso', 'Settimana con più ore del PEI', 'Controlla le ore della settimana.'),
    'settimana_oltre_pei_piu_20': ('avviso', 'Settimana oltre il PEI più il 20%',
                                   'Oltre il limite del capitolato: controlla le ore.'),
    'alunno_settimana_oltre_pei_tra_operatori': ('avviso', 'Più operatori della stessa figura oltre il PEI',
                                                 'Sommando le righe dello stesso alunno e della stessa figura la '
                                                 'settimana supera il PEI.'),
    'alunno_assente_e_operatore_assente': ('avviso', 'Alunno assente e operatore assente nello stesso giorno',
                                           'Controlla la nota e la sigla.'),
    'assenza_operatore_parziale': ('avviso', 'Operatore assente solo su alcune righe dello stesso giorno',
                                   'Lo stesso giorno ha una sigla su una riga e ore su un\'altra: controlla.'),
    'operatore_stesso_cf_nomi_diversi': ('avviso', 'Stesso operatore scritto in due modi',
                                         'Stesso codice fiscale, nome scritto diversamente: vale la prima riga.'),
    'operatore_con_piu_figure': ('avviso', 'Operatore con due figure',
                                 'Lo stesso operatore ha righe con figure diverse, o una figura diversa da quella '
                                 'che ha in Assisto: ogni riga vale con la sua figura. Controlla la qualifica.'),
    'operatore_qualifica_scritta_diversa': ('nota', 'Qualifica dello stesso operatore scritta in modi diversi',
                                            'Si usa la figura di ogni riga.'),
    'operatore_senza_ore_contratto': ('avviso', 'Operatore senza ore di contratto', 'Completa le ore nel file.'),
    'alunno_stesso_cf_nomi_diversi': ('avviso', 'Stesso alunno scritto in due modi',
                                      'Stesso codice fiscale, nome scritto diversamente: vale la prima riga.'),
    'alunno_pei_diverso_stessa_figura': ('avviso', 'PEI diverso per lo stesso alunno e la stessa figura',
                                         'Vale il numero più alto: controlla.'),
    'alunno_nome_diverso_in_assisto': ('avviso', 'Alunno già in Assisto con un nome scritto diversamente',
                                       'Resta il nome di Assisto (stesso codice fiscale).'),
    'alunno_di_altro_lotto': ('avviso', 'Alunno già in Assisto in un altro lotto',
                              'La coppia è di questo lotto; l\'alunno resta com\'è.'),
    'operatore_nome_diverso_in_assisto': ('avviso', 'Operatore già in Assisto con un nome scritto diversamente',
                                          'Resta il nome di Assisto (stesso codice fiscale).'),
    'operatori_omonimi_in_assisto': ('avviso', 'Più operatori con lo stesso nome in Assisto',
                                     'Senza un codice fiscale valido non si sa quale: si crea un operatore nuovo.'),
    'sostituto_senza_titolare': ('avviso', 'Sostituto senza il titolare',
                                 'Non c\'è la riga del titolare (stesso alunno e stessa figura): controlla.'),
    'coppia_scuola_diversa': ('avviso', 'Coppia già in Assisto con un\'altra scuola',
                              'Resta la scuola di Assisto (la scuola scritta nel file non si aggiunge): se l\'alunno '
                              'ha cambiato scuola, sistemalo nelle anagrafiche.'),
    'coppia_riaperta': ('avviso', 'Coppia chiusa che ha di nuovo ore',
                        'Il titolare era stato chiuso (per esempio con un cambio di operatore) e nel file ha di nuovo '
                        'ore: la coppia si riapre.'),
    'coppia_del_mese_non_nel_file': ('avviso', 'Coppia di questo mese che nel file non c\'è più',
                                     'Le sue ore importate prima si tolgono, la coppia resta in Assisto senza ore '
                                     '(vedi «Coppie che nel file non ci sono più»).'),
    'pei_diverso_in_assisto': ('avviso', 'PEI diverso da quello in Assisto',
                               'Il PEI di Assisto per questo mese non si cambia da qui: controllalo nelle anagrafiche.'),
    'righe_del_coordinatore': ('avviso', 'Righe del coordinatore',
                               'Le ore del coordinatore si scrivono nella fattura (totale del mese): queste righe '
                               'non si importano.'),
    # ---- note
    'intestazione_scuola_errata': ('nota', 'La colonna della scuola ha l\'intestazione «2»',
                                   'Come nel file del Comune: la scuola si legge lo stesso.'),
    'numero_come_testo': ('nota', 'Ore scritte come testo', 'Si leggono lo stesso (in Excel la VERIFICA non le '
                          'somma).'),
    'sigla_scritta_in_variante': ('nota', 'Sigle scritte in modi diversi',
                                  'Per esempio f, Fperm, F (PERM): si leggono lo stesso.'),
    'qualifica_spazi_irregolari': ('nota', 'Qualifiche con spazi in più', 'Si leggono lo stesso.'),
    'scuola_parentesi_non_chiusa': ('nota', 'Scuola con la parentesi non chiusa', 'Si legge lo stesso.'),
    'scuola_codice_sospetto': ('nota', 'Codice meccanografico con un numero al posto di una lettera',
                               'Per le paritarie (NA1A, NA1E, NA1M) è normale; il codice non si corregge.'),
    'scuola_senza_codice': ('avviso', 'Scuola senza codice meccanografico', 'La scuola si riconosce dal nome.'),
    'scuola_spazi_irregolari': ('nota', 'Scuola con spazi o a capo in più', 'Si legge lo stesso.'),
    'sostituzione_spazi_irregolari': ('nota', 'SI o NO con spazi in più', 'Si legge lo stesso.'),
    'verifica_senza_formula': ('nota', 'VERIFICA scritta a mano', 'Le ore si contano dai giorni, non dalla VERIFICA.'),
    'verifica_vuota': ('nota', 'VERIFICA vuota', 'Le ore si contano dai giorni, non dalla VERIFICA.'),
    'verifica_esclude_numeri_come_testo': ('nota', 'VERIFICA che non conta le ore scritte come testo',
                                           'Le ore si contano dai giorni: qui il totale è giusto.'),
    'verifica_diversa_dalla_somma': ('avviso', 'VERIFICA diversa dalla somma dei giorni',
                                     'Valgono le ore dei giorni: controlla la settimana.'),
    'settimana_senza_verifica': ('nota', 'Settimana senza colonna VERIFICA', 'Le ore si contano dai giorni.'),
    'riepilogo_non_allineato': ('nota', 'Il foglio «riepilogo» non è aggiornato',
                                'Non si usa: le ore si contano dal foglio presenze.'),
}


def spiegazione(codice):
    return SPIEGAZIONI.get(codice, ('avviso', codice.replace('_', ' ').capitalize(), ''))


def _gruppi(anomalie):
    """Avvisi raggruppati per codice, nell'ordine bloccanti, avvisi, note: [{codice,
    livello, titolo, spiegazione, n, righe: [{riga, colonna, dettaglio}]}] (mai nomi o CF)."""
    per_codice = collections.OrderedDict()
    for a in anomalie:
        per_codice.setdefault(a['codice'], []).append(a)
    ordine = {'bloccante': 0, 'avviso': 1, 'nota': 2}
    out = []
    for codice, lista in per_codice.items():
        livello, titolo, testo = spiegazione(codice)
        out.append({'codice': codice, 'livello': livello, 'titolo': titolo, 'spiegazione': testo, 'n': len(lista),
                    'righe': [{k: a.get(k) for k in ('riga', 'colonna', 'dettaglio')}
                              for a in lista[:MAX_RIGHE_PER_AVVISO]]})
    return sorted(out, key=lambda g: (ordine[g['livello']], -g['n']))


# ==================== dati di Napoli che servono all'import ====================

def _righe(conn, sql, parametri=()):
    return [dict(r) for r in conn.execute(sql, parametri)]


def _ora():
    return datetime.datetime.now().isoformat(timespec='seconds')


def mese_testo(anno, mese):
    return f'{MESI[mese - 1]} {anno}'


def _contesto(conn, lotto_id, anno, mese):
    """Tutto quello che l'import guarda nel database, letto una volta (solo tabelle napoli_*)."""
    lotto = napoli_db.lotto(lotto_id, conn)
    inizio, fine = datetime.date(anno, mese, 1), calc.fine_mese(anno, mese)
    regole = _righe(conn, 'SELECT * FROM napoli_regole WHERE lotto_id IS NULL OR lotto_id = ? ORDER BY id', (lotto_id,))
    ctx = {
        'lotto': lotto, 'anno': anno, 'mese': mese, 'inizio': inizio, 'fine': fine,
        'regole': calc.regole_alla_data(inizio, regole, lotto_id),
        'figure': {f['codice']: f for f in _righe(conn, 'SELECT * FROM napoli_figure ORDER BY ordine')},
        'alias': {a['testo']: a['figura'] for a in _righe(conn, 'SELECT testo, figura FROM napoli_alias_qualifiche')},
        'scuole': _righe(conn, 'SELECT * FROM napoli_scuole WHERE lotto_id = ? ORDER BY id', (lotto_id,)),
        'alunni': _righe(conn, 'SELECT id, lotto_id, cognome, nome, codice_fiscale, scuola_id, grado '
                               'FROM napoli_alunni ORDER BY id'),
        'operatori': _righe(conn, 'SELECT id, cognome, nome, codice_fiscale, cf_valido, figura, ore_contratto, '
                                  'qualifica_originale FROM napoli_operatori ORDER BY id'),
        'coppie': _righe(conn, 'SELECT * FROM napoli_coppie WHERE lotto_id = ? ORDER BY id', (lotto_id,)),
        'pei': _righe(conn, 'SELECT p.* FROM napoli_pei p JOIN napoli_alunni a ON a.id = p.alunno_id '
                            'ORDER BY p.valido_da, p.id'),
        'fogli': _righe(conn, 'SELECT f.* FROM napoli_fogli f JOIN napoli_coppie c ON c.id = f.coppia_id '
                              'WHERE c.lotto_id = ? AND f.anno = ? AND f.mese = ? ORDER BY f.id',
                        (lotto_id, anno, mese)),
        'presenze': _righe(conn, 'SELECT * FROM napoli_presenze WHERE lotto_id = ? AND data BETWEEN ? AND ? '
                                 'ORDER BY id', (lotto_id, inizio.isoformat(), fine.isoformat())),
        # coppie con giorni dopo la fine del mese (quelli del mese sono in 'presenze')
        'coppie_con_ore_dopo_il_mese': {r['coppia_id'] for r in _righe(
            conn, 'SELECT DISTINCT coppia_id FROM napoli_presenze WHERE lotto_id = ? AND data > ?',
            (lotto_id, fine.isoformat()))},
        'imports': _righe(conn, 'SELECT id, anno, mese, nome_file, sha256, n_righe, esito_json, annullato, data '
                                'FROM napoli_import WHERE lotto_id = ? ORDER BY id', (lotto_id,)),
        'chiuso': conn.execute('SELECT 1 FROM napoli_mesi_chiusi WHERE lotto_id = ? AND anno = ? AND mese = ?',
                               (lotto_id, anno, mese)).fetchone() is not None,
    }
    ctx['versione'] = _impronta_contesto(ctx)
    return ctx


def _impronta_contesto(ctx):
    """Impronta dei dati di Napoli guardati dall'import: se cambiano fra anteprima e
    conferma, la conferma si rifiuta (l'anteprima non direbbe piu' il vero)."""
    parti = {k: v for k, v in ctx.items() if k not in ('regole', 'inizio', 'fine', 'figure')}
    parti['coppie_con_ore_dopo_il_mese'] = sorted(ctx['coppie_con_ore_dopo_il_mese'])
    return hashlib.sha256(json.dumps(parti, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:24]


# ==================== scelte dell'anteprima ====================

def _scelte(scelte, ctx):
    """Le scelte fatte nella pagina, controllate: qualifiche nuove -> figura, grado delle
    scuole nuove, lettura delle ore ambigue, sovrascrivere le ore scritte a mano,
    conferme, subentri e chiusure proposte (None = la proposta)."""
    if scelte in (None, ''):
        scelte = {}
    if isinstance(scelte, str):
        try:
            scelte = json.loads(scelte)
        except ValueError:
            scelte = None
    if not isinstance(scelte, dict):
        raise DatiNonValidi('Le scelte non sono arrivate bene: rifai l\'anteprima.', codice='SCELTE_NON_VALIDE')

    def dizionario(nome, ammessi):
        valore = scelte.get(nome) or {}
        if not isinstance(valore, dict) or any(not isinstance(v, str) or v not in ammessi for v in valore.values()):
            raise DatiNonValidi('Le scelte non sono arrivate bene: rifai l\'anteprima.', codice='SCELTE_NON_VALIDE')
        return {str(k): v for k, v in valore.items()}

    def elenco(nome, tipo):
        valore = scelte.get(nome)
        if valore is None:
            return None
        if not isinstance(valore, list) or any(isinstance(v, bool) or not isinstance(v, tipo) for v in valore):
            raise DatiNonValidi('Le scelte non sono arrivate bene: rifai l\'anteprima.', codice='SCELTE_NON_VALIDE')
        return set(valore)

    return {
        'qualifiche': {pulito(k): v for k, v in dizionario('qualifiche', set(ctx['figure'])).items()},
        'gradi': dizionario('gradi', set(GRADI_SCUOLA) | {''}),
        'ore_ambigue': dizionario('ore_ambigue', {'ore_e_minuti', 'decimale'}),
        'sovrascrivi_manuali': napoli_db._booleano(scelte.get('sovrascrivi_manuali'), False, 'sovrascrivi_manuali'),
        'conferme': elenco('conferme', str) or set(),
        'subentri': elenco('subentri', int),
        'chiusure': elenco('chiusure', int),
    }


# ==================== il piano dell'import ====================

def _uguali_nomi(a, b):
    return chiave_nome_scuola(a) == chiave_nome_scuola(b)


def _nome_persona(p):
    return f'{p.get("cognome") or ""} {p.get("nome") or ""}'.strip()


def _chiavi_nome(p):
    """Le chiavi con cui si cerca una persona di Assisto per nome (cognome nome e nome cognome)."""
    return {chiave_nome_scuola(_nome_persona(p)), chiave_nome_scuola(f'{p.get("nome") or ""} {p.get("cognome") or ""}')}


def _cf_giusto(cf, valido=1):
    return bool(cf) and bool(valido) and calc.esito_codice_fiscale(cf)[1] == 'ok'


def _identita_scuola_assisto(s):
    return ('mecc', s['codice_meccanografico']) if s['codice_meccanografico'] else ('nome', chiave_nome_scuola(s['nome']))


def _attiva(c, minuti):
    return c['esito'] == 'sigla' or (c['esito'] in ('ore', 'da_confermare') and minuti > 0)


def _valori_presenza(c, minuti):
    return {'minuti_riconosciuti': minuti if c['esito'] != 'sigla' else 0, 'causale': c['causale'],
            'sigla': c['sigla'], 'testo_originale': c['testo'] or None}


def _stessi_valori(presenza, valori):
    return (presenza['stato'] == 'registrato' and presenza['minuti_riconosciuti'] == valori['minuti_riconosciuti']
            and (presenza['causale'] or None) == valori['causale'] and (presenza['sigla'] or None) == valori['sigla'])


def _elenco_municipalita(valori):
    numeri = sorted(v for v in valori if v is not None)
    testi = [str(v) for v in numeri] + (['senza municipalità'] if None in valori else [])
    return ' e '.join(testi)


class _Piano:
    """Cosa farebbe l'import, senza scrivere: si costruisce dalla lettura del file e dai
    dati di Napoli (ctx); la conferma lo applica cosi' com'e'."""

    def __init__(self, ctx, lettura, scelte, solo_confronto=False):
        self.ctx, self.lettura, self.scelte, self.solo_confronto = ctx, lettura, scelte, solo_confronto
        self.anno, self.mese = lettura['anno'], lettura['mese']
        self.inizio, self.fine = ctx['inizio'], ctx['fine']
        self.avvisi = []                       # come le anomalie della lettura (riga, colonna, codice)
        self.qualifiche = collections.OrderedDict()
        self.scuole = collections.OrderedDict()
        self.alunni = collections.OrderedDict()
        self.operatori = collections.OrderedDict()
        self.righe = []
        self.pei = collections.OrderedDict()
        self.conferme = collections.OrderedDict()
        self.subentri, self.chiusure, self.coppie_del_mese = [], [], []
        self.togliere, self.solo_in_assisto, self.manuali_diverse = [], [], []
        self.ambigue = {}                      # 'riga:colonna' -> {'scelta', 'ricordata'} (ore da confermare)
        self.municipalita_file = collections.defaultdict(set)     # identita' della scuola -> municipalita' nel file
        self.scuole_db = {s['id']: s for s in ctx['scuole']}
        self.alunni_cf = {a['codice_fiscale']: a for a in ctx['alunni']}
        self.alunni_radice, self.alunni_nome = collections.defaultdict(list), collections.defaultdict(list)
        for a in ctx['alunni']:
            if radice_cf(a['codice_fiscale']):
                self.alunni_radice[radice_cf(a['codice_fiscale'])].append(a)
            for k in _chiavi_nome(a):
                self.alunni_nome[k].append(a)
        self.operatori_cf = {}
        self.operatori_radice, self.operatori_nome = collections.defaultdict(list), collections.defaultdict(list)
        for o in ctx['operatori']:
            if o['codice_fiscale']:
                self.operatori_cf.setdefault(o['codice_fiscale'], o)
                if radice_cf(o['codice_fiscale']):
                    self.operatori_radice[radice_cf(o['codice_fiscale'])].append(o)
            for k in _chiavi_nome(o):
                self.operatori_nome[k].append(o)
        self.presenze = {(p['coppia_id'], p['data']): p for p in ctx['presenze']}
        self.fogli = {f['coppia_id']: f for f in ctx['fogli']}
        # coppie e PEI di Assisto per alunno (l'archivio cresce ogni mese); scuole di ogni operatore
        self.coppie_alunno = collections.defaultdict(list)
        self.scuole_operatore = collections.defaultdict(set)
        for c in ctx['coppie']:
            self.coppie_alunno[c['alunno_id']].append(c)
            if c['scuola_id'] in self.scuole_db:
                self.scuole_operatore[c['operatore_id']].add(_identita_scuola_assisto(self.scuole_db[c['scuola_id']]))
        self.pei_alunno = collections.defaultdict(list)
        for p in ctx['pei']:
            self.pei_alunno[p['alunno_id']].append(p)
        self._costruisci()

    # ---------- avvisi ----------
    def avviso(self, riga, codice, dettaglio=None, colonna=None):
        _anomalia(self.avvisi, riga, colonna, codice, dettaglio)

    # ---------- costruzione ----------
    def _costruisci(self):
        if self.ctx['chiuso'] and not self.solo_confronto:
            self.avviso(None, 'mese_chiuso', mese_testo(self.anno, self.mese))
        municipalita_note = self._municipalita_delle_scuole()
        for r in self.lettura['righe']:
            self.righe.append(self._riga(r, municipalita_note))
        self._doppie()
        for voce in self.righe:
            if voce['valida']:
                self._coppia(voce)
        self._ore_ambigue()
        for voce in self.righe:
            if voce['valida'] and voce['ruolo'] == 'sostituto':
                self._titolare_del_sostituto(voce)
        self._subentri()
        self._scuole_usate()
        for voce in self.righe:
            if voce['valida']:
                self._foglio(voce)
                self._celle(voce)
        self._pei()
        self._settimane_tra_operatori()
        self._presenze_senza_cella()
        self._chiusure()
        self._plessi()
        self._figure_degli_operatori()
        per_nome = [o for o in self.operatori.values() if o.get('per_nome') and not o.get('nuovo')]
        if per_nome:
            self.conferme['operatori_per_nome'] = per_nome

    def _municipalita_delle_scuole(self):
        """Per ogni scuola (codice o nome) le municipalita' scritte nel file e in Assisto."""
        note = collections.defaultdict(set)
        for r in self.lettura['righe']:
            k = self._identita_scuola(r)
            if k and r['municipalita'] is not None:
                note[k].add(r['municipalita'])
                self.municipalita_file[k].add(r['municipalita'])
        for s in self.ctx['scuole']:
            if s['municipalita'] is not None:
                note[_identita_scuola_assisto(s)].add(s['municipalita'])
        return note

    @staticmethod
    def _identita_scuola(r):
        s = r['scuola']
        if s['codice']:
            return ('mecc', s['codice'])
        nome = s['nome'] or s['testo']
        return ('nome', chiave_nome_scuola(nome)) if nome else None

    def _riga(self, r, municipalita_note):
        voce = {'r': r, 'riga': r['riga'], 'valida': True, 'ruolo': 'sostituto' if r['sostituzione'] else 'titolare'}
        n = r['riga']
        if r['lotto'] is not None and r['lotto'] != self.ctx['lotto']['numero_lotto']:
            self.avviso(n, 'riga_di_altro_lotto', f'lotto {r["lotto"]}')
            voce['valida'] = False
        # qualifica -> figura
        voce['figura'] = self._figura(r)
        if voce['figura'] is None:
            voce['valida'] = False
        elif self.ctx['figure'].get(voce['figura'], {}).get('ore_di_lotto'):
            self.avviso(n, 'righe_del_coordinatore')
            voce['valida'] = False
            voce['coordinatore'] = True
        voce['scuola'] = self._scuola(r, municipalita_note)
        voce['alunno'] = self._alunno(r, voce)
        voce['operatore'] = self._operatore(r, voce)
        if voce['scuola'] is None or voce['alunno'] is None or voce['operatore'] is None:
            voce['valida'] = False
        return voce

    def _figura(self, r):
        """La figura della qualifica: dalle grafie conosciute (napoli_alias_qualifiche) o,
        per una qualifica nuova, solo quella scelta nella pagina (la figura proposta si
        mostra, ma non e' gia' scelta: obbligo di scelta)."""
        testo = r['qualifica']
        if not testo:
            self.avviso(r['riga'], 'qualifica_mancante')
            return None
        if testo in self.ctx['alias']:
            return self.ctx['alias'][testo]
        voce = self.qualifiche.get(testo)
        if voce is None:
            voce = self.qualifiche[testo] = {'testo': testo, 'proposta': figura_proposta(testo),
                                             'figura': self.scelte['qualifiche'].get(testo), 'righe': []}
        voce['righe'].append(r['riga'])
        if voce['figura'] is None:
            self.avviso(r['riga'], 'qualifica_non_collegata', testo)
        return voce['figura']

    # ---------- scuole ----------
    def _scuola(self, r, municipalita_note):
        n = r['riga']
        identita = self._identita_scuola(r)
        if identita is None:
            self.avviso(n, 'riga_senza_scuola')
            return None
        mun = r['municipalita']
        if mun is None and len(municipalita_note.get(identita, ())) == 1:
            mun = next(iter(municipalita_note[identita]))
            self.avviso(n, 'municipalita_presa_dalla_scuola', str(mun))
        chiave = f'{identita[0]}:{identita[1]}|{"" if mun is None else mun}'
        voce = self.scuole.get(chiave)
        if voce is None:
            esistente, completa = self._scuola_in_assisto(identita, mun)
            codice = r['scuola']['codice']
            voce = {'chiave': chiave, 'identita': identita, 'codice': codice, 'municipalita': mun, 'righe': [],
                    'completa': completa, 'usata': True}
            if esistente:
                voce.update(id=esistente['id'], nome=esistente['nome'], grado=esistente['grado'], nuova=False)
                if completa:
                    self.avviso(n, 'municipalita_completata_in_assisto', f'municipalità {mun}')
            else:
                proposto = calc.grado_da_codice_meccanografico(codice)
                scelto = self.scelte['gradi'].get(chiave)
                voce.update(id=None, nome=r['scuola']['nome'] or r['scuola']['testo'], grado_proposto=proposto,
                            grado=(scelto or None) if scelto is not None else proposto, nuova=True)
            self.scuole[chiave] = voce
        voce['righe'].append(n)
        return voce

    def _plessi_in_assisto(self, identita):
        """I plessi di Assisto della stessa scuola (stesso codice meccanografico; senza
        codice, stesso nome), prima quelli senza codice."""
        tipo, valore = identita
        if tipo == 'mecc':
            return [s for s in self.ctx['scuole'] if s['codice_meccanografico'] == valore]
        candidate = [s for s in self.ctx['scuole'] if chiave_nome_scuola(s['nome']) == valore]
        return sorted(candidate, key=lambda s: (s['codice_meccanografico'] is not None, s['id']))

    @staticmethod
    def _stessa_scuola(s, identita):
        tipo, valore = identita
        return s['codice_meccanografico'] == valore if tipo == 'mecc' else chiave_nome_scuola(s['nome']) == valore

    def _scuola_in_assisto(self, identita, mun):
        """(plesso di Assisto, municipalita' da aggiungere). Lo stesso plesso ha la stessa
        scuola e la stessa municipalita'. Se in Assisto la scuola c'e' una volta sola e senza
        municipalita', e nel file ha una municipalita' sola, e' lo stesso plesso: la
        municipalita' del file si aggiunge. Altrimenti (municipalita' diversa) e' un plesso
        nuovo, da confermare (_plessi)."""
        plessi = self._plessi_in_assisto(identita)
        uguali = [s for s in plessi if s['municipalita'] == mun]
        if uguali:
            return uguali[0], False
        if mun is not None and len(plessi) == 1 and plessi[0]['municipalita'] is None \
                and self.municipalita_file.get(identita) == {mun}:
            return plessi[0], True
        return None, False

    def _scuole_usate(self):
        """Una scuola (o un plesso) nuova si crea solo se serve: se tutte le sue righe sono
        di coppie gia' in Assisto, quelle restano nella scuola della coppia (con un avviso o
        la conferma dei plessi) e nelle anagrafiche non resta una scuola vuota."""
        for s in self.scuole.values():
            if s['nuova']:
                voci = [v for v in self.righe if v.get('scuola') is s and not v.get('coordinatore')]
                s['usata'] = any(not v['valida'] or v.get('coppia_nuova') for v in voci)

    # ---------- alunni ----------
    def _alunno(self, r, voce_riga):
        n, al = r['riga'], r['alunno']
        if al['cf_esito'] in ('vuoto', 'formato'):
            self.avviso(n, 'riga_senza_alunno' if not al['cf'] and not al['nome_completo'] else 'cf_alunno_non_valido')
            return None
        chiave = _chiave_alunno_file(al['cf'])
        voce = self.alunni.get(chiave)
        if voce is None:
            esistente = self._alunno_in_assisto(al['cf'])
            voce = {'chiave': chiave, 'cf': al['cf'], 'cf_esito': al['cf_esito'], 'righe': [],
                    'scuola': voce_riga['scuola']}
            if esistente:
                voce.update(id=esistente['id'], cognome=esistente['cognome'], nome=esistente['nome'],
                            grado=esistente['grado'], nuovo=False, cf_assisto=esistente['codice_fiscale'])
                if not _uguali_nomi(_nome_persona(esistente), al['nome_completo']) and \
                        not _uguali_nomi(f'{esistente["nome"]} {esistente["cognome"]}', al['nome_completo']):
                    self.avviso(n, 'alunno_nome_diverso_in_assisto')
                if esistente['lotto_id'] != self.ctx['lotto']['id']:
                    self.avviso(n, 'alunno_di_altro_lotto')
            else:
                if not al['nome_completo']:
                    self.avviso(n, 'alunno_senza_nome')
                    return None
                voce.update(id=None, cognome=al['cognome'], nome=al['nome'] or '-', grado=None, nuovo=True)
                if self.alunni_nome.get(chiave_nome_scuola(al['nome_completo'])):
                    self.avviso(n, 'alunno_omonimo_in_assisto')
            self.alunni[chiave] = voce
        self._codice_alunno(voce, al, n)
        voce['righe'].append(n)
        return voce

    def _alunno_in_assisto(self, cf):
        """Lo stesso codice fiscale; altrimenti lo stesso codice con un altro ultimo
        carattere (uno dei due e' sbagliato: e' la stessa persona)."""
        esistente = self.alunni_cf.get(cf)
        if esistente:
            return esistente
        stessi = self.alunni_radice.get(radice_cf(cf) or '', [])
        return stessi[0] if len(stessi) == 1 else None

    def _codice_alunno(self, voce, al, n):
        """Il codice fiscale giusto, se arriva: per un alunno nuovo si salva quello giusto
        fra le sue righe; per uno di Assisto con il codice sbagliato si corregge."""
        if voce['nuovo']:
            if al['cf_esito'] == 'ok' and voce['cf_esito'] != 'ok':
                voce['cf'], voce['cf_esito'] = al['cf'], 'ok'
            return
        if al['cf'] == voce['cf_assisto'] or voce.get('cf_nuovo'):
            return
        giusto_in_assisto = _cf_giusto(voce['cf_assisto'])
        if al['cf_esito'] == 'ok' and not giusto_in_assisto and al['cf'] not in self.alunni_cf:
            voce['cf_nuovo'] = al['cf']
            self.avviso(n, 'cf_alunno_corretto_in_assisto')
        elif al['cf_esito'] != 'ok' and giusto_in_assisto:
            self.avviso(n, 'cf_alunno_giusto_in_assisto')

    # ---------- operatori ----------
    def _operatore(self, r, voce_riga):
        n, op = r['riga'], r['operatore']
        if not op['cf'] and not op['nome_completo']:
            self.avviso(n, 'riga_senza_operatore')
            return None
        chiave = _chiave_operatore_file(r)
        voce = self.operatori.get(chiave)
        if voce is None:
            esistente, modo = self._operatore_in_assisto(op, r)
            voce = {'chiave': chiave, 'righe': [], 'cf': op['cf'], 'cf_esito': op['cf_esito'],
                    'nome_file': op['nome_completo'], 'per_nome': modo == 'nome', 'ore_contratto': None}
            if esistente:
                voce.update(id=esistente['id'], cognome=esistente['cognome'], nome=esistente['nome'], nuovo=False,
                            ore_contratto_assisto=esistente['ore_contratto'], cf_assisto=esistente['codice_fiscale'],
                            cf_valido_assisto=esistente['cf_valido'], figura_assisto=esistente['figura'])
                if modo != 'nome' and op['nome_completo'] and \
                        not _uguali_nomi(_nome_persona(esistente), op['nome_completo']) and \
                        not _uguali_nomi(f'{esistente["nome"]} {esistente["cognome"]}', op['nome_completo']):
                    self.avviso(n, 'operatore_nome_diverso_in_assisto')
            else:
                if not op['nome_completo']:
                    self.avviso(n, 'riga_senza_operatore')
                    return None
                voce.update(id=None, cognome=op['cognome'], nome=op['nome'] or '-', nuovo=True,
                            figura=voce_riga['figura'], qualifica=r['qualifica'] or None)
            self.operatori[chiave] = voce
        self._codice_operatore(voce, op, n)
        voce['righe'].append(n)
        if voce['ore_contratto'] is None and r['ore_contratto'] is not None:
            voce['ore_contratto'] = r['ore_contratto']
        if voce.get('nuovo') and voce.get('figura') is None:
            voce['figura'] = voce_riga['figura']
        return voce

    def _operatore_in_assisto(self, op, r):
        """(operatore di Assisto, come si e' trovato): 'cf' (stesso codice), 'radice' (stesso
        codice salvo l'ultimo carattere) o 'nome' (da confermare, PROGETTO §7.1). Per nome
        si cerca solo se il codice del file non e' giusto, o se e' giusto ma in Assisto la
        persona ha un codice sbagliato o nessun codice (il mese dopo il codice arriva
        corretto); fra piu' omonimi vale quello che ha gia' coppie nella stessa scuola."""
        cf = op['cf']
        if cf:
            trovato = self.operatori_cf.get(cf)
            if trovato:
                return trovato, 'cf'
            stessi = self.operatori_radice.get(radice_cf(cf) or '', [])
            if len(stessi) == 1:
                return stessi[0], 'radice'
        if not op['nome_completo']:
            return None, None
        stesso_nome = self.operatori_nome.get(chiave_nome_scuola(op['nome_completo']), [])
        if op['cf_esito'] == 'ok':
            candidati = [o for o in stesso_nome if not _cf_giusto(o['codice_fiscale'], o['cf_valido'])]
            if stesso_nome and not candidati:
                self.avviso(r['riga'], 'operatore_omonimo_in_assisto')
        else:
            candidati = list(stesso_nome)
        if len(candidati) > 1:
            identita = self._identita_scuola(r)
            stessa_scuola = [o for o in candidati if identita in self.scuole_operatore.get(o['id'], ())]
            if len(stessa_scuola) == 1:
                candidati = stessa_scuola
        if len(candidati) == 1:
            return candidati[0], 'nome'
        if len(candidati) > 1:
            self.avviso(r['riga'], 'operatori_omonimi_in_assisto')
        return None, None

    def _codice_operatore(self, voce, op, n):
        """Il codice fiscale giusto, se arriva: per un operatore nuovo si salva quello giusto
        fra le sue righe; per uno di Assisto con un codice sbagliato o mancante si corregge
        (se i due codici differiscono di al massimo due caratteri, o in Assisto manca)."""
        if voce['nuovo']:
            if op['cf_esito'] == 'ok' and voce['cf_esito'] != 'ok' and radice_cf(op['cf']) == radice_cf(voce['cf']):
                voce['cf'], voce['cf_esito'] = op['cf'], 'ok'
            return
        if op['cf_esito'] != 'ok' or op['cf'] == voce['cf_assisto'] or voce.get('cf_nuovo') \
                or _cf_giusto(voce['cf_assisto'], voce['cf_valido_assisto']) or op['cf'] in self.operatori_cf \
                or differenza_cf(op['cf'], voce['cf_assisto']) is None:
            return
        voce['cf_nuovo'] = op['cf']
        if not voce['per_nome']:
            self.avviso(n, 'cf_operatore_corretto_in_assisto')

    def _figure_degli_operatori(self):
        """Lo stesso operatore con figure diverse: fra le sue righe, o fra le righe e la
        figura che ha in Assisto (ogni riga vale con la sua figura: solo un avviso)."""
        for o in self.operatori.values():
            voci = [v for v in self.righe if v.get('operatore') is o and v.get('figura') and not v.get('coordinatore')]
            nel_file = sorted({v['figura'] for v in voci}, key=lambda f: self.ctx['figure'].get(f, {}).get('ordine', 0))
            in_assisto = o.get('figura_assisto')
            if len(set(nel_file) | ({in_assisto} if in_assisto else set())) < 2:
                continue
            dettaglio = 'nel file ' + ' e '.join(napoli_db.nome_figura(f) for f in nel_file)
            if in_assisto:
                dettaglio += f', in Assisto {napoli_db.nome_figura(in_assisto)}'
            for v in voci:
                if len(nel_file) > 1 or v['figura'] != in_assisto:
                    self.avviso(v['riga'], 'operatore_con_piu_figure', dettaglio)

    def _doppie(self):
        viste = {}
        for voce in self.righe:
            if not voce['valida']:
                continue
            chiave = (id(voce['alunno']), id(voce['operatore']), voce['figura'], voce['ruolo'])
            if chiave in viste:
                prima = viste[chiave]
                self.avviso(voce['riga'], 'coppia_doppia', f'come la riga {prima["riga"]}')
                voce['valida'] = False
            else:
                viste[chiave] = voce

    # ---------- ore da confermare ----------
    def _minuti(self, r, c):
        """Minuti di una cella: per le ore da confermare la lettura scelta (nella pagina o
        nell'import di prima dello stesso file); finche' non si sceglie, quella decimale."""
        if c['esito'] != 'da_confermare':
            return c['minuti'] or 0
        scelta = (self.ambigue.get(f'{r["riga"]}:{c["colonna"]}') or {}).get('scelta') \
            or self.scelte['ore_ambigue'].get(f'{r["riga"]}:{c["colonna"]}') or 'decimale'
        return next(a['minuti'] for a in c['alternative'] if a['lettura'] == scelta)

    def _ore_ambigue(self):
        """Le ore da confermare ('1,30'): la scelta fatta nella pagina o, se la cella e' la
        stessa gia' importata (stesso testo, stessi minuti di una delle due letture), quella
        fatta nell'import di prima. Nessuna scelta gia' fatta dal programma."""
        for voce in self.righe:
            if voce.get('coordinatore'):
                continue
            r = voce['r']
            for d, c in r['celle'].items():
                if c['esito'] != 'da_confermare':
                    continue
                chiave = f'{r["riga"]}:{c["colonna"]}'
                scelta, ricordata = self.scelte['ore_ambigue'].get(chiave), False
                p = self.presenze.get((voce.get('coppia_id'), d.isoformat())) if voce.get('coppia_id') else None
                if scelta is None and p and p['origine'] == 'import_excel' and (p['testo_originale'] or '') == c['testo']:
                    scelta = next((a['lettura'] for a in c['alternative']
                                   if a['minuti'] == p['minuti_riconosciuti']), None)
                    ricordata = scelta is not None
                self.ambigue[chiave] = {'scelta': scelta, 'ricordata': ricordata, 'riga': r['riga'], 'data': d,
                                        'cella': c}

    def ore_ambigue_da_scegliere(self):
        return [k for k, x in self.ambigue.items() if x['scelta'] is None]

    # ---------- coppie ----------
    def _giorni_attivi(self, voce):
        r = voce['r']
        return sorted(d for d, c in r['celle'].items() if _attiva(c, self._minuti(r, c)))

    def _coppia(self, voce):
        r = voce['r']
        attivi = self._giorni_attivi(voce)
        primo, ultimo = (attivi[0], attivi[-1]) if attivi else (None, None)
        di = r['data_inizio'] or r['data_inizio_proposta']
        if voce['ruolo'] == 'titolare':
            # la data di inizio, se viene prima delle ore; altrimenti il primo del mese
            # (ore prima della data di inizio, data futura: gia' segnalati dalla lettura)
            dal = di if di and (primo is None or di <= primo) else self.inizio
            al = None
        else:
            dal = di if di and self.inizio <= di <= (primo or self.fine) else (primo or self.inizio)
            al = ultimo or self.fine
        voce.update(attivi=attivi, valido_da=dal, valido_a=al, coppia_id=None, coppia_cambi={}, titolare=None,
                    scuola_coppia=None)
        esistente = self._coppia_in_assisto(voce, dal)
        if esistente is None:
            voce['coppia_nuova'] = True
            return
        voce['coppia_nuova'] = False
        voce['coppia_id'] = esistente['id']
        voce['coppia_assisto'] = esistente
        cambi = {}
        if dal < calc.data(esistente['valido_da']):
            cambi['valido_da'] = dal.isoformat()
        if esistente['valido_a'] is not None:
            fine_attuale = calc.data(esistente['valido_a'])
            if voce['ruolo'] == 'titolare':
                if ultimo and ultimo > fine_attuale:        # ore dopo la chiusura: il titolare torna
                    cambi['valido_a'] = None
                    self.avviso(voce['riga'], 'coppia_riaperta')
            elif al > fine_attuale:                          # il sostituto continua
                cambi['valido_a'] = al.isoformat()
        voce['coppia_cambi'] = cambi
        # la scuola della coppia resta quella di Assisto
        scuola_coppia = self.scuole_db.get(esistente['scuola_id'])
        voce['scuola_coppia'] = scuola_coppia
        if scuola_coppia and voce['scuola'].get('id') != scuola_coppia['id']:
            if self._stessa_scuola(scuola_coppia, voce['scuola']['identita']):
                voce['plesso_diverso'] = True        # stessa scuola, altra municipalita': si conferma (_plessi)
            else:
                self.avviso(voce['riga'], 'coppia_scuola_diversa')

    def _coppia_in_assisto(self, voce, dal):
        """La coppia di Assisto con lo stesso alunno, operatore, figura e ruolo, valida nel
        mese o finita nel mese prima: un sostituto che continua o un titolare che torna dopo
        il cambio di operatore restano la stessa coppia (non se ne crea una ogni mese)."""
        alunno_id, operatore_id = voce['alunno'].get('id'), voce['operatore'].get('id')
        if not alunno_id or not operatore_id:
            return None
        fine_finestra = max(self.fine, dal)
        da_mese_prima = (self.inizio - datetime.timedelta(days=1)).replace(day=1)
        candidate = [c for c in self.coppie_alunno.get(alunno_id, ())
                     if c['operatore_id'] == operatore_id
                     and c['figura'] == voce['figura'] and c['ruolo'] == voce['ruolo']
                     and calc.data(c['valido_da']) <= fine_finestra
                     and (c['valido_a'] is None or calc.data(c['valido_a']) >= da_mese_prima)]
        return max(candidate, key=lambda c: (c['valido_da'], c['id'])) if candidate else None

    def _date_coppia(self, voce):
        """Le date della coppia dopo l'import: quelle della coppia nuova, o quelle di Assisto
        con i cambi (riapertura, sostituto che continua, subentro)."""
        if voce['coppia_nuova']:
            return voce['valido_da'], voce['valido_a']
        c, cambi = voce['coppia_assisto'], voce['coppia_cambi']
        fine = cambi['valido_a'] if 'valido_a' in cambi else c['valido_a']
        return calc.data(cambi.get('valido_da', c['valido_da'])), (calc.data(fine) if fine else None)

    def _titolare_del_sostituto(self, voce):
        """Il titolare del sostituto: la riga NO con lo stesso alunno e la stessa figura,
        altrimenti la coppia titolare di Assisto valida nel mese."""
        for altra in self.righe:
            if altra['valida'] and altra['ruolo'] == 'titolare' and altra['alunno'] is voce['alunno'] \
                    and altra['figura'] == voce['figura']:
                voce['titolare'] = altra
                return
        alunno_id = voce['alunno'].get('id')
        if alunno_id:
            for c in self.coppie_alunno.get(alunno_id, ()):
                if c['figura'] == voce['figura'] and c['ruolo'] == 'titolare' \
                        and calc.data(c['valido_da']) <= self.fine \
                        and (c['valido_a'] is None or calc.data(c['valido_a']) >= self.inizio):
                    voce['titolare'] = {'coppia_id': c['id'], 'coppia_assisto': c, 'riga': None, 'attivi': None}
                    return
        self.avviso(voce['riga'], 'sostituto_senza_titolare')

    def _subentri(self):
        """Un sostituto con la data di inizio dentro il mese: si propone di chiudere il
        titolare il giorno prima (se il titolare non ha ore da quel giorno)."""
        for voce in self.righe:
            r = voce['r']
            if not voce['valida'] or voce['ruolo'] != 'sostituto' or not voce.get('titolare'):
                continue
            di = r['data_inizio']
            if not di or not self.inizio < di <= self.fine:
                continue
            titolare = voce['titolare']
            chiudi_al = di - datetime.timedelta(days=1)
            if titolare.get('riga') is not None:
                if any(d >= di for d in titolare['attivi']) or titolare['valido_da'] > chiudi_al:
                    continue
                attuale = titolare.get('coppia_assisto')
            else:
                # titolare solo in Assisto: le sue ore importate prima si tolgono (non e' nel
                # file); contano i giorni scritti a mano o programmati e quelli dopo il mese
                attuale = titolare['coppia_assisto']
                if attuale['id'] in self.ctx['coppie_con_ore_dopo_il_mese'] or any(
                        p['coppia_id'] == attuale['id'] and p['data'] >= di.isoformat()
                        and p['origine'] != 'import_excel' for p in self.ctx['presenze']):
                    continue
            if attuale and attuale['valido_a'] is not None and calc.data(attuale['valido_a']) <= chiudi_al:
                continue
            scelto = self.scelte['subentri'] is None or voce['riga'] in self.scelte['subentri']
            proposta = {'riga': voce['riga'], 'titolare': titolare, 'chiudi_al': chiudi_al, 'scelto': scelto,
                        'sostituto': voce}
            self.subentri.append(proposta)
            if scelto and not self.solo_confronto:
                if titolare.get('riga') is not None and titolare.get('coppia_nuova'):
                    titolare['valido_a'] = chiudi_al
                else:
                    titolare.setdefault('coppia_cambi', {})['valido_a'] = chiudi_al.isoformat()

    # ---------- foglio, celle, PEI ----------
    def _foglio(self, voce):
        note = voce['r']['note'] or None
        dal, al = self._date_coppia(voce)
        if dal > self.fine or (al is not None and al < self.inizio):
            voce['foglio'] = None           # la coppia non vale nel mese (comincia dopo o e' chiusa prima)
            return
        attuale = self.fogli.get(voce['coppia_id']) if voce['coppia_id'] else None
        if attuale is None:
            voce['foglio'] = {'azione': 'nuovo', 'note': note}
            return
        cambi = {}
        if (attuale['note'] or None) != note:
            cambi['note'] = note
        if attuale['stato'] in ('preparato', 'stampato', 'ricevuto'):
            cambi['stato'] = 'registrato'
        voce['foglio'] = {'azione': 'cambia' if cambi else 'uguale', 'id': attuale['id'], 'cambi': cambi}

    def _celle(self, voce):
        r = voce['r']
        voce['celle'] = []
        for d, c in sorted(r['celle'].items()):
            if c['esito'] == 'errore':
                continue
            minuti = self._minuti(r, c)
            if not _attiva(c, minuti):
                continue
            valori = _valori_presenza(c, minuti)
            esistente = self.presenze.get((voce['coppia_id'], d.isoformat())) if voce['coppia_id'] else None
            if esistente is None:
                azione = 'nuova'
            elif _stessi_valori(esistente, valori):
                azione = 'uguale'
            elif esistente['origine'] == 'import_excel':
                azione = 'cambia'
            elif esistente['stato'] == 'programmato':
                azione = 'da_programmato'
            else:
                azione = 'manuale_diversa'
                self.manuali_diverse.append({'voce': voce, 'data': d, 'presenza': esistente, 'valori': valori,
                                             'colonna': c['colonna']})
                if self.scelte['sovrascrivi_manuali']:
                    azione = 'sovrascrivi'
            voce['celle'].append({'data': d, 'colonna': c['colonna'], 'valori': valori, 'azione': azione,
                                  'presenza': esistente, 'minuti': valori['minuti_riconosciuti']})

    def _pei(self):
        for voce in self.righe:
            r = voce['r']
            if not voce['valida'] or voce['ruolo'] != 'titolare' or not r['ore_progetto']:
                continue
            ore = r['ore_progetto']
            if not 0 < ore <= 40:
                self.avviso(voce['riga'], 'ore_progetto_fuori_limite', calc.numero_it(ore))
                continue
            chiave = (voce['alunno']['chiave'], voce['figura'])
            attuale = self.pei.get(chiave)
            if attuale is None:
                self.pei[chiave] = {'alunno': voce['alunno'], 'figura': voce['figura'], 'ore': ore,
                                    'righe': [voce['riga']]}
            else:
                attuale['righe'].append(voce['riga'])
                if ore != attuale['ore']:
                    self.avviso(voce['riga'], 'alunno_pei_diverso_stessa_figura')
                    attuale['ore'] = max(ore, attuale['ore'])
        for voce in self.pei.values():
            voce.update(self._azione_pei(voce))

    def _azione_pei(self, voce):
        """Il PEI del mese per alunno e figura: uguale a quello di Assisto (niente), nuovo
        dal primo del mese, oppure cambiato (quello di prima finisce il giorno prima)."""
        alunno_id, ore = voce['alunno'].get('id'), voce['ore']
        if not alunno_id:
            return {'azione': 'nuovo', 'valido_da': self.inizio, 'valido_a': None}
        tutti = [p for p in self.pei_alunno.get(alunno_id, ()) if p['figura'] == voce['figura']]
        nel_mese = [p for p in tutti if calc.data(p['valido_da']) <= self.fine
                    and (p['valido_a'] is None or calc.data(p['valido_a']) >= self.inizio)]
        if nel_mese:
            if all(calc.decimale(p['ore_settimanali']) == ore for p in nel_mese):
                return {'azione': 'uguale'}
            if len(nel_mese) == 1:
                p = nel_mese[0]
                if calc.data(p['valido_da']) < self.inizio:
                    return {'azione': 'cambia_dal_mese', 'precedente': p, 'valido_da': self.inizio,
                            'valido_a': p['valido_a']}
                return {'azione': 'cambia_ore', 'precedente': p}
            self.avviso(voce['righe'][0], 'pei_diverso_in_assisto')
            return {'azione': 'uguale'}
        dopo = [p for p in tutti if calc.data(p['valido_da']) > self.fine]
        prossimo = min(dopo, key=lambda p: p['valido_da']) if dopo else None
        if prossimo and calc.decimale(prossimo['ore_settimanali']) == ore:
            return {'azione': 'anticipa', 'precedente': prossimo}
        fine = (calc.data(prossimo['valido_da']) - datetime.timedelta(days=1)) if prossimo else None
        return {'azione': 'nuovo', 'valido_da': self.inizio, 'valido_a': fine}

    def _settimane_tra_operatori(self):
        """Piu' righe dello stesso alunno e della stessa figura: la somma della settimana
        contro il PEI (titolari piu' sostituti)."""
        gruppi = collections.defaultdict(list)
        for voce in self.righe:
            if voce['valida']:
                gruppi[(voce['alunno']['chiave'], voce['figura'])].append(voce)
        for chiave, voci in gruppi.items():
            pei = self.pei.get(chiave)
            if len(voci) < 2 or not pei:
                continue
            minuti = collections.Counter()
            for v in voci:
                for c in v['celle']:
                    minuti[c['data']] += c['minuti']
            for s in calc.verifica_settimane(dict(minuti), self.anno, self.mese, pei['ore'], self.ctx['regole']):
                if s['codice'] in ('settimana_oltre_pei', 'settimana_oltre_pei_piu_20') and s['settimana']:
                    self.avviso(voci[0]['riga'], 'alunno_settimana_oltre_pei_tra_operatori',
                                f'settimana {s["settimana"]}: {calc.numero_it(calc.ore_decimali(s["minuti"]))} '
                                f'ore, PEI {calc.numero_it(pei["ore"])}')

    def _presenze_senza_cella(self):
        """Giorni del mese in Assisto che nel file non ci sono: le ore importate prima si
        tolgono (il file e' il mese intero), quelle scritte a mano restano."""
        nel_file = {(v['coppia_id'], c['data'].isoformat()) for v in self.righe if v['valida'] and v['coppia_id']
                    for c in v['celle']}
        coppie = {c['id']: c for c in self.ctx['coppie']}
        for p in self.ctx['presenze']:
            if (p['coppia_id'], p['data']) in nel_file:
                continue
            if p['origine'] == 'import_excel':
                self.togliere.append(p)
            elif p['stato'] == 'registrato':
                self.solo_in_assisto.append({'presenza': p, 'coppia': coppie.get(p['coppia_id'])})

    def _chiusure(self):
        """Coppie valide alla fine del mese prima che nel file non ci sono: si propone di
        chiuderle l'ultimo giorno del mese prima (da confermare). Contano i giorni che
        restano dopo l'import: nel reimport, le ore importate prima di una riga tolta dal
        file si tolgono e la sua coppia si propone da chiudere. Una coppia che comincia in
        questo mese non si puo' chiudere prima di cominciare: si mostra (resta senza ore)."""
        if self.solo_confronto:
            return
        prima = self.inizio - datetime.timedelta(days=1)
        nel_file = {v['coppia_id'] for v in self.righe if v.get('coppia_id')}
        nel_file |= {v['titolare']['coppia_id'] for v in self.righe if v.get('titolare') and
                     v['titolare'].get('coppia_id')}
        tolte = {p['id'] for p in self.togliere}
        con_giorni = {p['coppia_id'] for p in self.ctx['presenze'] if p['id'] not in tolte}
        con_giorni |= self.ctx['coppie_con_ore_dopo_il_mese']
        for c in self.ctx['coppie']:
            if c['id'] in nel_file or c['id'] in con_giorni:
                continue
            if c['valido_a'] is not None and calc.data(c['valido_a']) < self.inizio:
                continue
            if calc.data(c['valido_da']) <= prima:
                scelto = self.scelte['chiusure'] is not None and c['id'] in self.scelte['chiusure']
                self.chiusure.append({'coppia': c, 'chiudi_al': prima, 'scelto': scelto})
            elif calc.data(c['valido_da']) <= self.fine:
                self.coppie_del_mese.append(c)
                self.avviso(None, 'coppia_del_mese_non_nel_file')

    def _plessi(self):
        """La stessa scuola con municipalita' diverse, nel file o fra il file e Assisto
        (REGOLE 12: la municipalita' e' della scuola): una municipalita' nuova diventa un
        altro plesso della stessa scuola, se serve a una coppia nuova; le righe di coppie
        gia' in Assisto restano nel plesso della coppia. In tutti e due i casi si chiede di
        confermare ("Ho controllato")."""
        per_scuola = collections.OrderedDict()
        for s in self.scuole.values():
            per_scuola.setdefault(s['identita'], []).append(s)
        voci = []
        for identita, lista in per_scuola.items():
            in_assisto = self._plessi_in_assisto(identita)
            nuovi = [s for s in lista if s['nuova'] and s['usata']]
            restano = [v for v in self.righe if v['valida'] and v.get('plesso_diverso')
                       and v['scuola']['identita'] == identita]
            mun_file = {s['municipalita'] for s in lista}
            mun_assisto = {s['municipalita'] for s in in_assisto}
            if not ((nuovi and len(mun_file | mun_assisto) > 1) or restano):
                continue
            testo = f'nel file municipalità {_elenco_municipalita(mun_file)}'
            if in_assisto:
                testo += f', in Assisto {_elenco_municipalita(mun_assisto)}'
            esiti = []
            if nuovi:
                mun_nuovi = {s['municipalita'] for s in nuovi}
                esiti.append(('si aggiunge il plesso della municipalità ' if len(nuovi) == 1 else
                              'si aggiungono i plessi delle municipalità ') + _elenco_municipalita(mun_nuovi))
            if restano:
                mun_coppie = {v['scuola_coppia']['municipalita'] for v in restano}
                esiti.append('le coppie già in Assisto restano nel plesso della municipalità '
                             + _elenco_municipalita(mun_coppie))
            righe = {n for s in nuovi for n in s['righe']} | {v['riga'] for v in restano}
            voci.append({'nome': lista[0]['nome'], 'codice': lista[0]['codice'], 'testo': f'{testo}: {"; ".join(esiti)}',
                         'righe': sorted(righe)})
        if voci:
            self.conferme['plessi'] = voci

    # ---------- riepiloghi ----------
    def grado_della_riga(self, voce):
        scuola = voce.get('scuola_coppia') or voce['scuola']
        g = calc.grado_fattura(voce['alunno'].get('grado')) or calc.grado_fattura(scuola.get('grado'))
        return g or 'da_decidere'

    def bloccanti(self):
        codici = {c for c, (livello, *_x) in SPIEGAZIONI.items() if livello == 'bloccante'}
        return [a for a in self.lettura['anomalie'] + self.avvisi if a['codice'] in codici]

    def conteggi(self):
        valide = [v for v in self.righe if v['valida']]
        celle = [c for v in valide for c in v['celle']]
        azioni = collections.Counter(c['azione'] for c in celle)
        coppie_nuove = sum(1 for v in valide if v.get('coppia_nuova'))
        coppie_cambiate = sum(1 for v in valide if not v.get('coppia_nuova') and v.get('coppia_cambi'))
        coppie_cambiate += sum(1 for s in self.subentri if s['scelto'] and s['titolare'].get('riga') is None)
        coppie_cambiate += sum(1 for c in self.chiusure if c['scelto'])
        fogli = collections.Counter((v.get('foglio') or {}).get('azione') for v in valide)
        pei = collections.Counter(p['azione'] for p in self.pei.values())
        operatori_cambiati = sum(1 for o in self.operatori.values() if self._cambi_operatore(o) or o.get('cf_nuovo'))
        sigle = collections.Counter(calc.TIPO_SIGLA.get(c['valori']['causale']) for c in celle
                                    if c['valori']['sigla'])
        return {
            'righe': len(self.lettura['righe']), 'righe_importate': len(valide),
            'righe_escluse': len(self.lettura['righe']) - len(valide),
            'celle_escluse': sum(1 for v in valide for c in v['r']['celle'].values() if c['esito'] == 'errore'),
            'operatori': len(self.operatori), 'alunni': len(self.alunni), 'scuole': len(self.scuole),
            'minuti': sum(c['minuti'] for c in celle), 'giorni_con_ore': sum(1 for c in celle if c['minuti']),
            'minuti_file': self.minuti_file(),
            'sigle': {k: sigle[k] for k in ('ferie', 'malattia', 'permesso') if sigle[k]},
            'nuovi': {'scuole': sum(1 for s in self.scuole.values() if s['nuova'] and s['usata']),
                      'alunni': sum(1 for a in self.alunni.values() if a['nuovo']),
                      'operatori': sum(1 for o in self.operatori.values() if o['nuovo']),
                      'coppie': coppie_nuove, 'pei': pei['nuovo'],
                      'qualifiche': sum(1 for q in self.qualifiche.values() if q['figura']),
                      'fogli': fogli['nuovo']},
            'aggiornati': {'coppie': coppie_cambiate, 'pei': pei['cambia_dal_mese'] + pei['cambia_ore'] + pei['anticipa'],
                           'operatori': operatori_cambiati, 'fogli': fogli['cambia'],
                           'scuole': sum(1 for s in self.scuole.values() if s.get('completa')),
                           'alunni': sum(1 for a in self.alunni.values() if a.get('cf_nuovo'))},
            'presenze': {'nuove': azioni['nuova'], 'uguali': azioni['uguale'], 'cambiate': azioni['cambia'],
                         'da_programmato': azioni['da_programmato'],
                         'manuali_diverse': azioni['manuale_diversa'] + azioni['sovrascrivi'],
                         'sovrascritte': azioni['sovrascrivi'], 'da_togliere': len(self.togliere),
                         'solo_in_assisto': len(self.solo_in_assisto)},
        }

    def minuti_file(self):
        """Le ore di tutte le righe del file (anche quelle che non si importano), dalle celle
        dei giorni, con la lettura scelta per le ore da confermare (decimale finche' non si
        sceglie)."""
        return sum(self._minuti(r, c) for r in self.lettura['righe'] for c in r['celle'].values()
                   if c['esito'] in ('ore', 'da_confermare'))

    def _cambi_operatore(self, o):
        if o.get('nuovo') or not o.get('id'):
            return {}
        if o.get('ore_contratto_assisto') is None and o.get('ore_contratto') is not None:
            return {'ore_contratto': float(o['ore_contratto'])}
        return {}

    def nessun_cambiamento(self):
        c = self.conteggi()
        return (not any(c['nuovi'].values()) and not any(c['aggiornati'].values())
                and not (c['presenze']['nuove'] or c['presenze']['cambiate'] or c['presenze']['da_programmato']
                         or c['presenze']['sovrascritte'] or c['presenze']['da_togliere']))

    def ore_per_figura(self):
        """Ore per figura e per grado (come il prospetto della fattura), dai giorni del file."""
        out = collections.OrderedDict()
        figure = sorted(self.ctx['figure'].values(), key=lambda f: f['ordine'])
        for f in figure:
            out[f['codice']] = {'figura': f['codice'], 'nome': napoli_db.nome_figura(f['codice']), 'righe': 0,
                                'minuti': 0, 'per_grado': {'inferiore': 0, 'superiore': 0, 'da_decidere': 0}}
        for voce in self.righe:
            if not voce['valida']:
                continue
            x = out[voce['figura']]
            x['righe'] += 1
            m = sum(c['minuti'] for c in voce['celle'])
            x['minuti'] += m
            x['per_grado'][self.grado_della_riga(voce)] += m
        return [x for x in out.values() if x['righe']]


# ==================== scrittura (conferma) e annullamento ====================

class NonRiuscito(napoli_db.ErroreNapoli):
    stato = 503
    codice = 'NON_RIUSCITO'


# Colonne delle tabelle toccate dall'import (per cambiare una riga se ne salvano prima
# solo le colonne cambiate; per le presenze la riga intera, che non ha dati personali).
TABELLE_IMPORT = ('alias_qualifiche', 'scuole', 'operatori', 'alunni', 'coppie', 'pei', 'fogli', 'presenze')


class _Registro:
    """Le righe create, cambiate e tolte da un import, per "Annulla import"
    (napoli_import.sostituite_json): id e valori di prima, mai codici fiscali. Delle
    anagrafiche si cambiano solo campi vuoti (ore di contratto, municipalita' della scuola)
    e i codici fiscali sbagliati corretti dal file: di quelli si salva solo la differenza
    (differenza_cf, al piu' due caratteri), mai il codice."""

    def __init__(self, conn):
        self.conn = conn
        self.create = collections.defaultdict(list)
        self.cambiate, self.tolte = [], []

    def inserisci(self, tabella, valori, registra=True):
        assert tabella in TABELLE_IMPORT, tabella
        nomi = ', '.join(valori)
        segnaposto = ', '.join('?' * len(valori))
        cur = self.conn.execute(f'INSERT INTO napoli_{tabella} ({nomi}) VALUES ({segnaposto})', tuple(valori.values()))
        if registra:
            self.create[tabella].append(cur.lastrowid)
        return cur.lastrowid

    def cambia(self, tabella, id_, valori):
        assert tabella in TABELLE_IMPORT and tabella != 'alias_qualifiche', tabella
        if tabella == 'presenze':
            prima = dict(self.conn.execute('SELECT * FROM napoli_presenze WHERE id = ?', (id_,)).fetchone())
        else:
            elenco = ', '.join(valori)
            prima = dict(self.conn.execute(f'SELECT {elenco} FROM napoli_{tabella} WHERE id = ?', (id_,)).fetchone())
        assegna = ', '.join(f'{k} = ?' for k in valori)
        self.conn.execute(f'UPDATE napoli_{tabella} SET {assegna} WHERE id = ?', tuple(valori.values()) + (id_,))
        self.cambiate.append({'tabella': tabella, 'id': id_, 'prima': prima})

    def correggi_cf(self, tabella, id_, vecchio, nuovo):
        """Il codice fiscale di un alunno o di un operatore corretto con quello del file."""
        assert tabella in ('alunni', 'operatori'), tabella
        differenza = differenza_cf(nuovo, vecchio)
        if differenza is None:           # il piano lo controlla prima: codici troppo diversi non si correggono
            return
        valori, prima = {'codice_fiscale': nuovo}, {}
        if tabella == 'operatori':
            prima['cf_valido'] = self.conn.execute('SELECT cf_valido FROM napoli_operatori WHERE id = ?',
                                                   (id_,)).fetchone()[0]
            valori['cf_valido'] = 1
        assegna = ', '.join(f'{k} = ?' for k in valori)
        self.conn.execute(f'UPDATE napoli_{tabella} SET {assegna} WHERE id = ?', tuple(valori.values()) + (id_,))
        self.cambiate.append({'tabella': tabella, 'id': id_, 'prima': prima, 'differenza_cf': differenza})

    def togli_presenza(self, presenza_id):
        riga = dict(self.conn.execute('SELECT * FROM napoli_presenze WHERE id = ?', (presenza_id,)).fetchone())
        fasce = _righe(self.conn, 'SELECT tipo, ordine, ora_inizio, ora_fine FROM napoli_presenze_fasce '
                                  'WHERE presenza_id = ? ORDER BY id', (presenza_id,))
        self.conn.execute('DELETE FROM napoli_presenze WHERE id = ?', (presenza_id,))
        self.tolte.append({'riga': riga, 'fasce': fasce})

    def json(self):
        return json.dumps({'versione': 1, 'create': dict(self.create), 'cambiate': self.cambiate, 'tolte': self.tolte},
                          ensure_ascii=False, default=str)


def _iso(valore):
    return valore.isoformat() if isinstance(valore, datetime.date) else valore


def _applica(conn, piano, import_id, ora):
    """Scrive il piano (dentro la transazione della conferma). Ritorna il registro."""
    reg = _Registro(conn)
    lotto_id = piano.ctx['lotto']['id']
    for q in piano.qualifiche.values():
        if q['figura']:
            conn.execute("INSERT INTO napoli_alias_qualifiche (testo, figura, origine) VALUES (?, ?, 'utente')",
                         (q['testo'], q['figura']))
            reg.create['alias_qualifiche'].append(q['testo'])
    for s in piano.scuole.values():
        if s['nuova'] and s['usata']:
            s['id'] = reg.inserisci('scuole', {
                'lotto_id': lotto_id, 'nome': s['nome'], 'codice_meccanografico': s['codice'], 'grado': s['grado'],
                'municipalita': s['municipalita'], 'data_inserimento': ora})
        elif s.get('completa'):
            reg.cambia('scuole', s['id'], {'municipalita': s['municipalita']})
    for o in piano.operatori.values():
        if o['nuovo']:
            o['id'] = reg.inserisci('operatori', {
                'cognome': o['cognome'], 'nome': o['nome'], 'codice_fiscale': o['cf'] or None,
                'cf_valido': 1 if o['cf_esito'] == 'ok' else 0, 'figura': o['figura'],
                'qualifica_originale': o.get('qualifica'),
                'ore_contratto': None if o['ore_contratto'] is None else float(o['ore_contratto']),
                'data_inserimento': ora})
        else:
            if piano._cambi_operatore(o):
                reg.cambia('operatori', o['id'], piano._cambi_operatore(o))
            if o.get('cf_nuovo'):
                reg.correggi_cf('operatori', o['id'], o['cf_assisto'], o['cf_nuovo'])
    for a in piano.alunni.values():
        if a['nuovo']:
            a['id'] = reg.inserisci('alunni', {
                'lotto_id': lotto_id, 'cognome': a['cognome'], 'nome': a['nome'], 'codice_fiscale': a['cf'],
                'scuola_id': a['scuola']['id'], 'data_inserimento': ora})
        elif a.get('cf_nuovo'):
            reg.correggi_cf('alunni', a['id'], a['cf_assisto'], a['cf_nuovo'])
    valide = [v for v in piano.righe if v['valida']]
    for v in sorted(valide, key=lambda v: v['ruolo'] != 'titolare'):        # i titolari prima dei sostituti
        if v['coppia_nuova']:
            titolare = v.get('titolare') if v['ruolo'] == 'sostituto' else None
            v['coppia_id'] = reg.inserisci('coppie', {
                'lotto_id': lotto_id, 'alunno_id': v['alunno']['id'], 'operatore_id': v['operatore']['id'],
                'scuola_id': v['scuola']['id'], 'figura': v['figura'], 'ruolo': v['ruolo'],
                'titolare_coppia_id': titolare['coppia_id'] if titolare else None,
                'valido_da': _iso(v['valido_da']), 'valido_a': _iso(v['valido_a']), 'origine': 'import_excel',
                'data_inserimento': ora})
        elif v['coppia_cambi']:
            reg.cambia('coppie', v['coppia_id'], {k: _iso(x) for k, x in v['coppia_cambi'].items()})
    for s in piano.subentri:
        t = s['titolare']
        if s['scelto'] and t.get('riga') is None and t.get('coppia_cambi'):
            reg.cambia('coppie', t['coppia_id'], dict(t['coppia_cambi']))
    for c in piano.chiusure:
        if c['scelto']:
            reg.cambia('coppie', c['coppia']['id'], {'valido_a': c['chiudi_al'].isoformat()})
    fonte = f'Foglio presenze di {mese_testo(piano.anno, piano.mese)}'
    for p in piano.pei.values():
        base = {'alunno_id': p['alunno']['id'], 'figura': p['figura'], 'ore_settimanali': float(p['ore']),
                'stato': 'definitivo', 'fonte': fonte, 'data_inserimento': ora}
        if p['azione'] == 'nuovo':
            reg.inserisci('pei', dict(base, valido_da=_iso(p['valido_da']), valido_a=_iso(p['valido_a'])))
        elif p['azione'] == 'cambia_dal_mese':
            prima = piano.inizio - datetime.timedelta(days=1)
            reg.cambia('pei', p['precedente']['id'], {'valido_a': prima.isoformat()})
            reg.inserisci('pei', dict(base, valido_da=piano.inizio.isoformat(), valido_a=p['precedente']['valido_a']))
        elif p['azione'] == 'cambia_ore':
            reg.cambia('pei', p['precedente']['id'], {'ore_settimanali': float(p['ore']), 'fonte': fonte})
        elif p['azione'] == 'anticipa':
            reg.cambia('pei', p['precedente']['id'], {'valido_da': piano.inizio.isoformat()})
    for v in valide:
        f = v.get('foglio')
        if f and f['azione'] == 'nuovo':
            reg.inserisci('fogli', {'coppia_id': v['coppia_id'], 'anno': piano.anno, 'mese': piano.mese,
                                    'stato': 'registrato', 'note': f['note']})
        elif f and f['azione'] == 'cambia':
            reg.cambia('fogli', f['id'], f['cambi'])
    for p in piano.togliere:
        reg.togli_presenza(p['id'])
    for v in valide:
        for c in v['celle']:
            if c['azione'] in ('uguale', 'manuale_diversa'):
                continue
            valori = dict(c['valori'], stato='registrato', calcolo='manuale', trattamento=None, minuti_svolti=None,
                          origine='import_excel', import_id=import_id, modificato_il=ora)
            if c['azione'] == 'nuova':
                reg.inserisci('presenze', dict(valori, coppia_id=v['coppia_id'], lotto_id=lotto_id,
                                               data=c['data'].isoformat(), figura=v['figura'], minuti_programmati=0),
                              registra=False)
            else:
                reg.cambia('presenze', c['presenza']['id'], valori)
    return reg


def _esito(piano):
    """Esito di un import da salvare e mostrare: solo conteggi (mai nomi o codici fiscali)."""
    c = piano.conteggi()
    return {'righe': c['righe'], 'righe_importate': c['righe_importate'], 'operatori': c['operatori'],
            'alunni': c['alunni'], 'scuole': c['scuole'], 'minuti': c['minuti'], 'nuovi': c['nuovi'],
            'aggiornati': c['aggiornati'], 'presenze': c['presenze'],
            'avvisi': dict(collections.Counter(a['codice'] for a in piano.lettura['anomalie'] + piano.avvisi))}


def _annulla_registro(conn, registro, import_id):
    """Rimette com'era tutto quello che l'import ha fatto (in ordine inverso)."""
    cambiate = registro.get('cambiate') or []
    create = registro.get('create') or {}
    # le presenze create dall'import: quelle con il suo numero che prima non c'erano
    cambiate_presenze = {c['id'] for c in cambiate if c['tabella'] == 'presenze'}
    for (id_,) in conn.execute('SELECT id FROM napoli_presenze WHERE import_id = ?', (import_id,)).fetchall():
        if id_ not in cambiate_presenze:
            conn.execute('DELETE FROM napoli_presenze WHERE id = ?', (id_,))
    for voce in reversed(cambiate):
        tabella = voce['tabella']
        if tabella not in TABELLE_IMPORT:
            raise ValueError(tabella)
        prima = {k: v for k, v in voce['prima'].items() if k != 'id'}
        if 'differenza_cf' in voce:         # codice fiscale corretto: si torna a quello di prima
            attuale = conn.execute(f'SELECT codice_fiscale FROM napoli_{tabella} WHERE id = ?', (voce['id'],)).fetchone()
            if attuale is None:
                continue
            prima['codice_fiscale'] = applica_differenza_cf(attuale[0] or '', voce['differenza_cf'])
        if not prima:
            continue
        assegna = ', '.join(f'{k} = ?' for k in prima)
        conn.execute(f'UPDATE napoli_{tabella} SET {assegna} WHERE id = ?', tuple(prima.values()) + (voce['id'],))
    for voce in registro.get('tolte') or []:
        riga = voce['riga']
        nomi = ', '.join(riga)
        conn.execute(f'INSERT INTO napoli_presenze ({nomi}) VALUES ({", ".join("?" * len(riga))})', tuple(riga.values()))
        for f in voce.get('fasce') or []:
            conn.execute('INSERT INTO napoli_presenze_fasce (presenza_id, tipo, ordine, ora_inizio, ora_fine) '
                         'VALUES (?, ?, ?, ?, ?)', (riga['id'], f['tipo'], f['ordine'], f['ora_inizio'], f['ora_fine']))
    for tabella in ('fogli', 'pei', 'coppie', 'alunni', 'operatori', 'scuole'):
        for id_ in sorted(create.get(tabella) or [], reverse=True):
            conn.execute(f'DELETE FROM napoli_{tabella} WHERE id = ?', (id_,))
    for testo in create.get('alias_qualifiche') or []:
        conn.execute("DELETE FROM napoli_alias_qualifiche WHERE testo = ? AND origine = 'utente'", (testo,))


# ==================== testi per la pagina (con i codici fiscali mascherati) ====================

def _testo_presenza(p):
    if p is None:
        return ''
    if p.get('sigla'):
        return p['sigla']
    if p.get('stato') == 'programmato':
        return 'da registrare'
    return calc.ore_due_forme(p.get('minuti_riconosciuti') or 0)


def _testo_valori(valori):
    return valori['sigla'] if valori['sigla'] else calc.ore_due_forme(valori['minuti_riconosciuti'])


def _ore_testo(minuti):
    return calc.numero_it(calc.ore_decimali(minuti))


class _Nomi:
    """Nomi di alunni e operatori di Assisto (per le proposte da confermare)."""

    def __init__(self, ctx):
        self.alunni = {a['id']: _nome_persona(a) for a in ctx['alunni']}
        self.operatori = {o['id']: _nome_persona(o) for o in ctx['operatori']}

    def coppia(self, c):
        if not c:
            return {'alunno': '', 'operatore': ''}
        return {'alunno': self.alunni.get(c['alunno_id'], ''), 'operatore': self.operatori.get(c['operatore_id'], '')}


def _nome_voce(voce):
    return _nome_persona(voce) if voce else ''


def _risposta(piano, lettura, ctx, sha, nome_file, modo):
    nomi = _Nomi(ctx)
    gruppi = _gruppi(lettura['anomalie'] + piano.avvisi)
    precedenti = [i for i in ctx['imports'] if not i['annullato'] and (i['anno'], i['mese']) == (piano.anno, piano.mese)]
    ultimo = precedenti[-1] if precedenti else None
    out = {
        'modo': modo,
        'file': {'nome': nome_file, 'sha256': sha, 'foglio': lettura['foglio'], 'anno': piano.anno, 'mese': piano.mese,
                 'mese_testo': mese_testo(piano.anno, piano.mese)},
        'lotto': {'id': ctx['lotto']['id'], 'nome': ctx['lotto']['nome'], 'numero_lotto': ctx['lotto']['numero_lotto']},
        'versione_dati': ctx['versione'],
        'mese_chiuso': ctx['chiuso'],
        'reimport': None if ultimo is None else {
            'import_id': ultimo['id'], 'data': ultimo['data'], 'nome_file': ultimo['nome_file'],
            'stesso_file': ultimo['sha256'] == sha},
        'conteggi': piano.conteggi(),
        'ore_per_figura': [dict(x, ore=_ore_testo(x['minuti']),
                                per_grado_ore={g: _ore_testo(m) for g, m in x['per_grado'].items()})
                           for x in piano.ore_per_figura()],
        'bloccanti': [g for g in gruppi if g['livello'] == 'bloccante'],
        'avvisi': [g for g in gruppi if g['livello'] == 'avviso'],
        'note': [g for g in gruppi if g['livello'] == 'nota'],
        'segnalazioni': {
            'righe_con_assenze_in_nota': sum(1 for r in lettura['righe'] if r['giorni_assente_note']),
            'giorni_assenza_in_nota': sum(len(r['giorni_assente_note']) for r in lettura['righe']),
            'celle_colorate': sum(r['colorate'] for r in lettura['righe'])},
    }
    c = out['conteggi']
    out['totale'] = {'minuti': c['minuti_file'], 'ore': _ore_testo(c['minuti_file']), 'hhmm': calc.hhmm(c['minuti_file'])}
    out['totale_importato'] = {'minuti': c['minuti'], 'ore': _ore_testo(c['minuti']), 'hhmm': calc.hhmm(c['minuti'])}
    if modo == 'confronto':
        out['confronto'] = _confronto(piano, nomi)
        return _senza_codici(out)
    out['qualifiche'] = [{'testo': q['testo'], 'proposta': q['proposta'], 'figura': q['figura'],
                          'righe': q['righe'][:20], 'n_righe': len(q['righe'])} for q in piano.qualifiche.values()]
    out['scuole_nuove'] = [{'chiave': s['chiave'], 'nome': s['nome'], 'codice': s['codice'] or '',
                            'municipalita': s['municipalita'], 'grado_proposto': s['grado_proposto'] or '',
                            'grado': s['grado'] or '', 'n_righe': len(s['righe'])}
                           for s in piano.scuole.values() if s['nuova'] and s['usata']]
    out['scuole_senza_grado'] = [{'nome': s['nome'], 'codice': s['codice'] or '', 'municipalita': s['municipalita'],
                                  'grado': s['grado'] or ''}
                                 for s in piano.scuole.values() if not s['nuova'] and not calc.grado_fattura(s['grado'])]
    out['ore_ambigue'] = []
    for chiave, x in sorted(piano.ambigue.items(), key=lambda kv: (kv[1]['riga'], kv[1]['data'])):
        cella = x['cella']
        out['ore_ambigue'].append({
            'chiave': chiave, 'riga': x['riga'], 'colonna': cella['colonna'], 'data': x['data'].isoformat(),
            'testo': cella['testo'], 'scelta': x['scelta'], 'ricordata': x['ricordata'],
            'alternative': [{'lettura': a['lettura'], 'testo': a['testo'], 'minuti': a['minuti']}
                            for a in cella['alternative']]})
    out['ore_ambigue_da_scegliere'] = len(piano.ore_ambigue_da_scegliere())
    out['conferme'] = []
    if 'plessi' in piano.conferme:
        out['conferme'].append({
            'codice': 'plessi', 'titolo': 'La stessa scuola in due municipalità',
            'testo': 'La municipalità è quella della scuola. Queste scuole compaiono con municipalità diverse, nel '
                     'file o fra il file e Assisto: una municipalità nuova diventa un altro plesso della stessa '
                     'scuola, le coppie già in Assisto restano nel loro plesso. Se è un errore di scrittura, '
                     'correggi il file e rifai l\'anteprima.',
            'voci': [{'testo': f'{v["nome"]} ({v["codice"] or "senza codice"}): {v["testo"]}',
                      'righe': v['righe'][:20]} for v in piano.conferme['plessi']]})
    if 'operatori_per_nome' in piano.conferme:
        def voce_operatore(o):
            testo = (f'{o["nome_file"]}: nel file {calc.maschera_codice_fiscale(o["cf"]) or "senza codice"}, '
                     f'in Assisto {calc.maschera_codice_fiscale(o.get("cf_assisto")) or "senza codice"}')
            if o.get('cf_nuovo'):
                testo += ' (il codice del file è giusto: si corregge anche in Assisto)'
            return {'testo': testo, 'righe': o['righe'][:20]}
        out['conferme'].append({
            'codice': 'operatori_per_nome', 'titolo': 'Operatori riconosciuti dal nome',
            'testo': 'Il codice fiscale nel file e quello in Assisto non sono uguali (uno dei due è scritto male), '
                     'ma in Assisto c\'è un operatore con lo stesso nome: si considera la stessa persona. Se non '
                     'lo è, correggi il codice fiscale nel file e rifai l\'anteprima.',
            'voci': [voce_operatore(o) for o in piano.conferme['operatori_per_nome']]})
    out['subentri'] = []
    for s in piano.subentri:
        sost, tit = s['sostituto'], s['titolare']
        nome_tit = _nome_voce(tit['operatore']) if tit.get('riga') is not None else \
            nomi.coppia(tit['coppia_assisto'])['operatore']
        out['subentri'].append({
            'riga': s['riga'], 'scelto': s['scelto'], 'chiudi_al': s['chiudi_al'].isoformat(),
            'testo': f'Riga {s["riga"]}: {_nome_voce(sost["operatore"])} prende il posto di {nome_tit} con '
                     f'{_nome_voce(sost["alunno"])} ({napoli_db.nome_figura(sost["figura"])}) dal '
                     f'{calc.data_it(sost["r"]["data_inizio"])}: la coppia di {nome_tit} finisce il '
                     f'{calc.data_it(s["chiudi_al"])}.'})
    out['chiusure'] = [{'id': c['coppia']['id'], 'scelto': c['scelto'], 'chiudi_al': c['chiudi_al'].isoformat(),
                        'testo': f'{nomi.coppia(c["coppia"])["operatore"]} con {nomi.coppia(c["coppia"])["alunno"]} '
                                 f'({napoli_db.nome_figura(c["coppia"]["figura"])}'
                                 f'{", sostituto" if c["coppia"]["ruolo"] == "sostituto" else ""}): non è nel file, '
                                 f'si chiude il {calc.data_it(c["chiudi_al"])}'}
                       for c in piano.chiusure]
    out['coppie_del_mese'] = [{'id': c['id'], 'testo': f'{nomi.coppia(c)["operatore"]} con {nomi.coppia(c)["alunno"]} '
                                                      f'({napoli_db.nome_figura(c["figura"])}'
                                                      f'{", sostituto" if c["ruolo"] == "sostituto" else ""}): '
                                                      f'comincia il {calc.data_it(calc.data(c["valido_da"]))}'}
                              for c in piano.coppie_del_mese]
    out['manuali_diverse'] = [{'riga': m['voce']['riga'], 'colonna': m['colonna'], 'data': m['data'].isoformat(),
                               'alunno': _nome_voce(m['voce']['alunno']),
                               'operatore': _nome_voce(m['voce']['operatore']),
                               'assisto': _testo_presenza(m['presenza']), 'file': _testo_valori(m['valori'])}
                              for m in piano.manuali_diverse[:100]]
    out['solo_in_assisto'] = [dict(nomi.coppia(x['coppia']), data=x['presenza']['data'],
                                   assisto=_testo_presenza(x['presenza']))
                              for x in piano.solo_in_assisto[:100]]
    out['conferme_richieste'] = list(piano.conferme)
    out['puo_importare'] = not out['bloccanti']
    out['nessun_cambiamento'] = piano.nessun_cambiamento()
    return _senza_codici(out)


def _confronto(piano, nomi):
    """Solo confronto: le differenze fra il file e i giorni registrati in Assisto."""
    righe_non_in_assisto, differenze, uguali = [], [], 0
    per_coppia = collections.defaultdict(dict)
    for p in piano.ctx['presenze']:
        if p['stato'] == 'registrato':
            per_coppia[p['coppia_id']][p['data']] = p
    nel_file = set()
    for v in piano.righe:
        if not v['valida']:
            continue
        minuti_file = sum(c['minuti'] for c in v['celle'])
        if not v['coppia_id']:
            righe_non_in_assisto.append({'riga': v['riga'], 'alunno': _nome_voce(v['alunno']),
                                         'operatore': _nome_voce(v['operatore']),
                                         'figura': napoli_db.nome_figura(v['figura']), 'ore': _ore_testo(minuti_file)})
            continue
        nel_file.add(v['coppia_id'])
        dal_file = {c['data'].isoformat(): c for c in v['celle']}
        in_assisto = per_coppia.get(v['coppia_id'], {})
        giorni = []
        for d in sorted(set(dal_file) | set(in_assisto)):
            f, a = dal_file.get(d), in_assisto.get(d)
            if f and a and _stessi_valori(a, f['valori']):
                continue
            giorni.append({'data': d, 'file': _testo_valori(f['valori']) if f else 'vuoto',
                           'assisto': _testo_presenza(a) if a else 'vuoto'})
        if giorni:
            minuti_assisto = sum(p['minuti_riconosciuti'] or 0 for p in in_assisto.values())
            differenze.append({'riga': v['riga'], 'alunno': _nome_voce(v['alunno']),
                               'operatore': _nome_voce(v['operatore']), 'figura': napoli_db.nome_figura(v['figura']),
                               'ore_file': _ore_testo(minuti_file), 'ore_assisto': _ore_testo(minuti_assisto),
                               'giorni': giorni})
        else:
            uguali += 1
    coppie = {c['id']: c for c in piano.ctx['coppie']}
    solo_in_assisto = []
    for coppia_id, giorni in per_coppia.items():
        if coppia_id not in nel_file:
            c = coppie.get(coppia_id)
            solo_in_assisto.append(dict(nomi.coppia(c), figura=napoli_db.nome_figura(c['figura']) if c else '',
                                        ore=_ore_testo(sum(p['minuti_riconosciuti'] or 0 for p in giorni.values()))))
    return {'coppie_uguali': uguali, 'differenze': differenze, 'righe_non_in_assisto': righe_non_in_assisto,
            'coppie_solo_in_assisto': solo_in_assisto}


# ==================== funzioni pubbliche ====================

def _leggi(dati, nome_file, regole=None):
    return leggi_master(dati, nome_file, regole)


def _prepara(lotto_id, dati, nome_file, scelte, solo_confronto=False):
    """Lettura del file, dati di Napoli del mese, piano. Non scrive nulla."""
    lettura = _leggi(dati, nome_file)
    with db.get_db_context() as conn:
        ctx = _contesto(conn, lotto_id, lettura['anno'], lettura['mese'])
    limiti = ('max_minuti_giorno_avviso', 'max_minuti_giorno_blocco', 'giorni_servizio', 'tetto_coeff',
              'tetto_arrotondamento')
    if any(ctx['regole'][k] != config_napoli.REGOLE_PREDEFINITE[k]['valore'] for k in limiti):
        lettura = _leggi(dati, nome_file, ctx['regole'])          # limiti diversi per questo lotto e mese
    piano = _Piano(ctx, lettura, _scelte(scelte, ctx), solo_confronto)
    return lettura, ctx, piano


def anteprima(lotto_id, dati, nome_file='', scelte=None, modo='import'):
    """Anteprima dell'import (modo 'import') o solo confronto (modo 'confronto'): non
    scrive nulla. Ritorna i dati per la pagina (codici fiscali mascherati)."""
    if modo not in ('import', 'confronto'):
        raise DatiNonValidi('Scegli se importare o solo confrontare.', 'modo')
    lettura, ctx, piano = _prepara(lotto_id, dati, nome_file, scelte, modo == 'confronto')
    return _risposta(piano, lettura, ctx, hashlib.sha256(dati).hexdigest(), nome_file, modo)


def _registra_ctrl_z(conn, import_id, descrizione):
    napoli_db.registra_azione(conn, 'import', descrizione, {'versione': 1, 'import_id': import_id})


def conferma(lotto_id, dati, nome_file, sha256_anteprima, versione_dati, scelte=None):
    """Importa il file visto nell'anteprima: stesso file (sha256), stessi dati di Napoli
    (versione_dati), nessun bloccante, conferme date. Copia di sicurezza del database,
    poi tutto in un'unica transazione. Ritorna {'import_id', 'messaggio', 'esito', ...}."""
    sha = hashlib.sha256(dati).hexdigest()
    if not sha256_anteprima or sha != str(sha256_anteprima).strip().lower():
        raise Conflitto('Il file non è più quello dell\'anteprima (forse è stato modificato o salvato di nuovo): '
                        'rifai l\'anteprima.', 'file', codice='FILE_CAMBIATO')
    lettura, ctx, piano = _prepara(lotto_id, dati, nome_file, scelte)
    testo_mese = mese_testo(piano.anno, piano.mese)
    if ctx['chiuso']:
        raise Conflitto(f'Il mese di {testo_mese} del lotto è chiuso: riaprilo prima di importare.',
                        codice='MESE_CHIUSO_LOTTO')
    if ctx['versione'] != versione_dati:
        raise Conflitto('Dopo l\'anteprima i dati di Napoli sono cambiati: rifai l\'anteprima prima di importare.',
                        codice='ANTEPRIMA_SUPERATA')
    bloccanti = piano.bloccanti()
    if bloccanti:
        raise DatiNonValidi('Prima di importare bisogna correggere il file: guarda la parte «Da correggere» '
                            'dell\'anteprima.', codice='IMPORT_BLOCCATO', bloccanti=_gruppi(bloccanti))
    if piano.ore_ambigue_da_scegliere():
        raise DatiNonValidi('Prima di importare scegli come leggere le ore nella parte «Ore da confermare».',
                            codice='DA_CONFERMARE', mancano=['ore_ambigue'])
    mancano = [c for c in piano.conferme if c not in piano.scelte['conferme']]
    if mancano:
        raise DatiNonValidi('Prima di importare spunta le caselle «Ho controllato» nella parte «Da confermare».',
                            codice='DA_CONFERMARE', mancano=mancano)
    if piano.nessun_cambiamento():
        return {'import_id': None, 'nessun_cambiamento': True, 'esito': _esito(piano),
                'messaggio': f'Niente da cambiare: {testo_mese} è già in Assisto così com\'è nel file'}
    copia = db.create_backup()
    if not copia:
        raise NonRiuscito('Non sono riuscito a fare la copia di sicurezza del database, quindi l\'import non è stato '
                          'fatto. Riprova; se succede ancora, controlla che sul disco ci sia spazio.',
                          codice='COPIA_NON_RIUSCITA')
    ora = _ora()
    nome = str(nome_file or '').replace('\\', '/').rsplit('/', 1)[-1][:200] or None
    with db.get_db_context() as conn:
        conn.execute('BEGIN IMMEDIATE')
        ctx_ora = _contesto(conn, lotto_id, piano.anno, piano.mese)
        if ctx_ora['versione'] != ctx['versione']:
            raise Conflitto('Mentre preparavo l\'import i dati di Napoli sono cambiati: rifai l\'anteprima.',
                            codice='ANTEPRIMA_SUPERATA')
        piano = _Piano(ctx_ora, lettura, piano.scelte)
        cur = conn.execute('INSERT INTO napoli_import (lotto_id, anno, mese, nome_file, sha256, n_righe, esito_json, '
                           'sostituite_json, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                           (lotto_id, piano.anno, piano.mese, nome, sha, len(lettura['righe']), '{}', '{}', ora))
        import_id = cur.lastrowid
        registro = _applica(conn, piano, import_id, ora)
        esito = _esito(piano)
        conn.execute('UPDATE napoli_import SET esito_json = ?, sostituite_json = ? WHERE id = ?',
                     (json.dumps(esito, ensure_ascii=False, default=str), registro.json(), import_id))
        ore = _ore_testo(esito['minuti'])
        _registra_ctrl_z(conn, import_id, f'Import del foglio presenze di {testo_mese}: {esito["righe_importate"]} '
                                          f'righe, {ore} ore')
    db.log_audit('import', 'napoli_import', import_id,
                 dettagli=f'Napoli, {ctx["lotto"]["nome"]}: import del foglio presenze di {testo_mese} '
                          f'({esito["righe_importate"]} righe, {ore} ore, {esito["presenze"]["nuove"]} giorni nuovi, '
                          f'{esito["presenze"]["cambiate"]} cambiati, {esito["presenze"]["da_togliere"]} tolti); '
                          f'copia di sicurezza {copia}')
    return {'import_id': import_id, 'nessun_cambiamento': False, 'esito': esito, 'copia': copia,
            'messaggio': f'Importato {testo_mese}: {esito["righe_importate"]} righe, {ore} ore'}


def _ultimo_import(imports):
    validi = [i for i in imports if not i['annullato']]
    return validi[-1] if validi else None


def storico(lotto_id):
    """Gli import del lotto, dal piu' recente: solo conteggi; si puo' annullare l'ultimo."""
    with db.get_db_context() as conn:
        napoli_db.lotto(lotto_id, conn)
        imports = _righe(conn, 'SELECT id, anno, mese, nome_file, n_righe, esito_json, annullato, data '
                               'FROM napoli_import WHERE lotto_id = ? ORDER BY id', (lotto_id,))
        chiusi = {(r['anno'], r['mese']) for r in _righe(conn, 'SELECT anno, mese FROM napoli_mesi_chiusi '
                                                               'WHERE lotto_id = ?', (lotto_id,))}
    ultimo = _ultimo_import(imports)
    out = []
    for i in reversed(imports):
        try:
            esito = json.loads(i['esito_json'] or '{}')
        except ValueError:
            esito = {}
        out.append({'id': i['id'], 'anno': i['anno'], 'mese': i['mese'],
                    'mese_testo': mese_testo(i['anno'], i['mese']) if i['anno'] and i['mese'] else '',
                    'nome_file': i['nome_file'] or '', 'data': i['data'], 'annullato': bool(i['annullato']),
                    'righe': esito.get('righe_importate', i['n_righe']),
                    'ore': _ore_testo(esito.get('minuti') or 0) if 'minuti' in esito else '',
                    'presenze': esito.get('presenze') or {},
                    'annullabile': bool(ultimo and ultimo['id'] == i['id'] and (i['anno'], i['mese']) not in chiusi)})
    return out


def annulla_import(import_id):
    """Annulla l'ultimo import del lotto: toglie quello che ha creato e rimette le righe
    cambiate o tolte com'erano. Copia di sicurezza prima. Errori: non e' l'ultimo, mese
    chiuso, ore cambiate a mano dopo l'import, dati aggiunti dopo e collegati."""
    with db.get_db_context() as conn:
        imp = conn.execute('SELECT * FROM napoli_import WHERE id = ?', (import_id,)).fetchone()
        if imp is None:
            raise NonTrovato('Questo import non c\'è più: ricarica la pagina.')
        imp = dict(imp)
        lotto = napoli_db.lotto(imp['lotto_id'], conn)
        imports = _righe(conn, 'SELECT id, annullato FROM napoli_import WHERE lotto_id = ? ORDER BY id',
                         (imp['lotto_id'],))
        testo_mese = mese_testo(imp['anno'], imp['mese'])
        if imp['annullato']:
            raise Conflitto('Questo import è già stato annullato.', codice='IMPORT_GIA_ANNULLATO')
        if _ultimo_import(imports)['id'] != imp['id']:
            raise Conflitto('Si può annullare solo l\'ultimo import del lotto: annulla prima quelli fatti dopo.',
                            codice='IMPORT_NON_ULTIMO')
        if conn.execute('SELECT 1 FROM napoli_mesi_chiusi WHERE lotto_id = ? AND anno = ? AND mese = ?',
                        (imp['lotto_id'], imp['anno'], imp['mese'])).fetchone():
            raise Conflitto(f'Il mese di {testo_mese} del lotto è chiuso: riaprilo prima di annullare l\'import.',
                            codice='MESE_CHIUSO_LOTTO')
        cambiate_dopo = conn.execute('SELECT COUNT(*) FROM napoli_presenze WHERE import_id = ? AND '
                                     "(origine <> 'import_excel' OR modificato_il <> ?)",
                                     (import_id, imp['data'])).fetchone()[0]
        if cambiate_dopo:
            raise Conflitto(f'Dopo l\'import {cambiate_dopo} giorni sono stati cambiati a mano: l\'import non si può '
                            'più annullare tutto insieme.', codice='IMPORT_CAMBIATO_DOPO')
    try:
        registro = json.loads(imp['sostituite_json'] or '{}')
    except ValueError:
        registro = {}
    if registro.get('versione') != 1:
        raise Conflitto('Questo import non si può annullare da qui.', codice='IMPORT_NON_ANNULLABILE')
    copia = db.create_backup()
    if not copia:
        raise NonRiuscito('Non sono riuscito a fare la copia di sicurezza del database: l\'annullamento non è stato '
                          'fatto. Riprova.', codice='COPIA_NON_RIUSCITA')
    try:
        with db.get_db_context() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT annullato FROM napoli_import WHERE id = ?', (import_id,)).fetchone()[0]:
                raise Conflitto('Questo import è già stato annullato.', codice='IMPORT_GIA_ANNULLATO')
            create = set(registro.get('create', {}).get('coppie') or [])
            if create and conn.execute(f'SELECT 1 FROM napoli_orari WHERE coppia_id IN '
                                       f'({", ".join("?" * len(create))}) LIMIT 1', tuple(create)).fetchone():
                raise Conflitto('Dopo l\'import sono stati aggiunti gli orari di coppie create dall\'import: '
                                'l\'import non si può più annullare.', codice='IMPORT_CAMBIATO_DOPO')
            _annulla_registro(conn, registro, import_id)
            conn.execute('UPDATE napoli_import SET annullato = 1 WHERE id = ?', (import_id,))
            for r in _righe(conn, "SELECT id, dati FROM napoli_annullamenti WHERE tipo = 'import'"):
                try:
                    if json.loads(r['dati']).get('import_id') == import_id:
                        conn.execute('DELETE FROM napoli_annullamenti WHERE id = ?', (r['id'],))
                except (ValueError, AttributeError):
                    continue
    except sqlite3.IntegrityError:
        raise Conflitto('Non si può annullare: dopo l\'import sono stati aggiunti dati collegati (per esempio '
                        'nelle anagrafiche).', codice='IMPORT_CAMBIATO_DOPO') from None
    db.log_audit('annullamento', 'napoli_import', import_id,
                 dettagli=f'Napoli, {lotto["nome"]}: annullato l\'import del foglio presenze di {testo_mese}; '
                          f'copia di sicurezza {copia}')
    return {'messaggio': f'Annullato l\'import di {testo_mese}: i dati sono tornati com\'erano prima', 'copia': copia}

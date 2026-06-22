"""
Import dell'anagrafica dipendenti (operatori OEPAC) da Excel.

Mappa le colonne principali ai campi della scheda dipendente; tutte le
altre colonne vengono conservate nei "dati extra" (JSON) con l'etichetta
originale, cosi' nessun dato dell'Excel va perso.

L'abbinamento con i dipendenti gia' presenti avviene per Codice Fiscale
(se presente) o, in mancanza, per nome+cognome: l'import e' idempotente.
"""

import io
import re
import unicodedata
from datetime import datetime, date

import openpyxl


def _norm(s):
    if s is None:
        return ''
    s = str(s).strip().lower()
    s = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', s)


# Intestazione normalizzata -> campo "core" della tabella dipendenti
CORE_MAP = {
    'cognome': 'cognome',
    'nome': 'nome',
    'codice fiscale': 'codice_fiscale',
    'qualifica': 'qualifica',
    'sede': 'sede',
    'monte ore contrattuale': 'ore_contrattuali_settimanali',
    'monte ore': 'ore_contrattuali_settimanali',
    'data assunzione': 'data_assunzione',
    'cellulare personale': 'telefono',
    'cellulare': 'telefono',
    'email personale': 'email',
}


def _fmt(v):
    """Normalizza un valore di cella in stringa/numero serializzabile."""
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.strftime('%Y-%m-%d')
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def parse_workbook(stream_or_bytes):
    """Legge il workbook e ritorna la lista di record.

    Ogni record: dict con i campi core (nome, cognome, codice_fiscale, email,
    telefono, qualifica, sede, ore_contrattuali_settimanali, data_assunzione)
    + 'extra' (dict) con le altre colonne (etichetta originale -> valore).
    Accetta sia uno stream/bytes (evita il controllo sull'estensione .xls).
    """
    if isinstance(stream_or_bytes, (bytes, bytearray)):
        stream_or_bytes = io.BytesIO(stream_or_bytes)
    wb = openpyxl.load_workbook(stream_or_bytes, data_only=True, read_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)

    try:
        header = next(rows)
    except StopIteration:
        return []

    # Mappa indice colonna -> ('core', campo) oppure ('extra', etichetta)
    colmap = []
    for h in header:
        etichetta = (str(h).strip() if h is not None else '')
        campo = CORE_MAP.get(_norm(etichetta))
        colmap.append(('core', campo) if campo else ('extra', etichetta))

    records = []
    for r in rows:
        if r is None:
            continue
        rec = {'extra': {}}
        for idx, cell in enumerate(r):
            if idx >= len(colmap):
                break
            kind, key = colmap[idx]
            val = _fmt(cell)
            if kind == 'core' and key:
                # se piu' colonne mappano lo stesso campo, tieni il primo non vuoto
                if not rec.get(key):
                    rec[key] = val
            elif kind == 'extra' and key:
                if val not in (None, ''):
                    rec['extra'][key] = val

        # Salta righe senza nome/cognome
        if not (rec.get('nome') and rec.get('cognome')):
            continue
        # Fallback email: usa Email Lavoro se manca quella personale
        if not rec.get('email'):
            for k, v in rec['extra'].items():
                if 'email' in _norm(k) and v:
                    rec['email'] = v
                    break
        records.append(rec)

    wb.close()
    return records


def chiave_cf(cf):
    return re.sub(r'\s+', '', (cf or '')).upper()


def chiave_nome(nome, cognome):
    return _norm(f"{cognome} {nome}")

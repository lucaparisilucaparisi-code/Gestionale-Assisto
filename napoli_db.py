"""Accesso ai dati della sezione Napoli: solo tabelle napoli_* (PROGETTO §4, §6).

Del programma di Roma si usano soltanto, di database.py, get_db_context (la
connessione) e log_audit (il registro attivita' condiviso: voci 'napoli_*', senza
codici fiscali, IBAN o altri valori). I controlli dei formati sono in
napoli_calcoli (funzioni pure); qui quelli che guardano il database (nomi e numeri
doppi, date sovrapposte, dati collegati) e la memoria di Ctrl+Z delle pagine di
Napoli (napoli_annullamenti), separata da quella di Roma.

Passo 1.3 (Impostazioni): dati della cooperativa e destinatario delle fatture
(napoli_impostazioni), lotti con la procedura "Crea il primo lotto", contratti
applicativi, tariffe e regole con data, grafie delle qualifiche; controlli del lotto
per la scheda Mese.

Errori: DatiNonValidi (400) con un messaggio semplice e il campo sbagliato,
Conflitto (409: dato gia' presente, date sovrapposte, dati collegati), NonTrovato
(404). routes_napoli li trasforma in risposte JSON {error, code, campo, ...}.
"""
import datetime
import json
import re
import sqlite3
from decimal import Decimal

import config_napoli
import database as db
import napoli_calcoli as calc

GRADI = calc.GRADI
NOMI_GRADO = {'inferiore': 'grado inferiore', 'superiore': 'grado superiore', None: 'tutti e due i gradi'}
# Memoria di Ctrl+Z: le azioni piu' recenti di ANNULLA_VALIDITA_ORE, al massimo MAX_ANNULLAMENTI.
ANNULLA_VALIDITA_ORE = 24
MAX_ANNULLAMENTI = 50
# Tabelle che Ctrl+Z sa rimettere com'erano (senza il prefisso napoli_) e la loro chiave.
TABELLE_ANNULLABILI = {'lotti': 'id', 'contratti': 'id', 'tariffe': 'id', 'regole': 'id',
                       'alias_qualifiche': 'testo', 'impostazioni': 'chiave'}
# Tabelle con dati di un lotto che impediscono di eliminarlo (oltre a contratti, tariffe e regole).
TABELLE_DATI_LOTTO = ('scuole', 'alunni', 'coppie', 'presenze', 'import', 'coordinamento', 'mesi_chiusi',
                      'fatture', 'calendario')


# ==================== errori ====================

class ErroreNapoli(Exception):
    stato = 400
    codice = 'DATI_NON_VALIDI'

    def __init__(self, messaggio, campo=None, codice=None, **altro):
        super().__init__(messaggio)
        self.messaggio = messaggio
        self.campo = campo
        self.altro = altro
        if codice:
            self.codice = codice

    def risposta(self):
        out = {'error': self.messaggio, 'code': self.codice}
        if self.campo:
            out['campo'] = self.campo
        out.update(self.altro)
        return out


class DatiNonValidi(ErroreNapoli):
    pass


class Conflitto(ErroreNapoli):
    stato = 409
    codice = 'CONFLITTO'


class NonTrovato(ErroreNapoli):
    stato = 404
    codice = 'NON_TROVATO'


# ==================== utilita' ====================

def _ora():
    return datetime.datetime.now().isoformat(timespec='seconds')


def _oggi():
    return datetime.date.today()


def _righe(conn, sql, parametri=()):
    return [dict(r) for r in conn.execute(sql, parametri)]


def _riga(conn, sql, parametri=()):
    r = conn.execute(sql, parametri).fetchone()
    return dict(r) if r else None


def _valida(funzione, campo, *argomenti, **opzioni):
    """Un controllo di napoli_calcoli: il ValueError diventa DatiNonValidi sul campo."""
    try:
        return funzione(*argomenti, **opzioni)
    except ValueError as e:
        raise DatiNonValidi(str(e), campo) from None


def _testo(dati, campo, etichetta, obbligatorio=False, massimo=200, maiuscolo=False, spazi=True, manca=None):
    """Testo di un campo: senza spazi in piu' (spazi=False li lascia, per i modelli dei
    testi), None se vuoto. Errore se manca ed e' obbligatorio, o se e' troppo lungo."""
    valore = dati.get(campo)
    if valore is None:
        valore = ''
    if isinstance(valore, bool) or not isinstance(valore, (str, int, float)):
        raise DatiNonValidi(f'{etichetta}: il valore non è valido.', campo)
    valore = ' '.join(str(valore).split()) if spazi else str(valore).strip()
    if maiuscolo:
        valore = valore.upper()
    if not valore:
        if obbligatorio:
            raise DatiNonValidi(manca or f'Manca: {etichetta.lower()}.', campo)
        return None
    if len(valore) > massimo:
        raise DatiNonValidi(f'{etichetta}: al massimo {massimo} caratteri (ne hai scritti {len(valore)}).', campo)
    return valore


def _codice(dati, campo, etichetta, lunghezza, esempio):
    """Codice di lettere e numeri di lunghezza fissa (CIG, CUP, codice univoco), in maiuscolo."""
    valore = re.sub(r'\s', '', str(dati.get(campo) or '')).upper()
    if not valore:
        return None
    if not re.fullmatch(r'[A-Z0-9]+', valore) or len(valore) != lunghezza:
        raise DatiNonValidi(f'{etichetta} ha {lunghezza} caratteri, solo lettere e numeri (per esempio {esempio}): '
                            f'"{valore}" ne ha {len(valore)}.', campo)
    return valore


def _data_facoltativa(dati, campo, nome):
    if dati.get(campo) in (None, ''):
        return None
    return _valida(calc.valida_data, campo, dati.get(campo), nome)


def _periodo(dati, nomi, fine_obbligatoria=False):
    try:
        return calc.valida_periodo(dati.get('valido_da'), dati.get('valido_a'), fine_obbligatoria, nomi)
    except ValueError as e:
        testo = str(e)
        campo = 'valido_a' if testo.startswith(nomi[1]) else 'valido_da'
        raise DatiNonValidi(testo, campo) from None


def _intero(dati, campo, etichetta, minimo, massimo):
    valore = dati.get(campo)
    if isinstance(valore, str) and re.fullmatch(r'\s*\d{1,9}\s*', valore):
        valore = int(valore)
    if isinstance(valore, bool) or not isinstance(valore, int) or not minimo <= valore <= massimo:
        raise DatiNonValidi(f'{etichetta}: scegli un numero da {minimo} a {massimo}.', campo)
    return valore


def _booleano(valore, predefinito=True):
    if valore in (None, ''):
        return predefinito
    if isinstance(valore, str):
        return valore.strip().lower() in ('1', 'true', 'si', 'sì', 'on')
    return bool(valore)


def _euro_it(cent):
    return calc.numero_it(calc.da_centesimi(cent))


def _periodo_it(dal, al):
    if not al:
        return f'dal {calc.data_it(dal)} (senza data di fine)'
    return f'dal {calc.data_it(dal)} al {calc.data_it(al)}'


def _giorno(valore):
    """Il giorno di una richiesta (oggi se manca), controllato."""
    if valore in (None, ''):
        return _oggi()
    return calc.data(_valida(calc.valida_data, 'giorno', valore, 'Il giorno'))


def _giorno_prima(giorno):
    return (calc.data(giorno) - datetime.timedelta(days=1)).isoformat()


# ==================== memoria di Ctrl+Z (napoli_annullamenti) ====================

class _Modifiche:
    """Le righe toccate da un'azione, com'erano prima, per Ctrl+Z: prima di cambiare o
    cancellare una riga si chiama prima(); dopo averne inserita una, nuova()."""

    def __init__(self, conn):
        self.conn = conn
        self.righe = []

    def prima(self, tabella, chiave):
        colonna = TABELLE_ANNULLABILI[tabella]
        riga = _riga(self.conn, f'SELECT * FROM napoli_{tabella} WHERE {colonna} = ?', (chiave,))
        self.righe.append({'tabella': tabella, 'chiave': chiave, 'prima': riga})

    def nuova(self, tabella, chiave):
        self.righe.append({'tabella': tabella, 'chiave': chiave, 'prima': None})

    def salva(self, tipo, descrizione):
        """Registra l'azione (senza nominativi nella descrizione) e tiene le ultime."""
        if not self.righe:
            return None
        cur = self.conn.execute(
            'INSERT INTO napoli_annullamenti (timestamp, tipo, descrizione, dati) VALUES (?, ?, ?, ?)',
            (_ora(), tipo, descrizione, json.dumps({'versione': 1, 'righe': self.righe}, ensure_ascii=False,
                                                   default=str)))
        self.conn.execute('DELETE FROM napoli_annullamenti WHERE id NOT IN '
                          '(SELECT id FROM napoli_annullamenti ORDER BY id DESC LIMIT ?)', (MAX_ANNULLAMENTI,))
        return cur.lastrowid


def _ripristina(conn, voce):
    tabella, chiave, prima = voce.get('tabella'), voce.get('chiave'), voce.get('prima')
    if tabella not in TABELLE_ANNULLABILI:
        raise DatiNonValidi('Questa modifica non si può annullare da qui.', codice='NON_ANNULLABILE')
    colonna = TABELLE_ANNULLABILI[tabella]
    if prima is None:
        conn.execute(f'DELETE FROM napoli_{tabella} WHERE {colonna} = ?', (chiave,))
        return
    esistenti = {r[1] for r in conn.execute(f'PRAGMA table_info(napoli_{tabella})')}
    valori = {k: v for k, v in prima.items() if k in esistenti}
    if conn.execute(f'SELECT 1 FROM napoli_{tabella} WHERE {colonna} = ?', (chiave,)).fetchone():
        assegna = ', '.join(f'{k} = ?' for k in valori if k != colonna)
        conn.execute(f'UPDATE napoli_{tabella} SET {assegna} WHERE {colonna} = ?',
                     tuple(v for k, v in valori.items() if k != colonna) + (chiave,))
    else:
        nomi = ', '.join(valori)
        segnaposto = ', '.join('?' * len(valori))
        conn.execute(f'INSERT INTO napoli_{tabella} ({nomi}) VALUES ({segnaposto})', tuple(valori.values()))


def _annullabile(timestamp, adesso=None):
    try:
        quando = datetime.datetime.fromisoformat(timestamp)
    except (TypeError, ValueError):
        return False
    return quando >= (adesso or datetime.datetime.now()) - datetime.timedelta(hours=ANNULLA_VALIDITA_ORE)


def _quando_it(timestamp):
    try:
        return datetime.datetime.fromisoformat(timestamp).strftime('%d/%m/%Y alle %H:%M')
    except (TypeError, ValueError):
        return ''


def ultima_annullabile():
    """Cosa annullerebbe Ctrl+Z su una pagina di Napoli: {'azione': {id, descrizione,
    quando} o None, 'scadute': azioni troppo vecchie ancora in memoria, 'ore_validita'}."""
    with db.get_db_context() as conn:
        ultima = _riga(conn, 'SELECT id, timestamp, tipo, descrizione FROM napoli_annullamenti '
                             'ORDER BY id DESC LIMIT 1')
        totale = conn.execute('SELECT COUNT(*) FROM napoli_annullamenti').fetchone()[0]
    if ultima and _annullabile(ultima['timestamp']):
        return {'azione': {'id': ultima['id'], 'descrizione': ultima['descrizione'],
                           'quando': _quando_it(ultima['timestamp'])},
                'scadute': 0, 'ore_validita': ANNULLA_VALIDITA_ORE}
    return {'azione': None, 'scadute': totale, 'ore_validita': ANNULLA_VALIDITA_ORE}


def annulla(atteso=None):
    """Annulla l'ultima azione di Napoli (solo se e' ancora annullabile). atteso: l'id
    mostrato nella conferma; se nel frattempo l'ultima e' un'altra, Conflitto."""
    try:
        with db.get_db_context() as conn:
            ultima = _riga(conn, 'SELECT * FROM napoli_annullamenti ORDER BY id DESC LIMIT 1')
            if not ultima or not _annullabile(ultima['timestamp']):
                testo = ('Nessuna modifica recente da annullare: quelle di più di '
                         f'{ANNULLA_VALIDITA_ORE} ore fa non si possono più annullare.' if ultima
                         else 'Nessuna modifica di Napoli da annullare.')
                raise DatiNonValidi(testo, codice='NIENTE_DA_ANNULLARE')
            if atteso is not None and str(atteso) != str(ultima['id']):
                raise Conflitto("L'ultima modifica è cambiata nel frattempo: premi di nuovo Ctrl+Z.",
                                codice='ANNULLA_CAMBIATO')
            try:
                dati = json.loads(ultima['dati'])
                voci = dati['righe'] if dati.get('versione') == 1 else None
            except (TypeError, ValueError, KeyError, AttributeError):
                voci = None
            if not isinstance(voci, list):
                raise DatiNonValidi('Questa modifica non si può annullare da qui.', codice='NON_ANNULLABILE')
            for voce in reversed(voci):
                _ripristina(conn, voce)
            conn.execute('DELETE FROM napoli_annullamenti WHERE id = ?', (ultima['id'],))
    except sqlite3.IntegrityError:
        raise Conflitto('Non si può annullare: nel frattempo sono stati aggiunti dati collegati a questa '
                        'modifica.', codice='ANNULLA_IMPOSSIBILE') from None
    db.log_audit('annullamento', 'napoli_annullamento', ultima['id'],
                 dettagli=f'Napoli: annullata la modifica "{ultima["descrizione"]}"')
    return {'descrizione': ultima['descrizione']}


# ==================== impostazioni: cooperativa e destinatario ====================

# (chiave, etichetta, tipo, lunghezza massima): chiavi di napoli_impostazioni.
CAMPI_COOPERATIVA = (
    ('cooperativa_denominazione', 'Ragione sociale', 'testo', 150),
    ('cooperativa_partita_iva', 'Partita IVA', 'partita_iva', None),
    ('cooperativa_codice_fiscale', 'Codice fiscale', 'codice_fiscale', None),
    ('cooperativa_indirizzo', 'Indirizzo della sede', 'testo', 150),
    ('cooperativa_cap', 'CAP', 'cap', None),
    ('cooperativa_comune', 'Comune', 'testo', 80),
    ('cooperativa_provincia', 'Provincia', 'provincia', None),
    ('cooperativa_banca', 'Banca', 'testo', 120),
    ('cooperativa_iban', 'IBAN', 'iban', None),
)
CAMPI_DESTINATARIO = (
    ('destinatario_denominazione', 'Ente destinatario', 'testo', 150),
    ('destinatario_indirizzo', 'Indirizzo', 'testo', 150),
    ('destinatario_cap', 'CAP', 'cap', None),
    ('destinatario_comune', 'Comune', 'testo', 80),
    ('destinatario_provincia', 'Provincia', 'provincia', None),
    ('destinatario_codice_fiscale', 'Codice fiscale dell\'ente', 'codice_fiscale', None),
)
GRUPPI_IMPOSTAZIONI = {'cooperativa': CAMPI_COOPERATIVA, 'destinatario': CAMPI_DESTINATARIO}
assert tuple(c for c, *_ in CAMPI_DESTINATARIO) == calc.CAMPI_DESTINATARIO


def _valore_impostazione(chiave, etichetta, tipo, massimo, valore):
    if tipo == 'testo':
        return _testo({chiave: valore}, chiave, etichetta, massimo=massimo)
    scritto = '' if valore is None else str(valore).strip()
    if not scritto:
        return None
    if tipo == 'iban':
        return _valida(calc.valida_iban, chiave, scritto)
    if tipo == 'partita_iva':
        return _valida(calc.valida_partita_iva, chiave, scritto, 'La partita IVA')
    if tipo == 'codice_fiscale':
        return _valida(calc.valida_codice_fiscale, chiave, scritto, 'Il codice fiscale')
    if tipo == 'cap':
        if not re.fullmatch(r'\d{5}', scritto):
            raise DatiNonValidi('Il CAP ha 5 cifre (per esempio 80133).', chiave)
        return scritto
    if tipo == 'provincia':
        if not re.fullmatch(r'[A-Za-z]{2}', scritto):
            raise DatiNonValidi('La provincia si scrive con la sigla di due lettere (per esempio NA).', chiave)
        return scritto.upper()
    raise ValueError(tipo)


def leggi_impostazioni(conn=None):
    """Tutte le impostazioni {chiave: valore} (uso interno: l'IBAN e' intero)."""
    if conn is None:
        with db.get_db_context() as c:
            return leggi_impostazioni(c)
    return {r['chiave']: r['valore'] for r in conn.execute('SELECT chiave, valore FROM napoli_impostazioni')}


def impostazioni_per_la_pagina():
    """Impostazioni da mostrare: l'IBAN solo mascherato; il destinatario salvato e quello
    proposto (dati pubblici dell'ente, da confermare)."""
    tutte = leggi_impostazioni()
    cooperativa = {c: tutte.get(c) or '' for c, *_ in CAMPI_COOPERATIVA if c != 'cooperativa_iban'}
    iban = tutte.get('cooperativa_iban') or ''
    cooperativa.update(iban_salvato=bool(iban), iban_mascherato=calc.maschera_iban(iban))
    destinatario = {c: tutte.get(c) or '' for c, *_ in CAMPI_DESTINATARIO}
    return {'cooperativa': cooperativa, 'destinatario': destinatario,
            'destinatario_salvato': bool(tutte.get('destinatario_denominazione')),
            'destinatario_testo': calc.testo_destinatario(tutte),
            'destinatario_proposto': dict(config_napoli.DESTINATARIO_PROPOSTO),
            'campi': {g: [{'chiave': c, 'etichetta': e} for c, e, *_ in campi]
                      for g, campi in GRUPPI_IMPOSTAZIONI.items()}}


def salva_impostazioni(gruppo, dati):
    """Salva i campi del gruppo ('cooperativa' o 'destinatario') presenti in dati: un campo
    assente resta com'e' (l'IBAN non torna mai alla pagina), uno vuoto si toglie.
    Ritorna le etichette dei campi cambiati."""
    campi = GRUPPI_IMPOSTAZIONI.get(gruppo)
    if campi is None:
        raise NonTrovato('Sezione delle impostazioni sconosciuta.')
    nuovi = {chiave: _valore_impostazione(chiave, etichetta, tipo, massimo, dati[chiave])
             for chiave, etichetta, tipo, massimo in campi if chiave in dati}
    etichette = {c: e for c, e, *_ in campi}
    with db.get_db_context() as conn:
        attuali = leggi_impostazioni(conn)
        cambiati = [c for c, v in nuovi.items() if (attuali.get(c) or None) != v]
        modifiche = _Modifiche(conn)
        for chiave in cambiati:
            modifiche.prima('impostazioni', chiave)
            if nuovi[chiave] is None:
                conn.execute('DELETE FROM napoli_impostazioni WHERE chiave = ?', (chiave,))
            else:
                conn.execute('INSERT INTO napoli_impostazioni (chiave, valore) VALUES (?, ?) '
                             'ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore', (chiave, nuovi[chiave]))
        titolo = 'Dati della cooperativa' if gruppo == 'cooperativa' else 'Destinatario delle fatture'
        modifiche.salva('impostazioni', f'{titolo}: {", ".join(etichette[c] for c in cambiati)}')
    if cambiati:
        db.log_audit('modifica', 'napoli_impostazioni',
                     dettagli=f'Napoli, {titolo.lower()}: cambiati {", ".join(etichette[c] for c in cambiati)}')
    return [etichette[c] for c in cambiati]


# ==================== figure ====================

def nome_figura(codice):
    """Nome breve della figura, come nelle righe della fattura (Asacom, Educatore...)."""
    return config_napoli.DESCRIZIONI_FATTURA.get(codice, str(codice).capitalize())


def elenco_figure(conn=None):
    if conn is None:
        with db.get_db_context() as c:
            return elenco_figure(c)
    figure = _righe(conn, 'SELECT codice, descrizione, ordine, ore_di_lotto FROM napoli_figure ORDER BY ordine')
    for f in figure:
        f['nome'] = nome_figura(f['codice'])
    return figure


def _figura(conn, dati, campo='figura'):
    codice = str(dati.get(campo) or '').strip().upper()
    if not codice:
        raise DatiNonValidi('Scegli la figura professionale.', campo)
    riga = _riga(conn, 'SELECT codice, descrizione FROM napoli_figure WHERE codice = ?', (codice,))
    if not riga:
        raise DatiNonValidi(f'La figura "{codice}" non esiste: scegline una dall\'elenco.', campo)
    return riga


# ==================== lotti ====================

COLONNE_LOTTO = ('nome', 'numero_lotto', 'municipalita', 'colore', 'attivo', 'cig', 'cup', 'oggetto_fattura',
                 'nota_fattura', 'destinatario', 'codice_univoco_ufficio', 'riferimento_amministrativo',
                 'intestazione_foglio')


def elenco_lotti(conn=None):
    if conn is None:
        with db.get_db_context() as c:
            return elenco_lotti(c)
    return _righe(conn, 'SELECT * FROM napoli_lotti ORDER BY numero_lotto, id')


def lotto(lotto_id, conn=None):
    if conn is None:
        with db.get_db_context() as c:
            return lotto(lotto_id, c)
    riga = _riga(conn, 'SELECT * FROM napoli_lotti WHERE id = ?', (lotto_id,))
    if not riga:
        raise NonTrovato('Il lotto non esiste (forse è stato eliminato): ricarica la pagina.')
    return riga


def _valida_modello(dati, campo, etichetta, ammessi):
    testo = _testo(dati, campo, etichetta, massimo=500, spazi=False)
    sconosciuti = calc.segnaposto_sconosciuti(testo, ammessi)
    if sconosciuti:
        raise DatiNonValidi(f'{etichetta}: {{{sconosciuti[0]}}} non si può usare. Si possono usare '
                            + ' '.join('{' + a + '}' for a in ammessi) + '.', campo)
    return testo


def _valida_lotto(conn, dati, lotto_id=None):
    """Campi del lotto controllati e nella forma del database. Errore (con il campo) se
    manca un dato obbligatorio, se un codice non ha la forma giusta, se nome o numero
    sono gia' di un altro lotto."""
    out = {
        'nome': _testo(dati, 'nome', 'Il nome del lotto', True, 60, manca='Scrivi il nome del lotto.'),
        'numero_lotto': _intero(dati, 'numero_lotto', 'Il numero del lotto', min(config_napoli.NUMERI_LOTTO),
                                max(config_napoli.NUMERI_LOTTO)),
        'municipalita': _testo(dati, 'municipalita', 'Le municipalità', True, 40,
                               manca='Scrivi le municipalità del lotto (per esempio 1 e 2).'),
        'cig': _codice(dati, 'cig', 'Il CIG', 10, '9A1B2C3D4E'),
        'cup': _codice(dati, 'cup', 'Il CUP', 15, 'B61H22000000001'),
        'codice_univoco_ufficio': _codice(dati, 'codice_univoco_ufficio', 'Il codice univoco ufficio', 6, 'UF1234'),
        'riferimento_amministrativo': _testo(dati, 'riferimento_amministrativo', 'Il riferimento amministrativo',
                                             massimo=30),
        'oggetto_fattura': _valida_modello(dati, 'oggetto_fattura', 'L\'oggetto della fattura',
                                           config_napoli.SEGNAPOSTO_OGGETTO),
        'nota_fattura': _valida_modello(dati, 'nota_fattura', 'La nota della fattura', config_napoli.SEGNAPOSTO_NOTA),
        'destinatario': _testo(dati, 'destinatario', 'Il destinatario del lotto', massimo=300),
        'intestazione_foglio': _testo(dati, 'intestazione_foglio', 'L\'intestazione del foglio firma', massimo=200),
        'colore': None,
        'attivo': 1 if _booleano(dati.get('attivo')) else 0,
    }
    colore = str(dati.get('colore') or '').strip()
    if colore:
        if not re.fullmatch(r'#[0-9A-Fa-f]{6}', colore):
            raise DatiNonValidi('Il colore non è valido: sceglilo dall\'elenco.', 'colore')
        out['colore'] = colore.upper()
    for altro in _righe(conn, 'SELECT id, nome, numero_lotto FROM napoli_lotti WHERE id IS NOT ?', (lotto_id,)):
        if altro['nome'].casefold() == out['nome'].casefold():
            raise Conflitto(f'C\'è già un lotto che si chiama "{altro["nome"]}": scegli un altro nome.', 'nome',
                            codice='LOTTO_GIA_PRESENTE')
        if altro['numero_lotto'] == out['numero_lotto']:
            raise Conflitto(f'Il lotto numero {out["numero_lotto"]} c\'è già: è "{altro["nome"]}".',
                            'numero_lotto', codice='LOTTO_GIA_PRESENTE')
    return out


def _inserisci_lotto(conn, valori, modifiche):
    nomi = ', '.join(valori) + ', data_creazione'
    segnaposto = ', '.join('?' * (len(valori) + 1))
    cur = conn.execute(f'INSERT INTO napoli_lotti ({nomi}) VALUES ({segnaposto})', tuple(valori.values()) + (_ora(),))
    modifiche.nuova('lotti', cur.lastrowid)
    return cur.lastrowid


def crea_lotto(dati):
    with db.get_db_context() as conn:
        valori = _valida_lotto(conn, dati)
        modifiche = _Modifiche(conn)
        lotto_id = _inserisci_lotto(conn, valori, modifiche)
        modifiche.salva('lotto', f'Nuovo lotto {valori["nome"]}')
    db.log_audit('creazione', 'napoli_lotto', lotto_id, dettagli=f'Napoli: nuovo lotto {valori["nome"]}')
    return lotto(lotto_id)


def aggiorna_lotto(lotto_id, dati):
    """Cambia i campi del lotto presenti in dati (gli altri restano come sono)."""
    with db.get_db_context() as conn:
        attuale = lotto(lotto_id, conn)
        unito = {k: attuale.get(k) for k in COLONNE_LOTTO}
        unito.update({k: v for k, v in dati.items() if k in COLONNE_LOTTO})
        valori = _valida_lotto(conn, unito, lotto_id)
        modifiche = _Modifiche(conn)
        modifiche.prima('lotti', lotto_id)
        assegna = ', '.join(f'{k} = ?' for k in valori)
        conn.execute(f'UPDATE napoli_lotti SET {assegna} WHERE id = ?', tuple(valori.values()) + (lotto_id,))
        modifiche.salva('lotto', f'Modifica del lotto {valori["nome"]}')
    db.log_audit('modifica', 'napoli_lotto', lotto_id, dettagli=f'Napoli: modificato il lotto {valori["nome"]}')
    return lotto(lotto_id)


def elimina_lotto(lotto_id):
    """Elimina un lotto senza dati (solo contratti, tariffe e regole, che si eliminano con
    lui): con scuole, alunni, presenze o fatture non si puo' (Svuota lotto, piu' avanti)."""
    with db.get_db_context() as conn:
        attuale = lotto(lotto_id, conn)
        for tabella in TABELLE_DATI_LOTTO:
            if conn.execute(f'SELECT 1 FROM napoli_{tabella} WHERE lotto_id = ? LIMIT 1', (lotto_id,)).fetchone():
                raise Conflitto(f'Il lotto "{attuale["nome"]}" ha già dati (scuole, alunni, presenze, fatture o '
                                'calendario): non si può eliminare.', codice='LOTTO_CON_DATI')
        modifiche = _Modifiche(conn)
        for tabella in ('regole', 'tariffe', 'contratti'):
            for r in conn.execute(f'SELECT id FROM napoli_{tabella} WHERE lotto_id = ? ORDER BY id',
                                  (lotto_id,)).fetchall():
                modifiche.prima(tabella, r['id'])
                conn.execute(f'DELETE FROM napoli_{tabella} WHERE id = ?', (r['id'],))
        modifiche.prima('lotti', lotto_id)
        conn.execute('DELETE FROM napoli_lotti WHERE id = ?', (lotto_id,))
        modifiche.salva('lotto', f'Eliminazione del lotto {attuale["nome"]}')
    db.log_audit('eliminazione', 'napoli_lotto', lotto_id, dettagli=f'Napoli: eliminato il lotto {attuale["nome"]}')


def proposta_lotto(conn=None):
    """Valori proposti dalla procedura "Crea il primo lotto": il primo numero libero, i
    modelli dei testi, le tariffe del contratto attuale (IVA esclusa, da confermare;
    l'interprete LIS senza tariffa) con le loro date."""
    if conn is None:
        with db.get_db_context() as c:
            return proposta_lotto(c)
    usati = {r['numero_lotto'] for r in elenco_lotti(conn)}
    liberi = [n for n in config_napoli.NUMERI_LOTTO if n not in usati]
    numero = liberi[0] if liberi else None
    proposto = {k: (v.format(numero=numero) if k == 'nome' and numero else v)
                for k, v in config_napoli.LOTTO_PROPOSTO.items()}
    proposto.update(numero_lotto=numero, municipalita='', cig='', attivo=1)
    if numero is None:
        proposto['nome'] = ''
    tariffe = {t['figura']: t for t in config_napoli.tariffe_proposte()}
    return {
        'lotto': proposto, 'numeri_liberi': liberi,
        'valido_da': config_napoli.INIZIO_CONTRATTO_ATTUALE, 'valido_a': config_napoli.FINE_TARIFFE_ATTUALI,
        'tariffe': [{'figura': f['codice'], 'descrizione': f['descrizione'],
                     'tariffa': _euro_it(tariffe[f['codice']]['tariffa_cent']) if f['codice'] in tariffe else ''}
                    for f in elenco_figure(conn)],
        'fonte': config_napoli.TARIFFE_PROPOSTE_FONTE,
        'segnaposto_oggetto': list(config_napoli.SEGNAPOSTO_OGGETTO),
        'segnaposto_nota': list(config_napoli.SEGNAPOSTO_NOTA),
    }


def crea_lotto_con_tariffe(dati):
    """Procedura "Crea il primo lotto": il lotto e le sue tariffe (quelle lasciate vuote non
    si creano) con le stesse date, in un'unica azione (un solo Ctrl+Z)."""
    voci = dati.get('tariffe') or []
    if not isinstance(voci, list):
        raise DatiNonValidi('Le tariffe non sono valide.', 'tariffe')
    with db.get_db_context() as conn:
        valori = _valida_lotto(conn, dati.get('lotto') if isinstance(dati.get('lotto'), dict) else {})
        dal, al = _periodo(dati, ('La data di inizio delle tariffe', 'La data di fine delle tariffe'))
        tariffe, viste = [], set()
        for i, voce in enumerate(voci):
            if not isinstance(voce, dict) or str(voce.get('tariffa') or '').strip() == '':
                continue
            figura = _figura(conn, voce)
            if figura['codice'] in viste:
                raise DatiNonValidi(f'La tariffa {nome_figura(figura["codice"])} c\'è due volte.', f'tariffe.{i}')
            viste.add(figura['codice'])
            cent = _valida(calc.valida_euro, f'tariffe.{i}', voce.get('tariffa'),
                           f'La tariffa {nome_figura(figura["codice"])}')
            tariffe.append((figura['codice'], cent))
        modifiche = _Modifiche(conn)
        lotto_id = _inserisci_lotto(conn, valori, modifiche)
        fonte = _testo(dati, 'fonte', 'La fonte', massimo=200) or config_napoli.TARIFFE_PROPOSTE_NOTA
        for figura, cent in tariffe:
            cur = conn.execute('INSERT INTO napoli_tariffe (lotto_id, figura, livello_ccnl, tariffa_cent, valido_da, '
                               'valido_a, fonte, data_inserimento) VALUES (?, ?, NULL, ?, ?, ?, ?, ?)',
                               (lotto_id, figura, cent, dal, al, fonte, _ora()))
            modifiche.nuova('tariffe', cur.lastrowid)
        modifiche.salva('lotto', f'Nuovo lotto {valori["nome"]} con {len(tariffe)} tariffe')
    db.log_audit('creazione', 'napoli_lotto', lotto_id,
                 dettagli=f'Napoli: nuovo lotto {valori["nome"]} con {len(tariffe)} tariffe {_periodo_it(dal, al)}')
    return lotto(lotto_id)


# ==================== contratti applicativi ====================

def _grado(dati, campo='grado'):
    valore = str(dati.get(campo) or '').strip().lower()
    if valore in ('', 'entrambi', 'tutti'):
        return None
    if valore not in GRADI:
        raise DatiNonValidi('Il grado è "inferiore", "superiore" oppure tutti e due.', campo)
    return valore


def _descrivi_contratto(c):
    return f'{c["numero"]} ({NOMI_GRADO[c.get("grado") or None]}, {_periodo_it(c["valido_da"], c["valido_a"])})'


def elenco_contratti(lotto_id, conn=None):
    if conn is None:
        with db.get_db_context() as c:
            return elenco_contratti(lotto_id, c)
    lotto(lotto_id, conn)
    righe = _righe(conn, 'SELECT * FROM napoli_contratti WHERE lotto_id = ? ORDER BY valido_da, grado, id',
                   (lotto_id,))
    for r in righe:
        r['importo'] = _euro_it(r['importo_cent']) if r.get('importo_cent') is not None else ''
        r['usato'] = bool(conn.execute(
            'SELECT 1 FROM napoli_coordinamento WHERE contratto_id = ? UNION ALL '
            'SELECT 1 FROM napoli_fatture WHERE contratto_id = ? LIMIT 1', (r['id'], r['id'])).fetchone())
    return righe


def _valida_contratto(conn, lotto_id, dati, contratto_id=None):
    dal, al = _periodo(dati, ('La data di inizio del contratto', 'La data di fine del contratto'),
                       fine_obbligatoria=True)
    out = {
        'grado': _grado(dati),
        'numero': _testo(dati, 'numero', 'Il numero del contratto', True, 20, maiuscolo=True,
                         manca='Scrivi il numero del contratto applicativo (per esempio XI).'),
        'accordo_quadro': _testo(dati, 'accordo_quadro', 'L\'accordo quadro', massimo=100),
        'repertorio': _testo(dati, 'repertorio', 'Il repertorio', massimo=50),
        'data_contratto': _data_facoltativa(dati, 'data_contratto', 'La data del contratto'),
        'dd_servizio': _testo(dati, 'dd_servizio', 'Il servizio della determina', massimo=30),
        'dd_numero': _testo(dati, 'dd_numero', 'Il numero della determina', massimo=30),
        'dd_data': _data_facoltativa(dati, 'dd_data', 'La data della determina'),
        'valido_da': dal, 'valido_a': al,
        'importo_cent': None,
        'note': _testo(dati, 'note', 'Le note', massimo=500),
    }
    if str(dati.get('importo') or '').strip():
        out['importo_cent'] = _valida(calc.valida_euro, 'importo', dati.get('importo'), 'L\'importo del contratto',
                                      minimo=Decimal('0'), massimo=Decimal('99999999.99'))
    altri = _righe(conn, 'SELECT * FROM napoli_contratti WHERE lotto_id = ? AND id IS NOT ? ORDER BY valido_da',
                   (lotto_id, contratto_id))
    for a in altri:
        if a['numero'] == out['numero'] and (a.get('grado') or None) == out['grado']:
            raise Conflitto(f'Il contratto {out["numero"]} per {NOMI_GRADO[out["grado"]]} c\'è già.', 'numero',
                            codice='CONTRATTO_GIA_PRESENTE')
    nuovo = dict(out, lotto_id=lotto_id, id=contratto_id or 'nuovo')
    sovrapposti = [b if a is nuovo else a for a, b in calc.contratti_sovrapposti(altri + [nuovo])
                   if a is nuovo or b is nuovo]
    if sovrapposti:
        raise Conflitto('Le date si sovrappongono a quelle del contratto ' + _descrivi_contratto(sovrapposti[0])
                        + ': le stesse ore finirebbero in due fatture. Cambia le date o il grado.', 'valido_da',
                        codice='CONTRATTI_SOVRAPPOSTI',
                        sovrapposti=[_descrivi_contratto(c) for c in sovrapposti])
    return out


def crea_contratto(lotto_id, dati):
    with db.get_db_context() as conn:
        lotto(lotto_id, conn)
        valori = _valida_contratto(conn, lotto_id, dati)
        nomi = ', '.join(valori) + ', lotto_id, data_inserimento'
        segnaposto = ', '.join('?' * (len(valori) + 2))
        cur = conn.execute(f'INSERT INTO napoli_contratti ({nomi}) VALUES ({segnaposto})',
                           tuple(valori.values()) + (lotto_id, _ora()))
        modifiche = _Modifiche(conn)
        modifiche.nuova('contratti', cur.lastrowid)
        modifiche.salva('contratto', f'Nuovo contratto applicativo {_descrivi_contratto(valori)}')
    db.log_audit('creazione', 'napoli_contratto', cur.lastrowid,
                 dettagli=f'Napoli: nuovo contratto applicativo {_descrivi_contratto(valori)}')
    return contratto(cur.lastrowid)


def contratto(contratto_id, conn=None):
    if conn is None:
        with db.get_db_context() as c:
            return contratto(contratto_id, c)
    riga = _riga(conn, 'SELECT * FROM napoli_contratti WHERE id = ?', (contratto_id,))
    if not riga:
        raise NonTrovato('Il contratto non esiste (forse è stato eliminato): ricarica la pagina.')
    return riga


def aggiorna_contratto(contratto_id, dati):
    with db.get_db_context() as conn:
        attuale = contratto(contratto_id, conn)
        valori = _valida_contratto(conn, attuale['lotto_id'], dati, contratto_id)
        modifiche = _Modifiche(conn)
        modifiche.prima('contratti', contratto_id)
        assegna = ', '.join(f'{k} = ?' for k in valori)
        conn.execute(f'UPDATE napoli_contratti SET {assegna} WHERE id = ?', tuple(valori.values()) + (contratto_id,))
        modifiche.salva('contratto', f'Modifica del contratto applicativo {_descrivi_contratto(valori)}')
    db.log_audit('modifica', 'napoli_contratto', contratto_id,
                 dettagli=f'Napoli: modificato il contratto applicativo {_descrivi_contratto(valori)}')
    return contratto(contratto_id)


def elimina_contratto(contratto_id):
    with db.get_db_context() as conn:
        attuale = contratto(contratto_id, conn)
        if conn.execute('SELECT 1 FROM napoli_coordinamento WHERE contratto_id = ? UNION ALL '
                        'SELECT 1 FROM napoli_fatture WHERE contratto_id = ? LIMIT 1',
                        (contratto_id, contratto_id)).fetchone():
            raise Conflitto(f'Il contratto {attuale["numero"]} ha già ore del coordinatore o fatture: non si può '
                            'eliminare (si possono cambiare le date).', codice='CONTRATTO_USATO')
        modifiche = _Modifiche(conn)
        modifiche.prima('contratti', contratto_id)
        conn.execute('DELETE FROM napoli_contratti WHERE id = ?', (contratto_id,))
        modifiche.salva('contratto', f'Eliminazione del contratto applicativo {_descrivi_contratto(attuale)}')
    db.log_audit('eliminazione', 'napoli_contratto', contratto_id,
                 dettagli=f'Napoli: eliminato il contratto applicativo {_descrivi_contratto(attuale)}')


# ==================== tariffe ====================

def _descrivi_tariffa(t):
    livello = f' livello {t["livello_ccnl"]}' if t.get('livello_ccnl') else ''
    return (f'{nome_figura(t["figura"])}{livello} {_euro_it(t["tariffa_cent"])} euro '
            f'{_periodo_it(t["valido_da"], t.get("valido_a"))}')


def elenco_tariffe(lotto_id, conn=None):
    if conn is None:
        with db.get_db_context() as c:
            return elenco_tariffe(lotto_id, c)
    lotto(lotto_id, conn)
    righe = _righe(conn, 'SELECT t.* FROM napoli_tariffe t JOIN napoli_figure f ON f.codice = t.figura '
                         'WHERE t.lotto_id = ? ORDER BY f.ordine, COALESCE(t.livello_ccnl, \'\'), t.valido_da',
                   (lotto_id,))
    for r in righe:
        r['tariffa'] = _euro_it(r['tariffa_cent'])
    return righe


def _chiudibili(nuovo, sovrapposti):
    """Righe sovrapposte che si possono chiudere il giorno prima dell'inizio della nuova
    (cominciano prima): la proposta "chiudi la precedente"."""
    if not sovrapposti or any(calc.data(s['valido_da']) >= calc.data(nuovo['valido_da']) for s in sovrapposti):
        return []
    return [{'id': s['id'], 'nuova_fine': _giorno_prima(nuovo['valido_da'])} for s in sovrapposti]


def _chiudi(conn, tabella, chiudibili, modifiche):
    for c in chiudibili:
        modifiche.prima(tabella, c['id'])
        conn.execute(f'UPDATE napoli_{tabella} SET valido_a = ? WHERE id = ?', (c['nuova_fine'], c['id']))


def _valida_tariffa(conn, lotto_id, dati, tariffa_id=None, chiudi_precedenti=False):
    figura = _figura(conn, dati)
    dal, al = _periodo(dati, ('La data di inizio della tariffa', 'La data di fine della tariffa'))
    out = {
        'figura': figura['codice'],
        'livello_ccnl': _testo(dati, 'livello_ccnl', 'Il livello', massimo=10, maiuscolo=True),
        'tariffa_cent': _valida(calc.valida_euro, 'tariffa', dati.get('tariffa'),
                                f'La tariffa {nome_figura(figura["codice"])}'),
        'valido_da': dal, 'valido_a': al,
        'fonte': _testo(dati, 'fonte', 'La fonte', massimo=200),
    }
    altre = _righe(conn, 'SELECT * FROM napoli_tariffe WHERE lotto_id = ? AND id IS NOT ? ORDER BY valido_da',
                   (lotto_id, tariffa_id))
    nuova = dict(out, lotto_id=lotto_id, id=tariffa_id or 'nuova')
    sovrapposte = [b if a is nuova else a for a, b in calc.tariffe_sovrapposte(altre + [nuova])
                   if a is nuova or b is nuova]
    chiudibili = _chiudibili(nuova, sovrapposte)
    if sovrapposte and not (chiudi_precedenti and chiudibili):
        testo = ('In questi giorni vale già la tariffa ' + _descrivi_tariffa(sovrapposte[0])
                 + ': due tariffe della stessa figura negli stessi giorni non si possono avere (la fattura non '
                 'saprebbe quale usare). Cambia le date')
        testo += (f', oppure chiudi la tariffa precedente al {calc.data_it(chiudibili[0]["nuova_fine"])}.'
                  if chiudibili else '.')
        raise Conflitto(testo, 'valido_da', codice='TARIFFE_SOVRAPPOSTE', chiudibili=chiudibili,
                        sovrapposte=[_descrivi_tariffa(t) for t in sovrapposte])
    return out, (chiudibili if sovrapposte else [])


def tariffa(tariffa_id, conn=None):
    if conn is None:
        with db.get_db_context() as c:
            return tariffa(tariffa_id, c)
    riga = _riga(conn, 'SELECT * FROM napoli_tariffe WHERE id = ?', (tariffa_id,))
    if not riga:
        raise NonTrovato('La tariffa non esiste (forse è stata eliminata): ricarica la pagina.')
    return riga


def crea_tariffa(lotto_id, dati):
    """Nuova tariffa del lotto. Con dati['chiudi_precedenti'] le tariffe della stessa figura
    che cominciano prima e valgono ancora si chiudono il giorno prima (stessa azione)."""
    with db.get_db_context() as conn:
        lotto(lotto_id, conn)
        valori, chiudere = _valida_tariffa(conn, lotto_id, dati, None, _booleano(dati.get('chiudi_precedenti'), False))
        modifiche = _Modifiche(conn)
        _chiudi(conn, 'tariffe', chiudere, modifiche)
        nomi = ', '.join(valori) + ', lotto_id, data_inserimento'
        segnaposto = ', '.join('?' * (len(valori) + 2))
        cur = conn.execute(f'INSERT INTO napoli_tariffe ({nomi}) VALUES ({segnaposto})',
                           tuple(valori.values()) + (lotto_id, _ora()))
        modifiche.nuova('tariffe', cur.lastrowid)
        descrizione = _descrivi_tariffa(valori)
        modifiche.salva('tariffa', f'Nuova tariffa {descrizione}')
    db.log_audit('creazione', 'napoli_tariffa', cur.lastrowid, dettagli=f'Napoli: nuova tariffa {descrizione}'
                 + (f' (chiuse {len(chiudere)} tariffe precedenti)' if chiudere else ''))
    return tariffa(cur.lastrowid)


def aggiorna_tariffa(tariffa_id, dati):
    with db.get_db_context() as conn:
        attuale = tariffa(tariffa_id, conn)
        valori, chiudere = _valida_tariffa(conn, attuale['lotto_id'], dati, tariffa_id,
                                           _booleano(dati.get('chiudi_precedenti'), False))
        modifiche = _Modifiche(conn)
        _chiudi(conn, 'tariffe', chiudere, modifiche)
        modifiche.prima('tariffe', tariffa_id)
        assegna = ', '.join(f'{k} = ?' for k in valori)
        conn.execute(f'UPDATE napoli_tariffe SET {assegna} WHERE id = ?', tuple(valori.values()) + (tariffa_id,))
        descrizione = _descrivi_tariffa(valori)
        modifiche.salva('tariffa', f'Modifica della tariffa {descrizione}')
    db.log_audit('modifica', 'napoli_tariffa', tariffa_id, dettagli=f'Napoli: modificata la tariffa {descrizione}')
    return tariffa(tariffa_id)


def elimina_tariffa(tariffa_id):
    """Le fatture gia' fatte non cambiano: hanno le loro tariffe congelate."""
    with db.get_db_context() as conn:
        attuale = tariffa(tariffa_id, conn)
        modifiche = _Modifiche(conn)
        modifiche.prima('tariffe', tariffa_id)
        conn.execute('DELETE FROM napoli_tariffe WHERE id = ?', (tariffa_id,))
        descrizione = _descrivi_tariffa(attuale)
        modifiche.salva('tariffa', f'Eliminazione della tariffa {descrizione}')
    db.log_audit('eliminazione', 'napoli_tariffa', tariffa_id, dettagli=f'Napoli: eliminata la tariffa {descrizione}')


# ==================== regole con data ====================

GIORNI_BREVI = ('lun', 'mar', 'mer', 'gio', 'ven', 'sab', 'dom')


def _numero_scritto(v):
    return f'{v:f}'.replace('.', ',')


def testo_valore_regola(chiave, valore):
    """Valore di una regola come si legge a schermo: '0,5', '5 ore', 'Si'', 'lun, mar...'."""
    definizione = config_napoli.REGOLE_PREDEFINITE[chiave]
    etichetta = config_napoli.ETICHETTE_REGOLE[chiave]
    tipo = definizione['tipo']
    if 'scelte' in etichetta:
        return etichetta['scelte'].get(valore, str(valore))
    if tipo == 'booleano':
        return 'Sì' if valore else 'No'
    if etichetta.get('unita') == 'minuti':
        ore, minuti = divmod(int(valore), 60)
        return f'{ore} ore' + (f' e {minuti} minuti' if minuti else '')
    if tipo in ('decimale', 'intero'):
        testo = _numero_scritto(Decimal(valore))
        return testo + ('%' if etichetta.get('unita') == 'percento' else '') + (
            ' giorni' if etichetta.get('unita') == 'giorni' else '')
    if tipo == 'giorni':
        return ', '.join(GIORNI_BREVI[g] for g in valore)
    if tipo == 'mesi':
        return ', '.join(calc.MESI[m - 1].lower() for m in valore)
    if tipo == 'elenco':
        return ', '.join(valore)
    return str(valore)


def _valore_json(valore):
    """Valore di una regola per napoli_regole.valore (JSON): i decimali come numero esatto."""
    if isinstance(valore, Decimal):
        return format(valore, 'f')
    if isinstance(valore, tuple):
        valore = list(valore)
    return json.dumps(valore, ensure_ascii=False)


def _valore_regola(chiave, valore):
    """Valore scritto nella pagina -> valore della regola nel suo tipo, con i limiti di
    ETICHETTE_REGOLE. Errore con un messaggio semplice."""
    definizione = config_napoli.REGOLE_PREDEFINITE[chiave]
    etichetta = config_napoli.ETICHETTE_REGOLE[chiave]
    tipo = definizione['tipo']
    nome = etichetta['etichetta']
    if tipo in ('decimale', 'intero'):
        try:
            letto = calc.decimale(valore)
        except ValueError:
            letto = None
        if letto is None or not letto.is_finite() or (tipo == 'intero' and letto != letto.to_integral_value()):
            raise DatiNonValidi(f'"{nome}": scrivi un numero{" intero" if tipo == "intero" else ""}.', 'valore')
        valore = int(letto) if tipo == 'intero' else letto
        minimo, massimo = etichetta.get('min'), etichetta.get('max')
        if minimo is not None and not minimo <= valore <= massimo:
            if etichetta.get('unita') == 'minuti':
                limiti = f'fra {_numero_scritto(Decimal(minimo) / 60)} e {_numero_scritto(Decimal(massimo) / 60)} ore'
            else:
                limiti = f'fra {_numero_scritto(Decimal(minimo))} e {_numero_scritto(Decimal(massimo))}'
            raise DatiNonValidi(f'"{nome}" deve essere {limiti}.', 'valore')
    elif tipo == 'testo':
        valore = _testo({'valore': valore}, 'valore', nome, True, 500, spazi=False,
                        manca=f'"{nome}": scrivi il testo.')
        sconosciuti = calc.segnaposto_sconosciuti(valore, etichetta.get('segnaposto', ()))
        if sconosciuti:
            ammessi = ' '.join('{' + s + '}' for s in etichetta.get('segnaposto', ())) or 'nessuno'
            raise DatiNonValidi(f'"{nome}": {{{sconosciuti[0]}}} non si può usare (si possono usare: {ammessi}).',
                                'valore')
    elif tipo == 'booleano':
        valore = _booleano(valore, None)
        if valore is None:
            raise DatiNonValidi(f'"{nome}": scegli sì o no.', 'valore')
    elif tipo in ('giorni', 'mesi'):
        if not isinstance(valore, list) or not valore:
            raise DatiNonValidi(f'"{nome}": scegli almeno un {"giorno" if tipo == "giorni" else "mese"}.', 'valore')
    try:
        return calc.valore_regola(chiave, valore)
    except ValueError:
        raise DatiNonValidi(f'"{nome}": il valore non è tra quelli ammessi.', 'valore') from None


def _descrivi_regola(r):
    dove = 'per tutti i lotti' if r.get('lotto_id') is None else 'per il lotto'
    valore = testo_valore_regola(r['chiave'], calc.valore_regola(r['chiave'], r['valore']))
    return (f'{config_napoli.ETICHETTE_REGOLE[r["chiave"]]["etichetta"]}: {valore} {dove} '
            f'{_periodo_it(r["valido_da"], r.get("valido_a"))}')


def _righe_regole(conn, lotto_id):
    return _righe(conn, 'SELECT * FROM napoli_regole WHERE lotto_id IS NULL OR lotto_id = ? ORDER BY valido_da, id',
                  (lotto_id,))


def elenco_regole(lotto_id=None, giorno=None):
    """Le regole con data come si mostrano: per ogni chiave la spiegazione, il valore che
    vale nel giorno (oggi) con la sua origine ('predefinita', 'tutti' i lotti o il 'lotto')
    e le righe salvate per tutti i lotti e per il lotto."""
    giorno = _giorno(giorno)
    with db.get_db_context() as conn:
        if lotto_id is not None:
            lotto(lotto_id, conn)
        righe = _righe_regole(conn, lotto_id)
    out = []
    for chiave, definizione in config_napoli.REGOLE_PREDEFINITE.items():
        etichetta = config_napoli.ETICHETTE_REGOLE[chiave]
        dettaglio = calc.regola_dettaglio(chiave, giorno, righe, lotto_id)
        salvate = []
        for r in righe:
            if r['chiave'] == chiave:
                v = calc.valore_regola(chiave, r['valore'])
                salvate.append(dict(r, valore_testo=testo_valore_regola(chiave, v), valore=_valore_pagina(v)))
        out.append({
            'chiave': chiave, 'etichetta': etichetta['etichetta'], 'spiegazione': etichetta.get('spiegazione', ''),
            'gruppo': etichetta['gruppo'], 'tipo': definizione['tipo'], 'unita': etichetta.get('unita'),
            'scelte': [{'valore': k, 'testo': t} for k, t in etichetta.get('scelte', {}).items()],
            'min': etichetta.get('min'), 'max': etichetta.get('max'),
            'predefinito': _valore_pagina(definizione['valore']),
            'predefinito_testo': testo_valore_regola(chiave, definizione['valore']),
            'fonte_predefinito': definizione.get('fonte', ''),
            'valore': _valore_pagina(dettaglio['valore']),
            'valore_testo': testo_valore_regola(chiave, dettaglio['valore']),
            'origine': dettaglio['origine'], 'valido_da': dettaglio['valido_da'], 'valido_a': dettaglio['valido_a'],
            'fuori_validita': dettaglio['fuori_validita'],
            'salvate': salvate,
        })
    return {'giorno': giorno.isoformat(), 'gruppi': [{'codice': c, 'nome': n} for c, n in config_napoli.GRUPPI_REGOLE],
            'regole': out}


def _valore_pagina(valore):
    """Valore di una regola per la pagina (JSON): i decimali come testo con la virgola."""
    if isinstance(valore, Decimal):
        return _numero_scritto(valore)
    if isinstance(valore, tuple):
        return list(valore)
    return valore


def regola_salvata(regola_id, conn=None):
    if conn is None:
        with db.get_db_context() as c:
            return regola_salvata(regola_id, c)
    riga = _riga(conn, 'SELECT * FROM napoli_regole WHERE id = ?', (regola_id,))
    if not riga:
        raise NonTrovato('La regola non esiste (forse è stata eliminata): ricarica la pagina.')
    return riga


def _valida_regola(conn, dati, regola_id=None, chiudi_precedenti=False):
    chiave = str(dati.get('chiave') or '').strip()
    if chiave not in config_napoli.REGOLE_PREDEFINITE:
        raise DatiNonValidi('Questa regola non esiste.', 'chiave')
    lotto_id = dati.get('lotto_id')
    lotto_id = None if lotto_id in (None, '') else _intero(dati, 'lotto_id', 'Il lotto', 1, 10 ** 9)
    if lotto_id is not None:
        lotto(lotto_id, conn)
    dal, al = _periodo(dati, ('La data da cui vale', 'La data di fine'))
    valore = _valore_regola(chiave, dati.get('valore'))
    out = {'lotto_id': lotto_id, 'chiave': chiave, 'valore': _valore_json(valore), 'valido_da': dal, 'valido_a': al,
           'fonte': _testo(dati, 'fonte', 'La nota', massimo=200)}
    altre = _righe(conn, 'SELECT * FROM napoli_regole WHERE chiave = ? AND lotto_id IS ? AND id IS NOT ? '
                         'ORDER BY valido_da', (chiave, lotto_id, regola_id))
    nuova = dict(out, id=regola_id or 'nuova')
    sovrapposte = [b if a is nuova else a for a, b in calc.periodi_sovrapposti(altre + [nuova])
                   if a is nuova or b is nuova]
    chiudibili = _chiudibili(nuova, sovrapposte)
    if sovrapposte and not (chiudi_precedenti and chiudibili):
        testo = ('In questi giorni vale già ' + _descrivi_regola(sovrapposte[0])
                 + '. Due valori della stessa regola negli stessi giorni non si possono avere: cambia le date')
        testo += (f', oppure chiudi il valore precedente al {calc.data_it(chiudibili[0]["nuova_fine"])}.'
                  if chiudibili else '.')
        raise Conflitto(testo, 'valido_da', codice='REGOLE_SOVRAPPOSTE', chiudibili=chiudibili,
                        sovrapposte=[_descrivi_regola(r) for r in sovrapposte])
    return out, (chiudibili if sovrapposte else [])


def crea_regola(dati):
    with db.get_db_context() as conn:
        valori, chiudere = _valida_regola(conn, dati, None, _booleano(dati.get('chiudi_precedenti'), False))
        modifiche = _Modifiche(conn)
        _chiudi(conn, 'regole', chiudere, modifiche)
        nomi = ', '.join(valori) + ', data_inserimento'
        segnaposto = ', '.join('?' * (len(valori) + 1))
        cur = conn.execute(f'INSERT INTO napoli_regole ({nomi}) VALUES ({segnaposto})',
                           tuple(valori.values()) + (_ora(),))
        modifiche.nuova('regole', cur.lastrowid)
        descrizione = _descrivi_regola(valori)
        modifiche.salva('regola', f'Regola {descrizione}')
    db.log_audit('creazione', 'napoli_regola', cur.lastrowid, dettagli=f'Napoli: regola {descrizione}')
    return regola_salvata(cur.lastrowid)


def aggiorna_regola(regola_id, dati):
    with db.get_db_context() as conn:
        attuale = regola_salvata(regola_id, conn)
        unito = dict(dati, chiave=attuale['chiave'], lotto_id=attuale['lotto_id'])
        valori, chiudere = _valida_regola(conn, unito, regola_id, _booleano(dati.get('chiudi_precedenti'), False))
        modifiche = _Modifiche(conn)
        _chiudi(conn, 'regole', chiudere, modifiche)
        modifiche.prima('regole', regola_id)
        assegna = ', '.join(f'{k} = ?' for k in valori)
        conn.execute(f'UPDATE napoli_regole SET {assegna} WHERE id = ?', tuple(valori.values()) + (regola_id,))
        descrizione = _descrivi_regola(valori)
        modifiche.salva('regola', f'Modifica della regola {descrizione}')
    db.log_audit('modifica', 'napoli_regola', regola_id, dettagli=f'Napoli: modificata la regola {descrizione}')
    return regola_salvata(regola_id)


def elimina_regola(regola_id):
    with db.get_db_context() as conn:
        attuale = regola_salvata(regola_id, conn)
        modifiche = _Modifiche(conn)
        modifiche.prima('regole', regola_id)
        conn.execute('DELETE FROM napoli_regole WHERE id = ?', (regola_id,))
        descrizione = _descrivi_regola(attuale)
        modifiche.salva('regola', f'Eliminazione della regola {descrizione}')
    db.log_audit('eliminazione', 'napoli_regola', regola_id, dettagli=f'Napoli: eliminata la regola {descrizione}')


# ==================== grafie delle qualifiche ====================

def _testo_qualifica(dati):
    testo = _testo(dati, 'testo', 'La qualifica', True, 80, maiuscolo=True,
                   manca='Scrivi la qualifica come compare nel file (per esempio EDUCATRICE PROF.LE).')
    return testo


def elenco_qualifiche():
    with db.get_db_context() as conn:
        return _righe(conn, 'SELECT a.testo, a.figura, a.origine, f.descrizione AS figura_descrizione '
                            'FROM napoli_alias_qualifiche a JOIN napoli_figure f ON f.codice = a.figura '
                            'ORDER BY f.ordine, a.testo')


def salva_qualifica(dati, nuova):
    """Nuova grafia (nuova=True) o cambio della figura di una grafia che c'e' gia' (diventa
    'utente')."""
    with db.get_db_context() as conn:
        testo = _testo_qualifica(dati)
        figura = _figura(conn, dati)
        attuale = _riga(conn, 'SELECT * FROM napoli_alias_qualifiche WHERE testo = ?', (testo,))
        if nuova and attuale:
            raise Conflitto(f'La qualifica "{testo}" c\'è già: vale {nome_figura(attuale["figura"])}.', 'testo',
                            codice='QUALIFICA_GIA_PRESENTE')
        if not nuova and not attuale:
            raise NonTrovato('La qualifica non esiste (forse è stata eliminata): ricarica la pagina.')
        modifiche = _Modifiche(conn)
        if attuale:
            modifiche.prima('alias_qualifiche', testo)
            conn.execute("UPDATE napoli_alias_qualifiche SET figura = ?, origine = 'utente' WHERE testo = ?",
                         (figura['codice'], testo))
        else:
            conn.execute("INSERT INTO napoli_alias_qualifiche (testo, figura, origine) VALUES (?, ?, 'utente')",
                         (testo, figura['codice']))
            modifiche.nuova('alias_qualifiche', testo)
        modifiche.salva('qualifica', f'Qualifica "{testo}" = {nome_figura(figura["codice"])}')
    db.log_audit('creazione' if nuova else 'modifica', 'napoli_qualifica',
                 dettagli=f'Napoli: qualifica "{testo}" = {nome_figura(figura["codice"])}')
    return {'testo': testo, 'figura': figura['codice']}


def elimina_qualifica(dati):
    """Solo le grafie aggiunte dall'utente: quelle predefinite servono all'import."""
    with db.get_db_context() as conn:
        testo = _testo_qualifica(dati)
        attuale = _riga(conn, 'SELECT * FROM napoli_alias_qualifiche WHERE testo = ?', (testo,))
        if not attuale:
            raise NonTrovato('La qualifica non esiste (forse è stata eliminata): ricarica la pagina.')
        if attuale['origine'] != 'utente':
            raise Conflitto('Le qualifiche predefinite non si eliminano (servono a leggere il file master); si può '
                            'cambiare la figura.', codice='QUALIFICA_PREDEFINITA')
        modifiche = _Modifiche(conn)
        modifiche.prima('alias_qualifiche', testo)
        conn.execute('DELETE FROM napoli_alias_qualifiche WHERE testo = ?', (testo,))
        modifiche.salva('qualifica', f'Eliminazione della qualifica "{testo}"')
    db.log_audit('eliminazione', 'napoli_qualifica', dettagli=f'Napoli: eliminata la qualifica "{testo}"')


# ==================== controlli del lotto (scheda Mese) ====================

def controlli_lotto(lotto_id, giorno=None):
    """Cosa manca per fare le fatture del lotto, con parole semplici: [{'codice', 'stato'
    ('ok', 'avviso', 'manca'), 'testo', 'sezione'}] (sezione = parte delle Impostazioni)."""
    giorno = _giorno(giorno)
    with db.get_db_context() as conn:
        dati_lotto = lotto(lotto_id, conn)
        impostazioni = leggi_impostazioni(conn)
        contratti = elenco_contratti(lotto_id, conn)
        tariffe = elenco_tariffe(lotto_id, conn)
        figure = elenco_figure(conn)
    out = []

    def voce(codice, stato, testo, sezione):
        out.append({'codice': codice, 'stato': stato, 'testo': testo, 'sezione': sezione})

    necessari = (('cooperativa_denominazione', 'la ragione sociale'), ('cooperativa_partita_iva', 'la partita IVA'),
                 ('cooperativa_iban', "l'IBAN"))
    mancano = [nome for c, nome in necessari if not impostazioni.get(c)]
    elenco = ' e '.join([', '.join(mancano[:-1]), mancano[-1]] if len(mancano) > 1 else mancano)
    voce('cooperativa', 'manca' if mancano else 'ok',
         f'Dati della cooperativa: {"mancano" if len(mancano) > 1 else "manca"} {elenco}' if mancano
         else 'Dati della cooperativa: ragione sociale, partita IVA e IBAN ci sono', 'cooperativa')
    destinatario = calc.destinatario_fattura(dati_lotto, impostazioni)
    voce('destinatario', 'ok' if destinatario else 'manca',
         f'Destinatario delle fatture: {destinatario}' if destinatario
         else 'Destinatario delle fatture: controlla i dati proposti e salvali', 'destinatario')
    voce('cig', 'ok' if dati_lotto.get('cig') else 'manca',
         f'CIG del lotto: {dati_lotto["cig"]}' if dati_lotto.get('cig') else 'Manca il CIG del lotto', 'lotto')
    voce('codice_univoco', 'ok' if dati_lotto.get('codice_univoco_ufficio') else 'avviso',
         f'Codice univoco ufficio: {dati_lotto["codice_univoco_ufficio"]}' if dati_lotto.get('codice_univoco_ufficio')
         else 'Manca il codice univoco ufficio (serve per la fattura elettronica)', 'lotto')
    if not contratti:
        voce('contratti', 'manca', 'Nessun contratto applicativo: aggiungi quello in corso (per esempio XI)',
             'contratti')
    else:
        for grado in GRADI:
            attivi = [c for c in contratti if (c.get('grado') in (None, grado))
                      and calc.data(c['valido_da']) <= giorno <= calc.data(c['valido_a'])]
            voce(f'contratto_{grado}', 'ok' if attivi else 'avviso',
                 (f'Oggi per il {NOMI_GRADO[grado]} vale il contratto {attivi[0]["numero"]} '
                  f'(fino al {calc.data_it(attivi[0]["valido_a"])})') if attivi
                 else f'Oggi nessun contratto applicativo copre il {NOMI_GRADO[grado]}', 'contratti')
        senza_dd = [c['numero'] for c in contratti if not (c.get('dd_numero') and c.get('dd_data'))]
        if senza_dd:
            voce('determine', 'manca', 'Mancano numero o data della determina (D.D.) del contratto '
                 + ', '.join(senza_dd), 'contratti')
    for f in figure:
        valide = [t for t in tariffe if t['figura'] == f['codice'] and not t.get('livello_ccnl')
                  and calc.data(t['valido_da']) <= giorno
                  and (not t.get('valido_a') or giorno <= calc.data(t['valido_a']))]
        if valide:
            t = valide[0]
            fine = t.get('valido_a')
            vicina = fine and (calc.data(fine) - giorno).days <= 60
            voce(f'tariffa_{f["codice"]}', 'avviso' if vicina else 'ok',
                 f'Tariffa {f["nome"]}: {t["tariffa"]} euro all\'ora'
                 + (f', finisce il {calc.data_it(fine)}: inserisci la nuova quando la conosci' if vicina else ''),
                 'tariffe')
        else:
            voce(f'tariffa_{f["codice"]}', 'avviso',
                 f'Oggi non c\'è una tariffa per {f["nome"]}: le sue ore non si possono fatturare',
                 'tariffe')
    return out

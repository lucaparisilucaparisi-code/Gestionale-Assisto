"""Anagrafiche della sezione Napoli (passo 1.6, PROGETTO §6): alunni, operatori, scuole e
plessi, coppie operatore-alunno e PEI per figura. Solo tabelle napoli_*.

I dati arrivano soprattutto dal caricamento dell'anagrafica dal file Excel (import_napoli,
REGOLE 14): qui si cercano, si guardano, si correggono e si aggiungono a mano.

Regole:
- controlli lato server con messaggi semplici e il campo sbagliato (napoli_db.DatiNonValidi,
  Conflitto, NonTrovato: routes_napoli li trasforma in {error, code, campo});
- codici fiscali solo mascherati nelle risposte (calc.maschera_codice_fiscale): si scrivono
  per cambiarli e non tornano mai interi alla pagina; mai nel registro attivita' o nella
  memoria di Ctrl+Z, come i nomi delle persone (napoli_db.COLONNE_PERSONALI): le azioni che
  cambiano nome, cognome, codice fiscale o note, o che eliminano una persona, non si
  annullano con Ctrl+Z (napoli_db.registra_non_annullabile) e lo dicono;
- archiviazione al posto della cancellazione: si elimina solo cio' che non ha dati collegati
  (ore, fogli firma, orari, ore del coordinatore); con i dati si archivia (alunni, operatori,
  scuole) o si chiude (coppie, PEI);
- ogni scrittura aggiorna modificato_il (migrazione 5: annullare un caricamento
  dell'anagrafica non cancella righe cambiate a mano dopo) e passa dalla memoria di Ctrl+Z
  di Napoli (napoli_db._Modifiche), separata da quella di Roma;
- la municipalita' e' quella della scuola (del plesso, REGOLE 12); il grado e' quello
  dell'alunno se c'e', altrimenti quello della scuola (della coppia, per le ore);
- "oggi" decide cosa e' in corso: coppie e PEI valgono dal giorno valido_da al giorno
  valido_a compresi (vuoto = senza fine).
"""
import collections
import datetime
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation

import database as db
import import_napoli
import napoli_calcoli as calc
import napoli_db as ndb
from napoli_db import Conflitto, DatiNonValidi, NonTrovato

MUNICIPALITA = tuple(range(1, 11))               # le dieci municipalita' di Napoli
GRADI_SCUOLA = ('inferiore', 'superiore', 'misto')
STATI_PEI = ('definitivo', 'provvisorio', 'sospeso')
RUOLI = ('titolare', 'sostituto')
TIPI_PARITARIE = ('1A', '1E', '1M')              # codici con la forma delle scuole paritarie (PROGETTO §1.5)
MAX_ORE_SETTIMANA = 40
# Valori dei filtri degli elenchi (il primo e' quello predefinito).
STATI_PERSONE = ('attivi', 'da_sistemare', 'archiviati', 'tutti')
STATI_SCUOLE = ('attive', 'da_sistemare', 'archiviate', 'tutte')
STATI_COPPIE = ('in_corso', 'future', 'finite', 'da_sistemare', 'tutte')
GRADI_FILTRO = ('inferiore', 'superiore', 'misto', 'da_decidere')
# REGOLE 15: lo spazio del credito/debito di Napoli nella scheda dell'alunno. Dal passo 1.7 il
# credito/debito del mese di ogni coppia e' nella griglia delle presenze (napoli_presenze); il
# riepilogo per figura qui, nel mese e dall'inizio dell'anno, arriva con un passo successivo.
CREDITO_DEBITO_TESTO = ('Il credito/debito del mese di ogni coppia si vede nella griglia delle presenze (colonna '
                        '«Cred./deb.») e nel dettaglio della coppia. Il riepilogo per figura arriverà qui.')
CREDITO_DEBITO_SPIEGAZIONE = ('Per ogni figura: ore previste (dalla programmazione settimanale o, se manca, dal PEI) '
                              'meno ore riconosciute, nel mese e dall\'inizio dell\'anno scolastico. Positivo = ore '
                              'ancora dovute all\'alunno, come nella Rendicontazione di Roma.')
MOTIVO_PERSONA_ELIMINATA = ('per la riservatezza i dati di una persona eliminata non restano in memoria. Se serve, '
                            'aggiungila di nuovo')
NOMI_CAMPI = {'cognome': 'cognome', 'nome': 'nome', 'codice_fiscale': 'codice fiscale', 'scuola_id': 'scuola',
              'grado': 'grado', 'esami': 'esami', 'note': 'note', 'figura': 'figura', 'livello_ccnl': 'livello',
              'ore_contratto': 'ore di contratto', 'cf_valido': 'codice fiscale', 'municipalita': 'municipalità',
              'codice_meccanografico': 'codice meccanografico', 'ore_settimanali': 'ore settimanali',
              'valido_da': 'inizio', 'valido_a': 'fine', 'stato': 'stato', 'fonte': 'nota',
              'titolare_coppia_id': 'titolare'}
NOMI_STATO_PEI = {'definitivo': 'definitivo', 'provvisorio': 'provvisorio', 'sospeso': 'sospeso'}


# ==================== utilita' ====================

def _ora():
    return ndb._ora()


def _oggi():
    return ndb._oggi().isoformat()


def _giorno_prima(giorno):
    return (calc.data(giorno) - datetime.timedelta(days=1)).isoformat()


def _giorno_dopo(giorno):
    return (calc.data(giorno) + datetime.timedelta(days=1)).isoformat()


def _normalizza(testo):
    s = unicodedata.normalize('NFKD', str(testo or '')).encode('ascii', 'ignore').decode('ascii')
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', s.lower()).split())


def _contiene(cerca, *campi):
    """Tutte le parole cercate compaiono nei campi (senza accenti, maiuscole e punteggiatura)."""
    parole = _normalizza(cerca).split()
    testo = ' ' + _normalizza(' '.join(str(c or '') for c in campi)) + ' '
    return all(p in testo for p in parole)


def nome_persona(p):
    return f'{p.get("cognome") or ""} {p.get("nome") or ""}'.strip() if p else ''


def _plurale(n, uno, molti):
    return f'{n} {uno if n == 1 else molti}'


def _elenco(voci):
    voci = [v for v in voci if v]
    return voci[0] if len(voci) == 1 else ', '.join(voci[:-1]) + ' e ' + voci[-1] if voci else ''


def _periodo_it(dal, al):
    return f'dal {calc.data_it(dal)}' + (f' al {calc.data_it(al)}' if al else '')


def _stato_periodo(dal, al, oggi):
    if dal > oggi:
        return 'futura'
    if al and al < oggi:
        return 'finita'
    return 'in_corso'


def _vale(riga, giorno):
    return riga['valido_da'] <= giorno and (not riga.get('valido_a') or giorno <= riga['valido_a'])


def _si_sovrappongono(a_dal, a_al, b_dal, b_al):
    return a_dal <= (b_al or '9999-12-31') and b_dal <= (a_al or '9999-12-31')


def _ore_testo(ore):
    if ore is None:
        return ''
    return calc.numero_it(Decimal(str(ore)), 2).rstrip('0').rstrip(',')


def _nota_libera(dati, campo='note', etichetta='Le note'):
    """Testo libero (note): al massimo 500 caratteri; un codice fiscale scritto li' per errore
    si salva mascherato (come le note del file Excel)."""
    testo = ndb._testo(dati, campo, etichetta, massimo=500, spazi=False)
    return import_napoli.nascondi_codici_fiscali(testo) if testo else None


def _codice_fiscale_persona(dati, obbligatorio, chi):
    """Codice fiscale di una persona: 16 lettere e cifre con il carattere di controllo giusto,
    in maiuscolo. Il valore scritto non torna mai nei messaggi."""
    scritto = re.sub(r'\s', '', str(dati.get('codice_fiscale') or '')).upper()
    if not scritto:
        if obbligatorio:
            raise DatiNonValidi(f'Scrivi il codice fiscale {chi}.', 'codice_fiscale')
        return None
    if len(scritto) != 16:
        raise DatiNonValidi(f'Il codice fiscale di una persona ha 16 lettere e cifre (ne hai scritte {len(scritto)}).',
                            'codice_fiscale')
    try:
        return calc.valida_codice_fiscale(scritto, 'Il codice fiscale')
    except ValueError as e:
        raise DatiNonValidi(str(e), 'codice_fiscale') from None


def _ore(dati, campo, etichetta, obbligatorio=False, massimo=MAX_ORE_SETTIMANA):
    """Ore a settimana scritte come le scrive una persona (12, 12,5 o 12.5): piu' di 0 e al
    massimo `massimo`, al piu' due decimali. None se vuoto e non obbligatorio."""
    valore = dati.get(campo)
    testo = '' if valore is None else str(valore).strip()
    if not testo:
        if obbligatorio:
            raise DatiNonValidi(f'Scrivi {etichetta.lower()} (per esempio 12 o 12,5).', campo)
        return None
    if isinstance(valore, bool) or testo.startswith('-') or not ndb.NUMERO_SCRITTO.fullmatch(testo):
        raise DatiNonValidi(f'{etichetta}: scrivi un numero di ore, per esempio 12 o 12,5.', campo)
    try:
        numero = Decimal(testo.replace(',', '.'))
    except InvalidOperation:
        raise DatiNonValidi(f'{etichetta}: scrivi un numero di ore, per esempio 12 o 12,5.', campo) from None
    if not 0 < numero <= massimo:
        raise DatiNonValidi(f'{etichetta}: più di 0 e al massimo {massimo} ore a settimana.', campo)
    if numero != numero.quantize(Decimal('0.01')):
        raise DatiNonValidi(f'{etichetta}: al massimo due cifre dopo la virgola.', campo)
    return float(numero)


def _municipalita(dati, campo='municipalita'):
    valore = dati.get(campo)
    testo = '' if valore is None or isinstance(valore, bool) else str(valore).strip()
    if not testo:
        raise DatiNonValidi('Scegli la municipalità della scuola (da 1 a 10).', campo)
    if not re.fullmatch(r'\d{1,2}', testo) or int(testo) not in MUNICIPALITA:
        raise DatiNonValidi('La municipalità è un numero da 1 a 10.', campo)
    return int(testo)


def _id(dati, campo, messaggio, obbligatorio=True):
    valore = dati.get(campo)
    if valore in (None, ''):
        if obbligatorio:
            raise DatiNonValidi(messaggio, campo)
        return None
    if isinstance(valore, bool) or not re.fullmatch(r'\d{1,9}', str(valore).strip()):
        raise DatiNonValidi(messaggio, campo)
    return int(str(valore).strip())


def _figura_persona(conn, dati, campo='figura', coppia=False):
    """Una figura dell'elenco chiuso (napoli_figure); per coppie e PEI non il coordinatore,
    che ha ore di lotto e non coppie."""
    figura = ndb._figura(conn, dati, campo)
    if coppia and _riga(conn, 'SELECT ore_di_lotto FROM napoli_figure WHERE codice = ?',
                        (figura['codice'],))['ore_di_lotto']:
        raise DatiNonValidi(f'{ndb.nome_figura(figura["codice"])}: le sue ore si scrivono per lotto e mese, non per '
                            'alunno. Scegli un\'altra figura.', campo)
    return figura['codice']


def _righe(conn, sql, parametri=()):
    return ndb._righe(conn, sql, parametri)


def _riga(conn, sql, parametri=()):
    return ndb._riga(conn, sql, parametri)


def _cambiati(attuale, valori):
    return [k for k, v in valori.items() if not _uguale(attuale.get(k), v)]


def _uguale(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return float(a) == float(b)
    return a == b


def _aggiorna_riga(conn, tabella, id_, valori):
    assegna = ', '.join(f'{k} = ?' for k in valori)
    conn.execute(f'UPDATE napoli_{tabella} SET {assegna} WHERE id = ?', tuple(valori.values()) + (id_,))


def _inserisci(conn, tabella, valori):
    nomi = ', '.join(valori)
    cur = conn.execute(f'INSERT INTO napoli_{tabella} ({nomi}) VALUES ({", ".join("?" * len(valori))})',
                       tuple(valori.values()))
    return cur.lastrowid


def _filtro(filtri, nome, ammessi, predefinito=None):
    valore = str((filtri or {}).get(nome) or '').strip()
    if not valore:
        return predefinito
    if valore not in ammessi:
        raise DatiNonValidi('Il filtro non è valido: ricarica la pagina.', nome)
    return valore


def _filtro_numero(filtri, nome):
    valore = str((filtri or {}).get(nome) or '').strip()
    if not valore:
        return None
    if not re.fullmatch(r'\d{1,9}', valore):
        raise DatiNonValidi('Il filtro non è valido: ricarica la pagina.', nome)
    return int(valore)


def _filtri(filtri, stati):
    return {
        'scuola_id': _filtro_numero(filtri, 'scuola_id'),
        'municipalita': _filtro_numero(filtri, 'municipalita'),
        'figura': _filtro(filtri, 'figura', {f['codice'] for f in ndb.elenco_figure()}),
        'grado': _filtro(filtri, 'grado', GRADI_FILTRO),
        'stato': _filtro(filtri, 'stato', stati, stati[0]),
        'ruolo': _filtro(filtri, 'ruolo', RUOLI),
        'cerca': str((filtri or {}).get('cerca') or '').strip()[:100],
    }


# ==================== le anagrafiche di un lotto, lette una volta ====================

class _Anagrafica:
    """Scuole, alunni, operatori (quelli con coppie nel lotto e quelli senza nessuna coppia),
    coppie e PEI di un lotto, con i conteggi dei dati collegati alle coppie (ore, fogli
    firma, orari), letti in una volta sola."""

    def __init__(self, conn, lotto_id, oggi=None):
        self.conn = conn
        self.lotto = ndb.lotto(lotto_id, conn)
        self.oggi = oggi or _oggi()
        self.scuole = _righe(conn, 'SELECT * FROM napoli_scuole WHERE lotto_id = ? ORDER BY nome, municipalita, id',
                             (lotto_id,))
        self.alunni = _righe(conn, 'SELECT * FROM napoli_alunni WHERE lotto_id = ? ORDER BY cognome, nome, id',
                             (lotto_id,))
        self.coppie = _righe(conn, 'SELECT * FROM napoli_coppie WHERE lotto_id = ? ORDER BY valido_da, id',
                             (lotto_id,))
        self.pei = _righe(conn, 'SELECT p.* FROM napoli_pei p JOIN napoli_alunni a ON a.id = p.alunno_id '
                                'WHERE a.lotto_id = ? ORDER BY p.figura, p.valido_da, p.id', (lotto_id,))
        self.operatori = _righe(conn, 'SELECT * FROM napoli_operatori WHERE id IN (SELECT operatore_id FROM '
                                      'napoli_coppie WHERE lotto_id = ?) OR id NOT IN (SELECT operatore_id FROM '
                                      'napoli_coppie) ORDER BY cognome, nome, id', (lotto_id,))
        self.presenze = {r['coppia_id']: r for r in _righe(
            conn, 'SELECT coppia_id, COUNT(*) AS n, MIN(data) AS prima, MAX(data) AS ultima FROM napoli_presenze '
                  'WHERE lotto_id = ? GROUP BY coppia_id', (lotto_id,))}
        self.fogli = {r['coppia_id']: r['n'] for r in _righe(
            conn, 'SELECT f.coppia_id, COUNT(*) AS n FROM napoli_fogli f JOIN napoli_coppie c ON c.id = f.coppia_id '
                  'WHERE c.lotto_id = ? GROUP BY f.coppia_id', (lotto_id,))}
        self.orari = {r['coppia_id']: r['n'] for r in _righe(
            conn, 'SELECT o.coppia_id, COUNT(*) AS n FROM napoli_orari o JOIN napoli_coppie c ON c.id = o.coppia_id '
                  'WHERE c.lotto_id = ? GROUP BY o.coppia_id', (lotto_id,))}
        self.calendario = {r['scuola_id'] for r in _righe(
            conn, 'SELECT DISTINCT scuola_id FROM napoli_calendario WHERE scuola_id IS NOT NULL')}
        self.figure = {f['codice']: f for f in ndb.elenco_figure(conn)}
        self.scuola = {s['id']: s for s in self.scuole}
        self.alunno = {a['id']: a for a in self.alunni}
        self.operatore = {o['id']: o for o in self.operatori}
        self.coppia = {c['id']: c for c in self.coppie}
        self.coppie_alunno = collections.defaultdict(list)
        self.coppie_operatore = collections.defaultdict(list)
        self.sostituti = collections.defaultdict(list)
        for c in self.coppie:
            self.coppie_alunno[c['alunno_id']].append(c)
            self.coppie_operatore[c['operatore_id']].append(c)
            if c.get('titolare_coppia_id'):
                self.sostituti[c['titolare_coppia_id']].append(c)
        self.pei_alunno = collections.defaultdict(list)
        for p in self.pei:
            self.pei_alunno[p['alunno_id']].append(p)
        self.alunni_scuola = collections.defaultdict(list)
        for a in self.alunni:
            self.alunni_scuola[a['scuola_id']].append(a)
        self.coppie_scuola = collections.defaultdict(list)
        for c in self.coppie:
            self.coppie_scuola[c['scuola_id']].append(c)
        self.plessi = collections.Counter(s['codice_meccanografico'] for s in self.scuole
                                          if s['codice_meccanografico'])

    # ---------- calcoli ----------

    def stato_coppia(self, c):
        return _stato_periodo(c['valido_da'], c.get('valido_a'), self.oggi)

    def aperta(self, c):
        """In corso o futura: la coppia ha ancora giorni di servizio da oggi."""
        return self.stato_coppia(c) != 'finita'

    def pei_in_vigore(self, alunno_id, figura, giorno=None):
        giorno = giorno or self.oggi
        valide = [p for p in self.pei_alunno.get(alunno_id, ()) if p['figura'] == figura and _vale(p, giorno)]
        return valide[-1] if valide else None

    def grado_alunno(self, a, scuola=None):
        """Il grado dell'alunno (il suo, altrimenti quello della scuola); None = da decidere
        (scuola senza grado o con alunni di tutti e due i gradi)."""
        if a.get('grado'):
            return a['grado']
        s = scuola if scuola is not None else self.scuola.get(a.get('scuola_id'))
        g = (s or {}).get('grado')
        return g if g in calc.GRADI else None

    def ore_coppia(self, c):
        """Ore a settimana della coppia: la sua quota, altrimenti il PEI della figura in vigore
        (oggi, o all'inizio se la coppia comincia dopo)."""
        if c.get('ore_settimanali') is not None:
            return c['ore_settimanali'], 'quota'
        giorno = max(self.oggi, c['valido_da'])
        if c.get('valido_a') and c['valido_a'] < giorno:
            giorno = c['valido_a']
        p = self.pei_in_vigore(c['alunno_id'], c['figura'], giorno)
        return (p['ore_settimanali'], 'pei') if p else (None, None)

    def dati_coppia(self, c):
        """Ore, fogli firma, orari e sostituti collegati: con questi la coppia non si elimina."""
        p = self.presenze.get(c['id']) or {}
        return {'presenze': p.get('n') or 0, 'prima_presenza': p.get('prima'), 'ultima_presenza': p.get('ultima'),
                'fogli': self.fogli.get(c['id'], 0), 'orari': self.orari.get(c['id'], 0),
                'sostituti': len(self.sostituti.get(c['id'], ()))}

    # ---------- righe per la pagina ----------

    def scuola_breve(self, s):
        if not s:
            return None
        return {'id': s['id'], 'nome': s['nome'], 'codice_meccanografico': s['codice_meccanografico'],
                'municipalita': s['municipalita'], 'grado': s['grado'], 'attiva': bool(s['attiva'])}

    def riga_scuola(self, s):
        codice = s['codice_meccanografico'] or ''
        alunni = [a for a in self.alunni_scuola.get(s['id'], ()) if a['attivo']]
        coppie = self.coppie_scuola.get(s['id'], ())
        in_corso = [c for c in coppie if self.stato_coppia(c) == 'in_corso']
        da_sistemare = []
        if s['attiva']:
            if s['grado'] is None:
                da_sistemare.append('grado_da_decidere')
            if s['municipalita'] is None:
                da_sistemare.append('municipalita_mancante')
            if s['grado'] == 'misto' and any(not a.get('grado') for a in alunni):
                da_sistemare.append('alunni_senza_grado')
        return dict(self.scuola_breve(s), grado_proposto=calc.grado_da_codice_meccanografico(codice),
                    paritaria=codice[2:4] in TIPI_PARITARIE, plessi=self.plessi.get(codice, 1) if codice else 1,
                    alunni=len(alunni), alunni_senza_grado=sum(1 for a in alunni if not a.get('grado')),
                    coppie=len(coppie), coppie_in_corso=len(in_corso),
                    coppie_aperte=sum(1 for c in coppie if self.aperta(c)),
                    eliminabile=not coppie and not self.alunni_scuola.get(s['id']) and s['id'] not in self.calendario,
                    da_sistemare=da_sistemare, modificato_il=s.get('modificato_il'))

    def riga_alunno(self, a):
        scuola = self.scuola.get(a['scuola_id'])
        coppie = self.coppie_alunno.get(a['id'], ())
        aperte = [c for c in coppie if self.aperta(c)]
        figure = sorted({p['figura'] for p in self.pei_alunno.get(a['id'], ())},
                        key=lambda f: self.figure.get(f, {}).get('ordine', 99))
        pei = []
        for f in figure:
            p = self.pei_in_vigore(a['id'], f)
            if p:
                pei.append({'id': p['id'], 'figura': f, 'nome_figura': ndb.nome_figura(f),
                            'ore': p['ore_settimanali'], 'ore_testo': _ore_testo(p['ore_settimanali']),
                            'stato': p['stato'], 'valido_da': p['valido_da'], 'valido_a': p['valido_a']})
        grado = self.grado_alunno(a, scuola)
        da_sistemare = []
        if a['attivo']:
            if scuola is None:
                da_sistemare.append('senza_scuola')
            elif not scuola['attiva']:
                da_sistemare.append('scuola_archiviata')
            if grado is None:
                da_sistemare.append('grado_da_decidere')
            if not pei:
                da_sistemare.append('senza_pei')
            if not [c for c in aperte if self.stato_coppia(c) == 'in_corso']:
                da_sistemare.append('senza_coppie')
        operatori = []
        for c in sorted(aperte, key=lambda c: (c['ruolo'] != 'titolare', c['valido_da'])):
            o = self.operatore.get(c['operatore_id'])
            operatori.append({'id': c['operatore_id'], 'coppia_id': c['id'], 'nome': nome_persona(o),
                              'figura': c['figura'], 'nome_figura': ndb.nome_figura(c['figura']),
                              'ruolo': c['ruolo'], 'stato': self.stato_coppia(c)})
        return {'id': a['id'], 'cognome': a['cognome'], 'nome': a['nome'], 'nome_completo': nome_persona(a),
                'cf': calc.maschera_codice_fiscale(a['codice_fiscale']), 'scuola': self.scuola_breve(scuola),
                'municipalita': (scuola or {}).get('municipalita'), 'grado': grado, 'grado_alunno': a.get('grado'),
                'esami': bool(a['esami']), 'attivo': bool(a['attivo']), 'archiviato_dal': a.get('archiviato_dal'),
                'pei': pei, 'operatori': operatori, 'coppie_in_corso': sum(1 for x in operatori
                                                                          if x['stato'] == 'in_corso'),
                'da_sistemare': da_sistemare, 'modificato_il': a.get('modificato_il')}

    def riga_operatore(self, o):
        coppie = self.coppie_operatore.get(o['id'], ())
        in_corso = [c for c in coppie if self.stato_coppia(c) == 'in_corso']
        ore = [self.ore_coppia(c)[0] for c in in_corso]
        ore_progetto = sum(Decimal(str(x)) for x in ore if x is not None)
        scuole = sorted({self.scuola[c['scuola_id']]['nome'] for c in in_corso if c['scuola_id'] in self.scuola})
        cf_da_controllare = not o.get('codice_fiscale') or not o.get('cf_valido')
        da_sistemare = []
        if o['attivo']:
            if cf_da_controllare:
                da_sistemare.append('codice_fiscale' if o.get('codice_fiscale') else 'codice_fiscale_mancante')
            if not in_corso:
                da_sistemare.append('senza_coppie')
            if o.get('ore_contratto') is None:
                da_sistemare.append('ore_contratto_mancanti')
            elif ore_progetto > Decimal(str(o['ore_contratto'])):
                da_sistemare.append('ore_oltre_contratto')
        return {'id': o['id'], 'cognome': o['cognome'], 'nome': o['nome'], 'nome_completo': nome_persona(o),
                'cf': calc.maschera_codice_fiscale(o.get('codice_fiscale')), 'cf_da_controllare': cf_da_controllare,
                'figura': o['figura'], 'nome_figura': ndb.nome_figura(o['figura']),
                'livello_ccnl': o.get('livello_ccnl'), 'ore_contratto': o.get('ore_contratto'),
                'ore_contratto_testo': _ore_testo(o.get('ore_contratto')),
                'ore_progetto': float(ore_progetto), 'ore_progetto_testo': _ore_testo(ore_progetto) if ore else '',
                'qualifica_originale': o.get('qualifica_originale'), 'attivo': bool(o['attivo']),
                'archiviato_dal': o.get('archiviato_dal'), 'coppie_in_corso': len(in_corso),
                'alunni': [nome_persona(self.alunno.get(c['alunno_id'])) for c in in_corso], 'scuole': scuole,
                'da_sistemare': da_sistemare, 'modificato_il': o.get('modificato_il')}

    def riga_coppia(self, c):
        alunno = self.alunno.get(c['alunno_id']) or {}
        operatore = self.operatore.get(c['operatore_id']) or {}
        scuola = self.scuola.get(c['scuola_id'])
        titolare = self.coppia.get(c.get('titolare_coppia_id'))
        ore, da_dove = self.ore_coppia(c)
        collegati = self.dati_coppia(c)
        grado = alunno.get('grado') or ((scuola or {}).get('grado') if (scuola or {}).get('grado') in calc.GRADI
                                        else None)
        da_sistemare = []
        stato = self.stato_coppia(c)
        if stato != 'finita':
            if operatore and operatore.get('figura') != c['figura']:
                da_sistemare.append('figura_diversa')
            if ore is None:
                da_sistemare.append('senza_pei')
            if grado is None:
                da_sistemare.append('grado_da_decidere')
            if operatore and not operatore.get('attivo'):
                da_sistemare.append('operatore_archiviato')
            if alunno and not alunno.get('attivo'):
                da_sistemare.append('alunno_archiviato')
        return {'id': c['id'], 'alunno': {'id': c['alunno_id'], 'nome': nome_persona(alunno),
                                          'attivo': bool(alunno.get('attivo'))},
                'operatore': {'id': c['operatore_id'], 'nome': nome_persona(operatore),
                              'figura': operatore.get('figura'), 'attivo': bool(operatore.get('attivo'))},
                'figura': c['figura'], 'nome_figura': ndb.nome_figura(c['figura']), 'ruolo': c['ruolo'],
                'titolare': ({'id': titolare['id'], 'operatore': nome_persona(self.operatore.get(
                    titolare['operatore_id']))} if titolare else None),
                'scuola': self.scuola_breve(scuola), 'municipalita': (scuola or {}).get('municipalita'),
                'grado': grado, 'valido_da': c['valido_da'], 'valido_a': c.get('valido_a'), 'stato': stato,
                'ore_settimanali': c.get('ore_settimanali'), 'ore': ore, 'ore_testo': _ore_testo(ore),
                'ore_da': da_dove, 'note': c.get('note'), 'origine': c.get('origine'),
                'eliminabile': not any((collegati['presenze'], collegati['fogli'], collegati['orari'],
                                        collegati['sostituti'])),
                'da_sistemare': da_sistemare, 'lotto': {'id': self.lotto['id'], 'nome': self.lotto['nome']},
                **collegati}


def _anagrafica(conn, lotto_id):
    return _Anagrafica(conn, lotto_id)


# ==================== riepilogo e elenchi ====================

def riepilogo(lotto_id):
    """Conteggi per le schede, cosa c'e' da sistemare, scuole e municipalita' per i filtri e
    se l'anagrafica del lotto e' ancora vuota (la pagina invita a caricarla dal file Excel)."""
    with db.get_db_context() as conn:
        an = _anagrafica(conn, lotto_id)
        ultimo = _riga(conn, 'SELECT id, anno, mese, data, esito_json FROM napoli_import WHERE lotto_id = ? AND '
                             'annullato = 0 ORDER BY id DESC LIMIT 1', (lotto_id,))
        scuole = [an.riga_scuola(s) for s in an.scuole]
        alunni = [an.riga_alunno(a) for a in an.alunni]
        operatori = [an.riga_operatore(o) for o in an.operatori]
        coppie = [an.riga_coppia(c) for c in an.coppie]
    ultimo_caricamento = None
    if ultimo:
        ultimo_caricamento = {'id': ultimo['id'], 'data': ultimo['data'],
                              'mese_testo': import_napoli.mese_testo(ultimo['anno'], ultimo['mese'])
                              if ultimo['anno'] and ultimo['mese'] else '',
                              'modo': import_napoli._modo_salvato(ultimo)}
    return {
        'lotto': {'id': an.lotto['id'], 'nome': an.lotto['nome']},
        'oggi': an.oggi,
        'vuota': not (an.scuole or an.alunni or an.coppie),
        'conteggi': {
            'alunni': sum(1 for a in alunni if a['attivo']), 'alunni_archiviati': sum(1 for a in alunni
                                                                                     if not a['attivo']),
            'operatori': sum(1 for o in operatori if o['attivo']),
            'operatori_archiviati': sum(1 for o in operatori if not o['attivo']),
            'scuole': sum(1 for s in scuole if s['attiva']), 'scuole_archiviate': sum(1 for s in scuole
                                                                                      if not s['attiva']),
            'coppie_in_corso': sum(1 for c in coppie if c['stato'] == 'in_corso'), 'coppie': len(coppie),
        },
        'da_sistemare': {'alunni': sum(1 for a in alunni if a['da_sistemare']),
                         'operatori': sum(1 for o in operatori if o['da_sistemare']),
                         'scuole': sum(1 for s in scuole if s['da_sistemare']),
                         'coppie': sum(1 for c in coppie if c['da_sistemare'])},
        'scuole': [an.scuola_breve(s) for s in an.scuole],
        'municipalita': sorted({s['municipalita'] for s in an.scuole if s['municipalita'] is not None}),
        'municipalita_possibili': list(MUNICIPALITA),
        'ultimo_caricamento': ultimo_caricamento,
    }


def _stato_persona(riga, stato):
    if stato == 'attivi':
        return riga['attivo']
    if stato == 'archiviati':
        return not riga['attivo']
    if stato == 'da_sistemare':
        return riga['attivo'] and bool(riga['da_sistemare'])
    return True


def elenco_alunni(lotto_id, filtri=None):
    f = _filtri(filtri, STATI_PERSONE)
    with db.get_db_context() as conn:
        an = _anagrafica(conn, lotto_id)
        out = []
        for a in an.alunni:
            riga = an.riga_alunno(a)
            coppie = an.coppie_alunno.get(a['id'], ())
            scuole = {a['scuola_id']} | {c['scuola_id'] for c in coppie if an.aperta(c)}
            if not _stato_persona(riga, f['stato']):
                continue
            if f['scuola_id'] and f['scuola_id'] not in scuole:
                continue
            if f['municipalita'] and f['municipalita'] not in {(an.scuola.get(s) or {}).get('municipalita')
                                                               for s in scuole}:
                continue
            if f['figura'] and f['figura'] not in ({p['figura'] for p in riga['pei']}
                                                   | {c['figura'] for c in coppie if an.aperta(c)}):
                continue
            if f['grado'] and (riga['grado'] or 'da_decidere') != f['grado']:
                continue
            if f['cerca'] and not _contiene(f['cerca'], a['cognome'], a['nome'], (riga['scuola'] or {}).get('nome')):
                continue
            out.append(riga)
    return {'righe': out, 'totale': len(out), 'filtri': f}


def elenco_operatori(lotto_id, filtri=None):
    f = _filtri(filtri, STATI_PERSONE)
    with db.get_db_context() as conn:
        an = _anagrafica(conn, lotto_id)
        out = []
        for o in an.operatori:
            riga = an.riga_operatore(o)
            aperte = [c for c in an.coppie_operatore.get(o['id'], ()) if an.aperta(c)]
            scuole = [an.scuola.get(c['scuola_id']) or {} for c in aperte]
            if not _stato_persona(riga, f['stato']):
                continue
            if f['figura'] and o['figura'] != f['figura'] and f['figura'] not in {c['figura'] for c in aperte}:
                continue
            if f['scuola_id'] and f['scuola_id'] not in {c['scuola_id'] for c in aperte}:
                continue
            if f['municipalita'] and f['municipalita'] not in {s.get('municipalita') for s in scuole}:
                continue
            if f['grado'] and f['grado'] not in {(an.grado_alunno(an.alunno.get(c['alunno_id']) or {},
                                                                  an.scuola.get(c['scuola_id'])) or 'da_decidere')
                                                 for c in aperte}:
                continue
            if f['cerca'] and not _contiene(f['cerca'], o['cognome'], o['nome'], o.get('qualifica_originale')):
                continue
            out.append(riga)
    return {'righe': out, 'totale': len(out), 'filtri': f}


def elenco_scuole(lotto_id, filtri=None):
    f = _filtri(filtri, STATI_SCUOLE)
    with db.get_db_context() as conn:
        an = _anagrafica(conn, lotto_id)
        out = []
        for s in an.scuole:
            riga = an.riga_scuola(s)
            stato = f['stato']
            if (stato == 'attive' and not s['attiva']) or (stato == 'archiviate' and s['attiva']) \
                    or (stato == 'da_sistemare' and not riga['da_sistemare']):
                continue
            if f['municipalita'] and s['municipalita'] != f['municipalita']:
                continue
            if f['grado'] and (s['grado'] or 'da_decidere') != f['grado']:
                continue
            if f['figura'] and f['figura'] not in {c['figura'] for c in an.coppie_scuola.get(s['id'], ())
                                                   if an.aperta(c)}:
                continue
            if f['cerca'] and not _contiene(f['cerca'], s['nome'], s['codice_meccanografico']):
                continue
            out.append(riga)
    return {'righe': out, 'totale': len(out), 'filtri': f}


def elenco_coppie(lotto_id, filtri=None):
    f = _filtri(filtri, STATI_COPPIE)
    with db.get_db_context() as conn:
        an = _anagrafica(conn, lotto_id)
        out = []
        for c in an.coppie:
            riga = an.riga_coppia(c)
            stato = f['stato']
            if stato == 'in_corso' and riga['stato'] != 'in_corso':
                continue
            if (stato == 'future' and riga['stato'] != 'futura') or (stato == 'finite' and riga['stato'] != 'finita'):
                continue
            if stato == 'da_sistemare' and not riga['da_sistemare']:
                continue
            if f['scuola_id'] and c['scuola_id'] != f['scuola_id']:
                continue
            if f['municipalita'] and riga['municipalita'] != f['municipalita']:
                continue
            if f['figura'] and c['figura'] != f['figura']:
                continue
            if f['grado'] and (riga['grado'] or 'da_decidere') != f['grado']:
                continue
            if f['ruolo'] and c['ruolo'] != f['ruolo']:
                continue
            if f['cerca'] and not _contiene(f['cerca'], riga['alunno']['nome'], riga['operatore']['nome']):
                continue
            out.append(riga)
    out.sort(key=lambda r: (_normalizza(r['alunno']['nome']), r['figura'], r['ruolo'] != 'titolare', r['valido_da']))
    return {'righe': out, 'totale': len(out), 'filtri': f}


def elenco(lotto_id, parte, filtri=None):
    """L'elenco di una parte delle anagrafiche ('alunni', 'operatori', 'scuole', 'coppie')."""
    funzioni = {'alunni': elenco_alunni, 'operatori': elenco_operatori, 'scuole': elenco_scuole,
                'coppie': elenco_coppie}
    if parte not in funzioni:
        raise DatiNonValidi('Elenco sconosciuto: ricarica la pagina.', 'parte')
    return funzioni[parte](lotto_id, filtri)


def cerca_codice_fiscale(testo):
    """Chi ha questo codice fiscale (alunni e operatori di tutti i lotti): il codice arriva
    nel corpo della richiesta (mai nell'indirizzo, che finisce nei log) e non torna indietro."""
    scritto = re.sub(r'\s', '', str(testo or '')).upper()
    if len(scritto) != 16 or not re.fullmatch(r'[A-Z0-9]{16}', scritto):
        raise DatiNonValidi('Scrivi il codice fiscale intero (16 lettere e cifre).', 'codice_fiscale')
    with db.get_db_context() as conn:
        alunni = _righe(conn, 'SELECT a.id, a.cognome, a.nome, a.attivo, a.lotto_id, l.nome AS lotto FROM '
                              'napoli_alunni a JOIN napoli_lotti l ON l.id = a.lotto_id WHERE a.codice_fiscale = ?',
                        (scritto,))
        operatori = _righe(conn, 'SELECT id, cognome, nome, attivo FROM napoli_operatori WHERE codice_fiscale = ?',
                           (scritto,))
    trovati = [{'tipo': 'alunno', 'id': a['id'], 'nome': nome_persona(a), 'attivo': bool(a['attivo']),
                'lotto_id': a['lotto_id'], 'lotto': a['lotto']} for a in alunni]
    trovati += [{'tipo': 'operatore', 'id': o['id'], 'nome': nome_persona(o), 'attivo': bool(o['attivo'])}
                for o in operatori]
    return {'trovati': trovati, 'cf': calc.maschera_codice_fiscale(scritto)}


# ==================== origine (caricamento o a mano) ====================

def _origine(conn, lotto_id, tabella, id_, riga):
    """Da dove viene la riga: il caricamento dell'anagrafica (o l'import) non annullato che
    l'ha creata, altrimenti aggiunta a mano. lotto_id None: gli import di tutti i lotti (gli
    operatori non sono di un lotto)."""
    for imp in _righe(conn, 'SELECT id, anno, mese, data, esito_json, sostituite_json FROM napoli_import '
                            'WHERE (? IS NULL OR lotto_id = ?) AND annullato = 0 ORDER BY id DESC',
                      (lotto_id, lotto_id)):
        try:
            create = (json.loads(imp['sostituite_json'] or '{}').get('create') or {}).get(tabella) or []
        except (ValueError, AttributeError):
            continue
        if id_ in create:
            cosa = 'Caricato' if import_napoli._modo_salvato(imp) == 'anagrafica' else 'Importato'
            mese = import_napoli.mese_testo(imp['anno'], imp['mese']) if imp['anno'] and imp['mese'] else ''
            cambiata = riga.get('modificato_il') not in (None, imp['data'])
            return {'tipo': 'import', 'import_id': imp['id'], 'cambiata_dopo': cambiata,
                    'testo': f'{cosa} dal file Excel di {mese} il {import_napoli._data_ora_it(imp["data"])}'
                             + ('; poi cambiato a mano' if cambiata else '')}
    quando = riga.get('data_inserimento')
    return {'tipo': 'manuale', 'testo': f'Aggiunto in Assisto il {import_napoli._data_ora_it(quando)}' if quando
            else 'Aggiunto in Assisto'}


# ==================== scuole e plessi ====================

def _scuola(conn, scuola_id):
    riga = _riga(conn, 'SELECT * FROM napoli_scuole WHERE id = ?', (scuola_id,))
    if not riga:
        raise NonTrovato('La scuola non c\'è più (forse è stata eliminata): ricarica la pagina.')
    return riga


def _descrivi_scuola(s):
    return f'{s["nome"]}' + (f' (municipalità {s["municipalita"]})' if s.get('municipalita') else '')


def _valida_scuola(conn, lotto_id, dati, attuale=None):
    unito = dict(attuale or {})
    unito.update({k: v for k, v in dati.items() if k in ('nome', 'codice_meccanografico', 'municipalita', 'grado')})
    codice = re.sub(r'\s', '', str(unito.get('codice_meccanografico') or '')).upper() or None
    if codice and not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{8}', codice):
        raise DatiNonValidi('Il codice meccanografico ha 10 lettere e cifre e comincia con la sigla della provincia '
                            '(per esempio NAIC8ZZ001).', 'codice_meccanografico')
    grado = str(unito.get('grado') or '').strip().lower() or None
    if grado is not None and grado not in GRADI_SCUOLA:
        raise DatiNonValidi('Il grado è "inferiore", "superiore", "misto" oppure da decidere.', 'grado')
    valori = {
        'nome': ndb._testo(unito, 'nome', 'Il nome della scuola', True, 200,
                           manca='Scrivi il nome della scuola o del plesso.'),
        'codice_meccanografico': codice,
        'municipalita': _municipalita(unito),
        'grado': grado,
    }
    for altra in _righe(conn, 'SELECT * FROM napoli_scuole WHERE lotto_id = ? AND id IS NOT ?',
                        (lotto_id, (attuale or {}).get('id'))):
        if altra['municipalita'] != valori['municipalita']:
            continue
        stessa = (codice and altra['codice_meccanografico'] == codice) or (
            not codice and not altra['codice_meccanografico']
            and import_napoli.chiave_nome_scuola(altra['nome']) == import_napoli.chiave_nome_scuola(valori['nome']))
        if stessa:
            raise Conflitto(f'Nella municipalità {valori["municipalita"]} c\'è già il plesso "{altra["nome"]}"'
                            + (f' con il codice {codice}' if codice else '') + ': è lo stesso? Modifica quello.',
                            'codice_meccanografico' if codice else 'nome', codice='SCUOLA_GIA_PRESENTE',
                            scuola_id=altra['id'])
    return valori


def _avvisi_scuola(conn, valori, scuola_id=None):
    avvisi = []
    proposto = calc.grado_da_codice_meccanografico(valori['codice_meccanografico'])
    if valori['grado'] is None:
        avvisi.append('Il grado è da decidere: le ore di questa scuola non vanno in fattura finché non lo scegli.')
    elif proposto and valori['grado'] in calc.GRADI and proposto != valori['grado']:
        avvisi.append(f'Il codice meccanografico fa pensare al {ndb.NOMI_GRADO[proposto]}: controlla il grado.')
    if valori['grado'] == 'misto' and scuola_id:
        n = conn.execute('SELECT COUNT(*) FROM napoli_alunni WHERE scuola_id = ? AND attivo = 1 AND grado IS NULL',
                         (scuola_id,)).fetchone()[0]
        if n:
            avvisi.append(f'{_plurale(n, "alunno", "alunni")} di questo plesso senza il grado: sceglilo nella scheda '
                          'dell\'alunno.')
    return avvisi


def crea_scuola(lotto_id, dati):
    with db.get_db_context() as conn:
        ndb.lotto(lotto_id, conn)
        valori = _valida_scuola(conn, lotto_id, dati)
        ora = _ora()
        scuola_id = _inserisci(conn, 'scuole', dict(valori, lotto_id=lotto_id, attiva=1, data_inserimento=ora,
                                                     modificato_il=ora))
        modifiche = ndb._Modifiche(conn)
        modifiche.nuova('scuole', scuola_id)
        modifiche.salva('scuola', f'Nuova scuola {_descrivi_scuola(valori)}')
        avvisi = _avvisi_scuola(conn, valori, scuola_id)
    db.log_audit('creazione', 'napoli_scuola', scuola_id, dettagli=f'Napoli: nuova scuola {_descrivi_scuola(valori)}')
    return {'scuola_id': scuola_id, 'avvisi': avvisi, 'messaggio': 'Scuola aggiunta'}


def aggiorna_scuola(scuola_id, dati):
    with db.get_db_context() as conn:
        attuale = _scuola(conn, scuola_id)
        valori = _valida_scuola(conn, attuale['lotto_id'], dati, attuale)
        cambiati = _cambiati(attuale, valori)
        if not cambiati:
            return {'scuola_id': scuola_id, 'avvisi': [], 'messaggio': 'Nessun cambiamento da salvare'}
        modifiche = ndb._Modifiche(conn)
        modifiche.prima('scuole', scuola_id)
        _aggiorna_riga(conn, 'scuole', scuola_id, dict({k: valori[k] for k in cambiati}, modificato_il=_ora()))
        cosa = _elenco([NOMI_CAMPI[k] for k in cambiati])
        modifiche.salva('scuola', f'Modifica della scuola {_descrivi_scuola(valori)}: {cosa}')
        avvisi = _avvisi_scuola(conn, valori, scuola_id)
    db.log_audit('modifica', 'napoli_scuola', scuola_id,
                 dettagli=f'Napoli: modificata la scuola {_descrivi_scuola(valori)} ({cosa})')
    messaggio = 'Scuola salvata'
    if 'grado' in cambiati:
        messaggio += ': il grado nuovo vale per le fatture non ancora definitive'
    return {'scuola_id': scuola_id, 'avvisi': avvisi, 'messaggio': messaggio}


def archivia_scuola(scuola_id, archivia=True):
    """Una scuola che non c'e' piu' nel lotto si archivia (resta per i mesi passati). Con
    alunni in servizio o coppie aperte no: prima si spostano o si chiudono."""
    with db.get_db_context() as conn:
        attuale = _scuola(conn, scuola_id)
        if bool(attuale['attiva']) != archivia:
            raise Conflitto('La scuola è già archiviata.' if archivia else 'La scuola non è archiviata.',
                            codice='GIA_ARCHIVIATA' if archivia else 'NON_ARCHIVIATA')
        if archivia:
            an = _anagrafica(conn, attuale['lotto_id'])
            alunni = [a for a in an.alunni_scuola.get(scuola_id, ()) if a['attivo']]
            aperte = [c for c in an.coppie_scuola.get(scuola_id, ()) if an.aperta(c)]
            if alunni or aperte:
                parti = [_plurale(len(alunni), 'alunno in servizio', 'alunni in servizio') if alunni else '',
                         _plurale(len(aperte), 'coppia ancora aperta', 'coppie ancora aperte') if aperte else '']
                raise Conflitto(f'In questa scuola ci sono ancora {_elenco(parti)}: prima chiudi le coppie e sposta '
                                'o archivia gli alunni, poi archivia la scuola.', codice='SCUOLA_IN_USO')
        modifiche = ndb._Modifiche(conn)
        modifiche.prima('scuole', scuola_id)
        _aggiorna_riga(conn, 'scuole', scuola_id, {'attiva': 0 if archivia else 1, 'modificato_il': _ora()})
        cosa = 'Archiviazione' if archivia else 'Ripristino'
        modifiche.salva('scuola', f'{cosa} della scuola {_descrivi_scuola(attuale)}')
    db.log_audit('modifica', 'napoli_scuola', scuola_id, dettagli=f'Napoli: {cosa.lower()} della scuola '
                                                                  f'{_descrivi_scuola(attuale)}')
    return {'scuola_id': scuola_id, 'messaggio': 'Scuola archiviata' if archivia else 'Scuola di nuovo attiva'}


def elimina_scuola(scuola_id):
    """Solo una scuola senza alunni, coppie e giorni del calendario (per esempio aggiunta per
    sbaglio): altrimenti si archivia."""
    with db.get_db_context() as conn:
        attuale = _scuola(conn, scuola_id)
        for tabella in ('coppie', 'alunni', 'calendario'):
            if conn.execute(f'SELECT 1 FROM napoli_{tabella} WHERE scuola_id = ? LIMIT 1', (scuola_id,)).fetchone():
                raise Conflitto('La scuola ha alunni, coppie o giorni del calendario: non si elimina. Se non c\'è più, '
                                'archiviala.', codice='SCUOLA_CON_DATI')
        modifiche = ndb._Modifiche(conn)
        modifiche.prima('scuole', scuola_id)
        conn.execute('DELETE FROM napoli_scuole WHERE id = ?', (scuola_id,))
        modifiche.salva('scuola', f'Eliminazione della scuola {_descrivi_scuola(attuale)}')
    db.log_audit('eliminazione', 'napoli_scuola', scuola_id,
                 dettagli=f'Napoli: eliminata la scuola {_descrivi_scuola(attuale)}')
    return {'messaggio': 'Scuola eliminata'}


# ==================== alunni ====================

def _alunno(conn, alunno_id):
    riga = _riga(conn, 'SELECT * FROM napoli_alunni WHERE id = ?', (alunno_id,))
    if not riga:
        raise NonTrovato('L\'alunno non c\'è più (forse è stato eliminato): ricarica la pagina.')
    return riga


def _scheda_n(id_):
    return f'scheda n. {id_}'


def _valida_alunno(conn, lotto_id, dati, attuale=None):
    """Campi dell'alunno nella forma del database. Un campo che non arriva resta com'e'; il
    codice fiscale vuoto in una modifica resta quello salvato (non torna mai alla pagina)."""
    unito = dict(attuale or {})
    unito.update({k: v for k, v in dati.items() if k in ('cognome', 'nome', 'scuola_id', 'grado', 'esami', 'note')})
    valori = {
        'cognome': ndb._testo(unito, 'cognome', 'Il cognome', True, 80, manca='Scrivi il cognome dell\'alunno.'),
        'nome': ndb._testo(unito, 'nome', 'Il nome', True, 80, manca='Scrivi il nome dell\'alunno.'),
    }
    nuovo_cf = _codice_fiscale_persona(dati, attuale is None, 'dell\'alunno')
    valori['codice_fiscale'] = nuovo_cf or attuale['codice_fiscale']
    if nuovo_cf:
        altro = _riga(conn, 'SELECT a.id, a.cognome, a.nome, l.nome AS lotto FROM napoli_alunni a JOIN napoli_lotti l '
                            'ON l.id = a.lotto_id WHERE a.codice_fiscale = ? AND a.id IS NOT ?',
                      (nuovo_cf, (attuale or {}).get('id')))
        if altro:
            raise Conflitto(f'C\'è già un alunno con questo codice fiscale: {nome_persona(altro)} ({altro["lotto"]}). '
                            'Aprilo dall\'elenco invece di aggiungerne un altro.', 'codice_fiscale',
                            codice='ALUNNO_GIA_PRESENTE', alunno_id=altro['id'])
    scuola_id = _id(unito, 'scuola_id', 'Scegli la scuola (il plesso) dell\'alunno.')
    scuola = _riga(conn, 'SELECT * FROM napoli_scuole WHERE id = ? AND lotto_id = ?', (scuola_id, lotto_id))
    if not scuola:
        raise DatiNonValidi('La scuola scelta non è di questo lotto: ricarica la pagina.', 'scuola_id')
    if not scuola['attiva'] and scuola_id != (attuale or {}).get('scuola_id'):
        raise DatiNonValidi('La scuola scelta è archiviata: scegline un\'altra o ripristinala.', 'scuola_id')
    valori['scuola_id'] = scuola_id
    grado = str(unito.get('grado') or '').strip().lower() or None
    if grado is not None and grado not in calc.GRADI:
        raise DatiNonValidi('Il grado è "inferiore", "superiore" oppure quello della scuola.', 'grado')
    if grado is None and scuola['grado'] == 'misto':
        raise DatiNonValidi('Il plesso ha alunni di tutti e due i gradi: scegli il grado dell\'alunno.', 'grado')
    valori['grado'] = grado
    valori['esami'] = 1 if ndb._booleano(unito.get('esami'), False, 'esami') else 0
    valori['note'] = _nota_libera(unito)
    return valori, scuola


def crea_alunno(lotto_id, dati):
    with db.get_db_context() as conn:
        lotto = ndb.lotto(lotto_id, conn)
        valori, _scuola_alunno = _valida_alunno(conn, lotto_id, dati)
        ora = _ora()
        alunno_id = _inserisci(conn, 'alunni', dict(valori, lotto_id=lotto_id, attivo=1, data_inserimento=ora,
                                                     modificato_il=ora))
        modifiche = ndb._Modifiche(conn)
        modifiche.nuova('alunni', alunno_id)
        modifiche.salva('alunno', f'Nuovo alunno ({_scheda_n(alunno_id)})')
    db.log_audit('creazione', 'napoli_alunno', alunno_id,
                 dettagli=f'Napoli, {lotto["nome"]}: nuovo alunno ({_scheda_n(alunno_id)})')
    return {'alunno_id': alunno_id, 'messaggio': 'Alunno aggiunto: ora aggiungi le ore del PEI e le coppie con gli '
                                                 'operatori'}


def aggiorna_alunno(alunno_id, dati):
    with db.get_db_context() as conn:
        attuale = _alunno(conn, alunno_id)
        valori, _scuola_alunno = _valida_alunno(conn, attuale['lotto_id'], dati, attuale)
        cambiati = _cambiati(attuale, valori)
        if not cambiati:
            return {'alunno_id': alunno_id, 'messaggio': 'Nessun cambiamento da salvare'}
        cosa = _elenco([NOMI_CAMPI[k] for k in cambiati])
        descrizione = f'Modifica di un alunno ({_scheda_n(alunno_id)}): {cosa}'
        personali = [k for k in cambiati if k in ndb.COLONNE_PERSONALI['alunni']]
        modifiche = ndb._Modifiche(conn)
        if not personali:
            modifiche.prima('alunni', alunno_id)
        _aggiorna_riga(conn, 'alunni', alunno_id, dict({k: valori[k] for k in cambiati}, modificato_il=_ora()))
        if personali:
            ndb.registra_non_annullabile(conn, 'alunno', descrizione, ndb.MOTIVO_DATI_PERSONALI)
        else:
            modifiche.salva('alunno', descrizione)
    db.log_audit('modifica', 'napoli_alunno', alunno_id, dettagli=f'Napoli: modificato un alunno '
                                                                  f'({_scheda_n(alunno_id)}): {cosa}')
    messaggio = 'Alunno salvato'
    if personali:
        messaggio += f' (Ctrl+Z non annulla le modifiche a {_elenco([NOMI_CAMPI[k] for k in personali])})'
    if 'scuola_id' in cambiati:
        messaggio += '. Le coppie restano nella loro scuola: cambiala nella coppia se serve'
    return {'alunno_id': alunno_id, 'messaggio': messaggio}


def _chiudi_righe(conn, tabella, righe, al, modifiche):
    """Le righe (coppie o PEI) che valgono ancora il giorno dopo `al` finiscono il giorno `al`."""
    chiuse = 0
    for r in righe:
        if r.get('valido_a') is None or r['valido_a'] > al:
            modifiche.prima(tabella, r['id'])
            _aggiorna_riga(conn, tabella, r['id'], {'valido_a': al, 'modificato_il': _ora()})
            chiuse += 1
    return chiuse


def archivia_alunno(alunno_id, dati):
    """L'alunno esce dal servizio dal giorno `dal` (oggi se manca): le sue coppie e i suoi
    PEI ancora aperti finiscono il giorno prima, tutto in un'azione (un solo Ctrl+Z). Non
    si archivia da un giorno in cui ha gia' ore registrate."""
    with db.get_db_context() as conn:
        attuale = _alunno(conn, alunno_id)
        if not attuale['attivo']:
            raise Conflitto('L\'alunno è già archiviato.', codice='GIA_ARCHIVIATO')
        dal = ndb._valida(calc.valida_data, 'dal', dati.get('dal') or _oggi(), 'La data di uscita')
        al = _giorno_prima(dal)
        an = _anagrafica(conn, attuale['lotto_id'])
        coppie = an.coppie_alunno.get(alunno_id, [])
        pei = an.pei_alunno.get(alunno_id, [])
        ultima = max((an.presenze[c['id']]['ultima'] for c in coppie if c['id'] in an.presenze), default=None)
        if ultima and ultima >= dal:
            raise Conflitto(f'L\'alunno ha ore registrate fino al {calc.data_it(ultima)}: si può archiviare dal '
                            f'{calc.data_it(_giorno_dopo(ultima))} in poi.', 'dal', codice='ORE_DOPO_LA_DATA')
        dopo = [r for r in coppie + pei if r['valido_da'] > al]
        if dopo:
            r = dopo[0]
            cosa = (f'la coppia con {nome_persona(an.operatore.get(r["operatore_id"]))}' if 'operatore_id' in r
                    else f'il PEI di {ndb.nome_figura(r["figura"])}')
            raise Conflitto(f'Nella scheda c\'è {cosa} che comincia il {calc.data_it(r["valido_da"])}, dalla data di '
                            'uscita in poi: eliminalo o cambia la data, poi archivia.', 'dal',
                            codice='COMINCIA_DOPO_LA_DATA')
        modifiche = ndb._Modifiche(conn)
        coppie_chiuse = _chiudi_righe(conn, 'coppie', coppie, al, modifiche)
        pei_chiusi = _chiudi_righe(conn, 'pei', pei, al, modifiche)
        modifiche.prima('alunni', alunno_id)
        _aggiorna_riga(conn, 'alunni', alunno_id, {'attivo': 0, 'archiviato_dal': dal, 'modificato_il': _ora()})
        modifiche.salva('alunno', f'Archiviazione di un alunno ({_scheda_n(alunno_id)}) dal {calc.data_it(dal)}')
    chiuse = _elenco([_plurale(coppie_chiuse, 'coppia', 'coppie') if coppie_chiuse else '',
                      _plurale(pei_chiusi, 'PEI', 'PEI') if pei_chiusi else ''])
    db.log_audit('modifica', 'napoli_alunno', alunno_id,
                 dettagli=f'Napoli: archiviato un alunno ({_scheda_n(alunno_id)}) dal {calc.data_it(dal)}'
                          + (f'; chiusi al {calc.data_it(al)}: {chiuse}' if chiuse else ''))
    messaggio = f'Alunno archiviato dal {calc.data_it(dal)}'
    if chiuse:
        messaggio += f': chiusi al {calc.data_it(al)} {chiuse}'
    return {'alunno_id': alunno_id, 'messaggio': messaggio}


def ripristina_alunno(alunno_id):
    with db.get_db_context() as conn:
        attuale = _alunno(conn, alunno_id)
        if attuale['attivo']:
            raise Conflitto('L\'alunno non è archiviato.', codice='NON_ARCHIVIATO')
        modifiche = ndb._Modifiche(conn)
        modifiche.prima('alunni', alunno_id)
        _aggiorna_riga(conn, 'alunni', alunno_id, {'attivo': 1, 'archiviato_dal': None, 'modificato_il': _ora()})
        modifiche.salva('alunno', f'Ripristino di un alunno ({_scheda_n(alunno_id)})')
    db.log_audit('modifica', 'napoli_alunno', alunno_id, dettagli=f'Napoli: ripristinato un alunno '
                                                                  f'({_scheda_n(alunno_id)})')
    return {'alunno_id': alunno_id, 'messaggio': 'Alunno di nuovo in servizio. Le coppie e i PEI chiusi restano '
                                                 'chiusi: riaprili dalla scheda se serve'}


def elimina_alunno(alunno_id):
    """Solo un alunno senza ore, fogli firma e orari (per esempio aggiunto per sbaglio): si
    eliminano anche i suoi PEI e le sue coppie. Altrimenti si archivia. Ctrl+Z non lo
    rimette (i dati personali non restano in memoria)."""
    with db.get_db_context() as conn:
        attuale = _alunno(conn, alunno_id)
        an = _anagrafica(conn, attuale['lotto_id'])
        coppie = an.coppie_alunno.get(alunno_id, [])
        for c in coppie:
            collegati = an.dati_coppia(c)
            esterni = [s for s in an.sostituti.get(c['id'], ()) if s['alunno_id'] != alunno_id]
            if collegati['presenze'] or collegati['fogli'] or collegati['orari'] or esterni:
                raise Conflitto('L\'alunno ha già ore registrate, fogli firma o orari: non si elimina, perché '
                                'servono per i mesi passati. Se non è più in servizio, archivialo.',
                                codice='ALUNNO_CON_DATI')
        pei = an.pei_alunno.get(alunno_id, [])
        for c in sorted(coppie, key=lambda c: c['ruolo'] == 'titolare'):     # prima i sostituti
            conn.execute('DELETE FROM napoli_coppie WHERE id = ?', (c['id'],))
        conn.execute('DELETE FROM napoli_pei WHERE alunno_id = ?', (alunno_id,))
        conn.execute('DELETE FROM napoli_alunni WHERE id = ?', (alunno_id,))
        descrizione = f'Eliminazione di un alunno ({_scheda_n(alunno_id)})'
        ndb.registra_non_annullabile(conn, 'alunno', descrizione, MOTIVO_PERSONA_ELIMINATA)
    db.log_audit('eliminazione', 'napoli_alunno', alunno_id,
                 dettagli=f'Napoli: eliminato un alunno ({_scheda_n(alunno_id)}) con {len(pei)} PEI e '
                          f'{len(coppie)} coppie')
    return {'messaggio': 'Alunno eliminato'}


def scheda_alunno(alunno_id):
    with db.get_db_context() as conn:
        attuale = _alunno(conn, alunno_id)
        an = _anagrafica(conn, attuale['lotto_id'])
        riga = an.riga_alunno(attuale)
        righe_pei = sorted(an.pei_alunno.get(alunno_id, []), key=lambda p: p['valido_da'], reverse=True)
        figure = sorted({p['figura'] for p in righe_pei}, key=lambda f: an.figure.get(f, {}).get('ordine', 99))
        pei = []
        for f in figure:
            in_vigore = an.pei_in_vigore(alunno_id, f)
            pei.append({'figura': f, 'nome_figura': ndb.nome_figura(f),
                        'in_vigore_id': in_vigore['id'] if in_vigore else None,
                        'righe': [_riga_pei(p, an.oggi) for p in righe_pei if p['figura'] == f]})
        coppie = [an.riga_coppia(c) for c in sorted(an.coppie_alunno.get(alunno_id, []),
                                                     key=lambda c: (an.stato_coppia(c) == 'finita', c['figura'],
                                                                    c['ruolo'] != 'titolare', c['valido_da']))]
        origine = _origine(conn, attuale['lotto_id'], 'alunni', alunno_id, attuale)
        eliminabile = not any(c['presenze'] or c['fogli'] or c['orari'] for c in coppie)
    figure_credito = [{'figura': p['figura'], 'nome_figura': p['nome_figura']} for p in pei] or \
        [{'figura': c['figura'], 'nome_figura': c['nome_figura']} for c in coppie[:1]]
    return {
        'alunno': dict(riga, note=attuale.get('note'), lotto={'id': an.lotto['id'], 'nome': an.lotto['nome']},
                       data_inserimento=attuale.get('data_inserimento')),
        'pei': pei, 'coppie': coppie, 'origine': origine, 'eliminabile': eliminabile, 'oggi': an.oggi,
        # REGOLE 15: il credito/debito del mese e' nella griglia presenze (passo 1.7); qui lo spazio
        'credito_debito': {'disponibile': False, 'testo': CREDITO_DEBITO_TESTO, 'spiegazione': CREDITO_DEBITO_SPIEGAZIONE,
                           'figure': figure_credito},
    }


def _riga_pei(p, oggi):
    return {'id': p['id'], 'figura': p['figura'], 'nome_figura': ndb.nome_figura(p['figura']),
            'ore': p['ore_settimanali'], 'ore_testo': _ore_testo(p['ore_settimanali']), 'valido_da': p['valido_da'],
            'valido_a': p['valido_a'], 'stato': p['stato'], 'fonte': p.get('fonte'),
            'periodo': _stato_periodo(p['valido_da'], p.get('valido_a'), oggi)}


# ==================== PEI (ore settimanali da progetto, per figura) ====================

def _pei(conn, pei_id):
    riga = _riga(conn, 'SELECT * FROM napoli_pei WHERE id = ?', (pei_id,))
    if not riga:
        raise NonTrovato('Queste ore del PEI non ci sono più (forse sono state eliminate): ricarica la pagina.')
    return riga


def _descrivi_pei(p):
    return f'{ndb.nome_figura(p["figura"])} {_ore_testo(p["ore_settimanali"])} h {_periodo_it(p["valido_da"], p.get("valido_a"))}'


def _valida_pei(conn, alunno, dati, attuale=None):
    unito = dict(attuale or {})
    unito.update({k: v for k, v in dati.items() if k in ('figura', 'ore_settimanali', 'valido_da', 'valido_a',
                                                          'stato', 'fonte')})
    figura = _figura_persona(conn, unito, coppia=True) if attuale is None else attuale['figura']
    dal, al = ndb._periodo(unito, ('La data di inizio', 'La data di fine'))
    stato = str(unito.get('stato') or 'definitivo').strip().lower()
    if stato not in STATI_PEI:
        raise DatiNonValidi('Lo stato del PEI è definitivo, provvisorio o sospeso.', 'stato')
    return {'figura': figura,
            'ore_settimanali': _ore(unito, 'ore_settimanali', 'Le ore a settimana', obbligatorio=True),
            'valido_da': dal, 'valido_a': al, 'stato': stato,
            'fonte': ndb._testo(unito, 'fonte', 'La nota', massimo=200)}


def _sovrapposti(righe, dal, al, escludi=None):
    return [r for r in righe if r['id'] != escludi and _si_sovrappongono(r['valido_da'], r.get('valido_a'), dal, al)]


def aggiungi_pei(alunno_id, dati):
    """Ore settimanali del PEI di una figura da un giorno: se c'era gia' un PEI della stessa
    figura che comincia prima, finisce il giorno prima (e, se andava oltre la fine del nuovo,
    riprende il giorno dopo), nella stessa azione. Un PEI che comincia lo stesso giorno o
    dopo si modifica, non se ne aggiunge un altro."""
    with db.get_db_context() as conn:
        alunno = _alunno(conn, alunno_id)
        if not alunno['attivo']:
            raise Conflitto('L\'alunno è archiviato: ripristinalo prima di cambiare il PEI.', codice='ARCHIVIATO')
        valori = _valida_pei(conn, alunno, dati)
        altri = _righe(conn, 'SELECT * FROM napoli_pei WHERE alunno_id = ? AND figura = ? ORDER BY valido_da',
                       (alunno_id, valori['figura']))
        sovrapposti = _sovrapposti(altri, valori['valido_da'], valori['valido_a'])
        dopo = [r for r in sovrapposti if r['valido_da'] >= valori['valido_da']]
        if dopo:
            raise Conflitto(f'Dal {calc.data_it(dopo[0]["valido_da"])} c\'è già il PEI {_descrivi_pei(dopo[0])}: '
                            'modifica quello invece di aggiungerne un altro.', 'valido_da', codice='PEI_SOVRAPPOSTI',
                            pei_id=dopo[0]['id'])
        modifiche = ndb._Modifiche(conn)
        ora = _ora()
        note = []
        for r in sovrapposti:
            modifiche.prima('pei', r['id'])
            fine_nuovo = valori['valido_a']
            if fine_nuovo and (r.get('valido_a') is None or r['valido_a'] > fine_nuovo):
                copia = {k: v for k, v in r.items() if k != 'id'}
                copia.update(valido_da=_giorno_dopo(fine_nuovo), data_inserimento=ora, modificato_il=ora)
                modifiche.nuova('pei', _inserisci(conn, 'pei', copia))
                note.append(f'quelle di prima ({_ore_testo(r["ore_settimanali"])} h) valgono fino al '
                            f'{calc.data_it(_giorno_prima(valori["valido_da"]))} e di nuovo dal '
                            f'{calc.data_it(copia["valido_da"])}')
            else:
                note.append(f'quelle di prima ({_ore_testo(r["ore_settimanali"])} h) valgono fino al '
                            f'{calc.data_it(_giorno_prima(valori["valido_da"]))}')
            _aggiorna_riga(conn, 'pei', r['id'], {'valido_a': _giorno_prima(valori['valido_da']), 'modificato_il': ora})
        pei_id = _inserisci(conn, 'pei', dict(valori, alunno_id=alunno_id, data_inserimento=ora, modificato_il=ora,
                                              fonte=valori['fonte'] or 'Scritto in Assisto'))
        modifiche.nuova('pei', pei_id)
        modifiche.salva('pei', f'PEI di un alunno ({_scheda_n(alunno_id)}): {_descrivi_pei(valori)}')
    db.log_audit('creazione', 'napoli_pei', pei_id,
                 dettagli=f'Napoli: PEI di un alunno ({_scheda_n(alunno_id)}): {_descrivi_pei(valori)}')
    messaggio = f'Ore del PEI salvate: {_descrivi_pei(valori)}'
    if note:
        messaggio += '; ' + '; '.join(note)
    return {'pei_id': pei_id, 'messaggio': messaggio}


def aggiorna_pei(pei_id, dati):
    """Corregge ore, date, stato o nota di una riga del PEI (la figura resta: per un'altra
    figura si aggiunge un PEI). Le date non possono accavallarsi con un'altra riga della
    stessa figura."""
    with db.get_db_context() as conn:
        attuale = _pei(conn, pei_id)
        alunno = _alunno(conn, attuale['alunno_id'])
        valori = _valida_pei(conn, alunno, dati, attuale)
        altri = _righe(conn, 'SELECT * FROM napoli_pei WHERE alunno_id = ? AND figura = ? ORDER BY valido_da',
                       (alunno['id'], attuale['figura']))
        sovrapposti = _sovrapposti(altri, valori['valido_da'], valori['valido_a'], escludi=pei_id)
        if sovrapposti:
            raise Conflitto(f'Le date si accavallano con il PEI {_descrivi_pei(sovrapposti[0])}: cambia le date di '
                            'uno dei due.', 'valido_da', codice='PEI_SOVRAPPOSTI')
        cambiati = _cambiati(attuale, valori)
        if not cambiati:
            return {'pei_id': pei_id, 'messaggio': 'Nessun cambiamento da salvare'}
        modifiche = ndb._Modifiche(conn)
        testo_libero = [k for k in cambiati if k in ndb.COLONNE_TESTO_LIBERO['pei']]
        if not testo_libero:
            modifiche.prima('pei', pei_id)
        _aggiorna_riga(conn, 'pei', pei_id, dict({k: valori[k] for k in cambiati}, modificato_il=_ora()))
        descrizione = f'Modifica del PEI di un alunno ({_scheda_n(alunno["id"])}): {_descrivi_pei(valori)}'
        if testo_libero:
            ndb.registra_non_annullabile(conn, 'pei', descrizione, ndb.MOTIVO_TESTO_LIBERO)
        else:
            modifiche.salva('pei', descrizione)
    db.log_audit('modifica', 'napoli_pei', pei_id,
                 dettagli=f'Napoli: modificato il PEI di un alunno ({_scheda_n(alunno["id"])}): {_descrivi_pei(valori)}')
    messaggio = f'PEI salvato: {_descrivi_pei(valori)}'
    if testo_libero:
        messaggio += ' (Ctrl+Z non annulla le modifiche alla nota)'
    return {'pei_id': pei_id, 'messaggio': messaggio}


def elimina_pei(pei_id):
    """Una riga del PEI scritta per sbaglio. Se l'alunno ha ore della figura in quel periodo
    non si elimina (si cambiano le date o le ore)."""
    with db.get_db_context() as conn:
        attuale = _pei(conn, pei_id)
        ore = conn.execute('SELECT COUNT(*) FROM napoli_presenze p JOIN napoli_coppie c ON c.id = p.coppia_id '
                           'WHERE c.alunno_id = ? AND p.figura = ? AND p.data >= ? AND p.data <= ?',
                           (attuale['alunno_id'], attuale['figura'], attuale['valido_da'],
                            attuale['valido_a'] or '9999-12-31')).fetchone()[0]
        if ore:
            raise Conflitto(f'In questo periodo ci sono già ore di {ndb.nome_figura(attuale["figura"])} registrate: '
                            'il PEI non si elimina, cambia le date o le ore.', codice='PEI_CON_ORE')
        modifiche = ndb._Modifiche(conn)
        modifiche.prima('pei', pei_id)
        conn.execute('DELETE FROM napoli_pei WHERE id = ?', (pei_id,))
        modifiche.salva('pei', f'Eliminazione del PEI di un alunno ({_scheda_n(attuale["alunno_id"])}): '
                               f'{_descrivi_pei(attuale)}')
    db.log_audit('eliminazione', 'napoli_pei', pei_id,
                 dettagli=f'Napoli: eliminato il PEI di un alunno ({_scheda_n(attuale["alunno_id"])}): '
                          f'{_descrivi_pei(attuale)}')
    messaggio = 'Ore del PEI eliminate'
    if str(attuale.get('fonte') or '').strip():
        messaggio += ' (con Ctrl+Z tornano senza la nota, che non resta in memoria)'
    return {'messaggio': messaggio}


# ==================== operatori ====================

def _operatore(conn, operatore_id):
    riga = _riga(conn, 'SELECT * FROM napoli_operatori WHERE id = ?', (operatore_id,))
    if not riga:
        raise NonTrovato('L\'operatore non c\'è più (forse è stato eliminato): ricarica la pagina.')
    return riga


def _valida_operatore(conn, dati, attuale=None):
    unito = dict(attuale or {})
    unito.update({k: v for k, v in dati.items() if k in ('cognome', 'nome', 'figura', 'livello_ccnl', 'ore_contratto',
                                                          'note')})
    valori = {
        'cognome': ndb._testo(unito, 'cognome', 'Il cognome', True, 80, manca='Scrivi il cognome dell\'operatore.'),
        'nome': ndb._testo(unito, 'nome', 'Il nome', True, 80, manca='Scrivi il nome dell\'operatore.'),
        'figura': _figura_persona(conn, unito),
    }
    livello = ndb._testo(unito, 'livello_ccnl', 'Il livello', massimo=10, maiuscolo=True)
    if livello and not re.fullmatch(r'[A-Z0-9][A-Z0-9 /]*', livello):
        raise DatiNonValidi('Il livello si scrive con lettere e cifre, per esempio D2.', 'livello_ccnl')
    valori['livello_ccnl'] = livello
    valori['ore_contratto'] = _ore(unito, 'ore_contratto', 'Le ore di contratto')
    valori['note'] = _nota_libera(unito)
    nuovo_cf = _codice_fiscale_persona(dati, False, 'dell\'operatore')
    if nuovo_cf:
        altro = _riga(conn, 'SELECT id, cognome, nome FROM napoli_operatori WHERE codice_fiscale = ? AND id IS NOT ?',
                      (nuovo_cf, (attuale or {}).get('id')))
        if altro:
            raise Conflitto(f'C\'è già un operatore con questo codice fiscale: {nome_persona(altro)}. Aprilo '
                            'dall\'elenco invece di aggiungerne un altro.', 'codice_fiscale',
                            codice='OPERATORE_GIA_PRESENTE', operatore_id=altro['id'])
        valori.update(codice_fiscale=nuovo_cf, cf_valido=1)
    elif attuale is None:
        valori.update(codice_fiscale=None, cf_valido=0)
    return valori


def crea_operatore(dati):
    with db.get_db_context() as conn:
        valori = _valida_operatore(conn, dati)
        ora = _ora()
        operatore_id = _inserisci(conn, 'operatori', dict(valori, attivo=1, data_inserimento=ora, modificato_il=ora))
        modifiche = ndb._Modifiche(conn)
        modifiche.nuova('operatori', operatore_id)
        modifiche.salva('operatore', f'Nuovo operatore ({_scheda_n(operatore_id)}, {ndb.nome_figura(valori["figura"])})')
    db.log_audit('creazione', 'napoli_operatore', operatore_id,
                 dettagli=f'Napoli: nuovo operatore ({_scheda_n(operatore_id)}, {ndb.nome_figura(valori["figura"])})')
    return {'operatore_id': operatore_id, 'messaggio': 'Operatore aggiunto: ora aggiungi le sue coppie con gli alunni'}


def aggiorna_operatore(operatore_id, dati):
    with db.get_db_context() as conn:
        attuale = _operatore(conn, operatore_id)
        valori = _valida_operatore(conn, dati, attuale)
        cambiati = _cambiati(attuale, valori)
        if not cambiati:
            return {'operatore_id': operatore_id, 'messaggio': 'Nessun cambiamento da salvare'}
        cosa = _elenco(list(dict.fromkeys(NOMI_CAMPI[k] for k in cambiati)))
        descrizione = f'Modifica di un operatore ({_scheda_n(operatore_id)}): {cosa}'
        personali = [k for k in cambiati if k in ndb.COLONNE_PERSONALI['operatori']]
        modifiche = ndb._Modifiche(conn)
        if not personali:
            modifiche.prima('operatori', operatore_id)
        _aggiorna_riga(conn, 'operatori', operatore_id, dict({k: valori[k] for k in cambiati}, modificato_il=_ora()))
        if personali:
            ndb.registra_non_annullabile(conn, 'operatore', descrizione, ndb.MOTIVO_DATI_PERSONALI)
        else:
            modifiche.salva('operatore', descrizione)
        diverse = 0
        if 'figura' in cambiati:
            diverse = conn.execute('SELECT COUNT(*) FROM napoli_coppie WHERE operatore_id = ? AND figura <> ? AND '
                                   '(valido_a IS NULL OR valido_a >= ?)', (operatore_id, valori['figura'],
                                                                         _oggi())).fetchone()[0]
    db.log_audit('modifica', 'napoli_operatore', operatore_id,
                 dettagli=f'Napoli: modificato un operatore ({_scheda_n(operatore_id)}): {cosa}')
    messaggio = 'Operatore salvato'
    if personali:
        messaggio += (' (Ctrl+Z non annulla le modifiche a '
                      f'{_elenco(list(dict.fromkeys(NOMI_CAMPI[k] for k in personali)))})')
    if diverse:
        messaggio += (f'. {_plurale(diverse, "coppia aperta ha", "coppie aperte hanno")} ancora un\'altra figura: '
                      'le ore si contano con la figura della coppia, cambiala se serve')
    return {'operatore_id': operatore_id, 'messaggio': messaggio}


def archivia_operatore(operatore_id, dati):
    """L'operatore non lavora piu' dal giorno `dal` (oggi se manca). Con coppie che valgono
    ancora da quel giorno no: prima si chiudono o si fa il subentro con un altro operatore."""
    with db.get_db_context() as conn:
        attuale = _operatore(conn, operatore_id)
        if not attuale['attivo']:
            raise Conflitto('L\'operatore è già archiviato.', codice='GIA_ARCHIVIATO')
        dal = ndb._valida(calc.valida_data, 'dal', dati.get('dal') or _oggi(), 'La data')
        aperte = _righe(conn, 'SELECT c.id, a.cognome, a.nome FROM napoli_coppie c JOIN napoli_alunni a ON '
                              'a.id = c.alunno_id WHERE c.operatore_id = ? AND (c.valido_a IS NULL OR c.valido_a >= ?) '
                              'ORDER BY a.cognome, a.nome', (operatore_id, dal))
        if aperte:
            nomi = _elenco([nome_persona(a) for a in aperte[:3]] + ([f'altri {len(aperte) - 3}']
                                                                    if len(aperte) > 3 else []))
            raise Conflitto(f'L\'operatore ha ancora {_plurale(len(aperte), "coppia", "coppie")} dal '
                            f'{calc.data_it(dal)} in poi ({nomi}): prima chiudile o fai il subentro con un altro '
                            'operatore.', 'dal', codice='OPERATORE_CON_COPPIE')
        modifiche = ndb._Modifiche(conn)
        modifiche.prima('operatori', operatore_id)
        _aggiorna_riga(conn, 'operatori', operatore_id, {'attivo': 0, 'archiviato_dal': dal, 'modificato_il': _ora()})
        modifiche.salva('operatore', f'Archiviazione di un operatore ({_scheda_n(operatore_id)}) dal {calc.data_it(dal)}')
    db.log_audit('modifica', 'napoli_operatore', operatore_id,
                 dettagli=f'Napoli: archiviato un operatore ({_scheda_n(operatore_id)}) dal {calc.data_it(dal)}')
    return {'operatore_id': operatore_id, 'messaggio': f'Operatore archiviato dal {calc.data_it(dal)}'}


def ripristina_operatore(operatore_id):
    with db.get_db_context() as conn:
        attuale = _operatore(conn, operatore_id)
        if attuale['attivo']:
            raise Conflitto('L\'operatore non è archiviato.', codice='NON_ARCHIVIATO')
        modifiche = ndb._Modifiche(conn)
        modifiche.prima('operatori', operatore_id)
        _aggiorna_riga(conn, 'operatori', operatore_id, {'attivo': 1, 'archiviato_dal': None, 'modificato_il': _ora()})
        modifiche.salva('operatore', f'Ripristino di un operatore ({_scheda_n(operatore_id)})')
    db.log_audit('modifica', 'napoli_operatore', operatore_id,
                 dettagli=f'Napoli: ripristinato un operatore ({_scheda_n(operatore_id)})')
    return {'operatore_id': operatore_id, 'messaggio': 'Operatore di nuovo in servizio'}


def elimina_operatore(operatore_id):
    """Solo un operatore senza coppie e senza ore del coordinatore (per esempio aggiunto per
    sbaglio); altrimenti si archivia. Ctrl+Z non lo rimette."""
    with db.get_db_context() as conn:
        _operatore(conn, operatore_id)
        if conn.execute('SELECT 1 FROM napoli_coppie WHERE operatore_id = ? UNION ALL SELECT 1 FROM '
                        'napoli_coordinamento WHERE operatore_id = ? LIMIT 1', (operatore_id, operatore_id)).fetchone():
            raise Conflitto('L\'operatore ha coppie con gli alunni o ore del coordinatore: non si elimina, perché '
                            'servono per i mesi passati. Se non lavora più, archivialo.', codice='OPERATORE_CON_DATI')
        conn.execute('DELETE FROM napoli_operatori WHERE id = ?', (operatore_id,))
        ndb.registra_non_annullabile(conn, 'operatore', f'Eliminazione di un operatore ({_scheda_n(operatore_id)})',
                                     MOTIVO_PERSONA_ELIMINATA)
    db.log_audit('eliminazione', 'napoli_operatore', operatore_id,
                 dettagli=f'Napoli: eliminato un operatore ({_scheda_n(operatore_id)})')
    return {'messaggio': 'Operatore eliminato'}


def scheda_operatore(operatore_id, lotto_id=None):
    """L'operatore con le sue coppie di tutti i lotti (le ore a settimana di quelle in corso
    confrontate con le ore di contratto). lotto_id: il lotto della pagina (i conteggi della
    riga sono di quel lotto)."""
    with db.get_db_context() as conn:
        attuale = _operatore(conn, operatore_id)
        lotti = [r['lotto_id'] for r in _righe(conn, 'SELECT DISTINCT lotto_id FROM napoli_coppie '
                                                     'WHERE operatore_id = ? ORDER BY lotto_id', (operatore_id,))]
        if lotto_id is not None:
            ndb.lotto(lotto_id, conn)
            if lotto_id not in lotti:
                lotti.insert(0, lotto_id)
        coppie, riga = [], None
        for lid in lotti:
            an = _anagrafica(conn, lid)
            if riga is None or lid == lotto_id:
                riga = an.riga_operatore(attuale)
            coppie += [an.riga_coppia(c) for c in an.coppie_operatore.get(operatore_id, [])]
        if riga is None:
            riga = _AnagraficaVuota().riga_operatore(attuale)
        origine = _origine(conn, None, 'operatori', operatore_id, attuale)
        coordinatore = bool(conn.execute('SELECT 1 FROM napoli_coordinamento WHERE operatore_id = ? LIMIT 1',
                                         (operatore_id,)).fetchone())
    coppie.sort(key=lambda c: (c['stato'] == 'finita', _normalizza(c['alunno']['nome']), c['valido_da']))
    in_corso = [c for c in coppie if c['stato'] == 'in_corso']
    ore = sum(Decimal(str(c['ore'])) for c in in_corso if c['ore'] is not None)
    return {'operatore': dict(riga, note=attuale.get('note'), data_inserimento=attuale.get('data_inserimento'),
                              ore_progetto=float(ore), ore_progetto_testo=_ore_testo(ore) if in_corso else '',
                              coppie_in_corso=len(in_corso)),
            'coppie': coppie, 'origine': origine, 'eliminabile': not coppie and not coordinatore}


class _AnagraficaVuota(_Anagrafica):
    """Per la riga di un operatore senza coppie in nessun lotto (niente da leggere)."""

    def __init__(self):
        self.oggi = _oggi()
        self.coppie_operatore, self.alunno, self.scuola, self.pei_alunno = {}, {}, {}, {}


# ==================== coppie operatore-alunno ====================

def _coppia(conn, coppia_id):
    riga = _riga(conn, 'SELECT * FROM napoli_coppie WHERE id = ?', (coppia_id,))
    if not riga:
        raise NonTrovato('La coppia non c\'è più (forse è stata eliminata): ricarica la pagina.')
    return riga


def _descrivi_coppia(c):
    ruolo = ' (sostituto)' if c.get('ruolo') == 'sostituto' else ''
    return f'{ndb.nome_figura(c["figura"])}{ruolo} {_periodo_it(c["valido_da"], c.get("valido_a"))}'


def _controlla_date_ore(an, c, dal, al):
    """Le date di una coppia devono comprendere i giorni che hanno gia' ore registrate."""
    collegati = an.dati_coppia(c) if c.get('id') in an.coppia else {}
    prima, ultima = collegati.get('prima_presenza'), collegati.get('ultima_presenza')
    if prima and dal > prima:
        raise Conflitto(f'La coppia ha ore registrate dal {calc.data_it(prima)}: non può cominciare dopo.', 'valido_da',
                        codice='ORE_FUORI_DATE')
    if ultima and al and al < ultima:
        raise Conflitto(f'La coppia ha ore registrate fino al {calc.data_it(ultima)}: non può finire prima (si può '
                        f'chiudere dal {calc.data_it(ultima)} in poi).', 'valido_a', codice='ORE_FUORI_DATE')


def _avvisi_coppia(an, c, chiusa=None):
    """Cose da controllare dopo il salvataggio (la coppia si salva lo stesso). chiusa: la
    coppia appena chiusa da un subentro, che nella lettura di prima valeva ancora."""
    avvisi = []
    operatore = an.operatore.get(c['operatore_id']) or {}
    if operatore and operatore.get('figura') != c['figura']:
        avvisi.append(f'L\'operatore è {ndb.nome_figura(operatore["figura"])}, la coppia {ndb.nome_figura(c["figura"])}:'
                      ' le ore si contano con la figura della coppia.')
    if c.get('ore_settimanali') is None and not an.pei_in_vigore(c['alunno_id'], c['figura'],
                                                                 max(an.oggi, c['valido_da'])):
        avvisi.append(f'L\'alunno non ha ore del PEI di {ndb.nome_figura(c["figura"])}: aggiungile nella sua scheda.')
    if c['ruolo'] == 'titolare':
        altri = [x for x in an.coppie_alunno.get(c['alunno_id'], ()) if x['id'] not in (c.get('id'), chiusa)
                 and x['figura'] == c['figura'] and x['ruolo'] == 'titolare'
                 and _si_sovrappongono(x['valido_da'], x.get('valido_a'), c['valido_da'], c.get('valido_a'))]
        if altri:
            avvisi.append(f'L\'alunno ha già un\'altra coppia titolare di {ndb.nome_figura(c["figura"])} negli stessi '
                          f'giorni (con {nome_persona(an.operatore.get(altri[0]["operatore_id"]))}): controlla che le '
                          'ore siano divise (ore a settimana della coppia).')
    return avvisi


def _valida_coppia(conn, an, dati, attuale=None):
    """Campi di una coppia. Alunno, operatore, figura e ruolo si scelgono quando la coppia
    nasce; dopo si cambiano scuola, ore, date, note (e il titolare di un sostituto). Per
    cambiare operatore c'e' il subentro."""
    unito = dict(attuale or {})
    unito.update({k: v for k, v in dati.items() if k in ('scuola_id', 'ore_settimanali', 'valido_da', 'valido_a',
                                                          'note', 'titolare_coppia_id')})
    if attuale is None:
        unito.update({k: v for k, v in dati.items() if k in ('alunno_id', 'operatore_id', 'figura', 'ruolo')})
        alunno_id = _id(unito, 'alunno_id', 'Scegli l\'alunno.')
        alunno = an.alunno.get(alunno_id)
        if not alunno:
            raise DatiNonValidi('L\'alunno scelto non è di questo lotto: ricarica la pagina.', 'alunno_id')
        if not alunno['attivo']:
            raise DatiNonValidi('L\'alunno scelto è archiviato: ripristinalo prima.', 'alunno_id')
        operatore_id = _id(unito, 'operatore_id', 'Scegli l\'operatore.')
        operatore = _riga(conn, 'SELECT * FROM napoli_operatori WHERE id = ?', (operatore_id,))
        if not operatore:
            raise DatiNonValidi('L\'operatore scelto non c\'è più: ricarica la pagina.', 'operatore_id')
        if not operatore['attivo']:
            raise DatiNonValidi('L\'operatore scelto è archiviato: ripristinalo prima.', 'operatore_id')
        an.operatore.setdefault(operatore_id, operatore)
        if not str(unito.get('figura') or '').strip():
            unito['figura'] = operatore['figura']
        figura = _figura_persona(conn, unito, coppia=True)
        ruolo = str(unito.get('ruolo') or 'titolare').strip().lower()
        if ruolo not in RUOLI:
            raise DatiNonValidi('Il ruolo è titolare o sostituto.', 'ruolo')
        if not str(unito.get('scuola_id') or '').strip():
            unito['scuola_id'] = alunno['scuola_id']
    else:
        alunno_id, operatore_id = attuale['alunno_id'], attuale['operatore_id']
        figura, ruolo = attuale['figura'], attuale['ruolo']
    scuola_id = _id(unito, 'scuola_id', 'Scegli la scuola (il plesso) della coppia.')
    scuola = an.scuola.get(scuola_id)
    if not scuola:
        raise DatiNonValidi('La scuola scelta non è di questo lotto: ricarica la pagina.', 'scuola_id')
    if not scuola['attiva'] and scuola_id != (attuale or {}).get('scuola_id'):
        raise DatiNonValidi('La scuola scelta è archiviata: scegline un\'altra.', 'scuola_id')
    dal, al = ndb._periodo(unito, ('La data di inizio', 'La data di fine'))
    titolare_id = None
    if ruolo == 'sostituto':
        titolare_id = _id(unito, 'titolare_coppia_id', 'Scegli chi sostituisce (la coppia del titolare).')
        titolare = an.coppia.get(titolare_id)
        if not titolare or titolare['alunno_id'] != alunno_id or titolare['figura'] != figura \
                or titolare['ruolo'] != 'titolare':
            raise DatiNonValidi('Il sostituto prende il posto di un titolare dello stesso alunno e della stessa '
                                'figura: sceglilo dall\'elenco.', 'titolare_coppia_id')
    valori = {'alunno_id': alunno_id, 'operatore_id': operatore_id, 'figura': figura, 'ruolo': ruolo,
              'titolare_coppia_id': titolare_id, 'scuola_id': scuola_id,
              'ore_settimanali': _ore(unito, 'ore_settimanali', 'Le ore a settimana della coppia'),
              'valido_da': dal, 'valido_a': al, 'note': _nota_libera(unito)}
    for altra in an.coppie_alunno.get(alunno_id, ()):
        if altra['id'] != (attuale or {}).get('id') and altra['operatore_id'] == operatore_id \
                and altra['figura'] == figura and altra['ruolo'] == ruolo \
                and _si_sovrappongono(altra['valido_da'], altra.get('valido_a'), dal, al):
            raise Conflitto(f'Questa coppia c\'è già: {_descrivi_coppia(altra)}. Cambia le date di quella invece di '
                            'aggiungerne un\'altra.', 'valido_da', codice='COPPIA_GIA_PRESENTE', coppia_id=altra['id'])
    if attuale is not None:
        _controlla_date_ore(an, attuale, dal, al)
        vecchia_fine = attuale.get('valido_a')
        if vecchia_fine and (al is None or al > vecchia_fine):
            # allungare (o riaprire) la coppia di una persona archiviata: come crearla
            operatore = _riga(conn, 'SELECT attivo FROM napoli_operatori WHERE id = ?', (operatore_id,)) or {}
            if not operatore.get('attivo'):
                raise Conflitto('L\'operatore è archiviato: ripristinalo prima di allungare o riaprire la coppia.',
                                'valido_a', codice='ARCHIVIATO')
            if not (an.alunno.get(alunno_id) or {}).get('attivo'):
                raise Conflitto('L\'alunno è archiviato: ripristinalo prima di allungare o riaprire la coppia.',
                                'valido_a', codice='ARCHIVIATO')
    return valori


def crea_coppia(lotto_id, dati):
    with db.get_db_context() as conn:
        an = _anagrafica(conn, lotto_id)
        valori = _valida_coppia(conn, an, dati)
        ora = _ora()
        coppia_id = _inserisci(conn, 'coppie', dict(valori, lotto_id=lotto_id, origine='manuale', data_inserimento=ora,
                                                     modificato_il=ora))
        modifiche = ndb._Modifiche(conn)
        modifiche.nuova('coppie', coppia_id)
        modifiche.salva('coppia', f'Nuova coppia ({_descrivi_coppia(valori)})')
        avvisi = _avvisi_coppia(an, valori)
    db.log_audit('creazione', 'napoli_coppia', coppia_id,
                 dettagli=f'Napoli, {an.lotto["nome"]}: nuova coppia operatore-alunno ({_descrivi_coppia(valori)})')
    return {'coppia_id': coppia_id, 'avvisi': avvisi, 'messaggio': 'Coppia aggiunta'}


def aggiorna_coppia(coppia_id, dati):
    with db.get_db_context() as conn:
        attuale = _coppia(conn, coppia_id)
        an = _anagrafica(conn, attuale['lotto_id'])
        valori = _valida_coppia(conn, an, dati, attuale)
        cambiati = _cambiati(attuale, valori)
        if not cambiati:
            return {'coppia_id': coppia_id, 'avvisi': [], 'messaggio': 'Nessun cambiamento da salvare'}
        modifiche = ndb._Modifiche(conn)
        testo_libero = [k for k in cambiati if k in ndb.COLONNE_TESTO_LIBERO['coppie']]
        if not testo_libero:
            modifiche.prima('coppie', coppia_id)
        _aggiorna_riga(conn, 'coppie', coppia_id, dict({k: valori[k] for k in cambiati}, modificato_il=_ora()))
        cosa = _elenco([NOMI_CAMPI.get(k, k) for k in cambiati])
        descrizione = f'Modifica di una coppia ({_descrivi_coppia(valori)}): {cosa}'
        if testo_libero:
            ndb.registra_non_annullabile(conn, 'coppia', descrizione, ndb.MOTIVO_TESTO_LIBERO)
        else:
            modifiche.salva('coppia', descrizione)
        avvisi = _avvisi_coppia(an, dict(valori, id=coppia_id))
    db.log_audit('modifica', 'napoli_coppia', coppia_id,
                 dettagli=f'Napoli: modificata una coppia operatore-alunno ({_descrivi_coppia(valori)}): {cosa}')
    messaggio = 'Coppia salvata'
    if testo_libero:
        messaggio += ' (Ctrl+Z non annulla le modifiche alle note)'
    return {'coppia_id': coppia_id, 'avvisi': avvisi, 'messaggio': messaggio}


def chiudi_coppia(coppia_id, dati):
    """La coppia finisce il giorno `valido_a` (non prima di un giorno con ore registrate)."""
    if not str(dati.get('valido_a') or '').strip():
        raise DatiNonValidi('Scegli l\'ultimo giorno della coppia.', 'valido_a')
    with db.get_db_context() as conn:
        attuale = _coppia(conn, coppia_id)
    esito = aggiorna_coppia(coppia_id, {'valido_a': dati.get('valido_a')})
    if esito['messaggio'] != 'Nessun cambiamento da salvare':
        al = ndb._valida(calc.valida_data, 'valido_a', dati.get('valido_a'), 'La data di fine')
        esito['messaggio'] = f'Coppia chiusa: l\'ultimo giorno è il {calc.data_it(al)}'
        if attuale.get('valido_a') and attuale['valido_a'] > al:
            esito['messaggio'] += f' (prima era il {calc.data_it(attuale["valido_a"])})'
    return esito


def subentro(coppia_id, dati):
    """Un altro operatore prende il posto di quello della coppia dal giorno `dal`: la coppia
    finisce il giorno prima e ne nasce una nuova con lo stesso alunno, figura, ruolo, scuola
    e ore, fino alla fine che aveva la vecchia. Tutto in un'azione (un solo Ctrl+Z)."""
    with db.get_db_context() as conn:
        attuale = _coppia(conn, coppia_id)
        an = _anagrafica(conn, attuale['lotto_id'])
        dal = ndb._valida(calc.valida_data, 'dal', dati.get('dal'), 'Il giorno del subentro')
        if dal <= attuale['valido_da']:
            raise DatiNonValidi(f'Il subentro è dopo l\'inizio della coppia ({calc.data_it(attuale["valido_da"])}): '
                                'per cambiare l\'operatore dal primo giorno elimina la coppia e aggiungine una nuova.',
                                'dal')
        if attuale.get('valido_a') and dal > attuale['valido_a']:
            raise DatiNonValidi(f'La coppia è finita il {calc.data_it(attuale["valido_a"])}: il subentro va prima.', 'dal')
        ultima = an.dati_coppia(attuale)['ultima_presenza']
        if ultima and ultima >= dal:
            raise Conflitto(f'La coppia ha ore registrate fino al {calc.data_it(ultima)}: il subentro va dal '
                            f'{calc.data_it(_giorno_dopo(ultima))} in poi.', 'dal', codice='ORE_FUORI_DATE')
        if _id(dati, 'operatore_id', 'Scegli l\'operatore che prende il posto.') == attuale['operatore_id']:
            raise DatiNonValidi('Scegli un operatore diverso da quello della coppia.', 'operatore_id')
        nuova = _valida_coppia(conn, an, {
            'alunno_id': attuale['alunno_id'], 'operatore_id': dati.get('operatore_id'), 'figura': attuale['figura'],
            'ruolo': attuale['ruolo'], 'titolare_coppia_id': attuale.get('titolare_coppia_id'),
            'scuola_id': attuale['scuola_id'], 'ore_settimanali': attuale.get('ore_settimanali'), 'valido_da': dal,
            'valido_a': attuale.get('valido_a'), 'note': f'Subentro dal {calc.data_it(dal)}'})
        modifiche = ndb._Modifiche(conn)
        modifiche.prima('coppie', coppia_id)
        ora = _ora()
        _aggiorna_riga(conn, 'coppie', coppia_id, {'valido_a': _giorno_prima(dal), 'modificato_il': ora})
        nuova_id = _inserisci(conn, 'coppie', dict(nuova, lotto_id=attuale['lotto_id'], origine='manuale',
                                                   data_inserimento=ora, modificato_il=ora))
        modifiche.nuova('coppie', nuova_id)
        # I sostituti della coppia di prima che cominciano dal giorno del subentro in poi
        # sostituiscono il nuovo operatore: passano alla coppia nuova. Quelli gia' cominciati
        # restano dove sono (i loro giorni di prima sostituivano l'operatore di prima).
        sostituti = [c for c in an.coppie_alunno.get(attuale['alunno_id'], ())
                     if c.get('titolare_coppia_id') == coppia_id and c['ruolo'] == 'sostituto']
        spostati = [c for c in sostituti if c['valido_da'] >= dal]
        for c in spostati:
            modifiche.prima('coppie', c['id'])
            _aggiorna_riga(conn, 'coppie', c['id'], {'titolare_coppia_id': nuova_id, 'modificato_il': ora})
        a_cavallo = [c for c in sostituti if c['valido_da'] < dal and (c.get('valido_a') is None or c['valido_a'] >= dal)]
        modifiche.salva('coppia', f'Subentro in una coppia ({ndb.nome_figura(attuale["figura"])}) dal '
                                  f'{calc.data_it(dal)}')
        avvisi = _avvisi_coppia(an, dict(nuova, id=nuova_id), chiusa=coppia_id)
        for c in a_cavallo:
            avvisi.append(f'Il sostituto {nome_persona(an.operatore.get(c["operatore_id"]))} '
                          f'({_periodo_it(c["valido_da"], c.get("valido_a"))}) resta collegato alla coppia di prima: '
                          'se dal subentro sostituisce il nuovo operatore, chiudilo e aggiungi un sostituto della '
                          'coppia nuova.')
        nome = nome_persona(an.operatore.get(nuova['operatore_id']))
    db.log_audit('creazione', 'napoli_coppia', nuova_id,
                 dettagli=f'Napoli, {an.lotto["nome"]}: subentro nella coppia n. {coppia_id} dal {calc.data_it(dal)} '
                          f'(nuova coppia n. {nuova_id})')
    messaggio = (f'Subentro fatto: dal {calc.data_it(dal)} la coppia è con {nome}; quella di prima finisce il '
                 f'{calc.data_it(_giorno_prima(dal))}')
    if len(spostati) == 1:
        messaggio += f'; il sostituto che comincia dal {calc.data_it(dal)} in poi passa alla coppia nuova'
    elif spostati:
        messaggio += f'; i {len(spostati)} sostituti che cominciano dal {calc.data_it(dal)} in poi passano alla coppia nuova'
    return {'coppia_id': nuova_id, 'avvisi': avvisi, 'messaggio': messaggio, 'sostituti_spostati': len(spostati)}


def elimina_coppia(coppia_id):
    """Solo una coppia senza ore, fogli firma, orari e sostituti (per esempio aggiunta per
    sbaglio); altrimenti si chiude."""
    with db.get_db_context() as conn:
        attuale = _coppia(conn, coppia_id)
        an = _anagrafica(conn, attuale['lotto_id'])
        collegati = an.dati_coppia(attuale)
        if collegati['sostituti']:
            raise Conflitto('La coppia ha dei sostituti collegati: elimina o chiudi prima quelle coppie.',
                            codice='COPPIA_CON_DATI')
        if collegati['presenze'] or collegati['fogli'] or collegati['orari']:
            raise Conflitto('La coppia ha già ore registrate, fogli firma o orari: non si elimina, perché servono per '
                            'i mesi passati. Se è finita, chiudila.', codice='COPPIA_CON_DATI')
        modifiche = ndb._Modifiche(conn)
        modifiche.prima('coppie', coppia_id)
        conn.execute('DELETE FROM napoli_coppie WHERE id = ?', (coppia_id,))
        modifiche.salva('coppia', f'Eliminazione di una coppia ({_descrivi_coppia(attuale)})')
    db.log_audit('eliminazione', 'napoli_coppia', coppia_id,
                 dettagli=f'Napoli: eliminata una coppia operatore-alunno ({_descrivi_coppia(attuale)})')
    messaggio = 'Coppia eliminata'
    if str(attuale.get('note') or '').strip():
        messaggio += ' (con Ctrl+Z torna senza le note, che non restano in memoria)'
    return {'messaggio': messaggio}

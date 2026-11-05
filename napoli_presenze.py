"""Griglia presenze della sezione Napoli (passo 1.7, PROGETTO §5-§6; REGOLE 1, 2, 3, 12, 14, 15).

Come il foglio "master" del Comune: una riga per coppia operatore-alunno (alunno,
operatore, figura, ore PEI, sostituzione SI/NO), una colonna per giorno di servizio del
mese (lunedi'-sabato; le domeniche non ci sono, le festivita' e le chiusure del calendario
sono grigie),
la VERIFICA dopo ogni settimana, il totale del mese e il CREDITO/DEBITO di Napoli.
Le ore si scrivono qui da ora in avanti (REGOLE 14: nessuno storico): ogni casella e' un
giorno di napoli_presenze, l'unica fonte delle ore (D5).

Regole:
- caselle come il §5.1 (napoli_calcoli.leggi_ore_griglia): ore svolte decimali ('2',
  '1,5'), ore e minuti ('1:30'), sigle F, M, P/F perm dell'operatore (0 ore), A = alunno
  assente (meta' del programmato; se il programmato non si conosce la risposta lo chiede,
  'servono_programmati'), '1,30' ambiguo da confermare ('da_confermare'), vuoto = la casella
  si cancella;
- nota del giorno (napoli_calcoli.TIPI_NOTA_GIORNO): assemblea o evento e uscita
  didattica contano le ore svolte (REGOLE 2); ritardo o uscita anticipata dell'alunno, con
  l'orario, valgono le ore svolte piu' meta' della parte persa (REGOLE 12); l'assenza
  recuperata non conta la meta' (REGOLE 1); una descrizione breve facoltativa (testo
  libero: i codici fiscali si salvano mascherati, Ctrl+Z non la ricorda);
- le ore riconosciute si calcolano con napoli_calcoli.giorno_da_griglia (esito_giorno) e
  si salvano (minuti_riconosciuti: la fattura legge quelle); la VERIFICA per settimana e'
  napoli_calcoli.verifica_settimane per alunno e figura (titolari piu' sostituti: gialla
  oltre il PEI, rossa oltre il tetto); il credito/debito e' previste - erogate
  (napoli_calcoli.minuti_previsti e credito_debito: previste dalla programmazione
  settimanale se c'e', altrimenti dal PEI ripartito sui giorni di servizio, "stima dal
  PEI"; i giorni di servizio sono senza le festivita' di napoli_calcoli.festivita e senza
  le chiusure del calendario; erogate = ore riconosciute). Le ore di un sostituto contano
  nella riga del suo titolare;
- scrivendo solo nella casella, la parte della nota del giorno che non vale piu' con il
  nuovo valore (il ritardo con 'A', 'assenza recuperata' con le ore svolte) si toglie da
  sola e la risposta lo dice ('tolte');
- un mese chiuso del lotto (napoli_mesi_chiusi) non si cambia: 409 MESE_CHIUSO_LOTTO, anche
  con Ctrl+Z. Il mese si chiude a mese finito e si riapre con un motivo, che resta nel
  registro attivita'. Niente ore nei giorni che devono ancora arrivare, fuori dalle date
  della coppia o nei giorni registrati dal foglio firma (fasce effettive);
- ogni salvataggio (un gruppo di caselle) e' un'azione di Ctrl+Z di Napoli
  (napoli_db._Modifiche) e una voce del registro attivita', senza nomi.
"""
import datetime

import database as db
import import_napoli
import napoli_calcoli as calc
import napoli_db as ndb
import napoli_fattura
from napoli_db import Conflitto, DatiNonValidi, NonTrovato

MAX_CELLE = 2000          # caselle in un salvataggio (un incolla grande, a gruppi)
NOTA_MAX = 100            # descrizione libera della nota del giorno
MOTIVO_MAX = 200          # motivo della riapertura del mese
GIORNI_BREVI = ('lun', 'mar', 'mer', 'gio', 'ven', 'sab', 'dom')

# Che cosa vuol dire ogni avviso di una riga (la pagina li mostra cosi').
SPIEGAZIONI = {
    'settimana_oltre_pei': 'Una settimana supera le ore del PEI (in giallo)',
    'settimana_oltre_pei_piu_20': 'Una settimana supera il PEI di oltre il 20% (in rosso)',
    'ore_giorno_oltre_5': 'Un giorno ha più di 5 ore',
    'giorno_non_registrato': 'Ci sono giorni preparati ma non ancora registrati: valgono 0',
    'ore_in_giorno_di_chiusura': 'Ore in un giorno festivo o di chiusura del calendario: contano lo stesso (se il '
                                 'servizio non c\'era, svuota la casella)',
    'ore_fuori_dalle_date': 'Ore fuori dalle date della coppia',
    'ore_in_giorno_non_di_servizio': 'Ore in un giorno senza servizio (domenica)',
    'diverso_dalla_formula': 'Ore diverse dal calcolo con le regole di oggi',
    'ore_svolte_con_alunno_assente': 'Ore svolte in un giorno con l\'alunno assente',
    'pei_mancante': 'Manca il PEI: niente VERIFICA e niente credito/debito',
    'pei_su_piu_titolari': 'Più titolari della stessa figura per l\'alunno negli stessi giorni, senza le ore della '
                           'coppia: ciascuno ha come previste il PEI intero (scrivi le ore di ogni coppia '
                           'nell\'anagrafica)',
    'coppia_senza_ore': 'Nessuna ora in tutto il mese',
}
# Le letture dei valori da confermare e i motivi per cui una casella non si salva.
MESSAGGI_CELLA = {
    'sigla_sconosciuta': '«{testo}» non è un numero di ore né una sigla: scrivi le ore (2, 1,5 o 1:30) oppure F, M, '
                         'P, A.',
    'ore_giorno_oltre_12': 'Più di 12 ore in un giorno non sono possibili: controlla le ore.',
    'nota_sconosciuta': 'La nota del giorno non è valida: ricarica la pagina e riprova.',
    'assente_e_parziale': 'Con l\'alunno assente (A) non si segna anche il ritardo o l\'uscita: scegli una delle due.',
    'operatore_e_parziale': 'Con l\'operatore assente (F, M o P) non serve segnare il ritardo dell\'alunno.',
    'recupero_senza_assenza': '«Assenza recuperata» vale solo per l\'alunno assente, in ritardo o uscito prima.',
    'programmati_non_validi': 'Le ore programmate vanno da 0 a 12.',
    'svolte_oltre_il_programmato': 'Con il ritardo o l\'uscita anticipata le ore svolte non possono superare quelle '
                                   'programmate: controlla le ore o le ore programmate.',
}
# Scrivendo solo nella casella, la parte della nota del giorno che non vale piu' si toglie da
# sola (_salva_una): che cosa e' stato tolto, per la pagina.
MESSAGGI_TOLTE = {
    'assente_e_parziale': 'Tolta la nota «{nota}»: con l\'alunno assente (A) non serve.',
    'operatore_e_parziale': 'Tolta la nota «{nota}»: con l\'operatore assente (F, M o P) non serve.',
    'recupero_senza_assenza': 'Tolta «Assenza recuperata»: vale solo per l\'alunno assente, in ritardo o uscito '
                              'prima.',
}
TESTI_NOTA = {
    'evento': 'Assemblea, sciopero o evento della scuola',
    'attivita_esterna': 'Uscita didattica o attività fuori dalla scuola',
    'ritardo': 'Alunno entrato in ritardo',
    'uscita_anticipata': 'Alunno uscito prima',
}
NOTE_BREVI = {'evento': 'Evento', 'attivita_esterna': 'Uscita didattica', 'ritardo': 'Entrato alle',
              'uscita_anticipata': 'Uscito alle'}


# ==================== aiuti ====================

def _mese_testo(anno, mese):
    return f'{calc.MESI[mese - 1].lower()} {anno}'


def _nome(cognome, nome):
    return f'{cognome or ""} {nome or ""}'.strip()


def _valida_mese(anno, mese):
    try:
        return calc.valida_mese(anno, mese)
    except ValueError as e:
        raise DatiNonValidi(str(e), 'mese') from None


def _chiuso(conn, lotto_id, anno, mese):
    return ndb._riga(conn, 'SELECT data_chiusura, nota FROM napoli_mesi_chiusi WHERE lotto_id = ? AND anno = ? '
                           'AND mese = ?', (lotto_id, anno, mese))


def _valida_in(riga, giorno):
    dal, al = riga.get('valido_da'), riga.get('valido_a')
    g = giorno.isoformat()
    return (not dal or dal <= g) and (not al or g <= al)


def _ore_due_forme(min_):
    return calc.ore_due_forme(min_)


def _durata_orari(orari, giorno):
    """Il programmato di un giorno dalla programmazione settimanale della coppia (None se non c'e')."""
    fasce = [o for o in orari if int(o['giorno']) == giorno.weekday() and _valida_in(o, giorno)]
    return calc.durata(fasce) if fasce else None


# ==================== lettura del mese ====================

class _Mese:
    """Tutto quello che serve per la griglia di un lotto in un mese, letto una volta."""

    def __init__(self, conn, lotto_id, anno, mese):
        self.lotto = ndb.lotto(lotto_id, conn)
        self.lotto_id, self.anno, self.mese = lotto_id, anno, mese
        self.dal = datetime.date(anno, mese, 1)
        self.al = calc.fine_mese(anno, mese)
        dal, al = self.dal.isoformat(), self.al.isoformat()
        self.oggi = ndb._oggi()
        righe_regole = ndb._righe(conn, 'SELECT * FROM napoli_regole')
        self.regole = {}
        d = self.dal
        while d <= self.al:
            self.regole[d] = calc.regole_alla_data(d, righe_regole, lotto_id)
            d += datetime.timedelta(days=1)
        self.regole_mese = self.regole[self.dal]
        self.servizio = tuple(self.regole_mese['giorni_servizio'])
        self.giorni = calc.giorni_mese(anno, mese, self.servizio)
        self.indice = {g: i for i, g in enumerate(self.giorni)}
        self.chiusura = _chiuso(conn, lotto_id, anno, mese)
        self.coppie = ndb._righe(conn, '''
            SELECT c.id, c.alunno_id, c.operatore_id, c.scuola_id, c.figura, c.ruolo, c.titolare_coppia_id,
                   c.ore_settimanali, c.valido_da, c.valido_a,
                   a.cognome AS a_cognome, a.nome AS a_nome, a.grado AS a_grado,
                   o.cognome AS o_cognome, o.nome AS o_nome,
                   s.nome AS s_nome, s.grado AS s_grado, s.municipalita AS s_municipalita
            FROM napoli_coppie c
            JOIN napoli_alunni a ON a.id = c.alunno_id
            JOIN napoli_operatori o ON o.id = c.operatore_id
            JOIN napoli_scuole s ON s.id = c.scuola_id
            WHERE c.lotto_id = ? AND ((c.valido_da <= ? AND (c.valido_a IS NULL OR c.valido_a >= ?))
                  OR c.id IN (SELECT coppia_id FROM napoli_presenze WHERE lotto_id = ? AND data BETWEEN ? AND ?))
            ORDER BY s.nome, s.municipalita, a.cognome, a.nome, c.figura, c.ruolo DESC, c.valido_da, c.id''',
            (lotto_id, al, dal, lotto_id, dal, al))
        self.presenze = {}
        for p in ndb._righe(conn, 'SELECT * FROM napoli_presenze WHERE lotto_id = ? AND data BETWEEN ? AND ?',
                            (lotto_id, dal, al)):
            self.presenze.setdefault(p['coppia_id'], {})[p['data']] = p
        self.fasce = {}
        for f in ndb._righe(conn, 'SELECT f.presenza_id, f.tipo, f.ordine, f.ora_inizio, f.ora_fine '
                                  'FROM napoli_presenze_fasce f JOIN napoli_presenze p ON p.id = f.presenza_id '
                                  'WHERE p.lotto_id = ? AND p.data BETWEEN ? AND ? ORDER BY f.ordine',
                            (lotto_id, dal, al)):
            self.fasce.setdefault(f['presenza_id'], {'P': [], 'E': []})[f['tipo']].append(f)
        self.pei = {}
        self.pei_sospesi = {}
        for r in ndb._righe(conn, 'SELECT alunno_id, figura, ore_settimanali, valido_da, valido_a, stato '
                                  'FROM napoli_pei WHERE alunno_id IN (SELECT alunno_id FROM napoli_coppie '
                                  'WHERE lotto_id = ?) AND valido_da <= ? AND (valido_a IS NULL OR valido_a >= ?) '
                                  'ORDER BY valido_da', (lotto_id, al, dal)):
            r['valido_da'] = calc.data(r['valido_da'])
            r['valido_a'] = calc.data(r['valido_a']) if r['valido_a'] else None
            dove = self.pei_sospesi if r['stato'] == 'sospeso' else self.pei
            dove.setdefault((r['alunno_id'], r['figura']), []).append(r)
        self.orari = {}
        for o in ndb._righe(conn, 'SELECT o.* FROM napoli_orari o JOIN napoli_coppie c ON c.id = o.coppia_id '
                                  'WHERE c.lotto_id = ?', (lotto_id,)):
            self.orari.setdefault(o['coppia_id'], []).append(o)
        self.chiusure_lotto, self.chiusure_scuola, self.eventi_lotto, self.eventi_scuola = {}, {}, {}, {}
        for c in ndb._righe(conn, 'SELECT * FROM napoli_calendario WHERE (lotto_id IS NULL OR lotto_id = ?) '
                                  'AND data BETWEEN ? AND ? ORDER BY lotto_id, scuola_id', (lotto_id, dal, al)):
            giorno = calc.data(c['data'])
            if c['tipo'] == 'chiusura':
                dove = self.chiusure_lotto if c['scuola_id'] is None else self.chiusure_scuola.setdefault(
                    c['scuola_id'], {})
            else:
                dove = self.eventi_lotto if c['scuola_id'] is None else self.eventi_scuola.setdefault(
                    c['scuola_id'], {})
            dove[giorno] = c['descrizione']
        # il calendario del mese non ha ancora chiusure (vacanze, seggi): la pagina avvisa nei
        # mesi con le vacanze di Natale o di Pasqua, che il calendario regionale fissa ogni anno
        self.calendario_vuoto = not self.chiusure_lotto and not self.chiusure_scuola
        # festivita' (napoli_calcoli.festivita): giorni chiusi di tutto il lotto, come le chiusure
        # del calendario (una chiusura scritta nello stesso giorno tiene la sua descrizione)
        self.festivi = {g: nome for g, nome in calc.festivita(anno).items() if g.month == mese}
        for giorno, nome in self.festivi.items():
            self.chiusure_lotto.setdefault(giorno, nome)
        self.finito = self.al <= self.oggi       # dall'ultimo giorno il mese si chiude
        # fatture definitive del mese (passo 1.9): i loro giorni, del loro grado, non cambiano
        self.definitive = ndb.fatture_definitive(conn, lotto_id, dal, al)

    def definitiva_del_giorno(self, c, giorno):
        """La fattura definitiva che contiene il giorno della coppia (per il suo grado; con il
        grado da decidere vale quella di un grado qualsiasi), oppure None."""
        grado = calc.grado_fattura(c['a_grado'] or c['s_grado'])
        g = giorno.isoformat()
        for f in self.definitive:
            if f['periodo_dal'] <= g <= f['periodo_al'] and grado in (None, f['grado']):
                return f
        return None

    def chiusura_del_giorno(self, scuola_id, giorno):
        return self.chiusure_scuola.get(scuola_id, {}).get(giorno) or self.chiusure_lotto.get(giorno)

    def colonne(self):
        out = []
        for voce, valore in calc.colonne_mese(self.anno, self.mese, self.servizio):
            if voce == 'giorno':
                out.append({'tipo': 'giorno', 'i': self.indice[valore], 'data': valore.isoformat(),
                            'numero': valore.day, 'nome': GIORNI_BREVI[valore.weekday()],
                            'chiuso': self.chiusure_lotto.get(valore), 'evento': self.eventi_lotto.get(valore),
                            'festivo': valore in self.festivi, 'futuro': valore > self.oggi})
            else:
                sett = calc.settimane_mese(self.anno, self.mese, self.servizio)[valore - 1]
                out.append({'tipo': 'verifica', 'settimana': valore, 'dal': sett[0].isoformat(),
                            'al': sett[-1].isoformat()})
        return out


def _pei_della_coppia(m, c):
    """Ore della coppia: la sua quota (ore_settimanali) se c'e', altrimenti i periodi del PEI
    dell'alunno per la figura (senza quelli sospesi)."""
    if c['ore_settimanali'] is not None:
        return calc.decimale(c['ore_settimanali'])
    return m.pei.get((c['alunno_id'], c['figura'])) or None


def _testo_pei(m, c):
    if c['ore_settimanali'] is not None:
        return calc.ore_it(calc.decimale(c['ore_settimanali']))
    periodi = m.pei.get((c['alunno_id'], c['figura'])) or []
    valori = []
    for p in periodi:
        t = calc.ore_it(calc.decimale(p['ore_settimanali']))
        if not valori or valori[-1] != t:
            valori.append(t)
    if valori:
        return ' → '.join(valori)
    return 'sospeso' if m.pei_sospesi.get((c['alunno_id'], c['figura'])) else ''


def _esito_salvato(m, p):
    """Ore riconosciute ricalcolate con le regole del giorno e avvisi di una presenza salvata."""
    fasce = m.fasce.get(p['id'], {'P': [], 'E': []})
    try:
        return calc.esito_giorno(
            fasce_p=[(f['ora_inizio'], f['ora_fine']) for f in fasce['P']],
            fasce_e=[(f['ora_inizio'], f['ora_fine']) for f in fasce['E']],
            causale=p['causale'] if p['causale'] in calc.PRECEDENZA_CAUSALI else None,
            trattamento=p['trattamento'] if p['trattamento'] in calc.TRATTAMENTI else None,
            minuti_programmati=p['minuti_programmati'], minuti_svolti=p['minuti_svolti'],
            minuti_extra=p['minuti_extra'], stato=p['stato'], calcolo=p['calcolo'],
            minuti_scritti=p['minuti_riconosciuti'] if p['calcolo'] == 'manuale' else None,
            regole=m.regole.get(calc.data(p['data'])))
    except ValueError:
        return {'minuti': p['minuti_riconosciuti'], 'formula': None, 'avvisi': []}


def _cella(m, p, chiusa):
    """Una casella per la pagina (solo le voci che servono): t testo, k tipo ('ore', 'A',
    'F', 'M', 'P', 'prog' = giorno preparato e non registrato), r minuti riconosciuti, c
    riconosciuti da mostrare nell'angolo se diversi dal testo, p programmati, nt/no/nx nota
    (tipo, orario, descrizione), rec assenza recuperata, a avvisi, bl bloccata (foglio)."""
    fasce = m.fasce.get(p['id'], {'P': [], 'E': []})
    r = int(p['minuti_riconosciuti'] or 0)
    out = {'r': r if p['stato'] == 'registrato' else 0}
    testo_r = calc.testo_ore_cella(r)
    if p['stato'] != 'registrato':
        out.update(k='prog', t='')
    elif p['sigla'] in calc.SIGLE_CELLA:
        out.update(k=calc.SIGLE_CELLA[p['sigla']], t=calc.SIGLE_CELLA[p['sigla']])
    elif p['calcolo'] == 'manuale' or p['minuti_svolti'] is None or p['minuti_svolti'] == r:
        out.update(k='ore', t=testo_r)
    else:
        out.update(k='ore', t=calc.testo_ore_cella(p['minuti_svolti']))
    if p['stato'] == 'registrato' and (out['k'] == 'A' or (out['k'] == 'ore' and testo_r != out['t'])):
        out['c'] = testo_r
    if p['minuti_programmati']:
        out['p'] = int(p['minuti_programmati'])
    tipo = p.get('nota_tipo') or calc.tipo_nota_da_causale(p['causale'])
    if tipo:
        out['nt'] = tipo
        if p.get('nota_ora'):
            out['no'] = p['nota_ora']
    if p.get('nota'):
        out['nx'] = p['nota']
    if p['trattamento'] == 'recupero':
        out['rec'] = True
    if p['origine'] == 'import_excel':
        out['o'] = 'import'
    if fasce['E']:
        out['bl'] = 'foglio'
    esito = _esito_salvato(m, p)
    avvisi = [a for a in esito['avvisi'] if a in SPIEGAZIONI or a == 'giorno_non_registrato']
    if p['stato'] == 'registrato' and esito.get('formula') is not None and esito['formula'] != r:
        if 'diverso_dalla_formula' not in avvisi:
            avvisi.append('diverso_dalla_formula')
    if p['stato'] == 'registrato':
        avvisi += [a['codice'] for a in calc.controlla_minuti_giorno(r, m.regole.get(calc.data(p['data'])))
                   if a['codice'] == 'ore_giorno_oltre_5']
    if chiusa and r:
        avvisi.append('ore_in_giorno_di_chiusura')
    if avvisi:
        out['a'] = sorted(set(avvisi))
    return out


def _righe(m, alunni=None):
    """Le righe della griglia (tutte, o solo quelle degli alunni indicati: dopo un
    salvataggio servono le righe con lo stesso alunno e figura, per la VERIFICA e il
    credito/debito)."""
    coppie = [c for c in m.coppie if alunni is None or c['alunno_id'] in alunni]
    per_id = {c['id']: c for c in coppie}
    righe = []
    gruppi = {}
    for c in coppie:
        gruppi.setdefault((c['alunno_id'], c['figura']), []).append(c)
    for c in coppie:
        presenze = m.presenze.get(c['id'], {})
        celle, fuori, chiusi, avvisi = {}, [], {}, set()
        fuori_servizio, definitiva = [], []
        for giorno in m.giorni:
            i = m.indice[giorno]
            if not _valida_in(c, giorno):
                fuori.append(i)
            if m.definitive and m.definitiva_del_giorno(c, giorno):
                definitiva.append(i)
            chiusa = m.chiusure_scuola.get(c['scuola_id'], {}).get(giorno)
            if chiusa and not m.chiusure_lotto.get(giorno):
                chiusi[str(i)] = chiusa
            p = presenze.get(giorno.isoformat())
            if p:
                cella = _cella(m, p, bool(m.chiusura_del_giorno(c['scuola_id'], giorno)))
                celle[str(i)] = cella
                avvisi.update(cella.get('a', ()))
                if cella['r'] and not _valida_in(c, giorno):
                    avvisi.add('ore_fuori_dalle_date')
        for data_testo, p in presenze.items():
            if calc.data(data_testo) not in m.indice and p['stato'] == 'registrato' and p['minuti_riconosciuti']:
                fuori_servizio.append({'data': data_testo, 'minuti': p['minuti_riconosciuti']})
                avvisi.add('ore_in_giorno_non_di_servizio')
        totale = sum(int(p['minuti_riconosciuti'] or 0) for p in presenze.values() if p['stato'] == 'registrato')
        righe.append({
            'id': c['id'], 'alunno_id': c['alunno_id'], 'operatore_id': c['operatore_id'],
            'alunno': _nome(c['a_cognome'], c['a_nome']), 'operatore': _nome(c['o_cognome'], c['o_nome']),
            'figura': c['figura'], 'figura_nome': ndb.nome_figura(c['figura']), 'ruolo': c['ruolo'],
            'sostituto': c['ruolo'] == 'sostituto', 'titolare_id': c['titolare_coppia_id'],
            'scuola_id': c['scuola_id'], 'scuola': c['s_nome'], 'municipalita': c['s_municipalita'],
            'grado': calc.grado_fattura(c['a_grado'] or c['s_grado']),
            'pei': _testo_pei(m, c), 'quota': c['ore_settimanali'] is not None,
            'dal': c['valido_da'], 'al': c['valido_a'],
            'celle': celle, 'fuori': fuori, 'chiusi': chiusi, 'fuori_servizio': fuori_servizio,
            'definitiva': definitiva,
            'totale': totale, 'totale_testo': calc.ore_brevi(totale),
            'avvisi': avvisi,
        })
    per_riga = {r['id']: r for r in righe}

    # VERIFICA per alunno e figura (titolari piu' sostituti), con i colori del gruppo
    for (alunno, figura), membri in gruppi.items():
        minuti = {}
        for c in membri:
            for data_testo, p in m.presenze.get(c['id'], {}).items():
                if p['stato'] == 'registrato':
                    minuti[data_testo] = minuti.get(data_testo, 0) + int(p['minuti_riconosciuti'] or 0)
        pei = m.pei.get((alunno, figura))
        settimane = [v for v in calc.verifica_settimane(minuti, m.anno, m.mese, pei, m.regole_mese)
                     if v['settimana'] is not None]
        for c in membri:
            riga = per_riga[c['id']]
            proprie_giorni = {}
            for data_testo, p in m.presenze.get(c['id'], {}).items():
                giorno = calc.data(data_testo)
                if p['stato'] == 'registrato' and giorno in m.indice:
                    proprie_giorni[giorno] = int(p['minuti_riconosciuti'] or 0)
            riga['settimane'] = []
            for v in settimane:
                proprie = sum(proprie_giorni.get(g, 0) for g in v['giorni'])
                voce = {'n': v['settimana'], 'minuti': proprie, 'testo': calc.ore_brevi(proprie),
                        'gruppo': v['minuti'], 'pei': v['pei_minuti'], 'tetto': v['tetto_minuti'],
                        'colore': v['colore']}
                riga['settimane'].append(voce)
                if v['codice']:
                    riga['avvisi'].add(v['codice'])
            riga['con_altri'] = len(membri) > 1
            if not pei and c['ore_settimanali'] is None and not m.orari.get(c['id']):
                riga['avvisi'].add('pei_mancante')

    # credito/debito (REGOLE 15): previste dalla programmazione o dal PEI; le ore di un
    # sostituto contano nella riga del suo titolare (se il titolare e' nel mese)
    giorni_coppia = {c['id']: [g for g in m.giorni if _valida_in(c, g) and not m.chiusura_del_giorno(c['scuola_id'], g)]
                     for c in coppie}
    for c in coppie:
        riga = per_riga[c['id']]
        giorni = giorni_coppia[c['id']]
        titolare = per_id.get(c['titolare_coppia_id']) if c['ruolo'] == 'sostituto' else None
        if titolare is not None:
            riga.update(previste=None, fonte=None, stima=False, erogate=None, credito_debito=None,
                        cd_nel_titolare=titolare['id'])
            continue
        previste = calc.minuti_previsti(giorni, m.orari.get(c['id']) or (), _pei_della_coppia(m, c), m.servizio)
        sostituti = [x['id'] for x in coppie if x['ruolo'] == 'sostituto' and x['titolare_coppia_id'] == c['id']]
        erogate = riga['totale'] + sum(per_riga[s]['totale'] for s in sostituti)
        riga.update(previste=previste['minuti'], fonte=previste['fonte'], stima=previste['stima'],
                    erogate=erogate, sostituti=sostituti,
                    credito_debito=calc.credito_debito(previste['minuti'], erogate), cd_nel_titolare=None)
    # due (o piu') titolari della stessa figura per l'alunno negli stessi giorni, con le previste
    # dal PEI intero (senza le ore della coppia): le previste si sommano due volte. Il calcolo
    # resta quello (non si sa come dividere il PEI), la riga lo segnala.
    for (alunno, figura), membri in gruppi.items():
        dal_pei = [c for c in membri if c['ruolo'] != 'sostituto' and c['ore_settimanali'] is None
                   and per_riga[c['id']].get('fonte') == 'pei']
        for k, a in enumerate(dal_pei):
            for b in dal_pei[k + 1:]:
                if set(giorni_coppia[a['id']]) & set(giorni_coppia[b['id']]):
                    per_riga[a['id']]['avvisi'].add('pei_su_piu_titolari')
                    per_riga[b['id']]['avvisi'].add('pei_su_piu_titolari')
    for riga in righe:
        riga['previste_testo'] = None if riga['previste'] is None else calc.ore_brevi(riga['previste'])
        riga['cd_testo'] = None if riga['credito_debito'] is None else calc.ore_brevi(riga['credito_debito'])
        if m.finito and not riga['totale'] and not riga['celle']:
            riga['avvisi'].add('coppia_senza_ore')
        if any(cella['k'] == 'prog' for cella in riga['celle'].values()):
            riga['avvisi'].add('giorno_non_registrato')
        riga['avvisi'] = sorted(riga['avvisi'])
    return righe


def _filtri(righe):
    scuole, operatori, municipalita, figure, gradi = {}, {}, set(), set(), set()
    for r in righe:
        scuole[r['scuola_id']] = {'id': r['scuola_id'], 'nome': r['scuola'], 'municipalita': r['municipalita']}
        operatori[r['operatore_id']] = {'id': r['operatore_id'], 'nome': r['operatore']}
        if r['municipalita'] is not None:
            municipalita.add(r['municipalita'])
        figure.add(r['figura'])
        gradi.add(r['grado'] or 'da_decidere')
    ordine_figure = [f['codice'] for f in ndb.elenco_figure()]
    return {
        'scuole': sorted(scuole.values(), key=lambda s: (s['nome'] or '', s['municipalita'] or 0)),
        'operatori': sorted(operatori.values(), key=lambda o: o['nome'].lower()),
        'municipalita': sorted(municipalita),
        'figure': [{'codice': f, 'nome': ndb.nome_figura(f)} for f in ordine_figure if f in figure],
        'gradi': [g for g in ('inferiore', 'superiore', 'da_decidere') if g in gradi],
    }


def _intestazione(m):
    return {
        'lotto': {'id': m.lotto['id'], 'nome': m.lotto['nome']},
        'anno': m.anno, 'mese': m.mese, 'testo': f'{calc.MESI[m.mese - 1]} {m.anno}',
        'dal': m.dal.isoformat(), 'al': m.al.isoformat(), 'oggi': m.oggi.isoformat(),
        'chiuso': m.chiusura is not None,
        'chiusura': ({'data': m.chiusura['data_chiusura'][:10], 'nota': m.chiusura.get('nota') or ''}
                     if m.chiusura else None),
        'finito': m.finito,
        'quota_assenza': calc.numero_it(m.regole_mese['quota_assenza_alunno']),
        'avviso_vacanze': _avviso_vacanze(m),
        # fatture definitive del mese: i loro giorni sono bloccati (righe: 'definitiva')
        'definitive': [{'testo': ndb.descrivi_fattura(f), 'grado': f['grado'], 'dal': f['periodo_dal'],
                        'al': f['periodo_al']} for f in m.definitive],
    }


def _avviso_vacanze(m):
    """Nei mesi con le vacanze di Natale o di Pasqua, finche' il calendario di Napoli del mese
    non ha chiusure: le previste del credito/debito contano anche i giorni di vacanza (le
    festivita' invece sono gia' tolte)."""
    vacanze = calc.vacanze_da_calendario(m.anno, m.mese) if m.calendario_vuoto else []
    if not vacanze:
        return None
    return (f'Le vacanze di {" e di ".join(vacanze)} non sono ancora nel calendario di Napoli: le ore previste (e '
            'il credito/debito) contano anche quei giorni. Le festività sono già tolte.')


def griglia(lotto_id, anno, mese):
    """La griglia del mese di un lotto: intestazione, colonne (giorni e VERIFICA), righe
    (una per coppia), filtri, spiegazioni degli avvisi."""
    anno, mese = _valida_mese(anno, mese)
    with db.get_db_context() as conn:
        m = _Mese(conn, lotto_id, anno, mese)
    righe = _righe(m)
    return dict(_intestazione(m), colonne=m.colonne(), giorni=[g.isoformat() for g in m.giorni], righe=righe,
                filtri=_filtri(righe), spiegazioni=SPIEGAZIONI, note=TESTI_NOTA)


# ==================== salvataggio delle caselle ====================

def _testo_attuale(p):
    """La casella com'e' adesso, scritta in modo che si rilegga uguale (per cambiare solo la nota)."""
    if p is None or p['stato'] != 'registrato':
        return ''
    if p['sigla']:
        return p['sigla']
    if p['calcolo'] == 'manuale' or p['minuti_svolti'] is None:
        return calc.hhmm(p['minuti_riconosciuti'] or 0)
    return calc.hhmm(p['minuti_svolti'])


def _leggi_programmati(valore):
    """Le ore programmate scritte nella finestra ('3', '2,5', '1:30') -> minuti."""
    lettura = calc.leggi_ore_griglia(valore)
    if lettura['esito'] == 'da_confermare':
        raise ValueError(f'«{valore}» si può leggere in due modi: scrivi 1:30 per un\'ora e mezza, oppure 1,5.')
    if lettura['esito'] != 'ore' or not 0 < lettura['minuti'] <= 720:
        raise ValueError('Le ore programmate sono un numero più di 0 e fino a 12 (per esempio 3, 2,5 o 1:30).')
    return lettura['minuti']


def _risultato(cella, esito, messaggio=None, **altro):
    out = {'coppia_id': cella['coppia_id'], 'data': cella['data'], 'esito': esito}
    if messaggio:
        out['messaggio'] = messaggio
    out.update(altro)
    return out


def _cella_richiesta(voce):
    """Coppia e data di una casella della richiesta (controllate)."""
    if not isinstance(voce, dict):
        raise DatiNonValidi('Le caselle non sono arrivate bene: ricarica la pagina e riprova.', 'celle')
    try:
        coppia_id = int(str(voce.get('coppia_id')).strip())
    except (TypeError, ValueError):
        raise DatiNonValidi('Le caselle non sono arrivate bene: ricarica la pagina e riprova.', 'celle') from None
    try:
        giorno = calc.valida_data(voce.get('data'), 'Il giorno')
    except ValueError as e:
        raise DatiNonValidi(str(e), 'celle') from None
    return coppia_id, giorno


COLONNE_SCRITTE = ('stato', 'calcolo', 'minuti_programmati', 'minuti_svolti', 'minuti_extra', 'tipo_extra',
                   'causale', 'trattamento', 'sigla', 'minuti_riconosciuti', 'nota_tipo', 'nota_ora', 'nota',
                   'testo_originale')


def salva_celle(lotto_id, dati):
    """Salva un gruppo di caselle della griglia (il salvataggio automatico, una nota del
    giorno, un incolla). dati: anno, mese, celle: [{coppia_id, data, e i campi che cambiano:
    testo, conferma ('ore_e_minuti' | 'decimale' per un valore ambiguo), programmati,
    nota_tipo, nota_ora, nota, recuperata}]. Un campo che non arriva resta com'e'.
    Le caselle che non si possono salvare tornano con il loro esito (da_confermare,
    servono_programmati, errore) e le altre si salvano lo stesso; il mese chiuso rifiuta
    tutto (409). Ritorna {'celle': esiti, 'righe': righe ricalcolate, 'messaggio', 'salvate'}."""
    anno, mese = _valida_mese(dati.get('anno'), dati.get('mese'))
    celle = dati.get('celle')
    if not isinstance(celle, list) or not celle:
        raise DatiNonValidi('Nessuna casella da salvare: ricarica la pagina e riprova.', 'celle')
    if len(celle) > MAX_CELLE:
        raise DatiNonValidi(f'Troppe caselle in una volta (al massimo {MAX_CELLE}): salva a gruppi.', 'celle')
    esiti, cambiate, alunni = [], {'nuove': 0, 'cambiate': 0, 'tolte': 0}, set()
    testo_libero = False
    with db.get_db_context() as conn:
        m = _Mese(conn, lotto_id, anno, mese)
        if m.chiusura:
            raise Conflitto(f'{calc.MESI[mese - 1]} {anno} di {m.lotto["nome"]} è chiuso: le ore non si cambiano '
                            'più. Per correggerle bisogna prima riaprire il mese.', codice='MESE_CHIUSO_LOTTO')
        coppie = {c['id']: c for c in m.coppie}
        modifiche = ndb._Modifiche(conn)
        ora = ndb._ora()
        visti = set()
        for voce in celle:
            coppia_id, giorno_testo = _cella_richiesta(voce)
            cella = {'coppia_id': coppia_id, 'data': giorno_testo}
            if (coppia_id, giorno_testo) in visti:
                raise DatiNonValidi('La stessa casella è arrivata due volte: ricarica la pagina e riprova.', 'celle')
            visti.add((coppia_id, giorno_testo))
            giorno = calc.data(giorno_testo)
            c = coppie.get(coppia_id)
            if c is None:
                esiti.append(_risultato(cella, 'errore', 'Questa coppia non è del lotto in questo mese: ricarica la '
                                                         'pagina.'))
                continue
            if (giorno.year, giorno.month) != (anno, mese):
                esiti.append(_risultato(cella, 'errore', f'Il {calc.data_it(giorno)} non è di '
                                                         f'{_mese_testo(anno, mese)}: ricarica la pagina.'))
                continue
            p = m.presenze.get(coppia_id, {}).get(giorno_testo)
            esito = _salva_una(conn, m, c, giorno, p, voce, modifiche, ora)
            esiti.append(dict(cella, **esito['risultato']))
            if esito.get('cambio'):
                cambiate[esito['cambio']] += 1
                alunni.add(c['alunno_id'])
                testo_libero = testo_libero or esito.get('testo_libero', False)
        n_cambiate = sum(cambiate.values())
        descrizione = None
        if n_cambiate:
            def quante(n, una, tante):
                return '' if not n else (f'1 {una}' if n == 1 else f'{n} {tante}')
            parti = [quante(cambiate['nuove'], 'scritta', 'scritte'), quante(cambiate['cambiate'], 'cambiata', 'cambiate'),
                     quante(cambiate['tolte'], 'cancellata', 'cancellate')]
            caselle = '1 casella' if n_cambiate == 1 else f'{n_cambiate} caselle'
            descrizione = (f'Griglia presenze di {_mese_testo(anno, mese)}: {caselle} '
                           f'({", ".join(x for x in parti if x)})')
            if testo_libero:
                ndb.registra_non_annullabile(conn, 'presenze', descrizione, ndb.MOTIVO_TESTO_LIBERO.replace(
                    'dalla scheda', 'dalla nota del giorno'))
            else:
                modifiche.salva('presenze', descrizione)
        # le righe con lo stesso alunno (VERIFICA e credito/debito cambiano anche li')
        m2 = _Mese(conn, lotto_id, anno, mese) if n_cambiate else m
    righe = _righe(m2, alunni) if alunni else []
    if descrizione:
        db.log_audit('modifica', 'napoli_presenze', None, dettagli=f'Napoli, {m.lotto["nome"]}: {descrizione}')
    da_fare = sum(1 for e in esiti if e['esito'] in ('da_confermare', 'servono_programmati', 'errore'))
    if n_cambiate:
        messaggio = f'Salvat{"a" if n_cambiate == 1 else "e"} {n_cambiate} casell{"a" if n_cambiate == 1 else "e"}'
    else:
        messaggio = 'Nessun cambiamento da salvare'
    if da_fare:
        messaggio += f'; {da_fare} da controllare'
    return {'celle': esiti, 'righe': righe, 'messaggio': messaggio, 'salvate': n_cambiate,
            'descrizione': descrizione}


def _salva_una(conn, m, c, giorno, p, voce, modifiche, ora):
    """Una casella: controlli, lettura con napoli_calcoli.giorno_da_griglia, scrittura.
    Ritorna {'risultato': {esito, messaggio, cella...}, 'cambio': 'nuove'|'cambiate'|'tolte'|None}."""
    def no(messaggio, **altro):
        return {'risultato': dict(esito='errore', messaggio=messaggio, **altro), 'cambio': None}

    regole = m.regole[giorno]
    if giorno.weekday() not in m.servizio:
        return no(f'{GIORNI_BREVI[giorno.weekday()].capitalize()} {calc.data_it(giorno)} non è un giorno di servizio.')
    if giorno > m.oggi:
        return no(f'Il {calc.data_it(giorno)} non è ancora arrivato: le ore si scrivono dal giorno stesso.',
                  codice='GIORNO_FUTURO')
    if not _valida_in(c, giorno):
        dal, al = c['valido_da'], c['valido_a']
        quando = f'dal {calc.data_it(dal)}' + (f' al {calc.data_it(al)}' if al else '')
        return no(f'La coppia vale {quando}: il {calc.data_it(giorno)} è fuori dalle sue date.',
                  codice='FUORI_DALLE_DATE')
    if p and m.fasce.get(p['id'], {}).get('E'):
        return no('Questo giorno è registrato dal foglio firma con gli orari: si cambia dal foglio della coppia.',
                  codice='DAL_FOGLIO')
    fattura = m.definitiva_del_giorno(c, giorno)
    if fattura:
        return no(f'Il {calc.data_it(giorno)} è nella fattura definitiva di {ndb.descrivi_fattura(fattura)}: le ore '
                  'non si cambiano. Se va corretta, riapri prima la fattura nella scheda Fattura.',
                  codice='FATTURA_DEFINITIVA')
    # i campi che non arrivano restano come sono
    testo = voce['testo'] if 'testo' in voce else _testo_attuale(p)
    if testo is not None and not isinstance(testo, (str, int, float)):
        return no('Il valore della casella non è valido: riscrivilo.')
    testo = '' if testo is None else str(testo).strip()
    if len(testo) > 20:
        return no('Il valore della casella è troppo lungo: scrivi le ore (2, 1,5 o 1:30) oppure F, M, P, A.')
    conferma = voce.get('conferma')
    if conferma not in (None, '', 'ore_e_minuti', 'decimale'):
        return no('La scelta non è valida: riscrivi la casella.')
    # casella svuotata (senza toccare la nota): il giorno si cancella tutto, nota del giorno
    # compresa, come dice la pagina ("vuoto = cancella"). Una nota scritta dalla sua finestra
    # su una casella vuota resta invece un giorno con 0 ore (nota_tipo arriva con la casella).
    svuotata = 'testo' in voce and testo == '' and 'nota_tipo' not in voce and 'nota' not in voce
    try:
        if svuotata:
            nota_tipo = None
        elif 'nota_tipo' in voce:
            nota_tipo = str(voce.get('nota_tipo') or '').strip() or None
            if nota_tipo is not None and nota_tipo not in calc.TIPI_NOTA_GIORNO:
                return no(MESSAGGI_CELLA['nota_sconosciuta'])
        else:
            nota_tipo = (p.get('nota_tipo') or calc.tipo_nota_da_causale(p['causale'])) if p else None
        if nota_tipo in calc.TIPI_NOTA_CON_ORA:
            ora_nota = voce.get('nota_ora') if 'nota_ora' in voce else (p.get('nota_ora') if p else None)
            if not ora_nota:
                return no(f'Scrivi a che ora l\'alunno è {"entrato" if nota_tipo == "ritardo" else "uscito"} '
                          '(per esempio 9:00).', campo='nota_ora')
            ora_nota = calc.valida_orario(ora_nota, 'L\'orario')
        else:
            ora_nota = None
        if svuotata:
            nota = None
        elif 'nota' in voce:
            nota = ndb._testo(voce, 'nota', 'La descrizione', massimo=NOTA_MAX)
            nota = import_napoli.nascondi_codici_fiscali(nota) if nota else None
        else:
            nota = p.get('nota') if p else None
        if svuotata:
            recuperata = False
        elif 'recuperata' in voce:
            recuperata = ndb._booleano(voce.get('recuperata'), False, 'recuperata')
        else:
            recuperata = bool(p and p['trattamento'] == 'recupero')
        if voce.get('programmati') not in (None, ''):
            programmati = _leggi_programmati(str(voce.get('programmati')).strip())
        elif p and p['minuti_programmati']:
            programmati = int(p['minuti_programmati'])
        else:
            programmati = _durata_orari(m.orari.get(c['id']) or [], giorno)
    except ValueError as e:
        return no(str(e))
    except DatiNonValidi as e:
        return no(e.messaggio, campo=e.campo)
    if testo == '' and nota_tipo is None and nota and 'testo' not in voce:
        return no('Per scrivere la descrizione scrivi anche le ore del giorno (anche 0) o scegli che cosa è successo.')
    esito = calc.giorno_da_griglia(testo, conferma or None, programmati, nota_tipo, recuperata, regole)
    # scrivendo solo nella casella (come in Excel), la parte della nota del giorno che con il
    # nuovo valore non vale piu' si toglie da sola, e la pagina lo dice: il ritardo o l'uscita
    # con «A» o con F, M, P; «Assenza recuperata» con le ore svolte o con l'operatore assente.
    # Ctrl+Z rimette il giorno com'era. Quello che arriva dalla finestra della nota resta com'e'.
    tolte = []
    while esito['esito'] == 'errore' and 'testo' in voce:
        if esito['codice'] in ('assente_e_parziale', 'operatore_e_parziale') and 'nota_tipo' not in voce:
            tolte.append(MESSAGGI_TOLTE[esito['codice']].format(nota=TESTI_NOTA[nota_tipo]))
            nota_tipo = ora_nota = None
        elif esito['codice'] == 'recupero_senza_assenza' and 'recuperata' not in voce and recuperata:
            tolte.append(MESSAGGI_TOLTE['recupero_senza_assenza'])
            recuperata = False
        else:
            break
        esito = calc.giorno_da_griglia(testo, conferma or None, programmati, nota_tipo, recuperata, regole)
    if esito['esito'] == 'da_confermare':
        lettura = esito['lettura']
        return {'risultato': {'esito': 'da_confermare', 'testo': testo, 'domanda': lettura.get('domanda'),
                              'alternative': [{'lettura': a['lettura'], 'minuti': a['minuti'],
                                               'testo': a['testo']} for a in lettura['alternative']]},
                'cambio': None}
    if esito['esito'] == 'servono_programmati':
        return {'risultato': {'esito': 'servono_programmati', 'testo': testo,
                              'messaggio': 'Per contare la metà servono le ore programmate di quel giorno.'},
                'cambio': None}
    if esito['esito'] == 'errore':
        if esito['codice'] == 'svolte_oltre_il_programmato' and 'nota_tipo' not in voce:
            # il ritardo o l'uscita viene dalla nota del giorno, non da quello che si e' scritto ora
            return no(f'Questo giorno ha la nota «{TESTI_NOTA[nota_tipo]}» con {calc.hhmm(programmati)} programmate: '
                      'le ore svolte non possono essere di più. Controlla le ore, oppure cambia la nota o le ore '
                      'programmate con «Nota del giorno» (Maiusc+F2).', codice=esito['codice'])
        modello = MESSAGGI_CELLA.get(esito['codice'], 'Questo valore non si può salvare: controllalo.')
        return no(modello.format(testo=testo), codice=esito['codice'])
    if esito['esito'] == 'vuoto':
        if p is None:
            return {'risultato': {'esito': 'invariata'}, 'cambio': None}
        # il giorno aveva una nota (tipo o descrizione): la pagina lo dice. Ctrl+Z rimette il
        # giorno con il tipo e l'orario della nota, ma non la descrizione libera (non resta in memoria)
        tolta_descrizione = bool(p.get('nota'))
        tolta_nota = tolta_descrizione or bool(p.get('nota_tipo') or calc.tipo_nota_da_causale(p['causale']))
        if m.fasce.get(p['id'], {}).get('P') or p['origine'] == 'programmazione':
            # giorno preparato dalla programmazione: torna "preparato", con il suo programmato
            if p['stato'] == 'programmato':
                return {'risultato': {'esito': 'invariata'}, 'cambio': None}
            modifiche.prima('presenze', p['id'])
            conn.execute('UPDATE napoli_presenze SET stato = ?, calcolo = ?, minuti_svolti = NULL, minuti_extra = 0, '
                         'tipo_extra = NULL, causale = NULL, trattamento = NULL, sigla = NULL, minuti_riconosciuti = 0, '
                         'nota_tipo = NULL, nota_ora = NULL, nota = NULL, testo_originale = NULL, '
                         "origine = 'programmazione', modificato_il = ? WHERE id = ?",
                         ('programmato', 'auto', ora, p['id']))
        else:
            modifiche.prima('presenze', p['id'])
            conn.execute('DELETE FROM napoli_presenze WHERE id = ?', (p['id'],))
        return {'risultato': {'esito': 'cancellata', 'tolta_nota': tolta_nota, 'tolta_descrizione': tolta_descrizione},
                'cambio': 'tolte'}
    originale = (testo or None) if 'testo' in voce else (p['testo_originale'] if p else None)
    campi = dict(esito['campi'], minuti_extra=0, tipo_extra=None, nota_tipo=nota_tipo, nota_ora=ora_nota, nota=nota,
                 testo_originale=originale)
    if p is not None:
        if all(_stesso(p.get(k), campi[k]) for k in COLONNE_SCRITTE if k != 'testo_originale'):
            return {'risultato': {'esito': 'invariata'}, 'cambio': None}
        modifiche.prima('presenze', p['id'])
        if not p.get('nota'):
            # senza descrizione di prima non c'e' niente di riservato da ricordare: Ctrl+Z la rimette vuota
            voce = modifiche.righe[-1]
            voce['prima']['nota'] = None
            voce['senza'] = [k for k in voce.get('senza', []) if k != 'nota']
        assegna = ', '.join(f'{k} = ?' for k in COLONNE_SCRITTE)
        conn.execute(f"UPDATE napoli_presenze SET {assegna}, origine = 'griglia', modificato_il = ? WHERE id = ?",
                     tuple(campi[k] for k in COLONNE_SCRITTE) + (ora, p['id']))
        cambio = 'cambiate'
        # una descrizione che c'era e cambia: quella di prima non resta in memoria, Ctrl+Z non la rimette
        testo_libero = bool(p.get('nota')) and not _stesso(p.get('nota'), nota)
    else:
        nomi = ', '.join(COLONNE_SCRITTE)
        cur = conn.execute(f'INSERT INTO napoli_presenze (coppia_id, lotto_id, data, figura, {nomi}, origine, '
                           f'modificato_il) VALUES (?, ?, ?, ?, {", ".join("?" * len(COLONNE_SCRITTE))}, ?, ?)',
                           (c['id'], m.lotto_id, giorno.isoformat(), c['figura'])
                           + tuple(campi[k] for k in COLONNE_SCRITTE) + ('griglia', ora))
        modifiche.nuova('presenze', cur.lastrowid)
        cambio = 'nuove'
        testo_libero = False         # una riga nuova si annulla togliendola: niente testo di prima da ricordare
    lettura = esito['lettura']
    avvisi = [a for a in lettura.get('avvisi', []) if a.startswith('letto_come') or a == 'ore_arrotondate_al_minuto']
    risultato = {'esito': 'salvata', 'minuti': campi['minuti_riconosciuti'], 'letture': avvisi}
    if tolte:
        risultato['tolte'] = tolte
    return {'risultato': risultato, 'cambio': cambio, 'testo_libero': testo_libero}


def _stesso(a, b):
    return (a if a not in ('',) else None) == (b if b not in ('',) else None)


# ==================== dettaglio di una coppia nel mese ====================

def _spiega(p, cella):
    """Come si arriva alle ore riconosciute di un giorno, con parole semplici."""
    r = int(p['minuti_riconosciuti'] or 0)
    if p['stato'] != 'registrato':
        return 'Giorno preparato ma non ancora registrato: vale 0'
    programmati, svolti = int(p['minuti_programmati'] or 0), int(p['minuti_svolti'] or 0)
    if p['calcolo'] == 'manuale':
        if p['sigla']:
            return f'Dal file Excel: {p["sigla"]}, {_ore_due_forme(r)}'
        return f'Dal file Excel: {_ore_due_forme(r)}'
    causale, tratt = p['causale'], p['trattamento']
    if causale == 'calendario':
        return 'Giorno di chiusura: 0'
    if causale in ('evento', 'attivita_esterna'):
        nome = TESTI_NOTA.get(p.get('nota_tipo') or causale, 'Evento')
        return f'{nome}: contano le ore svolte, {_ore_due_forme(svolti)}'
    if causale and causale.startswith('operatore_'):
        tipo = calc.TIPO_SIGLA.get(causale, 'assenza')
        return f'Operatore assente ({tipo}): {_ore_due_forme(r)}'
    if causale == 'alunno_assente':
        if tratt == 'recupero':
            return 'Alunno assente, assenza recuperata in un altro giorno: niente metà, 0'
        return f'Alunno assente: metà delle {calc.hhmm(programmati)} programmate = {_ore_due_forme(r)}'
    if causale == 'alunno_parziale':
        if p.get('nota_tipo') == 'uscita_anticipata':
            cosa = 'Alunno uscito prima' + (f' (alle {p["nota_ora"]})' if p.get('nota_ora') else '')
        elif p.get('nota_tipo') == 'ritardo':
            cosa = 'Alunno entrato in ritardo' + (f' (alle {p["nota_ora"]})' if p.get('nota_ora') else '')
        else:
            cosa = 'Alunno entrato in ritardo o uscito prima'
        if tratt == 'recupero':
            return f'{cosa}, parte persa recuperata: contano le ore svolte, {_ore_due_forme(svolti)}'
        persa = max(0, programmati - svolti)
        return (f'{cosa}: {calc.hhmm(svolti)} svolte + metà della parte persa ({calc.hhmm(persa)} su '
                f'{calc.hhmm(programmati)} programmate) = {_ore_due_forme(r)}')
    return f'Ore svolte: {_ore_due_forme(r)}'


def dettaglio(lotto_id, coppia_id, anno, mese):
    """Il dettaglio di una coppia nel mese: dati, giorni con la spiegazione delle ore,
    settimane con il PEI e il tetto, credito/debito con le previste."""
    anno, mese = _valida_mese(anno, mese)
    with db.get_db_context() as conn:
        m = _Mese(conn, lotto_id, anno, mese)
        coppia = next((c for c in m.coppie if c['id'] == coppia_id), None)
        if coppia is None:
            raise NonTrovato('Questa coppia non è del lotto in questo mese: ricarica la pagina.')
        foglio = ndb._riga(conn, 'SELECT stato, note, totale_scritto_min FROM napoli_fogli WHERE coppia_id = ? '
                                 'AND anno = ? AND mese = ?', (coppia_id, anno, mese))
    righe = {r['id']: r for r in _righe(m, {coppia['alunno_id']})}
    riga = righe[coppia_id]
    presenze = m.presenze.get(coppia_id, {})
    giorni = []
    for data_testo in sorted(presenze):
        p = presenze[data_testo]
        giorno = calc.data(data_testo)
        i = m.indice.get(giorno)
        cella = riga['celle'].get(str(i)) if i is not None else None
        giorni.append({
            'data': data_testo, 'giorno': f'{GIORNI_BREVI[giorno.weekday()]} {calc.data_it(giorno)}',
            'scritto': (cella or {}).get('t', p['sigla'] or ''), 'riconosciute': int(p['minuti_riconosciuti'] or 0),
            'riconosciute_testo': _ore_due_forme(int(p['minuti_riconosciuti'] or 0)),
            'spiegazione': _spiega(p, cella), 'nota_tipo': (cella or {}).get('nt'),
            'nota_testo': TESTI_NOTA.get((cella or {}).get('nt')), 'nota_ora': p.get('nota_ora'),
            'nota': p.get('nota') or '', 'avvisi': (cella or {}).get('a', []),
            'fuori_servizio': i is None,
        })
    titolare = None
    if coppia['ruolo'] == 'sostituto' and coppia['titolare_coppia_id']:
        t = next((c for c in m.coppie if c['id'] == coppia['titolare_coppia_id']), None)
        if t:
            titolare = {'id': t['id'], 'operatore': _nome(t['o_cognome'], t['o_nome'])}
    sostituti = [{'id': r['id'], 'operatore': r['operatore'], 'totale_testo': _ore_due_forme(r['totale'])}
                 for r in righe.values() if r['id'] in (riga.get('sostituti') or [])]
    altri = [{'id': r['id'], 'operatore': r['operatore'], 'ruolo': r['ruolo'],
              'totale_testo': _ore_due_forme(r['totale'])}
             for r in righe.values() if r['id'] != coppia_id and r['figura'] == coppia['figura']]
    settimane = []
    for v in riga['settimane']:
        sett = calc.settimane_mese(anno, mese, m.servizio)[v['n'] - 1]
        settimane.append(dict(v, dal=sett[0].isoformat(), al=sett[-1].isoformat(),
                              minuti_testo=_ore_due_forme(v['minuti']), gruppo_testo=_ore_due_forme(v['gruppo']),
                              pei_testo=_ore_due_forme(v['pei']) if v['pei'] is not None else None,
                              tetto_testo=_ore_due_forme(v['tetto']) if v['tetto'] is not None else None))
    giorni_validi = [g for g in m.giorni if _valida_in(coppia, g) and not m.chiusura_del_giorno(coppia['scuola_id'], g)]
    return {
        'coppia': {k: riga[k] for k in ('id', 'alunno', 'operatore', 'figura', 'figura_nome', 'ruolo', 'scuola',
                                         'municipalita', 'grado', 'pei', 'quota', 'dal', 'al', 'avvisi')},
        'mese': _intestazione(m),
        'giorni': giorni,
        'settimane': settimane,
        'totale_testo': _ore_due_forme(riga['totale']),
        'credito': {
            'previste': riga['previste'], 'erogate': riga['erogate'], 'credito_debito': riga['credito_debito'],
            'previste_testo': None if riga['previste'] is None else _ore_due_forme(riga['previste']),
            'erogate_testo': None if riga['erogate'] is None else _ore_due_forme(riga['erogate']),
            'cd_testo': riga['cd_testo'], 'fonte': riga['fonte'], 'stima': riga['stima'],
            'giorni_servizio': len(giorni_validi), 'nel_titolare': titolare,
        },
        'sostituti': sostituti,
        'altre_coppie': altri,
        'fuori_servizio': riga['fuori_servizio'],
        'foglio': ({'stato': foglio['stato'], 'note': foglio['note'] or ''} if foglio else None),
        'spiegazioni': SPIEGAZIONI,
    }


# ==================== chiusura e riapertura del mese del lotto ====================

def chiudi_mese(lotto_id, dati):
    """Chiude il mese del lotto (napoli_mesi_chiusi): da quel momento ore, note e ore del
    coordinatore del mese non si cambiano piu' (409 MESE_CHIUSO_LOTTO), nemmeno con Ctrl+Z.
    Si chiude a mese finito (dall'ultimo giorno), con le fatture del mese definitive (PROGETTO
    §9): se una fattura con ore non lo e', 409 FATTURE_NON_DEFINITIVE con l'elenco, salvo la
    conferma 'senza_fattura' ("per questi gradi la fattura non si fa adesso"). Nota facoltativa
    (codici fiscali mascherati)."""
    anno, mese = _valida_mese(dati.get('anno'), dati.get('mese'))
    senza_fattura = ndb._booleano(dati.get('senza_fattura'), False, 'senza_fattura')
    nota = ndb._testo(dati, 'nota', 'La nota', massimo=MOTIVO_MAX)
    nota = import_napoli.nascondi_codici_fiscali(nota) if nota else None
    oggi = ndb._oggi()
    testo = _mese_testo(anno, mese)
    with db.get_db_context() as conn:
        lotto = ndb.lotto(lotto_id, conn)
        if _chiuso(conn, lotto_id, anno, mese):
            raise Conflitto(f'{testo.capitalize()} di {lotto["nome"]} è già chiuso.', codice='MESE_GIA_CHIUSO')
        if oggi < calc.fine_mese(anno, mese):
            raise DatiNonValidi(f'{testo.capitalize()} non è ancora finito: il mese si chiude dall\'ultimo giorno, '
                                'quando tutte le ore sono scritte.', 'mese', codice='MESE_NON_FINITO')
        mancano = napoli_fattura.da_rendere_definitive(conn, lotto_id, anno, mese)
        if mancano and not senza_fattura:
            quante = 'una fattura con ore non è ancora definitiva' if len(mancano) == 1 else \
                f'{len(mancano)} fatture con ore non sono ancora definitive'
            raise Conflitto(f'Di {testo} {quante}: {"; ".join(mancano)}. Rendile definitive nella scheda Fattura, '
                            'oppure conferma che per ora la fattura non si fa.', codice='FATTURE_NON_DEFINITIVE',
                            fatture=mancano)
        conn.execute('INSERT INTO napoli_mesi_chiusi (lotto_id, anno, mese, data_chiusura, nota) VALUES (?, ?, ?, ?, ?)',
                     (lotto_id, anno, mese, ndb._ora(), nota))
        descrizione = f'Chiusura del mese di {testo}'
        ndb.registra_non_annullabile(conn, 'mese', descrizione,
                                     'un mese chiuso si riapre con il pulsante «Riapri il mese», scrivendo il motivo')
    db.log_audit('chiusura', 'napoli_mese', None, dettagli=f'Napoli, {lotto["nome"]}: chiuso il mese di {testo}')
    return {'messaggio': f'{testo.capitalize()} di {lotto["nome"]} è chiuso: le ore non si cambiano più'}


def riapri_mese(lotto_id, dati):
    """Riapre il mese chiuso del lotto, con il motivo (obbligatorio, resta nel registro
    attivita'; codici fiscali mascherati)."""
    anno, mese = _valida_mese(dati.get('anno'), dati.get('mese'))
    motivo = ndb._testo(dati, 'motivo', 'Il motivo', obbligatorio=True, massimo=MOTIVO_MAX,
                        manca='Scrivi perché riapri il mese: resta nel registro attività.')
    if len(motivo) < 5:
        raise DatiNonValidi('Scrivi il motivo con qualche parola in più: resta nel registro attività.', 'motivo')
    motivo = import_napoli.nascondi_codici_fiscali(motivo)
    testo = _mese_testo(anno, mese)
    with db.get_db_context() as conn:
        lotto = ndb.lotto(lotto_id, conn)
        if not _chiuso(conn, lotto_id, anno, mese):
            raise Conflitto(f'{testo.capitalize()} di {lotto["nome"]} non è chiuso.', codice='MESE_NON_CHIUSO')
        conn.execute('DELETE FROM napoli_mesi_chiusi WHERE lotto_id = ? AND anno = ? AND mese = ?',
                     (lotto_id, anno, mese))
        ndb.registra_non_annullabile(conn, 'mese', f'Riapertura del mese di {testo}',
                                     'per richiudere il mese usa il pulsante «Chiudi il mese»')
    db.log_audit('riapertura', 'napoli_mese', None,
                 dettagli=f'Napoli, {lotto["nome"]}: riaperto il mese di {testo}. Motivo: {motivo}')
    return {'messaggio': f'{testo.capitalize()} di {lotto["nome"]} è di nuovo aperto: le ore si possono cambiare'}

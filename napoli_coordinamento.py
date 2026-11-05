"""Ore del coordinatore della sezione Napoli (passo 1.8, PROGETTO §5.4 e §6, REGOLE 9 e 12).

Il coordinatore si fattura a ore, con una riga sua in ogni fattura (fattura reale di giugno
2026: "Coordinatore 71,55 ore x 29,66"). Le sue ore non vengono dai fogli firma: sono un
TOTALE MENSILE scritto a mano per lotto, grado e contratto applicativo (risposta Q4), in ore
decimali al centesimo, senza una persona obbligatoria (napoli_coordinamento, forma della
migrazione 3: l'operatore e' facoltativo e non si sceglie da qui), con una nota facoltativa.

Regole:
- una riga per mese, contratto applicativo e grado: i mesi sono quelli dei contratti del
  lotto fino al mese di oggi (le ore si scrivono a mese cominciato, REGOLE 14: da ora in
  avanti), i gradi quelli del contratto (senza grado = tutti e due);
- le ore si leggono con napoli_calcoli.leggi_ore_coordinatore: "71,55"; "71.55" vale 71,55
  e la risposta lo dice; "71,555", "71:33" e le altre scritte sono rifiutate con un
  messaggio semplice (campo 'ore'); la casella vuota toglie le ore del mese;
- un mese chiuso del lotto (napoli_mesi_chiusi) non si cambia: 409 MESE_CHIUSO_LOTTO, anche
  con Ctrl+Z (napoli_db.annulla);
- ogni scrittura passa dalla memoria di Ctrl+Z di Napoli (napoli_db._Modifiche) e dal
  registro attivita' (voce 'napoli_coordinamento', senza nomi). La nota e' un testo libero
  del lotto e del mese (non di un alunno): un codice fiscale scritto per errore si salva
  mascherato.
"""
import database as db
import import_napoli
import napoli_calcoli as calc
import napoli_db as ndb
from napoli_db import Conflitto, DatiNonValidi

NOTA_MAX = 200


def mese_testo(anno, mese):
    """'ottobre 2026' (nelle frasi)."""
    return f'{calc.MESI[mese - 1].lower()} {anno}'


def _mesi(dal, al):
    """(anno, mese) dal mese di `dal` a quello di `al`, compresi."""
    a, m = dal.year, dal.month
    while (a, m) <= (al.year, al.month):
        yield a, m
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)


def _chiuso(conn, lotto_id, anno, mese):
    return conn.execute('SELECT 1 FROM napoli_mesi_chiusi WHERE lotto_id = ? AND anno = ? AND mese = ?',
                        (lotto_id, anno, mese)).fetchone() is not None


def _descrizione(anno, mese, contratto, grado):
    """'ottobre 2026, contratto XI (grado inferiore)': senza nomi, per Ctrl+Z e il registro."""
    return f'{mese_testo(anno, mese)}, contratto {contratto["numero"]} ({ndb.NOMI_GRADO[grado]})'


def _riga(anno, mese, contratto, grado, salvata, periodo):
    """Una riga della tabella: il contratto e il grado del mese, con le ore salvate (o vuote)."""
    dal, al = periodo if periodo else (None, None)
    mese_intero = bool(periodo) and dal.day == 1 and al == calc.fine_mese(anno, mese)
    return {
        'chiave': f'{anno}-{mese:02d}-{contratto["id"]}-{grado}',
        'anno': anno, 'mese': mese, 'contratto_id': contratto['id'], 'numero': contratto['numero'],
        'grado': grado, 'grado_testo': ndb.NOMI_GRADO[grado],
        'dal': dal.isoformat() if dal else None, 'al': al.isoformat() if al else None,
        'periodo_testo': (f'dal {calc.data_it(dal)} al {calc.data_it(al)}' if periodo else
                          'fuori dalle date del contratto'),
        'mese_intero': mese_intero,
        'fuori_contratto': periodo is None,
        'id': salvata['id'] if salvata else None,
        'ore_cent': salvata['ore_cent'] if salvata else None,
        'ore': calc.numero_it(calc.decimale(salvata['ore_cent']) / 100) if salvata else '',
        'nota': (salvata.get('nota') or '') if salvata else '',
        'modificato_il': salvata.get('modificato_il') if salvata else None,
    }


def _ordine(r):
    return (r['numero'], calc.GRADI.index(r['grado']), r['contratto_id'])


def elenco(lotto_id):
    """I mesi del lotto, dal piu' recente, con le righe da compilare (contratto e grado) e le
    ore gia' salvate: {'lotto', 'oggi', 'mesi': [{anno, mese, testo, chiuso, righe}],
    'contratti', 'futuri' (contratti che cominciano dopo questo mese), 'max_ore'}."""
    oggi = ndb._oggi()
    limite = (oggi.year, oggi.month)
    with db.get_db_context() as conn:
        lotto = ndb.lotto(lotto_id, conn)
        contratti = ndb._righe(conn, 'SELECT * FROM napoli_contratti WHERE lotto_id = ? ORDER BY valido_da, grado, '
                                     'id', (lotto_id,))
        salvate = {(r['anno'], r['mese'], r['contratto_id'], r['grado']): r for r in ndb._righe(
            conn, 'SELECT * FROM napoli_coordinamento WHERE lotto_id = ?', (lotto_id,))}
        chiusi = {(r['anno'], r['mese']) for r in ndb._righe(
            conn, 'SELECT anno, mese FROM napoli_mesi_chiusi WHERE lotto_id = ?', (lotto_id,))}
    per_id = {c['id']: c for c in contratti}
    mesi = {}
    for c in contratti:
        for anno, mese in _mesi(calc.data(c['valido_da']), calc.data(c['valido_a'])):
            if (anno, mese) > limite:
                break
            periodo = calc.periodo_fattura(anno, mese, c['valido_da'], c['valido_a'])
            for grado in ([c['grado']] if c['grado'] else calc.GRADI):
                salvata = salvate.pop((anno, mese, c['id'], grado), None)
                mesi.setdefault((anno, mese), []).append(_riga(anno, mese, c, grado, salvata, periodo))
    # ore salvate che non stanno piu' in un mese del contratto (non dovrebbe succedere: le
    # Impostazioni non cambiano le date di un contratto che le lascerebbe fuori)
    for (anno, mese, contratto_id, grado), salvata in salvate.items():
        c = per_id.get(contratto_id) or {'id': contratto_id, 'numero': '?'}
        periodo = calc.periodo_fattura(anno, mese, c['valido_da'], c['valido_a']) if 'valido_da' in c else None
        mesi.setdefault((anno, mese), []).append(_riga(anno, mese, c, grado, salvata, periodo))
    fine_di_questo_mese = calc.fine_mese(*limite)
    futuri = [{'numero': c['numero'], 'grado_testo': ndb.NOMI_GRADO[c['grado']], 'dal': c['valido_da'],
               'dal_testo': calc.data_it(c['valido_da'])}
              for c in contratti if calc.data(c['valido_da']) > fine_di_questo_mese]
    return {
        'lotto': {'id': lotto['id'], 'nome': lotto['nome']},
        'oggi': oggi.isoformat(),
        'mesi': [{'anno': a, 'mese': m, 'testo': f'{calc.MESI[m - 1]} {a}', 'chiuso': (a, m) in chiusi,
                  'righe': sorted(righe, key=_ordine)}
                 for (a, m), righe in sorted(mesi.items(), reverse=True)],
        'contratti': len(contratti),
        'futuri': futuri,
        'max_ore': calc.ORE_COORDINATORE_MAX,
    }


def _intero(dati, campo, messaggio):
    valore = dati.get(campo)
    if isinstance(valore, bool):
        raise DatiNonValidi(messaggio, campo)
    try:
        return int(str(valore).strip())
    except (TypeError, ValueError):
        raise DatiNonValidi(messaggio, campo) from None


def salva(lotto_id, dati):
    """Scrive, cambia o toglie (ore vuote) le ore del coordinatore di un mese, contratto e
    grado. dati: anno, mese, contratto_id, grado e almeno uno fra 'ore' e 'nota' (un campo
    che non arriva resta com'e'). Ritorna {'riga', 'messaggio', 'lettura'}."""
    try:
        anno, mese = calc.valida_mese(dati.get('anno'), dati.get('mese'))
    except ValueError as e:
        raise DatiNonValidi(str(e), 'mese') from None
    contratto_id = _intero(dati, 'contratto_id', 'Scegli il contratto applicativo: ricarica la pagina.')
    grado = str(dati.get('grado') or '').strip().lower()
    if grado not in calc.GRADI:
        raise DatiNonValidi('Il grado è inferiore o superiore: ricarica la pagina.', 'grado')
    if 'ore' not in dati and 'nota' not in dati:
        raise DatiNonValidi('Le ore non sono arrivate: ricarica la pagina e riprova.', 'ore')
    oggi = ndb._oggi()
    with db.get_db_context() as conn:
        lotto = ndb.lotto(lotto_id, conn)
        contratto = ndb.contratto(contratto_id, conn)
        if contratto['lotto_id'] != lotto_id:
            raise DatiNonValidi('Il contratto non è di questo lotto: ricarica la pagina.', 'contratto_id')
        attuale = ndb._riga(conn, 'SELECT * FROM napoli_coordinamento WHERE lotto_id = ? AND grado = ? AND '
                                  'contratto_id = ? AND anno = ? AND mese = ?',
                            (lotto_id, grado, contratto_id, anno, mese))
        if contratto['grado'] and contratto['grado'] != grado:
            raise DatiNonValidi(f'Il contratto {contratto["numero"]} è del {ndb.NOMI_GRADO[contratto["grado"]]}: le '
                                f'ore del {ndb.NOMI_GRADO[grado]} vanno nel suo contratto.', 'grado')
        periodo = calc.periodo_fattura(anno, mese, contratto['valido_da'], contratto['valido_a'])
        if (anno, mese) > (oggi.year, oggi.month):
            raise DatiNonValidi(f'{calc.MESI[mese - 1]} {anno} non è ancora cominciato: le ore del coordinatore si '
                                'scrivono a mese cominciato.', 'mese', codice='MESE_FUTURO')
        if _chiuso(conn, lotto_id, anno, mese):
            raise Conflitto(f'{calc.MESI[mese - 1]} {anno} di {lotto["nome"]} è chiuso: le ore del coordinatore non si '
                            'cambiano più. Per correggerle bisogna prima riaprire il mese.', 'ore',
                            codice='MESE_CHIUSO_LOTTO')
        lettura = None
        if 'ore' in dati:
            try:
                ore_cent, lettura = calc.leggi_ore_coordinatore(dati.get('ore'))
            except ValueError as e:
                raise DatiNonValidi(str(e), 'ore') from None
        else:
            ore_cent = attuale['ore_cent'] if attuale else None
        if 'nota' in dati:
            nota = ndb._testo(dati, 'nota', 'La nota', massimo=NOTA_MAX)
            nota = import_napoli.nascondi_codici_fiscali(nota) if nota else None
        else:
            nota = attuale.get('nota') if attuale else None
        if periodo is None and not (attuale and ore_cent is None):
            # fuori dalle date del contratto si possono solo togliere ore rimaste di prima
            raise DatiNonValidi(f'Il contratto {contratto["numero"]} non copre {mese_testo(anno, mese)}: le ore '
                                'vanno nel contratto di quel mese.', 'mese', codice='FUORI_CONTRATTO')
        cosa = _descrizione(anno, mese, contratto, grado)
        modifiche = ndb._Modifiche(conn)
        ora = ndb._ora()
        if ore_cent is None:
            if nota:
                raise DatiNonValidi('Per salvare la nota scrivi anche le ore del mese (anche 0).', 'ore')
            if attuale is None:
                return {'riga': _riga(anno, mese, contratto, grado, None, periodo),
                        'messaggio': 'Nessun cambiamento da salvare', 'lettura': None}
            modifiche.prima('coordinamento', attuale['id'])
            conn.execute('DELETE FROM napoli_coordinamento WHERE id = ?', (attuale['id'],))
            riga_id, salvata, azione = attuale['id'], None, 'eliminazione'
            descrizione = f'Ore del coordinatore tolte: {cosa}'
            messaggio = f'Tolte le ore del coordinatore di {cosa}'
        elif attuale is None:
            cur = conn.execute('INSERT INTO napoli_coordinamento (lotto_id, grado, contratto_id, anno, mese, ore_cent, '
                               'nota, modificato_il) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                               (lotto_id, grado, contratto_id, anno, mese, ore_cent, nota, ora))
            riga_id, azione = cur.lastrowid, 'creazione'
            modifiche.nuova('coordinamento', riga_id)
            salvata = dict(id=riga_id, ore_cent=ore_cent, nota=nota, modificato_il=ora)
            descrizione = f'Ore del coordinatore: {cosa}, {calc.ore_it(calc.decimale(ore_cent) / 100)}'
            messaggio = f'Salvate le ore del coordinatore di {cosa}: {calc.ore_it(calc.decimale(ore_cent) / 100)}'
        else:
            if attuale['ore_cent'] == ore_cent and (attuale.get('nota') or None) == nota:
                return {'riga': _riga(anno, mese, contratto, grado, attuale, periodo),
                        'messaggio': 'Nessun cambiamento da salvare', 'lettura': lettura}
            modifiche.prima('coordinamento', attuale['id'])
            conn.execute('UPDATE napoli_coordinamento SET ore_cent = ?, nota = ?, modificato_il = ? WHERE id = ?',
                         (ore_cent, nota, ora, attuale['id']))
            riga_id, azione = attuale['id'], 'modifica'
            salvata = dict(attuale, ore_cent=ore_cent, nota=nota, modificato_il=ora)
            prima = calc.ore_it(calc.decimale(attuale['ore_cent']) / 100)
            dopo = calc.ore_it(calc.decimale(ore_cent) / 100)
            cambio = f'da {prima} a {dopo}' if attuale['ore_cent'] != ore_cent else 'nota cambiata'
            descrizione = f'Ore del coordinatore cambiate: {cosa}, {cambio}'
            messaggio = (f'Ore del coordinatore di {cosa}: {dopo} (prima {prima})' if attuale['ore_cent'] != ore_cent
                         else f'Nota salvata per le ore del coordinatore di {cosa}')
        modifiche.salva('coordinamento', descrizione)
    db.log_audit(azione, 'napoli_coordinamento', riga_id, dettagli=f'Napoli, {lotto["nome"]}: {descrizione}')
    return {'riga': _riga(anno, mese, contratto, grado, salvata, periodo), 'messaggio': messaggio, 'lettura': lettura}

"""Route di migrazione dati (export/import JSON) e audit log - Blueprint separato.

URL invariati (/api/migrazione/..., /api/audit ...); cambia solo l'organizzazione.
Nessuna dipendenza da helper locali di app.py.

Formato file v3.0: oltre alle 5 sezioni del formato precedente (commesse, scuole,
utenti, rendicontazione, calendario - ancora lette dai file piu' vecchi) contiene
'tabelle', cioe' TUTTE le tabelle di dominio riga per riga: variazioni monte ore,
dipendenti, assegnazioni, turni, assenze, sostituzioni, note, documenti, DD,
recuperi, override, mesi chiusi, impostazioni. Prima ne venivano esportate 5 su 20
e il "trasloco" su un altro PC perdeva in silenzio personale e variazioni.

Modalita' di importazione:
- merge   : aggiorna gli esistenti e aggiunge i nuovi (abbinamento per nome/chiave)
- skip    : aggiunge solo i nuovi, non tocca gli esistenti
- replace : svuota tutto e ricarica dal file con gli id originali (spostamento su
            un altro PC); backup automatico prima di iniziare, conferma esplicita.
"""
import io
import json
import os
from datetime import datetime

import pandas as pd
from flask import Blueprint, request, jsonify, send_file

import config
import database as db

logger = config.setup_logging()

migrazione_bp = Blueprint('migrazione', __name__)

VERSIONE_FILE = '3.0'

# Tabelle di dominio in ordine di dipendenza (i padri prima dei figli): e'
# l'ordine di inserimento del replace; per svuotare si usa l'inverso.
TABELLE_DOMINIO = [
    'commesse', 'scuole', 'utenti', 'variazioni_monte_ore', 'rendicontazione',
    'calendario_scolastico', 'dipendenti', 'assegnazioni', 'turni',
    'assenze_dipendenti', 'sostituzioni', 'note_utente', 'documenti_utente',
    'assenze', 'determine_dirigenziali', 'recuperi_ore', 'progettato_override',
    'report_override', 'mesi_chiusi', 'impostazioni',
]
# Tabelle derivate, svuotate nel replace e ricalcolate dall'app
TABELLE_DERIVATE = ['notifiche', 'undo_actions']

# Tabelle aggiuntive per merge/skip (le 5 storiche hanno una logica dedicata):
# (tabella, {colonna FK: tabella padre}, chiave naturale che identifica una riga)
TABELLE_MERGE = [
    ('dipendenti', {'commessa_id': 'commesse'}, ('nome', 'cognome', 'codice_fiscale')),
    ('variazioni_monte_ore', {'utente_id': 'utenti'}, ('utente_id', 'mese_inizio')),
    ('note_utente', {'utente_id': 'utenti'}, ('utente_id', 'data_creazione', 'contenuto')),
    ('documenti_utente', {'utente_id': 'utenti'}, ('utente_id', 'nome_file')),
    ('assenze', {'utente_id': 'utenti'}, ('utente_id', 'data_inizio', 'tipo')),
    ('assegnazioni', {'utente_id': 'utenti', 'dipendente_id': 'dipendenti'},
     ('utente_id', 'dipendente_id', 'valido_da')),
    ('turni', {'dipendente_id': 'dipendenti', 'scuola_id': 'scuole', 'utente_id': 'utenti'},
     ('dipendente_id', 'giorno', 'ora_inizio', 'ora_fine', 'valido_da')),
    ('assenze_dipendenti', {'dipendente_id': 'dipendenti'}, ('dipendente_id', 'data_inizio', 'data_fine')),
    ('sostituzioni', {'turno_id': 'turni', 'assente_id': 'dipendenti', 'sostituto_id': 'dipendenti',
                      'assenza_id': 'assenze_dipendenti'}, ('turno_id', 'data', 'assente_id')),
    ('determine_dirigenziali', {'commessa_id': 'commesse'},
     ('commessa_id', 'anno_scolastico', 'mese_inizio', 'anno_inizio', 'numero_dd')),
    ('recuperi_ore', {'commessa_id': 'commesse'},
     ('commessa_id', 'anno_scolastico', 'mese', 'anno', 'ore_recupero')),
    ('progettato_override', {'commessa_id': 'commesse'}, ('commessa_id', 'anno_scolastico', 'mese', 'anno')),
    ('report_override', {'commessa_id': 'commesse'}, ('commessa_id', 'anno_scolastico', 'mese', 'anno', 'campo')),
    ('mesi_chiusi', {}, ('anno', 'mese')),
    ('impostazioni', {}, ('chiave',)),
]
# FK facoltative (NULL ammesso): se il padre non e' mappabile la riga entra con
# NULL; per le altre FK la riga senza padre viene saltata.
FK_FACOLTATIVE = {('dipendenti', 'commessa_id'), ('turni', 'scuola_id'), ('turni', 'utente_id'),
                  ('sostituzioni', 'turno_id'), ('sostituzioni', 'sostituto_id'),
                  ('sostituzioni', 'assenza_id')}


def _versione_app():
    try:
        with open(os.path.join(config.BASE_DIR, 'VERSION'), encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return None


def _colonne(cursor, tabella):
    return [r[1] for r in cursor.execute(f'PRAGMA table_info({tabella})').fetchall()]


def _righe(cursor, tabella):
    return [dict(r) for r in cursor.execute(f'SELECT * FROM {tabella}').fetchall()]


@migrazione_bp.route('/api/migrazione/esporta')
def api_migrazione_esporta():
    """Esporta TUTTI i dati di dominio in JSON (v3.0), mantenendo anche le 5
    sezioni del formato precedente per compatibilita' con le vecchie versioni."""
    try:
        data = {
            'versione': VERSIONE_FILE,
            'versione_app': _versione_app(),
            'data_esportazione': datetime.now().isoformat(),
            'commesse': [],
            'scuole': [],
            'utenti': [],
            'rendicontazione': [],
            'calendario': [],
            'tabelle': {},
        }

        with db.get_db_context() as conn:
            cursor = conn.cursor()

            cursor.execute('SELECT * FROM commesse')
            for row in cursor.fetchall():
                data['commesse'].append({
                    'id': row['id'], 'nome': row['nome'], 'descrizione': row['descrizione'],
                    'colore': row['colore'], 'attiva': row['attiva'], 'data_creazione': row['data_creazione']
                })

            cursor.execute('''
                SELECT s.*, c.nome as commessa_nome
                FROM scuole s JOIN commesse c ON s.commessa_id = c.id
            ''')
            for row in cursor.fetchall():
                data['scuole'].append({
                    'id': row['id'], 'commessa_id': row['commessa_id'],
                    'commessa_nome': row['commessa_nome'], 'nome_completo': row['nome_completo']
                })

            cursor.execute('''
                SELECT u.*, s.nome_completo as scuola_nome, c.nome as commessa_nome
                FROM utenti u
                JOIN scuole s ON u.scuola_id = s.id
                JOIN commesse c ON s.commessa_id = c.id
            ''')
            for row in cursor.fetchall():
                r = dict(row)
                data['utenti'].append({
                    'id': r['id'], 'scuola_id': r['scuola_id'], 'scuola_nome': r['scuola_nome'],
                    'commessa_nome': r['commessa_nome'], 'nome': r['nome'], 'cognome': r['cognome'],
                    'nome_puntato': r['nome_puntato'], 'monte_ore_settimanale': r['monte_ore_settimanale'],
                    'lista_attesa': r.get('lista_attesa'), 'lista_attesa_as': r.get('lista_attesa_as'),
                    'attivo': r['attivo'], 'archiviato_dal': r.get('archiviato_dal'),
                    'data_inizio': r.get('data_inizio'), 'data_fine': r.get('data_fine'),
                    'budget_ore_mensile': r.get('budget_ore_mensile'),
                    'budget_ore_annuale': r.get('budget_ore_annuale'),
                    'data_inserimento': r['data_inserimento']
                })

            cursor.execute('''
                SELECT r.*, u.nome as utente_nome, u.cognome as utente_cognome
                FROM rendicontazione r JOIN utenti u ON r.utente_id = u.id
            ''')
            for row in cursor.fetchall():
                data['rendicontazione'].append({
                    'id': row['id'], 'utente_id': row['utente_id'],
                    'utente_nome': row['utente_nome'], 'utente_cognome': row['utente_cognome'],
                    'anno': row['anno'], 'mese': row['mese'],
                    'ore_lavorate_60': row['ore_lavorate_60'], 'pasti': row['pasti'],
                    'giorni_lavorativi': row['giorni_lavorativi'], 'note': row['note'],
                    'data_inserimento': row['data_inserimento'], 'data_modifica': row['data_modifica']
                })

            cursor.execute('SELECT * FROM calendario_scolastico')
            for row in cursor.fetchall():
                data['calendario'].append({
                    'anno_scolastico': row['anno_scolastico'], 'mese': row['mese'], 'anno': row['anno'],
                    'giorni_lavorativi': row['giorni_lavorativi'],
                    'giorni_lavorativi_altri': row['giorni_lavorativi_altri']
                })

            # Tutte le tabelle di dominio, riga per riga (formato completo)
            for tabella in TABELLE_DOMINIO:
                data['tabelle'][tabella] = _righe(cursor, tabella)

        output = io.BytesIO()
        output.write(json.dumps(data, indent=2, ensure_ascii=False, default=str).encode('utf-8'))
        output.seek(0)
        filename = f"gestionale_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        return send_file(output, mimetype='application/json', as_attachment=True, download_name=filename)

    except Exception as e:
        logger.error(f"Errore esportazione: {e}", exc_info=True)
        return jsonify({'error': 'Errore interno del server'}), 500


def _leggi_file_json():
    """Legge e valida il file JSON caricato; ritorna (data, errore, status)."""
    if 'file' not in request.files:
        return None, 'Nessun file caricato', 400
    file = request.files['file']
    if not file.filename.lower().endswith('.json'):
        return None, 'Il file deve essere in formato JSON', 400
    try:
        data = json.load(file)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, 'File JSON non valido', 400
    if not isinstance(data, dict) or 'versione' not in data:
        return None, 'File non valido: versione mancante', 400
    return data, None, None


def _importa_replace(tabelle):
    """Svuota le tabelle di dominio e le ricarica dal file con gli id originali,
    in UNA transazione (se qualcosa fallisce non resta nulla a meta'). Le colonne
    sconosciute (file di una versione piu' nuova) vengono ignorate, quelle
    mancanti prendono il default della tabella."""
    stats = {}
    with db.get_db_context() as conn:
        cursor = conn.cursor()
        for tabella in TABELLE_DERIVATE + list(reversed(TABELLE_DOMINIO)):
            cursor.execute(f'DELETE FROM {tabella}')
        for tabella in TABELLE_DOMINIO:
            righe = tabelle.get(tabella) or []
            colonne = set(_colonne(cursor, tabella))
            n = 0
            for riga in righe:
                cols = [c for c in riga.keys() if c in colonne]
                if not cols:
                    continue
                cursor.execute(
                    f"INSERT INTO {tabella} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                    [riga[c] for c in cols])
                n += 1
            stats[tabella] = n
        # File di versioni senza l'anno delle liste d'attesa: lo si ricava dai dati
        db.completa_anno_liste_attesa(cursor)
    return stats


def _merge_tabella(cursor, tabella, fks, chiave, righe, mappe, mode):
    """Importa una tabella aggiuntiva rimappando le chiavi esterne con gli id
    gia' assegnati ai padri; riconosce le righe gia' presenti dalla chiave
    naturale (merge = aggiorna, skip = lascia)."""
    colonne = set(_colonne(cursor, tabella))
    ha_id = 'id' in colonne
    mappa = mappe.setdefault(tabella, {})
    importati = aggiornati = saltati = 0

    for riga in righe:
        r = {k: v for k, v in riga.items() if k in colonne and k != 'id'}
        ok = True
        for col, padre in fks.items():
            if r.get(col) is None:
                continue
            nuovo = mappe.get(padre, {}).get(r[col])
            if nuovo is None:
                if (tabella, col) in FK_FACOLTATIVE:
                    r[col] = None
                else:
                    ok = False
                    break
            else:
                r[col] = nuovo
        if not ok:
            saltati += 1
            continue

        cond = [c for c in chiave if c in colonne]
        where = ' AND '.join(f"{c} IS ?" for c in cond)
        valori_chiave = [r.get(c) for c in cond]
        esistente = cursor.execute(
            f"SELECT {'id' if ha_id else '1'} FROM {tabella} WHERE {where}", valori_chiave).fetchone()

        if esistente:
            if ha_id and 'id' in riga:
                mappa[riga['id']] = esistente[0]
            if mode == 'merge':
                upd = {k: v for k, v in r.items() if k not in cond}
                if upd:
                    set_sql = ', '.join(f'{k} = ?' for k in upd)
                    if ha_id:
                        cursor.execute(f"UPDATE {tabella} SET {set_sql} WHERE id = ?",
                                       list(upd.values()) + [esistente[0]])
                    else:
                        cursor.execute(f"UPDATE {tabella} SET {set_sql} WHERE {where}",
                                       list(upd.values()) + valori_chiave)
                aggiornati += 1
            else:
                saltati += 1
            continue

        cursor.execute(f"INSERT INTO {tabella} ({', '.join(r)}) VALUES ({', '.join('?' * len(r))})",
                       list(r.values()))
        if ha_id and 'id' in riga:
            mappa[riga['id']] = cursor.lastrowid
        importati += 1

    return {'importati': importati, 'aggiornati': aggiornati, 'saltati': saltati}


# Campi dell'utente che "Unisci" copia dal file SOLO se il file li contiene: un
# file della versione precedente (formato 2.0) non ha date di servizio, budget ne'
# anno della lista d'attesa, e prima li azzerava su tutti gli utenti.
CAMPI_UTENTE_DAL_FILE = ('monte_ore_settimanale', 'lista_attesa', 'data_inizio', 'data_fine',
                         'budget_ore_mensile', 'budget_ore_annuale')


def _aggiorna_utente_da_file(cursor, utente_id, u):
    """Aggiorna un utente gia' presente con i soli campi presenti nel file."""
    assegnazioni, valori = [], []
    for campo in CAMPI_UTENTE_DAL_FILE:
        if campo in u:
            assegnazioni.append(f'{campo} = ?')
            valori.append(u[campo])
    if 'attivo' in u:
        attivo = 0 if u['attivo'] in (0, False, '0') else 1
        # archiviato_dal: NULL se attivo; da un file senza il mese
        # dell'archiviazione (versione vecchia) resta quello gia' presente
        assegnazioni.append('attivo = ?')
        assegnazioni.append('archiviato_dal = CASE WHEN ? THEN NULL ELSE COALESCE(?, archiviato_dal) END')
        valori += [attivo, attivo, u.get('archiviato_dal')]
    if assegnazioni:
        cursor.execute(f"UPDATE utenti SET {', '.join(assegnazioni)} WHERE id = ?", valori + [utente_id])


def _riga_ore_diversa(esistente, r):
    """True se la riga del file cambierebbe ore, pasti, giorni o note di quella salvata."""
    def num(v):
        return round(float(v or 0), 4)
    return (num(esistente['ore_lavorate_60']) != num(r.get('ore_lavorate_60'))
            or num(esistente['pasti']) != num(r.get('pasti', 0))
            or num(esistente['giorni_lavorativi']) != num(r.get('giorni_lavorativi'))
            or (esistente['note'] or '') != (r.get('note') or ''))


def _importa_merge(data, mode):
    """Unisce (merge) o aggiunge solo i nuovi (skip): le 5 sezioni storiche con
    abbinamento per nome, poi le tabelle aggiuntive del formato completo."""
    aggiorna = mode == 'merge'
    stats = {
        'commesse': {'importate': 0, 'aggiornate': 0},
        'scuole': {'importate': 0, 'aggiornate': 0},
        'utenti': {'importati': 0, 'aggiornati': 0},
        'rendicontazione': {'importate': 0, 'aggiornate': 0},
        'calendario': {'importati': 0, 'aggiornati': 0},
    }
    commesse_map, scuole_map, utenti_map = {}, {}, {}
    mesi_saltati = set()

    with db.get_db_context() as conn:
        cursor = conn.cursor()

        # 1. Commesse
        for c in data.get('commesse', []):
            cursor.execute('SELECT id FROM commesse WHERE nome = ?', (c['nome'],))
            existing = cursor.fetchone()
            if existing:
                commesse_map[c['id']] = existing['id']
                if aggiorna:
                    cursor.execute('UPDATE commesse SET descrizione = ?, colore = ?, attiva = ? WHERE id = ?',
                                   (c.get('descrizione'), c.get('colore', '#6366f1'),
                                    c.get('attiva', 1), existing['id']))
                    stats['commesse']['aggiornate'] += 1
            else:
                cursor.execute('''INSERT INTO commesse (nome, descrizione, colore, attiva, data_creazione)
                                  VALUES (?, ?, ?, ?, ?)''',
                               (c['nome'], c.get('descrizione'), c.get('colore', '#6366f1'),
                                c.get('attiva', 1), c.get('data_creazione', datetime.now().isoformat())))
                commesse_map[c['id']] = cursor.lastrowid
                stats['commesse']['importate'] += 1

        # 2. Scuole
        for s in data.get('scuole', []):
            new_commessa_id = commesse_map.get(s['commessa_id'])
            if not new_commessa_id:
                cursor.execute('SELECT id FROM commesse WHERE nome = ?', (s.get('commessa_nome', ''),))
                row = cursor.fetchone()
                new_commessa_id = row['id'] if row else None
            if not new_commessa_id:
                continue
            cursor.execute('SELECT id FROM scuole WHERE commessa_id = ? AND nome_completo = ?',
                           (new_commessa_id, s['nome_completo']))
            existing = cursor.fetchone()
            if existing:
                scuole_map[s['id']] = existing['id']
                stats['scuole']['aggiornate'] += 1
            else:
                cursor.execute('INSERT INTO scuole (commessa_id, nome_completo) VALUES (?, ?)',
                               (new_commessa_id, s['nome_completo']))
                scuole_map[s['id']] = cursor.lastrowid
                stats['scuole']['importate'] += 1

        # Etichette lista d'attesa prima dell'import (vedi 4b)
        liste_prima = {r[0]: r[1] for r in cursor.execute('SELECT id, lista_attesa FROM utenti').fetchall()}

        # 3. Utenti
        for u in data.get('utenti', []):
            new_scuola_id = scuole_map.get(u['scuola_id'])
            if not new_scuola_id:
                cursor.execute('''SELECT s.id FROM scuole s JOIN commesse c ON s.commessa_id = c.id
                                  WHERE s.nome_completo = ? AND c.nome = ?''',
                               (u.get('scuola_nome', ''), u.get('commessa_nome', '')))
                row = cursor.fetchone()
                new_scuola_id = row['id'] if row else None
            if not new_scuola_id:
                continue
            cursor.execute('''SELECT id FROM utenti WHERE scuola_id = ?
                              AND nome = ? COLLATE NOCASE AND cognome = ? COLLATE NOCASE''',
                           (new_scuola_id, u['nome'], u.get('cognome') or ''))
            existing = cursor.fetchone()
            if existing:
                utenti_map[u['id']] = existing['id']
                if aggiorna:
                    _aggiorna_utente_da_file(cursor, existing['id'], u)
                    stats['utenti']['aggiornati'] += 1
            else:
                nome_puntato = u.get('nome_puntato') or db.punteggia_nome(u['nome'], u.get('cognome') or '')
                cursor.execute('''INSERT INTO utenti (scuola_id, nome, cognome, nome_puntato,
                                      monte_ore_settimanale, lista_attesa, attivo, archiviato_dal,
                                      data_inizio, data_fine,
                                      budget_ore_mensile, budget_ore_annuale, data_inserimento)
                                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                               (new_scuola_id, u['nome'], u.get('cognome') or '', nome_puntato,
                                u['monte_ore_settimanale'], u.get('lista_attesa'), u.get('attivo', 1),
                                None if u.get('attivo', 1) else u.get('archiviato_dal'),
                                u.get('data_inizio'), u.get('data_fine'), u.get('budget_ore_mensile'),
                                u.get('budget_ore_annuale'), u.get('data_inserimento', datetime.now().isoformat())))
                utenti_map[u['id']] = cursor.lastrowid
                stats['utenti']['importati'] += 1

        # 4. Rendicontazione. Un mese chiuso non accetta ore nemmeno da qui (come
        # da import Excel e a mano): le righe che lo cambierebbero sono saltate e
        # riportate nell'esito; quelle uguali a quanto gia' salvato non contano.
        mesi_chiusi = {(m[0], m[1]) for m in cursor.execute('SELECT anno, mese FROM mesi_chiusi').fetchall()}
        stats['rendicontazione']['saltate_mese_chiuso'] = 0
        for r in data.get('rendicontazione', []):
            new_utente_id = utenti_map.get(r['utente_id'])
            if not new_utente_id:
                cursor.execute('SELECT id FROM utenti WHERE nome = ? AND cognome = ?',
                               (r.get('utente_nome', ''), r.get('utente_cognome', '')))
                row = cursor.fetchone()
                new_utente_id = row['id'] if row else None
            if not new_utente_id:
                continue
            cursor.execute('''SELECT id, ore_lavorate_60, pasti, giorni_lavorativi, note FROM rendicontazione
                              WHERE utente_id = ? AND anno = ? AND mese = ?''',
                           (new_utente_id, r['anno'], r['mese']))
            existing = cursor.fetchone()
            if (r['anno'], r['mese']) in mesi_chiusi:
                if not existing or (aggiorna and _riga_ore_diversa(existing, r)):
                    stats['rendicontazione']['saltate_mese_chiuso'] += 1
                    mesi_saltati.add((r['anno'], r['mese']))
                continue
            if existing:
                if aggiorna:
                    cursor.execute('''UPDATE rendicontazione
                                      SET ore_lavorate_60 = ?, pasti = ?, giorni_lavorativi = ?,
                                          note = ?, data_modifica = ?
                                      WHERE id = ?''',
                                   (r['ore_lavorate_60'], r.get('pasti', 0), r['giorni_lavorativi'],
                                    r.get('note'), datetime.now().isoformat(), existing['id']))
                    stats['rendicontazione']['aggiornate'] += 1
            else:
                cursor.execute('''INSERT INTO rendicontazione (utente_id, anno, mese, ore_lavorate_60,
                                      pasti, giorni_lavorativi, note, data_inserimento)
                                  VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                               (new_utente_id, r['anno'], r['mese'], r['ore_lavorate_60'],
                                r.get('pasti', 0), r['giorni_lavorativi'], r.get('note'),
                                r.get('data_inserimento', datetime.now().isoformat())))
                stats['rendicontazione']['importate'] += 1

        # 4b. Anno scolastico delle liste d'attesa degli utenti del file: quello del
        # file se c'e' (versioni nuove), altrimenti ricavato dalle ore appena
        # importate (ultimo mese con una riga), come per i DB delle versioni vecchie
        for u in data.get('utenti', []):
            nuovo_id = utenti_map.get(u['id'])
            if not nuovo_id:
                continue
            attuale = cursor.execute('SELECT lista_attesa FROM utenti WHERE id = ?', (nuovo_id,)).fetchone()[0]
            if u.get('lista_attesa_as') and (attuale or '').strip() and attuale == u.get('lista_attesa'):
                cursor.execute('UPDATE utenti SET lista_attesa_as = ? WHERE id = ?', (u['lista_attesa_as'], nuovo_id))
            elif attuale != liste_prima.get(nuovo_id):
                # etichetta nuova o cambiata dal file, senza anno: si ricava dai dati
                cursor.execute('UPDATE utenti SET lista_attesa_as = NULL WHERE id = ?', (nuovo_id,))
        db.completa_anno_liste_attesa(cursor, utenti_map.values())

        # 5. Calendario
        for cal in data.get('calendario', []):
            cursor.execute('''SELECT id FROM calendario_scolastico
                              WHERE anno_scolastico = ? AND mese = ? AND anno = ?''',
                           (cal['anno_scolastico'], cal['mese'], cal['anno']))
            existing = cursor.fetchone()
            if existing:
                if aggiorna:
                    cursor.execute('''UPDATE calendario_scolastico
                                      SET giorni_lavorativi = ?, giorni_lavorativi_altri = ? WHERE id = ?''',
                                   (cal['giorni_lavorativi'], cal.get('giorni_lavorativi_altri'), existing['id']))
                    stats['calendario']['aggiornati'] += 1
            else:
                cursor.execute('''INSERT INTO calendario_scolastico
                                      (anno_scolastico, mese, anno, giorni_lavorativi, giorni_lavorativi_altri)
                                  VALUES (?, ?, ?, ?, ?)''',
                               (cal['anno_scolastico'], cal['mese'], cal['anno'],
                                cal['giorni_lavorativi'], cal.get('giorni_lavorativi_altri')))
                stats['calendario']['importati'] += 1

        # 6. Tabelle aggiuntive (solo formato completo v3.0)
        tabelle = data.get('tabelle') or {}
        if tabelle:
            mappe = {'commesse': commesse_map, 'scuole': scuole_map, 'utenti': utenti_map}
            for tabella, fks, chiave in TABELLE_MERGE:
                righe = tabelle.get(tabella) or []
                if righe:
                    stats[tabella] = _merge_tabella(cursor, tabella, fks, chiave, righe, mappe, mode)

    return stats, sorted(mesi_saltati)


def _totali(stats):
    importati = sum(v for s in stats.values() for k, v in s.items() if k.startswith('importat'))
    aggiornati = sum(v for s in stats.values() for k, v in s.items() if k.startswith('aggiornat'))
    return importati, aggiornati


@migrazione_bp.route('/api/migrazione/importa', methods=['POST'])
def api_migrazione_importa():
    """Importa dati da file JSON di migrazione (mode: merge | skip | replace)"""
    data, errore, status = _leggi_file_json()
    if errore:
        return jsonify({'error': errore}), status
    nome_file = request.files['file'].filename

    mode = (request.form.get('mode') or 'merge').strip()
    if mode not in ('merge', 'skip', 'replace'):
        return jsonify({'error': "Modalita' non valida (merge, skip o replace)"}), 400

    if mode == 'replace':
        if not data.get('tabelle'):
            return jsonify({'error': "Il file e' di una versione precedente e non contiene tutte le tabelle: "
                                     "usa la modalita' Unisci"}), 400
        if (request.form.get('confirm') or '').strip() != 'SOSTITUISCI':
            return jsonify({'error': 'Per sostituire tutti i dati serve la conferma esplicita'}), 400
        backup = db.create_backup()
        try:
            stats = _importa_replace(data['tabelle'])
        except Exception as e:
            logger.error(f"Errore sostituzione dati: {e}", exc_info=True)
            return jsonify({'error': 'Sostituzione annullata: nessuna modifica applicata'}), 500
        db.log_audit('migrazione', 'sistema',
                     dettagli=f'Sostituiti tutti i dati da {nome_file} (backup precedente: {backup})')
        totale = sum(stats.values())
        return jsonify({'success': True, 'mode': mode, 'stats': stats, 'backup': backup,
                        'totale_importati': totale, 'totale_aggiornati': 0})

    try:
        stats, mesi_saltati = _importa_merge(data, mode)
    except Exception as e:
        logger.error(f"Errore importazione: {e}", exc_info=True)
        return jsonify({'error': 'Importazione annullata: nessuna modifica applicata'}), 500

    avvisi = []
    saltate = stats['rendicontazione']['saltate_mese_chiuso']
    if mesi_saltati:
        elenco = ', '.join(f"{config.MESI_NOME[m]} {a}" for a, m in mesi_saltati)
        if saltate == 1:
            righe, cambiarle = '1 riga di ore NON è stata scritta', 'cambiarla'
        else:
            righe, cambiarle = f'{saltate} righe di ore NON sono state scritte', 'cambiarle'
        if len(mesi_saltati) == 1:
            chiusi, riapri = 'il mese è chiuso', 'riapri il mese'
        else:
            chiusi, riapri = 'i mesi sono chiusi', 'riapri i mesi'
        avvisi.append(f"{righe} perché {chiusi} ({elenco}). Per {cambiarle} {riapri} da Chiusura Mese "
                      "e ripeti l'importazione.")
    db.log_audit('migrazione', 'sistema', dettagli=f'Importati dati da {nome_file} ({mode})'
                 + (f"; saltat{'a 1 riga' if saltate == 1 else f'e {saltate} righe'} di mesi chiusi"
                    if mesi_saltati else ''))
    importati, aggiornati = _totali(stats)
    return jsonify({'success': True, 'mode': mode, 'stats': stats, 'avvisi': avvisi,
                    'mesi_chiusi_saltati': [{'anno': a, 'mese': m} for a, m in mesi_saltati],
                    'totale_importati': importati, 'totale_aggiornati': aggiornati})


CONSIGLIO_AGGIORNAMENTO = (
    "Per passare a questa versione da una versione precedente NON usare questo file: chiudi il "
    "programma e copia il file gestionale.db della cartella vecchia nella cartella nuova, prima "
    "di avviarla (vedi il README, \"Aggiornare a una nuova versione\"). Così passano tutti i dati."
)


def _dati_mancanti_nel_file(data):
    """Elenco (in italiano) dei dati che un file di formato precedente (2.0, senza
    'tabelle') non contiene e che quindi non arriverebbero con l'importazione."""
    if data.get('tabelle'):
        return []
    mancanti = ['determine dirigenziali (DD)', 'recuperi ore', 'correzioni fatte a mano nei report']
    utenti = data.get('utenti') or []
    if utenti and not any('data_inizio' in u or 'data_fine' in u for u in utenti):
        mancanti.append('date di inizio e fine servizio degli utenti')
    mancanti += ['variazioni del monte ore', 'personale, assegnazioni e turni', 'note e documenti degli utenti',
                 'mesi chiusi', 'storico delle modifiche (registro attività)']
    return mancanti


@migrazione_bp.route('/api/migrazione/anteprima', methods=['POST'])
def api_migrazione_anteprima():
    """Anteprima dati da importare senza modificare il database"""
    data, errore, status = _leggi_file_json()
    if errore:
        return jsonify({'error': errore}), status

    tabelle = data.get('tabelle') or {}
    mancanti = _dati_mancanti_nel_file(data)
    return jsonify({
        'success': True,
        'versione': data.get('versione'),
        'versione_app': data.get('versione_app'),
        'data_esportazione': data.get('data_esportazione'),
        'completo': bool(tabelle),
        # file della versione precedente: cosa NON contiene e come aggiornare davvero
        'mancanti': mancanti,
        'consiglio': CONSIGLIO_AGGIORNAMENTO if mancanti else None,
        'riepilogo': {
            'commesse': len(data.get('commesse', [])),
            'scuole': len(data.get('scuole', [])),
            'utenti': len(data.get('utenti', [])),
            'rendicontazione': len(data.get('rendicontazione', [])),
            'calendario': len(data.get('calendario', [])),
        },
        'tabelle': {t: len(r or []) for t, r in tabelle.items()},
        'anteprima': {
            'commesse': [c['nome'] for c in data.get('commesse', [])[:5]],
            'scuole': [s['nome_completo'][:50] for s in data.get('scuole', [])[:5]],
            'utenti': [f"{u.get('cognome') or ''} {u['nome']}".strip() for u in data.get('utenti', [])[:5]]
        }
    })


# ==================== AUDIT TRAIL API ====================

@migrazione_bp.route('/api/audit', methods=['GET'])
def api_get_audit():
    """Ottiene l'audit trail"""
    limit = request.args.get('limit', 100, type=int)
    entita = request.args.get('entita')
    audit = db.get_audit_log(limit=min(limit, 500), entita=entita)
    return jsonify(audit)


@migrazione_bp.route('/api/audit/export')
def api_audit_export():
    """Esporta l'audit trail in Excel"""
    limit = request.args.get('limit', 500, type=int)
    entita = request.args.get('entita')
    audit = db.get_audit_log(limit=min(limit, 5000), entita=entita)

    output = io.BytesIO()
    rows = []
    for a in audit:
        rows.append({
            'Data/Ora': a.get('timestamp', ''),
            'Azione': a.get('azione', ''),
            'Entita': a.get('entita', ''),
            'ID Entita': a.get('entita_id', ''),
            'Dettagli': a.get('dettagli', ''),
            'Dati Precedenti': a.get('dati_precedenti', ''),
            'Dati Nuovi': a.get('dati_nuovi', '')
        })

    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=['Data/Ora', 'Azione', 'Entita', 'ID Entita', 'Dettagli'])
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Audit Trail', index=False)
        ws = writer.sheets['Audit Trail']
        ws.set_column('A:A', 20)
        ws.set_column('B:C', 15)
        ws.set_column('D:D', 10)
        ws.set_column('E:G', 40)

    output.seek(0)
    filename = f"audit_trail_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )

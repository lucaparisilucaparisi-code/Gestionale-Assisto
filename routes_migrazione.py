"""Route di migrazione dati (export/import JSON) e audit log - Blueprint separato.

URL invariati (/api/migrazione/..., /api/audit ...); cambia solo l'organizzazione.
Nessuna dipendenza da helper locali di app.py.
"""
import io
import json
from datetime import datetime

import pandas as pd
from flask import Blueprint, request, jsonify, send_file

import config
import database as db

logger = config.setup_logging()

migrazione_bp = Blueprint('migrazione', __name__)


@migrazione_bp.route('/api/migrazione/esporta')
def api_migrazione_esporta():
    """Esporta tutti i dati del database in formato JSON per migrazione"""
    try:
        data = {
            'versione': '2.0',
            'data_esportazione': datetime.now().isoformat(),
            'commesse': [],
            'scuole': [],
            'utenti': [],
            'rendicontazione': [],
            'calendario': []
        }

        with db.get_db_context() as conn:
            cursor = conn.cursor()

            # Esporta commesse
            cursor.execute('SELECT * FROM commesse')
            for row in cursor.fetchall():
                data['commesse'].append({
                    'id': row['id'],
                    'nome': row['nome'],
                    'descrizione': row['descrizione'],
                    'colore': row['colore'],
                    'attiva': row['attiva'],
                    'data_creazione': row['data_creazione']
                })

            # Esporta scuole
            cursor.execute('''
                SELECT s.*, c.nome as commessa_nome
                FROM scuole s
                JOIN commesse c ON s.commessa_id = c.id
            ''')
            for row in cursor.fetchall():
                data['scuole'].append({
                    'id': row['id'],
                    'commessa_id': row['commessa_id'],
                    'commessa_nome': row['commessa_nome'],
                    'nome_completo': row['nome_completo']
                })

            # Esporta utenti
            cursor.execute('''
                SELECT u.*, s.nome_completo as scuola_nome, c.nome as commessa_nome
                FROM utenti u
                JOIN scuole s ON u.scuola_id = s.id
                JOIN commesse c ON s.commessa_id = c.id
            ''')
            for row in cursor.fetchall():
                data['utenti'].append({
                    'id': row['id'],
                    'scuola_id': row['scuola_id'],
                    'scuola_nome': row['scuola_nome'],
                    'commessa_nome': row['commessa_nome'],
                    'nome': row['nome'],
                    'cognome': row['cognome'],
                    'nome_puntato': row['nome_puntato'],
                    'monte_ore_settimanale': row['monte_ore_settimanale'],
                    'lista_attesa': row['lista_attesa'],
                    'attivo': row['attivo'],
                    'data_inserimento': row['data_inserimento']
                })

            # Esporta rendicontazione
            cursor.execute('''
                SELECT r.*, u.nome as utente_nome, u.cognome as utente_cognome
                FROM rendicontazione r
                JOIN utenti u ON r.utente_id = u.id
            ''')
            for row in cursor.fetchall():
                data['rendicontazione'].append({
                    'id': row['id'],
                    'utente_id': row['utente_id'],
                    'utente_nome': row['utente_nome'],
                    'utente_cognome': row['utente_cognome'],
                    'anno': row['anno'],
                    'mese': row['mese'],
                    'ore_lavorate_60': row['ore_lavorate_60'],
                    'pasti': row['pasti'],
                    'giorni_lavorativi': row['giorni_lavorativi'],
                    'note': row['note'],
                    'data_inserimento': row['data_inserimento'],
                    'data_modifica': row['data_modifica']
                })

            # Esporta calendario
            cursor.execute('SELECT * FROM calendario_scolastico')
            for row in cursor.fetchall():
                data['calendario'].append({
                    'anno_scolastico': row['anno_scolastico'],
                    'mese': row['mese'],
                    'anno': row['anno'],
                    'giorni_lavorativi': row['giorni_lavorativi'],
                    'giorni_lavorativi_altri': row['giorni_lavorativi_altri']
                })

        # Crea file JSON
        output = io.BytesIO()
        output.write(json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8'))
        output.seek(0)

        filename = f"gestionale_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        return send_file(
            output,
            mimetype='application/json',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        logger.error(f"Errore esportazione: {e}")
        return jsonify({'error': str(e)}), 500


@migrazione_bp.route('/api/migrazione/importa', methods=['POST'])
def api_migrazione_importa():
    """Importa dati da file JSON di migrazione"""
    if 'file' not in request.files:
        return jsonify({'error': 'Nessun file caricato'}), 400

    file = request.files['file']
    if not file.filename.endswith('.json'):
        return jsonify({'error': 'Il file deve essere in formato JSON'}), 400

    mode = request.form.get('mode', 'merge')  # 'merge' o 'replace'

    try:
        data = json.load(file)

        if 'versione' not in data:
            return jsonify({'error': 'File non valido: versione mancante'}), 400

        stats = {
            'commesse': {'importate': 0, 'aggiornate': 0},
            'scuole': {'importate': 0, 'aggiornate': 0},
            'utenti': {'importati': 0, 'aggiornati': 0},
            'rendicontazione': {'importate': 0, 'aggiornate': 0},
            'calendario': {'importati': 0, 'aggiornati': 0}
        }

        # Mappa vecchi ID -> nuovi ID
        commesse_map = {}
        scuole_map = {}
        utenti_map = {}

        with db.get_db_context() as conn:
            cursor = conn.cursor()

            # 1. Importa commesse
            for c in data.get('commesse', []):
                cursor.execute('SELECT id FROM commesse WHERE nome = ?', (c['nome'],))
                existing = cursor.fetchone()
                if existing:
                    commesse_map[c['id']] = existing['id']
                    if mode == 'merge':
                        cursor.execute('''
                            UPDATE commesse SET descrizione = ?, colore = ?, attiva = ?
                            WHERE id = ?
                        ''', (c.get('descrizione'), c.get('colore', '#6366f1'),
                              c.get('attiva', 1), existing['id']))
                        stats['commesse']['aggiornate'] += 1
                else:
                    cursor.execute('''
                        INSERT INTO commesse (nome, descrizione, colore, attiva, data_creazione)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (c['nome'], c.get('descrizione'), c.get('colore', '#6366f1'),
                          c.get('attiva', 1), c.get('data_creazione', datetime.now().isoformat())))
                    commesse_map[c['id']] = cursor.lastrowid
                    stats['commesse']['importate'] += 1

            # 2. Importa scuole
            for s in data.get('scuole', []):
                new_commessa_id = commesse_map.get(s['commessa_id'])
                if not new_commessa_id:
                    # Cerca per nome commessa
                    cursor.execute('SELECT id FROM commesse WHERE nome = ?', (s.get('commessa_nome', ''),))
                    row = cursor.fetchone()
                    new_commessa_id = row['id'] if row else None

                if new_commessa_id:
                    cursor.execute('''
                        SELECT id FROM scuole WHERE commessa_id = ? AND nome_completo = ?
                    ''', (new_commessa_id, s['nome_completo']))
                    existing = cursor.fetchone()
                    if existing:
                        scuole_map[s['id']] = existing['id']
                        stats['scuole']['aggiornate'] += 1
                    else:
                        cursor.execute('''
                            INSERT INTO scuole (commessa_id, nome_completo) VALUES (?, ?)
                        ''', (new_commessa_id, s['nome_completo']))
                        scuole_map[s['id']] = cursor.lastrowid
                        stats['scuole']['importate'] += 1

            # 3. Importa utenti
            for u in data.get('utenti', []):
                new_scuola_id = scuole_map.get(u['scuola_id'])
                if not new_scuola_id:
                    # Cerca per nome scuola e commessa
                    cursor.execute('''
                        SELECT s.id FROM scuole s
                        JOIN commesse c ON s.commessa_id = c.id
                        WHERE s.nome_completo = ? AND c.nome = ?
                    ''', (u.get('scuola_nome', ''), u.get('commessa_nome', '')))
                    row = cursor.fetchone()
                    new_scuola_id = row['id'] if row else None

                if new_scuola_id:
                    cursor.execute('''
                        SELECT id FROM utenti WHERE scuola_id = ? AND nome = ? AND cognome = ?
                    ''', (new_scuola_id, u['nome'], u['cognome']))
                    existing = cursor.fetchone()
                    if existing:
                        utenti_map[u['id']] = existing['id']
                        if mode == 'merge':
                            cursor.execute('''
                                UPDATE utenti SET monte_ore_settimanale = ?, lista_attesa = ?, attivo = ?
                                WHERE id = ?
                            ''', (u['monte_ore_settimanale'], u.get('lista_attesa'),
                                  u.get('attivo', 1), existing['id']))
                        stats['utenti']['aggiornati'] += 1
                    else:
                        nome_puntato = u.get('nome_puntato') or f"{u['cognome']} {u['nome'][0]}."
                        cursor.execute('''
                            INSERT INTO utenti (scuola_id, nome, cognome, nome_puntato,
                                              monte_ore_settimanale, lista_attesa, attivo, data_inserimento)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (new_scuola_id, u['nome'], u['cognome'], nome_puntato,
                              u['monte_ore_settimanale'], u.get('lista_attesa'),
                              u.get('attivo', 1), u.get('data_inserimento', datetime.now().isoformat())))
                        utenti_map[u['id']] = cursor.lastrowid
                        stats['utenti']['importati'] += 1

            # 4. Importa rendicontazione
            for r in data.get('rendicontazione', []):
                new_utente_id = utenti_map.get(r['utente_id'])
                if not new_utente_id:
                    # Cerca per nome utente
                    cursor.execute('''
                        SELECT id FROM utenti WHERE nome = ? AND cognome = ?
                    ''', (r.get('utente_nome', ''), r.get('utente_cognome', '')))
                    row = cursor.fetchone()
                    new_utente_id = row['id'] if row else None

                if new_utente_id:
                    cursor.execute('''
                        SELECT id FROM rendicontazione WHERE utente_id = ? AND anno = ? AND mese = ?
                    ''', (new_utente_id, r['anno'], r['mese']))
                    existing = cursor.fetchone()
                    if existing:
                        if mode == 'merge':
                            cursor.execute('''
                                UPDATE rendicontazione
                                SET ore_lavorate_60 = ?, pasti = ?, giorni_lavorativi = ?,
                                    note = ?, data_modifica = ?
                                WHERE id = ?
                            ''', (r['ore_lavorate_60'], r.get('pasti', 0), r['giorni_lavorativi'],
                                  r.get('note'), datetime.now().isoformat(), existing['id']))
                        stats['rendicontazione']['aggiornate'] += 1
                    else:
                        cursor.execute('''
                            INSERT INTO rendicontazione (utente_id, anno, mese, ore_lavorate_60,
                                                        pasti, giorni_lavorativi, note, data_inserimento)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (new_utente_id, r['anno'], r['mese'], r['ore_lavorate_60'],
                              r.get('pasti', 0), r['giorni_lavorativi'], r.get('note'),
                              r.get('data_inserimento', datetime.now().isoformat())))
                        stats['rendicontazione']['importate'] += 1

            # 5. Importa calendario
            for cal in data.get('calendario', []):
                cursor.execute('''
                    SELECT id FROM calendario_scolastico
                    WHERE anno_scolastico = ? AND mese = ? AND anno = ?
                ''', (cal['anno_scolastico'], cal['mese'], cal['anno']))
                existing = cursor.fetchone()
                if existing:
                    if mode == 'merge':
                        cursor.execute('''
                            UPDATE calendario_scolastico
                            SET giorni_lavorativi = ?, giorni_lavorativi_altri = ?
                            WHERE id = ?
                        ''', (cal['giorni_lavorativi'], cal.get('giorni_lavorativi_altri'), existing['id']))
                    stats['calendario']['aggiornati'] += 1
                else:
                    cursor.execute('''
                        INSERT INTO calendario_scolastico
                            (anno_scolastico, mese, anno, giorni_lavorativi, giorni_lavorativi_altri)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (cal['anno_scolastico'], cal['mese'], cal['anno'],
                          cal['giorni_lavorativi'], cal.get('giorni_lavorativi_altri')))
                    stats['calendario']['importati'] += 1

        db.log_audit('migrazione', 'sistema', dettagli=f'Importati dati da {file.filename}')

        return jsonify({
            'success': True,
            'stats': stats,
            'totale_importati': (
                stats['commesse']['importate'] + stats['scuole']['importate'] +
                stats['utenti']['importati'] + stats['rendicontazione']['importate']
            ),
            'totale_aggiornati': (
                stats['commesse']['aggiornate'] + stats['scuole']['aggiornate'] +
                stats['utenti']['aggiornati'] + stats['rendicontazione']['aggiornate']
            )
        })

    except json.JSONDecodeError:
        return jsonify({'error': 'File JSON non valido'}), 400
    except Exception as e:
        logger.error(f"Errore importazione: {e}")
        return jsonify({'error': str(e)}), 500


@migrazione_bp.route('/api/migrazione/anteprima', methods=['POST'])
def api_migrazione_anteprima():
    """Anteprima dati da importare senza modificare il database"""
    if 'file' not in request.files:
        return jsonify({'error': 'Nessun file caricato'}), 400

    file = request.files['file']
    if not file.filename.endswith('.json'):
        return jsonify({'error': 'Il file deve essere in formato JSON'}), 400

    try:
        data = json.load(file)

        if 'versione' not in data:
            return jsonify({'error': 'File non valido: versione mancante'}), 400

        return jsonify({
            'success': True,
            'versione': data.get('versione'),
            'data_esportazione': data.get('data_esportazione'),
            'riepilogo': {
                'commesse': len(data.get('commesse', [])),
                'scuole': len(data.get('scuole', [])),
                'utenti': len(data.get('utenti', [])),
                'rendicontazione': len(data.get('rendicontazione', [])),
                'calendario': len(data.get('calendario', []))
            },
            'anteprima': {
                'commesse': [c['nome'] for c in data.get('commesse', [])[:5]],
                'scuole': [s['nome_completo'][:50] for s in data.get('scuole', [])[:5]],
                'utenti': [f"{u['cognome']} {u['nome']}" for u in data.get('utenti', [])[:5]]
            }
        })

    except json.JSONDecodeError:
        return jsonify({'error': 'File JSON non valido'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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

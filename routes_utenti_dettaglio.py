"""Route di dettaglio utente: documenti, note, assenze, budget ore, notifiche,
storico e report per utente - Blueprint separato da app.py.

URL e nomi funzione invariati. Endpoint API (nessun url_for verso di essi).
"""
import os

from flask import Blueprint, request, jsonify, send_file

import config
import database as db
from validators import validate_string

utenti_dettaglio_bp = Blueprint('utenti_dettaglio', __name__)


@utenti_dettaglio_bp.route('/api/utente/<int:utente_id>/documenti')
def api_get_documenti_utente(utente_id):
    """Ottiene tutti i documenti di un utente"""
    try:
        documenti = db.get_documenti_utente(utente_id)
        return jsonify({'documenti': documenti})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/utente/<int:utente_id>/documenti', methods=['POST'])
def api_upload_documento(utente_id):
    """Carica un documento per un utente"""
    if 'file' not in request.files:
        return jsonify({'error': 'Nessun file caricato'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Nessun file selezionato'}), 400

    try:
        # Validazione input
        tipo_documento, err = validate_string(request.form.get('tipo'), 'Tipo documento', max_length=50)
        if err:
            return jsonify({'error': err}), 400

        descrizione = request.form.get('descrizione', '')
        data_scadenza = request.form.get('data_scadenza')

        # Genera nome file univoco
        import uuid
        ext = os.path.splitext(file.filename)[1]
        nome_file = f"{utente_id}_{uuid.uuid4().hex}{ext}"

        # Cartella documenti
        docs_folder = os.path.join(config.UPLOAD_FOLDER, 'documenti')
        os.makedirs(docs_folder, exist_ok=True)

        filepath = os.path.join(docs_folder, nome_file)
        file.save(filepath)

        # Salva nel database
        doc_id = db.add_documento_utente(
            utente_id=utente_id,
            nome_file=nome_file,
            nome_originale=file.filename,
            tipo_documento=tipo_documento,
            descrizione=descrizione,
            data_scadenza=data_scadenza if data_scadenza else None,
            dimensione=os.path.getsize(filepath)
        )

        db.log_audit('upload', 'documento', doc_id,
                     f'Documento caricato: {file.filename} per utente {utente_id}')

        return jsonify({'success': True, 'id': doc_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/documento/<int:documento_id>')
def api_download_documento(documento_id):
    """Scarica un documento"""
    try:
        with db.get_db_context() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM documenti_utente WHERE id = ?', (documento_id,))
            doc = cursor.fetchone()

        if not doc:
            return jsonify({'error': 'Documento non trovato'}), 404

        docs_folder = os.path.join(config.UPLOAD_FOLDER, 'documenti')
        filepath = os.path.join(docs_folder, doc['nome_file'])

        if not os.path.exists(filepath):
            return jsonify({'error': 'File non trovato'}), 404

        return send_file(filepath, as_attachment=True, download_name=doc['nome_originale'])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/documento/<int:documento_id>', methods=['DELETE'])
def api_delete_documento(documento_id):
    """Elimina un documento"""
    try:
        nome_file = db.delete_documento_utente(documento_id)
        if nome_file:
            # Elimina anche il file fisico
            docs_folder = os.path.join(config.UPLOAD_FOLDER, 'documenti')
            filepath = os.path.join(docs_folder, nome_file)
            if os.path.exists(filepath):
                os.remove(filepath)

        db.log_audit('delete', 'documento', documento_id, 'Documento eliminato')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/documenti/scadenza')
def api_documenti_scadenza():
    """Ottiene i documenti in scadenza"""
    try:
        giorni = request.args.get('giorni', 30, type=int)
        documenti = db.get_documenti_in_scadenza(giorni)
        scaduti = db.get_documenti_scaduti()
        return jsonify({
            'in_scadenza': documenti,
            'scaduti': scaduti
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== API NOTE UTENTE ====================

@utenti_dettaglio_bp.route('/api/utente/<int:utente_id>/note')
def api_get_note_utente(utente_id):
    """Ottiene le note di un utente"""
    try:
        tipo = request.args.get('tipo')
        note = db.get_note_utente(utente_id, tipo)
        return jsonify({'note': note})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/utente/<int:utente_id>/note', methods=['POST'])
def api_add_nota_utente(utente_id):
    """Aggiunge una nota per un utente"""
    try:
        data = request.get_json()
        contenuto, err = validate_string(data.get('contenuto'), 'Contenuto', max_length=2000)
        if err:
            return jsonify({'error': err}), 400

        tipo = data.get('tipo', 'generale')
        priorita = data.get('priorita', 'normale')
        anno = data.get('anno')
        mese = data.get('mese')

        nota_id = db.add_nota_utente(utente_id, contenuto, tipo, priorita, anno, mese)
        db.log_audit('create', 'nota', nota_id, f'Nota aggiunta per utente {utente_id}')

        return jsonify({'success': True, 'id': nota_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/nota/<int:nota_id>', methods=['PUT'])
def api_update_nota(nota_id):
    """Aggiorna una nota"""
    try:
        data = request.get_json()
        contenuto = data.get('contenuto')
        priorita = data.get('priorita')

        if contenuto:
            contenuto, err = validate_string(contenuto, 'Contenuto', max_length=2000)
            if err:
                return jsonify({'error': err}), 400

        db.update_nota_utente(nota_id, contenuto, priorita)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/nota/<int:nota_id>', methods=['DELETE'])
def api_delete_nota(nota_id):
    """Elimina una nota"""
    try:
        db.delete_nota_utente(nota_id)
        db.log_audit('delete', 'nota', nota_id, 'Nota eliminata')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/utente/<int:utente_id>/note/mensili/<int:anno>/<int:mese>')
def api_get_note_mensili(utente_id, anno, mese):
    """Ottiene le note mensili di un utente"""
    try:
        note = db.get_note_mensili(utente_id, anno, mese)
        return jsonify({'note': note})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== API ASSENZE ====================

@utenti_dettaglio_bp.route('/api/utente/<int:utente_id>/assenze')
def api_get_assenze_utente(utente_id):
    """Ottiene le assenze di un utente"""
    try:
        anno = request.args.get('anno', type=int)
        assenze = db.get_assenze_utente(utente_id, anno)
        return jsonify({'assenze': assenze})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/utente/<int:utente_id>/assenze', methods=['POST'])
def api_add_assenza(utente_id):
    """Registra un'assenza"""
    try:
        data = request.get_json()

        data_inizio, err = validate_string(data.get('data_inizio'), 'Data inizio')
        if err:
            return jsonify({'error': err}), 400

        tipo, err = validate_string(data.get('tipo'), 'Tipo assenza', max_length=50)
        if err:
            return jsonify({'error': err}), 400

        assenza_id = db.add_assenza(
            utente_id=utente_id,
            data_inizio=data_inizio,
            tipo=tipo,
            data_fine=data.get('data_fine'),
            motivazione=data.get('motivazione'),
            note=data.get('note')
        )

        db.log_audit('create', 'assenza', assenza_id, f'Assenza registrata per utente {utente_id}')
        return jsonify({'success': True, 'id': assenza_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/assenza/<int:assenza_id>', methods=['PUT'])
def api_update_assenza(assenza_id):
    """Aggiorna un'assenza"""
    try:
        data = request.get_json()
        db.update_assenza(
            assenza_id,
            data_inizio=data.get('data_inizio'),
            data_fine=data.get('data_fine'),
            tipo=data.get('tipo'),
            motivazione=data.get('motivazione'),
            note=data.get('note')
        )
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/assenza/<int:assenza_id>', methods=['DELETE'])
def api_delete_assenza(assenza_id):
    """Elimina un'assenza"""
    try:
        db.delete_assenza(assenza_id)
        db.log_audit('delete', 'assenza', assenza_id, 'Assenza eliminata')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/assenze/periodo')
def api_assenze_periodo():
    """Ottiene le assenze in un periodo"""
    try:
        data_inizio = request.args.get('data_inizio')
        data_fine = request.args.get('data_fine')
        if not data_inizio or not data_fine:
            return jsonify({'error': 'Specificare data_inizio e data_fine'}), 400

        assenze = db.get_assenze_periodo(data_inizio, data_fine)
        return jsonify({'assenze': assenze})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/assenze/report/<int:anno>')
def api_report_assenze(anno):
    """Report assenze per anno"""
    try:
        mese = request.args.get('mese', type=int)
        commessa = request.args.get('commessa')
        report = db.get_report_assenze(anno, mese, commessa)
        return jsonify({'report': report})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== API BUDGET ORE ====================

@utenti_dettaglio_bp.route('/api/utente/<int:utente_id>/budget', methods=['PUT'])
def api_update_budget_utente(utente_id):
    """Aggiorna il budget ore di un utente"""
    try:
        data = request.get_json()
        db.update_budget_utente(
            utente_id,
            budget_mensile=data.get('budget_mensile'),
            budget_annuale=data.get('budget_annuale')
        )
        db.log_audit('update', 'budget', utente_id, 'Budget aggiornato')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/utente/<int:utente_id>/budget/<anno_scolastico>')
def api_get_budget_status(utente_id, anno_scolastico):
    """Ottiene lo stato del budget di un utente"""
    try:
        status = db.get_budget_status_utente(utente_id, anno_scolastico)
        if not status:
            return jsonify({'error': 'Utente non trovato'}), 404
        return jsonify(status)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/budget/critici/<anno_scolastico>')
def api_get_budget_critici(anno_scolastico):
    """Ottiene utenti con budget critico"""
    try:
        soglia = request.args.get('soglia', 80, type=int)
        utenti = db.get_utenti_budget_critico(anno_scolastico, soglia)
        return jsonify({'utenti': utenti})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== API NOTIFICHE ====================

@utenti_dettaglio_bp.route('/api/notifiche')
def api_get_notifiche():
    """Ottiene le notifiche"""
    try:
        solo_non_lette = request.args.get('tutte') != '1'
        limit = request.args.get('limit', 50, type=int)
        notifiche = db.get_notifiche(solo_non_lette, limit)
        count = db.count_notifiche_non_lette()
        return jsonify({'notifiche': notifiche, 'non_lette': count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/notifiche/<int:notifica_id>/letta', methods=['POST'])
def api_mark_notifica_letta(notifica_id):
    """Segna una notifica come letta"""
    try:
        db.mark_notifica_letta(notifica_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/notifiche/lette', methods=['POST'])
def api_mark_all_notifiche_lette():
    """Segna tutte le notifiche come lette"""
    try:
        db.mark_all_notifiche_lette()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/notifiche/<int:notifica_id>/archivia', methods=['POST'])
def api_archivia_notifica(notifica_id):
    """Archivia una notifica"""
    try:
        db.archivia_notifica(notifica_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/notifiche/genera', methods=['POST'])
def api_genera_notifiche():
    """Genera notifiche automatiche"""
    try:
        notifiche_ids = db.genera_notifiche_automatiche()
        return jsonify({'success': True, 'generate': len(notifiche_ids)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== API STORICO E REPORT UTENTI ====================

@utenti_dettaglio_bp.route('/api/utente/<int:utente_id>/storico-ore')
def api_get_storico_utente(utente_id):
    """Storico ore di un utente per ANNO SCOLASTICO (Set-Giu), con totali.
    Usato dalla pagina di dettaglio utente.

    NB: esiste un endpoint distinto e complementare `/storico` (api_storico_utente):
      - /storico-ore  -> filtra per anno scolastico, ritorna {storico, totali}
      - /storico      -> ultimi N mesi a ritroso, calcola media/credito-debito per riga
    I due servono casi d'uso diversi e non vanno unificati."""
    try:
        anno_scolastico = request.args.get('anno_scolastico')
        storico = db.get_storico_ore_utente(utente_id, anno_scolastico)
        totali = db.get_totali_utente(utente_id, anno_scolastico)
        return jsonify({'storico': storico, 'totali': totali})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/utente/<int:utente_id>/andamento')
def api_get_andamento_utente(utente_id):
    """Ottiene l'andamento ore di un utente"""
    try:
        mesi = request.args.get('mesi', 12, type=int)
        andamento = db.get_andamento_utente(utente_id, mesi)
        return jsonify({'andamento': andamento})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/utenti/classifica/<int:anno>')
def api_classifica_utenti(anno):
    """Classifica utenti per ore"""
    try:
        mese = request.args.get('mese', type=int)
        limit = request.args.get('limit', 20, type=int)
        order = request.args.get('order', 'desc')
        classifica = db.get_classifica_utenti_ore(anno, mese, limit, order)
        return jsonify({'classifica': classifica})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@utenti_dettaglio_bp.route('/api/utenti/confronto/<anno_scolastico>')
def api_confronto_utenti(anno_scolastico):
    """Confronta ore tra utenti"""
    try:
        utente_ids = request.args.get('ids', '')
        if not utente_ids:
            return jsonify({'error': 'Specificare IDs utenti'}), 400

        ids = [int(x) for x in utente_ids.split(',')]
        confronto = db.get_confronto_utenti(ids, anno_scolastico)
        return jsonify({'confronto': confronto})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== API DETTAGLIO UTENTE COMPLETO ====================

@utenti_dettaglio_bp.route('/api/utente/<int:utente_id>/dettaglio')
def api_get_utente_dettaglio(utente_id):
    """Ottiene tutti i dettagli di un utente (anagrafica, documenti, note, assenze, storico)"""
    try:
        utente = db.get_utente_by_id(utente_id)
        if not utente:
            return jsonify({'error': 'Utente non trovato'}), 404

        anno_scolastico = request.args.get('anno_scolastico', '2025-2026')

        documenti = db.get_documenti_utente(utente_id)
        note = db.get_note_utente(utente_id)
        assenze = db.get_assenze_utente(utente_id)
        storico = db.get_storico_ore_utente(utente_id, anno_scolastico)
        totali = db.get_totali_utente(utente_id, anno_scolastico)
        budget_status = db.get_budget_status_utente(utente_id, anno_scolastico)

        return jsonify({
            'utente': utente,
            'documenti': documenti,
            'note': note,
            'assenze': assenze,
            'storico': storico,
            'totali': totali,
            'budget': budget_status
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

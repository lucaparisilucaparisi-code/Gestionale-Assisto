"""Route di reportistica locale (Direttore Dipartimento), recuperi e override
del progettato/report - Blueprint separato da app.py.

URL e nomi funzione invariati. Usa database, validators e Flask.
"""

from flask import Blueprint, request, jsonify, render_template

import config
import database as db
from validators import validate_number, validate_integer

logger = config.setup_logging()

report_locale_bp = Blueprint('report_locale', __name__)


@report_locale_bp.route('/reportistica-locale')
def page_reportistica_locale():
    """Pagina reportistica locale per commessa"""
    return render_template('reportistica_locale.html')


@report_locale_bp.route('/api/reportistica-locale/<int:commessa_id>/<anno_scolastico>')
def api_report_locale(commessa_id, anno_scolastico):
    """API per ottenere il report locale di una commessa"""
    try:
        report = db.get_report_locale_commessa(commessa_id, anno_scolastico)
        commessa = db.get_commessa_by_id(commessa_id)
        report['commessa_nome'] = commessa['nome'] if commessa else 'Sconosciuta'
        return jsonify(report)
    except Exception as e:
        logger.error(f"Errore report locale: {e}")
        return jsonify({'error': str(e)}), 500


@report_locale_bp.route('/api/dd/<int:commessa_id>/<anno_scolastico>', methods=['GET'])
def api_get_dd(commessa_id, anno_scolastico):
    """Ottiene le DD per una commessa"""
    dd_list = db.get_dd_by_commessa(commessa_id, anno_scolastico)
    return jsonify(dd_list)


@report_locale_bp.route('/api/dd', methods=['POST'])
def api_add_dd():
    """Aggiunge una nuova DD"""
    data = request.json

    # Validazione
    commessa_id, err = validate_integer(data.get('commessa_id'), 'Commessa', min_val=1)
    if err:
        return jsonify({'error': err}), 400

    mese_inizio, err = validate_integer(data.get('mese_inizio'), 'Mese inizio', min_val=1, max_val=12)
    if err:
        return jsonify({'error': err}), 400

    anno_inizio, err = validate_integer(data.get('anno_inizio'), 'Anno inizio', min_val=2020, max_val=2100)
    if err:
        return jsonify({'error': err}), 400

    ore_settimanali, err = validate_number(data.get('ore_settimanali'), 'Ore settimanali', min_val=0)
    if err:
        return jsonify({'error': err}), 400

    ore_annuali, err = validate_number(data.get('ore_annuali'), 'Ore annuali', min_val=0)
    if err:
        return jsonify({'error': err}), 400

    anno_scolastico = data.get('anno_scolastico', '')
    if not anno_scolastico:
        return jsonify({'error': 'Anno scolastico obbligatorio'}), 400

    try:
        dd_id = db.add_dd(
            commessa_id=commessa_id,
            anno_scolastico=anno_scolastico,
            mese_inizio=mese_inizio,
            anno_inizio=anno_inizio,
            ore_settimanali=ore_settimanali,
            ore_annuali=ore_annuali,
            numero_dd=data.get('numero_dd'),
            data_dd=data.get('data_dd'),
            note=data.get('note')
        )
        logger.info(f"DD aggiunta: commessa={commessa_id}, ore_annuali={ore_annuali}")
        return jsonify({'success': True, 'id': dd_id})
    except Exception as e:
        logger.error(f"Errore aggiunta DD: {e}")
        return jsonify({'error': str(e)}), 500


@report_locale_bp.route('/api/dd/<int:dd_id>', methods=['PUT'])
def api_update_dd(dd_id):
    """Aggiorna una DD"""
    data = request.json

    try:
        db.update_dd(
            dd_id=dd_id,
            ore_settimanali=data.get('ore_settimanali'),
            ore_annuali=data.get('ore_annuali'),
            numero_dd=data.get('numero_dd'),
            data_dd=data.get('data_dd'),
            note=data.get('note')
        )
        logger.info(f"DD aggiornata: id={dd_id}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Errore aggiornamento DD: {e}")
        return jsonify({'error': str(e)}), 500


@report_locale_bp.route('/api/dd/<int:dd_id>', methods=['DELETE'])
def api_delete_dd(dd_id):
    """Elimina una DD"""
    try:
        db.delete_dd(dd_id)
        logger.info(f"DD eliminata: id={dd_id}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Errore eliminazione DD: {e}")
        return jsonify({'error': str(e)}), 500


@report_locale_bp.route('/api/recuperi/<int:commessa_id>/<anno_scolastico>', methods=['GET'])
def api_get_recuperi(commessa_id, anno_scolastico):
    """Ottiene i recuperi per una commessa"""
    recuperi = db.get_recuperi_by_commessa(commessa_id, anno_scolastico)
    return jsonify(recuperi)


@report_locale_bp.route('/api/recuperi', methods=['POST'])
def api_add_recupero():
    """Aggiunge un nuovo recupero"""
    data = request.json

    # Validazione
    commessa_id, err = validate_integer(data.get('commessa_id'), 'Commessa', min_val=1)
    if err:
        return jsonify({'error': err}), 400

    mese, err = validate_integer(data.get('mese'), 'Mese', min_val=1, max_val=12)
    if err:
        return jsonify({'error': err}), 400

    anno, err = validate_integer(data.get('anno'), 'Anno', min_val=2020, max_val=2100)
    if err:
        return jsonify({'error': err}), 400

    ore_recupero, err = validate_number(data.get('ore_recupero'), 'Ore recupero', min_val=0)
    if err:
        return jsonify({'error': err}), 400

    anno_scolastico = data.get('anno_scolastico', '')
    if not anno_scolastico:
        return jsonify({'error': 'Anno scolastico obbligatorio'}), 400

    try:
        recupero_id = db.add_recupero(
            commessa_id=commessa_id,
            anno_scolastico=anno_scolastico,
            mese=mese,
            anno=anno,
            ore_recupero=ore_recupero,
            note=data.get('note')
        )
        logger.info(f"Recupero aggiunto: commessa={commessa_id}, ore={ore_recupero}")
        return jsonify({'success': True, 'id': recupero_id})
    except Exception as e:
        logger.error(f"Errore aggiunta recupero: {e}")
        return jsonify({'error': str(e)}), 500


@report_locale_bp.route('/api/recuperi/<int:recupero_id>', methods=['PUT'])
def api_update_recupero(recupero_id):
    """Aggiorna un recupero"""
    data = request.json

    try:
        db.update_recupero(
            recupero_id=recupero_id,
            ore_recupero=data.get('ore_recupero'),
            note=data.get('note')
        )
        logger.info(f"Recupero aggiornato: id={recupero_id}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Errore aggiornamento recupero: {e}")
        return jsonify({'error': str(e)}), 500


@report_locale_bp.route('/api/recuperi/<int:recupero_id>', methods=['DELETE'])
def api_delete_recupero(recupero_id):
    """Elimina un recupero"""
    try:
        db.delete_recupero(recupero_id)
        logger.info(f"Recupero eliminato: id={recupero_id}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Errore eliminazione recupero: {e}")
        return jsonify({'error': str(e)}), 500


# ==================== OVERRIDE PROGETTATO ====================

@report_locale_bp.route('/api/progettato-override', methods=['POST'])
def api_set_progettato_override():
    """Imposta un override manuale per il progettato di un mese"""
    data = request.json

    commessa_id, err = validate_integer(data.get('commessa_id'), 'Commessa', min_val=1)
    if err:
        return jsonify({'error': err}), 400

    mese, err = validate_integer(data.get('mese'), 'Mese', min_val=1, max_val=12)
    if err:
        return jsonify({'error': err}), 400

    anno, err = validate_integer(data.get('anno'), 'Anno', min_val=2020, max_val=2100)
    if err:
        return jsonify({'error': err}), 400

    ore_progettate, err = validate_number(data.get('ore_progettate'), 'Ore progettate', min_val=0)
    if err:
        return jsonify({'error': err}), 400

    anno_scolastico = data.get('anno_scolastico', '')
    if not anno_scolastico:
        return jsonify({'error': 'Anno scolastico obbligatorio'}), 400

    try:
        db.set_progettato_override(commessa_id, anno_scolastico, mese, anno, ore_progettate)
        logger.info(f"Progettato override: commessa={commessa_id}, mese={mese}/{anno}, ore={ore_progettate}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Errore set progettato override: {e}")
        return jsonify({'error': str(e)}), 500


@report_locale_bp.route('/api/progettato-override/<int:commessa_id>/<anno_scolastico>/<int:mese>/<int:anno>', methods=['DELETE'])
def api_delete_progettato_override(commessa_id, anno_scolastico, mese, anno):
    """Rimuove l'override del progettato (torna al calcolo automatico)"""
    try:
        db.delete_progettato_override(commessa_id, anno_scolastico, mese, anno)
        logger.info(f"Progettato override rimosso: commessa={commessa_id}, mese={mese}/{anno}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Errore delete progettato override: {e}")
        return jsonify({'error': str(e)}), 500


# ==================== OVERRIDE REPORT GENERICO ====================

CAMPI_OVERRIDE_VALIDI = ['giorni_lavorativi', 'ore_progettate', 'ore_erogate', 'ore_recupero', 'max_imponibile', 'effettivo']

@report_locale_bp.route('/api/report-override', methods=['POST'])
def api_set_report_override():
    """Imposta un override manuale per un campo del report mensile"""
    data = request.json

    commessa_id, err = validate_integer(data.get('commessa_id'), 'Commessa', min_val=1)
    if err:
        return jsonify({'error': err}), 400

    mese, err = validate_integer(data.get('mese'), 'Mese', min_val=1, max_val=12)
    if err:
        return jsonify({'error': err}), 400

    anno, err = validate_integer(data.get('anno'), 'Anno', min_val=2020, max_val=2100)
    if err:
        return jsonify({'error': err}), 400

    campo = data.get('campo', '')
    if campo not in CAMPI_OVERRIDE_VALIDI:
        return jsonify({'error': f'Campo non valido. Campi ammessi: {", ".join(CAMPI_OVERRIDE_VALIDI)}'}), 400

    valore, err = validate_number(data.get('valore'), 'Valore', min_val=0)
    if err:
        return jsonify({'error': err}), 400

    anno_scolastico = data.get('anno_scolastico', '')
    if not anno_scolastico:
        return jsonify({'error': 'Anno scolastico obbligatorio'}), 400

    try:
        db.set_report_override(commessa_id, anno_scolastico, mese, anno, campo, valore)
        logger.info(f"Report override: commessa={commessa_id}, mese={mese}/{anno}, campo={campo}, valore={valore}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Errore set report override: {e}")
        return jsonify({'error': str(e)}), 500


@report_locale_bp.route('/api/report-override/<int:commessa_id>/<anno_scolastico>/<int:mese>/<int:anno>/<campo>', methods=['DELETE'])
def api_delete_report_override(commessa_id, anno_scolastico, mese, anno, campo):
    """Rimuove l'override di un campo (torna al calcolo automatico)"""
    if campo not in CAMPI_OVERRIDE_VALIDI:
        return jsonify({'error': 'Campo non valido'}), 400

    try:
        db.delete_report_override(commessa_id, anno_scolastico, mese, anno, campo)
        logger.info(f"Report override rimosso: commessa={commessa_id}, mese={mese}/{anno}, campo={campo}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Errore delete report override: {e}")
        return jsonify({'error': str(e)}), 500

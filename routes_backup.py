"""Route di backup/ripristino del database - Blueprint separato da app.py.

Gli URL restano identici (/api/backup ...); cambia solo l'organizzazione del codice.
Nessuna dipendenza da helper locali di app.py: usa solo database e Flask.
"""
from flask import Blueprint, request, jsonify, send_file

import database as db

backup_bp = Blueprint('backup', __name__)


@backup_bp.route('/api/backup', methods=['POST'])
def api_create_backup():
    """Crea un backup manuale del database"""
    backup_name = db.create_backup()
    if backup_name:
        db.log_audit('backup', 'sistema', dettagli=f'Backup manuale: {backup_name}')
        return jsonify({'success': True, 'backup': backup_name})
    return jsonify({'error': 'Errore creazione backup'}), 500


@backup_bp.route('/api/backup', methods=['GET'])
def api_get_backups():
    """Lista dei backup disponibili"""
    backups = db.get_backups_list()
    return jsonify(backups)


@backup_bp.route('/api/backup/download/<path:backup_name>', methods=['GET'])
def api_download_backup(backup_name):
    """Scarica un file di backup, per salvarlo dove si vuole (chiavetta, cloud...)."""
    backup_path = db.percorso_backup_valido(backup_name)
    if not backup_path:
        return jsonify({'error': 'Backup non trovato'}), 404
    return send_file(backup_path, as_attachment=True, download_name=backup_name)


@backup_bp.route('/api/backup/restore', methods=['POST'])
def api_restore_backup():
    """Ripristina un backup"""
    data = request.json or {}
    backup_name = data.get('backup')
    confirm = data.get('confirm', '')

    if confirm != 'CONFERMA':
        return jsonify({'error': 'Per procedere, devi confermare digitando "CONFERMA"'}), 400

    if not backup_name:
        return jsonify({'error': 'Nome backup richiesto'}), 400

    if db.restore_backup(backup_name):
        db.log_audit('ripristino', 'sistema', dettagli=f'Ripristinato backup: {backup_name}')
        return jsonify({'success': True, 'message': f'Backup {backup_name} ripristinato'})
    return jsonify({'error': 'Backup non trovato o errore nel ripristino'}), 400

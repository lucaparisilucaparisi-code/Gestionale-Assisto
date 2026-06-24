#!/usr/bin/env python3
"""
Gestionale OEPAC - Sistema di Rendicontazione
"""

import os
import re
import io
import json
import csv
import hashlib
import base64
import secrets
from functools import wraps
from io import StringIO
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, make_response, session
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# WebAuthn (impronta digitale / Windows Hello)
try:
    from webauthn import (
        generate_registration_options,
        verify_registration_response,
        generate_authentication_options,
        verify_authentication_response,
        options_to_json,
    )
    from webauthn.helpers.structs import (
        PublicKeyCredentialDescriptor,
        AuthenticatorSelectionCriteria,
        UserVerificationRequirement,
        ResidentKeyRequirement,
        RegistrationCredential,
        AuthenticationCredential,
    )
    from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
    WEBAUTHN_AVAILABLE = True
except ImportError:
    WEBAUTHN_AVAILABLE = False

import config
import database as db
import import_rendicontazione
import import_dipendenti
from routes_export import export_bp

logger = config.setup_logging()

def push_undo(action_type, data):
    """Salva un'azione nello stack undo persistente"""
    db.push_undo_action(action_type, data)


app = Flask(__name__)
app.register_blueprint(export_bp)
app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER
app.config['EXPORT_FOLDER'] = config.EXPORT_FOLDER
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH
def _load_or_generate_secret_key():
    """Carica il secret_key da file, oppure lo genera random e lo persiste.
    Priorita': variabile ambiente FLASK_SECRET_KEY > file .flask_secret_key."""
    env_key = os.environ.get('FLASK_SECRET_KEY')
    if env_key:
        return env_key
    key_path = os.path.join(os.path.dirname(config.DATABASE_PATH), '.flask_secret_key')
    try:
        if os.path.exists(key_path):
            with open(key_path, 'rb') as f:
                data = f.read().strip()
                if len(data) >= 32:
                    return data
        # Non esiste o corrotto: genera e salva con permessi ristretti
        new_key = secrets.token_bytes(32)
        with open(key_path, 'wb') as f:
            f.write(new_key)
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass  # Windows: chmod non applicabile
        return new_key
    except OSError as e:
        # Fallback: deterministico (meno sicuro ma funzionante)
        logger.warning(f"Impossibile persistere secret_key ({e}), uso fallback deterministico")
        return hashlib.sha256(config.DATABASE_PATH.encode()).hexdigest()


app.secret_key = _load_or_generate_secret_key()

# Assicura che le cartelle esistano
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['EXPORT_FOLDER'], exist_ok=True)
os.makedirs(config.BACKUP_FOLDER, exist_ok=True)

# Configurazione sessione (sicurezza)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 60 * 60 * 8  # 8 ore

# Inizializza database
db.init_db()


# ==================== AUTENTICAZIONE ====================
# Configurazione WebAuthn per localhost (single-user, single-device)
WEBAUTHN_RP_ID = 'localhost'
WEBAUTHN_RP_NAME = 'Assisto - Gestionale OEPAC'
WEBAUTHN_ORIGIN = 'http://localhost:5000'

# Route pubbliche che NON richiedono autenticazione
PUBLIC_ENDPOINTS = {
    'login_page',
    'setup_page',
    'api_auth_setup',
    'api_auth_login',
    'api_auth_status',
    'api_webauthn_auth_begin',
    'api_webauthn_auth_complete',
    'static',
}


@app.before_request
def require_authentication():
    """Protegge globalmente tutte le route tranne quelle in PUBLIC_ENDPOINTS."""
    endpoint = request.endpoint
    if endpoint is None:
        return  # 404 sara' gestito da Flask normalmente

    if endpoint in PUBLIC_ENDPOINTS:
        return

    # Se auth non configurata, vai a setup (tranne se gia' ci stai andando)
    if not db.auth_is_configured():
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Sistema non configurato', 'code': 'SETUP_REQUIRED'}), 403
        return redirect(url_for('setup_page'))

    # Se non autenticato, blocca
    if not session.get('authenticated'):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Non autenticato', 'code': 'AUTH_REQUIRED'}), 401
        return redirect(url_for('login_page', next=request.path))


def login_required(f):
    """Decorator: richiede che l'utente sia autenticato.
    Se non configurato, reindirizza a /setup. Se non loggato, a /login."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not db.auth_is_configured():
            return redirect(url_for('setup_page'))
        if not session.get('authenticated'):
            # Se è una chiamata API, ritorna 401 JSON
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Non autenticato', 'code': 'AUTH_REQUIRED'}), 401
            # Altrimenti redirect a login
            return redirect(url_for('login_page', next=request.path))
        return f(*args, **kwargs)
    return decorated


def _login_user(metodo):
    """Imposta la sessione come autenticata."""
    session.permanent = True
    session['authenticated'] = True
    session['auth_method'] = metodo
    session['auth_time'] = datetime.now().isoformat()
    db.auth_record_login(metodo)


# ---------- PAGINE AUTH ----------

@app.route('/setup', methods=['GET'])
def setup_page():
    """Prima configurazione: crea username e password."""
    if db.auth_is_configured():
        return redirect(url_for('login_page'))
    return render_template('setup.html')


@app.route('/login', methods=['GET'])
def login_page():
    """Pagina di login."""
    if not db.auth_is_configured():
        return redirect(url_for('setup_page'))
    if session.get('authenticated'):
        return redirect(url_for('index'))
    return render_template('login.html',
                           webauthn_available=WEBAUTHN_AVAILABLE,
                           has_credentials=len(db.webauthn_get_credentials()) > 0)


@app.route('/api/auth/setup', methods=['POST'])
def api_auth_setup():
    """Crea l'account iniziale (solo al primo setup)."""
    if db.auth_is_configured():
        return jsonify({'error': 'Gia configurato'}), 400

    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    if len(username) < 3:
        return jsonify({'error': 'Username deve essere almeno 3 caratteri'}), 400
    if len(password) < 8:
        return jsonify({'error': 'Password deve essere almeno 8 caratteri'}), 400

    password_hash = generate_password_hash(password)
    db.auth_create_user(username, password_hash)
    _login_user('password')
    return jsonify({'success': True})


@app.route('/api/auth/login', methods=['POST'])
def api_auth_login():
    """Login con username e password."""
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    user = db.auth_get_user()
    if not user or user['username'] != username:
        return jsonify({'error': 'Credenziali non valide'}), 401
    if not check_password_hash(user['password_hash'], password):
        return jsonify({'error': 'Credenziali non valide'}), 401

    _login_user('password')
    return jsonify({'success': True})


@app.route('/api/auth/logout', methods=['POST'])
def api_auth_logout():
    """Logout: pulisce la sessione."""
    session.clear()
    return jsonify({'success': True})


@app.route('/api/auth/status')
def api_auth_status():
    """Ritorna lo stato di autenticazione corrente."""
    user = db.auth_get_user() if db.auth_is_configured() else None
    return jsonify({
        'configured': db.auth_is_configured(),
        'authenticated': bool(session.get('authenticated')),
        'method': session.get('auth_method'),
        'username': user['username'] if user else None,
        'webauthn_available': WEBAUTHN_AVAILABLE,
        'webauthn_registered': len(db.webauthn_get_credentials()) > 0 if db.auth_is_configured() else False,
    })


# ---------- WEBAUTHN (impronta digitale / Windows Hello) ----------

def _webauthn_user_id():
    """User handle WebAuthn: deterministico (single-user).
    Deve essere un byte string stabile ma non deducibile dall'username."""
    user = db.auth_get_user()
    if not user:
        return None
    # Deriva da data_creazione + username (stabile, 32 byte)
    seed = (user['username'] + user['data_creazione']).encode('utf-8')
    return hashlib.sha256(seed).digest()


@app.route('/api/auth/webauthn/register/begin', methods=['POST'])
@login_required
def api_webauthn_register_begin():
    """Step 1: genera le options per la registrazione di una nuova credenziale."""
    if not WEBAUTHN_AVAILABLE:
        return jsonify({'error': 'WebAuthn non disponibile (pacchetto non installato)'}), 500

    user = db.auth_get_user()
    if not user:
        return jsonify({'error': 'Utente non trovato'}), 400

    # Escludi credenziali gia' registrate
    existing = db.webauthn_get_credentials()
    exclude = [
        PublicKeyCredentialDescriptor(id=bytes(c['credential_id']))
        for c in existing
    ]

    options = generate_registration_options(
        rp_id=WEBAUTHN_RP_ID,
        rp_name=WEBAUTHN_RP_NAME,
        user_id=_webauthn_user_id(),
        user_name=user['username'],
        user_display_name=user['username'],
        exclude_credentials=exclude,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.REQUIRED,
            resident_key=ResidentKeyRequirement.PREFERRED,
        ),
    )

    # Salva challenge in sessione (sara' verificato nello step successivo)
    session['webauthn_challenge'] = bytes_to_base64url(options.challenge)

    return app.response_class(options_to_json(options), mimetype='application/json')


@app.route('/api/auth/webauthn/register/complete', methods=['POST'])
@login_required
def api_webauthn_register_complete():
    """Step 2: verifica la risposta del browser e salva la credenziale."""
    if not WEBAUTHN_AVAILABLE:
        return jsonify({'error': 'WebAuthn non disponibile'}), 500

    challenge_b64 = session.pop('webauthn_challenge', None)
    if not challenge_b64:
        return jsonify({'error': 'Challenge non trovata o scaduta'}), 400

    data = request.get_json() or {}
    nome = (data.get('nome') or 'Impronta').strip()[:50]
    credential = data.get('credential')
    if not credential:
        return jsonify({'error': 'Credential mancante'}), 400

    try:
        verification = verify_registration_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge_b64),
            expected_origin=WEBAUTHN_ORIGIN,
            expected_rp_id=WEBAUTHN_RP_ID,
            require_user_verification=True,
        )
    except Exception as e:
        logger.warning(f"WebAuthn registration verification fallita: {e}")
        return jsonify({'error': f'Verifica fallita: {str(e)}'}), 400

    # Protezione contro response=null: il secondo .get() fallirebbe su None
    response_obj = credential.get('response') or {}
    transports = ','.join(response_obj.get('transports') or [])
    db.webauthn_add_credential(
        credential_id=verification.credential_id,
        public_key=verification.credential_public_key,
        sign_count=verification.sign_count,
        nome=nome,
        transports=transports or None,
    )
    return jsonify({'success': True, 'nome': nome})


@app.route('/api/auth/webauthn/authenticate/begin', methods=['POST'])
def api_webauthn_auth_begin():
    """Step 1: genera options per il login con impronta (no auth richiesta)."""
    if not WEBAUTHN_AVAILABLE:
        return jsonify({'error': 'WebAuthn non disponibile'}), 500
    if not db.auth_is_configured():
        return jsonify({'error': 'Nessun utente configurato'}), 400

    creds = db.webauthn_get_credentials()
    if not creds:
        return jsonify({'error': 'Nessuna impronta registrata'}), 400

    allowed = [
        PublicKeyCredentialDescriptor(id=bytes(c['credential_id']))
        for c in creds
    ]

    options = generate_authentication_options(
        rp_id=WEBAUTHN_RP_ID,
        allow_credentials=allowed,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    session['webauthn_auth_challenge'] = bytes_to_base64url(options.challenge)
    return app.response_class(options_to_json(options), mimetype='application/json')


@app.route('/api/auth/webauthn/authenticate/complete', methods=['POST'])
def api_webauthn_auth_complete():
    """Step 2: verifica la risposta e autentica."""
    if not WEBAUTHN_AVAILABLE:
        return jsonify({'error': 'WebAuthn non disponibile'}), 500

    challenge_b64 = session.pop('webauthn_auth_challenge', None)
    if not challenge_b64:
        return jsonify({'error': 'Challenge non trovata'}), 400

    data = request.get_json() or {}
    credential = data.get('credential')
    if not credential:
        return jsonify({'error': 'Credential mancante'}), 400

    try:
        raw_id = base64url_to_bytes(credential['rawId'])
    except Exception:
        return jsonify({'error': 'rawId non valido'}), 400

    stored = db.webauthn_get_credential_by_id(raw_id)
    if not stored:
        return jsonify({'error': 'Credenziale non riconosciuta'}), 401

    try:
        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge_b64),
            expected_origin=WEBAUTHN_ORIGIN,
            expected_rp_id=WEBAUTHN_RP_ID,
            credential_public_key=bytes(stored['public_key']),
            credential_current_sign_count=stored['sign_count'],
            require_user_verification=True,
        )
    except Exception as e:
        logger.warning(f"WebAuthn auth verification fallita: {e}")
        return jsonify({'error': 'Verifica impronta fallita'}), 401

    db.webauthn_update_sign_count(raw_id, verification.new_sign_count)
    _login_user('webauthn')
    return jsonify({'success': True})


@app.route('/api/auth/webauthn/credentials', methods=['GET'])
@login_required
def api_webauthn_list_credentials():
    """Lista le credenziali registrate (solo metadata)."""
    creds = db.webauthn_get_credentials()
    return jsonify({
        'credentials': [
            {
                'id': c['id'],
                'nome': c['nome'],
                'data_registrazione': c['data_registrazione'],
                'ultimo_utilizzo': c['ultimo_utilizzo'],
            }
            for c in creds
        ]
    })


@app.route('/api/auth/webauthn/credentials/<int:cred_id>', methods=['DELETE'])
@login_required
def api_webauthn_delete_credential(cred_id):
    """Rimuove una credenziale registrata."""
    db.webauthn_delete_credential(cred_id)
    return jsonify({'success': True})


@app.route('/api/auth/change-password', methods=['POST'])
@login_required
def api_auth_change_password():
    """Cambia la password dell'utente (richiede password corrente)."""
    data = request.get_json() or {}
    current = data.get('current_password') or ''
    nuova = data.get('new_password') or ''

    if len(nuova) < 8:
        return jsonify({'error': 'La nuova password deve essere almeno 8 caratteri'}), 400

    user = db.auth_get_user()
    if not user:
        # Scenario difensivo: record eliminato in un altro processo
        return jsonify({'error': 'Utente non trovato'}), 401
    if not check_password_hash(user['password_hash'], current):
        return jsonify({'error': 'Password corrente non valida'}), 401

    db.auth_update_credentials(password_hash=generate_password_hash(nuova))
    return jsonify({'success': True})


@app.route('/profilo')
@login_required
def profilo_page():
    """Pagina gestione profilo e impronte."""
    return render_template('profilo.html')




# Backup all'avvio
if config.BACKUP_ON_STARTUP:
    db.create_backup()
    logger.info("Backup automatico all'avvio completato")

# Costanti da config
MESI_NOME = config.MESI_NOME
MESI_SCOLASTICI = config.MESI_SCOLASTICI


# ==================== VALIDAZIONE ====================

def validate_string(value, field_name, max_length=100, required=True):
    """Valida una stringa: lunghezza, caratteri pericolosi"""
    if value is None or str(value).strip() == '':
        if required:
            return None, f'{field_name} e\' obbligatorio'
        return '', None

    value = str(value).strip()

    if len(value) > max_length:
        return None, f'{field_name} troppo lungo (max {max_length} caratteri)'

    # Blocca caratteri pericolosi (tag HTML, script injection)
    if re.search(r'<[^>]*script|javascript:|on\w+\s*=', value, re.IGNORECASE):
        return None, f'{field_name} contiene caratteri non validi'

    return value, None


def validate_number(value, field_name, min_val=0, max_val=None, required=True):
    """Valida un valore numerico"""
    if value is None or value == '':
        if required:
            return None, f'{field_name} e\' obbligatorio'
        return 0, None

    try:
        num = float(value)
    except (ValueError, TypeError):
        return None, f'{field_name} deve essere un numero valido'

    if num < min_val:
        return None, f'{field_name} deve essere almeno {min_val}'

    if max_val is not None and num > max_val:
        return None, f'{field_name} non puo\' superare {max_val}'

    return num, None


def validate_integer(value, field_name, min_val=0, max_val=None, required=True):
    """Valida un valore intero"""
    if value is None or value == '':
        if required:
            return None, f'{field_name} e\' obbligatorio'
        return 0, None

    try:
        num = int(value)
    except (ValueError, TypeError):
        return None, f'{field_name} deve essere un numero intero'

    if num < min_val:
        return None, f'{field_name} deve essere almeno {min_val}'

    if max_val is not None and num > max_val:
        return None, f'{field_name} non puo\' superare {max_val}'

    return num, None


# ==================== ROUTES PAGINE ====================

@app.route('/')
def index():
    """Dashboard principale"""
    return render_template('index.html')


@app.route('/import')
def import_page():
    """Pagina import Excel"""
    return render_template('import.html')


@app.route('/rendicontazione')
def rendicontazione_page():
    """Pagina rendicontazione mensile"""
    return render_template('rendicontazione.html')


@app.route('/chiusura-mese')
def chiusura_mese_page():
    """Procedura guidata di chiusura del mese"""
    return render_template('chiusura_mese.html')


@app.route('/calendario')
def calendario_page():
    """Pagina gestione calendario scolastico"""
    return render_template('calendario.html')


@app.route('/report')
def report_page():
    """Pagina generazione report"""
    return render_template('report.html')


@app.route('/utenti')
def utenti_page():
    """Pagina gestione utenti"""
    return render_template('utenti.html')


@app.route('/dipendenti')
def dipendenti_page():
    """Anagrafica dipendenti (operatori OEPAC)"""
    return render_template('dipendenti.html')


@app.route('/dipendente/<int:dipendente_id>')
def dipendente_dettaglio_page(dipendente_id):
    """Scheda del singolo dipendente"""
    return render_template('dipendente_dettaglio.html', dipendente_id=dipendente_id)


@app.route('/turni')
def turni_page():
    """Planner turni settimanali degli operatori"""
    return render_template('turni.html')


@app.route('/sostituzioni')
def sostituzioni_page():
    """Assenze degli operatori e gestione delle sostituzioni"""
    return render_template('sostituzioni.html')


@app.route('/impostazioni')
def impostazioni_page():
    """Area Impostazioni: porta alla prima sezione (Commesse)."""
    return redirect(url_for('commesse_page'))


@app.route('/commesse')
def commesse_page():
    """Pagina gestione commesse"""
    return render_template('commesse.html')


@app.route('/statistiche')
def statistiche_page():
    """Pagina statistiche avanzate"""
    return render_template('statistiche.html')


# ==================== API ====================

@app.route('/api/import-excel/template')
def api_import_template():
    """Scarica template Excel per l'import"""
    try:
        import io
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment

        wb = Workbook()
        ws = wb.active
        ws.title = "Utenti"

        # Header
        headers = ['Commessa', 'Albero Attività', 'Attività', 'Monte Ore Sett.']
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF")

        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center')

        # Esempi
        ws.cell(row=2, column=1, value="CIG 123456")
        ws.cell(row=2, column=2, value="IC Esempio - Scuola Primaria")
        ws.cell(row=2, column=3, value="Rossi Mario")
        ws.cell(row=2, column=4, value=10)

        ws.cell(row=3, column=1, value="CIG 123456")
        ws.cell(row=3, column=2, value="IC Esempio - Scuola Secondaria")
        ws.cell(row=3, column=3, value="Bianchi Anna")
        ws.cell(row=3, column=4, value=15)

        # Larghezza colonne
        ws.column_dimensions['A'].width = 15
        ws.column_dimensions['B'].width = 40
        ws.column_dimensions['C'].width = 25
        ws.column_dimensions['D'].width = 15

        # Salva in buffer
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='template_import_utenti.xlsx'
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/import-excel/cronologia')
def api_import_cronologia():
    """Ottiene cronologia import"""
    try:
        with db.get_db_context() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM import_cronologia
                ORDER BY data DESC
                LIMIT 20
            ''')
            rows = cursor.fetchall()

            cronologia = []
            for r in rows:
                cronologia.append({
                    'id': r['id'],
                    'data': r['data'],
                    'filename': r['filename'],
                    'importati': r['importati'],
                    'aggiornati': r['aggiornati'],
                    'errori': r['errori'],
                    'utente': r['utente'] or 'Sistema'
                })

            return jsonify({'cronologia': cronologia})
    except Exception as e:
        # Se la tabella non esiste, la creiamo
        try:
            with db.get_db_context() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS import_cronologia (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        filename TEXT,
                        importati INTEGER DEFAULT 0,
                        aggiornati INTEGER DEFAULT 0,
                        errori INTEGER DEFAULT 0,
                        utente TEXT
                    )
                ''')
            return jsonify({'cronologia': []})
        except Exception:
            return jsonify({'cronologia': []})


@app.route('/api/import-excel/preview', methods=['POST'])
def api_preview_excel():
    """Anteprima import Excel - mostra cosa verra' importato senza modificare il DB"""
    if 'file' not in request.files:
        return jsonify({'error': 'Nessun file caricato'}), 400

    file = request.files['file']
    if file.filename == '' or not file.filename.endswith(('.xlsx', '.xls')):
        return jsonify({'error': 'File non valido'}), 400

    try:
        df = pd.read_excel(file)
        df.columns = [str(col).strip().lower() for col in df.columns]

        # Mappa colonne (stessa logica di import)
        col_map = {}
        for col in df.columns:
            col_lower = str(col).lower()
            if 'commessa' in col_lower:
                col_map['commessa'] = col
            elif 'albero' in col_lower:
                col_map['scuola'] = col
            elif 'scuola' in col_lower or 'ic' in col_lower or 'plesso' in col_lower:
                if 'scuola' not in col_map:
                    col_map['scuola'] = col
            elif col_lower == 'attività' or col_lower == 'attivita':
                col_map['utente'] = col
            elif 'nome' in col_lower and 'cognome' not in col_lower:
                if 'utente' not in col_map:
                    col_map['nome'] = col
            elif 'cognome' in col_lower:
                col_map['cognome'] = col
            elif 'utente' in col_lower or 'nominativo' in col_lower:
                col_map['utente'] = col
            elif 'monte' in col_lower or 'ore' in col_lower:
                col_map['monte_ore'] = col

        # Genera anteprima righe
        preview_rows = []
        errors = []

        for idx, row in df.iterrows():
            try:
                commessa = str(row.get(col_map.get('commessa', ''), '')).strip()
                scuola = str(row.get(col_map.get('scuola', ''), '')).strip()

                if 'utente' in col_map:
                    nome_completo = str(row[col_map['utente']]).strip()
                    parti = nome_completo.split()
                    # Formato Excel: "Cognome Nome" -> cognome = primo token, nome = resto
                    cognome = parti[0] if parti else ''
                    nome = ' '.join(parti[1:]) if len(parti) >= 2 else ''
                else:
                    nome = str(row.get(col_map.get('nome', ''), '')).strip()
                    cognome = str(row.get(col_map.get('cognome', ''), '')).strip()

                monte_ore_val = row.get(col_map.get('monte_ore', ''), None)
                if pd.isna(monte_ore_val) if monte_ore_val is not None else True:
                    continue
                monte_ore = float(monte_ore_val)

                if not nome or nome == 'nan':
                    continue
                if not scuola or scuola == 'nan':
                    continue

                # Verifica se l'utente esiste già
                stato = 'nuovo'
                try:
                    with db.get_db_context() as conn:
                        cursor = conn.cursor()
                        cursor.execute('''
                            SELECT u.id FROM utenti u
                            JOIN scuole s ON u.scuola_id = s.id
                            WHERE u.nome = ? AND u.cognome = ? AND s.nome LIKE ?
                        ''', (nome, cognome, f'%{scuola[:30]}%'))
                        if cursor.fetchone():
                            stato = 'esistente'
                except Exception as e:
                    logger.warning(f"Anteprima import, controllo esistenza utente fallito "
                                   f"(riga {idx + 2}, {nome} {cognome}): {e}")

                preview_rows.append({
                    'riga': idx + 2,
                    'commessa': commessa,
                    'scuola': scuola[:50],
                    'nome': nome,
                    'cognome': cognome,
                    'monte_ore': monte_ore,
                    'stato': stato
                })
            except Exception as e:
                errors.append(f"Riga {idx+2}: {str(e)}")

        return jsonify({
            'success': True,
            'colonne_trovate': list(df.columns),
            'colonne_mappate': col_map,
            'totale_righe': len(df),
            'righe_valide': len(preview_rows),
            'preview': preview_rows[:50],
            'errors': errors[:10]
        })

    except Exception as e:
        return jsonify({'error': f'Errore lettura file: {str(e)}'}), 500


@app.route('/api/import-excel', methods=['POST'])
def api_import_excel():
    """Importa dati da file Excel"""
    logger.info("Inizio import Excel")

    if 'file' not in request.files:
        return jsonify({'error': 'Nessun file caricato'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Nessun file selezionato'}), 400

    if not file.filename.endswith(('.xlsx', '.xls')):
        return jsonify({'error': 'Formato file non valido. Usa .xlsx o .xls'}), 400

    try:
        logger.info(f"Lettura file: {file.filename}")

        # Leggi Excel
        df = pd.read_excel(file)
        logger.info(f"Righe trovate: {len(df)}")
        logger.info(f"Colonne originali: {list(df.columns)}")

        # Normalizza nomi colonne (converti tutto a stringa prima)
        df.columns = [str(col).strip().lower() for col in df.columns]
        logger.info(f"Colonne normalizzate: {list(df.columns)}")

        # Trova le colonne necessarie
        col_map = {}
        for col in df.columns:
            col_lower = str(col).lower()
            if 'commessa' in col_lower:
                col_map['commessa'] = col
            elif 'albero' in col_lower:
                col_map['scuola'] = col
            elif 'scuola' in col_lower or 'ic' in col_lower or 'plesso' in col_lower:
                if 'scuola' not in col_map:
                    col_map['scuola'] = col
            elif col_lower == 'attività' or col_lower == 'attivita':
                col_map['utente'] = col
            elif 'nome' in col_lower and 'cognome' not in col_lower:
                if 'utente' not in col_map:
                    col_map['nome'] = col
            elif 'cognome' in col_lower:
                col_map['cognome'] = col
            elif 'utente' in col_lower or 'nominativo' in col_lower:
                col_map['utente'] = col
            elif 'monte' in col_lower or 'ore' in col_lower:
                col_map['monte_ore'] = col

        logger.info(f"Colonne mappate: {col_map}")

        # Verifica colonne necessarie
        required = ['commessa', 'monte_ore']
        if 'utente' not in col_map and ('nome' not in col_map or 'cognome' not in col_map):
            return jsonify({'error': f'Colonna nome utente non trovata. Colonne trovate: {list(df.columns)}'}), 400

        if 'scuola' not in col_map:
            return jsonify({'error': f'Colonna scuola non trovata. Colonne trovate: {list(df.columns)}'}), 400

        for req in required:
            if req not in col_map:
                return jsonify({'error': f'Colonna {req} non trovata. Colonne trovate: {list(df.columns)}'}), 400

        # Modalità import
        import_mode = request.form.get('mode', 'update')  # 'update' or 'skip'

        # Importa dati
        imported = 0
        updated = 0
        skipped = 0
        errors = []

        for idx, row in df.iterrows():
            try:
                commessa = str(row[col_map['commessa']]).strip()
                scuola = str(row[col_map['scuola']]).strip()

                # Gestione nome
                if 'utente' in col_map:
                    nome_completo = str(row[col_map['utente']]).strip()
                    parti = nome_completo.split()
                    # Formato Excel: "Cognome Nome" -> cognome = primo token, nome = resto
                    if len(parti) >= 2:
                        cognome = parti[0]
                        nome = ' '.join(parti[1:])
                    else:
                        cognome = nome_completo
                        nome = ''
                else:
                    nome = str(row[col_map['nome']]).strip()
                    cognome = str(row[col_map.get('cognome', '')]).strip() if 'cognome' in col_map else ''

                monte_ore_val = row[col_map['monte_ore']]
                # Gestisci monte_ore che potrebbe essere stringa o numero
                if pd.isna(monte_ore_val):
                    continue
                monte_ore = float(monte_ore_val)

                # Salta righe vuote
                if not nome or nome == 'nan' or nome.lower() == 'nan':
                    continue
                if not scuola or scuola == 'nan' or scuola.lower() == 'nan':
                    continue

                # Crea/ottieni scuola
                scuola_id = db.get_or_create_scuola(commessa, scuola)
                if not scuola_id:
                    errors.append(f"Riga {idx+2}: Commessa '{commessa}' non valida")
                    continue

                # Verifica se l'utente esiste già
                with db.get_db_context() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT id FROM utenti
                        WHERE nome = ? AND cognome = ? AND scuola_id = ?
                    ''', (nome, cognome, scuola_id))
                    existing = cursor.fetchone()

                    if existing:
                        if import_mode == 'skip':
                            skipped += 1
                            continue
                        else:
                            # Aggiorna utente esistente
                            cursor.execute('''
                                UPDATE utenti SET monte_ore_settimanale = ?
                                WHERE id = ?
                            ''', (monte_ore, existing['id']))
                            updated += 1
                    else:
                        # Crea nuovo utente
                        db.get_or_create_utente(scuola_id, nome, cognome, monte_ore)
                        imported += 1

            except Exception as e:
                errors.append(f"Riga {idx+2}: {str(e)}")

        logger.info(f"Import completato: {imported} nuovi, {updated} aggiornati, {skipped} saltati")
        db.log_audit('import', 'utenti', dettagli=f'{imported} nuovi, {updated} aggiornati da {file.filename}')

        # Salva in cronologia
        try:
            with db.get_db_context() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS import_cronologia (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        filename TEXT,
                        importati INTEGER DEFAULT 0,
                        aggiornati INTEGER DEFAULT 0,
                        errori INTEGER DEFAULT 0,
                        utente TEXT
                    )
                ''')
                cursor.execute('''
                    INSERT INTO import_cronologia (filename, importati, aggiornati, errori)
                    VALUES (?, ?, ?, ?)
                ''', (file.filename, imported, updated, len(errors)))
        except Exception as e:
            logger.warning(f"Errore salvataggio cronologia: {e}")

        return jsonify({
            'success': True,
            'imported': imported,
            'updated': updated,
            'skipped': skipped,
            'errors': errors
        })

    except Exception as e:
        logger.error(f"Errore import: {str(e)}", exc_info=True)
        return jsonify({'error': f'Errore durante l\'import: {str(e)}'}), 500


# ==================== IMPORT RENDICONTAZIONE MENSILE ====================

def _analizza_rendicontazione(file):
    """Legge il file Excel e abbina le righe agli utenti in anagrafica.
    Ritorna la lista di fogli analizzati (vedi import_rendicontazione.analizza)."""
    fogli = import_rendicontazione.parse_workbook(file)
    utenti = db.get_all_utenti(page=None)
    return import_rendicontazione.analizza(fogli, utenti)


def _riepilogo_foglio(f, max_esempi=15):
    """Compatta un foglio analizzato per la risposta JSON (anteprima)."""
    def slim(voce):
        return {
            'nome': voce['nome_completo'],
            'scuola': (voce.get('scuola') or '')[:60],
            'commessa': voce.get('commessa', ''),
            'ore': voce.get('ore'),
            'pasti': voce.get('pasti'),
            'utente_nome': voce.get('utente_nome'),
        }
    return {
        'foglio': f['foglio'],
        'mese': f['mese'],
        'anno': f['anno'],
        'mese_nome': MESI_NOME.get(f['mese'], '') if f['mese'] else '',
        'riconosciuto': f['riconosciuto'],
        'periodo_valido': bool(f['mese'] and f['anno']),
        'n_match': len(f['match']),
        'n_non_trovati': len(f['non_trovati']),
        'n_ambigui': len(f['ambigui']),
        'n_senza_ore': len(f['senza_ore']),
        'anteprima_match': [slim(v) for v in f['match'][:max_esempi]],
        'esempi_non_trovati': [slim(v) for v in f['non_trovati'][:max_esempi]],
        'esempi_ambigui': [slim(v) for v in f['ambigui'][:max_esempi]],
    }


@app.route('/api/import-rendicontazione/preview', methods=['POST'])
def api_preview_rendicontazione():
    """Anteprima import rendicontazioni: mostra per ogni mese quanti utenti
    sono stati abbinati, senza modificare il database."""
    if 'file' not in request.files:
        return jsonify({'error': 'Nessun file caricato'}), 400
    file = request.files['file']
    if file.filename == '' or not file.filename.lower().endswith(('.xlsx', '.xls')):
        return jsonify({'error': 'File non valido. Usa .xlsx o .xls'}), 400

    try:
        analisi = _analizza_rendicontazione(file)
        fogli = [_riepilogo_foglio(f) for f in analisi]
        return jsonify({
            'success': True,
            'fogli': fogli,
            'totale_match': sum(f['n_match'] for f in fogli),
            'totale_non_trovati': sum(f['n_non_trovati'] for f in fogli),
            'totale_ambigui': sum(f['n_ambigui'] for f in fogli),
        })
    except Exception as e:
        logger.error(f"Errore anteprima rendicontazione: {e}", exc_info=True)
        return jsonify({'error': f'Errore lettura file: {str(e)}'}), 500


@app.route('/api/import-rendicontazione', methods=['POST'])
def api_import_rendicontazione():
    """Importa le rendicontazioni mensili. Scrive ore e pasti per gli utenti
    abbinati, un mese (foglio) alla volta in transazione."""
    if 'file' not in request.files:
        return jsonify({'error': 'Nessun file caricato'}), 400
    file = request.files['file']
    if file.filename == '' or not file.filename.lower().endswith(('.xlsx', '.xls')):
        return jsonify({'error': 'File non valido. Usa .xlsx o .xls'}), 400

    # Modalita': 'overwrite' sovrascrive sempre, 'solo_vuoti' tocca solo chi non ha ore
    modalita = (request.form.get('modalita') or 'solo_vuoti').strip()

    try:
        analisi = _analizza_rendicontazione(file)
    except Exception as e:
        logger.error(f"Errore lettura rendicontazione: {e}", exc_info=True)
        return jsonify({'error': f'Errore lettura file: {str(e)}'}), 500

    dettaglio = []
    tot_scritti = tot_saltati_pieni = tot_non_trovati = tot_ambigui = 0

    for f in analisi:
        if not (f['mese'] and f['anno']):
            dettaglio.append({'foglio': f['foglio'], 'errore': 'Mese/anno non riconosciuto dal foglio'})
            continue

        anno, mese = f['anno'], f['mese']

        # In modalita' "solo vuoti" salta gli utenti che hanno gia' ore nel mese
        gia_con_ore = set()
        if modalita != 'overwrite':
            for d in db.get_rendicontazione_completa(anno, mese):
                if (d.get('ore_lavorate_60') or 0) > 0:
                    gia_con_ore.add(d['utente_id'])

        updates = []
        saltati_pieni = 0
        for voce in f['match']:
            if voce['utente_id'] in gia_con_ore:
                saltati_pieni += 1
                continue
            updates.append({
                'utente_id': voce['utente_id'],
                'ore_lavorate': voce['ore'],
                'pasti': voce['pasti'],
            })

        try:
            scritti = db.update_rendicontazione_batch(anno, mese, updates)
        except Exception as e:
            logger.error(f"Errore scrittura rendicontazione {mese}/{anno}: {e}", exc_info=True)
            dettaglio.append({'foglio': f['foglio'], 'mese': mese, 'anno': anno,
                              'errore': str(e)})
            continue

        tot_scritti += scritti
        tot_saltati_pieni += saltati_pieni
        tot_non_trovati += len(f['non_trovati'])
        tot_ambigui += len(f['ambigui'])
        dettaglio.append({
            'foglio': f['foglio'], 'mese': mese, 'anno': anno,
            'mese_nome': MESI_NOME.get(mese, ''),
            'scritti': scritti,
            'saltati_gia_pieni': saltati_pieni,
            'non_trovati': len(f['non_trovati']),
            'ambigui': len(f['ambigui']),
        })

    db.log_audit('import_rendicontazione', 'rendicontazione',
                 dettagli=f"{tot_scritti} rendicontazioni importate da {file.filename}")
    try:
        with db.get_db_context() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS import_cronologia (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    filename TEXT, importati INTEGER DEFAULT 0,
                    aggiornati INTEGER DEFAULT 0, errori INTEGER DEFAULT 0, utente TEXT
                )''')
            conn.execute('''INSERT INTO import_cronologia (filename, importati, aggiornati, errori, utente)
                            VALUES (?, ?, 0, ?, ?)''',
                         (f"[Rendicontazione] {file.filename}", tot_scritti,
                          tot_non_trovati + tot_ambigui, session.get('username', 'Sistema')))
    except Exception as e:
        logger.warning(f"Cronologia import rendicontazione non salvata: {e}")

    return jsonify({
        'success': True,
        'modalita': modalita,
        'totale_scritti': tot_scritti,
        'totale_saltati_gia_pieni': tot_saltati_pieni,
        'totale_non_trovati': tot_non_trovati,
        'totale_ambigui': tot_ambigui,
        'dettaglio': dettaglio,
    })


# ==================== API DIPENDENTI ====================

@app.route('/api/dipendenti', methods=['GET'])
def api_get_dipendenti():
    """Elenco dipendenti, con ricerca/filtro opzionali e conteggio assistiti."""
    include_inactive = request.args.get('tutti') == '1'
    search = request.args.get('q')
    commessa_id = request.args.get('commessa_id', type=int)
    dipendenti = db.get_all_dipendenti(include_inactive=include_inactive, search=search, commessa_id=commessa_id)
    conteggi = db.count_assegnazioni_bulk()
    for d in dipendenti:
        d.update(conteggi.get(d['id'], {'assistiti': 0, 'ore_assegnate': 0}))
    return jsonify(dipendenti)


@app.route('/api/dipendenti', methods=['POST'])
def api_create_dipendente():
    """Crea un dipendente."""
    data = request.json or {}
    try:
        dip_id = db.create_dipendente(data)
        db.log_audit('create', 'dipendente', dip_id, f"{data.get('cognome','')} {data.get('nome','')}")
        return jsonify({'success': True, 'id': dip_id})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/dipendenti/<int:dipendente_id>', methods=['GET'])
def api_get_dipendente(dipendente_id):
    d = db.get_dipendente(dipendente_id)
    if not d:
        return jsonify({'error': 'Dipendente non trovato'}), 404
    d['assistiti'] = db.get_assistiti_dipendente(dipendente_id)
    # solo le ore (il conteggio 'assistiti' lo ricava il frontend dalla lista)
    d['ore_assegnate'] = db.count_assegnazioni_dipendente(dipendente_id)['ore_assegnate']
    return jsonify(d)


@app.route('/api/dipendenti/<int:dipendente_id>', methods=['PUT'])
def api_update_dipendente(dipendente_id):
    data = request.json or {}
    try:
        db.update_dipendente(dipendente_id, data)
        db.log_audit('update', 'dipendente', dipendente_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/dipendenti/<int:dipendente_id>', methods=['DELETE'])
def api_delete_dipendente(dipendente_id):
    db.delete_dipendente(dipendente_id)
    db.log_audit('delete', 'dipendente', dipendente_id)
    return jsonify({'success': True})


@app.route('/api/import-dipendenti/preview', methods=['POST'])
def api_preview_dipendenti():
    """Anteprima import anagrafica dipendenti: quanti nuovi/da aggiornare."""
    if 'file' not in request.files:
        return jsonify({'error': 'Nessun file caricato'}), 400
    file = request.files['file']
    if file.filename == '' or not file.filename.lower().endswith(('.xlsx', '.xls')):
        return jsonify({'error': 'File non valido. Usa .xlsx o .xls'}), 400
    try:
        records = import_dipendenti.parse_workbook(file.read())
    except Exception as e:
        logger.error(f"Errore anteprima dipendenti: {e}", exc_info=True)
        return jsonify({'error': f'Errore lettura file: {str(e)}'}), 500

    # Abbina agli esistenti (per CF o nome+cognome) per contare nuovi/da aggiornare
    esistenti = db.get_all_dipendenti(include_inactive=True)
    per_cf = {import_dipendenti.chiave_cf(d['codice_fiscale']): d for d in esistenti if d.get('codice_fiscale')}
    per_nome = {import_dipendenti.chiave_nome(d['nome'], d['cognome']): d for d in esistenti}

    nuovi = aggiornati = 0
    colonne_extra = set()
    esempi = []
    for r in records:
        cf = import_dipendenti.chiave_cf(r.get('codice_fiscale'))
        if cf:
            match = per_cf.get(cf)
        else:
            match = per_nome.get(import_dipendenti.chiave_nome(r.get('nome', ''), r.get('cognome', '')))
        if match:
            aggiornati += 1
        else:
            nuovi += 1
        colonne_extra.update((r.get('extra') or {}).keys())
        if len(esempi) < 12:
            esempi.append({
                'nome': f"{r.get('cognome','')} {r.get('nome','')}".strip(),
                'cf': r.get('codice_fiscale') or '',
                'qualifica': r.get('qualifica') or '',
                'ore': r.get('ore_contrattuali_settimanali'),
                'stato': 'aggiorna' if match else 'nuovo',
            })

    return jsonify({
        'success': True,
        'totale': len(records),
        'nuovi': nuovi,
        'aggiornati': aggiornati,
        'colonne_extra': sorted(colonne_extra),
        'esempi': esempi,
    })


@app.route('/api/import-dipendenti', methods=['POST'])
def api_import_dipendenti():
    """Importa l'anagrafica dipendenti (crea i nuovi, aggiorna gli esistenti)."""
    if 'file' not in request.files:
        return jsonify({'error': 'Nessun file caricato'}), 400
    file = request.files['file']
    if file.filename == '' or not file.filename.lower().endswith(('.xlsx', '.xls')):
        return jsonify({'error': 'File non valido. Usa .xlsx o .xls'}), 400
    try:
        records = import_dipendenti.parse_workbook(file.read())
        res = db.importa_dipendenti(records)
    except Exception as e:
        logger.error(f"Errore import dipendenti: {e}", exc_info=True)
        return jsonify({'error': f'Errore: {str(e)}'}), 500

    db.log_audit('import_dipendenti', 'dipendente',
                 dettagli=f"{res['creati']} creati, {res['aggiornati']} aggiornati da {file.filename}")
    try:
        with db.get_db_context() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS import_cronologia (
                id INTEGER PRIMARY KEY AUTOINCREMENT, data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                filename TEXT, importati INTEGER DEFAULT 0, aggiornati INTEGER DEFAULT 0,
                errori INTEGER DEFAULT 0, utente TEXT)''')
            conn.execute('''INSERT INTO import_cronologia (filename, importati, aggiornati, errori, utente)
                            VALUES (?, ?, ?, ?, ?)''',
                         (f"[Dipendenti] {file.filename}", res['creati'], res['aggiornati'],
                          len(res['errori']), session.get('username', 'Sistema')))
    except Exception as e:
        logger.warning(f"Cronologia import dipendenti non salvata: {e}")

    return jsonify({'success': True, **res, 'errori_count': len(res['errori']),
                    'errori': res['errori'][:10]})


# ==================== API ASSEGNAZIONI (utente <-> operatore) ====================

@app.route('/api/utente/<int:utente_id>/assegnazioni', methods=['GET'])
def api_get_assegnazioni_utente(utente_id):
    """Operatori assegnati a un assistito + bilancio ore."""
    return jsonify({
        'assegnazioni': db.get_assegnazioni_utente(utente_id),
        'bilancio': db.get_bilancio_assegnazioni_utente(utente_id),
    })


@app.route('/api/utente/<int:utente_id>/assegnazioni', methods=['POST'])
def api_create_assegnazione(utente_id):
    data = request.json or {}
    dipendente_id = data.get('dipendente_id')
    if not dipendente_id:
        return jsonify({'error': 'Operatore obbligatorio'}), 400
    try:
        ore = float(data.get('ore_settimanali') or 0)
    except (ValueError, TypeError):
        return jsonify({'error': 'Ore non valide'}), 400
    try:
        aid = db.create_assegnazione(utente_id, dipendente_id, ore,
                                     data.get('valido_da'), data.get('valido_a'), data.get('note'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    db.log_audit('create', 'assegnazione', aid, f"utente {utente_id} -> dip {dipendente_id} ({ore}h)")
    return jsonify({'success': True, 'id': aid, 'bilancio': db.get_bilancio_assegnazioni_utente(utente_id)})


@app.route('/api/assegnazioni/<int:assegnazione_id>', methods=['PUT'])
def api_update_assegnazione(assegnazione_id):
    data = request.json or {}
    ore = data.get('ore_settimanali')
    try:
        db.update_assegnazione(
            assegnazione_id,
            ore_settimanali=float(ore) if ore is not None else None,
            valido_da=data.get('valido_da'),
            valido_a=data.get('valido_a'),
            note=data.get('note'),
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'success': True})


@app.route('/api/assegnazioni/<int:assegnazione_id>', methods=['DELETE'])
def api_delete_assegnazione(assegnazione_id):
    db.delete_assegnazione(assegnazione_id)
    return jsonify({'success': True})


# ==================== API TURNI ====================

@app.route('/api/dipendenti/<int:dipendente_id>/turni', methods=['GET'])
def api_get_turni_dipendente(dipendente_id):
    return jsonify({
        'turni': db.get_turni_dipendente(dipendente_id),
        'ore_pianificate': db.ore_settimanali_pianificate(dipendente_id),
        'giorni': db.GIORNI_NOMI,
    })


@app.route('/api/dipendenti/<int:dipendente_id>/turni', methods=['POST'])
def api_create_turno(dipendente_id):
    d = request.json or {}
    if d.get('giorno') is None or not d.get('ora_inizio') or not d.get('ora_fine'):
        return jsonify({'error': 'Giorno e orari sono obbligatori'}), 400
    try:
        tid = db.create_turno(dipendente_id, d['giorno'], d['ora_inizio'], d['ora_fine'],
                              d.get('scuola_id'), d.get('utente_id'),
                              d.get('valido_da'), d.get('valido_a'), d.get('note'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'success': True, 'id': tid})


@app.route('/api/turni/<int:turno_id>', methods=['PUT'])
def api_update_turno(turno_id):
    try:
        db.update_turno(turno_id, **(request.json or {}))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'success': True})


@app.route('/api/turni/<int:turno_id>', methods=['DELETE'])
def api_delete_turno(turno_id):
    db.delete_turno(turno_id)
    return jsonify({'success': True})


@app.route('/api/turni/giorno')
def api_turni_giorno():
    """Vista giornaliera: tutti i turni di un giorno della settimana."""
    giorno = request.args.get('giorno', type=int)
    data = request.args.get('data')
    scuola_id = request.args.get('scuola_id', type=int)
    if giorno is None:
        return jsonify({'error': 'Giorno obbligatorio'}), 400
    return jsonify(db.get_turni_giorno(giorno, data=data, scuola_id=scuola_id))


# ==================== API ASSENZE DIPENDENTI ====================

@app.route('/api/dipendenti/<int:dipendente_id>/assenze', methods=['GET'])
def api_get_assenze_dip(dipendente_id):
    return jsonify(db.get_assenze_dipendente(dipendente_id))


@app.route('/api/dipendenti/<int:dipendente_id>/assenze', methods=['POST'])
def api_create_assenza_dip(dipendente_id):
    d = request.json or {}
    if not d.get('data_inizio'):
        return jsonify({'error': 'Data inizio obbligatoria'}), 400
    try:
        aid = db.create_assenza_dipendente(dipendente_id, d['data_inizio'], d.get('data_fine'),
                                           d.get('tipo'), d.get('motivazione'), d.get('note'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    # Genera automaticamente le sostituzioni da coprire per i turni nel periodo
    create = db.crea_sostituzioni_per_assenza(aid)
    db.log_audit('create', 'assenza_dipendente', aid, f"dip {dipendente_id}, {create} turni da coprire")
    return jsonify({'success': True, 'id': aid, 'turni_da_coprire': create})


@app.route('/api/assenze-dipendenti/<int:assenza_id>', methods=['DELETE'])
def api_delete_assenza_dip(assenza_id):
    db.delete_assenza_dipendente(assenza_id)
    return jsonify({'success': True})


# ==================== API SOSTITUZIONI ====================

@app.route('/api/sostituzioni', methods=['GET'])
def api_get_sostituzioni():
    return jsonify(db.get_sostituzioni(
        data_inizio=request.args.get('da'),
        data_fine=request.args.get('a'),
        solo_da_coprire=request.args.get('da_coprire') == '1',
    ))


@app.route('/api/sostituzioni/<int:sostituzione_id>/candidati', methods=['GET'])
def api_candidati_sostituzione(sostituzione_id):
    s = db.get_sostituzione(sostituzione_id)
    if not s:
        return jsonify({'error': 'Sostituzione non trovata'}), 404
    candidati = db.suggerisci_sostituti(s.get('scuola_id'), s['giorno'], s['ora_inizio'],
                                        s['ora_fine'], s['data'], escludi_id=s['assente_id'])
    return jsonify({'candidati': candidati})


@app.route('/api/sostituzioni/<int:sostituzione_id>/assegna', methods=['POST'])
def api_assegna_sostituto(sostituzione_id):
    d = request.json or {}
    if not d.get('sostituto_id'):
        return jsonify({'error': 'Sostituto obbligatorio'}), 400
    try:
        db.assegna_sostituto(sostituzione_id, d['sostituto_id'])
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'success': True})


@app.route('/api/sostituzioni/<int:sostituzione_id>/annulla', methods=['POST'])
def api_annulla_sostituto(sostituzione_id):
    db.annulla_sostituto(sostituzione_id)
    return jsonify({'success': True})


@app.route('/api/utenti', methods=['GET'])
def api_get_utenti():
    """Ottiene lista utenti con paginazione opzionale"""
    commessa = request.args.get('commessa')
    scuola_id = request.args.get('scuola_id')
    page = request.args.get('page', type=int)
    limit = request.args.get('limit', default=50, type=int)

    # Limita il numero massimo di elementi per pagina
    limit = min(limit, 200)

    utenti = db.get_all_utenti(commessa, scuola_id, page=page, limit=limit)

    # Se paginato, restituisci anche i metadati
    if page is not None:
        total = db.count_utenti(commessa, scuola_id)
        return jsonify({
            'data': [dict(u) for u in utenti],
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total,
                'pages': (total + limit - 1) // limit
            }
        })

    return jsonify([dict(u) for u in utenti])


@app.route('/api/scuole', methods=['GET'])
def api_get_scuole():
    """Ottiene lista scuole"""
    commessa = request.args.get('commessa')
    scuole = db.get_all_scuole(commessa)
    return jsonify(scuole)


@app.route('/api/utenti', methods=['POST'])
def api_create_utente():
    """Crea un nuovo utente manualmente"""
    data = request.json or {}

    # Validazione
    errors = []

    commessa, err = validate_string(data.get('commessa'), 'Commessa', config.MAX_COMMESSA_LENGTH)
    if err: errors.append(err)

    scuola_nome, err = validate_string(data.get('scuola'), 'Scuola', config.MAX_SCUOLA_LENGTH)
    if err: errors.append(err)

    nome, err = validate_string(data.get('nome'), 'Nome', config.MAX_NOME_LENGTH)
    if err: errors.append(err)

    cognome, err = validate_string(data.get('cognome'), 'Cognome', config.MAX_COGNOME_LENGTH, required=False)
    if err: errors.append(err)

    monte_ore, err = validate_number(data.get('monte_ore'), 'Monte ore', 0, config.MAX_ORE_SETTIMANALI)
    if err: errors.append(err)

    if errors:
        return jsonify({'error': '; '.join(errors)}), 400

    try:
        scuola_id = db.get_or_create_scuola(commessa, scuola_nome)
        if not scuola_id:
            return jsonify({'error': f'Commessa "{commessa}" non valida'}), 400

        utente_id = db.get_or_create_utente(scuola_id, nome, cognome, monte_ore)
        db.log_audit('creazione', 'utente', utente_id, f'{nome} {cognome}')
        logger.info(f"Utente creato: {nome} {cognome} (ID: {utente_id})")

        return jsonify({'success': True, 'utente_id': utente_id})
    except Exception as e:
        logger.error(f"Errore creazione utente: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/utenti/<int:utente_id>', methods=['PUT'])
def api_update_utente(utente_id):
    """Aggiorna un utente esistente"""
    data = request.json or {}

    try:
        with db.get_db_context() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM utenti WHERE id = ?", (utente_id,))
            utente = cursor.fetchone()
            if not utente:
                return jsonify({'error': 'Utente non trovato'}), 404

            dati_precedenti = dict(utente)

            # Salva per undo
            push_undo('update_utente', {
                'id': utente_id,
                'dati_precedenti': dati_precedenti
            })

            updates = []
            params = []
            errors = []

            if 'nome' in data and data['nome']:
                nome, err = validate_string(data['nome'], 'Nome', config.MAX_NOME_LENGTH)
                if err:
                    errors.append(err)
                else:
                    updates.append("nome = ?")
                    params.append(nome)

            if 'cognome' in data:
                cognome, err = validate_string(data['cognome'], 'Cognome', config.MAX_COGNOME_LENGTH, required=False)
                if err:
                    errors.append(err)
                else:
                    updates.append("cognome = ?")
                    params.append(cognome)

            if 'monte_ore' in data and data['monte_ore'] is not None:
                monte_ore, err = validate_number(data['monte_ore'], 'Monte ore', 0, config.MAX_ORE_SETTIMANALI)
                if err:
                    errors.append(err)
                else:
                    updates.append("monte_ore_settimanale = ?")
                    params.append(monte_ore)

            if 'lista_attesa' in data:
                updates.append("lista_attesa = ?")
                params.append(data['lista_attesa'] if data['lista_attesa'] else None)

            # Gestione periodo di validità (data_inizio, data_fine)
            if 'data_inizio' in data:
                # Formato atteso: 'YYYY-MM' o null/vuoto per rimuovere
                data_inizio = data['data_inizio'].strip() if data['data_inizio'] else None
                if data_inizio and not re.match(r'^\d{4}-\d{2}$', data_inizio):
                    errors.append("data_inizio deve essere nel formato YYYY-MM")
                else:
                    updates.append("data_inizio = ?")
                    params.append(data_inizio)

            if 'data_fine' in data:
                # Formato atteso: 'YYYY-MM' o null/vuoto per rimuovere
                data_fine = data['data_fine'].strip() if data['data_fine'] else None
                if data_fine and not re.match(r'^\d{4}-\d{2}$', data_fine):
                    errors.append("data_fine deve essere nel formato YYYY-MM")
                else:
                    updates.append("data_fine = ?")
                    params.append(data_fine)

            if errors:
                return jsonify({'error': '; '.join(errors)}), 400

            if 'nome' in data or 'cognome' in data:
                # Usa "or" per gestire sia valori None espliciti nel JSON che valori mancanti
                nome = (data.get('nome') or utente['nome'] or '').strip()
                cognome = (data.get('cognome') or utente['cognome'] or '').strip()
                nome_puntato = db.punteggia_nome(nome, cognome)
                updates.append("nome_puntato = ?")
                params.append(nome_puntato)

            if not updates:
                return jsonify({'success': True, 'message': 'Nessuna modifica da applicare'})

            params.append(utente_id)
            cursor.execute(f"UPDATE utenti SET {', '.join(updates)} WHERE id = ?", params)

        db.log_audit('modifica', 'utente', utente_id, dettagli=f'Aggiornamento utente', dati_precedenti=dati_precedenti, dati_nuovi=data)
        logger.info(f"Utente aggiornato: ID {utente_id}")

        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Errore aggiornamento utente {utente_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/utenti/<int:utente_id>', methods=['DELETE'])
def api_delete_utente(utente_id):
    """Elimina un utente"""
    try:
        with db.get_db_context() as conn:
            cursor = conn.cursor()

            # Recupera info utente per undo e audit
            cursor.execute("SELECT * FROM utenti WHERE id = ?", (utente_id,))
            utente = cursor.fetchone()

            # Salva dati per undo
            if utente:
                utente_data = dict(utente)
                cursor.execute("SELECT * FROM rendicontazione WHERE utente_id = ?", (utente_id,))
                rend_data = [dict(r) for r in cursor.fetchall()]
                push_undo('delete_utente', {
                    'utente': utente_data,
                    'rendicontazioni': rend_data
                })

            cursor.execute("DELETE FROM rendicontazione WHERE utente_id = ?", (utente_id,))
            cursor.execute("DELETE FROM utenti WHERE id = ?", (utente_id,))

        nome_utente = f"{utente['nome']} {utente['cognome']}" if utente else f"ID {utente_id}"
        db.log_audit('eliminazione', 'utente', utente_id, f'Eliminato utente {nome_utente}')
        logger.info(f"Utente eliminato: {nome_utente} (ID: {utente_id})")

        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Errore eliminazione utente {utente_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/utenti/bulk', methods=['PUT'])
def api_bulk_update_utenti():
    """Aggiornamento bulk di utenti (monte ore o lista attesa)"""
    data = request.json or {}
    updates = data.get('updates', [])

    if not updates:
        return jsonify({'error': 'Nessun aggiornamento specificato'}), 400

    if len(updates) > 200:
        return jsonify({'error': 'Massimo 200 aggiornamenti per richiesta'}), 400

    successi = 0
    errori = []

    for upd in updates:
        uid = upd.get('id')
        if not uid:
            continue
        try:
            set_parts = []
            params = []

            if 'monte_ore' in upd and upd['monte_ore'] is not None:
                ore, err = validate_number(upd['monte_ore'], 'Monte ore', 0, config.MAX_ORE_SETTIMANALI)
                if err:
                    errori.append(f'ID {uid}: {err}')
                    continue
                set_parts.append('monte_ore_settimanale = ?')
                params.append(ore)

            if 'lista_attesa' in upd:
                set_parts.append('lista_attesa = ?')
                params.append(upd['lista_attesa'] if upd['lista_attesa'] else None)

            if set_parts:
                with db.get_db_context() as conn:
                    cursor = conn.cursor()
                    params.append(uid)
                    cursor.execute(f"UPDATE utenti SET {', '.join(set_parts)} WHERE id = ?", params)
                successi += 1
        except Exception as e:
            errori.append(f'ID {uid}: {str(e)}')

    db.log_audit('bulk_modifica', 'utenti', dettagli=f'{successi} utenti aggiornati in bulk')
    logger.info(f"Bulk update: {successi} successi, {len(errori)} errori")

    return jsonify({
        'success': True,
        'aggiornati': successi,
        'errori': errori
    })


@app.route('/api/utenti/bulk', methods=['DELETE'])
def api_bulk_delete_utenti():
    """Eliminazione bulk di utenti"""
    data = request.json or {}
    ids = data.get('ids', [])

    if not ids:
        return jsonify({'error': 'Nessun utente specificato'}), 400

    eliminati = 0
    for uid in ids:
        try:
            with db.get_db_context() as conn:
                cursor = conn.cursor()

                # Salva dati per undo
                cursor.execute("SELECT * FROM utenti WHERE id = ?", (uid,))
                utente = cursor.fetchone()
                if utente:
                    utente_data = dict(utente)
                    cursor.execute("SELECT * FROM rendicontazione WHERE utente_id = ?", (uid,))
                    rend_data = [dict(r) for r in cursor.fetchall()]
                    push_undo('delete_utente', {
                        'utente': utente_data,
                        'rendicontazioni': rend_data
                    })

                cursor.execute("DELETE FROM rendicontazione WHERE utente_id = ?", (uid,))
                cursor.execute("DELETE FROM utenti WHERE id = ?", (uid,))
            eliminati += 1
        except Exception as e:
            logger.error(f"Errore bulk delete utente {uid}: {e}")

    db.log_audit('bulk_eliminazione', 'utenti', dettagli=f'{eliminati} utenti eliminati in bulk')
    return jsonify({'success': True, 'eliminati': eliminati})


@app.route('/api/utenti/export-csv')
def api_export_utenti_csv():
    """Esporta lista utenti in formato CSV"""
    commessa = request.args.get('commessa')

    with db.get_db_context() as conn:
        cursor = conn.cursor()

        query = '''
            SELECT u.id, u.nome, u.cognome, u.monte_ore_settimanale, u.lista_attesa,
                   u.data_inizio, u.data_fine, u.attivo,
                   s.nome_completo as scuola, c.nome as commessa
            FROM utenti u
            LEFT JOIN scuole s ON u.scuola_id = s.id
            LEFT JOIN commesse c ON s.commessa_id = c.id
            WHERE 1=1
        '''
        params = []
        if commessa:
            query += ' AND c.nome = ?'
            params.append(commessa)
        query += ' ORDER BY u.cognome, u.nome'

        cursor.execute(query, params)
        utenti = cursor.fetchall()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['nome', 'cognome', 'scuola', 'monte_ore', 'commessa', 'lista_attesa', 'data_inizio', 'data_fine', 'attivo'])

    for u in utenti:
        writer.writerow([
            u['nome'], u['cognome'], u['scuola'], u['monte_ore_settimanale'],
            u['commessa'], u['lista_attesa'] or '', u['data_inizio'] or '', u['data_fine'] or '',
            'si' if u['attivo'] else 'no'
        ])

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = 'attachment; filename=utenti_export.csv'
    return response


@app.route('/api/utenti/import-csv', methods=['POST'])
def api_import_utenti_csv():
    """Importa utenti da file CSV"""
    if 'file' not in request.files:
        return jsonify({'error': 'Nessun file caricato'}), 400

    file = request.files['file']
    mode = request.form.get('mode', 'add')  # 'add' o 'update'

    try:
        content = file.read().decode('utf-8-sig')  # utf-8-sig per gestire BOM
        reader = csv.DictReader(StringIO(content))

        aggiunti = 0
        aggiornati = 0
        errori = []

        with db.get_db_context() as conn:
            cursor = conn.cursor()

            for i, row in enumerate(reader, start=2):
                try:
                    nome = row.get('nome', '').strip()
                    cognome = row.get('cognome', '').strip()
                    scuola = row.get('scuola', '').strip()
                    monte_ore = float(row.get('monte_ore', 0) or 0)
                    commessa = row.get('commessa', '').strip()

                    if not nome:
                        errori.append(f"Riga {i}: nome mancante")
                        continue

                    # Trova o crea scuola
                    cursor.execute('''
                        SELECT s.id FROM scuole s
                        JOIN commesse c ON s.commessa_id = c.id
                        WHERE s.nome_completo = ? AND c.nome = ?
                    ''', (scuola, commessa))
                    scuola_row = cursor.fetchone()

                    if not scuola_row:
                        # Trova commessa
                        cursor.execute("SELECT id FROM commesse WHERE nome = ?", (commessa,))
                        comm = cursor.fetchone()
                        if not comm:
                            errori.append(f"Riga {i}: commessa '{commessa}' non trovata")
                            continue
                        # Crea scuola
                        cursor.execute("INSERT INTO scuole (nome_completo, commessa_id) VALUES (?, ?)", (scuola, comm['id']))
                        scuola_id = cursor.lastrowid
                    else:
                        scuola_id = scuola_row['id']

                    # Verifica se utente esiste
                    cursor.execute("SELECT id FROM utenti WHERE nome = ? AND cognome = ? AND scuola_id = ?", (nome, cognome, scuola_id))
                    existing = cursor.fetchone()

                    if existing and mode == 'update':
                        cursor.execute("UPDATE utenti SET monte_ore_settimanale = ? WHERE id = ?", (monte_ore, existing['id']))
                        aggiornati += 1
                    elif not existing:
                        nome_puntato = db.punteggia_nome(nome, cognome)
                        cursor.execute('''
                            INSERT INTO utenti (nome, cognome, nome_puntato, monte_ore_settimanale, scuola_id, attivo, data_inserimento)
                            VALUES (?, ?, ?, ?, ?, 1, ?)
                        ''', (nome, cognome, nome_puntato, monte_ore, scuola_id, datetime.now().isoformat()))
                        aggiunti += 1

                except Exception as e:
                    errori.append(f"Riga {i}: {str(e)}")

        return jsonify({
            'success': True,
            'aggiunti': aggiunti,
            'aggiornati': aggiornati,
            'errori': errori[:10]  # Max 10 errori
        })

    except Exception as e:
        return jsonify({'error': f'Errore elaborazione CSV: {str(e)}'}), 400


@app.route('/api/utenti/<int:utente_id>/duplica', methods=['POST'])
def api_duplica_utente(utente_id):
    """Duplica un utente"""
    with db.get_db_context() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM utenti WHERE id = ?", (utente_id,))
        utente = cursor.fetchone()

        if not utente:
            return jsonify({'error': 'Utente non trovato'}), 404

        nuovo_nome = f"{utente['nome']} (copia)"
        nome_puntato = db.punteggia_nome(nuovo_nome, utente['cognome'])

        cursor.execute('''
            INSERT INTO utenti (nome, cognome, nome_puntato, monte_ore_settimanale, scuola_id, lista_attesa, attivo, data_inserimento)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
        ''', (nuovo_nome, utente['cognome'], nome_puntato, utente['monte_ore_settimanale'], utente['scuola_id'], utente['lista_attesa'], datetime.now().isoformat()))

        nuovo_id = cursor.lastrowid

    db.log_audit('duplica', 'utente', nuovo_id, dettagli=f'Duplicato da utente {utente_id}')
    return jsonify({'success': True, 'nuovo_id': nuovo_id})


@app.route('/api/utenti/<int:utente_id>/cambio-scuola', methods=['POST'])
def api_cambio_scuola(utente_id):
    """Cambia la scuola di un utente"""
    data = request.json or {}
    nuova_scuola_id = data.get('scuola_id')

    if not nuova_scuola_id:
        return jsonify({'error': 'scuola_id richiesto'}), 400

    with db.get_db_context() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM utenti WHERE id = ?", (utente_id,))
        utente = cursor.fetchone()
        if not utente:
            return jsonify({'error': 'Utente non trovato'}), 404

        cursor.execute("SELECT id FROM scuole WHERE id = ?", (nuova_scuola_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'Scuola non trovata'}), 404

        vecchia_scuola = utente['scuola_id']
        cursor.execute("UPDATE utenti SET scuola_id = ? WHERE id = ?", (nuova_scuola_id, utente_id))

    db.log_audit('cambio_scuola', 'utente', utente_id, dettagli=f'Da scuola {vecchia_scuola} a {nuova_scuola_id}')
    return jsonify({'success': True})


@app.route('/api/utenti/<int:utente_id>/storico-monte-ore')
def api_storico_monte_ore(utente_id):
    """Ottiene lo storico delle modifiche al monte ore"""
    with db.get_db_context() as conn:
        cursor = conn.cursor()

        # Info utente
        cursor.execute("SELECT nome, cognome, monte_ore_settimanale FROM utenti WHERE id = ?", (utente_id,))
        utente = cursor.fetchone()
        if not utente:
            return jsonify({'error': 'Utente non trovato'}), 404

        # Cerca nei log di audit le modifiche al monte ore
        cursor.execute('''
            SELECT timestamp, dati_precedenti, dati_nuovi, dettagli
            FROM audit_log
            WHERE entita = 'utente' AND entita_id = ?
            AND (dati_nuovi LIKE '%monte_ore%' OR dettagli LIKE '%monte%')
            ORDER BY timestamp DESC
            LIMIT 20
        ''', (utente_id,))

        storico = []
        for row in cursor.fetchall():
            try:
                import json
                prec = json.loads(row['dati_precedenti']) if row['dati_precedenti'] else {}
                nuov = json.loads(row['dati_nuovi']) if row['dati_nuovi'] else {}
                storico.append({
                    'timestamp': row['timestamp'],
                    'monte_ore_precedente': prec.get('monte_ore_settimanale') or prec.get('monte_ore'),
                    'monte_ore_nuovo': nuov.get('monte_ore_settimanale') or nuov.get('monte_ore'),
                    'dettagli': row['dettagli']
                })
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

        utente_info = {
            'nome': utente['nome'],
            'cognome': utente['cognome'],
            'monte_ore_attuale': utente['monte_ore_settimanale']
        }

    return jsonify({
        'utente': utente_info,
        'storico': storico
    })


# ==================== VARIAZIONI MONTE ORE ====================

@app.route('/api/utenti/<int:utente_id>/variazioni-monte-ore')
@login_required
def api_get_variazioni_monte_ore(utente_id):
    """Lista variazioni monte ore di un utente"""
    variazioni = db.get_variazioni_monte_ore(utente_id)
    return jsonify({'variazioni': variazioni})


@app.route('/api/utenti/<int:utente_id>/variazioni-monte-ore', methods=['POST'])
@login_required
def api_add_variazione_monte_ore(utente_id):
    """Aggiunge una variazione monte ore"""
    data = request.json or {}

    monte_ore, err = validate_number(data.get('monte_ore'), 'Monte ore', 0, config.MAX_ORE_SETTIMANALI)
    if err:
        return jsonify({'error': err}), 400

    mese_inizio = (data.get('mese_inizio') or '').strip()
    if not mese_inizio or len(mese_inizio) != 7:
        return jsonify({'error': 'Mese inizio obbligatorio (formato YYYY-MM)'}), 400

    nota = (data.get('nota') or '').strip()[:500] or None

    var_id = db.add_variazione_monte_ore(utente_id, monte_ore, mese_inizio, nota)
    db.log_audit('variazione_monte_ore', 'utente', utente_id,
                 dettagli=f'Aggiunta variazione: {monte_ore}h da {mese_inizio}')
    return jsonify({'success': True, 'id': var_id})


@app.route('/api/variazioni-monte-ore/<int:variazione_id>', methods=['PUT'])
@login_required
def api_update_variazione_monte_ore(variazione_id):
    """Modifica una variazione monte ore"""
    data = request.json or {}

    kwargs = {}
    if 'monte_ore' in data and data['monte_ore'] is not None:
        monte_ore, err = validate_number(data['monte_ore'], 'Monte ore', 0, config.MAX_ORE_SETTIMANALI)
        if err:
            return jsonify({'error': err}), 400
        kwargs['monte_ore'] = monte_ore

    if 'mese_inizio' in data:
        mese_inizio = (data['mese_inizio'] or '').strip()
        if not mese_inizio or len(mese_inizio) != 7:
            return jsonify({'error': 'Mese inizio non valido'}), 400
        kwargs['mese_inizio'] = mese_inizio

    if 'nota' in data:
        kwargs['nota'] = (data['nota'] or '').strip()[:500] or None

    if not kwargs:
        return jsonify({'error': 'Nessun campo da aggiornare'}), 400

    ok = db.update_variazione_monte_ore(variazione_id, **kwargs)
    if not ok:
        return jsonify({'error': 'Variazione non trovata'}), 404
    return jsonify({'success': True})


@app.route('/api/variazioni-monte-ore/<int:variazione_id>', methods=['DELETE'])
@login_required
def api_delete_variazione_monte_ore(variazione_id):
    """Elimina una variazione monte ore"""
    ok = db.delete_variazione_monte_ore(variazione_id)
    if not ok:
        return jsonify({'error': 'Variazione non trovata'}), 404
    return jsonify({'success': True})


@app.route('/api/reset', methods=['POST'])
def api_reset_data():
    """Reset completo dei dati - RICHIEDE conferma esplicita"""
    data = request.json or {}
    reset_type = data.get('type', 'all')
    confirm_text = data.get('confirm', '')

    # Richiedi conferma esplicita: l'utente deve digitare "CONFERMA"
    if confirm_text != 'CONFERMA':
        return jsonify({'error': 'Per procedere, devi confermare digitando "CONFERMA"'}), 400

    valid_types = ['all', 'rendicontazioni', 'utenti']
    if reset_type not in valid_types:
        return jsonify({'error': 'Tipo reset non valido'}), 400

    try:
        # Backup automatico prima del reset
        backup_name = db.create_backup()
        logger.warning(f"RESET richiesto (tipo: {reset_type}). Backup creato: {backup_name}")

        with db.get_db_context() as conn:
            cursor = conn.cursor()

            if reset_type == 'all':
                cursor.execute("DELETE FROM rendicontazione")
                cursor.execute("DELETE FROM utenti")
                cursor.execute("DELETE FROM scuole")
                message = "Tutti i dati sono stati cancellati"
            elif reset_type == 'rendicontazioni':
                cursor.execute("DELETE FROM rendicontazione")
                message = "Tutte le rendicontazioni sono state cancellate"
            elif reset_type == 'utenti':
                cursor.execute("DELETE FROM rendicontazione")
                cursor.execute("DELETE FROM utenti")
                message = "Utenti e rendicontazioni cancellati"

        db.log_audit('reset', 'sistema', dettagli=f'Reset {reset_type}: {message}. Backup: {backup_name}')
        logger.warning(f"Reset completato: {message}")

        return jsonify({'success': True, 'message': message, 'backup': backup_name})
    except Exception as e:
        logger.error(f"Errore reset: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/commesse', methods=['GET'])
def api_get_commesse():
    """Ottiene lista commesse"""
    commesse = db.get_all_commesse()
    return jsonify(commesse)


@app.route('/api/commesse', methods=['POST'])
def api_create_commessa():
    """Crea una nuova commessa"""
    data = request.json or {}
    errors = []

    nome, err = validate_string(data.get('nome'), 'Nome commessa', config.MAX_COMMESSA_LENGTH)
    if err: errors.append(err)

    descrizione, err = validate_string(data.get('descrizione', ''), 'Descrizione', config.MAX_DESCRIZIONE_LENGTH, required=False)
    if err: errors.append(err)

    colore = data.get('colore', '#6366f1')
    if colore and not re.match(r'^#[0-9a-fA-F]{6}$', colore):
        errors.append('Colore non valido (formato: #RRGGBB)')

    if errors:
        return jsonify({'error': '; '.join(errors)}), 400

    commessa_id = db.create_commessa(nome, descrizione, colore)
    if not commessa_id:
        return jsonify({'error': 'Commessa gia\' esistente'}), 400

    db.log_audit('creazione', 'commessa', commessa_id, f'Nuova commessa: {nome}')
    logger.info(f"Commessa creata: {nome} (ID: {commessa_id})")

    return jsonify({'success': True, 'id': commessa_id})


@app.route('/api/commesse/<int:commessa_id>', methods=['PUT'])
def api_update_commessa(commessa_id):
    """Aggiorna una commessa"""
    data = request.json or {}
    errors = []

    nome = data.get('nome')
    if nome is not None:
        nome, err = validate_string(nome, 'Nome commessa', config.MAX_COMMESSA_LENGTH)
        if err: errors.append(err)

    descrizione = data.get('descrizione')
    if descrizione is not None:
        descrizione, err = validate_string(descrizione, 'Descrizione', config.MAX_DESCRIZIONE_LENGTH, required=False)
        if err: errors.append(err)

    colore = data.get('colore')
    if colore and not re.match(r'^#[0-9a-fA-F]{6}$', colore):
        errors.append('Colore non valido (formato: #RRGGBB)')

    if errors:
        return jsonify({'error': '; '.join(errors)}), 400

    db.update_commessa(
        commessa_id,
        nome=nome,
        descrizione=descrizione,
        colore=colore,
        attiva=data.get('attiva')
    )
    return jsonify({'success': True})


@app.route('/api/commesse/<int:commessa_id>', methods=['DELETE'])
def api_delete_commessa(commessa_id):
    """Elimina una commessa (soft delete)"""
    db.delete_commessa(commessa_id)
    return jsonify({'success': True})


@app.route('/api/stats/advanced')
def api_stats_advanced():
    """Statistiche avanzate per dashboard"""
    anno = request.args.get('anno', type=int)
    mese = request.args.get('mese', type=int)
    commessa = request.args.get('commessa')
    stats = db.get_statistiche_avanzate(anno, mese, commessa)
    return jsonify(stats)


@app.route('/api/stats/utenti-meno-ore/<int:anno>/<int:mese>')
def api_utenti_meno_ore(anno, mese):
    """Ottiene i 10 utenti con meno ore erogate rispetto alle previste"""
    utenti = db.get_utenti_meno_ore(anno, mese, limit=10)
    return jsonify(utenti)


@app.route('/api/stats/ore-confronto/<anno_scolastico>')
def api_ore_confronto(anno_scolastico):
    """Ottiene il confronto ore erogate vs previste per l'anno scolastico"""
    commessa = request.args.get('commessa')
    dati = db.get_ore_erogate_vs_previste(anno_scolastico, commessa)
    return jsonify(dati)


@app.route('/api/search')
def api_search():
    """Ricerca globale"""
    query = request.args.get('q', '').strip().lower()
    if len(query) < 2:
        return jsonify({'utenti': [], 'scuole': [], 'pages': []})

    # Pagine statiche
    pages = []
    pages_data = [
        {'title': 'Dashboard', 'url': '/', 'keywords': 'home dashboard principale panoramica riepilogo'},
        {'title': 'Import Excel', 'url': '/import', 'keywords': 'import excel carica dati upload file anteprima'},
        {'title': 'Rendicontazione', 'url': '/rendicontazione', 'keywords': 'ore rendicontazione inserisci mensile lavorate pasti'},
        {'title': 'Utenti', 'url': '/utenti', 'keywords': 'utenti gestione elenco operatori bulk modifica'},
        {'title': 'Commesse', 'url': '/commesse', 'keywords': 'commesse progetti gestione contratti lotti'},
        {'title': 'Calendario', 'url': '/calendario', 'keywords': 'calendario giorni lavorativi anno scolastico'},
        {'title': 'Report', 'url': '/report', 'keywords': 'report esporta excel word pdf stampa rendiconto'},
        {'title': 'Statistiche', 'url': '/statistiche', 'keywords': 'statistiche grafici analisi trend confronto'},
        {'title': 'Backup e Ripristino', 'url': '/statistiche', 'keywords': 'backup ripristino salvataggio dati restore'},
        {'title': 'Audit Trail', 'url': '/statistiche', 'keywords': 'audit trail log modifiche cronologia storico'},
    ]
    for p in pages_data:
        if query in p['keywords'] or query in p['title'].lower():
            pages.append({'title': p['title'], 'url': p['url']})

    # Cerca utenti
    with db.get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT u.id, u.nome, u.cognome, c.nome as commessa, s.nome_completo as scuola
            FROM utenti u
            JOIN scuole s ON u.scuola_id = s.id
            JOIN commesse c ON s.commessa_id = c.id
            WHERE u.attivo = 1 AND (
                LOWER(u.nome) LIKE ? OR
                LOWER(u.cognome) LIKE ? OR
                LOWER(u.nome || ' ' || u.cognome) LIKE ?
            )
            LIMIT 10
        ''', (f'%{query}%', f'%{query}%', f'%{query}%'))
        utenti = [dict(r) for r in cursor.fetchall()]

        # Cerca scuole
        cursor.execute('''
            SELECT s.id, s.nome_completo, c.nome as commessa
            FROM scuole s
            JOIN commesse c ON s.commessa_id = c.id
            WHERE c.attiva = 1 AND LOWER(s.nome_completo) LIKE ?
            LIMIT 10
        ''', (f'%{query}%',))
        scuole = [dict(r) for r in cursor.fetchall()]

        # Cerca commesse
        cursor.execute('''
            SELECT c.id, c.nome, c.descrizione, c.colore,
                (SELECT COUNT(*) FROM scuole s WHERE s.commessa_id = c.id) as num_scuole
            FROM commesse c
            WHERE c.attiva = 1 AND (LOWER(c.nome) LIKE ? OR LOWER(c.descrizione) LIKE ?)
            LIMIT 5
        ''', (f'%{query}%', f'%{query}%'))
        commesse = [dict(r) for r in cursor.fetchall()]

    return jsonify({
        'pages': pages[:5],
        'utenti': utenti,
        'scuole': scuole,
        'commesse': commesse
    })


@app.route('/api/rendicontazione/<int:anno>/<int:mese>', methods=['GET'])
def api_get_rendicontazione(anno, mese):
    """Ottiene rendicontazione mensile"""
    commessa = request.args.get('commessa')
    dati = db.get_rendicontazione_completa(anno, mese, commessa)
    totali_scuola = db.get_totali_per_scuola(anno, mese, commessa)

    # Calcola totali generali
    totale_generale = {
        'ore_lavorate_60': sum(d['ore_lavorate_60'] or 0 for d in dati),
        'ore_lavorate_100': sum(d['ore_lavorate_100'] or 0 for d in dati),
        'imponibile_100': sum(d['imponibile_100'] or 0 for d in dati),
        'iva_100': sum(d['iva_100'] or 0 for d in dati),
        'totale_100': sum(d['totale_100'] or 0 for d in dati),
        'pasti': sum(d['pasti'] or 0 for d in dati),
        'credito_debito': sum(d['credito_debito'] or 0 for d in dati),
        'num_utenti': len(dati)
    }

    return jsonify({
        'dati': dati,
        'totali_scuola': totali_scuola,
        'totale_generale': totale_generale,
        'mese_nome': MESI_NOME.get(mese, ''),
        'anno': anno
    })


@app.route('/api/rendicontazione/<int:anno>/<int:mese>', methods=['POST'])
def api_update_rendicontazione(anno, mese):
    """Aggiorna rendicontazione per un utente"""
    data = request.json
    utente_id = data.get('utente_id')

    if not utente_id:
        return jsonify({'error': 'utente_id richiesto'}), 400

    # Assicurati che esista la rendicontazione
    db.get_or_create_rendicontazione(utente_id, anno, mese)

    # Aggiorna
    db.update_rendicontazione(
        utente_id, anno, mese,
        ore_lavorate=data.get('ore_lavorate_60'),
        pasti=data.get('pasti'),
        note=data.get('note')
    )

    return jsonify({'success': True})


@app.route('/api/rendicontazione/<int:anno>/<int:mese>/batch', methods=['POST'])
def api_batch_update_rendicontazione(anno, mese):
    """Aggiorna rendicontazione per più utenti in una singola transazione"""
    data = request.json
    updates = data.get('updates', [])

    try:
        aggiornati = db.update_rendicontazione_batch(anno, mese, [
            {
                'utente_id': u.get('utente_id'),
                'ore_lavorate': u.get('ore_lavorate_60'),
                'pasti': u.get('pasti'),
                'note': u.get('note')
            }
            for u in updates
        ])
    except Exception as e:
        return jsonify({'success': False, 'error': f'Salvataggio annullato: {e}'}), 500

    return jsonify({'success': True, 'aggiornati': aggiornati})


@app.route('/api/rendicontazione/<int:anno>/<int:mese>/copia-precedente', methods=['POST'])
def api_copia_mese_precedente(anno, mese):
    """Copia ore dal mese precedente per utenti selezionati o tutti"""
    data = request.json
    utente_ids = data.get('utente_ids', [])  # Se vuoto, copia per tutti
    solo_vuoti = data.get('solo_vuoti', True)  # Copia solo se utente non ha ore

    # Calcola mese precedente
    if mese == 1:
        mese_prec = 12
        anno_prec = anno - 1
    else:
        mese_prec = mese - 1
        anno_prec = anno

    # Ottieni dati mese precedente
    dati_prec = db.get_rendicontazione_completa(anno_prec, mese_prec)
    if not dati_prec:
        return jsonify({'error': 'Nessun dato nel mese precedente', 'copiati': 0}), 404

    # Ottieni dati mese corrente per verificare quali utenti hanno già ore
    dati_corrente = db.get_rendicontazione_completa(anno, mese)
    utenti_con_ore = {d['utente_id'] for d in dati_corrente if (d.get('ore_lavorate_60') or 0) > 0}

    updates = []
    for d in dati_prec:
        uid = d['utente_id']

        # Filtra per utente_ids se specificato
        if utente_ids and uid not in utente_ids:
            continue

        # Salta se utente ha già ore e solo_vuoti è True
        if solo_vuoti and uid in utenti_con_ore:
            continue

        ore_prec = d.get('ore_lavorate_60', 0)
        if ore_prec and ore_prec > 0:
            updates.append({'utente_id': uid, 'ore_lavorate': ore_prec})

    try:
        copiati = db.update_rendicontazione_batch(anno, mese, updates)
    except Exception as e:
        return jsonify({'success': False, 'error': f'Copia annullata: {e}'}), 500

    return jsonify({
        'success': True,
        'copiati': copiati,
        'mese_origine': f"{MESI_NOME.get(mese_prec, '')} {anno_prec}"
    })


@app.route('/api/rendicontazione/<int:anno>/<int:mese>/compila-media', methods=['POST'])
def api_compila_con_media(anno, mese):
    """Compila le ore con la media prevista per utenti senza ore"""
    data = request.json or {}
    utente_ids = data.get('utente_ids', [])  # Se vuoto, compila per tutti senza ore

    dati = db.get_rendicontazione_completa(anno, mese)
    updates = []

    for d in dati:
        uid = d['utente_id']

        # Filtra per utente_ids se specificato
        if utente_ids and uid not in utente_ids:
            continue

        # Solo utenti senza ore
        if (d.get('ore_lavorate_60') or 0) > 0:
            continue

        # Usa la media con assenza come valore predefinito
        media = d.get('media_con_assenza_60', 0)
        if media and media > 0:
            updates.append({'utente_id': uid, 'ore_lavorate': round(media, 2)})

    try:
        compilati = db.update_rendicontazione_batch(anno, mese, updates)
    except Exception as e:
        return jsonify({'success': False, 'error': f'Compilazione annullata: {e}'}), 500

    return jsonify({
        'success': True,
        'compilati': compilati
    })


@app.route('/api/utente/<int:utente_id>/storico')
def api_storico_utente(utente_id):
    """Storico ore degli ultimi N mesi a ritroso, con media prevista e
    credito/debito calcolati per ogni riga (tiene conto delle variazioni
    monte ore). Complementare a `/storico-ore` (vedi nota in api_get_storico_utente)."""
    mesi_da_mostrare = request.args.get('mesi', config.STORICO_MESI_DEFAULT, type=int)

    with db.get_db_context() as conn:
        cursor = conn.cursor()

        # Info utente
        cursor.execute('''
            SELECT u.*, s.nome_completo as scuola, c.nome as commessa
            FROM utenti u
            LEFT JOIN scuole s ON u.scuola_id = s.id
            LEFT JOIN commesse c ON s.commessa_id = c.id
            WHERE u.id = ?
        ''', (utente_id,))
        utente = cursor.fetchone()

        if not utente:
            return jsonify({'error': 'Utente non trovato'}), 404

        # Storico rendicontazione: i giorni effettivi dipendono dal tipo di scuola
        scuola_utente = utente['scuola'] or ''
        is_infanzia = 'INFANZIA' in scuola_utente.upper()
        cursor.execute('''
            SELECT r.*,
                CASE WHEN ? = 1 THEN cal.giorni_lavorativi
                     ELSE COALESCE(cal.giorni_lavorativi_altri, cal.giorni_lavorativi)
                END as giorni_lavorativi
            FROM rendicontazione r
            LEFT JOIN calendario_scolastico cal ON r.mese = cal.mese AND r.anno = cal.anno
            WHERE r.utente_id = ?
            ORDER BY r.anno DESC, r.mese DESC
            LIMIT ?
        ''', (1 if is_infanzia else 0, utente_id, mesi_da_mostrare))

        storico = []
        monte_ore_base = utente['monte_ore_settimanale'] or 0
        variazioni_utente = db.get_variazioni_monte_ore(utente_id)

        def _get_monte_ore_mese(anno_r, mese_r):
            periodo = f"{anno_r:04d}-{mese_r:02d}"
            mo = monte_ore_base
            for v in variazioni_utente:
                if v['mese_inizio'] <= periodo:
                    mo = v['monte_ore']
            return mo

        for r in cursor.fetchall():
            monte_ore = _get_monte_ore_mese(r['anno'], r['mese'])
            giorni = r['giorni_lavorativi'] or config.GIORNI_LAVORATIVI_DEFAULT
            media_60, media_assenza = db.calcola_media_prevista(monte_ore, giorni)
            ore = r['ore_lavorate_60'] or 0
            credito_debito = media_assenza - ore

            storico.append({
                'anno': r['anno'],
                'mese': r['mese'],
                'mese_nome': MESI_NOME.get(r['mese'], ''),
                'ore_lavorate_60': round(ore, 2),
                'ore_lavorate_100': round(ore, 2),
                'media_prevista': round(media_assenza, 2),
                'credito_debito': round(credito_debito, 2),
                'pasti': r['pasti'] or 0,
                'note': r['note']
            })

        utente_info = {
            'id': utente['id'],
            'nome': utente['nome'],
            'cognome': utente['cognome'],
            'monte_ore_settimanale': utente['monte_ore_settimanale'],
            'scuola': utente['scuola'],
            'commessa': utente['commessa']
        }

    return jsonify({
        'utente': utente_info,
        'storico': storico
    })


@app.route('/api/rendicontazione/<int:anno>/<int:mese>/confronto-precedente')
def api_confronto_mese_precedente(anno, mese):
    """Ottiene le differenze di ore rispetto al mese precedente"""
    commessa = request.args.get('commessa')

    # Calcola mese precedente
    if mese == 1:
        mese_prec, anno_prec = 12, anno - 1
    else:
        mese_prec, anno_prec = mese - 1, anno

    dati_corrente = db.get_rendicontazione_completa(anno, mese, commessa)
    dati_prec = db.get_rendicontazione_completa(anno_prec, mese_prec, commessa)

    # Crea mappa ore mese precedente
    ore_prec_map = {d['utente_id']: d.get('ore_lavorate_60', 0) for d in dati_prec}

    differenze = {}
    for d in dati_corrente:
        uid = d['utente_id']
        ore_corr = d.get('ore_lavorate_60', 0) or 0
        ore_prec = ore_prec_map.get(uid, 0) or 0

        if ore_prec > 0:
            diff = ore_corr - ore_prec
            diff_perc = round((diff / ore_prec) * 100, 1) if ore_prec else 0
        else:
            diff = ore_corr
            diff_perc = 100 if ore_corr > 0 else 0

        differenze[uid] = {
            'ore_precedente': round(ore_prec, 2),
            'ore_corrente': round(ore_corr, 2),
            'differenza': round(diff, 2),
            'differenza_perc': diff_perc
        }

    return jsonify({
        'differenze': differenze,
        'mese_precedente': {
            'anno': anno_prec,
            'mese': mese_prec,
            'mese_nome': MESI_NOME.get(mese_prec, '')
        }
    })


@app.route('/api/alerts', methods=['GET'])
def api_get_alerts():
    """Ottiene alert automatici per la dashboard"""
    anno = request.args.get('anno', type=int)
    mese = request.args.get('mese', type=int)

    if not anno or not mese:
        # Default: mese corrente
        from datetime import datetime
        now = datetime.now()
        anno = now.year
        mese = now.month

    alerts = []

    # 1. Utenti senza ore nel mese corrente
    dati = db.get_rendicontazione_completa(anno, mese)
    senza_ore = [d for d in dati if not d.get('ore_lavorate_60') or d['ore_lavorate_60'] == 0]
    if senza_ore:
        alerts.append({
            'type': 'warning',
            'title': f'{len(senza_ore)} utenti senza ore registrate',
            'message': f'Nel mese di {MESI_NOME.get(mese, "")} {anno}',
            'action': '/rendicontazione',
            'action_label': 'Vai a Rendicontazione',
            'count': len(senza_ore)
        })

    # 2. Utenti con ore molto sotto la media (< 50%)
    sotto_media = [d for d in dati
                   if (d.get('ore_lavorate_60') or 0) > 0
                   and (d.get('media_con_assenza_60') or 0) > 0
                   and d['ore_lavorate_60'] < d['media_con_assenza_60'] * 0.5]
    if sotto_media:
        alerts.append({
            'type': 'danger',
            'title': f'{len(sotto_media)} utenti con ore < 50% della media',
            'message': 'Ore erogate significativamente sotto la media prevista',
            'action': '/rendicontazione',
            'action_label': 'Verifica',
            'count': len(sotto_media),
            'utenti': [f"{d['nome']} {d['cognome']}" for d in sotto_media[:5]]
        })

    # 3. Utenti con ore anomale (> 150% della media)
    sopra_media = [d for d in dati
                   if (d.get('ore_lavorate_60') or 0) > 0
                   and (d.get('media_con_assenza_60') or 0) > 0
                   and d['ore_lavorate_60'] > d['media_con_assenza_60'] * 1.5]
    if sopra_media:
        alerts.append({
            'type': 'info',
            'title': f'{len(sopra_media)} utenti con ore > 150% della media',
            'message': 'Verificare se le ore extra sono corrette',
            'action': '/rendicontazione',
            'action_label': 'Verifica',
            'count': len(sopra_media),
            'utenti': [f"{d['nome']} {d['cognome']}" for d in sopra_media[:5]]
        })

    # 4. Verifica calendario - giorni lavorativi non impostati
    anno_scolastico = f"{anno}-{anno+1}" if mese >= 9 else f"{anno-1}-{anno}"
    with db.get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) as count FROM calendario_scolastico
            WHERE anno_scolastico = ? AND giorni_lavorativi > 0
        ''', (anno_scolastico,))
        cal_count = cursor.fetchone()['count']

    if cal_count < 10:  # Meno di 10 mesi configurati
        alerts.append({
            'type': 'warning',
            'title': 'Calendario scolastico incompleto',
            'message': f'Solo {cal_count}/10 mesi configurati per {anno_scolastico}',
            'action': '/calendario',
            'action_label': 'Configura Calendario',
            'count': 10 - cal_count
        })

    # 5. Percentuale completamento mese
    if dati:
        completati = len([d for d in dati if (d.get('ore_lavorate_60') or 0) > 0])
        perc = round((completati / len(dati)) * 100)
        if perc < 100:
            alerts.append({
                'type': 'info',
                'title': f'Completamento mese: {perc}%',
                'message': f'{completati}/{len(dati)} utenti rendicontati',
                'action': '/rendicontazione',
                'action_label': 'Completa',
                'progress': perc
            })

    # 6. Documenti in scadenza nei prossimi 30 giorni
    try:
        docs = db.get_documenti_in_scadenza(giorni=30)
        if docs:
            alerts.append({
                'type': 'warning',
                'title': f'{len(docs)} documenti in scadenza',
                'message': 'Documenti utente in scadenza nei prossimi 30 giorni',
                'count': len(docs),
                'utenti': [f"{d['nome']} {d['cognome']}" for d in docs[:5]]
            })
    except Exception as e:
        logger.warning(f"Alert documenti in scadenza non disponibile: {e}")

    # 7. Budget ore quasi esaurito
    try:
        critici = db.get_utenti_budget_critico(anno_scolastico, 80)
        if critici:
            alerts.append({
                'type': 'danger',
                'title': f"{len(critici)} utenti oltre l'80% del budget ore",
                'message': f'Budget annuale quasi esaurito ({anno_scolastico})',
                'count': len(critici),
                'utenti': [f"{u['nome']} {u['cognome']}" for u in critici[:5]]
            })
    except Exception as e:
        logger.warning(f"Alert budget critici non disponibile: {e}")

    return jsonify({
        'alerts': alerts,
        'anno': anno,
        'mese': mese,
        'mese_nome': MESI_NOME.get(mese, ''),
        'total_alerts': len(alerts)
    })


@app.route('/api/calendario', methods=['GET'])
def api_get_calendario():
    """Ottiene calendario scolastico"""
    anno_scolastico = request.args.get('anno_scolastico', '2025-2026')

    with db.get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM calendario_scolastico
            WHERE anno_scolastico = ?
            ORDER BY anno, mese
        ''', (anno_scolastico,))
        result = cursor.fetchall()

        calendario = []
        for r in result:
            calendario.append({
                'mese': r['mese'],
                'anno': r['anno'],
                'giorni_lavorativi': r['giorni_lavorativi'],
                'giorni_lavorativi_altri': r['giorni_lavorativi_altri'],
                'mese_nome': MESI_NOME.get(r['mese'], '')
            })

    return jsonify({
        'anno_scolastico': anno_scolastico,
        'calendario': calendario
    })


@app.route('/api/calendario', methods=['POST'])
def api_update_calendario():
    """Aggiorna giorni lavorativi (default/infanzia + opzionale altri)"""
    data = request.json
    # giorni_lavorativi_altri e' opzionale: se non passato o None -> non distinzione
    altri = data.get('giorni_lavorativi_altri')
    if altri == '' or altri == 0:
        altri = None
    db.set_calendario(
        data['anno_scolastico'],
        data['mese'],
        data['anno'],
        data['giorni_lavorativi'],
        altri
    )
    return jsonify({'success': True})


@app.route('/api/calendario/<anno_scolastico>/copia-precedente', methods=['POST'])
def api_copia_calendario_precedente(anno_scolastico):
    """Copia i giorni lavorativi dall'anno precedente"""
    try:
        anno_inizio, anno_fine = map(int, anno_scolastico.split('-'))
        anno_precedente = f"{anno_inizio - 1}-{anno_inizio}"

        with db.get_db_context() as conn:
            cursor = conn.cursor()

            # Verifica che l'anno precedente esista
            cursor.execute('''
                SELECT COUNT(*) as count FROM calendario_scolastico
                WHERE anno_scolastico = ?
            ''', (anno_precedente,))
            if cursor.fetchone()['count'] == 0:
                return jsonify({'error': f'Anno {anno_precedente} non trovato'}), 404

            # Ottieni dati dell'anno precedente
            cursor.execute('''
                SELECT mese, giorni_lavorativi, giorni_lavorativi_altri FROM calendario_scolastico
                WHERE anno_scolastico = ?
            ''', (anno_precedente,))
            dati_precedenti = cursor.fetchall()

            copiati = 0
            for row in dati_precedenti:
                mese = row['mese']
                giorni = row['giorni_lavorativi']
                giorni_altri = row['giorni_lavorativi_altri']

                # Calcola l'anno corretto per questo mese
                if mese >= 9:  # Settembre-Dicembre
                    anno = anno_inizio
                else:  # Gennaio-Giugno
                    anno = anno_fine

                # Inserisci o aggiorna
                cursor.execute('''
                    INSERT OR REPLACE INTO calendario_scolastico
                    (anno_scolastico, mese, anno, giorni_lavorativi, giorni_lavorativi_altri)
                    VALUES (?, ?, ?, ?, ?)
                ''', (anno_scolastico, mese, anno, giorni, giorni_altri))
                copiati += 1

        return jsonify({
            'success': True,
            'copiati': copiati,
            'da_anno': anno_precedente
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/calendario/<anno_scolastico>/calcola-auto', methods=['POST'])
def api_calcola_calendario_auto(anno_scolastico):
    """Calcola automaticamente i giorni lavorativi (lun-ven, escluse festivita').
    Per giugno calcola anche giorni_lavorativi_altri fino all'8 giugno (fine scuola
    primaria/secondaria), mentre il campo principale copre fino al 30 giugno (infanzia).
    Per gli altri mesi usa date tipiche italiane (scuole aperte)."""
    try:
        from datetime import date, timedelta
        anno_inizio, anno_fine = map(int, anno_scolastico.split('-'))

        # Festivita' fisse italiane (giorno, mese) escluse dai giorni lavorativi
        FESTIVITA_FISSE = {
            (1, 1),   # Capodanno
            (6, 1),   # Epifania
            (25, 4),  # Liberazione
            (1, 5),   # Festa del Lavoro
            (2, 6),   # Festa della Repubblica
            (29, 6),  # SS. Pietro e Paolo (patrono di Roma)
            (1, 11),  # Ognissanti
            (8, 12),  # Immacolata
            (25, 12), # Natale
            (26, 12), # Santo Stefano
        }

        def calcola_pasqua(anno):
            """Data della domenica di Pasqua (algoritmo di Gauss/Butcher)."""
            a = anno % 19
            b = anno // 100
            c = anno % 100
            d = b // 4
            e = b % 4
            f = (b + 8) // 25
            g = (b - f + 1) // 3
            h = (19 * a + b - d - g + 15) % 30
            i = c // 4
            k = c % 4
            l = (32 + 2 * e + 2 * i - h - k) % 7
            m = (a + 11 * h + 22 * l) // 451
            mese = (h + l - 7 * m + 114) // 31
            giorno = ((h + l - 7 * m + 114) % 31) + 1
            return date(anno, mese, giorno)

        # Vacanze pasquali (calendario Lazio): dal giovedi' santo
        # al martedi' dopo Pasqua, inclusi
        pasqua = calcola_pasqua(anno_fine)
        vacanze_pasquali = set()
        d = pasqua - timedelta(days=3)
        while d <= pasqua + timedelta(days=2):
            vacanze_pasquali.add(d)
            d += timedelta(days=1)

        # Finestre di calendario scolastico (inizio, fine) per ogni mese, inclusive.
        # Valori tipici per regione Lazio; il numero risultante e' comunque editabile manualmente.
        # Per giugno si usano DUE finestre: infanzia fino al 30, altri fino all'8.
        FINESTRE = {
            9:  (date(anno_inizio, 9, 15), date(anno_inizio, 9, 30)),   # inizio scuola ~15/9
            10: (date(anno_inizio, 10, 1), date(anno_inizio, 10, 31)),
            11: (date(anno_inizio, 11, 1), date(anno_inizio, 11, 30)),
            12: (date(anno_inizio, 12, 1), date(anno_inizio, 12, 22)),  # vacanze di Natale
            1:  (date(anno_fine, 1, 8), date(anno_fine, 1, 31)),        # rientro ~8/1
            2:  (date(anno_fine, 2, 1), date(anno_fine, 2, 28)),
            3:  (date(anno_fine, 3, 1), date(anno_fine, 3, 31)),
            4:  (date(anno_fine, 4, 1), date(anno_fine, 4, 30)),
            5:  (date(anno_fine, 5, 1), date(anno_fine, 5, 31)),
            6:  (date(anno_fine, 6, 1), date(anno_fine, 6, 30)),        # infanzia fino al 30
        }
        # Giugno non-infanzia: finisce l'8
        FINESTRA_GIUGNO_ALTRI = (date(anno_fine, 6, 1), date(anno_fine, 6, 8))

        def conta_giorni(inizio, fine):
            """Conta giorni feriali (lun-ven) tra inizio e fine inclusi,
            escluse festivita' fisse e vacanze pasquali."""
            count = 0
            d = inizio
            while d <= fine:
                if (d.weekday() < 5
                        and (d.day, d.month) not in FESTIVITA_FISSE
                        and d not in vacanze_pasquali):
                    count += 1
                d += timedelta(days=1)
            return count

        mesi_calcolati = 0
        MESI_SCOLASTICI_LIST = [
            (9, anno_inizio), (10, anno_inizio), (11, anno_inizio), (12, anno_inizio),
            (1, anno_fine), (2, anno_fine), (3, anno_fine), (4, anno_fine), (5, anno_fine), (6, anno_fine)
        ]

        with db.get_db_context() as conn:
            cursor = conn.cursor()
            for mese, anno in MESI_SCOLASTICI_LIST:
                inizio, fine = FINESTRE[mese]
                giorni = conta_giorni(inizio, fine)

                # Solo a giugno calcoliamo anche la variante non-infanzia
                giorni_altri = None
                if mese == 6:
                    g_inizio, g_fine = FINESTRA_GIUGNO_ALTRI
                    giorni_altri = conta_giorni(g_inizio, g_fine)

                cursor.execute('''
                    INSERT OR REPLACE INTO calendario_scolastico
                    (anno_scolastico, mese, anno, giorni_lavorativi, giorni_lavorativi_altri)
                    VALUES (?, ?, ?, ?, ?)
                ''', (anno_scolastico, mese, anno, giorni, giorni_altri))
                mesi_calcolati += 1

        return jsonify({
            'success': True,
            'mesi_calcolati': mesi_calcolati
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/anni-scolastici', methods=['GET'])
def api_get_anni_scolastici():
    """Ottiene lista anni scolastici"""
    anni = db.get_anni_scolastici()
    return jsonify(anni)


@app.route('/api/anni-scolastici', methods=['POST'])
def api_create_anno_scolastico():
    """Crea nuovo anno scolastico"""
    data = request.json
    anno_inizio = data.get('anno_inizio')
    if not anno_inizio:
        return jsonify({'error': 'anno_inizio richiesto'}), 400

    anno_scolastico = db.create_anno_scolastico(anno_inizio)
    return jsonify({'anno_scolastico': anno_scolastico})





@app.route('/api/stats/utenti-da-completare/<int:anno>/<int:mese>')
def api_utenti_da_completare(anno, mese):
    """Ottiene gli utenti senza ore registrate per il mese specificato"""
    with db.get_db_context() as conn:
        cursor = conn.cursor()

        # Ottieni utenti attivi senza ore per questo mese
        cursor.execute('''
            SELECT u.id, u.nome, u.cognome, u.monte_ore_settimanale,
                   s.nome_completo as scuola, c.nome as commessa
            FROM utenti u
            JOIN scuole s ON u.scuola_id = s.id
            JOIN commesse c ON s.commessa_id = c.id
            LEFT JOIN rendicontazione r ON u.id = r.utente_id
                AND r.anno = ? AND r.mese = ?
            WHERE u.attivo = 1
                AND (r.ore_lavorate_60 IS NULL OR r.ore_lavorate_60 = 0)
            ORDER BY c.nome, s.nome_completo, u.cognome, u.nome
        ''', (anno, mese))

        utenti = []
        for row in cursor.fetchall():
            utenti.append({
                'id': row['id'],
                'nome': row['nome'],
                'cognome': row['cognome'],
                'nome_completo': f"{row['nome']} {row['cognome']}",
                'monte_ore': row['monte_ore_settimanale'],
                'scuola': row['scuola'],
                'commessa': row['commessa']
            })

    return jsonify(utenti)


@app.route('/api/stats')
def api_stats():
    """Statistiche generali"""
    with db.get_db_context() as conn:
        cursor = conn.cursor()

        # Conta utenti
        cursor.execute("SELECT COUNT(*) as count FROM utenti WHERE attivo = 1")
        num_utenti = cursor.fetchone()['count']

        # Conta scuole
        cursor.execute("SELECT COUNT(*) as count FROM scuole")
        num_scuole = cursor.fetchone()['count']

        # Conta utenti per commessa
        cursor.execute('''
            SELECT c.nome, COUNT(u.id) as count
            FROM commesse c
            LEFT JOIN scuole s ON c.id = s.commessa_id
            LEFT JOIN utenti u ON s.id = u.scuola_id AND u.attivo = 1
            GROUP BY c.id
        ''')
        utenti_per_commessa = {r['nome']: r['count'] for r in cursor.fetchall()}

    return jsonify({
        'num_utenti': num_utenti,
        'num_scuole': num_scuole,
        'utenti_per_commessa': utenti_per_commessa
    })


# ==================== BACKUP API ====================

@app.route('/api/backup', methods=['POST'])
def api_create_backup():
    """Crea un backup manuale del database"""
    backup_name = db.create_backup()
    if backup_name:
        db.log_audit('backup', 'sistema', dettagli=f'Backup manuale: {backup_name}')
        return jsonify({'success': True, 'backup': backup_name})
    return jsonify({'error': 'Errore creazione backup'}), 500


@app.route('/api/backup', methods=['GET'])
def api_get_backups():
    """Lista dei backup disponibili"""
    backups = db.get_backups_list()
    return jsonify(backups)


@app.route('/api/backup/restore', methods=['POST'])
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


# ==================== MIGRAZIONE DATI ====================

@app.route('/api/migrazione/esporta')
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


@app.route('/api/migrazione/importa', methods=['POST'])
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


@app.route('/api/migrazione/anteprima', methods=['POST'])
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

@app.route('/api/audit', methods=['GET'])
def api_get_audit():
    """Ottiene l'audit trail"""
    limit = request.args.get('limit', 100, type=int)
    entita = request.args.get('entita')
    audit = db.get_audit_log(limit=min(limit, 500), entita=entita)
    return jsonify(audit)


@app.route('/api/audit/export')
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


# ==================== UNDO ====================

@app.route('/api/undo', methods=['GET'])
def api_get_undo_stack():
    """Mostra le azioni annullabili (ora persistenti)"""
    undo_stack = db.get_undo_stack()
    actions = []
    for i, action in enumerate(undo_stack):
        desc = ''
        if action['type'] == 'delete_utente':
            u = action['data'].get('utente', {})
            desc = f'Eliminazione utente: {u.get("nome", "")} {u.get("cognome", "")}'
        elif action['type'] == 'update_utente':
            desc = f'Modifica utente ID {action["data"].get("id", "?")}'
        actions.append({
            'index': i,
            'tipo': action['type'],
            'descrizione': desc,
            'timestamp': action.get('timestamp', '')
        })
    return jsonify(actions[:10])


@app.route('/api/undo', methods=['POST'])
def api_undo():
    """Annulla l'ultima azione (persistente)"""
    action = db.pop_undo_action()

    if not action:
        return jsonify({'error': 'Nessuna azione da annullare'}), 400

    try:
        with db.get_db_context() as conn:
            cursor = conn.cursor()

            if action['type'] == 'delete_utente':
                u = action['data'].get('utente', {})
                # Ripristina utente
                cursor.execute('''
                    INSERT INTO utenti (id, scuola_id, nome, cognome, nome_puntato,
                        monte_ore_settimanale, attivo, lista_attesa, data_inserimento,
                        data_inizio, data_fine)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (u['id'], u['scuola_id'], u['nome'], u['cognome'],
                      u.get('nome_puntato', ''), u['monte_ore_settimanale'],
                      u.get('attivo', 1), u.get('lista_attesa'),
                      u.get('data_inserimento', datetime.now().isoformat()),
                      u.get('data_inizio'), u.get('data_fine')))

                # Ripristina rendicontazioni
                for r in action['data'].get('rendicontazioni', []):
                    cursor.execute('''
                        INSERT OR IGNORE INTO rendicontazione
                        (utente_id, anno, mese, ore_lavorate_60,
                         pasti, giorni_lavorativi, note, data_inserimento)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (r['utente_id'], r['anno'], r['mese'],
                          r.get('ore_lavorate_60'), r.get('pasti'),
                          r.get('giorni_lavorativi', 0), r.get('note'),
                          r.get('data_inserimento', datetime.now().isoformat())))

                nome = f"{u['nome']} {u.get('cognome', '')}"
                db.log_audit('undo', 'utente', u['id'], f'Ripristinato utente {nome}')
                return jsonify({'success': True, 'message': f'Utente {nome} ripristinato'})

            elif action['type'] == 'update_utente':
                old = action['data'].get('dati_precedenti', {})
                uid = action['data'].get('id')
                set_parts = []
                params = []
                for key in ['nome', 'cognome', 'monte_ore_settimanale', 'nome_puntato', 'lista_attesa']:
                    if key in old:
                        set_parts.append(f"{key} = ?")
                        params.append(old[key])
                if set_parts:
                    params.append(uid)
                    cursor.execute(f"UPDATE utenti SET {', '.join(set_parts)} WHERE id = ?", params)

                db.log_audit('undo', 'utente', uid, f'Ripristinati dati precedenti')
                return jsonify({'success': True, 'message': 'Modifica annullata'})

            return jsonify({'error': 'Tipo azione non supportato per undo'}), 400

    except Exception as e:
        logger.error(f"Errore undo: {e}")
        return jsonify({'error': str(e)}), 500


# ==================== CONFRONTO ANNUALE ====================

@app.route('/api/stats/confronto-annuale')
def api_confronto_annuale():
    """Confronta i dati di due anni scolastici"""
    anno_1 = request.args.get('anno_1')
    anno_2 = request.args.get('anno_2')

    if not anno_1 or not anno_2:
        return jsonify({'error': 'Specificare anno_1 e anno_2 (es: 2024-2025)'}), 400

    confronto = db.get_confronto_annuale(anno_1, anno_2)
    return jsonify({
        'anno_1': anno_1,
        'anno_2': anno_2,
        'confronto': confronto
    })


# ==================== STATISTICHE PER SCUOLA ====================

@app.route('/api/stats/per-scuola/<int:anno>/<int:mese>')
def api_stats_per_scuola(anno, mese):
    """Statistiche dettagliate per scuola, per grafici"""
    commessa = request.args.get('commessa')
    totali = db.get_totali_per_scuola(anno, mese, commessa)

    risultati = []
    for t in totali:
        risultati.append({
            'scuola': t['scuola'],
            'commessa': t['commessa'],
            'num_utenti': t['num_utenti'],
            'ore_erogate': round(t['ore_lavorate_60'] or 0, 2),
            'pasti': t['pasti'] or 0,
            'credito_debito': round(t['credito_debito'] or 0, 2),
            'imponibile': t.get('imponibile_100', 0),
            'totale': t.get('totale_100', 0)
        })

    return jsonify(risultati)


# ==================== ALERT AUTOMATICI ====================

@app.route('/api/alerts/<int:anno>/<int:mese>')
def api_get_alerts_by_period(anno, mese):
    """Ottiene gli alert automatici per il mese specifico"""
    commessa = request.args.get('commessa')
    alerts = db.get_alerts(anno, mese)

    # Filtra per commessa se specificata
    if commessa:
        alerts = [a for a in alerts if a.get('commessa') == commessa]

    return jsonify({
        'alerts': alerts,
        'totale': len(alerts),
        'per_tipo': {
            'danger': len([a for a in alerts if a['tipo'] == 'danger']),
            'warning': len([a for a in alerts if a['tipo'] == 'warning']),
            'info': len([a for a in alerts if a['tipo'] == 'info'])
        }
    })


# ==================== DASHBOARD FILTRATA ====================

@app.route('/api/stats/filtered')
def api_stats_filtered():
    """Statistiche dashboard con filtri per commessa e periodo"""
    commessa = request.args.get('commessa')
    anno = request.args.get('anno', type=int)
    mese = request.args.get('mese', type=int)

    with db.get_db_context() as conn:
        cursor = conn.cursor()

        stats = {}

        # Conteggio utenti (filtrato per commessa)
        if commessa:
            cursor.execute('''
                SELECT COUNT(*) FROM utenti u
                JOIN scuole s ON u.scuola_id = s.id
                JOIN commesse c ON s.commessa_id = c.id
                WHERE u.attivo = 1 AND c.nome = ?
            ''', (commessa,))
        else:
            cursor.execute("SELECT COUNT(*) FROM utenti WHERE attivo = 1")
        stats['num_utenti'] = cursor.fetchone()[0]

        # Conteggio scuole
        if commessa:
            cursor.execute('''
                SELECT COUNT(*) FROM scuole s
                JOIN commesse c ON s.commessa_id = c.id
                WHERE c.attiva = 1 AND c.nome = ?
            ''', (commessa,))
        else:
            cursor.execute("SELECT COUNT(*) FROM scuole")
        stats['num_scuole'] = cursor.fetchone()[0]

        # Ore mensili (se specificato periodo)
        if anno and mese:
            query_ore = '''
                SELECT
                    SUM(r.ore_lavorate_60) as ore_totali,
                    COUNT(DISTINCT CASE WHEN r.ore_lavorate_60 > 0 THEN r.utente_id END) as utenti_con_ore,
                    SUM(r.pasti) as pasti_totali
                FROM rendicontazione r
                JOIN utenti u ON r.utente_id = u.id
            '''
            params = [anno, mese]

            if commessa:
                query_ore += '''
                    JOIN scuole s ON u.scuola_id = s.id
                    JOIN commesse c ON s.commessa_id = c.id
                    WHERE r.anno = ? AND r.mese = ? AND u.attivo = 1 AND c.nome = ?
                '''
                params.append(commessa)
            else:
                query_ore += " WHERE r.anno = ? AND r.mese = ? AND u.attivo = 1"

            cursor.execute(query_ore, params)
            row = cursor.fetchone()
            stats['ore_mese'] = row['ore_totali'] or 0
            stats['utenti_con_ore'] = row['utenti_con_ore'] or 0
            stats['pasti_mese'] = row['pasti_totali'] or 0

    return jsonify(stats)


@app.route('/api/stats/trend')
def api_stats_trend():
    """Trend ore erogate per gli ultimi mesi dell'anno scolastico"""
    anno_scolastico = request.args.get('anno_scolastico')
    commessa = request.args.get('commessa')

    if not anno_scolastico:
        now = datetime.now()
        if now.month >= 9:
            anno_scolastico = f"{now.year}-{now.year + 1}"
        else:
            anno_scolastico = f"{now.year - 1}-{now.year}"

    anni = anno_scolastico.split('-')
    anno_inizio = int(anni[0])
    anno_fine = int(anni[1])

    risultati = []
    with db.get_db_context() as conn:
        cursor = conn.cursor()

        for mese in MESI_SCOLASTICI:
            anno = anno_inizio if mese >= 9 else anno_fine

            query = '''
                SELECT SUM(r.ore_lavorate_60) as ore_erogate
                FROM rendicontazione r
                JOIN utenti u ON r.utente_id = u.id
            '''
            params = [anno, mese]

            if commessa:
                query += '''
                    JOIN scuole s ON u.scuola_id = s.id
                    JOIN commesse c ON s.commessa_id = c.id
                    WHERE r.anno = ? AND r.mese = ? AND u.attivo = 1 AND c.nome = ?
                '''
                params.append(commessa)
            else:
                query += " WHERE r.anno = ? AND r.mese = ? AND u.attivo = 1"

            cursor.execute(query, params)
            row = cursor.fetchone()

            risultati.append({
                'mese': mese,
                'mese_nome': MESI_NOME.get(mese, '')[:3],
                'anno': anno,
                'ore_erogate': round(row['ore_erogate'] or 0, 2)
            })

    return jsonify(risultati)


@app.route('/api/stats/confronto-mese')
def api_stats_confronto_mese():
    """Confronto ore tra mese corrente e mese precedente"""
    anno = request.args.get('anno', type=int)
    mese = request.args.get('mese', type=int)
    commessa = request.args.get('commessa')

    if not anno or not mese:
        now = datetime.now()
        anno = now.year
        mese = now.month

    # Calcola mese precedente
    if mese == 1:
        mese_prec, anno_prec = 12, anno - 1
    else:
        mese_prec, anno_prec = mese - 1, anno

    with db.get_db_context() as conn:
        cursor = conn.cursor()

        def get_ore_mese(a, m):
            query = '''
                SELECT
                    COALESCE(SUM(r.ore_lavorate_60), 0) as ore,
                    COUNT(DISTINCT CASE WHEN r.ore_lavorate_60 > 0 THEN r.utente_id END) as utenti_attivi,
                    COALESCE(SUM(r.pasti), 0) as pasti
                FROM rendicontazione r
                JOIN utenti u ON r.utente_id = u.id
            '''
            params = [a, m]
            if commessa:
                query += '''
                    JOIN scuole s ON u.scuola_id = s.id
                    JOIN commesse c ON s.commessa_id = c.id
                    WHERE r.anno = ? AND r.mese = ? AND u.attivo = 1 AND c.nome = ?
                '''
                params.append(commessa)
            else:
                query += ' WHERE r.anno = ? AND r.mese = ? AND u.attivo = 1'
            cursor.execute(query, params)
            return cursor.fetchone()

        corrente = get_ore_mese(anno, mese)
        precedente = get_ore_mese(anno_prec, mese_prec)

        ore_corr = corrente['ore'] or 0
        ore_prec = precedente['ore'] or 0

        if ore_prec > 0:
            variazione_perc = round(((ore_corr - ore_prec) / ore_prec) * 100, 1)
        else:
            variazione_perc = 100 if ore_corr > 0 else 0

        result = {
            'mese_corrente': {
                'anno': anno,
                'mese': mese,
                'mese_nome': MESI_NOME.get(mese, ''),
                'ore': round(ore_corr, 2),
                'utenti_attivi': corrente['utenti_attivi'] or 0,
                'pasti': corrente['pasti'] or 0
            },
            'mese_precedente': {
                'anno': anno_prec,
                'mese': mese_prec,
                'mese_nome': MESI_NOME.get(mese_prec, ''),
                'ore': round(ore_prec, 2),
                'utenti_attivi': precedente['utenti_attivi'] or 0,
                'pasti': precedente['pasti'] or 0
            },
            'variazione': {
                'ore': round(ore_corr - ore_prec, 2),
                'percentuale': variazione_perc
            }
        }

    return jsonify(result)


@app.route('/api/stats/top-scuole')
def api_stats_top_scuole():
    """Top 5 scuole per ore erogate"""
    anno = request.args.get('anno', type=int)
    mese = request.args.get('mese', type=int)
    commessa = request.args.get('commessa')
    limit = request.args.get('limit', 5, type=int)

    if not anno or not mese:
        now = datetime.now()
        anno = now.year
        mese = now.month

    with db.get_db_context() as conn:
        cursor = conn.cursor()

        query = '''
            SELECT
                s.nome_completo as scuola,
                c.nome as commessa,
                SUM(r.ore_lavorate_60) as ore_erogate,
                COUNT(DISTINCT r.utente_id) as num_utenti,
                SUM(r.pasti) as pasti
            FROM rendicontazione r
            JOIN utenti u ON r.utente_id = u.id
            JOIN scuole s ON u.scuola_id = s.id
            JOIN commesse c ON s.commessa_id = c.id
            WHERE r.anno = ? AND r.mese = ? AND u.attivo = 1
        '''
        params = [anno, mese]

        if commessa:
            query += ' AND c.nome = ?'
            params.append(commessa)

        query += '''
            GROUP BY s.id
            HAVING ore_erogate > 0
            ORDER BY ore_erogate DESC
            LIMIT ?
        '''
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        risultati = []
        for r in rows:
            risultati.append({
                'scuola': r['scuola'][:40] + '...' if len(r['scuola'] or '') > 40 else r['scuola'],
                'scuola_full': r['scuola'],
                'commessa': r['commessa'],
                'ore_erogate': round(r['ore_erogate'] or 0, 2),
                'num_utenti': r['num_utenti'] or 0,
                'pasti': r['pasti'] or 0
            })

    return jsonify({
        'top_scuole': risultati,
        'anno': anno,
        'mese': mese,
        'mese_nome': MESI_NOME.get(mese, '')
    })


@app.route('/api/stats/credito-debito')
def api_stats_credito_debito():
    """Statistiche aggregate credito/debito"""
    anno = request.args.get('anno', type=int)
    mese = request.args.get('mese', type=int)
    commessa = request.args.get('commessa')

    if not anno or not mese:
        now = datetime.now()
        anno = now.year
        mese = now.month

    dati = db.get_rendicontazione_completa(anno, mese, commessa)

    totale_credito = 0
    totale_debito = 0
    utenti_in_credito = 0
    utenti_in_debito = 0
    utenti_in_pari = 0

    for d in dati:
        cd = d.get('credito_debito', 0) or 0
        if cd > 0.5:  # Tolleranza di 30 minuti
            totale_credito += cd
            utenti_in_credito += 1
        elif cd < -0.5:
            totale_debito += abs(cd)
            utenti_in_debito += 1
        else:
            utenti_in_pari += 1

    return jsonify({
        'totale_credito': round(totale_credito, 2),
        'totale_debito': round(totale_debito, 2),
        'saldo_netto': round(totale_credito - totale_debito, 2),
        'utenti_in_credito': utenti_in_credito,
        'utenti_in_debito': utenti_in_debito,
        'utenti_in_pari': utenti_in_pari,
        'totale_utenti': len(dati),
        'anno': anno,
        'mese': mese,
        'mese_nome': MESI_NOME.get(mese, '')
    })


# ==================== DOCUMENTAZIONE API ====================

@app.route('/api/docs')
def api_docs():
    """Documentazione API interattiva"""
    endpoints = [
        {
            'method': 'GET', 'path': '/api/utenti',
            'desc': 'Lista utenti attivi',
            'params': [
                {'nome': 'commessa', 'tipo': 'string', 'desc': 'Filtra per commessa'},
                {'nome': 'scuola_id', 'tipo': 'integer', 'desc': 'Filtra per scuola'}
            ]
        },
        {
            'method': 'POST', 'path': '/api/utenti',
            'desc': 'Crea nuovo utente',
            'body': {'commessa': 'string*', 'scuola': 'string*', 'nome': 'string*', 'cognome': 'string', 'monte_ore': 'number*'}
        },
        {
            'method': 'PUT', 'path': '/api/utenti/<id>',
            'desc': 'Aggiorna utente',
            'body': {'nome': 'string', 'cognome': 'string', 'monte_ore': 'number', 'lista_attesa': 'string'}
        },
        {
            'method': 'DELETE', 'path': '/api/utenti/<id>',
            'desc': 'Elimina utente'
        },
        {
            'method': 'GET', 'path': '/api/scuole',
            'desc': 'Lista scuole',
            'params': [{'nome': 'commessa', 'tipo': 'string', 'desc': 'Filtra per commessa'}]
        },
        {
            'method': 'GET', 'path': '/api/commesse',
            'desc': 'Lista commesse attive'
        },
        {
            'method': 'POST', 'path': '/api/commesse',
            'desc': 'Crea nuova commessa',
            'body': {'nome': 'string*', 'descrizione': 'string', 'colore': 'string (#RRGGBB)'}
        },
        {
            'method': 'PUT', 'path': '/api/commesse/<id>',
            'desc': 'Aggiorna commessa',
            'body': {'nome': 'string', 'descrizione': 'string', 'colore': 'string', 'attiva': 'boolean'}
        },
        {
            'method': 'DELETE', 'path': '/api/commesse/<id>',
            'desc': 'Disattiva commessa (soft delete)'
        },
        {
            'method': 'GET', 'path': '/api/rendicontazione/<anno>/<mese>',
            'desc': 'Rendicontazione mensile con tutti i calcoli',
            'params': [{'nome': 'commessa', 'tipo': 'string', 'desc': 'Filtra per commessa'}]
        },
        {
            'method': 'POST', 'path': '/api/rendicontazione/<anno>/<mese>',
            'desc': 'Aggiorna ore per un utente',
            'body': {'utente_id': 'integer*', 'ore_lavorate_60': 'number', 'pasti': 'integer', 'note': 'string'}
        },
        {
            'method': 'POST', 'path': '/api/rendicontazione/<anno>/<mese>/batch',
            'desc': 'Aggiorna ore per piu\' utenti',
            'body': {'updates': '[{utente_id, ore_lavorate_60, pasti, note}]'}
        },
        {
            'method': 'POST', 'path': '/api/import-excel',
            'desc': 'Importa dati da file Excel (.xlsx/.xls)',
            'body': {'file': 'multipart/form-data'}
        },
        {
            'method': 'GET', 'path': '/api/calendario',
            'desc': 'Calendario scolastico',
            'params': [{'nome': 'anno_scolastico', 'tipo': 'string', 'desc': 'Es: 2025-2026'}]
        },
        {
            'method': 'POST', 'path': '/api/calendario',
            'desc': 'Aggiorna giorni lavorativi',
            'body': {'anno_scolastico': 'string*', 'mese': 'integer*', 'anno': 'integer*', 'giorni_lavorativi': 'integer*'}
        },
        {
            'method': 'GET', 'path': '/api/stats',
            'desc': 'Statistiche generali'
        },
        {
            'method': 'GET', 'path': '/api/stats/advanced',
            'desc': 'Statistiche avanzate per dashboard',
            'params': [
                {'nome': 'anno', 'tipo': 'integer', 'desc': 'Anno'},
                {'nome': 'mese', 'tipo': 'integer', 'desc': 'Mese'}
            ]
        },
        {
            'method': 'GET', 'path': '/api/stats/filtered',
            'desc': 'Statistiche filtrate per commessa e periodo',
            'params': [
                {'nome': 'commessa', 'tipo': 'string', 'desc': 'Filtra per commessa'},
                {'nome': 'anno', 'tipo': 'integer', 'desc': 'Anno'},
                {'nome': 'mese', 'tipo': 'integer', 'desc': 'Mese'}
            ]
        },
        {
            'method': 'GET', 'path': '/api/stats/trend',
            'desc': 'Trend ore erogate per anno scolastico',
            'params': [
                {'nome': 'anno_scolastico', 'tipo': 'string', 'desc': 'Es: 2025-2026'},
                {'nome': 'commessa', 'tipo': 'string', 'desc': 'Filtra per commessa'}
            ]
        },
        {
            'method': 'GET', 'path': '/api/export/excel/<anno>/<mese>',
            'desc': 'Esporta rendicontazione in Excel Premium',
            'params': [
                {'nome': 'commessa', 'tipo': 'string', 'desc': 'Filtra per commessa'},
                {'nome': 'privacy', 'tipo': 'boolean', 'desc': 'Anonimizza nomi'}
            ]
        },
        {
            'method': 'GET', 'path': '/api/export/municipale/<anno>/<mese>',
            'desc': 'Riepilogo Municipale'
        },
        {
            'method': 'GET', 'path': '/api/export/dipartimentale/<anno>/<mese>',
            'desc': 'Monitoraggio Dipartimentale'
        },
        {
            'method': 'GET', 'path': '/api/export/word/<anno>/<mese>',
            'desc': 'Relazione Word sull\'andamento del servizio'
        },
        {
            'method': 'POST', 'path': '/api/backup',
            'desc': 'Crea backup manuale del database'
        },
        {
            'method': 'GET', 'path': '/api/backup',
            'desc': 'Lista backup disponibili'
        },
        {
            'method': 'POST', 'path': '/api/backup/restore',
            'desc': 'Ripristina un backup (richiede confirm: "CONFERMA")',
            'body': {'backup': 'string*', 'confirm': '"CONFERMA"'}
        },
        {
            'method': 'POST', 'path': '/api/reset',
            'desc': 'Reset dati (richiede confirm: "CONFERMA")',
            'body': {'type': 'all|rendicontazioni|utenti', 'confirm': '"CONFERMA"'}
        },
        {
            'method': 'GET', 'path': '/api/audit',
            'desc': 'Audit trail delle operazioni',
            'params': [
                {'nome': 'limit', 'tipo': 'integer', 'desc': 'Numero max risultati (default 100)'},
                {'nome': 'entita', 'tipo': 'string', 'desc': 'Filtra per tipo entita'}
            ]
        },
        {
            'method': 'GET', 'path': '/api/docs',
            'desc': 'Questa documentazione'
        },
    ]

    return jsonify({
        'nome': 'Gestionale OEPAC API',
        'versione': '2.1',
        'parametri_calcolo': {
            'tariffa_oraria': config.TARIFFA_ORARIA,
            'iva': f'{config.IVA_PERCENTUALE * 100}%',
            'tasso_assenza': f'{config.TASSO_ASSENZA * 100}%',
            'coefficiente_giornaliero': config.COEFFICIENTE_GIORNALIERO
        },
        'endpoints': endpoints
    })


# ==================== API DOCUMENTI UTENTE ====================

@app.route('/api/utente/<int:utente_id>/documenti')
def api_get_documenti_utente(utente_id):
    """Ottiene tutti i documenti di un utente"""
    try:
        documenti = db.get_documenti_utente(utente_id)
        return jsonify({'documenti': documenti})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/utente/<int:utente_id>/documenti', methods=['POST'])
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


@app.route('/api/documento/<int:documento_id>')
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


@app.route('/api/documento/<int:documento_id>', methods=['DELETE'])
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


@app.route('/api/documenti/scadenza')
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

@app.route('/api/utente/<int:utente_id>/note')
def api_get_note_utente(utente_id):
    """Ottiene le note di un utente"""
    try:
        tipo = request.args.get('tipo')
        note = db.get_note_utente(utente_id, tipo)
        return jsonify({'note': note})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/utente/<int:utente_id>/note', methods=['POST'])
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


@app.route('/api/nota/<int:nota_id>', methods=['PUT'])
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


@app.route('/api/nota/<int:nota_id>', methods=['DELETE'])
def api_delete_nota(nota_id):
    """Elimina una nota"""
    try:
        db.delete_nota_utente(nota_id)
        db.log_audit('delete', 'nota', nota_id, 'Nota eliminata')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/utente/<int:utente_id>/note/mensili/<int:anno>/<int:mese>')
def api_get_note_mensili(utente_id, anno, mese):
    """Ottiene le note mensili di un utente"""
    try:
        note = db.get_note_mensili(utente_id, anno, mese)
        return jsonify({'note': note})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== API ASSENZE ====================

@app.route('/api/utente/<int:utente_id>/assenze')
def api_get_assenze_utente(utente_id):
    """Ottiene le assenze di un utente"""
    try:
        anno = request.args.get('anno', type=int)
        assenze = db.get_assenze_utente(utente_id, anno)
        return jsonify({'assenze': assenze})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/utente/<int:utente_id>/assenze', methods=['POST'])
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


@app.route('/api/assenza/<int:assenza_id>', methods=['PUT'])
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


@app.route('/api/assenza/<int:assenza_id>', methods=['DELETE'])
def api_delete_assenza(assenza_id):
    """Elimina un'assenza"""
    try:
        db.delete_assenza(assenza_id)
        db.log_audit('delete', 'assenza', assenza_id, 'Assenza eliminata')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/assenze/periodo')
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


@app.route('/api/assenze/report/<int:anno>')
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

@app.route('/api/utente/<int:utente_id>/budget', methods=['PUT'])
def api_update_budget_utente(utente_id):
    """Aggiorna il budget ore di un utente"""
    try:
        data = request.get_json()
        db.update_budget_utente(
            utente_id,
            budget_mensile=data.get('budget_mensile'),
            budget_annuale=data.get('budget_annuale')
        )
        db.log_audit('update', 'budget', utente_id, f'Budget aggiornato')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/utente/<int:utente_id>/budget/<anno_scolastico>')
def api_get_budget_status(utente_id, anno_scolastico):
    """Ottiene lo stato del budget di un utente"""
    try:
        status = db.get_budget_status_utente(utente_id, anno_scolastico)
        if not status:
            return jsonify({'error': 'Utente non trovato'}), 404
        return jsonify(status)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/budget/critici/<anno_scolastico>')
def api_get_budget_critici(anno_scolastico):
    """Ottiene utenti con budget critico"""
    try:
        soglia = request.args.get('soglia', 80, type=int)
        utenti = db.get_utenti_budget_critico(anno_scolastico, soglia)
        return jsonify({'utenti': utenti})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== API NOTIFICHE ====================

@app.route('/api/notifiche')
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


@app.route('/api/notifiche/<int:notifica_id>/letta', methods=['POST'])
def api_mark_notifica_letta(notifica_id):
    """Segna una notifica come letta"""
    try:
        db.mark_notifica_letta(notifica_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/notifiche/lette', methods=['POST'])
def api_mark_all_notifiche_lette():
    """Segna tutte le notifiche come lette"""
    try:
        db.mark_all_notifiche_lette()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/notifiche/<int:notifica_id>/archivia', methods=['POST'])
def api_archivia_notifica(notifica_id):
    """Archivia una notifica"""
    try:
        db.archivia_notifica(notifica_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/notifiche/genera', methods=['POST'])
def api_genera_notifiche():
    """Genera notifiche automatiche"""
    try:
        notifiche_ids = db.genera_notifiche_automatiche()
        return jsonify({'success': True, 'generate': len(notifiche_ids)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== API STORICO E REPORT UTENTI ====================

@app.route('/api/utente/<int:utente_id>/storico-ore')
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


@app.route('/api/utente/<int:utente_id>/andamento')
def api_get_andamento_utente(utente_id):
    """Ottiene l'andamento ore di un utente"""
    try:
        mesi = request.args.get('mesi', 12, type=int)
        andamento = db.get_andamento_utente(utente_id, mesi)
        return jsonify({'andamento': andamento})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/utenti/classifica/<int:anno>')
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


@app.route('/api/utenti/confronto/<anno_scolastico>')
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

@app.route('/api/utente/<int:utente_id>/dettaglio')
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


# ==================== PAGINA DETTAGLIO UTENTE ====================

@app.route('/utente/<int:utente_id>')
def utente_dettaglio_page(utente_id):
    """Pagina dettaglio utente"""
    return render_template('utente_dettaglio.html', utente_id=utente_id)


# ==================== CONFIG API ====================

# ==================== REPORTISTICA LOCALE ====================

@app.route('/reportistica-locale')
def page_reportistica_locale():
    """Pagina reportistica locale per commessa"""
    return render_template('reportistica_locale.html')


@app.route('/api/reportistica-locale/<int:commessa_id>/<anno_scolastico>')
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


@app.route('/api/dd/<int:commessa_id>/<anno_scolastico>', methods=['GET'])
def api_get_dd(commessa_id, anno_scolastico):
    """Ottiene le DD per una commessa"""
    dd_list = db.get_dd_by_commessa(commessa_id, anno_scolastico)
    return jsonify(dd_list)


@app.route('/api/dd', methods=['POST'])
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


@app.route('/api/dd/<int:dd_id>', methods=['PUT'])
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


@app.route('/api/dd/<int:dd_id>', methods=['DELETE'])
def api_delete_dd(dd_id):
    """Elimina una DD"""
    try:
        db.delete_dd(dd_id)
        logger.info(f"DD eliminata: id={dd_id}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Errore eliminazione DD: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/recuperi/<int:commessa_id>/<anno_scolastico>', methods=['GET'])
def api_get_recuperi(commessa_id, anno_scolastico):
    """Ottiene i recuperi per una commessa"""
    recuperi = db.get_recuperi_by_commessa(commessa_id, anno_scolastico)
    return jsonify(recuperi)


@app.route('/api/recuperi', methods=['POST'])
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


@app.route('/api/recuperi/<int:recupero_id>', methods=['PUT'])
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


@app.route('/api/recuperi/<int:recupero_id>', methods=['DELETE'])
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

@app.route('/api/progettato-override', methods=['POST'])
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


@app.route('/api/progettato-override/<int:commessa_id>/<anno_scolastico>/<int:mese>/<int:anno>', methods=['DELETE'])
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

@app.route('/api/report-override', methods=['POST'])
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


@app.route('/api/report-override/<int:commessa_id>/<anno_scolastico>/<int:mese>/<int:anno>/<campo>', methods=['DELETE'])
def api_delete_report_override(commessa_id, anno_scolastico, mese, anno, campo):
    """Rimuove l'override di un campo (torna al calcolo automatico)"""
    if campo not in CAMPI_OVERRIDE_VALIDI:
        return jsonify({'error': f'Campo non valido'}), 400

    try:
        db.delete_report_override(commessa_id, anno_scolastico, mese, anno, campo)
        logger.info(f"Report override rimosso: commessa={commessa_id}, mese={mese}/{anno}, campo={campo}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Errore delete report override: {e}")
        return jsonify({'error': str(e)}), 500


# ==================== API STATISTICHE AVANZATE ====================

@app.route('/api/stats/heatmap/<anno_scolastico>')
def api_stats_heatmap(anno_scolastico):
    """Heatmap presenza mensile per utente"""
    try:
        commessa = request.args.get('commessa')
        limit = request.args.get('limit', 50, type=int)

        anni = anno_scolastico.split('-')
        anno_inizio = int(anni[0])
        anno_fine = int(anni[1])

        with db.get_db_context() as conn:
            # Ottieni utenti con JOIN per commessa e scuola
            query_utenti = """
                SELECT u.id, u.nome, u.cognome, cm.nome as commessa,
                       s.nome_completo as scuola, u.monte_ore_settimanale
                FROM utenti u
                JOIN scuole s ON u.scuola_id = s.id
                JOIN commesse cm ON s.commessa_id = cm.id
                WHERE u.attivo = 1
            """
            params = []
            if commessa:
                query_utenti += " AND cm.nome = ?"
                params.append(commessa)
            query_utenti += " ORDER BY u.cognome, u.nome LIMIT ?"
            params.append(limit)

            cursor = conn.execute(query_utenti, params)
            utenti = [dict(row) for row in cursor.fetchall()]

            # Mesi dell'anno scolastico
            mesi_scolastici = [
                {'mese': 9, 'anno': anno_inizio},
                {'mese': 10, 'anno': anno_inizio},
                {'mese': 11, 'anno': anno_inizio},
                {'mese': 12, 'anno': anno_inizio},
                {'mese': 1, 'anno': anno_fine},
                {'mese': 2, 'anno': anno_fine},
                {'mese': 3, 'anno': anno_fine},
                {'mese': 4, 'anno': anno_fine},
                {'mese': 5, 'anno': anno_fine},
                {'mese': 6, 'anno': anno_fine}
            ]

            # Cache variazioni monte ore per ogni mese
            variazioni_per_mese = {}
            for m in mesi_scolastici:
                variazioni_per_mese[(m['mese'], m['anno'])] = db.get_monte_ore_effettivo_bulk(m['anno'], m['mese'])

            # Per ogni utente, ottieni le ore erogate per ogni mese
            heatmap_data = []
            for utente in utenti:
                utente_data = {
                    'id': utente['id'],
                    'nome': f"{utente['nome']} {utente['cognome']}",
                    'commessa': utente['commessa'],
                    'monte_ore': utente['monte_ore_settimanale'],
                    'mesi': []
                }

                for m in mesi_scolastici:
                    cursor = conn.execute("""
                        SELECT COALESCE(SUM(ore_lavorate_60), 0) as ore
                        FROM rendicontazione
                        WHERE utente_id = ? AND anno = ? AND mese = ?
                    """, [utente['id'], m['anno'], m['mese']])

                    ore = cursor.fetchone()['ore']

                    # Monte ore effettivo (con variazione se presente)
                    var_mese = variazioni_per_mese.get((m['mese'], m['anno']), {})
                    monte_ore_eff = var_mese.get(utente['id'], utente['monte_ore_settimanale'] or 0)

                    # Calcola ore previste per il mese (formula centralizzata)
                    giorni_lav = db.get_calendario(anno_scolastico, m['mese'], m['anno'])
                    _, ore_previste_ridotte = db.calcola_media_prevista(monte_ore_eff, giorni_lav)

                    # Calcola percentuale completamento
                    percentuale = (ore / ore_previste_ridotte * 100) if ore_previste_ridotte > 0 else 0

                    utente_data['mesi'].append({
                        'mese': m['mese'],
                        'anno': m['anno'],
                        'ore': round(ore, 2),
                        'ore_previste': round(ore_previste_ridotte, 2),
                        'percentuale': round(min(percentuale, 150), 1)  # Cap a 150%
                    })

                heatmap_data.append(utente_data)

            return jsonify({
                'heatmap': heatmap_data,
                'mesi': [{'mese': m['mese'], 'anno': m['anno']} for m in mesi_scolastici]
            })
    except Exception as e:
        logger.error(f"Errore heatmap: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats/scuole-dettaglio')
def api_stats_scuole_dettaglio():
    """Statistiche dettagliate per scuola con filtri"""
    try:
        anno = request.args.get('anno', type=int)
        mese = request.args.get('mese', type=int)
        commessa = request.args.get('commessa')
        order_by = request.args.get('order_by', 'ore_erogate')
        order_dir = request.args.get('order_dir', 'desc')

        with db.get_db_context() as conn:
            # NOTA: utenti.scuola e utenti.commessa non esistono, facciamo JOIN
            query = """
                SELECT
                    s.nome_completo as scuola,
                    cm.nome as commessa,
                    COUNT(DISTINCT u.id) as num_utenti,
                    SUM(u.monte_ore_settimanale) as monte_ore_totale
            """

            if anno and mese:
                query += """,
                    COALESCE(SUM(r.ore_lavorate_60), 0) as ore_erogate,
                    COALESCE(SUM(r.ore_lavorate_60 * 24.07), 0) as imponibile,
                    COALESCE(SUM(r.ore_lavorate_60 * 25.27), 0) as totale_iva
                """

            query += """
                FROM utenti u
                JOIN scuole s ON u.scuola_id = s.id
                JOIN commesse cm ON s.commessa_id = cm.id
            """

            if anno and mese:
                query += """
                    LEFT JOIN rendicontazione r ON u.id = r.utente_id
                        AND r.anno = ? AND r.mese = ?
                """

            query += " WHERE u.attivo = 1"

            params = []
            if anno and mese:
                params.extend([anno, mese])

            if commessa:
                query += " AND cm.nome = ?"
                params.append(commessa)

            query += " GROUP BY s.id, s.nome_completo, cm.nome"

            # Order by (usa gli alias definiti nella SELECT)
            valid_orders = {
                'ore_erogate': 'ore_erogate',
                'num_utenti': 'num_utenti',
                'monte_ore_totale': 'monte_ore_totale',
                'scuola': 's.nome_completo'
            }
            if order_by in valid_orders:
                direction = 'DESC' if order_dir.lower() == 'desc' else 'ASC'
                query += f" ORDER BY {valid_orders[order_by]} {direction}"

            cursor = conn.execute(query, params)
            scuole = [dict(row) for row in cursor.fetchall()]

            return jsonify({'scuole': scuole})
    except Exception as e:
        logger.error(f"Errore stats scuole: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats/validazione')
def api_stats_validazione():
    """Verifica anomalie nei dati e restituisce avvisi"""
    try:
        anno = request.args.get('anno', type=int)
        mese = request.args.get('mese', type=int)

        if not anno or not mese:
            now = datetime.now()
            anno = anno or now.year
            mese = mese or now.month

        anomalie = []

        with db.get_db_context() as conn:
            # 1. Utenti senza ore nel mese
            cursor = conn.execute("""
                SELECT u.id, u.nome, u.cognome, cm.nome as commessa,
                       s.nome_completo as scuola, u.monte_ore_settimanale
                FROM utenti u
                JOIN scuole s ON u.scuola_id = s.id
                JOIN commesse cm ON s.commessa_id = cm.id
                WHERE u.attivo = 1
                AND u.monte_ore_settimanale > 0
                AND u.id NOT IN (
                    SELECT DISTINCT utente_id FROM rendicontazione
                    WHERE anno = ? AND mese = ? AND ore_lavorate_60 > 0
                )
            """, [anno, mese])
            utenti_senza_ore = [dict(row) for row in cursor.fetchall()]

            if utenti_senza_ore:
                anomalie.append({
                    'tipo': 'warning',
                    'categoria': 'ore_mancanti',
                    'titolo': 'Utenti senza ore registrate',
                    'messaggio': f'{len(utenti_senza_ore)} utenti non hanno ore registrate questo mese',
                    'conteggio': len(utenti_senza_ore),
                    'dettagli': [{'id': u['id'], 'nome': f"{u['nome']} {u['cognome']}", 'commessa': u['commessa']}
                                for u in utenti_senza_ore[:10]]
                })

            # 2. Utenti con ore negative o anomale
            cursor = conn.execute("""
                SELECT u.id, u.nome, u.cognome, r.ore_lavorate_60, u.monte_ore_settimanale
                FROM rendicontazione r
                JOIN utenti u ON r.utente_id = u.id
                WHERE r.anno = ? AND r.mese = ?
                AND (r.ore_lavorate_60 < 0 OR r.ore_lavorate_60 > 200)
            """, [anno, mese])
            ore_anomale = [dict(row) for row in cursor.fetchall()]

            if ore_anomale:
                anomalie.append({
                    'tipo': 'danger',
                    'categoria': 'ore_anomale',
                    'titolo': 'Ore con valori anomali',
                    'messaggio': f'{len(ore_anomale)} registrazioni hanno valori sospetti',
                    'conteggio': len(ore_anomale),
                    'dettagli': [{'id': u['id'], 'nome': f"{u['nome']} {u['cognome']}", 'ore': u['ore_lavorate_60']}
                                for u in ore_anomale]
                })

            # 3. Utenti con monte ore = 0 ma con ore lavorate
            cursor = conn.execute("""
                SELECT u.id, u.nome, u.cognome, r.ore_lavorate_60
                FROM rendicontazione r
                JOIN utenti u ON r.utente_id = u.id
                WHERE r.anno = ? AND r.mese = ?
                AND u.monte_ore_settimanale = 0
                AND r.ore_lavorate_60 > 0
            """, [anno, mese])
            monte_ore_zero = [dict(row) for row in cursor.fetchall()]

            if monte_ore_zero:
                anomalie.append({
                    'tipo': 'info',
                    'categoria': 'monte_ore_zero',
                    'titolo': 'Utenti con monte ore non configurato',
                    'messaggio': f'{len(monte_ore_zero)} utenti hanno ore lavorate ma monte ore = 0',
                    'conteggio': len(monte_ore_zero),
                    'dettagli': [{'id': u['id'], 'nome': f"{u['nome']} {u['cognome']}", 'ore': u['ore_lavorate_60']}
                                for u in monte_ore_zero]
                })

            # 4. Utenti con ore erogate molto diverse dalle previste (>50% differenza)
            cursor = conn.execute("""
                SELECT
                    u.id, u.nome, u.cognome, u.monte_ore_settimanale,
                    COALESCE(SUM(r.ore_lavorate_60), 0) as ore_erogate
                FROM utenti u
                LEFT JOIN rendicontazione r ON u.id = r.utente_id AND r.anno = ? AND r.mese = ?
                WHERE u.attivo = 1 AND u.monte_ore_settimanale > 0
                GROUP BY u.id
            """, [anno, mese])

            # Determina anno scolastico
            anno_scolastico_validazione = f"{anno}-{anno+1}" if mese >= 9 else f"{anno-1}-{anno}"
            giorni_lav = db.get_calendario(anno_scolastico_validazione, mese, anno)
            differenze_anomale = []
            variazioni_anomalie = db.get_monte_ore_effettivo_bulk(anno, mese)

            for row in cursor.fetchall():
                monte_ore_eff = variazioni_anomalie.get(row['id'], row['monte_ore_settimanale'])
                _, ore_previste_ridotte = db.calcola_media_prevista(monte_ore_eff, giorni_lav)
                ore_erogate = row['ore_erogate']

                if ore_previste_ridotte > 0:
                    diff_percentuale = abs(ore_erogate - ore_previste_ridotte) / ore_previste_ridotte * 100
                    if diff_percentuale > config.SOGLIA_ANOMALIA_PERCENTUALE and ore_erogate > 0:
                        differenze_anomale.append({
                            'id': row['id'],
                            'nome': f"{row['nome']} {row['cognome']}",
                            'ore_erogate': round(ore_erogate, 2),
                            'ore_previste': round(ore_previste_ridotte, 2),
                            'diff_percentuale': round(diff_percentuale, 1)
                        })

            if differenze_anomale:
                anomalie.append({
                    'tipo': 'warning',
                    'categoria': 'differenze_elevate',
                    'titolo': 'Differenze significative ore',
                    'messaggio': f'{len(differenze_anomale)} utenti con differenza >50% tra ore erogate e previste',
                    'conteggio': len(differenze_anomale),
                    'dettagli': differenze_anomale[:10]
                })

            # 5. Commesse senza dati nel mese
            cursor = conn.execute("""
                SELECT c.nome, COUNT(u.id) as num_utenti
                FROM commesse c
                LEFT JOIN scuole s ON s.commessa_id = c.id
                LEFT JOIN utenti u ON u.scuola_id = s.id AND u.attivo = 1
                WHERE c.attiva = 1
                GROUP BY c.id
                HAVING num_utenti = 0
            """)
            commesse_vuote = [dict(row) for row in cursor.fetchall()]

            if commesse_vuote:
                anomalie.append({
                    'tipo': 'info',
                    'categoria': 'commesse_vuote',
                    'titolo': 'Commesse senza utenti',
                    'messaggio': f'{len(commesse_vuote)} commesse attive non hanno utenti associati',
                    'conteggio': len(commesse_vuote),
                    'dettagli': [{'nome': c['nome']} for c in commesse_vuote]
                })

        # Riepilogo
        riepilogo = {
            'totale_anomalie': len(anomalie),
            'critiche': len([a for a in anomalie if a['tipo'] == 'danger']),
            'avvisi': len([a for a in anomalie if a['tipo'] == 'warning']),
            'info': len([a for a in anomalie if a['tipo'] == 'info'])
        }

        return jsonify({
            'anomalie': anomalie,
            'riepilogo': riepilogo,
            'periodo': {'anno': anno, 'mese': mese}
        })
    except Exception as e:
        logger.error(f"Errore validazione: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats/confronto-annuale-dettaglio')
def api_stats_confronto_annuale_dettaglio():
    """Confronto dettagliato tra anni scolastici"""
    try:
        mese = request.args.get('mese', type=int)
        commessa = request.args.get('commessa')

        if not mese:
            mese = datetime.now().month

        with db.get_db_context() as conn:
            # Ottieni anni scolastici disponibili
            cursor = conn.execute("SELECT DISTINCT anno_scolastico FROM calendario_scolastico ORDER BY anno_scolastico DESC LIMIT 5")
            anni = [row['anno_scolastico'] for row in cursor.fetchall()]

            risultati = []
            for anno_scolastico in anni:
                anni_parts = anno_scolastico.split('-')
                anno_effettivo = int(anni_parts[0]) if mese >= 9 else int(anni_parts[1])

                query = """
                    SELECT
                        COUNT(DISTINCT r.utente_id) as num_utenti,
                        COALESCE(SUM(r.ore_lavorate_60), 0) as ore_erogate,
                        COALESCE(SUM(r.ore_lavorate_60 * 24.07), 0) as imponibile
                    FROM rendicontazione r
                    JOIN utenti u ON r.utente_id = u.id
                """
                params = [anno_effettivo, mese]

                if commessa:
                    query += """
                    JOIN scuole s ON u.scuola_id = s.id
                    JOIN commesse cm ON s.commessa_id = cm.id
                    WHERE r.anno = ? AND r.mese = ? AND cm.nome = ?
                    """
                    params.append(commessa)
                else:
                    query += " WHERE r.anno = ? AND r.mese = ?"

                cursor = conn.execute(query, params)
                dati = cursor.fetchone()

                risultati.append({
                    'anno_scolastico': anno_scolastico,
                    'anno': anno_effettivo,
                    'mese': mese,
                    'num_utenti': dati['num_utenti'],
                    'ore_erogate': round(dati['ore_erogate'], 2),
                    'imponibile': round(dati['imponibile'], 2)
                })

            # Calcola variazioni percentuali
            for i in range(len(risultati) - 1):
                if risultati[i + 1]['ore_erogate'] > 0:
                    variazione = ((risultati[i]['ore_erogate'] - risultati[i + 1]['ore_erogate'])
                                 / risultati[i + 1]['ore_erogate'] * 100)
                    risultati[i]['variazione'] = round(variazione, 1)
                else:
                    risultati[i]['variazione'] = None

            if risultati:
                risultati[-1]['variazione'] = None

            return jsonify({'confronto': risultati})
    except Exception as e:
        logger.error(f"Errore confronto annuale: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/utenti/filtrati')
def api_utenti_filtrati():
    """API per ottenere lista utenti con filtri avanzati"""
    try:
        commessa = request.args.get('commessa')
        scuola = request.args.get('scuola')
        search = request.args.get('search', '').strip()

        with db.get_db_context() as conn:
            # NOTA: utenti.commessa, utenti.scuola non esistono, usiamo JOIN.
            query = """
                SELECT u.id, u.nome, u.cognome,
                       cm.nome as commessa,
                       s.nome_completo as scuola,
                       u.monte_ore_settimanale
                FROM utenti u
                JOIN scuole s ON u.scuola_id = s.id
                JOIN commesse cm ON s.commessa_id = cm.id
                WHERE u.attivo = 1
            """
            params = []

            if commessa:
                query += " AND cm.nome = ?"
                params.append(commessa)

            if scuola:
                query += " AND s.nome_completo LIKE ?"
                params.append(f"%{scuola}%")

            if search:
                query += " AND (u.nome LIKE ? OR u.cognome LIKE ?)"
                params.extend([f"%{search}%", f"%{search}%"])

            query += " ORDER BY u.cognome, u.nome"

            cursor = conn.execute(query, params)
            utenti = [dict(row) for row in cursor.fetchall()]

            return jsonify(utenti)
    except Exception as e:
        logger.error(f"Errore utenti filtrati: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/scuole/lista')
def api_scuole_lista():
    """Lista scuole per filtri dropdown"""
    try:
        commessa = request.args.get('commessa')

        with db.get_db_context() as conn:
            # NOTA: utenti.scuola/utenti.commessa non esistono, facciamo JOIN
            query = """
                SELECT s.nome_completo as scuola,
                       cm.nome as commessa,
                       COUNT(u.id) as num_utenti
                FROM scuole s
                JOIN commesse cm ON s.commessa_id = cm.id
                LEFT JOIN utenti u ON u.scuola_id = s.id AND u.attivo = 1
                WHERE s.nome_completo IS NOT NULL AND s.nome_completo != ''
            """
            params = []

            if commessa:
                query += " AND cm.nome = ?"
                params.append(commessa)

            query += " GROUP BY s.id, s.nome_completo, cm.nome ORDER BY s.nome_completo"

            cursor = conn.execute(query, params)
            scuole = [dict(row) for row in cursor.fetchall()]

            return jsonify(scuole)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/config')
def api_get_config():
    """Ritorna la configurazione corrente (parametri di calcolo)"""
    return jsonify({
        'tariffa_oraria': config.TARIFFA_ORARIA,
        'iva_percentuale': config.IVA_PERCENTUALE,
        'tasso_assenza': config.TASSO_ASSENZA,
        'coefficiente_giornaliero': config.COEFFICIENTE_GIORNALIERO,
        'max_ore_settimanali': config.MAX_ORE_SETTIMANALI,
        'max_pasti_mensili': config.MAX_PASTI_MENSILI
    })


def open_browser():
    """Apre il browser dopo un breve ritardo"""
    import webbrowser
    import time
    time.sleep(1.5)
    webbrowser.open('http://localhost:5000')


if __name__ == '__main__':
    import sys
    import threading

    logger.info("=" * 50)
    logger.info("  GESTIONALE OEPAC - Sistema di Rendicontazione")
    logger.info("=" * 50)
    logger.info("  Avvio server su http://localhost:5000")

    if getattr(sys, 'frozen', False):
        logger.info("  Apertura browser in corso...")
        threading.Thread(target=open_browser, daemon=True).start()
        app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
    else:
        logger.info("  Premi Ctrl+C per terminare")
        app.run(debug=True, host='0.0.0.0', port=5000)

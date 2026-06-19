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

logger = config.setup_logging()

def push_undo(action_type, data):
    """Salva un'azione nello stack undo persistente"""
    db.push_undo_action(action_type, data)


app = Flask(__name__)
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


def decimal_to_sessagesimal(decimal_hours):
    """
    Converte ore decimali in formato HH:MM
    Es: 1.50 → "1:30", 2.25 → "2:15", 0.75 → "0:45"
    """
    if decimal_hours is None or decimal_hours == 0:
        return "0:00"

    hours = int(decimal_hours)
    minutes = round((decimal_hours - hours) * 60)

    # Gestisci arrotondamento
    if minutes == 60:
        hours += 1
        minutes = 0

    return f"{hours}:{minutes:02d}"


# Mappa per ordinamento cronologico dei mesi di lista attesa (anno scolastico)
_LISTA_ATTESA_MESI_ORDER = {
    'Settembre': 9, 'Ottobre': 10, 'Novembre': 11, 'Dicembre': 12,
    'Gennaio': 1, 'Febbraio': 2, 'Marzo': 3, 'Aprile': 4, 'Maggio': 5, 'Giugno': 6,
}
_LISTA_ATTESA_MESI_ABBR = {
    'Settembre': 'Set', 'Ottobre': 'Ott', 'Novembre': 'Nov', 'Dicembre': 'Dic',
    'Gennaio': 'Gen', 'Febbraio': 'Feb', 'Marzo': 'Mar', 'Aprile': 'Apr',
    'Maggio': 'Mag', 'Giugno': 'Giu',
}
# Ordine cronologico nell'anno scolastico (Set -> Giu)
_LISTA_ATTESA_SORT_INDEX = ['Settembre', 'Ottobre', 'Novembre', 'Dicembre',
                            'Gennaio', 'Febbraio', 'Marzo', 'Aprile', 'Maggio', 'Giugno']


def get_liste_attesa_ordinate(dati, anno_report, mese_report):
    """Ritorna i valori distinti di lista_attesa presenti nei dati, ordinati
    cronologicamente per anno scolastico, con etichetta 'Lista Mes YYYY'.

    Returns: list of dict { 'valore': 'Settembre', 'label': 'Lista Set 2025', 'anno': 2025 }
    """
    # Determina anno di inizio dell'anno scolastico
    if mese_report >= 9:
        anno_inizio_as = anno_report
    else:
        anno_inizio_as = anno_report - 1

    valori = set()
    for d in dati:
        la = (d.get('lista_attesa') or '').strip()
        if la:
            valori.add(la)

    risultato = []
    for v in valori:
        if v in _LISTA_ATTESA_SORT_INDEX:
            idx = _LISTA_ATTESA_SORT_INDEX.index(v)
            anno_v = anno_inizio_as if idx < 4 else anno_inizio_as + 1
            abbr = _LISTA_ATTESA_MESI_ABBR[v]
            label = f"Lista {abbr} {anno_v}"
            risultato.append({'valore': v, 'label': label, 'anno': anno_v, 'sort_idx': idx})
        else:
            # Valore non riconosciuto: lo mettiamo in fondo con label grezza
            risultato.append({'valore': v, 'label': f"Lista {v}", 'anno': 9999, 'sort_idx': 99})

    risultato.sort(key=lambda x: x['sort_idx'])
    return risultato


# ==================== BRAND / STILI REPORT ====================

# Palette report (coerente con il brand)
REPORT_PRIMARY = '#4F46E5'        # Indigo
REPORT_PRIMARY_DARK = '#3730A3'   # Indigo scuro
REPORT_ACCENT = '#0EA5E9'         # Sky blue
REPORT_DARK = '#1E293B'           # Slate scuro (per testi e totali)
REPORT_MUTED = '#64748B'          # Slate medio
REPORT_LIGHT = '#F1F5F9'          # Slate chiaro (righe alternate)
REPORT_BORDER = '#CBD5E1'         # Bordo cella tenue
REPORT_SUCCESS = '#10B981'        # Verde


def get_excel_brand_styles(workbook):
    """Restituisce un dizionario di formati Excel branded e coerenti."""
    FONT = 'Calibri'

    return {
        'title': workbook.add_format({
            'bold': True, 'font_size': 18, 'font_name': FONT,
            'bg_color': REPORT_PRIMARY, 'font_color': 'white',
            'align': 'center', 'valign': 'vcenter',
        }),
        'subtitle': workbook.add_format({
            'bold': True, 'font_size': 11, 'font_name': FONT,
            'bg_color': REPORT_DARK, 'font_color': 'white',
            'align': 'center', 'valign': 'vcenter',
        }),
        'section': workbook.add_format({
            'bold': True, 'font_size': 12, 'font_name': FONT,
            'bg_color': REPORT_DARK, 'font_color': 'white',
            'align': 'left', 'valign': 'vcenter', 'indent': 1,
        }),
        'info': workbook.add_format({
            'italic': True, 'font_size': 9, 'font_name': FONT,
            'font_color': REPORT_MUTED, 'align': 'left', 'valign': 'vcenter',
        }),
        'header': workbook.add_format({
            'bold': True, 'font_size': 10, 'font_name': FONT,
            'bg_color': REPORT_PRIMARY, 'font_color': 'white',
            'align': 'center', 'valign': 'vcenter',
            'border': 1, 'border_color': REPORT_PRIMARY_DARK,
            'text_wrap': True,
        }),
        'cell': workbook.add_format({
            'font_size': 10, 'font_name': FONT, 'align': 'left',
            'valign': 'vcenter', 'border': 1, 'border_color': REPORT_BORDER,
        }),
        'cell_alt': workbook.add_format({
            'font_size': 10, 'font_name': FONT, 'align': 'left',
            'valign': 'vcenter', 'border': 1, 'border_color': REPORT_BORDER,
            'bg_color': REPORT_LIGHT,
        }),
        'cell_center': workbook.add_format({
            'font_size': 10, 'font_name': FONT, 'align': 'center',
            'valign': 'vcenter', 'border': 1, 'border_color': REPORT_BORDER,
        }),
        'cell_center_alt': workbook.add_format({
            'font_size': 10, 'font_name': FONT, 'align': 'center',
            'valign': 'vcenter', 'border': 1, 'border_color': REPORT_BORDER,
            'bg_color': REPORT_LIGHT,
        }),
        'number': workbook.add_format({
            'font_size': 10, 'font_name': FONT, 'num_format': '#,##0.00',
            'align': 'right', 'valign': 'vcenter',
            'border': 1, 'border_color': REPORT_BORDER,
        }),
        'number_alt': workbook.add_format({
            'font_size': 10, 'font_name': FONT, 'num_format': '#,##0.00',
            'align': 'right', 'valign': 'vcenter',
            'border': 1, 'border_color': REPORT_BORDER,
            'bg_color': REPORT_LIGHT,
        }),
        'integer': workbook.add_format({
            'font_size': 10, 'font_name': FONT, 'num_format': '#,##0',
            'align': 'right', 'valign': 'vcenter',
            'border': 1, 'border_color': REPORT_BORDER,
        }),
        'integer_alt': workbook.add_format({
            'font_size': 10, 'font_name': FONT, 'num_format': '#,##0',
            'align': 'right', 'valign': 'vcenter',
            'border': 1, 'border_color': REPORT_BORDER,
            'bg_color': REPORT_LIGHT,
        }),
        'money': workbook.add_format({
            'font_size': 10, 'font_name': FONT, 'num_format': '€ #,##0.00',
            'align': 'right', 'valign': 'vcenter',
            'border': 1, 'border_color': REPORT_BORDER,
        }),
        'money_alt': workbook.add_format({
            'font_size': 10, 'font_name': FONT, 'num_format': '€ #,##0.00',
            'align': 'right', 'valign': 'vcenter',
            'border': 1, 'border_color': REPORT_BORDER,
            'bg_color': REPORT_LIGHT,
        }),
        'total_label': workbook.add_format({
            'bold': True, 'font_size': 10, 'font_name': FONT,
            'bg_color': REPORT_DARK, 'font_color': 'white',
            'align': 'left', 'valign': 'vcenter',
            'border': 1, 'border_color': REPORT_DARK,
            'indent': 1,
        }),
        'total_cell': workbook.add_format({
            'bold': True, 'font_size': 10, 'font_name': FONT,
            'bg_color': REPORT_DARK, 'font_color': 'white',
            'align': 'center', 'valign': 'vcenter',
            'border': 1, 'border_color': REPORT_DARK,
        }),
        'total_number': workbook.add_format({
            'bold': True, 'font_size': 10, 'font_name': FONT,
            'bg_color': REPORT_DARK, 'font_color': 'white',
            'num_format': '#,##0.00', 'align': 'right', 'valign': 'vcenter',
            'border': 1, 'border_color': REPORT_DARK,
        }),
        'total_integer': workbook.add_format({
            'bold': True, 'font_size': 10, 'font_name': FONT,
            'bg_color': REPORT_DARK, 'font_color': 'white',
            'num_format': '#,##0', 'align': 'right', 'valign': 'vcenter',
            'border': 1, 'border_color': REPORT_DARK,
        }),
        'total_money': workbook.add_format({
            'bold': True, 'font_size': 10, 'font_name': FONT,
            'bg_color': REPORT_DARK, 'font_color': 'white',
            'num_format': '€ #,##0.00', 'align': 'right', 'valign': 'vcenter',
            'border': 1, 'border_color': REPORT_DARK,
        }),
        'summary_label': workbook.add_format({
            'bold': True, 'font_size': 10, 'font_name': FONT,
            'bg_color': REPORT_LIGHT, 'font_color': REPORT_DARK,
            'align': 'right', 'valign': 'vcenter',
            'border': 1, 'border_color': REPORT_BORDER,
        }),
        'summary_money': workbook.add_format({
            'font_size': 10, 'font_name': FONT, 'num_format': '€ #,##0.00',
            'align': 'right', 'valign': 'vcenter',
            'border': 1, 'border_color': REPORT_BORDER,
        }),
        'grand_label': workbook.add_format({
            'bold': True, 'font_size': 11, 'font_name': FONT,
            'bg_color': REPORT_PRIMARY, 'font_color': 'white',
            'align': 'right', 'valign': 'vcenter',
            'border': 1, 'border_color': REPORT_PRIMARY_DARK,
        }),
        'grand_money': workbook.add_format({
            'bold': True, 'font_size': 11, 'font_name': FONT,
            'bg_color': REPORT_PRIMARY, 'font_color': 'white',
            'num_format': '€ #,##0.00', 'align': 'right', 'valign': 'vcenter',
            'border': 1, 'border_color': REPORT_PRIMARY_DARK,
        }),
    }


def _style_word_cell_bg(cell, hex_color):
    """Imposta il colore di sfondo di una cella Word (hex senza '#')."""
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tc_pr.append(shd)


def style_word_table_header(table, bg_color='4F46E5', font_color='FFFFFF'):
    """Applica stile professionale alla prima riga (header) di una tabella Word."""
    if not table.rows:
        return
    hdr_row = table.rows[0]
    for cell in hdr_row.cells:
        _style_word_cell_bg(cell, bg_color)
        for paragraph in cell.paragraphs:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in paragraph.runs:
                run.bold = True
                run.font.color.rgb = RGBColor.from_string(font_color)
                run.font.name = 'Calibri'
                run.font.size = Pt(10)


def style_word_table_alternating_rows(table, color_light='FFFFFF', color_alt='F1F5F9'):
    """Applica righe alternate alla tabella Word (skip header)."""
    for i, row in enumerate(table.rows):
        if i == 0:
            continue
        bg = color_alt if (i % 2 == 0) else color_light
        for cell in row.cells:
            _style_word_cell_bg(cell, bg)
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.name = 'Calibri'
                    run.font.size = Pt(10)


def style_word_table_total_row(table, bg_color='1E293B', font_color='FFFFFF'):
    """Applica stile alla riga di totale (ultima riga) di una tabella Word."""
    if not table.rows:
        return
    last_row = table.rows[-1]
    for cell in last_row.cells:
        _style_word_cell_bg(cell, bg_color)
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.bold = True
                run.font.color.rgb = RGBColor.from_string(font_color)
                run.font.name = 'Calibri'
                run.font.size = Pt(10)


def add_word_page_number_footer(doc):
    """Aggiunge un footer con numero pagina al documento Word."""
    section = doc.sections[0]
    footer = section.footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    run = p.add_run('Pagina ')
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor.from_string('64748B')

    # PAGE field
    fld_char_begin = OxmlElement('w:fldChar')
    fld_char_begin.set(qn('w:fldCharType'), 'begin')
    instr_text = OxmlElement('w:instrText')
    instr_text.set(qn('xml:space'), 'preserve')
    instr_text.text = 'PAGE'
    fld_char_end = OxmlElement('w:fldChar')
    fld_char_end.set(qn('w:fldCharType'), 'end')

    page_run = p.add_run()
    page_run.font.size = Pt(9)
    page_run.font.color.rgb = RGBColor.from_string('64748B')
    page_run._r.append(fld_char_begin)
    page_run._r.append(instr_text)
    page_run._r.append(fld_char_end)

    run2 = p.add_run(' di ')
    run2.font.size = Pt(9)
    run2.font.color.rgb = RGBColor.from_string('64748B')

    # NUMPAGES field
    fld_char_begin2 = OxmlElement('w:fldChar')
    fld_char_begin2.set(qn('w:fldCharType'), 'begin')
    instr_text2 = OxmlElement('w:instrText')
    instr_text2.set(qn('xml:space'), 'preserve')
    instr_text2.text = 'NUMPAGES'
    fld_char_end2 = OxmlElement('w:fldChar')
    fld_char_end2.set(qn('w:fldCharType'), 'end')

    numpages_run = p.add_run()
    numpages_run.font.size = Pt(9)
    numpages_run.font.color.rgb = RGBColor.from_string('64748B')
    numpages_run._r.append(fld_char_begin2)
    numpages_run._r.append(instr_text2)
    numpages_run._r.append(fld_char_end2)


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
    """Aggiorna rendicontazione per più utenti"""
    data = request.json
    updates = data.get('updates', [])

    for update in updates:
        utente_id = update.get('utente_id')
        if utente_id:
            db.get_or_create_rendicontazione(utente_id, anno, mese)
            db.update_rendicontazione(
                utente_id, anno, mese,
                ore_lavorate=update.get('ore_lavorate_60'),
                pasti=update.get('pasti'),
                note=update.get('note')
            )

    return jsonify({'success': True})


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

    copiati = 0
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
            db.get_or_create_rendicontazione(uid, anno, mese)
            db.update_rendicontazione(uid, anno, mese, ore_lavorate=ore_prec)
            copiati += 1

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
    compilati = 0

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
            db.get_or_create_rendicontazione(uid, anno, mese)
            db.update_rendicontazione(uid, anno, mese, ore_lavorate=round(media, 2))
            compilati += 1

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
            (1, 11),  # Ognissanti
            (8, 12),  # Immacolata
            (25, 12), # Natale
            (26, 12), # Santo Stefano
        }

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
            """Conta giorni feriali (lun-ven) tra inizio e fine inclusi, escluse festivita'."""
            count = 0
            d = inizio
            while d <= fine:
                if d.weekday() < 5 and (d.day, d.month) not in FESTIVITA_FISSE:
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


# ==================== EXPORT PREMIUM ====================

@app.route('/api/export/excel/<int:anno>/<int:mese>')
def api_export_excel(anno, mese):
    """Esporta rendicontazione in Excel - Versione Premium"""
    commessa = request.args.get('commessa')
    privacy = request.args.get('privacy', 'false').lower() == 'true'

    dati = db.get_rendicontazione_completa(anno, mese, commessa)
    totali_scuola = db.get_totali_per_scuola(anno, mese, commessa)

    # Costanti per calcolo fatturazione
    TARIFFA = config.TARIFFA_ORARIA
    IVA_PERC = config.IVA_PERCENTUALE

    # Calcola totali ore
    ore_totali_60 = sum(d['ore_lavorate_60'] or 0 for d in dati)
    ore_totali_100 = sum(d['ore_lavorate_100'] or 0 for d in dati)
    ore_previste = sum(d['media_con_assenza_60'] or 0 for d in dati)

    # Calcolo fatturazione corretto (sul totale, non somma di arrotondamenti)
    imponibile_totale = round(ore_totali_100 * TARIFFA, 2)
    iva_totale = round(imponibile_totale * IVA_PERC, 2)
    totale_lordo = round(imponibile_totale + iva_totale, 2)

    # Calcola statistiche avanzate
    totale_generale = {
        'num_utenti': len(dati),
        'ore_lavorate_60': ore_totali_60,
        'ore_lavorate_100': ore_totali_100,
        'ore_previste': ore_previste,
        'imponibile_100': imponibile_totale,
        'iva_100': iva_totale,
        'totale_100': totale_lordo,
        'pasti': sum(d['pasti'] or 0 for d in dati),
        'credito_debito': sum(d['credito_debito'] or 0 for d in dati)
    }

    # Calcola percentuale completamento
    if totale_generale['ore_previste'] > 0:
        perc_completamento = (totale_generale['ore_lavorate_60'] / totale_generale['ore_previste']) * 100
    else:
        perc_completamento = 0

    # Determina anno scolastico
    if mese >= 9:
        anno_scolastico = f"{anno}/{anno+1}"
    else:
        anno_scolastico = f"{anno-1}/{anno}"

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book

        # ========== DEFINIZIONE FORMATI PREMIUM ==========
        # Colori brand
        PRIMARY_COLOR = config.PRIMARY_COLOR
        PRIMARY_DARK = config.PRIMARY_DARK
        SUCCESS_COLOR = config.SUCCESS_COLOR
        DANGER_COLOR = config.DANGER_COLOR
        WARNING_COLOR = config.WARNING_COLOR
        DARK_COLOR = config.DARK_COLOR
        LIGHT_COLOR = config.LIGHT_COLOR

        # Formato titolo principale
        title_fmt = workbook.add_format({
            'bold': True,
            'font_size': 24,
            'font_color': DARK_COLOR,
            'align': 'left',
            'valign': 'vcenter'
        })

        # Formato sottotitolo
        subtitle_fmt = workbook.add_format({
            'font_size': 12,
            'font_color': '#64748B',
            'align': 'left'
        })

        # Formato header tabella
        header_fmt = workbook.add_format({
            'bold': True,
            'font_size': 10,
            'font_color': 'white',
            'bg_color': PRIMARY_COLOR,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'border_color': PRIMARY_DARK,
            'text_wrap': True
        })

        # Formato cella normale
        cell_fmt = workbook.add_format({
            'font_size': 10,
            'align': 'left',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#E2E8F0'
        })

        # Formato numeri
        number_fmt = workbook.add_format({
            'font_size': 10,
            'num_format': '#,##0.00',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#E2E8F0'
        })

        # Formato valuta
        money_fmt = workbook.add_format({
            'font_size': 10,
            'num_format': '€ #,##0.00',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#E2E8F0',
            'font_color': SUCCESS_COLOR
        })

        # Formato credito (positivo)
        credit_fmt = workbook.add_format({
            'font_size': 10,
            'num_format': '#,##0.00',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#E2E8F0',
            'font_color': SUCCESS_COLOR,
            'bold': True
        })

        # Formato debito (negativo)
        debit_fmt = workbook.add_format({
            'font_size': 10,
            'num_format': '#,##0.00',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#E2E8F0',
            'font_color': DANGER_COLOR,
            'bold': True
        })

        # Formato totale riga
        total_fmt = workbook.add_format({
            'bold': True,
            'font_size': 10,
            'bg_color': '#EEF2FF',
            'align': 'right',
            'valign': 'vcenter',
            'border': 2,
            'border_color': PRIMARY_COLOR
        })

        # Formato totale valuta
        total_money_fmt = workbook.add_format({
            'bold': True,
            'font_size': 10,
            'num_format': '€ #,##0.00',
            'bg_color': '#EEF2FF',
            'align': 'right',
            'valign': 'vcenter',
            'border': 2,
            'border_color': PRIMARY_COLOR,
            'font_color': PRIMARY_DARK
        })

        # Formato KPI
        kpi_label_fmt = workbook.add_format({
            'font_size': 10,
            'font_color': '#64748B',
            'align': 'left',
            'valign': 'vcenter'
        })

        kpi_value_fmt = workbook.add_format({
            'bold': True,
            'font_size': 14,
            'font_color': DARK_COLOR,
            'align': 'left',
            'valign': 'vcenter'
        })

        kpi_money_fmt = workbook.add_format({
            'bold': True,
            'font_size': 14,
            'font_color': SUCCESS_COLOR,
            'num_format': '€ #,##0.00',
            'align': 'left',
            'valign': 'vcenter'
        })

        # ========== FOGLIO 1: RIEPILOGO ESECUTIVO ==========
        ws_summary = workbook.add_worksheet('Riepilogo')

        # Titolo report
        ws_summary.set_row(0, 40)
        ws_summary.write('A1', f'RENDICONTAZIONE OEPAC - {MESI_NOME[mese]} {anno}', title_fmt)
        ws_summary.write('A2', f'Anno Scolastico {anno_scolastico}', subtitle_fmt)
        if commessa:
            ws_summary.write('A3', f'Commessa: {commessa}', subtitle_fmt)

        ws_summary.write('A5', f'Generato il: {datetime.now().strftime("%d/%m/%Y alle %H:%M")}', subtitle_fmt)

        # KPI Cards
        ws_summary.write('A7', 'INDICATORI CHIAVE DI PERFORMANCE', workbook.add_format({
            'bold': True, 'font_size': 14, 'font_color': DARK_COLOR
        }))

        # Converti ore 60' in formato HH:MM per visualizzazione
        ore_60_formatted = decimal_to_sessagesimal(totale_generale['ore_lavorate_60'])

        kpis = [
            ('Utenti Totali', totale_generale['num_utenti'], None),
            ('Ore Lavorate (60\')', ore_60_formatted, None),
            ('Ore Previste (-11%)', round(totale_generale['ore_previste'], 2), None),
            ('% Completamento', f'{perc_completamento:.1f}%', None),
            ('Imponibile Totale', totale_generale['imponibile_100'], 'money'),
            ('IVA 5%', totale_generale['iva_100'], 'money'),
            ('Totale Lordo', totale_generale['totale_100'], 'money'),
            ('Credito/Debito Ore', round(totale_generale['credito_debito'], 2), None),
            ('Pasti Totali', totale_generale['pasti'], None),
        ]

        row = 8
        col = 0
        for i, (label, value, fmt_type) in enumerate(kpis):
            if i > 0 and i % 3 == 0:
                row += 3
                col = 0

            ws_summary.write(row, col, label, kpi_label_fmt)
            if fmt_type == 'money':
                ws_summary.write(row + 1, col, value, kpi_money_fmt)
            else:
                ws_summary.write(row + 1, col, value, kpi_value_fmt)
            col += 2

        # Riepilogo per scuola
        ws_summary.write(row + 5, 0, 'RIEPILOGO PER SCUOLA', workbook.add_format({
            'bold': True, 'font_size': 14, 'font_color': DARK_COLOR
        }))

        headers_scuola = ['Commessa', 'Scuola', 'Utenti', 'Ore (60\')', 'Ore (100\')', 'Imponibile', 'Totale']
        for c, h in enumerate(headers_scuola):
            ws_summary.write(row + 7, c, h, header_fmt)

        for i, t in enumerate(totali_scuola):
            r = row + 8 + i
            ws_summary.write(r, 0, t['commessa'], cell_fmt)
            ws_summary.write(r, 1, t['scuola'], cell_fmt)
            ws_summary.write(r, 2, t['num_utenti'], number_fmt)
            ws_summary.write(r, 3, decimal_to_sessagesimal(t['ore_lavorate_60']), cell_fmt)
            ws_summary.write(r, 4, t['ore_lavorate_100'], number_fmt)
            ws_summary.write(r, 5, t['imponibile_100'], money_fmt)
            ws_summary.write(r, 6, t['totale_100'], money_fmt)

        # Imposta larghezza colonne - B più larga per nomi scuole completi
        ws_summary.set_column('A:A', 20)
        ws_summary.set_column('B:B', 60)
        ws_summary.set_column('C:G', 15)

        # ========== FOGLIO 2: DETTAGLIO COMPLETO ==========
        ws_detail = workbook.add_worksheet('Dettaglio')

        # Header
        ws_detail.set_row(0, 30)
        ws_detail.write('A1', f'Dettaglio Rendicontazione - {MESI_NOME[mese]} {anno}', title_fmt)

        headers = [
            'Commessa', 'Scuola', 'Utente', 'A.C.', 'Monte Ore',
            'Media Mens.', 'Media -11%', 'Ore Lav. (60\')', 'Ore (100\')',
            'Imponibile', 'IVA 5%', 'Totale', 'Pasti', 'Cred/Deb', 'Lista Attesa'
        ]

        for c, h in enumerate(headers):
            ws_detail.write(2, c, h, header_fmt)

        # Dati
        for i, d in enumerate(dati):
            r = 3 + i
            utente = d['nome_puntato'] if privacy else f"{d['nome']} {d['cognome']}"

            ws_detail.write(r, 0, d['commessa'], cell_fmt)
            ws_detail.write(r, 1, d['scuola'], cell_fmt)
            ws_detail.write(r, 2, utente, cell_fmt)
            ws_detail.write(r, 3, d['nome_puntato'], cell_fmt)
            ws_detail.write(r, 4, d['monte_ore_settimanale'], number_fmt)
            ws_detail.write(r, 5, d['media_mensile_60'], number_fmt)
            ws_detail.write(r, 6, d['media_con_assenza_60'], number_fmt)
            ws_detail.write(r, 7, decimal_to_sessagesimal(d['ore_lavorate_60'] or 0), cell_fmt)
            ws_detail.write(r, 8, d['ore_lavorate_100'] or 0, number_fmt)
            ws_detail.write(r, 9, d['imponibile_100'] or 0, money_fmt)
            ws_detail.write(r, 10, d['iva_100'] or 0, money_fmt)
            ws_detail.write(r, 11, d['totale_100'] or 0, money_fmt)
            ws_detail.write(r, 12, d['pasti'] or 0, number_fmt)

            # Credito/Debito con colore condizionale
            cd = d['credito_debito'] or 0
            ws_detail.write(r, 13, cd, credit_fmt if cd >= 0 else debit_fmt)

            # Lista Attesa
            ws_detail.write(r, 14, d.get('lista_attesa') or '', cell_fmt)

        # Riga totali
        total_row = 3 + len(dati)
        ws_detail.write(total_row, 0, 'TOTALE', total_fmt)
        ws_detail.write(total_row, 7, decimal_to_sessagesimal(totale_generale['ore_lavorate_60']), total_fmt)
        ws_detail.write(total_row, 8, totale_generale['ore_lavorate_100'], total_fmt)
        ws_detail.write(total_row, 9, totale_generale['imponibile_100'], total_money_fmt)
        ws_detail.write(total_row, 10, totale_generale['iva_100'], total_money_fmt)
        ws_detail.write(total_row, 11, totale_generale['totale_100'], total_money_fmt)
        ws_detail.write(total_row, 12, totale_generale['pasti'], total_fmt)
        ws_detail.write(total_row, 13, totale_generale['credito_debito'], total_fmt)
        ws_detail.write(total_row, 14, '', total_fmt)

        # Larghezza colonne - B più larga per nomi scuole completi
        ws_detail.set_column('A:A', 12)
        ws_detail.set_column('B:B', 55)
        ws_detail.set_column('C:C', 25)
        ws_detail.set_column('D:D', 8)
        ws_detail.set_column('E:N', 12)
        ws_detail.set_column('O:O', 12)

        # Freeze panes
        ws_detail.freeze_panes(3, 0)

        # ========== FOGLIO 3: ANALISI STATISTICHE ==========
        ws_stats = workbook.add_worksheet('Statistiche')

        ws_stats.write('A1', 'ANALISI STATISTICHE', title_fmt)
        ws_stats.write('A3', 'Distribuzione Ore per Commessa', workbook.add_format({
            'bold': True, 'font_size': 12
        }))

        # Raggruppa per commessa
        commesse_stats = {}
        for d in dati:
            c = d['commessa']
            if c not in commesse_stats:
                commesse_stats[c] = {'ore': 0, 'utenti': 0, 'totale': 0}
            commesse_stats[c]['ore'] += d['ore_lavorate_60'] or 0
            commesse_stats[c]['utenti'] += 1
            commesse_stats[c]['totale'] += d['totale_100'] or 0

        ws_stats.write(4, 0, 'Commessa', header_fmt)
        ws_stats.write(4, 1, 'Utenti', header_fmt)
        ws_stats.write(4, 2, 'Ore Totali', header_fmt)
        ws_stats.write(4, 3, 'Fatturato', header_fmt)

        row = 5
        for c, stats in commesse_stats.items():
            ws_stats.write(row, 0, c, cell_fmt)
            ws_stats.write(row, 1, stats['utenti'], number_fmt)
            ws_stats.write(row, 2, stats['ore'], number_fmt)
            ws_stats.write(row, 3, stats['totale'], money_fmt)
            row += 1

        # Grafico a torta per distribuzione ore
        if len(commesse_stats) > 0:
            chart = workbook.add_chart({'type': 'pie'})
            chart.add_series({
                'name': 'Distribuzione Ore',
                'categories': f'=Statistiche!$A$6:$A${5 + len(commesse_stats)}',
                'values': f'=Statistiche!$C$6:$C${5 + len(commesse_stats)}',
                'data_labels': {'percentage': True, 'category': True}
            })
            chart.set_title({'name': 'Distribuzione Ore per Commessa'})
            chart.set_style(10)
            ws_stats.insert_chart('F3', chart, {'x_scale': 1.2, 'y_scale': 1.2})

        # Grafico a barre per fatturato
        if len(commesse_stats) > 0:
            chart2 = workbook.add_chart({'type': 'column'})
            chart2.add_series({
                'name': 'Fatturato',
                'categories': f'=Statistiche!$A$6:$A${5 + len(commesse_stats)}',
                'values': f'=Statistiche!$D$6:$D${5 + len(commesse_stats)}',
                'fill': {'color': PRIMARY_COLOR}
            })
            chart2.set_title({'name': 'Fatturato per Commessa'})
            chart2.set_style(10)
            chart2.set_y_axis({'num_format': '€ #,##0'})
            ws_stats.insert_chart('F18', chart2, {'x_scale': 1.2, 'y_scale': 1.2})

        ws_stats.set_column('A:D', 15)

        # ========== FOGLIO 4: DETTAGLIO PER SCUOLA (RAGGRUPPATO) ==========
        ws_scuola = workbook.add_worksheet('Dettaglio per Scuola')

        # Formato per header scuola
        scuola_header_fmt = workbook.add_format({
            'bold': True,
            'font_size': 11,
            'font_color': 'white',
            'bg_color': '#5B5FC7',
            'align': 'left',
            'valign': 'vcenter',
            'border': 1
        })

        # Formato celle utente
        utente_cell_fmt = workbook.add_format({
            'font_size': 9,
            'align': 'left',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#E2E8F0',
            'indent': 1
        })

        utente_number_fmt = workbook.add_format({
            'font_size': 9,
            'num_format': '#,##0.00',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#E2E8F0'
        })

        utente_money_fmt = workbook.add_format({
            'font_size': 9,
            'num_format': '€ #,##0.00',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#E2E8F0'
        })

        # Header del foglio
        ws_scuola.set_row(0, 30)
        ws_scuola.write('A1', f'Dettaglio per Scuola - {MESI_NOME[mese]} {anno}', title_fmt)

        # Raggruppa dati per scuola
        scuole_dict = {}
        for d in dati:
            scuola = d['scuola']
            if scuola not in scuole_dict:
                scuole_dict[scuola] = []
            scuole_dict[scuola].append(d)

        # Headers colonne dati utente
        detail_headers = ['Nome Puntato', 'Monte Ore', 'Media Mens.', 'Media -11%', 'Ore Lav. (60\')',
                          'Ore (100\')', 'Imponibile', 'IVA 5%', 'Totale', 'Pasti', 'Cred/Deb', 'Lista Attesa']

        row = 3
        for scuola, utenti in sorted(scuole_dict.items()):
            # Riga header scuola (espandibile)
            ws_scuola.merge_range(row, 0, row, len(detail_headers), f'⊟ {scuola}', scuola_header_fmt)
            row += 1

            # Header colonne per questa scuola
            for col, h in enumerate(detail_headers):
                ws_scuola.write(row, col, h, header_fmt)
            row += 1

            # Dati utenti
            for u in utenti:
                nome_puntato = u['nome_puntato'] if privacy else f"{u['nome']} {u['cognome']}"
                ws_scuola.write(row, 0, nome_puntato, utente_cell_fmt)
                ws_scuola.write(row, 1, u['monte_ore_settimanale'], utente_number_fmt)
                ws_scuola.write(row, 2, u['media_mensile_60'] or 0, utente_number_fmt)
                ws_scuola.write(row, 3, u['media_con_assenza_60'] or 0, utente_number_fmt)
                ws_scuola.write(row, 4, decimal_to_sessagesimal(u['ore_lavorate_60'] or 0), utente_cell_fmt)
                ws_scuola.write(row, 5, u['ore_lavorate_100'] or 0, utente_number_fmt)
                ws_scuola.write(row, 6, u['imponibile_100'] or 0, utente_money_fmt)
                ws_scuola.write(row, 7, u['iva_100'] or 0, utente_money_fmt)
                ws_scuola.write(row, 8, u['totale_100'] or 0, utente_money_fmt)
                ws_scuola.write(row, 9, u['pasti'] or 0, utente_number_fmt)
                ws_scuola.write(row, 10, u['credito_debito'] or 0, utente_number_fmt)
                ws_scuola.write(row, 11, u.get('lista_attesa') or '', utente_cell_fmt)
                row += 1

            # Riga vuota tra scuole
            row += 1

        # Larghezza colonne
        ws_scuola.set_column('A:A', 15)
        ws_scuola.set_column('B:L', 12)

    output.seek(0)

    filename = f"OEPAC_Rendicontazione_{MESI_NOME[mese]}_{anno}"
    if commessa:
        filename += f"_{commessa.replace(' ', '_')}"
    if privacy:
        filename += "_privacy"
    filename += ".xlsx"

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


@app.route('/api/export/annuale/<anno_scolastico>')
def api_export_annuale(anno_scolastico):
    """Esporta rendicontazione annuale - Versione Premium"""
    commessa = request.args.get('commessa')
    privacy = request.args.get('privacy', 'false').lower() == 'true'

    # Parse anno scolastico
    anni = anno_scolastico.split('-')
    anno_inizio = int(anni[0])
    anno_fine = int(anni[1])

    # Costanti
    TARIFFA = config.TARIFFA_ORARIA
    IVA_PERC = config.IVA_PERCENTUALE
    TASSO_ASSENZA = config.TASSO_ASSENZA

    # Raccogli tutti i dati dell'anno per calcoli aggregati
    tutti_dati_anno = {}  # {mese: dati}
    utenti_aggregati = {}  # {utente_id: {dati aggregati}}

    for mese in MESI_SCOLASTICI:
        anno = anno_inizio if mese >= 9 else anno_fine
        dati = db.get_rendicontazione_completa(anno, mese, commessa)
        tutti_dati_anno[mese] = {'anno': anno, 'dati': dati}

        # Aggrega per utente
        for d in dati:
            utente_key = d['utente_id']
            if utente_key not in utenti_aggregati:
                utenti_aggregati[utente_key] = {
                    'nome': d['nome'],
                    'cognome': d['cognome'],
                    'nome_puntato': d['nome_puntato'],
                    'scuola': d['scuola'],
                    'commessa': d['commessa'],
                    'monte_ore_settimanale': d['monte_ore_settimanale'],
                    'ore_erogate_totali': 0,
                    'monte_ore_previsto_totale': 0,  # Somma delle medie mensili -11%
                    'pasti_totali': 0,
                    'imponibile_totale': 0,
                    'mesi_attivi': 0
                }
            utenti_aggregati[utente_key]['ore_erogate_totali'] += d['ore_lavorate_60'] or 0
            utenti_aggregati[utente_key]['monte_ore_previsto_totale'] += d['media_con_assenza_60'] or 0
            utenti_aggregati[utente_key]['pasti_totali'] += d['pasti'] or 0
            utenti_aggregati[utente_key]['imponibile_totale'] += d['imponibile_100'] or 0
            utenti_aggregati[utente_key]['mesi_attivi'] += 1

    # Calcola totali annuali
    totale_ore_60 = sum(
        sum(d['ore_lavorate_60'] or 0 for d in m['dati'])
        for m in tutti_dati_anno.values()
    )
    totale_ore_100 = sum(
        sum(d['ore_lavorate_100'] or 0 for d in m['dati'])
        for m in tutti_dati_anno.values()
    )
    totale_ore_previste = sum(
        sum(d['media_con_assenza_60'] or 0 for d in m['dati'])
        for m in tutti_dati_anno.values()
    )
    totale_pasti = sum(
        sum(d['pasti'] or 0 for d in m['dati'])
        for m in tutti_dati_anno.values()
    )
    imponibile_annuale = round(totale_ore_100 * TARIFFA, 2)
    iva_annuale = round(imponibile_annuale * IVA_PERC, 2)
    totale_lordo_annuale = round(imponibile_annuale + iva_annuale, 2)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book

        # ========== DEFINIZIONE FORMATI PREMIUM ==========
        PRIMARY_COLOR = config.PRIMARY_COLOR
        PRIMARY_DARK = config.PRIMARY_DARK
        SUCCESS_COLOR = config.SUCCESS_COLOR
        DANGER_COLOR = config.DANGER_COLOR
        WARNING_COLOR = config.WARNING_COLOR
        DARK_COLOR = config.DARK_COLOR
        LIGHT_COLOR = config.LIGHT_COLOR

        # Formato titolo principale
        title_fmt = workbook.add_format({
            'bold': True,
            'font_size': 24,
            'font_color': DARK_COLOR,
            'align': 'left',
            'valign': 'vcenter'
        })

        # Formato sottotitolo
        subtitle_fmt = workbook.add_format({
            'font_size': 12,
            'font_color': '#64748B',
            'align': 'left'
        })

        # Formato sezione
        section_fmt = workbook.add_format({
            'bold': True,
            'font_size': 14,
            'font_color': DARK_COLOR,
            'bottom': 2,
            'bottom_color': PRIMARY_COLOR
        })

        # Formato header tabella
        header_fmt = workbook.add_format({
            'bold': True,
            'font_size': 10,
            'font_color': 'white',
            'bg_color': PRIMARY_COLOR,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'border_color': PRIMARY_DARK,
            'text_wrap': True
        })

        # Formato header alternativo (grigio)
        header_alt_fmt = workbook.add_format({
            'bold': True,
            'font_size': 10,
            'font_color': 'white',
            'bg_color': '#475569',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'text_wrap': True
        })

        # Formato cella normale
        cell_fmt = workbook.add_format({
            'font_size': 10,
            'align': 'left',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#E2E8F0'
        })

        # Formato cella alternata (zebra)
        cell_alt_fmt = workbook.add_format({
            'font_size': 10,
            'align': 'left',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#E2E8F0',
            'bg_color': '#F8FAFC'
        })

        # Formato numeri
        number_fmt = workbook.add_format({
            'font_size': 10,
            'num_format': '#,##0.00',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#E2E8F0'
        })

        number_alt_fmt = workbook.add_format({
            'font_size': 10,
            'num_format': '#,##0.00',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#E2E8F0',
            'bg_color': '#F8FAFC'
        })

        # Formato valuta
        money_fmt = workbook.add_format({
            'font_size': 10,
            'num_format': '€ #,##0.00',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#E2E8F0',
            'font_color': SUCCESS_COLOR
        })

        money_alt_fmt = workbook.add_format({
            'font_size': 10,
            'num_format': '€ #,##0.00',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#E2E8F0',
            'font_color': SUCCESS_COLOR,
            'bg_color': '#F8FAFC'
        })

        # Formato credito (positivo)
        credit_fmt = workbook.add_format({
            'font_size': 10,
            'num_format': '+#,##0.00;-#,##0.00',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#E2E8F0',
            'font_color': SUCCESS_COLOR,
            'bold': True
        })

        credit_alt_fmt = workbook.add_format({
            'font_size': 10,
            'num_format': '+#,##0.00;-#,##0.00',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#E2E8F0',
            'font_color': SUCCESS_COLOR,
            'bold': True,
            'bg_color': '#F8FAFC'
        })

        # Formato debito (negativo)
        debit_fmt = workbook.add_format({
            'font_size': 10,
            'num_format': '+#,##0.00;-#,##0.00',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#E2E8F0',
            'font_color': DANGER_COLOR,
            'bold': True
        })

        debit_alt_fmt = workbook.add_format({
            'font_size': 10,
            'num_format': '+#,##0.00;-#,##0.00',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#E2E8F0',
            'font_color': DANGER_COLOR,
            'bold': True,
            'bg_color': '#F8FAFC'
        })

        # Formato totale riga
        total_fmt = workbook.add_format({
            'bold': True,
            'font_size': 10,
            'bg_color': '#EEF2FF',
            'align': 'right',
            'valign': 'vcenter',
            'border': 2,
            'border_color': PRIMARY_COLOR
        })

        total_text_fmt = workbook.add_format({
            'bold': True,
            'font_size': 10,
            'bg_color': '#EEF2FF',
            'align': 'left',
            'valign': 'vcenter',
            'border': 2,
            'border_color': PRIMARY_COLOR
        })

        # Formato totale valuta
        total_money_fmt = workbook.add_format({
            'bold': True,
            'font_size': 10,
            'num_format': '€ #,##0.00',
            'bg_color': '#EEF2FF',
            'align': 'right',
            'valign': 'vcenter',
            'border': 2,
            'border_color': PRIMARY_COLOR,
            'font_color': PRIMARY_DARK
        })

        # Formato KPI
        kpi_label_fmt = workbook.add_format({
            'font_size': 10,
            'font_color': '#64748B',
            'align': 'left',
            'valign': 'vcenter'
        })

        kpi_value_fmt = workbook.add_format({
            'bold': True,
            'font_size': 16,
            'font_color': DARK_COLOR,
            'align': 'left',
            'valign': 'vcenter'
        })

        kpi_money_fmt = workbook.add_format({
            'bold': True,
            'font_size': 16,
            'font_color': SUCCESS_COLOR,
            'num_format': '€ #,##0.00',
            'align': 'left',
            'valign': 'vcenter'
        })

        kpi_box_fmt = workbook.add_format({
            'bg_color': '#F1F5F9',
            'border': 1,
            'border_color': '#E2E8F0'
        })

        # ========== FOGLIO 1: DASHBOARD ANNUALE ==========
        ws_dashboard = workbook.add_worksheet('Dashboard')

        # Titolo
        ws_dashboard.set_row(0, 45)
        ws_dashboard.merge_range('A1:H1', f'RIEPILOGO ANNUALE OEPAC', title_fmt)
        ws_dashboard.write('A2', f'Anno Scolastico {anno_scolastico}', subtitle_fmt)
        if commessa:
            ws_dashboard.write('A3', f'Commessa: {commessa}', subtitle_fmt)
        ws_dashboard.write('A4', f'Generato il: {datetime.now().strftime("%d/%m/%Y alle %H:%M")}', subtitle_fmt)

        # Sezione KPI principali
        ws_dashboard.write('A6', 'INDICATORI CHIAVE ANNUALI', section_fmt)

        # Calcola percentuale completamento
        perc_completamento = (totale_ore_60 / totale_ore_previste * 100) if totale_ore_previste > 0 else 0

        kpis = [
            ('Utenti Attivi', len(utenti_aggregati), None),
            ('Ore Erogate Totali', decimal_to_sessagesimal(totale_ore_60), None),
            ('Ore Previste (-11%)', decimal_to_sessagesimal(totale_ore_previste), None),
            ('Completamento', f'{perc_completamento:.1f}%', None),
            ('Imponibile Annuale', imponibile_annuale, 'money'),
            ('IVA 5%', iva_annuale, 'money'),
            ('Totale Lordo', totale_lordo_annuale, 'money'),
            ('Pasti Totali', totale_pasti, None),
        ]

        row = 7
        col = 0
        for i, (label, value, fmt_type) in enumerate(kpis):
            if i > 0 and i % 4 == 0:
                row += 3
                col = 0

            ws_dashboard.write(row, col, label, kpi_label_fmt)
            if fmt_type == 'money':
                ws_dashboard.write(row + 1, col, value, kpi_money_fmt)
            else:
                ws_dashboard.write(row + 1, col, value, kpi_value_fmt)
            col += 2

        # Sezione Riepilogo Mensile
        ws_dashboard.write(row + 5, 0, 'ANDAMENTO MENSILE', section_fmt)

        headers_mese = ['Mese', 'Utenti', 'Ore Erogate', 'Ore Previste', 'Completamento', 'Imponibile', 'Totale', 'Pasti']
        for c, h in enumerate(headers_mese):
            ws_dashboard.write(row + 7, c, h, header_fmt)

        riepilogo_row = row + 8
        totali_riepilogo = {'utenti': 0, 'ore': 0, 'previste': 0, 'imponibile': 0, 'totale': 0, 'pasti': 0}

        for mese in MESI_SCOLASTICI:
            anno = tutti_dati_anno[mese]['anno']
            dati = tutti_dati_anno[mese]['dati']

            ore_mese = sum(d['ore_lavorate_60'] or 0 for d in dati)
            ore_100_mese = sum(d['ore_lavorate_100'] or 0 for d in dati)
            ore_previste_mese = sum(d['media_con_assenza_60'] or 0 for d in dati)
            imponibile_mese = round(ore_100_mese * TARIFFA, 2)
            iva_mese = round(imponibile_mese * IVA_PERC, 2)
            totale_mese = round(imponibile_mese + iva_mese, 2)
            pasti_mese = sum(d['pasti'] or 0 for d in dati)
            perc_mese = (ore_mese / ore_previste_mese * 100) if ore_previste_mese > 0 else 0

            is_alt = (riepilogo_row - row - 8) % 2 == 1
            cf = cell_alt_fmt if is_alt else cell_fmt
            nf = number_alt_fmt if is_alt else number_fmt
            mf = money_alt_fmt if is_alt else money_fmt

            ws_dashboard.write(riepilogo_row, 0, f'{MESI_NOME[mese]} {anno}', cf)
            ws_dashboard.write(riepilogo_row, 1, len(dati), nf)
            ws_dashboard.write(riepilogo_row, 2, decimal_to_sessagesimal(ore_mese), cf)
            ws_dashboard.write(riepilogo_row, 3, decimal_to_sessagesimal(ore_previste_mese), cf)
            ws_dashboard.write(riepilogo_row, 4, f'{perc_mese:.1f}%', cf)
            ws_dashboard.write(riepilogo_row, 5, imponibile_mese, mf)
            ws_dashboard.write(riepilogo_row, 6, totale_mese, mf)
            ws_dashboard.write(riepilogo_row, 7, pasti_mese, nf)

            totali_riepilogo['ore'] += ore_mese
            totali_riepilogo['previste'] += ore_previste_mese
            totali_riepilogo['imponibile'] += imponibile_mese
            totali_riepilogo['totale'] += totale_mese
            totali_riepilogo['pasti'] += pasti_mese

            riepilogo_row += 1

        # Riga totali
        ws_dashboard.write(riepilogo_row, 0, 'TOTALE ANNUALE', total_text_fmt)
        ws_dashboard.write(riepilogo_row, 1, len(utenti_aggregati), total_fmt)
        ws_dashboard.write(riepilogo_row, 2, decimal_to_sessagesimal(totali_riepilogo['ore']), total_fmt)
        ws_dashboard.write(riepilogo_row, 3, decimal_to_sessagesimal(totali_riepilogo['previste']), total_fmt)
        perc_tot = (totali_riepilogo['ore'] / totali_riepilogo['previste'] * 100) if totali_riepilogo['previste'] > 0 else 0
        ws_dashboard.write(riepilogo_row, 4, f'{perc_tot:.1f}%', total_fmt)
        ws_dashboard.write(riepilogo_row, 5, totali_riepilogo['imponibile'], total_money_fmt)
        ws_dashboard.write(riepilogo_row, 6, totali_riepilogo['totale'], total_money_fmt)
        ws_dashboard.write(riepilogo_row, 7, totali_riepilogo['pasti'], total_fmt)

        # Larghezza colonne
        ws_dashboard.set_column('A:A', 18)
        ws_dashboard.set_column('B:H', 14)

        # ========== FOGLIO 2: RIEPILOGO UTENTI (NUOVO!) ==========
        ws_utenti = workbook.add_worksheet('Riepilogo Utenti')

        ws_utenti.set_row(0, 40)
        ws_utenti.merge_range('A1:J1', f'RIEPILOGO PER UTENTE - A.S. {anno_scolastico}', title_fmt)
        ws_utenti.write('A2', 'Vista aggregata delle ore erogate per ogni utente', subtitle_fmt)
        ws_utenti.write('A3', f'Monte ore con detrazione assenze previste: {int(TASSO_ASSENZA*100)}%', subtitle_fmt)

        headers_utenti = [
            'Utente', 'Scuola', 'Commessa', 'Monte Ore Sett.',
            'Mesi Attivi', 'Monte Ore Previsto', 'Ore Erogate',
            'Credito/Debito', 'Pasti', 'Imponibile'
        ]

        for c, h in enumerate(headers_utenti):
            ws_utenti.write(5, c, h, header_fmt)

        # Ordina utenti per cognome e nome
        utenti_sorted = sorted(
            utenti_aggregati.values(),
            key=lambda x: (x['cognome'].lower(), x['nome'].lower())
        )

        utente_row = 6
        for i, u in enumerate(utenti_sorted):
            is_alt = i % 2 == 1
            cf = cell_alt_fmt if is_alt else cell_fmt
            nf = number_alt_fmt if is_alt else number_fmt
            mf = money_alt_fmt if is_alt else money_fmt

            utente_nome = u['nome_puntato'] if privacy else f"{u['nome']} {u['cognome']}"
            credito_debito = u['monte_ore_previsto_totale'] - u['ore_erogate_totali']

            # Seleziona formato per credito/debito
            if credito_debito >= 0:
                cd_fmt = credit_alt_fmt if is_alt else credit_fmt
            else:
                cd_fmt = debit_alt_fmt if is_alt else debit_fmt

            ws_utenti.write(utente_row, 0, utente_nome, cf)
            ws_utenti.write(utente_row, 1, u['scuola'], cf)
            ws_utenti.write(utente_row, 2, u['commessa'], cf)
            ws_utenti.write(utente_row, 3, u['monte_ore_settimanale'], nf)
            ws_utenti.write(utente_row, 4, u['mesi_attivi'], nf)
            ws_utenti.write(utente_row, 5, decimal_to_sessagesimal(u['monte_ore_previsto_totale']), cf)
            ws_utenti.write(utente_row, 6, decimal_to_sessagesimal(u['ore_erogate_totali']), cf)
            ws_utenti.write(utente_row, 7, round(credito_debito, 2), cd_fmt)
            ws_utenti.write(utente_row, 8, u['pasti_totali'], nf)
            ws_utenti.write(utente_row, 9, u['imponibile_totale'], mf)

            utente_row += 1

        # Riga totali utenti
        tot_monte_previsto = sum(u['monte_ore_previsto_totale'] for u in utenti_sorted)
        tot_ore_erogate = sum(u['ore_erogate_totali'] for u in utenti_sorted)
        tot_credito_debito = tot_monte_previsto - tot_ore_erogate
        tot_pasti = sum(u['pasti_totali'] for u in utenti_sorted)
        tot_imponibile = sum(u['imponibile_totale'] for u in utenti_sorted)

        ws_utenti.write(utente_row, 0, 'TOTALE', total_text_fmt)
        ws_utenti.write(utente_row, 1, '', total_fmt)
        ws_utenti.write(utente_row, 2, '', total_fmt)
        ws_utenti.write(utente_row, 3, '', total_fmt)
        ws_utenti.write(utente_row, 4, len(utenti_sorted), total_fmt)
        ws_utenti.write(utente_row, 5, decimal_to_sessagesimal(tot_monte_previsto), total_fmt)
        ws_utenti.write(utente_row, 6, decimal_to_sessagesimal(tot_ore_erogate), total_fmt)
        ws_utenti.write(utente_row, 7, round(tot_credito_debito, 2), total_fmt)
        ws_utenti.write(utente_row, 8, tot_pasti, total_fmt)
        ws_utenti.write(utente_row, 9, tot_imponibile, total_money_fmt)

        # Larghezza colonne
        ws_utenti.set_column('A:A', 25)
        ws_utenti.set_column('B:B', 50)
        ws_utenti.set_column('C:C', 15)
        ws_utenti.set_column('D:J', 16)

        # Freeze header
        ws_utenti.freeze_panes(6, 0)

        # ========== FOGLI MENSILI (DETTAGLIO) ==========
        for mese in MESI_SCOLASTICI:
            anno = tutti_dati_anno[mese]['anno']
            dati = tutti_dati_anno[mese]['dati']

            sheet_name = f'{MESI_NOME[mese][:3]} {anno}'
            ws_mese = workbook.add_worksheet(sheet_name)

            # Titolo
            ws_mese.set_row(0, 30)
            ws_mese.merge_range('A1:L1', f'Dettaglio {MESI_NOME[mese]} {anno}', title_fmt)

            # Headers
            headers_mese = [
                'Commessa', 'Scuola', 'Utente', 'Monte Ore',
                'Media Mens.', 'Media -11%', 'Ore (60\')', 'Ore (100\')',
                'Imponibile', 'IVA 5%', 'Totale', 'Cred/Deb', 'Pasti'
            ]

            for c, h in enumerate(headers_mese):
                ws_mese.write(2, c, h, header_fmt)

            # Dati
            for i, d in enumerate(dati):
                r = 3 + i
                is_alt = i % 2 == 1
                cf = cell_alt_fmt if is_alt else cell_fmt
                nf = number_alt_fmt if is_alt else number_fmt
                mf = money_alt_fmt if is_alt else money_fmt

                utente = d['nome_puntato'] if privacy else f"{d['nome']} {d['cognome']}"
                cd = d['credito_debito'] or 0

                if cd >= 0:
                    cd_f = credit_alt_fmt if is_alt else credit_fmt
                else:
                    cd_f = debit_alt_fmt if is_alt else debit_fmt

                ws_mese.write(r, 0, d['commessa'], cf)
                ws_mese.write(r, 1, d['scuola'], cf)
                ws_mese.write(r, 2, utente, cf)
                ws_mese.write(r, 3, d['monte_ore_settimanale'], nf)
                ws_mese.write(r, 4, round(d['media_mensile_60'] or 0, 2), nf)
                ws_mese.write(r, 5, round(d['media_con_assenza_60'] or 0, 2), nf)
                ws_mese.write(r, 6, decimal_to_sessagesimal(d['ore_lavorate_60'] or 0), cf)
                ws_mese.write(r, 7, d['ore_lavorate_100'] or 0, nf)
                ws_mese.write(r, 8, d['imponibile_100'] or 0, mf)
                ws_mese.write(r, 9, d['iva_100'] or 0, mf)
                ws_mese.write(r, 10, d['totale_100'] or 0, mf)
                ws_mese.write(r, 11, cd, cd_f)
                ws_mese.write(r, 12, d['pasti'] or 0, nf)

            # Riga totali
            if dati:
                total_row = 3 + len(dati)
                ore_tot_60 = sum(d['ore_lavorate_60'] or 0 for d in dati)
                ore_tot_100 = sum(d['ore_lavorate_100'] or 0 for d in dati)
                imp_tot = round(ore_tot_100 * TARIFFA, 2)
                iva_tot = round(imp_tot * IVA_PERC, 2)
                tot_tot = round(imp_tot + iva_tot, 2)
                cd_tot = sum(d['credito_debito'] or 0 for d in dati)
                pasti_tot = sum(d['pasti'] or 0 for d in dati)

                ws_mese.write(total_row, 0, 'TOTALE', total_text_fmt)
                for c in range(1, 6):
                    ws_mese.write(total_row, c, '', total_fmt)
                ws_mese.write(total_row, 6, decimal_to_sessagesimal(ore_tot_60), total_fmt)
                ws_mese.write(total_row, 7, ore_tot_100, total_fmt)
                ws_mese.write(total_row, 8, imp_tot, total_money_fmt)
                ws_mese.write(total_row, 9, iva_tot, total_money_fmt)
                ws_mese.write(total_row, 10, tot_tot, total_money_fmt)
                ws_mese.write(total_row, 11, round(cd_tot, 2), total_fmt)
                ws_mese.write(total_row, 12, pasti_tot, total_fmt)

            # Larghezza colonne
            ws_mese.set_column('A:A', 12)
            ws_mese.set_column('B:B', 45)
            ws_mese.set_column('C:C', 22)
            ws_mese.set_column('D:M', 12)

            # Freeze header
            ws_mese.freeze_panes(3, 0)

    output.seek(0)

    filename = f"rendicontazione_annuale_{anno_scolastico}"
    if commessa:
        filename += f"_{commessa.replace(' ', '_')}"
    filename += ".xlsx"

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


# ==================== REPORT MUNICIPALE E DIPARTIMENTALE ====================

def classifica_livello_scolastico(scuola_nome):
    """
    Classifica una scuola per livello scolastico in base al nome.
    Ritorna una tupla (livello, ordine) per ordinamento.

    Esempi:
    - /IC ANAGNI/Infanzia/ANAGNI - Via Anagni, 48 → Infanzia Statale (dentro IC)
    - /INFANZIA COMUNALE/TOTI - Via del Pigneto, 104 → Infanzia Capitolina
    - /IC ANAGNI/Primaria/FIUGGI - Via Fiuggi, 18 → Primaria e Secondaria I° Statale
    - /IC ANAGNI/Secondaria/TONIOLO - Via Anagni, 46 → Primaria e Secondaria I° Statale
    """
    nome_upper = scuola_nome.upper()

    # 1. Infanzia Capitolina = contiene "INFANZIA COMUNALE"
    if 'INFANZIA COMUNALE' in nome_upper:
        return ('Infanzia Capitolina', 1)

    # 2. Scuole Paritarie = contiene "PARITARI"
    if 'PARITARI' in nome_upper:
        if 'INFANZIA' in nome_upper:
            return ('Infanzia Paritaria', 3)
        else:
            return ('Primaria e Secondaria I° Paritaria', 5)

    # 3. Scuole dentro IC = contiene "/IC " all'inizio del path
    # Es: /IC ANAGNI/Infanzia/... o /IC ANAGNI/Primaria/...
    if '/IC ' in nome_upper:
        # Cerca il tipo di scuola nel nome
        if 'INFANZIA' in nome_upper:
            return ('Infanzia Statale', 2)
        elif 'PRIMARIA' in nome_upper or 'SECONDARIA' in nome_upper:
            return ('Primaria e Secondaria I° Statale', 4)
        else:
            # IC senza tipo specifico → default primaria/secondaria
            return ('Primaria e Secondaria I° Statale', 4)

    # 4. Altre scuole con "INFANZIA" ma senza "COMUNALE" e senza "IC"
    # → probabilmente capitoline non etichettate correttamente
    if 'INFANZIA' in nome_upper:
        return ('Infanzia Capitolina', 1)

    # 5. Default finale
    return ('Primaria e Secondaria I° Statale', 4)


@app.route('/api/export/municipale/<int:anno>/<int:mese>')
def api_export_municipale(anno, mese):
    """Esporta Riepilogo Municipale - Report per il Municipio"""
    commessa = request.args.get('commessa')

    dati = db.get_rendicontazione_completa(anno, mese, commessa)
    totali_scuola = db.get_totali_per_scuola(anno, mese, commessa)

    # Costanti
    TARIFFA = config.TARIFFA_ORARIA
    IVA_PERC = config.IVA_PERCENTUALE

    # Determina anno scolastico
    if mese >= 9:
        anno_scolastico = f"{anno}/{anno+1}"
    else:
        anno_scolastico = f"{anno-1}/{anno}"

    # Calcola totali generali
    totale_generale = {
        'num_utenti': len(dati),
        'utenti_lista_attesa': sum(1 for d in dati if d.get('lista_attesa')),
        'ore_previste': sum(d['media_con_assenza_60'] or 0 for d in dati),
        'ore_erogate_60': sum(d['ore_lavorate_60'] or 0 for d in dati),
        'ore_erogate_100': sum(d['ore_lavorate_100'] or 0 for d in dati),
    }

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        s = get_excel_brand_styles(workbook)

        # ========== FOGLIO 1: RIEPILOGO MUNICIPALE ==========
        ws = workbook.add_worksheet('Riepilogo Municipale')
        ws.hide_gridlines(2)

        N_COLS = 7  # 7 colonne tabella scuole

        # Titolo
        ws.set_row(0, 36)
        ws.merge_range(0, 0, 0, N_COLS - 1,
            f"RIEPILOGO MUNICIPALE", s['title'])

        # Sottotitolo (mese / anno scolastico / commessa)
        sottotitolo = f"{MESI_NOME[mese].upper()} {anno}   ·   A.S. {anno_scolastico}"
        if commessa:
            sottotitolo += f"   ·   Commessa: {commessa}"
        ws.set_row(1, 22)
        ws.merge_range(1, 0, 1, N_COLS - 1, sottotitolo, s['subtitle'])

        # Riga vuota spaziatrice
        ws.set_row(2, 8)

        # Sezione "DETTAGLIO PER SCUOLA"
        ws.set_row(3, 22)
        ws.merge_range(3, 0, 3, N_COLS - 1, '  DETTAGLIO PER ISTITUTO/SCUOLA', s['section'])

        # Headers tabella
        row = 4
        headers = [
            'Istituto Comprensivo / Scuola',
            "Ore erogate (60')",
            'Tariffa',
            "Totale (60')",
            "Ore (100')",
            'Tariffa',
            'Totale €'
        ]
        ws.set_row(row, 32)
        for col, h in enumerate(headers):
            ws.write(row, col, h, s['header'])

        # Freeze panes sotto l'header
        ws.freeze_panes(row + 1, 0)

        # Dati per scuola con righe alternate
        row = 5
        tot_ore_60 = 0
        tot_ore_100 = 0
        tot_importo_60 = 0
        tot_importo_100 = 0

        for idx, t in enumerate(totali_scuola):
            alt = (idx % 2 == 1)
            ore_60 = t['ore_lavorate_60'] or 0
            ore_100 = t['ore_lavorate_100'] or 0
            importo_60 = ore_60 * TARIFFA
            importo_100 = ore_100 * TARIFFA

            cell_f = s['cell_alt'] if alt else s['cell']
            cell_c_f = s['cell_center_alt'] if alt else s['cell_center']
            num_f = s['number_alt'] if alt else s['number']
            money_f = s['money_alt'] if alt else s['money']

            ws.write(row, 0, t['scuola'], cell_f)
            ws.write(row, 1, decimal_to_sessagesimal(ore_60), cell_c_f)
            ws.write(row, 2, TARIFFA, money_f)
            ws.write(row, 3, importo_60, money_f)
            ws.write(row, 4, ore_100, num_f)
            ws.write(row, 5, TARIFFA, money_f)
            ws.write(row, 6, importo_100, money_f)

            tot_ore_60 += ore_60
            tot_ore_100 += ore_100
            tot_importo_60 += importo_60
            tot_importo_100 += importo_100
            row += 1

        # Riga totale
        ws.set_row(row, 24)
        ws.write(row, 0, 'TOTALE', s['total_label'])
        ws.write(row, 1, decimal_to_sessagesimal(tot_ore_60), s['total_cell'])
        ws.write(row, 2, TARIFFA, s['total_money'])
        ws.write(row, 3, tot_importo_60, s['total_money'])
        ws.write(row, 4, tot_ore_100, s['total_number'])
        ws.write(row, 5, TARIFFA, s['total_money'])
        ws.write(row, 6, tot_importo_100, s['total_money'])

        # Calcoli finali — Box di sintesi fatturazione
        imponibile = tot_importo_100
        iva = imponibile * IVA_PERC
        totale_fatturare = imponibile + iva

        row += 2
        ws.set_row(row, 22)
        ws.merge_range(row, 0, row, N_COLS - 1, '  RIEPILOGO FATTURAZIONE', s['section'])
        row += 1
        ws.write(row, 5, 'Imponibile', s['summary_label'])
        ws.write(row, 6, imponibile, s['summary_money'])
        row += 1
        ws.write(row, 5, f"IVA {int(IVA_PERC * 100)}%", s['summary_label'])
        ws.write(row, 6, iva, s['summary_money'])
        row += 1
        ws.set_row(row, 24)
        ws.write(row, 5, 'IMPORTO DA FATTURARE', s['grand_label'])
        ws.write(row, 6, totale_fatturare, s['grand_money'])

        # ========== Sezione Riepilogativo per Lista di Attesa ==========
        row += 3

        # Liste di attesa distinte ordinate cronologicamente
        liste_attesa = get_liste_attesa_ordinate(dati, anno, mese)

        # Suddividi utenti
        utenti_non_lista = [d for d in dati if not d.get('lista_attesa')]
        utenti_in_lista_totali = [d for d in dati if d.get('lista_attesa')]
        utenti_per_lista = {l['valore']: [d for d in dati if (d.get('lista_attesa') or '').strip() == l['valore']]
                            for l in liste_attesa}

        def _conta_con_ore(lst):
            return sum(1 for d in lst if (d['ore_lavorate_60'] or 0) > 0)

        def _somma_ore_100(lst):
            return sum(d['ore_lavorate_100'] or 0 for d in lst)

        n_col_riepilogo = 4 + len(liste_attesa)
        section_end_col = max(n_col_riepilogo - 1, N_COLS - 1)

        ws.set_row(row, 22)
        ws.merge_range(row, 0, row, section_end_col, '  RIEPILOGATIVO PER LISTA DI ATTESA', s['section'])
        row += 1

        # Header
        riepilogo_headers = ['Indicatore', 'Utenti serviti totali', 'Non in lista attesa', 'Di cui in lista di attesa']
        for l in liste_attesa:
            riepilogo_headers.append(l['label'])
        ws.set_row(row, 32)
        for col, h in enumerate(riepilogo_headers):
            ws.write(row, col, h, s['header'])

        # Riga 1: Alunni/ore/importo (numero utenti)
        row += 1
        ws.write(row, 0, 'Alunni assistiti (totale)', s['cell'])
        ws.write(row, 1, totale_generale['num_utenti'], s['integer'])
        ws.write(row, 2, len(utenti_non_lista), s['integer'])
        ws.write(row, 3, len(utenti_in_lista_totali), s['integer'])
        for i, l in enumerate(liste_attesa):
            ws.write(row, 4 + i, len(utenti_per_lista[l['valore']]), s['integer'])

        # Riga 2: Alunni effettivamente assistiti
        row += 1
        ws.write(row, 0, 'Alunni effettivamente assistiti nel mese', s['cell_alt'])
        ws.write(row, 1, _conta_con_ore(dati), s['integer_alt'])
        ws.write(row, 2, _conta_con_ore(utenti_non_lista), s['integer_alt'])
        ws.write(row, 3, _conta_con_ore(utenti_in_lista_totali), s['integer_alt'])
        for i, l in enumerate(liste_attesa):
            ws.write(row, 4 + i, _conta_con_ore(utenti_per_lista[l['valore']]), s['integer_alt'])

        # Riga 3: Ore erogate (100')
        row += 1
        ore_100_non_lista = _somma_ore_100(utenti_non_lista)
        ore_100_in_lista = _somma_ore_100(utenti_in_lista_totali)
        ws.write(row, 0, "Ore effettivamente erogate (al netto dell'11%)", s['cell'])
        ws.write(row, 1, tot_ore_100, s['number'])
        ws.write(row, 2, ore_100_non_lista, s['number'])
        ws.write(row, 3, ore_100_in_lista, s['number'])
        for i, l in enumerate(liste_attesa):
            ws.write(row, 4 + i, _somma_ore_100(utenti_per_lista[l['valore']]), s['number'])

        # Riga 4: Importo (imponibile + IVA)
        row += 1
        importo_non_lista = ore_100_non_lista * TARIFFA
        importo_in_lista = ore_100_in_lista * TARIFFA
        totale_non_lista = importo_non_lista * (1 + IVA_PERC)
        totale_in_lista = importo_in_lista * (1 + IVA_PERC)
        ws.write(row, 0, 'Importo effettivamente erogato (IVA inclusa)', s['cell_alt'])
        ws.write(row, 1, totale_fatturare, s['money_alt'])
        ws.write(row, 2, totale_non_lista, s['money_alt'])
        ws.write(row, 3, totale_in_lista, s['money_alt'])
        for i, l in enumerate(liste_attesa):
            ore_lista = _somma_ore_100(utenti_per_lista[l['valore']])
            tot_lista = ore_lista * TARIFFA * (1 + IVA_PERC)
            ws.write(row, 4 + i, tot_lista, s['money_alt'])

        # Footer informativo
        row += 2
        ws.write(row, 0, f"Documento generato il {datetime.now().strftime('%d/%m/%Y %H:%M')}", s['info'])

        # Larghezze colonne
        ws.set_column('A:A', 52)
        ws.set_column(1, max(N_COLS - 1, n_col_riepilogo - 1), 18)

        # Margini per stampa
        ws.set_margins(left=0.5, right=0.5, top=0.5, bottom=0.5)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)
        ws.repeat_rows(0, 1)

        # ========== FOGLIO 2: DETTAGLIO UTENTI ==========
        ws_utenti = workbook.add_worksheet('Dettaglio Utenti')
        ws_utenti.hide_gridlines(2)

        N_COLS_U = 7

        # Titolo
        ws_utenti.set_row(0, 36)
        ws_utenti.merge_range(0, 0, 0, N_COLS_U - 1, 'DETTAGLIO UTENTI', s['title'])

        # Sottotitolo
        ws_utenti.set_row(1, 22)
        sub_u = f"{MESI_NOME[mese].upper()} {anno}   ·   A.S. {anno_scolastico}"
        if commessa:
            sub_u += f"   ·   Commessa: {commessa}"
        ws_utenti.merge_range(1, 0, 1, N_COLS_U - 1, sub_u, s['subtitle'])

        ws_utenti.set_row(2, 8)

        # Headers tabella utenti
        utenti_headers = ['Scuola', 'Utente', 'Monte Ore', "Ore Erogate (60')", "Ore (100')", 'Totale €', 'Lista Attesa']
        row_u = 3
        ws_utenti.set_row(row_u, 32)
        for col, h in enumerate(utenti_headers):
            ws_utenti.write(row_u, col, h, s['header'])

        ws_utenti.freeze_panes(row_u + 1, 0)

        # Dati utenti con righe alternate
        row_u = 4
        for idx, d in enumerate(dati):
            alt = (idx % 2 == 1)
            cell_f = s['cell_alt'] if alt else s['cell']
            cell_c_f = s['cell_center_alt'] if alt else s['cell_center']
            num_f = s['number_alt'] if alt else s['number']
            money_f = s['money_alt'] if alt else s['money']

            ws_utenti.write(row_u, 0, d['scuola'], cell_f)
            ws_utenti.write(row_u, 1, f"{d['nome']} {d['cognome']}", cell_f)
            ws_utenti.write(row_u, 2, d['monte_ore_settimanale'], num_f)
            ws_utenti.write(row_u, 3, decimal_to_sessagesimal(d['ore_lavorate_60'] or 0), cell_c_f)
            ws_utenti.write(row_u, 4, d['ore_lavorate_100'] or 0, num_f)
            ws_utenti.write(row_u, 5, d['totale_100'] or 0, money_f)
            ws_utenti.write(row_u, 6, d.get('lista_attesa') or '—', cell_c_f)
            row_u += 1

        # Footer informativo
        row_u += 1
        ws_utenti.write(row_u, 0, f"Documento generato il {datetime.now().strftime('%d/%m/%Y %H:%M')}", s['info'])

        # Larghezza colonne foglio utenti
        ws_utenti.set_column('A:A', 50)
        ws_utenti.set_column('B:B', 26)
        ws_utenti.set_column('C:C', 12)
        ws_utenti.set_column('D:F', 16)
        ws_utenti.set_column('G:G', 14)

        # Margini per stampa
        ws_utenti.set_margins(left=0.5, right=0.5, top=0.5, bottom=0.5)
        ws_utenti.set_landscape()
        ws_utenti.fit_to_pages(1, 0)
        ws_utenti.repeat_rows(0, 3)

    output.seek(0)

    filename = f"Riepilogo_Municipale_{MESI_NOME[mese]}_{anno}"
    if commessa:
        filename += f"_{commessa.replace(' ', '_')}"
    filename += ".xlsx"

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


@app.route('/api/export/dipartimentale/<int:anno>/<int:mese>')
def api_export_dipartimentale(anno, mese):
    """Esporta Monitoraggio Dipartimentale - Report per livello scolastico"""
    commessa = request.args.get('commessa')

    dati = db.get_rendicontazione_completa(anno, mese, commessa)

    # Costanti (stesse del riepilogo municipale per coerenza)
    TARIFFA = config.TARIFFA_ORARIA
    IVA_PERC = config.IVA_PERCENTUALE

    # Determina anno scolastico
    if mese >= 9:
        anno_scolastico = f"{anno}/{anno+1}"
    else:
        anno_scolastico = f"{anno-1}/{anno}"

    # Raggruppa per livello scolastico
    livelli = {}
    for d in dati:
        livello, ordine = classifica_livello_scolastico(d['scuola'])

        if livello not in livelli:
            livelli[livello] = {
                'ordine': ordine,
                'n_utenti': 0,
                'ore_richieste': 0,  # media -11%
                'ore_erogate': 0,    # ore lavorate 100'
                'importo_impegnato': 0,  # media -11% × tariffa con IVA
                'importo_liquidato': 0   # ore erogate × tariffa con IVA
            }

        ore_richieste = d['media_con_assenza_60'] or 0
        ore_erogate = d['ore_lavorate_100'] or 0

        livelli[livello]['n_utenti'] += 1
        livelli[livello]['ore_richieste'] += ore_richieste
        livelli[livello]['ore_erogate'] += ore_erogate
        livelli[livello]['importo_impegnato'] += ore_richieste * TARIFFA * (1 + IVA_PERC)
        livelli[livello]['importo_liquidato'] += ore_erogate * TARIFFA * (1 + IVA_PERC)

    # Ordina per ordine predefinito
    livelli_ordinati = sorted(livelli.items(), key=lambda x: x[1]['ordine'])

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        s = get_excel_brand_styles(workbook)

        # Foglio
        ws = workbook.add_worksheet('Monitoraggio Dipartimentale')
        ws.hide_gridlines(2)

        N_COLS = 6

        # Titolo
        ws.set_row(0, 36)
        ws.merge_range(0, 0, 0, N_COLS - 1, 'MONITORAGGIO DIPARTIMENTALE', s['title'])

        # Sottotitolo
        sub = f"{MESI_NOME[mese].upper()} {anno}   ·   A.S. {anno_scolastico}"
        if commessa:
            sub += f"   ·   Commessa: {commessa}"
        ws.set_row(1, 22)
        ws.merge_range(1, 0, 1, N_COLS - 1, sub, s['subtitle'])

        # Spazio
        ws.set_row(2, 8)

        # Sezione
        ws.set_row(3, 22)
        ws.merge_range(3, 0, 3, N_COLS - 1, '  RIEPILOGO PER LIVELLO SCOLASTICO', s['section'])

        # ========== TABELLA DATI ==========
        # Headers
        row = 4
        headers = [
            'Livello Scolastico',
            'N. Utenti',
            'Ore richieste',
            'Ore Erogate',
            'Importo Impegnato',
            'Importo Liquidato'
        ]

        ws.set_row(row, 36)
        for col, h in enumerate(headers):
            ws.write(row, col, h, s['header'])

        ws.freeze_panes(row + 1, 0)

        # Dati per livello (righe alternate)
        row = 5
        tot_utenti = 0
        tot_ore_richieste = 0
        tot_ore_erogate = 0
        tot_impegnato = 0
        tot_liquidato = 0

        for idx, (livello, stats) in enumerate(livelli_ordinati):
            alt = (idx % 2 == 1)
            cell_f = s['cell_alt'] if alt else s['cell']
            num_f = s['number_alt'] if alt else s['number']
            int_f = s['integer_alt'] if alt else s['integer']
            money_f = s['money_alt'] if alt else s['money']

            ws.write(row, 0, livello, cell_f)
            ws.write(row, 1, stats['n_utenti'], int_f)
            ws.write(row, 2, stats['ore_richieste'], num_f)
            ws.write(row, 3, stats['ore_erogate'], num_f)
            ws.write(row, 4, stats['importo_impegnato'], money_f)
            ws.write(row, 5, stats['importo_liquidato'], money_f)

            tot_utenti += stats['n_utenti']
            tot_ore_richieste += stats['ore_richieste']
            tot_ore_erogate += stats['ore_erogate']
            tot_impegnato += stats['importo_impegnato']
            tot_liquidato += stats['importo_liquidato']

            row += 1

        # Riga TOTALE
        ws.set_row(row, 26)
        ws.write(row, 0, 'TOTALE', s['total_label'])
        ws.write(row, 1, tot_utenti, s['total_integer'])
        ws.write(row, 2, tot_ore_richieste, s['total_number'])
        ws.write(row, 3, tot_ore_erogate, s['total_number'])
        ws.write(row, 4, tot_impegnato, s['total_money'])
        ws.write(row, 5, tot_liquidato, s['total_money'])

        # Footer informativo
        row += 2
        ws.write(row, 0, f"Documento generato il {datetime.now().strftime('%d/%m/%Y %H:%M')}", s['info'])

        # Larghezza colonne
        ws.set_column('A:A', 30)
        ws.set_column('B:B', 12)
        ws.set_column('C:D', 16)
        ws.set_column('E:F', 20)

        # Stampa
        ws.set_margins(left=0.5, right=0.5, top=0.5, bottom=0.5)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)
        ws.repeat_rows(0, 1)

    output.seek(0)

    filename = f"Monitoraggio_Dipartimentale_{MESI_NOME[mese]}_{anno}"
    if commessa:
        filename += f"_{commessa.replace(' ', '_')}"
    filename += ".xlsx"

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


# ==================== STATISTICHE ====================

@app.route('/api/export/word/<int:anno>/<int:mese>')
def api_export_word(anno, mese):
    """Genera un documento Word con relazione sull'andamento del servizio mensile"""
    commessa = request.args.get('commessa')

    dati = db.get_rendicontazione_completa(anno, mese, commessa)
    totali_scuola = db.get_totali_per_scuola(anno, mese, commessa)

    # Costanti
    TARIFFA = config.TARIFFA_ORARIA
    IVA_PERC = config.IVA_PERCENTUALE

    # Calcola totali
    ore_totali_60 = sum(d['ore_lavorate_60'] or 0 for d in dati)
    ore_totali_100 = sum(d['ore_lavorate_100'] or 0 for d in dati)
    ore_previste = sum(d['media_con_assenza_60'] or 0 for d in dati)
    pasti_totali = sum(d['pasti'] or 0 for d in dati)
    credito_debito = sum(d['credito_debito'] or 0 for d in dati)

    # Calcolo fatturazione
    imponibile_totale = round(ore_totali_100 * TARIFFA, 2)
    iva_totale = round(imponibile_totale * IVA_PERC, 2)
    totale_lordo = round(imponibile_totale + iva_totale, 2)

    # Percentuale completamento
    perc_completamento = (ore_totali_60 / ore_previste * 100) if ore_previste > 0 else 0

    # Utenti con ore e in lista attesa
    utenti_con_ore = sum(1 for d in dati if (d['ore_lavorate_60'] or 0) > 0)
    utenti_lista_attesa = sum(1 for d in dati if d.get('lista_attesa'))

    # Determina anno scolastico
    if mese >= 9:
        anno_scolastico = f"{anno}/{anno+1}"
    else:
        anno_scolastico = f"{anno-1}/{anno}"

    # Crea documento Word
    doc = Document()

    # Stile di default del documento
    style_normal = doc.styles['Normal']
    style_normal.font.name = 'Calibri'
    style_normal.font.size = Pt(11)

    # Imposta margini
    sections = doc.sections
    for section in sections:
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.5)

    # Footer con numero pagina
    add_word_page_number_footer(doc)

    # ========== INTESTAZIONE BRANDED ==========
    # Barra colorata superiore (titolo con sfondo indigo)
    title_table = doc.add_table(rows=1, cols=1)
    title_cell = title_table.rows[0].cells[0]
    _style_word_cell_bg(title_cell, '4F46E5')
    title_p = title_cell.paragraphs[0]
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_p.add_run('RELAZIONE SUL SERVIZIO OEPAC')
    title_run.bold = True
    title_run.font.size = Pt(22)
    title_run.font.color.rgb = RGBColor.from_string('FFFFFF')
    title_run.font.name = 'Calibri'

    # Sottotitolo con sfondo dark
    sub_table = doc.add_table(rows=1, cols=1)
    sub_cell = sub_table.rows[0].cells[0]
    _style_word_cell_bg(sub_cell, '1E293B')
    sub_p = sub_cell.paragraphs[0]
    sub_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_run = sub_p.add_run(f'{MESI_NOME[mese].upper()} {anno}   ·   A.S. {anno_scolastico}')
    sub_run.bold = True
    sub_run.font.size = Pt(13)
    sub_run.font.color.rgb = RGBColor.from_string('FFFFFF')
    sub_run.font.name = 'Calibri'

    if commessa:
        comm_para = doc.add_paragraph()
        comm_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = comm_para.add_run(f'Commessa: {commessa}')
        run.font.size = Pt(11)
        run.italic = True
        run.font.color.rgb = RGBColor.from_string('64748B')

    # Data di emissione
    data_em = doc.add_paragraph()
    data_em.alignment = WD_ALIGN_PARAGRAPH.CENTER
    de_run = data_em.add_run(f"Emesso il {datetime.now().strftime('%d/%m/%Y')}")
    de_run.font.size = Pt(10)
    de_run.italic = True
    de_run.font.color.rgb = RGBColor.from_string('64748B')

    doc.add_paragraph()

    # Sezione 1: Panoramica Generale
    h1 = doc.add_heading('1. PANORAMICA GENERALE', level=1)
    for run in h1.runs:
        run.font.color.rgb = RGBColor.from_string('4F46E5')

    intro = doc.add_paragraph()
    intro.add_run(f"Nel mese di {MESI_NOME[mese]} {anno}, relativo all'anno scolastico {anno_scolastico}, "
                  f"il servizio OEPAC ha assistito un totale di ").bold = False
    intro.add_run(f"{len(dati)} utenti").bold = True
    intro.add_run(f" distribuiti su ")
    intro.add_run(f"{len(totali_scuola)} scuole").bold = True
    intro.add_run(".")

    if utenti_lista_attesa > 0:
        lista_para = doc.add_paragraph()
        lista_para.add_run(f"Di questi, {utenti_lista_attesa} utenti risultano in lista di attesa.").italic = True

    # Sezione 2: Dati Quantitativi
    h2 = doc.add_heading('2. DATI QUANTITATIVI', level=1)
    for run in h2.runs:
        run.font.color.rgb = RGBColor.from_string('4F46E5')

    # Tabella KPI
    table_kpi = doc.add_table(rows=1, cols=2)
    table_kpi.style = 'Table Grid'
    table_kpi.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr_cells = table_kpi.rows[0].cells
    hdr_cells[0].text = 'Indicatore'
    hdr_cells[1].text = 'Valore'

    kpi_data = [
        ('Utenti totali assistiti', str(len(dati))),
        ('Utenti effettivamente serviti nel mese', str(utenti_con_ore)),
        ('Utenti in lista di attesa', str(utenti_lista_attesa)),
        ('Ore previste (Media -11%)', f'{ore_previste:.2f}'),
        ('Ore effettivamente erogate', f'{ore_totali_60:.2f}'),
        ('Percentuale completamento', f'{perc_completamento:.1f}%'),
        ('Pasti erogati', str(pasti_totali)),
        ('Credito/Debito ore', f'{credito_debito:+.2f}'),
    ]

    for label, value in kpi_data:
        row_cells = table_kpi.add_row().cells
        row_cells[0].text = label
        row_cells[1].text = value

    style_word_table_header(table_kpi)
    style_word_table_alternating_rows(table_kpi)

    doc.add_paragraph()

    # Sezione 3: Dati Economici
    h3 = doc.add_heading('3. DATI ECONOMICI', level=1)
    for run in h3.runs:
        run.font.color.rgb = RGBColor.from_string('4F46E5')

    econ_para = doc.add_paragraph()
    econ_para.add_run(f"Sulla base delle ore erogate nel mese di {MESI_NOME[mese]}, "
                      f"applicando la tariffa oraria di € {TARIFFA:.2f} (esclusa IVA), "
                      f"si riportano i seguenti dati economici:")

    table_econ = doc.add_table(rows=1, cols=2)
    table_econ.style = 'Table Grid'
    table_econ.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr_cells = table_econ.rows[0].cells
    hdr_cells[0].text = 'Voce'
    hdr_cells[1].text = 'Importo'

    econ_data = [
        ('Ore erogate (centesimali)', f'{ore_totali_100:.2f}'),
        ('Imponibile', f'€ {imponibile_totale:,.2f}'),
        (f'IVA {int(IVA_PERC * 100)}%', f'€ {iva_totale:,.2f}'),
        ('TOTALE DA FATTURARE', f'€ {totale_lordo:,.2f}'),
    ]

    for label, value in econ_data:
        row_cells = table_econ.add_row().cells
        row_cells[0].text = label
        row_cells[1].text = value

    style_word_table_header(table_econ)
    style_word_table_alternating_rows(table_econ)
    style_word_table_total_row(table_econ, bg_color='4F46E5')

    doc.add_paragraph()

    # Sezione 4: Riepilogativo per Lista di Attesa
    h4 = doc.add_heading('4. RIEPILOGATIVO PER LISTA DI ATTESA', level=1)
    for run in h4.runs:
        run.font.color.rgb = RGBColor.from_string('4F46E5')

    liste_attesa = get_liste_attesa_ordinate(dati, anno, mese)
    utenti_non_lista_rel = [d for d in dati if not d.get('lista_attesa')]
    utenti_in_lista_rel = [d for d in dati if d.get('lista_attesa')]
    utenti_per_lista_rel = {l['valore']: [d for d in dati if (d.get('lista_attesa') or '').strip() == l['valore']]
                            for l in liste_attesa}

    def _conta_con_ore_rel(lst):
        return sum(1 for d in lst if (d['ore_lavorate_60'] or 0) > 0)

    def _somma_ore_100_rel(lst):
        return sum(d['ore_lavorate_100'] or 0 for d in lst)

    # Tabella riepilogativo: 4 righe x (4 + N liste) colonne
    n_cols_riep = 4 + len(liste_attesa)
    table_riep = doc.add_table(rows=1, cols=n_cols_riep)
    table_riep.style = 'Table Grid'
    table_riep.alignment = WD_TABLE_ALIGNMENT.CENTER

    # Header
    hdr = table_riep.rows[0].cells
    hdr[0].text = 'Indicatore'
    hdr[1].text = 'Utenti serviti totali'
    hdr[2].text = 'Non in lista attesa'
    hdr[3].text = 'Di cui in lista di attesa'
    for i, l in enumerate(liste_attesa):
        hdr[4 + i].text = l['label']

    # Riga 1: Alunni
    r1 = table_riep.add_row().cells
    r1[0].text = 'Alunni assistiti (totale)'
    r1[1].text = str(len(dati))
    r1[2].text = str(len(utenti_non_lista_rel))
    r1[3].text = str(len(utenti_in_lista_rel))
    for i, l in enumerate(liste_attesa):
        r1[4 + i].text = str(len(utenti_per_lista_rel[l['valore']]))

    # Riga 2: Alunni assistiti
    r2 = table_riep.add_row().cells
    r2[0].text = 'Alunni effettivamente assistiti nel mese'
    r2[1].text = str(_conta_con_ore_rel(dati))
    r2[2].text = str(_conta_con_ore_rel(utenti_non_lista_rel))
    r2[3].text = str(_conta_con_ore_rel(utenti_in_lista_rel))
    for i, l in enumerate(liste_attesa):
        r2[4 + i].text = str(_conta_con_ore_rel(utenti_per_lista_rel[l['valore']]))

    # Riga 3: Ore erogate (100')
    ore_100_non_lista_rel = _somma_ore_100_rel(utenti_non_lista_rel)
    ore_100_in_lista_rel = _somma_ore_100_rel(utenti_in_lista_rel)
    r3 = table_riep.add_row().cells
    r3[0].text = "Ore effettivamente erogate (al netto dell'11%)"
    r3[1].text = f'{ore_totali_100:.2f}'
    r3[2].text = f'{ore_100_non_lista_rel:.2f}'
    r3[3].text = f'{ore_100_in_lista_rel:.2f}'
    for i, l in enumerate(liste_attesa):
        r3[4 + i].text = f'{_somma_ore_100_rel(utenti_per_lista_rel[l["valore"]]):.2f}'

    # Riga 4: Importo (imponibile + IVA)
    importo_non_lista_rel = ore_100_non_lista_rel * TARIFFA * (1 + IVA_PERC)
    importo_in_lista_rel = ore_100_in_lista_rel * TARIFFA * (1 + IVA_PERC)
    r4 = table_riep.add_row().cells
    r4[0].text = 'Importo erogato (IVA inclusa)'
    r4[1].text = f'€ {totale_lordo:,.2f}'
    r4[2].text = f'€ {importo_non_lista_rel:,.2f}'
    r4[3].text = f'€ {importo_in_lista_rel:,.2f}'
    for i, l in enumerate(liste_attesa):
        ore_l = _somma_ore_100_rel(utenti_per_lista_rel[l['valore']])
        imp_l = ore_l * TARIFFA * (1 + IVA_PERC)
        r4[4 + i].text = f'€ {imp_l:,.2f}'

    style_word_table_header(table_riep)
    style_word_table_alternating_rows(table_riep)

    doc.add_paragraph()

    # Sezione 5: Distribuzione per Scuola
    h5 = doc.add_heading('5. DISTRIBUZIONE PER SCUOLA', level=1)
    for run in h5.runs:
        run.font.color.rgb = RGBColor.from_string('4F46E5')

    if totali_scuola:
        distr_para = doc.add_paragraph()
        distr_para.add_run("Di seguito il riepilogo delle ore erogate suddivise per scuola:")

        table_scuole = doc.add_table(rows=1, cols=5)
        table_scuole.style = 'Table Grid'
        table_scuole.alignment = WD_TABLE_ALIGNMENT.CENTER
        hdr_cells = table_scuole.rows[0].cells
        headers = ['Scuola', 'Utenti', 'Ore Erogate', 'Imponibile', 'Totale']
        for i, h in enumerate(headers):
            hdr_cells[i].text = h

        # Totalizzatori per la riga TOTALE
        tot_utenti_s = 0
        tot_ore_s = 0.0
        tot_imp_s = 0.0
        tot_tot_s = 0.0

        for t in totali_scuola:
            row_cells = table_scuole.add_row().cells
            nome_scuola = t['scuola'][:50] + '...' if len(t['scuola']) > 50 else t['scuola']
            row_cells[0].text = nome_scuola
            row_cells[1].text = str(t['num_utenti'])
            row_cells[2].text = f"{t['ore_lavorate_60']:.2f}"
            row_cells[3].text = f"€ {t['imponibile_100']:,.2f}"
            row_cells[4].text = f"€ {t['totale_100']:,.2f}"

            tot_utenti_s += t['num_utenti'] or 0
            tot_ore_s += t['ore_lavorate_60'] or 0
            tot_imp_s += t['imponibile_100'] or 0
            tot_tot_s += t['totale_100'] or 0

        # Riga TOTALE
        tot_cells = table_scuole.add_row().cells
        tot_cells[0].text = 'TOTALE'
        tot_cells[1].text = str(tot_utenti_s)
        tot_cells[2].text = f"{tot_ore_s:.2f}"
        tot_cells[3].text = f"€ {tot_imp_s:,.2f}"
        tot_cells[4].text = f"€ {tot_tot_s:,.2f}"

        style_word_table_header(table_scuole)
        style_word_table_alternating_rows(table_scuole)
        style_word_table_total_row(table_scuole)

    doc.add_paragraph()

    # Sezione 6: Analisi e Osservazioni
    h6 = doc.add_heading('6. ANALISI E OSSERVAZIONI', level=1)
    for run in h6.runs:
        run.font.color.rgb = RGBColor.from_string('4F46E5')

    # Analisi automatica basata sui dati
    if perc_completamento >= 95:
        analisi = f"Il servizio ha raggiunto un ottimo livello di completamento ({perc_completamento:.1f}%), " \
                  f"superando il 95% delle ore previste."
    elif perc_completamento >= 80:
        analisi = f"Il servizio ha raggiunto un buon livello di completamento ({perc_completamento:.1f}%), " \
                  f"erogando oltre l'80% delle ore previste."
    elif perc_completamento >= 60:
        analisi = f"Il servizio ha raggiunto un livello di completamento nella media ({perc_completamento:.1f}%). " \
                  f"Si suggerisce di verificare eventuali criticità."
    else:
        analisi = f"Il livello di completamento ({perc_completamento:.1f}%) risulta inferiore alle aspettative. " \
                  f"Si raccomanda un'analisi approfondita delle cause."

    doc.add_paragraph(analisi)

    if credito_debito > 0:
        cred_para = doc.add_paragraph()
        cred_para.add_run(f"Il saldo credito/debito ore è positivo (+{credito_debito:.2f} ore), "
                         f"indicando ore non ancora erogate rispetto alle previste.")
    elif credito_debito < 0:
        cred_para = doc.add_paragraph()
        cred_para.add_run(f"Il saldo credito/debito ore è negativo ({credito_debito:.2f} ore), "
                         f"indicando ore erogate in eccesso rispetto alle previste.")

    # Sottosezione: Utenti con tasso di erogazione < 50%
    utenti_bassa_erogazione = []
    for d in dati:
        ore_erogate = d['ore_lavorate_60'] or 0
        ore_previste = d['media_con_assenza_60'] or 0
        if ore_previste > 0:
            tasso = (ore_erogate / ore_previste) * 100
            if tasso < 50:
                utenti_bassa_erogazione.append({
                    'nome': f"{d['nome']} {d['cognome']}",
                    'scuola': d['scuola'],
                    'ore_previste': ore_previste,
                    'ore_erogate': ore_erogate,
                    'tasso': tasso
                })

    if utenti_bassa_erogazione:
        doc.add_paragraph()
        h61 = doc.add_heading('6.1 Utenti con tasso di erogazione inferiore al 50%', level=2)
        for run in h61.runs:
            run.font.color.rgb = RGBColor.from_string('EF4444')

        alert_para = doc.add_paragraph()
        alert_para.add_run(f"Si segnalano {len(utenti_bassa_erogazione)} utenti con un tasso di erogazione "
                          f"inferiore al 50% rispetto alle ore previste:")

        table_alert = doc.add_table(rows=1, cols=5)
        table_alert.style = 'Table Grid'
        table_alert.alignment = WD_TABLE_ALIGNMENT.CENTER
        hdr_cells = table_alert.rows[0].cells
        headers_alert = ['Utente', 'Scuola', 'Ore Previste', 'Ore Erogate', 'Tasso']
        for i, h in enumerate(headers_alert):
            hdr_cells[i].text = h

        # Ordina per tasso crescente (i più critici prima)
        utenti_bassa_erogazione.sort(key=lambda x: x['tasso'])

        for u in utenti_bassa_erogazione:
            row_cells = table_alert.add_row().cells
            row_cells[0].text = u['nome']
            nome_scuola = u['scuola'][:40] + '...' if len(u['scuola']) > 40 else u['scuola']
            row_cells[1].text = nome_scuola
            row_cells[2].text = f"{u['ore_previste']:.2f}"
            row_cells[3].text = f"{u['ore_erogate']:.2f}"
            row_cells[4].text = f"{u['tasso']:.1f}%"

        style_word_table_header(table_alert, bg_color='EF4444')
        style_word_table_alternating_rows(table_alert, color_alt='FEE2E2')

    doc.add_paragraph()

    # Sezione 7: Conclusioni
    h7 = doc.add_heading('7. CONCLUSIONI', level=1)
    for run in h7.runs:
        run.font.color.rgb = RGBColor.from_string('4F46E5')

    concl = doc.add_paragraph()
    concl.add_run(f"In sintesi, nel mese di {MESI_NOME[mese]} {anno} il servizio OEPAC ha erogato "
                  f"complessivamente {ore_totali_60:.2f} ore di assistenza a {utenti_con_ore} utenti, "
                  f"per un importo totale da fatturare pari a € {totale_lordo:,.2f}.")

    # Data e firma
    doc.add_paragraph()
    doc.add_paragraph()

    data_para = doc.add_paragraph()
    data_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    dr = data_para.add_run(f"Data: {datetime.now().strftime('%d/%m/%Y')}")
    dr.bold = True

    doc.add_paragraph()

    firma_para = doc.add_paragraph()
    firma_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    fr = firma_para.add_run("Il Responsabile del Servizio")
    fr.bold = True

    firma_line = doc.add_paragraph()
    firma_line.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    firma_line.add_run("_________________________")

    # Salva in buffer
    output = io.BytesIO()
    doc.save(output)
    output.seek(0)

    filename = f"Relazione_OEPAC_{MESI_NOME[mese]}_{anno}"
    if commessa:
        filename += f"_{commessa.replace(' ', '_')}"
    filename += ".docx"

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        as_attachment=True,
        download_name=filename
    )


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


# ==================== REPORT SCHEDULATI ====================

@app.route('/api/export/scheduled', methods=['POST'])
def api_scheduled_export():
    """Genera report per un range di mesi in un'unica richiesta"""
    data = request.json or {}
    anno_scolastico = data.get('anno_scolastico')
    mesi = data.get('mesi', [])  # lista di {mese, anno}
    tipo = data.get('tipo', 'excel')  # excel, municipale, dipartimentale
    commessa = data.get('commessa')

    if not anno_scolastico:
        return jsonify({'error': 'Anno scolastico richiesto'}), 400

    if not mesi:
        # Genera per tutti i mesi dell'anno scolastico
        anni = anno_scolastico.split('-')
        anno_inizio = int(anni[0])
        anno_fine = int(anni[1])
        mesi = [{'mese': m, 'anno': anno_inizio if m >= 9 else anno_fine} for m in MESI_SCOLASTICI]

    report_generati = []
    for periodo in mesi:
        m = periodo['mese']
        a = periodo['anno']
        dati = db.get_rendicontazione_completa(a, m, commessa)
        ore = sum(d['ore_lavorate_60'] or 0 for d in dati)
        if ore > 0:
            report_generati.append({
                'mese': m,
                'anno': a,
                'mese_nome': MESI_NOME.get(m, ''),
                'utenti': len(dati),
                'ore': round(ore, 2)
            })

    db.log_audit('export_schedulato', 'report', dettagli=f'{len(report_generati)} report generati')

    return jsonify({
        'success': True,
        'report': report_generati,
        'totale_report': len(report_generati)
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

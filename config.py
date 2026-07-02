"""
Configurazione centralizzata - Gestionale OEPAC
"""

import os
import logging

# ==================== PERCORSI ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, 'gestionale.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
EXPORT_FOLDER = os.path.join(BASE_DIR, 'exports')
BACKUP_FOLDER = os.path.join(BASE_DIR, 'backups')
LOG_FOLDER = os.path.join(BASE_DIR, 'logs')

# ==================== COSTANTI ECONOMICHE ====================
TARIFFA_ORARIA = 24.07
TASSO_ASSENZA = 0.11
IVA_PERCENTUALE = 0.05
COEFFICIENTE_GIORNALIERO = 0.2


def anno_scolastico_di(anno: int, mese: int, sep: str = '-') -> str:
    """Anno scolastico (Set-Giu) a cui appartiene un (anno, mese).

    Regola UNICA per tutta l'app: mese >= 9 -> 'anno{sep}anno+1', altrimenti
    'anno-1{sep}anno'. sep='-' e' il formato chiave del DB, sep='/' quello
    di visualizzazione nei report."""
    if mese >= 9:
        return f"{anno}{sep}{anno + 1}"
    return f"{anno - 1}{sep}{anno}"


def calcola_fatturazione(ore) -> tuple:
    """Calcolo di fatturazione unico (imponibile, IVA, totale) dalle ore in 100'.

    E' l'unica fonte di verita' per imponibile/IVA/totale: si arrotonda UNA sola
    volta sull'aggregato invece di sommare valori gia' arrotondati, cosi' anteprima
    a schermo, statistiche ed export producono gli stessi numeri (niente divergenze
    di centesimi). Non hardcodare mai la tariffa o il moltiplicatore IVA altrove.

    Ritorna: (imponibile, iva, totale) arrotondati a 2 decimali.
    """
    ore = ore or 0
    imponibile = round(ore * TARIFFA_ORARIA, 2)
    iva = round(imponibile * IVA_PERCENTUALE, 2)
    totale = round(imponibile + iva, 2)
    return imponibile, iva, totale

# ==================== PARAMETRI CALCOLO / REPORT ====================
# Giorni lavorativi di fallback se il calendario non ha dati per il mese
GIORNI_LAVORATIVI_DEFAULT = 22
# Numero di mesi mostrati di default nello storico utente
STORICO_MESI_DEFAULT = 6
# Soglia percentuale per segnalare differenze anomale ore erogate vs previste
SOGLIA_ANOMALIA_PERCENTUALE = 50

# ==================== LIMITI UPLOAD ====================
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB

# ==================== VALIDAZIONE ====================
MAX_NOME_LENGTH = 100
MAX_COGNOME_LENGTH = 100
MAX_SCUOLA_LENGTH = 200
MAX_COMMESSA_LENGTH = 100
MAX_DESCRIZIONE_LENGTH = 500
MAX_NOTE_LENGTH = 1000
MAX_ORE_SETTIMANALI = 40.0
MAX_ORE_MENSILI = 200.0
MAX_PASTI_MENSILI = 31
MIN_GIORNI_LAVORATIVI = 0
MAX_GIORNI_LAVORATIVI = 23

# ==================== BACKUP ====================
MAX_BACKUPS = 30  # Numero massimo di backup da conservare
BACKUP_ON_STARTUP = True

# ==================== MESI ====================
MESI_NOME = {
    1: 'Gennaio', 2: 'Febbraio', 3: 'Marzo', 4: 'Aprile',
    5: 'Maggio', 6: 'Giugno', 7: 'Luglio', 8: 'Agosto',
    9: 'Settembre', 10: 'Ottobre', 11: 'Novembre', 12: 'Dicembre'
}

MESI_SCOLASTICI = [9, 10, 11, 12, 1, 2, 3, 4, 5, 6]

# ==================== COLORI BRAND (per export) ====================
PRIMARY_COLOR = '#6366F1'
PRIMARY_DARK = '#4F46E5'
SUCCESS_COLOR = '#10B981'
DANGER_COLOR = '#EF4444'
WARNING_COLOR = '#F59E0B'
DARK_COLOR = '#1E293B'
LIGHT_COLOR = '#F8FAFC'

# ==================== LOGGING ====================
def setup_logging():
    """Configura il sistema di logging"""
    os.makedirs(LOG_FOLDER, exist_ok=True)

    logger = logging.getLogger('oepac')
    logger.setLevel(logging.INFO)

    # Evita duplicati
    if logger.handlers:
        return logger

    # File handler con rotazione: evita che oepac.log cresca all'infinito
    # (5 file da ~1MB = max ~5MB conservati).
    from logging.handlers import RotatingFileHandler
    file_handler = RotatingFileHandler(
        os.path.join(LOG_FOLDER, 'oepac.log'),
        maxBytes=1_000_000,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_fmt = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_fmt)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_fmt = logging.Formatter('[%(levelname)s] %(message)s')
    console_handler.setFormatter(console_fmt)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

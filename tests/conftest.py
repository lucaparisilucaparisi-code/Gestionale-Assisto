"""Configurazione pytest per il Gestionale OEPAC.

Reindirizza il database su un file temporaneo PRIMA di importare app/database,
così i test non toccano mai `gestionale.db` reale e non creano backup.
"""
import os
import sys
import tempfile
import importlib

import pytest

# Rendi importabili i moduli del progetto (cartella padre di tests/)
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)


@pytest.fixture(scope='session')
def app_module():
    """Importa app/database con un DB temporaneo isolato e auth configurata.

    Scope 'session': il DB temporaneo viene creato una sola volta per l'intera
    sessione di test e rimosso alla fine.
    """
    import config

    tmp_dir = tempfile.mkdtemp(prefix='oepac_test_')
    tmp_db = os.path.join(tmp_dir, 'test_gestionale.db')

    # Reindirizza percorsi e disabilita il backup all'avvio
    config.DATABASE_PATH = tmp_db
    config.BACKUP_ON_STARTUP = False
    config.BACKUP_FOLDER = os.path.join(tmp_dir, 'backups')
    os.makedirs(config.BACKUP_FOLDER, exist_ok=True)

    # Importa database e allinea il suo path globale (letto a import-time)
    import database as db
    db.DATABASE_PATH = tmp_db
    db.init_db()

    # Importa l'app Flask (init_db gira di nuovo ma è idempotente)
    import app as app_mod

    # Configura un utente di autenticazione per i test
    from werkzeug.security import generate_password_hash
    if not db.auth_is_configured():
        db.auth_create_user('tester', generate_password_hash('secret'))

    yield app_mod

    # Pulizia
    try:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass


@pytest.fixture
def db_mod(app_module):
    """Modulo database già inizializzato sul DB di test."""
    import database as db
    return db


@pytest.fixture
def client(app_module):
    """Test client Flask già autenticato."""
    flask_app = app_module.app
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as c:
        with c.session_transaction() as sess:
            sess['authenticated'] = True
            sess['auth_method'] = 'test'
        yield c


@pytest.fixture
def sample_data(db_mod):
    """Crea una commessa, una scuola e un utente di prova; ritorna gli id.

    Pulisce le variazioni monte ore dell'utente al termine di ogni test.
    """
    db = db_mod
    commessa_id = db.create_commessa('TEST COMMESSA', 'Commessa di test')
    scuola_id = db.get_or_create_scuola('TEST COMMESSA', 'IC Test - Scuola Primaria Test')
    utente_id = db.get_or_create_utente(scuola_id, 'Test', 'Utente', 15)

    yield {
        'commessa_id': commessa_id,
        'scuola_id': scuola_id,
        'utente_id': utente_id,
    }

    # Cleanup variazioni create durante il test
    for v in db.get_variazioni_monte_ore(utente_id):
        db.delete_variazione_monte_ore(v['id'])

"""Test di sicurezza: validazione input su operazioni sensibili.

Copre in particolare la difesa da path traversal in restore_backup, che
ripristina un file come database applicativo.
"""
import os


def test_restore_backup_rifiuta_path_traversal(db_mod, tmp_path):
    """Nomi con percorso/'..'/assoluti non devono poter caricare file arbitrari."""
    db = db_mod
    import config

    # File "malevolo" fuori dalla cartella dei backup
    evil = tmp_path / 'evil.db'
    evil.write_bytes(b'EVIL')

    original = open(db.DATABASE_PATH, 'rb').read()

    rel = os.path.relpath(str(evil), config.BACKUP_FOLDER)  # contiene '..'
    for nome in [rel, str(evil), '../evil.db', 'sub/evil.db', '..', '']:
        assert db.restore_backup(nome) is False, f"accettato nome non valido: {nome!r}"

    # Il database non deve essere stato sovrascritto
    assert open(db.DATABASE_PATH, 'rb').read() == original


def test_restore_backup_rifiuta_nome_inesistente(db_mod):
    """Un nome dall'aspetto legittimo ma non presente in cartella va respinto."""
    assert db_mod.restore_backup('gestionale_backup_99999999_000000.db') is False


def test_restore_backup_accetta_backup_reale(db_mod):
    """Un backup realmente creato dev'essere ripristinabile."""
    db = db_mod
    nome = db.create_backup()
    assert nome, "create_backup non ha prodotto un backup"
    assert db.restore_backup(nome) is True


def test_percorso_backup_valido_rifiuta_traversal(db_mod):
    """L'helper condiviso rifiuta nomi con percorso e nomi inesistenti."""
    db = db_mod
    for nome in ['../evil.db', 'sub/evil.db', '', 'gestionale_backup_00000000_000000.db']:
        assert db.percorso_backup_valido(nome) is None
    nome = db.create_backup()
    assert db.percorso_backup_valido(nome) is not None


def test_download_backup_route(client, db_mod):
    """Un backup reale si scarica; un nome inesistente restituisce 404."""
    nome = db_mod.create_backup()
    r = client.get(f'/api/backup/download/{nome}')
    assert r.status_code == 200
    assert len(r.data) > 0
    r = client.get('/api/backup/download/gestionale_backup_00000000_000000.db')
    assert r.status_code == 404


def test_reset_password_cambia_hash_senza_perdere_dati(db_mod, sample_data, monkeypatch):
    """reset_password aggiorna l'hash (nuova password valida, vecchia no) e i
    dati restano al loro posto."""
    from werkzeug.security import check_password_hash
    import reset_password

    utenti_prima = len(db_mod.get_all_utenti())

    monkeypatch.setattr('sys.argv', ['reset_password.py', '--password', 'nuovapass123'])
    assert reset_password.main() == 0

    hash_nuovo = db_mod.auth_get_user()['password_hash']
    assert check_password_hash(hash_nuovo, 'nuovapass123')
    assert not check_password_hash(hash_nuovo, 'secret')  # vecchia password non valida
    # I dati non sono stati toccati
    assert len(db_mod.get_all_utenti()) == utenti_prima


def test_reset_password_rifiuta_password_corta(db_mod, monkeypatch):
    """Password troppo corta: nessuna modifica e uscita con errore."""
    import reset_password
    hash_prima = db_mod.auth_get_user()['password_hash']
    monkeypatch.setattr('sys.argv', ['reset_password.py', '--password', 'corta'])
    assert reset_password.main() == 1
    assert db_mod.auth_get_user()['password_hash'] == hash_prima

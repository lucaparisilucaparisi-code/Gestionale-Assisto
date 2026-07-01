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

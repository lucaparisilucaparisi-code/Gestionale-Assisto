"""Test delle funzioni di prodotto della v1.6.0: annulla import, mese chiuso,
cartella backup esterna.
"""
import io
import os

import openpyxl


def test_import_risposta_include_backup_pre_import(client, db_mod):
    """La risposta dell'import deve esporre il nome del backup pre-import,
    cosi' il frontend puo' offrire 'Annulla questo import'."""
    db_mod.create_commessa('OEPAC UNDOIMP')
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['Commessa', 'Scuola', 'Nome', 'Cognome', 'Monte Ore'])
    ws.append(['OEPAC UNDOIMP', 'IC UndoImp - Primaria', 'Anna', 'Import', 10])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    r = client.post('/api/import-excel',
                    data={'file': (buf, 'anagrafica.xlsx')},
                    content_type='multipart/form-data')
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body.get('backup_pre_import'), 'nome backup assente dalla risposta'
    # il backup esiste davvero ed e' ripristinabile
    assert db_mod.percorso_backup_valido(body['backup_pre_import'])


def test_mese_chiuso_persistente(client):
    """Il flag 'mese chiuso' persiste e si puo' rimuovere."""
    r = client.get('/api/mese-chiuso/2026/3')
    assert r.get_json()['chiuso'] is False

    assert client.post('/api/mese-chiuso/2026/3').status_code == 200
    body = client.get('/api/mese-chiuso/2026/3').get_json()
    assert body['chiuso'] is True and body['data_chiusura']

    assert client.delete('/api/mese-chiuso/2026/3').status_code == 200
    assert client.get('/api/mese-chiuso/2026/3').get_json()['chiuso'] is False


def test_cartella_backup_esterna(client, db_mod, tmp_path):
    """La cartella esterna viene validata, salvata, e i backup vi vengono copiati."""
    # cartella inesistente -> rifiutata
    r = client.post('/api/backup/cartella-esterna',
                    json={'cartella': '/percorso/che/non/esiste'})
    assert r.status_code == 400

    # cartella valida -> accettata e usata dal prossimo backup
    esterna = tmp_path / 'backup_esterni'
    esterna.mkdir()
    r = client.post('/api/backup/cartella-esterna', json={'cartella': str(esterna)})
    assert r.status_code == 200

    nome = db_mod.create_backup()
    assert nome
    assert os.path.exists(esterna / nome), 'backup non copiato nella cartella esterna'

    # rimozione dell'impostazione
    r = client.post('/api/backup/cartella-esterna', json={'cartella': ''})
    assert r.status_code == 200
    assert client.get('/api/backup/cartella-esterna').get_json()['cartella'] == ''

"""Test del parsing e import idempotente dell'anagrafica dipendenti."""
import io

import openpyxl

import import_dipendenti as imp


def _wb(rows):
    """Crea un xlsx in memoria: prima riga intestazioni, poi i dati."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['Cognome', 'Nome', 'Codice Fiscale', 'Qualifica',
               'Monte ore contrattuale', 'Genere', 'Livello'])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_mappa_core_e_extra():
    data = _wb([['Rossi', 'Mario', 'RSSMRA80A01H501U', 'OEPAC', 25, 'M', 'D1']])
    recs = imp.parse_workbook(data)
    assert len(recs) == 1
    r = recs[0]
    assert r['cognome'] == 'Rossi' and r['nome'] == 'Mario'
    assert r['codice_fiscale'] == 'RSSMRA80A01H501U'
    assert r['ore_contrattuali_settimanali'] == 25
    # le colonne non-core finiscono in extra con l'etichetta originale
    assert r['extra']['Genere'] == 'M' and r['extra']['Livello'] == 'D1'


def test_import_idempotente_e_omonimi(db_mod):
    db = db_mod
    # Due OMONIMI con CF diversi + un terzo distinto
    data = _wb([
        ['Bianchi', 'Luca', 'BNCLCU80A01H501A', 'OEPAC', 20, 'M', 'C1'],
        ['Bianchi', 'Luca', 'BNCLCU90B02H501B', 'OEPAC', 18, 'M', 'C2'],  # stesso nome, CF diverso
        ['Verdi', 'Sara', 'VRDSRA85C03H501C', 'OEPAC', 30, 'F', 'D1'],
    ])
    recs = imp.parse_workbook(data)
    res = db.importa_dipendenti(recs)
    # I due omonimi NON devono essere fusi: 3 creati
    assert res['creati'] == 3 and res['aggiornati'] == 0

    # Re-import: tutti abbinati per CF, nessun duplicato
    res2 = db.importa_dipendenti(recs)
    assert res2['creati'] == 0 and res2['aggiornati'] == 3

    cf_presenti = {d['codice_fiscale'] for d in db.get_all_dipendenti(include_inactive=True)}
    assert {'BNCLCU80A01H501A', 'BNCLCU90B02H501B', 'VRDSRA85C03H501C'} <= cf_presenti

"""Archivio Roma INVENTATO per la fotografia di Roma (test_roma_golden, test_roma_invariata).

Due anni scolastici (2024-25 e 2025-26) di tre commesse di prova, scritti SOLO con le
API HTTP che esistono nella v1.20.1, con l'orologio fermo su date diverse come farebbe
l'operatrice nel tempo: anagrafica (anche da import Excel e con plessi omonimi in due
commesse), calendario automatico e ritocchi, ore e pasti mese per mese (anche zero,
sopra e sotto la media, un mese a meta'), mesi chiusi e riaperti, variazioni aperte e
temporanee, liste d'attesa di anni diversi, archiviazioni (anche dal wizard del nuovo
anno, che conserva il monte ore dei mesi passati), cambio di scuola, operatori con
assegnazioni, turni, assenze e sostituzioni, determine, recuperi, correzioni dei
report, note, assenze, documenti, budget, notifiche, Ctrl+Z.

Nomi di fantasia, nessun codice fiscale: nessun dato reale.
Ore sempre in quarti d'ora: somme esatte con qualunque versione di Python.

Non cambiare questo file senza rigenerare tests/golden/roma_v1_20_1.json SUL CODICE
DELLA v1.20.1 (vedi docs/ARCHITETTURA.md, "Protezioni per Roma").
"""
import io
from datetime import datetime

# Orologio della fotografia e mesi in cui si fotografano gli export mensili.
OGGI_FOTOGRAFIA = datetime(2026, 4, 15, 10, 0)
MESI_EXPORT = [(2024, 10), (2025, 6), (2025, 10), (2026, 3)]

NORD, SUD, VUOTA = 'ROMA PROVA NORD', 'ROMA PROVA SUD', 'ROMA PROVA VUOTA'
ARCOBALENO = 'IC Fantasia - Primaria Arcobaleno'      # stesso nome in NORD e in SUD
GIRASOLE = 'IC Fantasia - Infanzia Girasole'
GALILEO = 'IC Immaginario - Secondaria Galileo'
STELLA = 'IC Lontano - Infanzia Stella'

# (chiave, commessa, scuola, nome, cognome, monte ore settimanale)
UTENTI = [
    ('alba', NORD, ARCOBALENO, 'Alba', 'Esempio', 10),
    ('bruno', NORD, ARCOBALENO, 'Bruno', 'Fittizio', 12.5),
    ('ciro', NORD, ARCOBALENO, 'Ciro', 'Inventato', 8),
    ('dalia', NORD, GIRASOLE, 'Dalia', 'Immaginaria', 15),
    ('elio', NORD, GIRASOLE, 'Elio', 'Finto', 6),
    ('fiore', NORD, GALILEO, 'Fiore', 'Sintetico', 9),
    ('gaia', NORD, GALILEO, 'Gaia', 'Campione', 18),
    ('alba_sud', SUD, ARCOBALENO, 'Alba', 'Esempio', 10),  # omonima, altra commessa
    ('ivo', SUD, ARCOBALENO, 'Ivo', 'Modello', 14),
    ('luna', SUD, STELLA, 'Luna', 'Ipotetica', 12),
    ('marco', SUD, STELLA, 'Marco', 'Demo', 7.5),
]
# Arrivano dopo: Nora a ottobre 2025 (a mano), Oscar e Pia dall'import Excel.
UTENTI_DOPO = [
    ('nora', NORD, ARCOBALENO, 'Nora', 'Nuova', 11),
    ('oscar', SUD, STELLA, 'Oscar', 'Prova', 5),
    ('pia', SUD, ARCOBALENO, 'Pia', 'Prova', 11.25),
]
OPERATORI = [
    ('primo', 'Primo', 'Operatore', NORD, 25),
    ('seconda', 'Seconda', 'Operatrice', NORD, 30),
    ('terzo', 'Terzo', 'Operatore', SUD, 20),
    ('quarta', 'Quarta', 'Operatrice', SUD, 18),
]


def _quarti(x):
    """Arrotonda al quarto d'ora (valori esatti in virgola mobile)."""
    return round(x * 4) / 4


class _Archivio:
    def __init__(self, client):
        self.c = client
        self.u = {}          # chiave -> id utente
        self.d = {}          # chiave -> id dipendente
        self.commessa_id = {}
        self.scuola_id = {}  # (commessa, scuola) -> id

    # --- richieste ---
    def _ok(self, r):
        assert r.status_code == 200, (r.status_code, r.get_data(as_text=True)[:300])
        return r.get_json(silent=True)

    def post(self, url, dati=None):
        return self._ok(self.c.post(url, json=dati if dati is not None else {}))

    def put(self, url, dati):
        return self._ok(self.c.put(url, json=dati))

    def delete(self, url):
        return self._ok(self.c.delete(url))

    def get(self, url):
        return self._ok(self.c.get(url))

    # --- anagrafica ---
    def crea_utente(self, chiave, commessa, scuola, nome, cognome, monte_ore):
        j = self.post('/api/utenti', {'commessa': commessa, 'scuola': scuola, 'nome': nome,
                                      'cognome': cognome, 'monte_ore': monte_ore})
        self.u[chiave] = j['utente_id']

    def leggi_scuole(self):
        for commessa in (NORD, SUD):
            for s in self.get(f'/api/scuole?commessa={commessa.replace(" ", "%20")}'):
                self.scuola_id[(commessa, s.get('nome_completo') or s.get('nome'))] = s['id']

    # --- ore ---
    def ore_mese(self, anno, mese, chiavi=None, fattore=1.0):
        """Ore e pasti del mese per gli utenti indicati (tutti quelli creati se None)."""
        righe = []
        for i, (chiave, _, scuola, _, _, monte) in enumerate(UTENTI + UTENTI_DOPO):
            if chiave not in self.u or (chiavi is not None and chiave not in chiavi):
                continue
            k = (i * 7 + mese * 3) % 6
            ore = 0.0 if k == 5 and chiave in ('ciro', 'luna') else _quarti(monte * (3.1 + 0.25 * k) * fattore)
            riga = {'utente_id': self.u[chiave], 'ore_lavorate_60': ore}
            if 'Secondaria' not in scuola:
                riga['pasti'] = (k * 3 + mese) % 19
            if k == 2:
                riga['note'] = 'Recupero di due ore della settimana precedente'
            righe.append(riga)
        self.post(f'/api/rendicontazione/{anno}/{mese}/batch', {'updates': righe})


def costruisci_archivio(client, orologio):
    """Scrive l'archivio con il client di prova (sessione autenticata) e
    orologio(quando), il context manager che ferma l'ora del programma
    (strumenti.fotografa_roma.orologio_fermo). Ritorna gli id creati."""
    a = _Archivio(client)

    with orologio(datetime(2024, 9, 16, 9, 0)):
        for nome, colore in ((NORD, '#10B981'), (SUD, '#F59E0B'), (VUOTA, None)):
            a.post('/api/commesse', {'nome': nome, 'descrizione': 'Commessa inventata per i test',
                                         'colore': colore})
        for c in a.get('/api/commesse'):
            a.commessa_id[c['nome']] = c['id']
        a.post('/api/anno-scolastico/prepara', {'anno_scolastico': '2024-2025'})
        a.post('/api/calendario', {'anno_scolastico': '2024-2025', 'mese': 3, 'anno': 2025,
                                   'giorni_lavorativi': 20, 'giorni_lavorativi_altri': 21})
        for riga in UTENTI:
            a.crea_utente(*riga)
        a.leggi_scuole()
        for chiave, nome, cognome, commessa, ore in OPERATORI:
            j = a.post('/api/dipendenti', {'nome': nome, 'cognome': cognome, 'qualifica': 'OEPAC',
                                           'commessa_id': a.commessa_id[commessa],
                                           'ore_contrattuali_settimanali': ore,
                                           'data_assunzione': '2024-09-01', 'sede': 'Sede di prova'})
            a.d[chiave] = j['id']
        for dip, utente, ore in (('primo', 'alba', 6), ('primo', 'bruno', 8), ('seconda', 'dalia', 10),
                                 ('seconda', 'gaia', 12), ('terzo', 'ivo', 9), ('quarta', 'luna', 7)):
            a.post(f'/api/utente/{a.u[utente]}/assegnazioni',
                   {'dipendente_id': a.d[dip], 'ore_settimanali': ore, 'valido_da': '2024-09-16'})
        for dip, utente, commessa, scuola, giorni, inizio, fine in (
                ('primo', 'alba', NORD, ARCOBALENO, (0, 2), '08:30', '10:30'),
                ('primo', 'bruno', NORD, ARCOBALENO, (0, 1, 3), '11:00', '13:00'),
                ('seconda', 'dalia', NORD, GIRASOLE, (1, 2, 3, 4), '09:00', '11:30'),
                ('terzo', 'ivo', SUD, ARCOBALENO, (0, 1, 2), '08:00', '11:00'),
                ('quarta', 'luna', SUD, STELLA, (3, 4), '10:00', '13:30')):
            for g in giorni:
                a.post(f'/api/dipendenti/{a.d[dip]}/turni',
                       {'giorno': g, 'ora_inizio': inizio, 'ora_fine': fine, 'valido_da': '2024-09-16',
                        'scuola_id': a.scuola_id[(commessa, scuola)], 'utente_id': a.u[utente]})
        for commessa, ore_sett, ore_anno in ((NORD, 78.5, 2747.5), (SUD, 44, 1540)):
            a.post('/api/dd', {'commessa_id': a.commessa_id[commessa], 'anno_scolastico': '2024-2025',
                               'mese_inizio': 9, 'anno_inizio': 2024, 'ore_settimanali': ore_sett,
                               'ore_annuali': ore_anno, 'numero_dd': 'DD di prova 1', 'data_dd': '2024-09-10',
                               'note': 'Determina inventata'})
        a.put(f'/api/utente/{a.u["gaia"]}/budget', {'budget_mensile': 70, 'budget_annuale': 650})

    with orologio(datetime(2024, 11, 5, 9, 30)):
        a.ore_mese(2024, 10)
        a.post(f'/api/utenti/{a.u["gaia"]}/variazioni-monte-ore',
               {'monte_ore': 22, 'mese_inizio': '2024-11', 'nota': 'Aumento da PEI (prova)'})

    with orologio(datetime(2024, 12, 4, 16, 0)):
        a.ore_mese(2024, 11)
        a.post('/api/mese-chiuso/2024/10')

    with orologio(datetime(2025, 1, 8, 10, 15)):
        a.ore_mese(2024, 12)
        a.put(f'/api/utenti/{a.u["elio"]}', {'data_fine': '2024-12'})
        a.put(f'/api/utenti/{a.u["elio"]}', {'attivo': False})

    with orologio(datetime(2025, 4, 3, 11, 0)):
        a.ore_mese(2025, 3)
        a.put(f'/api/utenti/{a.u["ciro"]}', {'lista_attesa': 'Marzo', 'lista_attesa_as': '2024-2025'})
        a.post(f'/api/utente/{a.u["dalia"]}/assenze',
               {'data_inizio': '2025-03-10', 'data_fine': '2025-03-14', 'tipo': 'malattia',
                'motivazione': 'Assenza di prova', 'note': 'Inventata'})

    with orologio(datetime(2025, 6, 10, 9, 0)):
        a.ore_mese(2025, 5)
        a.post('/api/recuperi', {'commessa_id': a.commessa_id[NORD], 'anno_scolastico': '2024-2025',
                                 'mese': 5, 'anno': 2025, 'ore_recupero': 6.5, 'note': 'Recupero di prova'})
        a.post('/api/progettato-override', {'commessa_id': a.commessa_id[SUD], 'anno_scolastico': '2024-2025',
                                            'mese': 5, 'anno': 2025, 'ore_progettate': 180.75})
        a.post('/api/report-override', {'commessa_id': a.commessa_id[NORD], 'anno_scolastico': '2024-2025',
                                        'mese': 3, 'anno': 2025, 'campo': 'giorni_lavorativi', 'valore': 19})

    with orologio(datetime(2025, 6, 30, 17, 0)):
        a.ore_mese(2025, 6, fattore=0.3)
        a.post('/api/mese-chiuso/2024/11')
        a.post('/api/mese-chiuso/2024/12')

    # Wizard del nuovo anno: calendario, variazioni chiuse al 31/8, monte ore nuovo
    # (con il valore vecchio conservato per i mesi passati), un'archiviazione.
    with orologio(datetime(2025, 7, 1, 9, 0)):
        a.post('/api/anno-scolastico/prepara', {'anno_scolastico': '2025-2026'})
        a.get('/api/anno-scolastico/utenti-anteprima?anno_scolastico=2025-2026')
        a.post('/api/anno-scolastico/prepara-utenti',
               {'anno_scolastico': '2025-2026', 'chiudi_variazioni': True,
                'monte_ore': {str(a.u['bruno']): 14}, 'archivia': [a.u['marco']]})

    with orologio(datetime(2025, 9, 15, 8, 45)):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(['Commessa', 'Albero Attività', 'Attività', 'Monte Ore Sett.'])
        for _, commessa, scuola, nome, cognome, monte in UTENTI_DOPO[1:]:
            ws.append([commessa, scuola, f'{cognome} {nome}', monte])     # "Cognome Nome"
        ws.append([SUD, ARCOBALENO, 'Modello Ivo', 14])
        dati = io.BytesIO()
        wb.save(dati)
        dati.seek(0)
        a._ok(a.c.post('/api/import-excel', data={'file': (dati, 'anagrafica_prova.xlsx'), 'mode': 'update'},
                       content_type='multipart/form-data'))
        for u in a.get(f'/api/utenti?commessa={SUD.replace(" ", "%20")}'):
            if u['cognome'] == 'Prova':
                a.u[u['nome'].lower()] = u['id']
        a.post('/api/dd', {'commessa_id': a.commessa_id[NORD], 'anno_scolastico': '2025-2026',
                           'mese_inizio': 9, 'anno_inizio': 2025, 'ore_settimanali': 90.5,
                           'ore_annuali': 3167.5, 'numero_dd': 'DD di prova 2', 'data_dd': '2025-09-08'})
        a.post('/api/calendario', {'anno_scolastico': '2025-2026', 'mese': 10, 'anno': 2025,
                                   'giorni_lavorativi': 22, 'giorni_lavorativi_altri': 23})
        j = a.post('/api/dipendenti', {'nome': 'Quinto', 'cognome': 'Operatore', 'qualifica': 'OEPAC',
                                       'commessa_id': a.commessa_id[SUD], 'ore_contrattuali_settimanali': 24,
                                       'data_assunzione': '2025-09-01'})
        a.d['quinto'] = j['id']
        a.post(f'/api/utente/{a.u["oscar"]}/assegnazioni',
               {'dipendente_id': a.d['quinto'], 'ore_settimanali': 5, 'valido_da': '2025-09-15'})

    with orologio(datetime(2025, 10, 3, 10, 0)):
        a.ore_mese(2025, 9)

    with orologio(datetime(2025, 10, 6, 12, 0)):
        a.crea_utente(*UTENTI_DOPO[0])
        a.put(f'/api/utenti/{a.u["nora"]}', {'data_inizio': '2025-10'})

    with orologio(datetime(2025, 11, 4, 9, 0)):
        a.ore_mese(2025, 10)
        a.post(f'/api/utenti/{a.u["fiore"]}/variazioni-monte-ore',
               {'monte_ore': 12, 'mese_inizio': '2025-11', 'mese_fine': '2025-12', 'nota': 'Temporanea (prova)'})

    with orologio(datetime(2025, 12, 3, 15, 30)):
        a.ore_mese(2025, 11)
        a.post('/api/mese-chiuso/2025/9')
        a.post('/api/mese-chiuso/2025/10')
        a.post('/api/mese-chiuso/2025/11')
        a.delete('/api/mese-chiuso/2025/11')          # riaperto

    with orologio(datetime(2026, 1, 9, 9, 0)):
        a.ore_mese(2025, 12, chiavi={'alba_sud', 'ivo', 'luna', 'oscar', 'pia'})   # NORD da completare
        a.post(f'/api/utenti/{a.u["ivo"]}/cambio-scuola', {'scuola_id': a.scuola_id[(SUD, STELLA)]})

    with orologio(datetime(2026, 2, 4, 11, 0)):
        a.ore_mese(2026, 1)
        a.post(f'/api/utente/{a.u["alba"]}/note', {'contenuto': 'Nota generale di prova', 'tipo': 'generale',
                                                   'priorita': 'alta'})
        a.post(f'/api/utente/{a.u["alba"]}/note', {'contenuto': 'Nota del mese (prova)', 'tipo': 'mensile',
                                                   'priorita': 'normale', 'anno': 2026, 'mese': 1})
        for nome_file, scadenza in (('certificato_prova.txt', '2025-12-31'), ('progetto_prova.txt', '')):
            a._ok(a.c.post(f'/api/utente/{a.u["alba"]}/documenti',
                           data={'file': (io.BytesIO(b'Documento inventato per i test'), nome_file),
                                 'tipo': 'certificato', 'descrizione': 'Documento di prova',
                                 'data_scadenza': scadenza},
                           content_type='multipart/form-data'))

    with orologio(datetime(2026, 3, 4, 10, 0)):
        a.ore_mese(2026, 2, chiavi={'alba', 'bruno', 'dalia', 'fiore', 'gaia', 'nora', 'alba_sud', 'oscar'})
        a.post('/api/rendicontazione/2026/2/copia-precedente', {'solo_vuoti': True})
        a.put(f'/api/utenti/{a.u["luna"]}', {'lista_attesa': 'Febbraio', 'lista_attesa_as': '2025-2026'})

    with orologio(datetime(2026, 4, 2, 9, 30)):
        a.ore_mese(2026, 3, fattore=1.15)
        a.post(f'/api/dipendenti/{a.d["primo"]}/assenze',
               {'data_inizio': '2026-03-16', 'data_fine': '2026-03-18', 'tipo': 'ferie', 'motivazione': 'Prova'})
        da_coprire = a.get('/api/sostituzioni?da_coprire=1')
        if isinstance(da_coprire, dict):
            da_coprire = da_coprire.get('sostituzioni') or da_coprire.get('data') or []
        if da_coprire:
            a.post(f'/api/sostituzioni/{da_coprire[0]["id"]}/assegna', {'sostituto_id': a.d['seconda']})
        a.post('/api/recuperi', {'commessa_id': a.commessa_id[SUD], 'anno_scolastico': '2025-2026',
                                 'mese': 3, 'anno': 2026, 'ore_recupero': 4.25})

    with orologio(OGGI_FOTOGRAFIA):
        a.ore_mese(2026, 4, chiavi={'alba', 'bruno', 'ciro', 'nora'}, fattore=0.5)
        a.post('/api/rendicontazione/2026/4/compila-media', {'utente_ids': [a.u['pia']]})
        a.post('/api/notifiche/genera')
        j = a.post(f'/api/utenti/{a.u["ivo"]}/duplica')
        a.delete(f'/api/utenti/{j["nuovo_id"]}')
        a.put(f'/api/utenti/{a.u["ciro"]}', {'lista_attesa': 'Aprile', 'lista_attesa_as': '2025-2026'})

    return {'utenti': dict(a.u), 'dipendenti': dict(a.d), 'commesse': dict(a.commessa_id)}

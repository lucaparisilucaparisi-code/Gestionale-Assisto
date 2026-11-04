#!/usr/bin/env python3
"""Fotografia delle uscite di Roma: numeri e strutture, non l'HTML che cambia.

Una fotografia e' la raccolta delle risposte di tutte le rotte GET di Roma (pagine,
API, statistiche, report ed export) su un database, ridotte a cio' che conta:
- JSON: i valori, con le date-ora del momento e la versione mascherate;
- Excel: fogli, celle (formule comprese) e celle unite;
- Word: paragrafi e tabelle;
- pagine: titolo, id degli elementi, intestazioni e un'impronta del contenuto
  della pagina, SENZA il menu laterale (l'unica parte che Napoli cambia).

La usano (docs/ARCHITETTURA.md, "Protezioni per Roma"):
- tests/test_roma_golden.py: l'archivio Roma inventato (tests/roma_sintetico.py)
  deve dare sempre la fotografia di tests/golden/roma_v1_20_1.json;
- tests/test_roma_invariata.py: la fotografia non cambia quando nel database ci
  sono anche dati di Napoli; ogni rotta dell'applicazione e' classificata qui;
- strumenti/confronta_roma.py: confronto fra due versioni su copie di un database.

Uso a riga di comando (scrive la fotografia in un file JSON e non stampa dati):

    python strumenti/fotografa_roma.py --sintetico --uscita FILE [--codice CARTELLA]
    python strumenti/fotografa_roma.py --db COPIA.db --uscita FILE [--codice CARTELLA] [--oggi AAAA-MM-GG]

--codice e' la cartella della versione da fotografare (predefinita: questa). Con
--sintetico l'archivio inventato si crea in un database temporaneo; con --db si
lavora su quel file, che viene aggiornato da init_db: deve essere una COPIA.
Il modulo non importa niente del programma finche' non serve, cosi' la stessa
copia fotografa anche una versione precedente.
"""
import argparse
import contextlib
import datetime as _dt
import hashlib
import html.parser
import importlib.util
import io
import json
import os
import pathlib
import re
import sqlite3
import sys
import tempfile
from urllib.parse import urlencode

VERSIONE_FOTOGRAFIA = 1
CARTELLA_PROGETTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ==================== INVENTARIO DELLE ROTTE ====================
# Ogni rotta di app.url_map sta in UNA delle tre classi (test_inventario_rotte):
# - ROTTE_ROMA: quelle di Roma, che devono restare identiche. Le GET si
#   fotografano tutte (FOTOGRAFIE, sotto); le altre sono scritture, il cui effetto
#   si vede dalle GET;
# - ROTTE_NAPOLI: quelle della sezione Napoli (/napoli, /api/napoli/...);
# - ESCLUSE: rotte comuni che possono cambiare quando ci sono dati di Napoli, con
#   il motivo.
# Una rotta nuova non classificata fa fallire il test.

ROTTE_ROMA_SCRITTURA = frozenset({
    '/api/anno-scolastico/prepara',
    '/api/anno-scolastico/prepara-utenti',
    '/api/assegnazioni/<int:assegnazione_id>',
    '/api/assenza/<int:assenza_id>',
    '/api/assenze-dipendenti/<int:assenza_id>',
    '/api/auth/change-password',
    '/api/auth/login',
    '/api/auth/logout',
    '/api/auth/setup',
    '/api/auth/webauthn/authenticate/begin',
    '/api/auth/webauthn/authenticate/complete',
    '/api/auth/webauthn/credentials/<int:cred_id>',
    '/api/auth/webauthn/register/begin',
    '/api/auth/webauthn/register/complete',
    '/api/calendario/<anno_scolastico>/calcola-auto',
    '/api/calendario/<anno_scolastico>/copia-precedente',
    '/api/commesse/<int:commessa_id>',
    '/api/dd',
    '/api/dd/<int:dd_id>',
    '/api/import-dipendenti',
    '/api/import-dipendenti/preview',
    '/api/import-excel',
    '/api/import-excel/preview',
    '/api/import-rendicontazione',
    '/api/import-rendicontazione/preview',
    '/api/migrazione/anteprima',
    '/api/migrazione/importa',
    '/api/nota/<int:nota_id>',
    '/api/notifiche/<int:notifica_id>/archivia',
    '/api/notifiche/<int:notifica_id>/letta',
    '/api/notifiche/genera',
    '/api/notifiche/lette',
    '/api/progettato-override',
    '/api/progettato-override/<int:commessa_id>/<anno_scolastico>/<int:mese>/<int:anno>',
    '/api/recuperi',
    '/api/recuperi/<int:recupero_id>',
    '/api/rendicontazione/<int:anno>/<int:mese>/batch',
    '/api/rendicontazione/<int:anno>/<int:mese>/compila-media',
    '/api/report-override',
    '/api/report-override/<int:commessa_id>/<anno_scolastico>/<int:mese>/<int:anno>/<campo>',
    '/api/reset',
    '/api/sostituzioni/<int:sostituzione_id>/annulla',
    '/api/sostituzioni/<int:sostituzione_id>/assegna',
    '/api/turni/<int:turno_id>',
    '/api/undo/scadute',
    '/api/utente/<int:utente_id>/budget',
    '/api/utenti/<int:utente_id>',
    '/api/utenti/<int:utente_id>/cambio-scuola',
    '/api/utenti/<int:utente_id>/duplica',
    '/api/utenti/bulk',
    '/api/utenti/import-csv',
    '/api/variazioni-monte-ore/<int:variazione_id>',
})

# Riempita dai passi della sezione Napoli (rotte sotto /napoli e /api/napoli).
ROTTE_NAPOLI = frozenset()
PREFISSI_NAPOLI = ('/napoli', '/api/napoli')

_MOTIVO_BACKUP = "backup dell'intero database: l'import di Napoli crea un backup e il file contiene anche Napoli"
ESCLUSE = {
    '/static/<path:filename>': 'file statici: app.js cambia per Napoli (Alt+8, annulla della pagina); '
                               'li controllano test_css_integrita e i test della grafica',
    '/api/audit': "registro attivita' condiviso: le azioni di Napoli vi scrivono le loro voci",
    '/api/audit/export': "registro attivita' condiviso: le azioni di Napoli vi scrivono le loro voci",
    '/api/backup': _MOTIVO_BACKUP,
    '/api/backup/cartella-esterna': _MOTIVO_BACKUP,
    '/api/backup/download/<path:backup_name>': _MOTIVO_BACKUP,
    '/api/backup/restore': _MOTIVO_BACKUP,
}

# Chiavi che dipendono dall'ambiente e non dai dati: sum() compensata dalla 3.12.
CHIAVI_AMBIENTE = frozenset({'somma_compensata'})
# Blocco del trasloco JSON che i passi di Napoli aggiungono solo se ci sono dati di
# Napoli (PROGETTO §4.5): non fa parte di Roma.
CHIAVI_NAPOLI_TRASLOCO = frozenset({'napoli'})


# ==================== CONTESTO: COSA C'E' NEL DATABASE ====================

def anno_scolastico(anno, mese):
    """Come config.anno_scolastico_di, senza importare il programma."""
    return f"{anno}-{anno + 1}" if mese >= 9 else f"{anno - 1}-{anno}"


class Contesto:
    """Elenchi letti dal database (sola lettura) da cui nascono gli indirizzi.

    mesi: tutti quelli con righe di rendicontazione; mesi_export: i mesi per gli
    export mensili (tutti se None). filtri: "Tutte" (None) e le commesse che hanno
    almeno una scuola (quelle vuote compaiono comunque in "Tutte" e negli elenchi)."""

    def __init__(self, percorso_db, mesi_export=None):
        conn = sqlite3.connect(pathlib.Path(percorso_db).resolve().as_uri() + '?mode=ro', uri=True)
        try:
            def colonna(sql):
                return [r[0] for r in conn.execute(sql)]
            self.commesse = [(r[0], r[1]) for r in conn.execute('SELECT id, nome FROM commesse ORDER BY id')]
            con_scuole = set(colonna('SELECT DISTINCT commessa_id FROM scuole'))
            self.mesi = [(r[0], r[1]) for r in conn.execute(
                'SELECT DISTINCT anno, mese FROM rendicontazione ORDER BY anno, mese')]
            calendario = colonna('SELECT DISTINCT anno_scolastico FROM calendario_scolastico')
            self.utenti = colonna('SELECT id FROM utenti ORDER BY id')
            self.dipendenti = colonna('SELECT id FROM dipendenti ORDER BY id')
            self.sostituzioni = colonna('SELECT id FROM sostituzioni ORDER BY id')
            self.documenti = colonna('SELECT id FROM documenti_utente ORDER BY id')
            self.scuole = colonna('SELECT nome_completo FROM scuole ORDER BY id')
        finally:
            conn.close()
        self.anni = sorted(set(calendario) | {anno_scolastico(a, m) for a, m in self.mesi})
        self.anni_solari = sorted({a for a, _ in self.mesi})
        self.mesi_export = self.mesi if mesi_export is None else [tuple(m) for m in mesi_export]
        self.filtri = [None] + [nome for i, nome in self.commesse if i in con_scuole]


def _url(percorso, **parametri):
    """Indirizzo con i parametri non vuoti, nell'ordine dato."""
    coppie = [(k, v) for k, v in parametri.items() if v is not None]
    return percorso + ('?' + urlencode(coppie) if coppie else '')


def _per_mese_e_commessa(percorso, c):
    return [_url(percorso, anno=a, mese=m, commessa=f) for a, m in c.mesi for f in c.filtri]


def _mese_nel_percorso(modello, c, con_commessa=True):
    filtri = c.filtri if con_commessa else [None]
    return [_url(modello.format(anno=a, mese=m), commessa=f) for a, m in c.mesi for f in filtri]


def _export_mensile(tipo, c, privacy=True):
    urls = [_url(f'/api/export/{tipo}/{a}/{m}', commessa=f) for a, m in c.mesi_export for f in c.filtri]
    if privacy and c.mesi_export:
        a, m = c.mesi_export[-1]
        urls.append(_url(f'/api/export/{tipo}/{a}/{m}', privacy='true'))
    return urls


def _per_utente(modello, c, **parametri):
    return [_url(modello.format(id=u), **parametri) for u in c.utenti]


def _per_utente_e_anno(modello, c, chiave=None):
    if chiave:
        return [_url(modello.format(id=u), **{chiave: a}) for u in c.utenti for a in c.anni]
    return [modello.format(id=u, anno=a) for u in c.utenti for a in c.anni]


def _coppie_di_anni(c):
    return [(c.anni[i], c.anni[i + 1]) for i in range(len(c.anni) - 1)]


def _ricerche(c):
    """Parole da cercare: frammenti dei nomi delle scuole (mai nomi di persone)."""
    parole = []
    for nome in c.scuole:
        for p in re.findall(r'[A-Za-z]{4,}', nome or ''):
            if p.lower() not in parole:
                parole.append(p.lower())
    return parole[:4] or ['scuola']


FOTOGRAFIE = {
    # --- pagine ---
    '/': lambda c: ['/'],
    '/calendario': lambda c: ['/calendario'],
    '/chiusura-mese': lambda c: ['/chiusura-mese'],
    '/commesse': lambda c: ['/commesse'],
    '/dipendenti': lambda c: ['/dipendenti'],
    '/import': lambda c: ['/import'],
    '/impostazioni': lambda c: ['/impostazioni'],
    '/login': lambda c: ['/login'],
    '/profilo': lambda c: ['/profilo'],
    '/rendicontazione': lambda c: ['/rendicontazione'],
    '/report': lambda c: ['/report'],
    '/reportistica-locale': lambda c: ['/reportistica-locale'],
    '/setup': lambda c: ['/setup'],
    '/sostituzioni': lambda c: ['/sostituzioni'],
    '/statistiche': lambda c: ['/statistiche'],
    '/turni': lambda c: ['/turni'],
    '/utenti': lambda c: ['/utenti'],
    '/utente/<int:utente_id>': lambda c: [f'/utente/{u}' for u in c.utenti],
    '/dipendente/<int:dipendente_id>': lambda c: [f'/dipendente/{d}' for d in c.dipendenti],
    # --- accesso e impostazioni ---
    '/api/auth/status': lambda c: ['/api/auth/status'],
    '/api/auth/webauthn/credentials': lambda c: ['/api/auth/webauthn/credentials'],
    '/api/config': lambda c: ['/api/config'],
    '/api/docs': lambda c: ['/api/docs'],
    '/api/commesse': lambda c: ['/api/commesse'],
    '/api/calendario': lambda c: [_url('/api/calendario', anno_scolastico=a) for a in c.anni],
    '/api/anni-scolastici': lambda c: ['/api/anni-scolastici'],
    '/api/anno-scolastico/prossimo': lambda c: ['/api/anno-scolastico/prossimo'],
    '/api/anno-scolastico/utenti-anteprima': lambda c: [
        _url('/api/anno-scolastico/utenti-anteprima', anno_scolastico=a) for a in c.anni],
    '/api/mese-chiuso/<int:anno>/<int:mese>': lambda c: [f'/api/mese-chiuso/{a}/{m}' for a, m in c.mesi],
    '/api/undo': lambda c: ['/api/undo'],
    '/api/undo/ultima': lambda c: ['/api/undo/ultima'],
    '/api/migrazione/esporta': lambda c: ['/api/migrazione/esporta'],
    '/api/import-excel/cronologia': lambda c: ['/api/import-excel/cronologia'],
    '/api/import-excel/template': lambda c: ['/api/import-excel/template'],
    # --- utenti, scuole, ricerca ---
    '/api/utenti': lambda c: [_url('/api/utenti', attivi=s, commessa=f)
                              for s in (None, '0', 'tutti') for f in c.filtri]
    + ['/api/utenti?page=1&limit=5&attivi=tutti'],
    '/api/utenti/filtrati': lambda c: [_url('/api/utenti/filtrati', commessa=f) for f in c.filtri]
    + [_url('/api/utenti/filtrati', search=p) for p in _ricerche(c)],
    '/api/utenti/export-csv': lambda c: [_url('/api/utenti/export-csv', commessa=f) for f in c.filtri],
    '/api/scuole': lambda c: [_url('/api/scuole', commessa=f) for f in c.filtri],
    '/api/scuole/lista': lambda c: [_url('/api/scuole/lista', commessa=f) for f in c.filtri],
    '/api/search': lambda c: [_url('/api/search', q=p) for p in _ricerche(c)],
    '/api/utenti/<int:utente_id>/storico-monte-ore': lambda c: _per_utente(
        '/api/utenti/{id}/storico-monte-ore', c),
    '/api/utenti/<int:utente_id>/variazioni-monte-ore': lambda c: _per_utente(
        '/api/utenti/{id}/variazioni-monte-ore', c),
    '/api/utenti/classifica/<int:anno>': lambda c: [
        _url(f'/api/utenti/classifica/{a}', mese=m, order=o) for a, m in c.mesi for o in (None, 'asc')],
    '/api/utenti/confronto/<anno_scolastico>': lambda c: [
        _url(f'/api/utenti/confronto/{a}', ids=','.join(str(u) for u in c.utenti)) for a in c.anni],
    # --- scheda utente ---
    '/api/utente/<int:utente_id>/dettaglio': lambda c: _per_utente_e_anno(
        '/api/utente/{id}/dettaglio', c, 'anno_scolastico'),
    '/api/utente/<int:utente_id>/storico': lambda c: _per_utente('/api/utente/{id}/storico', c, mesi=24),
    '/api/utente/<int:utente_id>/storico-ore': lambda c: _per_utente_e_anno(
        '/api/utente/{id}/storico-ore', c, 'anno_scolastico'),
    '/api/utente/<int:utente_id>/andamento': lambda c: _per_utente('/api/utente/{id}/andamento', c, mesi=24),
    '/api/utente/<int:utente_id>/assegnazioni': lambda c: _per_utente('/api/utente/{id}/assegnazioni', c),
    '/api/utente/<int:utente_id>/assenze': lambda c: _per_utente('/api/utente/{id}/assenze', c),
    '/api/utente/<int:utente_id>/documenti': lambda c: _per_utente('/api/utente/{id}/documenti', c),
    '/api/utente/<int:utente_id>/note': lambda c: _per_utente('/api/utente/{id}/note', c),
    '/api/utente/<int:utente_id>/note/mensili/<int:anno>/<int:mese>': lambda c: [
        f'/api/utente/{u}/note/mensili/{a}/{m}' for u in c.utenti for a, m in c.mesi_export],
    '/api/utente/<int:utente_id>/budget/<anno_scolastico>': lambda c: _per_utente_e_anno(
        '/api/utente/{id}/budget/{anno}', c),
    '/api/budget/critici/<anno_scolastico>': lambda c: [f'/api/budget/critici/{a}' for a in c.anni],
    '/api/documento/<int:documento_id>': lambda c: [f'/api/documento/{d}' for d in c.documenti],
    '/api/documenti/scadenza': lambda c: ['/api/documenti/scadenza'],
    '/api/notifiche': lambda c: ['/api/notifiche', '/api/notifiche?tutte=1'],
    '/api/assenze/periodo': lambda c: [
        _url('/api/assenze/periodo', data_inizio=f'{a[:4]}-09-01', data_fine=f'{a[5:]}-08-31') for a in c.anni],
    '/api/assenze/report/<int:anno>': lambda c: [
        _url(f'/api/assenze/report/{a}', commessa=f) for a in c.anni_solari for f in c.filtri],
    # --- personale ---
    '/api/dipendenti': lambda c: ['/api/dipendenti', '/api/dipendenti?tutti=1']
    + [_url('/api/dipendenti', commessa_id=i) for i, _ in c.commesse],
    '/api/dipendenti/<int:dipendente_id>': lambda c: [f'/api/dipendenti/{d}' for d in c.dipendenti],
    '/api/dipendenti/<int:dipendente_id>/turni': lambda c: [f'/api/dipendenti/{d}/turni' for d in c.dipendenti],
    '/api/dipendenti/<int:dipendente_id>/assenze': lambda c: [
        f'/api/dipendenti/{d}/assenze' for d in c.dipendenti],
    '/api/turni/giorno': lambda c: [_url('/api/turni/giorno', giorno=g) for g in range(6)],
    '/api/sostituzioni': lambda c: ['/api/sostituzioni', '/api/sostituzioni?da_coprire=1'],
    '/api/sostituzioni/<int:sostituzione_id>/candidati': lambda c: [
        f'/api/sostituzioni/{s}/candidati' for s in c.sostituzioni],
    # --- rendicontazione e statistiche del mese ---
    '/api/rendicontazione/<int:anno>/<int:mese>': lambda c: _mese_nel_percorso(
        '/api/rendicontazione/{anno}/{mese}', c),
    '/api/rendicontazione/<int:anno>/<int:mese>/copia-precedente': lambda c: _mese_nel_percorso(
        '/api/rendicontazione/{anno}/{mese}/copia-precedente', c),
    '/api/rendicontazione/<int:anno>/<int:mese>/confronto-precedente': lambda c: _mese_nel_percorso(
        '/api/rendicontazione/{anno}/{mese}/confronto-precedente', c),
    '/api/alerts': lambda c: _per_mese_e_commessa('/api/alerts', c),
    '/api/alerts/<int:anno>/<int:mese>': lambda c: _mese_nel_percorso('/api/alerts/{anno}/{mese}', c),
    '/api/stats': lambda c: ['/api/stats'],
    '/api/stats/advanced': lambda c: _per_mese_e_commessa('/api/stats/advanced', c),
    '/api/stats/filtered': lambda c: _per_mese_e_commessa('/api/stats/filtered', c)
    + [_url('/api/stats/filtered', commessa=f) for f in c.filtri],
    '/api/stats/confronto-mese': lambda c: _per_mese_e_commessa('/api/stats/confronto-mese', c),
    '/api/stats/top-scuole': lambda c: _per_mese_e_commessa('/api/stats/top-scuole', c),
    '/api/stats/credito-debito': lambda c: _per_mese_e_commessa('/api/stats/credito-debito', c),
    '/api/stats/scuole-dettaglio': lambda c: _per_mese_e_commessa('/api/stats/scuole-dettaglio', c),
    '/api/stats/validazione': lambda c: _per_mese_e_commessa('/api/stats/validazione', c),
    '/api/stats/per-scuola/<int:anno>/<int:mese>': lambda c: _mese_nel_percorso(
        '/api/stats/per-scuola/{anno}/{mese}', c),
    '/api/stats/utenti-meno-ore/<int:anno>/<int:mese>': lambda c: _mese_nel_percorso(
        '/api/stats/utenti-meno-ore/{anno}/{mese}', c),
    '/api/stats/utenti-da-completare/<int:anno>/<int:mese>': lambda c: _mese_nel_percorso(
        '/api/stats/utenti-da-completare/{anno}/{mese}', c, con_commessa=False),
    # --- statistiche dell'anno ---
    '/api/stats/trend': lambda c: [_url('/api/stats/trend', anno_scolastico=a, commessa=f)
                                   for a in c.anni for f in c.filtri],
    '/api/stats/heatmap/<anno_scolastico>': lambda c: [_url(f'/api/stats/heatmap/{a}', commessa=f)
                                                      for a in c.anni for f in c.filtri],
    '/api/stats/ore-confronto/<anno_scolastico>': lambda c: [
        _url(f'/api/stats/ore-confronto/{a}', commessa=f) for a in c.anni for f in c.filtri],
    '/api/stats/confronto-annuale': lambda c: [
        _url('/api/stats/confronto-annuale', anno_1=a, anno_2=b) for a, b in _coppie_di_anni(c)],
    '/api/stats/confronto-annuale-dettaglio': lambda c: [
        _url('/api/stats/confronto-annuale-dettaglio', commessa=f, mese=m)
        for f in c.filtri for m in sorted({m for _, m in c.mesi})],
    # --- reportistica DD ---
    '/api/reportistica-locale/<int:commessa_id>/<anno_scolastico>': lambda c: [
        f'/api/reportistica-locale/{i}/{a}' for i, _ in c.commesse for a in c.anni],
    '/api/dd/<int:commessa_id>/<anno_scolastico>': lambda c: [
        f'/api/dd/{i}/{a}' for i, _ in c.commesse for a in c.anni],
    '/api/recuperi/<int:commessa_id>/<anno_scolastico>': lambda c: [
        f'/api/recuperi/{i}/{a}' for i, _ in c.commesse for a in c.anni],
    # --- export ---
    '/api/export/excel/<int:anno>/<int:mese>': lambda c: _export_mensile('excel', c),
    '/api/export/municipale/<int:anno>/<int:mese>': lambda c: _export_mensile('municipale', c),
    '/api/export/dipartimentale/<int:anno>/<int:mese>': lambda c: _export_mensile('dipartimentale', c, False),
    '/api/export/word/<int:anno>/<int:mese>': lambda c: _export_mensile('word', c),
    '/api/export/annuale/<anno_scolastico>': lambda c: [
        _url(f'/api/export/annuale/{a}', commessa=f) for a in c.anni for f in c.filtri]
    + [_url(f'/api/export/annuale/{a}', privacy='true') for a in c.anni[-1:]],
}

ROTTE_ROMA = frozenset(FOTOGRAFIE) | ROTTE_ROMA_SCRITTURA


def regole_applicazione(flask_app):
    """{regola: metodi} di tutte le rotte dell'applicazione (HEAD e OPTIONS esclusi)."""
    regole = {}
    for r in flask_app.url_map.iter_rules():
        regole.setdefault(r.rule, set()).update(r.methods - {'HEAD', 'OPTIONS'})
    return regole


def controlla_inventario(regole):
    """Problemi dell'inventario per le regole {regola: metodi} dell'applicazione:
    rotte non classificate o in piu' classi, classificate ma inesistenti, GET di
    Roma senza fotografia, rotte di Napoli fuori dai loro prefissi (e viceversa),
    esclusioni senza motivo. Lista vuota = tutto a posto."""
    classi = {'ROTTE_ROMA': ROTTE_ROMA, 'ROTTE_NAPOLI': ROTTE_NAPOLI, 'ESCLUSE': frozenset(ESCLUSE)}
    problemi = []
    for regola in sorted(regole):
        dove = [nome for nome, insieme in classi.items() if regola in insieme]
        if not dove:
            problemi.append(f'{regola}: rotta non classificata (ROTTE_ROMA, ROTTE_NAPOLI o ESCLUSE)')
        elif len(dove) > 1:
            problemi.append(f"{regola}: in piu' classi ({', '.join(dove)})")
        if regola in ROTTE_ROMA_SCRITTURA and 'GET' in regole[regola]:
            problemi.append(f'{regola}: GET di Roma senza fotografia (aggiungerla a FOTOGRAFIE)')
        napoli = regola.startswith(PREFISSI_NAPOLI)
        if napoli and regola in ROTTE_ROMA:
            problemi.append(f'{regola}: rotta di Napoli classificata come Roma')
        if regola in ROTTE_NAPOLI and not napoli:
            problemi.append(f'{regola}: rotta di Napoli fuori da {" / ".join(PREFISSI_NAPOLI)}')
    for nome, insieme in classi.items():
        for regola in sorted(insieme - set(regole)):
            problemi.append(f"{regola}: in {nome} ma non esiste piu' nell'applicazione")
    problemi += [f'{r}: esclusa senza motivo' for r, motivo in sorted(ESCLUSE.items()) if not motivo.strip()]
    return problemi


def indirizzi(contesto):
    """[(regola, url)] da fotografare, in un ordine fisso."""
    return [(regola, u) for regola in sorted(FOTOGRAFIE) for u in FOTOGRAFIE[regola](contesto)]


# ==================== OROLOGIO FERMO ====================

class _MetaOra(type):
    def __instancecheck__(cls, obj):
        return isinstance(obj, _dt.datetime)


class _MetaOggi(type):
    def __instancecheck__(cls, obj):
        return isinstance(obj, _dt.date)


@contextlib.contextmanager
def orologio_fermo(quando):
    """Fa vedere al programma l'ora `quando` (datetime senza fuso).

    Sostituisce i nomi `datetime` e `date` nei moduli del programma (quelli nella
    cartella di config.py) e il giorno di config.anno_scolastico_corrente, che
    importa `date` al momento della chiamata. Le classi sostitutive sono
    sottoclassi di quelle vere e rispondono True a isinstance per gli oggetti veri.
    Non si annida: dentro un orologio fermo se ne apre un altro solo dopo averlo chiuso."""
    vero_date = _dt.date

    class Ora(_dt.datetime, metaclass=_MetaOra):
        @classmethod
        def now(cls, tz=None):
            return quando if tz is None else quando.replace(tzinfo=tz)

        @classmethod
        def today(cls):
            return quando

        @classmethod
        def utcnow(cls):
            return quando

    class Oggi(_dt.date, metaclass=_MetaOggi):
        @classmethod
        def today(cls):
            return quando.date()

    config = sys.modules.get('config')
    cartella = os.path.dirname(os.path.abspath(config.__file__)) if config else CARTELLA_PROGETTO
    salvati = []
    for modulo in list(sys.modules.values()):
        f = getattr(modulo, '__file__', None)
        if not f or os.path.dirname(os.path.abspath(f)) != cartella:
            continue
        for nome, vero, finto in (('datetime', _dt.datetime, Ora), ('date', vero_date, Oggi)):
            if getattr(modulo, nome, None) is vero:
                salvati.append((modulo, nome, vero))
                setattr(modulo, nome, finto)
    originale = getattr(config, 'anno_scolastico_corrente', None) if config else None
    if originale is not None:
        def anno_scolastico_corrente(*args, **kwargs):
            _dt.date = Oggi          # solo per la durata della chiamata
            try:
                return originale(*args, **kwargs)
            finally:
                _dt.date = vero_date
        config.anno_scolastico_corrente = anno_scolastico_corrente
    try:
        yield
    finally:
        for modulo, nome, vero in salvati:
            setattr(modulo, nome, vero)
        if originale is not None:
            config.anno_scolastico_corrente = originale


# ==================== NORMALIZZAZIONE ====================

_DATAORA = re.compile(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?')
_DATAORA_IT = re.compile(r'\d{2}/\d{2}/\d{4},?\s+(ore\s+)?\d{2}[:.]\d{2}([:.]\d{2})?')
_UUID = re.compile(r'[0-9a-f]{32}')


class Normalizzatore:
    """Toglie dalle risposte cio' che non dipende dai dati: le date-ora del momento
    (scritte da Python o da SQLite), i nomi casuali dei file caricati, la versione
    del programma e le chiavi che dipendono dall'ambiente (CHIAVI_AMBIENTE)."""

    def __init__(self, versione):
        self._versione = re.compile(r'(?<![\d.])' + re.escape(versione) + r'(?![\d.])') if versione else None

    def testo(self, s):
        s = _DATAORA.sub('<dataora>', s)
        s = _DATAORA_IT.sub('<dataora>', s)
        s = _UUID.sub('<uuid>', s)
        if self._versione:
            s = self._versione.sub('<versione>', s)
        return s

    def valore(self, v, via_chiavi=frozenset()):
        if isinstance(v, bool) or v is None:
            return v
        if isinstance(v, float):
            if v != v:
                return 'NaN'         # NaN != NaN: due fotografie uguali risulterebbero diverse
            v = round(v, 6)
            return int(v) if v.is_integer() else v
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            return self.testo(v)
        if isinstance(v, dict):
            return {str(k): ('<ambiente>' if k in CHIAVI_AMBIENTE else self.valore(x))
                    for k, x in sorted(v.items(), key=lambda kv: str(kv[0])) if k not in via_chiavi}
        if isinstance(v, (list, tuple)):
            return [self.valore(x) for x in v]
        if isinstance(v, _dt.datetime):
            return v.date().isoformat() if v.time() == _dt.time(0) else '<dataora>'
        if isinstance(v, (_dt.date, _dt.time)):
            return v.isoformat()
        return self.testo(str(v))


_VUOTI = frozenset({'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta',
                    'source', 'track', 'wbr'})
_INTESTAZIONI = ('h1', 'h2', 'h3', 'h4')


class _LettorePagina(html.parser.HTMLParser):
    """Dal contenuto della pagina (<main>, senza il menu laterale): id degli
    elementi, intestazioni e testo; dalla pagina intera il titolo e APP_CONFIG."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.titolo, self.id, self.intestazioni, self.testo, self.app_config = '', [], [], [], None
        self._in_main = 0
        self._tag = []
        self._intestazione = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'main':
            self._in_main += 1
        if self._in_main and a.get('id'):
            self.id.append(f"{tag}#{a['id']}")
        if tag in _INTESTAZIONI and self._in_main and self._intestazione is None:
            self._intestazione = []
        if tag not in _VUOTI:
            self._tag.append(tag)

    def handle_endtag(self, tag):
        if tag == 'main' and self._in_main:
            self._in_main -= 1
        if tag in _INTESTAZIONI and self._intestazione is not None:
            self.intestazioni.append(' '.join(' '.join(self._intestazione).split()))
            self._intestazione = None
        if tag in self._tag:
            while self._tag.pop() != tag:
                pass

    def handle_data(self, data):
        corrente = self._tag[-1] if self._tag else ''
        if corrente == 'title':
            self.titolo += data
        elif corrente == 'script':
            m = re.search(r'window\.APP_CONFIG\s*=\s*(\{.*?\});', data, re.S)
            if m:
                self.app_config = json.loads(m.group(1))
        elif self._in_main and corrente != 'style':
            t = ' '.join(data.split())
            if t:
                self.testo.append(t)
                if self._intestazione is not None:
                    self._intestazione.append(t)


def _leggi_pagina(testo, norm):
    p = _LettorePagina()
    p.feed(testo)
    contenuto = norm.testo(' '.join(p.testo))
    return {
        'titolo': norm.testo(' '.join(p.titolo.split())),
        'id': p.id,
        'intestazioni': [norm.testo(t) for t in p.intestazioni],
        'impronta_contenuto': hashlib.sha256(contenuto.encode('utf-8')).hexdigest()[:16],
        'app_config': norm.valore(p.app_config),
    }


def _leggi_xlsx(dati, norm):
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(dati), data_only=False)
    fogli = []
    for ws in wb.worksheets:
        righe = []
        for riga in ws.iter_rows(values_only=True):
            valori = [norm.valore(v) for v in riga]
            while valori and valori[-1] in (None, ''):
                valori.pop()
            righe.append(valori)
        while righe and not righe[-1]:
            righe.pop()
        fogli.append({'nome': ws.title, 'celle': righe,
                      'unite': sorted(str(r) for r in ws.merged_cells.ranges)})
    return fogli


def _leggi_docx(dati, norm):
    import docx
    d = docx.Document(io.BytesIO(dati))
    sezioni = [[norm.testo(p.text) for p in s.header.paragraphs + s.footer.paragraphs if p.text.strip()]
               for s in d.sections]
    return {
        'paragrafi': [norm.testo(p.text) for p in d.paragraphs if p.text.strip()],
        'tabelle': [[[norm.testo(cella.text) for cella in riga.cells] for riga in t.rows] for t in d.tables],
        'intestazioni_e_piedi': sezioni,
    }


def leggi_risposta(r, norm, via_chiavi=frozenset()):
    """Una risposta del client di prova ridotta a stato, tipo, nome del file e contenuto."""
    tipo = (r.headers.get('Content-Type') or '').split(';')[0].strip()
    esito = {'stato': r.status_code, 'tipo': tipo}
    disp = r.headers.get('Content-Disposition') or ''
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', disp)
    if m:
        esito['file'] = norm.testo(m.group(1))
    if r.status_code in (301, 302, 303, 307, 308):
        esito['verso'] = norm.testo(re.sub(r'^https?://[^/]+', '', r.headers.get('Location') or ''))
        return esito
    dati = r.get_data()
    if tipo == 'application/json':
        esito['contenuto'] = norm.valore(json.loads(dati.decode('utf-8')), via_chiavi)
    elif tipo == 'text/html':
        esito['contenuto'] = _leggi_pagina(dati.decode('utf-8'), norm)
    elif tipo.endswith('spreadsheetml.sheet'):
        esito['contenuto'] = _leggi_xlsx(dati, norm)
    elif tipo.endswith('wordprocessingml.document'):
        esito['contenuto'] = _leggi_docx(dati, norm)
    elif tipo.startswith('text/'):
        esito['contenuto'] = [norm.testo(x) for x in dati.decode('utf-8-sig').splitlines()]
    else:
        esito['contenuto'] = {'byte': len(dati), 'sha256': hashlib.sha256(dati).hexdigest()}
    return esito


def leggi_versione(cartella_codice):
    try:
        with open(os.path.join(cartella_codice, 'VERSION'), encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return ''


def fotografa(client, contesto, versione=''):
    """{'versione_fotografia', 'rotte': {regola: {url: risposta normalizzata}}}."""
    norm = Normalizzatore(versione)
    rotte = {}
    for regola, u in indirizzi(contesto):
        via = CHIAVI_NAPOLI_TRASLOCO if regola == '/api/migrazione/esporta' else frozenset()
        rotte.setdefault(regola, {})[u] = leggi_risposta(client.get(u), norm, via)
    return {'versione_fotografia': VERSIONE_FOTOGRAFIA, 'rotte': rotte}


def fotografa_sintetico(client, percorso_db, sintetico, versione=''):
    """Fotografia dell'archivio inventato (gia' costruito con
    sintetico.costruisci_archivio) con l'orologio e i mesi di export dell'archivio:
    la stessa procedura per il file golden e per i test."""
    with orologio_fermo(sintetico.OGGI_FOTOGRAFIA):
        foto = fotografa(client, Contesto(percorso_db, sintetico.MESI_EXPORT), versione)
    foto['oggi'] = sintetico.OGGI_FOTOGRAFIA.isoformat()
    return foto


UTENTE_FOTOGRAFIA = 'fotografia'


def client_fotografia(flask_app, database):
    """Client di prova con la sessione autenticata della fotografia. Se il database
    non ha ancora l'accesso configurato, lo configura (password casuale)."""
    if not database.auth_is_configured():
        from werkzeug.security import generate_password_hash
        database.auth_create_user(UTENTE_FOTOGRAFIA, generate_password_hash(os.urandom(16).hex()))
    client = flask_app.test_client()
    with client.session_transaction() as s:
        s['authenticated'] = True
        s['auth_method'] = UTENTE_FOTOGRAFIA
    return client


def differenze(prima, dopo):
    """Confronta due fotografie: {'identiche': n, 'diverse': {regola: n_url},
    'solo_prima': [regole], 'solo_dopo': [regole]}. Non riporta contenuti."""
    rp, rd = prima.get('rotte', {}), dopo.get('rotte', {})
    esito = {'identiche': 0, 'diverse': {}, 'solo_prima': sorted(set(rp) - set(rd)),
             'solo_dopo': sorted(set(rd) - set(rp))}
    for regola in sorted(set(rp) & set(rd)):
        a, b = rp[regola], rd[regola]
        n = sum(1 for u in set(a) | set(b) if a.get(u) != b.get(u))
        if n:
            esito['diverse'][regola] = n
        else:
            esito['identiche'] += 1
    return esito


def _prima_differenza(a, b, dove=''):
    """Percorso e valori della prima differenza fra due valori JSON."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            if a.get(k, '<manca>') != b.get(k, '<manca>'):
                return _prima_differenza(a.get(k, '<manca>'), b.get(k, '<manca>'), f'{dove}.{k}')
    if isinstance(a, list) and isinstance(b, list):
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return _prima_differenza(x, y, f'{dove}[{i}]')
        if len(a) != len(b):
            return f'{dove}: {len(a)} elementi invece di {len(b)}'
    return f'{dove}: atteso {_compatto(a)[:200]}, ottenuto {_compatto(b)[:200]}'


def descrivi_differenze(attesa, ottenuta, massimo=8):
    """Messaggio per i test: rotte diverse e, per i primi indirizzi, la prima
    differenza con i valori. Contiene dati: SOLO per gli archivi inventati."""
    d = differenze(attesa, ottenuta)
    righe = [f"rotte identiche {d['identiche']}, diverse {len(d['diverse'])}: "
             + ', '.join(f'{r} ({n})' for r, n in d['diverse'].items())]
    for chiave in ('solo_prima', 'solo_dopo'):
        if d[chiave]:
            righe.append(f'{chiave}: ' + ', '.join(d[chiave]))
    ra, ro = attesa.get('rotte', {}), ottenuta.get('rotte', {})
    for regola in d['diverse']:
        for u in sorted(set(ra[regola]) | set(ro[regola])):
            if len(righe) > massimo:
                return '\n'.join(righe)
            x, y = ra[regola].get(u, '<manca>'), ro[regola].get(u, '<manca>')
            if x != y:
                righe.append(f'{u}{_prima_differenza(x, y)}')
    return '\n'.join(righe)


def _compatto(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def scrivi(foto, percorso):
    """Scrive la fotografia con una riga per indirizzo: il file resta leggibile e
    un cambiamento si vede sulla riga del suo indirizzo."""
    os.makedirs(os.path.dirname(os.path.abspath(percorso)), exist_ok=True)
    rotte = foto.get('rotte', {})
    righe = ['{']
    for k in sorted(k for k in foto if k != 'rotte'):
        righe.append(f' {_compatto(k)}: {_compatto(foto[k])},')
    righe.append(' "rotte": {')
    for i, regola in enumerate(sorted(rotte)):
        righe.append(f'  {_compatto(regola)}: {{')
        urls = sorted(rotte[regola])
        for j, u in enumerate(urls):
            righe.append(f'   {_compatto(u)}: {_compatto(rotte[regola][u])}' + (',' if j < len(urls) - 1 else ''))
        righe.append('  }' + (',' if i < len(rotte) - 1 else ''))
    righe.append(' }')
    righe.append('}')
    with open(percorso, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(righe) + '\n')


def leggi(percorso):
    with open(percorso, encoding='utf-8') as f:
        return json.load(f)


# ==================== USO A RIGA DI COMANDO ====================

def _prepara_programma(codice, percorso_db, lavoro):
    """Importa la versione in `codice` con database, backup, file e log in
    cartelle di lavoro (niente viene scritto nella cartella del programma) e senza
    messaggi a schermo, che potrebbero contenere dati."""
    import logging
    sys.dont_write_bytecode = True       # niente __pycache__ nella cartella della versione
    sys.path.insert(0, codice)
    os.environ.setdefault('FLASK_SECRET_KEY', os.urandom(32).hex())
    import config
    config.DATABASE_PATH = percorso_db
    config.BACKUP_ON_STARTUP = False
    for nome in ('BACKUP_FOLDER', 'UPLOAD_FOLDER', 'EXPORT_FOLDER', 'LOG_FOLDER'):
        setattr(config, nome, os.path.join(lavoro, nome.split('_')[0].lower()))
    import database
    for h in list(logging.getLogger('oepac').handlers):
        if type(h) is logging.StreamHandler:
            logging.getLogger('oepac').removeHandler(h)
    database.DATABASE_PATH = percorso_db
    # init_db una volta sola, all'import di app, come all'avvio del programma e
    # come nei test: ogni esecuzione fa avanzare i contatori degli id
    import app as app_mod
    return client_fotografia(app_mod.app, database)


def _carica_da_file(nome, percorso):
    spec = importlib.util.spec_from_file_location(nome, percorso)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def main(argv=None):
    p = argparse.ArgumentParser(description='Fotografia delle uscite di Roma (scrive un file JSON, non stampa dati).')
    sorgente = p.add_mutually_exclusive_group(required=True)
    sorgente.add_argument('--sintetico', action='store_true', help="archivio Roma inventato (tests/roma_sintetico.py)")
    sorgente.add_argument('--db', help='COPIA del database da fotografare (viene aggiornata da init_db)')
    p.add_argument('--uscita', required=True, help='file JSON della fotografia')
    p.add_argument('--codice', default=CARTELLA_PROGETTO, help='cartella della versione da fotografare')
    p.add_argument('--oggi', help="data dell'orologio fermo (AAAA-MM-GG; predefinita: oggi)")
    a = p.parse_args(argv)
    codice = os.path.abspath(a.codice)
    with tempfile.TemporaryDirectory(prefix='fotografia_roma_') as lavoro:
        if a.sintetico:
            sintetico = _carica_da_file('roma_sintetico', os.path.join(CARTELLA_PROGETTO, 'tests', 'roma_sintetico.py'))
            percorso_db = os.path.join(lavoro, 'gestionale.db')
            client = _prepara_programma(codice, percorso_db, lavoro)
            sintetico.costruisci_archivio(client, orologio_fermo)
            foto = fotografa_sintetico(client, percorso_db, sintetico, leggi_versione(codice))
        else:
            percorso_db = os.path.abspath(a.db)
            client = _prepara_programma(codice, percorso_db, lavoro)
            quando = _dt.datetime.combine(_dt.date.fromisoformat(a.oggi) if a.oggi else _dt.date.today(),
                                          _dt.time(10, 0))
            with orologio_fermo(quando):
                foto = fotografa(client, Contesto(percorso_db), leggi_versione(codice))
            foto['oggi'] = quando.isoformat()
        scrivi(foto, a.uscita)
    return 0


if __name__ == '__main__':
    sys.exit(main())

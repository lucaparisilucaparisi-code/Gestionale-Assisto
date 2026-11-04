"""VR6: controllo statico della separazione fra Napoli e Roma.

(a) I moduli di Napoli (napoli_*.py, routes_napoli.py, import_napoli.py,
    export_napoli.py, config_napoli.py) nelle stringhe SQL nominano solo tabelle
    napoli_* (piu' le tabelle di sistema di SQLite in sola lettura); non usano
    tariffe e calcoli di Roma (config.TARIFFA_ORARIA, IVA_PERCENTUALE,
    calcola_fatturazione...); di database.py e routes_export.py usano solo le
    funzioni comuni elencate in DATABASE_AMMESSI ed EXPORT_AMMESSI, che non
    leggono ne' scrivono tabelle di Roma (log_audit scrive il registro condiviso).
(b) Nei file di Roma (moduli Python, script di avvio, template, JS e CSS) la
    parola "napoli" compare solo nei punti ammessi (PROGETTO §4.5), con il numero
    di occorrenze fissato in OCCORRENZE_AMMESSE: ogni aggancio nuovo va dichiarato qui.

Ogni regola ha anche la prova che il controllo se ne accorge (test_controllo_*).
"""
import ast
import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODULI_NAPOLI = ('napoli_*.py', 'routes_napoli.py', 'import_napoli.py', 'export_napoli.py', 'config_napoli.py')
FILE_NAPOLI_UI = ('templates/napoli_*.html', 'templates/_napoli_*.html', 'static/js/napoli*.js',
                  'static/css/napoli*.css')
FILE_ROMA = ('*.py', '*.bat', '*.sh', 'templates/*.html', 'static/*.js', 'static/*.json', 'static/js/*.js',
             'static/css/*.css')

PREFISSO = 'napoli_'
TABELLE_SISTEMA = frozenset({'sqlite_master', 'sqlite_schema'})   # sola lettura (esistenza di tabelle)
CONFIG_VIETATI = frozenset({'TARIFFA_ORARIA', 'IVA_PERCENTUALE', 'TASSO_ASSENZA', 'COEFFICIENTE_GIORNALIERO',
                            'SETTIMANE_ANNO_SCOLASTICO', 'calcola_fatturazione'})
DATABASE_AMMESSI = frozenset({'get_db_context', 'create_backup', 'log_audit',
                              '_norm_ora', '_overlap', '_periodi_sovrapposti', '_turno_valido_in_data'})
EXPORT_AMMESSI = frozenset({'get_excel_brand_styles', '_fmt_euro_it'})
MODULI_CONTROLLATI = {'config': ('vietati', CONFIG_VIETATI), 'database': ('ammessi', DATABASE_AMMESSI),
                      'routes_export': ('ammessi', EXPORT_AMMESSI)}

# Occorrenze ammesse della parola "napoli" (maiuscole o minuscole) nei file di Roma.
# Vuoto finche' la sezione non c'e'; i passi successivi aggiungono i punti del
# PROGETTO §4.5 (database.py, app.py, templates/base.html, static/js/app.js,
# routes_migrazione.py, templates/commesse.html) con il loro numero esatto.
OCCORRENZE_AMMESSE = {}


def _file(modelli):
    trovati = set()
    for m in modelli:
        trovati.update(os.path.relpath(p, ROOT).replace(os.sep, '/') for p in glob.glob(os.path.join(ROOT, m)))
    return trovati


def moduli_napoli():
    return sorted(_file(MODULI_NAPOLI))


def file_roma():
    return sorted(_file(FILE_ROMA) - _file(MODULI_NAPOLI) - _file(FILE_NAPOLI_UI))


# ==================== (a) i moduli di Napoli ====================

# Una stringa e' SQL se ha una parola chiave in maiuscolo (come in tutto il programma)
# o se comincia con una parola chiave, anche in minuscolo.
_PAROLA_SQL = re.compile(r'\b(SELECT|INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP|WITH|FROM|JOIN|INTO)\b')
_INIZIO_SQL = re.compile(r'^\s*(SELECT|INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP|WITH|FROM|JOIN|LEFT|INNER|'
                         r'CROSS|WHERE)\b', re.I)
_TABELLA = re.compile(
    r'\b(?:INTO|UPDATE|TABLE(?:\s+IF\s+(?:NOT\s+)?EXISTS)?|REFERENCES|JOIN)\s+([^\s(),;]+)'
    r'|\bINDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?\S+\s+ON\s+([^\s(),;]+)'
    r'|\bTRIGGER\s+(?:IF\s+NOT\s+EXISTS\s+)?\S+\s+.*?\bON\s+([^\s(),;]+)', re.I | re.S)
_FROM = re.compile(r'\bFROM\s+(.+?)(?=\b(?:WHERE|GROUP|ORDER|LIMIT|HAVING|WINDOW|UNION|EXCEPT|INTERSECT|'
                   r'JOIN|LEFT|RIGHT|INNER|OUTER|CROSS|NATURAL|ON|USING|RETURNING)\b|[);]|$)', re.I | re.S)
_CTE = re.compile(r'(?:\bWITH(?:\s+RECURSIVE)?|,)\s+([A-Za-z_]\w*)\s+AS\s*\(', re.I)


def _testo_stringa(nodo):
    """Testo di una stringa o di una f-string ('{?}' al posto delle parti calcolate)."""
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return nodo.value
    if isinstance(nodo, ast.JoinedStr):
        return ''.join(v.value if isinstance(v, ast.Constant) else '{?}' for v in nodo.values)
    return None


def _docstring(nodo):
    corpo = getattr(nodo, 'body', None)
    if corpo and isinstance(corpo, list) and isinstance(corpo[0], ast.Expr):
        return corpo[0].value
    return None


def tabelle_sql(testo):
    """Nomi delle tabelle in una stringa SQL (vuoto se la stringa non e' SQL)."""
    if not (_PAROLA_SQL.search(testo) or _INIZIO_SQL.match(testo)):
        return []
    senza_upsert = re.sub(r'\bDO\s+UPDATE\b', 'DO_UPDATE', testo, flags=re.I)
    cte = {m.lower() for m in _CTE.findall(senza_upsert)}
    nomi = [n for gruppo in _TABELLA.findall(senza_upsert) for n in gruppo if n]
    for elenco in _FROM.findall(senza_upsert):
        for parte in elenco.split(','):
            parte = parte.strip()
            if parte and not parte.startswith('('):
                nomi.append(parte.split()[0])
    nomi = [n.strip('"`[]').split('.')[-1] for n in nomi]
    return [n for n in nomi if n.lower() not in cte and not n.lower().startswith('pragma_')]


def problemi_modulo_napoli(sorgente, nome='modulo'):
    """Problemi di un modulo di Napoli: tabelle non napoli_* nelle stringhe SQL,
    tariffe e calcoli di Roma, funzioni di database.py e routes_export.py non ammesse."""
    albero = ast.parse(sorgente)
    docstring = {id(d) for n in ast.walk(albero) for d in [_docstring(n)] if d is not None}
    problemi = []
    alias = {}   # nome locale -> modulo di Roma controllato
    for n in ast.walk(albero):
        if isinstance(n, (ast.Constant, ast.JoinedStr)) and id(n) not in docstring:
            testo = _testo_stringa(n)
            for t in tabelle_sql(testo or ''):
                if '{?}' in t and not t.startswith(PREFISSO):
                    problemi.append(f'{nome}:{n.lineno}: nome di tabella calcolato, non verificabile: {t}')
                elif not t.startswith(PREFISSO) and t not in TABELLE_SISTEMA:
                    problemi.append(f'{nome}:{n.lineno}: tabella di Roma nello SQL: {t}')
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name in MODULI_CONTROLLATI:
                    alias[a.asname or a.name] = a.name
        elif isinstance(n, ast.ImportFrom) and n.module in MODULI_CONTROLLATI:
            for a in n.names:
                problemi += _uso(n.module, a.name, f'{nome}:{n.lineno}')
    for n in ast.walk(albero):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in alias:
            problemi += _uso(alias[n.value.id], n.attr, f'{nome}:{n.lineno}')
    return problemi


def _uso(modulo, attributo, dove):
    tipo, elenco = MODULI_CONTROLLATI[modulo]
    vietato = attributo in elenco if tipo == 'vietati' else attributo not in elenco
    return [f'{dove}: {modulo}.{attributo} non e\' ammesso nei moduli di Napoli'] if vietato else []


def test_moduli_napoli_usano_solo_tabelle_napoli():
    problemi = []
    for rel in moduli_napoli():
        with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
            problemi += problemi_modulo_napoli(f.read(), rel)
    assert problemi == [], '\n'.join(problemi)


def test_controllo_trova_le_tabelle_di_roma():
    sorgente = '''
import database as db
import config


def salva(conn, x):
    """Docstring che nomina utenti e FROM rendicontazione: ignorata."""
    conn.execute("INSERT INTO napoli_alunni (cognome) VALUES (?)", (x,))
    conn.execute("SELECT a.id FROM napoli_alunni a JOIN napoli_scuole s ON s.id = a.scuola_id")
    conn.execute("INSERT INTO napoli_regole (chiave) VALUES (?) ON CONFLICT(chiave) DO UPDATE SET chiave = 1")
    conn.execute("WITH ultimi AS (SELECT * FROM napoli_presenze) SELECT * FROM ultimi")
    conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'napoli_%'")
    conn.execute("INSERT INTO utenti (nome) VALUES (?)", (x,))
    conn.execute("select * from napoli_coppie, rendicontazione")
    conn.execute(f"DELETE FROM {x} WHERE id = 1")
    conn.execute(f"DELETE FROM napoli_{x} WHERE id = 1")
    conn.execute("UPDATE commesse SET nome = ?", (x,))
    with db.get_db_context():
        db.log_audit('napoli_import', 'napoli_lotto')
        db.update_rendicontazione(1, 2025, 10, ore_lavorate=1)
    return config.calcola_fatturazione(x), config.MESI_NOME
'''
    problemi = problemi_modulo_napoli(sorgente, 'napoli_prova.py')
    testo = '\n'.join(problemi)
    for atteso in ('tabella di Roma nello SQL: utenti', 'tabella di Roma nello SQL: rendicontazione',
                   'nome di tabella calcolato, non verificabile: {?}', 'tabella di Roma nello SQL: commesse',
                   'database.update_rendicontazione', 'config.calcola_fatturazione'):
        assert atteso in testo, testo
    assert len(problemi) == 6, testo


def test_controllo_trova_gli_import_non_ammessi():
    sorgente = 'from database import get_db_context, get_rendicontazione_completa\nfrom config import IVA_PERCENTUALE\n'
    problemi = problemi_modulo_napoli(sorgente, 'routes_napoli.py')
    assert len(problemi) == 2 and 'get_rendicontazione_completa' in problemi[0] and 'IVA_PERCENTUALE' in problemi[1]


# ==================== (b) i file di Roma ====================

def occorrenze_napoli(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8', errors='replace') as f:
        return len(re.findall('napoli', f.read(), re.I))


def test_roma_nomina_napoli_solo_nei_punti_ammessi():
    trovate = {rel: n for rel in file_roma() for n in [occorrenze_napoli(rel)] if n}
    assert trovate == OCCORRENZE_AMMESSE, (
        f'occorrenze di "napoli" nei file di Roma: {trovate}; ammesse: {OCCORRENZE_AMMESSE}. '
        'Un aggancio nuovo va dichiarato in OCCORRENZE_AMMESSE (PROGETTO §4.5).')


def test_elenco_dei_file_di_roma():
    """Il controllo (b) guarda davvero i file di Roma e lascia fuori quelli di Napoli."""
    roma = file_roma()
    for atteso in ('app.py', 'database.py', 'config.py', 'routes_export.py', 'templates/base.html',
                   'static/js/app.js', 'static/css/style.css'):
        assert atteso in roma
    assert not any(os.path.basename(r).startswith(('napoli', '_napoli')) or r.endswith('_napoli.py') for r in roma)

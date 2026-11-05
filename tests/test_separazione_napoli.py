"""VR6: controllo statico della separazione fra Napoli e Roma.

(a) I moduli di Napoli (napoli_*.py, routes_napoli.py, import_napoli.py,
    export_napoli.py, config_napoli.py) nelle stringhe SQL nominano solo tabelle
    napoli_* (piu' le tabelle di sistema di SQLite in sola lettura); non usano
    tariffe e calcoli di Roma (config.TARIFFA_ORARIA, IVA_PERCENTUALE,
    calcola_fatturazione...); di database.py e routes_export.py usano solo le
    funzioni comuni elencate in DATABASE_AMMESSI ed EXPORT_AMMESSI, che non
    leggono ne' scrivono tabelle di Roma (log_audit scrive il registro condiviso);
    non importano altri moduli di Roma (app, routes_*, import_*...).
    Lo SQL si legge anche quando e' costruito (f-string, +, %, .format, join): le
    parti calcolate diventano {?}, e un nome di tabella calcolato che non comincia
    per napoli_ e' un problema. Non sono ammessi gli import con * dai moduli di Roma
    ne' gli import o getattr con nomi calcolati, che non si potrebbero verificare.
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
# Contatori AUTOINCREMENT: ammessi solo per righe di tabelle napoli_* (name = 'napoli_...'),
# come nella ricostruzione di napoli_coordinamento della migrazione 3.
CONTATORI = 'sqlite_sequence'
_SOLO_CONTATORI_NAPOLI = re.compile(r"\bname\s*=\s*'napoli_\w+'", re.I)
CONFIG_VIETATI = frozenset({'TARIFFA_ORARIA', 'IVA_PERCENTUALE', 'TASSO_ASSENZA', 'COEFFICIENTE_GIORNALIERO',
                            'SETTIMANE_ANNO_SCOLASTICO', 'calcola_fatturazione'})
DATABASE_AMMESSI = frozenset({'get_db_context', 'create_backup', 'log_audit',
                              '_norm_ora', '_overlap', '_periodi_sovrapposti', '_turno_valido_in_data'})
EXPORT_AMMESSI = frozenset({'get_excel_brand_styles', '_fmt_euro_it'})
VALIDATORS_AMMESSI = frozenset({'validate_string', 'validate_number', 'validate_integer'})
# I soli moduli di Roma che Napoli puo' importare, con cio' che puo' usarne; ogni
# altro modulo (o pacchetto) della cartella del programma che non e' di Napoli e'
# vietato (moduli_roma).
MODULI_CONTROLLATI = {'config': ('vietati', CONFIG_VIETATI), 'database': ('ammessi', DATABASE_AMMESSI),
                      'routes_export': ('ammessi', EXPORT_AMMESSI), 'validators': ('ammessi', VALIDATORS_AMMESSI)}

# Occorrenze ammesse della parola "napoli" (maiuscole o minuscole) nei file di Roma.
# Ogni passo aggiunge i suoi punti del PROGETTO §4.5 (database.py, app.py,
# templates/base.html, static/js/app.js, routes_migrazione.py, templates/commesse.html)
# con il loro numero esatto.
OCCORRENZE_AMMESSE = {
    'database.py': 11,           # import napoli_schema e le migrazioni 2, 3, 4 e 5 in MIGRAZIONI (con i commenti)
    'app.py': 6,                 # import e registrazione del blueprint routes_napoli (con il commento)
    'templates/base.html': 20,   # voce "Napoli" del menu e della ricerca rapida (Alt+8), ogni elemento con
                                 # data-sezione="napoli", e il commento
    'static/js/app.js': 4,       # Alt+8 -> /napoli (navMap e guida delle scorciatoie) e annullaPagina (commenti)
}


def _file(modelli):
    trovati = set()
    for m in modelli:
        trovati.update(os.path.relpath(p, ROOT).replace(os.sep, '/') for p in glob.glob(os.path.join(ROOT, m)))
    return trovati


def moduli_napoli():
    return sorted(_file(MODULI_NAPOLI))


def moduli_roma():
    """Nomi importabili dei moduli e pacchetti di Roma nella cartella del programma."""
    nomi = {os.path.splitext(f)[0] for f in _file(('*.py',)) - _file(MODULI_NAPOLI)}
    nomi |= {d for d in os.listdir(ROOT) if os.path.isfile(os.path.join(ROOT, d, '__init__.py'))
             or (os.path.isdir(os.path.join(ROOT, d)) and glob.glob(os.path.join(ROOT, d, '*.py')))}
    return frozenset(nomi)


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


_SEGNAPOSTO_PERCENTO = re.compile(r'%(?:\([^)]*\))?[-#0 +]*\d*(?:\.\d+)?[sdifrx]')
_SEGNAPOSTO_FORMAT = re.compile(r'\{[^{}]*\}')


def _testo_stringa(nodo):
    """Testo di una stringa, anche costruita: f-string, concatenazione con +, % e
    .format() su una stringa, separatore.join([...]); le parti calcolate diventano
    '{?}'. None se l'espressione non e' una stringa."""
    if isinstance(nodo, ast.Constant):
        return nodo.value if isinstance(nodo.value, str) else None
    if isinstance(nodo, ast.JoinedStr):
        return ''.join(v.value if isinstance(v, ast.Constant) else '{?}' for v in nodo.values)
    if isinstance(nodo, ast.BinOp) and isinstance(nodo.op, ast.Add):
        a, b = _testo_stringa(nodo.left), _testo_stringa(nodo.right)
        if a is None and b is None:
            return None
        return ('{?}' if a is None else a) + ('{?}' if b is None else b)
    if isinstance(nodo, ast.BinOp) and isinstance(nodo.op, ast.Mod):
        a = _testo_stringa(nodo.left)
        return None if a is None else _SEGNAPOSTO_PERCENTO.sub('{?}', a)
    if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute):
        base = _testo_stringa(nodo.func.value)
        if base is None:
            return None
        if nodo.func.attr == 'format':
            return _SEGNAPOSTO_FORMAT.sub('{?}', base)
        if nodo.func.attr == 'join' and nodo.args and isinstance(nodo.args[0], (ast.List, ast.Tuple)):
            parti = (_testo_stringa(e) for e in nodo.args[0].elts)
            return base.join('{?}' if p is None else p for p in parti)
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


def _problemi_sql(testo, dove):
    problemi = []
    for t in tabelle_sql(testo):
        if '{?}' in t and not t.startswith(PREFISSO):
            problemi.append(f'{dove}: nome di tabella calcolato, non verificabile: {t}')
        elif t == CONTATORI:
            if not _SOLO_CONTATORI_NAPOLI.search(testo):
                problemi.append(f'{dove}: contatori di tabelle non napoli_* ({t})')
        elif not t.startswith(PREFISSO) and t not in TABELLE_SISTEMA:
            problemi.append(f'{dove}: tabella di Roma nello SQL: {t}')
    return problemi


def _import(modulo, dove, roma):
    """Problema di un import (None se ammesso): moduli di Roma non controllati."""
    radice = (modulo or '').split('.')[0]
    if radice in roma and radice not in MODULI_CONTROLLATI:
        return f'{dove}: il modulo di Roma {modulo} non e\' ammesso nei moduli di Napoli'
    return None


def problemi_modulo_napoli(sorgente, nome='modulo', roma=None):
    """Problemi di un modulo di Napoli: tabelle non napoli_* nelle stringhe SQL (anche
    costruite), tariffe e calcoli di Roma, funzioni di database.py, routes_export.py e
    validators.py non ammesse, altri moduli di Roma importati, import con * e import o
    getattr non verificabili. roma: nomi dei moduli di Roma (predefinito: moduli_roma())."""
    roma = moduli_roma() if roma is None else roma
    albero = ast.parse(sorgente)
    visti = {id(d) for n in ast.walk(albero) for d in [_docstring(n)] if d is not None}
    problemi = []
    alias = {}   # nome locale -> modulo di Roma controllato
    for n in ast.walk(albero):        # in ampiezza: un'espressione prima delle sue parti
        if id(n) in visti:
            continue
        dove = f'{nome}:{getattr(n, "lineno", 0)}'
        testo = _testo_stringa(n) if isinstance(n, ast.expr) else None
        if testo is not None:
            visti.update(id(x) for x in ast.walk(n))     # le parti non si rileggono da sole
            problemi += _problemi_sql(testo, dove)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name in MODULI_CONTROLLATI:
                    alias[a.asname or a.name] = a.name
                problemi += [p for p in [_import(a.name, dove, roma)] if p]
        elif isinstance(n, ast.ImportFrom) and n.level == 0:
            problemi += [p for p in [_import(n.module, dove, roma)] if p]
            if n.module in MODULI_CONTROLLATI:
                for a in n.names:
                    if a.name == '*':
                        problemi.append(f'{dove}: from {n.module} import * non e\' verificabile')
                    else:
                        problemi += _uso(n.module, a.name, dove)
        elif isinstance(n, ast.Call) and _chiama(n, ('__import__', 'import_module', 'getattr')):
            primo = n.args[0] if n.args else None
            nome_fn = n.func.id if isinstance(n.func, ast.Name) else n.func.attr
            if nome_fn == 'getattr':
                if isinstance(primo, ast.Name) and primo.id in alias:
                    attributo = n.args[1] if len(n.args) > 1 else None
                    if isinstance(attributo, ast.Constant) and isinstance(attributo.value, str):
                        problemi += _uso(alias[primo.id], attributo.value, dove)
                    else:
                        problemi.append(f'{dove}: getattr su {alias[primo.id]} con un nome calcolato, '
                                        'non verificabile')
            elif isinstance(primo, ast.Constant) and isinstance(primo.value, str):
                problemi += [p for p in [_import(primo.value, dove, roma)] if p]
                if primo.value in MODULI_CONTROLLATI:
                    problemi.append(f'{dove}: import di {primo.value} per nome, non verificabile')
            else:
                problemi.append(f'{dove}: import con un nome calcolato, non verificabile')
    for n in ast.walk(albero):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in alias:
            problemi += _uso(alias[n.value.id], n.attr, f'{nome}:{n.lineno}')
    return problemi


def _chiama(nodo, nomi):
    f = nodo.func
    return (isinstance(f, ast.Name) and f.id in nomi) or (isinstance(f, ast.Attribute) and f.attr in nomi
                                                          and f.attr != 'getattr')


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
    conn.execute("UPDATE sqlite_sequence SET seq = 9 WHERE name = 'napoli_coordinamento'")
    conn.execute("UPDATE sqlite_sequence SET seq = 9 WHERE name = 'utenti'")
    with db.get_db_context():
        db.log_audit('napoli_import', 'napoli_lotto')
        db.update_rendicontazione(1, 2025, 10, ore_lavorate=1)
    return config.calcola_fatturazione(x), config.MESI_NOME
'''
    problemi = problemi_modulo_napoli(sorgente, 'napoli_prova.py')
    testo = '\n'.join(problemi)
    for atteso in ('tabella di Roma nello SQL: utenti', 'tabella di Roma nello SQL: rendicontazione',
                   'nome di tabella calcolato, non verificabile: {?}', 'tabella di Roma nello SQL: commesse',
                   'database.update_rendicontazione', 'config.calcola_fatturazione',
                   'contatori di tabelle non napoli_* (sqlite_sequence)'):
        assert atteso in testo, testo
    assert len(problemi) == 7, testo


def test_controllo_trova_gli_import_non_ammessi():
    sorgente = 'from database import get_db_context, get_rendicontazione_completa\nfrom config import IVA_PERCENTUALE\n'
    problemi = problemi_modulo_napoli(sorgente, 'routes_napoli.py')
    assert len(problemi) == 2 and 'get_rendicontazione_completa' in problemi[0] and 'IVA_PERCENTUALE' in problemi[1]


def test_controllo_trova_lo_sql_costruito():
    sorgente = """
TABELLA = 'utenti'


def leggi(conn, t, x, colonne):
    conn.execute("SELECT * FROM " + "rendicontazione WHERE id = ?", (x,))
    conn.execute("SELECT * FROM " + t)
    conn.execute("DELETE FROM %s WHERE id = ?" % t, (x,))
    conn.execute("UPDATE {} SET nome = ?".format(t), (x,))
    conn.execute(" ".join(["SELECT", colonne, "FROM", "commesse"]))
    conn.execute("SELECT * FROM napoli_" + t)
    conn.execute("SELECT %s FROM napoli_alunni WHERE id = %d" % (colonne, x))
    conn.execute(f"SELECT {colonne} FROM napoli_coppie " + "JOIN scuole ON 1")
    conn.execute("INSERT INTO napoli_alunni (nome) VALUES (?)", (x,))
"""
    problemi = problemi_modulo_napoli(sorgente, 'napoli_prova.py')
    testo = '\n'.join(problemi)
    for atteso in ('napoli_prova.py:6: tabella di Roma nello SQL: rendicontazione',
                   'napoli_prova.py:7: nome di tabella calcolato, non verificabile: {?}',
                   'napoli_prova.py:8: nome di tabella calcolato, non verificabile: {?}',
                   'napoli_prova.py:9: nome di tabella calcolato, non verificabile: {?}',
                   'napoli_prova.py:10: tabella di Roma nello SQL: commesse',
                   'napoli_prova.py:13: tabella di Roma nello SQL: scuole'):
        assert atteso in testo, testo
    assert len(problemi) == 6, testo        # una volta sola per espressione; le righe 11, 12 e 14 vanno bene


def test_controllo_trova_i_moduli_di_roma_e_gli_import_non_verificabili():
    sorgente = """
import importlib
import json
import app
import routes_dashboard as rd
from import_rendicontazione import parse_ore
from routes_migrazione import TABELLE_DOMINIO
from strumenti import fotografa_roma
from config import *
from database import *
from validators import validate_string, valida_tutto
import config_napoli
import napoli_calcoli
import database as db
modulo = importlib.import_module('routes_backup')
altro = __import__(json.dumps('x'))
f = getattr(db, 'update_rendicontazione')
g = getattr(db, 'get_db_context')
h = getattr(db, json.dumps('x'))
"""
    problemi = problemi_modulo_napoli(sorgente, 'routes_napoli.py')
    testo = '\n'.join(problemi)
    for atteso in ('il modulo di Roma app ', 'il modulo di Roma routes_dashboard ',
                   'il modulo di Roma import_rendicontazione ', 'il modulo di Roma routes_migrazione ',
                   'il modulo di Roma strumenti ', 'from config import * non e\' verificabile',
                   'from database import * non e\' verificabile', 'validators.valida_tutto',
                   'il modulo di Roma routes_backup ', 'import con un nome calcolato',
                   'database.update_rendicontazione', 'getattr su database con un nome calcolato'):
        assert atteso in testo, testo
    assert len(problemi) == 12, testo
    assert {'app', 'database', 'config', 'routes_export', 'strumenti', 'tests'} <= moduli_roma()
    assert not {'napoli_calcoli', 'napoli_schema', 'config_napoli'} & moduli_roma()


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

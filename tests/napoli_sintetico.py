"""Foglio presenze "master" di Napoli INVENTATO, creato durante i test (PROGETTO §12).

Stessa struttura del file che il coordinatore manda ogni mese (marzo 2026): una riga
per coppia operatore-alunno, una colonna per ogni giorno da lunedi' a sabato, VERIFICA
dopo ogni settimana, sostituzione SI/NO e note; foglio "riepilogo" non aggiornato.
41 righe, nomi di fantasia, scuole con codici "ZZ"; i codici fiscali hanno il carattere
di controllo giusto ma il codice comune Z999, che non esiste (seme_napoli): non possono
essere di una persona vera. Nessun file binario nel repository: genera() lo scrive in
una cartella temporanea insieme ai valori attesi, calcolati qui in modo indipendente
dal lettore (import_napoli), e master_sintetico_atteso.json.

Casi coperti (quasi tutti visti nel file vero, solo come forma):
qualifiche scritte in modi diversi (ASACOM, "ASACOM ", ASACM, EDUCATICE PROFESSIONALE,
PSICOLOGA, TIFLOLOGA...); sigle F, M, F perm e varianti (f, "F ", Fperm, F (PERM),
F perm)); numeri scritti come testo ("1.5"); date "O3/11/2025", "26/11 2025",
"06/10/205", anno sbagliato (06/10/2026 con ore a marzo), inizio futuro senza ore; ore
di contratto "23 var or" e "34 con var"; ore da progetto "13 var oraria"; alunno assente
= meta' dell'orario programmato (cella colorata, nota "Alunno assente: ..."); assenza
recuperata; recupero di ferie di febbraio; sostituti (SI) nei giorni di malattia o
ferie del titolare; cambio di operatore a meta' mese (subentro dal 24); alunno con due
figure; operatore con quattro alunni; plesso chiuso; assemblea; uscita didattica;
VERIFICA sovrascritta con un numero; Lotto e Municipalita' vuoti; la stessa scuola in
due municipalita' (due plessi); scuola senza parentesi di chiusura, con "COD. MECC.",
a capo, con "1" nel tipo, senza codice; codice fiscale con il carattere di controllo
sbagliato e di 17 caratteri; stesso codice fiscale con due scritture del nome; una
cella "1,30" alla maniera dei fogli firma (1 ora e 30 minuti, da confermare).

omonimi=True: tre alunni e un operatore hanno i nomi di utenti e operatori dell'archivio
Roma inventato (tests/roma_sintetico.py), per provare che Roma non cambia.
"""
import datetime
import json
import os
import re
import shutil
import tempfile
import zipfile

import openpyxl
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from seme_napoli import codice_fiscale_inventato

ANNO, MESE = 2026, 3
COOP = 'COOPERATIVA SOCIALE DI FANTASIA S.C.S.'
NOME_FILE = 'master_sintetico.xlsx'

# ==================== scrittura nel formato del master ====================

INTESTAZIONE_FISSA = [
    'Lotto', 'Cooperativa', 'Nome Cognome Operatore', 'Cf Operatore', 'Qualifica Professionale',
    'Data Inizio attività', 'Ore settimanali da contratto', 'Nome Cognome alunno/a', 'Cf alunno/a',
    'Ore settimanali da progetto (indicare il n. di ore di assistenza da erogare su ciascun alunno assistito)',
    'Municipalita’', 2,                     # nel file vero l'intestazione della scuola e' "2"
]
INTESTAZIONE_FINALE = ['Sostituzione operatore\n(SI/NO)',
                       'NOTE \n(Esempio: Date e ore assenze alunno o altre considerazioni)']
CHIAVI_FISSE = ['lotto', 'cooperativa', 'operatore', 'cf_operatore', 'qualifica', 'data_inizio',
                'ore_contratto', 'alunno', 'cf_alunno', 'ore_progetto', 'municipalita', 'scuola']
GRIGIO = PatternFill('solid', fgColor='FFD9D9D9')
SALMONE = PatternFill('solid', fgColor='FFFAE2D5')    # giorno di alunno assente (meta' delle ore)
ROSSO_CHIARO = PatternFill(bgColor='FFFFC7CE')
FORMATO_DATA = 'mm-dd-yy'


def colonne_mese(anno, mese):
    """('giorno', data) da lunedi' a sabato e ('verifica', n) dopo ogni sabato e a fine mese."""
    out, sett = [], 1
    d = datetime.date(anno, mese, 1)
    while d.month == mese:
        if d.weekday() != 6:
            out.append(('giorno', d))
            if d.weekday() == 5:
                out.append(('verifica', sett))
                sett += 1
        d += datetime.timedelta(days=1)
    if out and out[-1][0] != 'verifica':
        out.append(('verifica', sett))
    return out


def scrivi_master(percorso, anno, mese, righe, righe_riepilogo=None, titolo_foglio='master'):
    """Scrive il file. righe: dict con CHIAVI_FISSE, 'giorni' {data: valore}, 'colorati'
    (date con la cella colorata), 'sostituzione', 'note', 'verifica_fissa' {settimana:
    numero} (una VERIFICA sovrascritta a mano). Le VERIFICA sono formule con il valore
    gia' calcolato (come le salva Excel: SOMMA ignora i numeri scritti come testo)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = titolo_foglio
    sequenza = colonne_mese(anno, mese)
    intest = list(INTESTAZIONE_FISSA)
    for tipo, x in sequenza:
        intest.append(datetime.datetime(x.year, x.month, x.day) if tipo == 'giorno' else 'VERIFICA')
    intest += INTESTAZIONE_FINALE
    for j, v in enumerate(intest, start=1):
        c = ws.cell(1, j, v)
        c.font = Font(bold=True)
        c.fill = GRIGIO
        c.alignment = Alignment(wrap_text=True, horizontal='center', vertical='center')
        if isinstance(v, datetime.datetime):
            c.number_format = FORMATO_DATA
    base = len(INTESTAZIONE_FISSA)
    col_sost = base + len(sequenza) + 1
    valori_formule = {}
    for i, r in enumerate(righe, start=2):
        for j, chiave in enumerate(CHIAVI_FISSE, start=1):
            v = r.get(chiave)
            if isinstance(v, datetime.date) and not isinstance(v, datetime.datetime):
                v = datetime.datetime(v.year, v.month, v.day)
            c = ws.cell(i, j, v)
            if isinstance(v, datetime.datetime):
                c.number_format = FORMATO_DATA
        inizio_sett = None
        for k, (tipo, x) in enumerate(sequenza):
            jj = base + k + 1
            if tipo == 'giorno':
                inizio_sett = inizio_sett or jj
                c = ws.cell(i, jj, r.get('giorni', {}).get(x))
                if x in r.get('colorati', ()):
                    c.fill = SALMONE
                continue
            fisso = (r.get('verifica_fissa') or {}).get(x)
            if fisso is not None:
                ws.cell(i, jj, fisso)
            else:
                a, b = get_column_letter(inizio_sett), get_column_letter(jj - 1)
                ws.cell(i, jj, f'=SUM({a}{i}:{b}{i})')
                somma = sum(ws.cell(i, k2).value for k2 in range(inizio_sett, jj)
                            if isinstance(ws.cell(i, k2).value, (int, float))
                            and not isinstance(ws.cell(i, k2).value, bool))
                valori_formule[f'{get_column_letter(jj)}{i}'] = somma
            inizio_sett = None
        ws.cell(i, col_sost, r.get('sostituzione'))
        ws.cell(i, col_sost + 1, r.get('note'))
    ultima = len(righe) + 1
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = f'A1:{get_column_letter(col_sost + 1)}{ultima}'
    if righe:
        for k, (tipo, _x) in enumerate(sequenza):
            if tipo == 'verifica':
                lettera = get_column_letter(base + k + 1)
                ws.conditional_formatting.add(f'{lettera}2:{lettera}{ultima}', CellIsRule(
                    operator='greaterThan', formula=['$J2'], fill=ROSSO_CHIARO))
        ws.conditional_formatting.add(f'I2:I{ultima}', FormulaRule(
            formula=[f'COUNTIF($I$2:$I${ultima},I2)>1'], fill=ROSSO_CHIARO))
    if righe_riepilogo is not None:
        _scrivi_riepilogo(wb, righe_riepilogo)
    wb.save(percorso)
    _salva_valori_formule(percorso, valori_formule)


def _scrivi_riepilogo(wb, righe_riepilogo):
    ws = wb.create_sheet('riepilogo')
    ws['B2'], ws['C2'] = 'Cf Operatore', 'Nome Cognome Operatore'
    ws['D2'] = 'Somma di Ore settimanali da contratto'
    ws['E2'] = 'Somma di Ore settimanali da progetto'
    i = 3
    for cf, nome, contratto, progetto in righe_riepilogo:
        for j, v in enumerate((cf, nome, contratto, progetto), start=2):
            ws.cell(i, j, v)
        i += 1
    ws.cell(i, 2, 'Totale complessivo')
    ws.cell(i, 4, sum(x[2] or 0 for x in righe_riepilogo))
    ws.cell(i, 5, sum(x[3] or 0 for x in righe_riepilogo))


def _salva_valori_formule(percorso, valori):
    """openpyxl scrive le formule senza risultato: si aggiunge il valore calcolato, come
    farebbe Excel salvando, cosi' chi legge i valori trova il numero."""
    if not valori:
        return
    with zipfile.ZipFile(percorso) as z:
        contenuti = {n: z.read(n) for n in z.namelist()}
        info = {n: z.getinfo(n) for n in z.namelist()}
    parte = 'xl/worksheets/sheet1.xml'
    xml = contenuti[parte].decode('utf-8')

    def sostituisci(m):
        ref = m.group(1)
        if ref not in valori:
            return m.group(0)
        v = valori[ref]
        testo = f'{int(v)}' if float(v).is_integer() else repr(float(v))
        return f'<c r="{ref}"{m.group(2)}><f>{m.group(3)}</f><v>{testo}</v></c>'

    contenuti[parte] = re.sub(r'<c r="([A-Z]+\d+)"([^>]*)><f>([^<]*)</f><v\s*/?>(?:</v>)?</c>',
                              sostituisci, xml).encode('utf-8')
    fd, tmp = tempfile.mkstemp(suffix='.xlsx')
    os.close(fd)
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, dati in contenuti.items():
            z.writestr(info[n], dati)
    shutil.move(tmp, percorso)


# ==================== i dati inventati ====================

SCUOLE = {
    'S1': ('I.C. ALFA CENTAURI - PLESSO NORD (COD.MECC. NAIC8ZZ001)', 2),
    'S1b': ('I.C. ALFA CENTAURI - PLESSO NORD (COD.MECC. NAIC8ZZ001', 2),      # parentesi non chiusa
    'S2': ('I.C. 99 BETA - C.D. GAMMA (COD.MECC. NA1C8ZZ002)', 2),             # '1' nel tipo
    'S3': ('IS DELTA EPSILON (COD.MECC. NAIS0ZZ003)', 1),
    'S3b': ('IS DELTA  EPSILON (COD. MECC. NAIS0ZZ003)', 1),                   # doppio spazio, 'COD. MECC.'
    'S4': ('LICEO ZETA ETA (COD.MECC.\nNAPC0ZZ004)', 1),                       # a capo
    'S5': ('CONVITTO NAZIONALE THETA (COD.MECC. NAVC0ZZ005)', 2),
    'S6': ('SCUOLA SECONDARIA I GRADO ( SCUOLA MEDIA )', 1),                   # senza codice
}
CHIUSURE = {'S3': [20, 23, 24], 'S3b': [20, 23, 24], 'S1': [2], 'S1b': [2]}
SCHEMI = {13: [3, 2, 3, 2, 3], 15: [3, 3, 3, 3, 3], 8: [2, 2, 0, 2, 2], 10: [2, 2, 2, 2, 2],
          7: [2, 0, 3, 0, 2], '13b': [2.5, 2.5, 3, 2.5, 2.5], '8b': [1.5, 2, 1.5, 1.5, 1.5],
          '13t': [3, 0, 3, 4, 3]}

# operatori: (cognome, nome, sesso, nascita, qualifica come scritta)
OPERATORI = {
    'O1': ('PROVA', 'ALFA', 'F', datetime.date(1985, 4, 12), 'ASACOM'),
    'O2': ('ESEMPIO', 'BETA', 'M', datetime.date(1979, 11, 3), 'ASACOM'),
    'O3': ('FITTIZIO', 'GAMMA ROSA', 'F', datetime.date(1990, 1, 25), 'ASACOM '),
    'O4': ('DE PROVA', 'DELTA', 'F', datetime.date(1988, 6, 30), 'EDUCATORE PROFESSIONALE'),
    'O5': ('INVENTATO', 'EPSILON', 'F', datetime.date(1992, 9, 9), 'EDUCATICE PROFESSIONALE'),
    'O6': ('CAMPIONE', 'ZETA', 'F', datetime.date(1983, 2, 17), 'EDUCATRICE'),
    'O7': ('SINTETICO', 'ETA', 'F', datetime.date(1986, 12, 1), 'PSICOLOGA'),
    'O8': ('MODELLO', 'THETA', 'M', datetime.date(1975, 5, 21), 'PSICOLOGO'),
    'O9': ('DEMO', 'IOTA', 'F', datetime.date(1981, 8, 14), 'TIFLOLOGA'),
    'O10': ('SIMULATO', 'KAPPA', 'F', datetime.date(1994, 3, 8), 'EDUCATRICE PROFESSIONALE'),
    'O11': ('BOZZA', 'LAMBDA', 'F', datetime.date(1977, 7, 7), 'ASACOM'),
    'O12': ('SCHEMA', 'SIGMA', 'F', datetime.date(1991, 10, 19), 'ASACOM'),
    'O13': ('TRACCIA', 'OMEGA', 'M', datetime.date(1987, 4, 2), 'EDUCATORE PROFESSIONALE'),
    'O14': ('MODULO', 'RHO', 'F', datetime.date(1993, 12, 24), 'ASACOM'),
    'O15': ('FORMATO', 'TAU', 'F', datetime.date(1996, 2, 11), 'EDUCATORE PROFESSIONALE'),
    'O16': ('IPOTESI', 'PHI', 'M', datetime.date(1995, 6, 6), 'EDUCATORE PROFESSIONALE'),
    'O17': ('DI ESEMPIO', 'ALFA MARIA', 'F', datetime.date(1984, 1, 31), 'ASACOM'),
    'O18': ('FINZIONE', 'OMICRON', 'F', datetime.date(1998, 3, 3), 'EDUCATORE PROFESSIONALE'),
    'O19': ('BOZZA', 'ALFA', 'F', datetime.date(1980, 5, 5), 'ASACOM'),
    'O20': ('TEST', 'BETA', 'F', datetime.date(1989, 9, 29), 'ASACOM'),
    'O21': ('PROVA', 'GAMMA', 'F', datetime.date(1982, 11, 11), 'EDUCATRICE PROFESSIONALE'),
    'O22': ('ESEMPIO', 'DELTA', 'F', datetime.date(1976, 4, 4), 'PSICOLOGA'),
}
# Con omonimi=True: nomi di utenti e operatori dell'archivio Roma inventato (date di
# nascita diverse da quelle del seme: codici fiscali diversi).
OMONIMI_ALUNNI = {'A1': ('ESEMPIO', 'ALBA'), 'A3': ('FITTIZIO', 'BRUNO'), 'A13': ('CAMPIONE', 'GAIA')}
OMONIMI_OPERATORI = {'O1': ('OPERATORE', 'PRIMO')}

# assenze dell'operatore: giorno -> sigla scritta (su tutte le sue righe con orario quel giorno)
ASSENZE_OP = {
    'O2': {9: 'F', 10: 'F', 11: 'f'},
    'O4': {16: 'M', 17: 'M', 18: 'M', 19: 'M'},
    'O8': {5: 'M', 6: 'M'},
    'O11': {27: 'F ', 30: 'F'},
    'O14': {12: 'Fperm'},
    'O19': {4: 'F perm)'},
    'O21': {25: 'M', 26: 'M', 27: 'M'},
}
ASSENZE_PARZIALI = {('O5', 'A8'): {10: 'F (PERM)'}}       # permesso solo su una delle sue righe

_NOMI_ALUNNI = ['ALFA', 'BETA ANNA', 'GAMMA', 'DELTA', 'EPSILON', 'ZETA', 'ETA LUCE', 'THETA', 'IOTA',
                'KAPPA', 'LAMBDA', 'MI', 'NI', 'XI', 'OMICRON', 'PI', 'RHO', 'SIGMA', 'TAU', 'YPSILON',
                'PHI', 'CHI', 'PSI', 'OMEGA', 'ALEPH', 'BET', 'GHIMEL', 'DALET', 'HE', 'VAV', 'ZAIN',
                'HET', 'TET', 'IOD', 'CAF']
_COGNOMI_ALUNNI = ['ALUNNO', 'SCOLARO', 'DISCENTE', 'ALLIEVO', 'STUDENTE', 'APPRENDISTA', 'NOVIZIO']
ALUNNI = {}
for _k in range(1, 36):
    ALUNNI[f'A{_k}'] = (_COGNOMI_ALUNNI[_k % 7] + ('' if _k < 8 else ' DI PROVA' if _k % 5 == 0 else ''),
                        _NOMI_ALUNNI[_k - 1], 'F' if _k % 2 else 'M',
                        datetime.date(2010 + _k % 12, 1 + _k % 12, 1 + _k % 27))

R = []        # una voce per riga del foglio, nell'ordine del file


def _riga(op, al, J, scuola, **kw):
    d = dict(op=op, al=al, J=J, scuola=scuola, schema=kw.pop('schema', J if isinstance(J, int) else 13))
    d.update(kw)
    R.append(d)


_riga('O1', 'A1', 13, 'S1', contratto=26, inizio=datetime.date(2025, 10, 1), assente=[11, 17, 18],
      note='Alunno assente: 11,17,18. Il giorno 2 il plesso è stato chiuso per lavori idraulici')
_riga('O1', 'A2', 13, 'S1b', schema='13b', inizio=datetime.date(2025, 10, 1), assente=[6, 12, 30, 31],
      valori={26: '1.5'}, note='Alunno assente il 6, 12, 30, 31')
_riga('O2', 'A3', 13, 'S2', contratto=13, inizio=datetime.date(2025, 10, 6), assente_rec=[(4, 5)],
      note="Alunno assente il giorno 4 (or prog 8/11) e l'oper ha effettuato le ore il giorno 5")
_riga('O3', 'A4', 15, 'S3', contratto=15, inizio='O3/11/2025', recuperi={13: 1},
      note="L'oper il giorno 13 ha rec 1h del giorno 12/02 di ferie (orar prog 10/11)")
_riga('O3', 'A5', 8, 'S3b', contratto='23 var or', inizio='26/11 2025', assente=[5])
_riga('O4', 'A6', 13, 'S4', contratto=21, inizio=datetime.date(2025, 10, 6), mun=None, note='Alunno assente: 3')
_riga('O4', 'A7', 8, 'S4', inizio=datetime.date(2025, 10, 6), assente=[9, 10])
_riga('O5', 'A8', 8, 'S5', contratto=29, inizio=datetime.date(2025, 10, 13), schema='8b')
_riga('O5', 'A9', 13, 'S5', inizio=datetime.date(2025, 10, 13), assente=[2, 3], valori={5: '1,30'},
      note="Alunno assente i giorni 2,3. Il giorno 5 l'alunno è uscito anticipatamente")
_riga('O5', 'A10', 8, 'S5', inizio=datetime.date(2025, 10, 13), assente=[19])
_riga('O6', 'A11', 10, 'S6', inizio='06/10/205', fino_a=13, note='OPERATRICE DIMESSA DAL 16 MARZO')
_riga('O6', 'A12', 8, 'S6', inizio=datetime.date(2026, 1, 21), fino_a=13)
_riga('O7', 'A13', 8, 'S1', inizio=datetime.date(2025, 10, 1), assente=[24])
_riga('O8', 'A14', 8, 'S2', inizio=datetime.date(2026, 10, 6), assente=[16])      # anno sbagliato
_riga('O9', 'A15', 13, 'S3', schema='13t', contratto=13, inizio='O7/11/2025')
_riga('O10', 'A15', 13, 'S3', contratto=26, inizio=datetime.date(2025, 11, 3), assente=[26], assente_rec=[(9, 10)],
      note="Alunno assente il 26. Alunno assente il giorno 9 (or prog 8/11) e l'op ha recuperato le ore il giorno 10")
_riga('O10', 'A16', '13 var oraria', 'S3', schema=13, inizio=datetime.date(2025, 11, 3))
_riga('O11', 'A17', 8, 'S2', contratto=26, inizio=datetime.date(2025, 10, 1), recuperi={12: 4, 13: 2},
      note="L'oper il giorno 12 ha rec 4h e il giorno 13 2h del giorno di ferie 18/02 (or prog 9/13)")
_riga('O11', 'A18', 8, 'S2', inizio=datetime.date(2025, 10, 1), assente=[16, 17])
_riga('O11', 'A19', 8, 'S2', inizio=datetime.date(2025, 10, 1), lotto=None)
_riga('O11', 'A20', 8, 'S2', contratto='34 con var', inizio=datetime.date(2026, 2, 23), valori={5: 1},
      note='Il giorno 5 assemblea scolastica')
_riga('O12', 'A21', 15, 'S1', contratto=28, inizio=datetime.date(2025, 10, 7), cf_errato='controllo',
      verifica_fissa={2: 3}, assente=[25])
_riga('O12', 'A22', 13, 'S1', inizio=datetime.date(2025, 10, 7), cf_errato='controllo', qualifica='ASACM',
      nome_variante='SCHEMA SIGMMA')
_riga('O13', 'A23', 13, 'S5', contratto=13, inizio=datetime.date(2025, 10, 27), assente=[30])
_riga('O14', 'A23', 15, 'S5', contratto=30, inizio=datetime.date(2026, 1, 7), valori={27: 4},
      note='27 USCITA DIDATTICA')
_riga('O14', 'A25', 13, 'S5', inizio=datetime.date(2026, 1, 7))
_riga('O15', 'A6', 13, 'S4', sost='SI', copre=('O4', 'A6', [16, 17, 18, 19]), mun=1, alunno_variante=True,
      note="L'operatore ha sostituito la collega i giorni 16,17,18,19")
_riga('O15', 'A26', 13, 'S4', contratto=26, inizio=datetime.date(2025, 10, 6))
_riga('O16', 'A11', 10, 'S6', sost='SI', contratto=18, inizio=datetime.date(2026, 3, 24), dal=24,
      note="PRESA IN CARICO DELL'OPER DAL 24 MARZO")
_riga('O16', 'A12', 8, 'S6', sost='SI', inizio=datetime.date(2026, 3, 24), dal=24)
_riga('O17', 'A3', 13, 'S2', sost='SI', copre=('O2', 'A3', [9, 10, 11]), cf_errato='formato',
      note='Ha sostituito il collega i giorni 9,10,11')
_riga('O17', 'A27', 13, 'S2', contratto=21, inizio=datetime.date(2025, 10, 1), cf_errato='formato')
_riga('O17', 'A28', 8, 'S2', inizio=datetime.date(2025, 10, 1), cf_errato='formato', valori={18: '2.5'},
      schema='8b')
_riga('O18', 'A29', 10, 'S6', contratto=10, inizio=datetime.date(2026, 4, 24), nessuna=True, sost=None)
_riga('O19', 'A30', 13, 'S3', contratto=28, inizio=datetime.date(2025, 10, 1), assente=[3, 12])
_riga('O19', 'A31', 15, 'S3', inizio=datetime.date(2025, 10, 1))
_riga('O20', 'A32', 15, 'S1', contratto=15, inizio=datetime.date(2025, 10, 1), assente=[9, 10, 11, 12, 13],
      note='Alunno assente dal 9 al 13')
_riga('O20', 'A30', 13, 'S3', sost='SI ', copre=('O19', 'A30', [4]),
      note="L'operatrice ha sostituito la collega il giorno 4")
_riga('O21', 'A33', 8, 'S4', contratto=21, inizio=datetime.date(2025, 10, 1))
_riga('O21', 'A34', 13, 'S4', inizio=datetime.date(2025, 10, 1), assente=[2])
_riga('O22', 'A35', 7, 'S5', contratto=7, inizio=datetime.date(2025, 10, 15), assente=[18])


def _giorni_mese(anno=ANNO, mese=MESE):
    return [x for t, x in colonne_mese(anno, mese) if t == 'giorno']


def _programmato(rec, d):
    return 0 if d.weekday() >= 5 else SCHEMI[rec['schema']][d.weekday()]


def _rec_di(op, al):
    return next(r for r in R if r['op'] == op and r['al'] == al and not r.get('copre'))


def _sigla(v):
    return isinstance(v, str) and not re.fullmatch(r'\s*\d+(?:[.,]\d+)?\s*', v)


def minuti_attesi(v):
    """Minuti di una cella come li deve leggere l'import (indipendente dal lettore):
    numeri e testi numerici in ore decimali, '1,30' = 1 h 30 min, sigle 0."""
    if v is None:
        return 0
    if isinstance(v, str):
        if _sigla(v):
            return 0
        if v.strip() == '1,30':
            return 90
        return round(float(v.replace(',', '.')) * 60)
    return round(v * 60)


def costruisci(omonimi=False, anno=ANNO, mese=MESE):
    """(righe per scrivi_master, minuti attesi per riga {data: minuti}). Con un altro mese
    (anno, mese) le stesse righe con gli stessi numeri dei giorni (il mese dopo, per le
    prove dei reimport e delle coppie che continuano)."""
    righe, attese = [], []
    for rec in R:
        cog, nom, sesso, nascita, qual = OPERATORI[rec['op']]
        if omonimi and rec['op'] in OMONIMI_OPERATORI:
            cog, nom = OMONIMI_OPERATORI[rec['op']]
        cf_op = codice_fiscale_inventato(cog, nom, nascita, sesso)
        if rec.get('cf_errato') == 'controllo':
            cf_op = cf_op[:15] + ('A' if cf_op[15] != 'A' else 'B')
        elif rec.get('cf_errato') == 'formato':
            cf_op = cf_op[:11] + '0' + cf_op[11:]            # 17 caratteri
        acog, anom, asesso, anascita = ALUNNI[rec['al']]
        if omonimi and rec['al'] in OMONIMI_ALUNNI:
            acog, anom = OMONIMI_ALUNNI[rec['al']]
        cf_al = codice_fiscale_inventato(acog, anom, anascita, asesso)
        nome_al = f'{acog} {anom}' + ('A' if rec.get('alunno_variante') else '')   # stesso CF, refuso
        scuola_txt, mun = SCUOLE[rec['scuola']]
        valori, minuti, colorati = {}, {}, set()
        for d in _giorni_mese(anno, mese):
            g, p, v = d.day, _programmato(rec, d), None
            if d.weekday() == 5 or rec.get('nessuna') or g in CHIUSURE.get(rec['scuola'], []):
                v = None
            elif (rec.get('fino_a') and g > rec['fino_a']) or (rec.get('dal') and g < rec['dal']):
                v = None
            elif rec.get('copre'):
                top, tal, gg = rec['copre']
                v = _programmato(_rec_di(top, tal), d) if g in gg else None
            else:
                sig = ASSENZE_PARZIALI.get((rec['op'], rec['al']), {}).get(g) or \
                    (ASSENZE_OP.get(rec['op'], {}).get(g) if p > 0 else None)
                if sig:
                    v = sig
                elif g in rec.get('assente', []):
                    v = p / 2.0
                    colorati.add(d)
                elif g in [a for a, _b in rec.get('assente_rec', [])]:
                    v = None
                else:
                    v = p if p > 0 else None
                extra = rec.get('recuperi', {}).get(g, 0)
                for a, b in rec.get('assente_rec', []):
                    if b == g:
                        extra += _programmato(rec, datetime.date(anno, mese, a))
                if extra and not isinstance(v, str):
                    v = (v or 0) + extra
            if g in rec.get('valori', {}):
                v = rec['valori'][g]
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            valori[d] = v
            minuti[d] = minuti_attesi(v)
        righe.append({
            'lotto': rec.get('lotto', 1), 'cooperativa': COOP,
            'operatore': rec.get('nome_variante') or f'{cog} {nom}', 'cf_operatore': cf_op,
            'qualifica': rec.get('qualifica', qual), 'data_inizio': rec.get('inizio'),
            'ore_contratto': rec.get('contratto'), 'alunno': nome_al, 'cf_alunno': cf_al,
            'ore_progetto': rec['J'], 'municipalita': rec.get('mun', mun), 'scuola': scuola_txt,
            'giorni': valori, 'colorati': colorati, 'sostituzione': rec.get('sost', 'NO'), 'note': rec.get('note'),
            'verifica_fissa': rec.get('verifica_fissa'),
        })
        attese.append(minuti)
    return righe, attese


def _figura(qualifica):
    q = qualifica.strip().upper()
    if q.startswith('ASAC'):
        return 'ASACOM'
    if q.startswith('EDUC'):
        return 'EDUCATORE'
    if q.startswith('PSICOL'):
        return 'PSICOLOGO'
    return 'TIFLOLOGO'


def genera(cartella, omonimi=False, nome_file=NOME_FILE, modifica=None, anno=ANNO, mese=MESE):
    """Scrive il master inventato e i valori attesi nella cartella; ritorna (percorso
    del file, valori attesi). I minuti si contano dalle celle dei giorni.
    modifica(righe): per le varianti dei test (una cella o una municipalita' diverse...),
    chiamata prima di scrivere il file; i valori attesi restano quelli del file normale.
    anno, mese: il mese del file (di solito marzo 2026; aprile per il mese dopo)."""
    os.makedirs(cartella, exist_ok=True)
    righe, attese = costruisci(omonimi, anno, mese)
    if modifica is not None:
        modifica(righe)
    # foglio riepilogo NON aggiornato (come nel file vero): manca l'ultimo operatore, un valore e' vecchio
    acc = {}
    for r in righe:
        v = acc.setdefault(r['cf_operatore'], [r['operatore'], 0, 0])
        v[1] += r['ore_contratto'] if isinstance(r['ore_contratto'], (int, float)) else 0
        v[2] += r['ore_progetto'] if isinstance(r['ore_progetto'], (int, float)) else 0
    riepilogo = [(k, v[0], v[1], v[2]) for k, v in acc.items()][:-1]
    riepilogo[0] = (riepilogo[0][0], riepilogo[0][1], riepilogo[0][2], riepilogo[0][3] + 5)
    percorso = os.path.join(cartella, nome_file)
    scrivi_master(percorso, anno, mese, righe, righe_riepilogo=riepilogo)

    per_figura = {}
    for rec, r, minuti in zip(R, righe, attese):
        x = per_figura.setdefault(_figura(r['qualifica']), {'righe': 0, 'minuti': 0, 'operatori': set(),
                                                             'alunni': set()})
        x['righe'] += 1
        x['minuti'] += sum(minuti.values())
        x['operatori'].add(rec['op'])
        x['alunni'].add(rec['al'])
    sigle = {}
    for r in righe:
        for v in r['giorni'].values():
            if _sigla(v):
                k = re.sub(r'[\s().]+', '', v.upper())
                tipo = 'malattia' if k == 'M' else 'ferie' if k == 'F' else 'permesso'
                sigle[tipo] = sigle.get(tipo, 0) + 1
    atteso = {
        'file': nome_file, 'anno': anno, 'mese': mese, 'righe': len(righe), 'operatori': len(OPERATORI),
        'alunni': len({rec['al'] for rec in R}), 'scuole_codice': 5,
        'minuti_per_riga': [sum(m.values()) for m in attese],
        'ore_per_riga': [sum(m.values()) / 60 for m in attese],
        'per_figura': {f: {'righe': x['righe'], 'operatori': len(x['operatori']), 'alunni': len(x['alunni']),
                           'minuti': x['minuti'], 'ore': x['minuti'] / 60} for f, x in per_figura.items()},
        'totale_minuti': sum(sum(m.values()) for m in attese),
        'totale_ore': sum(sum(m.values()) for m in attese) / 60,
        'sigle': sigle,
        'celle_colorate': sum(len(r['colorati']) for r in righe),
        'separazione_cognome_nome': {'riga': 7, 'cognome': 'DE PROVA', 'nome': 'DELTA'},
        'nota': 'Dati inventati. minuti_per_riga nell\'ordine delle righe del foglio (dalla riga 2).',
    }
    with open(os.path.join(cartella, 'master_sintetico_atteso.json'), 'w', encoding='utf-8') as fh:
        json.dump(atteso, fh, ensure_ascii=False, indent=1)
    return percorso, atteso


def leggi_bytes(cartella, omonimi=False, nome_file=NOME_FILE, modifica=None, anno=ANNO, mese=MESE):
    """Il master inventato come bytes (per le richieste di prova) e i valori attesi."""
    percorso, atteso = genera(cartella, omonimi, nome_file, modifica, anno, mese)
    with open(percorso, 'rb') as fh:
        return fh.read(), atteso

"""Export della sezione Napoli (PROGETTO §7.2).

Passo 1.9: il prospetto fattura in Excel, con lo stile degli export di Roma
(routes_export.get_excel_brand_styles, importata senza modificarla) e un file che Excel apre
senza "riparazione" (xlsxwriter, celle unite che non si sovrappongono, nomi dei fogli validi).
Fogli:
- «Prospetto»: dati della fattura, righe come la fattura reale (descrizione, quantita' in ore,
  prezzo unitario, importo), ritenuta, imponibile, IVA, totale e "da pagare"; nessun nominativo;
- «Per scuola» e «Per operatore»: le ore della fattura per scuola (con la municipalita') e per
  operatore, con la figura, per controllare (mai alunni ne' codici fiscali);
- «Controlli»: i bloccanti e gli avvisi spiegati;
- «Ritenute»: le ritenute dello 0,50% delle fatture definitive del contratto applicativo.
I numeri sono numeri (non testo), con il formato all'italiana di Excel: rileggendo il file si
ottengono gli stessi valori del prospetto. Le pagine si stampano in A4 su una pagina di larghezza.
"""
import datetime
import io
import re

import xlsxwriter

import napoli_calcoli as calc
from routes_export import get_excel_brand_styles

NOMI_FOGLI = ('Prospetto', 'Per scuola', 'Per operatore', 'Controlli', 'Ritenute')
STATI = {'definitiva': 'Definitiva', 'riaperta': 'Riaperta (non definitiva)', 'da_fare': 'Da rendere definitiva'}


def _euro(cent):
    return int(cent) / 100


def _nome_file(p):
    """'Napoli_Fattura_Lotto1_XI_inferiore_Giugno_2026.xlsx' (solo lettere, cifre e trattini bassi)."""
    m = p['mese_info']
    parti = ['Napoli', 'Fattura', f'Lotto{p["testata"].get("numero_lotto") or ""}', p['numero'] or '', p['grado'],
             calc.MESI[m['mese'] - 1], str(m['anno'])]
    nome = '_'.join(re.sub(r'[^A-Za-z0-9]+', '', str(x)) for x in parti if str(x))
    return f'{nome}.xlsx'


def _titolo(ws, s, colonne, titolo, sottotitolo):
    ws.set_row(0, 34)
    ws.merge_range(0, 0, 0, colonne - 1, titolo, s['title'])
    ws.set_row(1, 22)
    ws.merge_range(1, 0, 1, colonne - 1, sottotitolo, s['subtitle'])
    ws.set_row(2, 8)


def _stampa(ws, orizzontale=False, ripeti=None):
    ws.set_paper(9)                       # A4
    if orizzontale:
        ws.set_landscape()
    else:
        ws.set_portrait()
    ws.set_margins(left=0.5, right=0.5, top=0.6, bottom=0.6)
    ws.fit_to_pages(1, 0)
    ws.hide_gridlines(2)
    if ripeti is not None:
        ws.repeat_rows(0, ripeti)


def _sottotitolo(p):
    return (f'{p["testata"].get("lotto") or ""}   ·   {p["scuole_grado"]}   ·   Contratto {p["numero"]}   ·   '
            f'{p["periodo_testo"]}')


def _foglio_prospetto(wb, s, p, f):
    ws = wb.add_worksheet('Prospetto')
    colonne = 4
    stato = STATI.get(p['stato'], p['stato'])
    if p['stato'] == 'definitiva' and p['fattura']:
        titolo = f'FATTURA DEFINITIVA N. {p["fattura"]["numero"]} DEL {p["fattura"]["data_testo"]}'
    else:
        titolo = 'PROSPETTO FATTURA (NON ANCORA DEFINITIVA)'
    _titolo(ws, s, colonne, titolo, _sottotitolo(p))
    t = p['testata']
    riga = 3
    ws.merge_range(riga, 0, riga, colonne - 1, 'DATI DELLA FATTURA', s['section'])
    riga += 1
    pagamento = 'Bonifico bancario'
    if t.get('iban'):
        pagamento += f' sull\'IBAN della cooperativa {t["iban"]}'
    pagamento += f', scadenza {p["scadenza_testo"]}' if p.get('scadenza_testo') else ''
    dati = [
        ('Stato', stato),
        ('Cooperativa', ' · '.join(x for x in (t.get('cooperativa'), f'P.IVA {t["partita_iva"]}' if t.get('partita_iva')
                                                else '', f'CF {t["codice_fiscale"]}' if t.get('codice_fiscale') else '')
                                   if x)),
        ('Destinatario', p['destinatario']),
        ('Oggetto', p['oggetto']),
        ('CIG', t.get('cig') or ''),
        ('Codice univoco ufficio', t.get('codice_univoco_ufficio') or ''),
        ('Contratto applicativo', ' · '.join(x for x in (t.get('contratto'), t.get('accordo_quadro')) if x)),
        ('Periodo di competenza', p['periodo_testo']),
        ('Nota', p['nota']),
        ('Pagamento', pagamento),
    ]
    for etichetta, valore in dati:
        alt = riga % 2 == 0
        ws.write(riga, 0, etichetta, s['summary_label'])
        # le celle unite non si allargano da sole: l'altezza per le righe di testo (circa 60 lettere a riga)
        ws.set_row(riga, max(18, 15 * -(-len(str(valore or '')) // 60)))
        ws.merge_range(riga, 1, riga, colonne - 1, valore or '', f['testo_alt' if alt else 'testo'])
        riga += 1
    riga += 1
    ws.merge_range(riga, 0, riga, colonne - 1, 'RIGHE DELLA FATTURA', s['section'])
    riga += 1
    ws.set_row(riga, 30)
    for c, h in enumerate(('Descrizione', 'Quantità (ore)', 'Prezzo unitario', 'Importo')):
        ws.write(riga, c, h, s['header'])
    riga += 1
    for i, r in enumerate(p['righe']):
        alt = i % 2 == 1
        ws.write(riga, 0, r['descrizione'], s['cell_alt' if alt else 'cell'])
        ws.write_number(riga, 1, _euro(r['ore_cent']), s['number_alt' if alt else 'number'])
        ws.write_number(riga, 2, _euro(r['tariffa_cent']), s['money_alt' if alt else 'money'])
        ws.write_number(riga, 3, _euro(r['importo_cent']), s['money_alt' if alt else 'money'])
        riga += 1
    if not p['righe']:
        ws.merge_range(riga, 0, riga, colonne - 1, 'Nessuna ora da fatturare nel periodo.', s['cell'])
        riga += 1
    tot = p['totali']
    ws.set_row(riga, 30)
    ws.write(riga, 0, p['ritenuta_testo'], f['ritenuta'])
    ws.write(riga, 1, '', s['cell'])
    ws.write(riga, 2, '', s['cell'])
    ws.write_number(riga, 3, -_euro(tot['ritenuta_cent']), s['money'])
    riga += 1
    ws.write(riga, 0, 'Totale delle righe', s['cell'])
    ws.write(riga, 1, '', s['cell'])
    ws.write(riga, 2, '', s['cell'])
    ws.write_number(riga, 3, _euro(tot['somma_cent']), s['money'])
    riga += 2
    for etichetta, chiave, stile in (('Imponibile', 'imponibile', 'summary'),
                                     (f'IVA {p["iva_percento"]}%', 'iva', 'summary'),
                                     ('Totale documento', 'totale', 'summary'),
                                     ('Da pagare' + (' (split payment)' if p['split_payment'] else ''), 'da_pagare',
                                      'grand')):
        ws.set_row(riga, 22 if stile == 'grand' else 18)
        ws.merge_range(riga, 0, riga, 2, etichetta, s[f'{stile}_label'])
        ws.write_number(riga, 3, _euro(tot[chiave + '_cent']), s[f'{stile}_money'])
        riga += 1
    riga += 1
    if p['split_payment']:
        ws.set_row(riga, 30)
        ws.merge_range(riga, 0, riga, colonne - 1,
                       'Scissione dei pagamenti (split payment, art. 17-ter del D.P.R. 633/1972): l\'IVA la versa '
                       'l\'ente, alla cooperativa si paga l\'imponibile.', s['note'])
        riga += 1
    ws.set_row(riga, 30)
    ws.merge_range(riga, 0, riga, colonne - 1,
                   'Prospetto preparato con Assisto: non è la fattura elettronica. Righe, testi e totali si ricopiano '
                   'nel programma di fatturazione.', s['note'])
    riga += 2
    ws.write(riga, 0, f'Documento generato il {datetime.datetime.now().strftime("%d/%m/%Y %H:%M")}', s['info'])
    ws.set_column(0, 0, 58)
    ws.set_column(1, 1, 14)
    ws.set_column(2, 2, 15)
    ws.set_column(3, 3, 17)
    _stampa(ws)
    return ws


def _foglio_tabella(wb, s, nome, p, intestazioni, larghezze, righe, numeriche=(), totale=None, nota=None):
    ws = wb.add_worksheet(nome)
    colonne = len(intestazioni)
    _titolo(ws, s, colonne, nome.upper(), _sottotitolo(p))
    riga = 3
    ws.set_row(riga, 30)
    for c, h in enumerate(intestazioni):
        ws.write(riga, c, h, s['header'])
    ws.freeze_panes(riga + 1, 0)
    riga += 1
    for i, valori in enumerate(righe):
        alt = i % 2 == 1
        for c, v in enumerate(valori):
            if c in numeriche:
                ws.write_number(riga, c, v, s['number_alt' if alt else 'number'])
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                ws.write_number(riga, c, v, s['integer_alt' if alt else 'integer'])
            else:
                ws.write(riga, c, '' if v is None else str(v), s['cell_alt' if alt else 'cell'])
        riga += 1
    if not righe:
        ws.merge_range(riga, 0, riga, colonne - 1, 'Niente da mostrare.', s['cell'])
        riga += 1
    if totale is not None:
        ws.set_row(riga, 22)
        etichetta, valori = totale
        ws.merge_range(riga, 0, riga, colonne - 1 - len(valori), etichetta, s['total_label'])
        for k, v in enumerate(valori):
            ws.write_number(riga, colonne - len(valori) + k, v, s['total_number'])
        riga += 1
    if nota:
        riga += 1
        ws.set_row(riga, 30)
        ws.merge_range(riga, 0, riga, colonne - 1, nota, s['note'])
    for c, w in enumerate(larghezze):
        ws.set_column(c, c, w)
    _stampa(ws, ripeti=3)
    return ws


def prospetto_excel(p, ritenute=None):
    """Il prospetto (napoli_fattura.prospetto) in un file Excel: (BytesIO, nome del file)."""
    uscita = io.BytesIO()
    wb = xlsxwriter.Workbook(uscita, {'in_memory': True})
    s = get_excel_brand_styles(wb)
    f = {
        'testo': wb.add_format({'font_size': 10, 'font_name': 'Calibri', 'align': 'left', 'valign': 'vcenter',
                                'border': 1, 'border_color': '#CBD5E1', 'text_wrap': True}),
        'testo_alt': wb.add_format({'font_size': 10, 'font_name': 'Calibri', 'align': 'left', 'valign': 'vcenter',
                                    'border': 1, 'border_color': '#CBD5E1', 'text_wrap': True,
                                    'bg_color': '#F1F5F9'}),
        'ritenuta': wb.add_format({'font_size': 10, 'font_name': 'Calibri', 'align': 'left', 'valign': 'vcenter',
                                   'border': 1, 'border_color': '#CBD5E1', 'text_wrap': True, 'italic': True}),
    }
    _foglio_prospetto(wb, s, p, f)
    minuti = [x['minuti'] for x in p['dettaglio']['scuole']]
    _foglio_tabella(wb, s, 'Per scuola', p, ('Scuola', 'Municipalità', 'Figura', 'Ore'), (52, 13, 18, 12),
                    [(x['scuola'], x['municipalita'], x['figura'], float(calc.ore_decimali(x['minuti'])))
                     for x in p['dettaglio']['scuole']], numeriche=(3,),
                    totale=('Totale', [float(calc.ore_decimali(sum(minuti)))]),
                    nota='Ore registrate nella griglia presenze, al centesimo (senza il coordinatore).')
    minuti = [x['minuti'] for x in p['dettaglio']['operatori']]
    _foglio_tabella(wb, s, 'Per operatore', p, ('Operatore', 'Figura', 'Ore'), (44, 18, 12),
                    [(x['operatore'], x['figura'], float(calc.ore_decimali(x['minuti'])))
                     for x in p['dettaglio']['operatori']], numeriche=(2,),
                    totale=('Totale', [float(calc.ore_decimali(sum(minuti)))]),
                    nota='Ore registrate nella griglia presenze, al centesimo (senza il coordinatore).')
    controlli = [('Da sistemare', b['titolo'], b['testo']) for b in p['bloccanti']]
    controlli += [('Da controllare', a['titolo'], a['testo']) for a in p['avvisi']]
    if not controlli:
        controlli = [('A posto', 'Nessun controllo da sistemare', '')]
    _foglio_tabella(wb, s, 'Controlli', p, ('Tipo', 'Che cosa', 'Spiegazione'), (16, 34, 90), controlli)
    contratto = next((c for c in (ritenute or {}).get('contratti', []) if c['contratto_id'] == p['contratto_id']),
                     None)
    righe_rit = [(x['numero'], x['data_testo'], x['grado_testo'], x['periodo_testo'], _euro(x['somma_cent']),
                  _euro(x['ritenuta_cent'])) for x in (contratto or {}).get('fatture', [])]
    _foglio_tabella(wb, s, 'Ritenute', p, ('Fattura n.', 'Data', 'Grado', 'Periodo', 'Somma delle righe',
                                           'Ritenuta 0,50%'), (14, 12, 17, 32, 18, 16), righe_rit, numeriche=(4, 5),
                    totale=('Ritenute del contratto ' + str(p['numero']),
                            [sum(r[4] for r in righe_rit), sum(r[5] for r in righe_rit)]) if righe_rit else None,
                    nota=('Le ritenute dello 0,50% delle fatture definitive del contratto applicativo: si svincolano '
                          'alla fine del contratto, con la fattura di svincolo.'))
    wb.close()
    uscita.seek(0)
    return uscita, _nome_file(p)

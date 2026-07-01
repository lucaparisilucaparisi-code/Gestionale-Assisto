"""Route di dashboard filtrata, alert automatici e documentazione API -
Blueprint separato da app.py. URL e nomi funzione invariati; endpoint API.
"""
from datetime import datetime

from flask import Blueprint, request, jsonify

import config
import database as db

MESI_NOME = config.MESI_NOME
MESI_SCOLASTICI = config.MESI_SCOLASTICI

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/api/alerts/<int:anno>/<int:mese>')
def api_get_alerts_by_period(anno, mese):
    """Ottiene gli alert automatici per il mese specifico"""
    commessa = request.args.get('commessa')
    alerts = db.get_alerts(anno, mese)

    # Filtra per commessa se specificata
    if commessa:
        alerts = [a for a in alerts if a.get('commessa') == commessa]

    return jsonify({
        'alerts': alerts,
        'totale': len(alerts),
        'per_tipo': {
            'danger': len([a for a in alerts if a['tipo'] == 'danger']),
            'warning': len([a for a in alerts if a['tipo'] == 'warning']),
            'info': len([a for a in alerts if a['tipo'] == 'info'])
        }
    })


# ==================== DASHBOARD FILTRATA ====================

@dashboard_bp.route('/api/stats/filtered')
def api_stats_filtered():
    """Statistiche dashboard con filtri per commessa e periodo"""
    commessa = request.args.get('commessa')
    anno = request.args.get('anno', type=int)
    mese = request.args.get('mese', type=int)

    with db.get_db_context() as conn:
        cursor = conn.cursor()

        stats = {}

        # Conteggio utenti (filtrato per commessa)
        if commessa:
            cursor.execute('''
                SELECT COUNT(*) FROM utenti u
                JOIN scuole s ON u.scuola_id = s.id
                JOIN commesse c ON s.commessa_id = c.id
                WHERE u.attivo = 1 AND c.nome = ?
            ''', (commessa,))
        else:
            cursor.execute("SELECT COUNT(*) FROM utenti WHERE attivo = 1")
        stats['num_utenti'] = cursor.fetchone()[0]

        # Conteggio scuole
        if commessa:
            cursor.execute('''
                SELECT COUNT(*) FROM scuole s
                JOIN commesse c ON s.commessa_id = c.id
                WHERE c.attiva = 1 AND c.nome = ?
            ''', (commessa,))
        else:
            cursor.execute("SELECT COUNT(*) FROM scuole")
        stats['num_scuole'] = cursor.fetchone()[0]

        # Ore mensili (se specificato periodo)
        if anno and mese:
            query_ore = '''
                SELECT
                    SUM(r.ore_lavorate_60) as ore_totali,
                    COUNT(DISTINCT CASE WHEN r.ore_lavorate_60 > 0 THEN r.utente_id END) as utenti_con_ore,
                    SUM(r.pasti) as pasti_totali
                FROM rendicontazione r
                JOIN utenti u ON r.utente_id = u.id
            '''
            params = [anno, mese]

            if commessa:
                query_ore += '''
                    JOIN scuole s ON u.scuola_id = s.id
                    JOIN commesse c ON s.commessa_id = c.id
                    WHERE r.anno = ? AND r.mese = ? AND u.attivo = 1 AND c.nome = ?
                '''
                params.append(commessa)
            else:
                query_ore += " WHERE r.anno = ? AND r.mese = ? AND u.attivo = 1"

            cursor.execute(query_ore, params)
            row = cursor.fetchone()
            stats['ore_mese'] = row['ore_totali'] or 0
            stats['utenti_con_ore'] = row['utenti_con_ore'] or 0
            stats['pasti_mese'] = row['pasti_totali'] or 0

    return jsonify(stats)


@dashboard_bp.route('/api/stats/trend')
def api_stats_trend():
    """Trend ore erogate per gli ultimi mesi dell'anno scolastico"""
    anno_scolastico = request.args.get('anno_scolastico')
    commessa = request.args.get('commessa')

    if not anno_scolastico:
        now = datetime.now()
        if now.month >= 9:
            anno_scolastico = f"{now.year}-{now.year + 1}"
        else:
            anno_scolastico = f"{now.year - 1}-{now.year}"

    anni = anno_scolastico.split('-')
    anno_inizio = int(anni[0])
    anno_fine = int(anni[1])

    risultati = []
    with db.get_db_context() as conn:
        cursor = conn.cursor()

        for mese in MESI_SCOLASTICI:
            anno = anno_inizio if mese >= 9 else anno_fine

            query = '''
                SELECT SUM(r.ore_lavorate_60) as ore_erogate
                FROM rendicontazione r
                JOIN utenti u ON r.utente_id = u.id
            '''
            params = [anno, mese]

            if commessa:
                query += '''
                    JOIN scuole s ON u.scuola_id = s.id
                    JOIN commesse c ON s.commessa_id = c.id
                    WHERE r.anno = ? AND r.mese = ? AND u.attivo = 1 AND c.nome = ?
                '''
                params.append(commessa)
            else:
                query += " WHERE r.anno = ? AND r.mese = ? AND u.attivo = 1"

            cursor.execute(query, params)
            row = cursor.fetchone()

            risultati.append({
                'mese': mese,
                'mese_nome': MESI_NOME.get(mese, '')[:3],
                'anno': anno,
                'ore_erogate': round(row['ore_erogate'] or 0, 2)
            })

    return jsonify(risultati)


@dashboard_bp.route('/api/stats/confronto-mese')
def api_stats_confronto_mese():
    """Confronto ore tra mese corrente e mese precedente"""
    anno = request.args.get('anno', type=int)
    mese = request.args.get('mese', type=int)
    commessa = request.args.get('commessa')

    if not anno or not mese:
        now = datetime.now()
        anno = now.year
        mese = now.month

    # Calcola mese precedente
    if mese == 1:
        mese_prec, anno_prec = 12, anno - 1
    else:
        mese_prec, anno_prec = mese - 1, anno

    with db.get_db_context() as conn:
        cursor = conn.cursor()

        def get_ore_mese(a, m):
            query = '''
                SELECT
                    COALESCE(SUM(r.ore_lavorate_60), 0) as ore,
                    COUNT(DISTINCT CASE WHEN r.ore_lavorate_60 > 0 THEN r.utente_id END) as utenti_attivi,
                    COALESCE(SUM(r.pasti), 0) as pasti
                FROM rendicontazione r
                JOIN utenti u ON r.utente_id = u.id
            '''
            params = [a, m]
            if commessa:
                query += '''
                    JOIN scuole s ON u.scuola_id = s.id
                    JOIN commesse c ON s.commessa_id = c.id
                    WHERE r.anno = ? AND r.mese = ? AND u.attivo = 1 AND c.nome = ?
                '''
                params.append(commessa)
            else:
                query += ' WHERE r.anno = ? AND r.mese = ? AND u.attivo = 1'
            cursor.execute(query, params)
            return cursor.fetchone()

        corrente = get_ore_mese(anno, mese)
        precedente = get_ore_mese(anno_prec, mese_prec)

        ore_corr = corrente['ore'] or 0
        ore_prec = precedente['ore'] or 0

        if ore_prec > 0:
            variazione_perc = round(((ore_corr - ore_prec) / ore_prec) * 100, 1)
        else:
            variazione_perc = 100 if ore_corr > 0 else 0

        result = {
            'mese_corrente': {
                'anno': anno,
                'mese': mese,
                'mese_nome': MESI_NOME.get(mese, ''),
                'ore': round(ore_corr, 2),
                'utenti_attivi': corrente['utenti_attivi'] or 0,
                'pasti': corrente['pasti'] or 0
            },
            'mese_precedente': {
                'anno': anno_prec,
                'mese': mese_prec,
                'mese_nome': MESI_NOME.get(mese_prec, ''),
                'ore': round(ore_prec, 2),
                'utenti_attivi': precedente['utenti_attivi'] or 0,
                'pasti': precedente['pasti'] or 0
            },
            'variazione': {
                'ore': round(ore_corr - ore_prec, 2),
                'percentuale': variazione_perc
            }
        }

    return jsonify(result)


@dashboard_bp.route('/api/stats/top-scuole')
def api_stats_top_scuole():
    """Top 5 scuole per ore erogate"""
    anno = request.args.get('anno', type=int)
    mese = request.args.get('mese', type=int)
    commessa = request.args.get('commessa')
    limit = request.args.get('limit', 5, type=int)

    if not anno or not mese:
        now = datetime.now()
        anno = now.year
        mese = now.month

    with db.get_db_context() as conn:
        cursor = conn.cursor()

        query = '''
            SELECT
                s.nome_completo as scuola,
                c.nome as commessa,
                SUM(r.ore_lavorate_60) as ore_erogate,
                COUNT(DISTINCT r.utente_id) as num_utenti,
                SUM(r.pasti) as pasti
            FROM rendicontazione r
            JOIN utenti u ON r.utente_id = u.id
            JOIN scuole s ON u.scuola_id = s.id
            JOIN commesse c ON s.commessa_id = c.id
            WHERE r.anno = ? AND r.mese = ? AND u.attivo = 1
        '''
        params = [anno, mese]

        if commessa:
            query += ' AND c.nome = ?'
            params.append(commessa)

        query += '''
            GROUP BY s.id
            HAVING ore_erogate > 0
            ORDER BY ore_erogate DESC
            LIMIT ?
        '''
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        risultati = []
        for r in rows:
            risultati.append({
                'scuola': r['scuola'][:40] + '...' if len(r['scuola'] or '') > 40 else r['scuola'],
                'scuola_full': r['scuola'],
                'commessa': r['commessa'],
                'ore_erogate': round(r['ore_erogate'] or 0, 2),
                'num_utenti': r['num_utenti'] or 0,
                'pasti': r['pasti'] or 0
            })

    return jsonify({
        'top_scuole': risultati,
        'anno': anno,
        'mese': mese,
        'mese_nome': MESI_NOME.get(mese, '')
    })


@dashboard_bp.route('/api/stats/credito-debito')
def api_stats_credito_debito():
    """Statistiche aggregate credito/debito"""
    anno = request.args.get('anno', type=int)
    mese = request.args.get('mese', type=int)
    commessa = request.args.get('commessa')

    if not anno or not mese:
        now = datetime.now()
        anno = now.year
        mese = now.month

    dati = db.get_rendicontazione_completa(anno, mese, commessa)

    totale_credito = 0
    totale_debito = 0
    utenti_in_credito = 0
    utenti_in_debito = 0
    utenti_in_pari = 0

    for d in dati:
        cd = d.get('credito_debito', 0) or 0
        if cd > 0.5:  # Tolleranza di 30 minuti
            totale_credito += cd
            utenti_in_credito += 1
        elif cd < -0.5:
            totale_debito += abs(cd)
            utenti_in_debito += 1
        else:
            utenti_in_pari += 1

    return jsonify({
        'totale_credito': round(totale_credito, 2),
        'totale_debito': round(totale_debito, 2),
        'saldo_netto': round(totale_credito - totale_debito, 2),
        'utenti_in_credito': utenti_in_credito,
        'utenti_in_debito': utenti_in_debito,
        'utenti_in_pari': utenti_in_pari,
        'totale_utenti': len(dati),
        'anno': anno,
        'mese': mese,
        'mese_nome': MESI_NOME.get(mese, '')
    })


# ==================== DOCUMENTAZIONE API ====================

@dashboard_bp.route('/api/docs')
def api_docs():
    """Documentazione API interattiva"""
    endpoints = [
        {
            'method': 'GET', 'path': '/api/utenti',
            'desc': 'Lista utenti attivi',
            'params': [
                {'nome': 'commessa', 'tipo': 'string', 'desc': 'Filtra per commessa'},
                {'nome': 'scuola_id', 'tipo': 'integer', 'desc': 'Filtra per scuola'}
            ]
        },
        {
            'method': 'POST', 'path': '/api/utenti',
            'desc': 'Crea nuovo utente',
            'body': {'commessa': 'string*', 'scuola': 'string*', 'nome': 'string*', 'cognome': 'string', 'monte_ore': 'number*'}
        },
        {
            'method': 'PUT', 'path': '/api/utenti/<id>',
            'desc': 'Aggiorna utente',
            'body': {'nome': 'string', 'cognome': 'string', 'monte_ore': 'number', 'lista_attesa': 'string'}
        },
        {
            'method': 'DELETE', 'path': '/api/utenti/<id>',
            'desc': 'Elimina utente'
        },
        {
            'method': 'GET', 'path': '/api/scuole',
            'desc': 'Lista scuole',
            'params': [{'nome': 'commessa', 'tipo': 'string', 'desc': 'Filtra per commessa'}]
        },
        {
            'method': 'GET', 'path': '/api/commesse',
            'desc': 'Lista commesse attive'
        },
        {
            'method': 'POST', 'path': '/api/commesse',
            'desc': 'Crea nuova commessa',
            'body': {'nome': 'string*', 'descrizione': 'string', 'colore': 'string (#RRGGBB)'}
        },
        {
            'method': 'PUT', 'path': '/api/commesse/<id>',
            'desc': 'Aggiorna commessa',
            'body': {'nome': 'string', 'descrizione': 'string', 'colore': 'string', 'attiva': 'boolean'}
        },
        {
            'method': 'DELETE', 'path': '/api/commesse/<id>',
            'desc': 'Disattiva commessa (soft delete)'
        },
        {
            'method': 'GET', 'path': '/api/rendicontazione/<anno>/<mese>',
            'desc': 'Rendicontazione mensile con tutti i calcoli',
            'params': [{'nome': 'commessa', 'tipo': 'string', 'desc': 'Filtra per commessa'}]
        },
        {
            'method': 'POST', 'path': '/api/rendicontazione/<anno>/<mese>',
            'desc': 'Aggiorna ore per un utente',
            'body': {'utente_id': 'integer*', 'ore_lavorate_60': 'number', 'pasti': 'integer', 'note': 'string'}
        },
        {
            'method': 'POST', 'path': '/api/rendicontazione/<anno>/<mese>/batch',
            'desc': 'Aggiorna ore per piu\' utenti',
            'body': {'updates': '[{utente_id, ore_lavorate_60, pasti, note}]'}
        },
        {
            'method': 'POST', 'path': '/api/import-excel',
            'desc': 'Importa dati da file Excel (.xlsx/.xls)',
            'body': {'file': 'multipart/form-data'}
        },
        {
            'method': 'GET', 'path': '/api/calendario',
            'desc': 'Calendario scolastico',
            'params': [{'nome': 'anno_scolastico', 'tipo': 'string', 'desc': 'Es: 2025-2026'}]
        },
        {
            'method': 'POST', 'path': '/api/calendario',
            'desc': 'Aggiorna giorni lavorativi',
            'body': {'anno_scolastico': 'string*', 'mese': 'integer*', 'anno': 'integer*', 'giorni_lavorativi': 'integer*'}
        },
        {
            'method': 'GET', 'path': '/api/stats',
            'desc': 'Statistiche generali'
        },
        {
            'method': 'GET', 'path': '/api/stats/advanced',
            'desc': 'Statistiche avanzate per dashboard',
            'params': [
                {'nome': 'anno', 'tipo': 'integer', 'desc': 'Anno'},
                {'nome': 'mese', 'tipo': 'integer', 'desc': 'Mese'}
            ]
        },
        {
            'method': 'GET', 'path': '/api/stats/filtered',
            'desc': 'Statistiche filtrate per commessa e periodo',
            'params': [
                {'nome': 'commessa', 'tipo': 'string', 'desc': 'Filtra per commessa'},
                {'nome': 'anno', 'tipo': 'integer', 'desc': 'Anno'},
                {'nome': 'mese', 'tipo': 'integer', 'desc': 'Mese'}
            ]
        },
        {
            'method': 'GET', 'path': '/api/stats/trend',
            'desc': 'Trend ore erogate per anno scolastico',
            'params': [
                {'nome': 'anno_scolastico', 'tipo': 'string', 'desc': 'Es: 2025-2026'},
                {'nome': 'commessa', 'tipo': 'string', 'desc': 'Filtra per commessa'}
            ]
        },
        {
            'method': 'GET', 'path': '/api/export/excel/<anno>/<mese>',
            'desc': 'Esporta rendicontazione in Excel Premium',
            'params': [
                {'nome': 'commessa', 'tipo': 'string', 'desc': 'Filtra per commessa'},
                {'nome': 'privacy', 'tipo': 'boolean', 'desc': 'Anonimizza nomi'}
            ]
        },
        {
            'method': 'GET', 'path': '/api/export/municipale/<anno>/<mese>',
            'desc': 'Riepilogo Municipale'
        },
        {
            'method': 'GET', 'path': '/api/export/dipartimentale/<anno>/<mese>',
            'desc': 'Monitoraggio Dipartimentale'
        },
        {
            'method': 'GET', 'path': '/api/export/word/<anno>/<mese>',
            'desc': 'Relazione Word sull\'andamento del servizio'
        },
        {
            'method': 'POST', 'path': '/api/backup',
            'desc': 'Crea backup manuale del database'
        },
        {
            'method': 'GET', 'path': '/api/backup',
            'desc': 'Lista backup disponibili'
        },
        {
            'method': 'POST', 'path': '/api/backup/restore',
            'desc': 'Ripristina un backup (richiede confirm: "CONFERMA")',
            'body': {'backup': 'string*', 'confirm': '"CONFERMA"'}
        },
        {
            'method': 'POST', 'path': '/api/reset',
            'desc': 'Reset dati (richiede confirm: "CONFERMA")',
            'body': {'type': 'all|rendicontazioni|utenti', 'confirm': '"CONFERMA"'}
        },
        {
            'method': 'GET', 'path': '/api/audit',
            'desc': 'Audit trail delle operazioni',
            'params': [
                {'nome': 'limit', 'tipo': 'integer', 'desc': 'Numero max risultati (default 100)'},
                {'nome': 'entita', 'tipo': 'string', 'desc': 'Filtra per tipo entita'}
            ]
        },
        {
            'method': 'GET', 'path': '/api/docs',
            'desc': 'Questa documentazione'
        },
    ]

    return jsonify({
        'nome': 'Gestionale OEPAC API',
        'versione': '2.1',
        'parametri_calcolo': {
            'tariffa_oraria': config.TARIFFA_ORARIA,
            'iva': f'{config.IVA_PERCENTUALE * 100}%',
            'tasso_assenza': f'{config.TASSO_ASSENZA * 100}%',
            'coefficiente_giornaliero': config.COEFFICIENTE_GIORNALIERO
        },
        'endpoints': endpoints
    })

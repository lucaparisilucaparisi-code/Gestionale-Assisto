"""Blueprint della sezione Napoli: pagine /napoli e API /api/napoli (PROGETTO §6).

L'accesso e' quello del resto del programma (before_request di app.py): le rotte
qui non hanno controlli propri. I dati passano solo da napoli_db (tabelle
napoli_*); ogni API controlla i dati lato server e risponde con messaggi semplici
({error, code, campo}: 400 dati non validi, 404 non trovato, 409 conflitto, per
esempio date sovrapposte). Le rotte sono elencate in ROTTE_NAPOLI di
strumenti/fotografa_roma.py (test_inventario_rotte).

Passo 1.3: scheda Mese (per ora i controlli del lotto e la procedura "Crea il primo
lotto") e Impostazioni (cooperativa, destinatario, lotti, contratti applicativi,
tariffe e regole con data, qualifiche), con il loro Ctrl+Z (/api/napoli/annulla).
Passi 1.4-1.5: scheda Importa (/napoli/import): dal file Excel "master" si carica
l'anagrafica (azione principale, REGOLE 14) o, come opzione secondaria, anche le ore di
un mese; anteprima, conferma, solo confronto, elenco e annullamento (import_napoli).
Passo 1.6: scheda Anagrafiche (/napoli/anagrafiche): alunni, operatori, scuole e plessi,
coppie operatore-alunno e PEI, con ricerca, filtri, creazione e modifica a mano,
archiviazione (napoli_anagrafiche). La ricerca non va mai nell'indirizzo (un nome o un
codice fiscale finirebbe nei log): la pagina chiede gli elenchi con una POST
(/api/napoli/lotti/<id>/anagrafiche/elenco); la GET degli elenchi ha solo i filtri.
Passo 1.8: ore del coordinatore nella scheda Mese (napoli_coordinamento): un totale
mensile per lotto, grado e contratto applicativo.
"""
import json
import logging
import sqlite3

from flask import Blueprint, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge

import import_napoli
import napoli_anagrafiche as anagrafiche
import napoli_coordinamento as coordinamento
import napoli_db

napoli_bp = Blueprint('napoli', __name__)
logger = logging.getLogger('oepac.napoli')   # nel file di log del programma


# ==================== errori ====================

@napoli_bp.errorhandler(napoli_db.ErroreNapoli)
def _errore_napoli(e):
    return jsonify(e.risposta()), e.stato


@napoli_bp.errorhandler(sqlite3.IntegrityError)
def _dati_doppi(e):
    logger.warning('Napoli: vincolo del database su %s %s: %s', request.method, request.path, e)
    return jsonify({'error': 'Questi dati ci sono già o sono collegati ad altri: ricarica la pagina e controlla.',
                    'code': 'CONFLITTO'}), 409


@napoli_bp.errorhandler(sqlite3.OperationalError)
def _database_occupato(e):
    logger.error('Napoli: errore del database su %s %s: %s', request.method, request.path, e)
    return jsonify({'error': 'Il programma è occupato in questo momento: riprova tra qualche secondo.',
                    'code': 'DATABASE_OCCUPATO'}), 503


@napoli_bp.errorhandler(RequestEntityTooLarge)
def _file_troppo_grande(e):
    return jsonify({'error': 'Il file è troppo grande (al massimo 16 MB): controlla di aver scelto il foglio '
                             'presenze del mese.', 'code': 'FILE_TROPPO_GRANDE', 'campo': 'file'}), 413


def _dati():
    """Corpo JSON della richiesta (un oggetto), altrimenti 400."""
    dati = request.get_json(silent=True)
    if not isinstance(dati, dict):
        raise napoli_db.DatiNonValidi('I dati non sono arrivati: ricarica la pagina e riprova.')
    return dati


def _ok(**valori):
    return jsonify(dict(success=True, **valori))


def _con_nota(messaggio, riga):
    """Il messaggio dopo un salvataggio, piu' come sono cambiate le date della riga
    precedente (la nota di napoli_db, tolta dalla riga)."""
    nota = riga.pop('nota', '')
    return f'{messaggio}.{nota}' if nota else messaggio


# ==================== pagine ====================

def _pulisci_annullamenti():
    """Ad ogni pagina di Napoli si svuotano le azioni di Ctrl+Z scadute (i valori di prima,
    IBAN compreso, non restano nel database); se il database e' occupato, la prossima volta."""
    try:
        napoli_db.pulisci_annullamenti()
    except sqlite3.OperationalError as e:
        logger.warning('Napoli: azioni scadute di Ctrl+Z non svuotate: %s', e)


@napoli_bp.route('/napoli')
def mese_page():
    """Scheda Mese: con un lotto i controlli per la fattura; senza, "Crea il primo lotto"."""
    _pulisci_annullamenti()
    return render_template('napoli_mese.html')


@napoli_bp.route('/napoli/impostazioni')
def impostazioni_page():
    _pulisci_annullamenti()
    return render_template('napoli_impostazioni.html')


@napoli_bp.route('/napoli/anagrafiche')
def anagrafiche_page():
    """Scheda Anagrafiche: alunni, operatori, scuole e plessi, coppie (una parte alla volta)."""
    _pulisci_annullamenti()
    return render_template('napoli_anagrafiche.html')


@napoli_bp.route('/napoli/import')
def import_page():
    """Scheda Importa: il foglio presenze del mese (master) con anteprima e conferma."""
    _pulisci_annullamenti()
    return render_template('napoli_import.html')


# ==================== impostazioni: cooperativa e destinatario ====================

@napoli_bp.route('/api/napoli/impostazioni', methods=['GET'])
def api_impostazioni():
    return jsonify(napoli_db.impostazioni_per_la_pagina())


@napoli_bp.route('/api/napoli/impostazioni/<gruppo>', methods=['PUT'])
def api_salva_impostazioni(gruppo):
    cambiati = napoli_db.salva_impostazioni(gruppo, _dati())
    messaggio = 'Salvato' if cambiati else 'Nessun cambiamento da salvare'
    return _ok(cambiati=cambiati, messaggio=messaggio, impostazioni=napoli_db.impostazioni_per_la_pagina())


@napoli_bp.route('/api/napoli/figure', methods=['GET'])
def api_figure():
    return jsonify(napoli_db.elenco_figure())


# ==================== lotti ====================

@napoli_bp.route('/api/napoli/lotti', methods=['GET'])
def api_lotti():
    return jsonify(napoli_db.elenco_lotti())


@napoli_bp.route('/api/napoli/lotti', methods=['POST'])
def api_crea_lotto():
    return _ok(lotto=napoli_db.crea_lotto(_dati()), messaggio='Lotto creato')


@napoli_bp.route('/api/napoli/lotti/proposta', methods=['GET'])
def api_proposta_lotto():
    """Valori proposti dalla procedura guidata (nome, numero libero, tariffe del contratto)."""
    return jsonify(napoli_db.proposta_lotto())


@napoli_bp.route('/api/napoli/lotti/procedura', methods=['POST'])
def api_procedura_lotto():
    """Procedura "Crea il primo lotto": il lotto con le sue tariffe, in un'unica azione."""
    nuovo = napoli_db.crea_lotto_con_tariffe(_dati())
    return _ok(lotto=nuovo, messaggio=f'Lotto {nuovo["nome"]} creato con le sue tariffe')


@napoli_bp.route('/api/napoli/lotti/<int:lotto_id>', methods=['GET'])
def api_lotto(lotto_id):
    return jsonify(napoli_db.lotto(lotto_id))


@napoli_bp.route('/api/napoli/lotti/<int:lotto_id>', methods=['PUT'])
def api_aggiorna_lotto(lotto_id):
    return _ok(lotto=napoli_db.aggiorna_lotto(lotto_id, _dati()), messaggio='Lotto salvato')


@napoli_bp.route('/api/napoli/lotti/<int:lotto_id>', methods=['DELETE'])
def api_elimina_lotto(lotto_id):
    napoli_db.elimina_lotto(lotto_id)
    return _ok(messaggio='Lotto eliminato')


@napoli_bp.route('/api/napoli/lotti/<int:lotto_id>/controlli', methods=['GET'])
def api_controlli_lotto(lotto_id):
    return jsonify(napoli_db.controlli_lotto(lotto_id, request.args.get('giorno')))


# ==================== ore del coordinatore (passo 1.8) ====================

@napoli_bp.route('/api/napoli/lotti/<int:lotto_id>/coordinamento', methods=['GET'])
def api_coordinamento(lotto_id):
    """I mesi dei contratti del lotto fino a oggi, con le ore del coordinatore per contratto e grado."""
    return jsonify(coordinamento.elenco(lotto_id))


@napoli_bp.route('/api/napoli/lotti/<int:lotto_id>/coordinamento', methods=['PUT'])
def api_salva_coordinamento(lotto_id):
    """Ore (e nota) del coordinatore di un mese, contratto e grado; ore vuote = tolte."""
    return _ok(**coordinamento.salva(lotto_id, _dati()))


# ==================== contratti applicativi ====================

@napoli_bp.route('/api/napoli/lotti/<int:lotto_id>/contratti', methods=['GET'])
def api_contratti(lotto_id):
    return jsonify(napoli_db.elenco_contratti(lotto_id))


@napoli_bp.route('/api/napoli/lotti/<int:lotto_id>/contratti', methods=['POST'])
def api_crea_contratto(lotto_id):
    return _ok(contratto=napoli_db.crea_contratto(lotto_id, _dati()), messaggio='Contratto applicativo aggiunto')


@napoli_bp.route('/api/napoli/contratti/<int:contratto_id>', methods=['PUT'])
def api_aggiorna_contratto(contratto_id):
    return _ok(contratto=napoli_db.aggiorna_contratto(contratto_id, _dati()), messaggio='Contratto salvato')


@napoli_bp.route('/api/napoli/contratti/<int:contratto_id>', methods=['DELETE'])
def api_elimina_contratto(contratto_id):
    napoli_db.elimina_contratto(contratto_id)
    return _ok(messaggio='Contratto eliminato')


# ==================== tariffe ====================

@napoli_bp.route('/api/napoli/lotti/<int:lotto_id>/tariffe', methods=['GET'])
def api_tariffe(lotto_id):
    return jsonify(napoli_db.elenco_tariffe(lotto_id))


@napoli_bp.route('/api/napoli/lotti/<int:lotto_id>/tariffe', methods=['POST'])
def api_crea_tariffa(lotto_id):
    nuova = napoli_db.crea_tariffa(lotto_id, _dati())
    return _ok(messaggio=_con_nota('Tariffa aggiunta', nuova), tariffa=nuova)


@napoli_bp.route('/api/napoli/tariffe/<int:tariffa_id>', methods=['PUT'])
def api_aggiorna_tariffa(tariffa_id):
    salvata = napoli_db.aggiorna_tariffa(tariffa_id, _dati())
    return _ok(messaggio=_con_nota('Tariffa salvata', salvata), tariffa=salvata)


@napoli_bp.route('/api/napoli/tariffe/<int:tariffa_id>', methods=['DELETE'])
def api_elimina_tariffa(tariffa_id):
    napoli_db.elimina_tariffa(tariffa_id)
    return _ok(messaggio='Tariffa eliminata')


# ==================== regole con data ====================

def _lotto_della_richiesta():
    valore = request.args.get('lotto_id', '')
    if not valore:
        return None
    if not valore.isdigit():
        raise napoli_db.DatiNonValidi('Il lotto non è valido: ricarica la pagina.', 'lotto_id')
    return int(valore)


@napoli_bp.route('/api/napoli/regole', methods=['GET'])
def api_regole():
    return jsonify(napoli_db.elenco_regole(_lotto_della_richiesta(), request.args.get('giorno')))


@napoli_bp.route('/api/napoli/regole', methods=['POST'])
def api_crea_regola():
    nuova = napoli_db.crea_regola(_dati())
    return _ok(messaggio=_con_nota('Regola salvata', nuova), regola=nuova)


@napoli_bp.route('/api/napoli/regole/<int:regola_id>', methods=['PUT'])
def api_aggiorna_regola(regola_id):
    salvata = napoli_db.aggiorna_regola(regola_id, _dati())
    return _ok(messaggio=_con_nota('Regola salvata', salvata), regola=salvata)


@napoli_bp.route('/api/napoli/regole/<int:regola_id>', methods=['DELETE'])
def api_elimina_regola(regola_id):
    napoli_db.elimina_regola(regola_id)
    return _ok(messaggio='Regola eliminata: vale di nuovo il valore precedente')


# ==================== qualifiche (grafie del file master -> figura) ====================

@napoli_bp.route('/api/napoli/qualifiche', methods=['GET'])
def api_qualifiche():
    return jsonify(napoli_db.elenco_qualifiche())


@napoli_bp.route('/api/napoli/qualifiche', methods=['POST'])
def api_crea_qualifica():
    return _ok(qualifica=napoli_db.salva_qualifica(_dati(), nuova=True), messaggio='Qualifica aggiunta')


@napoli_bp.route('/api/napoli/qualifiche', methods=['PUT'])
def api_aggiorna_qualifica():
    return _ok(qualifica=napoli_db.salva_qualifica(_dati(), nuova=False), messaggio='Qualifica salvata')


@napoli_bp.route('/api/napoli/qualifiche', methods=['DELETE'])
def api_elimina_qualifica():
    napoli_db.elimina_qualifica(_dati())
    return _ok(messaggio='Qualifica eliminata')


# ==================== import del foglio presenze (master) ====================

def _file_e_lotto():
    """Il file caricato (bytes, nome) e il lotto scelto, da una richiesta multipart."""
    file = request.files.get('file')
    if file is None or not file.filename:
        raise napoli_db.DatiNonValidi('Scegli il file Excel del foglio presenze.', 'file', codice='FILE_MANCANTE')
    dati = file.read()
    valore = str(request.form.get('lotto_id') or '').strip()
    if not valore.isdigit():
        raise napoli_db.DatiNonValidi('Scegli il lotto.', 'lotto_id')
    return dati, file.filename, int(valore)


def _scelte_della_richiesta():
    testo = request.form.get('scelte') or '{}'
    try:
        return json.loads(testo)
    except ValueError:
        raise napoli_db.DatiNonValidi('Le scelte non sono arrivate bene: rifai l\'anteprima.',
                                      codice='SCELTE_NON_VALIDE') from None


@napoli_bp.route('/api/napoli/import/anteprima', methods=['POST'])
def api_import_anteprima():
    """Anteprima dell'anagrafica (modo 'anagrafica', predefinito), delle ore del mese
    (modo 'ore') o solo confronto (modo 'confronto'): non scrive nulla."""
    dati, nome, lotto_id = _file_e_lotto()
    return jsonify(import_napoli.anteprima(lotto_id, dati, nome, _scelte_della_richiesta(),
                                           request.form.get('modo')))


@napoli_bp.route('/api/napoli/import/conferma', methods=['POST'])
def api_import_conferma():
    """Importa il file dell'anteprima (stesso sha256, stesso modo, stessi dati), con le
    scelte fatte: solo l'anagrafica (predefinito) o anche le ore del mese (modo 'ore')."""
    dati, nome, lotto_id = _file_e_lotto()
    esito = import_napoli.conferma(lotto_id, dati, nome, request.form.get('sha256'),
                                   request.form.get('versione_dati'), _scelte_della_richiesta(),
                                   request.form.get('modo'))
    return _ok(**esito)


@napoli_bp.route('/api/napoli/lotti/<int:lotto_id>/import', methods=['GET'])
def api_import_storico(lotto_id):
    return jsonify(import_napoli.storico(lotto_id))


@napoli_bp.route('/api/napoli/import/<int:import_id>/annulla', methods=['POST'])
def api_import_annulla(import_id):
    return _ok(**import_napoli.annulla_import(import_id))


# ==================== anagrafiche (passo 1.6) ====================

FILTRI_ANAGRAFICHE = ('scuola_id', 'municipalita', 'figura', 'grado', 'stato', 'ruolo')


def _filtri_della_richiesta():
    """Filtri di un elenco nell'indirizzo (GET). La ricerca no: anche un codice fiscale
    scritto a meta' finirebbe nei log, quindi si manda solo con la POST di
    /api/napoli/lotti/<id>/anagrafiche/elenco."""
    if request.args.get('cerca'):
        raise napoli_db.DatiNonValidi('La ricerca non va nell\'indirizzo: ricarica la pagina e riprova.', 'cerca',
                                      codice='RICERCA_NELL_INDIRIZZO')
    return {k: request.args.get(k, '') for k in FILTRI_ANAGRAFICHE}


@napoli_bp.route('/api/napoli/lotti/<int:lotto_id>/anagrafiche', methods=['GET'])
def api_anagrafiche(lotto_id):
    """Conteggi, cosa c'e' da sistemare, scuole e municipalita' per i filtri, anagrafica vuota."""
    return jsonify(anagrafiche.riepilogo(lotto_id))


@napoli_bp.route('/api/napoli/lotti/<int:lotto_id>/anagrafiche/elenco', methods=['POST'])
def api_elenco_anagrafiche(lotto_id):
    """Un elenco (alunni, operatori, scuole o coppie) con filtri e ricerca nel corpo della
    richiesta: la pagina cerca sempre cosi', perche' un nome o un codice fiscale scritto
    nella ricerca non deve finire nell'indirizzo (e nei log)."""
    dati = _dati()
    filtri = {k: dati.get(k, '') for k in FILTRI_ANAGRAFICHE + ('cerca',)}
    return jsonify(anagrafiche.elenco(lotto_id, dati.get('parte'), filtri))


@napoli_bp.route('/api/napoli/anagrafiche/codice-fiscale', methods=['POST'])
def api_cerca_codice_fiscale():
    """Chi ha questo codice fiscale: nel corpo della richiesta, mai nell'indirizzo."""
    return jsonify(anagrafiche.cerca_codice_fiscale(_dati().get('codice_fiscale')))


@napoli_bp.route('/api/napoli/lotti/<int:lotto_id>/alunni', methods=['GET'])
def api_alunni(lotto_id):
    return jsonify(anagrafiche.elenco_alunni(lotto_id, _filtri_della_richiesta()))


@napoli_bp.route('/api/napoli/lotti/<int:lotto_id>/alunni', methods=['POST'])
def api_crea_alunno(lotto_id):
    return _ok(**anagrafiche.crea_alunno(lotto_id, _dati()))


@napoli_bp.route('/api/napoli/alunni/<int:alunno_id>', methods=['GET'])
def api_alunno(alunno_id):
    return jsonify(anagrafiche.scheda_alunno(alunno_id))


@napoli_bp.route('/api/napoli/alunni/<int:alunno_id>', methods=['PUT'])
def api_aggiorna_alunno(alunno_id):
    return _ok(**anagrafiche.aggiorna_alunno(alunno_id, _dati()))


@napoli_bp.route('/api/napoli/alunni/<int:alunno_id>', methods=['DELETE'])
def api_elimina_alunno(alunno_id):
    return _ok(**anagrafiche.elimina_alunno(alunno_id))


@napoli_bp.route('/api/napoli/alunni/<int:alunno_id>/archivia', methods=['POST'])
def api_archivia_alunno(alunno_id):
    return _ok(**anagrafiche.archivia_alunno(alunno_id, _dati()))


@napoli_bp.route('/api/napoli/alunni/<int:alunno_id>/ripristina', methods=['POST'])
def api_ripristina_alunno(alunno_id):
    return _ok(**anagrafiche.ripristina_alunno(alunno_id))


@napoli_bp.route('/api/napoli/alunni/<int:alunno_id>/pei', methods=['POST'])
def api_aggiungi_pei(alunno_id):
    return _ok(**anagrafiche.aggiungi_pei(alunno_id, _dati()))


@napoli_bp.route('/api/napoli/pei/<int:pei_id>', methods=['PUT'])
def api_aggiorna_pei(pei_id):
    return _ok(**anagrafiche.aggiorna_pei(pei_id, _dati()))


@napoli_bp.route('/api/napoli/pei/<int:pei_id>', methods=['DELETE'])
def api_elimina_pei(pei_id):
    return _ok(**anagrafiche.elimina_pei(pei_id))


@napoli_bp.route('/api/napoli/lotti/<int:lotto_id>/operatori', methods=['GET'])
def api_operatori(lotto_id):
    return jsonify(anagrafiche.elenco_operatori(lotto_id, _filtri_della_richiesta()))


@napoli_bp.route('/api/napoli/operatori', methods=['POST'])
def api_crea_operatore():
    return _ok(**anagrafiche.crea_operatore(_dati()))


@napoli_bp.route('/api/napoli/operatori/<int:operatore_id>', methods=['GET'])
def api_operatore(operatore_id):
    return jsonify(anagrafiche.scheda_operatore(operatore_id, _lotto_della_richiesta()))


@napoli_bp.route('/api/napoli/operatori/<int:operatore_id>', methods=['PUT'])
def api_aggiorna_operatore(operatore_id):
    return _ok(**anagrafiche.aggiorna_operatore(operatore_id, _dati()))


@napoli_bp.route('/api/napoli/operatori/<int:operatore_id>', methods=['DELETE'])
def api_elimina_operatore(operatore_id):
    return _ok(**anagrafiche.elimina_operatore(operatore_id))


@napoli_bp.route('/api/napoli/operatori/<int:operatore_id>/archivia', methods=['POST'])
def api_archivia_operatore(operatore_id):
    return _ok(**anagrafiche.archivia_operatore(operatore_id, _dati()))


@napoli_bp.route('/api/napoli/operatori/<int:operatore_id>/ripristina', methods=['POST'])
def api_ripristina_operatore(operatore_id):
    return _ok(**anagrafiche.ripristina_operatore(operatore_id))


@napoli_bp.route('/api/napoli/lotti/<int:lotto_id>/scuole', methods=['GET'])
def api_scuole(lotto_id):
    return jsonify(anagrafiche.elenco_scuole(lotto_id, _filtri_della_richiesta()))


@napoli_bp.route('/api/napoli/lotti/<int:lotto_id>/scuole', methods=['POST'])
def api_crea_scuola(lotto_id):
    return _ok(**anagrafiche.crea_scuola(lotto_id, _dati()))


@napoli_bp.route('/api/napoli/scuole/<int:scuola_id>', methods=['PUT'])
def api_aggiorna_scuola(scuola_id):
    return _ok(**anagrafiche.aggiorna_scuola(scuola_id, _dati()))


@napoli_bp.route('/api/napoli/scuole/<int:scuola_id>', methods=['DELETE'])
def api_elimina_scuola(scuola_id):
    return _ok(**anagrafiche.elimina_scuola(scuola_id))


@napoli_bp.route('/api/napoli/scuole/<int:scuola_id>/archivia', methods=['POST'])
def api_archivia_scuola(scuola_id):
    return _ok(**anagrafiche.archivia_scuola(scuola_id, True))


@napoli_bp.route('/api/napoli/scuole/<int:scuola_id>/ripristina', methods=['POST'])
def api_ripristina_scuola(scuola_id):
    return _ok(**anagrafiche.archivia_scuola(scuola_id, False))


@napoli_bp.route('/api/napoli/lotti/<int:lotto_id>/coppie', methods=['GET'])
def api_coppie(lotto_id):
    return jsonify(anagrafiche.elenco_coppie(lotto_id, _filtri_della_richiesta()))


@napoli_bp.route('/api/napoli/lotti/<int:lotto_id>/coppie', methods=['POST'])
def api_crea_coppia(lotto_id):
    return _ok(**anagrafiche.crea_coppia(lotto_id, _dati()))


@napoli_bp.route('/api/napoli/coppie/<int:coppia_id>', methods=['PUT'])
def api_aggiorna_coppia(coppia_id):
    return _ok(**anagrafiche.aggiorna_coppia(coppia_id, _dati()))


@napoli_bp.route('/api/napoli/coppie/<int:coppia_id>', methods=['DELETE'])
def api_elimina_coppia(coppia_id):
    return _ok(**anagrafiche.elimina_coppia(coppia_id))


@napoli_bp.route('/api/napoli/coppie/<int:coppia_id>/chiudi', methods=['POST'])
def api_chiudi_coppia(coppia_id):
    return _ok(**anagrafiche.chiudi_coppia(coppia_id, _dati()))


@napoli_bp.route('/api/napoli/coppie/<int:coppia_id>/subentro', methods=['POST'])
def api_subentro(coppia_id):
    return _ok(**anagrafiche.subentro(coppia_id, _dati()))


# ==================== Ctrl+Z delle pagine di Napoli ====================

@napoli_bp.route('/api/napoli/annulla/ultima', methods=['GET'])
def api_annulla_ultima():
    """Cosa annullerebbe Ctrl+Z su una pagina di Napoli (mai un'azione di Roma)."""
    return jsonify(napoli_db.ultima_annullabile())


@napoli_bp.route('/api/napoli/annulla', methods=['POST'])
def api_annulla():
    dati = request.get_json(silent=True) or {}
    esito = napoli_db.annulla(dati.get('id') if isinstance(dati, dict) else None)
    return _ok(messaggio=f'Annullato: {esito["descrizione"]}')

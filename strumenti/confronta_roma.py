#!/usr/bin/env python3
"""Confronto delle uscite di Roma fra due versioni di Assisto, su COPIE di un database.

Da usare prima di un rilascio, sul PC dell'utente e solo con il suo consenso
(VR7, docs/ARCHITETTURA.md, "Protezioni per Roma"):

    python strumenti/confronta_roma.py --db gestionale.db --vecchia CARTELLA_VERSIONE_VECCHIA [--nuova CARTELLA]

--vecchia e --nuova sono le cartelle delle due versioni (per esempio quella della
v1.20.1 estratta dallo ZIP e questa, che e' la predefinita per --nuova).

Il file indicato con --db non viene mai modificato: lo strumento ne fa due copie in
una cartella temporanea (con il backup di SQLite, che legge anche le modifiche
ancora nel file -wal), avvia ciascuna versione sulla sua copia in un processo a
parte (strumenti/fotografa_roma.py: all'avvio la versione aggiorna la copia come
farebbe con il database vero), fotografa tutte le rotte di Roma con lo stesso
orologio fermo e confronta le due fotografie. Stampa SOLO conteggi e nomi delle
rotte, mai dati; copie e fotografie si cancellano alla fine.

Esce con 0 se le uscite di Roma sono identiche, 1 se ci sono differenze, 2 se non
e' stato possibile fotografare.
"""
import argparse
import datetime
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import tempfile

try:
    import fotografa_roma                      # avviato come script da strumenti/
except ImportError:                            # importato come strumenti.confronta_roma
    from strumenti import fotografa_roma

FOTOGRAFA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fotografa_roma.py')


def copia_database(origine, destinazione):
    """Copia coerente del database (anche con il file -wal) senza modificarlo."""
    src = sqlite3.connect(pathlib.Path(origine).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        dst = sqlite3.connect(destinazione)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _tipo_errore(stderr):
    """Solo il tipo dell'eccezione (il messaggio potrebbe contenere dati)."""
    for riga in reversed(stderr.decode('utf-8', errors='replace').strip().splitlines()):
        m = re.match(r'([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt))\b', riga)
        if m:
            return m.group(1)
    return 'errore'


def fotografa_versione(codice, copia, uscita, oggi, lavoro):
    """Fotografia di una versione in un processo separato; None se riuscita,
    altrimenti il tipo dell'errore. L'output del processo non si mostra."""
    r = subprocess.run([sys.executable, FOTOGRAFA, '--db', copia, '--codice', codice,
                        '--uscita', uscita, '--oggi', oggi],
                       cwd=lavoro, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return None if r.returncode == 0 and os.path.exists(uscita) else _tipo_errore(r.stderr)


def confronta(db, vecchia, nuova, oggi, scrivi=print):
    with tempfile.TemporaryDirectory(prefix='confronta_roma_') as lavoro:
        foto = {}
        for nome, codice in (('vecchia', vecchia), ('nuova', nuova)):
            cartella = os.path.join(lavoro, nome)
            os.makedirs(cartella)
            copia = os.path.join(cartella, 'gestionale.db')
            copia_database(db, copia)
            uscita = os.path.join(cartella, 'fotografia.json')
            errore = fotografa_versione(codice, copia, uscita, oggi, cartella)
            if errore:
                scrivi(f'La fotografia della versione {nome} non e\' riuscita ({errore}).')
                return 2
            foto[nome] = fotografa_roma.leggi(uscita)
    d = fotografa_roma.differenze(foto['vecchia'], foto['nuova'])
    n_url = sum(len(v) for v in foto['nuova'].get('rotte', {}).values())
    scrivi(f"Versione vecchia {fotografa_roma.leggi_versione(vecchia) or '?'}, "
           f"nuova {fotografa_roma.leggi_versione(nuova) or '?'}; orologio fermo al {oggi}.")
    scrivi(f"Rotte di Roma confrontate: {d['identiche'] + len(d['diverse'])} ({n_url} indirizzi).")
    scrivi(f"Identiche: {d['identiche']}. Diverse: {len(d['diverse'])}.")
    for regola, n in d['diverse'].items():
        scrivi(f'  diversa: {regola} ({n} indirizzi)')
    for chiave, testo in (('solo_prima', 'solo nella vecchia'), ('solo_dopo', 'solo nella nuova')):
        for regola in d[chiave]:
            scrivi(f'  {testo}: {regola}')
    return 1 if d['diverse'] or d['solo_prima'] or d['solo_dopo'] else 0


def main(argv=None):
    p = argparse.ArgumentParser(description='Confronta le uscite di Roma di due versioni su copie di un database '
                                            '(stampa solo conteggi e nomi delle rotte).')
    p.add_argument('--db', required=True, help='database da confrontare (non viene modificato)')
    p.add_argument('--vecchia', required=True, help='cartella della versione di riferimento')
    p.add_argument('--nuova', default=fotografa_roma.CARTELLA_PROGETTO, help='cartella della versione nuova')
    p.add_argument('--oggi', default=datetime.date.today().isoformat(),
                   help="data dell'orologio fermo, uguale per le due versioni (AAAA-MM-GG)")
    a = p.parse_args(argv)
    for cartella in (a.vecchia, a.nuova):
        if not os.path.exists(os.path.join(cartella, 'app.py')):
            p.error(f'{cartella}: non e\' la cartella di una versione di Assisto (manca app.py)')
    if not os.path.isfile(a.db):
        p.error(f'{a.db}: file non trovato')
    return confronta(os.path.abspath(a.db), os.path.abspath(a.vecchia), os.path.abspath(a.nuova), a.oggi)


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Reimposta la password del gestionale SENZA cancellare i dati.

Da usare se hai dimenticato la password. Funziona solo sul computer dove risiede
il database (avere accesso al file = autorizzazione), quindi non apre falle di
sicurezza. I dati (utenti, rendicontazioni, ecc.) NON vengono toccati.

Uso:
    python reset_password.py                 # chiede la nuova password a schermo
    python reset_password.py --password XYZ  # imposta la password passata
    python reset_password.py --username mario --password XYZ
"""
import argparse
import getpass
import sys

from werkzeug.security import generate_password_hash

import database as db

MIN_LEN = 8


def main():
    parser = argparse.ArgumentParser(description="Reimposta la password del gestionale OEPAC.")
    parser.add_argument('--password', help="Nuova password (se omessa, verra' chiesta).")
    parser.add_argument('--username', help="Nuovo username (opzionale).")
    args = parser.parse_args()

    db.init_db()

    if not db.auth_is_configured():
        print("Nessun utente configurato: avvia il gestionale e completa la pagina di setup.")
        return 1

    utente = db.auth_get_user()
    print(f"Utente attuale: {utente.get('username', '(sconosciuto)')}")

    nuova = args.password
    if not nuova:
        nuova = getpass.getpass("Nuova password (min 8 caratteri): ")
        conferma = getpass.getpass("Conferma password: ")
        if nuova != conferma:
            print("Le password non coincidono. Nessuna modifica effettuata.")
            return 1

    if len(nuova) < MIN_LEN:
        print(f"La password deve avere almeno {MIN_LEN} caratteri. Nessuna modifica effettuata.")
        return 1

    db.auth_update_credentials(
        username=args.username,
        password_hash=generate_password_hash(nuova),
    )
    print("Password reimpostata con successo. I tuoi dati sono intatti.")
    if args.username:
        print(f"Nuovo username: {args.username}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

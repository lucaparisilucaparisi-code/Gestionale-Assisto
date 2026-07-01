# Architettura & guida sviluppatore — Gestionale OEPAC

Nota tecnica per chi sviluppa. Per l'uso e l'installazione vedi il `README.md`.

## Struttura dei moduli

| File | Responsabilità |
|------|----------------|
| `app.py` | Applicazione Flask: route pagine e molte API, autenticazione (sessione + WebAuthn), import. Registra i blueprint sotto. |
| `database.py` | Tutto l'accesso ai dati SQLite: schema/migrazioni, CRUD, calcoli di dominio. |
| `routes_export.py` | Blueprint export (Excel, PDF, Word). |
| `routes_backup.py` | Blueprint backup/ripristino (`/api/backup...`). |
| `routes_migrazione.py` | Blueprint migrazione dati JSON e audit log (`/api/migrazione`, `/api/audit`). |
| `routes_report_locale.py` | Blueprint reportistica DD, recuperi, override (`/reportistica-locale`, `/api/dd`, `/api/recuperi`, override). |
| `validators.py` | Validazione input condivisa (`validate_string/number/integer`). |
| `config.py` | Costanti economiche, parametri, logging e l'helper `calcola_fatturazione`. |
| `import_*.py` | Parsing dei file Excel (anagrafica e rendicontazione). |
| `templates/`, `static/` | UI (Jinja2, CSS, JS, PWA). |
| `tests/` | Suite pytest su DB temporaneo (non tocca `gestionale.db`). |

## Regole di dominio da NON duplicare

Queste logiche hanno una **sola** implementazione condivisa: usarla sempre, mai
reimplementarla inline (a schermo, in SQL o negli export).

- **Fatturazione** → `config.calcola_fatturazione(ore)` ritorna `(imponibile, iva, totale)`.
  Arrotonda una sola volta sull'aggregato: **non** sommare valori già arrotondati,
  e **non** hardcodare la tariffa o il moltiplicatore IVA nelle query.
- **Media prevista** → `database.calcola_media_prevista(monte_ore, giorni)`.
- **Giorni lavorativi effettivi** → `database.risolvi_giorni_lavorativi(giorni_calendario)`
  (regola unica: calendario → `GIORNI_LAVORATIVI_DEFAULT`). Deve valere identica in
  vista mensile, storico e aggregati.

## Convenzioni

- **Suffissi `_60` / `_100`**: `_60` = ore in formato sessagesimale (base 60'),
  `_100` = ore in formato centesimale/decimale (base 100'). Nel dataset attuale i due
  valori coincidono (i dati sono importati già in centesimale); le colonne restano
  distinte per compatibilità con i report.
- **Naming**: verbi tecnici/CRUD in inglese (`get_`, `update_`, `delete_`), concetti di
  dominio in italiano (`calcola_media_prevista`, `commessa`, `rendicontazione`). Le
  colonne DB sono in italiano. Mantenere questa coerenza nelle nuove funzioni.
- **Credito/Debito**: `media_con_assenza - ore_lavorate`. Positivo = **debito** (ore da
  recuperare), negativo = **credito**.

## Database

- Connessioni tramite `database.get_db_context()` (context manager con commit su
  uscita pulita e rollback su errore). La factory unica `_connect()` imposta
  `foreign_keys=ON`, `busy_timeout` e `journal_mode=WAL`.
- Le FOREIGN KEY sono **applicate**: le cancellazioni con `ON DELETE CASCADE`
  funzionano (niente righe orfane). Attenzione a inserire sempre i parent prima dei figli.
- Migrazioni: attualmente `ALTER TABLE` idempotenti in `init_db`, con
  `PRAGMA user_version` come baseline. Le nuove migrazioni vanno numerate a partire da lì.
- Backup/restore usano l'API `sqlite3.backup()` (consistente con WAL). Il ripristino
  valida il nome del file (no path traversal).

## Sviluppo

```bash
pip install -r requirements-dev.txt
pytest                 # test
ruff check .           # lint
ruff check . --fix     # lint con fix automatici
```

La CI (`.github/workflows/ci.yml`) esegue ruff + pytest su Python 3.9 e 3.12 ad ogni push/PR.

## Refactoring pianificati (da fare come interventi dedicati e revisionati)

Non vanno affrontati "di corsa" perché toccano molte route con copertura di test
ancora parziale; ognuno merita una PR isolata con test aggiuntivi prima del merge:

1. **Split di `app.py` in blueprint per dominio** — *in corso*. Estratti finora:
   backup, migrazione/audit, reportistica/override (+ `validators.py` condiviso).
   Da estrarre: statistiche (route sparse), documenti/note/assenze, dipendenti/turni,
   auth. Regola seguita: spostare solo gruppi le cui route NON sono referenziate da
   `url_for` (endpoint API chiamati via fetch), così i nomi endpoint possono cambiare
   senza rompere i template; verificare ogni estrazione con lo smoke test di tutte le
   route GET + la suite.
2. **Layer di servizio**: estrarre lo SQL grezzo ancora presente in alcune route
   "grasse" (es. `api_migrazione_importa`) in funzioni di dominio in `database.py`.
3. **Type hints progressivi** sulle funzioni più riusate + `mypy` non bloccante in CI.
4. **Consolidamento tabelle override legacy** (`get_report_locale_commessa`): unificare
   la doppia lettura vecchia/nuova con una migrazione dati versionata.

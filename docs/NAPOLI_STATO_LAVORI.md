# Sezione Napoli: stato dei lavori e come riprendere

Nota di lavoro per riprendere lo sviluppo della sezione Napoli (assistenza specialistica, Comune di Napoli).
Non contiene dati personali. Il disegno tecnico è in `docs/ARCHITETTURA.md`, sezioni "Protezioni per Roma"
e "Sezione Napoli".

## Fatto (sul branch, verificato da un revisore indipendente)

| Passo | Contenuto |
|---|---|
| Fase 0 | Protezioni per Roma: fotografia delle uscite di Roma (`tests/golden`), invarianza con dati Napoli, inventario delle rotte, separazione statica, `strumenti/confronta_roma.py` |
| 1.1-1.2 | Schema `napoli_*` (migrazioni 2-4) e calcoli puri (`napoli_calcoli.py`, `config_napoli.py`) |
| 1.3 | Impostazioni: cooperativa, destinatario, lotti, contratti applicativi, tariffe e regole con data, qualifiche; procedura "Crea il primo lotto" |
| 1.4-1.5 | Import del file Excel: azione principale "Carica l'anagrafica"; le ore del mese solo come opzione secondaria |
| 1.6 | Anagrafiche: alunni, operatori, scuole e plessi, coppie, PEI per figura (v1.21.0) |
| 1.8 | Ore del coordinatore: totale mensile per lotto + grado + contratto |
| 1.7 | Griglia presenze del mese con VERIFICA settimanali e credito/debito di Napoli. L'ultima correzione (`ea2fd4a`) va ancora riverificata |
| Roma | Monte ore del mese nelle pagine, plurali degli avvisi, etichette dei confronti (nessun numero cambiato) |

## In corso al momento della pausa

**1.9 Prospetto fattura.** Il lavoro è stato fermato dall'utente prima della verifica. È salvato nel commit
"lavoro in corso" che segue questa nota: backend `napoli_fattura.py`, `export_napoli.py`, pagina
`templates/napoli_fattura.html`. Per riprendere:

1. Completare test, export Excel e stampa A4.
2. Superare la verifica indipendente. Criterio: con dati inventati equivalenti alla fattura di riferimento
   di giugno 2026 il prospetto torna al centesimo su somma, ritenuta 0,50%, imponibile, IVA 5%, totale e
   "da pagare" (split payment).

## Da fare, in ordine

1. Riverifica della griglia presenze (1.7, commit `ea2fd4a`).
2. **1.10 Report mensile per il Municipio.**
   - Lo stesso modello del file Excel che la cooperativa invia oggi: colonne fisse, un giorno per colonna
     dal lunedì al sabato, VERIFICA con `=SUM`, celle color salmone per l'alunno assente, note
     "Alunno assente: ...".
   - Arricchito con:
     - copertina;
     - totale per riga;
     - programmato e svolto;
     - recuperi e sostituto;
     - legenda;
     - riepiloghi per figura, scuola e municipalità;
     - controlli;
     - firme.
   - Prototipo del formato: lettore e scrittore del master usati per l'import.
3. **1.11 Rilascio v1.22.0**: blocco `napoli` nel trasloco JSON, manuale nel README, `docs/ARCHITETTURA.md`.
4. **Fase 1B**:
   - 1.12 calendario di Napoli;
   - 1.13 programmazione settimanale;
   - 1.14 "Prepara il mese";
   - 1.15 stampa dei fogli firma precompilati in A4;
   - 1.16 registrazione digitale del foglio firma;
   - 1.17 cruscotto del mese e rilascio v1.23.0.
5. **Fase 2**: assenze degli operatori, registro delle ore non svolte, recuperi con i limiti del capitolato,
   banca ore con usi A-D, scadenze e decurtazione, fattura di fase 2 senza doppi conteggi (rilascio v1.24.0).
6. Osservazioni minori dei revisori ancora aperte: vedi i messaggi di commit "correzioni dalla revisione".

## Regole confermate dall'utente (sintesi)

1. **Alunno assente**: si rendiconta metà dell'orario programmato. Se l'operatore recupera, si rendiconta
   solo il recupero, senza doppio conteggio.
2. **Assemblee, uscite ed eventi**: contano le ore effettivamente svolte.
3. **Sigle F, M, F perm** (ferie, malattia, permesso dell'operatore): 0 ore se non c'è un sostituto.
4. **Ritardo o uscita anticipata dell'alunno**: ore svolte più metà della parte persa.
5. **Recupero in un mese successivo** di un'assenza già fatturata a metà: si fattura il recupero meno la metà
   già fatturata.
6. **Tariffe**: IVA esclusa, con data di validità. Proposte: Asacom 23,44; Educatore e Tiflologo 24,28;
   Psicologo e Coordinatore 29,66; valide fino al 31/01/2027. LIS da configurare.
7. **Fattura**:
   - una per lotto + grado (inferiore o superiore) + contratto applicativo + periodo, anche parziale;
   - coordinatore fatturato a ore, con il totale mensile inserito a mano;
   - ritenuta 0,50%, IVA 5% in split payment;
   - "da pagare" = imponibile.
8. **Municipalità**: è quella della scuola o del plesso.
9. **Import**: serve a creare l'anagrafica. Le ore dei mesi passati non si caricano.
10. **Credito/debito**: c'è per ogni commessa, con le sue regole.
    - Roma resta com'è.
    - Napoli: previste = ore programmate (o PEI ripartito, con avviso); erogate = ore riconosciute; stessa
      convenzione della Rendicontazione di Roma.
11. **Ambiente dell'utente**: Windows, schermo 1536x864 e 1366x768, Excel che blocca i file aperti, stampa A4
    da Edge/Chrome.
12. **Privacy**: mai dati reali nel repository o nei test; codici fiscali sempre mascherati; nessun dato
    sanitario.

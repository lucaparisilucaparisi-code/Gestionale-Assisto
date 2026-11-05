/* Sezione Napoli (PROGETTO §6): il codice delle pagine /napoli.
 *
 * Usa solo le API /api/napoli e gli aiuti comuni di app.js (apiCall, showToast,
 * showConfirmDialog, openModal, closeModal, escapeHtml, formatDataIT, rigaDati, icona,
 * MenuAzioni, FormValidator, setButtonLoading). Le pagine di Roma non caricano questo file.
 *
 * - NapoliComune: il lotto scelto (ricordato nel browser, sempre dentro try/catch: se il
 *   browser non lo ricorda si riparte dal primo lotto), le figure, gli errori dei campi e
 *   Ctrl+Z di Napoli. window.annullaPagina: app.js lo usa al posto dell'annulla di Roma,
 *   cosi' Ctrl+Z su una pagina di Napoli non annulla mai un'azione di Roma (e viceversa);
 * - NapoliProcedura: "Crea il primo lotto" (anche "Nuovo lotto") in tre passi;
 * - NapoliMese (con NapoliCoordinatore: le ore del coordinatore del mese, passo 1.8),
 *   NapoliPresenze (la griglia del mese, passo 1.7), NapoliFattura (i prospetti fattura del
 *   mese, passo 1.9), NapoliAnagrafiche, NapoliImport e NapoliImpostazioni: le schede
 *   (Anagrafiche: alunni, operatori, scuole e plessi, coppie, con filtri, schede e moduli;
 *   Importa: dal file Excel "master" l'anagrafica, l'azione principale, o in una parte
 *   secondaria le ore di un mese; anteprima, scelte da confermare, caricamento e
 *   "Annulla il caricamento").
 * Ogni controllo vero e' sul server: qui si guardano solo i campi vuoti, per non far
 * aspettare la risposta.
 */
'use strict';

const NAPOLI_CHIAVE_LOTTO = 'napoli.lotto';
const NAPOLI_MODELLO_NOME = 'NAPOLI LOTTO {numero}';   // come config_napoli.LOTTO_PROPOSTO['nome']
const NAPOLI_NOMI_GRADO = { inferiore: 'Grado inferiore', superiore: 'Grado superiore', '': 'Tutti e due i gradi' };
const NAPOLI_ICONE_STATO = {
    ok: 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z',
    avviso: 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z',
    manca: 'M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z',
};
const NAPOLI_CLASSE_STATO = { ok: 'da-fare-ok', avviso: 'da-fare-warning', manca: 'da-fare-danger' };
const NAPOLI_GIORNI = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica'];
const NAPOLI_MESI = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio', 'agosto',
    'settembre', 'ottobre', 'novembre', 'dicembre'];

// ==================== aiuti ====================

function napoliSvg(d, px = 20, classe = '') {
    return `<svg class="${classe}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" width="${px}" height="${px}" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${d}"/></svg>`;
}

function napoliOggi() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function napoliGiornoDopo(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
    if (!m) return '';
    const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]) + 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function napoliPeriodo(dal, al) {
    return al ? `dal ${formatDataIT(dal)} al ${formatDataIT(al)}` : `dal ${formatDataIT(dal)}, senza fine`;
}

function napoliValeOggi(riga) {
    const oggi = napoliOggi();
    return riga.valido_da <= oggi && (!riga.valido_a || oggi <= riga.valido_a);
}

/** La descrizione della figura dice qualcosa in piu' del nome breve (Asacom: si'; Psicologo: no). */
function napoliDescrizioneDiversa(f) {
    return String(f.descrizione || '').toLowerCase() !== String(f.nome || '').toLowerCase();
}

/** Sostituisce i segnaposto {nome} conosciuti (come napoli_calcoli.riempi_modello). */
function napoliRiempiModello(modello, valori) {
    return String(modello || '').replace(/\{(\w+)\}/g, (tutto, nome) => (nome in valori ? String(valori[nome]) : tutto));
}

/** Il nome di un lotto segue il suo numero finche' e' quello proposto (o vuoto): cambiando
 *  "Lotto 2" in "Lotto 3", "NAPOLI LOTTO 2" diventa "NAPOLI LOTTO 3"; un nome scritto a
 *  mano resta com'e'. modello: una funzione che da' il modello del nome proposto. */
function napoliNomeSegueNumero(nome, numero, modello) {
    numero.addEventListener('change', () => {
        const m = modello() || NAPOLI_MODELLO_NOME;
        const scritto = nome.value.trim();
        const proposti = [...numero.options].map(o => napoliRiempiModello(m, { numero: o.value }));
        if (!scritto || proposti.includes(scritto)) nome.value = napoliRiempiModello(m, { numero: numero.value });
    });
}

/** Il nome dice un numero di lotto diverso da quello scelto ("NAPOLI LOTTO 2", Lotto 3)? */
function napoliNomeENumeroDiversi(nome, numero) {
    const m = /\blotto\s*(\d+)\b/i.exec(nome || '');
    return !!m && Number(m[1]) !== Number(numero);
}

/** Valori dei campi [data-campo] di un contenitore: {campo: testo}. */
function napoliLeggiCampi(contenitore) {
    const dati = {};
    contenitore.querySelectorAll('input[data-campo], select[data-campo], textarea[data-campo]').forEach(el => {
        dati[el.dataset.campo] = el.value.trim();
    });
    return dati;
}

function napoliRiempiCampi(contenitore, dati) {
    contenitore.querySelectorAll('input[data-campo], select[data-campo], textarea[data-campo]').forEach(el => {
        const v = dati[el.dataset.campo];
        el.value = v === null || v === undefined ? '' : String(v);
    });
}

function napoliPulisciErrori(contenitore) {
    contenitore.querySelectorAll('.field-error').forEach(el => el.remove());
    contenitore.querySelectorAll('.error').forEach(el => el.classList.remove('error'));
}

/** Il testo di un errore per l'utente: senza collegamento il browser dice "Failed to fetch"
 *  (in inglese, tecnico), qui diventa una frase in italiano. */
function napoliTestoErrore(err, riserva = 'Operazione non riuscita: riprova.') {
    if (err instanceof TypeError && !('status' in err)) {
        return 'Il collegamento con Assisto si è interrotto: controlla che il programma sia aperto e riprova.';
    }
    return (err && err.message) || riserva;
}

/** Errore di un'API: il messaggio vicino al campo sbagliato (se il server lo dice) e in un avviso. */
function napoliMostraErrore(err, contenitore) {
    const messaggio = napoliTestoErrore(err);
    const campo = err && err.data && err.data.campo;
    if (contenitore) napoliPulisciErrori(contenitore);
    const el = campo && contenitore ? contenitore.querySelector(`[data-campo="${CSS.escape(campo)}"]`) : null;
    if (el) {
        // il messaggio sta sotto il campo: niente avviso in basso, che coprirebbe il modulo
        el.closest('details')?.setAttribute('open', '');
        FormValidator.showFieldError(el, messaggio);
        el.focus?.();
        el.scrollIntoView?.({ block: 'nearest' });
        return;
    }
    showToast(messaggio, 'error', 9000);
}

function napoliCampoObbligatorio(input, messaggio) {
    if (input.value.trim()) return true;
    input.closest('details')?.setAttribute('open', '');
    FormValidator.showFieldError(input, messaggio);
    input.focus();
    return false;
}

// ==================== comune a tutte le pagine ====================

const NapoliComune = {
    lotti: [],
    lotto: null,
    figure: null,
    alCambioLotto: null,
    dopoAnnulla: null,
    primaDiAnnullare: null,

    lottoRicordato() {
        try { return Number(localStorage.getItem(NAPOLI_CHIAVE_LOTTO)) || null; } catch (e) { return null; }
    },

    ricorda(id) {
        try { localStorage.setItem(NAPOLI_CHIAVE_LOTTO, String(id)); } catch (e) { /* il browser non ricorda: pazienza */ }
    },

    async caricaLotti(preferito) {
        this.lotti = await apiCall('/api/napoli/lotti');
        const id = Number(preferito) || (this.lotto && this.lotto.id) || this.lottoRicordato();
        this.lotto = this.lotti.find(l => l.id === id) || this.lotti[0] || null;
        if (this.lotto) this.ricorda(this.lotto.id);
        this.disegnaScelta();
        return this.lotto;
    },

    disegnaScelta() {
        const box = document.getElementById('napoli-scelta-lotto');
        const scelta = document.getElementById('napoli-lotto');
        if (!box || !scelta) return;
        box.hidden = this.lotti.length === 0;
        scelta.innerHTML = this.lotti.map(l =>
            `<option value="${l.id}">${escapeHtml(l.nome)}${l.attivo ? '' : ' (non attivo)'}</option>`).join('');
        if (this.lotto) scelta.value = String(this.lotto.id);
        if (!scelta.dataset.pronta) {
            scelta.dataset.pronta = '1';
            scelta.addEventListener('change', () => {
                this.lotto = this.lotti.find(l => String(l.id) === scelta.value) || null;
                if (this.lotto) this.ricorda(this.lotto.id);
                if (typeof this.alCambioLotto === 'function') this.alCambioLotto();
            });
        }
    },

    async caricaFigure() {
        if (!this.figure) this.figure = await apiCall('/api/napoli/figure');
        return this.figure;
    },

    descrizioneFigura(codice) {
        const f = (this.figure || []).find(x => x.codice === codice);
        return f ? f.descrizione : codice;
    },

    nomeFigura(codice) {
        const f = (this.figure || []).find(x => x.codice === codice);
        return f ? f.nome : codice;
    },

    /** Le figure per una tendina; proposta: la figura suggerita (indicata, non scelta). */
    opzioniFigure(scelta, proposta = null) {
        return (this.figure || []).map(f =>
            `<option value="${escapeHtml(f.codice)}"${f.codice === scelta ? ' selected' : ''}>${escapeHtml(f.nome)}${napoliDescrizioneDiversa(f) ? ` (${escapeHtml(f.descrizione)})` : ''}${f.codice === proposta ? ' — proposta' : ''}</option>`).join('');
    },

    /** Ctrl+Z delle pagine di Napoli: prima si chiede, con la descrizione e l'ora della modifica. */
    async annulla() {
        // conferma gia' aperta (una che si sta chiudendo resta nella pagina ancora 300 ms: non conta)
        if (document.querySelector('#confirm-dialog-overlay.active')) return;
        // le caselle ancora da salvare partono prima: Ctrl+Z annulla l'ultima modifica davvero fatta
        // (se non si salvano, la pagina lo dice e non si annulla niente)
        if (typeof this.primaDiAnnullare === 'function' && (await this.primaDiAnnullare()) === false) return;
        let info;
        try {
            info = await apiCall('/api/napoli/annulla/ultima');
        } catch (e) {
            showToast(e.message || 'Annulla non disponibile', 'warning');
            return;
        }
        if (info.non_annullabile) {
            // l'ultima azione ha cambiato dati personali (o eliminato una persona): i valori di
            // prima non restano in memoria, quindi Ctrl+Z non la annulla e lo dice
            const n = info.non_annullabile;
            showToast(`«${n.descrizione}» (${n.quando}) non si annulla con Ctrl+Z: ${n.motivo}.`, 'warning', 10000);
            return;
        }
        if (!info.azione) {
            showToast(info.scadute
                ? `Niente da annullare: le modifiche di più di ${info.ore_validita} ore fa non si possono più annullare`
                : 'Nessuna modifica di Napoli da annullare', 'info');
            return;
        }
        showConfirmDialog(
            'Annullare questa modifica?',
            `${info.azione.descrizione}${info.azione.chi ? ` (${info.azione.chi})` : ''}. Modifica fatta il ${info.azione.quando}.`,
            async () => {
                try {
                    const r = await apiCall('/api/napoli/annulla', { method: 'POST', body: JSON.stringify({ id: info.azione.id }) });
                    showToast(r.messaggio || 'Modifica annullata', 'success');
                    if (typeof this.dopoAnnulla === 'function') await this.dopoAnnulla();
                    else window.location.reload();
                } catch (e) {
                    showToast(e.message || 'Annullamento non riuscito', 'error', 9000);
                }
            },
            { confirmText: 'Annulla la modifica', cancelText: 'Lascia com\'è', type: 'warning' }
        );
    },
};

// app.js: Ctrl+Z su questa pagina chiama questa funzione invece dell'annulla di Roma
window.annullaPagina = () => NapoliComune.annulla();

// ==================== procedura "Crea il primo lotto" ====================

const NapoliProcedura = {
    passo: 1,
    proposta: null,
    dopo: null,
    pronta: false,

    el(id) { return document.getElementById(id); },

    prepara() {
        if (this.pronta) return;
        this.pronta = true;
        napoliNomeSegueNumero(this.el('proc-nome'), this.el('proc-numero'), () => this.proposta && this.proposta.modello_nome);
        this.el('proc-avanti').addEventListener('click', () => this.avanti());
        this.el('proc-indietro').addEventListener('click', () => this.vai(Math.max(1, this.passo - 1)));
        this.el('napoli-modal-procedura').addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && e.target.matches('input')) { e.preventDefault(); this.avanti(); }
        });
    },

    /** Apre la procedura con i valori proposti; dopo(lotto) dopo la creazione. */
    async apri(dopo) {
        this.prepara();
        this.dopo = dopo;
        try {
            this.proposta = await apiCall('/api/napoli/lotti/proposta');
            await NapoliComune.caricaFigure();
        } catch (e) {
            showToast(e.message || 'Proposta non disponibile', 'error');
            return;
        }
        const p = this.proposta;
        if (!p.numeri_liberi.length) {
            showToast('Ci sono già cinque lotti: non se ne possono aggiungere altri.', 'warning', 7000);
            return;
        }
        this.el('proc-titolo').textContent = NapoliComune.lotti.length ? 'Nuovo lotto' : 'Crea il primo lotto';
        this.el('proc-nome').value = p.lotto.nome || '';
        this.el('proc-numero').innerHTML = p.numeri_liberi.map(n => `<option value="${n}">Lotto ${n}</option>`).join('');
        this.el('proc-numero').value = String(p.lotto.numero_lotto);
        this.el('proc-municipalita').value = '';
        this.el('proc-cig').value = '';
        this.el('proc-codice-univoco').value = p.lotto.codice_univoco_ufficio || '';
        this.el('proc-riferimento').value = p.lotto.riferimento_amministrativo || '';
        this.el('proc-dal').value = p.valido_da || '';
        this.el('proc-al').value = p.valido_a || '';
        this.el('proc-tariffe').innerHTML = p.tariffe.map((t, i) => `
            <tr>
                <td><label for="proc-tariffa-${i}"><span class="napoli-figura-nome">${escapeHtml(NapoliComune.nomeFigura(t.figura))}</span>
                    ${napoliDescrizioneDiversa({ nome: NapoliComune.nomeFigura(t.figura), descrizione: t.descrizione })
                        ? `<span class="napoli-figura-descrizione">${escapeHtml(t.descrizione)}</span>` : ''}</label></td>
                <td class="napoli-numero">
                    <input type="text" id="proc-tariffa-${i}" class="form-control" inputmode="decimal" autocomplete="off"
                           data-figura="${escapeHtml(t.figura)}" data-campo="tariffe.${i}" value="${escapeHtml(t.tariffa)}"
                           placeholder="nessuna">
                </td>
            </tr>`).join('');
        napoliPulisciErrori(this.el('napoli-modal-procedura'));
        this.vai(1);
        openModal('napoli-modal-procedura');
    },

    vai(n) {
        this.passo = n;
        const modale = this.el('napoli-modal-procedura');
        modale.querySelectorAll('[data-pagina-passo]').forEach(s => { s.hidden = Number(s.dataset.paginaPasso) !== n; });
        modale.querySelectorAll('.napoli-passi li').forEach(li => {
            const k = Number(li.dataset.passo);
            li.classList.toggle('attivo', k === n);
            li.classList.toggle('fatto', k < n);
            if (k === n) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
        });
        this.el('proc-indietro').style.visibility = n === 1 ? 'hidden' : 'visible';
        this.el('proc-avanti').textContent = n === 3 ? 'Crea il lotto' : 'Avanti';
        const primo = modale.querySelector(`[data-pagina-passo="${n}"] input, [data-pagina-passo="${n}"] select`);
        if (primo) setTimeout(() => primo.focus(), 50);
        else setTimeout(() => this.el('proc-avanti').focus(), 50);
    },

    datiLotto() {
        const p = this.proposta.lotto;
        return {
            nome: this.el('proc-nome').value.trim(),
            numero_lotto: Number(this.el('proc-numero').value),
            municipalita: this.el('proc-municipalita').value.trim(),
            cig: this.el('proc-cig').value.trim(),
            codice_univoco_ufficio: this.el('proc-codice-univoco').value.trim(),
            riferimento_amministrativo: this.el('proc-riferimento').value.trim(),
            oggetto_fattura: p.oggetto_fattura,
            nota_fattura: p.nota_fattura,
        };
    },

    tariffe() {
        return [...this.el('proc-tariffe').querySelectorAll('input[data-figura]')]
            .map(input => ({ figura: input.dataset.figura, tariffa: input.value.trim() }));
    },

    controllaPasso1() {
        const modale = this.el('napoli-modal-procedura');
        napoliPulisciErrori(modale);
        return napoliCampoObbligatorio(this.el('proc-nome'), 'Scrivi il nome del lotto.')
            && napoliCampoObbligatorio(this.el('proc-municipalita'), 'Scrivi le municipalità del lotto (per esempio 1 e 2).');
    },

    controllaPasso2() {
        napoliPulisciErrori(this.el('napoli-modal-procedura'));
        if (!napoliCampoObbligatorio(this.el('proc-dal'), 'Scegli da quando valgono le tariffe.')) return false;
        const al = this.el('proc-al');
        if (al.value && al.value < this.el('proc-dal').value) {
            FormValidator.showFieldError(al, 'La data di fine viene prima di quella di inizio.');
            al.focus();
            return false;
        }
        return true;
    },

    riepilogo() {
        const l = this.datiLotto();
        const tariffe = this.tariffe().filter(t => t.tariffa);
        const senza = this.tariffe().filter(t => !t.tariffa).map(t => NapoliComune.nomeFigura(t.figura));
        const al = this.el('proc-al').value;
        const diversi = napoliNomeENumeroDiversi(l.nome, l.numero_lotto);
        this.el('proc-riepilogo').innerHTML = [
            diversi ? `<div class="alert alert-warning napoli-avviso-nome">Il nome "${escapeHtml(l.nome)}" non corrisponde al numero scelto (Lotto ${l.numero_lotto}): controlla che sia giusto, oppure torna indietro e correggilo.</div>` : '',
            rigaDati('Nome', escapeHtml(l.nome)),
            rigaDati('Numero', `Lotto ${l.numero_lotto}`),
            rigaDati('Municipalità', escapeHtml(l.municipalita)),
            rigaDati('CIG', l.cig ? escapeHtml(l.cig) : '<span class="napoli-vuoto">da aggiungere</span>'),
            rigaDati('Codice univoco ufficio', escapeHtml(l.codice_univoco_ufficio)),
            rigaDati('Riferimento amministrativo', escapeHtml(l.riferimento_amministrativo)),
            rigaDati('Tariffe IVA esclusa', tariffe.length
                ? tariffe.map(t => `${escapeHtml(NapoliComune.nomeFigura(t.figura))} ${escapeHtml(t.tariffa)} €`).join('<br>')
                : '<span class="napoli-vuoto">nessuna</span>'),
            rigaDati('Valgono', escapeHtml(napoliPeriodo(this.el('proc-dal').value, al))),
            senza.length ? rigaDati('Senza tariffa', escapeHtml(senza.join(', '))) : '',
        ].join('');
    },

    async avanti() {
        if (this.passo === 1) {
            if (this.controllaPasso1()) this.vai(2);
        } else if (this.passo === 2) {
            if (this.controllaPasso2()) { this.riepilogo(); this.vai(3); }
        } else {
            await this.invia();
        }
    },

    async invia() {
        const pulsante = this.el('proc-avanti');
        if (pulsante.disabled) return;
        setButtonLoading(pulsante, true);
        try {
            const r = await apiCall('/api/napoli/lotti/procedura', {
                method: 'POST',
                body: JSON.stringify({
                    lotto: this.datiLotto(), tariffe: this.tariffe(),
                    valido_da: this.el('proc-dal').value, valido_a: this.el('proc-al').value,
                }),
            });
            closeModal('napoli-modal-procedura');
            showToast(`${r.messaggio}. Se c'è un errore, Ctrl+Z annulla la creazione.`, 'success', 7000);
            NapoliComune.ricorda(r.lotto.id);
            if (typeof this.dopo === 'function') await this.dopo(r.lotto);
        } catch (e) {
            const campo = (e.data && e.data.campo) || '';
            this.vai(campo.startsWith('tariffe') || campo.startsWith('valido') ? 2 : 1);
            setTimeout(() => napoliMostraErrore(e, this.el('napoli-modal-procedura')), 60);
        } finally {
            setButtonLoading(pulsante, false);
            this.el('proc-avanti').textContent = this.passo === 3 ? 'Crea il lotto' : 'Avanti';
        }
    },
};

function napoliBenvenuto() {
    return `
        <div class="napoli-benvenuto">
            ${napoliSvg('M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4', 48)}
            <h2>Per cominciare, crea il primo lotto</h2>
            <p>Il programma propone il nome, i testi della fattura e le tariffe del contratto attuale: tu controlli, completi e confermi. Ci vuole un minuto.</p>
            <button type="button" class="btn btn-primary" data-azione="crea-lotto">
                ${napoliSvg('M12 6v6m0 0v6m0-6h6m-6 0H6', 18)}
                Crea il primo lotto
            </button>
        </div>`;
}

// ==================== scheda Mese ====================

const NapoliMese = {
    async avvia() {
        NapoliComune.alCambioLotto = () => this.disegna();
        NapoliComune.dopoAnnulla = async () => { await NapoliComune.caricaLotti(); await this.disegna(); };
        NapoliComune.primaDiAnnullare = () => NapoliCoordinatore.salvaInSospeso();
        document.getElementById('napoli-mese').addEventListener('click', (e) => {
            if (e.target.closest('[data-azione="crea-lotto"]')) {
                NapoliProcedura.apri(async (lotto) => { await NapoliComune.caricaLotti(lotto.id); await this.disegna(); });
            }
        });
        try {
            await NapoliComune.caricaLotti();
        } catch (e) {
            document.getElementById('napoli-mese').innerHTML = `<div class="alert alert-danger">${escapeHtml(e.message || 'Dati non disponibili')}</div>`;
            return;
        }
        await this.disegna();
    },

    async disegna() {
        const box = document.getElementById('napoli-mese');
        const lotto = NapoliComune.lotto;
        if (!lotto) {
            box.innerHTML = `<div class="card">${napoliBenvenuto()}</div>`;
            await NapoliCoordinatore.carica();
            return;
        }
        NapoliCoordinatore.carica();          // il riquadro delle ore del coordinatore, sotto i controlli
        let controlli;
        try {
            controlli = await apiCall(`/api/napoli/lotti/${lotto.id}/controlli`);
        } catch (e) {
            box.innerHTML = `<div class="alert alert-danger">${escapeHtml(e.message || 'Controlli non disponibili')}</div>`;
            return;
        }
        const ordine = { manca: 0, avviso: 1, ok: 2 };
        controlli.sort((a, b) => ordine[a.stato] - ordine[b.stato]);
        const voce = (c) => `
            <div class="da-fare-item ${NAPOLI_CLASSE_STATO[c.stato]}">
                ${napoliSvg(NAPOLI_ICONE_STATO[c.stato], 20, 'da-fare-icona')}
                <div class="da-fare-testo"><div class="da-fare-titolo">${escapeHtml(c.testo)}</div></div>
                ${c.stato === 'ok' ? '' : `<a class="btn btn-sm btn-secondary da-fare-azione" href="/napoli/impostazioni#${escapeHtml(c.sezione)}">Sistema</a>`}
            </div>`;
        const daFare = controlli.filter(c => c.stato !== 'ok');
        const aPosto = controlli.filter(c => c.stato === 'ok');
        const mancano = controlli.filter(c => c.stato === 'manca').length;
        const avvisi = controlli.filter(c => c.stato === 'avviso').length;
        const conteggio = mancano
            ? `<span class="badge badge-danger">${mancano} da sistemare</span>`
            : (avvisi ? `<span class="badge badge-warning">${avvisi} da controllare</span>` : '<span class="badge badge-success">Tutto a posto</span>');
        box.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">Prima delle fatture di ${escapeHtml(lotto.nome)}</h2>
                    ${conteggio}
                </div>
                <div>
                    ${daFare.map(voce).join('')}
                    ${aPosto.length ? `
                    <details class="section napoli-controlli-ok"${daFare.length ? '' : ' open'}>
                        <summary>Già a posto (${aPosto.length})</summary>
                        ${aPosto.map(voce).join('')}
                    </details>` : ''}
                </div>
            </div>
            <p class="napoli-nota">L'anagrafica (alunni, operatori, scuole, coppie e PEI) si carica dal file Excel del coordinatore nella scheda <a href="/napoli/import">Importa</a> e si controlla o si corregge nella scheda <a href="/napoli/anagrafiche">Anagrafiche</a>. Le ore degli operatori si scrivono nella scheda <a href="/napoli/presenze">Presenze</a>, quelle del coordinatore qui sotto (o nella scheda Fattura). Il prospetto della fattura del mese, da ricopiare nel programma di fatturazione, è nella scheda <a href="/napoli/fattura">Fattura</a>. I fogli firma arriveranno con i prossimi aggiornamenti di Assisto.</p>`;
    },
};

// ==================== ore del coordinatore (scheda Mese, passo 1.8) ====================

const NAPOLI_COORD_ATTESA = 2000;        // come il salvataggio automatico della Rendicontazione
const NAPOLI_COORD_MESI_VISIBILI = 6;    // gli altri mesi con «Mostra anche i mesi prima»
const NAPOLI_COORD_ICONA_OK = 'M5 13l4 4L19 7';
const NAPOLI_COORD_ICONA_ERRORE = 'M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z';

/**
 * Il totale mensile delle ore del coordinatore per contratto applicativo e grado (REGOLE 12):
 * una casella per riga, con il salvataggio automatico (dopo 2 secondi o uscendo dalla
 * casella) e la navigazione da tastiera della Rendicontazione (Invio e frecce: la casella
 * sotto o sopra). Ogni riga si salva da sola (PUT .../coordinamento, solo i campi cambiati);
 * il controllo vero delle ore e' sul server, che risponde con il messaggio da mostrare sotto
 * la riga. Un mese chiuso ha le caselle bloccate.
 */
const NapoliCoordinatore = {
    dati: null,
    righe: new Map(),        // chiave -> { riga, mese, salvato, corrente, timer, inVolo, ancora, errore, lettura }
    tuttiIMesi: false,
    pronta: false,
    ultimoSalvataggio: null,

    el(id) { return document.getElementById(id); },

    prepara() {
        if (this.pronta) return;
        this.pronta = true;
        const box = this.el('coord-contenuto');
        box.addEventListener('input', (e) => {
            if (e.target.matches('input[data-coord]')) this.modificata(e.target);
        });
        box.addEventListener('change', (e) => {
            if (e.target.matches('input[data-coord]')) this.salvaRiga(e.target.closest('tr').dataset.chiave);
        });
        box.addEventListener('keydown', (e) => {
            if (e.target.matches('input[data-coord]')) this.tasti(e);
        });
        // uscendo dalla casella: il valore come l'ha salvato il server (71.55 -> 71,55)
        box.addEventListener('focusout', (e) => {
            if (e.target.matches('input[data-coord]')) {
                const chiave = e.target.closest('tr').dataset.chiave;
                setTimeout(() => this.aggiornaRiga(chiave), 0);
            }
        });
        box.addEventListener('click', (e) => {
            if (!e.target.closest('[data-azione="coord-tutti"]')) return;
            this.tuttiIMesi = !this.tuttiIMesi;
            this.disegnaTabella();
        });
        // uscita dalla pagina entro i 2 secondi: le caselle cambiate partono subito
        window.addEventListener('pagehide', () => this.inviaInUscita());
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'hidden') this.inviaInUscita();
        });
    },

    async carica() {
        const card = this.el('napoli-coordinatore');
        if (!card) return;
        const lotto = NapoliComune.lotto;
        this.prepara();
        await this.salvaInSospeso();         // cambio di lotto o Ctrl+Z: prima le caselle in sospeso
        if (!lotto) { card.hidden = true; this.dati = null; return; }
        let dati;
        try {
            dati = await apiCall(`/api/napoli/lotti/${lotto.id}/coordinamento`);
        } catch (e) {
            card.hidden = false;
            this.el('coord-contenuto').innerHTML = `<div class="alert alert-danger">${escapeHtml(e.message || 'Ore del coordinatore non disponibili')}</div>`;
            return;
        }
        if (!NapoliComune.lotto || NapoliComune.lotto.id !== dati.lotto.id) return;   // lotto cambiato nel frattempo
        this.dati = dati;
        this.righe = new Map();
        dati.mesi.forEach(m => m.righe.forEach(r => this.righe.set(r.chiave, {
            riga: r, mese: m, salvato: { ore: r.ore, nota: r.nota }, corrente: null, timer: null, inVolo: null,
            ancora: false, errore: null, lettura: null,
        })));
        card.hidden = false;
        this.disegnaTabella();
        this.mostraStato();
    },

    disegnaTabella() {
        const d = this.dati;
        const box = this.el('coord-contenuto');
        if (!d.contratti) {
            box.innerHTML = `<p class="napoli-coord-vuoto">Per scrivere le ore del coordinatore serve almeno un contratto applicativo del lotto (con il numero, il grado e le date).
                <a class="btn btn-sm btn-secondary" href="/napoli/impostazioni#contratti">Aggiungi un contratto</a></p>`;
            return;
        }
        if (!d.mesi.length) {
            const f = d.futuri[0];
            box.innerHTML = `<p class="napoli-coord-vuoto">${f
                ? `Il contratto ${escapeHtml(f.numero)} comincia il ${escapeHtml(f.dal_testo)}: le ore del coordinatore si scrivono da quel mese.`
                : 'Nessun mese da compilare: i contratti del lotto sono già finiti.'}</p>`;
            return;
        }
        const mesi = this.tuttiIMesi ? d.mesi : d.mesi.slice(0, NAPOLI_COORD_MESI_VISIBILI);
        const altri = d.mesi.length - NAPOLI_COORD_MESI_VISIBILI;
        box.innerHTML = `
            <div class="table-responsive napoli-coord-tabella-box">
                <table class="table napoli-tabella-coordinatore">
                    <thead><tr>
                        <th scope="col">Contratto applicativo</th>
                        <th scope="col">Periodo</th>
                        <th scope="col" class="napoli-numero">Ore del mese</th>
                        <th scope="col">Nota (facoltativa)</th>
                    </tr></thead>
                    ${mesi.map(m => this.htmlMese(m)).join('')}
                </table>
            </div>
            ${altri > 0 ? `<button type="button" class="btn btn-ghost btn-sm napoli-coord-tutti" data-azione="coord-tutti">${this.tuttiIMesi
                ? 'Mostra solo gli ultimi mesi' : `Mostra anche i mesi prima (${altri})`}</button>` : ''}
            ${d.futuri.length ? `<p class="napoli-aiuto">${d.futuri.map(f => `Il contratto ${escapeHtml(f.numero)} (${escapeHtml(f.grado_testo)}) comincia il ${escapeHtml(f.dal_testo)}: le sue ore si scrivono da quel mese.`).join(' ')}</p>` : ''}`;
        this.righe.forEach((st, chiave) => this.aggiornaRiga(chiave));
    },

    htmlMese(m) {
        return `<tbody class="napoli-coord-mese${m.chiuso ? ' chiuso' : ''}">
            <tr class="napoli-coord-mese-riga"><th colspan="4" scope="rowgroup">${escapeHtml(m.testo)}${m.chiuso
                ? ' <span class="badge badge-secondary badge-sm" title="Il mese del lotto è chiuso: le ore non si cambiano">Mese chiuso</span>' : ''}</th></tr>
            ${m.righe.map(r => this.htmlRiga(r, m)).join('')}
        </tbody>`;
    },

    htmlRiga(r, m) {
        const st = this.righe.get(r.chiave);
        const v = st.corrente || st.salvato;
        const dove = `${m.testo}, contratto ${r.numero}, ${r.grado_testo}`;
        const bloccata = m.chiuso || r.definitiva ? ' disabled' : '';
        return `<tr data-chiave="${escapeHtml(r.chiave)}" class="napoli-coord-riga">
                <td><span class="napoli-figura-nome">Contratto ${escapeHtml(r.numero)}</span>
                    <div class="napoli-sotto-in">${escapeHtml(napoliMaiuscola(r.grado_testo))}</div></td>
                <td>${escapeHtml(r.periodo_testo)}${r.mese_intero || r.fuori_contratto ? '' : '<div class="napoli-sotto-in">parte del mese</div>'}${r.definitiva
                    ? ` <span class="badge badge-success badge-sm" title="La fattura ${escapeHtml(r.definitiva)} è definitiva: le ore non si cambiano (si riapre nella scheda Fattura)">Fattura definitiva</span>` : ''}</td>
                <td class="napoli-numero"><input type="text" class="table-input napoli-coord-ore" data-coord="ore"
                    inputmode="decimal" autocomplete="off" value="${escapeHtml(v.ore)}" placeholder="${m.chiuso ? '' : 'da scrivere'}"
                    aria-label="Ore del coordinatore, ${escapeHtml(dove)}" aria-describedby="coord-msg-${escapeHtml(r.chiave)}"${bloccata}></td>
                <td><input type="text" class="form-control napoli-coord-nota" data-coord="nota" maxlength="200" autocomplete="off"
                    value="${escapeHtml(v.nota)}" placeholder="${m.chiuso ? '' : 'facoltativa'}"
                    aria-label="Nota delle ore del coordinatore, ${escapeHtml(dove)}"${bloccata}></td>
            </tr>
            <tr class="napoli-coord-messaggio" data-messaggio="${escapeHtml(r.chiave)}" hidden>
                <td colspan="4"><div id="coord-msg-${escapeHtml(r.chiave)}"></div></td>
            </tr>`;
    },

    /** Riga e messaggio di una riga, senza ridisegnare la tabella (la casella attiva resta). */
    aggiornaRiga(chiave) {
        const st = this.righe.get(chiave);
        const tr = this.el('coord-contenuto').querySelector(`tr[data-chiave="${CSS.escape(chiave)}"]`);
        if (!st || !tr) return;
        const ore = tr.querySelector('[data-coord="ore"]');
        const nota = tr.querySelector('[data-coord="nota"]');
        // il valore salvato come lo scrive il server (71.55 -> 71,55), se la casella non e' cambiata dopo
        if (!st.corrente) {
            if (document.activeElement !== ore) ore.value = st.salvato.ore;
            if (document.activeElement !== nota) nota.value = st.salvato.nota;
        }
        ore.classList.toggle('input-error', !!st.errore && st.errore.campo !== 'nota');
        nota.classList.toggle('input-error', !!st.errore && st.errore.campo === 'nota');
        // "cambiata, da salvare" (azzurra) solo senza errore: una casella sbagliata resta rossa
        ore.classList.toggle('changed', !st.errore && !!st.corrente && st.corrente.ore !== (st.salvato.ore || ''));
        nota.classList.toggle('changed', !st.errore && !!st.corrente && st.corrente.nota !== (st.salvato.nota || ''));
        ore.disabled = nota.disabled = !!st.mese.chiuso || !!st.riga.definitiva;
        const riga = tr.nextElementSibling;
        const box = riga.querySelector('div');
        const testo = st.errore ? st.errore.messaggio : (st.lettura || '');
        box.className = st.errore ? 'napoli-coord-errore' : 'napoli-coord-lettura';
        box.setAttribute('role', st.errore ? 'alert' : 'status');
        box.textContent = testo;
        riga.hidden = !testo;
    },

    valori(chiave) {
        const tr = this.el('coord-contenuto').querySelector(`tr[data-chiave="${CSS.escape(chiave)}"]`);
        if (!tr) {                // riga nascosta («Mostra solo gli ultimi mesi»): i valori ricordati
            const st = this.righe.get(chiave);
            return { ...(st.corrente || st.salvato) };
        }
        return { ore: tr.querySelector('[data-coord="ore"]').value.trim(), nota: tr.querySelector('[data-coord="nota"]').value.trim() };
    },

    modificata(input) {
        const chiave = input.closest('tr').dataset.chiave;
        const st = this.righe.get(chiave);
        if (!st) return;
        st.corrente = this.valori(chiave);
        st.ancora = true;
        clearTimeout(st.timer);
        st.timer = setTimeout(() => this.salvaRiga(chiave), NAPOLI_COORD_ATTESA);
        this.aggiornaRiga(chiave);
        this.mostraStato('in_sospeso');
    },

    /** Solo i campi cambiati rispetto a quelli salvati; null se non e' cambiato niente. */
    corpo(st) {
        if (!st.corrente) return null;
        const r = st.riga;
        const corpo = { anno: r.anno, mese: r.mese, contratto_id: r.contratto_id, grado: r.grado };
        if (st.corrente.ore !== (st.salvato.ore || '')) corpo.ore = st.corrente.ore;
        if (st.corrente.nota !== (st.salvato.nota || '')) corpo.nota = st.corrente.nota;
        return ('ore' in corpo || 'nota' in corpo) ? corpo : null;
    },

    async salvaRiga(chiave) {
        const st = this.righe.get(chiave);
        if (!st) return;
        clearTimeout(st.timer);
        st.timer = null;
        if (st.inVolo) { st.ancora = true; return st.inVolo; }      // riparte quando finisce quello in corso
        st.ancora = false;
        const corpo = this.corpo(st);
        if (!corpo) {
            // di nuovo il valore salvato (anche dopo un errore): niente da mandare
            if (st.corrente || st.errore) { st.corrente = null; st.errore = null; this.aggiornaRiga(chiave); }
            this.mostraStato();
            return;
        }
        const lotto = this.dati.lotto.id;
        this.mostraStato('salvo');
        st.inVolo = (async () => {
            try {
                const r = await apiCall(`/api/napoli/lotti/${lotto}/coordinamento`, { method: 'PUT', body: JSON.stringify(corpo) });
                if ('ore' in corpo) st.salvato.ore = r.riga.ore;
                if ('nota' in corpo) st.salvato.nota = r.riga.nota;
                Object.assign(st.riga, { id: r.riga.id, ore: r.riga.ore, nota: r.riga.nota, ore_cent: r.riga.ore_cent });
                st.errore = null;
                st.lettura = r.lettura || null;
                // se le caselle non sono cambiate mentre si salvava, la riga e' tutta salvata
                const ora = this.valori(chiave);
                const oreUguali = 'ore' in corpo ? ora.ore === corpo.ore : ora.ore === (st.salvato.ore || '');
                const noteUguali = 'nota' in corpo ? ora.nota === corpo.nota : ora.nota === (st.salvato.nota || '');
                st.corrente = oreUguali && noteUguali ? null : ora;
                this.ultimoSalvataggio = new Date();          // la lettura ("71.55" = 71,55) si vede sotto la riga
            } catch (e) {
                st.errore = { messaggio: e.message || 'Salvataggio non riuscito: riprova.', campo: (e.data && e.data.campo) || 'ore' };
                if (e.code === 'FATTURA_DEFINITIVA') st.riga.definitiva = st.riga.definitiva || 'definitiva';
                if (e.code === 'MESE_CHIUSO_LOTTO') {
                    st.mese.chiuso = true;          // chiuso nel frattempo: le caselle del mese si bloccano
                    this.righe.forEach((altra, k) => { if (altra.mese === st.mese) this.aggiornaRiga(k); });
                }
            } finally {
                st.inVolo = null;
            }
            this.aggiornaRiga(chiave);
            if (st.ancora) await this.salvaRiga(chiave);
            this.mostraStato();
        })();
        return st.inVolo;
    },

    /** Le caselle cambiate e non ancora salvate partono adesso (Ctrl+Z, cambio di lotto). */
    async salvaInSospeso() {
        const attese = [];
        this.righe.forEach((st, chiave) => {
            if (st.timer || st.inVolo || (st.corrente && st.ancora)) attese.push(this.salvaRiga(chiave));
        });
        await Promise.all(attese);
    },

    /** Pagina chiusa entro i 2 secondi: fetch keepalive, che il browser porta a termine lo stesso. */
    inviaInUscita() {
        if (!this.dati) return;
        this.righe.forEach((st, chiave) => {
            if (!st.timer) return;
            clearTimeout(st.timer);
            st.timer = null;
            const corpo = this.corpo(st);
            if (!corpo) return;
            fetch(`/api/napoli/lotti/${this.dati.lotto.id}/coordinamento`, {
                method: 'PUT', keepalive: true, credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo),
            }).then(r => (r.ok ? r.json() : null)).then((r) => {
                // scheda solo nascosta (la pagina e' ancora aperta): la riga torna "salvata"
                if (!r || !r.riga) return;
                if ('ore' in corpo) st.salvato.ore = r.riga.ore;
                if ('nota' in corpo) st.salvato.nota = r.riga.nota;
                const ora = this.valori(chiave);
                if (ora.ore === (corpo.ore ?? st.salvato.ore) && ora.nota === (corpo.nota ?? st.salvato.nota)) st.corrente = null;
                st.errore = null;
                this.ultimoSalvataggio = new Date();
                this.aggiornaRiga(chiave);
                this.mostraStato();
            }).catch(() => { /* la pagina si sta chiudendo, o l'errore si vedra' al prossimo salvataggio */ });
        });
    },

    /** Invio e frecce come in Rendicontazione: la casella della stessa colonna sotto o sopra. */
    tasti(e) {
        let passo = 0;
        if (e.key === 'Enter' || e.key === 'ArrowDown') passo = 1;
        else if (e.key === 'ArrowUp') passo = -1;
        else return;
        e.preventDefault();
        const colonna = [...this.el('coord-contenuto').querySelectorAll(`input[data-coord="${e.target.dataset.coord}"]`)]
            .filter(i => !i.disabled);
        const prossima = colonna[colonna.indexOf(e.target) + passo];
        if (prossima) { prossima.focus(); prossima.select(); }
        else if (e.key === 'Enter') e.target.blur();          // ultima riga: si chiude la casella e si salva
    },

    mostraStato(tipo) {
        const box = this.el('coord-salvataggio');
        const testo = (stato, icona, scritta) => {
            box.className = ['auto-save-indicator', stato].filter(Boolean).join(' ');
            box.innerHTML = `${icona ? napoliSvg(icona, 14) : ''}<span id="coord-salvataggio-testo">${escapeHtml(scritta)}</span>`;
        };
        if (tipo === 'in_sospeso') return testo('pending', '', 'Modifiche in sospeso…');
        if (tipo === 'salvo') return testo('saving', '', 'Salvataggio…');
        const st = [...this.righe.values()];
        if (st.some(x => x.timer || x.inVolo)) return testo('pending', '', 'Modifiche in sospeso…');
        const errori = st.filter(x => x.errore).length;
        const ora = this.ultimoSalvataggio
            ? this.ultimoSalvataggio.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' }) : null;
        if (errori) {
            const caselle = errori === 1 ? '1 casella da correggere' : `${errori} caselle da correggere`;
            return testo('errore', NAPOLI_COORD_ICONA_ERRORE, ora ? `Salvato alle ${ora}, tranne ${caselle}` : caselle);
        }
        if (ora) return testo('saved', NAPOLI_COORD_ICONA_OK, `Salvato alle ${ora}`);
        return testo('', NAPOLI_COORD_ICONA_OK, 'Salvataggio automatico');
    },
};

// ==================== scheda Anagrafiche (alunni, operatori, scuole, coppie) ====================

const NAPOLI_STATI_FILTRO = {
    alunni: [['attivi', 'In servizio'], ['da_sistemare', 'Da sistemare'], ['archiviati', 'Archiviati'], ['tutti', 'Tutti']],
    operatori: [['attivi', 'In servizio'], ['da_sistemare', 'Da sistemare'], ['archiviati', 'Archiviati'], ['tutti', 'Tutti']],
    scuole: [['attive', 'Attive'], ['da_sistemare', 'Da sistemare'], ['archiviate', 'Archiviate'], ['tutte', 'Tutte']],
    coppie: [['in_corso', 'In corso'], ['future', 'Da cominciare'], ['finite', 'Finite'], ['da_sistemare', 'Da sistemare'], ['tutte', 'Tutte']],
};
// filtri che valgono per ogni parte (gli altri si nascondono)
const NAPOLI_FILTRI_PARTE = {
    alunni: ['scuola_id', 'municipalita', 'figura', 'grado', 'stato'],
    operatori: ['scuola_id', 'municipalita', 'figura', 'grado', 'stato'],
    scuole: ['municipalita', 'figura', 'grado', 'stato'],
    coppie: ['scuola_id', 'municipalita', 'figura', 'grado', 'ruolo', 'stato'],
};
const NAPOLI_PARTI_ANAGRAFICA = {
    alunni: { titolo: 'Alunni', nuovo: 'Nuovo alunno', vuoto: 'Nessun alunno' },
    operatori: { titolo: 'Operatori', nuovo: 'Nuovo operatore', vuoto: 'Nessun operatore' },
    scuole: { titolo: 'Scuole e plessi', nuovo: 'Nuova scuola', vuoto: 'Nessuna scuola' },
    coppie: { titolo: 'Coppie operatore-alunno', nuovo: 'Nuova coppia', vuoto: 'Nessuna coppia' },
};
const NAPOLI_DA_SISTEMARE = {
    grado_da_decidere: 'Grado da decidere',
    senza_pei: 'Senza ore del PEI',
    senza_coppie: 'Senza coppie in corso',
    senza_scuola: 'Senza scuola',
    scuola_archiviata: 'Scuola archiviata',
    codice_fiscale: 'Codice fiscale da controllare',
    codice_fiscale_mancante: 'Codice fiscale mancante',
    ore_contratto_mancanti: 'Ore di contratto mancanti',
    ore_oltre_contratto: 'Più ore del contratto',
    municipalita_mancante: 'Municipalità mancante',
    alunni_senza_grado: 'Alunni senza grado',
    figura_diversa: 'Figura diversa da quella dell\'operatore',
    operatore_archiviato: 'Operatore archiviato',
    alunno_archiviato: 'Alunno archiviato',
};
const NAPOLI_STATO_COPPIA = { in_corso: ['In corso', 'badge-success'], futura: ['Da cominciare', 'badge-info'], finita: ['Finita', 'badge-secondary'] };
const NAPOLI_GRADO_SCUOLA = { inferiore: 'Grado inferiore', superiore: 'Grado superiore', misto: 'Misto' };
const NAPOLI_STATI_PEI = [['definitivo', 'Definitivo'], ['provvisorio', 'Provvisorio'], ['sospeso', 'Sospeso']];
const NAPOLI_LIVELLI = ['C3', 'D1', 'D2', 'E2'];
// un codice fiscale intero scritto nella ricerca: si cerca con una POST, mai nell'indirizzo
const NAPOLI_RX_CF = /^[A-Za-z]{6}[0-9LMNPQRSTUVlmnpqrstuv]{2}[A-Za-z][0-9LMNPQRSTUVlmnpqrstuv]{2}[A-Za-z][0-9LMNPQRSTUVlmnpqrstuv]{3}[A-Za-z]$/;

function napoliBadge(testo, classe = 'badge-warning') {
    return `<span class="badge ${classe} badge-sm">${escapeHtml(testo)}</span>`;
}

function napoliDaSistemare(codici) {
    return (codici || []).map(c => napoliBadge(NAPOLI_DA_SISTEMARE[c] || c)).join('');
}

function napoliMunicipalita(m) {
    return m ? `Municipalità ${m}` : 'Municipalità mancante';
}

function napoliGradoTesto(g) {
    return g ? (NAPOLI_GRADO_SCUOLA[g] || g) : 'Grado da decidere';
}

function napoliOre(testo) {
    return testo ? `${escapeHtml(testo)} h` : '';
}

/** Primi `n` nomi e "e altri N". */
function napoliPrimi(voci, n = 3) {
    if (voci.length <= n) return voci;
    return voci.slice(0, n).concat([`e ${voci.length - n === 1 ? 'un altro' : `altri ${voci.length - n}`}`]);
}

const NapoliAnagrafiche = {
    PARTI: ['alunni', 'operatori', 'scuole', 'coppie'],
    parte: 'alunni',
    riepilogo: null,
    filtri: {},
    righe: [],
    seq: 0,
    attesaCerca: null,
    modulo: null,
    schedaDati: null,

    el(id) { return document.getElementById(id); },

    async avvia() {
        this.azzeraFiltri();
        NapoliComune.alCambioLotto = () => {
            this.azzeraFiltri();
            if (window.location.hash.replace('#', '') !== this.parte) window.location.hash = this.parte;
            else this.mostra();
        };
        NapoliComune.dopoAnnulla = async () => { await this.mostra(); };
        window.addEventListener('hashchange', () => this.mostra());
        this.collega();
        try {
            await Promise.all([NapoliComune.caricaLotti(), NapoliComune.caricaFigure()]);
        } catch (e) {
            showToast(e.message || 'Dati non disponibili', 'error');
        }
        await this.mostra();
    },

    azzeraFiltri() {
        this.filtri = {};
        this.PARTI.forEach(p => { this.filtri[p] = { stato: NAPOLI_STATI_FILTRO[p][0][0] }; });
        const cerca = this.el('filtro-cerca');
        if (cerca) cerca.value = '';
    },

    /** #alunni, #operatori, #scuole, #coppie o la scheda #alunno-12, #operatore-7. */
    indirizzo() {
        const h = window.location.hash.replace('#', '');
        const m = /^(alunno|operatore)-(\d+)$/.exec(h);
        if (m) return { parte: m[1] === 'alunno' ? 'alunni' : 'operatori', scheda: { tipo: m[1], id: Number(m[2]) } };
        return { parte: this.PARTI.includes(h) ? h : 'alunni', scheda: null };
    },

    collega() {
        this.el('napoli-annulla-ultima').addEventListener('click', () => NapoliComune.annulla());
        this.el('btn-nuovo').addEventListener('click', () => this.nuovo(this.parte));
        this.el('elenco-da-sistemare').addEventListener('click', () => {
            const f = this.filtri[this.parte];
            f.stato = f.stato === 'da_sistemare' ? NAPOLI_STATI_FILTRO[this.parte][0][0] : 'da_sistemare';
            this.el('filtro-stato').value = f.stato;
            this.carica();
        });
        this.el('form-anagrafica').addEventListener('submit', (e) => { e.preventDefault(); this.invia(); });
        document.querySelectorAll('[data-campo-filtro]').forEach(sel => {
            sel.addEventListener('change', () => {
                this.filtri[this.parte][sel.dataset.campoFiltro] = sel.value;
                this.carica();
            });
        });
        const cerca = this.el('filtro-cerca');
        cerca.addEventListener('input', () => {
            clearTimeout(this.attesaCerca);
            this.attesaCerca = setTimeout(() => this.cerca(cerca.value.trim()), 300);
        });
        cerca.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); clearTimeout(this.attesaCerca); this.cerca(cerca.value.trim()); }
        });
        document.addEventListener('click', (e) => {
            const b = e.target.closest('[data-azione]');
            if (!b || !b.closest('#napoli-anagrafiche')) return;
            if (b.dataset.azione === 'crea-lotto') {
                NapoliProcedura.apri(async (lotto) => { await NapoliComune.caricaLotti(lotto.id); await this.mostra(); });
                return;
            }
            this.azione(b.dataset.azione, b.dataset.id ? Number(b.dataset.id) : null, b);
        });
        // una riga dell'elenco si apre anche con un clic sulla riga (fuori dai pulsanti)
        this.el('elenco-tabella').addEventListener('click', (e) => {
            if (e.target.closest('a, button')) return;
            const tr = e.target.closest('tr[data-apri]');
            if (tr) window.location.hash = tr.dataset.apri;
        });
    },

    async mostra() {
        const lotto = NapoliComune.lotto;
        const senza = this.el('anagrafiche-senza-lotto');
        const vuota = this.el('anagrafiche-vuota');
        const contenuto = this.el('anagrafiche-contenuto');
        if (!lotto) {
            senza.innerHTML = `<div class="card">${napoliBenvenuto()}</div>`;
            senza.hidden = false;
            vuota.hidden = contenuto.hidden = true;
            return;
        }
        senza.hidden = true;
        try {
            this.riepilogo = await apiCall(`/api/napoli/lotti/${lotto.id}/anagrafiche`);
        } catch (e) {
            senza.innerHTML = `<div class="alert alert-danger">${escapeHtml(e.message || 'Anagrafiche non disponibili')}</div>`;
            senza.hidden = false;
            vuota.hidden = contenuto.hidden = true;
            return;
        }
        const r = this.riepilogo;
        const { parte, scheda } = this.indirizzo();
        // anagrafica vuota: l'azione principale e' caricarla dal file Excel (REGOLE 14)
        // vuota = senza scuole, alunni e coppie del lotto: gli operatori sono della
        // cooperativa e uno aggiunto a mano non vuol dire che l'anagrafica sia caricata
        if (r.vuota && !scheda) {
            vuota.hidden = false;
            contenuto.hidden = true;
            return;
        }
        vuota.hidden = true;
        contenuto.hidden = false;
        this.disegnaConteggi();
        if (scheda) await this.apriScheda(scheda);
        else await this.mostraParte(parte);
    },

    disegnaConteggi() {
        const c = this.riepilogo.conteggi, d = this.riepilogo.da_sistemare;
        const valori = { alunni: c.alunni, operatori: c.operatori, scuole: c.scuole, coppie: c.coppie_in_corso };
        document.querySelectorAll('[data-conta]').forEach(el => { el.textContent = String(valori[el.dataset.conta]); });
        this.daSistemare = d;
    },

    /** "N da sistemare" accanto al titolo dell'elenco: un clic mostra solo quelle righe. */
    disegnaDaSistemare() {
        const n = (this.daSistemare || {})[this.parte] || 0;
        const b = this.el('elenco-da-sistemare');
        const attivo = this.filtri[this.parte].stato === 'da_sistemare';
        b.hidden = !n;
        b.textContent = attivo ? `${n} da sistemare: mostra tutti` : `${n} da sistemare`;
        b.setAttribute('aria-pressed', attivo ? 'true' : 'false');
        b.title = attivo ? 'Mostra di nuovo tutte le righe' : 'Mostra solo le righe con qualcosa da sistemare';
    },

    segnaParte(parte) {
        document.querySelectorAll('[data-parte-link]').forEach(a => {
            const attiva = a.dataset.parteLink === parte;
            a.classList.toggle('attiva', attiva);
            if (attiva) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
        });
    },

    async mostraParte(parte) {
        this.parte = parte;
        this.segnaParte(parte);
        this.el('anagrafiche-elenco').hidden = false;
        this.el('anagrafiche-scheda').hidden = true;
        const info = NAPOLI_PARTI_ANAGRAFICA[parte];
        this.el('elenco-titolo').textContent = info.titolo;
        this.el('btn-nuovo').textContent = info.nuovo;
        this.preparaFiltri(parte);
        await this.carica();
    },

    preparaFiltri(parte) {
        const f = this.filtri[parte];
        const ammessi = NAPOLI_FILTRI_PARTE[parte];
        document.querySelectorAll('[data-filtro]').forEach(g => { g.hidden = !ammessi.includes(g.dataset.filtro); });
        const r = this.riepilogo;
        this.el('filtro-scuola').innerHTML = '<option value="">Tutte</option>' + r.scuole.filter(s => s.attiva)
            .map(s => `<option value="${s.id}">${escapeHtml(s.nome)}${r.municipalita.length > 1 && s.municipalita ? ` (mun. ${s.municipalita})` : ''}</option>`).join('');
        this.el('filtro-municipalita').innerHTML = '<option value="">Tutte</option>'
            + r.municipalita.map(m => `<option value="${m}">${m}</option>`).join('');
        this.el('filtro-figura').innerHTML = '<option value="">Tutte</option>' + (NapoliComune.figure || [])
            .filter(x => parte === 'operatori' || !x.ore_di_lotto)
            .map(x => `<option value="${escapeHtml(x.codice)}">${escapeHtml(x.nome)}</option>`).join('');
        this.el('filtro-grado').querySelectorAll('[data-solo]').forEach(o => { o.hidden = o.disabled = o.dataset.solo !== parte; });
        this.el('filtro-stato').innerHTML = NAPOLI_STATI_FILTRO[parte].map(([v, t]) => `<option value="${v}">${t}</option>`).join('');
        document.querySelectorAll('[data-campo-filtro]').forEach(sel => { sel.value = f[sel.dataset.campoFiltro] || ''; });
        if (!this.el('filtro-stato').value) this.el('filtro-stato').value = NAPOLI_STATI_FILTRO[parte][0][0];
        this.el('filtro-cerca').value = f.cerca || '';
        this.el('filtro-cerca').placeholder = parte === 'scuole' ? 'Nome o codice'
            : (parte === 'coppie' ? 'Alunno o operatore' : 'Nome o codice fiscale');
        this.el('anagrafiche-trovato').hidden = true;
    },

    async cerca(testo) {
        const box = this.el('anagrafiche-trovato');
        if (NAPOLI_RX_CF.test(testo.replace(/\s/g, '')) && ['alunni', 'operatori'].includes(this.parte)) {
            // il codice fiscale non va nell'indirizzo (finirebbe nei log): una POST, e la risposta non lo ripete
            try {
                const r = await apiCall('/api/napoli/anagrafiche/codice-fiscale', {
                    method: 'POST', body: JSON.stringify({ codice_fiscale: testo }) });
                box.innerHTML = r.trovati.length
                    ? `<strong>Codice fiscale ${escapeHtml(r.cf)}:</strong> ` + r.trovati.map(t =>
                        `${escapeHtml(t.nome)} (${t.tipo === 'alunno' ? `alunno${t.lotto_id !== NapoliComune.lotto.id ? ', ' + escapeHtml(t.lotto) : ''}` : 'operatore'}${t.attivo ? '' : ', archiviato'})
                         ${t.tipo === 'operatore' || t.lotto_id === NapoliComune.lotto.id ? `<a class="btn btn-sm btn-secondary" href="#${t.tipo}-${t.id}">Apri la scheda</a>` : ''}`).join(' · ')
                    : `Nessun alunno e nessun operatore ha il codice fiscale ${escapeHtml(r.cf)}.`;
                const tipo = r.trovati.length ? 'alert-info' : 'alert-warning';
                box.className = `napoli-trovato alert ${tipo}`;
                box.hidden = false;
            } catch (e) {
                napoliMostraErrore(e);
            }
            return;
        }
        box.hidden = true;
        this.filtri[this.parte].cerca = testo;
        await this.carica();
    },

    async carica() {
        const lotto = NapoliComune.lotto;
        const parte = this.parte;
        const f = this.filtri[parte];
        // filtri e ricerca nel corpo di una POST: un nome o un codice fiscale scritto nella
        // ricerca (anche a meta') non finisce nell'indirizzo, cioe' nei log
        const corpo = { parte };
        Object.entries(f).forEach(([k, v]) => {
            if (v && (k === 'cerca' || NAPOLI_FILTRI_PARTE[parte].includes(k))) corpo[k] = v;
        });
        const seq = ++this.seq;
        const box = this.el('elenco-tabella');
        try {
            const r = await apiCall(`/api/napoli/lotti/${lotto.id}/anagrafiche/elenco`, {
                method: 'POST', body: JSON.stringify(corpo) });
            if (seq !== this.seq) return;       // risposta superata da un filtro piu' recente
            this.righe = r.righe;
            this.el('elenco-conta').textContent = `${r.totale} ${r.totale === 1 ? 'riga' : 'righe'}`;
            this.disegnaDaSistemare();
            box.innerHTML = r.righe.length ? this['tabella_' + parte](r.righe) : this.vuoto(parte);
        } catch (e) {
            if (seq !== this.seq) return;
            box.innerHTML = `<div class="alert alert-danger napoli-esito-elenco">${escapeHtml(e.message || 'Elenco non disponibile')}</div>`;
        }
    },

    vuoto(parte) {
        const f = this.filtri[parte];
        const filtrato = f.cerca || NAPOLI_FILTRI_PARTE[parte].some(k => k !== 'stato' && f[k])
            || f.stato !== NAPOLI_STATI_FILTRO[parte][0][0];
        return `<p class="napoli-vuoto napoli-elenco-vuoto">${NAPOLI_PARTI_ANAGRAFICA[parte].vuoto}${filtrato
            ? ' con questi filtri: cambia o togli i filtri qui sopra.' : '.'}</p>`;
    },

    // ---------- elenchi ----------

    tabella_alunni(righe) {
        return `<table class="table napoli-tabella-anagrafica">
            <thead><tr><th scope="col">Alunno</th><th scope="col">Scuola</th><th scope="col">Ore del PEI a settimana</th>
                <th scope="col">Operatori</th><th scope="col" aria-label="Azioni"></th></tr></thead>
            <tbody>${righe.map(a => `
                <tr data-apri="alunno-${a.id}" class="napoli-riga-cliccabile${a.attivo ? '' : ' napoli-riga-archiviata'}">
                    <td><a class="napoli-nome" href="#alunno-${a.id}">${escapeHtml(a.nome_completo)}</a>
                        <div class="napoli-sotto"><span class="napoli-cf" title="Codice fiscale (mascherato)">${escapeHtml(a.cf)}</span>
                        ${a.esami ? napoliBadge('Esami', 'badge-info') : ''}
                        ${a.attivo ? '' : napoliBadge(`Archiviato dal ${formatDataIT(a.archiviato_dal)}`, 'badge-secondary')}
                        ${napoliDaSistemare(a.da_sistemare)}</div></td>
                    <td>${a.scuola ? escapeHtml(a.scuola.nome) : '<span class="napoli-vuoto">nessuna</span>'}
                        <div class="napoli-sotto">${a.scuola ? `${napoliMunicipalita(a.municipalita)} · ${napoliGradoTesto(a.grado)}` : ''}</div></td>
                    <td>${a.pei.length ? a.pei.map(p => `<span class="napoli-chip">${escapeHtml(p.nome_figura)} <strong>${napoliOre(p.ore_testo)}</strong></span>`).join('') : '<span class="napoli-vuoto">nessuna</span>'}</td>
                    <td>${a.operatori.length ? napoliPrimi(a.operatori.map(o => `${escapeHtml(o.nome)} <span class="napoli-sotto-in">· ${escapeHtml(o.nome_figura)}${o.ruolo === 'sostituto' ? ', sostituto' : ''}${o.stato === 'futura' ? ', da cominciare' : ''}</span>`)).map(x => `<div class="napoli-op">${x}</div>`).join('') : '<span class="napoli-vuoto">nessuno</span>'}</td>
                    <td class="napoli-azioni"><a class="btn btn-sm btn-secondary" href="#alunno-${a.id}" aria-label="Apri la scheda di ${escapeHtml(a.nome_completo)}">Apri</a></td>
                </tr>`).join('')}</tbody></table>`;
    },

    tabella_operatori(righe) {
        return `<table class="table napoli-tabella-anagrafica">
            <thead><tr><th scope="col">Operatore</th><th scope="col">Figura</th><th scope="col" class="napoli-numero">Ore a settimana</th>
                <th scope="col">Alunni (coppie in corso)</th><th scope="col" aria-label="Azioni"></th></tr></thead>
            <tbody>${righe.map(o => `
                <tr data-apri="operatore-${o.id}" class="napoli-riga-cliccabile${o.attivo ? '' : ' napoli-riga-archiviata'}">
                    <td><a class="napoli-nome" href="#operatore-${o.id}">${escapeHtml(o.nome_completo)}</a>
                        <div class="napoli-sotto">${o.cf ? `<span class="napoli-cf" title="Codice fiscale (mascherato)">${escapeHtml(o.cf)}</span>` : ''}
                        ${o.attivo ? '' : napoliBadge(`Archiviato dal ${formatDataIT(o.archiviato_dal)}`, 'badge-secondary')}
                        ${napoliDaSistemare(o.da_sistemare)}</div></td>
                    <td>${escapeHtml(o.nome_figura)}${o.livello_ccnl ? `<div class="napoli-sotto">Livello ${escapeHtml(o.livello_ccnl)}</div>` : ''}</td>
                    <td class="napoli-numero">${o.ore_progetto_testo ? `<strong>${escapeHtml(o.ore_progetto_testo)}</strong>` : '—'}
                        <div class="napoli-sotto napoli-sotto-destra">${o.ore_contratto_testo ? `su ${escapeHtml(o.ore_contratto_testo)} di contratto` : 'contratto: —'}</div></td>
                    <td>${o.alunni.length ? napoliPrimi(o.alunni.map(escapeHtml)).map(x => `<div class="napoli-op">${x}</div>`).join('') : '<span class="napoli-vuoto">nessuno</span>'}
                        ${o.scuole.length ? `<div class="napoli-sotto">${escapeHtml(napoliPrimi(o.scuole, 2).join(', '))}</div>` : ''}</td>
                    <td class="napoli-azioni"><a class="btn btn-sm btn-secondary" href="#operatore-${o.id}" aria-label="Apri la scheda di ${escapeHtml(o.nome_completo)}">Apri</a></td>
                </tr>`).join('')}</tbody></table>`;
    },

    tabella_scuole(righe) {
        return `<table class="table napoli-tabella-anagrafica">
            <thead><tr><th scope="col">Scuola o plesso</th><th scope="col">Municipalità</th><th scope="col">Grado</th>
                <th scope="col" class="napoli-numero">Alunni</th><th scope="col" class="napoli-numero">Coppie in corso</th><th scope="col" aria-label="Azioni"></th></tr></thead>
            <tbody>${righe.map(s => `
                <tr class="${s.attiva ? '' : 'napoli-riga-archiviata'}">
                    <td><span class="napoli-nome">${escapeHtml(s.nome)}</span>
                        <div class="napoli-sotto">${s.codice_meccanografico ? `<span>${escapeHtml(s.codice_meccanografico)}</span>` : '<span>senza codice meccanografico</span>'}
                        ${s.plessi > 1 ? napoliBadge(`${s.plessi} plessi con questo codice`, 'badge-info') : ''}
                        ${s.paritaria ? napoliBadge('Codice da paritaria', 'badge-info') : ''}
                        ${s.attiva ? '' : napoliBadge('Archiviata', 'badge-secondary')}
                        ${napoliDaSistemare(s.da_sistemare.filter(c => c !== 'grado_da_decidere'))}</div></td>
                    <td>${s.municipalita ? escapeHtml(String(s.municipalita)) : napoliBadge('Mancante')}</td>
                    <td>${s.grado ? escapeHtml(napoliGradoTesto(s.grado)) : napoliBadge('Da decidere')}
                        ${!s.grado && s.grado_proposto ? `<div class="napoli-sotto">dal codice: ${escapeHtml(NAPOLI_GRADO_SCUOLA[s.grado_proposto].toLowerCase())}</div>` : ''}</td>
                    <td class="napoli-numero">${s.alunni}</td>
                    <td class="napoli-numero">${s.coppie_in_corso}</td>
                    <td class="napoli-azioni">
                        <button type="button" class="btn btn-sm btn-secondary" data-azione="modifica-scuola" data-id="${s.id}" aria-label="Modifica ${escapeHtml(s.nome)}">${icona('matita')} Modifica</button>
                        <button type="button" class="btn btn-sm btn-secondary btn-solo-icona" data-azione="altro-scuola" data-id="${s.id}" title="Altre azioni" aria-label="Altre azioni su ${escapeHtml(s.nome)}" aria-haspopup="menu" aria-expanded="false">${icona('altro')}</button>
                    </td>
                </tr>`).join('')}</tbody></table>`;
    },

    periodoCoppia(c) {
        const [testo, classe] = NAPOLI_STATO_COPPIA[c.stato];
        return `<span class="napoli-periodo">dal ${escapeHtml(formatDataIT(c.valido_da))}</span>${c.valido_a
            ? `<br><span class="napoli-periodo">al ${escapeHtml(formatDataIT(c.valido_a))}</span>` : ''}<div class="napoli-sotto">${napoliBadge(testo, classe)}</div>`;
    },

    oreCoppia(c) {
        if (!c.ore_testo) return '<span class="napoli-vuoto">—</span>';
        return `<strong>${escapeHtml(c.ore_testo)}</strong><div class="napoli-sotto napoli-sotto-destra">${c.ore_da === 'quota' ? 'della coppia' : 'dal PEI'}</div>`;
    },

    pulsantiCoppia(c) {
        return `<td class="napoli-azioni">
            <button type="button" class="btn btn-sm btn-secondary" data-azione="modifica-coppia" data-id="${c.id}" aria-label="Modifica la coppia">${icona('matita')} Modifica</button>
            <button type="button" class="btn btn-sm btn-secondary btn-solo-icona" data-azione="altro-coppia" data-id="${c.id}" title="Altre azioni" aria-label="Altre azioni sulla coppia" aria-haspopup="menu" aria-expanded="false">${icona('altro')}</button>
        </td>`;
    },

    tabella_coppie(righe, colonne = ['alunno', 'operatore']) {
        const conAlunno = colonne.includes('alunno'), conOperatore = colonne.includes('operatore');
        return `<table class="table napoli-tabella-anagrafica">
            <thead><tr>${conAlunno ? '<th scope="col">Alunno</th>' : ''}${conOperatore ? '<th scope="col">Operatore</th>' : ''}
                <th scope="col">Figura</th><th scope="col">Scuola</th><th scope="col">Periodo</th><th scope="col" class="napoli-numero">Ore a settimana</th><th scope="col" aria-label="Azioni"></th></tr></thead>
            <tbody>${righe.map(c => `
                <tr class="${c.stato === 'finita' ? 'napoli-riga-archiviata' : ''}">
                    ${conAlunno ? `<td><a class="napoli-nome" href="#alunno-${c.alunno.id}">${escapeHtml(c.alunno.nome)}</a>${c.alunno.attivo ? '' : `<div class="napoli-sotto">${napoliBadge('Alunno archiviato', 'badge-secondary')}</div>`}</td>` : ''}
                    ${conOperatore ? `<td><a class="napoli-nome" href="#operatore-${c.operatore.id}">${escapeHtml(c.operatore.nome)}</a>
                        <div class="napoli-sotto">${c.ruolo === 'sostituto' ? `<span>sostituto${c.titolare ? ` di ${escapeHtml(c.titolare.operatore)}` : ''}</span>` : '<span>titolare</span>'}</div></td>` : ''}
                    <td>${escapeHtml(c.nome_figura)}${!conOperatore && c.ruolo === 'sostituto' ? '<div class="napoli-sotto">sostituto</div>' : ''}
                        ${c.da_sistemare.length ? `<div class="napoli-sotto">${napoliDaSistemare(c.da_sistemare)}</div>` : ''}</td>
                    <td>${c.scuola ? escapeHtml(c.scuola.nome) : ''}<div class="napoli-sotto">${napoliMunicipalita(c.municipalita)}</div></td>
                    <td>${this.periodoCoppia(c)}</td>
                    <td class="napoli-numero">${this.oreCoppia(c)}</td>
                    ${this.pulsantiCoppia(c)}
                </tr>`).join('')}</tbody></table>`;
    },

    // ---------- schede di alunno e operatore ----------

    async apriScheda(scheda) {
        this.parte = scheda.tipo === 'alunno' ? 'alunni' : 'operatori';
        this.segnaParte(this.parte);
        this.el('anagrafiche-elenco').hidden = true;
        const box = this.el('anagrafiche-scheda');
        box.hidden = false;
        try {
            const url = scheda.tipo === 'alunno' ? `/api/napoli/alunni/${scheda.id}`
                : `/api/napoli/operatori/${scheda.id}?lotto_id=${NapoliComune.lotto.id}`;
            this.schedaDati = Object.assign(await apiCall(url), { tipo: scheda.tipo });
        } catch (e) {
            box.innerHTML = `<div class="card-body"><div class="alert alert-danger">${escapeHtml(e.message || 'Scheda non disponibile')}</div>
                <a class="btn btn-secondary" href="#${this.parte}">Torna all'elenco</a></div>`;
            return;
        }
        if (scheda.tipo === 'alunno' && this.schedaDati.alunno.lotto.id !== NapoliComune.lotto.id) {
            window.location.hash = 'alunni';       // un alunno di un altro lotto: si torna all'elenco
            return;
        }
        box.innerHTML = scheda.tipo === 'alunno' ? this.schedaAlunno(this.schedaDati) : this.schedaOperatore(this.schedaDati);
        box.querySelector('h2')?.focus({ preventScroll: true });
        window.scrollTo({ top: 0 });
    },

    testaScheda(indietro, titolo, sotto, pulsanti) {
        return `<div class="card-header napoli-scheda-testa">
                <div class="napoli-scheda-nome">
                    <a class="napoli-indietro" href="#${indietro[0]}">${napoliSvg('M15 19l-7-7 7-7', 16)} ${indietro[1]}</a>
                    <h2 class="napoli-scheda-titolo" tabindex="-1">${escapeHtml(titolo)}</h2>
                    <div class="napoli-sotto">${sotto}</div>
                </div>
                <div class="napoli-scheda-pulsanti">${pulsanti}</div>
            </div>`;
    },

    schedaAlunno(d) {
        const a = d.alunno;
        const sotto = `<span class="napoli-cf" title="Codice fiscale (mascherato)">${escapeHtml(a.cf)}</span>
            ${a.esami ? napoliBadge('Esami', 'badge-info') : ''}
            ${a.attivo ? napoliBadge('In servizio', 'badge-success') : napoliBadge(`Archiviato dal ${formatDataIT(a.archiviato_dal)}`, 'badge-secondary')}
            ${napoliDaSistemare(a.da_sistemare)}`;
        const pulsanti = `
            <button type="button" class="btn btn-primary btn-sm" data-azione="modifica-alunno" data-id="${a.id}">${icona('matita')} Modifica</button>
            <button type="button" class="btn btn-sm btn-secondary btn-solo-icona" data-azione="altro-alunno" data-id="${a.id}" title="Altre azioni" aria-label="Altre azioni sull'alunno" aria-haspopup="menu" aria-expanded="false">${icona('altro')}</button>`;
        const pei = d.pei.length ? `<div class="table-container"><table class="table napoli-tabella-anagrafica">
                <thead><tr><th scope="col">Figura</th><th scope="col" class="napoli-numero">Ore a settimana</th><th scope="col">Periodo</th><th scope="col">Stato</th><th scope="col" aria-label="Azioni"></th></tr></thead>
                <tbody>${d.pei.map(g => g.righe.map((p, i) => `
                    <tr class="${i ? 'napoli-storico' : ''}${p.periodo === 'finita' ? ' napoli-riga-archiviata' : ''}">
                        <td>${i ? '<span class="napoli-sotto-in">prima</span>' : `<span class="napoli-figura-nome">${escapeHtml(p.nome_figura)}</span>`}</td>
                        <td class="napoli-numero"><strong>${napoliOre(p.ore_testo)}</strong></td>
                        <td>${escapeHtml(napoliPeriodo(p.valido_da, p.valido_a))}${p.id === g.in_vigore_id ? napoliBadge('in vigore', 'badge-success') : ''}${p.periodo === 'futura' ? napoliBadge('da cominciare', 'badge-info') : ''}</td>
                        <td>${escapeHtml((NAPOLI_STATI_PEI.find(x => x[0] === p.stato) || ['', p.stato])[1])}${p.fonte ? `<div class="napoli-sotto">${escapeHtml(p.fonte)}</div>` : ''}</td>
                        <td class="napoli-azioni">
                            ${i === 0 && a.attivo ? `<button type="button" class="btn btn-sm btn-secondary" data-azione="cambia-pei" data-id="${p.id}" data-figura="${escapeHtml(p.figura)}">Cambia le ore</button>` : ''}
                            <button type="button" class="btn btn-sm btn-secondary btn-solo-icona" data-azione="modifica-pei" data-id="${p.id}" title="Correggi questa riga" aria-label="Correggi questa riga del PEI">${icona('matita')}</button>
                            <button type="button" class="btn btn-sm btn-icon-danger btn-solo-icona" data-azione="elimina-pei" data-id="${p.id}" title="Elimina" aria-label="Elimina questa riga del PEI">${icona('cestino')}</button>
                        </td>
                    </tr>`).join('')).join('')}</tbody></table></div>`
            : '<p class="napoli-vuoto">Nessuna ora del PEI: aggiungi le ore settimanali da progetto di ogni figura.</p>';
        const coppie = d.coppie.length ? `<div class="table-container">${this.tabella_coppie(d.coppie, ['operatore'])}</div>`
            : '<p class="napoli-vuoto">Nessuna coppia: aggiungi l\'operatore (o gli operatori) che seguono l\'alunno.</p>';
        const credito = `<div class="napoli-credito">
                ${napoliSvg('M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z', 20)}
                <div><p class="napoli-credito-titolo">${escapeHtml(d.credito_debito.testo)}</p>
                <p class="napoli-credito-testo">${escapeHtml(d.credito_debito.spiegazione)}</p>
                ${d.credito_debito.figure.length ? `<div class="napoli-credito-figure">${d.credito_debito.figure.map(f =>
                    `<span class="napoli-chip">${escapeHtml(f.nome_figura)}: <strong>—</strong></span>`).join('')}</div>` : ''}</div>
            </div>`;
        return this.testaScheda(['alunni', 'Alunni'], a.nome_completo, sotto, pulsanti) + `
            <div class="card-body">
                <div class="napoli-dati">
                    ${rigaDati('Scuola', a.scuola ? escapeHtml(a.scuola.nome) : '')}
                    ${rigaDati('Municipalità della scuola', a.municipalita ? escapeHtml(String(a.municipalita)) : '')}
                    ${rigaDati('Grado', a.grado ? escapeHtml(napoliGradoTesto(a.grado)) + (a.grado_alunno ? '' : ' <span class="napoli-sotto-in">(della scuola)</span>')
                        : `${napoliBadge('Da decidere')} <span class="napoli-sotto-in">sceglilo nella scuola (Scuole e plessi) o qui con Modifica</span>`)}
                    ${rigaDati('Esami', a.esami ? 'Sì: il servizio continua fino alla fine degli esami' : 'No')}
                    ${rigaDati('Lotto', escapeHtml(a.lotto.nome))}
                    ${rigaDati('Da dove viene', escapeHtml(d.origine.testo))}
                    <div class="dati-riga-larga">${rigaDati('Note', a.note ? escapeHtml(a.note) : '')}</div>
                </div>
                <section class="napoli-sezione" aria-labelledby="titolo-pei">
                    <div class="napoli-sezione-testa"><h3 id="titolo-pei">Ore settimanali da progetto (PEI)</h3>
                        ${a.attivo ? `<button type="button" class="btn btn-sm btn-primary" data-azione="nuovo-pei" data-id="${a.id}">Aggiungi le ore di una figura</button>` : ''}</div>
                    ${pei}
                </section>
                <section class="napoli-sezione" aria-labelledby="titolo-coppie">
                    <div class="napoli-sezione-testa"><h3 id="titolo-coppie">Coppie con gli operatori</h3>
                        ${a.attivo ? `<button type="button" class="btn btn-sm btn-primary" data-azione="nuova-coppia-alunno" data-id="${a.id}">Aggiungi una coppia</button>` : ''}</div>
                    ${coppie}
                </section>
                <section class="napoli-sezione" aria-labelledby="titolo-credito">
                    <div class="napoli-sezione-testa"><h3 id="titolo-credito">Credito/debito ore</h3></div>
                    ${credito}
                </section>
            </div>`;
    },

    schedaOperatore(d) {
        const o = d.operatore;
        const sotto = `${o.cf ? `<span class="napoli-cf" title="Codice fiscale (mascherato)">${escapeHtml(o.cf)}</span>` : ''}
            ${o.attivo ? napoliBadge('In servizio', 'badge-success') : napoliBadge(`Archiviato dal ${formatDataIT(o.archiviato_dal)}`, 'badge-secondary')}
            ${napoliDaSistemare(o.da_sistemare)}`;
        const pulsanti = `
            <button type="button" class="btn btn-primary btn-sm" data-azione="modifica-operatore" data-id="${o.id}">${icona('matita')} Modifica</button>
            <button type="button" class="btn btn-sm btn-secondary btn-solo-icona" data-azione="altro-operatore" data-id="${o.id}" title="Altre azioni" aria-label="Altre azioni sull'operatore" aria-haspopup="menu" aria-expanded="false">${icona('altro')}</button>`;
        const coppie = d.coppie.length ? `<div class="table-container">${this.tabella_coppie(d.coppie, ['alunno'])}</div>`
            : '<p class="napoli-vuoto">Nessuna coppia: aggiungi gli alunni che segue.</p>';
        const ore = o.ore_progetto_testo
            ? `<strong>${napoliOre(o.ore_progetto_testo)}</strong> a settimana ${o.coppie_in_corso === 1 ? 'nella coppia in corso' : `nelle ${o.coppie_in_corso} coppie in corso`}${o.ore_contratto_testo ? `, su ${napoliOre(o.ore_contratto_testo)} di contratto` : ''}`
            : '';
        return this.testaScheda(['operatori', 'Operatori'], o.nome_completo, sotto, pulsanti) + `
            <div class="card-body">
                <div class="napoli-dati">
                    ${rigaDati('Figura', escapeHtml(o.nome_figura))}
                    ${rigaDati('Livello del contratto di lavoro', o.livello_ccnl ? escapeHtml(o.livello_ccnl) : '')}
                    ${rigaDati('Ore di contratto a settimana', o.ore_contratto_testo ? napoliOre(o.ore_contratto_testo) : '')}
                    ${rigaDati('Ore con gli alunni', ore)}
                    ${rigaDati('Qualifica scritta nel file', o.qualifica_originale ? escapeHtml(o.qualifica_originale) : '')}
                    ${rigaDati('Da dove viene', escapeHtml(d.origine.testo))}
                    <div class="dati-riga-larga">${rigaDati('Note', o.note ? escapeHtml(o.note) : '')}</div>
                </div>
                <section class="napoli-sezione" aria-labelledby="titolo-coppie-op">
                    <div class="napoli-sezione-testa"><h3 id="titolo-coppie-op">Coppie con gli alunni</h3>
                        ${o.attivo ? `<button type="button" class="btn btn-sm btn-primary" data-azione="nuova-coppia-operatore" data-id="${o.id}">Aggiungi una coppia</button>` : ''}</div>
                    ${coppie}
                </section>
            </div>`;
    },

    // ---------- azioni ----------

    coppiaDa(id) {
        const tutte = this.righe.concat((this.schedaDati && this.schedaDati.coppie) || []);
        return tutte.find(c => c.id === id && c.alunno && c.operatore);
    },

    azione(azione, id, pulsante) {
        const d = this.schedaDati;
        const azioni = {
            'nuova-scuola': () => this.nuovo('scuole'),
            'modifica-scuola': () => this.moduloScuola(this.righe.find(s => s.id === id)),
            'altro-scuola': () => {
                const s = this.righe.find(x => x.id === id);
                MenuAzioni.apri(pulsante, [
                    s.attiva ? { testo: 'Archivia (non c\'è più)', icona: 'archivia', azione: () => this.conferma('scuola', 'archivia', s) }
                        : { testo: 'Rimetti fra le attive', icona: 'ripristina', azione: () => this.conferma('scuola', 'ripristina', s) },
                    { testo: 'Elimina', icona: 'cestino', pericolo: true, azione: () => this.conferma('scuola', 'elimina', s) },
                ]);
            },
            'modifica-alunno': () => this.moduloAlunno(d.alunno, d),
            'altro-alunno': () => MenuAzioni.apri(pulsante, [
                d.alunno.attivo ? { testo: 'Archivia (esce dal servizio)', icona: 'archivia', azione: () => this.moduloArchivia('alunno', d.alunno) }
                    : { testo: 'Rimetti in servizio', icona: 'ripristina', azione: () => this.conferma('alunno', 'ripristina', d.alunno) },
                { testo: 'Elimina', icona: 'cestino', pericolo: true, azione: () => this.conferma('alunno', 'elimina', d.alunno, d) },
            ]),
            'modifica-operatore': () => this.moduloOperatore(d.operatore),
            'altro-operatore': () => MenuAzioni.apri(pulsante, [
                d.operatore.attivo ? { testo: 'Archivia (non lavora più)', icona: 'archivia', azione: () => this.moduloArchivia('operatore', d.operatore) }
                    : { testo: 'Rimetti in servizio', icona: 'ripristina', azione: () => this.conferma('operatore', 'ripristina', d.operatore) },
                { testo: 'Elimina', icona: 'cestino', pericolo: true, azione: () => this.conferma('operatore', 'elimina', d.operatore, d) },
            ]),
            'nuovo-pei': () => this.moduloPei({ alunno: d.alunno }),
            'cambia-pei': () => this.moduloPei({ alunno: d.alunno, figura: pulsante.dataset.figura }),
            'modifica-pei': () => this.moduloPei({ alunno: d.alunno, riga: this.rigaPei(id) }),
            'elimina-pei': () => this.conferma('pei', 'elimina', this.rigaPei(id)),
            'nuova-coppia-alunno': () => this.moduloCoppia({ alunno: d.alunno }),
            'nuova-coppia-operatore': () => this.moduloCoppia({ operatore: d.operatore }),
            'modifica-coppia': () => this.moduloCoppia({ coppia: this.coppiaDa(id) }),
            'altro-coppia': () => {
                const c = this.coppiaDa(id);
                MenuAzioni.apri(pulsante, [
                    { testo: 'Chiudi (ultimo giorno)', icona: 'archivia', azione: () => this.moduloChiudi(c) },
                    { testo: 'Subentro di un altro operatore', icona: 'ripristina', azione: () => this.moduloSubentro(c) },
                    { testo: 'Elimina', icona: 'cestino', pericolo: true, azione: () => this.conferma('coppia', 'elimina', c) },
                ]);
            },
        };
        if (azioni[azione]) azioni[azione]();
    },

    rigaPei(id) {
        for (const g of (this.schedaDati.pei || [])) {
            const p = g.righe.find(r => r.id === id);
            if (p) return p;
        }
        return null;
    },

    nuovo(parte) {
        if (parte === 'alunni') this.moduloAlunno(null);
        else if (parte === 'operatori') this.moduloOperatore(null);
        else if (parte === 'scuole') this.moduloScuola(null);
        else this.moduloCoppia({});
    },

    /** Conferme di ripristino ed eliminazione (le eliminazioni di persone non si annullano con Ctrl+Z). */
    conferma(tipo, cosa, riga, dati) {
        const nome = tipo === 'scuola' ? riga.nome : (tipo === 'pei' ? `${riga.nome_figura} ${riga.ore_testo} h`
            : (tipo === 'coppia' ? `${riga.alunno.nome} con ${riga.operatore.nome}` : riga.nome_completo));
        const url = { scuola: `/api/napoli/scuole/${riga.id}`, alunno: `/api/napoli/alunni/${riga.id}`,
            operatore: `/api/napoli/operatori/${riga.id}`, pei: `/api/napoli/pei/${riga.id}`, coppia: `/api/napoli/coppie/${riga.id}` }[tipo];
        const testi = {
            'scuola:archivia': ['Archiviare la scuola?', `«${nome}» resta per i mesi passati ma non si sceglie più per alunni e coppie. Si può archiviare solo senza alunni in servizio e coppie aperte.`, 'Archivia'],
            'scuola:ripristina': ['Rimettere la scuola fra le attive?', `«${nome}» si potrà di nuovo scegliere per alunni e coppie.`, 'Rimetti fra le attive'],
            'scuola:elimina': ['Eliminare la scuola?', `«${nome}» si elimina solo se non ha alunni, coppie e giorni del calendario (per esempio se è stata aggiunta per sbaglio). Ctrl+Z la rimette.`, 'Elimina'],
            'alunno:ripristina': ['Rimettere l\'alunno in servizio?', `${nome} torna fra gli alunni in servizio. Le coppie e i PEI chiusi restano chiusi: riaprili dalla scheda se serve.`, 'Rimetti in servizio'],
            'alunno:elimina': ['Eliminare l\'alunno?', `${nome} si elimina con le sue ${dati && dati.coppie.length ? `${dati.coppie.length} coppie e le ` : ''}ore del PEI solo se non ha ore registrate, fogli firma o orari; altrimenti va archiviato. Attenzione: l'eliminazione non si annulla con Ctrl+Z.`, 'Elimina'],
            'operatore:ripristina': ['Rimettere l\'operatore in servizio?', `${nome} torna fra gli operatori in servizio.`, 'Rimetti in servizio'],
            'operatore:elimina': ['Eliminare l\'operatore?', `${nome} si elimina solo se non ha coppie con gli alunni e ore del coordinatore; altrimenti va archiviato. Attenzione: l'eliminazione non si annulla con Ctrl+Z.`, 'Elimina'],
            'pei:elimina': ['Eliminare queste ore del PEI?', `${nome} ${napoliPeriodo(riga.valido_da, riga.valido_a)}. Se ci sono già ore registrate in questo periodo non si eliminano. Ctrl+Z le rimette.`, 'Elimina'],
            'coppia:elimina': ['Eliminare la coppia?', `${nome} (${riga.nome_figura}). Si elimina solo se non ha ore, fogli firma, orari o sostituti; altrimenti si chiude. Ctrl+Z la rimette.`, 'Elimina'],
        }[`${tipo}:${cosa}`];
        const metodo = cosa === 'elimina' ? 'DELETE' : 'POST';
        const indirizzo = cosa === 'elimina' ? url : `${url}/${cosa}`;
        showConfirmDialog(testi[0], testi[1], async () => {
            try {
                const r = await apiCall(indirizzo, { method: metodo, body: JSON.stringify({}) });
                showToast(r.messaggio, 'success', 7000);
                if (cosa === 'elimina' && (tipo === 'alunno' || tipo === 'operatore')) window.location.hash = this.parte;
                else await this.mostra();
            } catch (e) {
                showToast(e.message || 'Operazione non riuscita', 'error', 10000);
            }
        }, { type: cosa === 'elimina' ? 'danger' : 'warning', confirmText: testi[2], cancelText: 'Lascia com\'è' });
    },

    // ---------- moduli (una finestra sola, i campi da una descrizione) ----------

    /** Un campo del modulo. tipo: testo, data, numero, scelta, casella, area, sola (solo da leggere). */
    campo(c, valori) {
        const id = `ana-${c.nome}`;
        const v = valori[c.nome] === null || valori[c.nome] === undefined ? '' : valori[c.nome];
        const etichetta = `${escapeHtml(c.etichetta)}${c.obbligatorio ? ' *' : ''}`;
        const aiuto = c.aiuto ? `<p class="form-help" id="${id}-aiuto">${c.aiuto}</p>` : '';
        const descritto = c.aiuto ? ` aria-describedby="${id}-aiuto"` : '';
        if (c.tipo === 'sola') {
            return `<div class="form-group"><span class="form-label">${etichetta}</span><div class="napoli-campo-solo">${c.html || escapeHtml(String(v))}</div>${aiuto}</div>`;
        }
        if (c.tipo === 'casella') {
            return `<div class="form-group napoli-gruppo-casella"><label class="napoli-scelta-riga" for="${id}">
                <input type="checkbox" id="${id}" data-campo="${c.nome}"${v ? ' checked' : ''}${descritto}> <span>${etichetta}</span></label>${aiuto}</div>`;
        }
        let input;
        if (c.tipo === 'scelta') {
            input = `<select id="${id}" class="form-control" data-campo="${c.nome}"${descritto}>${c.opzioni.map(([valore, testo, extra]) =>
                `<option value="${escapeHtml(String(valore))}"${String(valore) === String(v) ? ' selected' : ''}${extra || ''}>${escapeHtml(testo)}</option>`).join('')}</select>`;
        } else if (c.tipo === 'area') {
            input = `<textarea id="${id}" class="form-control" data-campo="${c.nome}" rows="2" maxlength="${c.max || 500}"${descritto}>${escapeHtml(String(v))}</textarea>`;
        } else {
            const tipo = c.tipo === 'data' ? 'date' : 'text';
            const extra = c.tipo === 'numero' ? ' inputmode="decimal"' : '';
            input = `<input type="${tipo}" id="${id}" class="form-control" data-campo="${c.nome}" value="${escapeHtml(String(v))}"${extra}
                ${c.max ? ` maxlength="${c.max}"` : ''}${c.placeholder ? ` placeholder="${escapeHtml(c.placeholder)}"` : ''}${c.lista ? ` list="${id}-lista"` : ''}
                autocomplete="off" spellcheck="false"${descritto}>${c.lista ? `<datalist id="${id}-lista">${c.lista.map(x => `<option value="${escapeHtml(x)}">`).join('')}</datalist>` : ''}`;
        }
        return `<div class="form-group" data-gruppo="${c.nome}"${c.nascosto ? ' hidden' : ''}><label class="form-label" for="${id}">${etichetta}</label>${input}${aiuto}</div>`;
    },

    /** Apre la finestra con i campi (righe: un campo o un elenco di campi sulla stessa riga). */
    apriModulo({ titolo, intro, righe, valori = {}, salva = 'Salva', invia, prepara }) {
        const form = this.el('form-anagrafica');
        this.el('anagrafica-titolo').textContent = titolo;
        this.el('anagrafica-salva').textContent = salva;
        form.innerHTML = (intro ? `<p class="napoli-intro">${intro}</p>` : '') + righe.map(r => (Array.isArray(r)
            ? `<div class="form-row">${r.map(c => this.campo(c, valori)).join('')}</div>` : this.campo(r, valori))).join('');
        napoliPulisciErrori(form);
        this.modulo = { invia };
        if (typeof prepara === 'function') prepara(form);
        openModal('napoli-modal-anagrafica');
        setTimeout(() => form.querySelector('input:not([type=checkbox]):not([disabled]), select, textarea')?.focus(), 60);
    },

    leggiModulo() {
        const dati = {};
        this.el('form-anagrafica').querySelectorAll('[data-campo]').forEach(el => {
            if (el.closest('[hidden]')) return;
            dati[el.dataset.campo] = el.type === 'checkbox' ? el.checked : el.value.trim();
        });
        return dati;
    },

    async invia() {
        if (!this.modulo) return;
        const form = this.el('form-anagrafica');
        const pulsante = this.el('anagrafica-salva');
        if (pulsante.disabled) return;
        napoliPulisciErrori(form);
        setButtonLoading(pulsante, true);
        try {
            const r = await this.modulo.invia(this.leggiModulo());
            closeModal('napoli-modal-anagrafica');
            const avvisi = (r.avvisi || []).filter(Boolean);
            showToast(`${r.messaggio}.${avvisi.length ? ' ' + avvisi.join(' ') : ''}`.replace('..', '.'),
                avvisi.length ? 'warning' : 'success', avvisi.length ? 10000 : 6000);
            const h = window.location.hash;
            if (r.alunno_id && !h.startsWith('#alunno-')) window.location.hash = `alunno-${r.alunno_id}`;
            else if (r.operatore_id && !h.startsWith('#operatore-')) window.location.hash = `operatore-${r.operatore_id}`;
            else if (r.scuola_id && h !== '#scuole') window.location.hash = 'scuole';
            else await this.mostra();
        } catch (e) {
            napoliMostraErrore(e, form);
        } finally {
            setButtonLoading(pulsante, false);
        }
    },

    opzioniScuole(scelta) {
        return [['', '— scegli —']].concat(this.riepilogo.scuole.filter(s => s.attiva || s.id === scelta).map(s =>
            [s.id, `${s.nome}${s.municipalita ? ` (municipalità ${s.municipalita})` : ''}${s.attiva ? '' : ' (archiviata)'}`]));
    },

    opzioniFigure(perCoppia, vuota = '— scegli —') {
        return [['', vuota]].concat((NapoliComune.figure || []).filter(f => !perCoppia || !f.ore_di_lotto)
            .map(f => [f.codice, `${f.nome}${napoliDescrizioneDiversa(f) ? ` (${f.descrizione})` : ''}`]));
    },

    moduloScuola(s) {
        const nuova = !s;
        const municipalita = [['', '— scegli —']].concat(this.riepilogo.municipalita_possibili.map(m => [m, String(m)]));
        this.apriModulo({
            titolo: nuova ? 'Nuova scuola o plesso' : 'Modifica la scuola',
            intro: 'Lo stesso codice meccanografico in due municipalità sono due plessi: se la scuola è in un\'altra municipalità, aggiungi un altro plesso.',
            righe: [
                { nome: 'nome', etichetta: 'Nome della scuola o del plesso', obbligatorio: true, max: 200 },
                [{ nome: 'codice_meccanografico', etichetta: 'Codice meccanografico', max: 12, placeholder: 'per esempio NAIC8ZZ001' },
                    { nome: 'municipalita', etichetta: 'Municipalità', tipo: 'scelta', obbligatorio: true, opzioni: municipalita }],
                { nome: 'grado', etichetta: 'Grado', tipo: 'scelta', opzioni: [['inferiore', 'Grado inferiore (infanzia, primaria, secondaria di I grado)'],
                    ['superiore', 'Grado superiore (secondaria di II grado)'], ['misto', 'Misto: si sceglie per ogni alunno'], ['', 'Da decidere']],
                aiuto: 'Il grado decide in quale fattura vanno le ore. <span id="ana-grado-proposto"></span>' },
            ],
            valori: nuova ? { grado: '' } : s,
            salva: nuova ? 'Aggiungi la scuola' : 'Salva la scuola',
            invia: (dati) => apiCall(nuova ? `/api/napoli/lotti/${NapoliComune.lotto.id}/scuole` : `/api/napoli/scuole/${s.id}`,
                { method: nuova ? 'POST' : 'PUT', body: JSON.stringify(dati) }),
            prepara: (form) => {
                const codice = form.querySelector('#ana-codice_meccanografico');
                const proposta = () => {
                    const tipo = codice.value.replace(/\s/g, '').toUpperCase().slice(2, 4);
                    const g = ['IC', 'AA', 'EE', 'MM', 'CT', '1A', '1E', '1M'].includes(tipo) ? 'inferiore'
                        : (['IS', 'PC', 'PS', 'PM', 'TD', 'TF', 'RH', 'RI', 'SD', 'TL'].includes(tipo) ? 'superiore' : '');
                    form.querySelector('#ana-grado-proposto').textContent = g ? `Dal codice sembra ${NAPOLI_GRADO_SCUOLA[g].toLowerCase()}: controlla.` : '';
                };
                codice.addEventListener('input', proposta);
                proposta();
            },
        });
    },

    moduloAlunno(a, d) {
        const nuovo = !a;
        const gradi = [['', 'Quello della scuola'], ['inferiore', 'Grado inferiore'], ['superiore', 'Grado superiore']];
        this.apriModulo({
            titolo: nuovo ? 'Nuovo alunno' : 'Modifica l\'alunno',
            righe: [
                [{ nome: 'cognome', etichetta: 'Cognome', obbligatorio: true, max: 80 }, { nome: 'nome', etichetta: 'Nome', obbligatorio: true, max: 80 }],
                { nome: 'codice_fiscale', etichetta: 'Codice fiscale', obbligatorio: nuovo, max: 16,
                    placeholder: nuovo ? '16 lettere e cifre' : `salvato: ${a.cf}`,
                    aiuto: nuovo ? 'Serve per riconoscere l\'alunno nel file Excel del Comune. A schermo si vede solo in parte.'
                        : 'Il codice salvato non si mostra intero: scrivilo solo se è da correggere. Il cambio non si annulla con Ctrl+Z.' },
                { nome: 'scuola_id', etichetta: 'Scuola (plesso)', tipo: 'scelta', obbligatorio: true, opzioni: this.opzioniScuole(a && a.scuola && a.scuola.id),
                    aiuto: 'La municipalità è quella della scuola.' },
                [{ nome: 'grado', etichetta: 'Grado', tipo: 'scelta', opzioni: gradi, aiuto: 'Da scegliere se la scuola è mista.' },
                    { nome: 'esami', etichetta: 'Ha gli esami (servizio fino alla fine degli esami, a luglio)', tipo: 'casella' }],
                { nome: 'note', etichetta: 'Note', tipo: 'area', aiuto: 'Niente dati sanitari (art. 12.3 del capitolato). Le modifiche alle note non si annullano con Ctrl+Z.' },
            ],
            valori: nuovo ? {} : { cognome: a.cognome, nome: a.nome, scuola_id: a.scuola && a.scuola.id, grado: a.grado_alunno || '', esami: a.esami, note: a.note },
            salva: nuovo ? 'Aggiungi l\'alunno' : 'Salva',
            invia: (dati) => apiCall(nuovo ? `/api/napoli/lotti/${NapoliComune.lotto.id}/alunni` : `/api/napoli/alunni/${a.id}`,
                { method: nuovo ? 'POST' : 'PUT', body: JSON.stringify(dati) }),
        });
    },

    moduloOperatore(o) {
        const nuovo = !o;
        this.apriModulo({
            titolo: nuovo ? 'Nuovo operatore' : 'Modifica l\'operatore',
            righe: [
                [{ nome: 'cognome', etichetta: 'Cognome', obbligatorio: true, max: 80 }, { nome: 'nome', etichetta: 'Nome', obbligatorio: true, max: 80 }],
                { nome: 'codice_fiscale', etichetta: 'Codice fiscale', max: 16,
                    placeholder: nuovo ? '16 lettere e cifre' : (o.cf ? `salvato: ${o.cf}` : 'non c\'è: scrivilo'),
                    aiuto: nuovo ? 'Serve per riconoscere l\'operatore nel file Excel.'
                        : 'Il codice salvato non si mostra intero: scrivilo solo se è da correggere. Il cambio non si annulla con Ctrl+Z.' },
                [{ nome: 'figura', etichetta: 'Figura professionale', tipo: 'scelta', obbligatorio: true, opzioni: this.opzioniFigure(false) },
                    { nome: 'livello_ccnl', etichetta: 'Livello', max: 10, lista: NAPOLI_LIVELLI, placeholder: 'per esempio D2' }],
                { nome: 'ore_contratto', etichetta: 'Ore di contratto a settimana', tipo: 'numero', placeholder: 'per esempio 25 o 25,5' },
                { nome: 'note', etichetta: 'Note', tipo: 'area', aiuto: 'Niente dati sanitari. Le modifiche alle note non si annullano con Ctrl+Z.' },
            ],
            valori: nuovo ? {} : { cognome: o.cognome, nome: o.nome, figura: o.figura, livello_ccnl: o.livello_ccnl,
                ore_contratto: o.ore_contratto_testo, note: o.note },
            salva: nuovo ? 'Aggiungi l\'operatore' : 'Salva',
            invia: (dati) => apiCall(nuovo ? '/api/napoli/operatori' : `/api/napoli/operatori/${o.id}`,
                { method: nuovo ? 'POST' : 'PUT', body: JSON.stringify(dati) }),
        });
    },

    moduloPei({ alunno, figura, riga }) {
        const modifica = !!riga;
        const stati = NAPOLI_STATI_PEI.map(([v, t]) => [v, t]);
        const figuraFissa = modifica ? riga.figura : figura;
        this.apriModulo({
            titolo: modifica ? 'Correggi le ore del PEI' : (figura ? `Cambia le ore del PEI: ${NapoliComune.nomeFigura(figura)}` : 'Ore del PEI di una figura'),
            intro: modifica ? 'Correggi questa riga se è stata scritta male. Per un cambio da un certo giorno usa invece «Cambia le ore».'
                : 'Le ore settimanali da progetto valgono dal giorno scelto: se la figura aveva già delle ore, quelle di prima valgono fino al giorno prima.',
            righe: [
                figuraFissa ? { nome: 'figura_testo', etichetta: 'Figura', tipo: 'sola', html: escapeHtml(NapoliComune.nomeFigura(figuraFissa)) }
                    : { nome: 'figura', etichetta: 'Figura', tipo: 'scelta', obbligatorio: true, opzioni: this.opzioniFigure(true) },
                [{ nome: 'ore_settimanali', etichetta: 'Ore a settimana', tipo: 'numero', obbligatorio: true, placeholder: 'per esempio 13 o 12,5' },
                    { nome: 'stato', etichetta: 'Stato del PEI', tipo: 'scelta', opzioni: stati }],
                [{ nome: 'valido_da', etichetta: 'Valgono dal', tipo: 'data', obbligatorio: true },
                    { nome: 'valido_a', etichetta: 'fino al', tipo: 'data', aiuto: 'Vuoto = senza una data di fine.' }],
                { nome: 'fonte', etichetta: 'Nota (da dove viene)', max: 200, placeholder: 'per esempio: verbale GLO del 10/10/2026' },
            ],
            valori: modifica ? { ore_settimanali: riga.ore_testo, stato: riga.stato, valido_da: riga.valido_da, valido_a: riga.valido_a, fonte: riga.fonte }
                : { valido_da: napoliOggi(), stato: 'definitivo' },
            salva: 'Salva le ore',
            invia: (dati) => {
                if (!modifica && figura) dati.figura = figura;
                return apiCall(modifica ? `/api/napoli/pei/${riga.id}` : `/api/napoli/alunni/${alunno.id}/pei`,
                    { method: modifica ? 'PUT' : 'POST', body: JSON.stringify(dati) });
            },
        });
    },

    async elenchiPerCoppia() {
        const lotto = NapoliComune.lotto.id;
        const [alunni, operatori, coppie] = await Promise.all([
            apiCall(`/api/napoli/lotti/${lotto}/alunni?stato=attivi`),
            apiCall(`/api/napoli/lotti/${lotto}/operatori?stato=attivi`),
            apiCall(`/api/napoli/lotti/${lotto}/coppie?stato=tutte`)]);
        return { alunni: alunni.righe, operatori: operatori.righe, coppie: coppie.righe };
    },

    async moduloCoppia({ coppia, alunno, operatore }) {
        let elenchi;
        try {
            elenchi = await this.elenchiPerCoppia();
        } catch (e) {
            showToast(e.message || 'Dati non disponibili', 'error');
            return;
        }
        const nuova = !coppia;
        const titolari = (alunnoId, figura) => [['', '— scegli —']].concat(elenchi.coppie
            .filter(c => c.ruolo === 'titolare' && c.alunno.id === Number(alunnoId) && c.figura === figura && (!coppia || c.id !== coppia.id))
            .map(c => [c.id, `${c.operatore.nome} (${napoliPeriodo(c.valido_da, c.valido_a)})`]));
        const righe = [];
        if (nuova) {
            righe.push(alunno ? { nome: 'alunno_testo', etichetta: 'Alunno', tipo: 'sola', html: escapeHtml(alunno.nome_completo) }
                : { nome: 'alunno_id', etichetta: 'Alunno', tipo: 'scelta', obbligatorio: true,
                    opzioni: [['', '— scegli —']].concat(elenchi.alunni.map(a => [a.id, `${a.nome_completo}${a.scuola ? ' · ' + a.scuola.nome : ''}`])) });
            righe.push(operatore ? { nome: 'operatore_testo', etichetta: 'Operatore', tipo: 'sola', html: `${escapeHtml(operatore.nome_completo)} (${escapeHtml(operatore.nome_figura)})` }
                : { nome: 'operatore_id', etichetta: 'Operatore', tipo: 'scelta', obbligatorio: true,
                    opzioni: [['', '— scegli —']].concat(elenchi.operatori.map(o => [o.id, `${o.nome_completo} (${o.nome_figura})`])) });
            righe.push([{ nome: 'figura', etichetta: 'Figura della coppia', tipo: 'scelta', opzioni: this.opzioniFigure(true, 'quella dell\'operatore'),
                aiuto: 'Le ore si contano con la figura della coppia.' },
            { nome: 'ruolo', etichetta: 'Ruolo', tipo: 'scelta', opzioni: [['titolare', 'Titolare'], ['sostituto', 'Sostituto (SI nel file)']] }]);
        } else {
            righe.push({ nome: 'chi', etichetta: 'Coppia', tipo: 'sola',
                html: `${escapeHtml(coppia.alunno.nome)} con ${escapeHtml(coppia.operatore.nome)} · ${escapeHtml(coppia.nome_figura)}${coppia.ruolo === 'sostituto' ? ' · sostituto' : ''}`,
                aiuto: 'Alunno, operatore e figura non si cambiano: per un altro operatore usa «Subentro».' });
        }
        righe.push({ nome: 'titolare_coppia_id', etichetta: 'Sostituisce', tipo: 'scelta', obbligatorio: true,
            opzioni: coppia ? titolari(coppia.alunno.id, coppia.figura) : [['', '— scegli prima alunno e figura —']],
            nascosto: !(coppia && coppia.ruolo === 'sostituto') });
        righe.push({ nome: 'scuola_id', etichetta: 'Scuola (plesso) del foglio firma', tipo: 'scelta', obbligatorio: true,
            opzioni: this.opzioniScuole(coppia && coppia.scuola && coppia.scuola.id) });
        righe.push([{ nome: 'valido_da', etichetta: 'Dal', tipo: 'data', obbligatorio: true },
            { nome: 'valido_a', etichetta: 'Al', tipo: 'data', aiuto: 'Vuoto = senza una data di fine.' }]);
        righe.push({ nome: 'ore_settimanali', etichetta: 'Ore a settimana della coppia', tipo: 'numero', placeholder: 'vuoto = tutte le ore del PEI della figura',
            aiuto: 'Solo se l\'alunno ha più operatori della stessa figura e le ore sono divise.' });
        righe.push({ nome: 'note', etichetta: 'Note', tipo: 'area', aiuto: 'Niente dati sanitari.' });
        const valori = coppia ? { titolare_coppia_id: coppia.titolare && coppia.titolare.id, scuola_id: coppia.scuola && coppia.scuola.id,
            valido_da: coppia.valido_da, valido_a: coppia.valido_a, ore_settimanali: coppia.ore_da === 'quota' ? coppia.ore_testo : '', note: coppia.note }
            : { valido_da: napoliOggi(), ruolo: 'titolare', figura: '', scuola_id: alunno && alunno.scuola ? alunno.scuola.id : '' };
        this.apriModulo({
            titolo: nuova ? 'Nuova coppia operatore-alunno' : 'Modifica la coppia',
            intro: nuova ? 'Una coppia è un operatore che segue un alunno per una figura: corrisponde a una riga del file Excel e a un foglio firma al mese.' : '',
            righe, valori, salva: nuova ? 'Aggiungi la coppia' : 'Salva la coppia',
            invia: (dati) => {
                if (alunno) dati.alunno_id = alunno.id;
                if (operatore) dati.operatore_id = operatore.id;
                return apiCall(nuova ? `/api/napoli/lotti/${NapoliComune.lotto.id}/coppie` : `/api/napoli/coppie/${coppia.id}`,
                    { method: nuova ? 'POST' : 'PUT', body: JSON.stringify(dati) });
            },
            prepara: (form) => {
                if (!nuova) return;
                const q = (n) => form.querySelector(`#ana-${n}`);
                const aggiorna = () => {
                    const alunnoId = alunno ? alunno.id : q('alunno_id').value;
                    const op = operatore || elenchi.operatori.find(o => String(o.id) === (q('operatore_id') || {}).value);
                    const figura = q('figura').value || (op ? op.figura : '');
                    const sostituto = q('ruolo').value === 'sostituto';
                    form.querySelector('[data-gruppo="titolare_coppia_id"]').hidden = !sostituto;
                    const sel = q('titolare_coppia_id');
                    const prima = sel.value;
                    sel.innerHTML = (alunnoId && figura ? titolari(alunnoId, figura) : [['', '— scegli prima alunno e figura —']])
                        .map(([v, t]) => `<option value="${escapeHtml(String(v))}">${escapeHtml(t)}</option>`).join('');
                    sel.value = prima;
                };
                const scuolaDellAlunno = () => {
                    const a = elenchi.alunni.find(x => String(x.id) === q('alunno_id').value);
                    if (a && a.scuola) q('scuola_id').value = String(a.scuola.id);
                };
                ['figura', 'ruolo', 'operatore_id'].forEach(n => q(n) && q(n).addEventListener('change', aggiorna));
                if (q('alunno_id')) q('alunno_id').addEventListener('change', () => { scuolaDellAlunno(); aggiorna(); });
                aggiorna();
            },
        });
    },

    moduloChiudi(c) {
        this.apriModulo({
            titolo: 'Chiudi la coppia',
            intro: `${escapeHtml(c.alunno.nome)} con ${escapeHtml(c.operatore.nome)} (${escapeHtml(c.nome_figura)}): scegli l'ultimo giorno di servizio. La coppia resta per i mesi passati.`,
            righe: [{ nome: 'valido_a', etichetta: 'Ultimo giorno', tipo: 'data', obbligatorio: true }],
            valori: { valido_a: c.valido_a || napoliOggi() },
            salva: 'Chiudi la coppia',
            invia: (dati) => apiCall(`/api/napoli/coppie/${c.id}/chiudi`, { method: 'POST', body: JSON.stringify(dati) }),
        });
    },

    async moduloSubentro(c) {
        let operatori;
        try {
            operatori = (await apiCall(`/api/napoli/lotti/${NapoliComune.lotto.id}/operatori?stato=attivi`)).righe;
        } catch (e) {
            showToast(e.message || 'Dati non disponibili', 'error');
            return;
        }
        const stessa = operatori.filter(o => o.id !== c.operatore.id).sort((a, b) => (a.figura !== c.figura) - (b.figura !== c.figura));
        this.apriModulo({
            titolo: 'Subentro di un altro operatore',
            intro: `${escapeHtml(c.alunno.nome)} · ${escapeHtml(c.nome_figura)}: dal giorno scelto l'alunno è seguito da un altro operatore. La coppia con ${escapeHtml(c.operatore.nome)} finisce il giorno prima; la nuova ha la stessa scuola e le stesse ore.`,
            righe: [{ nome: 'operatore_id', etichetta: 'Nuovo operatore', tipo: 'scelta', obbligatorio: true,
                opzioni: [['', '— scegli —']].concat(stessa.map(o => [o.id, `${o.nome_completo} (${o.nome_figura})`])) },
            { nome: 'dal', etichetta: 'Dal giorno', tipo: 'data', obbligatorio: true }],
            valori: { dal: napoliOggi() },
            salva: 'Fai il subentro',
            invia: (dati) => apiCall(`/api/napoli/coppie/${c.id}/subentro`, { method: 'POST', body: JSON.stringify(dati) }),
        });
    },

    moduloArchivia(tipo, riga) {
        const alunno = tipo === 'alunno';
        this.apriModulo({
            titolo: alunno ? 'Archivia l\'alunno' : 'Archivia l\'operatore',
            intro: alunno
                ? `${escapeHtml(riga.nome_completo)} esce dal servizio dal giorno scelto: le sue coppie e le ore del PEI ancora aperte finiscono il giorno prima. Resta tutto per i mesi passati; Ctrl+Z rimette com'era.`
                : `${escapeHtml(riga.nome_completo)} non lavora più dal giorno scelto. Se ha ancora coppie da quel giorno, prima chiudile o fai il subentro con un altro operatore.`,
            righe: [{ nome: 'dal', etichetta: alunno ? 'Esce dal servizio dal' : 'Non lavora più dal', tipo: 'data', obbligatorio: true }],
            valori: { dal: napoliOggi() },
            salva: 'Archivia',
            invia: (dati) => apiCall(`/api/napoli/${alunno ? 'alunni' : 'operatori'}/${riga.id}/archivia`, { method: 'POST', body: JSON.stringify(dati) }),
        });
    },
};

// ==================== scheda Importa (anagrafica dal file Excel "master") ====================

const NAPOLI_GRADI_SCUOLA = [
    ['inferiore', 'Grado inferiore'], ['superiore', 'Grado superiore'],
    ['misto', 'Misto (si sceglie per alunno)'], ['', 'Da decidere'],
];
// Bloccanti che si sistemano scegliendo nella pagina (non correggendo il file).
const NAPOLI_SCELTE_BLOCCANTI = ['qualifica_non_collegata', 'municipalita_da_scegliere'];
const NAPOLI_ICONE_LIVELLO = { bloccante: NAPOLI_ICONE_STATO.manca, avviso: NAPOLI_ICONE_STATO.avviso, nota: NAPOLI_ICONE_STATO.ok };

function napoliDataOra(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(iso || '');
    return m ? `${m[3]}/${m[2]}/${m[1]} alle ${m[4]}:${m[5]}` : formatDataIT(iso);
}

function napoliDimensione(byte) {
    if (byte < 1024) return `${byte} byte`;
    if (byte < 1024 * 1024) return `${Math.round(byte / 1024)} KB`;
    return `${(byte / 1024 / 1024).toLocaleString('it-IT', { maximumFractionDigits: 1 })} MB`;
}

function napoliMaiuscola(testo) {
    const t = String(testo || '');
    return t.charAt(0).toUpperCase() + t.slice(1);
}

function napoliNumeroIt(n) {
    return Number(n || 0).toLocaleString('it-IT');
}

/** "riga 41", "righe 3, 7", "righe 1, 2, … 20 e altre 5": le righe del file di una voce
 *  (il server ne manda al massimo 20, n e' quante sono in tutto). */
function napoliRigheTesto(righe, n = righe.length) {
    const altre = n > righe.length ? ` e altre ${napoliNumeroIt(n - righe.length)}` : '';
    return `${n === 1 ? 'riga' : 'righe'} ${righe.join(', ')}${altre}`;
}

/** "3 giorni nuovi, 1 cambiato": solo le voci con un numero diverso da zero. Ogni voce e'
 *  [numero, testo al plurale, testo al singolare (se diverso)]. */
function napoliElenco(voci) {
    const scritte = voci.filter(([n]) => n).map(([n, plurale, singolare]) =>
        `${napoliNumeroIt(n)} ${n === 1 && singolare ? singolare : plurale}`);
    return scritte.length ? scritte.join(', ') : '';
}

/** Testi della pagina che cambiano con il modo: l'anagrafica (l'azione principale,
 *  REGOLE 14) o le ore dei giorni di un mese (l'opzione secondaria). */
const NAPOLI_MODI_IMPORT = {
    anagrafica: {
        attesa: 'Leggo il file e preparo l\'anteprima dell\'anagrafica…',
        titolo: () => 'Anteprima dell\'anagrafica',
        pulsante: () => 'Carica l\'anagrafica',
    },
    ore: {
        attesa: 'Leggo il file e preparo l\'anteprima delle ore del mese…',
        titolo: (a) => `Anteprima delle ore: foglio presenze di ${a.file.mese_testo}`,
        pulsante: (a) => `Importa le ore di ${a.file.mese_testo}`,
    },
    confronto: { attesa: 'Confronto le ore del file con Assisto…' },
};

const NapoliImport = {
    file: null,           // {nome, dati (ArrayBuffer), dimensione}
    anteprima: null,      // ultima risposta (anteprima o confronto); anteprima.modo = 'anagrafica' | 'ore' | 'confronto'
    scelte: {},           // le scelte fatte nella pagina, mandate a ogni anteprima e alla conferma
    seq: 0,               // scarta le risposte superate da una richiesta piu' recente
    timer: null,
    storico: [],

    el(id) { return document.getElementById(id); },

    async avvia() {
        NapoliComune.alCambioLotto = async () => { this.azzera(); await this.mostraLotto(); };
        NapoliComune.dopoAnnulla = async () => { await NapoliComune.caricaLotti(); this.azzera(); await this.mostraLotto(); };
        this.collega();
        try {
            await Promise.all([NapoliComune.caricaLotti(), NapoliComune.caricaFigure()]);
        } catch (e) {
            this.el('import-risultato').innerHTML = `<div class="alert alert-danger">${escapeHtml(e.message || 'Dati non disponibili')}</div>`;
            return;
        }
        await this.mostraLotto();
    },

    async mostraLotto() {
        const lotto = NapoliComune.lotto;
        const senza = this.el('import-senza-lotto');
        senza.hidden = !!lotto;
        this.el('import-scelta').hidden = !lotto;
        this.el('import-storico-card').hidden = !lotto;
        if (!lotto) {
            senza.innerHTML = `<div class="card">${napoliBenvenuto()}</div>`;
            return;
        }
        await this.caricaStorico();
    },

    collega() {
        const zona = this.el('import-file-zona');
        const input = this.el('import-file');
        zona.addEventListener('click', (e) => { if (e.target !== input) input.click(); });
        zona.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
        });
        input.addEventListener('change', () => {
            const f = input.files && input.files[0];
            input.value = '';            // si puo' scegliere di nuovo lo stesso file (anche dopo averlo corretto)
            this.scegli(f);
        });
        ['dragenter', 'dragover'].forEach(t => zona.addEventListener(t, (e) => { e.preventDefault(); zona.classList.add('dragover'); }));
        ['dragleave', 'drop'].forEach(t => zona.addEventListener(t, (e) => { e.preventDefault(); zona.classList.remove('dragover'); }));
        zona.addEventListener('drop', (e) => this.scegli(e.dataTransfer && e.dataTransfer.files[0]));
        this.el('btn-import-cambia').addEventListener('click', () => input.click());
        this.el('btn-import-anteprima').addEventListener('click', () => this.chiedi('anagrafica'));
        this.el('btn-import-ore').addEventListener('click', () => this.chiedi('ore'));
        this.el('btn-import-confronta').addEventListener('click', () => this.chiedi('confronto'));
        this.el('napoli-annulla-ultima').addEventListener('click', () => NapoliComune.annulla());
        this.el('import-senza-lotto').addEventListener('click', (e) => {
            if (e.target.closest('[data-azione="crea-lotto"]')) {
                NapoliProcedura.apri(async (lotto) => { await NapoliComune.caricaLotti(lotto.id); await this.mostraLotto(); });
            }
        });
        const risultato = this.el('import-risultato');
        risultato.addEventListener('change', (e) => this.cambiaScelta(e.target));
        risultato.addEventListener('click', (e) => {
            const b = e.target.closest('[data-azione]');
            if (!b) return;
            if (b.dataset.azione === 'importa') this.importa();
            else if (b.dataset.azione === 'lascia') this.azzera(true);
            else if (b.dataset.azione === 'altro-file') { this.azzera(true); this.el('import-file').click(); }
            else if (b.dataset.azione === 'anteprima-ore') this.chiedi('ore');
        });
        this.el('import-storico').addEventListener('click', (e) => {
            const b = e.target.closest('[data-annulla-import]');
            if (b) this.annullaImport(Number(b.dataset.annullaImport));
        });
    },

    /** Il file scelto si legge subito: se e' aperto in Excel su Windows il browser non lo
     *  puo' leggere, e lo si dice qui con parole semplici. Poi l'anteprima dell'anagrafica. */
    async scegli(file) {
        if (!file) return;
        this.azzera(true);
        const nome = file.name || '';
        if (nome.startsWith('~$')) {
            this.errore('Hai scelto il file temporaneo che Excel crea mentre il foglio è aperto (il nome comincia con ~$). Chiudi Excel e scegli il file vero, quello senza ~$ all\'inizio del nome.');
            return;
        }
        if (/\.xls$/i.test(nome)) {
            this.errore('Il file è nel formato vecchio di Excel (.xls): aprilo in Excel e salvalo come «Cartella di lavoro di Excel (.xlsx)», poi sceglilo di nuovo.');
            return;
        }
        if (!/\.(xlsx|xlsm)$/i.test(nome)) {
            this.errore('Scegli il file Excel con gli operatori e gli alunni (con il nome che finisce per .xlsx).');
            return;
        }
        let dati;
        try {
            dati = await file.arrayBuffer();
        } catch (e) {
            this.errore('Il file non si riesce ad aprire: probabilmente è aperto in Excel. Chiudi il file in Excel e sceglilo di nuovo.');
            return;
        }
        this.file = { nome, dati, dimensione: file.size };
        this.el('import-file-nome').textContent = nome;
        this.el('import-file-info').textContent = napoliDimensione(file.size);
        this.el('import-file-zona').hidden = true;
        this.el('import-file-scelto').hidden = false;
        this.pulsanti(true);
        this.chiedi('anagrafica');
    },

    pulsanti(attivi) {
        ['btn-import-anteprima', 'btn-import-ore', 'btn-import-confronta'].forEach(id => {
            this.el(id).disabled = !attivi || !this.file;
        });
    },

    /** Torna alla scelta del file (togliFile: anche il file scelto). */
    azzera(togliFile = false) {
        this.seq++;
        clearTimeout(this.timer);
        this.anteprima = null;
        this.scelte = {};
        this.el('import-risultato').innerHTML = '';
        if (togliFile) {
            this.file = null;
            this.el('import-file-zona').hidden = false;
            this.el('import-file-scelto').hidden = true;
        }
        this.pulsanti(true);
    },

    /** Il messaggio rosso (file aperto in Excel, file temporaneo ~$, .xls, file rovinato...)
     *  sta sotto la scheda di scelta: la pagina lo porta in vista (a 1366x768 sarebbe fuori
     *  dallo schermo, REGOLE 13), con il pulsante per scegliere di nuovo il file. */
    errore(messaggio, titolo = 'Il file non si può usare') {
        const box = this.el('import-risultato');
        box.innerHTML = `
            <div class="card napoli-esito">
                <div class="alert alert-danger" role="alert" tabindex="-1">
                    ${napoliSvg(NAPOLI_ICONE_STATO.manca, 22)}
                    <div><strong>${escapeHtml(titolo)}</strong><br>${escapeHtml(messaggio)}</div>
                </div>
                <div class="napoli-azioni-modulo">
                    <button type="button" class="btn btn-primary" data-azione="altro-file">Scegli di nuovo il file</button>
                </div>
            </div>`;
        this.inVista(box.querySelector('.napoli-esito'), false);
        box.querySelector('.alert').focus({ preventScroll: true });
    },

    /** Porta in vista (in cima, sotto la barra in alto) il riquadro del risultato. */
    inVista(el, liscio = true) {
        if (el) el.scrollIntoView({ behavior: liscio ? 'smooth' : 'auto', block: 'start' });
    },

    /** Manda il file (gia' letto) con il lotto e gli altri campi. Errori con il messaggio del server. */
    async invia(url, campi) {
        const dati = new FormData();
        dati.append('file', new Blob([this.file.dati]), this.file.nome);
        dati.append('lotto_id', String(NapoliComune.lotto.id));
        Object.entries(campi).forEach(([k, v]) => dati.append(k, v));
        let risposta;
        try {
            risposta = await fetch(url, { method: 'POST', body: dati });
        } catch (e) {
            throw new Error('Il collegamento con Assisto si è interrotto: controlla che il programma sia aperto e riprova.');
        }
        const corpo = await risposta.json().catch(() => ({}));
        if (!risposta.ok) {
            const err = new Error(corpo.error || (risposta.status === 413
                ? 'Il file è troppo grande: controlla di aver scelto il file Excel giusto.'
                : 'Qualcosa non ha funzionato: riprova tra qualche secondo.'));
            err.status = risposta.status;
            err.code = corpo.code || null;
            err.data = corpo;
            throw err;
        }
        return corpo;
    },

    /** Anteprima ('anagrafica' o 'ore') o solo confronto. aggiorna: dopo una scelta, la
     *  stessa anteprima ricalcolata. */
    async chiedi(modo, aggiorna = false) {
        if (!this.file || !NapoliComune.lotto) return;
        const seq = ++this.seq;
        const box = this.el('import-risultato');
        if (!aggiorna) {
            this.scelte = {};
            box.innerHTML = `<div class="card napoli-esito"><div class="loading"><div class="spinner"></div></div>
                <p class="napoli-attesa">${escapeHtml(NAPOLI_MODI_IMPORT[modo].attesa)}</p></div>`;
            this.inVista(box.querySelector('.napoli-esito'));
        } else {
            box.querySelector('.napoli-anteprima')?.classList.add('napoli-in-aggiornamento');
        }
        this.pulsanti(false);
        try {
            const r = await this.invia('/api/napoli/import/anteprima', { modo, scelte: JSON.stringify(this.scelte) });
            if (seq !== this.seq) return;
            this.anteprima = r;
            if (r.modo === 'confronto') this.disegnaConfronto(r);
            else this.disegnaAnteprima(r, aggiorna);
        } catch (e) {
            // senza risposta (Assisto chiuso) o con un errore del programma non e' colpa del file
            const titolo = !e.status ? 'Assisto non risponde' : (e.status >= 500 ? 'Qualcosa non ha funzionato' : undefined);
            if (seq === this.seq) this.errore(e.message, titolo);
        } finally {
            if (seq === this.seq) this.pulsanti(true);
        }
    },

    /** Una scelta della pagina: si ricorda e l'anteprima si ricalcola (le conferme no). */
    cambiaScelta(el) {
        const tipo = el.dataset.scelta;
        if (!tipo || !this.anteprima) return;
        const s = this.scelte;
        if (tipo === 'conferma') {
            s.conferme = [...this.el('import-risultato').querySelectorAll('[data-scelta="conferma"]:checked')].map(x => x.value);
            this.statoImporta();
            return;
        }
        // «— scegli —» toglie la scelta (il server accetta solo figure e municipalita' vere)
        const scegli = (nome) => {
            s[nome] = s[nome] || {};
            if (el.value) s[nome][el.dataset.chiave] = el.value;
            else delete s[nome][el.dataset.chiave];
        };
        if (tipo === 'qualifica') scegli('qualifiche');
        else if (tipo === 'plesso') scegli('plessi');
        else if (tipo === 'grado') (s.gradi = s.gradi || {})[el.dataset.chiave] = el.value;
        else if (tipo === 'ambigua') (s.ore_ambigue = s.ore_ambigue || {})[el.dataset.chiave] = el.value;
        else if (tipo === 'sovrascrivi') s.sovrascrivi_manuali = el.checked;
        else if (tipo === 'subentro' || tipo === 'chiusura') {
            const chiave = tipo === 'subentro' ? 'subentri' : 'chiusure';
            s[chiave] = [...this.el('import-risultato').querySelectorAll(`[data-scelta="${tipo}"]:checked`)].map(x => Number(x.value));
        }
        const modo = this.anteprima.modo;
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.chiedi(modo, true), 350);
    },

    /** Le scelte gia' fatte (o proposte) nell'anteprima diventano quelle da mandare. */
    ricordaScelte(a) {
        const s = this.scelte;
        s.qualifiche = Object.fromEntries((a.qualifiche || []).filter(q => q.figura).map(q => [q.testo, q.figura]));
        s.gradi = Object.fromEntries((a.scuole_nuove || []).map(x => [x.chiave, x.grado || '']));
        s.ore_ambigue = Object.fromEntries((a.ore_ambigue || []).filter(x => x.scelta).map(x => [x.chiave, x.scelta]));
        s.plessi = Object.fromEntries((a.plessi_da_scegliere || []).filter(x => x.scelta).map(x => [x.chiave, String(x.scelta)]));
        s.subentri = (a.subentri || []).filter(x => x.scelto).map(x => x.riga);
        s.chiusure = (a.chiusure || []).filter(x => x.scelto).map(x => x.id);
        s.conferme = (s.conferme || []).filter(c => (a.conferme_richieste || []).includes(c));
        s.sovrascrivi_manuali = !!s.sovrascrivi_manuali;
    },

    disegnaAnteprima(a, aggiorna) {
        const box = this.el('import-risultato');
        const scroll = window.scrollY;
        const attivo = document.activeElement && document.activeElement.dataset && document.activeElement.dataset.scelta
            ? `[data-scelta="${document.activeElement.dataset.scelta}"][data-chiave="${CSS.escape(document.activeElement.dataset.chiave || '')}"]` : null;
        this.ricordaScelte(a);
        const c = a.conteggi;
        const anagrafica = a.modo === 'anagrafica';
        const testi = NAPOLI_MODI_IMPORT[a.modo];
        const quarto = anagrafica
            ? this.numero(napoliNumeroIt(c.scuole), 'scuole e plessi')
            : this.numero(escapeHtml(a.totale.ore), `ore nel file (${escapeHtml(a.totale.hhmm)})`);
        const dati = anagrafica ? `dati di ${escapeHtml(a.file.mese_testo)}` : `foglio «${escapeHtml(a.file.foglio)}»`;
        box.innerHTML = `
            <section class="card napoli-anteprima" aria-labelledby="titolo-anteprima">
                <div class="card-header">
                    <div>
                        <h2 class="card-title" id="titolo-anteprima">${escapeHtml(testi.titolo(a))}</h2>
                        <p class="napoli-sottotitolo">${escapeHtml(a.file.nome)} · ${dati} · ${escapeHtml(a.lotto.nome)} · <strong>niente è ancora salvato</strong></p>
                    </div>
                    <span class="badge" id="import-bollino"></span>
                </div>
                <div class="card-body">
                    ${this.htmlReimport(a)}
                    <div class="napoli-numeri">
                        ${this.numero(napoliNumeroIt(c.righe), 'righe (coppie operatore-alunno)')}
                        ${this.numero(napoliNumeroIt(c.operatori), 'operatori')}
                        ${this.numero(napoliNumeroIt(c.alunni), 'alunni')}
                        ${quarto}
                    </div>
                    ${this.htmlBloccanti(a)}
                    ${this.htmlDaConfermare(a)}
                    ${anagrafica ? this.htmlCoppie(a) : this.htmlOre(a)}
                    ${this.htmlCambia(a)}
                    ${this.htmlAvvisi(a)}
                </div>
                <div class="napoli-barra-import">
                    <p class="napoli-barra-testo" id="import-motivo"></p>
                    <div class="napoli-barra-pulsanti">
                        <button type="button" class="btn btn-secondary" data-azione="lascia">Lascia perdere</button>
                        <button type="button" class="btn btn-primary" data-azione="importa" id="btn-importa">${escapeHtml(testi.pulsante(a))}</button>
                    </div>
                </div>
            </section>`;
        this.statoImporta();
        if (aggiorna) {
            window.scrollTo(0, scroll);
            const el = attivo && box.querySelector(attivo);
            if (el) el.focus({ preventScroll: true });
        } else {
            this.inVista(box.querySelector('.napoli-anteprima'));
        }
    },

    numero(valore, etichetta) {
        return `<div class="napoli-numero-box"><span class="napoli-numero-valore">${valore}</span><span class="napoli-numero-etichetta">${escapeHtml(etichetta)}</span></div>`;
    },

    htmlReimport(a) {
        if (a.mese_chiuso || !a.reimport) return '';
        const quando = napoliDataOra(a.reimport.data);
        const info = (testo) => `<div class="alert alert-info napoli-alert">${napoliSvg(NAPOLI_ICONE_STATO.ok, 20)}<div>${testo}</div></div>`;
        if (a.modo === 'anagrafica') {
            const file = `${escapeHtml(a.reimport.nome_file || '')}${a.reimport.mese_testo ? `, dati di ${escapeHtml(a.reimport.mese_testo)}` : ''}`;
            if (a.nessun_cambiamento) {
                return info(`<strong>L'anagrafica di questo file è già in Assisto.</strong> Ultimo caricamento il ${escapeHtml(quando)} (file ${file}): non serve caricarla di nuovo.`);
            }
            return info(`<strong>L'anagrafica è già stata caricata il ${escapeHtml(quando)}</strong> (file ${file}). Qui sotto vedi solo cosa aggiunge o cambia questo file; quello che c'è già resta com'è.`);
        }
        const mese = escapeHtml(napoliMaiuscola(a.file.mese_testo));
        if (a.reimport.stesso_file || a.nessun_cambiamento) {
            return info(`<strong>Le ore di ${escapeHtml(a.file.mese_testo)} sono già state importate il ${escapeHtml(quando)}.</strong> ${a.nessun_cambiamento ? 'Il file non cambia niente in Assisto: non serve importarlo di nuovo.' : 'Ci sono delle differenze: qui sotto vedi cosa cambia.'}`);
        }
        return `<div class="alert alert-warning napoli-alert">${napoliSvg(NAPOLI_ICONE_STATO.avviso, 20)}<div><strong>${mese}: le ore sono già state importate il ${escapeHtml(quando)}</strong> (file ${escapeHtml(a.reimport.nome_file || '')}). Importando di nuovo si sostituiscono solo le ore importate prima; le ore scritte a mano in Assisto non si toccano, se non lo scegli tu qui sotto.</div></div>`;
    },

    htmlGruppo(g, aperto) {
        const righe = g.righe.map(r => {
            const dove = r.riga ? `Riga ${r.riga}${r.colonna ? `, colonna ${escapeHtml(r.colonna)}` : ''}` : (r.colonna ? `Colonna ${escapeHtml(r.colonna)}` : 'Tutto il file');
            return `<li>${dove}${r.dettaglio ? `: <span class="napoli-dettaglio">${escapeHtml(r.dettaglio)}</span>` : ''}</li>`;
        }).join('');
        const altre = g.n > g.righe.length ? `<li class="napoli-vuoto">e altre ${napoliNumeroIt(g.n - g.righe.length)}</li>` : '';
        return `
            <details class="napoli-gruppo-avviso livello-${g.livello}"${aperto ? ' open' : ''}>
                <summary>
                    ${napoliSvg(NAPOLI_ICONE_LIVELLO[g.livello], 18, 'napoli-icona-livello')}
                    <span class="napoli-avviso-titolo">${escapeHtml(g.titolo)}</span>
                    <span class="napoli-avviso-conta">${napoliNumeroIt(g.n)}</span>
                </summary>
                ${g.spiegazione ? `<p class="napoli-avviso-spiega">${escapeHtml(g.spiegazione)}</p>` : ''}
                <ul class="napoli-righe-avviso">${righe}${altre}</ul>
            </details>`;
    },

    /** Cosa si sceglie nella pagina fra i bloccanti ('le figure delle qualifiche nuove e i plessi'). */
    testoScelte(bloccanti) {
        return [bloccanti.some(g => g.codice === 'qualifica_non_collegata') ? 'le figure delle qualifiche nuove' : '',
            bloccanti.some(g => g.codice === 'municipalita_da_scegliere') ? 'i plessi' : ''].filter(Boolean).join(' e ');
    },

    /** I bloccanti: errori del file (da correggere in Excel) e scelte da fare nella pagina
     *  (qualifiche nuove, plessi). Con le sole scelte il titolo non parla di correggere. */
    htmlBloccanti(a) {
        if (!a.bloccanti.length) return '';
        const azione = a.modo === 'anagrafica' ? 'caricare' : 'importare';
        const scelte = a.bloccanti.filter(g => NAPOLI_SCELTE_BLOCCANTI.includes(g.codice));
        const nelFile = 'correggilo in Excel, salvalo, chiudilo e sceglilo di nuovo qui sopra';
        let titolo = `Da correggere prima di ${azione}`;
        let intro = `Queste righe si correggono nel file: ${nelFile}.`;
        let classe = 'napoli-blocco-danger';
        if (scelte.length === a.bloccanti.length) {
            titolo = `Da scegliere prima di ${azione}`;
            intro = `Nel file non c'è niente da correggere: scegli ${this.testoScelte(scelte)} qui sotto, in «Da confermare».`;
            classe = 'napoli-blocco-warning';
        } else if (scelte.length) {
            intro = `Scegli ${this.testoScelte(scelte)} qui sotto, in «Da confermare». Il resto si corregge nel file: ${nelFile}.`;
        }
        return `
            <div class="napoli-blocco ${classe}">
                <h3>${escapeHtml(titolo)}</h3>
                <p class="napoli-intro">${escapeHtml(intro)}</p>
                ${a.bloccanti.map(g => this.htmlGruppo(NAPOLI_SCELTE_BLOCCANTI.includes(g.codice) ? { ...g, livello: 'avviso' } : g, true)).join('')}
            </div>`;
    },

    htmlScuoleNuove(a) {
        const daDecidere = a.scuole_nuove.filter(x => !x.grado).length;
        const conGradi = (a.conferme_richieste || []).includes('gradi');
        const paritarie = a.scuole_nuove.some(x => x.paritaria);
        const classeParte = conGradi ? 'napoli-parte-conferma napoli-conferma-obbligatoria' : 'napoli-parte-conferma';
        const classeTabella = a.scuole_nuove.length > 8 ? 'table-container napoli-tabella-alta' : 'table-container';
        return `
            <div class="${classeParte}">
                <h4>Scuole nuove: controlla il grado (${napoliNumeroIt(a.scuole_nuove.length)})${daDecidere ? ` <span class="badge badge-warning">${daDecidere} senza grado</span>` : ''}</h4>
                <p class="napoli-intro">Il grado decide in quale fattura vanno le ore (grado inferiore o superiore, con fondi diversi). È proposto dal codice meccanografico: controllalo scuola per scuola e cambialo se serve.${paritarie ? ' Le scuole segnate «paritaria» hanno il codice delle scuole paritarie: controllale con più attenzione.' : ''} Per le scuole senza grado le ore restano «da decidere» e la fattura aspetta.</p>
                <div class="${classeTabella}"><table class="table napoli-tabella-compatta">
                    <thead><tr><th scope="col">Scuola</th><th scope="col">Codice</th><th scope="col">Municipalità</th><th scope="col">Righe</th><th scope="col">Grado</th></tr></thead>
                    <tbody>${a.scuole_nuove.map(x => `
                        <tr><td>${escapeHtml(x.nome)}</td>
                            <td>${escapeHtml(x.codice) || '<span class="napoli-vuoto">senza codice</span>'}${x.paritaria ? ' <span class="badge badge-sm badge-secondary">paritaria</span>' : ''}</td>
                            <td>${x.municipalita ?? '<span class="napoli-vuoto">manca</span>'}</td><td>${x.n_righe}</td>
                            <td><select class="form-control" data-scelta="grado" data-chiave="${escapeHtml(x.chiave)}" aria-label="Grado di ${escapeHtml(x.nome)}">
                                ${NAPOLI_GRADI_SCUOLA.map(([v, t]) => `<option value="${v}"${(x.grado || '') === v ? ' selected' : ''}>${t}${v && v === x.grado_proposto ? ' (proposto)' : ''}</option>`).join('')}
                            </select></td></tr>`).join('')}</tbody>
                </table></div>
                ${conGradi ? `<label class="napoli-scelta napoli-ho-controllato"><input type="checkbox" value="gradi" data-scelta="conferma"${(this.scelte.conferme || []).includes('gradi') ? ' checked' : ''}> <strong>Ho controllato i gradi</strong></label>` : ''}
            </div>`;
    },

    htmlDaConfermare(a) {
        const parti = [];
        const s = this.scelte;
        if (a.qualifiche.length) {
            parti.push(`
                <div class="napoli-parte-conferma">
                    <h4>Qualifiche nuove</h4>
                    <p class="napoli-intro">Queste qualifiche non sono ancora in Assisto: scegli tu la figura professionale di ognuna (quando il programma riconosce la qualifica, nella tendina la figura è indicata come «proposta»). La scelta resta salvata per i prossimi file.</p>
                    <div class="table-container"><table class="table napoli-tabella-compatta">
                        <thead><tr><th scope="col">Qualifica nel file</th><th scope="col">Righe</th><th scope="col">Figura</th></tr></thead>
                        <tbody>${a.qualifiche.map(q => `
                            <tr><td><strong>${escapeHtml(q.testo)}</strong></td><td>${q.n_righe}</td>
                                <td><select class="form-control napoli-scelta-figura" data-scelta="qualifica" data-chiave="${escapeHtml(q.testo)}" aria-label="Figura per ${escapeHtml(q.testo)}">
                                    <option value=""${q.figura ? '' : ' selected'}>— scegli —</option>${NapoliComune.opzioniFigure(q.figura, q.proposta)}
                                </select></td></tr>`).join('')}</tbody>
                    </table></div>
                </div>`);
        }
        if ((a.plessi_da_scegliere || []).length) {
            const daScegliere = a.plessi_da_scegliere.filter(x => !x.scelta).length;
            parti.push(`
                <div class="napoli-parte-conferma">
                    <h4>Plessi da scegliere${daScegliere ? ` <span class="badge badge-warning">${napoliNumeroIt(daScegliere)} da scegliere</span>` : ''}</h4>
                    <p class="napoli-intro">In queste righe manca la municipalità e la scuola è in più municipalità (plessi diversi). La municipalità è quella della scuola: scegli tu in quale plesso va ogni coppia. Se preferisci, scrivi la municipalità nel file e sceglilo di nuovo.</p>
                    <div class="table-container"><table class="table napoli-tabella-compatta">
                        <thead><tr><th scope="col">Riga</th><th scope="col">Coppia</th><th scope="col">Scuola</th><th scope="col">Plesso</th></tr></thead>
                        <tbody>${a.plessi_da_scegliere.map(x => `
                            <tr><td>${x.riga}</td>
                                <td>${escapeHtml(x.operatore)} con ${escapeHtml(x.alunno)}${x.figura ? ` <span class="napoli-vuoto">(${escapeHtml(x.figura)})</span>` : ''}</td>
                                <td>${escapeHtml(x.nome)} <span class="napoli-vuoto">(${escapeHtml(x.codice) || 'senza codice'})</span></td>
                                <td><select class="form-control napoli-scelta-plesso" data-scelta="plesso" data-chiave="${escapeHtml(x.chiave)}" aria-label="Plesso della riga ${x.riga}">
                                    <option value=""${x.scelta ? '' : ' selected'}>— scegli —</option>
                                    ${x.possibili.map(m => `<option value="${m}"${x.scelta === m ? ' selected' : ''}>Municipalità ${m}</option>`).join('')}
                                </select></td></tr>`).join('')}</tbody>
                    </table></div>
                </div>`);
        }
        if (a.ore_ambigue.length) {
            parti.push(`
                <div class="napoli-parte-conferma">
                    <h4>Ore da confermare${a.ore_ambigue_da_scegliere ? ` <span class="badge badge-warning">${napoliNumeroIt(a.ore_ambigue_da_scegliere)} da scegliere</span>` : ''}</h4>
                    <p class="napoli-intro">Nel foglio presenze le ore si scrivono in decimale (1,5 = un'ora e mezza), ma queste celle si possono leggere anche come sul foglio firma (1,30 = un'ora e trenta minuti). Scegli tu come leggere ogni cella: finché non scegli, nei totali qui sotto sono contate in decimale e non si può importare.</p>
                    ${a.ore_ambigue.map(x => `
                        <fieldset class="napoli-ambigua">
                            <legend>Riga ${x.riga}, colonna ${escapeHtml(x.colonna)} (${escapeHtml(formatDataIT(x.data))}): scritto «${escapeHtml(x.testo)}»${x.ricordata ? ' <span class="napoli-vuoto">(scelta già fatta nell\'import di prima)</span>' : ''}</legend>
                            ${x.alternative.map(alt => `
                                <label class="napoli-scelta"><input type="radio" name="ambigua-${escapeHtml(x.chiave)}" value="${alt.lettura}" data-scelta="ambigua" data-chiave="${escapeHtml(x.chiave)}"${s.ore_ambigue[x.chiave] === alt.lettura ? ' checked' : ''}>
                                    ${escapeHtml(alt.testo)}</label>`).join('')}
                        </fieldset>`).join('')}
                </div>`);
        }
        a.conferme.forEach(conf => {
            // senza niente da cambiare la conferma resta solo come avviso (senza casella)
            const classeParte = conf.solo_avviso ? 'napoli-parte-conferma' : 'napoli-parte-conferma napoli-conferma-obbligatoria';
            parti.push(`
                <div class="${classeParte}">
                    <h4>${escapeHtml(conf.titolo)}</h4>
                    <p class="napoli-intro">${escapeHtml(conf.testo)}</p>
                    ${conf.voci.length ? `<ul class="napoli-elenco">${conf.voci.map(v => `<li>${escapeHtml(v.testo)} <span class="napoli-vuoto">(${napoliRigheTesto(v.righe, v.n_righe)})</span></li>`).join('')}</ul>` : ''}
                    ${conf.solo_avviso
                        ? '<p class="napoli-nota napoli-nota-stretta">Il file non cambia niente in Assisto, quindi qui non c\'è niente da confermare: è solo un avviso.</p>'
                        : `<label class="napoli-scelta napoli-ho-controllato"><input type="checkbox" value="${escapeHtml(conf.codice)}" data-scelta="conferma"${(s.conferme || []).includes(conf.codice) ? ' checked' : ''}> <strong>Ho controllato</strong></label>`}
                </div>`);
        });
        if (a.scuole_nuove.length) parti.push(this.htmlScuoleNuove(a));
        if (a.subentri.length) {
            parti.push(`
                <div class="napoli-parte-conferma">
                    <h4>Cambi di operatore</h4>
                    <p class="napoli-intro">Un sostituto comincia durante il mese e il titolare non ha più ore da quel giorno: si propone di chiudere la coppia del titolare. Togli la spunta se il titolare tornerà.</p>
                    ${a.subentri.map(x => `<label class="napoli-scelta napoli-scelta-riga"><input type="checkbox" value="${x.riga}" data-scelta="subentro"${s.subentri.includes(x.riga) ? ' checked' : ''}> ${escapeHtml(x.testo)}</label>`).join('')}
                </div>`);
        }
        if (a.chiusure.length || a.coppie_del_mese.length) {
            const resta = a.modo === 'anagrafica' ? 'restano in Assisto come sono' : 'restano in Assisto senza le ore del file';
            parti.push(`
                <div class="napoli-parte-conferma">
                    <h4>Coppie che nel file non ci sono più</h4>
                    ${a.chiusure.length ? `<p class="napoli-intro">Erano attive il mese prima ma in questo file non compaiono. Spunta quelle da chiudere (finiscono l'ultimo giorno del mese prima); le altre restano aperte.</p>
                    ${a.chiusure.map(x => `<label class="napoli-scelta napoli-scelta-riga"><input type="checkbox" value="${x.id}" data-scelta="chiusura"${s.chiusure.includes(x.id) ? ' checked' : ''}> ${escapeHtml(x.testo)}</label>`).join('')}` : ''}
                    ${a.coppie_del_mese.length ? `<p class="napoli-intro">Queste coppie cominciano in questo mese ma nel file non ci sono: ${resta}. Se sono state create dal caricamento di prima con una riga sbagliata, annulla quel caricamento (nell'elenco in fondo alla pagina) e carica di nuovo questo file.</p>
                    <ul class="napoli-elenco">${a.coppie_del_mese.map(x => `<li>${escapeHtml(x.testo)}</li>`).join('')}</ul>` : ''}
                </div>`);
        }
        if (a.manuali_diverse.length) {
            const n = a.conteggi.presenze.manuali_diverse;
            parti.push(`
                <div class="napoli-parte-conferma">
                    <h4>Ore scritte a mano in Assisto diverse dal file (${napoliNumeroIt(n)})</h4>
                    <p class="napoli-intro">Queste ore sono state registrate in Assisto (foglio firma o griglia) e il file dice un'altra cosa. Se non scegli altrimenti restano quelle di Assisto.</p>
                    <div class="table-container napoli-tabella-alta"><table class="table napoli-tabella-compatta">
                        <thead><tr><th scope="col">Giorno</th><th scope="col">Alunno</th><th scope="col">Operatore</th><th scope="col">In Assisto</th><th scope="col">Nel file</th></tr></thead>
                        <tbody>${a.manuali_diverse.map(m => `<tr><td>${escapeHtml(formatDataIT(m.data))}</td><td>${escapeHtml(m.alunno)}</td><td>${escapeHtml(m.operatore)}</td><td>${escapeHtml(m.assisto)}</td><td>${escapeHtml(m.file)}</td></tr>`).join('')}</tbody>
                    </table></div>
                    <label class="napoli-scelta"><input type="checkbox" data-scelta="sovrascrivi"${s.sovrascrivi_manuali ? ' checked' : ''}> Sostituisci anche queste ore con quelle del file</label>
                </div>`);
        }
        if (!parti.length) return '';
        return `
            <div class="napoli-blocco">
                <h3>Da confermare</h3>
                ${parti.join('')}
            </div>`;
    },

    /** Le ore per figura e per grado che Assisto avra' dopo l'import (modo 'ore'). */
    htmlOre(a) {
        const righe = a.ore_per_figura;
        if (!righe.length) return '';
        const somma = (g) => righe.reduce((n, x) => n + x.per_grado[g], 0);
        const ore = (min) => (min ? (min / 60).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—');
        const daDecidere = somma('da_decidere');
        const p = a.conteggi.presenze;
        const restano = p.manuali_diverse - p.sovrascritte;
        const note = [
            restano ? `Per ${napoliElenco([[restano, 'giorni scritti a mano in Assisto, diversi dal file, contano', 'giorno scritto a mano in Assisto, diverso dal file, contano']])} le ore di Assisto, che restano come sono.` : '',
            p.solo_in_assisto ? `Non ${p.solo_in_assisto === 1 ? 'è contato 1 giorno scritto a mano in Assisto che nel file non c\'è: resta in Assisto e andrà in fattura' : `sono contati ${napoliNumeroIt(p.solo_in_assisto)} giorni scritti a mano in Assisto che nel file non ci sono: restano in Assisto e andranno in fattura`}.` : '',
        ].filter(Boolean).join(' ');
        return `
            <div class="napoli-blocco">
                <h3>Ore per figura e per grado</h3>
                <p class="napoli-intro">Le ore che Assisto avrà dopo l'import per le righe del file, divise come le righe della fattura. Il grado viene dalla scuola${daDecidere ? ': le ore «da decidere» sono di scuole senza grado (scegli il grado qui sopra)' : ''}.${this.testoEsclusi(a)}</p>
                <div class="table-container"><table class="table napoli-tabella-ore">
                    <thead><tr><th scope="col">Figura</th><th scope="col" class="text-right">Righe</th><th scope="col" class="text-right">Grado inferiore</th><th scope="col" class="text-right">Grado superiore</th><th scope="col" class="text-right">Da decidere</th><th scope="col" class="text-right">Totale ore</th></tr></thead>
                    <tbody>${righe.map(x => {
                        const classeDaDecidere = x.per_grado.da_decidere ? 'napoli-numero napoli-da-decidere' : 'napoli-numero';
                        return `
                        <tr><td><span class="napoli-figura-nome">${escapeHtml(x.nome)}</span></td><td class="napoli-numero">${x.righe}</td>
                            <td class="napoli-numero">${ore(x.per_grado.inferiore)}</td><td class="napoli-numero">${ore(x.per_grado.superiore)}</td>
                            <td class="${classeDaDecidere}">${ore(x.per_grado.da_decidere)}</td>
                            <td class="napoli-numero"><strong>${escapeHtml(x.ore)}</strong></td></tr>`;
                    }).join('')}</tbody>
                    <tfoot><tr><td><strong>Totale</strong></td><td class="napoli-numero">${righe.reduce((n, x) => n + x.righe, 0)}</td>
                        <td class="napoli-numero">${ore(somma('inferiore'))}</td><td class="napoli-numero">${ore(somma('superiore'))}</td>
                        <td class="napoli-numero">${ore(daDecidere)}</td><td class="napoli-numero"><strong>${escapeHtml(a.totale_tabella.ore)}</strong></td></tr></tfoot>
                </table></div>
                ${note ? `<p class="napoli-nota napoli-nota-stretta">${escapeHtml(note)}</p>` : ''}
            </div>`;
    },

    /** Le coppie e le ore settimanali da progetto (PEI) per figura e per grado (modo 'anagrafica'). */
    htmlCoppie(a) {
        const righe = a.ore_per_figura;
        if (!righe.length) return '';
        const somma = (g) => righe.reduce((n, x) => n + x.righe_per_grado[g], 0);
        const n = (v) => (v ? napoliNumeroIt(v) : '—');
        const daDecidere = somma('da_decidere');
        return `
            <div class="napoli-blocco">
                <h3>Coppie per figura e per grado</h3>
                <p class="napoli-intro">Le coppie operatore-alunno del file, divise come le righe della fattura. Il grado viene dalla scuola${daDecidere ? ': le coppie «da decidere» sono di scuole senza grado (scegli il grado qui sopra)' : ''}. Le ore PEI sono le ore settimanali da progetto degli alunni.${this.testoEsclusi(a)}</p>
                <div class="table-container"><table class="table napoli-tabella-ore">
                    <thead><tr><th scope="col">Figura</th><th scope="col" class="text-right">Coppie</th><th scope="col" class="text-right">Grado inferiore</th><th scope="col" class="text-right">Grado superiore</th><th scope="col" class="text-right">Da decidere</th><th scope="col" class="text-right">Ore PEI a settimana</th></tr></thead>
                    <tbody>${righe.map(x => {
                        const classeDaDecidere = x.righe_per_grado.da_decidere ? 'napoli-numero napoli-da-decidere' : 'napoli-numero';
                        return `
                        <tr><td><span class="napoli-figura-nome">${escapeHtml(x.nome)}</span></td><td class="napoli-numero"><strong>${x.righe}</strong></td>
                            <td class="napoli-numero">${n(x.righe_per_grado.inferiore)}</td><td class="napoli-numero">${n(x.righe_per_grado.superiore)}</td>
                            <td class="${classeDaDecidere}">${n(x.righe_per_grado.da_decidere)}</td>
                            <td class="napoli-numero">${escapeHtml(x.pei_ore)}</td></tr>`;
                    }).join('')}</tbody>
                    <tfoot><tr><td><strong>Totale</strong></td><td class="napoli-numero"><strong>${righe.reduce((t, x) => t + x.righe, 0)}</strong></td>
                        <td class="napoli-numero">${n(somma('inferiore'))}</td><td class="napoli-numero">${n(somma('superiore'))}</td>
                        <td class="napoli-numero">${n(daDecidere)}</td><td class="napoli-numero">${escapeHtml(a.totale_tabella.pei_ore)}</td></tr></tfoot>
                </table></div>
            </div>`;
    },

    /** Cosa non e' contato nella tabella (righe che non si importano, celle da correggere). */
    testoEsclusi(a) {
        const c = a.conteggi;
        const voci = [[c.righe_escluse, 'righe che non si caricano (per esempio quelle da correggere o del coordinatore)', 'riga che non si carica (per esempio da correggere o del coordinatore)']];
        if (a.modo !== 'anagrafica') voci.push([c.celle_escluse, 'celle da correggere', 'cella da correggere']);
        const esclusi = napoliElenco(voci);
        return esclusi ? ` Non sono contate: ${esclusi}.` : '';
    },

    htmlCambia(a) {
        const c = a.conteggi;
        const p = c.presenze;
        const anagrafica = a.modo === 'anagrafica';
        const nuovi = napoliElenco([[c.nuovi.scuole, 'scuole', 'scuola'], [c.nuovi.alunni, 'alunni', 'alunno'], [c.nuovi.operatori, 'operatori', 'operatore'],
            [c.nuovi.coppie, 'coppie operatore-alunno', 'coppia operatore-alunno'], [c.nuovi.pei, 'PEI (ore settimanali da progetto)'],
            [c.nuovi.qualifiche, 'qualifiche collegate a una figura', 'qualifica collegata a una figura']]);
        const aggiornati = napoliElenco([[c.aggiornati.coppie, 'coppie (date o plesso)', 'coppia (date o plesso)'], [c.aggiornati.pei, 'PEI (ore settimanali da progetto)'],
            [c.aggiornati.operatori, 'operatori (ore di contratto o codice fiscale)', 'operatore (ore di contratto o codice fiscale)'],
            [c.aggiornati.alunni, 'alunni (codice fiscale corretto o plesso)', 'alunno (codice fiscale corretto o plesso)'],
            [c.aggiornati.scuole, 'scuole (municipalità aggiunta)', 'scuola (municipalità aggiunta)'],
            [c.aggiornati.fogli, 'note dei fogli', 'nota di un foglio'],
            [(c.tolti || {}).scuole, 'plessi senza municipalità tolti (erano rimasti vuoti)', 'plesso senza municipalità tolto (era rimasto vuoto)']]);
        if (anagrafica) {
            return `
                <div class="napoli-blocco">
                    <h3>Cosa cambia in Assisto</h3>
                    <div class="napoli-dati">
                        ${rigaDati('Nuovi in Assisto', escapeHtml(nuovi || 'nessuno'))}
                        ${rigaDati('Aggiornati', escapeHtml(aggiornati || 'niente'))}
                        ${rigaDati('Ore dei giorni', 'non si caricano: da ora in poi si scrivono in Assisto')}
                    </div>
                </div>`;
        }
        const giorni = napoliElenco([[p.nuove, 'nuovi', 'nuovo'], [p.cambiate, 'cambiati (ore importate prima)', 'cambiato (ore importate prima)'],
            [p.da_programmato, 'completati (erano solo programmati)', 'completato (era solo programmato)'], [p.sovrascritte, 'scritti a mano e sostituiti', 'scritto a mano e sostituito'],
            [p.da_togliere, 'tolti (non sono più nel file)', 'tolto (non è più nel file)'], [p.uguali, 'già uguali', 'già uguale']]);
        const sigle = napoliElenco([[c.sigle.ferie, 'giorni di ferie', 'giorno di ferie'], [c.sigle.malattia, 'giorni di malattia', 'giorno di malattia'],
            [c.sigle.permesso, 'giorni di permesso', 'giorno di permesso']]);
        const s = a.segnalazioni;
        return `
            <div class="napoli-blocco">
                <h3>Cosa cambia in Assisto</h3>
                <div class="napoli-dati">
                    ${rigaDati('Giorni da salvare', escapeHtml(giorni || 'nessuno'))}
                    ${rigaDati('Operatore assente', escapeHtml(sigle ? `${sigle} (0 ore)` : 'nessun giorno'))}
                    ${rigaDati('Nuovi in Assisto', escapeHtml(nuovi || 'nessuno'))}
                    ${rigaDati('Aggiornati', escapeHtml(aggiornati || 'niente'))}
                    ${p.solo_in_assisto ? rigaDati('Solo in Assisto', escapeHtml(p.solo_in_assisto === 1 ? '1 giorno scritto a mano che nel file non c\'è: resta' : `${napoliNumeroIt(p.solo_in_assisto)} giorni scritti a mano che nel file non ci sono: restano`)) : ''}
                </div>
                ${s.righe_con_assenze_in_nota || s.celle_colorate ? `<p class="napoli-nota">Promemoria: ${escapeHtml(napoliElenco([[s.righe_con_assenze_in_nota, 'righe hanno nelle note i giorni di alunno assente', 'riga ha nelle note i giorni di alunno assente'], [s.celle_colorate, 'celle sono colorate', 'cella è colorata']]))}. Servono solo come promemoria: le ore valgono come sono scritte nelle celle.</p>` : ''}
                <p class="napoli-nota">La colonna NOTE si salva nel foglio del mese (i codici fiscali solo mascherati): non scriverci dati sulla salute degli alunni.</p>
            </div>`;
    },

    htmlAvvisi(a) {
        if (!a.avvisi.length && !a.note.length) return '';
        const n = a.avvisi.reduce((t, g) => t + g.n, 0);
        return `
            <div class="napoli-blocco">
                ${a.avvisi.length ? `<h3>Da controllare (${napoliNumeroIt(n)})</h3>
                <p class="napoli-intro">Non impediscono di ${a.modo === 'anagrafica' ? 'caricare l\'anagrafica' : 'importare'}, ma conviene guardarli: apri una voce per vedere le righe del file.</p>
                ${a.avvisi.map(g => this.htmlGruppo(g, false)).join('')}` : ''}
                ${a.note.length ? `<details class="napoli-note-file"><summary>Altre cose che il programma ha già sistemato da solo (${a.note.length})</summary>
                    ${a.note.map(g => this.htmlGruppo(g, false)).join('')}</details>` : ''}
            </div>`;
    },

    /** Il pulsante (Carica l'anagrafica / Importa le ore) e il bollino in alto: si salva
     *  solo senza bloccanti, con le ore da confermare scelte, le conferme spuntate e
     *  qualcosa da cambiare. */
    statoImporta() {
        const a = this.anteprima;
        const b = this.el('btn-importa');
        const motivo = this.el('import-motivo');
        const bollino = this.el('import-bollino');
        if (!a || !b) return;
        const anagrafica = a.modo === 'anagrafica';
        const mancano = (a.conferme_richieste || []).filter(c => !(this.scelte.conferme || []).includes(c));
        const ore = a.ore_ambigue_da_scegliere || 0;
        const pronto = anagrafica ? 'Si può caricare' : 'Si può importare';
        let testo = '';
        let stato = ['badge-success', pronto];
        if (a.mese_chiuso) {
            testo = anagrafica ? 'Il mese del file è chiuso per questo lotto: riaprilo, oppure usa il file di un mese non ancora chiuso.'
                : 'Il mese del lotto è chiuso: riaprilo prima di importare.';
            stato = ['badge-danger', 'Mese chiuso'];
        } else if (a.bloccanti.length && a.bloccanti.every(g => NAPOLI_SCELTE_BLOCCANTI.includes(g.codice))) {
            // si sistemano nella pagina, senza cambiare il file
            testo = `Scegli ${this.testoScelte(a.bloccanti)} nella parte «Da confermare».`;
            stato = ['badge-warning', `${napoliNumeroIt(a.bloccanti.reduce((n, g) => n + g.n, 0))} da scegliere`];
        } else if (a.bloccanti.length) {
            testo = 'Prima correggi il file (parte «Da correggere»).';
            stato = ['badge-danger', `${napoliNumeroIt(a.bloccanti.reduce((n, g) => n + g.n, 0))} da correggere`];
        } else if (a.nessun_cambiamento) {
            testo = 'Il file non cambia niente in Assisto.';
            stato = ['badge-success', 'Niente di nuovo'];
        } else if (ore || mancano.length) {
            testo = [ore ? 'Scegli come leggere le ore nella parte «Ore da confermare».' : '',
                mancano.length ? 'Spunta le caselle «Ho controllato» nella parte «Da confermare».' : ''].filter(Boolean).join(' ');
            stato = ['badge-warning', 'Da confermare'];
        } else {
            testo = `Prima di ${anagrafica ? 'caricare' : 'importare'} viene fatta da sola una copia di sicurezza del database.`;
        }
        b.disabled = stato[1] !== pronto;
        b.hidden = !!a.nessun_cambiamento;
        motivo.textContent = testo;
        if (bollino) {
            bollino.className = `badge ${stato[0]}`;
            bollino.textContent = stato[1];
        }
    },

    importa() {
        const a = this.anteprima;
        if (!a || this.el('btn-importa').disabled) return;
        const c = a.conteggi;
        if (a.modo === 'anagrafica') {
            const nuovi = napoliElenco([[c.nuovi.scuole, 'scuole', 'scuola'], [c.nuovi.alunni, 'alunni', 'alunno'],
                [c.nuovi.operatori, 'operatori', 'operatore'], [c.nuovi.coppie, 'coppie', 'coppia']]);
            showConfirmDialog('Caricare l\'anagrafica dal file?',
                `Nel lotto ${a.lotto.nome}${nuovi ? ` si aggiungono ${nuovi}` : ' si aggiornano i dati indicati'}. Le ore dei giorni non si caricano. Prima viene fatta da sola una copia di sicurezza del database; se poi qualcosa non va, «Annulla il caricamento» (nell'elenco in fondo alla pagina) rimette tutto com'era.`,
                () => this.conferma(),
                { confirmText: 'Carica l\'anagrafica', cancelText: 'Non ancora', type: 'info' });
            return;
        }
        showConfirmDialog(`Importare le ore di ${a.file.mese_testo}?`,
            `${napoliNumeroIt(c.righe_importate)} righe e ${a.totale_importato.ore} ore nel lotto ${a.lotto.nome}. Prima viene fatta da sola una copia di sicurezza del database; se poi qualcosa non va, «Annulla l'import» (nell'elenco in fondo alla pagina) rimette tutto com'era.`,
            () => this.conferma(),
            { confirmText: `Importa le ore di ${a.file.mese_testo}`, cancelText: 'Non ancora', type: 'info' });
    },

    async conferma() {
        const a = this.anteprima;
        const b = this.el('btn-importa');
        setButtonLoading(b, true);
        try {
            const r = await this.invia('/api/napoli/import/conferma', {
                modo: a.modo, sha256: a.file.sha256, versione_dati: a.versione_dati, scelte: JSON.stringify(this.scelte),
            });
            const annulla = a.modo === 'anagrafica' ? '«Annulla il caricamento»' : '«Annulla l\'import»';
            showToast(r.nessun_cambiamento ? r.messaggio
                : `${r.messaggio}. Se c'è un errore, ${annulla} (o Ctrl+Z) rimette tutto com'era.`, 'success', 9000);
            this.mostraEsito(r);
            await this.caricaStorico();
        } catch (e) {
            if (e.code === 'FILE_CAMBIATO' || e.code === 'ANTEPRIMA_SUPERATA') {
                showToast(`${e.message} L'anteprima è stata rifatta: controllala e premi di nuovo il pulsante.`, 'warning', 10000);
                await this.chiedi(a.modo, true);
            } else {
                showToast(e.message, 'error', 10000);
                if (e.code === 'IMPORT_BLOCCATO' || e.code === 'DA_CONFERMARE') await this.chiedi(a.modo, true);
            }
        } finally {
            const ancora = this.el('btn-importa');
            if (ancora) { setButtonLoading(ancora, false); this.statoImporta(); }
        }
    },

    mostraEsito(r) {
        const p = r.esito.presenze;
        const n = r.esito.nuovi;
        const anagrafica = r.modo === 'anagrafica';
        this.file = null;
        this.anteprima = null;
        this.scelte = {};
        this.el('import-file-zona').hidden = false;
        this.el('import-file-scelto').hidden = true;
        this.pulsanti(true);
        const g = r.esito.aggiornati || {};
        const nuovi = napoliElenco([[n.scuole, 'scuole', 'scuola'], [n.alunni, 'alunni', 'alunno'], [n.operatori, 'operatori', 'operatore'], [n.coppie, 'coppie', 'coppia'], [n.pei, 'PEI']]) || 'nessuno';
        // anche i dati solo aggiornati (per esempio le coppie dei sostituti che continuano)
        const aggiornati = napoliElenco([[g.coppie, 'coppie', 'coppia'], [g.pei, 'PEI'], [g.operatori, 'operatori', 'operatore'],
            [g.alunni, 'alunni', 'alunno'], [g.scuole, 'scuole', 'scuola']]);
        const testoAggiornati = aggiornati ? ` Aggiornati: ${aggiornati}.` : '';
        const dettaglio = anagrafica ? `Nuovi: ${nuovi}.${testoAggiornati} Le ore dei giorni non sono state caricate.`
            : `Giorni: ${napoliElenco([[p.nuove, 'nuovi', 'nuovo'], [p.cambiate, 'cambiati', 'cambiato'], [p.da_programmato, 'completati', 'completato'], [p.sovrascritte, 'sostituiti', 'sostituito'], [p.da_togliere, 'tolti', 'tolto'], [p.uguali, 'già uguali', 'già uguale']]) || 'nessuno'}. Nuovi: ${nuovi}.${testoAggiornati}`;
        this.el('import-risultato').innerHTML = `
            <section class="card napoli-esito">
                <div class="alert alert-success napoli-alert">
                    ${napoliSvg(NAPOLI_ICONE_STATO.ok, 22)}
                    <div><strong>${escapeHtml(r.messaggio)}</strong><br>
                        ${r.nessun_cambiamento ? '' : escapeHtml(dettaglio)}
                        ${r.copia ? `<br><span class="napoli-vuoto">Prima ${anagrafica ? 'del caricamento' : 'dell\'import'} è stata fatta da sola una copia di sicurezza del database: la trovi nel Profilo, in «Backup e sicurezza dati».</span>` : ''}</div>
                </div>
                <div class="napoli-azioni-modulo">
                    <button type="button" class="btn btn-secondary" data-azione="altro-file">Scegli un altro file</button>
                    ${anagrafica ? '<a class="btn btn-primary" href="/napoli/anagrafiche#alunni">Controlla le anagrafiche</a>' : ''}
                </div>
            </section>`;
        this.inVista(this.el('import-risultato').querySelector('.napoli-esito'));
    },

    disegnaConfronto(a) {
        const x = a.confronto;
        const box = this.el('import-risultato');
        const tabellaGiorni = (giorni) => `
            <div class="table-container"><table class="table napoli-tabella-compatta">
                <thead><tr><th scope="col">Giorno</th><th scope="col">Nel file</th><th scope="col">In Assisto</th></tr></thead>
                <tbody>${giorni.map(g => `<tr><td>${escapeHtml(formatDataIT(g.data, true))}</td><td>${escapeHtml(g.file)}</td><td>${escapeHtml(g.assisto)}</td></tr>`).join('')}</tbody>
            </table></div>`;
        box.innerHTML = `
            <section class="card napoli-anteprima" aria-labelledby="titolo-confronto">
                <div class="card-header">
                    <div>
                        <h2 class="card-title" id="titolo-confronto">Confronto delle ore con Assisto: ${escapeHtml(a.file.mese_testo)}</h2>
                        <p class="napoli-sottotitolo">${escapeHtml(a.file.nome)} · ${escapeHtml(a.lotto.nome)} · <strong>niente viene salvato</strong></p>
                    </div>
                    ${x.differenze.length || x.righe_non_in_assisto.length || x.coppie_solo_in_assisto.length
                        ? '<span class="badge badge-warning">Ci sono differenze</span>' : '<span class="badge badge-success">Tutto uguale</span>'}
                </div>
                <div class="card-body">
                    <div class="napoli-numeri">
                        ${this.numero(napoliNumeroIt(x.coppie_uguali), 'coppie uguali')}
                        ${this.numero(napoliNumeroIt(x.differenze.length), 'coppie con differenze')}
                        ${this.numero(napoliNumeroIt(x.righe_non_in_assisto.length), 'righe del file non in Assisto')}
                        ${this.numero(napoliNumeroIt(x.coppie_solo_in_assisto.length), 'coppie solo in Assisto')}
                    </div>
                    ${x.differenze.length ? `<div class="napoli-blocco"><h3>Differenze giorno per giorno</h3>
                        ${x.differenze.map(d => `
                            <details class="napoli-gruppo-avviso livello-avviso">
                                <summary><span class="napoli-avviso-titolo">Riga ${d.riga}: ${escapeHtml(d.alunno)} con ${escapeHtml(d.operatore)} (${escapeHtml(d.figura)})</span>
                                    <span class="napoli-avviso-conta">file ${escapeHtml(d.ore_file)} · Assisto ${escapeHtml(d.ore_assisto)}</span></summary>
                                ${tabellaGiorni(d.giorni)}
                            </details>`).join('')}</div>` : ''}
                    ${x.righe_non_in_assisto.length ? `<div class="napoli-blocco"><h3>Righe del file che in Assisto non ci sono</h3>
                        <ul class="napoli-elenco">${x.righe_non_in_assisto.map(r => `<li>Riga ${r.riga}: ${escapeHtml(r.alunno)} con ${escapeHtml(r.operatore)} (${escapeHtml(r.figura)}), ${escapeHtml(r.ore)} ore</li>`).join('')}</ul></div>` : ''}
                    ${x.coppie_solo_in_assisto.length ? `<div class="napoli-blocco"><h3>Coppie con ore in Assisto che nel file non ci sono</h3>
                        <ul class="napoli-elenco">${x.coppie_solo_in_assisto.map(r => `<li>${escapeHtml(r.alunno)} con ${escapeHtml(r.operatore)} (${escapeHtml(r.figura)}), ${escapeHtml(r.ore)} ore</li>`).join('')}</ul></div>` : ''}
                    ${this.htmlAvvisi(a)}
                </div>
                <div class="napoli-barra-import">
                    <p class="napoli-barra-testo">Il confronto non salva nulla. Per caricare l'anagrafica usa «Mostra l'anteprima dell'anagrafica» qui sopra.</p>
                    <div class="napoli-barra-pulsanti">
                        <button type="button" class="btn btn-secondary" data-azione="lascia">Chiudi il confronto</button>
                        <button type="button" class="btn btn-secondary" data-azione="anteprima-ore">Anteprima delle ore del mese</button>
                    </div>
                </div>
            </section>`;
        this.inVista(box.querySelector('.napoli-anteprima'));
    },

    async caricaStorico() {
        const lotto = NapoliComune.lotto;
        const box = this.el('import-storico');
        if (!lotto) return;
        try {
            this.storico = await apiCall(`/api/napoli/lotti/${lotto.id}/import`);
        } catch (e) {
            box.innerHTML = `<div class="alert alert-danger">${escapeHtml(e.message || 'Elenco non disponibile')}</div>`;
            return;
        }
        if (!this.storico.length) {
            box.innerHTML = '<p class="napoli-vuoto">Nessun caricamento per questo lotto.</p>';
            return;
        }
        // cosa ha fatto il caricamento: anche i dati solo aggiornati (per esempio le coppie
        // dei sostituti che continuano), non solo quelli nuovi
        const cosa = (i) => {
            const p = i.presenze || {};
            const n = i.nuovi || {};
            const g = i.aggiornati || {};
            if (i.modo === 'anagrafica') {
                const fatto = napoliElenco([[n.alunni, 'alunni nuovi', 'alunno nuovo'], [n.operatori, 'operatori nuovi', 'operatore nuovo'],
                    [n.coppie, 'coppie nuove', 'coppia nuova'], [n.scuole, 'scuole nuove', 'scuola nuova'], [n.pei, 'PEI nuovi', 'PEI nuovo'],
                    [g.coppie, 'coppie aggiornate', 'coppia aggiornata'], [g.pei, 'PEI aggiornati', 'PEI aggiornato'],
                    [g.operatori, 'operatori aggiornati', 'operatore aggiornato'], [g.alunni, 'alunni aggiornati', 'alunno aggiornato'],
                    [g.scuole, 'scuole aggiornate', 'scuola aggiornata'], [(i.tolti || {}).scuole, 'plessi vuoti tolti', 'plesso vuoto tolto']]);
                return `Anagrafica<br><span class="napoli-vuoto">${escapeHtml(fatto || 'nessun dato nuovo o cambiato')}</span>`;
            }
            const giorni = napoliElenco([[p.nuove, 'nuovi', 'nuovo'], [p.cambiate, 'cambiati', 'cambiato'],
                [p.da_programmato, 'completati', 'completato'], [p.sovrascritte, 'sostituiti', 'sostituito'], [p.da_togliere, 'tolti', 'tolto']]);
            return `Ore del mese<br><span class="napoli-vuoto">${escapeHtml(giorni ? `giorni: ${giorni}` : 'nessun giorno nuovo o cambiato')}</span>`;
        };
        const classeRiga = (i) => (i.annullato ? 'napoli-riga-annullata' : '');
        box.innerHTML = `
            <div class="table-container"><table class="table">
                <thead><tr><th scope="col">Mese del file</th><th scope="col">Cosa</th><th scope="col">File</th><th scope="col">Caricato il</th>
                    <th scope="col" class="text-right">Righe</th><th scope="col" class="text-right">Ore</th><th scope="col" aria-label="Azioni"></th></tr></thead>
                <tbody>${this.storico.map(i => `<tr class="${classeRiga(i)}">
                        <td><strong>${escapeHtml(i.mese_testo)}</strong>${i.annullato ? ' <span class="badge badge-sm badge-secondary">annullato</span>' : ''}</td>
                        <td>${cosa(i)}</td>
                        <td class="napoli-nome-file">${escapeHtml(i.nome_file)}</td>
                        <td>${escapeHtml(napoliDataOra(i.data))}</td>
                        <td class="napoli-numero">${napoliNumeroIt(i.righe)}</td>
                        <td class="napoli-numero">${escapeHtml(i.ore) || '—'}</td>
                        <td class="napoli-azioni">${i.annullabile ? `<button type="button" class="btn btn-sm btn-secondary" data-annulla-import="${i.id}">${i.modo === 'anagrafica' ? 'Annulla il caricamento' : 'Annulla l\'import'}</button>` : ''}</td>
                    </tr>`).join('')}</tbody>
            </table></div>
            <p class="napoli-nota">Si può annullare solo l'ultimo caricamento del lotto, se il mese non è chiuso.</p>`;
    },

    annullaImport(id) {
        const i = this.storico.find(x => x.id === id);
        if (!i) return;
        const anagrafica = i.modo === 'anagrafica';
        showConfirmDialog(anagrafica ? `Annullare il caricamento dell'anagrafica (file di ${i.mese_testo})?` : `Annullare l'import delle ore di ${i.mese_testo}?`,
            anagrafica
                ? "Si tolgono le coppie, gli alunni, gli operatori, le scuole e i PEI creati da questo caricamento, e tornano com'erano i dati che aveva cambiato. Prima viene fatta da sola una copia di sicurezza del database."
                : "Si tolgono le ore, le coppie, gli alunni, gli operatori e le scuole creati da questo import, e tornano com'erano le ore che aveva cambiato. Prima viene fatta da sola una copia di sicurezza del database.",
            async () => {
                try {
                    const r = await apiCall(`/api/napoli/import/${id}/annulla`, { method: 'POST', body: '{}' });
                    showToast(r.messaggio, 'success', 8000);
                    this.azzera(true);
                    await this.caricaStorico();
                } catch (e) {
                    showToast(e.message, 'error', 10000);
                }
            }, { confirmText: anagrafica ? 'Annulla il caricamento' : 'Annulla l\'import', cancelText: 'Lascia com\'è', type: 'danger' });
    },
};

// ==================== scheda Impostazioni ====================

const NapoliImpostazioni = {
    PARTI: ['lotto', 'contratti', 'tariffe', 'regole', 'cooperativa', 'destinatario', 'qualifiche'],
    parte: 'lotto',
    contratti: [],
    tariffe: [],
    regole: null,
    qualifiche: [],
    impostazioni: null,
    modifica: {},

    el(id) { return document.getElementById(id); },

    async avvia() {
        NapoliComune.alCambioLotto = () => this.mostra(this.parte);
        NapoliComune.dopoAnnulla = async () => { await NapoliComune.caricaLotti(); await this.mostra(this.parte); };
        window.addEventListener('hashchange', () => this.mostra(this.parteDaIndirizzo()));
        this.collega();
        try {
            await Promise.all([NapoliComune.caricaLotti(), NapoliComune.caricaFigure()]);
        } catch (e) {
            showToast(e.message || 'Dati non disponibili', 'error');
        }
        await this.mostra(this.parteDaIndirizzo());
    },

    parteDaIndirizzo() {
        const h = window.location.hash.replace('#', '');
        return this.PARTI.includes(h) ? h : 'lotto';
    },

    async mostra(parte) {
        this.parte = parte;
        document.querySelectorAll('.napoli-parte').forEach(s => { s.hidden = s.dataset.parte !== parte; });
        document.querySelectorAll('[data-parte-link]').forEach(a => {
            const attiva = a.dataset.parteLink === parte;
            a.classList.toggle('attiva', attiva);
            if (attiva) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current');
        });
        try {
            await this['carica_' + parte]();
        } catch (e) {
            showToast(e.message || 'Dati non disponibili', 'error');
        }
    },

    /** Le parti del lotto senza un lotto: l'invito a crearlo. */
    senzaLotto(idContenuto) {
        if (NapoliComune.lotto) return false;
        this.el(idContenuto).innerHTML = napoliBenvenuto();
        return true;
    },

    creaLotto() {
        NapoliProcedura.apri(async (lotto) => {
            await NapoliComune.caricaLotti(lotto.id);
            window.location.hash = 'lotto';
            await this.mostra('lotto');
        });
    },

    collega() {
        document.addEventListener('click', (e) => {
            if (e.target.closest('.napoli-parti [data-azione="crea-lotto"]')) this.creaLotto();
        });
        this.el('napoli-annulla-ultima').addEventListener('click', () => NapoliComune.annulla());
        this.el('btn-nuovo-lotto').addEventListener('click', () => this.creaLotto());
        this.el('btn-modifica-lotto').addEventListener('click', () => this.apriLotto());
        const altro = this.el('btn-altro-lotto');
        altro.innerHTML = icona('altro');
        altro.addEventListener('click', () => MenuAzioni.apri(altro, [
            { testo: 'Elimina il lotto', icona: 'cestino', pericolo: true, azione: () => this.eliminaLotto() },
        ]));
        this.el('form-lotto').addEventListener('submit', (e) => { e.preventDefault(); this.salvaLotto(); });
        this.el('lotto-oggetto').addEventListener('input', () => this.esempioOggetto());
        this.el('lotto-numero').addEventListener('change', () => this.esempioOggetto());
        napoliNomeSegueNumero(this.el('lotto-nome'), this.el('lotto-numero'), () => NAPOLI_MODELLO_NOME);
        this.el('btn-nuovo-contratto').addEventListener('click', () => this.apriContratto(null));
        this.el('form-contratto').addEventListener('submit', (e) => { e.preventDefault(); this.salvaContratto(); });
        this.el('btn-nuova-tariffa').addEventListener('click', () => this.apriTariffa(null));
        this.el('form-tariffa').addEventListener('submit', (e) => { e.preventDefault(); this.salvaTariffa(false); });
        this.el('form-regola').addEventListener('submit', (e) => { e.preventDefault(); this.salvaRegola(false); });
        this.el('form-cooperativa').addEventListener('submit', (e) => { e.preventDefault(); this.salvaCooperativa(); });
        this.el('btn-togli-iban').addEventListener('click', () => this.togliIban());
        this.el('form-destinatario').addEventListener('submit', (e) => { e.preventDefault(); this.salvaDestinatario(); });
        this.el('btn-proposta-destinatario').addEventListener('click', () => {
            napoliRiempiCampi(this.el('form-destinatario'), this.impostazioni.destinatario_proposto);
            showToast('Dati proposti rimessi: premi Salva per tenerli', 'info');
        });
        this.el('btn-nuova-qualifica').addEventListener('click', () => this.apriQualifica(null));
        this.el('form-qualifica').addEventListener('submit', (e) => { e.preventDefault(); this.salvaQualifica(); });
        // pulsanti delle righe (Modifica, Elimina, Cambia...): un solo ascoltatore per parte
        ['contratti-contenuto', 'tariffe-contenuto', 'regole-contenuto', 'qualifiche-contenuto'].forEach(id => {
            this.el(id).addEventListener('click', (e) => {
                const b = e.target.closest('button[data-azione]');
                if (b) this.azioneRiga(b.dataset.azione, b.dataset.id, b);
            });
        });
    },

    azioneRiga(azione, id, pulsante) {
        const azioni = {
            'modifica-contratto': () => this.apriContratto(this.contratti.find(c => String(c.id) === id)),
            'elimina-contratto': () => this.eliminaContratto(this.contratti.find(c => String(c.id) === id)),
            'nuova-tariffa': () => this.apriTariffa(null, pulsante.dataset.figura),
            'modifica-tariffa': () => this.apriTariffa(this.tariffe.find(t => String(t.id) === id)),
            'elimina-tariffa': () => this.eliminaTariffa(this.tariffe.find(t => String(t.id) === id)),
            'cambia-regola': () => this.apriRegola(id, null),
            'modifica-regola': () => this.apriRegola(pulsante.dataset.chiave, Number(id)),
            'elimina-regola': () => this.eliminaRegola(pulsante.dataset.chiave, Number(id)),
            'modifica-qualifica': () => this.apriQualifica(this.qualifiche.find(q => q.testo === pulsante.dataset.testo)),
            'elimina-qualifica': () => this.eliminaQualifica(pulsante.dataset.testo),
        };
        if (azioni[azione]) azioni[azione]();
    },

    pulsantiRiga(tipo, id, etichetta, conElimina = true, extra = '', colonne = 1) {
        return `<td class="napoli-azioni"${colonne > 1 ? ` colspan="${colonne}"` : ''}>
            <button type="button" class="btn btn-sm btn-secondary" data-azione="modifica-${tipo}" data-id="${escapeHtml(String(id))}" ${extra} aria-label="Modifica ${escapeHtml(etichetta)}">${icona('matita')} Modifica</button>
            ${conElimina ? `<button type="button" class="btn btn-sm btn-icon-danger btn-solo-icona" data-azione="elimina-${tipo}" data-id="${escapeHtml(String(id))}" ${extra} title="Elimina" aria-label="Elimina ${escapeHtml(etichetta)}">${icona('cestino')}</button>` : ''}
        </td>`;
    },

    async inviaModulo(url, metodo, dati, contenitore, pulsante) {
        if (pulsante) setButtonLoading(pulsante, true);
        try {
            return await apiCall(url, { method: metodo, body: JSON.stringify(dati) });
        } catch (e) {
            e.contenitore = contenitore;
            throw e;
        } finally {
            if (pulsante) setButtonLoading(pulsante, false);
        }
    },

    pulsanteDi(form) {
        return document.querySelector(`button[type="submit"][form="${form.id}"]`) || form.querySelector('button[type="submit"]');
    },

    // ---------- dati del lotto ----------

    async carica_lotto() {
        const l = NapoliComune.lotto;
        this.el('btn-modifica-lotto').hidden = !l;
        this.el('btn-altro-lotto').hidden = !l;
        this.el('btn-nuovo-lotto').hidden = !l;
        if (this.senzaLotto('lotto-contenuto')) return;
        const vuoto = (v) => (v ? escapeHtml(String(v)) : '');
        const testo = (modello, valori) => (modello
            ? `<span class="napoli-esempio">${escapeHtml(napoliRiempiModello(modello, valori))}</span>`
              + `<span class="napoli-modello">Esempio per giugno 2026. Modello: ${escapeHtml(modello)}</span>`
            : 'il testo proposto');
        const valoriOggetto = { lotto: l.numero_lotto, grado: 'inferiore', dal: '08', al: '30', mese: 'Giugno', anno: '2026', contratto: 'XI' };
        const valoriNota = { servizio: l.riferimento_amministrativo || '…', dd_numero: '31', dd_data: '12/06/2026' };
        this.el('lotto-contenuto').innerHTML = `
            <div class="napoli-dati">
                ${rigaDati('Nome', vuoto(l.nome))}
                ${rigaDati('Numero', `Lotto ${l.numero_lotto}`)}
                ${rigaDati('Municipalità', vuoto(l.municipalita))}
                ${rigaDati('Stato', l.attivo ? 'Attivo' : 'Non più attivo')}
                ${rigaDati('CIG', vuoto(l.cig))}
                ${rigaDati('CUP', vuoto(l.cup))}
                ${rigaDati('Codice univoco ufficio', vuoto(l.codice_univoco_ufficio))}
                ${rigaDati('Riferimento amministrativo', vuoto(l.riferimento_amministrativo))}
            </div>
            <div class="napoli-dati mt-3">
                <div class="dati-riga-larga">${rigaDati('Oggetto della fattura', testo(l.oggetto_fattura, valoriOggetto))}</div>
                <div class="dati-riga-larga">${rigaDati('Nota della fattura', testo(l.nota_fattura, valoriNota))}</div>
                <div class="dati-riga-larga">${rigaDati('Destinatario', l.destinatario
                    ? escapeHtml(l.destinatario) : 'quello delle impostazioni, uguale per tutti i lotti')}</div>
            </div>`;
    },

    esempioOggetto() {
        const l = NapoliComune.lotto || {};
        const modello = this.el('lotto-oggetto').value;
        const numero = this.el('lotto-numero').value || l.numero_lotto;
        this.el('lotto-oggetto-esempio').textContent = modello.trim()
            ? 'Esempio: ' + napoliRiempiModello(modello, { lotto: numero, grado: 'inferiore', dal: '08', al: '30', mese: 'Giugno', anno: '2026', contratto: 'XI' })
            : '';
    },

    apriLotto() {
        const l = NapoliComune.lotto;
        if (!l) return;
        const form = this.el('form-lotto');
        napoliPulisciErrori(form);
        const usati = NapoliComune.lotti.filter(x => x.id !== l.id).map(x => x.numero_lotto);
        this.el('lotto-numero').innerHTML = [1, 2, 3, 4, 5].map(n =>
            `<option value="${n}"${usati.includes(n) ? ' disabled' : ''}>Lotto ${n}${usati.includes(n) ? ' (già usato)' : ''}</option>`).join('');
        napoliRiempiCampi(form, l);
        this.el('lotto-attivo').value = l.attivo ? '1' : '0';
        this.esempioOggetto();
        openModal('napoli-modal-lotto');
    },

    async salvaLotto() {
        const form = this.el('form-lotto');
        napoliPulisciErrori(form);
        if (!napoliCampoObbligatorio(this.el('lotto-nome'), 'Scrivi il nome del lotto.')
            || !napoliCampoObbligatorio(this.el('lotto-municipalita'), 'Scrivi le municipalità del lotto.')) return;
        const dati = napoliLeggiCampi(form);
        dati.numero_lotto = Number(dati.numero_lotto);
        dati.attivo = dati.attivo === '1';
        try {
            const r = await this.inviaModulo(`/api/napoli/lotti/${NapoliComune.lotto.id}`, 'PUT', dati, form, this.pulsanteDi(form));
            closeModal('napoli-modal-lotto');
            showToast(r.messaggio, 'success');
            await NapoliComune.caricaLotti(r.lotto.id);
            await this.carica_lotto();
        } catch (e) {
            napoliMostraErrore(e, form);
        }
    },

    eliminaLotto() {
        const l = NapoliComune.lotto;
        if (!l) return;
        showConfirmDialog(`Eliminare il lotto ${l.nome}?`,
            'Si eliminano anche i suoi contratti applicativi, le tariffe e le regole del lotto. Un lotto con scuole, alunni o presenze non si può eliminare. Ctrl+Z rimette tutto com\'era.',
            async () => {
                try {
                    const r = await apiCall(`/api/napoli/lotti/${l.id}`, { method: 'DELETE' });
                    showToast(r.messaggio, 'success');
                    NapoliComune.lotto = null;
                    await NapoliComune.caricaLotti();
                    await this.mostra('lotto');
                } catch (e) {
                    showToast(e.message, 'error', 9000);
                }
            }, { type: 'danger', confirmText: 'Elimina il lotto', cancelText: 'Non eliminare' });
    },

    // ---------- contratti applicativi ----------

    async carica_contratti() {
        this.el('btn-nuovo-contratto').hidden = !NapoliComune.lotto;
        if (this.senzaLotto('contratti-contenuto')) return;
        const lotto = NapoliComune.lotto;
        this.contratti = await apiCall(`/api/napoli/lotti/${lotto.id}/contratti`);
        const box = this.el('contratti-contenuto');
        if (!this.contratti.length) {
            box.innerHTML = '<p class="napoli-vuoto">Nessun contratto applicativo: aggiungi quello in corso (per esempio XI) con le sue date e la determina.</p>';
            return;
        }
        box.innerHTML = `
            <div class="table-container">
                <table class="table">
                    <thead><tr>
                        <th scope="col">Numero</th><th scope="col">Grado</th><th scope="col">Periodo</th>
                        <th scope="col">Determina (D.D.)</th><th scope="col" class="text-right">Importo</th><th scope="col" aria-label="Azioni"></th>
                    </tr></thead>
                    <tbody>
                        ${this.contratti.map(c => `
                            <tr>
                                <td><strong>${escapeHtml(c.numero)}</strong>${napoliValeOggi(c) ? '<span class="badge badge-success badge-sm napoli-badge-riga">in corso</span>' : ''}</td>
                                <td>${escapeHtml(NAPOLI_NOMI_GRADO[c.grado || ''])}</td>
                                <td>${escapeHtml(napoliPeriodo(c.valido_da, c.valido_a))}</td>
                                <td>${c.dd_numero && c.dd_data
                                    ? escapeHtml(`D.D. ${c.dd_servizio || lotto.riferimento_amministrativo || ''} N.${c.dd_numero} del ${formatDataIT(c.dd_data)}`)
                                    : '<span class="badge badge-warning">da completare</span>'}</td>
                                <td class="napoli-numero">${c.importo ? escapeHtml(c.importo) + ' €' : ''}</td>
                                ${this.pulsantiRiga('contratto', c.id, `il contratto ${c.numero}`, !c.usato)}
                            </tr>`).join('')}
                    </tbody>
                </table>
            </div>`;
    },

    apriContratto(c) {
        const form = this.el('form-contratto');
        napoliPulisciErrori(form);
        this.modifica.contratto = c ? c.id : null;
        this.el('contratto-titolo').textContent = c ? `Contratto applicativo ${c.numero}` : 'Nuovo contratto applicativo';
        const dati = c ? Object.assign({}, c, { grado: c.grado || '', importo: c.importo || '' }) : { grado: 'inferiore' };
        napoliRiempiCampi(form, dati);
        this.el('contratto-dd-servizio').placeholder = NapoliComune.lotto.riferimento_amministrativo || '';
        form.querySelector('details').open = !!(c && (c.accordo_quadro || c.repertorio || c.data_contratto || c.importo || c.note));
        openModal('napoli-modal-contratto');
    },

    async salvaContratto() {
        const form = this.el('form-contratto');
        napoliPulisciErrori(form);
        if (!napoliCampoObbligatorio(this.el('contratto-numero'), 'Scrivi il numero del contratto (per esempio XI).')
            || !napoliCampoObbligatorio(this.el('contratto-dal'), 'Scegli la data di inizio.')
            || !napoliCampoObbligatorio(this.el('contratto-al'), 'Scegli la data di fine.')) return;
        const id = this.modifica.contratto;
        const url = id ? `/api/napoli/contratti/${id}` : `/api/napoli/lotti/${NapoliComune.lotto.id}/contratti`;
        try {
            const r = await this.inviaModulo(url, id ? 'PUT' : 'POST', napoliLeggiCampi(form), form, this.pulsanteDi(form));
            closeModal('napoli-modal-contratto');
            showToast(r.messaggio, 'success');
            await this.carica_contratti();
        } catch (e) {
            napoliMostraErrore(e, form);
        }
    },

    eliminaContratto(c) {
        if (!c) return;
        showConfirmDialog(`Eliminare il contratto ${c.numero}?`, `${NAPOLI_NOMI_GRADO[c.grado || '']}, ${napoliPeriodo(c.valido_da, c.valido_a)}. Ctrl+Z lo rimette.`,
            async () => {
                try {
                    const r = await apiCall(`/api/napoli/contratti/${c.id}`, { method: 'DELETE' });
                    showToast(r.messaggio, 'success');
                    await this.carica_contratti();
                } catch (e) {
                    showToast(e.message, 'error', 9000);
                }
            }, { type: 'danger', confirmText: 'Elimina', cancelText: 'Non eliminare' });
    },

    // ---------- tariffe ----------

    async carica_tariffe() {
        this.el('btn-nuova-tariffa').hidden = !NapoliComune.lotto;
        if (this.senzaLotto('tariffe-contenuto')) return;
        this.tariffe = await apiCall(`/api/napoli/lotti/${NapoliComune.lotto.id}/tariffe`);
        const figura = (f, prima) => (prima
            ? `<div class="napoli-figura-nome">${escapeHtml(f.nome)}</div>${napoliDescrizioneDiversa(f) ? `<div class="napoli-figura-descrizione">${escapeHtml(f.descrizione)}</div>` : ''}`
            : '');
        const righe = (NapoliComune.figure || []).map(f => {
            const sue = this.tariffe.filter(t => t.figura === f.codice);
            const aggiungi = `<button type="button" class="btn btn-sm btn-ghost" data-azione="nuova-tariffa" data-figura="${escapeHtml(f.codice)}" aria-label="Aggiungi una tariffa ${escapeHtml(f.nome)}">Aggiungi</button>`;
            if (!sue.length) {
                return `<tr><td>${figura(f, true)}</td><td colspan="2" class="napoli-vuoto">Nessuna tariffa: le ore di questa figura non si possono fatturare finché non c'è.</td><td class="napoli-azioni">${aggiungi}</td></tr>`;
            }
            return sue.map((t, i) => `
                <tr class="${i ? 'napoli-stessa-figura' : ''}">
                    <td>${figura(f, i === 0)}</td>
                    <td class="napoli-numero"><strong>${escapeHtml(t.tariffa)} €</strong>${t.livello_ccnl ? `<br><span class="badge badge-secondary badge-sm">livello ${escapeHtml(t.livello_ccnl)}</span>` : ''}</td>
                    <td>${escapeHtml(napoliPeriodo(t.valido_da, t.valido_a))}${napoliValeOggi(t) ? '<span class="badge badge-success badge-sm napoli-badge-riga">vale oggi</span>' : ''}
                        ${t.fonte ? `<div class="napoli-figura-descrizione">${escapeHtml(t.fonte)}</div>` : ''}</td>
                    ${this.pulsantiRiga('tariffa', t.id, `la tariffa ${f.nome} ${t.tariffa} euro`)}
                </tr>`).join('');
        }).join('');
        this.el('tariffe-contenuto').innerHTML = `
            <div class="table-container">
                <table class="table">
                    <thead><tr><th scope="col">Figura</th><th scope="col" class="text-right">Euro all'ora</th><th scope="col">Quando vale</th><th scope="col" aria-label="Azioni"></th></tr></thead>
                    <tbody>${righe}</tbody>
                </table>
            </div>`;
    },

    apriTariffa(t, figura) {
        const form = this.el('form-tariffa');
        napoliPulisciErrori(form);
        this.modifica.tariffa = t ? t.id : null;
        this.el('tariffa-figura').innerHTML = NapoliComune.opzioniFigure(t ? t.figura : figura);
        this.el('tariffa-figura').disabled = false;
        let dati;
        if (t) {
            dati = Object.assign({}, t);
        } else {
            // la nuova tariffa comincia il giorno dopo la fine dell'ultima della stessa figura
            const scelta = figura || this.el('tariffa-figura').value;
            const ultima = this.tariffe.filter(x => x.figura === scelta && !x.livello_ccnl && x.valido_a)
                .sort((a, b) => (a.valido_a < b.valido_a ? 1 : -1))[0];
            dati = { figura: scelta, valido_da: ultima ? napoliGiornoDopo(ultima.valido_a) : '' };
        }
        napoliRiempiCampi(form, dati);
        this.el('tariffa-titolo').textContent = t ? `Tariffa ${NapoliComune.nomeFigura(t.figura)}` : 'Nuova tariffa';
        form.querySelector('details').open = !!(t && (t.livello_ccnl || t.fonte));
        openModal('napoli-modal-tariffa');
    },

    async salvaTariffa(chiudiPrecedenti) {
        const form = this.el('form-tariffa');
        napoliPulisciErrori(form);
        if (!napoliCampoObbligatorio(this.el('tariffa-euro'), 'Scrivi la tariffa, per esempio 23,44.')
            || !napoliCampoObbligatorio(this.el('tariffa-dal'), 'Scegli da quando vale.')) return;
        const id = this.modifica.tariffa;
        const dati = Object.assign(napoliLeggiCampi(form), { chiudi_precedenti: !!chiudiPrecedenti });
        const url = id ? `/api/napoli/tariffe/${id}` : `/api/napoli/lotti/${NapoliComune.lotto.id}/tariffe`;
        try {
            const r = await this.inviaModulo(url, id ? 'PUT' : 'POST', dati, form, this.pulsanteDi(form));
            closeModal('napoli-modal-tariffa');
            showToast(r.messaggio, 'success', r.messaggio.length > 40 ? 9000 : 5000);
            await this.carica_tariffe();
        } catch (e) {
            if (e.code === 'TARIFFE_SOVRAPPOSTE' && e.data.chiudibili && e.data.chiudibili.length && !chiudiPrecedenti) {
                this.proponiChiusura(e, () => this.salvaTariffa(true), 'Chiudi la precedente e salva');
            } else {
                napoliMostraErrore(e, form);
            }
        }
    },

    /** Date sovrapposte a un valore che comincia prima: quello finisce il giorno prima e, se
     *  andava oltre la fine del nuovo, riprende il giorno dopo (il server lo divide in due:
     *  nessun giorno resta senza valore). Il messaggio del server dice le date. */
    proponiChiusura(e, riprova, testo) {
        const divide = (e.data.chiudibili || []).some(c => c.riprende_da);
        showConfirmDialog('Le date si sovrappongono', e.message,
            riprova, { confirmText: divide ? 'Salva solo per questi giorni' : testo, cancelText: 'Correggo le date', type: 'warning' });
    },

    eliminaTariffa(t) {
        if (!t) return;
        showConfirmDialog('Eliminare la tariffa?',
            `${NapoliComune.nomeFigura(t.figura)}: ${t.tariffa} euro, ${napoliPeriodo(t.valido_da, t.valido_a)}. Le fatture già fatte non cambiano. Ctrl+Z la rimette.`,
            async () => {
                try {
                    const r = await apiCall(`/api/napoli/tariffe/${t.id}`, { method: 'DELETE' });
                    showToast(r.messaggio, 'success');
                    await this.carica_tariffe();
                } catch (e) {
                    showToast(e.message, 'error', 9000);
                }
            }, { type: 'danger', confirmText: 'Elimina', cancelText: 'Non eliminare' });
    },

    // ---------- regole con data ----------

    async carica_regole() {
        const lotto = NapoliComune.lotto;
        this.regole = await apiCall('/api/napoli/regole' + (lotto ? `?lotto_id=${lotto.id}` : ''));
        const origine = (r) => ({
            predefinita: '<span class="badge badge-secondary badge-sm">predefinita</span>',
            tutti: '<span class="badge badge-primary badge-sm">tutti i lotti</span>',
            lotto: '<span class="badge badge-success badge-sm">questo lotto</span>',
        })[r.origine];
        const lunga = (r) => (r.tipo === 'testo' ? 'lungo' : '');   // i testi lunghi in piccolo
        // righe dei valori salvati: "Modifica" e il cestino non entrano nella sola colonna dei
        // pulsanti (stretta, la tabella ha le colonne fisse), quindi prendono anche "Da dove"
        const tabella = (regole) => `
            <div class="table-container">
                <table class="table napoli-tabella-regole">
                    <colgroup><col class="c-regola"><col class="c-valore"><col class="c-dove"><col class="c-azioni"></colgroup>
                    <thead><tr><th scope="col">Regola</th><th scope="col">Oggi vale</th><th scope="col">Da dove</th><th scope="col" aria-label="Azioni"></th></tr></thead>
                    <tbody>${regole.map(r => `
                        <tr>
                            <td><div class="napoli-regola-etichetta">${escapeHtml(r.etichetta)}</div>
                                ${r.spiegazione ? `<div class="napoli-regola-spiegazione">${escapeHtml(r.spiegazione)}</div>` : ''}</td>
                            <td class="napoli-regola-valore ${lunga(r)}">${escapeHtml(r.valore_testo)}</td>
                            <td>${origine(r)}${r.fuori_validita ? ' <span class="badge badge-warning badge-sm">da aggiornare</span>' : ''}</td>
                            <td class="napoli-azioni"><button type="button" class="btn btn-sm btn-secondary" data-azione="cambia-regola" data-id="${escapeHtml(r.chiave)}" aria-label="Cambia: ${escapeHtml(r.etichetta)}">Cambia</button></td>
                        </tr>
                        ${r.salvate.map(s => `
                        <tr class="napoli-storico">
                            <td>${escapeHtml(s.valore_testo)} · ${s.lotto_id ? 'questo lotto' : 'tutti i lotti'}${s.fonte ? ` · <span class="text-muted">${escapeHtml(s.fonte)}</span>` : ''}</td>
                            <td>${escapeHtml(napoliPeriodo(s.valido_da, s.valido_a))}</td>
                            ${this.pulsantiRiga('regola', s.id, `il valore ${s.valore_testo}`, true, `data-chiave="${escapeHtml(r.chiave)}"`, 2)}
                        </tr>`).join('')}`).join('')}
                    </tbody>
                </table>
            </div>`;
        const gruppi = this.regole.gruppi.map(g => {
            const sue = this.regole.regole.filter(r => r.gruppo === g.codice);
            if (!sue.length) return '';
            if (g.codice === 'fase_2') {
                return `<details class="section napoli-gruppo-regole"><summary>${escapeHtml(g.nome)}</summary>${tabella(sue)}</details>`;
            }
            return `<div class="napoli-gruppo-regole"><h3>${escapeHtml(g.nome)}</h3>${tabella(sue)}</div>`;
        }).join('');
        this.el('regole-contenuto').innerHTML = (lotto ? '' : '<p class="napoli-vuoto">Senza un lotto si vedono e si cambiano solo le regole per tutti i lotti.</p>') + gruppi;
    },

    regola(chiave) {
        return this.regole.regole.find(r => r.chiave === chiave);
    },

    campoValore(r, valore) {
        const box = this.el('regola-valore-campo');
        const etichetta = this.el('regola-valore-etichetta');
        etichetta.textContent = r.unita === 'minuti' ? 'Nuovo valore (ore) *' : 'Nuovo valore *';
        etichetta.setAttribute('for', 'regola-valore');
        if (r.scelte.length || r.tipo === 'booleano') {
            const scelte = r.tipo === 'booleano' ? [{ valore: true, testo: 'Sì' }, { valore: false, testo: 'No' }] : r.scelte;
            box.innerHTML = `<select id="regola-valore" class="form-control">${scelte.map((s, i) =>
                `<option value="${i}"${s.valore === valore ? ' selected' : ''}>${escapeHtml(s.testo)}</option>`).join('')}</select>`;
            box.dataset.scelte = JSON.stringify(scelte.map(s => s.valore));
        } else if (r.tipo === 'giorni' || r.tipo === 'mesi') {
            etichetta.removeAttribute('for');
            const nomi = r.tipo === 'giorni' ? NAPOLI_GIORNI : NAPOLI_MESI;
            const base = r.tipo === 'giorni' ? 0 : 1;
            box.innerHTML = `<div class="napoli-giorni" role="group" aria-label="${escapeHtml(r.etichetta)}">${nomi.map((n, i) =>
                `<label class="napoli-scelta"><input type="checkbox" value="${i + base}"${(valore || []).includes(i + base) ? ' checked' : ''}> ${n}</label>`).join('')}</div>`;
        } else if (r.tipo === 'elenco' && r.voci.length) {
            // codici fissi (gli usi A, B, D): una casella per ciascuno, niente da scrivere
            etichetta.removeAttribute('for');
            box.innerHTML = `<div class="napoli-giorni" role="group" aria-label="${escapeHtml(r.etichetta)}">${r.voci.map(v =>
                `<label class="napoli-scelta"><input type="checkbox" value="${escapeHtml(v.valore)}"${(valore || []).includes(v.valore) ? ' checked' : ''}> ${escapeHtml(v.testo)}</label>`).join('')}</div>`;
        } else if (r.tipo === 'testo') {
            box.innerHTML = `<textarea id="regola-valore" class="form-control" rows="3" maxlength="500">${escapeHtml(valore || '')}</textarea>`;
        } else if (r.tipo === 'elenco') {
            box.innerHTML = `<input type="text" id="regola-valore" class="form-control" value="${escapeHtml((valore || []).join(', '))}" autocomplete="off">`;
        } else {
            const testo = r.unita === 'minuti' ? formatNumero(Number(valore) / 60) : String(valore ?? '');
            box.innerHTML = `<input type="text" id="regola-valore" class="form-control napoli-campo-medio" inputmode="decimal" value="${escapeHtml(testo)}" autocomplete="off">`;
        }
    },

    leggiValore(r) {
        const box = this.el('regola-valore-campo');
        if (r.scelte.length || r.tipo === 'booleano') {
            return JSON.parse(box.dataset.scelte)[Number(this.el('regola-valore').value)];
        }
        if (r.tipo === 'giorni' || r.tipo === 'mesi') {
            return [...box.querySelectorAll('input:checked')].map(i => Number(i.value));
        }
        if (r.tipo === 'elenco' && r.voci.length) {
            return [...box.querySelectorAll('input:checked')].map(i => i.value);
        }
        const testo = this.el('regola-valore').value.trim();
        if (r.tipo === 'elenco') return testo.split(',').map(x => x.trim()).filter(Boolean);
        if (r.unita === 'minuti') {
            // solo numeri scritti per esteso (1,5 o 1.5): altrimenti il server risponde "scrivi un numero"
            if (!/^-?(\d+([.,]\d*)?|[.,]\d+)$/.test(testo)) return testo;
            return Math.round(Number(testo.replace(',', '.')) * 60);
        }
        return testo;
    },

    /** Cambia una regola da una data (riga nuova) o modifica una riga salvata (idSalvata). */
    apriRegola(chiave, idSalvata) {
        const r = this.regola(chiave);
        if (!r) return;
        const salvata = idSalvata ? r.salvate.find(s => s.id === idSalvata) : null;
        const form = this.el('form-regola');
        napoliPulisciErrori(form);
        this.modifica.regola = { chiave, id: salvata ? salvata.id : null };
        this.el('regola-titolo').textContent = salvata ? 'Modifica il valore salvato' : 'Cambia la regola';
        this.el('regola-nome').textContent = r.etichetta;
        this.el('regola-spiegazione').textContent = [r.spiegazione,
            `Valore predefinito: ${r.predefinito_testo}.`].filter(Boolean).join(' ');
        const valore = salvata ? salvata.valore : r.valore;
        this.campoValore(r, valore);
        this.el('regola-dal').value = salvata ? salvata.valido_da : napoliOggi();
        this.el('regola-al').value = salvata ? (salvata.valido_a || '') : '';
        this.el('regola-fonte').value = salvata ? (salvata.fonte || '') : '';
        const lotto = NapoliComune.lotto;
        const perLotto = salvata ? !!salvata.lotto_id : r.origine === 'lotto';
        form.querySelectorAll('input[name="regola-ambito"]').forEach(i => {
            i.checked = (i.value === 'lotto') === perLotto;
            i.disabled = !!salvata || (i.value === 'lotto' && !lotto);
        });
        this.el('regola-ambito-lotto').textContent = lotto ? lotto.nome : 'questo lotto';
        openModal('napoli-modal-regola');
    },

    async salvaRegola(chiudiPrecedenti) {
        const form = this.el('form-regola');
        napoliPulisciErrori(form);
        if (!napoliCampoObbligatorio(this.el('regola-dal'), 'Scegli da quando vale.')) return;
        const { chiave, id } = this.modifica.regola;
        const r = this.regola(chiave);
        const perLotto = form.querySelector('input[name="regola-ambito"]:checked')?.value === 'lotto';
        const dati = {
            chiave, valore: this.leggiValore(r), valido_da: this.el('regola-dal').value, valido_a: this.el('regola-al').value,
            fonte: this.el('regola-fonte').value.trim(), chiudi_precedenti: !!chiudiPrecedenti,
            lotto_id: perLotto && NapoliComune.lotto ? NapoliComune.lotto.id : null,
        };
        try {
            const res = await this.inviaModulo(id ? `/api/napoli/regole/${id}` : '/api/napoli/regole', id ? 'PUT' : 'POST',
                dati, form, this.pulsanteDi(form));
            closeModal('napoli-modal-regola');
            showToast(res.messaggio, 'success', res.messaggio.length > 40 ? 9000 : 5000);
            await this.carica_regole();
        } catch (e) {
            if (e.code === 'REGOLE_SOVRAPPOSTE' && e.data.chiudibili && e.data.chiudibili.length && !chiudiPrecedenti) {
                this.proponiChiusura(e, () => this.salvaRegola(true), 'Chiudi il valore di prima e salva');
            } else {
                napoliMostraErrore(e, form);
            }
        }
    },

    eliminaRegola(chiave, id) {
        const r = this.regola(chiave);
        const s = r && r.salvate.find(x => x.id === id);
        if (!s) return;
        showConfirmDialog('Eliminare questo valore?',
            `${r.etichetta}: ${s.valore_testo}, ${napoliPeriodo(s.valido_da, s.valido_a)}. In quei giorni varrà di nuovo il valore precedente. Ctrl+Z lo rimette.`,
            async () => {
                try {
                    const res = await apiCall(`/api/napoli/regole/${id}`, { method: 'DELETE' });
                    showToast(res.messaggio, 'success');
                    await this.carica_regole();
                } catch (e) {
                    showToast(e.message, 'error', 9000);
                }
            }, { type: 'danger', confirmText: 'Elimina', cancelText: 'Non eliminare' });
    },

    // ---------- cooperativa e destinatario ----------

    async caricaImpostazioni() {
        this.impostazioni = await apiCall('/api/napoli/impostazioni');
        return this.impostazioni;
    },

    async carica_cooperativa() {
        const imp = await this.caricaImpostazioni();
        const form = this.el('form-cooperativa');
        napoliPulisciErrori(form);
        napoliRiempiCampi(form, imp.cooperativa);
        const iban = this.el('coop-iban');
        iban.value = '';
        iban.placeholder = imp.cooperativa.iban_salvato ? imp.cooperativa.iban_mascherato : 'IT seguito da 25 lettere e numeri';
        this.el('coop-iban-aiuto').textContent = imp.cooperativa.iban_salvato
            ? `IBAN salvato: ${imp.cooperativa.iban_mascherato}. Per sicurezza si vede solo in parte. Per cambiarlo scrivi quello nuovo; per tenerlo lascia la casella vuota.`
            : 'Il programma controlla che l\'IBAN sia scritto bene (cifre di controllo).';
        this.el('btn-togli-iban').hidden = !imp.cooperativa.iban_salvato;
    },

    async salvaCooperativa() {
        const form = this.el('form-cooperativa');
        napoliPulisciErrori(form);
        const dati = napoliLeggiCampi(form);
        if (!dati.cooperativa_iban) delete dati.cooperativa_iban;   // vuoto = l'IBAN salvato resta
        try {
            const r = await this.inviaModulo('/api/napoli/impostazioni/cooperativa', 'PUT', dati, form, this.pulsanteDi(form));
            showToast(r.cambiati.length ? `Salvato: ${r.cambiati.join(', ')}` : r.messaggio, r.cambiati.length ? 'success' : 'info');
            await this.carica_cooperativa();
        } catch (e) {
            napoliMostraErrore(e, form);
        }
    },

    togliIban() {
        showConfirmDialog('Togliere l\'IBAN salvato?', 'Senza IBAN il prospetto della fattura non si potrà rendere definitivo. Ctrl+Z lo rimette.',
            async () => {
                try {
                    await apiCall('/api/napoli/impostazioni/cooperativa', { method: 'PUT', body: JSON.stringify({ cooperativa_iban: '' }) });
                    showToast('IBAN tolto', 'success');
                    await this.carica_cooperativa();
                } catch (e) {
                    showToast(e.message, 'error', 9000);
                }
            }, { type: 'danger', confirmText: 'Togli l\'IBAN', cancelText: 'Tienilo' });
    },

    async carica_destinatario() {
        const imp = await this.caricaImpostazioni();
        const form = this.el('form-destinatario');
        napoliPulisciErrori(form);
        napoliRiempiCampi(form, imp.destinatario_salvato ? imp.destinatario : imp.destinatario_proposto);
        this.el('destinatario-stato').hidden = imp.destinatario_salvato;
    },

    async salvaDestinatario() {
        const form = this.el('form-destinatario');
        napoliPulisciErrori(form);
        if (!napoliCampoObbligatorio(this.el('dest-denominazione'), 'Scrivi l\'ente a cui si intestano le fatture.')) return;
        try {
            const r = await this.inviaModulo('/api/napoli/impostazioni/destinatario', 'PUT', napoliLeggiCampi(form), form, this.pulsanteDi(form));
            showToast(r.cambiati.length ? 'Destinatario salvato' : r.messaggio, r.cambiati.length ? 'success' : 'info');
            await this.carica_destinatario();
        } catch (e) {
            napoliMostraErrore(e, form);
        }
    },

    // ---------- qualifiche ----------

    async carica_qualifiche() {
        this.qualifiche = await apiCall('/api/napoli/qualifiche');
        this.el('qualifiche-contenuto').innerHTML = `
            <div class="table-container">
                <table class="table">
                    <thead><tr><th scope="col">Come è scritta nel file</th><th scope="col">Figura</th><th scope="col">Origine</th><th scope="col" aria-label="Azioni"></th></tr></thead>
                    <tbody>${this.qualifiche.map(q => `
                        <tr>
                            <td><strong>${escapeHtml(q.testo)}</strong></td>
                            <td>${escapeHtml(q.figura_descrizione)}</td>
                            <td>${q.origine === 'utente' ? '<span class="badge badge-success badge-sm">aggiunta</span>' : '<span class="badge badge-secondary badge-sm">predefinita</span>'}</td>
                            ${this.pulsantiRiga('qualifica', q.testo, `la qualifica ${q.testo}`, q.origine === 'utente', `data-testo="${escapeHtml(q.testo)}"`)}
                        </tr>`).join('')}
                    </tbody>
                </table>
            </div>`;
    },

    apriQualifica(q) {
        const form = this.el('form-qualifica');
        napoliPulisciErrori(form);
        this.modifica.qualifica = q ? q.testo : null;
        this.el('qualifica-titolo').textContent = q ? 'Cambia la figura' : 'Nuova qualifica';
        // per una qualifica nuova nessuna figura e' gia' scelta (come nell'import): si sceglie
        this.el('qualifica-figura').innerHTML = q ? NapoliComune.opzioniFigure(q.figura)
            : `<option value="" selected>— scegli —</option>${NapoliComune.opzioniFigure(null)}`;
        this.el('qualifica-testo').value = q ? q.testo : '';
        this.el('qualifica-testo').readOnly = !!q;
        openModal('napoli-modal-qualifica');
    },

    async salvaQualifica() {
        const form = this.el('form-qualifica');
        napoliPulisciErrori(form);
        if (!napoliCampoObbligatorio(this.el('qualifica-testo'), 'Scrivi la qualifica come compare nel file.')) return;
        if (!napoliCampoObbligatorio(this.el('qualifica-figura'), 'Scegli la figura professionale.')) return;
        const nuova = !this.modifica.qualifica;
        try {
            const r = await this.inviaModulo('/api/napoli/qualifiche', nuova ? 'POST' : 'PUT', napoliLeggiCampi(form), form, this.pulsanteDi(form));
            closeModal('napoli-modal-qualifica');
            showToast(r.messaggio, 'success');
            await this.carica_qualifiche();
        } catch (e) {
            napoliMostraErrore(e, form);
        }
    },

    eliminaQualifica(testo) {
        showConfirmDialog('Eliminare la qualifica?', `"${testo}". Ctrl+Z la rimette.`, async () => {
            try {
                const r = await apiCall('/api/napoli/qualifiche', { method: 'DELETE', body: JSON.stringify({ testo }) });
                showToast(r.messaggio, 'success');
                await this.carica_qualifiche();
            } catch (e) {
                showToast(e.message, 'error', 9000);
            }
        }, { type: 'danger', confirmText: 'Elimina', cancelText: 'Non eliminare' });
    },
};

// ==================== scheda Presenze (griglia del mese, passo 1.7) ====================

const NAPOLI_PRESENZE_ATTESA = 2000;          // come il salvataggio automatico della Rendicontazione
// caselle per richiesta: il server ne prende al massimo 2000 (napoli_presenze.MAX_CELLE); un incolla
// piu' grande parte a gruppi, una richiesta dopo l'altra
const NAPOLI_PRESENZE_GRUPPO = 2000;
// uscendo dalla pagina il browser porta a termine richieste per al massimo 64 KB in tutto (fetch
// keepalive): quello che non ci sta resta da salvare e la pagina chiede prima di uscire
const NAPOLI_PRESENZE_USCITA_BYTE = 60000;
// nuovi tentativi da soli quando il collegamento o il programma non rispondono: 5, 10, 20, 30 secondi
const NAPOLI_PRESENZE_RIPROVA = [5000, 10000, 20000, 30000];
const NAPOLI_CHIAVE_MESE = 'napoli.mese';
const NAPOLI_TESTI_GRADO = { inferiore: 'Inferiore', superiore: 'Superiore', da_decidere: 'Da decidere' };
const NAPOLI_SIGLE_OPERATORE = { F: 'Ferie dell\'operatore', M: 'Malattia dell\'operatore', P: 'Permesso dell\'operatore (F perm)' };
const NAPOLI_NOTE_GIORNO = {
    evento: 'Assemblea o evento della scuola', attivita_esterna: 'Uscita didattica',
    ritardo: 'Alunno entrato alle', uscita_anticipata: 'Alunno uscito alle',
};

/** Ore e minuti: 90 -> '1:30' (come napoli_calcoli.hhmm). */
function napoliHhmm(min) {
    const segno = min < 0 ? '-' : '';
    const a = Math.abs(Math.round(min));
    return `${segno}${Math.floor(a / 60)}:${String(a % 60).padStart(2, '0')}`;
}

/** Minuti in ore decimali al centesimo (arrotondamento commerciale), senza zeri inutili:
 *  750 -> '12,5', 80 -> '1,33' (come napoli_calcoli.ore_brevi). */
function napoliOreBrevi(min) {
    const segno = min < 0 ? '-' : '';
    const cent = Math.floor((Math.abs(Math.round(min)) * 100 + 30) / 60);
    let testo = `${Math.floor(cent / 100)},${String(cent % 100).padStart(2, '0')}`;
    testo = testo.replace(/0+$/, '').replace(/,$/, '');
    return segno + testo.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
}

/** Le due forme: '1:30 (1,50)' (come napoli_calcoli.ore_due_forme). */
function napoliOreDueForme(min) {
    const cent = Math.floor((Math.abs(Math.round(min)) * 100 + 30) / 60);
    return `${napoliHhmm(min)} (${min < 0 ? '-' : ''}${Math.floor(cent / 100)},${String(cent % 100).padStart(2, '0')})`;
}

/** Una casella scritta come nel master (come napoli_calcoli.testo_ore_cella): 90 -> '1,5', 80 -> '1:20'. */
function napoliTestoCella(min) {
    return min % 15 ? napoliHhmm(min) : napoliOreBrevi(min);
}

/** Il giorno della settimana di una data 'AAAA-MM-GG' ('giovedì'), senza passare dal fuso orario. */
function napoliGiornoLungo(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
    return m ? NAPOLI_GIORNI[(new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).getDay() + 6) % 7] : '';
}

function napoliNormalizza(testo) {
    return String(testo || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
}

/**
 * La griglia presenze del mese del lotto (REGOLE 1-3, 12, 14, 15): una riga per coppia, una
 * casella per giorno di servizio, VERIFICA per settimana, totale e credito/debito. Ogni
 * numero mostrato (ore riconosciute, VERIFICA, totali, credito/debito) arriva dal server
 * (napoli_presenze, con napoli_calcoli): la pagina somma solo minuti interi per il
 * riepilogo delle righe mostrate. Salvataggio automatico a gruppi 2 secondi dopo l'ultimo
 * tasto (al massimo 2000 caselle per richiesta, e uscendo dalla pagina con fetch keepalive); se
 * non riesce, come in Rendicontazione: "Modifiche non salvate", il pulsante "Riprova a salvare"
 * (anche Ctrl+S), nuovi tentativi da soli se il collegamento o il programma non rispondono, e
 * la domanda del browser prima di uscire. Le caselle da chiarire ("1,30", le ore programmate di
 * un giorno con l'alunno assente) si chiedono una alla volta.
 */
const NapoliPresenze = {
    dati: null,
    righe: new Map(),          // id coppia -> riga del server
    attese: new Map(),         // 'coppia|indice' -> casella da salvare {coppia_id, data, testo, ...}
    errori: new Map(),         // 'coppia|indice' -> messaggio
    domande: [],               // caselle da chiarire, una alla volta
    domanda: null,
    letturaScelta: null,       // "Leggi cosi' anche le prossime caselle" per i valori come 1,30
    timer: null,
    inVolo: null,
    ancora: false,
    ultimoSalvataggio: null,
    erroreSalvataggio: null,   // l'ultimo salvataggio non e' riuscito (rete, programma): il messaggio
    tentativi: 0,              // salvataggi non riusciti di fila (per l'attesa del prossimo tentativo)
    riprova: null,             // il nuovo tentativo da solo
    attiva: null,              // la casella scelta {id, i}
    filtri: { cerca: '', scuola: '', operatore: '', figura: '', grado: '', municipalita: '', avvisi: false },
    seqCaricamento: 0,

    el(id) { return document.getElementById(id); },

    async avvia() {
        NapoliComune.alCambioLotto = async () => {
            // con caselle non salvate si resta sul lotto e sul mese mostrati (come in Rendicontazione)
            if (!(await this.puoLasciare())) { this.tornaAlMostrato(); return; }
            await this.carica();
        };
        NapoliComune.dopoAnnulla = async () => { await this.carica(true); };
        NapoliComune.primaDiAnnullare = () => this.puoLasciare('Modifiche non salvate: prima di annullare bisogna salvarle. Riprova il salvataggio.', 'annulli l\'ultima modifica');
        this.collega();
        try {
            await NapoliComune.caricaLotti();
        } catch (e) {
            this.el('presenze-senza-lotto').hidden = false;
            this.el('presenze-senza-lotto').innerHTML = `<div class="alert alert-danger">${escapeHtml(e.message || 'Dati non disponibili')}</div>`;
            return;
        }
        this.preparaMesi();
        await this.carica();
    },

    // ---------- mese scelto (ricordato nel browser) ----------

    meseRicordato() {
        try {
            const v = localStorage.getItem(NAPOLI_CHIAVE_MESE);
            return /^\d{4}-\d{2}$/.test(v || '') ? v : null;
        } catch (e) { return null; }
    },

    ricordaMese(v) {
        try { localStorage.setItem(NAPOLI_CHIAVE_MESE, v); } catch (e) { /* il browser non ricorda: pazienza */ }
    },

    preparaMesi(scelto) {
        const oggi = new Date();
        const corrente = `${oggi.getFullYear()}-${String(oggi.getMonth() + 1).padStart(2, '0')}`;
        const valore = scelto || this.meseRicordato() || corrente;
        const mesi = [];
        for (let k = -12; k <= 1; k++) {
            const d = new Date(oggi.getFullYear(), oggi.getMonth() + k, 1);
            mesi.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
        }
        if (!mesi.includes(valore)) mesi.push(valore);
        mesi.sort();
        const scelta = this.el('pm-mese');
        scelta.innerHTML = mesi.map(v => `<option value="${v}">${escapeHtml(napoliMaiuscola(formatMeseIT(v)))}</option>`).join('');
        scelta.value = valore;
    },

    meseScelto() {
        const [anno, mese] = this.el('pm-mese').value.split('-').map(Number);
        return { anno, mese };
    },

    async cambiaMese(passo) {
        if (!(await this.puoLasciare())) return;
        const scelta = this.el('pm-mese');
        const { anno, mese } = this.meseScelto();
        const d = new Date(anno, mese - 1 + passo, 1);
        const v = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
        if (![...scelta.options].some(o => o.value === v)) this.preparaMesi(v);
        scelta.value = v;
        this.ricordaMese(v);
        await this.carica();
    },

    /** Il salvataggio non e' riuscito: la scelta del lotto e del mese torna su quelli mostrati. */
    tornaAlMostrato() {
        const d = this.dati;
        if (!d) return;
        const l = NapoliComune.lotti.find(x => x.id === d.lotto.id);
        if (l && NapoliComune.lotto !== l) {
            NapoliComune.lotto = l;
            NapoliComune.ricorda(l.id);
            NapoliComune.disegnaScelta();
        }
        const v = `${d.anno}-${String(d.mese).padStart(2, '0')}`;
        const scelta = this.el('pm-mese');
        if (![...scelta.options].some(o => o.value === v)) this.preparaMesi(v);
        scelta.value = v;
        this.ricordaMese(v);
    },

    // ---------- eventi ----------

    collega() {
        const griglia = this.el('presenze-griglia');
        griglia.addEventListener('input', (e) => { if (e.target.matches('.g-in')) this.modificata(e.target); });
        griglia.addEventListener('keydown', (e) => { if (e.target.matches('.g-in')) this.tasti(e); });
        griglia.addEventListener('focusin', (e) => { if (e.target.matches('.g-in')) this.scelta(e.target); });
        // come in Excel: un clic su una casella la sceglie tutta (scrivendo si sostituisce)
        griglia.addEventListener('mousedown', (e) => { this.appenaScelta = e.target.matches('.g-in') && document.activeElement !== e.target ? e.target : null; });
        griglia.addEventListener('mouseup', (e) => {
            if (this.appenaScelta && e.target === this.appenaScelta) { e.preventDefault(); this.appenaScelta.select(); }
            this.appenaScelta = null;
        });
        griglia.addEventListener('paste', (e) => { if (e.target.matches('.g-in')) this.incolla(e); });
        griglia.addEventListener('click', (e) => {
            if (e.target.closest('.g-in')) return;
            const tr = e.target.closest('tr[data-id]');
            if (tr && e.target.closest('.g-fissa, .g-ver, .g-tot, .g-cd')) this.apriDettaglio(Number(tr.dataset.id));
        });
        this.el('pm-mese').addEventListener('change', async () => {
            if (!(await this.puoLasciare())) { this.tornaAlMostrato(); return; }
            this.ricordaMese(this.el('pm-mese').value);
            await this.carica();
        });
        this.el('pm-prima').addEventListener('click', () => this.cambiaMese(-1));
        this.el('pm-dopo').addEventListener('click', () => this.cambiaMese(1));
        this.el('presenze-filtri').addEventListener('input', (e) => this.leggiFiltro(e.target));
        this.el('presenze-filtri').addEventListener('change', (e) => this.leggiFiltro(e.target));
        this.el('pf-avvisi').addEventListener('click', () => {
            this.filtri.avvisi = !this.filtri.avvisi;
            this.el('pf-avvisi').setAttribute('aria-pressed', String(this.filtri.avvisi));
            this.filtra();
        });
        this.el('btn-nota-giorno').addEventListener('click', () => {
            if (this.attiva) this.apriNota(this.attiva.id, this.attiva.i);
            else showToast('Scegli prima una casella della griglia, poi la sua nota del giorno.', 'info');
        });
        this.el('btn-presenze-annulla').addEventListener('click', () => NapoliComune.annulla());
        // "Riprova a salvare" (compare solo se il salvataggio non riesce) e Ctrl+S (app.js: data-action="save")
        this.el('btn-presenze-riprova').addEventListener('click', () => this.salvaSubito());
        this.el('btn-mese').addEventListener('click', () => this.apriMese());
        this.el('form-nota').addEventListener('submit', (e) => { e.preventDefault(); this.salvaNota(); });
        this.el('form-nota').addEventListener('change', () => this.aggiornaNota());
        this.el('form-mese').addEventListener('submit', (e) => { e.preventDefault(); this.confermaMese(); });
        const domanda = this.el('napoli-modal-domanda');
        domanda.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') { e.stopPropagation(); this.lasciaDomanda(); return; }
            // la finestra si apre da sola dopo il salvataggio: un Invio premuto per la griglia proprio
            // in quel momento non sceglie niente (serve un Invio voluto, dopo aver letto)
            if (e.key === 'Enter' && Date.now() - (this.domandaDal || 0) < 600) { e.preventDefault(); e.stopPropagation(); }
        });
        domanda.addEventListener('click', (e) => { if (e.target === domanda) { e.stopPropagation(); this.lasciaDomanda(); } }, true);
        this.el('form-domanda').addEventListener('submit', (e) => { e.preventDefault(); this.rispondi(); });
        this.el('domanda-pulsanti').addEventListener('click', (e) => {
            const b = e.target.closest('button[data-risposta]');
            if (b) this.rispondi(b.dataset.risposta);
        });
        this.el('coppia-corpo').addEventListener('click', (e) => {
            const b = e.target.closest('[data-nota-giorno]');
            if (!b) return;
            const r = this.righe.get(Number(b.dataset.coppia));
            const i = this.dati.giorni.indexOf(b.dataset.notaGiorno);
            if (r && i >= 0) { closeModal('napoli-modal-coppia'); this.apriNota(r.id, i); }
        });
        // caselle che uscendo andrebbero perse (da correggere, salvataggio non riuscito, o troppe
        // per partire all'uscita): il browser chiede prima di lasciare la pagina
        window.addEventListener('beforeunload', (e) => {
            if (this.nonPartono()) { e.preventDefault(); e.returnValue = ''; }
        });
        // uscita dalla pagina entro i 2 secondi: le caselle cambiate partono subito
        window.addEventListener('pagehide', () => this.inviaInUscita());
        document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') this.inviaInUscita(); });
        window.addEventListener('resize', () => this.misura());
        document.querySelector('.napoli-presenze-aiuto')?.addEventListener('toggle', () => this.misura());
        // la testata cambia altezza (stato del salvataggio piu' lungo, "Riprova a salvare", mese
        // chiuso): la griglia si rimisura, cosi' la pagina non scorre
        if (typeof ResizeObserver === 'function') {
            const osserva = new ResizeObserver(() => this.misura());
            ['.napoli-presenze-testa', '#presenze-chiuso', '#presenze-filtri'].forEach(s => {
                const el = document.querySelector(s);
                if (el) osserva.observe(el);
            });
        }
    },

    // ---------- caricamento e disegno ----------

    async carica(tieniPosto = false) {
        const lotto = NapoliComune.lotto;
        const vuoto = this.el('presenze-senza-lotto');
        const contenuto = this.el('presenze-contenuto');
        if (!lotto) {
            contenuto.hidden = true;
            vuoto.hidden = false;
            vuoto.innerHTML = `<div class="card">${napoliBenvenuto()}</div>`;
            vuoto.querySelector('[data-azione="crea-lotto"]')?.addEventListener('click', () =>
                NapoliProcedura.apri(async (l) => { await NapoliComune.caricaLotti(l.id); await this.carica(); }));
            return;
        }
        vuoto.hidden = true;
        contenuto.hidden = false;
        const box = this.el('presenze-griglia');
        const posto = tieniPosto ? { x: box.scrollLeft, y: box.scrollTop, attiva: this.attiva } : null;
        const { anno, mese } = this.meseScelto();
        const seq = ++this.seqCaricamento;
        if (!tieniPosto) box.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
        let dati;
        try {
            dati = await apiCall(`/api/napoli/lotti/${lotto.id}/presenze?anno=${anno}&mese=${mese}`);
        } catch (e) {
            if (seq !== this.seqCaricamento) return;
            box.innerHTML = `<div class="alert alert-danger napoli-esito-elenco">${escapeHtml(napoliTestoErrore(e, 'Presenze non disponibili'))}</div>`;
            return;
        }
        if (seq !== this.seqCaricamento) return;          // risposta superata (altro mese o lotto)
        this.dati = dati;
        this.righe = new Map(dati.righe.map(r => [r.id, r]));
        this.attese = new Map();
        this.errori = new Map();
        this.azzeraErrore();
        this.domande = [];
        this.attiva = null;
        this.disegnaFiltri();
        this.disegnaTesta();
        this.disegnaGriglia();
        this.filtra();
        this.mostraStato();
        this.mostraCasella();
        this.misura();
        if (posto) {
            box.scrollLeft = posto.x;
            box.scrollTop = posto.y;
            if (posto.attiva) this.input(posto.attiva.id, posto.attiva.i)?.focus({ preventScroll: true });
        }
    },

    /** La griglia occupa lo spazio che resta sotto (scorre solo lei, non la pagina): se sotto la
     *  scheda il margine della pagina la fa ancora scorrere di qualche pixel, la griglia cala di
     *  quei pixel (mai sotto le 260 di altezza). */
    misura() {
        const box = this.el('presenze-griglia');
        if (!box || box.offsetParent === null) return;
        const piede = document.querySelector('.napoli-presenze-piede');
        const alto = box.getBoundingClientRect().top + window.scrollY;
        const resta = Math.max(260, Math.floor(window.innerHeight - alto - (piede ? piede.offsetHeight : 0) - 28));
        box.style.maxHeight = `${resta}px`;
        const troppo = document.documentElement.scrollHeight - window.innerHeight;
        if (troppo > 0 && box.offsetHeight >= resta) box.style.maxHeight = `${Math.max(260, resta - troppo)}px`;
    },

    disegnaTesta() {
        const d = this.dati;
        const n = d.righe.length;
        this.el('presenze-conta').textContent = n === 1 ? '1 coppia' : `${n} coppie`;
        const chiuso = this.el('presenze-chiuso');
        chiuso.hidden = !d.chiuso;
        if (d.chiuso) {
            // una riga sola (a 1366x768 la griglia ha bisogno di altezza): per riaprire c'e' il pulsante in alto
            const nota = d.chiusura.nota ? ` Nota: ${escapeHtml(d.chiusura.nota)}.` : '';
            chiuso.innerHTML = `${napoliSvg('M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z', 16)}
                <span><strong>${escapeHtml(d.testo)} è chiuso</strong> dal ${escapeHtml(formatDataIT(d.chiusura.data))}: le ore non si cambiano più. Per correggere usa «Riapri il mese» qui sopra e scrivi il motivo.${nota}</span>`;
            chiuso.title = `${d.testo} è chiuso dal ${formatDataIT(d.chiusura.data)}.${d.chiusura.nota ? ` Nota: ${d.chiusura.nota}.` : ''}`;
        }
        const b = this.el('btn-mese');
        b.hidden = false;
        b.disabled = !d.chiuso && !d.finito;
        b.textContent = d.chiuso ? 'Riapri il mese' : 'Chiudi il mese';
        b.title = d.chiuso ? 'Riapre il mese scrivendo il motivo, che resta nel registro attività'
            : (d.finito ? 'Blocca le ore del mese del lotto' : 'Il mese si chiude dall\'ultimo giorno, quando tutte le ore sono scritte');
        // a mese chiuso le note non si scrivono: il pulsante non serve (e lascia posto alla testata)
        this.el('btn-nota-giorno').hidden = d.chiuso;
    },

    disegnaFiltri() {
        const f = this.dati.filtri;
        const opzioni = (id, voci, tutte) => {
            const sel = this.el(id);
            const prima = sel.value;
            sel.innerHTML = `<option value="">${tutte}</option>` + voci.map(([v, t]) =>
                `<option value="${escapeHtml(String(v))}">${escapeHtml(t)}</option>`).join('');
            sel.value = voci.some(([v]) => String(v) === prima) ? prima : '';
            this.filtri[sel.dataset.filtro] = sel.value;
        };
        const nomi = {};
        f.scuole.forEach(s => { nomi[s.nome] = (nomi[s.nome] || 0) + 1; });
        opzioni('pf-scuola', f.scuole.map(s => [s.id, nomi[s.nome] > 1 && s.municipalita ? `${s.nome} (Mun. ${s.municipalita})` : s.nome]), 'Tutte le scuole');
        opzioni('pf-operatore', f.operatori.map(o => [o.id, o.nome]), 'Tutti gli operatori');
        opzioni('pf-figura', f.figure.map(x => [x.codice, x.nome]), 'Tutte le figure');
        opzioni('pf-grado', f.gradi.map(g => [g, `Grado ${(NAPOLI_TESTI_GRADO[g] || g).toLowerCase()}`]), 'Tutti i gradi');
        opzioni('pf-municipalita', f.municipalita.map(m => [m, `Municipalità ${m}`]), 'Tutte le municipalità');
    },

    leggiFiltro(el) {
        if (el.id === 'pf-cerca') this.filtri.cerca = el.value;
        else if (el.dataset.filtro) this.filtri[el.dataset.filtro] = el.value;
        else return;
        this.filtra();
    },

    passaFiltri(r, conAvvisi = true) {
        const f = this.filtri;
        if (f.scuola && String(r.scuola_id) !== f.scuola) return false;
        if (f.operatore && String(r.operatore_id) !== f.operatore) return false;
        if (f.figura && r.figura !== f.figura) return false;
        if (f.grado && (r.grado || 'da_decidere') !== f.grado) return false;
        if (f.municipalita && String(r.municipalita) !== f.municipalita) return false;
        if (conAvvisi && f.avvisi && !r.avvisi.length) return false;
        if (f.cerca) {
            const parole = napoliNormalizza(f.cerca).split(/\s+/).filter(Boolean);
            const testo = napoliNormalizza(`${r.alunno} ${r.operatore}`);
            if (!parole.every(p => testo.includes(p))) return false;
        }
        return true;
    },

    filtra() {
        const tbody = this.el('presenze-griglia').querySelector('tbody');
        if (!tbody) return;
        let visibili = 0;
        tbody.querySelectorAll('tr[data-id]').forEach(tr => {
            const ok = this.passaFiltri(this.righe.get(Number(tr.dataset.id)));
            tr.hidden = !ok;
            if (ok) visibili++;
        });
        const vuoto = this.el('presenze-griglia').querySelector('.napoli-griglia-vuota');
        if (vuoto) vuoto.hidden = visibili > 0 || !this.dati.righe.length;
        const conAvvisi = [...this.righe.values()].filter(r => r.avvisi.length && this.passaFiltri(r, false)).length;
        this.el('pf-avvisi-conta').textContent = String(conAvvisi);
        this.el('pf-avvisi').hidden = !conAvvisi && !this.filtri.avvisi;
        this.riepilogo();
    },

    riepilogo() {
        const righe = [...this.righe.values()].filter(r => this.passaFiltri(r));
        const box = this.el('presenze-riepilogo');
        if (!this.dati.righe.length) { box.textContent = ''; return; }
        const ore = righe.reduce((s, r) => s + r.totale, 0);
        const conPreviste = righe.filter(r => r.previste !== null);
        const previste = conPreviste.reduce((s, r) => s + r.previste, 0);
        const cd = conPreviste.reduce((s, r) => s + r.credito_debito, 0);
        const stima = conPreviste.some(r => r.stima);
        const cdClasse = cd >= 0 ? 'text-success' : 'text-danger';      // come in Rendicontazione
        const n = righe.length === this.dati.righe.length ? `${righe.length} ${righe.length === 1 ? 'coppia' : 'coppie'}`
            : `${righe.length} di ${this.dati.righe.length} coppie`;
        box.innerHTML = `<span>${escapeHtml(n)}</span>
            <span>Ore del mese <strong>${napoliOreBrevi(ore)}</strong></span>
            ${conPreviste.length ? `<span>Previste <strong>${stima ? '≈ ' : ''}${napoliOreBrevi(previste)}</strong></span>
            <span>Credito/debito <strong class="${cdClasse}">${stima ? '≈ ' : ''}${napoliOreBrevi(cd)}</strong></span>` : ''}
            ${stima ? '<span class="napoli-stima-pei" title="Per queste righe manca la programmazione settimanale: le ore previste sono le ore PEI della settimana ripartite sui giorni di servizio del mese">≈ = stima dal PEI</span>' : ''}
            ${conPreviste.length && this.dati.avviso_vacanze ? `<span class="napoli-avviso-vacanze" title="${escapeHtml(this.dati.avviso_vacanze)}">${napoliSvg(NAPOLI_ICONE_STATO.avviso, 14)} Vacanze non ancora nel calendario</span>` : ''}`;
    },

    disegnaGriglia() {
        const d = this.dati;
        const box = this.el('presenze-griglia');
        if (!d.righe.length) {
            box.innerHTML = `<div class="napoli-coord-vuoto napoli-griglia-niente">
                ${napoliSvg(NAPOLI_ICONE_STATO.avviso, 20)}
                <span>Nessuna coppia operatore-alunno in servizio a ${escapeHtml(formatMeseIT(`${d.anno}-${String(d.mese).padStart(2, '0')}`))} in questo lotto. Le coppie arrivano dall'anagrafica:</span>
                <a class="btn btn-sm btn-secondary" href="/napoli/import">Carica l'anagrafica</a>
                <a class="btn btn-sm btn-ghost" href="/napoli/anagrafiche#coppie">Vai alle coppie</a></div>`;
            return;
        }
        const testa = d.colonne.map(c => {
            if (c.tipo === 'verifica') {
                return `<th scope="col" class="g-ver" title="VERIFICA della settimana ${c.settimana}: dal ${formatDataIT(c.dal)} al ${formatDataIT(c.al)}">Sett.<br>${c.settimana}</th>`;
            }
            const classi = ['g-g', c.nome === 'sab' ? 'g-sab' : '', c.chiuso ? 'g-chiuso' : '', c.futuro ? 'g-futuro' : ''].filter(Boolean).join(' ');
            const chiuso = c.chiuso ? ` · ${c.festivo ? 'festivo' : 'chiuso'}: ${c.chiuso}` : '';
            const titolo = `${napoliMaiuscola(napoliGiornoLungo(c.data))} ${formatDataIT(c.data)}${chiuso}${c.evento ? ` · ${c.evento}` : ''}`;
            return `<th scope="col" class="${classi}" data-i="${c.i}" title="${escapeHtml(titolo)}"><span>${c.nome}</span>${c.numero}${c.evento ? '<i class="g-evento" aria-hidden="true"></i>' : ''}</th>`;
        }).join('');
        box.innerHTML = `
            <table class="napoli-griglia${d.chiuso ? ' g-mese-chiuso' : ''}" aria-label="Presenze di ${escapeHtml(d.testo)}">
                <thead><tr>
                    <th scope="col" class="g-fissa g-alunno">Alunno</th>
                    <th scope="col" class="g-fissa g-operatore">Operatore</th>
                    <th scope="col" class="g-fissa g-figura">Figura</th>
                    <th scope="col" class="g-fissa g-pei" title="Ore settimanali da PEI (o la quota della coppia)">PEI</th>
                    <th scope="col" class="g-fissa g-sost" title="Sostituzione operatore (SI/NO)">Sost.</th>
                    ${testa}
                    <th scope="col" class="g-tot" title="Totale del mese: ore riconosciute">Totale</th>
                    <th scope="col" class="g-cd" title="Credito/debito: ore previste meno ore riconosciute (positivo = ore ancora dovute all'alunno)">Cred./<br>deb.</th>
                </tr></thead>
                <tbody>${d.righe.map(r => this.htmlRiga(r)).join('')}</tbody>
            </table>
            <p class="napoli-griglia-vuota" hidden>Nessuna riga con questi filtri.</p>`;
    },

    fuori(r) {
        if (!r._fuori) r._fuori = new Set(r.fuori);
        return r._fuori;
    },

    /** I giorni della riga in una fattura definitiva (passo 1.9): bloccati finche' non si riapre. */
    definitiva(r) {
        if (!r._definitiva) r._definitiva = new Set(r.definitiva || []);
        return r._definitiva;
    },

    classeCella(r, col, c) {
        const i = col.i;
        const classi = ['g-c'];
        if (col.chiuso || r.chiusi[i]) classi.push('g-chiuso');
        if (this.fuori(r).has(i)) classi.push('g-fuori');
        if (this.definitiva(r).has(i)) classi.push('g-definitiva');
        if (col.futuro) classi.push('g-futuro');
        if (col.nome === 'sab') classi.push('g-sab');
        if (c) {
            if (c.k === 'A') classi.push('g-assente');
            else if (NAPOLI_SIGLE_OPERATORE[c.k]) classi.push('g-sigla');
            else if (c.k === 'prog') classi.push('g-prog');
            if (c.nt || c.nx) classi.push('g-nota');
            if (c.a) classi.push('g-avviso');
            if (c.bl) classi.push('g-bloccata');
            if (c.c) classi.push('g-con-angolo');
        }
        const chiave = `${r.id}|${i}`;
        if (this.errori.has(chiave)) classi.push('g-errore');
        else if (this.attese.has(chiave)) classi.push('g-cambiata');
        return classi.join(' ');
    },

    bloccata(r, col, c) {
        return this.fuori(r).has(col.i) || col.futuro || !!(c && c.bl) || this.definitiva(r).has(col.i);
    },

    htmlRiga(r) {
        const celle = this.dati.colonne.map(col => {
            if (col.tipo === 'verifica') return this.htmlSettimana(r, col.settimana);
            const c = r.celle[col.i];
            const segnaposto = c && c.k === 'prog' && c.p ? ` placeholder="${napoliTestoCella(c.p)}"` : '';
            return `<td class="${this.classeCella(r, col, c)}" data-i="${col.i}"><input class="g-in" value="${c ? escapeHtml(c.t) : ''}"${segnaposto}${this.bloccata(r, col, c) ? ' disabled' : ''}${this.dati.chiuso ? ' readonly' : ''} maxlength="12" autocomplete="off" spellcheck="false">${c && c.c ? `<span class="g-ang">${escapeHtml(c.c)}</span>` : ''}</td>`;
        }).join('');
        return `<tr data-id="${r.id}" class="${this.classeRiga(r)}">
            <th scope="row" class="g-fissa g-alunno"><button type="button" class="g-nome" title="${escapeHtml(this.titoloNome(r))}">${escapeHtml(r.alunno)}</button></th>
            <td class="g-fissa g-operatore" title="${escapeHtml(r.operatore)}">${escapeHtml(r.operatore)}</td>
            <td class="g-fissa g-figura">${escapeHtml(r.figura_nome)}</td>
            <td class="g-fissa g-pei"${r.quota ? ' title="Quota della coppia"' : ''}>${escapeHtml(r.pei || '—')}</td>
            <td class="g-fissa g-sost">${r.sostituto ? '<strong>SI</strong>' : 'NO'}</td>
            ${celle}
            <td class="g-tot">${escapeHtml(r.totale_testo)}</td>
            ${this.htmlCredito(r)}
        </tr>`;
    },

    /** Il suggerimento sul nome: apre il dettaglio; con gli avvisi della riga, per esteso. */
    titoloNome(r) {
        const avvisi = r.avvisi.map(a => `• ${this.dati.spiegazioni[a] || a}`);
        return `${r.alunno}: apri il dettaglio del mese${avvisi.length ? `\nDa controllare:\n${avvisi.join('\n')}` : ''}`;
    },

    classeRiga(r) {
        return [r.sostituto ? 'g-riga-sost' : '', r.avvisi.length ? 'g-riga-avvisi' : ''].filter(Boolean).join(' ');
    },

    htmlSettimana(r, n) {
        const s = (r.settimane || []).find(x => x.n === n);
        if (!s) return '<td class="g-ver"></td>';
        const dove = s.colore === 'rosso' ? ' g-rosso' : (s.colore === 'giallo' ? ' g-giallo' : '');
        return `<td class="g-ver${dove}" data-s="${n}">${s.minuti ? escapeHtml(s.testo) : ''}</td>`;
    },

    htmlCredito(r) {
        if (r.cd_nel_titolare) return '<td class="g-cd g-cd-titolare" title="Le ore del sostituto contano nel credito/debito della riga del titolare">↑</td>';
        if (r.credito_debito === null) return '<td class="g-cd" title="Manca il PEI: il credito/debito non si calcola">—</td>';
        const classe = r.credito_debito >= 0 ? 'text-success' : 'text-danger';
        let titolo = r.stima ? 'Stima dal PEI (manca la programmazione settimanale)' : 'Dalla programmazione settimanale';
        // previste dal PEI intero su piu' titolari: il credito/debito va controllato
        const dubbio = r.avvisi.includes('pei_su_piu_titolari') ? ' g-cd-dubbio' : '';
        if (dubbio) titolo += `. Attenzione: ${this.dati.spiegazioni.pei_su_piu_titolari}`;
        return `<td class="g-cd ${classe}${dubbio}" title="${escapeHtml(titolo)}">${r.stima ? '≈ ' : ''}${escapeHtml(r.cd_testo)}</td>`;
    },

    tr(id) { return this.el('presenze-griglia').querySelector(`tr[data-id="${id}"]`); },

    input(id, i) { return this.tr(id)?.querySelector(`td[data-i="${i}"] .g-in`) || null; },

    colonna(i) {
        if (!this.dati._perIndice) this.dati._perIndice = new Map(this.dati.colonne.filter(c => c.tipo === 'giorno').map(c => [c.i, c]));
        return this.dati._perIndice.get(i);
    },

    /** Una riga ricalcolata dal server: caselle, VERIFICA, totale e credito/debito, senza
     *  ridisegnare la tabella (la casella attiva e quelle in sospeso restano come sono). */
    aggiornaRiga(r) {
        this.righe.set(r.id, r);
        const k = this.dati.righe.findIndex(x => x.id === r.id);
        if (k >= 0) this.dati.righe[k] = r;
        const tr = this.tr(r.id);
        if (!tr) return;
        tr.className = this.classeRiga(r);
        const nome = tr.querySelector('.g-nome');
        if (nome) nome.title = this.titoloNome(r);
        tr.querySelectorAll('td.g-c').forEach(td => this.aggiornaCella(r, td));
        tr.querySelectorAll('td.g-ver[data-s]').forEach(td => {
            const nuovo = document.createElement('tbody');
            nuovo.innerHTML = `<tr>${this.htmlSettimana(r, Number(td.dataset.s))}</tr>`;
            td.replaceWith(nuovo.querySelector('td'));
        });
        tr.querySelector('.g-tot').textContent = r.totale_testo;
        const cd = document.createElement('tbody');
        cd.innerHTML = `<tr>${this.htmlCredito(r)}</tr>`;
        tr.querySelector('.g-cd').replaceWith(cd.querySelector('td'));
    },

    aggiornaCella(r, td) {
        const i = Number(td.dataset.i);
        const col = this.colonna(i);
        const c = r.celle[i];
        const chiave = `${r.id}|${i}`;
        td.className = this.classeCella(r, col, c);
        const input = td.querySelector('.g-in');
        if (!this.attese.has(chiave) && !this.errori.has(chiave)) {
            const testo = c ? c.t : '';
            if (input.value !== testo) input.value = testo;
        }
        input.placeholder = c && c.k === 'prog' && c.p ? napoliTestoCella(c.p) : '';
        input.disabled = this.bloccata(r, col, c);
        let angolo = td.querySelector('.g-ang');
        if (c && c.c) {
            if (!angolo) { angolo = document.createElement('span'); angolo.className = 'g-ang'; td.appendChild(angolo); }
            angolo.textContent = c.c;
        } else if (angolo) {
            angolo.remove();
        }
    },

    // ---------- la casella scelta ----------

    posizione(input) {
        const td = input.closest('td');
        return { id: Number(td.parentElement.dataset.id), i: Number(td.dataset.i) };
    },

    scelta(input) {
        const { id, i } = this.posizione(input);
        this.attiva = { id, i };
        const r = this.righe.get(id);
        const col = this.colonna(i);
        input.setAttribute('aria-label', `${napoliGiornoLungo(col.data)} ${formatDataIT(col.data)}, ${r.alunno} con ${r.operatore}`);
        input.setAttribute('aria-describedby', 'presenze-casella');
        // subito, come in Rendicontazione: una selezione rimandata (setTimeout) arriverebbe dopo i
        // tasti gia' in coda e ne sostituirebbe il primo ("1,5" diventerebbe "5"). Tab e frecce
        // scelgono gia' tutto, il clic lo sceglie al rilascio del tasto (mouseup)
        input.select();
        this.mostraCasella();
    },

    /** La barra sopra la griglia: la casella scelta per esteso. */
    mostraCasella() {
        const barra = this.el('presenze-casella');
        if (!this.attiva) {
            barra.innerHTML = this.dati && this.dati.chiuso
                ? '<span class="napoli-barra-invito">Scegli una casella per vederla qui per esteso (il mese è chiuso: solo lettura).</span>'
                : '<span class="napoli-barra-invito">Scegli una casella per vederla qui per esteso. Scrivi le ore svolte (2, 1,5 o 1:30) oppure F, M, P, A; si salva da solo.</span>';
            return;
        }
        const { id, i } = this.attiva;
        const r = this.righe.get(id);
        const col = this.colonna(i);
        if (!r || !col) { barra.textContent = ''; return; }
        const c = r.celle[i];
        const chiave = `${id}|${i}`;
        const giorno = `${napoliMaiuscola(napoliGiornoLungo(col.data))} ${formatDataIT(col.data)}`;
        const parti = [];
        if (this.errori.has(chiave)) parti.push(`<span class="g-barra-errore">${escapeHtml(this.errori.get(chiave))}</span>`);
        else if (this.attese.has(chiave)) parti.push('Da salvare…');
        else if (this.fuori(r).has(i)) parti.push(`Fuori dalle date della coppia (${escapeHtml(napoliPeriodo(r.dal, r.al))})`);
        else if (col.futuro) parti.push('Giorno non ancora arrivato');
        else if (!c) parti.push('Nessuna ora scritta');
        else if (c.k === 'prog') parti.push(`Preparato, non registrato: vale 0${c.p ? ` (programmate ${napoliOreDueForme(c.p)})` : ''}`);
        else if (c.k === 'A') {
            parti.push(c.rec ? 'Alunno assente, assenza recuperata: niente metà'
                : `Alunno assente: metà${c.p ? ` delle ${napoliHhmm(c.p)} programmate` : ''} = <strong>${napoliOreDueForme(c.r)}</strong>`);
        } else if (NAPOLI_SIGLE_OPERATORE[c.k]) parti.push(`${NAPOLI_SIGLE_OPERATORE[c.k]}: 0 ore`);
        else {
            parti.push(`Ore riconosciute <strong>${napoliOreDueForme(c.r)}</strong>`);
            if (c.o === 'import') parti.push('dal file Excel');
        }
        if (c && c.bl) parti.push('registrato dal foglio firma: si cambia dal foglio della coppia');
        if (this.definitiva(r).has(i)) parti.push('nella fattura definitiva: per cambiare le ore riapri la fattura nella scheda Fattura');
        if (c && c.nt) parti.push(`Nota: ${escapeHtml(NAPOLI_NOTE_GIORNO[c.nt])}${c.no ? ` ${escapeHtml(c.no)}` : ''}${c.rec && c.nt !== 'evento' ? ', recuperata' : ''}`);
        if (c && c.nx) parti.push(`«${escapeHtml(c.nx)}»`);
        const chiuso = col.chiuso || r.chiusi[i];
        if (chiuso) parti.push(`${col.chiuso && col.festivo ? 'Festivo' : 'Chiuso'}: ${escapeHtml(chiuso)}`);
        if (col.evento) parti.push(escapeHtml(col.evento));
        if (c && c.a) parti.push(...c.a.map(a => `<span class="g-barra-avviso">${napoliSvg(NAPOLI_ICONE_STATO.avviso, 14)} ${escapeHtml(this.dati.spiegazioni[a] || a)}</span>`));
        barra.innerHTML = `<strong>${escapeHtml(giorno)}</strong> · ${escapeHtml(r.alunno)} con ${escapeHtml(r.operatore)} (${escapeHtml(r.figura_nome)}) · ${parti.join(' · ')}`;
    },

    // ---------- tastiera ----------

    tasti(e) {
        const input = e.target;
        const { id, i } = this.posizione(input);
        const chiave = `${id}|${i}`;
        if (e.key === 'F2' && e.shiftKey) {
            e.preventDefault();
            this.apriNota(id, i);
            return;
        }
        if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z') {
            // mentre si scrive, Ctrl+Z toglie le lettere; a casella salvata annulla l'ultima modifica di Napoli
            if (!this.attese.has(chiave)) { e.preventDefault(); NapoliComune.annulla(); }
            return;
        }
        if (e.key === 'Escape' && (this.attese.has(chiave) || this.errori.has(chiave))) {
            e.preventDefault();
            this.attese.delete(chiave);
            this.errori.delete(chiave);
            if (!this.attese.size) { clearTimeout(this.timer); this.timer = null; this.azzeraErrore(); }
            this.aggiornaCella(this.righe.get(id), input.closest('td'));
            input.select();
            this.mostraCasella();
            this.mostraStato();
            return;
        }
        let dx = 0, dy = 0;
        if (e.key === 'Enter') dy = e.shiftKey ? -1 : 1;
        else if (e.key === 'ArrowDown') dy = 1;
        else if (e.key === 'ArrowUp') dy = -1;
        else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
            const tutto = input.selectionStart === 0 && input.selectionEnd === input.value.length;
            const inFondo = input.selectionStart === input.value.length && input.selectionEnd === input.value.length;
            const inCima = input.selectionStart === 0 && input.selectionEnd === 0;
            if (e.key === 'ArrowRight' && (tutto || inFondo)) dx = 1;
            else if (e.key === 'ArrowLeft' && (tutto || inCima)) dx = -1;
            else return;
        } else return;
        e.preventDefault();
        const prossima = this.vicina(input, dx, dy);
        if (prossima) { prossima.focus(); prossima.select(); }
        else if (e.key === 'Enter') input.blur();          // ultima riga: si chiude la casella (si salva dopo 2 s)
    },

    vicina(input, dx, dy) {
        const td = input.closest('td');
        if (dx) {
            let altra = td;
            do {
                altra = dx > 0 ? altra.nextElementSibling : altra.previousElementSibling;
            } while (altra && !(altra.matches('td.g-c') && !altra.querySelector('.g-in').disabled));
            return altra ? altra.querySelector('.g-in') : null;
        }
        const i = td.dataset.i;
        let tr = td.parentElement;
        do {
            tr = dy > 0 ? tr.nextElementSibling : tr.previousElementSibling;
            const altra = tr && !tr.hidden ? tr.querySelector(`td[data-i="${i}"] .g-in`) : null;
            if (altra && !altra.disabled) return altra;
        } while (tr);
        return null;
    },

    /** Incolla da Excel: righe e colonne a partire dalla casella (le caselle bloccate si saltano). */
    incolla(e) {
        const testo = (e.clipboardData || window.clipboardData)?.getData('text') || '';
        const righe = testo.replace(/\r/g, '').split('\n').map(r => r.split('\t'));
        while (righe.length && righe[righe.length - 1].every(v => v.trim() === '')) righe.pop();
        if (!righe.length || (righe.length === 1 && righe[0].length === 1)) return;   // un solo valore: incolla normale
        e.preventDefault();
        if (this.dati.chiuso) { showToast('Il mese è chiuso: non si incolla.', 'warning'); return; }
        const inizio = e.target.closest('td');
        let tr = inizio.parentElement;
        const colonne = [...tr.querySelectorAll('td.g-c')];
        const primo = colonne.indexOf(inizio);
        let n = 0, saltati = 0;
        for (const valori of righe) {
            while (tr && tr.hidden) tr = tr.nextElementSibling;
            if (!tr) break;
            const caselle = [...tr.querySelectorAll('td.g-c')];
            valori.forEach((v, k) => {
                const td = caselle[primo + k];
                if (!td) return;
                const input = td.querySelector('.g-in');
                if (input.disabled) { saltati++; return; }
                input.value = v.trim();
                this.modificata(input);
                n++;
            });
            tr = tr.nextElementSibling;
        }
        showToast(`${n === 1 ? 'Incollato 1 valore' : `Incollati ${n} valori`}${saltati ? `; ${saltati} nei giorni bloccati non incollati` : ''}`, 'info');
    },

    // ---------- salvataggio automatico ----------

    modificata(input) {
        if (this.dati.chiuso) return;
        const { id, i } = this.posizione(input);
        const chiave = `${id}|${i}`;
        this.attese.set(chiave, { coppia_id: id, data: this.dati.giorni[i], testo: input.value.trim() });
        this.errori.delete(chiave);
        const td = input.closest('td');
        td.classList.add('g-cambiata');
        td.classList.remove('g-errore');
        this.programma();
        this.mostraStato('in_sospeso');
        if (this.attiva && this.attiva.id === id && this.attiva.i === i) this.mostraCasella();
    },

    /** Il salvataggio parte 2 secondi dopo l'ultimo tasto (o subito, con attesa 0). */
    programma(attesa = NAPOLI_PRESENZE_ATTESA) {
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.salva(), attesa);
    },

    /** I gruppi da mandare: al massimo NAPOLI_PRESENZE_GRUPPO caselle e, se indicato, al massimo
     *  quei byte per richiesta (l'uscita dalla pagina). */
    gruppi(voci, maxByte = Infinity) {
        const out = [];
        let gruppo = [], byte = 0;
        for (const voce of voci) {
            const peso = JSON.stringify(voce[1]).length + 1;
            if (gruppo.length && (gruppo.length >= NAPOLI_PRESENZE_GRUPPO || byte + peso > maxByte)) {
                out.push(gruppo);
                gruppo = [];
                byte = 0;
            }
            gruppo.push(voce);
            byte += peso;
        }
        if (gruppo.length) out.push(gruppo);
        return out;
    },

    async salva() {
        clearTimeout(this.timer);
        this.timer = null;
        clearTimeout(this.riprova);
        this.riprova = null;
        if (this.inVolo) { this.ancora = true; return this.inVolo; }
        if (!this.attese.size || !this.dati) { this.azzeraErrore(); this.mostraStato(); return; }
        this.ancora = false;
        const d = this.dati;
        const lotto = d.lotto.id;
        // le caselle in sospeso adesso partono a gruppi, una richiesta dopo l'altra; quelle scritte
        // nel frattempo aspettano i loro 2 secondi (poi partono con il giro dopo)
        const gruppi = this.gruppi([...this.attese]).map(g => g.map(([chiave]) => chiave));
        this.mostraStato('salvo');
        this.inVolo = (async () => {
            try {
                for (const chiavi of gruppi) {
                    if (this.dati !== d) break;
                    const inviate = new Map();
                    chiavi.forEach((k) => { if (this.attese.has(k)) { inviate.set(k, this.attese.get(k)); this.attese.delete(k); } });
                    if (!inviate.size) continue;
                    try {
                        const r = await apiCall(`/api/napoli/lotti/${lotto}/presenze`, {
                            method: 'POST', body: JSON.stringify({ anno: d.anno, mese: d.mese, celle: [...inviate.values()] }),
                        });
                        if (this.dati === d) this.applica(r, inviate);
                    } catch (e) {
                        // non salvate: tornano in sospeso (se nel frattempo non sono state riscritte)
                        inviate.forEach((v, k) => { if (!this.attese.has(k)) this.attese.set(k, v); });
                        throw e;
                    }
                }
            } catch (e) {
                if (e.code === 'FATTURA_DEFINITIVA') st.riga.definitiva = st.riga.definitiva || 'definitiva';
                if (e.code === 'MESE_CHIUSO_LOTTO') {
                    showToast(e.message, 'warning', 10000);
                    this.attese = new Map();
                    this.azzeraErrore();
                    await this.carica(true);
                } else if (this.dati === d) {
                    this.nonRiuscito(e);
                }
            } finally {
                this.inVolo = null;
            }
            if (this.ancora && this.attese.size && !this.timer && !this.erroreSalvataggio) await this.salva();
            this.mostraStato();
        })();
        return this.inVolo;
    },

    /** Salvataggio non riuscito: le caselle restano in sospeso, lo stato dice "Modifiche non
     *  salvate" con il pulsante per riprovare (come in Rendicontazione); se il collegamento o il
     *  programma non rispondono, il programma riprova da solo dopo qualche secondo. */
    nonRiuscito(e) {
        const rete = !e.status;
        const ritenta = rete || e.status >= 500;
        let messaggio;
        if (rete) messaggio = 'Il collegamento con Assisto si è interrotto: le ore scritte non sono ancora salvate.';
        else if (e.status === 401) messaggio = 'La sessione è scaduta: entra di nuovo nel programma da un\'altra scheda, poi premi «Riprova» in alto.';
        else if (e.status >= 500 && e.code !== 'DATABASE_OCCUPATO') messaggio = 'Il programma non è riuscito a salvare: le ore scritte non sono ancora salvate.';
        else messaggio = e.message || 'Il salvataggio non è riuscito.';
        const nuovo = this.erroreSalvataggio !== messaggio;
        this.erroreSalvataggio = messaggio;
        this.tentativi += 1;
        if (ritenta) {
            const attesa = NAPOLI_PRESENZE_RIPROVA[Math.min(this.tentativi, NAPOLI_PRESENZE_RIPROVA.length) - 1];
            clearTimeout(this.riprova);
            this.riprova = setTimeout(() => { this.riprova = null; this.salva(); }, attesa);
        }
        // un solo avviso per lo stesso problema (i tentativi da soli non ne aggiungono altri)
        if (nuovo) {
            showToast(`Modifiche non salvate. ${messaggio}${ritenta ? ' Riprovo da solo fra qualche secondo; puoi anche premere «Riprova» in alto. Non chiudere la pagina.' : ''}`, 'error', 12000);
        }
    },

    azzeraErrore() {
        this.erroreSalvataggio = null;
        this.tentativi = 0;
        clearTimeout(this.riprova);
        this.riprova = null;
    },

    /** "Riprova a salvare" e Ctrl+S: le caselle in sospeso partono subito. */
    salvaSubito() {
        if (!this.dati || this.dati.chiuso) return;
        if (!this.attese.size && !this.inVolo) {
            this.mostraStato();
            if (!this.errori.size) showToast('Nessuna modifica da salvare', 'info');
            return;
        }
        this.salva();
    },

    applica(r, inviate) {
        this.azzeraErrore();
        let toltaNota = false, toltaDescrizione = false;
        const tolte = [];                                // parti della nota tolte scrivendo nella casella
        for (const e of r.celle) {
            const i = this.dati.giorni.indexOf(e.data);
            const chiave = `${e.coppia_id}|${i}`;
            const mandata = inviate.get(chiave);
            if (this.attese.has(chiave)) continue;         // riscritta mentre si salvava: riparte
            if (e.esito === 'errore') {
                this.errori.set(chiave, e.messaggio);
            } else if (e.esito === 'da_confermare') {
                if (this.letturaScelta && e.alternative.some(a => a.lettura === this.letturaScelta)) {
                    this.attese.set(chiave, { ...mandata, conferma: this.letturaScelta });
                } else {
                    this.errori.set(chiave, `«${e.testo}» si può leggere in due modi: da confermare`);
                    this.domande.push({ tipo: 'lettura', chiave, cella: mandata, esito: e });
                }
            } else if (e.esito === 'servono_programmati') {
                this.errori.set(chiave, 'Mancano le ore programmate di quel giorno');
                this.domande.push({ tipo: 'programmati', chiave, cella: mandata, esito: e });
            } else {
                this.errori.delete(chiave);
                if (e.tolta_nota) toltaNota = true;
                if (e.tolta_descrizione) toltaDescrizione = true;
                if (e.tolte) tolte.push(...e.tolte.map(t => `${formatDataIT(e.data).slice(0, 5)}, ${this.righe.get(e.coppia_id)?.alunno || ''}: ${t}`));
            }
        }
        r.righe.forEach(riga => this.aggiornaRiga(riga));
        // le caselle non toccate dal ricalcolo (errori, domande) prendono la classe giusta
        inviate.forEach((v, chiave) => {
            const [id, i] = chiave.split('|').map(Number);
            const td = this.input(id, i)?.closest('td');
            if (td) this.aggiornaCella(this.righe.get(id), td);
        });
        this.ultimoSalvataggio = new Date();             // anche senza cambiamenti: niente resta da salvare
        if (toltaDescrizione) showToast('Cancellato un giorno con la nota del giorno: con Ctrl+Z torna il giorno con la nota, ma non la descrizione scritta.', 'info', 8000);
        else if (toltaNota) showToast('Cancellato un giorno con la nota del giorno: con Ctrl+Z torna com\'era.', 'info', 8000);
        // la parte della nota che non valeva piu' con il nuovo valore (ritardo con "A", recuperata
        // con le ore svolte): tolta da sola, la pagina lo dice
        if (tolte.length) {
            const altre = tolte.length > 2 ? ` (e altre ${tolte.length - 2})` : '';
            showToast(`${tolte.slice(0, 2).join(' · ').replace(/\.$/, '')}${altre}. Con Ctrl+Z torna com'era.`, 'info', 10000);
        }
        // lettura scelta per i valori come "1,30": le caselle ripartono subito con la scelta
        if (this.attese.size && !this.timer) this.programma(300);
        this.mostraCasella();
        this.riepilogo();
        this.prossimaDomanda();
    },

    /** Le caselle cambiate e non ancora salvate partono adesso (Ctrl+Z, cambio di mese o lotto,
     *  chiusura del mese). Ritorna false se qualcuna non si e' salvata (rete, programma). */
    async salvaInSospeso() {
        if (this.inVolo) await this.inVolo;
        if (this.attese.size) await this.salva();
        return !this.attese.size;
    },

    /** Prima di cambiare mese o lotto, di annullare o di chiudere il mese: con caselle non
     *  salvate si resta qui; con caselle da correggere (in rosso: non si sono salvate) si chiede
     *  se lasciarle, perche' ricaricando la griglia si perdono. */
    async puoLasciare(messaggio = 'Modifiche non salvate: resto sul mese mostrato. Riprova il salvataggio.',
        azione = 'cambi mese o lotto') {
        if (!(await this.salvaInSospeso())) {
            showToast(messaggio, 'error', 9000);
            return false;
        }
        return this.lasciaDaCorreggere(azione);
    },

    /** Le caselle da correggere (sigla sconosciuta, «A» senza le ore programmate, «1,30» da
     *  chiarire) non sono salvate: prima di perderle si chiede. true = si puo' andare avanti. */
    lasciaDaCorreggere(azione) {
        const n = this.errori.size;
        if (!n || !this.dati || this.dati.chiuso) return Promise.resolve(true);
        const caselle = n === 1 ? '1 casella da correggere non è salvata' : `${n} caselle da correggere non sono salvate`;
        return new Promise((risolvi) => {
            let fatto = false;
            const fine = (avanti) => {
                if (fatto) return;
                fatto = true;
                // si resta: il cursore va sulla prima casella da correggere (a finestra chiusa)
                if (!avanti) setTimeout(() => this.vaiAllaPrimaDaCorreggere(), 320);
                risolvi(avanti);
            };
            // la scelta sicura e' quella di Invio (il pulsante principale): restare
            showConfirmDialog('Caselle da correggere',
                `${caselle} (in rosso): se ${azione}, quello che c'è scritto si perde.`,
                () => fine(false), { type: 'warning', confirmText: 'Resta e correggi', cancelText: 'Continua senza salvarle' });
            document.getElementById('confirm-dialog-cancel')?.addEventListener('click', () => fine(true));
            // Esc o un clic fuori dalla finestra: si resta
            const finestra = document.getElementById('confirm-dialog-overlay');
            if (!finestra || typeof MutationObserver !== 'function') return;
            const osserva = new MutationObserver(() => {
                if (finestra.isConnected) return;
                osserva.disconnect();
                fine(false);
            });
            osserva.observe(document.body, { childList: true });
        });
    },

    vaiAllaPrimaDaCorreggere() {
        for (const chiave of this.errori.keys()) {
            const [id, i] = chiave.split('|').map(Number);
            const input = this.input(id, i);
            if (input && !input.closest('tr').hidden) { input.focus(); input.select(); return; }
        }
    },

    /** Pagina chiusa entro i 2 secondi: fetch keepalive, che il browser porta a termine lo stesso
     *  (al massimo 64 KB: quello che non ci sta resta in sospeso, e il browser ha gia' chiesto
     *  se lasciare la pagina, vedi nonPartono). */
    inviaInUscita() {
        if (!this.dati || !this.attese.size) return;
        clearTimeout(this.timer);
        this.timer = null;
        const d = this.dati;
        const primo = this.gruppi([...this.attese], NAPOLI_PRESENZE_USCITA_BYTE)[0];
        const inviate = new Map(primo);
        inviate.forEach((v, k) => this.attese.delete(k));
        // non partite (o non arrivate): tornano in sospeso e ripartono se la pagina resta aperta
        const rimetti = () => {
            inviate.forEach((v, k) => { if (!this.attese.has(k)) this.attese.set(k, v); });
            this.ripartiDopo(d);
        };
        let invio;
        try {
            invio = fetch(`/api/napoli/lotti/${d.lotto.id}/presenze`, {
                method: 'POST', keepalive: true, credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ anno: d.anno, mese: d.mese, celle: [...inviate.values()] }),
            });
        } catch (e) {
            rimetti();
            return;
        }
        invio.then(r => (r.ok ? r.json() : null)).then((r) => {
            // scheda solo nascosta (la pagina e' ancora aperta): le righe tornano aggiornate
            if (r && this.dati === d) {
                this.applica(r, inviate);
                this.ripartiDopo(d);
                this.mostraStato();
            } else if (!r) rimetti();
        }).catch(rimetti);
        // il resto (oltre i 64 KB) riparte da solo se la pagina resta aperta
        this.ripartiDopo(d);
    },

    ripartiDopo(d) {
        if (this.dati !== d || !this.attese.size) return;
        if (this.inVolo) this.ancora = true;
        else if (!this.timer) this.programma();
    },

    /** Caselle che uscendo adesso andrebbero perse: quelle da correggere (non salvate), oppure il
     *  salvataggio non riesce, oppure sono troppe per partire all'uscita (oltre i 64 KB di fetch
     *  keepalive). */
    nonPartono() {
        if (!this.dati || this.dati.chiuso) return false;
        if (this.errori.size) return true;              // caselle da correggere: non si sono salvate
        if (!this.attese.size) return false;
        if (this.erroreSalvataggio) return true;
        return this.gruppi([...this.attese], NAPOLI_PRESENZE_USCITA_BYTE).length > 1;
    },

    mostraStato(tipo) {
        const box = this.el('presenze-salvataggio');
        const riprova = this.el('btn-presenze-riprova');
        // largo: l'inizio della scritta che si legge solo sugli schermi larghi (a 1366 la testata
        // resta su una riga); per esteso nel suggerimento
        const testo = (stato, icona, scritta, titolo = '', largo = '') => {
            box.className = ['auto-save-indicator', stato].filter(Boolean).join(' ');
            box.innerHTML = `${icona === 'gira' ? '<div class="spinner-small"></div>' : (icona ? napoliSvg(icona, 14) : '')}<span>${largo ? `<span class="napoli-solo-largo">${escapeHtml(largo)}</span>` : ''}${escapeHtml(scritta)}</span>`;
            box.title = titolo || (largo ? largo + scritta : '');
            // come in Rendicontazione: il pulsante per riprovare c'e' solo se il salvataggio non e' riuscito
            if (riprova) riprova.hidden = stato !== 'errore' || !this.attese.size;
            // con «Riprova» la testata sta su una riga a 1366 senza «N coppie» (che si legge anche
            // nel riepilogo sotto la griglia)
            this.el('presenze-conta')?.classList.toggle('napoli-solo-largo', !!riprova && !riprova.hidden);
        };
        if (tipo === 'in_sospeso') return testo('pending', '', 'Modifiche in sospeso…');
        if (tipo === 'salvo' || this.inVolo) return testo('saving', 'gira', 'Salvataggio…');
        if (this.erroreSalvataggio && this.attese.size) {
            return testo('errore', NAPOLI_COORD_ICONA_ERRORE, 'Modifiche non salvate', this.erroreSalvataggio);
        }
        if (this.timer || this.attese.size) return testo('pending', '', 'Modifiche in sospeso…');
        const ora = this.ultimoSalvataggio
            ? this.ultimoSalvataggio.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' }) : null;
        const errori = this.errori.size;
        if (errori) {
            const caselle = errori === 1 ? '1 casella da correggere' : `${errori} caselle da correggere`;
            return testo('errore', NAPOLI_COORD_ICONA_ERRORE, caselle, '', ora ? `Salvato alle ${ora}, tranne ` : '');
        }
        if (this.dati && this.dati.chiuso) return testo('', NAPOLI_ICONE_STATO.ok, 'Mese chiuso: solo lettura');
        if (ora) return testo('saved', NAPOLI_COORD_ICONA_OK, `Salvato alle ${ora}`);
        return testo('', NAPOLI_COORD_ICONA_OK, 'Salvataggio automatico');
    },

    // ---------- domande sulle caselle: "1,30" e ore programmate ----------

    chiDove(cella) {
        const r = this.righe.get(cella.coppia_id);
        return `${napoliGiornoLungo(cella.data)} ${formatDataIT(cella.data)}, ${r ? `${r.alunno} con ${r.operatore}` : ''}`;
    },

    prossimaDomanda() {
        const overlay = this.el('napoli-modal-domanda');
        if (this.domanda && !overlay.classList.contains('active')) this.domanda = null;   // chiusa da fuori
        if (this.domanda || !this.domande.length) return;
        if (document.querySelector('.modal-overlay.active')) return;     // un'altra finestra aperta: dopo
        const q = this.domande.shift();
        if (!this.errori.has(q.chiave) || this.attese.has(q.chiave)) { this.prossimaDomanda(); return; }
        this.domanda = q;
        const form = this.el('form-domanda');
        const pulsanti = this.el('domanda-pulsanti');
        if (q.tipo === 'lettura') {
            this.el('domanda-titolo').textContent = 'Come va letto?';
            form.innerHTML = `<p>Hai scritto <strong>«${escapeHtml(q.esito.testo)}»</strong> per ${escapeHtml(this.chiDove(q.cella))}.</p>
                <p class="napoli-intro">Nel file del Comune le ore si scrivono con la virgola (1,5 = un'ora e mezza), ma sui fogli firma «1,30» vuol dire spesso un'ora e trenta minuti. Scegli tu:</p>
                <label class="napoli-scelta-riga"><input type="checkbox" id="domanda-sempre"> Leggi così anche le prossime caselle scritte in questo modo (fino a quando ricarichi la pagina)</label>`;
            pulsanti.innerHTML = `<button type="button" class="btn btn-secondary" data-risposta="lascia">Correggi la casella</button>
                ${q.esito.alternative.map(a => `<button type="button" class="btn btn-primary" data-risposta="${escapeHtml(a.lettura)}">${escapeHtml(a.testo)}</button>`).join('')}`;
        } else {
            this.el('domanda-titolo').textContent = 'Ore programmate del giorno';
            const r = this.righe.get(q.cella.coppia_id);
            form.innerHTML = `<p>Per ${escapeHtml(this.chiDove(q.cella))} si conta la metà delle ore programmate, ma il programma non le conosce (manca la programmazione settimanale).</p>
                <div class="form-group napoli-campo-medio">
                    <label class="form-label" for="domanda-programmati">Quante ore erano programmate quel giorno?</label>
                    <input type="text" class="form-control" id="domanda-programmati" data-campo="programmati" inputmode="decimal" autocomplete="off" placeholder="per esempio 3 oppure 2,5">
                    <p class="napoli-aiuto">${r && r.pei ? `Ore PEI della settimana: ${escapeHtml(r.pei)}.` : ''} Si scrivono come nelle caselle: 3, 2,5 oppure 1:30.</p>
                </div>`;
            pulsanti.innerHTML = `<button type="button" class="btn btn-secondary" data-risposta="lascia">Lascia la casella da sistemare</button>
                <button type="submit" form="form-domanda" class="btn btn-primary">Salva</button>`;
        }
        this.domandaDal = Date.now();
        openModal('napoli-modal-domanda');
        // da tastiera si risponde subito: il fuoco va sul campo delle ore programmate o sulla
        // prima lettura proposta, non sulla X di chiusura
        const primo = q.tipo === 'lettura' ? pulsanti.querySelector('button[data-risposta]:not([data-risposta="lascia"])')
            : this.el('domanda-programmati');
        if (!primo) return;
        focusInFinestra(primo);
        // openModal mette il fuoco sulla X e, se in quell'istante non e' ancora visibile, ci riprova
        // fino a 120 ms dopo: passato quel tempo il fuoco torna qui (se nessuno l'ha spostato)
        setTimeout(() => {
            if (this.domanda === q && document.activeElement?.classList?.contains('modal-close')) primo.focus();
        }, 160);
    },

    rispondi(risposta) {
        const q = this.domanda;
        if (!q) return;
        if (risposta === 'lascia') { this.lasciaDomanda(); return; }
        let cella;
        if (q.tipo === 'lettura') {
            if (!risposta) return;
            if (this.el('domanda-sempre')?.checked) this.letturaScelta = risposta;
            cella = { ...q.cella, conferma: risposta };
        } else {
            const campo = this.el('domanda-programmati');
            if (!napoliCampoObbligatorio(campo, 'Scrivi le ore programmate (per esempio 3).')) return;
            cella = { ...q.cella, programmati: campo.value.trim() };
        }
        this.domanda = null;
        closeModal('napoli-modal-domanda');
        this.errori.delete(q.chiave);
        this.attese.set(q.chiave, cella);
        const [id, i] = q.chiave.split('|').map(Number);
        const td = this.input(id, i)?.closest('td');
        if (td) this.aggiornaCella(this.righe.get(id), td);
        this.salva();
    },

    lasciaDomanda() {
        const q = this.domanda;
        this.domanda = null;
        closeModal('napoli-modal-domanda');
        if (q) {
            const [id, i] = q.chiave.split('|').map(Number);
            const input = this.input(id, i);
            if (input) { input.focus(); input.select(); }
        }
        this.mostraStato();
        setTimeout(() => this.prossimaDomanda(), 50);
    },

    // ---------- nota del giorno ----------

    async apriNota(id, i) {
        const r = this.righe.get(id);
        const col = this.colonna(i);
        if (!r || !col) return;
        if (this.dati.chiuso) { showToast('Il mese è chiuso: le note non si cambiano più.', 'warning'); return; }
        if (this.bloccata(r, col, r.celle[i])) { showToast('In questo giorno non si scrivono ore per questa coppia.', 'info'); return; }
        const chiave = `${id}|${i}`;
        const c = r.celle[i] || {};
        const input = this.input(id, i);
        // la casella va con la nota se non e' salvata: in sospeso, oppure rimasta "da sistemare"
        // (una "A" senza le ore programmate, un "1,30" da chiarire, una sigla sconosciuta). Si
        // manda il valore che si vede, cosi' la nota non lo perde
        let testo = null;
        if (this.attese.has(chiave)) testo = this.attese.get(chiave).testo;
        else if (this.errori.has(chiave) && input) testo = input.value.trim();
        this.nota = { id, i, chiave, testo,
            assente: ((testo ?? input?.value ?? c.t ?? '').trim().toUpperCase() === 'A') };
        const form = this.el('form-nota');
        napoliPulisciErrori(form);
        this.el('nota-chi').textContent = `${napoliMaiuscola(napoliGiornoLungo(col.data))} ${formatDataIT(col.data)} · ${r.alunno} con ${r.operatore} (${r.figura_nome})`;
        form.querySelectorAll('input[name="nota_tipo"]').forEach(x => { x.checked = x.value === (c.nt || ''); });
        this.el('nota-ora').value = c.no || '';
        this.el('nota-programmati').value = c.p ? napoliTestoCella(c.p) : '';
        this.el('nota-recuperata').checked = !!c.rec;
        this.el('nota-testo').value = c.nx || '';
        this.aggiornaNota();
        openModal('napoli-modal-nota');
    },

    aggiornaNota() {
        const tipo = this.el('form-nota').querySelector('input[name="nota_tipo"]:checked')?.value || '';
        const conOra = tipo === 'ritardo' || tipo === 'uscita_anticipata';
        this.el('nota-gruppo-ora').hidden = !conOra;
        this.el('nota-ora-etichetta').textContent = tipo === 'uscita_anticipata' ? 'Uscito alle' : 'Entrato alle';
        const recuperabile = conOra || (this.nota && this.nota.assente);
        const rec = this.el('nota-recuperata');
        rec.disabled = !recuperabile;
        if (!recuperabile) rec.checked = false;
    },

    async salvaNota() {
        const n = this.nota;
        if (!n) return;
        const form = this.el('form-nota');
        napoliPulisciErrori(form);
        const tipo = form.querySelector('input[name="nota_tipo"]:checked')?.value || '';
        const conOra = tipo === 'ritardo' || tipo === 'uscita_anticipata';
        if (conOra && !napoliCampoObbligatorio(this.el('nota-ora'), 'Scrivi a che ora (per esempio 9:00).')) return;
        const cella = { coppia_id: n.id, data: this.dati.giorni[n.i], nota_tipo: tipo, nota_ora: conOra ? this.el('nota-ora').value.trim() : '',
            nota: this.el('nota-testo').value.trim(), recuperata: this.el('nota-recuperata').checked };
        const programmati = this.el('nota-programmati').value.trim();
        if (programmati) cella.programmati = programmati;
        if (n.testo !== null) cella.testo = n.testo;          // la casella cambiata e non ancora salvata va con la nota
        if (this.inVolo) await this.inVolo;
        const d = this.dati;
        const pulsante = this.el('nota-salva');
        const inSospeso = this.attese.get(n.chiave);
        this.attese.delete(n.chiave);                      // parte con la nota, non due volte
        // era l'unica casella in sospeso: il salvataggio automatico non ha piu' niente da mandare
        if (!this.attese.size) { clearTimeout(this.timer); this.timer = null; }
        // se la nota non si salva, la casella torna in sospeso con il suo salvataggio automatico
        const rimetti = () => {
            if (inSospeso && !this.attese.has(n.chiave)) this.attese.set(n.chiave, inSospeso);
            if (this.attese.size && !this.timer && !this.inVolo) this.programma();
            this.mostraStato();
        };
        setButtonLoading(pulsante, true);
        try {
            const r = await apiCall(`/api/napoli/lotti/${d.lotto.id}/presenze`, {
                method: 'POST', body: JSON.stringify({ anno: d.anno, mese: d.mese, celle: [cella] }),
            });
            const e = r.celle[0];
            if (e.esito === 'errore' || e.esito === 'servono_programmati') {
                const err = new Error(e.esito === 'errore' ? e.messaggio : 'Scrivi le ore programmate di quel giorno: servono per la metà.');
                err.data = { campo: e.esito === 'servono_programmati' ? 'programmati' : (e.campo || null) };
                r.righe.forEach(riga => this.aggiornaRiga(riga));
                rimetti();
                napoliMostraErrore(err, form);
                return;
            }
            const inviate = new Map([[n.chiave, cella]]);
            closeModal('napoli-modal-nota');
            this.applica(r, inviate);
            if (e.esito === 'salvata') showToast(r.descrizione ? 'Nota del giorno salvata' : 'Nessun cambiamento da salvare', 'success');
            this.mostraStato();
        } catch (err) {
            rimetti();
            napoliMostraErrore(err, form);
            if (err.code === 'MESE_CHIUSO_LOTTO') { closeModal('napoli-modal-nota'); await this.carica(true); }
        } finally {
            setButtonLoading(pulsante, false);
        }
    },

    // ---------- dettaglio della coppia nel mese ----------

    async apriDettaglio(id) {
        const d = this.dati;
        const corpo = this.el('coppia-corpo');
        const r = this.righe.get(id);
        this.el('coppia-titolo').textContent = r ? `${r.alunno} con ${r.operatore}` : 'Dettaglio del mese';
        this.el('coppia-anagrafica').href = r ? `/napoli/anagrafiche#alunno-${r.alunno_id}` : '/napoli/anagrafiche';
        corpo.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
        openModal('napoli-modal-coppia');
        await this.salvaInSospeso();
        let x;
        try {
            x = await apiCall(`/api/napoli/lotti/${d.lotto.id}/presenze/coppie/${id}?anno=${d.anno}&mese=${d.mese}`);
        } catch (e) {
            corpo.innerHTML = `<div class="alert alert-danger">${escapeHtml(napoliTestoErrore(e, 'Dettaglio non disponibile'))}</div>`;
            return;
        }
        const c = x.coppia;
        const cr = x.credito;
        const chip = (etichetta, valore) => valore ? `<span class="napoli-chip">${escapeHtml(etichetta)} <strong>${escapeHtml(String(valore))}</strong></span>` : '';
        let credito;
        if (cr.nel_titolare) {
            credito = `<p>Le ore di questa sostituzione contano nel credito/debito della riga del titolare (${escapeHtml(cr.nel_titolare.operatore)}).</p>`;
        } else if (cr.previste === null) {
            credito = '<p>Manca il PEI di questa figura (e la programmazione settimanale): il credito/debito non si calcola. Aggiungi il PEI nella scheda dell\'alunno.</p>';
        } else {
            const fonte = cr.stima
                ? `<strong>stima dal PEI</strong>: le ore PEI della settimana ripartite sui ${cr.giorni_servizio} giorni di servizio del mese (lunedì-sabato, senza le festività e le chiusure), perché manca la programmazione settimanale`
                : `dalla programmazione settimanale, nei ${cr.giorni_servizio} giorni di servizio del mese (senza le festività e le chiusure)`;
            const cdClasse = cr.credito_debito >= 0 ? 'text-success' : 'text-danger';
            credito = `<div class="napoli-numeri napoli-numeri-tre">
                    <div class="napoli-numero-box"><span class="napoli-numero-valore">${cr.stima ? '≈ ' : ''}${escapeHtml(cr.previste_testo)}</span><span class="napoli-numero-etichetta">Ore previste</span></div>
                    <div class="napoli-numero-box"><span class="napoli-numero-valore">${escapeHtml(cr.erogate_testo)}</span><span class="napoli-numero-etichetta">Ore riconosciute${x.sostituti.length ? ' (con i sostituti)' : ''}</span></div>
                    <div class="napoli-numero-box"><span class="napoli-numero-valore ${cdClasse}">${cr.stima ? '≈ ' : ''}${escapeHtml(napoliOreDueForme(cr.credito_debito))}</span><span class="napoli-numero-etichetta">Credito/debito</span></div>
                </div>
                <p class="napoli-aiuto">Previste ${fonte}. Credito/debito = previste meno riconosciute, come in Rendicontazione: positivo (verde) = ore ancora dovute all'alunno, negativo (rosso) = ore in più.</p>
                ${c.avvisi.includes('pei_su_piu_titolari') ? `<div class="alert alert-warning napoli-alert">${escapeHtml(x.spiegazioni.pei_su_piu_titolari)}.</div>` : ''}
                ${x.mese.avviso_vacanze ? `<div class="alert alert-warning napoli-alert">${escapeHtml(x.mese.avviso_vacanze)}</div>` : ''}`;
        }
        // a 1366 la tabella sta nella finestra: numero e giorni della settimana in una colonna
        const settimane = x.settimane.map(s => `<tr>
                <td><strong>Sett. ${s.n}</strong> <span class="napoli-periodo">${escapeHtml(formatDataIT(s.dal).slice(0, 5))} - ${escapeHtml(formatDataIT(s.al).slice(0, 5))}</span></td>
                <td class="napoli-numero">${escapeHtml(s.minuti_testo)}</td>
                ${x.altre_coppie.length ? `<td class="napoli-numero">${escapeHtml(s.gruppo_testo)}</td>` : ''}
                <td class="napoli-numero">${escapeHtml(s.pei_testo || '—')}</td><td class="napoli-numero">${escapeHtml(s.tetto_testo || '—')}</td>
                <td>${s.colore === 'rosso' ? '<span class="badge badge-danger">Oltre il PEI + 20%</span>' : (s.colore === 'giallo' ? '<span class="badge badge-warning">Oltre il PEI</span>' : (s.pei ? '<span class="badge badge-success">Entro il PEI</span>' : ''))}</td>
            </tr>`).join('');
        const giorni = x.giorni.length ? x.giorni.map(g => `<tr>
                <td class="napoli-periodo">${escapeHtml(g.giorno)}</td>
                <td class="napoli-numero"><strong>${escapeHtml(g.scritto)}</strong></td>
                <td class="napoli-numero">${escapeHtml(g.riconosciute_testo)}</td>
                <td>${escapeHtml(g.spiegazione)}${g.nota ? `<div class="napoli-sotto-in">«${escapeHtml(g.nota)}»</div>` : ''}${g.avvisi.map(a => `<div class="napoli-sotto-in napoli-da-decidere">${escapeHtml(x.spiegazioni[a] || a)}</div>`).join('')}</td>
                <td class="napoli-azioni">${!g.fuori_servizio && !x.mese.chiuso ? `<button type="button" class="btn btn-ghost btn-sm" data-nota-giorno="${escapeHtml(g.data)}" data-coppia="${c.id}">Nota</button>` : ''}</td>
            </tr>`).join('') : '<tr><td colspan="5" class="napoli-vuoto">Nessun giorno scritto in questo mese.</td></tr>';
        corpo.innerHTML = `
            <div class="napoli-trovato">
                ${chip('Figura', c.figura_nome)}${chip('Scuola', c.scuola)}${chip('Municipalità', c.municipalita)}
                ${chip('Grado', NAPOLI_TESTI_GRADO[c.grado || 'da_decidere'])}${chip(c.quota ? 'Ore della coppia' : 'PEI', c.pei ? `${c.pei} h a settimana` : 'manca')}
                ${chip('Ruolo', c.ruolo === 'sostituto' ? 'sostituto' : 'titolare')}${chip('Dal', formatDataIT(c.dal))}${c.al ? chip('Al', formatDataIT(c.al)) : ''}
            </div>
            <section class="napoli-sezione"><div class="napoli-sezione-testa"><h3>${escapeHtml(x.mese.testo)}: ${escapeHtml(x.totale_testo)} riconosciute</h3></div>${credito}</section>
            <section class="napoli-sezione"><div class="napoli-sezione-testa"><h3>Settimane (VERIFICA)</h3></div>
                <div class="table-container"><table class="table napoli-tabella-compatta napoli-tabella-settimane"><thead><tr><th>Settimana</th><th class="napoli-numero">Ore</th>${x.altre_coppie.length ? '<th class="napoli-numero" title="Le ore dell\'alunno per la figura, con le altre coppie">Tutte le coppie</th>' : ''}<th class="napoli-numero">PEI</th><th class="napoli-numero" title="PEI + 20%, arrotondato all\'ora">Tetto</th><th></th></tr></thead><tbody>${settimane}</tbody></table></div>
                ${x.altre_coppie.length ? `<p class="napoli-aiuto">La VERIFICA guarda l'alunno per la figura: insieme a ${x.altre_coppie.map(a => `${escapeHtml(a.operatore)} (${a.ruolo === 'sostituto' ? 'sostituto' : 'titolare'}, ${escapeHtml(a.totale_testo)})`).join(', ')}.</p>` : ''}
            </section>
            <section class="napoli-sezione"><div class="napoli-sezione-testa"><h3>Giorni</h3></div>
                <div class="table-container"><table class="table napoli-tabella-compatta"><thead><tr><th>Giorno</th><th class="napoli-numero">Scritto</th><th class="napoli-numero">Riconosciute</th><th>Come si calcola</th><th></th></tr></thead><tbody>${giorni}</tbody></table></div>
            </section>
            ${x.foglio && x.foglio.note ? `<section class="napoli-sezione"><div class="napoli-sezione-testa"><h3>Note del foglio</h3></div><p>${escapeHtml(x.foglio.note)}</p></section>` : ''}
            ${c.avvisi.length ? `<section class="napoli-sezione"><div class="napoli-sezione-testa"><h3>Avvisi</h3></div><ul class="napoli-elenco">${c.avvisi.map(a => `<li>${escapeHtml(x.spiegazioni[a] || a)}</li>`).join('')}</ul></section>` : ''}`;
    },

    // ---------- chiusura e riapertura del mese del lotto ----------

    async apriMese() {
        if (!(await this.puoLasciare('Modifiche non salvate: il mese si chiude dopo averle salvate. Riprova il salvataggio.',
            this.dati.chiuso ? 'riapri il mese' : 'chiudi il mese'))) return;
        const d = this.dati;
        const form = this.el('form-mese');
        napoliPulisciErrori(form);
        const conferma = this.el('mese-conferma');
        if (d.chiuso) {
            this.el('mese-titolo').textContent = `Riapri ${formatMeseIT(`${d.anno}-${String(d.mese).padStart(2, '0')}`)}`;
            form.innerHTML = `<p>Riaprendo il mese le ore di ${escapeHtml(d.lotto.nome)} si possono di nuovo cambiare. Il motivo resta nel registro attività.</p>
                <div class="form-group"><label class="form-label" for="mese-motivo">Motivo della riapertura</label>
                <input type="text" class="form-control" id="mese-motivo" data-campo="motivo" maxlength="200" autocomplete="off" placeholder="per esempio: correzione delle ore di una coppia"></div>
                <p class="napoli-aiuto">Non scrivere dati personali o motivi di salute.</p>`;
            conferma.textContent = 'Riapri il mese';
        } else {
            const righe = d.righe;
            const senzaOre = righe.filter(r => !r.totale && !Object.keys(r.celle).length).length;
            const conAvvisi = righe.filter(r => r.avvisi.length).length;
            const nonRegistrati = righe.filter(r => r.avvisi.includes('giorno_non_registrato')).length;
            const ore = righe.reduce((s, r) => s + r.totale, 0);
            const voci = [
                `${righe.length === 1 ? '1 coppia' : `${righe.length} coppie`}, ${napoliOreBrevi(ore)} ore riconosciute`,
                senzaOre ? `${senzaOre === 1 ? '1 coppia' : `${senzaOre} coppie`} senza ore` : '',
                nonRegistrati ? `${nonRegistrati === 1 ? '1 coppia' : `${nonRegistrati} coppie`} con giorni non registrati (valgono 0)` : '',
                conAvvisi ? `${conAvvisi === 1 ? '1 riga' : `${conAvvisi} righe`} con avvisi (filtro «Solo con avvisi»)` : '',
            ].filter(Boolean);
            this.el('mese-titolo').textContent = `Chiudi ${formatMeseIT(`${d.anno}-${String(d.mese).padStart(2, '0')}`)}`;
            form.innerHTML = `<p>Chiudendo il mese le ore, le note e le ore del coordinatore di ${escapeHtml(d.testo.toLowerCase())} di ${escapeHtml(d.lotto.nome)} non si cambiano più, nemmeno con Ctrl+Z. Si può riaprire scrivendo il motivo.</p>
                <ul class="napoli-elenco">${voci.map(v => `<li>${escapeHtml(v)}</li>`).join('')}</ul>
                <div class="form-group"><label class="form-label" for="mese-nota">Nota (facoltativa)</label>
                <input type="text" class="form-control" id="mese-nota" data-campo="nota" maxlength="200" autocomplete="off"></div>`;
            conferma.textContent = 'Chiudi il mese';
        }
        openModal('napoli-modal-mese');
    },

    async confermaMese() {
        const d = this.dati;
        const form = this.el('form-mese');
        const riapri = d.chiuso;
        const corpo = { anno: d.anno, mese: d.mese };
        if (riapri) {
            const motivo = this.el('mese-motivo');
            if (!napoliCampoObbligatorio(motivo, 'Scrivi perché riapri il mese.')) return;
            corpo.motivo = motivo.value.trim();
        } else {
            corpo.nota = this.el('mese-nota').value.trim();
            // fatture del mese non definitive (PROGETTO §9): si chiude solo confermando
            if (this.el('mese-senza-fattura')?.checked) corpo.senza_fattura = true;
        }
        const pulsante = this.el('mese-conferma');
        setButtonLoading(pulsante, true);
        try {
            const r = await apiCall(`/api/napoli/lotti/${d.lotto.id}/mesi/${riapri ? 'riapri' : 'chiudi'}`, { method: 'POST', body: JSON.stringify(corpo) });
            closeModal('napoli-modal-mese');
            showToast(r.messaggio, 'success');
            await this.carica(true);
        } catch (e) {
            if (e.code === 'FATTURE_NON_DEFINITIVE' && !this.el('mese-senza-fattura')) {
                const box = document.createElement('div');
                box.className = 'alert alert-warning napoli-alert';
                box.setAttribute('role', 'alert');
                const fatture = (e.data && e.data.fatture) || [];
                box.innerHTML = `${napoliSvg(NAPOLI_ICONE_STATO.avviso, 18)}<div>
                    <strong>${fatture.length === 1 ? 'Una fattura del mese non è ancora definitiva' : `${fatture.length} fatture del mese non sono ancora definitive`}</strong>
                    <ul class="napoli-elenco">${fatture.map(f => `<li>${escapeHtml(f)}</li>`).join('')}</ul>
                    <p>Di solito prima si rende definitiva la fattura nella scheda <a href="/napoli/fattura">Fattura</a>, poi si chiude il mese.</p>
                    <label class="napoli-scelta-riga"><input type="checkbox" id="mese-senza-fattura"> Chiudi lo stesso: per ${fatture.length === 1 ? 'questa' : 'queste'} la fattura non si fa adesso</label>
                </div>`;
                form.prepend(box);
                this.el('mese-senza-fattura').focus();
            } else {
                napoliMostraErrore(e, form);
            }
        } finally {
            setButtonLoading(pulsante, false);
        }
    },
};

// ==================== scheda Fattura (prospetto fattura, passo 1.9) ====================

const NAPOLI_FATTURA_ATTESA = 2000;          // ore del coordinatore: come il salvataggio automatico della Rendicontazione
const NAPOLI_ICONA_EXCEL = 'M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z';
const NAPOLI_ICONA_STAMPA = 'M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z';
const NAPOLI_ICONA_LUCCHETTO = 'M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z';
const NAPOLI_ICONA_COPIA = 'M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z';

/** Data e ora 'AAAA-MM-GGTHH:MM:SS' -> '31/07/2026 alle 10:30' (senza fuso orario). */
function napoliQuando(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso || '');
    return m ? `${m[3]}/${m[2]}/${m[1]} alle ${m[4]}:${m[5]}` : '';
}

/**
 * I prospetti fattura del mese del lotto (REGOLE 9): uno per contratto applicativo e grado, con
 * le righe come la fattura reale, la ritenuta, l'imponibile, l'IVA e "da pagare" (split
 * payment); i controlli spiegati (in rosso quelli da sistemare prima della definitiva); le ore
 * del coordinatore, che si salvano da sole 2 secondi dopo l'ultimo tasto, uscendo dalla casella
 * o con Invio (frecce ↑ ↓ come in Rendicontazione: la casella sopra o sotto); Excel, Stampa,
 * «Rendi definitiva» (numero e data della fattura emessa) e «Riapri la fattura» (con il
 * motivo). Ogni numero arriva dal server (napoli_fattura): la pagina non calcola niente.
 */
const NapoliFattura = {
    dati: null,
    ritenute: null,
    coord: new Map(),        // chiave del prospetto -> { salvato, corrente, timer, inVolo, ancora, errore, lettura }
    ultimoSalvataggio: null,
    daRicaricare: false,     // ore del coordinatore salvate: i prospetti si ricaricano
    seq: 0,
    scelto: null,            // il prospetto della finestra aperta

    el(id) { return document.getElementById(id); },

    async avvia() {
        NapoliComune.alCambioLotto = async () => { await this.salvaInSospeso(); await this.carica(); };
        NapoliComune.dopoAnnulla = async () => { await this.carica(); };
        NapoliComune.primaDiAnnullare = () => this.salvaInSospeso();
        this.collega();
        try {
            await NapoliComune.caricaLotti();
        } catch (e) {
            const box = this.el('fattura-senza-lotto');
            box.hidden = false;
            box.innerHTML = `<div class="alert alert-danger">${escapeHtml(napoliTestoErrore(e, 'Dati non disponibili'))}</div>`;
            return;
        }
        this.preparaMesi();
        await this.carica();
    },

    // ---------- mese scelto (lo stesso della scheda Presenze, ricordato nel browser) ----------

    preparaMesi(scelto) {
        const oggi = new Date();
        const corrente = `${oggi.getFullYear()}-${String(oggi.getMonth() + 1).padStart(2, '0')}`;
        let ricordato = null;
        try {
            const v = localStorage.getItem(NAPOLI_CHIAVE_MESE);
            ricordato = /^\d{4}-\d{2}$/.test(v || '') ? v : null;
        } catch (e) { /* il browser non ricorda: il mese di oggi */ }
        const valore = scelto || ricordato || corrente;
        const mesi = [];
        for (let k = -12; k <= 1; k++) {
            const d = new Date(oggi.getFullYear(), oggi.getMonth() + k, 1);
            mesi.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
        }
        if (!mesi.includes(valore)) mesi.push(valore);
        mesi.sort();
        const scelta = this.el('fm-mese');
        scelta.innerHTML = mesi.map(v => `<option value="${v}">${escapeHtml(napoliMaiuscola(formatMeseIT(v)))}</option>`).join('');
        scelta.value = valore;
    },

    meseScelto() {
        const [anno, mese] = this.el('fm-mese').value.split('-').map(Number);
        return { anno, mese };
    },

    ricordaMese(v) {
        try { localStorage.setItem(NAPOLI_CHIAVE_MESE, v); } catch (e) { /* il browser non ricorda: pazienza */ }
    },

    async cambiaMese(passo) {
        await this.salvaInSospeso();
        const { anno, mese } = this.meseScelto();
        const d = new Date(anno, mese - 1 + passo, 1);
        const v = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
        const scelta = this.el('fm-mese');
        if (![...scelta.options].some(o => o.value === v)) this.preparaMesi(v);
        scelta.value = v;
        this.ricordaMese(v);
        await this.carica();
    },

    // ---------- eventi ----------

    collega() {
        this.el('fm-mese').addEventListener('change', async () => {
            await this.salvaInSospeso();
            this.ricordaMese(this.el('fm-mese').value);
            await this.carica();
        });
        this.el('fm-prima').addEventListener('click', () => this.cambiaMese(-1));
        this.el('fm-dopo').addEventListener('click', () => this.cambiaMese(1));
        this.el('btn-fattura-annulla').addEventListener('click', () => NapoliComune.annulla());
        const box = this.el('fattura-contenuto');
        box.addEventListener('input', (e) => { if (e.target.matches('input.nf-coord')) this.modificata(e.target); });
        box.addEventListener('change', (e) => { if (e.target.matches('input.nf-coord')) this.salvaCoord(e.target.dataset.chiave); });
        box.addEventListener('keydown', (e) => { if (e.target.matches('input.nf-coord')) this.tasti(e); });
        box.addEventListener('click', (e) => {
            const b = e.target.closest('[data-azione]');
            if (!b) return;
            const chiave = b.closest('[data-chiave]')?.dataset.chiave;
            if (b.dataset.azione === 'definitiva') this.apriDefinitiva(chiave);
            else if (b.dataset.azione === 'riapri') this.apriRiapri(chiave);
            else if (b.dataset.azione === 'copia') this.copia(b);
        });
        this.el('form-definitiva').addEventListener('submit', (e) => { e.preventDefault(); this.confermaDefinitiva(); });
        this.el('definitiva-data').addEventListener('input', () => this.aggiornaScadenza());
        this.el('form-riapri').addEventListener('submit', (e) => { e.preventDefault(); this.confermaRiapri(); });
        // uscita dalla pagina entro i 2 secondi: le ore del coordinatore cambiate partono subito
        window.addEventListener('pagehide', () => this.inviaInUscita());
        document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') this.inviaInUscita(); });
    },

    // ---------- caricamento ----------

    async carica() {
        const lotto = NapoliComune.lotto;
        const senza = this.el('fattura-senza-lotto');
        if (!lotto) {
            senza.hidden = false;
            this.el('fattura-pagina').hidden = true;
            senza.innerHTML = `<div class="card">${napoliBenvenuto()}</div>`;
            senza.querySelector('[data-azione="crea-lotto"]')?.addEventListener('click', () =>
                NapoliProcedura.apri(async (l) => { await NapoliComune.caricaLotti(l.id); await this.carica(); }));
            return;
        }
        senza.hidden = true;
        this.el('fattura-pagina').hidden = false;
        const { anno, mese } = this.meseScelto();
        const seq = ++this.seq;
        let d, rit;
        try {
            [d, rit] = await Promise.all([
                apiCall(`/api/napoli/lotti/${lotto.id}/fatture?anno=${anno}&mese=${mese}`),
                apiCall(`/api/napoli/lotti/${lotto.id}/fatture/ritenute`),
            ]);
        } catch (e) {
            if (seq !== this.seq) return;
            this.el('fattura-contenuto').innerHTML = `<div class="alert alert-danger">${escapeHtml(napoliTestoErrore(e, 'Prospetti non disponibili'))}</div>`;
            return;
        }
        if (seq !== this.seq) return;           // lotto o mese cambiati nel frattempo
        this.dati = d;
        this.ritenute = rit;
        // le ore del coordinatore: si tiene quello che si sta scrivendo (se il prospetto c'e' ancora)
        const prima = this.coord;
        this.coord = new Map();
        d.prospetti.forEach((p) => {
            const vecchio = prima.get(p.chiave);
            const st = { salvato: p.coordinatore.ore, corrente: null, timer: null, inVolo: null, ancora: false, errore: null, lettura: null };
            if (vecchio && vecchio.lotto === d.lotto.id && vecchio.mese === `${d.anno}-${d.mese}`) {
                Object.assign(st, { corrente: vecchio.corrente, timer: vecchio.timer, inVolo: vecchio.inVolo, ancora: vecchio.ancora,
                    errore: vecchio.errore, lettura: vecchio.lettura });
            }
            st.lotto = d.lotto.id;
            st.mese = `${d.anno}-${d.mese}`;
            this.coord.set(p.chiave, st);
        });
        this.disegna();
        this.disegnaRitenute();
        this.mostraStato();
    },

    // ---------- disegno ----------

    disegna() {
        const d = this.dati;
        const attiva = document.activeElement && document.activeElement.matches && document.activeElement.matches('input.nf-coord')
            ? { chiave: document.activeElement.dataset.chiave, inizio: document.activeElement.selectionStart, fine: document.activeElement.selectionEnd } : null;
        const conOre = d.prospetti.filter(p => !p.vuoto);
        this.el('fattura-conta').textContent = d.prospetti.length === 1 ? '1 fattura' : `${d.prospetti.length} fatture`;
        this.el('fattura-conta').hidden = !d.prospetti.length;
        const avvisi = [];
        if (d.chiuso) avvisi.push(`<div class="napoli-mese-chiuso">${napoliSvg(NAPOLI_ICONA_LUCCHETTO, 16)}<span><strong>${escapeHtml(d.testo)} è chiuso</strong>: le ore non si cambiano. Le fatture si possono comunque rendere definitive o riaprire.</span></div>`);
        if (d.ore_senza_contratto) {
            const una = d.ore_senza_contratto === '1';
            avvisi.push(`<div class="alert alert-warning napoli-alert">${napoliSvg(NAPOLI_ICONE_STATO.avviso, 18)}<div><strong>${una ? '1 ora' : `${escapeHtml(d.ore_senza_contratto)} ore`} di ${escapeHtml(d.testo.toLowerCase())} ${una ? 'è' : 'sono'} in giorni che nessun contratto applicativo copre</strong>: non ${una ? 'va' : 'vanno'} in nessuna fattura. Aggiungi il contratto (o correggi le sue date) nelle <a href="/napoli/impostazioni#contratti">Impostazioni, Contratti</a>.</div></div>`);
        }
        this.el('fattura-avvisi-mese').innerHTML = avvisi.join('');
        const box = this.el('fattura-contenuto');
        if (!d.prospetti.length) {
            box.innerHTML = `<div class="card"><div class="card-body napoli-fattura-vuota">
                ${napoliSvg('M9 14l6-6m-5.5.5h.01m4.99 5h.01M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16l3.5-2 3.5 2 3.5-2 3.5 2z', 40)}
                <h2>Nessun contratto applicativo copre ${escapeHtml(d.testo.toLowerCase())}</h2>
                <p>Le fatture si fanno per contratto applicativo (per esempio «XI») e grado: aggiungi il contratto con le sue date${d.contratti ? ', oppure scegli un altro mese' : ''}.</p>
                <a class="btn btn-primary" href="/napoli/impostazioni#contratti">Vai ai contratti applicativi</a>
            </div></div>`;
            return;
        }
        // prima quelle con ore: quelle vuote (un grado senza ore) restano in fondo, piu' piccole
        const vuoti = d.prospetti.filter(p => p.vuoto);
        box.innerHTML = conOre.map(p => this.htmlProspetto(p)).join('') + vuoti.map(p => this.htmlVuoto(p)).join('');
        if (attiva) {
            const input = box.querySelector(`input.nf-coord[data-chiave="${CSS.escape(attiva.chiave)}"]`);
            if (input && !input.disabled) {
                input.focus();
                try { input.setSelectionRange(attiva.inizio, attiva.fine); } catch (e) { /* casella senza selezione */ }
            }
        }
        this.coord.forEach((st, chiave) => this.aggiornaCoord(chiave));
    },

    titolo(p) {
        return `Contratto ${escapeHtml(p.numero)} · ${escapeHtml(p.grado_testo)}`;
    },

    badgeStato(p) {
        const f = p.fattura;
        if (p.stato === 'definitiva') return `<span class="badge badge-success napoli-badge-stato">${napoliSvg(NAPOLI_ICONA_LUCCHETTO, 13)} Definitiva · n. ${escapeHtml(f.numero)} del ${escapeHtml(f.data_testo)}</span>`;
        if (p.vuoto) return '<span class="badge badge-secondary napoli-badge-stato">Nessuna ora</span>';
        const n = p.bloccanti.length;
        const riaperta = p.stato === 'riaperta' ? '<span class="badge badge-info napoli-badge-stato">Riaperta</span> ' : '';
        if (n) return `${riaperta}<span class="badge badge-danger napoli-badge-stato">${n === 1 ? '1 cosa da sistemare' : `${n} cose da sistemare`}</span>`;
        return `${riaperta}<span class="badge badge-warning napoli-badge-stato">Da rendere definitiva</span>`;
    },

    htmlRighe(p) {
        const t = p.totali;
        const righe = p.righe.map(r => `<tr>
                <td>${escapeHtml(r.descrizione)}</td>
                <td class="napoli-numero">${escapeHtml(r.ore)}</td>
                <td class="napoli-numero">${escapeHtml(r.tariffa)}</td>
                <td class="napoli-numero">${escapeHtml(r.importo)}</td>
            </tr>`).join('');
        return `<div class="table-container napoli-fattura-tabella-box"><table class="table napoli-tabella-fattura">
            <caption class="napoli-sr">Righe della fattura: ${this.titolo(p)}, ${escapeHtml(p.periodo_testo)}</caption>
            <thead><tr><th scope="col">Descrizione</th><th scope="col" class="napoli-numero">Ore</th>
                <th scope="col" class="napoli-numero">Prezzo unitario</th><th scope="col" class="napoli-numero">Importo (€)</th></tr></thead>
            <tbody>${righe}
                <tr class="nf-somma"><td colspan="3">Somma delle righe</td><td class="napoli-numero">${escapeHtml(t.somma)}</td></tr>
                <tr class="nf-ritenuta"><td colspan="3">${escapeHtml(p.ritenuta_testo)}</td><td class="napoli-numero">-${escapeHtml(t.ritenuta)}</td></tr>
            </tbody>
            <tfoot>
                <tr><th scope="row" colspan="3">Imponibile</th><td class="napoli-numero">${escapeHtml(t.imponibile)}</td></tr>
                <tr><th scope="row" colspan="3">IVA ${escapeHtml(p.iva_percento)}%</th><td class="napoli-numero">${escapeHtml(t.iva)}</td></tr>
                <tr><th scope="row" colspan="3">Totale documento</th><td class="napoli-numero">${escapeHtml(t.totale)}</td></tr>
                <tr class="nf-da-pagare"><th scope="row" colspan="3">Da pagare${p.split_payment ? ' <span class="napoli-sotto-in">split payment: l\'IVA la versa l\'ente</span>' : ''}</th>
                    <td class="napoli-numero">${escapeHtml(t.da_pagare)}</td></tr>
            </tfoot>
        </table></div>`;
    },

    htmlCoord(p) {
        const c = p.coordinatore;
        const chiave = p.chiave;
        let motivo = '';
        if (!c.modificabile) {
            if (p.stato === 'definitiva') motivo = 'Fattura definitiva: le ore non si cambiano.';
            else if (this.dati.chiuso) motivo = 'Mese chiuso: le ore non si cambiano.';
            else motivo = 'Il mese non è ancora cominciato.';
        }
        return `<div class="napoli-prospetto-coord">
            <label class="form-label" for="nfc-${escapeHtml(chiave)}">Ore del coordinatore</label>
            <div class="nf-coord-riga">
                <input type="text" class="table-input nf-coord" id="nfc-${escapeHtml(chiave)}" data-chiave="${escapeHtml(chiave)}"
                    inputmode="decimal" autocomplete="off" maxlength="12" value="${escapeHtml(c.ore)}" placeholder="${c.modificabile ? 'da scrivere' : ''}"
                    aria-describedby="nfcm-${escapeHtml(chiave)}"${c.modificabile ? '' : ' disabled'}>
                <span class="napoli-sotto-in">${c.modificabile ? 'totale del periodo, in ore con la virgola (71,55); si salva da solo' : escapeHtml(motivo)}</span>
            </div>
            <div class="nf-coord-messaggio" id="nfcm-${escapeHtml(chiave)}" hidden></div>
        </div>`;
    },

    htmlControllo(c, livello) {
        const icona = livello === 'bloccante' ? NAPOLI_ICONE_STATO.manca : NAPOLI_ICONE_STATO.avviso;
        return `<li class="nf-controllo livello-${livello}">
            ${napoliSvg(icona, 18, 'napoli-icona-livello')}
            <div><strong>${escapeHtml(c.titolo)}</strong>
                ${c.testo ? `<p>${escapeHtml(c.testo)}</p>` : ''}
                ${c.link ? `<a href="${escapeHtml(c.link)}" class="nf-sistema">Sistema in ${escapeHtml(c.link_testo || 'Impostazioni')} →</a>` : ''}</div>
        </li>`;
    },

    htmlControlli(p) {
        const parti = [];
        if (p.stato === 'definitiva') {
            parti.push(`<p class="nf-pronta nf-definitiva">${napoliSvg(NAPOLI_ICONA_LUCCHETTO, 18)}<span>Resa definitiva il ${escapeHtml(napoliQuando(p.fattura.definitiva_il))}: righe, totali e testi non cambiano più e le ore del periodo (${escapeHtml(p.grado_testo.toLowerCase())}) sono bloccate.</span></p>`);
        } else if (p.bloccanti.length) {
            parti.push(`<h3 class="nf-titolo-controlli nf-danger">Da sistemare prima della definitiva</h3>
                <ul class="nf-controlli">${p.bloccanti.map(b => this.htmlControllo(b, 'bloccante')).join('')}</ul>`);
        } else {
            parti.push(`<p class="nf-pronta">${napoliSvg(NAPOLI_ICONE_STATO.ok, 18)}<span>Tutto a posto: controlla i numeri e rendi definitiva la fattura quando l'hai emessa.</span></p>`);
        }
        if (p.avvisi.length) {
            parti.push(`<h3 class="nf-titolo-controlli nf-warning">Da controllare</h3>
                <ul class="nf-controlli">${p.avvisi.map(a => this.htmlControllo(a, 'avviso')).join('')}</ul>`);
        }
        return parti.join('');
    },

    htmlTesti(p) {
        const t = p.testata;
        const pagamento = ['Bonifico bancario', t.iban ? `IBAN della cooperativa ${t.iban}` : '',
            p.scadenza_testo ? `scadenza ${p.scadenza_testo}` : ''].filter(Boolean).join(' · ');
        const voce = (etichetta, valore, copia = false) => `<div class="nf-testo">
            <dt>${escapeHtml(etichetta)}${copia && valore ? ` <button type="button" class="btn btn-ghost btn-sm nf-copia" data-azione="copia" data-testo="${escapeHtml(valore)}" title="Copia il testo, da incollare nel programma di fatturazione">${napoliSvg(NAPOLI_ICONA_COPIA, 14)} Copia</button>` : ''}</dt>
            <dd>${valore ? escapeHtml(valore) : '<span class="napoli-vuoto">manca</span>'}</dd></div>`;
        return `<dl class="napoli-prospetto-testi">
            ${voce('Oggetto', p.oggetto, true)}
            ${voce('Nota', p.nota, true)}
            ${voce('Destinatario', p.destinatario)}
            ${voce('Pagamento', pagamento)}
            ${voce('CIG e codice univoco ufficio', [t.cig ? `CIG ${t.cig}` : '', t.codice_univoco_ufficio ? `codice univoco ${t.codice_univoco_ufficio}` : ''].filter(Boolean).join(' · '))}
            ${voce('Cooperativa', [t.cooperativa, t.partita_iva ? `P.IVA ${t.partita_iva}` : ''].filter(Boolean).join(' · '))}
        </dl>`;
    },

    indirizzo(p, base) {
        const d = this.dati;
        return `${base}?lotto_id=${d.lotto.id}&anno=${d.anno}&mese=${d.mese}&contratto_id=${p.contratto_id}&grado=${encodeURIComponent(p.grado)}`;
    },

    htmlAzioni(p) {
        const definitiva = p.stato === 'definitiva';
        const titoloNo = p.bloccanti.length ? 'Prima sistema le cose in rosso' : (p.vuoto ? 'Nessuna ora da fatturare' : '');
        return `<div class="napoli-prospetto-azioni">
            <a class="btn btn-secondary btn-sm" href="${this.indirizzo(p, '/api/napoli/fatture/excel')}" download title="Il prospetto in Excel, con le ore per scuola e per operatore">${napoliSvg(NAPOLI_ICONA_EXCEL, 16)} Excel</a>
            <a class="btn btn-secondary btn-sm" href="${this.indirizzo(p, '/napoli/fattura/stampa')}&stampa=1" target="_blank" rel="noopener" title="Il prospetto su un foglio A4, da stampare o salvare in PDF">${napoliSvg(NAPOLI_ICONA_STAMPA, 16)} Stampa</a>
            <span class="nf-spazio"></span>
            ${definitiva
                ? `<button type="button" class="btn btn-secondary btn-sm" data-azione="riapri" title="Riapre la fattura scrivendo il motivo: le ore del periodo si possono di nuovo cambiare">Riapri la fattura</button>`
                : `<button type="button" class="btn btn-primary btn-sm" data-azione="definitiva"${p.puo_rendere_definitiva ? '' : ` disabled title="${escapeHtml(titoloNo)}"`}>${napoliSvg(NAPOLI_ICONA_LUCCHETTO, 16)} Rendi definitiva</button>`}
        </div>`;
    },

    htmlDettaglio(p) {
        const s = p.dettaglio.scuole;
        const o = p.dettaglio.operatori;
        if (!s.length) return '';
        return `<details class="napoli-prospetto-dettaglio">
            <summary>Dettaglio delle ore per scuola e per operatore</summary>
            <div class="nf-dettaglio-corpo">
                <div class="table-container"><table class="table napoli-tabella-compatta">
                    <thead><tr><th>Scuola</th><th>Mun.</th><th>Figura</th><th class="napoli-numero">Ore</th></tr></thead>
                    <tbody>${s.map(x => `<tr><td>${escapeHtml(x.scuola)}</td><td>${x.municipalita ?? ''}</td><td>${escapeHtml(x.figura)}</td><td class="napoli-numero">${escapeHtml(x.ore)}</td></tr>`).join('')}</tbody>
                </table></div>
                <div class="table-container"><table class="table napoli-tabella-compatta">
                    <thead><tr><th>Operatore</th><th>Figura</th><th class="napoli-numero">Ore</th></tr></thead>
                    <tbody>${o.map(x => `<tr><td>${escapeHtml(x.operatore)}</td><td>${escapeHtml(x.figura)}</td><td class="napoli-numero">${escapeHtml(x.ore)}</td></tr>`).join('')}</tbody>
                </table></div>
            </div>
            <p class="napoli-aiuto">Le ore della griglia presenze di questo periodo e grado, al centesimo (senza il coordinatore).</p>
        </details>`;
    },

    htmlProspetto(p) {
        return `<section class="card napoli-prospetto nf-${escapeHtml(p.stato)}" data-chiave="${escapeHtml(p.chiave)}" aria-labelledby="pt-${escapeHtml(p.chiave)}">
            <div class="card-header napoli-prospetto-testa">
                <div>
                    <h2 class="card-title" id="pt-${escapeHtml(p.chiave)}">${this.titolo(p)}</h2>
                    <p class="napoli-sottotitolo">Competenze ${escapeHtml(p.periodo_testo)}${p.mese_intero ? '' : ' (parte del mese, dalle date del contratto)'}</p>
                </div>
                <div class="nf-stato">${this.badgeStato(p)}</div>
            </div>
            <div class="card-body">
                <div class="napoli-prospetto-corpo">
                    <div class="napoli-prospetto-righe">${this.htmlRighe(p)}</div>
                    <div class="napoli-prospetto-lato">${this.htmlCoord(p)}${this.htmlControlli(p)}</div>
                </div>
                ${this.htmlTesti(p)}
                ${this.htmlAzioni(p)}
                ${this.htmlDettaglio(p)}
            </div>
        </section>`;
    },

    htmlVuoto(p) {
        const avviso = p.bloccanti.find(b => b.codice !== 'periodo_non_finito');
        return `<section class="card napoli-prospetto napoli-prospetto-vuoto" data-chiave="${escapeHtml(p.chiave)}" aria-labelledby="pt-${escapeHtml(p.chiave)}">
            <div class="card-header napoli-prospetto-testa">
                <div>
                    <h2 class="card-title" id="pt-${escapeHtml(p.chiave)}">${this.titolo(p)}</h2>
                    <p class="napoli-sottotitolo">Competenze ${escapeHtml(p.periodo_testo)}: nessuna ora registrata di questo grado, niente da fatturare.</p>
                </div>
                <div class="nf-stato">${this.badgeStato(p)}</div>
            </div>
            <div class="card-body napoli-prospetto-vuoto-corpo">
                ${this.htmlCoord(p)}
                ${avviso ? `<ul class="nf-controlli">${this.htmlControllo(avviso, 'bloccante')}</ul>` : ''}
            </div>
        </section>`;
    },

    disegnaRitenute() {
        const r = this.ritenute;
        const box = this.el('ritenute-contenuto');
        if (!r || !r.contratti.length) {
            box.innerHTML = '<p class="napoli-vuoto">Ancora nessuna fattura definitiva in questo lotto.</p>';
            return;
        }
        const righe = r.contratti.map(c => `
            <tbody>
                <tr class="nf-ritenute-contratto"><th colspan="4" scope="rowgroup">Contratto ${escapeHtml(c.numero)} · ${escapeHtml(napoliMaiuscola(c.grado_testo))} · ${escapeHtml(c.periodo_testo)}${c.accordo_quadro ? ` · accordo ${escapeHtml(c.accordo_quadro)}` : ''}${c.finito ? ' <span class="badge badge-secondary badge-sm">finito: da svincolare</span>' : ''}</th></tr>
                ${c.fatture.map(f => `<tr><td>n. ${escapeHtml(f.numero)} del ${escapeHtml(f.data_testo)}</td><td>${escapeHtml(f.grado_testo)}, ${escapeHtml(f.periodo_testo)}</td>
                    <td class="napoli-numero">${escapeHtml(f.somma)}</td><td class="napoli-numero">${escapeHtml(f.ritenuta)}</td></tr>`).join('')}
                <tr class="nf-ritenute-totale"><th scope="row" colspan="2">Totale del contratto ${escapeHtml(c.numero)} (${c.n === 1 ? '1 fattura' : `${c.n} fatture`})</th>
                    <td class="napoli-numero">${escapeHtml(c.somma)}</td><td class="napoli-numero">${escapeHtml(c.ritenuta)}</td></tr>
            </tbody>`).join('');
        box.innerHTML = `<div class="table-container"><table class="table napoli-tabella-ritenute">
            <thead><tr><th scope="col">Fattura</th><th scope="col">Grado e periodo</th><th scope="col" class="napoli-numero">Somma delle righe (€)</th><th scope="col" class="napoli-numero">Ritenuta 0,50% (€)</th></tr></thead>
            ${righe}
            <tfoot><tr><th scope="row" colspan="3">Ritenute di tutti i contratti del lotto</th><td class="napoli-numero">${escapeHtml(r.totale)}</td></tr></tfoot>
        </table></div>`;
    },

    // ---------- ore del coordinatore (si salvano da sole) ----------

    prospettoDi(chiave) {
        return (this.dati && this.dati.prospetti.find(p => p.chiave === chiave)) || null;
    },

    input(chiave) {
        return this.el('fattura-contenuto').querySelector(`input.nf-coord[data-chiave="${CSS.escape(chiave)}"]`);
    },

    aggiornaCoord(chiave) {
        const st = this.coord.get(chiave);
        const input = this.input(chiave);
        if (!st || !input) return;
        if (st.corrente !== null && document.activeElement !== input) input.value = st.corrente;
        else if (st.corrente === null && document.activeElement !== input) input.value = st.salvato;
        input.classList.toggle('input-error', !!st.errore);
        input.classList.toggle('changed', !st.errore && st.corrente !== null && st.corrente !== st.salvato);
        const box = this.el(`nfcm-${chiave}`);
        const testo = st.errore || st.lettura || '';
        box.className = st.errore ? 'nf-coord-messaggio napoli-coord-errore' : 'nf-coord-messaggio napoli-coord-lettura';
        box.setAttribute('role', st.errore ? 'alert' : 'status');
        box.textContent = testo;
        box.hidden = !testo;
    },

    modificata(input) {
        const chiave = input.dataset.chiave;
        const st = this.coord.get(chiave);
        if (!st) return;
        st.corrente = input.value.trim();
        st.ancora = true;
        clearTimeout(st.timer);
        st.timer = setTimeout(() => this.salvaCoord(chiave), NAPOLI_FATTURA_ATTESA);
        this.aggiornaCoord(chiave);
        this.mostraStato('in_sospeso');
    },

    corpoCoord(chiave) {
        const st = this.coord.get(chiave);
        const p = this.prospettoDi(chiave);
        if (!st || !p || st.corrente === null || st.corrente === st.salvato) return null;
        const c = p.coordinatore;
        return { anno: c.anno, mese: c.mese, contratto_id: c.contratto_id, grado: c.grado, ore: st.corrente };
    },

    async salvaCoord(chiave) {
        const st = this.coord.get(chiave);
        if (!st) return;
        clearTimeout(st.timer);
        st.timer = null;
        if (st.inVolo) { st.ancora = true; return st.inVolo; }
        st.ancora = false;
        const corpo = this.corpoCoord(chiave);
        if (!corpo) {
            if (st.corrente !== null || st.errore) { st.corrente = null; st.errore = null; this.aggiornaCoord(chiave); }
            this.mostraStato();
            return;
        }
        const lotto = this.dati.lotto.id;
        this.mostraStato('salvo');
        st.inVolo = (async () => {
            try {
                const r = await apiCall(`/api/napoli/lotti/${lotto}/coordinamento`, { method: 'PUT', body: JSON.stringify(corpo) });
                st.salvato = r.riga.ore;
                st.errore = null;
                st.lettura = r.lettura || null;
                const input = this.input(chiave);
                const ora = input ? input.value.trim() : corpo.ore;
                st.corrente = ora === corpo.ore ? null : ora;
                this.ultimoSalvataggio = new Date();
                this.daRicaricare = true;
            } catch (e) {
                st.errore = napoliTestoErrore(e, 'Salvataggio non riuscito: riprova.');
            }
            st.inVolo = null;
            this.aggiornaCoord(chiave);
            if (st.ancora) await this.salvaCoord(chiave);
            // righe e totali con le ore nuove, quando non resta niente da salvare
            if (this.daRicaricare && ![...this.coord.values()].some(x => x.timer || x.inVolo)) {
                this.daRicaricare = false;
                await this.carica();
            }
            this.mostraStato();
        })();
        return st.inVolo;
    },

    async salvaInSospeso() {
        const attese = [];
        this.coord.forEach((st, chiave) => {
            if (st.timer || st.inVolo || (st.corrente !== null && st.corrente !== st.salvato && !st.errore)) attese.push(this.salvaCoord(chiave));
        });
        await Promise.all(attese);
    },

    inviaInUscita() {
        if (!this.dati) return;
        this.coord.forEach((st, chiave) => {
            if (!st.timer) return;
            clearTimeout(st.timer);
            st.timer = null;
            const corpo = this.corpoCoord(chiave);
            if (!corpo) return;
            fetch(`/api/napoli/lotti/${this.dati.lotto.id}/coordinamento`, {
                method: 'PUT', keepalive: true, credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo),
            }).then(r => (r.ok ? r.json() : null)).then((r) => {
                if (!r || !r.riga) return;
                st.salvato = r.riga.ore;
                st.corrente = null;
                this.ultimoSalvataggio = new Date();
                this.mostraStato();
            }).catch(() => { /* la pagina si sta chiudendo */ });
        });
    },

    /** Invio e frecce come in Rendicontazione: la casella delle ore del coordinatore sopra o sotto; Esc rimette il valore salvato. */
    tasti(e) {
        const input = e.target;
        if (e.key === 'Escape') {
            const st = this.coord.get(input.dataset.chiave);
            if (st && st.corrente !== null) {
                e.preventDefault();
                e.stopPropagation();
                clearTimeout(st.timer);
                st.timer = null;
                st.corrente = null;
                st.errore = null;
                input.value = st.salvato;
                this.aggiornaCoord(input.dataset.chiave);
                this.mostraStato();
            }
            return;
        }
        let passo = 0;
        if (e.key === 'Enter' || e.key === 'ArrowDown') passo = 1;
        else if (e.key === 'ArrowUp') passo = -1;
        else return;
        e.preventDefault();
        const caselle = [...this.el('fattura-contenuto').querySelectorAll('input.nf-coord')].filter(i => !i.disabled);
        const prossima = caselle[caselle.indexOf(input) + passo];
        this.salvaCoord(input.dataset.chiave);
        if (prossima) { prossima.focus(); prossima.select(); }
        else if (e.key === 'Enter') input.blur();
    },

    mostraStato(tipo) {
        const box = this.el('fattura-salvataggio');
        const testo = (stato, icona, scritta) => {
            box.className = ['auto-save-indicator', stato].filter(Boolean).join(' ');
            box.innerHTML = `${icona ? napoliSvg(icona, 14) : ''}<span>${escapeHtml(scritta)}</span>`;
        };
        if (tipo === 'in_sospeso') return testo('pending', '', 'Modifiche in sospeso…');
        if (tipo === 'salvo') return testo('saving', '', 'Salvataggio…');
        const st = [...this.coord.values()];
        if (st.some(x => x.timer || x.inVolo)) return testo('pending', '', 'Modifiche in sospeso…');
        const errori = st.filter(x => x.errore).length;
        const ora = this.ultimoSalvataggio
            ? this.ultimoSalvataggio.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' }) : null;
        if (errori) return testo('errore', NAPOLI_COORD_ICONA_ERRORE, errori === 1 ? '1 casella da correggere' : `${errori} caselle da correggere`);
        if (ora) return testo('saved', NAPOLI_COORD_ICONA_OK, `Salvato alle ${ora}`);
        return testo('', NAPOLI_COORD_ICONA_OK, 'Salvataggio automatico');
    },

    // ---------- copia dei testi ----------

    async copia(pulsante) {
        const testo = pulsante.dataset.testo || '';
        try {
            await navigator.clipboard.writeText(testo);
            showToast('Testo copiato: incollalo nel programma di fatturazione (Ctrl+V)', 'success');
        } catch (e) {
            // senza appunti (browser che non li permette): il testo si seleziona, Ctrl+C lo copia
            const dd = pulsante.closest('.nf-testo')?.querySelector('dd');
            if (dd) {
                const r = document.createRange();
                r.selectNodeContents(dd);
                const sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(r);
            }
            showToast('Il testo è selezionato: premi Ctrl+C per copiarlo', 'info');
        }
    },

    // ---------- rendi definitiva e riapri ----------

    async apriDefinitiva(chiave) {
        await this.salvaInSospeso();
        const p = this.prospettoDi(chiave);
        if (!p) return;
        if (!p.puo_rendere_definitiva) { showToast('Prima sistema le cose in rosso del prospetto.', 'warning'); return; }
        this.scelto = p;
        const form = this.el('form-definitiva');
        napoliPulisciErrori(form);
        this.el('definitiva-chi').textContent = `${p.numero ? `Contratto ${p.numero}` : ''} · ${p.grado_testo} · competenze ${p.periodo_testo} · da pagare ${p.totali.da_pagare} €`;
        const oggi = this.dati.oggi;
        this.el('definitiva-numero').value = (p.fattura && p.fattura.numero) || '';
        this.el('definitiva-data').value = (p.fattura && p.fattura.data) || oggi;
        this.el('definitiva-data').max = oggi;
        this.aggiornaScadenza();
        openModal('napoli-modal-definitiva');
        // dopo il fuoco che openModal mette sulla X (che riprova fino a 120 ms): il numero della fattura
        setTimeout(() => focusInFinestra(this.el('definitiva-numero')), 160);
    },

    aggiornaScadenza() {
        const p = this.scelto;
        const v = this.el('definitiva-data').value;
        const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v || '');
        if (!p || !m) { this.el('definitiva-scadenza').textContent = ''; return; }
        const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]) + p.giorni_pagamento);
        const testo = `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}/${d.getFullYear()}`;
        this.el('definitiva-scadenza').textContent = `Scadenza del pagamento: ${testo} (${p.giorni_pagamento} giorni dalla data della fattura).`;
    },

    async confermaDefinitiva() {
        const p = this.scelto;
        const form = this.el('form-definitiva');
        const numero = this.el('definitiva-numero');
        const data = this.el('definitiva-data');
        if (!napoliCampoObbligatorio(numero, 'Scrivi il numero della fattura emessa.')) return;
        if (!napoliCampoObbligatorio(data, 'Scrivi la data della fattura emessa.')) return;
        const pulsante = this.el('definitiva-conferma');
        setButtonLoading(pulsante, true);
        try {
            const r = await apiCall(`/api/napoli/lotti/${this.dati.lotto.id}/fatture/definitiva`, { method: 'POST', body: JSON.stringify({
                anno: this.dati.anno, mese: this.dati.mese, contratto_id: p.contratto_id, grado: p.grado,
                numero: numero.value.trim(), data: data.value, impronta: p.impronta,
            }) });
            closeModal('napoli-modal-definitiva');
            showToast(r.messaggio, 'success', 8000);
            await this.carica();
        } catch (e) {
            if (e.code === 'PROSPETTO_CAMBIATO' || e.code === 'FATTURA_BLOCCATA' || e.code === 'GIA_DEFINITIVA') {
                closeModal('napoli-modal-definitiva');
                showToast(e.message, 'warning', 10000);
                await this.carica();
            } else {
                napoliMostraErrore(e, form);
            }
        } finally {
            setButtonLoading(pulsante, false);
        }
    },

    apriRiapri(chiave) {
        const p = this.prospettoDi(chiave);
        if (!p || !p.fattura) return;
        this.scelto = p;
        const form = this.el('form-riapri');
        napoliPulisciErrori(form);
        this.el('riapri-titolo').textContent = `Riapri la fattura n. ${p.fattura.numero}`;
        this.el('riapri-chi').textContent = `Contratto ${p.numero} · ${p.grado_testo} · competenze ${p.periodo_testo}`;
        this.el('riapri-motivo').value = '';
        openModal('napoli-modal-riapri');
        setTimeout(() => focusInFinestra(this.el('riapri-motivo')), 160);
    },

    async confermaRiapri() {
        const p = this.scelto;
        const form = this.el('form-riapri');
        const motivo = this.el('riapri-motivo');
        if (!napoliCampoObbligatorio(motivo, 'Scrivi perché riapri la fattura.')) return;
        const pulsante = this.el('riapri-conferma');
        setButtonLoading(pulsante, true);
        try {
            const r = await apiCall(`/api/napoli/fatture/${p.fattura.id}/riapri`, { method: 'POST', body: JSON.stringify({ motivo: motivo.value.trim() }) });
            closeModal('napoli-modal-riapri');
            showToast(r.messaggio, 'success', 8000);
            await this.carica();
        } catch (e) {
            napoliMostraErrore(e, form);
        } finally {
            setButtonLoading(pulsante, false);
        }
    },
};

window.NapoliComune = NapoliComune;
window.NapoliProcedura = NapoliProcedura;
window.NapoliMese = NapoliMese;
window.NapoliCoordinatore = NapoliCoordinatore;
window.NapoliAnagrafiche = NapoliAnagrafiche;
window.NapoliImport = NapoliImport;
window.NapoliImpostazioni = NapoliImpostazioni;
window.NapoliPresenze = NapoliPresenze;
window.NapoliFattura = NapoliFattura;

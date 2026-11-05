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
 * - NapoliMese, NapoliAnagrafiche, NapoliImport e NapoliImpostazioni: le schede
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

/** Errore di un'API: il messaggio vicino al campo sbagliato (se il server lo dice) e in un avviso. */
function napoliMostraErrore(err, contenitore) {
    const messaggio = (err && err.message) || 'Operazione non riuscita: riprova.';
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
            return;
        }
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
            <p class="napoli-nota">L'anagrafica (alunni, operatori, scuole, coppie e PEI) si carica dal file Excel del coordinatore nella scheda <a href="/napoli/import">Importa</a> e si controlla o si corregge nella scheda <a href="/napoli/anagrafiche">Anagrafiche</a>. Presenze, fogli firma e fattura del mese arriveranno nella sezione Napoli con i prossimi aggiornamenti di Assisto.</p>`;
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
        if (r.vuota && !r.conteggi.operatori && !scheda) {
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
        const parametri = new URLSearchParams();
        Object.entries(f).forEach(([k, v]) => {
            if (v && (k === 'cerca' || NAPOLI_FILTRI_PARTE[parte].includes(k))) parametri.set(k, v);
        });
        const seq = ++this.seq;
        const box = this.el('elenco-tabella');
        try {
            const r = await apiCall(`/api/napoli/lotti/${lotto.id}/${parte}?${parametri}`);
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

window.NapoliComune = NapoliComune;
window.NapoliProcedura = NapoliProcedura;
window.NapoliMese = NapoliMese;
window.NapoliAnagrafiche = NapoliAnagrafiche;
window.NapoliImport = NapoliImport;
window.NapoliImpostazioni = NapoliImpostazioni;

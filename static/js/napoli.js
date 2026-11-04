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
 * - NapoliMese, NapoliImport e NapoliImpostazioni: le schede (Importa: il foglio presenze
 *   del mese con anteprima, scelte da confermare, importazione e "Annulla import").
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
        if (document.getElementById('confirm-dialog-overlay')) return;   // conferma gia' aperta
        let info;
        try {
            info = await apiCall('/api/napoli/annulla/ultima');
        } catch (e) {
            showToast(e.message || 'Annulla non disponibile', 'warning');
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
            `${info.azione.descrizione}. Modifica fatta il ${info.azione.quando}.`,
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
            <p class="napoli-nota">Il foglio presenze del mese (il file Excel del coordinatore) si importa dalla scheda <a href="/napoli/import">Importa</a>. Presenze, fogli firma e fattura del mese arriveranno nella sezione Napoli con i prossimi aggiornamenti di Assisto.</p>`;
    },
};

// ==================== scheda Importa (foglio presenze del mese) ====================

const NAPOLI_GRADI_SCUOLA = [
    ['inferiore', 'Grado inferiore'], ['superiore', 'Grado superiore'],
    ['misto', 'Misto (si sceglie per alunno)'], ['', 'Da decidere'],
];
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

/** "3 giorni nuovi, 1 cambiato": solo le voci con un numero diverso da zero. Ogni voce e'
 *  [numero, testo al plurale, testo al singolare (se diverso)]. */
function napoliElenco(voci) {
    const scritte = voci.filter(([n]) => n).map(([n, plurale, singolare]) =>
        `${napoliNumeroIt(n)} ${n === 1 && singolare ? singolare : plurale}`);
    return scritte.length ? scritte.join(', ') : '';
}

const NapoliImport = {
    file: null,           // {nome, dati (ArrayBuffer), dimensione}
    anteprima: null,      // ultima risposta (anteprima o confronto)
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
        this.el('btn-import-anteprima').addEventListener('click', () => this.chiedi('import'));
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
            else if (b.dataset.azione === 'anteprima') this.chiedi('import');
        });
        this.el('import-storico').addEventListener('click', (e) => {
            const b = e.target.closest('[data-annulla-import]');
            if (b) this.annullaImport(Number(b.dataset.annullaImport));
        });
    },

    /** Il file scelto si legge subito: se e' aperto in Excel su Windows il browser non lo
     *  puo' leggere, e lo si dice qui con parole semplici. */
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
            this.errore('Scegli il file Excel del foglio presenze (con il nome che finisce per .xlsx).');
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
        this.chiedi('import');
    },

    pulsanti(attivi) {
        this.el('btn-import-anteprima').disabled = !attivi || !this.file;
        this.el('btn-import-confronta').disabled = !attivi || !this.file;
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

    errore(messaggio, titolo = 'Il file non si può importare') {
        this.el('import-risultato').innerHTML = `
            <div class="card napoli-esito">
                <div class="alert alert-danger">
                    ${napoliSvg(NAPOLI_ICONE_STATO.manca, 22)}
                    <div><strong>${escapeHtml(titolo)}</strong><br>${escapeHtml(messaggio)}</div>
                </div>
            </div>`;
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
                ? 'Il file è troppo grande: controlla di aver scelto il foglio presenze del mese.'
                : 'Qualcosa non ha funzionato: riprova tra qualche secondo.'));
            err.status = risposta.status;
            err.code = corpo.code || null;
            err.data = corpo;
            throw err;
        }
        return corpo;
    },

    /** Anteprima (o solo confronto). aggiorna: dopo una scelta, la stessa anteprima ricalcolata. */
    async chiedi(modo, aggiorna = false) {
        if (!this.file || !NapoliComune.lotto) return;
        const seq = ++this.seq;
        const box = this.el('import-risultato');
        if (!aggiorna) {
            this.scelte = {};
            box.innerHTML = `<div class="card napoli-esito"><div class="loading"><div class="spinner"></div></div>
                <p class="napoli-attesa">${modo === 'confronto' ? 'Confronto il file con Assisto…' : 'Leggo il file e preparo l\'anteprima…'}</p></div>`;
        } else {
            box.querySelector('.napoli-anteprima')?.classList.add('napoli-in-aggiornamento');
        }
        this.pulsanti(false);
        try {
            const r = await this.invia('/api/napoli/import/anteprima', { modo, scelte: JSON.stringify(this.scelte) });
            if (seq !== this.seq) return;
            this.anteprima = r;
            if (modo === 'confronto') this.disegnaConfronto(r);
            else this.disegnaAnteprima(r, aggiorna);
        } catch (e) {
            if (seq === this.seq) this.errore(e.message);
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
        if (tipo === 'qualifica') (s.qualifiche = s.qualifiche || {})[el.dataset.chiave] = el.value;
        else if (tipo === 'grado') (s.gradi = s.gradi || {})[el.dataset.chiave] = el.value;
        else if (tipo === 'ambigua') (s.ore_ambigue = s.ore_ambigue || {})[el.dataset.chiave] = el.value;
        else if (tipo === 'sovrascrivi') s.sovrascrivi_manuali = el.checked;
        else if (tipo === 'subentro' || tipo === 'chiusura') {
            const chiave = tipo === 'subentro' ? 'subentri' : 'chiusure';
            s[chiave] = [...this.el('import-risultato').querySelectorAll(`[data-scelta="${tipo}"]:checked`)].map(x => Number(x.value));
        }
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.chiedi('import', true), 350);
    },

    /** Le scelte gia' fatte (o proposte) nell'anteprima diventano quelle da mandare. */
    ricordaScelte(a) {
        const s = this.scelte;
        s.qualifiche = Object.fromEntries((a.qualifiche || []).filter(q => q.figura).map(q => [q.testo, q.figura]));
        s.gradi = Object.fromEntries((a.scuole_nuove || []).map(x => [x.chiave, x.grado || '']));
        s.ore_ambigue = Object.fromEntries((a.ore_ambigue || []).filter(x => x.scelta).map(x => [x.chiave, x.scelta]));
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
        box.innerHTML = `
            <section class="card napoli-anteprima" aria-labelledby="titolo-anteprima">
                <div class="card-header">
                    <div>
                        <h2 class="card-title" id="titolo-anteprima">Anteprima: foglio presenze di ${escapeHtml(a.file.mese_testo)}</h2>
                        <p class="napoli-sottotitolo">${escapeHtml(a.file.nome)} · foglio «${escapeHtml(a.file.foglio)}» · ${escapeHtml(a.lotto.nome)} · <strong>niente è ancora salvato</strong></p>
                    </div>
                    <span class="badge" id="import-bollino"></span>
                </div>
                <div class="card-body">
                    ${this.htmlReimport(a)}
                    <div class="napoli-numeri">
                        ${this.numero(napoliNumeroIt(c.righe), 'righe (coppie operatore-alunno)')}
                        ${this.numero(napoliNumeroIt(c.operatori), 'operatori')}
                        ${this.numero(napoliNumeroIt(c.alunni), 'alunni')}
                        ${this.numero(escapeHtml(a.totale.ore), `ore nel file (${escapeHtml(a.totale.hhmm)})`)}
                    </div>
                    ${this.htmlBloccanti(a)}
                    ${this.htmlDaConfermare(a)}
                    ${this.htmlOre(a)}
                    ${this.htmlCambia(a)}
                    ${this.htmlAvvisi(a)}
                </div>
                <div class="napoli-barra-import">
                    <p class="napoli-barra-testo" id="import-motivo"></p>
                    <div class="napoli-barra-pulsanti">
                        <button type="button" class="btn btn-secondary" data-azione="lascia">Lascia perdere</button>
                        <button type="button" class="btn btn-primary" data-azione="importa" id="btn-importa">Importa ${escapeHtml(a.file.mese_testo)}</button>
                    </div>
                </div>
            </section>`;
        this.statoImporta();
        if (aggiorna) {
            window.scrollTo(0, scroll);
            const el = attivo && box.querySelector(attivo);
            if (el) el.focus({ preventScroll: true });
        } else {
            box.querySelector('.napoli-anteprima').scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    },

    numero(valore, etichetta) {
        return `<div class="napoli-numero-box"><span class="napoli-numero-valore">${valore}</span><span class="napoli-numero-etichetta">${escapeHtml(etichetta)}</span></div>`;
    },

    htmlReimport(a) {
        if (a.mese_chiuso) return '';
        if (!a.reimport) return '';
        const quando = napoliDataOra(a.reimport.data);
        if (a.reimport.stesso_file || a.nessun_cambiamento) {
            return `<div class="alert alert-info napoli-alert">${napoliSvg(NAPOLI_ICONE_STATO.ok, 20)}<div><strong>${escapeHtml(napoliMaiuscola(a.file.mese_testo))} è già stato importato il ${escapeHtml(quando)}.</strong> ${a.nessun_cambiamento ? 'Il file non cambia niente in Assisto: non serve importarlo di nuovo.' : 'Ci sono delle differenze: qui sotto vedi cosa cambia.'}</div></div>`;
        }
        return `<div class="alert alert-warning napoli-alert">${napoliSvg(NAPOLI_ICONE_STATO.avviso, 20)}<div><strong>${escapeHtml(napoliMaiuscola(a.file.mese_testo))} è già stato importato il ${escapeHtml(quando)}</strong> (file ${escapeHtml(a.reimport.nome_file || '')}). Importando di nuovo si sostituiscono solo le ore importate prima; le ore scritte a mano in Assisto non si toccano, se non lo scegli tu qui sotto.</div></div>`;
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

    htmlBloccanti(a) {
        if (!a.bloccanti.length) return '';
        return `
            <div class="napoli-blocco napoli-blocco-danger">
                <h3>Da correggere prima di importare</h3>
                <p class="napoli-intro">Le qualifiche si collegano qui sotto, in «Da confermare». Il resto si corregge nel file: correggilo in Excel, salvalo, chiudilo e sceglilo di nuovo qui sopra.</p>
                ${a.bloccanti.map(g => this.htmlGruppo(g, true)).join('')}
            </div>`;
    },

    htmlDaConfermare(a) {
        const parti = [];
        const s = this.scelte;
        if (a.qualifiche.length) {
            parti.push(`
                <div class="napoli-parte-conferma">
                    <h4>Qualifiche nuove</h4>
                    <p class="napoli-intro">Queste qualifiche non sono ancora in Assisto: scegli tu la figura professionale di ognuna (quando il programma riconosce la qualifica, nella tendina la figura è indicata come «proposta»). La scelta resta salvata per i prossimi mesi.</p>
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
            parti.push(`
                <div class="napoli-parte-conferma napoli-conferma-obbligatoria">
                    <h4>${escapeHtml(conf.titolo)}</h4>
                    <p class="napoli-intro">${escapeHtml(conf.testo)}</p>
                    <ul class="napoli-elenco">${conf.voci.map(v => `<li>${escapeHtml(v.testo)} <span class="napoli-vuoto">(righe ${v.righe.join(', ')})</span></li>`).join('')}</ul>
                    <label class="napoli-scelta napoli-ho-controllato"><input type="checkbox" value="${escapeHtml(conf.codice)}" data-scelta="conferma"${(s.conferme || []).includes(conf.codice) ? ' checked' : ''}> <strong>Ho controllato</strong></label>
                </div>`);
        });
        if (a.scuole_nuove.length) {
            const daDecidere = a.scuole_nuove.filter(x => !x.grado).length;
            parti.push(`
                <details class="napoli-parte-conferma"${daDecidere ? ' open' : ''}>
                    <summary><h4>Scuole nuove (${a.scuole_nuove.length})${daDecidere ? ` <span class="badge badge-warning">${daDecidere} senza grado</span>` : ''}</h4></summary>
                    <p class="napoli-intro">Il grado decide in quale fattura vanno le ore (grado inferiore o superiore). È proposto dal codice meccanografico: controllalo. Per le scuole senza grado le ore restano «da decidere» e la fattura aspetta.</p>
                    <div class="table-container"><table class="table napoli-tabella-compatta">
                        <thead><tr><th scope="col">Scuola</th><th scope="col">Codice</th><th scope="col">Municipalità</th><th scope="col">Righe</th><th scope="col">Grado</th></tr></thead>
                        <tbody>${a.scuole_nuove.map(x => `
                            <tr><td>${escapeHtml(x.nome)}</td><td>${escapeHtml(x.codice) || '<span class="napoli-vuoto">senza codice</span>'}</td>
                                <td>${x.municipalita ?? '<span class="napoli-vuoto">manca</span>'}</td><td>${x.n_righe}</td>
                                <td><select class="form-control" data-scelta="grado" data-chiave="${escapeHtml(x.chiave)}" aria-label="Grado di ${escapeHtml(x.nome)}">
                                    ${NAPOLI_GRADI_SCUOLA.map(([v, t]) => `<option value="${v}"${(x.grado || '') === v ? ' selected' : ''}>${t}${v && v === x.grado_proposto ? ' (proposto)' : ''}</option>`).join('')}
                                </select></td></tr>`).join('')}</tbody>
                    </table></div>
                </details>`);
        }
        if (a.subentri.length) {
            parti.push(`
                <div class="napoli-parte-conferma">
                    <h4>Cambi di operatore</h4>
                    <p class="napoli-intro">Un sostituto comincia durante il mese e il titolare non ha più ore da quel giorno: si propone di chiudere la coppia del titolare. Togli la spunta se il titolare tornerà.</p>
                    ${a.subentri.map(x => `<label class="napoli-scelta napoli-scelta-riga"><input type="checkbox" value="${x.riga}" data-scelta="subentro"${s.subentri.includes(x.riga) ? ' checked' : ''}> ${escapeHtml(x.testo)}</label>`).join('')}
                </div>`);
        }
        if (a.chiusure.length || a.coppie_del_mese.length) {
            parti.push(`
                <div class="napoli-parte-conferma">
                    <h4>Coppie che nel file non ci sono più</h4>
                    ${a.chiusure.length ? `<p class="napoli-intro">Erano attive il mese prima ma in questo file non compaiono. Spunta quelle da chiudere (finiscono l'ultimo giorno del mese prima); le altre restano aperte.</p>
                    ${a.chiusure.map(x => `<label class="napoli-scelta napoli-scelta-riga"><input type="checkbox" value="${x.id}" data-scelta="chiusura"${s.chiusure.includes(x.id) ? ' checked' : ''}> ${escapeHtml(x.testo)}</label>`).join('')}` : ''}
                    ${a.coppie_del_mese.length ? `<p class="napoli-intro">Queste coppie cominciano in questo mese ma nel file non ci sono: restano in Assisto senza le ore del file. Se sono state create dall'import di prima con una riga sbagliata, annulla quell'import (nell'elenco in fondo alla pagina) e importa di nuovo questo file.</p>
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

    htmlOre(a) {
        const righe = a.ore_per_figura;
        if (!righe.length) return '';
        const somma = (g) => righe.reduce((n, x) => n + x.per_grado[g], 0);
        const ore = (min) => (min ? (min / 60).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—');
        const daDecidere = somma('da_decidere');
        return `
            <div class="napoli-blocco">
                <h3>Ore per figura e per grado</h3>
                <p class="napoli-intro">Come le righe della fattura. Il grado viene dalla scuola${daDecidere ? ': le ore «da decidere» sono di scuole senza grado (scegli il grado qui sopra)' : ''}.${this.testoEsclusi(a)}</p>
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
                        <td class="napoli-numero">${ore(daDecidere)}</td><td class="napoli-numero"><strong>${escapeHtml(a.totale_importato.ore)}</strong></td></tr></tfoot>
                </table></div>
            </div>`;
    },

    /** Cosa non e' contato nelle ore della tabella (righe che non si importano, celle da correggere). */
    testoEsclusi(a) {
        const c = a.conteggi;
        const esclusi = napoliElenco([[c.righe_escluse, 'righe che non si importano (per esempio quelle da correggere o del coordinatore)', 'riga che non si importa (per esempio da correggere o del coordinatore)'],
            [c.celle_escluse, 'celle da correggere', 'cella da correggere']]);
        return esclusi ? ` Non sono contate: ${esclusi}.` : '';
    },

    htmlCambia(a) {
        const c = a.conteggi;
        const p = c.presenze;
        const giorni = napoliElenco([[p.nuove, 'nuovi', 'nuovo'], [p.cambiate, 'cambiati (ore importate prima)', 'cambiato (ore importate prima)'],
            [p.da_programmato, 'completati (erano solo programmati)', 'completato (era solo programmato)'], [p.sovrascritte, 'scritti a mano e sostituiti', 'scritto a mano e sostituito'],
            [p.da_togliere, 'tolti (non sono più nel file)', 'tolto (non è più nel file)'], [p.uguali, 'già uguali', 'già uguale']]);
        const nuovi = napoliElenco([[c.nuovi.scuole, 'scuole', 'scuola'], [c.nuovi.alunni, 'alunni', 'alunno'], [c.nuovi.operatori, 'operatori', 'operatore'],
            [c.nuovi.coppie, 'coppie operatore-alunno', 'coppia operatore-alunno'], [c.nuovi.pei, 'PEI (ore settimanali da progetto)'],
            [c.nuovi.qualifiche, 'qualifiche collegate a una figura', 'qualifica collegata a una figura']]);
        const aggiornati = napoliElenco([[c.aggiornati.coppie, 'coppie (date)', 'coppia (date)'], [c.aggiornati.pei, 'PEI (ore settimanali da progetto)'],
            [c.aggiornati.operatori, 'operatori (ore di contratto o codice fiscale)', 'operatore (ore di contratto o codice fiscale)'],
            [c.aggiornati.alunni, 'alunni (codice fiscale corretto)', 'alunno (codice fiscale corretto)'],
            [c.aggiornati.scuole, 'scuole (municipalità aggiunta)', 'scuola (municipalità aggiunta)'],
            [c.aggiornati.fogli, 'note dei fogli', 'nota di un foglio']]);
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
            </div>`;
    },

    htmlAvvisi(a) {
        if (!a.avvisi.length && !a.note.length) return '';
        const n = a.avvisi.reduce((t, g) => t + g.n, 0);
        return `
            <div class="napoli-blocco">
                ${a.avvisi.length ? `<h3>Da controllare (${napoliNumeroIt(n)})</h3>
                <p class="napoli-intro">Non impediscono di importare, ma conviene guardarli: apri una voce per vedere le righe del file.</p>
                ${a.avvisi.map(g => this.htmlGruppo(g, false)).join('')}` : ''}
                ${a.note.length ? `<details class="napoli-note-file"><summary>Altre cose che il programma ha già sistemato da solo (${a.note.length})</summary>
                    ${a.note.map(g => this.htmlGruppo(g, false)).join('')}</details>` : ''}
            </div>`;
    },

    /** Il pulsante Importa e il bollino in alto: si importa solo senza bloccanti, con le ore
     *  da confermare scelte, le conferme spuntate e qualcosa da cambiare. */
    statoImporta() {
        const a = this.anteprima;
        const b = this.el('btn-importa');
        const motivo = this.el('import-motivo');
        const bollino = this.el('import-bollino');
        if (!a || !b) return;
        const mancano = (a.conferme_richieste || []).filter(c => !(this.scelte.conferme || []).includes(c));
        const ore = a.ore_ambigue_da_scegliere || 0;
        let testo = '';
        let stato = ['badge-success', 'Si può importare'];
        if (a.mese_chiuso) {
            testo = 'Il mese del lotto è chiuso: riaprilo prima di importare.';
            stato = ['badge-danger', 'Mese chiuso'];
        } else if (a.bloccanti.length) {
            testo = 'Prima correggi il file (parte «Da correggere»).';
            stato = ['badge-danger', `${napoliNumeroIt(a.bloccanti.reduce((n, g) => n + g.n, 0))} da correggere`];
        } else if (a.nessun_cambiamento) {
            testo = 'Il file non cambia niente in Assisto.';
            stato = ['badge-success', 'Niente di nuovo'];
        } else if (ore || mancano.length) {
            testo = [ore ? 'Scegli come leggere le ore nella parte «Ore da confermare».' : '',
                mancano.length ? 'Spunta «Ho controllato» nella parte «Da confermare».' : ''].filter(Boolean).join(' ');
            stato = ['badge-warning', 'Da confermare'];
        } else {
            testo = 'Prima di importare viene fatta da sola una copia di sicurezza del database.';
        }
        b.disabled = stato[1] !== 'Si può importare';
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
        showConfirmDialog(`Importare il foglio presenze di ${a.file.mese_testo}?`,
            `${napoliNumeroIt(c.righe_importate)} righe e ${a.totale_importato.ore} ore nel lotto ${a.lotto.nome}. Prima viene fatta da sola una copia di sicurezza del database; se poi qualcosa non va, «Annulla import» rimette tutto com'era.`,
            () => this.conferma(),
            { confirmText: `Importa ${a.file.mese_testo}`, cancelText: 'Non ancora', type: 'info' });
    },

    async conferma() {
        const a = this.anteprima;
        const b = this.el('btn-importa');
        setButtonLoading(b, true);
        try {
            const r = await this.invia('/api/napoli/import/conferma', {
                sha256: a.file.sha256, versione_dati: a.versione_dati, scelte: JSON.stringify(this.scelte),
            });
            showToast(r.nessun_cambiamento ? r.messaggio
                : `${r.messaggio}. Se c'è un errore, «Annulla import» (o Ctrl+Z) rimette tutto com'era.`, 'success', 9000);
            this.mostraEsito(r, a);
            await this.caricaStorico();
        } catch (e) {
            if (e.code === 'FILE_CAMBIATO' || e.code === 'ANTEPRIMA_SUPERATA') {
                showToast(`${e.message} L'anteprima è stata rifatta: controllala e premi di nuovo Importa.`, 'warning', 10000);
                await this.chiedi('import', true);
            } else {
                showToast(e.message, 'error', 10000);
                if (e.code === 'IMPORT_BLOCCATO' || e.code === 'DA_CONFERMARE') await this.chiedi('import', true);
            }
        } finally {
            const ancora = this.el('btn-importa');
            if (ancora) { setButtonLoading(ancora, false); this.statoImporta(); }
        }
    },

    mostraEsito(r, a) {
        const p = r.esito.presenze;
        const n = r.esito.nuovi;
        this.file = null;
        this.anteprima = null;
        this.scelte = {};
        this.el('import-file-zona').hidden = false;
        this.el('import-file-scelto').hidden = true;
        this.pulsanti(true);
        this.el('import-risultato').innerHTML = `
            <section class="card napoli-esito">
                <div class="alert alert-success napoli-alert">
                    ${napoliSvg(NAPOLI_ICONE_STATO.ok, 22)}
                    <div><strong>${escapeHtml(r.messaggio)}</strong><br>
                        ${r.nessun_cambiamento ? '' : escapeHtml(`Giorni: ${napoliElenco([[p.nuove, 'nuovi', 'nuovo'], [p.cambiate, 'cambiati', 'cambiato'], [p.da_programmato, 'completati', 'completato'], [p.sovrascritte, 'sostituiti', 'sostituito'], [p.da_togliere, 'tolti', 'tolto'], [p.uguali, 'già uguali', 'già uguale']]) || 'nessuno'}. Nuovi: ${napoliElenco([[n.scuole, 'scuole', 'scuola'], [n.alunni, 'alunni', 'alunno'], [n.operatori, 'operatori', 'operatore'], [n.coppie, 'coppie', 'coppia']]) || 'nessuno'}.`)}
                        ${r.copia ? '<br><span class="napoli-vuoto">Prima dell\'import è stata fatta da sola una copia di sicurezza del database: la trovi nel Profilo, in «Backup e sicurezza dati».</span>' : ''}</div>
                </div>
                <div class="napoli-azioni-modulo">
                    <button type="button" class="btn btn-secondary" data-azione="altro-file">Importa un altro file</button>
                </div>
            </section>`;
        this.el('import-risultato').querySelector('.napoli-esito').scrollIntoView({ behavior: 'smooth', block: 'start' });
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
                        <h2 class="card-title" id="titolo-confronto">Confronto con Assisto: ${escapeHtml(a.file.mese_testo)}</h2>
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
                    <p class="napoli-barra-testo">Per salvare le ore del file usa «Mostra l'anteprima» e poi «Importa».</p>
                    <div class="napoli-barra-pulsanti">
                        <button type="button" class="btn btn-secondary" data-azione="lascia">Chiudi il confronto</button>
                        <button type="button" class="btn btn-primary" data-azione="anteprima">Mostra l'anteprima</button>
                    </div>
                </div>
            </section>`;
        box.querySelector('.napoli-anteprima').scrollIntoView({ behavior: 'smooth', block: 'start' });
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
            box.innerHTML = '<p class="napoli-vuoto">Nessun import per questo lotto.</p>';
            return;
        }
        box.innerHTML = `
            <div class="table-container"><table class="table">
                <thead><tr><th scope="col">Mese</th><th scope="col">File</th><th scope="col">Importato il</th>
                    <th scope="col" class="text-right">Righe</th><th scope="col" class="text-right">Ore</th><th scope="col">Giorni</th><th scope="col" aria-label="Azioni"></th></tr></thead>
                <tbody>${this.storico.map(i => {
                    const p = i.presenze || {};
                    const classeRiga = i.annullato ? 'napoli-riga-annullata' : '';
                    return `<tr class="${classeRiga}">
                        <td><strong>${escapeHtml(i.mese_testo)}</strong>${i.annullato ? ' <span class="badge badge-sm badge-secondary">annullato</span>' : ''}</td>
                        <td class="napoli-nome-file">${escapeHtml(i.nome_file)}</td>
                        <td>${escapeHtml(napoliDataOra(i.data))}</td>
                        <td class="napoli-numero">${napoliNumeroIt(i.righe)}</td>
                        <td class="napoli-numero">${escapeHtml(i.ore)}</td>
                        <td>${escapeHtml(napoliElenco([[p.nuove, 'nuovi', 'nuovo'], [p.cambiate, 'cambiati', 'cambiato'], [p.da_togliere, 'tolti', 'tolto']]) || '—')}</td>
                        <td class="napoli-azioni">${i.annullabile ? `<button type="button" class="btn btn-sm btn-secondary" data-annulla-import="${i.id}">Annulla import</button>` : ''}</td>
                    </tr>`;
                }).join('')}</tbody>
            </table></div>
            <p class="napoli-nota">Si può annullare solo l'ultimo import del lotto, se il mese non è chiuso.</p>`;
    },

    annullaImport(id) {
        const i = this.storico.find(x => x.id === id);
        if (!i) return;
        showConfirmDialog(`Annullare l'import di ${i.mese_testo}?`,
            "Si tolgono le ore, le coppie, gli alunni, gli operatori e le scuole creati da questo import, e tornano com'erano le ore che aveva cambiato. Prima viene fatta da sola una copia di sicurezza del database.",
            async () => {
                try {
                    const r = await apiCall(`/api/napoli/import/${id}/annulla`, { method: 'POST', body: '{}' });
                    showToast(r.messaggio, 'success', 8000);
                    this.azzera(true);
                    await this.caricaStorico();
                } catch (e) {
                    showToast(e.message, 'error', 10000);
                }
            }, { confirmText: 'Annulla l\'import', cancelText: 'Lascia com\'è', type: 'danger' });
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
        this.el('qualifica-figura').innerHTML = NapoliComune.opzioniFigure(q ? q.figura : 'ASACOM');
        this.el('qualifica-testo').value = q ? q.testo : '';
        this.el('qualifica-testo').readOnly = !!q;
        openModal('napoli-modal-qualifica');
    },

    async salvaQualifica() {
        const form = this.el('form-qualifica');
        napoliPulisciErrori(form);
        if (!napoliCampoObbligatorio(this.el('qualifica-testo'), 'Scrivi la qualifica come compare nel file.')) return;
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
window.NapoliImport = NapoliImport;
window.NapoliImpostazioni = NapoliImpostazioni;

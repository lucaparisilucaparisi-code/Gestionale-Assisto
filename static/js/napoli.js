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
 * - NapoliMese e NapoliImpostazioni: le due schede.
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

    opzioniFigure(scelta) {
        return (this.figure || []).map(f =>
            `<option value="${escapeHtml(f.codice)}"${f.codice === scelta ? ' selected' : ''}>${escapeHtml(f.nome)}${napoliDescrizioneDiversa(f) ? ` (${escapeHtml(f.descrizione)})` : ''}</option>`).join('');
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
            <p class="napoli-nota">Presenze, fogli firma e fattura del mese arriveranno nella sezione Napoli con i prossimi aggiornamenti di Assisto.</p>`;
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
window.NapoliImpostazioni = NapoliImpostazioni;

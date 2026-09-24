// ==================== DASHBOARD ====================
// Logica della dashboard: stato del mese, cose da fare, numeri e trend.
// Helper condivisi (apiCall, animateCounter, MESI, ChartManager, ...) sono in app.js.

let _ultimoTrend = null;   // dati del trend, per ridisegnarlo al cambio di tema
// Numero del caricamento in corso: cambiando in fretta commessa e mese, le
// risposte di un caricamento vecchio non devono sovrascrivere quelle nuove.
let _caricamento = 0;
const _superato = (n) => n !== _caricamento;

document.addEventListener('DOMContentLoaded', async () => {
    await initDashboardFilters();
    await loadDashboardData();
});

async function initDashboardFilters() {
    // Popola filtro commessa
    await populateCommesseSelect('filter-commessa', true);

    // Popola filtro periodo (mesi dell'anno scolastico corrente)
    const periodoSelect = document.getElementById('filter-periodo');
    if (periodoSelect) {
        const annoScolastico = getCurrentAnnoScolastico();
        const [annoInizio, annoFine] = annoScolastico.split('-').map(Number);
        const now = new Date();
        const currentMese = now.getMonth() + 1;
        const currentAnno = now.getFullYear();

        let options = '<option value="">Anno completo</option>';
        MESI_SCOLASTICI.forEach(mese => {
            const anno = mese >= 9 ? annoInizio : annoFine;
            const selected = (mese === currentMese && anno === currentAnno) ? 'selected' : '';
            options += `<option value="${mese}-${anno}" ${selected}>${MESI[mese]} ${anno}</option>`;
        });
        periodoSelect.innerHTML = options;
    }

    document.getElementById('filter-commessa')?.addEventListener('change', () => loadDashboardData());
    document.getElementById('filter-periodo')?.addEventListener('change', () => loadDashboardData());
    document.getElementById('btn-refresh-dashboard')?.addEventListener('click', () => loadDashboardData());
}

function getActiveFilters() {
    const commessa = document.getElementById('filter-commessa')?.value || '';
    const periodo = document.getElementById('filter-periodo')?.value || '';
    let anno = null, mese = null;
    if (periodo) {
        [mese, anno] = periodo.split('-').map(Number);
    }
    return { commessa, anno, mese };
}

// Periodo effettivo: filtro selezionato oppure mese corrente
function getPeriodoCorrente() {
    const filters = getActiveFilters();
    const now = new Date();
    return {
        commessa: filters.commessa,
        anno: filters.anno || now.getFullYear(),
        mese: filters.mese || (now.getMonth() + 1)
    };
}

/** Querystring con anno, mese e (se scelta) commessa del periodo mostrato. */
function _qsPeriodo() {
    const { anno, mese, commessa } = getPeriodoCorrente();
    const qs = new URLSearchParams({ anno, mese });
    if (commessa) qs.set('commessa', commessa);
    return qs.toString();
}

async function loadDashboardData() {
    // Ogni blocco si carica per conto suo: un errore in uno non ferma gli altri
    // (prima un'eccezione nei grafici lasciava 'Ultimo aggiornamento: --').
    const filters = getActiveFilters();
    const n = ++_caricamento;
    aggiornaSottotitoliReport();
    await Promise.allSettled([
        loadNumeri(filters, n),
        loadStatoMese(n),
        loadDaFare(n),
        loadTrend(n),
    ]);
    if (_superato(n)) return;
    // Banner nuovo anno scolastico (giugno-ottobre, se non ancora preparato)
    loadBannerNuovoAnno();
    updateLastRefresh();
}

// ==================== NUMERI DEL SERVIZIO ====================

async function loadNumeri(filters, n = _caricamento) {
    try {
        const qs = filters.commessa ? `?commessa=${encodeURIComponent(filters.commessa)}` : '';
        const urlUtenti = filters.commessa ? `/api/utenti?commessa=${encodeURIComponent(filters.commessa)}` : '/api/utenti';
        const [stats, commesse, base, utenti] = await Promise.all([
            apiCall(`/api/stats/filtered${qs}`),
            apiCall('/api/commesse'),
            apiCall('/api/stats'),
            apiCall(urlUtenti),
        ]);
        if (_superato(n)) return;
        animateCounter(document.getElementById('stat-utenti'), stats.num_utenti || 0, 800);
        animateCounter(document.getElementById('stat-scuole'), stats.num_scuole || 0, 800);

        // Checklist di primo avvio: mostrata solo con anagrafica vuota (senza filtri)
        const onboarding = document.getElementById('onboarding-card');
        if (onboarding) {
            onboarding.style.display =
                (!filters.commessa && (stats.num_utenti || 0) === 0) ? '' : 'none';
        }

        // Commesse attive: con un filtro conta solo quella scelta
        const attive = commesse.filter(c => c.attiva && (!filters.commessa || c.nome === filters.commessa));
        animateCounter(document.getElementById('stat-commesse'), attive.length, 800);
        const labelCommesse = document.getElementById('stat-commesse-label');
        if (labelCommesse) labelCommesse.textContent = attive.length === 1 ? 'commessa attiva' : 'commesse attive';

        // Utenti per commessa, col colore scelto in Impostazioni > Commesse
        // (sostituisce la ciambella, identica a quella di Statistiche)
        const dettaglio = document.getElementById('stat-utenti-commesse');
        if (dettaglio) {
            const perCommessa = base.utenti_per_commessa || {};
            const voci = filters.commessa ? [] : commesse
                .filter(c => (perCommessa[c.nome] || 0) > 0)
                .map(c => `<span class="dash-numero-commessa"><span class="legend-dot" style="background:${escapeHtml(c.colore || 'var(--primary)')}"></span>${escapeHtml(c.nome)} ${perCommessa[c.nome]}</span>`);
            dettaglio.innerHTML = voci.length > 1 ? voci.join('') : '';
        }

        const monteOreTotale = utenti.reduce((sum, u) => sum + (u.monte_ore_settimanale || 0), 0);
        animateCounter(document.getElementById('stat-monte-ore'), Math.round(monteOreTotale), 1000);
    } catch (error) {
        console.error('Errore caricamento numeri dashboard:', error);
    }
}

// ==================== STATO DEL MESE ====================

// Quanti nomi mostrare: gli altri si vedono in Rendicontazione (niente scorrimento interno)
const DA_COMPLETARE_VISIBILI = 5;

/** Il mese mostrato non e' ancora finito (le ore si registrano a fine mese). */
function _meseInCorso(anno, mese) {
    const oggi = new Date();
    const chiave = anno * 12 + mese;
    return chiave >= oggi.getFullYear() * 12 + (oggi.getMonth() + 1);
}

async function loadStatoMese(n = _caricamento) {
    const { anno, mese, commessa } = getPeriodoCorrente();
    const nomeEl = document.getElementById('stato-mese-nome');
    const percentEl = document.getElementById('stato-mese-percent');
    const barEl = document.getElementById('stato-mese-bar');
    const testoEl = document.getElementById('stato-mese-testo');
    const listaEl = document.getElementById('lista-da-completare');
    if (!nomeEl) return;

    nomeEl.textContent = `${MESI[mese]} ${anno}`;
    const urlMese = `/rendicontazione?anno=${anno}&mese=${mese}`;
    document.getElementById('stato-mese-link')?.setAttribute('href', urlMese);

    try {
        const qsTot = new URLSearchParams({ anno, mese });
        if (commessa) qsTot.set('commessa', commessa);
        const [elenco, statsTot, anniConCalendario] = await Promise.all([
            apiCall(`/api/stats/utenti-da-completare/${anno}/${mese}`),
            apiCall(`/api/stats/filtered?${qsTot}`),
            // stesso elenco del menu "Anno scolastico" della Rendicontazione
            apiCall('/api/anni-scolastici').catch(() => null),
        ]);
        if (_superato(n)) return;
        const daCompletare = commessa ? elenco.filter(u => u.commessa === commessa) : elenco;
        const totale = statsTot.num_utenti || 0;

        // La Rendicontazione apre solo i mesi di scuola degli anni che hanno il
        // calendario: per gli altri (es. settembre, prima di "Prepara il calendario")
        // le righe non sono link, perche' porterebbero a un altro mese.
        const annoScol = _annoScolasticoPeriodo();
        const meseDiScuola = MESI_SCOLASTICI.includes(mese);
        const apribile = meseDiScuola && (!anniConCalendario || anniConCalendario.includes(annoScol));

        const completati = Math.max(totale - daCompletare.length, 0);
        const percent = totale > 0 ? Math.round((completati / totale) * 100) : 0;

        // Mese ancora in corso: 0% e' normale (le ore si registrano a fine mese),
        // quindi grigio e barra blu; il rosso resta ai mesi gia' finiti.
        const inCorso = _meseInCorso(anno, mese);
        let livello = percent >= 100 ? 'success' : percent >= 50 ? 'warning' : 'danger';
        if (inCorso && percent < 100) livello = null;
        percentEl.textContent = `${percent}%`;
        percentEl.className = 'badge ' + (livello ? `badge-${livello}` : 'badge-secondary');
        percentEl.title = inCorso && percent < 100 ? 'Mese in corso' : '';
        barEl.style.width = `${percent}%`;
        barEl.style.background = livello ? `var(--${livello})` : 'var(--primary)';
        testoEl.textContent = totale > 0
            ? `${completati} di ${totale} utenti rendicontati — ${daCompletare.length} senza ore`
            : 'Nessun utente attivo nel periodo selezionato';

        if (daCompletare.length === 0) {
            listaEl.innerHTML = totale > 0
                ? `<p class="da-completare-ok">✓ Tutti gli utenti hanno le ore registrate</p>`
                : '';
        } else {
            // Ogni riga apre la Rendicontazione del mese gia' filtrata su quell'utente
            let html = daCompletare.slice(0, DA_COMPLETARE_VISIBILI).map(u => {
                const nome = `${u.nome} ${u.cognome}`;
                const scuola = u.scuola || '';
                const tag = apribile ? 'a' : 'div';
                const link = apribile
                    ? ` href="${urlMese}&cerca=${encodeURIComponent(nome)}" title="Apri ${escapeHtml(nome)} in Rendicontazione"`
                    : '';
                return `
                <${tag} class="da-completare-item"${link}>
                    <span class="da-completare-info">
                        <span class="da-completare-nome">${escapeHtml(nome)}</span>
                        <span class="da-completare-scuola" title="${escapeHtml(scuola)}">${escapeHtml(u.commessa)} · ${escapeHtml(scuola)}</span>
                    </span>
                    <span class="badge badge-secondary da-completare-monte" title="Monte ore settimanale">${formatNumero(u.monte_ore)} h/sett.</span>
                </${tag}>`;
            }).join('');
            if (apribile) {
                html += `<a class="da-completare-more" href="${urlMese}&senza_ore=1">${
                    daCompletare.length > DA_COMPLETARE_VISIBILI
                        ? `Vedi tutti i ${daCompletare.length} in Rendicontazione`
                        : 'Apri in Rendicontazione'} →</a>`;
            } else if (meseDiScuola) {
                // Al posto di "Vedi tutti": il passo che manca per poter registrare le ore
                html += `<p class="da-completare-avviso">Per registrare le ore di ${MESI[mese]} ${anno} serve prima
                    il calendario ${escapeHtml(annoScol)}. <a href="/calendario" data-prepara-anno="${escapeHtml(annoScol)}">Prepara il calendario →</a></p>`;
            } else {
                html += `<p class="da-completare-avviso">${MESI[mese]} non è un mese di scuola: in Rendicontazione le ore si registrano da settembre a giugno.</p>`;
            }
            listaEl.innerHTML = html;
            // Se e' l'anno del riquadro "Prepara il nuovo anno", il passo si fa da qui
            // (stessa conferma del pulsante "1 · Prepara il calendario"); altrimenti Calendario
            listaEl.querySelector('[data-prepara-anno]')?.addEventListener('click', (e) => {
                if (_annoWizard === annoScol) {
                    e.preventDefault();
                    preparaNuovoAnno(annoScol);
                }
            });
        }
    } catch (error) {
        console.error('Errore caricamento stato mese:', error);
        testoEl.textContent = 'Dati non disponibili';
    }
}

// ==================== DA FARE (avvisi + controlli dei dati) ====================

// Gia' detti dallo Stato del mese: non si ripetono qui
const DA_FARE_ESCLUSI = new Set(['senza_ore', 'completamento', 'ore_mancanti',
    // stessi utenti degli avvisi "sotto il 50%" / "sopra il 150%" della media
    'differenze_elevate']);
const LIVELLI = { danger: 0, warning: 1, info: 2 };
// Avvisi senza un collegamento proprio: dove si vedono tutti gli utenti citati
const AZIONI_PREDEFINITE = { budget: ['/utenti', 'Apri gli utenti'], documenti: ['/utenti', 'Apri gli utenti'] };
const ICONE_LIVELLO = {
    warning: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />',
    danger: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />',
    info: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />'
};

/** Voce dell'elenco "Da fare" nello stesso formato per avvisi e controlli. */
function _vocePerDaFare(livello, titolo, messaggio, nomi, totaleNomi, azione, etichettaAzione) {
    return { livello: LIVELLI[livello] !== undefined ? livello : 'info', titolo, messaggio, nomi: nomi || [], totaleNomi: totaleNomi || 0, azione, etichettaAzione };
}

async function loadDaFare(n = _caricamento) {
    const lista = document.getElementById('da-fare-list');
    const contatore = document.getElementById('da-fare-count');
    if (!lista) return;
    const { anno, mese } = getPeriodoCorrente();
    const qs = _qsPeriodo();
    const urlMese = `/rendicontazione?anno=${anno}&mese=${mese}`;

    const [avvisi, controlli] = await Promise.allSettled([
        apiCall(`/api/alerts?${qs}`),
        apiCall(`/api/stats/validazione?${qs}`),
    ]);
    if (_superato(n)) return;

    const voci = [];
    if (avvisi.status === 'fulfilled') {
        (avvisi.value.alerts || []).filter(a => !DA_FARE_ESCLUSI.has(a.categoria)).forEach(a => {
            const [azionePred, etichettaPred] = AZIONI_PREDEFINITE[a.categoria] || [];
            const azione = a.action === '/rendicontazione' ? urlMese : (a.action || azionePred);
            voci.push(_vocePerDaFare(a.type, a.title, a.message, a.utenti, a.count, azione, a.action_label || etichettaPred));
        });
    }
    if (controlli.status === 'fulfilled') {
        (controlli.value.anomalie || []).filter(a => !DA_FARE_ESCLUSI.has(a.categoria)).forEach(a => {
            const nomi = (a.dettagli || []).map(d => d.nome || d.commessa || '').filter(Boolean);
            const azione = a.categoria === 'commesse_vuote' ? '/commesse' : urlMese;
            voci.push(_vocePerDaFare(a.tipo, a.titolo, a.messaggio, nomi, a.conteggio, azione, 'Verifica'));
        });
    }
    voci.sort((x, y) => LIVELLI[x.livello] - LIVELLI[y.livello]);

    if (avvisi.status === 'rejected' && controlli.status === 'rejected') {
        contatore.className = 'badge badge-secondary';
        contatore.textContent = '--';
        lista.innerHTML = '<p class="da-fare-vuoto text-muted">Controlli non disponibili</p>';
        return;
    }

    if (voci.length === 0) {
        contatore.className = 'badge badge-success';
        contatore.textContent = 'Nessun avviso';
        lista.innerHTML = `<p class="da-fare-vuoto">✓ Nessun altro avviso per ${MESI[mese]} ${anno}</p>`;
        return;
    }

    // Il contatore prende il colore della voce piu' grave (prima era sempre rosso)
    const piuGrave = voci[0].livello;
    contatore.className = 'badge ' + (piuGrave === 'info' ? 'badge-secondary' : `badge-${piuGrave}`);
    contatore.textContent = voci.length;

    lista.innerHTML = voci.map(v => {
        const nomiVisti = v.nomi.slice(0, 3);
        const altri = Math.max(v.totaleNomi, v.nomi.length) - nomiVisti.length;
        const nomi = nomiVisti.length ? `
            <div class="da-fare-nomi">${nomiVisti.map(n => escapeHtml(n)).join(', ')}${
                altri > 0 ? ` … e altri ${altri}${v.azione ? ` · <a href="${escapeHtml(v.azione)}">vedi tutti</a>` : ''}` : ''}</div>` : '';
        return `
        <div class="validation-item da-fare-item da-fare-${v.livello}">
            <svg class="da-fare-icona" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                ${ICONE_LIVELLO[v.livello]}
            </svg>
            <div class="da-fare-testo">
                <div class="da-fare-titolo">${escapeHtml(v.titolo)}</div>
                <div class="da-fare-messaggio">${escapeHtml(v.messaggio || '')}</div>
                ${nomi}
            </div>
            ${v.azione ? `<a href="${escapeHtml(v.azione)}" class="btn btn-sm btn-secondary da-fare-azione">${escapeHtml(v.etichettaAzione || 'Vai')}</a>` : ''}
        </div>`;
    }).join('');
}

// ==================== TREND ====================

/** Anno scolastico del periodo mostrato (es. '2026-2027'). */
function _annoScolasticoPeriodo() {
    const { anno, mese } = getPeriodoCorrente();
    return mese >= 9 ? `${anno}-${anno + 1}` : `${anno - 1}-${anno}`;
}

async function loadTrend(n = _caricamento) {
    const annoScolastico = _annoScolasticoPeriodo();
    const titolo = document.getElementById('trend-titolo');
    if (titolo) titolo.textContent = `Trend ore erogate ${annoScolastico}`;
    try {
        const { commessa } = getActiveFilters();
        const qs = new URLSearchParams({ anno_scolastico: annoScolastico });
        if (commessa) qs.set('commessa', commessa);
        const dati = await apiCall(`/api/stats/trend?${qs}`);
        if (_superato(n)) return;
        _ultimoTrend = { dati, annoScolastico };
        disegnaTrend();
    } catch (error) {
        console.error('Errore trend:', error);
    }
}

function disegnaTrend() {
    const canvas = document.getElementById('chart-trend');
    const vuoto = document.getElementById('trend-vuoto');
    if (!canvas || !_ultimoTrend) return;
    const { dati, annoScolastico } = _ultimoTrend;

    // Libera la tela prima di ridisegnare: un secondo 'new Chart' sulla stessa
    // tela va in errore e fermava tutto il resto della pagina
    Chart.getChart(canvas)?.destroy();

    const oggi = new Date();
    const chiaveOggi = oggi.getFullYear() * 12 + oggi.getMonth() + 1;
    // I mesi futuri restano vuoti: niente linea che "crolla" a zero
    const valori = dati.map(d => (d.anno * 12 + d.mese > chiaveOggi ? null : (d.ore_erogate || 0)));
    const nessunaOra = !valori.some(v => v > 0);
    canvas.hidden = nessunaOra;
    if (vuoto) {
        vuoto.hidden = !nessunaOra;
        vuoto.textContent = `Nessuna ora ancora registrata per il ${annoScolastico}`;
    }
    if (nessunaOra) return;

    const colors = ChartManager.getColors();
    const gradient = canvas.getContext('2d').createLinearGradient(0, 0, 0, 200);
    gradient.addColorStop(0, 'rgba(59, 130, 246, 0.25)');
    gradient.addColorStop(1, 'rgba(59, 130, 246, 0)');

    new Chart(canvas, {
        type: 'line',
        data: {
            labels: dati.map(d => d.mese_nome),
            datasets: [{
                label: 'Ore erogate',
                data: valori,
                borderColor: colors.primary,
                backgroundColor: gradient,
                borderWidth: 3,
                fill: true,
                tension: 0.3,
                spanGaps: false,
                pointBackgroundColor: colors.primary,
                pointBorderColor: colors.fondo,
                pointBorderWidth: 2,
                pointRadius: 4,
                pointHoverRadius: 7
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: ChartManager.tooltip(colors, {
                    callbacks: {
                        title: (items) => {
                            const d = dati[items[0].dataIndex];
                            return `${MESI[d.mese]} ${d.anno}`;
                        },
                        label: (ctx) => `${ctx.parsed.y.toLocaleString('it-IT', { maximumFractionDigits: 2 })} ore`
                    }
                })
            },
            scales: {
                x: {
                    grid: { color: colors.grid },
                    ticks: { color: colors.text }
                },
                y: {
                    beginAtZero: true,
                    grid: { color: colors.grid },
                    ticks: {
                        color: colors.text,
                        callback: (value) => value.toLocaleString('it-IT')
                    },
                    title: { display: true, text: 'ore', color: colors.text }
                }
            },
            animation: {
                duration: 800,
                easing: 'easeOutQuart'
            }
        }
    });
}

function updateLastRefresh() {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const el = document.getElementById('last-update');
    if (el) el.textContent = `Ultimo aggiornamento: ${timeStr}`;
}

// ==================== QUICK EXPORT ====================

/** Nei report rapidi il mese che si scarica e' scritto sulla scheda. */
function aggiornaSottotitoliReport() {
    const { anno, mese } = getPeriodoCorrente();
    document.querySelectorAll('.report-quick-periodo').forEach(el => {
        el.textContent = `${MESI[mese]} ${anno}`;
    });
}

function quickExportExcel() {
    const { anno, mese } = getPeriodoCorrente();
    window.location.href = `/api/export/excel/${anno}/${mese}`;
    showToast('Download Report Completo in corso...', 'success');
}

function quickExportMunicipale() {
    const { anno, mese } = getPeriodoCorrente();
    window.location.href = `/api/export/municipale/${anno}/${mese}`;
    showToast('Download Report Municipale in corso...', 'success');
}

function quickExportDipartimentale() {
    const { anno, mese } = getPeriodoCorrente();
    window.location.href = `/api/export/dipartimentale/${anno}/${mese}`;
    showToast('Download Report Dipartimentale in corso...', 'success');
}

// Al cambio di tema il trend si ridisegna con i colori nuovi (prima numeri e
// griglia restavano bianchi e sparivano sul fondo chiaro)
window.addEventListener('themechange', () => {
    try {
        disegnaTrend();
    } catch (error) {
        console.error('Trend non ridisegnato al cambio tema:', error);
    }
});

// ==================== BANNER NUOVO ANNO SCOLASTICO ====================

let _bannerAnnoInit = false;
let _annoWizard = null;
let _wizardUtenti = [];
let _wizardStato = {};   // id utente -> { nuovo, archivia }: modifiche fatte nella tabella

async function loadBannerNuovoAnno() {
    const card = document.getElementById('nuovo-anno-card');
    if (!card) return;
    try {
        const stato = await apiCall('/api/anno-scolastico/prossimo');
        if (!stato.mostra_banner) {
            // Ultimo passo appena fatto: il riquadro resta con l'esito ("2 di 2 fatti")
            // finche' non si cambia pagina (prima spariva subito, esito compreso, sia
            // dopo il passo 1 sia dopo il passo 2); al prossimo caricamento non c'e' piu'
            if (stato.prossimo && document.getElementById('nuovo-anno-esito')?.innerHTML.trim()) {
                renderPassiNuovoAnno(stato);
                return;
            }
            card.style.display = 'none';
            return;
        }
        _annoWizard = stato.prossimo;
        document.getElementById('nuovo-anno-label').textContent = stato.prossimo;
        card.style.display = '';
        renderPassiNuovoAnno(stato);

        if (!_bannerAnnoInit) {
            _bannerAnnoInit = true;
            document.getElementById('btn-prepara-anno').addEventListener('click', () => preparaNuovoAnno(_annoWizard));
            // "Dettagli": apre e chiude la spiegazione dei due passi
            document.getElementById('btn-nuovo-anno-dettagli')?.addEventListener('click', (e) => {
                const body = document.getElementById('nuovo-anno-body');
                body.hidden = !body.hidden;
                e.currentTarget.setAttribute('aria-expanded', String(!body.hidden));
            });
            document.getElementById('btn-wizard-utenti').addEventListener('click', () => apriWizardUtenti(_annoWizard));
            document.getElementById('btn-wizard-utenti-applica').addEventListener('click', applicaWizardUtenti);
            document.getElementById('wizard-utenti-cerca').addEventListener('input', renderWizardUtenti);
            document.getElementById('wizard-chiudi-variazioni').addEventListener('change', aggiornaRiepilogoWizard);
            // Le modifiche nella tabella restano anche se si filtra/rirenderizza
            const tbody = document.getElementById('wizard-utenti-tbody');
            tbody.addEventListener('input', (e) => {
                if (e.target.classList.contains('wizard-nuovo-mo')) {
                    _statoWizard(e.target.dataset.id).nuovo = e.target.value;
                    aggiornaRiepilogoWizard();
                }
            });
            tbody.addEventListener('change', (e) => {
                if (e.target.classList.contains('wizard-archivia')) {
                    _statoWizard(e.target.dataset.id).archivia = e.target.checked;
                    e.target.closest('tr')?.classList.toggle('wizard-riga-archivia', e.target.checked);
                    aggiornaRiepilogoWizard();
                }
            });
        }
    } catch (e) { console.error(e); }
}

function _statoWizard(id) {
    if (!_wizardStato[id]) _wizardStato[id] = {};
    return _wizardStato[id];
}

function renderPassiNuovoAnno(stato) {
    const mostra = (id, visibile) => {
        const el = document.getElementById(id);
        if (el) el.style.display = visibile ? '' : 'none';
    };
    document.getElementById('passo-calendario')?.classList.toggle('fatto', !!stato.pronto);
    document.getElementById('passo-utenti')?.classList.toggle('fatto', !!stato.utenti_pronti);
    mostra('btn-prepara-anno', !stato.pronto);
    mostra('passo-calendario-ok', stato.pronto);
    mostra('btn-wizard-utenti', !stato.utenti_pronti);
    mostra('passo-utenti-ok', stato.utenti_pronti);
    const fatti = (stato.pronto ? 1 : 0) + (stato.utenti_pronti ? 1 : 0);
    const progresso = document.getElementById('nuovo-anno-progresso');
    if (progresso) progresso.textContent = `${fatti} di 2 ${fatti === 1 ? 'fatto' : 'fatti'}`;
}

function preparaNuovoAnno(annoScolastico) {
    showConfirmDialog(
        `Preparare il calendario ${annoScolastico}?`,
        'Verranno creati i giorni lavorativi di ogni mese, calcolati automaticamente ' +
        '(regole Regione Lazio). Potrai rivederli e correggerli dalla pagina Calendario.',
        async () => {
            const btn = document.getElementById('btn-prepara-anno');
            btn.disabled = true;
            try {
                const data = await apiCall('/api/anno-scolastico/prepara', {
                    method: 'POST',
                    body: JSON.stringify({ anno_scolastico: annoScolastico })
                });
                const MESI_BREVI = ['','Gen','Feb','Mar','Apr','Mag','Giu','Lug','Ago','Set','Ott','Nov','Dic'];
                const righe = data.mesi.map(m =>
                    `<tr><td>${MESI_BREVI[m.mese]} ${m.anno}</td>` +
                    `<td class="text-right">${m.giorni}${m.giorni_altri != null ? ` (non-infanzia: ${m.giorni_altri})` : ''}</td></tr>`
                ).join('');
                // Passo 2 gia' fatto: il nuovo anno e' pronto (l'esito resta visibile)
                const utentiFatti = document.getElementById('passo-utenti')?.classList.contains('fatto');
                document.getElementById('nuovo-anno-esito').innerHTML = `
                    <div class="alert alert-success">
                        <div><strong>Calendario ${escapeHtml(data.anno_scolastico)} creato</strong> per ${data.mesi.length} mesi.
                        ${utentiFatti ? 'Il nuovo anno è pronto.' : 'Ora puoi passare al punto 2 (utenti e monte ore).'}</div>
                    </div>
                    <div class="table-responsive mt-2" style="max-width:420px;">
                        <table class="table">
                            <thead><tr><th>Mese</th><th class="text-right">Giorni lavorativi</th></tr></thead>
                            <tbody>${righe}</tbody>
                        </table>
                    </div>`;
                showToast('Calendario del nuovo anno preparato', 'success');
                // Tutta la dashboard: lo Stato del mese diventa apribile e l'avviso
                // "Calendario incompleto" in Da fare sparisce (poi il banner)
                loadDashboardData();
            } catch (e) {
                showToast(e.message || 'Errore nella preparazione', 'error');
            } finally {
                btn.disabled = false;
            }
        },
        { confirmText: 'Prepara', type: 'info' }
    );
}

async function apriWizardUtenti(annoScolastico) {
    _wizardStato = {};
    document.getElementById('wizard-utenti-anno').textContent = annoScolastico;
    document.getElementById('wizard-utenti-cerca').value = '';
    const tbody = document.getElementById('wizard-utenti-tbody');
    tbody.innerHTML = '<tr><td colspan="5" class="text-center py-4"><div class="spinner"></div></td></tr>';
    openModal('modal-nuovo-anno-utenti');
    try {
        const data = await apiCall(`/api/anno-scolastico/utenti-anteprima?anno_scolastico=${encodeURIComponent(annoScolastico)}`);
        _wizardUtenti = data.utenti || [];
        document.getElementById('wizard-variazioni-n').textContent = data.variazioni_da_chiudere;
        document.getElementById('wizard-chiudi-variazioni').checked = data.variazioni_da_chiudere > 0;
        renderWizardUtenti();
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-center text-danger">${escapeHtml(e.message || 'Errore nel caricamento')}</td></tr>`;
    }
}

function renderWizardUtenti() {
    const tbody = document.getElementById('wizard-utenti-tbody');
    const q = (document.getElementById('wizard-utenti-cerca').value || '').toLowerCase().trim();
    const righe = _wizardUtenti.filter(u => !q || `${u.nome} ${u.cognome || ''} ${u.scuola || ''}`.toLowerCase().includes(q));
    if (!righe.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-4">Nessun utente</td></tr>';
        aggiornaRiepilogoWizard();
        return;
    }
    tbody.innerHTML = righe.map(u => {
        const st = _wizardStato[u.id] || {};
        const nuovo = st.nuovo !== undefined ? st.nuovo : u.monte_ore_base;
        // Mai spuntato in partenza: chi e' uscito ha gia' la data di fine, che lo
        // esclude dal nuovo anno; qui c'e' solo l'indicazione "uscito a mm/aaaa"
        const archivia = st.archivia !== undefined ? st.archivia : false;
        const diverso = Number(u.effettivo_giugno) !== Number(u.monte_ore_base);
        const [aFine, mFine] = String(u.data_fine || '').split('-');
        const fine = u.data_fine
            ? `<span class="text-muted" style="font-size:0.75rem;">${u.uscito ? 'uscito a' : 'fine'} ${escapeHtml(mFine && aFine ? `${mFine}/${aFine}` : u.data_fine)}</span>`
            : '';
        return `<tr class="${archivia ? 'wizard-riga-archivia' : ''}">
            <td><strong>${escapeHtml(u.nome)} ${escapeHtml(u.cognome || '')}</strong>
                <div class="text-muted" style="font-size:0.8rem;">${escapeHtml(u.scuola || '')}</div></td>
            <td class="text-center">${formatNumero(u.monte_ore_base)}</td>
            <td class="text-center ${diverso ? 'wizard-diff' : ''}" title="${u.variazioni_aperte} variazione/i ancora aperta/e">${formatNumero(u.effettivo_giugno)}${diverso ? ' ⚠' : ''}</td>
            <td><input type="number" class="form-control wizard-nuovo-mo" data-id="${u.id}" value="${nuovo}" step="0.5" min="0" max="40" style="width:100px;" aria-label="Nuovo monte ore"></td>
            <td class="text-center wizard-cella-archivia"><label class="wizard-archivia-label">
                <input type="checkbox" class="wizard-archivia" data-id="${u.id}" ${archivia ? 'checked' : ''} aria-label="Archivia ${escapeHtml(u.nome)} ${escapeHtml(u.cognome || '')}">
                ${fine}</label></td>
        </tr>`;
    }).join('');
    aggiornaRiepilogoWizard();
}

function _modificheWizard() {
    const monte_ore = {};
    const archivia = [];
    _wizardUtenti.forEach(u => {
        const st = _wizardStato[u.id] || {};
        const nuovo = (st.nuovo !== undefined && st.nuovo !== '') ? Number(st.nuovo) : Number(u.monte_ore_base);
        if (nuovo !== Number(u.monte_ore_base)) monte_ore[u.id] = nuovo;
        if (st.archivia) archivia.push(u.id);
    });
    return { monte_ore, archivia };
}

function aggiornaRiepilogoWizard() {
    const el = document.getElementById('wizard-utenti-riepilogo');
    if (!el) return;
    const { monte_ore, archivia } = _modificheWizard();
    const chiudi = document.getElementById('wizard-chiudi-variazioni').checked;
    const nVar = chiudi ? Number(document.getElementById('wizard-variazioni-n').textContent || 0) : 0;
    el.textContent = `${nVar} variazioni da chiudere · ${Object.keys(monte_ore).length} monte ore da aggiornare · ${archivia.length} da archiviare`;
}

function applicaWizardUtenti() {
    const { monte_ore, archivia } = _modificheWizard();
    const chiudi = document.getElementById('wizard-chiudi-variazioni').checked;
    const nVar = chiudi ? Number(document.getElementById('wizard-variazioni-n').textContent || 0) : 0;
    const righe = [];
    if (chiudi) righe.push(`${nVar} variazioni monte ore chiuse al 31 agosto`);
    righe.push(`${Object.keys(monte_ore).length} monte ore di partenza aggiornati`);
    righe.push(`${archivia.length} utenti archiviati`);
    // Testo vero: niente cambia nei mesi gia' rendicontati (monte ore e archiviati)
    let spiegazione = '.';
    if (Object.keys(monte_ore).length) {
        spiegazione += ' Il nuovo monte ore vale da settembre: i mesi passati tengono quello di prima ' +
            '(resta come variazione chiusa ad agosto) e ogni cambio resta nello storico dell\'utente.';
    }
    if (archivia.length) {
        spiegazione += ' Gli archiviati non compariranno nei mesi futuri; i mesi già rendicontati restano ' +
            'invariati. Si ritrovano nel filtro "Archiviati" della pagina Utenti.';
    }
    showConfirmDialog(
        `Applicare le modifiche per il ${_annoWizard}?`,
        righe.join(' · ') + spiegazione,
        async () => {
            const btn = document.getElementById('btn-wizard-utenti-applica');
            btn.disabled = true;
            try {
                const res = await apiCall('/api/anno-scolastico/prepara-utenti', {
                    method: 'POST',
                    body: JSON.stringify({ anno_scolastico: _annoWizard, chiudi_variazioni: chiudi, monte_ore, archivia })
                });
                closeModal('modal-nuovo-anno-utenti');
                document.getElementById('nuovo-anno-esito').innerHTML = `
                    <div class="alert alert-success">
                        <div><strong>Utenti pronti per il ${escapeHtml(_annoWizard)}.</strong>
                        ${res.variazioni_chiuse} variazioni chiuse, ${res.monte_ore_modificati} monte ore aggiornati
                        (per ${res.variazioni_conservate || 0} i mesi passati tengono il valore di prima),
                        ${res.archiviati} utenti archiviati. I mesi già rendicontati non cambiano.</div>
                    </div>`;
                showToast('Utenti preparati per il nuovo anno', 'success');
                loadBannerNuovoAnno();
                if (typeof loadDashboardData === 'function') loadDashboardData();
            } catch (e) {
                showToast(e.message || 'Errore nell\'applicazione delle modifiche', 'error');
            } finally {
                btn.disabled = false;
            }
        },
        { confirmText: 'Applica', type: 'info' }
    );
}

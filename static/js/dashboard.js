// ==================== DASHBOARD ====================
// Logica della dashboard: stato del mese, avvisi, validazione e grafici.
// Helper condivisi (apiCall, animateCounter, MESI, ...) sono in app.js.

let chartCommesse = null;
let chartTrend = null;

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

async function loadDashboardData() {
    try {
        const filters = getActiveFilters();
        const queryParams = new URLSearchParams();
        if (filters.commessa) queryParams.set('commessa', filters.commessa);
        if (filters.anno) queryParams.set('anno', filters.anno);
        if (filters.mese) queryParams.set('mese', filters.mese);
        const qs = queryParams.toString() ? `?${queryParams}` : '';

        // KPI
        const stats = await apiCall(`/api/stats/filtered${qs}`);
        animateCounter(document.getElementById('stat-utenti'), stats.num_utenti || 0, 800);
        animateCounter(document.getElementById('stat-scuole'), stats.num_scuole || 0, 800);

        // Checklist di primo avvio: mostrata solo con anagrafica vuota (senza filtri)
        const onboarding = document.getElementById('onboarding-card');
        if (onboarding) {
            onboarding.style.display =
                (!filters.commessa && (stats.num_utenti || 0) === 0) ? '' : 'none';
        }

        // Banner nuovo anno scolastico (giugno-ottobre, se non ancora preparato)
        loadBannerNuovoAnno();

        const commesse = await apiCall('/api/commesse');
        animateCounter(document.getElementById('stat-commesse'), commesse.filter(c => c.attiva).length, 800);

        const urlUtenti = filters.commessa ? `/api/utenti?commessa=${encodeURIComponent(filters.commessa)}` : '/api/utenti';
        const utenti = await apiCall(urlUtenti);
        const monteOreTotale = utenti.reduce((sum, u) => sum + (u.monte_ore_settimanale || 0), 0);
        animateCounter(document.getElementById('stat-monte-ore'), Math.round(monteOreTotale), 1000);

        // Stato del mese, avvisi, validazione
        await loadStatoMese();
        await loadAlerts();
        await loadValidazione();

        // Grafici
        const statsBase = await apiCall('/api/stats');
        await updateCharts(statsBase.utenti_per_commessa);

        updateLastRefresh();
    } catch (error) {
        console.error('Errore caricamento dati dashboard:', error);
    }
}

// ==================== STATO DEL MESE ====================

async function loadStatoMese() {
    const { anno, mese, commessa } = getPeriodoCorrente();
    const nomeEl = document.getElementById('stato-mese-nome');
    const percentEl = document.getElementById('stato-mese-percent');
    const barEl = document.getElementById('stato-mese-bar');
    const testoEl = document.getElementById('stato-mese-testo');
    const listaEl = document.getElementById('lista-da-completare');
    if (!nomeEl) return;

    nomeEl.textContent = `${MESI[mese]} ${anno}`;

    try {
        let daCompletare = await apiCall(`/api/stats/utenti-da-completare/${anno}/${mese}`);
        if (commessa) {
            daCompletare = daCompletare.filter(u => u.commessa === commessa);
        }

        const qsTot = new URLSearchParams({ anno, mese });
        if (commessa) qsTot.set('commessa', commessa);
        const statsTot = await apiCall(`/api/stats/filtered?${qsTot}`);
        const totale = statsTot.num_utenti || 0;

        const completati = Math.max(totale - daCompletare.length, 0);
        const percent = totale > 0 ? Math.round((completati / totale) * 100) : 0;

        percentEl.textContent = `${percent}%`;
        percentEl.className = 'badge ' + (percent >= 100 ? 'badge-success' : percent >= 50 ? 'badge-warning' : 'badge-danger');
        barEl.style.width = `${percent}%`;
        barEl.style.background = percent >= 100 ? 'var(--success)' : percent >= 50 ? 'var(--warning)' : 'var(--danger)';
        testoEl.textContent = totale > 0
            ? `${completati} di ${totale} utenti rendicontati — ${daCompletare.length} senza ore`
            : 'Nessun utente attivo nel periodo selezionato';

        if (daCompletare.length === 0) {
            listaEl.innerHTML = totale > 0
                ? `<div class="empty-state" style="padding: 16px;">
                       <p class="text-muted text-center" style="margin: 0;">✓ Tutti gli utenti hanno le ore registrate</p>
                   </div>`
                : '';
        } else {
            const utentiToShow = daCompletare.slice(0, 8);
            let html = utentiToShow.map(u => `
                <div class="da-completare-item">
                    <div class="da-completare-info">
                        <span class="da-completare-nome">${escapeHtml(u.nome)} ${escapeHtml(u.cognome)}</span>
                        <span class="da-completare-scuola">${escapeHtml(u.commessa)} - ${escapeHtml(u.scuola.substring(0, 40))}${u.scuola.length > 40 ? '...' : ''}</span>
                    </div>
                    <span class="badge badge-secondary">${formatNumero(u.monte_ore)}h</span>
                </div>
            `).join('');
            if (daCompletare.length > 8) {
                html += `<div class="da-completare-more"><span class="text-muted">+ altri ${daCompletare.length - 8} utenti</span></div>`;
            }
            listaEl.innerHTML = html;
        }
    } catch (error) {
        console.error('Errore caricamento stato mese:', error);
        testoEl.textContent = 'Dati non disponibili';
    }
}

// ==================== ALERT AUTOMATICI ====================

async function loadAlerts() {
    try {
        const { anno, mese } = getPeriodoCorrente();

        const data = await apiCall(`/api/alerts?anno=${anno}&mese=${mese}`);
        const panel = document.getElementById('alerts-panel');
        const list = document.getElementById('alerts-list');
        const countBadge = document.getElementById('alerts-count');

        if (data.total_alerts > 0) {
            panel.style.display = '';
            countBadge.style.display = '';
            countBadge.textContent = data.total_alerts;

            const iconMap = {
                warning: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />',
                danger: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />',
                info: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />',
                success: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />'
            };

            list.innerHTML = data.alerts.slice(0, 10).map(a => `
                <div class="alert-item alert-${a.type}" style="display: flex; align-items: flex-start; gap: 12px; padding: 12px; border-radius: 8px; margin-bottom: 8px; background: var(--${a.type === 'danger' ? 'danger' : a.type === 'warning' ? 'warning' : a.type === 'info' ? 'primary' : 'success'}-bg, rgba(var(--${a.type}-rgb), 0.1));">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" style="width: 20px; height: 20px; flex-shrink: 0; color: var(--${a.type});">
                        ${iconMap[a.type] || iconMap.info}
                    </svg>
                    <div style="flex: 1; min-width: 0;">
                        <div style="font-weight: 600; font-size: 0.875rem; color: var(--text-primary);">${escapeHtml(a.title)}</div>
                        <div style="font-size: 0.75rem; color: var(--text-secondary); margin-top: 2px;">${escapeHtml(a.message)}</div>
                        ${a.utenti ? `<div style="font-size: 0.7rem; color: var(--text-tertiary); margin-top: 4px;">${a.utenti.slice(0, 3).map(u => escapeHtml(u)).join(', ')}${a.utenti.length > 3 ? '...' : ''}</div>` : ''}
                        ${a.progress !== undefined ? `<div style="margin-top: 8px; background: var(--bg-secondary); border-radius: 4px; height: 6px; overflow: hidden;"><div style="width: ${a.progress}%; height: 100%; background: var(--${a.type}); transition: width 0.3s;"></div></div>` : ''}
                    </div>
                    ${a.action ? `<a href="${a.action}" class="btn btn-sm btn-${a.type === 'danger' ? 'danger' : 'secondary'}" style="flex-shrink: 0; font-size: 0.7rem; padding: 4px 8px;">${escapeHtml(a.action_label || 'Vai')}</a>` : ''}
                </div>
            `).join('');

            if (data.total_alerts > 10) {
                list.innerHTML += `<p class="text-center text-muted text-xs mt-2">+ altri ${data.total_alerts - 10} alert</p>`;
            }
        } else {
            panel.style.display = 'none';
        }
    } catch (e) {
        console.log('Alerts non disponibili:', e);
    }
}

// ==================== VALIDAZIONE DATI ====================

async function loadValidazione() {
    const container = document.getElementById('validazione-content');
    const badge = document.getElementById('validazione-badge');

    container.innerHTML = '<div class="loading" style="padding: 20px;"><div class="spinner"></div></div>';

    try {
        const { anno, mese } = getPeriodoCorrente();

        const data = await apiCall(`/api/stats/validazione?anno=${anno}&mese=${mese}`);

        if (data.riepilogo.critiche > 0) {
            badge.className = 'badge badge-danger';
            const n = data.riepilogo.critiche;
            badge.textContent = `${n} ${n === 1 ? 'critico' : 'critici'}`;
        } else if (data.riepilogo.avvisi > 0) {
            badge.className = 'badge badge-warning';
            const n = data.riepilogo.avvisi;
            badge.textContent = `${n} ${n === 1 ? 'avviso' : 'avvisi'}`;
        } else {
            badge.className = 'badge badge-success';
            badge.textContent = 'OK';
        }

        if (data.anomalie.length === 0) {
            container.innerHTML = `
                <div class="validation-success" style="padding: 24px; text-align: center;">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"
                         style="width: 48px; height: 48px; color: var(--success); margin: 0 auto 12px;">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                              d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <p style="color: var(--success); font-weight: 600; margin: 0 0 4px;">Nessuna anomalia rilevata</p>
                    <p style="color: var(--text-tertiary); font-size: 0.8rem; margin: 0;">
                        ${MESI[mese]} ${anno} - Tutti i dati sono coerenti
                    </p>
                </div>
            `;
            return;
        }

        const iconMap = {
            danger: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />',
            warning: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />',
            info: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />'
        };

        container.innerHTML = data.anomalie.map(a => `
            <div class="validation-item validation-${a.tipo}" style="display: flex; align-items: flex-start; gap: 12px; padding: 14px 16px; border-bottom: 1px solid var(--border-color);">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"
                     style="width: 20px; height: 20px; flex-shrink: 0; color: var(--${a.tipo});">
                    ${iconMap[a.tipo]}
                </svg>
                <div style="flex: 1; min-width: 0;">
                    <div style="font-weight: 600; font-size: 0.9rem; color: var(--text-primary);">${escapeHtml(a.titolo)}</div>
                    <div style="font-size: 0.8rem; color: var(--text-secondary); margin-top: 2px;">${escapeHtml(a.messaggio)}</div>
                    ${a.dettagli && a.dettagli.length > 0 ? `
                        <div style="font-size: 0.75rem; color: var(--text-tertiary); margin-top: 6px;">
                            ${a.dettagli.slice(0, 3).map(d => escapeHtml(d.nome || d.commessa || '')).filter(Boolean).join(', ')}
                            ${a.dettagli.length > 3 ? `<span class="text-muted">... e altri ${a.dettagli.length - 3}</span>` : ''}
                        </div>
                    ` : ''}
                </div>
                <div style="text-align: right; flex-shrink: 0;">
                    <span class="badge badge-${a.tipo}" style="font-size: 0.7rem;">${a.conteggio}</span>
                </div>
            </div>
        `).join('');

    } catch (e) {
        console.error('Errore validazione:', e);
        badge.className = 'badge badge-secondary';
        badge.textContent = '--';
        container.innerHTML = '<div class="text-center text-muted py-4">Errore nel caricamento</div>';
    }
}

// ==================== GRAFICI ====================

async function updateCharts(utentiPerCommessa) {
    // Chart Commesse (Doughnut)
    const ctx1 = document.getElementById('chart-commesse');
    if (ctx1 && utentiPerCommessa) {
        const labels = Object.keys(utentiPerCommessa);
        const data = Object.values(utentiPerCommessa);
        const colors = ['#0A84FF', '#BF5AF2', '#30D158', '#FF9F0A', '#FF453A', '#64D2FF'];

        if (chartCommesse) chartCommesse.destroy();

        const isDarkDoughnut = document.documentElement.getAttribute('data-theme') !== 'light';
        const tooltipBgDoughnut = isDarkDoughnut ? 'rgba(28, 28, 30, 0.95)' : 'rgba(255, 255, 255, 0.95)';
        const tooltipTextDoughnut = isDarkDoughnut ? '#fff' : '#1D1D1F';
        const tooltipBorderDoughnut = isDarkDoughnut ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)';

        chartCommesse = new Chart(ctx1, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: colors.slice(0, labels.length),
                    borderWidth: 0,
                    hoverOffset: 8
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: tooltipBgDoughnut,
                        titleColor: tooltipTextDoughnut,
                        bodyColor: isDarkDoughnut ? 'rgba(255,255,255,0.8)' : 'rgba(0,0,0,0.7)',
                        borderColor: tooltipBorderDoughnut,
                        borderWidth: 1,
                        cornerRadius: 8,
                        padding: 12
                    }
                },
                cutout: '65%',
                animation: {
                    animateRotate: true,
                    animateScale: true
                }
            }
        });

        const legendContainer = document.getElementById('legend-commesse');
        legendContainer.innerHTML = labels.map((label, i) =>
            `<div class="legend-item">
                <span class="legend-dot" style="background:${colors[i]}"></span>
                <span>${escapeHtml(label)} (${data[i]})</span>
            </div>`
        ).join('');
    }

    // Chart Trend (Line)
    try {
        const filters = getActiveFilters();
        const trendQs = filters.commessa ? `?commessa=${encodeURIComponent(filters.commessa)}` : '';
        const trendData = await apiCall(`/api/stats/trend${trendQs}`);
        const ctx2 = document.getElementById('chart-trend');

        if (ctx2 && trendData && trendData.length > 0) {
            if (chartTrend) chartTrend.destroy();

            const labels = trendData.map(d => d.mese_nome);
            const oreData = trendData.map(d => d.ore_erogate || 0);

            const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
            const gridColor = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.08)';
            const tickColor = isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.6)';
            const tooltipBg = isDark ? 'rgba(28, 28, 30, 0.95)' : 'rgba(255, 255, 255, 0.95)';
            const tooltipText = isDark ? '#fff' : '#1D1D1F';
            const tooltipBorder = isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)';

            const gradient = ctx2.getContext('2d').createLinearGradient(0, 0, 0, 200);
            gradient.addColorStop(0, 'rgba(10, 132, 255, 0.3)');
            gradient.addColorStop(1, 'rgba(10, 132, 255, 0)');

            chartTrend = new Chart(ctx2, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Ore Erogate',
                        data: oreData,
                        borderColor: '#0A84FF',
                        backgroundColor: gradient,
                        borderWidth: 3,
                        fill: true,
                        tension: 0.4,
                        pointBackgroundColor: '#0A84FF',
                        pointBorderColor: '#fff',
                        pointBorderWidth: 2,
                        pointRadius: 5,
                        pointHoverRadius: 8
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: tooltipBg,
                            titleColor: tooltipText,
                            bodyColor: isDark ? 'rgba(255,255,255,0.8)' : 'rgba(0,0,0,0.7)',
                            borderColor: tooltipBorder,
                            borderWidth: 1,
                            cornerRadius: 8,
                            padding: 12,
                            callbacks: {
                                label: (ctx) => `${ctx.parsed.y.toLocaleString('it-IT')} ore`
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: { color: gridColor },
                            ticks: { color: tickColor }
                        },
                        y: {
                            grid: { color: gridColor },
                            ticks: {
                                color: tickColor,
                                callback: (value) => value.toLocaleString('it-IT')
                            }
                        }
                    },
                    animation: {
                        duration: 1000,
                        easing: 'easeOutQuart'
                    }
                }
            });
        }
    } catch (error) {
        console.log('Trend data not available:', error);
    }
}

function updateLastRefresh() {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const el = document.getElementById('last-update');
    if (el) el.textContent = `Ultimo aggiornamento: ${timeStr}`;
}

// ==================== QUICK EXPORT ====================

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

// Aggiorna grafici al cambio tema
window.addEventListener('themechange', async () => {
    try {
        const stats = await apiCall('/api/stats');
        await updateCharts(stats.utenti_per_commessa);
    } catch (error) {
        console.log('Chart refresh on theme change failed:', error);
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
                document.getElementById('nuovo-anno-esito').innerHTML = `
                    <div class="alert alert-success">
                        <div><strong>Calendario ${escapeHtml(data.anno_scolastico)} creato</strong> per ${data.mesi.length} mesi.
                        Ora puoi passare al punto 2 (utenti e monte ore).</div>
                    </div>
                    <div class="table-responsive mt-2" style="max-width:420px;">
                        <table class="table">
                            <thead><tr><th>Mese</th><th class="text-right">Giorni lavorativi</th></tr></thead>
                            <tbody>${righe}</tbody>
                        </table>
                    </div>`;
                showToast('Calendario del nuovo anno preparato', 'success');
                loadBannerNuovoAnno();
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
        const archivia = st.archivia !== undefined ? st.archivia : u.proposta_archivio;
        const diverso = Number(u.effettivo_giugno) !== Number(u.monte_ore_base);
        return `<tr class="${archivia ? 'wizard-riga-archivia' : ''}">
            <td><strong>${escapeHtml(u.nome)} ${escapeHtml(u.cognome || '')}</strong>
                <div class="text-muted" style="font-size:0.8rem;">${escapeHtml(u.scuola || '')}</div></td>
            <td class="text-center">${formatNumero(u.monte_ore_base)}</td>
            <td class="text-center ${diverso ? 'wizard-diff' : ''}" title="${u.variazioni_aperte} variazione/i ancora aperta/e">${formatNumero(u.effettivo_giugno)}${diverso ? ' ⚠' : ''}</td>
            <td><input type="number" class="form-control wizard-nuovo-mo" data-id="${u.id}" value="${nuovo}" step="0.5" min="0" max="40" style="width:100px;" aria-label="Nuovo monte ore"></td>
            <td class="text-center wizard-cella-archivia"><label class="wizard-archivia-label">
                <input type="checkbox" class="wizard-archivia" data-id="${u.id}" ${archivia ? 'checked' : ''} aria-label="Archivia ${escapeHtml(u.nome)} ${escapeHtml(u.cognome || '')}">
                ${u.data_fine ? `<span class="text-muted" style="font-size:0.75rem;">fine ${escapeHtml(formatDataIT(u.data_fine))}</span>` : ''}</label></td>
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
        const arch = st.archivia !== undefined ? st.archivia : u.proposta_archivio;
        if (arch) archivia.push(u.id);
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
    showConfirmDialog(
        `Applicare le modifiche per il ${_annoWizard}?`,
        righe.join(' · ') + '. Ogni monte ore cambiato resta nello storico dell\'utente; ' +
        'gli archiviati si ritrovano nel filtro "Archiviati" della pagina Utenti.',
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
                        ${res.variazioni_chiuse} variazioni chiuse, ${res.monte_ore_modificati} monte ore aggiornati,
                        ${res.archiviati} utenti archiviati.</div>
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

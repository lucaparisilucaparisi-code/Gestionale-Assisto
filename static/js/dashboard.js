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
                    <span class="badge badge-secondary">${u.monte_ore}h</span>
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
            badge.textContent = `${data.riepilogo.critiche} critici`;
        } else if (data.riepilogo.avvisi > 0) {
            badge.className = 'badge badge-warning';
            badge.textContent = `${data.riepilogo.avvisi} avvisi`;
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

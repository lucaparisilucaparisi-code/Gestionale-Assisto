/**
 * Gestionale OEPAC - Advanced Features v1.0
 * Funzionalità avanzate: sparklines, progress rings, heatmap, filtri, offline, notifiche, etc.
 */

// ==================== SPARKLINES ====================

const Sparkline = {
    /**
     * Crea una sparkline SVG inline
     * @param {number[]} data - Array di valori
     * @param {object} options - Opzioni di configurazione
     */
    create(data, options = {}) {
        const {
            width = 80,
            height = 24,
            strokeColor = 'var(--primary)',
            strokeWidth = 2,
            fillColor = null,
            showDots = false,
            animate = true
        } = options;

        if (!data || data.length < 2) return '';

        const min = Math.min(...data);
        const max = Math.max(...data);
        const range = max - min || 1;

        const points = data.map((val, i) => {
            const x = (i / (data.length - 1)) * width;
            const y = height - ((val - min) / range) * (height - 4) - 2;
            return `${x},${y}`;
        });

        const pathD = `M ${points.join(' L ')}`;
        const fillPathD = `M 0,${height} L ${points.join(' L ')} L ${width},${height} Z`;

        let svg = `<svg class="sparkline" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`;

        if (fillColor) {
            svg += `<path d="${fillPathD}" fill="${fillColor}" opacity="0.2"/>`;
        }

        svg += `<path d="${pathD}" fill="none" stroke="${strokeColor}" stroke-width="${strokeWidth}" stroke-linecap="round" stroke-linejoin="round"`;

        if (animate) {
            const pathLength = data.length * 20;
            svg += ` stroke-dasharray="${pathLength}" stroke-dashoffset="${pathLength}" class="sparkline-animate"`;
        }

        svg += `/>`;

        if (showDots) {
            const lastPoint = points[points.length - 1].split(',');
            svg += `<circle cx="${lastPoint[0]}" cy="${lastPoint[1]}" r="3" fill="${strokeColor}"/>`;
        }

        svg += `</svg>`;
        return svg;
    },

    /**
     * Aggiunge sparkline a una stat-card
     */
    addToStatCard(cardElement, data, trend = null) {
        if (!cardElement || !data) return;

        const sparklineContainer = document.createElement('div');
        sparklineContainer.className = 'stat-sparkline';

        const color = trend > 0 ? 'var(--success)' : trend < 0 ? 'var(--danger)' : 'var(--primary)';
        sparklineContainer.innerHTML = this.create(data, {
            strokeColor: color,
            fillColor: color,
            showDots: true
        });

        const existingSparkline = cardElement.querySelector('.stat-sparkline');
        if (existingSparkline) existingSparkline.remove();

        cardElement.appendChild(sparklineContainer);
    }
};

// ==================== PROGRESS RING ====================

const ProgressRing = {
    /**
     * Crea un progress ring SVG
     * @param {number} percent - Percentuale (0-100)
     * @param {object} options - Opzioni
     */
    create(percent, options = {}) {
        const {
            size = 60,
            strokeWidth = 6,
            color = 'var(--primary)',
            bgColor = 'var(--bg-tertiary)',
            showLabel = true,
            labelSize = '0.85rem',
            animate = true
        } = options;

        const radius = (size - strokeWidth) / 2;
        const circumference = radius * 2 * Math.PI;
        const offset = circumference - (percent / 100) * circumference;
        const center = size / 2;

        return `
            <div class="progress-ring-container" style="width: ${size}px; height: ${size}px;">
                <svg class="progress-ring" width="${size}" height="${size}">
                    <circle
                        class="progress-ring-bg"
                        stroke="${bgColor}"
                        stroke-width="${strokeWidth}"
                        fill="transparent"
                        r="${radius}"
                        cx="${center}"
                        cy="${center}"
                    />
                    <circle
                        class="progress-ring-progress"
                        stroke="${color}"
                        stroke-width="${strokeWidth}"
                        stroke-linecap="round"
                        fill="transparent"
                        r="${radius}"
                        cx="${center}"
                        cy="${center}"
                        style="stroke-dasharray: ${circumference}; stroke-dashoffset: ${animate ? circumference : offset};"
                        data-offset="${offset}"
                    />
                </svg>
                ${showLabel ? `<span class="progress-ring-label" style="font-size: ${labelSize}">${Math.round(percent)}%</span>` : ''}
            </div>
        `;
    },

    /**
     * Anima un progress ring
     */
    animate(element) {
        const circle = element.querySelector('.progress-ring-progress');
        if (circle) {
            const offset = circle.dataset.offset;
            setTimeout(() => {
                circle.style.strokeDashoffset = offset;
            }, 100);
        }
    },

    /**
     * Aggiorna il valore di un progress ring
     */
    update(element, percent, color = null) {
        const circle = element.querySelector('.progress-ring-progress');
        const label = element.querySelector('.progress-ring-label');

        if (circle) {
            const radius = parseFloat(circle.getAttribute('r'));
            const circumference = radius * 2 * Math.PI;
            const offset = circumference - (percent / 100) * circumference;
            circle.style.strokeDashoffset = offset;
            if (color) circle.style.stroke = color;
        }

        if (label) {
            label.textContent = `${Math.round(percent)}%`;
        }
    }
};

// ==================== HEATMAP CALENDAR ====================

const HeatmapCalendar = {
    /**
     * Crea un heatmap calendario
     * @param {object} data - { 'YYYY-MM-DD': value, ... }
     * @param {object} options - Opzioni
     */
    create(containerId, data, options = {}) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const {
            startDate = new Date(new Date().getFullYear(), new Date().getMonth() - 11, 1),
            endDate = new Date(),
            colorScale = ['#1a1a2e', '#16213e', '#0f3460', '#0a84ff', '#30d158'],
            cellSize = 12,
            cellGap = 3,
            showMonthLabels = true,
            showDayLabels = true
        } = options;

        const days = ['L', 'M', 'M', 'G', 'V', 'S', 'D'];
        const months = ['Gen', 'Feb', 'Mar', 'Apr', 'Mag', 'Giu', 'Lug', 'Ago', 'Set', 'Ott', 'Nov', 'Dic'];

        // Calcola il range di valori
        const values = Object.values(data).filter(v => v > 0);
        const maxValue = Math.max(...values, 1);
        const minValue = Math.min(...values, 0);

        // Genera i giorni
        let currentDate = new Date(startDate);
        const cellsData = [];

        while (currentDate <= endDate) {
            const dateStr = currentDate.toISOString().split('T')[0];
            const value = data[dateStr] || 0;
            const dayOfWeek = (currentDate.getDay() + 6) % 7; // Lunedì = 0

            cellsData.push({
                date: dateStr,
                value,
                dayOfWeek,
                month: currentDate.getMonth(),
                colorIndex: value === 0 ? 0 : Math.min(Math.ceil((value / maxValue) * (colorScale.length - 1)), colorScale.length - 1)
            });

            currentDate.setDate(currentDate.getDate() + 1);
        }

        // Calcola le settimane
        const weeks = [];
        let currentWeek = [];

        cellsData.forEach((cell, i) => {
            if (i === 0) {
                // Riempi i giorni vuoti all'inizio
                for (let d = 0; d < cell.dayOfWeek; d++) {
                    currentWeek.push(null);
                }
            }

            currentWeek.push(cell);

            if (cell.dayOfWeek === 6 || i === cellsData.length - 1) {
                weeks.push([...currentWeek]);
                currentWeek = [];
            }
        });

        // Genera HTML
        let html = '<div class="heatmap-calendar">';

        if (showDayLabels) {
            html += '<div class="heatmap-day-labels">';
            days.forEach((day, i) => {
                html += `<span style="height: ${cellSize}px; margin-bottom: ${cellGap}px; display: ${i % 2 === 0 ? 'flex' : 'none'}; align-items: center;">${day}</span>`;
            });
            html += '</div>';
        }

        html += '<div class="heatmap-grid">';

        if (showMonthLabels) {
            html += '<div class="heatmap-month-labels">';
            let lastMonth = -1;
            weeks.forEach((week, weekIndex) => {
                const firstCell = week.find(c => c !== null);
                if (firstCell && firstCell.month !== lastMonth) {
                    html += `<span style="left: ${weekIndex * (cellSize + cellGap)}px">${months[firstCell.month]}</span>`;
                    lastMonth = firstCell.month;
                }
            });
            html += '</div>';
        }

        html += '<div class="heatmap-weeks">';
        weeks.forEach(week => {
            html += '<div class="heatmap-week">';
            week.forEach(cell => {
                if (cell === null) {
                    html += `<div class="heatmap-cell empty" style="width: ${cellSize}px; height: ${cellSize}px;"></div>`;
                } else {
                    const tooltip = `${cell.date}: ${cell.value} ore`;
                    html += `<div class="heatmap-cell" data-tooltip="${tooltip}" style="width: ${cellSize}px; height: ${cellSize}px; background-color: ${colorScale[cell.colorIndex]};"></div>`;
                }
            });
            html += '</div>';
        });
        html += '</div></div>';

        // Legenda
        html += '<div class="heatmap-legend">';
        html += '<span>Meno</span>';
        colorScale.forEach(color => {
            html += `<div class="heatmap-legend-cell" style="background-color: ${color};"></div>`;
        });
        html += '<span>Più</span>';
        html += '</div></div>';

        container.innerHTML = html;
    }
};

// ==================== SAVED FILTERS ====================

const SavedFilters = {
    STORAGE_KEY: 'gestionale_saved_filters',

    getAll() {
        try {
            return JSON.parse(localStorage.getItem(this.STORAGE_KEY)) || {};
        } catch {
            return {};
        }
    },

    save(pageKey, filterName, filterData) {
        const filters = this.getAll();
        if (!filters[pageKey]) filters[pageKey] = {};
        filters[pageKey][filterName] = {
            data: filterData,
            createdAt: new Date().toISOString()
        };
        localStorage.setItem(this.STORAGE_KEY, JSON.stringify(filters));
        showToast(`Filtro "${filterName}" salvato`, 'success');
    },

    load(pageKey, filterName) {
        const filters = this.getAll();
        return filters[pageKey]?.[filterName]?.data || null;
    },

    delete(pageKey, filterName) {
        const filters = this.getAll();
        if (filters[pageKey]) {
            delete filters[pageKey][filterName];
            localStorage.setItem(this.STORAGE_KEY, JSON.stringify(filters));
            showToast(`Filtro "${filterName}" eliminato`, 'info');
        }
    },

    getForPage(pageKey) {
        const filters = this.getAll();
        return filters[pageKey] || {};
    },

    /**
     * Renderizza UI per filtri salvati
     */
    renderUI(containerId, pageKey, onApply) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const filters = this.getForPage(pageKey);
        const filterNames = Object.keys(filters);

        if (filterNames.length === 0) {
            container.innerHTML = '<span class="text-muted">Nessun filtro salvato</span>';
            return;
        }

        let html = '<div class="saved-filters-list">';
        filterNames.forEach(name => {
            html += `
                <div class="saved-filter-item" data-filter="${escapeHtml(name)}">
                    <span class="saved-filter-name">${escapeHtml(name)}</span>
                    <div class="saved-filter-actions">
                        <button class="btn-icon" onclick="SavedFilters.applyFilter('${pageKey}', '${escapeHtml(name)}', ${onApply.name})" title="Applica">
                            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                            </svg>
                        </button>
                        <button class="btn-icon danger" onclick="SavedFilters.deleteFilter('${pageKey}', '${escapeHtml(name)}', '${containerId}')" title="Elimina">
                            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </button>
                    </div>
                </div>
            `;
        });
        html += '</div>';
        container.innerHTML = html;
    },

    applyFilter(pageKey, filterName, callback) {
        const data = this.load(pageKey, filterName);
        if (data && typeof callback === 'function') {
            callback(data);
            showToast(`Filtro "${filterName}" applicato`, 'success');
        }
    },

    deleteFilter(pageKey, filterName, containerId) {
        showConfirmDialog(
            'Elimina filtro',
            `Vuoi eliminare il filtro "${filterName}"?`,
            () => {
                this.delete(pageKey, filterName);
                this.renderUI(containerId, pageKey, () => {});
            },
            { type: 'warning' }
        );
    }
};

// ==================== FILTER CHIPS ====================

const FilterChips = {
    /**
     * Renderizza filter chips
     * @param {string} containerId - ID del container
     * @param {object[]} filters - Array di { key, label, value }
     * @param {function} onRemove - Callback quando si rimuove un chip
     */
    render(containerId, filters, onRemove) {
        const container = document.getElementById(containerId);
        if (!container) return;

        if (!filters || filters.length === 0) {
            container.innerHTML = '';
            container.style.display = 'none';
            return;
        }

        container.style.display = 'flex';
        container.innerHTML = filters.map(f => `
            <div class="filter-chip" data-key="${f.key}">
                <span class="filter-chip-label">${escapeHtml(f.label)}:</span>
                <span class="filter-chip-value">${escapeHtml(f.value)}</span>
                <button class="filter-chip-remove" onclick="FilterChips.remove('${containerId}', '${f.key}', ${onRemove.name})">
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                </button>
            </div>
        `).join('');

        // Aggiungi pulsante "Cancella tutti"
        if (filters.length > 1) {
            container.innerHTML += `
                <button class="filter-chip-clear-all" onclick="FilterChips.clearAll('${containerId}', ${onRemove.name})">
                    Cancella tutti
                </button>
            `;
        }
    },

    remove(containerId, key, callback) {
        if (typeof callback === 'function') {
            callback(key);
        }
    },

    clearAll(containerId, callback) {
        if (typeof callback === 'function') {
            callback('__all__');
        }
    }
};

// ==================== FUZZY SEARCH ====================

const FuzzySearch = {
    /**
     * Calcola la distanza di Levenshtein
     */
    levenshtein(a, b) {
        const matrix = [];

        for (let i = 0; i <= b.length; i++) {
            matrix[i] = [i];
        }

        for (let j = 0; j <= a.length; j++) {
            matrix[0][j] = j;
        }

        for (let i = 1; i <= b.length; i++) {
            for (let j = 1; j <= a.length; j++) {
                if (b.charAt(i - 1) === a.charAt(j - 1)) {
                    matrix[i][j] = matrix[i - 1][j - 1];
                } else {
                    matrix[i][j] = Math.min(
                        matrix[i - 1][j - 1] + 1,
                        matrix[i][j - 1] + 1,
                        matrix[i - 1][j] + 1
                    );
                }
            }
        }

        return matrix[b.length][a.length];
    },

    /**
     * Cerca con fuzzy matching
     * @param {string} query - Termine di ricerca
     * @param {object[]} items - Array di oggetti
     * @param {string[]} keys - Chiavi su cui cercare
     * @param {number} threshold - Soglia di similarità (0-1)
     */
    search(query, items, keys, threshold = 0.3) {
        if (!query || query.length < 2) return items;

        const queryLower = query.toLowerCase();

        return items
            .map(item => {
                let bestScore = 0;

                keys.forEach(key => {
                    const value = String(item[key] || '').toLowerCase();

                    // Match esatto
                    if (value.includes(queryLower)) {
                        bestScore = Math.max(bestScore, 1);
                        return;
                    }

                    // Match fuzzy
                    const words = value.split(/\s+/);
                    words.forEach(word => {
                        if (word.length > 0) {
                            const distance = this.levenshtein(queryLower, word);
                            const maxLen = Math.max(queryLower.length, word.length);
                            const similarity = 1 - (distance / maxLen);
                            bestScore = Math.max(bestScore, similarity);
                        }
                    });
                });

                return { item, score: bestScore };
            })
            .filter(result => result.score >= threshold)
            .sort((a, b) => b.score - a.score)
            .map(result => result.item);
    }
};

// ==================== SEARCH HISTORY ====================

const SearchHistory = {
    STORAGE_KEY: 'gestionale_search_history',
    MAX_ITEMS: 10,

    getAll() {
        try {
            return JSON.parse(localStorage.getItem(this.STORAGE_KEY)) || [];
        } catch {
            return [];
        }
    },

    add(query, page = '') {
        if (!query || query.length < 2) return;

        let history = this.getAll();

        // Rimuovi duplicati
        history = history.filter(h => h.query !== query);

        // Aggiungi in cima
        history.unshift({ query, page, timestamp: Date.now() });

        // Limita la lunghezza
        history = history.slice(0, this.MAX_ITEMS);

        localStorage.setItem(this.STORAGE_KEY, JSON.stringify(history));
    },

    clear() {
        localStorage.removeItem(this.STORAGE_KEY);
    },

    renderDropdown(containerId, onSelect) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const history = this.getAll();

        if (history.length === 0) {
            container.innerHTML = '<div class="search-history-empty">Nessuna ricerca recente</div>';
            return;
        }

        let html = '<div class="search-history-header"><span>Ricerche recenti</span><button onclick="SearchHistory.clear(); SearchHistory.renderDropdown(\'' + containerId + '\')">Cancella</button></div>';
        html += '<div class="search-history-list">';

        history.forEach(h => {
            const timeAgo = this.formatTimeAgo(h.timestamp);
            html += `
                <div class="search-history-item" onclick="${onSelect.name}('${escapeHtml(h.query)}')">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <span class="search-history-query">${escapeHtml(h.query)}</span>
                    <span class="search-history-time">${timeAgo}</span>
                </div>
            `;
        });

        html += '</div>';
        container.innerHTML = html;
    },

    formatTimeAgo(timestamp) {
        const seconds = Math.floor((Date.now() - timestamp) / 1000);

        if (seconds < 60) return 'Ora';
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m fa`;
        if (seconds < 86400) return `${Math.floor(seconds / 3600)}h fa`;
        return `${Math.floor(seconds / 86400)}g fa`;
    }
};

// ==================== BOTTOM NAVIGATION (MOBILE) ====================

const BottomNav = {
    init() {
        // Crea bottom nav solo su mobile
        if (window.innerWidth > 768) return;

        const nav = document.createElement('nav');
        nav.className = 'bottom-nav';
        nav.innerHTML = `
            <a href="/" class="bottom-nav-item ${location.pathname === '/' ? 'active' : ''}">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
                </svg>
                <span>Home</span>
            </a>
            <a href="/rendicontazione" class="bottom-nav-item ${location.pathname.includes('rendicontazione') ? 'active' : ''}">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                </svg>
                <span>Rend.</span>
            </a>
            <a href="/utenti" class="bottom-nav-item ${location.pathname.includes('utenti') ? 'active' : ''}">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
                </svg>
                <span>Utenti</span>
            </a>
            <a href="/report" class="bottom-nav-item ${location.pathname.includes('report') ? 'active' : ''}">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <span>Report</span>
            </a>
            <button class="bottom-nav-item" onclick="BottomNav.showMore()">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
                </svg>
                <span>Menu</span>
            </button>
        `;

        document.body.appendChild(nav);
        document.body.classList.add('has-bottom-nav');
    },

    showMore() {
        const sidebar = document.getElementById('sidebar');
        if (sidebar) {
            sidebar.classList.toggle('open');
        }
    }
};

// ==================== PULL TO REFRESH ====================

const PullToRefresh = {
    init(refreshCallback) {
        if (!('ontouchstart' in window)) return;

        let startY = 0;
        let pulling = false;
        const threshold = 80;

        const indicator = document.createElement('div');
        indicator.className = 'pull-to-refresh-indicator';
        indicator.innerHTML = `
            <div class="pull-to-refresh-spinner"></div>
            <span>Rilascia per aggiornare</span>
        `;
        document.body.prepend(indicator);

        document.addEventListener('touchstart', (e) => {
            if (window.scrollY === 0) {
                startY = e.touches[0].pageY;
                pulling = true;
            }
        }, { passive: true });

        document.addEventListener('touchmove', (e) => {
            if (!pulling) return;

            const currentY = e.touches[0].pageY;
            const diff = currentY - startY;

            if (diff > 0 && diff < threshold * 2) {
                indicator.style.transform = `translateY(${Math.min(diff, threshold)}px)`;
                indicator.classList.toggle('ready', diff > threshold);
            }
        }, { passive: true });

        document.addEventListener('touchend', () => {
            if (!pulling) return;
            pulling = false;

            const transform = indicator.style.transform;
            const match = transform.match(/translateY\((\d+)px\)/);
            const distance = match ? parseInt(match[1]) : 0;

            if (distance >= threshold && indicator.classList.contains('ready')) {
                indicator.classList.add('refreshing');

                if (typeof refreshCallback === 'function') {
                    refreshCallback().finally(() => {
                        indicator.classList.remove('refreshing', 'ready');
                        indicator.style.transform = 'translateY(0)';
                    });
                } else {
                    setTimeout(() => {
                        indicator.classList.remove('refreshing', 'ready');
                        indicator.style.transform = 'translateY(0)';
                        location.reload();
                    }, 1000);
                }
            } else {
                indicator.classList.remove('ready');
                indicator.style.transform = 'translateY(0)';
            }
        });
    }
};

// ==================== SWIPE ACTIONS ====================

const SwipeActions = {
    /**
     * Inizializza swipe actions su una riga di tabella
     * @param {HTMLElement} row - Elemento riga
     * @param {object} actions - { left: [...], right: [...] }
     */
    init(row, actions = {}) {
        if (!row || !('ontouchstart' in window)) return;

        let startX = 0;
        let currentX = 0;
        let swiping = false;

        // Crea container azioni
        const leftActions = document.createElement('div');
        leftActions.className = 'swipe-actions swipe-actions-left';

        const rightActions = document.createElement('div');
        rightActions.className = 'swipe-actions swipe-actions-right';

        if (actions.left) {
            actions.left.forEach(action => {
                leftActions.innerHTML += `
                    <button class="swipe-action ${action.class || ''}" onclick="${action.onclick}" style="background: ${action.color || 'var(--primary)'}">
                        ${action.icon || ''}
                        <span>${action.label}</span>
                    </button>
                `;
            });
            row.prepend(leftActions);
        }

        if (actions.right) {
            actions.right.forEach(action => {
                rightActions.innerHTML += `
                    <button class="swipe-action ${action.class || ''}" onclick="${action.onclick}" style="background: ${action.color || 'var(--danger)'}">
                        ${action.icon || ''}
                        <span>${action.label}</span>
                    </button>
                `;
            });
            row.append(rightActions);
        }

        row.classList.add('swipeable');

        row.addEventListener('touchstart', (e) => {
            startX = e.touches[0].pageX;
            swiping = true;
            row.classList.add('swiping');
        }, { passive: true });

        row.addEventListener('touchmove', (e) => {
            if (!swiping) return;
            currentX = e.touches[0].pageX;
            const diff = currentX - startX;

            const maxSwipe = 100;
            const clampedDiff = Math.max(-maxSwipe, Math.min(maxSwipe, diff));

            row.style.transform = `translateX(${clampedDiff}px)`;
        }, { passive: true });

        row.addEventListener('touchend', () => {
            if (!swiping) return;
            swiping = false;
            row.classList.remove('swiping');

            const diff = currentX - startX;
            const threshold = 60;

            if (Math.abs(diff) < threshold) {
                row.style.transform = 'translateX(0)';
            } else {
                row.style.transform = `translateX(${diff > 0 ? '80px' : '-80px'})`;
            }
        });
    },

    reset(row) {
        if (row) {
            row.style.transform = 'translateX(0)';
        }
    }
};

// ==================== NOTIFICATION CENTER ====================

const NotificationCenter = {
    notifications: [],
    unreadCount: 0,

    init() {
        this.loadFromStorage();
        this.renderBadge();
        this.createUI();
    },

    loadFromStorage() {
        try {
            const stored = localStorage.getItem('gestionale_notifications');
            if (stored) {
                this.notifications = JSON.parse(stored);
                this.unreadCount = this.notifications.filter(n => !n.read).length;
            }
        } catch (e) {
            console.error('Error loading notifications:', e);
        }
    },

    saveToStorage() {
        localStorage.setItem('gestionale_notifications', JSON.stringify(this.notifications));
    },

    add(notification) {
        const newNotif = {
            id: Date.now(),
            title: notification.title,
            message: notification.message,
            type: notification.type || 'info',
            timestamp: Date.now(),
            read: false,
            action: notification.action || null
        };

        this.notifications.unshift(newNotif);
        this.notifications = this.notifications.slice(0, 50); // Max 50 notifiche
        this.unreadCount++;

        this.saveToStorage();
        this.renderBadge();
        this.showPopup(newNotif);

        return newNotif.id;
    },

    markAsRead(id) {
        const notif = this.notifications.find(n => n.id === id);
        if (notif && !notif.read) {
            notif.read = true;
            this.unreadCount--;
            this.saveToStorage();
            this.renderBadge();
        }
    },

    markAllAsRead() {
        this.notifications.forEach(n => n.read = true);
        this.unreadCount = 0;
        this.saveToStorage();
        this.renderBadge();
        this.renderList();
    },

    delete(id) {
        const index = this.notifications.findIndex(n => n.id === id);
        if (index > -1) {
            if (!this.notifications[index].read) {
                this.unreadCount--;
            }
            this.notifications.splice(index, 1);
            this.saveToStorage();
            this.renderBadge();
            this.renderList();
        }
    },

    clearAll() {
        this.notifications = [];
        this.unreadCount = 0;
        this.saveToStorage();
        this.renderBadge();
        this.renderList();
    },

    renderBadge() {
        const badges = document.querySelectorAll('.notification-badge-count');
        badges.forEach(badge => {
            if (this.unreadCount > 0) {
                badge.textContent = this.unreadCount > 99 ? '99+' : this.unreadCount;
                badge.style.display = 'flex';
            } else {
                badge.style.display = 'none';
            }
        });
    },

    createUI() {
        // Aggiungi pulsante nella topbar se non esiste
        const topbarRight = document.querySelector('.topbar-right');
        if (topbarRight && !document.getElementById('notification-btn')) {
            const btn = document.createElement('button');
            btn.id = 'notification-btn';
            btn.className = 'topbar-btn';
            btn.innerHTML = `
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                </svg>
                <span class="notification-badge-count" style="display: none;">0</span>
            `;
            btn.onclick = () => this.toggle();
            topbarRight.insertBefore(btn, topbarRight.firstChild);
        }

        // Crea pannello notifiche
        if (!document.getElementById('notification-panel')) {
            const panel = document.createElement('div');
            panel.id = 'notification-panel';
            panel.className = 'notification-panel';
            panel.innerHTML = `
                <div class="notification-panel-header">
                    <h3>Notifiche</h3>
                    <div class="notification-panel-actions">
                        <button onclick="NotificationCenter.markAllAsRead()" title="Segna tutte come lette">
                            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                            </svg>
                        </button>
                        <button onclick="NotificationCenter.clearAll()" title="Cancella tutte">
                            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                            </svg>
                        </button>
                    </div>
                </div>
                <div class="notification-panel-list" id="notification-list"></div>
            `;
            document.body.appendChild(panel);

            // Chiudi cliccando fuori
            document.addEventListener('click', (e) => {
                if (!panel.contains(e.target) && !e.target.closest('#notification-btn')) {
                    panel.classList.remove('open');
                }
            });
        }

        this.renderBadge();
        this.renderList();
    },

    toggle() {
        const panel = document.getElementById('notification-panel');
        if (panel) {
            panel.classList.toggle('open');
            if (panel.classList.contains('open')) {
                this.renderList();
            }
        }
    },

    renderList() {
        const list = document.getElementById('notification-list');
        if (!list) return;

        if (this.notifications.length === 0) {
            list.innerHTML = `
                <div class="notification-empty">
                    <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                    </svg>
                    <p>Nessuna notifica</p>
                </div>
            `;
            return;
        }

        const icons = {
            info: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />',
            success: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />',
            warning: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />',
            error: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />'
        };

        list.innerHTML = this.notifications.map(n => `
            <div class="notification-item ${n.read ? 'read' : ''}" data-id="${n.id}" onclick="NotificationCenter.markAsRead(${n.id})">
                <div class="notification-item-icon ${n.type}">
                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        ${icons[n.type] || icons.info}
                    </svg>
                </div>
                <div class="notification-item-content">
                    <div class="notification-item-title">${escapeHtml(n.title)}</div>
                    <div class="notification-item-message">${escapeHtml(n.message)}</div>
                    <div class="notification-item-time">${this.formatTime(n.timestamp)}</div>
                </div>
                <button class="notification-item-delete" onclick="event.stopPropagation(); NotificationCenter.delete(${n.id})">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                </button>
            </div>
        `).join('');
    },

    showPopup(notification) {
        // Mostra anche un toast per le notifiche in tempo reale
        showToast(notification.message, notification.type, 4000);
    },

    formatTime(timestamp) {
        const diff = Date.now() - timestamp;
        const minutes = Math.floor(diff / 60000);
        const hours = Math.floor(diff / 3600000);
        const days = Math.floor(diff / 86400000);

        if (minutes < 1) return 'Ora';
        if (minutes < 60) return `${minutes}m fa`;
        if (hours < 24) return `${hours}h fa`;
        if (days < 7) return `${days}g fa`;
        return new Date(timestamp).toLocaleDateString('it-IT');
    }
};

// ==================== PROGRESS INDICATOR ====================

const ProgressIndicator = {
    overlay: null,

    show(message = 'Operazione in corso...', options = {}) {
        const { determinate = false, progress = 0, cancelable = false, onCancel = null } = options;

        if (!this.overlay) {
            this.overlay = document.createElement('div');
            this.overlay.className = 'progress-indicator-overlay';
            document.body.appendChild(this.overlay);
        }

        this.overlay.innerHTML = `
            <div class="progress-indicator-content">
                <div class="progress-indicator-spinner ${determinate ? 'hidden' : ''}"></div>
                ${determinate ? `
                    <div class="progress-indicator-bar">
                        <div class="progress-indicator-fill" style="width: ${progress}%"></div>
                    </div>
                    <div class="progress-indicator-percent">${Math.round(progress)}%</div>
                ` : ''}
                <p class="progress-indicator-message">${escapeHtml(message)}</p>
                ${cancelable ? '<button class="btn btn-secondary btn-sm" id="progress-cancel-btn">Annulla</button>' : ''}
            </div>
        `;

        this.overlay.classList.add('active');

        if (cancelable && onCancel) {
            document.getElementById('progress-cancel-btn')?.addEventListener('click', () => {
                onCancel();
                this.hide();
            });
        }
    },

    update(progress, message = null) {
        if (!this.overlay) return;

        const fill = this.overlay.querySelector('.progress-indicator-fill');
        const percent = this.overlay.querySelector('.progress-indicator-percent');
        const msg = this.overlay.querySelector('.progress-indicator-message');

        if (fill) fill.style.width = `${progress}%`;
        if (percent) percent.textContent = `${Math.round(progress)}%`;
        if (message && msg) msg.textContent = message;
    },

    hide() {
        if (this.overlay) {
            this.overlay.classList.remove('active');
        }
    }
};

// ==================== SOUND/HAPTIC FEEDBACK ====================

const Feedback = {
    enabled: localStorage.getItem('feedback_enabled') !== 'false',

    sounds: {
        success: null,
        error: null,
        notification: null,
        click: null
    },

    init() {
        // Pre-carica i suoni (usando Web Audio API per bassa latenza)
        if ('AudioContext' in window || 'webkitAudioContext' in window) {
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
        }
    },

    toggle() {
        this.enabled = !this.enabled;
        localStorage.setItem('feedback_enabled', this.enabled);
        showToast(this.enabled ? 'Feedback sonoro attivato' : 'Feedback sonoro disattivato', 'info');
    },

    play(type = 'click') {
        if (!this.enabled || !this.audioContext) return;

        const frequencies = {
            success: [523.25, 659.25, 783.99], // C5, E5, G5
            error: [311.13, 277.18], // Eb4, C#4
            notification: [659.25, 783.99], // E5, G5
            click: [1000] // 1kHz click
        };

        const freq = frequencies[type] || frequencies.click;
        const duration = type === 'click' ? 0.05 : 0.15;

        freq.forEach((f, i) => {
            const oscillator = this.audioContext.createOscillator();
            const gainNode = this.audioContext.createGain();

            oscillator.connect(gainNode);
            gainNode.connect(this.audioContext.destination);

            oscillator.frequency.value = f;
            oscillator.type = type === 'click' ? 'square' : 'sine';

            gainNode.gain.setValueAtTime(0.1, this.audioContext.currentTime + i * 0.1);
            gainNode.gain.exponentialRampToValueAtTime(0.01, this.audioContext.currentTime + i * 0.1 + duration);

            oscillator.start(this.audioContext.currentTime + i * 0.1);
            oscillator.stop(this.audioContext.currentTime + i * 0.1 + duration);
        });
    },

    haptic(type = 'light') {
        if (!this.enabled || !navigator.vibrate) return;

        const patterns = {
            light: [10],
            medium: [20],
            heavy: [30],
            success: [10, 50, 10],
            error: [50, 30, 50],
            notification: [10, 30, 10, 30, 10]
        };

        navigator.vibrate(patterns[type] || patterns.light);
    },

    success() {
        this.play('success');
        this.haptic('success');
    },

    error() {
        this.play('error');
        this.haptic('error');
    },

    notification() {
        this.play('notification');
        this.haptic('notification');
    },

    click() {
        this.play('click');
        this.haptic('light');
    }
};

// ==================== VIRTUAL SCROLLING ====================

const VirtualScroll = {
    /**
     * Inizializza virtual scrolling per una tabella grande
     * @param {string} containerId - ID del container
     * @param {array} data - Array di dati
     * @param {function} renderRow - Funzione per renderizzare una riga
     * @param {object} options - Opzioni
     */
    init(containerId, data, renderRow, options = {}) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const {
            rowHeight = 48,
            bufferSize = 10,
            tableClass = 'table'
        } = options;

        const totalHeight = data.length * rowHeight;
        let scrollTop = 0;
        let visibleStart = 0;
        let visibleEnd = 0;

        // Crea struttura
        container.innerHTML = `
            <div class="virtual-scroll-container" style="height: 400px; overflow-y: auto;">
                <div class="virtual-scroll-spacer" style="height: ${totalHeight}px; position: relative;">
                    <table class="${tableClass} virtual-table">
                        <thead></thead>
                        <tbody id="${containerId}-tbody"></tbody>
                    </table>
                </div>
            </div>
        `;

        const scrollContainer = container.querySelector('.virtual-scroll-container');
        const tbody = document.getElementById(`${containerId}-tbody`);

        const render = () => {
            const containerHeight = scrollContainer.clientHeight;
            visibleStart = Math.max(0, Math.floor(scrollTop / rowHeight) - bufferSize);
            visibleEnd = Math.min(data.length, Math.ceil((scrollTop + containerHeight) / rowHeight) + bufferSize);

            const fragment = document.createDocumentFragment();

            for (let i = visibleStart; i < visibleEnd; i++) {
                const row = renderRow(data[i], i);
                if (row) {
                    row.style.position = 'absolute';
                    row.style.top = `${i * rowHeight}px`;
                    row.style.width = '100%';
                    fragment.appendChild(row);
                }
            }

            tbody.innerHTML = '';
            tbody.appendChild(fragment);
        };

        scrollContainer.addEventListener('scroll', () => {
            scrollTop = scrollContainer.scrollTop;
            requestAnimationFrame(render);
        });

        render();

        return {
            refresh: (newData) => {
                data = newData;
                container.querySelector('.virtual-scroll-spacer').style.height = `${data.length * rowHeight}px`;
                render();
            },
            scrollTo: (index) => {
                scrollContainer.scrollTop = index * rowHeight;
            }
        };
    }
};

// ==================== LAZY LOADING ====================

const LazyLoad = {
    observer: null,

    init() {
        if ('IntersectionObserver' in window) {
            this.observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        const el = entry.target;

                        if (el.dataset.src) {
                            el.src = el.dataset.src;
                            el.removeAttribute('data-src');
                        }

                        if (el.dataset.bgSrc) {
                            el.style.backgroundImage = `url(${el.dataset.bgSrc})`;
                            el.removeAttribute('data-bg-src');
                        }

                        if (el.dataset.lazyLoad) {
                            const callback = window[el.dataset.lazyLoad];
                            if (typeof callback === 'function') {
                                callback(el);
                            }
                            el.removeAttribute('data-lazy-load');
                        }

                        el.classList.add('lazy-loaded');
                        this.observer.unobserve(el);
                    }
                });
            }, {
                rootMargin: '50px 0px',
                threshold: 0.01
            });
        }
    },

    observe(element) {
        if (this.observer && element) {
            this.observer.observe(element);
        }
    },

    observeAll(selector = '[data-src], [data-bg-src], [data-lazy-load]') {
        document.querySelectorAll(selector).forEach(el => this.observe(el));
    }
};

// ==================== SKELETON STATES ====================

const SkeletonLoader = {
    /**
     * Crea uno skeleton per una card
     */
    card(options = {}) {
        const { lines = 3, hasImage = false, hasActions = false } = options;

        return `
            <div class="skeleton-card">
                ${hasImage ? '<div class="skeleton skeleton-image"></div>' : ''}
                <div class="skeleton-content">
                    <div class="skeleton skeleton-title"></div>
                    ${Array(lines).fill('<div class="skeleton skeleton-text"></div>').join('')}
                </div>
                ${hasActions ? '<div class="skeleton-actions"><div class="skeleton skeleton-btn"></div></div>' : ''}
            </div>
        `;
    },

    /**
     * Crea uno skeleton per una tabella
     */
    table(rows = 5, cols = 4) {
        let html = '<table class="table skeleton-table"><thead><tr>';
        for (let c = 0; c < cols; c++) {
            html += '<th><div class="skeleton skeleton-text" style="width: 80%"></div></th>';
        }
        html += '</tr></thead><tbody>';

        for (let r = 0; r < rows; r++) {
            html += '<tr>';
            for (let c = 0; c < cols; c++) {
                const width = 50 + Math.random() * 40;
                html += `<td><div class="skeleton skeleton-text" style="width: ${width}%"></div></td>`;
            }
            html += '</tr>';
        }

        html += '</tbody></table>';
        return html;
    },

    /**
     * Crea skeleton per stat cards
     */
    statCards(count = 4) {
        return Array(count).fill(`
            <div class="stat-card skeleton-stat-card">
                <div class="skeleton skeleton-text" style="width: 60%"></div>
                <div class="skeleton skeleton-title" style="width: 40%; height: 2rem; margin-top: 0.5rem;"></div>
            </div>
        `).join('');
    },

    /**
     * Mostra skeleton in un container
     */
    show(containerId, type = 'card', options = {}) {
        const container = document.getElementById(containerId);
        if (!container) return;

        let html = '';
        switch (type) {
            case 'card':
                html = this.card(options);
                break;
            case 'cards':
                html = Array(options.count || 3).fill(this.card(options)).join('');
                break;
            case 'table':
                html = this.table(options.rows, options.cols);
                break;
            case 'stat-cards':
                html = this.statCards(options.count);
                break;
        }

        container.innerHTML = html;
        container.classList.add('loading-skeleton');
    },

    /**
     * Nascondi skeleton
     */
    hide(containerId) {
        const container = document.getElementById(containerId);
        if (container) {
            container.classList.remove('loading-skeleton');
        }
    }
};

// ==================== PDF EXPORT ====================

const PDFExport = {
    /**
     * Esporta elemento come PDF (richiede html2pdf.js)
     */
    async export(elementId, filename = 'export.pdf', options = {}) {
        const element = document.getElementById(elementId);
        if (!element) {
            showToast('Elemento non trovato', 'error');
            return;
        }

        // Carica html2pdf.js se non presente
        if (typeof html2pdf === 'undefined') {
            await this.loadLibrary();
        }

        const defaultOptions = {
            margin: 10,
            filename: filename,
            image: { type: 'jpeg', quality: 0.98 },
            html2canvas: { scale: 2, useCORS: true },
            jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
        };

        const mergedOptions = { ...defaultOptions, ...options };

        ProgressIndicator.show('Generazione PDF in corso...');

        try {
            await html2pdf().set(mergedOptions).from(element).save();
            showToast('PDF generato con successo', 'success');
            Feedback.success();
        } catch (error) {
            console.error('PDF export error:', error);
            showToast('Errore nella generazione del PDF', 'error');
            Feedback.error();
        } finally {
            ProgressIndicator.hide();
        }
    },

    async loadLibrary() {
        return new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js';
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }
};

// ==================== EMAIL REPORT ====================

const EmailReport = {
    /**
     * Mostra modal per invio report via email
     */
    showModal(reportType, reportData = {}) {
        const modalHtml = `
            <div class="modal-overlay active" id="email-report-modal">
                <div class="modal">
                    <div class="modal-header">
                        <h2>Invia Report via Email</h2>
                        <button class="modal-close" onclick="closeModal('email-report-modal')">
                            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </button>
                    </div>
                    <div class="modal-body">
                        <div class="form-group">
                            <label for="email-to">Destinatario *</label>
                            <input type="email" id="email-to" class="form-control" placeholder="email@esempio.it" required>
                        </div>
                        <div class="form-group">
                            <label for="email-cc">CC (opzionale)</label>
                            <input type="email" id="email-cc" class="form-control" placeholder="cc@esempio.it">
                        </div>
                        <div class="form-group">
                            <label for="email-subject">Oggetto</label>
                            <input type="text" id="email-subject" class="form-control" value="Report ${reportType} - ${new Date().toLocaleDateString('it-IT')}">
                        </div>
                        <div class="form-group">
                            <label for="email-message">Messaggio (opzionale)</label>
                            <textarea id="email-message" class="form-control" rows="3" placeholder="Aggiungi un messaggio..."></textarea>
                        </div>
                        <div class="form-group">
                            <label class="checkbox-label">
                                <input type="checkbox" id="email-attach-pdf" checked>
                                <span>Allega PDF</span>
                            </label>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" onclick="closeModal('email-report-modal')">Annulla</button>
                        <button class="btn btn-primary" onclick="EmailReport.send('${reportType}')">
                            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                            </svg>
                            Invia
                        </button>
                    </div>
                </div>
            </div>
        `;

        // Rimuovi modal esistente
        document.getElementById('email-report-modal')?.remove();
        document.body.insertAdjacentHTML('beforeend', modalHtml);
    },

    async send(reportType) {
        // Funzionalita' invio email non implementata lato server.
        // Mostriamo un messaggio chiaro invece di una finta chiamata API.
        showToast('Invio email non ancora disponibile. Scarica il report ed invialo manualmente.', 'warning');
    }
};

// ==================== COMPARATIVE CHARTS ====================

const ComparativeCharts = {
    /**
     * Crea un grafico comparativo mese su mese
     */
    createMonthComparison(canvasId, currentData, previousData, labels) {
        const ctx = document.getElementById(canvasId)?.getContext('2d');
        if (!ctx) return;

        return ChartManager.createBarChart(canvasId, labels, [
            { label: 'Mese corrente', data: currentData },
            { label: 'Mese precedente', data: previousData }
        ]);
    },

    /**
     * Crea un grafico comparativo anno su anno
     */
    createYearComparison(canvasId, currentYearData, previousYearData, labels) {
        const ctx = document.getElementById(canvasId)?.getContext('2d');
        if (!ctx) return;

        return ChartManager.createLineChart(canvasId, labels, [
            { label: 'Anno corrente', data: currentYearData },
            { label: 'Anno precedente', data: previousYearData }
        ]);
    }
};

// ==================== SERVICE WORKER REGISTRATION ====================

const OfflineMode = {
    async init() {
        if ('serviceWorker' in navigator) {
            try {
                const registration = await navigator.serviceWorker.register('/static/sw.js');
                console.log('Service Worker registered:', registration.scope);

                // Notifica quando disponibile offline
                registration.addEventListener('updatefound', () => {
                    const newWorker = registration.installing;
                    newWorker.addEventListener('statechange', () => {
                        if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                            NotificationCenter.add({
                                title: 'Aggiornamento disponibile',
                                message: 'Una nuova versione è disponibile. Ricarica la pagina per aggiornarla.',
                                type: 'info'
                            });
                        }
                    });
                });
            } catch (error) {
                console.error('Service Worker registration failed:', error);
            }
        }

        // Listener per stato online/offline
        window.addEventListener('online', () => {
            document.body.classList.remove('offline');
            showToast('Connessione ripristinata', 'success');
        });

        window.addEventListener('offline', () => {
            document.body.classList.add('offline');
            showToast('Modalità offline attiva', 'warning');
        });
    },

    isOnline() {
        return navigator.onLine;
    }
};

// ==================== INITIALIZATION ====================

// Le funzionalità avanzate sono disponibili ma non inizializzate automaticamente
// per evitare conflitti e migliorare le performance.
// Usare: AdvancedFeatures.init() per inizializzare tutto
// oppure inizializzare i singoli moduli manualmente (es: NotificationCenter.init())

const AdvancedFeatures = {
    init() {
        // Init solo se esplicitamente richiesto
        if (document.querySelector('.bottom-nav')) BottomNav.init();
        if (document.querySelector('.notification-center')) NotificationCenter.init();
        // Feedback.init(); // Disabilitato - causa lag
        // LazyLoad.init(); // Disabilitato - può causare conflitti
        // OfflineMode.init(); // SW già registrato in base.html
    }
};

window.AdvancedFeatures = AdvancedFeatures;

// ==================== GLOBAL EXPORTS ====================

window.Sparkline = Sparkline;
window.ProgressRing = ProgressRing;
window.HeatmapCalendar = HeatmapCalendar;
window.SavedFilters = SavedFilters;
window.FilterChips = FilterChips;
window.FuzzySearch = FuzzySearch;
window.SearchHistory = SearchHistory;
window.BottomNav = BottomNav;
window.PullToRefresh = PullToRefresh;
window.SwipeActions = SwipeActions;
window.NotificationCenter = NotificationCenter;
window.ProgressIndicator = ProgressIndicator;
window.Feedback = Feedback;
window.VirtualScroll = VirtualScroll;
window.LazyLoad = LazyLoad;
window.SkeletonLoader = SkeletonLoader;
window.PDFExport = PDFExport;
window.EmailReport = EmailReport;
window.ComparativeCharts = ComparativeCharts;
window.OfflineMode = OfflineMode;

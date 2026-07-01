/**
 * Gestionale OEPAC - JavaScript Premium v2.0
 * Apple-inspired UI interactions
 */

// ==================== CONSTANTS ====================

const MESI = {
    1: 'Gennaio', 2: 'Febbraio', 3: 'Marzo', 4: 'Aprile',
    5: 'Maggio', 6: 'Giugno', 7: 'Luglio', 8: 'Agosto',
    9: 'Settembre', 10: 'Ottobre', 11: 'Novembre', 12: 'Dicembre'
};

const MESI_SCOLASTICI = [9, 10, 11, 12, 1, 2, 3, 4, 5, 6];

// ==================== THEME MANAGEMENT ====================

const ThemeManager = {
    init() {
        const savedTheme = localStorage.getItem('theme') || 'dark';
        this.setTheme(savedTheme, false);

        const toggle = document.getElementById('theme-toggle');
        if (toggle) {
            toggle.addEventListener('click', () => this.toggle());
        }
    },

    setTheme(theme, dispatchEvent = true) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('theme', theme);

        // Dispatch custom event for theme change (useful for charts refresh)
        if (dispatchEvent) {
            window.dispatchEvent(new CustomEvent('themechange', { detail: { theme } }));
        }
    },

    toggle() {
        const current = document.documentElement.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        this.setTheme(next);
    },

    get current() {
        return document.documentElement.getAttribute('data-theme');
    },

    get isDark() {
        return this.current === 'dark';
    }
};

// ==================== SIDEBAR MANAGEMENT ====================

const SidebarManager = {
    init() {
        // Sidebar is now fixed, no collapse functionality
        this.sidebar = document.getElementById('sidebar');
        this.mobileBtn = document.getElementById('mobile-menu-btn');

        // Mobile menu only
        this.mobileBtn?.addEventListener('click', () => this.toggleMobile());

        // Close on mobile when clicking outside
        document.addEventListener('click', (e) => {
            if (window.innerWidth <= 768 &&
                this.sidebar?.classList.contains('open') &&
                !this.sidebar.contains(e.target) &&
                !this.mobileBtn?.contains(e.target)) {
                this.sidebar.classList.remove('open');
                this._syncExpanded();
            }
        });
    },

    toggleMobile() {
        this.sidebar?.classList.toggle('open');
        this._syncExpanded();
    },

    _syncExpanded() {
        // Mantiene aria-expanded del bottone allineato allo stato della sidebar
        const open = this.sidebar?.classList.contains('open') ? 'true' : 'false';
        this.mobileBtn?.setAttribute('aria-expanded', open);
    }
};

// ==================== SEARCH ====================

const SearchManager = {
    init() {
        this.modal = document.getElementById('search-modal');
        this.input = document.getElementById('global-search-input');
        this.results = document.getElementById('search-results');
        this.trigger = document.getElementById('search-trigger');
        this.selectedIndex = -1;

        if (!this.modal || !this.input) return;

        // Open search
        this.trigger?.addEventListener('click', () => this.open());

        // Close on overlay click
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) this.close();
        });

        // Search input
        this.input.addEventListener('input', () => this.search());

        // Keyboard navigation in results
        this.input.addEventListener('keydown', (e) => this.handleKeydown(e));
    },

    open() {
        this.modal?.classList.add('active');
        this.input?.focus();
        this.input.value = '';
        this.selectedIndex = -1;
        this.resetResults();
    },

    close() {
        this.modal?.classList.remove('active');
        this.selectedIndex = -1;
    },

    resetResults() {
        this.results.innerHTML = `
            <div class="search-empty">
                <p>Inizia a digitare per cercare...</p>
                <p class="text-xs mt-2">Premi ESC per chiudere</p>
            </div>
        `;
    },

    async search() {
        const query = this.input.value.trim();
        if (query.length < 2) {
            this.resetResults();
            return;
        }

        try {
            const response = await apiCall(`/api/search?q=${encodeURIComponent(query)}`);
            this.renderResults(response);
        } catch (error) {
            console.error('Search error:', error);
        }
    },

    renderResults(data) {
        const totalResults = (data.pages?.length || 0) + (data.utenti?.length || 0) +
                           (data.scuole?.length || 0) + (data.commesse?.length || 0);

        if (totalResults === 0) {
            this.results.innerHTML = `
                <div class="search-empty">
                    <p>Nessun risultato trovato</p>
                </div>
            `;
            return;
        }

        let html = '';
        let globalIdx = 0;

        // Pages
        if (data.pages?.length) {
            html += '<div class="search-section-label" style="padding: 8px 16px; font-size: 0.7rem; text-transform: uppercase; color: var(--text-quaternary); font-weight: 600;">Pagine</div>';
            data.pages.forEach((page) => {
                html += `
                    <a href="${page.url}" class="search-result-item" data-index="${globalIdx++}">
                        <div class="search-result-icon">
                            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                            </svg>
                        </div>
                        <div class="search-result-content">
                            <div class="search-result-title">${page.title}</div>
                            <div class="search-result-subtitle">Pagina</div>
                        </div>
                    </a>
                `;
            });
        }

        // Commesse
        if (data.commesse?.length) {
            html += '<div class="search-section-label" style="padding: 8px 16px; font-size: 0.7rem; text-transform: uppercase; color: var(--text-quaternary); font-weight: 600;">Commesse</div>';
            data.commesse.forEach((c) => {
                html += `
                    <a href="/commesse" class="search-result-item" data-index="${globalIdx++}">
                        <div class="search-result-icon" style="color: ${c.colore || 'var(--primary)'}">
                            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                            </svg>
                        </div>
                        <div class="search-result-content">
                            <div class="search-result-title">${c.nome}</div>
                            <div class="search-result-subtitle">${c.num_scuole || 0} scuole${c.descrizione ? ' - ' + c.descrizione.substring(0, 30) : ''}</div>
                        </div>
                    </a>
                `;
            });
        }

        // Utenti
        if (data.utenti?.length) {
            html += '<div class="search-section-label" style="padding: 8px 16px; font-size: 0.7rem; text-transform: uppercase; color: var(--text-quaternary); font-weight: 600;">Utenti</div>';
            data.utenti.forEach((u) => {
                html += `
                    <a href="/utenti?search=${encodeURIComponent(u.nome + ' ' + u.cognome)}" class="search-result-item" data-index="${globalIdx++}">
                        <div class="search-result-icon">
                            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                            </svg>
                        </div>
                        <div class="search-result-content">
                            <div class="search-result-title">${u.nome} ${u.cognome}</div>
                            <div class="search-result-subtitle">${u.commessa} - ${(u.scuola || '').substring(0, 40)}...</div>
                        </div>
                    </a>
                `;
            });
        }

        // Scuole
        if (data.scuole?.length) {
            html += '<div class="search-section-label" style="padding: 8px 16px; font-size: 0.7rem; text-transform: uppercase; color: var(--text-quaternary); font-weight: 600;">Scuole</div>';
            data.scuole.forEach((s) => {
                html += `
                    <a href="/utenti?scuola=${s.id}" class="search-result-item" data-index="${globalIdx++}">
                        <div class="search-result-icon">
                            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
                            </svg>
                        </div>
                        <div class="search-result-content">
                            <div class="search-result-title">${(s.nome_completo || '').substring(0, 50)}...</div>
                            <div class="search-result-subtitle">${s.commessa}</div>
                        </div>
                    </a>
                `;
            });
        }

        // Result count footer
        html += `<div style="padding: 8px 16px; font-size: 0.75rem; color: var(--text-quaternary); text-align: center; border-top: 1px solid var(--border-color);">${totalResults} risultati trovati</div>`;

        this.results.innerHTML = html;
    },

    handleKeydown(e) {
        const items = this.results.querySelectorAll('.search-result-item');

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            this.selectedIndex = Math.min(this.selectedIndex + 1, items.length - 1);
            this.updateSelection(items);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            this.selectedIndex = Math.max(this.selectedIndex - 1, 0);
            this.updateSelection(items);
        } else if (e.key === 'Enter' && this.selectedIndex >= 0) {
            e.preventDefault();
            items[this.selectedIndex]?.click();
        }
    },

    updateSelection(items) {
        items.forEach((item, index) => {
            item.classList.toggle('active', index === this.selectedIndex);
        });
    }
};

// ==================== KEYBOARD SHORTCUTS ====================

const KeyboardShortcuts = {
    // Mappa navigazione: Alt+numero -> pagina
    navMap: {
        '1': '/',              // Dashboard
        '2': '/rendicontazione', // Rendicontazione
        '3': '/utenti',        // Utenti
        '4': '/commesse',      // Commesse
        '5': '/import',        // Import
        '6': '/report',        // Report
        '7': '/calendario',    // Calendario
    },

    init() {
        document.addEventListener('keydown', (e) => {
            // Skip se siamo in un input
            const isInput = e.target.matches('input, textarea, select');

            // Cmd/Ctrl + K - Open search
            if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
                e.preventDefault();
                SearchManager.open();
            }

            // Cmd/Ctrl + S - Save (if there's a save button)
            if ((e.metaKey || e.ctrlKey) && e.key === 's') {
                const saveBtn = document.querySelector('[data-action="save"], #btn-save:not(:disabled)');
                if (saveBtn) {
                    e.preventDefault();
                    saveBtn.click();
                }
            }

            // Cmd/Ctrl + Z - Undo (only when not in input)
            if ((e.metaKey || e.ctrlKey) && e.key === 'z' && !isInput) {
                e.preventDefault();
                undoLastAction();
            }

            // Alt + numero: Navigazione rapida tra le pagine
            if (e.altKey && !e.ctrlKey && !e.metaKey && !isInput) {
                const navTarget = this.navMap[e.key];
                if (navTarget) {
                    e.preventDefault();
                    window.location.href = navTarget;
                }
            }

            // ? - Mostra help scorciatoie (solo se non in input)
            if (e.key === '?' && !isInput && !e.ctrlKey && !e.metaKey && !e.altKey) {
                e.preventDefault();
                this.showShortcutsHelp();
            }

            // Escape - Close modals/search
            if (e.key === 'Escape') {
                const activeModal = document.querySelector('.modal-overlay.active');
                if (activeModal) {
                    if (activeModal.id === 'search-modal') {
                        SearchManager.close();
                    } else if (activeModal.id === 'shortcuts-help-modal') {
                        activeModal.remove();
                    } else {
                        activeModal.classList.remove('active');
                        document.body.style.overflow = '';
                    }
                }
            }

            // Cmd/Ctrl + / - Toggle sidebar (disabled - sidebar is fixed)
            if ((e.metaKey || e.ctrlKey) && e.key === '/') {
                e.preventDefault();
                // Sidebar is now fixed, no collapse
            }
        });
    },

    showShortcutsHelp() {
        // Rimuovi se esiste
        document.getElementById('shortcuts-help-modal')?.remove();

        const modal = document.createElement('div');
        modal.id = 'shortcuts-help-modal';
        modal.className = 'modal-overlay active';
        modal.style.cssText = 'position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 9999;';

        modal.innerHTML = `
            <div style="background: var(--bg-primary); border-radius: 16px; padding: 24px; max-width: 400px; width: 90%; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25);">
                <h3 style="margin: 0 0 16px; font-size: 1.1rem; font-weight: 600;">Scorciatoie da tastiera</h3>
                <div style="display: grid; gap: 8px;">
                    <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border-color);">
                        <span>Ricerca globale</span>
                        <kbd style="background: var(--bg-secondary); padding: 2px 8px; border-radius: 4px; font-size: 0.8rem;">Ctrl/Cmd + K</kbd>
                    </div>
                    <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border-color);">
                        <span>Salva modifiche</span>
                        <kbd style="background: var(--bg-secondary); padding: 2px 8px; border-radius: 4px; font-size: 0.8rem;">Ctrl/Cmd + S</kbd>
                    </div>
                    <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border-color);">
                        <span>Annulla</span>
                        <kbd style="background: var(--bg-secondary); padding: 2px 8px; border-radius: 4px; font-size: 0.8rem;">Ctrl/Cmd + Z</kbd>
                    </div>
                    <div style="font-weight: 600; margin-top: 12px; margin-bottom: 4px;">Navigazione rapida</div>
                    <div style="display: flex; justify-content: space-between; padding: 4px 0;">
                        <span>Dashboard</span>
                        <kbd style="background: var(--bg-secondary); padding: 2px 8px; border-radius: 4px; font-size: 0.8rem;">Alt + 1</kbd>
                    </div>
                    <div style="display: flex; justify-content: space-between; padding: 4px 0;">
                        <span>Rendicontazione</span>
                        <kbd style="background: var(--bg-secondary); padding: 2px 8px; border-radius: 4px; font-size: 0.8rem;">Alt + 2</kbd>
                    </div>
                    <div style="display: flex; justify-content: space-between; padding: 4px 0;">
                        <span>Utenti</span>
                        <kbd style="background: var(--bg-secondary); padding: 2px 8px; border-radius: 4px; font-size: 0.8rem;">Alt + 3</kbd>
                    </div>
                    <div style="display: flex; justify-content: space-between; padding: 4px 0;">
                        <span>Commesse</span>
                        <kbd style="background: var(--bg-secondary); padding: 2px 8px; border-radius: 4px; font-size: 0.8rem;">Alt + 4</kbd>
                    </div>
                    <div style="display: flex; justify-content: space-between; padding: 4px 0;">
                        <span>Import</span>
                        <kbd style="background: var(--bg-secondary); padding: 2px 8px; border-radius: 4px; font-size: 0.8rem;">Alt + 5</kbd>
                    </div>
                    <div style="display: flex; justify-content: space-between; padding: 4px 0;">
                        <span>Report</span>
                        <kbd style="background: var(--bg-secondary); padding: 2px 8px; border-radius: 4px; font-size: 0.8rem;">Alt + 6</kbd>
                    </div>
                    <div style="display: flex; justify-content: space-between; padding: 4px 0;">
                        <span>Calendario</span>
                        <kbd style="background: var(--bg-secondary); padding: 2px 8px; border-radius: 4px; font-size: 0.8rem;">Alt + 7</kbd>
                    </div>
                </div>
                <button onclick="this.closest('.modal-overlay').remove()" style="margin-top: 20px; width: 100%; padding: 10px; border: none; background: var(--primary); color: white; border-radius: 8px; cursor: pointer; font-weight: 500;">Chiudi</button>
                <p style="text-align: center; margin-top: 12px; font-size: 0.75rem; color: var(--text-tertiary);">Premi <kbd style="background: var(--bg-secondary); padding: 1px 4px; border-radius: 3px;">?</kbd> per mostrare questa guida</p>
            </div>
        `;

        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.remove();
        });

        document.body.appendChild(modal);
    }
};

// ==================== UTILITIES ====================

/**
 * CONVERSIONE ORE - Funzione critica
 * Converte input in formato ore:minuti OPPURE decimale in ore decimali
 */
function parseTimeInput(value) {
    if (value === '' || value === null || value === undefined) {
        return 0;
    }

    let str = String(value).trim();

    // Se contiene ":" è sicuramente formato ore:minuti
    if (str.includes(':')) {
        const parts = str.split(':');
        const hours = parseInt(parts[0]) || 0;
        const minutes = parseInt(parts[1]) || 0;
        return hours + (minutes / 60);
    }

    // Sostituisci virgola con punto
    str = str.replace(',', '.');

    // Se contiene un punto decimale
    if (str.includes('.')) {
        const parts = str.split('.');
        const intPart = parseInt(parts[0]) || 0;
        const decPart = parts[1] || '0';

        if (decPart.length === 2) {
            const minutes = parseInt(decPart);
            if (minutes <= 59) {
                return intPart + (minutes / 60);
            }
        }
        return parseFloat(str) || 0;
    }

    // Numero intero = ore
    return parseInt(str) || 0;
}

/**
 * Converte ore decimali in formato sessagesimale (HH:MM)
 * Es: 1.50 → "1:30", 2.25 → "2:15", 0.75 → "0:45"
 */
function decimalToSessagesimal(decimal) {
    if (decimal === null || decimal === undefined || decimal === 0) {
        return '';
    }

    const hours = Math.floor(decimal);
    const minutes = Math.round((decimal - hours) * 60);

    // Gestisci arrotondamento (es: 0.999... → 1:00)
    if (minutes === 60) {
        return `${hours + 1}:00`;
    }

    return `${hours}:${minutes.toString().padStart(2, '0')}`;
}

function formatHours(value) {
    return (value || 0).toFixed(2);
}

function formatCurrency(value) {
    return new Intl.NumberFormat('it-IT', {
        style: 'currency',
        currency: 'EUR',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(value || 0);
}

function formatNumber(value, decimals = 2) {
    return (value || 0).toFixed(decimals);
}

// ==================== TOAST NOTIFICATIONS ====================

function showToast(message, type = 'success', duration = 5000) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    const icons = {
        success: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />',
        error: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />',
        warning: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />',
        info: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />'
    };

    toast.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            ${icons[type] || icons.success}
        </svg>
        <span>${escapeHtml(message)}</span>
        <button class="toast-close" onclick="this.parentElement.remove()" aria-label="Chiudi">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
        </button>
    `;
    container.appendChild(toast);

    // Auto-remove con progress bar
    const progressBar = document.createElement('div');
    progressBar.className = 'toast-progress';
    progressBar.style.animationDuration = `${duration}ms`;
    toast.appendChild(progressBar);

    setTimeout(() => {
        toast.style.animation = 'toastSlideIn 0.4s ease reverse';
        setTimeout(() => toast.remove(), 400);
    }, duration);
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ==================== CONFIRM DIALOG ====================

function showConfirmDialog(title, message, onConfirm, options = {}) {
    const {
        confirmText = 'Conferma',
        cancelText = 'Annulla',
        type = 'warning',
        requireInput = false,
        inputPlaceholder = ''
    } = options;

    // Rimuovi dialog precedente se presente
    document.getElementById('confirm-dialog-overlay')?.remove();

    const colorMap = {
        warning: 'var(--warning)',
        danger: 'var(--danger)',
        info: 'var(--primary)',
        success: 'var(--success)'
    };

    const iconMap = {
        warning: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />',
        danger: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />',
        info: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />',
        success: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />'
    };

    const overlay = document.createElement('div');
    overlay.id = 'confirm-dialog-overlay';
    overlay.className = 'confirm-dialog-overlay';

    overlay.innerHTML = `
        <div class="confirm-dialog">
            <div class="confirm-dialog-icon" style="color: ${colorMap[type]}">
                <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    ${iconMap[type] || iconMap.warning}
                </svg>
            </div>
            <h3 class="confirm-dialog-title">${escapeHtml(title)}</h3>
            <p class="confirm-dialog-message">${escapeHtml(message)}</p>
            ${requireInput ? `<input type="text" class="confirm-dialog-input" id="confirm-dialog-input" placeholder="${escapeHtml(inputPlaceholder)}" autocomplete="off">` : ''}
            <div class="confirm-dialog-actions">
                <button class="btn btn-secondary" id="confirm-dialog-cancel">${escapeHtml(cancelText)}</button>
                <button class="btn btn-${type === 'danger' ? 'danger' : 'primary'}" id="confirm-dialog-confirm">${escapeHtml(confirmText)}</button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);

    // Focus sull'input o sul pulsante conferma
    requestAnimationFrame(() => {
        overlay.classList.add('active');
        if (requireInput) {
            document.getElementById('confirm-dialog-input')?.focus();
        } else {
            document.getElementById('confirm-dialog-cancel')?.focus();
        }
    });

    const closeDialog = () => {
        overlay.classList.remove('active');
        setTimeout(() => overlay.remove(), 300);
    };

    document.getElementById('confirm-dialog-cancel').addEventListener('click', closeDialog);

    document.getElementById('confirm-dialog-confirm').addEventListener('click', () => {
        if (requireInput) {
            const inputVal = document.getElementById('confirm-dialog-input')?.value || '';
            onConfirm(inputVal);
        } else {
            onConfirm();
        }
        closeDialog();
    });

    // Chiudi con Escape
    overlay.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeDialog();
        if (e.key === 'Enter' && !requireInput) {
            document.getElementById('confirm-dialog-confirm')?.click();
        }
    });

    // Chiudi cliccando fuori
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) closeDialog();
    });
}

// ==================== FORM VALIDATION ====================

const FormValidator = {
    rules: {
        required: (value) => value !== null && value !== undefined && String(value).trim() !== '',
        maxLength: (value, max) => String(value).length <= max,
        minLength: (value, min) => String(value).length >= min,
        number: (value) => !isNaN(parseFloat(value)) && isFinite(value),
        minValue: (value, min) => parseFloat(value) >= min,
        maxValue: (value, max) => parseFloat(value) <= max,
        integer: (value) => Number.isInteger(Number(value)),
        color: (value) => /^#[0-9a-fA-F]{6}$/.test(value)
    },

    validate(formId, fieldRules) {
        const errors = {};
        let isValid = true;

        // Pulisci errori precedenti
        document.querySelectorAll(`#${formId} .field-error`).forEach(el => el.remove());
        document.querySelectorAll(`#${formId} .form-control.error`).forEach(el => el.classList.remove('error'));

        Object.entries(fieldRules).forEach(([fieldId, rules]) => {
            const input = document.getElementById(fieldId);
            if (!input) return;

            const value = input.value;

            for (const rule of rules) {
                let valid = true;
                let message = '';

                if (rule.type === 'required' && !this.rules.required(value)) {
                    valid = false;
                    message = rule.message || 'Campo obbligatorio';
                } else if (rule.type === 'maxLength' && !this.rules.maxLength(value, rule.value)) {
                    valid = false;
                    message = rule.message || `Massimo ${rule.value} caratteri`;
                } else if (rule.type === 'number' && value && !this.rules.number(value)) {
                    valid = false;
                    message = rule.message || 'Inserisci un numero valido';
                } else if (rule.type === 'minValue' && value && !this.rules.minValue(value, rule.value)) {
                    valid = false;
                    message = rule.message || `Valore minimo: ${rule.value}`;
                } else if (rule.type === 'maxValue' && value && !this.rules.maxValue(value, rule.value)) {
                    valid = false;
                    message = rule.message || `Valore massimo: ${rule.value}`;
                }

                if (!valid) {
                    isValid = false;
                    errors[fieldId] = message;
                    this.showFieldError(input, message);
                    break;
                }
            }
        });

        return { isValid, errors };
    },

    showFieldError(input, message) {
        input.classList.add('error');
        const errorEl = document.createElement('span');
        errorEl.className = 'field-error';
        errorEl.textContent = message;
        input.parentElement.appendChild(errorEl);

        // Rimuovi errore quando l'utente corregge
        input.addEventListener('input', function handler() {
            input.classList.remove('error');
            errorEl.remove();
            input.removeEventListener('input', handler);
        }, { once: true });
    }
};

// ==================== API HELPER ====================

async function apiCall(url, options = {}) {
    try {
        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Errore sconosciuto');
        }

        return data;
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

// ==================== DATE HELPERS ====================

function getCurrentAnnoScolastico() {
    const now = new Date();
    const month = now.getMonth() + 1;
    const year = now.getFullYear();

    if (month >= 9) {
        return `${year}-${year + 1}`;
    } else {
        return `${year - 1}-${year}`;
    }
}

function getCurrentMeseAnno() {
    const now = new Date();
    return {
        mese: now.getMonth() + 1,
        anno: now.getFullYear()
    };
}

async function populateAnniScolastici(selectId) {
    const select = document.getElementById(selectId);
    if (!select) return;

    try {
        const anni = await apiCall('/api/anni-scolastici');
        select.innerHTML = anni.map(anno =>
            `<option value="${anno}">${anno}</option>`
        ).join('');

        const current = getCurrentAnnoScolastico();
        if (anni.includes(current)) {
            select.value = current;
        }
    } catch (error) {
        console.error('Errore caricamento anni scolastici:', error);
    }
}

function populateMesiScolastici(selectId, annoScolastico) {
    const select = document.getElementById(selectId);
    if (!select || !annoScolastico) return;

    const [annoInizio, annoFine] = annoScolastico.split('-').map(Number);

    select.innerHTML = MESI_SCOLASTICI.map(mese => {
        const anno = mese >= 9 ? annoInizio : annoFine;
        return `<option value="${mese}-${anno}">${MESI[mese]} ${anno}</option>`;
    }).join('');

    const current = getCurrentMeseAnno();
    const currentValue = `${current.mese}-${current.anno}`;
    const option = select.querySelector(`option[value="${currentValue}"]`);
    if (option) {
        select.value = currentValue;
    }
}

// ==================== LOADING STATES ====================

function showLoading(containerId, message = 'Caricamento...') {
    const container = document.getElementById(containerId);
    if (container) {
        container.innerHTML = `
            <div class="loading">
                <div class="spinner"></div>
                <p class="loading-text">${message}</p>
            </div>
        `;
    }
}

// Global Loading Overlay
function showGlobalLoading(message = 'Caricamento...') {
    const overlay = document.getElementById('global-loading');
    const textEl = document.getElementById('global-loading-text');
    if (overlay) {
        if (textEl) textEl.textContent = message;
        overlay.classList.add('active');
    }
}

function hideGlobalLoading() {
    const overlay = document.getElementById('global-loading');
    if (overlay) {
        overlay.classList.remove('active');
    }
}

// Button Loading State
function setButtonLoading(button, isLoading, originalText = null) {
    if (!button) return;

    if (isLoading) {
        button._originalHTML = button.innerHTML;
        button.classList.add('loading');
        button.disabled = true;
    } else {
        button.classList.remove('loading');
        button.disabled = false;
        if (button._originalHTML) {
            button.innerHTML = button._originalHTML;
        } else if (originalText) {
            button.innerHTML = originalText;
        }
    }
}

// Enhanced API call with automatic loading state
async function apiCallWithLoading(url, options = {}, loadingMessage = 'Caricamento...') {
    showGlobalLoading(loadingMessage);
    try {
        const response = await apiCall(url, options);
        return response;
    } finally {
        hideGlobalLoading();
    }
}

function showEmptyState(containerId, title, message, actionText = null, actionCallback = null, iconType = 'inbox') {
    const container = document.getElementById(containerId);
    if (container) {
        // Icon variants for different empty states
        const icons = {
            inbox: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />',
            users: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />',
            search: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />',
            document: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />',
            calendar: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />',
            chart: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />',
            folder: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />'
        };

        const iconPath = icons[iconType] || icons.inbox;

        let html = `
            <div class="empty-state">
                <div class="empty-state-icon-wrapper">
                    <svg class="empty-state-icon" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        ${iconPath}
                    </svg>
                </div>
                <h3 class="empty-state-title">${title}</h3>
                <p class="empty-state-text">${message}</p>
        `;

        if (actionText && actionCallback) {
            html += `
                <button class="empty-state-cta" onclick="${actionCallback}">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
                    </svg>
                    ${actionText}
                </button>
            `;
        }

        html += `</div>`;
        container.innerHTML = html;
    }
}

// ==================== MODALS ====================

function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    }
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('active');
        document.body.style.overflow = '';
    }
}

// Close modal clicking outside
document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay') && e.target.id !== 'search-modal') {
        e.target.classList.remove('active');
        document.body.style.overflow = '';
    }
});

// ==================== FILE UPLOAD ====================

function initFileUpload(uploadId, inputId, onFileSelect) {
    const uploadArea = document.getElementById(uploadId);
    const fileInput = document.getElementById(inputId);

    if (!uploadArea || !fileInput) return;

    uploadArea.addEventListener('click', () => fileInput.click());

    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('dragover');
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');

        const files = e.dataTransfer.files;
        if (files.length > 0) {
            onFileSelect(files[0]);
        }
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            onFileSelect(e.target.files[0]);
        }
    });
}

// ==================== CHARTS ====================

const ChartManager = {
    charts: {},

    getColors() {
        const isDark = ThemeManager.current === 'dark';
        return {
            primary: '#0A84FF',
            secondary: '#BF5AF2',
            success: '#30D158',
            warning: '#FF9F0A',
            danger: '#FF453A',
            cyan: '#64D2FF',
            text: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.6)',
            grid: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)'
        };
    },

    createPieChart(canvasId, data, labels) {
        const ctx = document.getElementById(canvasId)?.getContext('2d');
        if (!ctx) return null;

        const colors = this.getColors();

        if (this.charts[canvasId]) {
            this.charts[canvasId].destroy();
        }

        this.charts[canvasId] = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: [colors.primary, colors.secondary, colors.success, colors.warning, colors.danger, colors.cyan],
                    borderWidth: 0,
                    hoverOffset: 8
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '65%',
                plugins: {
                    legend: {
                        display: false
                    }
                }
            }
        });

        return this.charts[canvasId];
    },

    createBarChart(canvasId, labels, datasets) {
        const ctx = document.getElementById(canvasId)?.getContext('2d');
        if (!ctx) return null;

        const colors = this.getColors();

        if (this.charts[canvasId]) {
            this.charts[canvasId].destroy();
        }

        this.charts[canvasId] = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: datasets.map((ds, i) => ({
                    ...ds,
                    backgroundColor: [colors.primary, colors.secondary, colors.success][i] || colors.primary,
                    borderRadius: 6,
                    barThickness: 24
                }))
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: datasets.length > 1,
                        position: 'bottom',
                        labels: {
                            color: colors.text,
                            padding: 20,
                            usePointStyle: true,
                            pointStyle: 'circle'
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: colors.text }
                    },
                    y: {
                        grid: { color: colors.grid },
                        ticks: { color: colors.text },
                        beginAtZero: true
                    }
                }
            }
        });

        return this.charts[canvasId];
    },

    createLineChart(canvasId, labels, datasets) {
        const ctx = document.getElementById(canvasId)?.getContext('2d');
        if (!ctx) return null;

        const colors = this.getColors();

        if (this.charts[canvasId]) {
            this.charts[canvasId].destroy();
        }

        this.charts[canvasId] = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: datasets.map((ds, i) => ({
                    ...ds,
                    borderColor: [colors.primary, colors.secondary, colors.success][i] || colors.primary,
                    backgroundColor: 'transparent',
                    tension: 0.4,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    borderWidth: 3
                }))
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    intersect: false,
                    mode: 'index'
                },
                plugins: {
                    legend: {
                        display: datasets.length > 1,
                        position: 'bottom',
                        labels: {
                            color: colors.text,
                            padding: 20,
                            usePointStyle: true,
                            pointStyle: 'circle'
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: colors.text }
                    },
                    y: {
                        grid: { color: colors.grid },
                        ticks: { color: colors.text },
                        beginAtZero: true
                    }
                }
            }
        });

        return this.charts[canvasId];
    }
};

// ==================== DASHBOARD STATS ====================

async function loadDashboardStats() {
    try {
        const stats = await apiCall('/api/stats/advanced');

        // Update stat cards
        animateCounter(document.getElementById('stat-utenti'), stats.num_utenti || 0);
        animateCounter(document.getElementById('stat-scuole'), stats.num_scuole || 0);
        animateCounter(document.getElementById('stat-commesse'), stats.num_commesse || 0);
        animateCounter(document.getElementById('stat-monte-ore'), stats.monte_ore_totale || 0);

        // Create pie chart for commesse distribution
        if (stats.utenti_per_commessa?.length) {
            const labels = stats.utenti_per_commessa.map(c => c.nome);
            const data = stats.utenti_per_commessa.map(c => c.count);
            ChartManager.createPieChart('chart-commesse', data, labels);

            // Update legend
            const legendContainer = document.getElementById('legend-commesse');
            if (legendContainer) {
                const colors = ['#0A84FF', '#BF5AF2', '#30D158', '#FF9F0A', '#FF453A', '#64D2FF'];
                legendContainer.innerHTML = stats.utenti_per_commessa.map((c, i) => `
                    <div class="legend-item">
                        <span class="legend-dot" style="background: ${colors[i % colors.length]}"></span>
                        <span>${c.nome}: ${c.count}</span>
                    </div>
                `).join('');
            }
        }

        // Create trend chart
        if (stats.trend_mensile?.length) {
            const labels = stats.trend_mensile.map(t => MESI[t.mese]?.substring(0, 3));
            const data = stats.trend_mensile.map(t => t.ore_totali || 0);
            ChartManager.createLineChart('chart-trend', labels, [{
                label: 'Ore Erogate',
                data: data
            }]);
        }

    } catch (error) {
        console.error('Errore caricamento statistiche:', error);
    }
}

function animateCounter(element, targetValue, duration = 1000) {
    if (!element) return;

    const startValue = 0;
    const startTime = performance.now();

    function update(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);

        const easeOutQuart = 1 - Math.pow(1 - progress, 4);
        const currentValue = Math.round(startValue + (targetValue - startValue) * easeOutQuart);

        element.textContent = currentValue.toLocaleString('it-IT');

        if (progress < 1) {
            requestAnimationFrame(update);
        }
    }

    requestAnimationFrame(update);
}

// ==================== POPULATE COMMESSE SELECT ====================

async function populateCommesseSelect(selectId, includeAll = true) {
    const select = document.getElementById(selectId);
    if (!select) return;

    try {
        const commesse = await apiCall('/api/commesse');

        let options = includeAll ? '<option value="">Tutte le commesse</option>' : '';
        options += commesse.map(c =>
            `<option value="${c.nome}" data-color="${c.colore}">${c.nome}</option>`
        ).join('');

        select.innerHTML = options;
    } catch (error) {
        console.error('Errore caricamento commesse:', error);
    }
}

// ==================== COMMAND PALETTE ====================

const CommandPalette = {
    overlay: null,
    input: null,
    results: null,
    items: [],
    selectedIndex: 0,
    isOpen: false,

    init() {
        this.overlay = document.getElementById('command-palette-overlay');
        this.input = document.getElementById('command-input');
        this.results = document.getElementById('command-results');

        if (!this.overlay) return;

        // Raccogli tutti gli items
        this.items = Array.from(this.results.querySelectorAll('.command-item'));

        // Event listeners
        document.addEventListener('keydown', (e) => this.handleGlobalKeydown(e));
        this.input?.addEventListener('input', () => this.handleSearch());
        this.overlay?.addEventListener('click', (e) => {
            if (e.target === this.overlay) this.close();
        });

        // Click su items
        this.items.forEach((item, index) => {
            item.addEventListener('click', () => this.executeItem(item));
            item.addEventListener('mouseenter', () => this.setSelected(index));
        });

        // Pulsante nella topbar
        const cmdBtn = document.getElementById('cmd-palette-btn');
        cmdBtn?.addEventListener('click', () => this.open());
    },

    handleGlobalKeydown(e) {
        // ⌘K o Ctrl+K per aprire
        if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
            e.preventDefault();
            this.toggle();
            return;
        }

        // Shortcuts numerici ⌘1-5
        if ((e.metaKey || e.ctrlKey) && e.key >= '1' && e.key <= '5') {
            e.preventDefault();
            const urls = ['/', '/rendicontazione', '/utenti', '/report', '/commesse'];
            const index = parseInt(e.key) - 1;
            if (urls[index]) window.location.href = urls[index];
            return;
        }

        if (!this.isOpen) return;

        switch (e.key) {
            case 'Escape':
                e.preventDefault();
                this.close();
                break;
            case 'ArrowDown':
                e.preventDefault();
                this.moveSelection(1);
                break;
            case 'ArrowUp':
                e.preventDefault();
                this.moveSelection(-1);
                break;
            case 'Enter':
                e.preventDefault();
                this.executeSelected();
                break;
        }
    },

    toggle() {
        this.isOpen ? this.close() : this.open();
    },

    open() {
        this.isOpen = true;
        this.overlay.classList.add('active');
        this.input.value = '';
        this.input.focus();
        this.resetSearch();
        this.selectedIndex = 0;
        this.updateSelection();
        document.body.style.overflow = 'hidden';
    },

    close() {
        this.isOpen = false;
        this.overlay.classList.remove('active');
        document.body.style.overflow = '';
    },

    handleSearch() {
        const query = this.input.value.toLowerCase().trim();

        this.items.forEach(item => {
            const title = item.querySelector('.command-item-title')?.textContent.toLowerCase() || '';
            const desc = item.querySelector('.command-item-desc')?.textContent.toLowerCase() || '';
            const matches = title.includes(query) || desc.includes(query);
            item.style.display = matches ? 'flex' : 'none';
        });

        // Reset selezione al primo visibile
        const visibleItems = this.items.filter(i => i.style.display !== 'none');
        this.selectedIndex = 0;
        this.updateSelection();
    },

    resetSearch() {
        this.items.forEach(item => item.style.display = 'flex');
    },

    moveSelection(direction) {
        const visibleItems = this.items.filter(i => i.style.display !== 'none');
        if (visibleItems.length === 0) return;

        this.selectedIndex = (this.selectedIndex + direction + visibleItems.length) % visibleItems.length;
        this.updateSelection();
    },

    setSelected(index) {
        this.selectedIndex = index;
        this.updateSelection();
    },

    updateSelection() {
        const visibleItems = this.items.filter(i => i.style.display !== 'none');
        visibleItems.forEach((item, i) => {
            item.classList.toggle('selected', i === this.selectedIndex);
        });

        // Scroll into view
        const selected = visibleItems[this.selectedIndex];
        selected?.scrollIntoView({ block: 'nearest' });
    },

    executeSelected() {
        const visibleItems = this.items.filter(i => i.style.display !== 'none');
        const item = visibleItems[this.selectedIndex];
        if (item) this.executeItem(item);
    },

    executeItem(item) {
        const action = item.dataset.action;
        const url = item.dataset.url;

        if (action === 'navigate' && url) {
            this.close();
            // Animazione di uscita
            document.body.classList.add('page-transition');
            setTimeout(() => {
                window.location.href = url;
            }, 150);
        }
    }
};

// ==================== CONFETTI CELEBRATION ====================

function triggerConfetti() {
    const colors = ['#0A84FF', '#BF5AF2', '#30D158', '#FF9F0A', '#FF453A'];
    const confettiCount = 100;

    for (let i = 0; i < confettiCount; i++) {
        const confetti = document.createElement('div');
        confetti.className = 'confetti';
        confetti.style.cssText = `
            left: ${Math.random() * 100}vw;
            background: ${colors[Math.floor(Math.random() * colors.length)]};
            animation-delay: ${Math.random() * 0.5}s;
            animation-duration: ${1 + Math.random()}s;
        `;
        document.body.appendChild(confetti);

        setTimeout(() => confetti.remove(), 2000);
    }
}

// ==================== INITIALIZATION ====================

document.addEventListener('DOMContentLoaded', () => {
    // Initialize managers
    ThemeManager.init();
    SidebarManager.init();
    SearchManager.init();
    KeyboardShortcuts.init();
    CommandPalette.init();

    // Load dashboard stats if on dashboard
    if (document.getElementById('stat-utenti')) {
        loadDashboardStats();
    }

    // Add entrance animations with stagger
    document.querySelectorAll('.card, .stat-card').forEach((el, index) => {
        el.style.animationDelay = `${index * 0.08}s`;
        el.classList.add('animate-in');
    });

    // Animazione numeri contatori
    document.querySelectorAll('.stat-value[data-target]').forEach(el => {
        animateCounter(el, parseInt(el.dataset.target) || 0);
    });
});

// ==================== UNDO ====================

async function undoLastAction() {
    try {
        const result = await apiCall('/api/undo', { method: 'POST' });
        if (result.success) {
            showToast(result.message || 'Azione annullata', 'info');
            // Ricarica la pagina corrente per aggiornare i dati
            if (typeof loadUtenti === 'function') loadUtenti();
            if (typeof loadDashboardData === 'function') loadDashboardData();
        }
    } catch (e) {
        showToast(e.message || 'Nessuna azione da annullare', 'warning');
    }
}

// ==================== GLOBAL EXPORTS ====================

window.parseTimeInput = parseTimeInput;
window.decimalToSessagesimal = decimalToSessagesimal;
window.formatHours = formatHours;
window.formatCurrency = formatCurrency;
window.formatNumber = formatNumber;
window.showToast = showToast;
window.escapeHtml = escapeHtml;
window.showConfirmDialog = showConfirmDialog;
window.FormValidator = FormValidator;
window.apiCall = apiCall;
window.apiCallWithLoading = apiCallWithLoading;
window.showLoading = showLoading;
window.showGlobalLoading = showGlobalLoading;
window.hideGlobalLoading = hideGlobalLoading;
window.setButtonLoading = setButtonLoading;
window.showEmptyState = showEmptyState;
window.openModal = openModal;
window.closeModal = closeModal;
window.populateAnniScolastici = populateAnniScolastici;
window.populateMesiScolastici = populateMesiScolastici;
window.populateCommesseSelect = populateCommesseSelect;
window.initFileUpload = initFileUpload;
window.animateCounter = animateCounter;
window.ChartManager = ChartManager;
window.CommandPalette = CommandPalette;
window.triggerConfetti = triggerConfetti;
window.undoLastAction = undoLastAction;
window.MESI = MESI;
window.MESI_SCOLASTICI = MESI_SCOLASTICI;

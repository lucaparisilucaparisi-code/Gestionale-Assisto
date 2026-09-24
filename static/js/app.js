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

        // Menu a pannello (fino a 1024px, come nel CSS): si chiude toccando fuori,
        // cioe' sul velo scuro, oppure con Esc. Prima valeva solo fino a 768px e con
        // la finestra a meta' schermo (960px) il menu restava aperto sopra la pagina.
        document.addEventListener('click', (e) => {
            if (this._aPannello() &&
                this.sidebar?.classList.contains('open') &&
                !this.sidebar.contains(e.target) &&
                !this.mobileBtn?.contains(e.target)) {
                this.chiudi();
            }
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.sidebar?.classList.contains('open') &&
                !document.querySelector('.modal-overlay.active')) {
                this.chiudi();
                this.mobileBtn?.focus();
            }
        });
    },

    _aPannello() {
        return window.matchMedia('(max-width: 1024px)').matches;
    },

    toggleMobile() {
        this.sidebar?.classList.toggle('open');
        this._syncExpanded();
    },

    chiudi() {
        this.sidebar?.classList.remove('open');
        this._syncExpanded();
    },

    _syncExpanded() {
        // Mantiene aria-expanded del bottone allineato allo stato della sidebar e
        // mette 'sidebar-open' sul body, che disegna il velo scuro (refine.css)
        const aperto = !!this.sidebar?.classList.contains('open');
        this.mobileBtn?.setAttribute('aria-expanded', aperto ? 'true' : 'false');
        document.body.classList.toggle('sidebar-open', aperto);
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

            // Cmd/Ctrl + K: gestito dalla CommandPalette (listener dedicato)

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
                    if (activeModal.id === 'shortcuts-help-modal') {
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

        // Finestra normale (.modal, come le altre): prima era una terza versione con
        // stili scritti qui, angoli da 16px e fondo nero pieno
        const riga = (nome, tasti) => `<div class="scorciatoia-riga"><span>${nome}</span><kbd class="command-kbd">${tasti}</kbd></div>`;
        const pagine = [['1', 'Dashboard'], ['2', 'Rendicontazione'], ['3', 'Utenti'], ['4', 'Commesse'],
            ['5', 'Import'], ['6', 'Report'], ['7', 'Calendario']];

        const modal = document.createElement('div');
        modal.id = 'shortcuts-help-modal';
        modal.className = 'modal-overlay active';
        modal.innerHTML = `
            <div class="modal" role="dialog" aria-modal="true" aria-labelledby="shortcuts-help-titolo" style="max-width: 420px;">
                <div class="modal-header">
                    <h3 class="modal-title" id="shortcuts-help-titolo">Scorciatoie da tastiera</h3>
                    <button type="button" class="modal-close" data-chiudi aria-label="Chiudi" title="Chiudi">
                        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                    </button>
                </div>
                <div class="modal-body">
                    ${riga('Ricerca rapida', 'Ctrl+K')}
                    ${riga('Salva modifiche', 'Ctrl+S')}
                    ${riga('Annulla', 'Ctrl+Z')}
                    <div class="scorciatoie-sezione">Navigazione rapida</div>
                    ${pagine.map(([n, nome]) => riga(nome, `Alt+${n}`)).join('')}
                    <p class="scorciatoie-nota">Premi <kbd class="command-kbd">?</kbd> per mostrare questa guida</p>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-primary" data-chiudi>Chiudi</button>
                </div>
            </div>
        `;

        modal.addEventListener('click', (e) => {
            if (e.target === modal || e.target.closest('[data-chiudi]')) modal.remove();
        });

        document.body.appendChild(modal);
        modal.querySelector('.modal-footer .btn')?.focus();
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

// ==================== FORMATI ITALIANI (numeri, ore, date) ====================
// Un solo modo di scrivere numeri e date in tutta l'app: '61,94', '5.963,00',
// '28/09/2026', 'settembre 2025'. Prima convivevano '61.94' (toFixed, all'inglese)
// e '1.490,90 €' nella stessa riga, e date tecniche come '2026-09-28'.
// Solo per il testo mostrato: il valore di un <input type="number"> vuole il punto.

function formatHours(value) {
    return formatNumber(value, 2);
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
    let n = Number(value);
    if (!isFinite(n)) n = 0;
    // arrotonda prima, cosi' -0,001 non diventa '-0,00'
    const f = Math.pow(10, decimals);
    n = Math.round(n * f) / f + 0;
    return n.toLocaleString('it-IT', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

/**
 * Ore decimali all'italiana: 61.94 -> '61,94'. Con segno=true i valori positivi
 * hanno il '+' davanti (crediti/saldi: '+56,67', '-19,25').
 */
function formatOre(value, segno = false, decimals = 2) {
    const testo = formatNumber(value, decimals);
    return segno && Number(value) > 0 && testo !== formatNumber(0, decimals) ? `+${testo}` : testo;
}

/** Numero senza zeri inutili: 12 -> '12', 12.5 -> '12,5' (monte ore, giorni). */
function formatNumero(value, maxDecimali = 2) {
    const n = Number(value);
    if (value === null || value === undefined || value === '' || !isFinite(n)) return value == null ? '' : String(value);
    return (n + 0).toLocaleString('it-IT', { maximumFractionDigits: maxDecimali });
}

const _GIORNI_BREVI = ['dom', 'lun', 'mar', 'mer', 'gio', 'ven', 'sab'];

/** '2026-09-28' (anche con l'ora dopo) -> Date locale, senza slittamenti di fuso. */
function _dataDaIso(valore) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(valore || ''));
    return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
}

/**
 * Data all'italiana: '2026-09-28' -> '28/09/2026'; con conGiorno 'lun 28/09/2026'.
 * Un solo mese ('2025-09') diventa 'settembre 2025'. Un valore che non e' una
 * data resta com'e'; vuoto -> ''.
 */
function formatDataIT(valore, conGiorno = false) {
    if (!valore) return '';
    const d = _dataDaIso(valore);
    if (!d) return /^\d{4}-\d{2}$/.test(String(valore)) ? formatMeseIT(valore) : String(valore);
    const testo = `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}/${d.getFullYear()}`;
    return conGiorno ? `${_GIORNI_BREVI[d.getDay()]} ${testo}` : testo;
}

/**
 * Periodo tra due date: '28/09 → 02/10/2026' (stesso anno) o '28/12/2025 → 02/01/2026';
 * senza fine: '28/09/2026 → sempre' (il testo finale si puo' cambiare).
 */
function formatPeriodoIT(da, a, senzaFine = 'sempre') {
    if (!a) return `${formatDataIT(da)} → ${senzaFine}`;
    const d1 = _dataDaIso(da), d2 = _dataDaIso(a);
    if (d1 && d2 && d1.getFullYear() === d2.getFullYear()) {
        return `${formatDataIT(da).slice(0, 5)} → ${formatDataIT(a)}`;
    }
    return `${formatDataIT(da)} → ${formatDataIT(a)}`;
}

/** Mese all'italiana: '2025-09' (o '2025-09-01') -> 'settembre 2025'. */
function formatMeseIT(valore) {
    const m = /^(\d{4})-(\d{2})/.exec(String(valore || ''));
    if (!m) return valore ? String(valore) : '';
    return `${MESI[Number(m[2])].toLowerCase()} ${m[1]}`;
}

/** Data e ora senza secondi: '23/09/2026, 08:43'. */
function formatDataOraIT(valore) {
    if (!valore) return '';
    const d = new Date(String(valore).replace(' ', 'T'));
    if (isNaN(d)) return String(valore);
    return d.toLocaleString('it-IT', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
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
    // anche le virgolette: il risultato finisce spesso dentro title="..." e
    // aria-label="..." (nomi delle scuole, delle persone)
    return div.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// ==================== CONFIRM DIALOG ====================

function showConfirmDialog(title, message, onConfirm, options = {}) {
    // extraText/onExtra: terzo pulsante facoltativo (es. "Apri le Variazioni"),
    // che chiude la conferma senza confermare e fa un'altra cosa
    const {
        confirmText = 'Conferma',
        cancelText = 'Annulla',
        type = 'warning',
        requireInput = false,
        inputPlaceholder = '',
        extraText = '',
        onExtra = null
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
                ${extraText ? `<button class="btn btn-secondary" id="confirm-dialog-extra">${escapeHtml(extraText)}</button>` : ''}
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
            focusInFinestra(document.getElementById('confirm-dialog-input'));
        } else {
            focusInFinestra(document.getElementById('confirm-dialog-cancel'));
        }
    });

    const closeDialog = () => {
        overlay.classList.remove('active');
        setTimeout(() => overlay.remove(), 300);
    };

    document.getElementById('confirm-dialog-cancel').addEventListener('click', closeDialog);
    document.getElementById('confirm-dialog-extra')?.addEventListener('click', () => {
        closeDialog();
        if (typeof onExtra === 'function') onExtra();
    });

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
        // Le opzioni vanno prima degli header: cosi' un chiamante che passa
        // options.headers li integra invece di perdere il Content-Type JSON
        const response = await fetch(url, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...(options.headers || {})
            }
        });

        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            // Errore "ricco": chi chiama puo' reagire al codice (es. UTENTE_DUPLICATO,
            // MESE_CHIUSO) e non solo al testo del messaggio
            const err = new Error(data.error || 'Errore sconosciuto');
            err.status = response.status;
            err.code = data.code || null;
            err.data = data;
            throw err;
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
    } else if (current.anno * 12 + current.mese > annoFine * 12 + 6) {
        // Anno scolastico gia' finito (o luglio/agosto): il mese piu' utile e' giugno,
        // non settembre dell'anno prima
        select.value = select.options[select.options.length - 1].value;
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

// ==================== ICONE E MENU AZIONI DELLE RIGHE ====================

// Icone a linea dello stesso set del menu laterale: prendono il colore del testo
// (stroke=currentColor), al posto delle emoji e dei caratteri ✎ e ×.
const ICONE = {
    matita: 'M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z',
    cestino: 'M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16',
    altro: 'M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 11-2 0 1 1 0 012 0zm7 0a1 1 0 11-2 0 1 1 0 012 0zm7 0a1 1 0 11-2 0 1 1 0 012 0z',
    storico: 'M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z',
    archivia: 'M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4',
    ripristina: 'M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15',
};

/** SVG di un'icona di ICONE, decorativa (il nome lo danno title/aria-label del pulsante). */
function icona(nome, px = 16) {
    return `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" width="${px}" height="${px}" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${ICONE[nome]}"/></svg>`;
}

/**
 * Riga etichetta/valore delle schede Utente e Dipendente (stesso componente nelle
 * due pagine). Il valore arriva gia' in HTML sicuro; se manca compare un trattino
 * grigio, non in grassetto come se fosse un dato vero ('Non specificato').
 */
function rigaDati(etichetta, valore) {
    const vuoto = valore === null || valore === undefined || String(valore).trim() === '';
    return `<div class="dati-riga"><span class="dati-etichetta">${etichetta}</span>` +
        `<span class="dati-valore${vuoto ? ' vuoto' : ''}">${vuoto ? '—' : valore}</span></div>`;
}

/**
 * Menu '⋯' delle azioni secondarie di una riga (Storico, Archivia, Elimina...).
 * voci: [{ testo, icona, azione, pericolo }] oppure 'separatore'.
 * Il menu sta sopra la pagina (position:fixed), cosi' le tabelle che scorrono
 * non lo tagliano; si chiude scegliendo una voce, cliccando fuori o con Esc.
 * Frecce su/giu' per spostarsi tra le voci.
 */
const MenuAzioni = {
    el: null,
    trigger: null,

    apri(trigger, voci) {
        const giaAperto = this.trigger === trigger;
        this.chiudi(false);
        if (giaAperto) return;   // secondo clic sullo stesso pulsante: chiude
        const menu = document.createElement('div');
        menu.className = 'menu-azioni';
        menu.setAttribute('role', 'menu');
        voci.forEach(v => {
            if (v === 'separatore') {
                menu.insertAdjacentHTML('beforeend', '<div class="menu-azioni-sep" role="separator"></div>');
                return;
            }
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'menu-azioni-voce' + (v.pericolo ? ' pericolo' : '');
            b.setAttribute('role', 'menuitem');
            b.innerHTML = (v.icona ? icona(v.icona) : '') + `<span>${escapeHtml(v.testo)}</span>`;
            b.addEventListener('click', () => { this.chiudi(false); v.azione(); });
            menu.appendChild(b);
        });
        document.body.appendChild(menu);
        this.el = menu;
        this.trigger = trigger;
        trigger.setAttribute('aria-expanded', 'true');

        this._posiziona();
        if (!this.el) return;   // pulsante fuori vista: niente menu
        menu.querySelector('.menu-azioni-voce')?.focus({ preventScroll: true });

        this._fuori = (e) => { if (!menu.contains(e.target) && !trigger.contains(e.target)) this.chiudi(false); };
        this._tasti = (e) => {
            const voci = [...menu.querySelectorAll('.menu-azioni-voce')];
            const i = voci.indexOf(document.activeElement);
            if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); this.chiudi(true); }
            else if (e.key === 'ArrowDown') { e.preventDefault(); voci[(i + 1) % voci.length].focus(); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); voci[(i - 1 + voci.length) % voci.length].focus(); }
            else if (e.key === 'Tab') { this.chiudi(true); }   // Tab riparte dal pulsante '⋯'
        };
        // se la pagina o la tabella scorrono il menu segue il pulsante (si chiude
        // quando il pulsante esce dalla vista)
        this._scorri = () => this._posiziona();
        document.addEventListener('click', this._fuori, true);
        document.addEventListener('keydown', this._tasti, true);
        window.addEventListener('scroll', this._scorri, true);
        window.addEventListener('resize', this._scorri);
    },

    _posiziona() {
        const menu = this.el, trigger = this.trigger;
        if (!menu || !trigger) return;
        const r = trigger.getBoundingClientRect();
        if (r.bottom < 0 || r.top > window.innerHeight || r.right < 0 || r.left > window.innerWidth || !r.width) {
            this.chiudi(false);
            return;
        }
        // sotto il pulsante, allineato al suo bordo destro; sopra se in basso non c'e' posto
        const w = menu.offsetWidth, h = menu.offsetHeight;
        const left = Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8));
        const top = (r.bottom + 4 + h > window.innerHeight - 8 && r.top - 4 - h > 8) ? r.top - 4 - h : r.bottom + 4;
        menu.style.left = `${left}px`;
        menu.style.top = `${top}px`;
    },

    chiudi(rimettiFocus) {
        if (!this.el) return;
        document.removeEventListener('click', this._fuori, true);
        document.removeEventListener('keydown', this._tasti, true);
        window.removeEventListener('scroll', this._scorri, true);
        window.removeEventListener('resize', this._scorri);
        this.el.remove();
        this.el = null;
        const t = this.trigger;
        this.trigger = null;
        if (t) {
            t.setAttribute('aria-expanded', 'false');
            if (rimettiFocus) t.focus();
        }
    }
};

// ==================== MODALS ====================

// Elemento che aveva il focus prima dell'apertura, per ripristinarlo alla chiusura
let _modalFocusPrecedente = null;

/**
 * Mette il focus su un elemento di una finestra appena aperta. Le finestre passano
 * da visibility:hidden a visible con una transizione: nell'istante dell'apertura
 * sono ancora 'hidden' e focus() non ha effetto (con Ctrl+K si scriveva nel vuoto).
 * Se il primo tentativo non riesce, si riprova appena la finestra e' visibile.
 */
function focusInFinestra(el) {
    if (!el || !el.focus) return;
    el.focus();
    if (document.activeElement === el) return;
    requestAnimationFrame(() => requestAnimationFrame(() => {
        if (document.activeElement !== el) el.focus();
    }));
    setTimeout(() => { if (document.activeElement !== el && el.offsetParent !== null) el.focus(); }, 120);
}

const _FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), ' +
                   'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';

        // Semantica dialog + focus dentro la modale (screen reader e tastiera)
        const dialog = modal.querySelector('.modal, .modal-content') || modal;
        dialog.setAttribute('role', 'dialog');
        dialog.setAttribute('aria-modal', 'true');
        _modalFocusPrecedente = document.activeElement;
        const primo = dialog.querySelector(_FOCUSABLE);
        focusInFinestra(primo || dialog);

        // Trap del Tab: il focus cicla dentro la modale
        modal.addEventListener('keydown', _modalTrapTab);
    }
}

function _modalTrapTab(e) {
    if (e.key !== 'Tab') return;
    const modal = e.currentTarget;
    const focusabili = Array.from(modal.querySelectorAll(_FOCUSABLE))
        .filter(el => el.offsetParent !== null);
    if (!focusabili.length) return;
    const primo = focusabili[0];
    const ultimo = focusabili[focusabili.length - 1];
    if (e.shiftKey && document.activeElement === primo) {
        e.preventDefault(); ultimo.focus();
    } else if (!e.shiftKey && document.activeElement === ultimo) {
        e.preventDefault(); primo.focus();
    }
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('active');
        modal.removeEventListener('keydown', _modalTrapTab);
        document.body.style.overflow = '';
        // Ripristina il focus sull'elemento che ha aperto la modale
        _modalFocusPrecedente?.focus?.();
        _modalFocusPrecedente = null;
    }
}

// Close modal clicking outside
document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay')) {
        e.target.classList.remove('active');
        document.body.style.overflow = '';
        _modalFocusPrecedente?.focus?.();
        _modalFocusPrecedente = null;
    }
});

// ==================== FILE UPLOAD ====================

function initFileUpload(uploadId, inputId, onFileSelect) {
    const uploadArea = document.getElementById(uploadId);
    const fileInput = document.getElementById(inputId);

    if (!uploadArea || !fileInput) return;

    uploadArea.addEventListener('click', () => fileInput.click());

    // Raggiungibile anche con la tastiera (Tab, poi Invio o Spazio): il campo file
    // vero e' nascosto con display:none e prima la zona si poteva usare solo col mouse.
    if (!uploadArea.hasAttribute('tabindex')) uploadArea.setAttribute('tabindex', '0');
    uploadArea.setAttribute('role', 'button');
    uploadArea.addEventListener('keydown', (e) => {
        if (e.target !== uploadArea) return;
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            fileInput.click();
        }
    });

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
    // Come ridisegnare ogni grafico: al cambio di tema si rifanno tutti con i
    // colori nuovi (prima assi e griglia restavano bianchi sul fondo chiaro).
    _ricette: {},

    /**
     * Colori dei grafici presi dai token CSS del tema attivo: un solo blu
     * (--primary) per le ore erogate, grigio neutro per i riferimenti (ore
     * previste), le tinte di stato per il resto. Prima era una tavolozza scritta
     * a mano (#0A84FF, un azzurro diverso dai pulsanti, e il viola #BF5AF2).
     */
    getColors() {
        const css = getComputedStyle(document.documentElement);
        const token = (nome, riserva) => (css.getPropertyValue(nome) || '').trim() || riserva;
        const isDark = ThemeManager.current !== 'light';
        const c = {
            primary: token('--primary', '#3B82F6'),
            neutro: isDark ? '#6B7280' : '#CBD5E1',
            success: token('--success', '#30D158'),
            warning: token('--warning', '#FF9F0A'),
            danger: token('--danger', '#FF453A'),
            cyan: token('--cyan', '#64D2FF'),
            text: isDark ? 'rgba(255,255,255,0.72)' : 'rgba(0,0,0,0.68)',
            grid: isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)',
            fondo: token('--bg-card-solid', isDark ? '#1C1C1E' : '#FFFFFF'),
            testo: token('--text-primary', isDark ? '#FFFFFF' : '#000000'),
            tooltipBg: isDark ? 'rgba(28, 28, 30, 0.95)' : 'rgba(255, 255, 255, 0.97)',
            tooltipText: isDark ? '#FFFFFF' : '#1D1D1F',
            tooltipBody: isDark ? 'rgba(255,255,255,0.8)' : 'rgba(0,0,0,0.72)',
            tooltipBorder: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.12)'
        };
        // ripiego per le serie senza un colore proprio
        c.serie = [c.primary, c.neutro, c.success, c.warning, c.danger, c.cyan];
        return c;
    },

    /** Riquadro del suggerimento coerente col tema (stesso aspetto in tutte le pagine). */
    tooltip(colors, extra = {}) {
        return {
            backgroundColor: colors.tooltipBg,
            titleColor: colors.tooltipText,
            bodyColor: colors.tooltipBody,
            borderColor: colors.tooltipBorder,
            borderWidth: 1,
            cornerRadius: 8,
            padding: 12,
            ...extra
        };
    },

    /** Libera la tela: un secondo 'new Chart' sulla stessa tela va in errore. */
    _libera(canvasId) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return null;
        Chart.getChart(canvas)?.destroy();
        delete this.charts[canvasId];
        return canvas;
    },

    /**
     * Ciambella. `colori` (facoltativo): un colore per fetta, per esempio il
     * colore scelto per ogni commessa in Impostazioni > Commesse. Al centro il
     * totale con `etichettaTotale` (es. 'utenti').
     */
    createPieChart(canvasId, data, labels, colori = null, etichettaTotale = '') {
        this._ricette[canvasId] = () => this.createPieChart(canvasId, data, labels, colori, etichettaTotale);
        const canvas = this._libera(canvasId);
        if (!canvas) return null;

        const colors = this.getColors();
        const totale = data.reduce((a, b) => a + (Number(b) || 0), 0);
        const testoCentrale = {
            id: 'testoCentrale',
            afterDraw(chart) {
                if (!etichettaTotale) return;
                const meta = chart.getDatasetMeta(0);
                const arco = meta && meta.data && meta.data[0];
                if (!arco) return;
                const { ctx } = chart;
                ctx.save();
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillStyle = colors.testo;
                ctx.font = '700 22px -apple-system, "Segoe UI", Roboto, sans-serif';
                ctx.fillText(totale.toLocaleString('it-IT'), arco.x, arco.y - 7);
                ctx.fillStyle = colors.text;
                ctx.font = '500 12px -apple-system, "Segoe UI", Roboto, sans-serif';
                ctx.fillText(etichettaTotale, arco.x, arco.y + 14);
                ctx.restore();
            }
        };

        this.charts[canvasId] = new Chart(canvas, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: labels.map((_, i) => (colori && colori[i]) || colors.serie[i % colors.serie.length]),
                    borderColor: colors.fondo,
                    borderWidth: 2,
                    hoverOffset: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '68%',
                plugins: {
                    legend: { display: false },
                    tooltip: this.tooltip(colors)
                }
            },
            plugins: [testoCentrale]
        });

        return this.charts[canvasId];
    },

    /**
     * Barre. Ogni serie puo' portare il suo colore (backgroundColor) oppure un
     * `ruolo` della tavolozza del tema ('primary', 'neutro', ...): prima il colore
     * veniva sempre sostituito, per questo le "ore previste" uscivano viola pieno.
     * `unita` (es. 'ore') compare nel suggerimento e sull'asse.
     */
    createBarChart(canvasId, labels, datasets, unita = '') {
        this._ricette[canvasId] = () => this.createBarChart(canvasId, labels, datasets, unita);
        const canvas = this._libera(canvasId);
        if (!canvas) return null;

        const colors = this.getColors();
        const conUnita = (v) => `${formatNumber(v)}${unita ? ' ' + unita : ''}`;

        this.charts[canvasId] = new Chart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: datasets.map((ds, i) => ({
                    ...ds,
                    backgroundColor: ds.backgroundColor ?? colors[ds.ruolo] ?? colors.serie[i] ?? colors.primary,
                    borderRadius: 4,
                    maxBarThickness: 24
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
                            pointStyle: 'rectRounded'
                        }
                    },
                    tooltip: this.tooltip(colors, {
                        callbacks: { label: (ctx) => `${ctx.dataset.label}: ${conUnita(ctx.parsed.y)}` }
                    })
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: colors.text }
                    },
                    y: {
                        grid: { color: colors.grid },
                        ticks: { color: colors.text, callback: (v) => Number(v).toLocaleString('it-IT') },
                        title: { display: !!unita, text: unita, color: colors.text },
                        beginAtZero: true
                    }
                }
            }
        });

        return this.charts[canvasId];
    },

    createLineChart(canvasId, labels, datasets, unita = '') {
        this._ricette[canvasId] = () => this.createLineChart(canvasId, labels, datasets, unita);
        const canvas = this._libera(canvasId);
        if (!canvas) return null;

        const colors = this.getColors();
        const conUnita = (v) => `${formatNumber(v)}${unita ? ' ' + unita : ''}`;

        this.charts[canvasId] = new Chart(canvas, {
            type: 'line',
            data: {
                labels: labels,
                datasets: datasets.map((ds, i) => {
                    const colore = ds.borderColor ?? colors[ds.ruolo] ?? colors.serie[i] ?? colors.primary;
                    return {
                        ...ds,
                        borderColor: colore,
                        backgroundColor: ds.backgroundColor ?? 'transparent',
                        pointBackgroundColor: colore,
                        tension: 0.3,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        borderWidth: 3
                    };
                })
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
                    },
                    tooltip: this.tooltip(colors, {
                        callbacks: { label: (ctx) => conUnita(ctx.parsed.y) }
                    })
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: colors.text }
                    },
                    y: {
                        grid: { color: colors.grid },
                        ticks: { color: colors.text, callback: (v) => Number(v).toLocaleString('it-IT') },
                        title: { display: !!unita, text: unita, color: colors.text },
                        beginAtZero: true
                    }
                }
            }
        });

        return this.charts[canvasId];
    },

    /** Ridisegna i grafici ancora presenti nella pagina con i colori del tema attivo. */
    aggiornaTema() {
        Object.entries(this._ricette).forEach(([canvasId, ridisegna]) => {
            if (document.getElementById(canvasId)) ridisegna();
            else delete this._ricette[canvasId];
        });
    }
};

window.addEventListener('themechange', () => ChartManager.aggiornaTema());

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

        // Niente Ctrl+1..5 qui: in Chrome ed Edge passano da una scheda del browser
        // all'altra. Le scorciatoie di pagina sono Alt+numero (KeyboardShortcuts.navMap),
        // le stesse indicate nella ricerca.

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
        focusInFinestra(this.input);
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
    KeyboardShortcuts.init();
    CommandPalette.init();

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
window.formatOre = formatOre;
window.formatNumero = formatNumero;
window.formatDataIT = formatDataIT;
window.formatPeriodoIT = formatPeriodoIT;
window.formatMeseIT = formatMeseIT;
window.formatDataOraIT = formatDataOraIT;
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
window.icona = icona;
window.rigaDati = rigaDati;
window.MenuAzioni = MenuAzioni;
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

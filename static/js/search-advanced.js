/**
 * Advanced Search System
 * Sistema di ricerca avanzato con fuzzy search, highlighting e suggerimenti
 */

class AdvancedSearch {
    constructor(options = {}) {
        this.input = typeof options.input === 'string'
            ? document.querySelector(options.input)
            : options.input;
        this.container = options.container || this.input?.closest('.search-bar-container');
        this.targetSelector = options.targetSelector || 'tbody tr[data-utente-id]';
        this.searchFields = options.searchFields || ['nome', 'cognome', 'scuola'];
        this.minChars = options.minChars || 1;
        this.debounceTime = options.debounceTime || 150;
        this.fuzzySearch = options.fuzzySearch !== false;
        this.highlightClass = options.highlightClass || 'search-highlight';
        this.onSearch = options.onSearch || null;
        this.onClear = options.onClear || null;

        // State
        this.debounceTimeout = null;
        this.searchHistory = this.loadSearchHistory();
        this.currentResults = [];
        this.selectedIndex = -1;

        // UI Elements
        this.resultsCount = null;
        this.clearBtn = null;
        this.suggestionsPanel = null;

        if (this.input) {
            this.init();
        }
    }

    init() {
        this.createUI();
        this.bindEvents();
        this.addAccessibility();
    }

    createUI() {
        // Crea/trova il counter dei risultati
        this.resultsCount = this.container?.querySelector('.search-results-count')
            || this.createResultsCounter();

        // Crea/trova il pulsante clear
        this.clearBtn = this.container?.querySelector('.search-clear')
            || this.createClearButton();

        // Crea il pannello suggerimenti
        this.suggestionsPanel = this.createSuggestionsPanel();

        // Aggiungi classe per stile avanzato
        this.container?.classList.add('search-advanced');

        // Crea indicatore di ricerca
        this.createSearchIndicator();
    }

    createResultsCounter() {
        const counter = document.createElement('span');
        counter.className = 'search-results-count';
        this.container?.appendChild(counter);
        return counter;
    }

    createClearButton() {
        const btn = document.createElement('button');
        btn.className = 'search-clear';
        btn.type = 'button';
        btn.title = 'Cancella ricerca (Esc)';
        btn.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" width="18" height="18">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
        `;
        btn.style.display = 'none';
        this.input?.parentElement?.appendChild(btn);
        return btn;
    }

    createSuggestionsPanel() {
        const panel = document.createElement('div');
        panel.className = 'search-suggestions';
        panel.setAttribute('role', 'listbox');
        panel.setAttribute('aria-label', 'Suggerimenti di ricerca');
        this.container?.appendChild(panel);
        return panel;
    }

    createSearchIndicator() {
        const indicator = document.createElement('div');
        indicator.className = 'search-indicator';
        indicator.innerHTML = `
            <div class="search-indicator-spinner"></div>
        `;
        this.container?.appendChild(indicator);
        this.searchIndicator = indicator;
    }

    bindEvents() {
        // Input events
        this.input?.addEventListener('input', (e) => this.handleInput(e));
        this.input?.addEventListener('keydown', (e) => this.handleKeydown(e));
        this.input?.addEventListener('focus', () => this.handleFocus());
        this.input?.addEventListener('blur', () => this.handleBlur());

        // Clear button
        this.clearBtn?.addEventListener('click', () => this.clear());

        // Shortcut globale per focus su ricerca
        document.addEventListener('keydown', (e) => {
            if ((e.key === 'f' || e.key === 'F') && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                this.input?.focus();
            }
        });
    }

    addAccessibility() {
        this.input?.setAttribute('role', 'searchbox');
        this.input?.setAttribute('aria-autocomplete', 'list');
        this.input?.setAttribute('aria-controls', 'search-suggestions');
        this.input?.setAttribute('aria-expanded', 'false');
    }

    handleInput(e) {
        const query = e.target.value;

        // Mostra/nascondi clear button
        this.clearBtn.style.display = query ? 'flex' : 'none';

        // Debounce
        clearTimeout(this.debounceTimeout);

        if (query.length === 0) {
            this.clear(false);
            return;
        }

        if (query.length < this.minChars) {
            return;
        }

        // Mostra indicatore di ricerca
        this.showSearching();

        this.debounceTimeout = setTimeout(() => {
            this.performSearch(query);
        }, this.debounceTime);
    }

    handleKeydown(e) {
        switch(e.key) {
            case 'Escape':
                this.clear();
                this.input?.blur();
                break;
            case 'ArrowDown':
                e.preventDefault();
                this.navigateSuggestions(1);
                break;
            case 'ArrowUp':
                e.preventDefault();
                this.navigateSuggestions(-1);
                break;
            case 'Enter':
                e.preventDefault();
                this.selectSuggestion();
                break;
        }
    }

    handleFocus() {
        this.container?.classList.add('search-focused');

        // Mostra suggerimenti dalla storia se input vuoto
        if (!this.input?.value && this.searchHistory.length > 0) {
            this.showHistory();
        }
    }

    handleBlur() {
        // Delay per permettere click su suggerimenti
        setTimeout(() => {
            this.container?.classList.remove('search-focused');
            this.hideSuggestions();
        }, 200);
    }

    performSearch(query) {
        const normalizedQuery = this.normalizeString(query);
        const rows = document.querySelectorAll(this.targetSelector);

        let matchCount = 0;
        const matchedGroups = new Set();

        rows.forEach(row => {
            // Rimuovi highlight precedenti
            this.removeHighlights(row);

            // Raccogli testo da cercare
            const searchableText = this.getSearchableText(row);

            // Verifica match
            const isMatch = this.fuzzySearch
                ? this.fuzzyMatch(normalizedQuery, searchableText)
                : searchableText.includes(normalizedQuery);

            if (isMatch) {
                row.classList.remove('search-hidden');
                row.classList.add('search-match');
                matchCount++;

                // Evidenzia i match
                this.highlightMatches(row, query);

                // Trova il gruppo (scuola header)
                const groupHeader = this.findGroupHeader(row);
                if (groupHeader) {
                    matchedGroups.add(groupHeader);
                }
            } else {
                row.classList.add('search-hidden');
                row.classList.remove('search-match');
            }
        });

        // Mostra/nascondi group headers
        this.updateGroupHeaders(matchedGroups);

        // Aggiorna totale righe
        this.updateTotaleRighe(rows, matchedGroups);

        // Aggiorna UI
        this.updateResultsCount(matchCount, rows.length);
        this.hideSearching();

        // Salva nella storia
        if (matchCount > 0 && query.length >= 2) {
            this.addToHistory(query);
        }

        // Callback
        if (this.onSearch) {
            this.onSearch(query, matchCount, this.currentResults);
        }
    }

    getSearchableText(row) {
        let text = '';

        // Cerca nelle celle specificate
        this.searchFields.forEach(field => {
            const cell = row.querySelector(`td[data-field="${field}"]`)
                || row.querySelector(`td:first-child`);
            if (cell) {
                text += ' ' + cell.textContent;
            }
        });

        // Aggiungi anche dati da attributi
        if (row.dataset.nome) text += ' ' + row.dataset.nome;
        if (row.dataset.cognome) text += ' ' + row.dataset.cognome;
        if (row.dataset.scuola) text += ' ' + row.dataset.scuola;

        // Se non ci sono campi specifici, prendi tutto il testo della riga
        if (!text.trim()) {
            text = row.textContent;
        }

        return this.normalizeString(text);
    }

    normalizeString(str) {
        return str
            .toLowerCase()
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '') // Rimuove accenti
            .trim();
    }

    fuzzyMatch(query, text) {
        // Match fuzzy: ogni carattere della query deve apparire in ordine nel testo
        let queryIndex = 0;
        const queryLen = query.length;

        for (let i = 0; i < text.length && queryIndex < queryLen; i++) {
            if (text[i] === query[queryIndex]) {
                queryIndex++;
            }
        }

        // Se tutti i caratteri sono stati trovati, è un match
        // Ma verifichiamo anche la substring normale per risultati migliori
        return queryIndex === queryLen || text.includes(query);
    }

    highlightMatches(row, query) {
        const words = query.trim().split(/\s+/);

        // Evidenzia nelle celle testuali
        row.querySelectorAll('td').forEach(cell => {
            // Salta celle con input
            if (cell.querySelector('input, select')) return;

            words.forEach(word => {
                if (word.length >= 2) {
                    this.highlightText(cell, word);
                }
            });
        });
    }

    highlightText(element, query) {
        const walker = document.createTreeWalker(
            element,
            NodeFilter.SHOW_TEXT,
            null,
            false
        );

        const nodesToHighlight = [];
        let node;

        while (node = walker.nextNode()) {
            const text = node.textContent;
            const normalizedText = this.normalizeString(text);
            const normalizedQuery = this.normalizeString(query);
            const index = normalizedText.indexOf(normalizedQuery);

            if (index !== -1) {
                nodesToHighlight.push({ node, index, length: query.length });
            }
        }

        // Applica highlight (in ordine inverso per non invalidare gli indici)
        nodesToHighlight.reverse().forEach(({ node, index, length }) => {
            const text = node.textContent;
            const before = text.substring(0, index);
            const match = text.substring(index, index + length);
            const after = text.substring(index + length);

            const span = document.createElement('span');
            span.className = this.highlightClass;
            span.textContent = match;

            const fragment = document.createDocumentFragment();
            if (before) fragment.appendChild(document.createTextNode(before));
            fragment.appendChild(span);
            if (after) fragment.appendChild(document.createTextNode(after));

            node.parentNode.replaceChild(fragment, node);
        });
    }

    removeHighlights(element) {
        element.querySelectorAll(`.${this.highlightClass}`).forEach(highlight => {
            const parent = highlight.parentNode;
            parent.replaceChild(document.createTextNode(highlight.textContent), highlight);
            parent.normalize();
        });
    }

    findGroupHeader(row) {
        let prev = row.previousElementSibling;
        while (prev) {
            if (prev.classList.contains('scuola-header')) {
                return prev;
            }
            prev = prev.previousElementSibling;
        }
        return null;
    }

    updateGroupHeaders(matchedGroups) {
        document.querySelectorAll('.scuola-header').forEach(header => {
            if (matchedGroups.has(header)) {
                header.classList.remove('search-hidden');
            } else {
                header.classList.add('search-hidden');
            }
        });

        // Nascondi anche le righe totale delle scuole senza match
        document.querySelectorAll('.scuola-totale').forEach(totale => {
            const scuolaName = this.findScuolaNameForTotale(totale);
            let hasMatch = false;
            matchedGroups.forEach(header => {
                if (header.textContent.includes(scuolaName)) {
                    hasMatch = true;
                }
            });
            totale.classList.toggle('search-hidden', !hasMatch);
        });
    }

    findScuolaNameForTotale(totaleRow) {
        const text = totaleRow.querySelector('td')?.textContent || '';
        const match = text.match(/Totale (.+)/);
        return match ? match[1] : '';
    }

    updateTotaleRighe(rows, matchedGroups) {
        // Nascondi righe totale scuola se non ci sono match
        document.querySelectorAll('.scuola-totale').forEach(totale => {
            const prev = totale.previousElementSibling;
            if (prev && !prev.classList.contains('search-hidden')) {
                totale.classList.remove('search-hidden');
            }
        });
    }

    updateResultsCount(count, total) {
        if (!this.resultsCount) return;

        const query = this.input?.value || '';

        if (!query) {
            this.resultsCount.textContent = '';
            this.resultsCount.classList.remove('has-results', 'no-results');
            return;
        }

        if (count === 0) {
            this.resultsCount.innerHTML = `
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" width="14" height="14">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
                Nessun risultato
            `;
            this.resultsCount.classList.add('no-results');
            this.resultsCount.classList.remove('has-results');
        } else {
            this.resultsCount.innerHTML = `
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" width="14" height="14">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                </svg>
                ${count} risultat${count === 1 ? 'o' : 'i'}
            `;
            this.resultsCount.classList.add('has-results');
            this.resultsCount.classList.remove('no-results');
        }

        // Animazione
        this.resultsCount.classList.add('animate');
        setTimeout(() => this.resultsCount.classList.remove('animate'), 300);
    }

    showSearching() {
        this.searchIndicator?.classList.add('active');
        this.container?.classList.add('searching');
    }

    hideSearching() {
        this.searchIndicator?.classList.remove('active');
        this.container?.classList.remove('searching');
    }

    clear(resetInput = true) {
        if (resetInput && this.input) {
            this.input.value = '';
        }

        this.clearBtn.style.display = 'none';

        // Rimuovi filtri
        document.querySelectorAll('.search-hidden').forEach(el => {
            el.classList.remove('search-hidden');
        });
        document.querySelectorAll('.search-match').forEach(el => {
            el.classList.remove('search-match');
        });

        // Rimuovi highlights
        document.querySelectorAll(`.${this.highlightClass}`).forEach(highlight => {
            const parent = highlight.parentNode;
            parent.replaceChild(document.createTextNode(highlight.textContent), highlight);
            parent.normalize();
        });

        this.updateResultsCount(0, 0);
        this.hideSuggestions();

        if (this.onClear) {
            this.onClear();
        }
    }

    // === Storia ricerche ===
    loadSearchHistory() {
        try {
            return JSON.parse(localStorage.getItem('searchHistory') || '[]').slice(0, 5);
        } catch {
            return [];
        }
    }

    addToHistory(query) {
        this.searchHistory = this.searchHistory.filter(q => q !== query);
        this.searchHistory.unshift(query);
        this.searchHistory = this.searchHistory.slice(0, 5);
        localStorage.setItem('searchHistory', JSON.stringify(this.searchHistory));
    }

    showHistory() {
        if (this.searchHistory.length === 0) return;

        let html = `
            <div class="search-suggestions-header">
                <span>Ricerche recenti</span>
                <button class="search-clear-history" type="button">Cancella</button>
            </div>
        `;

        this.searchHistory.forEach((query, index) => {
            html += `
                <div class="search-suggestion-item" data-index="${index}" data-query="${query}">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" width="14" height="14">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <span>${query}</span>
                </div>
            `;
        });

        this.suggestionsPanel.innerHTML = html;
        this.suggestionsPanel.classList.add('visible');

        // Event listeners
        this.suggestionsPanel.querySelectorAll('.search-suggestion-item').forEach(item => {
            item.addEventListener('click', () => {
                this.input.value = item.dataset.query;
                this.performSearch(item.dataset.query);
                this.hideSuggestions();
            });
        });

        this.suggestionsPanel.querySelector('.search-clear-history')?.addEventListener('click', () => {
            this.clearHistory();
        });
    }

    clearHistory() {
        this.searchHistory = [];
        localStorage.removeItem('searchHistory');
        this.hideSuggestions();
    }

    hideSuggestions() {
        this.suggestionsPanel?.classList.remove('visible');
        this.selectedIndex = -1;
    }

    navigateSuggestions(direction) {
        const items = this.suggestionsPanel?.querySelectorAll('.search-suggestion-item') || [];
        if (items.length === 0) return;

        // Rimuovi selezione corrente
        items[this.selectedIndex]?.classList.remove('selected');

        // Calcola nuovo indice
        this.selectedIndex += direction;
        if (this.selectedIndex < 0) this.selectedIndex = items.length - 1;
        if (this.selectedIndex >= items.length) this.selectedIndex = 0;

        // Applica selezione
        items[this.selectedIndex].classList.add('selected');
    }

    selectSuggestion() {
        const items = this.suggestionsPanel?.querySelectorAll('.search-suggestion-item') || [];
        const selected = items[this.selectedIndex];

        if (selected) {
            this.input.value = selected.dataset.query;
            this.performSearch(selected.dataset.query);
            this.hideSuggestions();
        }
    }
}

// === Funzione di inizializzazione globale ===
function initAdvancedSearch(selector, options = {}) {
    const input = document.querySelector(selector);
    if (input) {
        return new AdvancedSearch({ input, ...options });
    }
    return null;
}

// === Esporta per uso globale ===
window.AdvancedSearch = AdvancedSearch;
window.initAdvancedSearch = initAdvancedSearch;

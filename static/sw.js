/**
 * Service Worker - Gestionale OEPAC v2.0
 * Gestione cache avanzata e modalità offline
 */

// Incrementare ad ogni modifica di CSS/JS/HTML: forza l'aggiornamento della
// cache (l'handler activate elimina le versioni precedenti) evitando asset stale.
const CACHE_VERSION = 'v4';
const STATIC_CACHE = `static-${CACHE_VERSION}`;
const DYNAMIC_CACHE = `dynamic-${CACHE_VERSION}`;
const API_CACHE = `api-${CACHE_VERSION}`;

// Risorse statiche da cachare immediatamente
const STATIC_ASSETS = [
    '/',
    '/static/css/style.css',
    '/static/css/premium-effects.css',
    '/static/css/ux-enhancements.css',
    '/static/css/search-advanced.css',
    '/static/css/advanced-features.css',
    '/static/js/app.js',
    '/static/js/advanced-features.js',
    '/static/js/search-advanced.js',
    '/static/manifest.json',
    '/static/icons/icon.svg'
];

// API da cachare per uso offline
const CACHEABLE_API = [
    '/api/commesse',
    '/api/anni-scolastici',
    '/api/stats/advanced'
];

// Install - Cache static assets
self.addEventListener('install', (event) => {
    console.log('[SW] Installing...');
    event.waitUntil(
        caches.open(STATIC_CACHE)
            .then((cache) => {
                console.log('[SW] Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => self.skipWaiting())
            .catch((error) => {
                console.error('[SW] Cache install failed:', error);
            })
    );
});

// Activate - Clean old caches
self.addEventListener('activate', (event) => {
    console.log('[SW] Activating...');
    event.waitUntil(
        caches.keys()
            .then((keys) => {
                return Promise.all(
                    keys.filter(key =>
                        key !== STATIC_CACHE &&
                        key !== DYNAMIC_CACHE &&
                        key !== API_CACHE
                    ).map(key => {
                        console.log('[SW] Deleting old cache:', key);
                        return caches.delete(key);
                    })
                );
            })
            .then(() => self.clients.claim())
    );
});

// Fetch - Strategie di caching differenziate
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);

    // Skip non-GET requests
    if (request.method !== 'GET') return;

    // Skip external resources
    if (url.origin !== location.origin) return;

    // API endpoints - Network first, fallback to cache
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(networkFirstWithCache(request, API_CACHE));
        return;
    }

    // Static assets - Cache first
    if (url.pathname.startsWith('/static/')) {
        event.respondWith(cacheFirstWithNetwork(request, STATIC_CACHE));
        return;
    }

    // HTML pages - Network first
    event.respondWith(networkFirstWithCache(request, DYNAMIC_CACHE));
});

/**
 * Cache First Strategy
 * Per risorse statiche che cambiano raramente
 */
async function cacheFirstWithNetwork(request, cacheName) {
    const cached = await caches.match(request);
    if (cached) {
        // Aggiorna in background
        fetch(request).then(response => {
            if (response.ok) {
                caches.open(cacheName).then(cache => {
                    cache.put(request, response);
                });
            }
        }).catch(() => {});
        return cached;
    }

    try {
        const response = await fetch(request);
        if (response.ok) {
            const cache = await caches.open(cacheName);
            cache.put(request, response.clone());
        }
        return response;
    } catch (error) {
        console.error('[SW] Fetch failed:', error);
        return new Response('Offline', { status: 503 });
    }
}

/**
 * Network First Strategy
 * Per contenuti dinamici e API
 */
async function networkFirstWithCache(request, cacheName) {
    try {
        const response = await fetch(request);

        if (response.ok) {
            const cache = await caches.open(cacheName);
            cache.put(request, response.clone());
        }

        return response;
    } catch (error) {
        console.log('[SW] Network failed, trying cache:', request.url);

        const cached = await caches.match(request);
        if (cached) {
            return cached;
        }

        // Per pagine HTML, ritorna una risposta offline
        if (request.headers.get('accept')?.includes('text/html')) {
            return new Response(`
                <!DOCTYPE html>
                <html lang="it">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Offline - Assisto</title>
                    <style>
                        * { margin: 0; padding: 0; box-sizing: border-box; }
                        body {
                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                            background: linear-gradient(135deg, #1a1a2e 0%, #0f0f23 100%);
                            color: #fff;
                            min-height: 100vh;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            text-align: center;
                            padding: 20px;
                        }
                        .offline-container { max-width: 400px; }
                        .offline-icon {
                            width: 80px; height: 80px;
                            margin: 0 auto 24px;
                            background: rgba(255,255,255,0.1);
                            border-radius: 50%;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                        }
                        .offline-icon svg { width: 40px; height: 40px; color: #FF9F0A; }
                        h1 { font-size: 1.5rem; margin-bottom: 12px; }
                        p { color: rgba(255,255,255,0.7); margin-bottom: 24px; line-height: 1.6; }
                        button {
                            background: #0A84FF;
                            color: white;
                            border: none;
                            padding: 12px 24px;
                            border-radius: 8px;
                            font-size: 1rem;
                            font-weight: 600;
                            cursor: pointer;
                            transition: transform 0.2s, box-shadow 0.2s;
                        }
                        button:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(10,132,255,0.4); }
                    </style>
                </head>
                <body>
                    <div class="offline-container">
                        <div class="offline-icon">
                            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 5.636a9 9 0 010 12.728m0 0l-2.829-2.829m2.829 2.829L21 21M15.536 8.464a5 5 0 010 7.072m0 0l-2.829-2.829m-4.243 2.829a4.978 4.978 0 01-1.414-2.83m-1.414 5.658a9 9 0 01-2.167-9.238m7.824 2.167a1 1 0 111.414 1.414m-1.414-1.414L3 3m8.293 8.293l1.414 1.414" />
                            </svg>
                        </div>
                        <h1>Sei offline</h1>
                        <p>Non riesco a connettermi al server. Controlla la tua connessione internet e riprova.</p>
                        <button onclick="location.reload()">Riprova</button>
                    </div>
                </body>
                </html>
            `, {
                status: 503,
                headers: { 'Content-Type': 'text/html' }
            });
        }

        // Per API, ritorna errore JSON
        return new Response(JSON.stringify({
            error: 'Offline',
            message: 'Connessione non disponibile',
            cached: false
        }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' }
        });
    }
}

// Background Sync per operazioni offline
self.addEventListener('sync', (event) => {
    console.log('[SW] Background sync:', event.tag);

    if (event.tag === 'sync-pending-operations') {
        event.waitUntil(syncPendingOperations());
    }
});

/**
 * Sincronizza operazioni salvate offline
 */
async function syncPendingOperations() {
    try {
        const db = await openDB();
        const operations = await getAllOperations(db);

        for (const op of operations) {
            try {
                const response = await fetch(op.url, {
                    method: op.method,
                    headers: op.headers,
                    body: op.body
                });

                if (response.ok) {
                    await deleteOperation(db, op.id);
                    console.log('[SW] Synced operation:', op.id);
                }
            } catch (error) {
                console.error('[SW] Failed to sync operation:', op.id, error);
            }
        }
    } catch (error) {
        console.error('[SW] Sync failed:', error);
    }
}

// IndexedDB helpers
const DB_NAME = 'gestionale-offline';
const STORE_NAME = 'pending-operations';

function openDB() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, 1);
        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve(request.result);
        request.onupgradeneeded = (event) => {
            const db = event.target.result;
            if (!db.objectStoreNames.contains(STORE_NAME)) {
                db.createObjectStore(STORE_NAME, { keyPath: 'id', autoIncrement: true });
            }
        };
    });
}

function getAllOperations(db) {
    return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readonly');
        const store = tx.objectStore(STORE_NAME);
        const request = store.getAll();
        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve(request.result || []);
    });
}

function deleteOperation(db, id) {
    return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readwrite');
        const store = tx.objectStore(STORE_NAME);
        const request = store.delete(id);
        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve();
    });
}

// Push Notifications
self.addEventListener('push', (event) => {
    if (!event.data) return;

    const data = event.data.json();

    const options = {
        body: data.body || 'Nuova notifica',
        icon: '/static/icons/icon.svg',
        badge: '/static/icons/icon.svg',
        vibrate: [100, 50, 100],
        data: { url: data.url || '/' },
        actions: data.actions || [
            { action: 'open', title: 'Apri' },
            { action: 'dismiss', title: 'Chiudi' }
        ]
    };

    event.waitUntil(
        self.registration.showNotification(data.title || 'Assisto', options)
    );
});

// Notification click
self.addEventListener('notificationclick', (event) => {
    event.notification.close();

    if (event.action === 'dismiss') return;

    const url = event.notification.data?.url || '/';

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true })
            .then((clientList) => {
                for (const client of clientList) {
                    if (client.url.includes(url) && 'focus' in client) {
                        return client.focus();
                    }
                }
                return clients.openWindow(url);
            })
    );
});

console.log('[SW] Service Worker loaded - Version:', CACHE_VERSION);

/**
 * Service Worker - Gestionale OEPAC
 *
 * Strategia volutamente semplice per un'app locale con dati riservati:
 * - /static/*        -> cache-first, una cache per versione (gli URL portano ?v=VERSIONE)
 * - pagine e /api/*  -> SEMPRE dalla rete: nessun dato dell'operatore finisce in cache
 *                       (prima restava disponibile anche dopo il logout, su un PC condiviso);
 *                       se la rete manca, le navigazioni ricevono una pagina "offline"
 *
 * La versione arriva dall'URL di registrazione (/static/sw.js?v=1.11.0): ad ogni
 * release la cache precedente viene eliminata all'attivazione, senza numeri da
 * aggiornare a mano.
 */
const VERSIONE = new URL(self.location.href).searchParams.get('v') || 'dev';
const STATIC_CACHE = `static-${VERSIONE}`;

const STATIC_ASSETS = [
    '/static/css/style.css',
    '/static/css/components.css',
    '/static/css/refine.css',
    '/static/css/auth.css',
    '/static/js/app.js',
    '/static/js/dashboard.js',
    '/static/js/vendor/chart.umd.min.js',
    '/static/manifest.json',
    '/static/icons/icon.svg',
].map(u => `${u}?v=${VERSIONE}`);

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(STATIC_CACHE)
            .then(cache => cache.addAll(STATIC_ASSETS))
            .catch(err => console.warn('[SW] precache non riuscito:', err))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys()
            .then(keys => Promise.all(keys.filter(k => k !== STATIC_CACHE).map(k => caches.delete(k))))
            .then(() => self.clients.claim())
    );
});

// Al logout la pagina chiede di svuotare tutto (cache statica compresa)
self.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'CLEAR_CACHES') {
        event.waitUntil(caches.keys().then(keys => Promise.all(keys.map(k => caches.delete(k)))));
    }
});

self.addEventListener('fetch', (event) => {
    const { request } = event;
    if (request.method !== 'GET') return;
    const url = new URL(request.url);
    if (url.origin !== self.location.origin) return;

    if (url.pathname.startsWith('/static/')) {
        event.respondWith(cacheFirst(request));
        return;
    }
    if (request.mode === 'navigate') {
        event.respondWith(fetch(request).catch(() => paginaOffline()));
    }
    // API e tutto il resto: nessuna intercettazione, nessuna cache
});

async function cacheFirst(request) {
    const cache = await caches.open(STATIC_CACHE);
    const cached = await cache.match(request);
    if (cached) return cached;
    try {
        const response = await fetch(request);
        if (response.ok) cache.put(request, response.clone());
        return response;
    } catch (error) {
        return new Response('Offline', { status: 503 });
    }
}

function paginaOffline() {
    return new Response(`<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Offline - Assisto</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #111827; color: #fff;
               min-height: 100vh; display: flex; align-items: center; justify-content: center; text-align: center; padding: 20px; }
        .box { max-width: 420px; }
        h1 { font-size: 1.4rem; margin-bottom: 10px; }
        p { color: rgba(255,255,255,0.75); margin-bottom: 22px; line-height: 1.6; }
        button { background: #3B82F6; color: #fff; border: none; padding: 12px 24px; border-radius: 8px; font-size: 1rem; font-weight: 600; cursor: pointer; }
    </style>
</head>
<body>
    <div class="box">
        <h1>Il gestionale non risponde</h1>
        <p>Controlla che il programma (avvia.bat) sia in esecuzione su questo PC, poi riprova.</p>
        <button onclick="location.reload()">Riprova</button>
    </div>
</body>
</html>`, { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } });
}

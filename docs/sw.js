// Minimal offline support for the PWA "add to home screen" experience.
// Everything same-origin (app shell HTML/CSS/JS/icons *and* data JSON) is
// network-first: when online you always get the freshest deployed files,
// and the cache is only ever used as a fallback when the network request
// fails (i.e. genuinely offline). This intentionally trades a little bit of
// offline-shell speed for correctness -- a cache-first shell means anyone
// who ever registered this worker would keep seeing a frozen snapshot of
// the site forever, since the browser never re-fetches a cached URL once
// it's cache-first. Cross-origin requests (Chart.js CDN, Binance WebSocket,
// TWSE quotes) are left alone entirely -- this worker only ever touches
// same-origin requests.
const CACHE_VERSION = "v2";
const APP_CACHE = `app-cache-${CACHE_VERSION}`;

const SHELL_URLS = [
  "./index.html", "./prices.html", "./paper.html", "./auto-trade.html",
  "./assets/common.js", "./assets/app.js", "./assets/prices.js",
  "./assets/paper.js", "./assets/paper-page.js", "./assets/auto-trade-page.js", "./assets/style.css",
  "./manifest.json",
  "./icons/favicon-16.png", "./icons/favicon-32.png",
  "./icons/icon-192.png", "./icons/icon-512.png", "./icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(APP_CACHE)
      .then((cache) => cache.addAll(SHELL_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys
        .filter((key) => key !== APP_CACHE)
        .map((key) => caches.delete(key)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return; // don't touch cross-origin requests
  if (event.request.method !== "GET") return;

  event.respondWith(networkFirst(event.request));
});

async function networkFirst(request) {
  const cache = await caches.open(APP_CACHE);
  try {
    const resp = await fetch(request);
    cache.put(request, resp.clone());
    return resp;
  } catch (err) {
    const cached = await cache.match(request);
    if (cached) return cached;
    throw err;
  }
}

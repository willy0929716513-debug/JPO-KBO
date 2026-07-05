// Minimal offline support for the PWA "add to home screen" experience.
// Static app-shell files (HTML/CSS/JS/icons) are cache-first so the app
// still opens offline; the data JSON files are network-first so you
// always get the freshest signals when online, falling back to the last
// cached copy when you don't have a connection. Cross-origin requests
// (Chart.js CDN, Binance WebSocket, TWSE quotes) are left alone entirely --
// this worker only ever touches same-origin requests.
const CACHE_VERSION = "v1";
const SHELL_CACHE = `app-shell-${CACHE_VERSION}`;
const DATA_CACHE = `app-data-${CACHE_VERSION}`;

const SHELL_URLS = [
  "./index.html", "./prices.html", "./paper.html",
  "./assets/common.js", "./assets/app.js", "./assets/prices.js",
  "./assets/paper.js", "./assets/paper-page.js", "./assets/style.css",
  "./manifest.json",
  "./icons/favicon-16.png", "./icons/favicon-32.png",
  "./icons/icon-192.png", "./icons/icon-512.png", "./icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys
        .filter((key) => key !== SHELL_CACHE && key !== DATA_CACHE)
        .map((key) => caches.delete(key)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return; // don't touch cross-origin requests
  if (event.request.method !== "GET") return;

  if (url.pathname.includes("/data/")) {
    event.respondWith(networkFirst(event.request));
  } else {
    event.respondWith(cacheFirst(event.request));
  }
});

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const resp = await fetch(request);
    const cache = await caches.open(SHELL_CACHE);
    cache.put(request, resp.clone());
    return resp;
  } catch (err) {
    return cached || Response.error();
  }
}

async function networkFirst(request) {
  const cache = await caches.open(DATA_CACHE);
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

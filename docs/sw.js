// App shell offline; prices always fetched fresh when online, last copy shown when offline.
const CACHE = "deals-v1";
const SHELL = ["./", "index.html", "manifest.webmanifest", "icon-192.png", "icon-512.png",
  "fonts/barlow-latin-400-normal.woff2", "fonts/barlow-latin-ext-400-normal.woff2", "fonts/barlow-latin-600-normal.woff2",
  "fonts/barlow-latin-ext-600-normal.woff2", "fonts/barlow-condensed-latin-600-normal.woff2", "fonts/barlow-condensed-latin-ext-600-normal.woff2",
  "fonts/barlow-condensed-latin-700-normal.woff2", "fonts/barlow-condensed-latin-ext-700-normal.woff2"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", (e) => { e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.endsWith("/data/products.json") || e.request.mode === "navigate") {
    e.respondWith(fetch(e.request).then((r) => { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(url.pathname.endsWith(".json") ? "data/products.json" : e.request, copy)); return r; })
      .catch(() => caches.match(url.pathname.endsWith(".json") ? "data/products.json" : e.request).then((r) => r || caches.match("index.html"))));
    return;
  }
  e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
});

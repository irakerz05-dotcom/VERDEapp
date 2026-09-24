const CACHE = "verde-pwa-v2";
const ASSETS = ["./", "./index.html", "./styles.css", "./js/app.js", "./js/services/verde-api.js", "./manifest.webmanifest", "./icons/icon.svg"];
self.addEventListener("install", (event) => event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS)).then(() => self.skipWaiting())));
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request)));
});

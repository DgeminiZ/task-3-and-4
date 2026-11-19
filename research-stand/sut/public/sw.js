const CACHE = "webgl-pwa-lab-v1";

const PRECACHE = [
  "/",
  "/index.html",
  "/css/app.css",
  "/js/main.js",
  "/js/scene.js",
  "/js/metrics.js",
  "/js/rng.js",
  "/vendor/three.module.min.js",
  "/manifest.webmanifest",
  "/icons/icon.svg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;

  event.respondWith(
    (async () => {
      const cache = await caches.open(CACHE);
      const hit = await cache.match(event.request, { ignoreSearch: true });
      if (hit) return hit;

      try {
        const response = await fetch(event.request);
        if (response.ok && new URL(event.request.url).origin === self.location.origin) {
          cache.put(event.request, response.clone());
        }
        return response;
      } catch (error) {
        const fallback = await cache.match("/index.html");
        if (fallback) return fallback;
        return new Response("offline", { status: 503, statusText: "offline" });
      }
    })(),
  );
});

self.addEventListener("message", (event) => {
  if (!event.data || event.data.type !== "precache-status") return;
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.keys())
      .then((keys) => {
        event.ports[0].postMessage({ cacheEntries: keys.length, cacheName: CACHE });
      }),
  );
});

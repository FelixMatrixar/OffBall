// OffBall's service worker (PRD 4.3: installable as a PWA; 15.11: the offline state). The build prepends VERSION and
// SHELL (vite.config.ts): the app shell's hashed files, cached on install so the app opens without a network. Lazy
// chunks (charts, 3D), fonts and other same-origin files are cached the first time they're used. Live feeds and video
// are never cached: a feed is live, and video arrives in byte ranges. A new build waits until the viewer reloads.
/* global VERSION, SHELL */
const SHELL_CACHE = `offball-shell-${VERSION}`;
const RUNTIME_CACHE = 'offball-runtime';
const FONTS = ['https://fonts.googleapis.com', 'https://fonts.gstatic.com'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL)));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      for (const key of await caches.keys()) if (key.startsWith('offball-shell-') && key !== SHELL_CACHE) await caches.delete(key);
      await self.clients.claim();
    })(),
  );
});

// The page asks for this when the viewer chooses to reload into the new version.
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  const accept = req.headers.get('accept') || '';
  if (accept.includes('text/event-stream') || req.headers.has('range') || url.pathname.includes('/clips/') || url.pathname.includes('/feeds/')) return;
  if (req.mode === 'navigate') event.respondWith(page(req));
  else if (url.origin === self.location.origin && url.pathname.includes('/assets/')) event.respondWith(cacheFirst(req));
  else if (FONTS.includes(url.origin) || url.origin === self.location.origin) event.respondWith(staleWhileRevalidate(req));
});

/** The page: fresh from the network when it answers in time, else the cached shell (hash routes share one page). */
async function page(req) {
  const cache = await caches.open(SHELL_CACHE);
  try {
    const res = await Promise.race([fetch(req), new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 4000))]);
    if (res.ok) cache.put('./', res.clone());
    return res;
  } catch {
    return (await cache.match('./')) || (await cache.match('index.html')) || Response.error();
  }
}

/** Hashed build files never change, so a cached copy is always right. */
async function cacheFirst(req) {
  const hit = await caches.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) (await caches.open(RUNTIME_CACHE)).put(req, res.clone());
  return res;
}

async function staleWhileRevalidate(req) {
  const cache = await caches.open(RUNTIME_CACHE);
  const hit = await cache.match(req);
  const fresh = fetch(req)
    .then((res) => {
      if (res.ok || res.type === 'opaque') cache.put(req, res.clone());
      return res;
    })
    .catch(() => hit || Response.error());
  return hit || fresh;
}

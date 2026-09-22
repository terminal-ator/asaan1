const CACHE = 'asaan-shell-v1'

self.addEventListener('install', event => {
  self.skipWaiting()
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(['/', '/manifest.webmanifest', '/icon.svg'])))
})

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key !== CACHE) await caches.delete(key)
    }
    await self.clients.claim()
  })())
})

// Staff pages and API responses must never be served from an old cache.
const BACKEND_PREFIXES = ['/api/', '/console/', '/admin/', '/static/', '/media/']

self.addEventListener('fetch', event => {
  const request = event.request
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  if (url.origin !== location.origin) return
  if (BACKEND_PREFIXES.some(prefix => url.pathname.startsWith(prefix))) return

  // Hashed build assets never change under the same name: cache first.
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(caches.match(request).then(cached => cached || fetch(request).then(response => {
      const copy = response.clone()
      caches.open(CACHE).then(cache => cache.put(request, copy))
      return response
    })))
    return
  }

  // The app shell is fetched first and cached for offline use.
  event.respondWith(fetch(request).then(response => {
    const copy = response.clone()
    caches.open(CACHE).then(cache => cache.put(request, copy))
    return response
  }).catch(() => caches.match(request).then(cached => cached || caches.match('/'))))
})

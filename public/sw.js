const CACHE = 'asaan-shell-v4'

self.addEventListener('install', event => {
  self.skipWaiting()
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(['/', '/manifest.webmanifest', '/icon.svg', '/sales/', '/sales/manifest.webmanifest', '/sales/icon.svg'])))
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

  // The app shell is fetched first and cached for offline use. Pages skip the
  // browser's HTTP cache so a deploy shows up on the next open; the salesman
  // app falls back to its own shell, not the shop's.
  const shell = url.pathname.startsWith('/sales') ? '/sales/' : '/'
  const fresh = request.mode === 'navigate' ? fetch(url.href, { cache: 'no-cache', credentials: 'same-origin' }) : fetch(request)
  event.respondWith(fresh.then(response => {
    const copy = response.clone()
    caches.open(CACHE).then(cache => cache.put(request, copy))
    return response
  }).catch(() => caches.match(request).then(cached => cached || caches.match(shell))))
})

// Order-status notifications from the server.
self.addEventListener('push', event => {
  let data = { title: 'Asaan', body: '', url: '/' }
  try { data = { ...data, ...(event.data ? event.data.json() : {}) } } catch { data.body = event.data ? event.data.text() : '' }
  event.waitUntil(self.registration.showNotification(data.title, {
    body: data.body,
    icon: '/icon.svg',
    badge: '/icon.svg',
    data: { url: data.url || '/' },
  }))
})

self.addEventListener('notificationclick', event => {
  event.notification.close()
  const url = (event.notification.data && event.notification.data.url) || '/'
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
    for (const client of list) { if ('focus' in client) return client.focus() }
    return self.clients.openWindow(url)
  }))
})

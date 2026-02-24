/**
 * aeOS Service Worker — offline-first caching strategy.
 *
 * Strategy:
 *  - App shell (HTML, CSS, JS, icons): Cache-first with network fallback
 *  - API/data requests: Network-first with cache fallback
 *  - IndexedDB is managed by the app; SW handles only static assets here
 */

import { precacheAndRoute, cleanupOutdatedCaches } from 'workbox-precaching';
import { registerRoute, setDefaultHandler } from 'workbox-routing';
import {
  CacheFirst,
  NetworkFirst,
  StaleWhileRevalidate,
} from 'workbox-strategies';
import { ExpirationPlugin } from 'workbox-expiration';
import { CacheableResponsePlugin } from 'workbox-cacheable-response';

// ─── Precache the Vite-built manifest ─────────────────────────────────────────
// __WB_MANIFEST is replaced by workbox-inject-manifest at build time.
precacheAndRoute(self.__WB_MANIFEST ?? []);
cleanupOutdatedCaches();

// ─── Cache Names ──────────────────────────────────────────────────────────────
const SHELL_CACHE   = 'aeos-shell-v1';
const FONT_CACHE    = 'aeos-fonts-v1';
const IMAGE_CACHE   = 'aeos-images-v1';

// ─── App Shell — Cache-First ──────────────────────────────────────────────────
registerRoute(
  ({ request }) =>
    request.destination === 'document' ||
    request.destination === 'script'   ||
    request.destination === 'style',
  new CacheFirst({
    cacheName: SHELL_CACHE,
    plugins: [
      new CacheableResponsePlugin({ statuses: [0, 200] }),
      new ExpirationPlugin({ maxEntries: 60, maxAgeSeconds: 30 * 24 * 60 * 60 }),
    ],
  })
);

// ─── Fonts — Cache-First (long TTL) ──────────────────────────────────────────
registerRoute(
  ({ request }) => request.destination === 'font',
  new CacheFirst({
    cacheName: FONT_CACHE,
    plugins: [
      new CacheableResponsePlugin({ statuses: [0, 200] }),
      new ExpirationPlugin({ maxEntries: 20, maxAgeSeconds: 365 * 24 * 60 * 60 }),
    ],
  })
);

// ─── Images — Stale-while-revalidate ─────────────────────────────────────────
registerRoute(
  ({ request }) => request.destination === 'image',
  new StaleWhileRevalidate({
    cacheName: IMAGE_CACHE,
    plugins: [
      new CacheableResponsePlugin({ statuses: [0, 200] }),
      new ExpirationPlugin({ maxEntries: 100, maxAgeSeconds: 7 * 24 * 60 * 60 }),
    ],
  })
);

// ─── Default fallback ────────────────────────────────────────────────────────
setDefaultHandler(new NetworkFirst({ cacheName: 'aeos-default-v1' }));

// ─── Lifecycle ────────────────────────────────────────────────────────────────
self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// ─── Background Sync placeholder ─────────────────────────────────────────────
self.addEventListener('sync', (event) => {
  if (event.tag === 'aeos-sync') {
    event.waitUntil(
      self.clients.matchAll().then(clients =>
        clients.forEach(c => c.postMessage({ type: 'SYNC_REQUESTED' }))
      )
    );
  }
});

// ─── Push notifications placeholder ──────────────────────────────────────────
self.addEventListener('push', (event) => {
  const data = event.data?.json() ?? {};
  event.waitUntil(
    self.registration.showNotification(data.title ?? 'aeOS', {
      body: data.body ?? '',
      icon: '/icons/icon-192.png',
      badge: '/icons/icon-72.png',
      data: data.url,
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  if (event.notification.data) {
    event.waitUntil(self.clients.openWindow(event.notification.data));
  }
});

/**
 * aeOS — Application Bootstrap
 *
 * Boot sequence:
 *  1. Register Service Worker
 *  2. Open IndexedDB (Dexie) and seed default settings
 *  3. Animate boot splash
 *  4. Mount router and toast system
 *  5. Start connection monitoring
 */

import { initDatabase } from './db/index.js';
import { Router } from './ui/router.js';
import { initToasts, showToast } from './ui/toast.js';

const BOOT_STEPS = [
  { label: 'Registering service worker…', pct: 10 },
  { label: 'Opening intelligence database…', pct: 35 },
  { label: 'Loading schemas…', pct: 55 },
  { label: 'Mounting interface…', pct: 80 },
  { label: 'Ready.', pct: 100 },
];

async function boot() {
  const bootSplash = document.getElementById('boot-splash');
  const bootBar    = document.getElementById('boot-bar');
  const bootStatus = document.getElementById('boot-status');
  const shell      = document.getElementById('shell');

  function setProgress(pct, label) {
    bootBar.style.width = `${pct}%`;
    bootStatus.textContent = label;
  }

  // Step 1 — Service Worker
  setProgress(BOOT_STEPS[0].pct, BOOT_STEPS[0].label);
  await registerServiceWorker();

  // Step 2 — Database
  setProgress(BOOT_STEPS[1].pct, BOOT_STEPS[1].label);
  try {
    await initDatabase();
  } catch (err) {
    console.error('[aeOS] Database init failed:', err);
    bootStatus.textContent = 'Database error — running in memory-only mode.';
    bootStatus.style.color = 'var(--color-error)';
    await sleep(1500);
  }

  // Step 3 — Schemas loaded (Dexie handles this synchronously)
  setProgress(BOOT_STEPS[2].pct, BOOT_STEPS[2].label);
  await sleep(120);

  // Step 4 — Mount UI
  setProgress(BOOT_STEPS[3].pct, BOOT_STEPS[3].label);
  initToasts();

  const router = new Router(
    document.getElementById('main-content'),
    document.getElementById('sidebar')
  );

  window.__aeos = { router }; // dev convenience

  // Step 5 — Done
  setProgress(BOOT_STEPS[4].pct, BOOT_STEPS[4].label);
  await sleep(250);

  // Reveal shell, hide splash
  shell.classList.remove('shell--hidden');
  bootSplash.classList.add('is-hidden');

  // Start online/offline monitor
  monitorConnectivity();

  // Back/forward navigation
  window.addEventListener('popstate', (e) => {
    const view = e.state?.view ?? new URLSearchParams(location.search).get('view') ?? 'dashboard';
    router.navigate(view, { pushState: false });
  });
}

// ─── Service Worker ────────────────────────────────────────────────────────

async function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  try {
    const reg = await navigator.serviceWorker.register('/service-worker.js', { type: 'module' });
    reg.addEventListener('updatefound', () => {
      const newWorker = reg.installing;
      newWorker.addEventListener('statechange', () => {
        if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
          showToast({ message: 'Update available — reload to apply', type: 'info', duration: 8000 });
        }
      });
    });
  } catch (err) {
    console.warn('[aeOS] Service Worker registration failed:', err.message);
  }
}

// ─── Connectivity Monitor ─────────────────────────────────────────────────

function monitorConnectivity() {
  const indicator = document.getElementById('connection-status');
  const dot       = indicator?.querySelector('.connection-status__dot');
  const label     = indicator?.querySelector('.connection-status__label');

  function update(online) {
    indicator?.classList.toggle('connection-status--online',  online);
    indicator?.classList.toggle('connection-status--offline', !online);
    if (label) label.textContent = online ? 'Online' : 'Offline';
  }

  window.addEventListener('online',  () => {
    update(true);
    showToast({ message: 'Back online', type: 'success' });
  });
  window.addEventListener('offline', () => {
    update(false);
    showToast({ message: 'Working offline — data saved locally', type: 'warning' });
  });

  update(navigator.onLine);
}

// ─── Util ─────────────────────────────────────────────────────────────────

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ─── Launch ───────────────────────────────────────────────────────────────

boot().catch(err => {
  console.error('[aeOS] Fatal boot error:', err);
  document.getElementById('boot-status').textContent = 'Fatal error — see console.';
});

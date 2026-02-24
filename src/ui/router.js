import { renderDashboard } from './views/dashboard.js';
import { renderGenericView } from './views/generic.js';
import { renderSettings } from './views/settings.js';

/**
 * aeOS client-side router.
 * Views are keyed by their `data-view` attribute on sidebar nav items.
 */

const VIEW_RENDERERS = {
  dashboard:   (el) => renderDashboard(el),
  agents:      (el) => renderGenericView(el, 'agents'),
  memories:    (el) => renderGenericView(el, 'memories'),
  tasks:       (el) => renderGenericView(el, 'tasks'),
  notes:       (el) => renderGenericView(el, 'notes'),
  thoughts:    (el) => renderGenericView(el, 'thoughts'),
  connections: (el) => renderGenericView(el, 'connections'),
  tags:        (el) => renderGenericView(el, 'tags'),
  projects:    (el) => renderGenericView(el, 'projects'),
  events:      (el) => renderGenericView(el, 'events'),
  goals:       (el) => renderGenericView(el, 'goals'),
  insights:    (el) => renderGenericView(el, 'insights'),
  settings:    (el) => renderSettings(el),
};

export class Router {
  constructor(contentEl, sidebarEl) {
    this._content  = contentEl;
    this._sidebar  = sidebarEl;
    this._current  = null;

    // Sidebar clicks
    sidebarEl.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-view]');
      if (btn) this.navigate(btn.dataset.view);
    });

    // Global navigation events (from within views)
    window.addEventListener('aeos:navigate', (e) => {
      this.navigate(e.detail.view);
    });

    // Handle URL query param on initial load
    const params = new URLSearchParams(location.search);
    const initial = params.get('view') ?? 'dashboard';
    this.navigate(initial, { pushState: false });
  }

  async navigate(view, { pushState = true } = {}) {
    if (!VIEW_RENDERERS[view]) {
      console.warn(`[router] unknown view: ${view}`);
      view = 'dashboard';
    }

    this._current = view;

    // Update active nav item
    this._sidebar.querySelectorAll('[data-view]').forEach(btn => {
      btn.classList.toggle('nav-item--active', btn.dataset.view === view);
      btn.setAttribute('aria-current', btn.dataset.view === view ? 'page' : 'false');
    });

    // Push URL state
    if (pushState) {
      const url = new URL(location.href);
      url.searchParams.set('view', view);
      history.pushState({ view }, '', url);
    }

    // Render with loading state
    this._content.innerHTML = '<div class="loading-state" style="display:flex;align-items:center;justify-content:center;height:200px;color:var(--color-text-muted);font-family:var(--font-mono);font-size:var(--text-sm)">Loading...</div>';

    try {
      await VIEW_RENDERERS[view](this._content);
    } catch (err) {
      console.error(`[router] render error for "${view}":`, err);
      this._content.innerHTML = `
        <div class="card" style="margin:var(--space-6)">
          <h2 style="color:var(--color-error);margin-bottom:var(--space-3)">Render Error</h2>
          <pre style="font-size:var(--text-xs);color:var(--color-text-muted);white-space:pre-wrap">${err.message}</pre>
        </div>
      `;
    }
  }

  get currentView() {
    return this._current;
  }
}

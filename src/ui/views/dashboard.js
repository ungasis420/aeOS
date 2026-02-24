import db from '../../db/index.js';
import { SCHEMA_META } from '../../db/schemas.js';

/**
 * Dashboard view — system overview with live stats from all 13 collections.
 */
export async function renderDashboard(container) {
  // Fetch counts from all 13 tables in parallel
  const [
    agentsCount,
    sessionsCount,
    memoriesCount,
    tasksCount,
    notesCount,
    thoughtsCount,
    connectionsCount,
    tagsCount,
    projectsCount,
    eventsCount,
    goalsCount,
    insightsCount,
    settingsCount,
  ] = await Promise.all([
    db.agents.count(),
    db.sessions.count(),
    db.memories.count(),
    db.tasks.count(),
    db.notes.count(),
    db.thoughts.count(),
    db.connections.count(),
    db.tags.count(),
    db.projects.count(),
    db.events.count(),
    db.goals.count(),
    db.insights.count(),
    db.settings.count(),
  ]);

  // Recent tasks
  const recentTasks = await db.tasks.orderBy('createdAt').reverse().limit(5).toArray();

  // Recent memories
  const recentMemories = await db.memories.orderBy('createdAt').reverse().limit(5).toArray();

  const stats = [
    { key: 'agents',      count: agentsCount,      accent: 'blue'   },
    { key: 'sessions',    count: sessionsCount,     accent: 'purple' },
    { key: 'memories',    count: memoriesCount,     accent: 'cyan'   },
    { key: 'tasks',       count: tasksCount,        accent: 'green'  },
    { key: 'notes',       count: notesCount,        accent: 'yellow' },
    { key: 'thoughts',    count: thoughtsCount,     accent: 'orange' },
    { key: 'connections', count: connectionsCount,  accent: 'blue'   },
    { key: 'tags',        count: tagsCount,         accent: 'cyan'   },
    { key: 'projects',    count: projectsCount,     accent: 'purple' },
    { key: 'events',      count: eventsCount,       accent: 'blue'   },
    { key: 'goals',       count: goalsCount,        accent: 'green'  },
    { key: 'insights',    count: insightsCount,     accent: 'yellow' },
    { key: 'settings',    count: settingsCount,     accent: 'blue'   },
  ];

  container.innerHTML = `
    <div class="view-header">
      <div>
        <h1 class="view-header__title">Intelligence Dashboard</h1>
        <p class="view-header__sub">aeOS — offline-first intelligence layer</p>
      </div>
      <div style="display:flex;gap:var(--space-2)">
        <button class="btn btn--ghost btn--sm" id="refresh-dashboard">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/>
            <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/>
          </svg>
          Refresh
        </button>
      </div>
    </div>

    <!-- Schema stat grid (all 13) -->
    <section aria-label="Schema statistics">
      <h2 class="section-label">Data Schemas</h2>
      <div class="stat-grid" id="schema-grid">
        ${stats.map(({ key, count, accent }) => `
          <div class="card card--accent-${accent}" role="article">
            <div class="card__header">
              <span class="card__title">${SCHEMA_META[key].label}</span>
            </div>
            <div class="card__value">${count.toLocaleString()}</div>
            <div class="card__delta">${SCHEMA_META[key].description}</div>
          </div>
        `).join('')}
      </div>
    </section>

    <!-- Activity panels -->
    <div class="panels-row" style="display:grid;grid-template-columns:1fr 1fr;gap:var(--space-4)">
      <!-- Recent Tasks -->
      <section class="card" aria-label="Recent tasks">
        <div class="card__header">
          <h2 class="card__title">Recent Tasks</h2>
          <button class="btn btn--ghost btn--sm" data-view="tasks">View all</button>
        </div>
        ${recentTasks.length ? `
          <table class="data-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Status</th>
                <th>Priority</th>
              </tr>
            </thead>
            <tbody>
              ${recentTasks.map(t => `
                <tr>
                  <td>${escHtml(t.title ?? '—')}</td>
                  <td><span class="badge badge--${statusColor(t.status)}">${escHtml(t.status ?? 'pending')}</span></td>
                  <td><span class="badge badge--${priorityColor(t.priority)}">${escHtml(t.priority ?? 'normal')}</span></td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        ` : `
          <div class="empty-state">
            <p class="empty-state__title">No tasks yet</p>
            <p>Create your first task to get started.</p>
          </div>
        `}
      </section>

      <!-- Recent Memories -->
      <section class="card" aria-label="Recent memories">
        <div class="card__header">
          <h2 class="card__title">Recent Memories</h2>
          <button class="btn btn--ghost btn--sm" data-view="memories">View all</button>
        </div>
        ${recentMemories.length ? `
          <table class="data-table">
            <thead>
              <tr>
                <th>Type</th>
                <th>Importance</th>
                <th>Stored</th>
              </tr>
            </thead>
            <tbody>
              ${recentMemories.map(m => `
                <tr>
                  <td><span class="badge badge--cyan">${escHtml(m.type ?? 'general')}</span></td>
                  <td>${m.importance ?? '—'}</td>
                  <td style="color:var(--color-text-muted);font-size:var(--text-xs)">${formatDate(m.createdAt)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        ` : `
          <div class="empty-state">
            <p class="empty-state__title">No memories yet</p>
            <p>Intelligence builds as data flows in.</p>
          </div>
        `}
      </section>
    </div>

    <!-- System health -->
    <section class="card" aria-label="System information">
      <div class="card__header">
        <h2 class="card__title">System</h2>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:var(--space-4)">
        <div>
          <div style="font-size:var(--text-xs);color:var(--color-text-muted);margin-bottom:var(--space-1)">Storage Engine</div>
          <div style="font-family:var(--font-mono);font-size:var(--text-sm)">IndexedDB / Dexie v3</div>
        </div>
        <div>
          <div style="font-size:var(--text-xs);color:var(--color-text-muted);margin-bottom:var(--space-1)">Schema Version</div>
          <div style="font-family:var(--font-mono);font-size:var(--text-sm)">v1 (13 tables)</div>
        </div>
        <div>
          <div style="font-size:var(--text-xs);color:var(--color-text-muted);margin-bottom:var(--space-1)">Mode</div>
          <div style="font-family:var(--font-mono);font-size:var(--text-sm)">Offline-first PWA</div>
        </div>
        <div>
          <div style="font-size:var(--text-xs);color:var(--color-text-muted);margin-bottom:var(--space-1)">Built</div>
          <div style="font-family:var(--font-mono);font-size:var(--text-sm)">${new Date().toLocaleDateString()}</div>
        </div>
      </div>
    </section>
  `;

  // Attach refresh handler
  container.querySelector('#refresh-dashboard')?.addEventListener('click', () => {
    renderDashboard(container);
  });

  // Delegate nav buttons inside panels
  container.querySelectorAll('[data-view]').forEach(btn => {
    btn.addEventListener('click', () => {
      window.dispatchEvent(new CustomEvent('aeos:navigate', { detail: { view: btn.dataset.view } }));
    });
  });
}

// -- Helpers --

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function statusColor(status) {
  const map = { done: 'green', completed: 'green', active: 'blue', pending: 'yellow', blocked: 'red' };
  return map[status] ?? 'purple';
}

function priorityColor(priority) {
  const map = { high: 'red', urgent: 'red', medium: 'yellow', low: 'cyan', normal: 'blue' };
  return map[priority] ?? 'blue';
}

import db from '../../db/index.js';

/**
 * Settings view — read/write system configuration keys.
 */
export async function renderSettings(container) {
  const allSettings = await db.settings.toArray();
  const grouped = allSettings.reduce((acc, s) => {
    const g = s.group ?? 'other';
    (acc[g] ??= []).push(s);
    return acc;
  }, {});

  container.innerHTML = `
    <div class="view-header">
      <div>
        <h1 class="view-header__title">Settings</h1>
        <p class="view-header__sub">System configuration — stored in IndexedDB</p>
      </div>
    </div>

    ${Object.entries(grouped).map(([group, items]) => `
      <section class="card" style="margin-bottom:var(--space-4)">
        <h2 class="card__title" style="margin-bottom:var(--space-4);text-transform:capitalize">${group}</h2>
        <div style="display:flex;flex-direction:column;gap:var(--space-3)">
          ${items.map(item => renderSettingRow(item)).join('')}
        </div>
      </section>
    `).join('')}

    <section class="card">
      <h2 class="card__title" style="margin-bottom:var(--space-4)">Database</h2>
      <div style="display:flex;gap:var(--space-3);flex-wrap:wrap">
        <button class="btn btn--ghost btn--sm" id="export-db">Export JSON snapshot</button>
        <button class="btn btn--ghost btn--sm" id="clear-db" style="color:var(--color-error)">Clear all data</button>
      </div>
    </section>
  `;

  // Save on change
  container.querySelectorAll('[data-setting-key]').forEach(input => {
    input.addEventListener('change', async (e) => {
      const key = e.target.dataset.settingKey;
      let value = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
      // Coerce numeric
      if (e.target.type === 'number') value = Number(value);
      await db.settings.put({ key, value, group: e.target.dataset.group, updatedAt: new Date().toISOString() });
      window.dispatchEvent(new CustomEvent('aeos:toast', {
        detail: { message: `Saved: ${key}`, type: 'success' }
      }));
    });
  });

  container.querySelector('#export-db')?.addEventListener('click', exportDatabase);
  container.querySelector('#clear-db')?.addEventListener('click', clearDatabase);
}

function renderSettingRow(item) {
  const inputId = `setting-${item.key.replace(/\./g, '-')}`;
  let input;

  if (typeof item.value === 'boolean') {
    input = `<input type="checkbox" id="${inputId}" data-setting-key="${item.key}" data-group="${item.group ?? ''}" ${item.value ? 'checked' : ''} style="width:16px;height:16px;cursor:pointer">`;
  } else if (typeof item.value === 'number') {
    input = `<input type="number" id="${inputId}" data-setting-key="${item.key}" data-group="${item.group ?? ''}" value="${item.value}" style="width:100px;padding:var(--space-1) var(--space-2);background:var(--color-surface-3);border:1px solid var(--color-border);border-radius:var(--radius-sm);color:var(--color-text-primary);font-family:var(--font-mono);font-size:var(--text-sm)">`;
  } else {
    input = `<input type="text" id="${inputId}" data-setting-key="${item.key}" data-group="${item.group ?? ''}" value="${String(item.value ?? '')}" style="flex:1;max-width:300px;padding:var(--space-1) var(--space-2);background:var(--color-surface-3);border:1px solid var(--color-border);border-radius:var(--radius-sm);color:var(--color-text-primary);font-family:var(--font-mono);font-size:var(--text-sm)">`;
  }

  return `
    <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--space-4)">
      <label for="${inputId}" style="font-size:var(--text-sm);font-family:var(--font-mono);color:var(--color-text-secondary)">${item.key}</label>
      ${input}
    </div>
  `;
}

async function exportDatabase() {
  const snapshot = {};
  const tables = ['agents','sessions','memories','tasks','notes','thoughts','connections','tags','projects','events','goals','insights','settings'];
  for (const t of tables) {
    snapshot[t] = await db[t].toArray();
  }
  const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `aeos-snapshot-${Date.now()}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

async function clearDatabase() {
  if (!confirm('Delete ALL aeOS data? This cannot be undone.')) return;
  const tables = ['agents','sessions','memories','tasks','notes','thoughts','connections','tags','projects','events','goals','insights'];
  await Promise.all(tables.map(t => db[t].clear()));
  window.dispatchEvent(new CustomEvent('aeos:toast', {
    detail: { message: 'All data cleared', type: 'warning' }
  }));
}

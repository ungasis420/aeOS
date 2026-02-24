import db from '../../db/index.js';
import { SCHEMA_META } from '../../db/schemas.js';

/**
 * Generic list view — renders any of the 13 collections as a simple table.
 * Each dedicated view can override this for custom UX.
 */
export async function renderGenericView(container, tableName) {
  const meta = SCHEMA_META[tableName];
  if (!meta) {
    container.innerHTML = `<p style="color:var(--color-error)">Unknown view: ${tableName}</p>`;
    return;
  }

  const table = db[tableName];
  const records = await table.orderBy('id').reverse().limit(50).toArray();

  container.innerHTML = `
    <div class="view-header">
      <div>
        <h1 class="view-header__title">${meta.label}</h1>
        <p class="view-header__sub">${meta.description}</p>
      </div>
      <button class="btn btn--primary btn--sm" id="new-record">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
        New ${meta.label.slice(0, -1)}
      </button>
    </div>

    <div class="card">
      ${records.length ? renderTable(records) : `
        <div class="empty-state">
          <p class="empty-state__title">No ${meta.label.toLowerCase()} yet</p>
          <p>${meta.description}</p>
          <button class="btn btn--primary" id="new-record-empty">
            Add first ${meta.label.slice(0, -1).toLowerCase()}
          </button>
        </div>
      `}
    </div>
  `;

  // Placeholder create handler
  container.querySelectorAll('#new-record, #new-record-empty').forEach(btn => {
    btn.addEventListener('click', () => {
      window.dispatchEvent(new CustomEvent('aeos:toast', {
        detail: { message: `New ${meta.label.slice(0,-1)} form coming soon`, type: 'info' }
      }));
    });
  });
}

function renderTable(records) {
  if (!records.length) return '';
  const keys = Object.keys(records[0]).filter(k => !['id'].includes(k)).slice(0, 6);
  return `
    <table class="data-table">
      <thead>
        <tr>
          <th>#</th>
          ${keys.map(k => `<th>${formatKey(k)}</th>`).join('')}
        </tr>
      </thead>
      <tbody>
        ${records.map(r => `
          <tr>
            <td style="color:var(--color-text-muted);font-family:var(--font-mono)">${r.id}</td>
            ${keys.map(k => `<td>${formatValue(r[k])}</td>`).join('')}
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

function formatKey(key) {
  return key.replace(/([A-Z])/g, ' $1').replace(/^./, s => s.toUpperCase());
}

function formatValue(val) {
  if (val === null || val === undefined) return '<span style="color:var(--color-text-muted)">—</span>';
  if (typeof val === 'boolean') return val ? '✓' : '✗';
  if (Array.isArray(val)) return val.length ? `[${val.slice(0,3).join(', ')}]` : '[]';
  const str = String(val);
  if (str.match(/^\d{4}-\d{2}-\d{2}T/)) {
    return `<span style="color:var(--color-text-muted);font-size:var(--text-xs)">${new Date(val).toLocaleDateString()}</span>`;
  }
  if (str.length > 60) return `<span title="${str.replace(/"/g,'&quot;')}">${str.slice(0,60)}…</span>`;
  return str;
}

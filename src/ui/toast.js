/**
 * Toast notification system.
 * Listens for 'aeos:toast' CustomEvents dispatched on window.
 */

const container = () => document.getElementById('toast-container');

export function initToasts() {
  window.addEventListener('aeos:toast', (e) => {
    showToast(e.detail);
  });
}

/**
 * @param {{ message: string, type?: 'success'|'error'|'info'|'warning', duration?: number }} options
 */
export function showToast({ message, type = 'info', duration = 3500 }) {
  const el = document.createElement('div');
  el.className = `toast toast--${type}`;
  el.setAttribute('role', 'status');
  el.innerHTML = `
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;color:${iconColor(type)}">
      ${iconPath(type)}
    </svg>
    <span style="flex:1">${escHtml(message)}</span>
    <button onclick="this.parentElement.remove()" style="background:none;border:none;color:var(--color-text-muted);cursor:pointer;padding:0;line-height:1" aria-label="Dismiss">✕</button>
  `;

  container().appendChild(el);

  setTimeout(() => {
    el.style.transition = 'opacity 300ms, transform 300ms';
    el.style.opacity = '0';
    el.style.transform = 'translateY(8px)';
    setTimeout(() => el.remove(), 300);
  }, duration);
}

function iconPath(type) {
  switch (type) {
    case 'success': return '<polyline points="20 6 9 17 4 12"/>';
    case 'error':   return '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>';
    case 'warning': return '<path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>';
    default:        return '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>';
  }
}

function iconColor(type) {
  const map = { success: 'var(--color-success)', error: 'var(--color-error)', warning: 'var(--color-warning)', info: 'var(--color-info)' };
  return map[type] ?? 'var(--color-info)';
}

function escHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

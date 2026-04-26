// ── Thème dark/light ─────────────────────────────────────
const THEME_KEY = 'yt-dl-theme';

function initTheme() {
  const saved = localStorage.getItem(THEME_KEY) || 'dark';
  applyTheme(saved);

  document.getElementById('btnTheme').addEventListener('click', () => {
    const current = document.documentElement.dataset.theme || 'dark';
    applyTheme(current === 'dark' ? 'light' : 'dark');
  });
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem(THEME_KEY, theme);
  const btn = document.getElementById('btnTheme');
  if (btn) btn.textContent = theme === 'dark' ? '☀️' : '🌙';
}

// ── Navigation onglets ────────────────────────────────────
function initTabs() {
  const topBtns    = document.querySelectorAll('#topTabs .tab-btn');
  const bottomBtns = document.querySelectorAll('#bottomNav .bottom-nav-item');
  const panels     = document.querySelectorAll('.tab-panel');

  function switchTab(tabId) {
    panels.forEach(p => p.classList.toggle('active', p.id === 'tab-' + tabId));
    topBtns.forEach(b => b.classList.toggle('active', b.dataset.tab === tabId));
    bottomBtns.forEach(b => b.classList.toggle('active', b.dataset.tab === tabId));
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }

  topBtns.forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));
  bottomBtns.forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));
  window.switchTab = switchTab;
}

// ── Utilitaires ───────────────────────────────────────────
function formatDuration(seconds) {
  if (!seconds) return '--:--';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}:${pad(m)}:${pad(s)}`;
  return `${m}:${pad(s)}`;
}

function pad(n) { return String(n).padStart(2, '0'); }

function tcToSeconds(tc) {
  if (!tc) return 0;
  const parts = tc.split(':').map(Number);
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  return 0;
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1024 / 1024).toFixed(1) + ' MB';
}

async function postJSON(url, data) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return res.json();
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

window.appUtils = { formatDuration, pad, tcToSeconds, formatSize, postJSON, escHtml };

document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  initTabs();
  if (typeof lucide !== 'undefined') lucide.createIcons();
});

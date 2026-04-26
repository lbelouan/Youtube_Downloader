document.addEventListener('DOMContentLoaded', () => {
  const { escHtml } = window.appUtils;

  const queueList     = document.getElementById('queueList');
  const queueBadge    = document.getElementById('queueBadge');
  const queueBadgeMob = document.getElementById('queueBadgeMobile');
  const btnClearQueue = document.getElementById('btnClearQueue');

  function connectSSE() {
    const sse = new EventSource('/stream/queue');
    sse.onmessage = (event) => {
      const queue = JSON.parse(event.data);
      renderQueue(queue);
      updateBadge(queue);
    };
    sse.onerror = () => { sse.close(); setTimeout(connectSSE, 3000); };
  }

  connectSSE();

  function renderQueue(queue) {
    if (queue.length === 0) {
      queueList.innerHTML = `
        <div class="empty-state">
          <i data-lucide="inbox"></i>
          <p>La file est vide.</p>
          <p class="empty-hint">Ajoutez des vidéos depuis l'onglet Télécharger.</p>
        </div>`;
      if (typeof lucide !== 'undefined') lucide.createIcons();
      return;
    }

    const sorted = [
      ...queue.filter(t => t.status === 'running'),
      ...queue.filter(t => t.status === 'pending'),
      ...queue.filter(t => ['done','error','cancelled'].includes(t.status)).reverse(),
    ];

    // Mise à jour diff — remplacer seulement les cartes modifiées
    const existingIds = new Set(
      [...queueList.querySelectorAll('.task-card')].map(c => c.dataset.id)
    );
    const newIds = new Set(sorted.map(t => t.id));

    existingIds.forEach(id => {
      if (!newIds.has(id)) queueList.querySelector(`[data-id="${id}"]`)?.remove();
    });

    sorted.forEach((task, idx) => {
      const card    = buildTaskCard(task);
      const existing = queueList.querySelector(`[data-id="${task.id}"]`);
      if (existing) {
        existing.replaceWith(card);
      } else {
        const cards = queueList.querySelectorAll('.task-card');
        cards[idx] ? queueList.insertBefore(card, cards[idx]) : queueList.appendChild(card);
      }
    });

    queueList.querySelector('.empty-state')?.remove();
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }

  function buildTaskCard(task) {
    const card = document.createElement('div');
    card.className  = `task-card status-${task.status}`;
    card.dataset.id = task.id;

    const isPending = task.status === 'pending';
    const isRunning = task.status === 'running';
    const isDone    = task.status === 'done';
    const isActive  = isPending || isRunning;

    const tcInfo = task.start || task.end
      ? `${task.start || '00:00:00'} → ${task.end || 'fin'}`
      : 'Vidéo complète';

    card.innerHTML = `
      <div class="task-header">
        <span class="badge badge-${task.status}">${statusLabel(task.status)}</span>
        <span class="task-filename">${escHtml(task.filename || 'extrait')}.mp4</span>
        <div class="task-actions">
          ${isPending ? `<button class="btn-up"    title="Monter">↑</button>` : ''}
          ${isPending ? `<button class="btn-down"  title="Descendre">↓</button>` : ''}
          ${isActive  ? `<button class="btn-cancel" title="Annuler">✕</button>` : ''}
          ${isDone    ? `<button class="btn-dl"     title="Télécharger">⬇</button>` : ''}
        </div>
      </div>
      <div class="task-title">${escHtml(task.title || task.url || '')}</div>
      <div class="task-meta">${tcInfo}</div>
      <div class="progress-track" style="margin:8px 0 4px">
        <div class="progress-fill ${isRunning ? 'running' : ''}"
             style="width:${task.progress || 0}%"></div>
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span style="font-size:0.75rem;color:var(--color-text-muted)">${task.progress || 0}%</span>
        ${task.error ? `<span class="task-error">⚠ ${escHtml(task.error)}</span>` : ''}
      </div>
    `;

    card.querySelector('.btn-up')?.addEventListener('click', () => reorderTask(task.id, 'up'));
    card.querySelector('.btn-down')?.addEventListener('click', () => reorderTask(task.id, 'down'));
    card.querySelector('.btn-cancel')?.addEventListener('click', () => cancelTask(task.id));
    card.querySelector('.btn-dl')?.addEventListener('click', () => {
      window.location.href = `/download/file/${encodeURIComponent(task.id)}`;
    });

    return card;
  }

  function statusLabel(s) {
    return { pending:'En attente', running:'En cours', done:'Terminé',
             error:'Erreur', cancelled:'Annulé' }[s] || s;
  }

  function updateBadge(queue) {
    const active = queue.filter(t => ['pending','running'].includes(t.status)).length;
    [queueBadge, queueBadgeMob].forEach(b => {
      if (!b) return;
      b.textContent   = active || '';
      b.style.display = active ? 'inline-flex' : 'none';
    });
  }

  async function cancelTask(id) {
    await fetch(`/queue/cancel/${encodeURIComponent(id)}`, { method: 'POST' });
  }

  async function reorderTask(id, direction) {
    await fetch('/queue/reorder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, direction }),
    });
  }

  btnClearQueue?.addEventListener('click', () => fetch('/queue/clear', { method: 'POST' }));
});

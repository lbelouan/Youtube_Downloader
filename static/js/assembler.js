document.addEventListener('DOMContentLoaded', () => {
  const { escHtml, formatSize } = window.appUtils;

  const assembleList     = document.getElementById('assembleList');
  const emptyState       = document.getElementById('assembleEmptyState');
  const assembleFileName = document.getElementById('assembleFileName');
  const crfSlider        = document.getElementById('crfSlider');
  const crfValue         = document.getElementById('crfValue');
  const crfGroup         = document.getElementById('crfGroup');
  const compatWarning    = document.getElementById('compatWarning');
  const btnAssemble      = document.getElementById('btnAssemble');
  const btnCancelAsm     = document.getElementById('btnCancelAssemble');
  const progressSec      = document.getElementById('assembleProgressSection');
  const progressFill     = document.getElementById('assembleProgressFill');
  const progressPct      = document.getElementById('assembleProgressPct');

  let uploadedFiles = []; // [{ filename, path, size? }]

  // ── CRF slider + auto ───────────────────────────────────
  const crfAuto = document.getElementById('crfAuto');
  const crfDesc = document.getElementById('crfDesc');

  const CRF_LEVELS = [
    { max: 0,  label: 'Lossless — taille énorme, inutile en pratique',                        cls: 'quality-high'   },
    { max: 17, label: 'Très haute qualité — fichier volumineux',                               cls: 'quality-high'   },
    { max: 18, label: 'Quasi-lossless — recommandé, difficile à distinguer de l\'original',   cls: 'quality-high'   },
    { max: 22, label: 'Haute qualité — léger gain de taille',                                  cls: 'quality-good'   },
    { max: 23, label: 'Défaut x264 — bon équilibre qualité / taille',                          cls: 'quality-good'   },
    { max: 27, label: 'Qualité correcte — compression notable',                                cls: 'quality-medium' },
    { max: 28, label: 'Compression visible — acceptable pour le web',                          cls: 'quality-medium' },
    { max: 40, label: 'Qualité réduite — artefacts visibles',                                  cls: 'quality-low'    },
    { max: 51, label: 'Qualité minimale — très dégradé',                                       cls: 'quality-low'    },
  ];

  function getCrfInfo(val) {
    return CRF_LEVELS.find(l => val <= l.max) || CRF_LEVELS.at(-1);
  }

  function updateCrfDesc() {
    const val  = parseInt(crfSlider.value);
    const info = getCrfInfo(val);
    crfValue.textContent = val;
    crfDesc.className    = `crf-desc ${info.cls}`;
    crfDesc.innerHTML    = `<span class="crf-desc-val">${val}</span>${info.label}`;
  }

  function setCrfAuto(auto) {
    if (auto) {
      crfSlider.value         = 18;
      crfSlider.disabled      = true;
      crfSlider.style.opacity = '0.4';
    } else {
      crfSlider.disabled      = false;
      crfSlider.style.opacity = '1';
    }
    updateCrfDesc();
  }

  crfAuto.addEventListener('change', () => setCrfAuto(crfAuto.checked));
  crfSlider.addEventListener('input', updateCrfDesc);
  setCrfAuto(true);
  updateCrfDesc();

  document.querySelectorAll('input[name="assembleMode"]').forEach(r => {
    r.addEventListener('change', () => {
      crfGroup.style.display = r.value !== 'concat' ? 'block' : 'none';
    });
  });

  // ── Mode local : dossier sur disque ─────────────────────
  const btnRefresh = document.getElementById('btnRefreshFiles');
  if (btnRefresh) {
    btnRefresh.addEventListener('click', () => loadLocalFiles(true));
  }
  loadLocalFiles(false);

  async function loadLocalFiles(showFeedback = false) {
    const btnRefresh = document.getElementById('btnRefreshFiles');
    if (btnRefresh) btnRefresh.disabled = true;
    try {
      const res  = await fetch('/api/assembler-local-files');
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      uploadedFiles = data.files || [];
      renderAssembleList();
      if (showFeedback && uploadedFiles.length === 0) {
        showFolderHint('Aucun fichier MP4 trouvé dans le dossier.');
      } else if (showFeedback) {
        showFolderHint(`${uploadedFiles.length} fichier(s) détecté(s).`);
      }
    } catch (e) {
      console.error('Erreur chargement fichiers locaux :', e);
    } finally {
      if (btnRefresh) btnRefresh.disabled = false;
    }
  }

  function showFolderHint(msg) {
    let hint = document.getElementById('folderHintMsg');
    if (!hint) {
      hint = document.createElement('p');
      hint.id = 'folderHintMsg';
      hint.className = 'folder-hint-msg';
      const box = document.querySelector('.local-folder-box');
      if (box) box.appendChild(hint);
    }
    hint.textContent = msg;
    setTimeout(() => { if (hint) hint.textContent = ''; }, 4000);
  }

  // ── Liste d'assemblage ───────────────────────────────────
  function renderAssembleList() {
    [...assembleList.querySelectorAll('.assemble-item')].forEach(i => i.remove());

    if (uploadedFiles.length === 0) {
      if (emptyState) emptyState.style.display = 'flex';
      btnAssemble.disabled = true;
      return;
    }
    if (emptyState) emptyState.style.display = 'none';
    btnAssemble.disabled = false;

    uploadedFiles.forEach((f, idx) => {
      const item = document.createElement('div');
      item.className = 'assemble-item';
      const sizeStr = f.size ? ` · ${formatSize(f.size)}` : '';
      item.innerHTML = `
        <span class="assemble-item-idx">${idx + 1}</span>
        <div class="assemble-item-info">
          <div class="assemble-item-name">${escHtml(f.filename)}</div>
          <div class="assemble-item-meta">Prêt${sizeStr}</div>
        </div>
        <div class="assemble-item-actions">
          <button class="btn-up" title="Monter">↑</button>
          <button class="btn-down" title="Descendre">↓</button>
          <button class="btn-remove" title="Retirer de la liste">✕</button>
        </div>
      `;
      item.querySelector('.btn-up').addEventListener('click', () => {
        if (idx > 0) {
          [uploadedFiles[idx - 1], uploadedFiles[idx]] = [uploadedFiles[idx], uploadedFiles[idx - 1]];
          renderAssembleList();
        }
      });
      item.querySelector('.btn-down').addEventListener('click', () => {
        if (idx < uploadedFiles.length - 1) {
          [uploadedFiles[idx], uploadedFiles[idx + 1]] = [uploadedFiles[idx + 1], uploadedFiles[idx]];
          renderAssembleList();
        }
      });
      item.querySelector('.btn-remove').addEventListener('click', () => {
        uploadedFiles.splice(idx, 1);
        renderAssembleList();
      });
      assembleList.appendChild(item);
    });
  }

  // ── Assemblage ───────────────────────────────────────────
  let _asmJobId      = null;
  let _asmPollTimer  = null;
  let _asmCancelled  = false;

  function resetAssembleUI() {
    clearInterval(_asmPollTimer);
    progressFill.classList.remove('running');
    progressSec.style.display = 'none';
    progressFill.style.width  = '0%';
    btnAssemble.disabled      = false;
    _asmJobId     = null;
    _asmPollTimer = null;
    _asmCancelled = false;
  }

  // Bouton Annuler assemblage
  btnCancelAsm.addEventListener('click', async () => {
    if (!_asmJobId) return;
    _asmCancelled = true;
    clearInterval(_asmPollTimer);
    try { await fetch(`/api/assemble-cancel/${_asmJobId}`, { method: 'POST' }); } catch (_) {}
    progressPct.textContent = '⛔ Annulé';
    progressFill.classList.remove('running');
    setTimeout(resetAssembleUI, 1000);
  });

  btnAssemble.addEventListener('click', async () => {
    if (uploadedFiles.length === 0) return;

    const filename = assembleFileName.value.trim() || 'video_finale';
    const mode     = document.querySelector('input[name="assembleMode"]:checked')?.value || 'auto';
    const crf      = parseInt(crfSlider.value);

    _asmCancelled             = false;
    btnAssemble.disabled      = true;
    progressSec.style.display = 'block';
    progressFill.style.width  = '2%';
    progressFill.classList.add('running');
    progressPct.textContent   = '0%';

    try {
      // 1. Lancer l'assemblage en tâche de fond
      const startRes = await fetch('/assemble', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          files: uploadedFiles.map(f => f.path),
          filename, mode, crf,
        }),
      });
      const startData = await startRes.json();
      if (startData.error) throw new Error(startData.error);
      _asmJobId = startData.job_id;

      // 2. Poller la progression toutes les secondes
      await new Promise((resolve, reject) => {
        _asmPollTimer = setInterval(async () => {
          if (_asmCancelled) { clearInterval(_asmPollTimer); return; }
          try {
            const res  = await fetch(`/api/assemble-progress/${_asmJobId}`);
            const data = await res.json();

            const pct = data.progress || 0;
            progressFill.style.width = Math.max(pct, 2) + '%';
            progressPct.textContent  = pct + '%';

            if (data.status === 'done') {
              clearInterval(_asmPollTimer);
              resolve();
            } else if (data.status === 'error') {
              clearInterval(_asmPollTimer);
              reject(new Error(data.error || 'Erreur inconnue'));
            } else if (data.status === 'cancelled') {
              clearInterval(_asmPollTimer);
              reject(new Error('cancelled'));
            }
          } catch (_) { /* erreur réseau transitoire */ }
        }, 1000);
      });

      // 3. Télécharger le fichier assemblé
      progressFill.style.width = '100%';
      progressPct.textContent  = 'Téléchargement...';

      const a    = document.createElement('a');
      a.href     = `/api/assemble-download/${_asmJobId}`;
      a.download = `${filename}.mp4`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);

      progressFill.classList.remove('running');
      progressPct.textContent = '✅ Terminé';
      uploadedFiles = [];
      renderAssembleList();
      setTimeout(resetAssembleUI, 3000);

    } catch (e) {
      if (e.message !== 'cancelled') {
        progressSec.style.display = 'none';
        alert('Erreur assemblage : ' + e.message);
      }
      resetAssembleUI();
    }
  });
});

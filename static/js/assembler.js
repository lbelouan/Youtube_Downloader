document.addEventListener('DOMContentLoaded', () => {
  const { escHtml } = window.appUtils;

  const uploadZone    = document.getElementById('uploadZone');
  const fileInput     = document.getElementById('fileInputHidden');
  const assembleList  = document.getElementById('assembleList');
  const emptyState    = document.getElementById('assembleEmptyState');
  const assembleFileName = document.getElementById('assembleFileName');
  const crfSlider     = document.getElementById('crfSlider');
  const crfValue      = document.getElementById('crfValue');
  const crfGroup      = document.getElementById('crfGroup');
  const compatWarning = document.getElementById('compatWarning');
  const btnAssemble   = document.getElementById('btnAssemble');
  const progressSec   = document.getElementById('assembleProgressSection');
  const progressFill  = document.getElementById('assembleProgressFill');
  const progressPct   = document.getElementById('assembleProgressPct');

  let uploadedFiles = []; // [{ filename, path }]

  // ── CRF slider + auto ───────────────────────────────────
  const crfAuto = document.getElementById('crfAuto');
  const crfDesc = document.getElementById('crfDesc');

  const CRF_LEVELS = [
    { max: 0,  label: 'Lossless — taille énorme, inutile en pratique',          cls: 'quality-high'   },
    { max: 17, label: 'Très haute qualité — fichier volumineux',                 cls: 'quality-high'   },
    { max: 18, label: 'Quasi-lossless — recommandé, difficile à distinguer de l\'original', cls: 'quality-high' },
    { max: 22, label: 'Haute qualité — léger gain de taille',                   cls: 'quality-good'   },
    { max: 23, label: 'Défaut x264 — bon équilibre qualité / taille',           cls: 'quality-good'   },
    { max: 27, label: 'Qualité correcte — compression notable',                 cls: 'quality-medium' },
    { max: 28, label: 'Compression visible — acceptable pour le web',           cls: 'quality-medium' },
    { max: 40, label: 'Qualité réduite — artefacts visibles',                   cls: 'quality-low'    },
    { max: 51, label: 'Qualité minimale — très dégradé',                        cls: 'quality-low'    },
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
      crfSlider.value    = 18;
      crfSlider.disabled = true;
      crfSlider.style.opacity = '0.4';
    } else {
      crfSlider.disabled = false;
      crfSlider.style.opacity = '1';
    }
    updateCrfDesc();
  }

  crfAuto.addEventListener('change', () => setCrfAuto(crfAuto.checked));
  crfSlider.addEventListener('input', updateCrfDesc);

  // Init
  setCrfAuto(true);
  updateCrfDesc();

  document.querySelectorAll('input[name="assembleMode"]').forEach(r => {
    r.addEventListener('change', () => {
      crfGroup.style.display = r.value !== 'concat' ? 'block' : 'none';
    });
  });

  // ── Upload zone ──────────────────────────────────────────
  uploadZone.addEventListener('click', () => fileInput.click());

  uploadZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadZone.classList.add('dragover');
  });
  uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('dragover'));
  uploadZone.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadZone.classList.remove('dragover');
    handleFiles([...e.dataTransfer.files]);
  });

  fileInput.addEventListener('change', () => {
    handleFiles([...fileInput.files]);
    fileInput.value = '';
  });

  async function handleFiles(files) {
    const mp4s = files.filter(f => f.name.endsWith('.mp4') || f.type === 'video/mp4');
    if (!mp4s.length) return;

    // Afficher état "upload en cours"
    btnAssemble.disabled = true;
    uploadZone.querySelector('p').textContent = `Upload de ${mp4s.length} fichier(s)...`;

    const formData = new FormData();
    mp4s.forEach(f => formData.append('files', f));

    try {
      const res  = await fetch('/api/upload', { method: 'POST', body: formData });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      uploadedFiles.push(...data.files);
      renderAssembleList();
    } catch (e) {
      alert('Erreur upload : ' + e.message);
    } finally {
      uploadZone.querySelector('p').textContent = 'Glissez des fichiers MP4 ici';
    }
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
      item.innerHTML = `
        <span class="assemble-item-idx">${idx + 1}</span>
        <div class="assemble-item-info">
          <div class="assemble-item-name">${escHtml(f.filename)}</div>
          <div class="assemble-item-meta">${f.path ? 'Prêt' : ''}</div>
        </div>
        <div class="assemble-item-actions">
          <button class="btn-up" title="Monter">↑</button>
          <button class="btn-down" title="Descendre">↓</button>
          <button class="btn-remove" title="Supprimer">🗑</button>
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
  btnAssemble.addEventListener('click', async () => {
    if (uploadedFiles.length === 0) return;

    const filename = assembleFileName.value.trim() || 'video_finale';
    const mode     = document.querySelector('input[name="assembleMode"]:checked')?.value || 'auto';
    const crf      = parseInt(crfSlider.value);

    btnAssemble.disabled = true;
    progressSec.style.display   = 'block';
    progressFill.style.width    = '30%';
    progressFill.classList.add('running');
    progressPct.textContent     = 'Assemblage...';

    try {
      const res = await fetch('/assemble', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          files:    uploadedFiles.map(f => f.path),
          filename, mode, crf,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: 'Erreur inconnue' }));
        throw new Error(err.error);
      }

      // Déclencher le téléchargement depuis le blob
      progressFill.style.width = '80%';
      progressPct.textContent  = 'Téléchargement...';

      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href     = url;
      a.download = `${filename}.mp4`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      progressFill.classList.remove('running');
      progressFill.style.width = '100%';
      progressPct.textContent  = '✅ Terminé';
      uploadedFiles = [];
      renderAssembleList();

    } catch (e) {
      progressSec.style.display = 'none';
      alert('Erreur assemblage : ' + e.message);
    } finally {
      btnAssemble.disabled = false;
    }
  });
});

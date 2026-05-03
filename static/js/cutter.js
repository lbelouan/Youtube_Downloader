/* ══════════════════════════════════════════════════════════
   CUTTER — Découpe vidéo locale avec player intégré
   ══════════════════════════════════════════════════════════ */

document.addEventListener('DOMContentLoaded', () => {
  const { escHtml } = window.appUtils;

  // ── DOM ─────────────────────────────────────────────────
  const pathInput       = document.getElementById('cutterPathInput');
  const btnLoad         = document.getElementById('btnLoadVideo');
  const playerSection   = document.getElementById('cutterPlayerSection');
  const infoBar         = document.getElementById('cutterInfoBar');
  const videoEl         = document.getElementById('cutterVideo');
  const scrubber        = document.getElementById('cutterScrubber');
  const timeCurrent     = document.getElementById('cutterTimeCurrent');
  const timeDuration    = document.getElementById('cutterTimeDuration');
  const btnPlayPause    = document.getElementById('btnCutterPlayPause');
  const playIcon        = document.getElementById('cutterPlayIcon');
  const btnBack5        = document.getElementById('btnCutterBack5');
  const btnFwd5         = document.getElementById('btnCutterFwd5');
  const btnSpeed        = document.getElementById('btnCutterSpeed');
  const loopCheckbox    = document.getElementById('cutterLoopSegment');
  const canvas          = document.getElementById('cutterTimeline');
  const ctx             = canvas.getContext('2d');
  const btnSetIn        = document.getElementById('btnSetIn');
  const btnSetOut       = document.getElementById('btnSetOut');
  const inTimeEl        = document.getElementById('cutInTime');
  const outTimeEl       = document.getElementById('cutOutTime');
  const btnAdd          = document.getElementById('btnAddSegment');
  const segList         = document.getElementById('cutterSegmentsList');
  const segCount        = document.getElementById('cutSegmentCount');
  const emptyState      = document.getElementById('cutEmptyState');
  const btnClearAll     = document.getElementById('btnClearSegments');
  const exportSection   = document.getElementById('cutterExportSection');
  const btnExport       = document.getElementById('btnExportSegments');
  const exportLabel     = document.getElementById('btnExportLabel');
  const progressSec     = document.getElementById('cutterProgressSection');
  const progressFill    = document.getElementById('cutterProgressFill');
  const progressPct     = document.getElementById('cutterProgressPct');
  const progressLbl     = document.getElementById('cutterProgressLabel');
  const btnCancel       = document.getElementById('btnCancelCut');
  const pathError       = document.getElementById('cutterPathError');
  const btnResetCutter  = document.getElementById('btnResetCutter');

  // ── État ─────────────────────────────────────────────────
  let videoPath    = null;
  let duration     = 0;
  let inTime       = null;
  let outTime      = null;
  let segments     = [];
  let speeds       = [0.25, 0.5, 1, 1.5, 2];
  let speedIdx     = 2;   // 1×
  let _jobId       = null;
  let _pollTimer   = null;
  let _cancelled   = false;

  // ── Helpers timecode ─────────────────────────────────────
  function fmtTc(sec) {
    if (sec === null || sec === undefined || isNaN(sec)) return '--:--:--.---';
    const h  = Math.floor(sec / 3600);
    const m  = Math.floor((sec % 3600) / 60);
    const s  = Math.floor(sec % 60);
    const ms = Math.round((sec % 1) * 1000);
    return `${pad(h)}:${pad(m)}:${pad(s)}.${String(ms).padStart(3, '0')}`;
  }
  function pad(n) { return String(n).padStart(2, '0'); }

  function fmtDur(sec) {
    if (!sec) return '0s';
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = (sec % 60).toFixed(1);
    if (h > 0) return `${h}h ${pad(m)}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  }

  function fmtRes(w, h) {
    if (!w || !h) return '';
    if (h >= 2160) return '4K';
    if (h >= 1080) return '1080p';
    if (h >= 720)  return '720p';
    if (h >= 480)  return '480p';
    return `${h}p`;
  }

  // ── Charger la vidéo ─────────────────────────────────────
  btnLoad.addEventListener('click', loadVideo);
  pathInput.addEventListener('keydown', e => { if (e.key === 'Enter') loadVideo(); });

  async function loadVideo() {
    const path  = pathInput.value.trim();
    const isUrl = path.startsWith('http://') || path.startsWith('https://');

    pathError.textContent = '';
    pathError.classList.remove('visible');
    if (!path) {
      pathError.textContent = 'Entrez un chemin de fichier ou une URL YouTube.';
      pathError.classList.add('visible');
      return;
    }

    btnLoad.disabled = true;
    btnLoad.innerHTML = '<i data-lucide="loader-2" class="spin"></i><span>Chargement…</span>';
    if (typeof lucide !== 'undefined') lucide.createIcons();

    try {
      if (isUrl) {
        // ── URL YouTube ─────────────────────────────────────
        const [infoRes, streamRes] = await Promise.all([
          fetch('/api/info?url=' + encodeURIComponent(path)),
          fetch('/api/youtube/stream-url?url=' + encodeURIComponent(path)),
        ]);
        const info   = await infoRes.json();
        const stream = await streamRes.json();

        if (info.error)   throw new Error(info.error);
        if (stream.error) throw new Error('Stream : ' + stream.error);

        videoPath = path;          // URL YouTube originale — utilisée pour le téléchargement
        duration  = info.duration || 0;

        infoBar.innerHTML = `
          <span class="cutter-info-item">
            <i data-lucide="youtube"></i>
            <strong>YouTube</strong>
          </span>
          <span class="cutter-info-item" style="flex:1;min-width:0;overflow:hidden">
            <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:300px"
            >${escHtml(info.title || '')}</span>
          </span>
          <span class="cutter-info-item">
            <i data-lucide="clock-3"></i>
            <strong>${fmtDur(duration)}</strong>
          </span>
          <span class="cutter-info-item">
            <i data-lucide="monitor"></i>
            <strong>${info.max_res || '?'}</strong>
            <span class="cutter-yt-preview-note">(preview 720p)</span>
          </span>
        `;

        scrubber.max  = duration;
        scrubber.step = Math.max(0.001, duration / 10000);
        timeDuration.textContent = fmtTc(duration);

        // La source est l'URL de stream directe (pas l'URL YouTube)
        videoEl.src = stream.url;
        videoEl.load();

      } else {
        // ── Fichier local ────────────────────────────────────
        const res  = await fetch('/api/video/info?path=' + encodeURIComponent(path));
        const info = await res.json();
        if (info.error) throw new Error(info.error);

        videoPath = path;
        duration  = info.duration || 0;

        infoBar.innerHTML = `
          <span class="cutter-info-item">
            <i data-lucide="clock-3"></i>
            <strong>${fmtDur(duration)}</strong>
          </span>
          <span class="cutter-info-item">
            <i data-lucide="monitor"></i>
            <strong>${fmtRes(info.width, info.height)}</strong>
            <span>${info.width}×${info.height}</span>
          </span>
          <span class="cutter-info-item">
            <i data-lucide="film"></i>
            <strong>${info.codec?.toUpperCase() || '?'}</strong>
          </span>
          <span class="cutter-info-item">
            <i data-lucide="gauge"></i>
            <span>${info.fps || '?'} fps</span>
          </span>
        `;

        scrubber.max  = duration;
        scrubber.step = Math.max(0.001, duration / 10000);
        timeDuration.textContent = fmtTc(duration);

        videoEl.src = '/api/video/stream?path=' + encodeURIComponent(path);
        videoEl.load();
      }

      if (typeof lucide !== 'undefined') lucide.createIcons();

      // Réinitialiser l'état de découpe
      inTime = outTime = null;
      segments = [];
      renderInOut();
      renderSegments();
      resetExportUI(false);

      playerSection.style.display = 'block';
      if (btnResetCutter) btnResetCutter.style.display = 'inline-flex';
      setTimeout(resizeCanvas, 100);

    } catch (e) {
      pathError.textContent = 'Erreur : ' + e.message;
      pathError.classList.add('visible');
    } finally {
      btnLoad.disabled = false;
      btnLoad.innerHTML = '<i data-lucide="folder-open"></i><span>Charger</span>';
      if (typeof lucide !== 'undefined') lucide.createIcons();
    }
  }

  // ── Events vidéo ─────────────────────────────────────────
  videoEl.addEventListener('timeupdate', () => {
    const t = videoEl.currentTime;
    timeCurrent.textContent = fmtTc(t);
    scrubber.value = t;
    updateScrubberBg();
    drawTimeline();

    // Loop IN→OUT
    if (loopCheckbox.checked && inTime !== null && outTime !== null && outTime > inTime) {
      if (t >= outTime) {
        videoEl.currentTime = inTime;
      }
    }
  });

  videoEl.addEventListener('play', () => {
    playIcon.setAttribute('data-lucide', 'pause');
    if (typeof lucide !== 'undefined') lucide.createIcons();
  });
  videoEl.addEventListener('pause', () => {
    playIcon.setAttribute('data-lucide', 'play');
    if (typeof lucide !== 'undefined') lucide.createIcons();
  });
  videoEl.addEventListener('loadedmetadata', () => {
    if (!duration && videoEl.duration && isFinite(videoEl.duration)) {
      duration = videoEl.duration;
      scrubber.max = duration;
      timeDuration.textContent = fmtTc(duration);
    }
    resizeCanvas();
    drawTimeline();
  });

  // ── Transport ─────────────────────────────────────────────
  btnPlayPause.addEventListener('click', () => {
    if (videoEl.paused) videoEl.play();
    else videoEl.pause();
  });

  btnBack5.addEventListener('click', () => {
    videoEl.currentTime = Math.max(0, videoEl.currentTime - 5);
  });
  btnFwd5.addEventListener('click', () => {
    videoEl.currentTime = Math.min(duration, videoEl.currentTime + 5);
  });

  btnSpeed.addEventListener('click', () => {
    speedIdx = (speedIdx + 1) % speeds.length;
    const sp = speeds[speedIdx];
    videoEl.playbackRate = sp;
    btnSpeed.textContent = sp === 1 ? '1×' : sp + '×';
  });

  // ── Scrubber ──────────────────────────────────────────────
  scrubber.addEventListener('input', () => {
    videoEl.currentTime = parseFloat(scrubber.value);
    updateScrubberBg();
    drawTimeline();
  });

  function updateScrubberBg() {
    const pct = duration > 0 ? (videoEl.currentTime / duration) * 100 : 0;
    scrubber.style.background =
      `linear-gradient(to right, var(--color-accent) ${pct}%, var(--color-bg-hover) ${pct}%)`;
  }

  // ── Clavier ───────────────────────────────────────────────
  document.addEventListener('keydown', e => {
    // Ignorer si focus sur un input texte
    if (['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
    if (!videoPath) return;
    if (document.getElementById('tab-cutter')?.classList.contains('active') === false) return;

    if (e.code === 'Space') {
      e.preventDefault();
      if (videoEl.paused) videoEl.play(); else videoEl.pause();
    } else if (e.code === 'ArrowLeft') {
      e.preventDefault();
      videoEl.currentTime = Math.max(0, videoEl.currentTime - (e.shiftKey ? 1 : 5));
    } else if (e.code === 'ArrowRight') {
      e.preventDefault();
      videoEl.currentTime = Math.min(duration, videoEl.currentTime + (e.shiftKey ? 1 : 5));
    } else if (e.code === 'KeyI') {
      e.preventDefault();
      setIn();
    } else if (e.code === 'KeyO') {
      e.preventDefault();
      setOut();
    } else if (e.code === 'Enter' && !btnAdd.disabled) {
      e.preventDefault();
      addSegment();
    }
  });

  // ── IN / OUT ──────────────────────────────────────────────
  btnSetIn.addEventListener('click', setIn);
  btnSetOut.addEventListener('click', setOut);

  function setIn() {
    inTime = videoEl.currentTime;
    renderInOut();
    drawTimeline();
  }

  function setOut() {
    outTime = videoEl.currentTime;
    renderInOut();
    drawTimeline();
  }

  function renderInOut() {
    inTimeEl.textContent  = fmtTc(inTime);
    outTimeEl.textContent = fmtTc(outTime);

    inTimeEl.classList.toggle('unset',  inTime  === null);
    outTimeEl.classList.toggle('unset', outTime === null);

    const canAdd = inTime !== null && outTime !== null && outTime > inTime;
    btnAdd.disabled = !canAdd;
  }

  // ── Ajouter un segment ───────────────────────────────────
  btnAdd.addEventListener('click', addSegment);

  function addSegment() {
    if (inTime === null || outTime === null || outTime <= inTime) return;
    segments.push({ start: inTime, end: outTime });
    inTime = outTime = null;
    renderInOut();
    renderSegments();
    drawTimeline();
  }

  function renderSegments() {
    // Vider (garder emptyState)
    [...segList.querySelectorAll('.cut-segment-item')].forEach(el => el.remove());

    const n = segments.length;
    segCount.textContent = n;

    if (n === 0) {
      emptyState.style.display = 'flex';
      exportSection.style.display = 'none';
      btnClearAll.style.display = 'none';
      return;
    }

    emptyState.style.display = 'none';
    exportSection.style.display = 'block';
    btnClearAll.style.display = '';
    exportLabel.textContent = `Exporter ${n} segment${n > 1 ? 's' : ''}${n > 1 ? ' → ZIP' : ''}`;

    segments.forEach((seg, i) => {
      const dur = seg.end - seg.start;
      const el  = document.createElement('div');
      el.className = 'cut-segment-item';
      el.innerHTML = `
        <span class="seg-idx">${i + 1}</span>
        <div class="seg-info">
          <span class="seg-times">${fmtTc(seg.start)} → ${fmtTc(seg.end)}</span>
          <span class="seg-dur">${fmtDur(dur)}</span>
        </div>
        <div class="seg-actions">
          <button class="btn-seg-goto" title="Aller au début du segment">
            <i data-lucide="corner-down-right"></i>
          </button>
          <button class="btn-seg-remove" title="Supprimer">✕</button>
        </div>
      `;
      el.querySelector('.btn-seg-goto').addEventListener('click', () => {
        videoEl.currentTime = seg.start;
        videoEl.play();
      });
      el.querySelector('.btn-seg-remove').addEventListener('click', () => {
        segments.splice(i, 1);
        renderSegments();
        drawTimeline();
      });
      segList.appendChild(el);
    });

    if (typeof lucide !== 'undefined') lucide.createIcons();
  }

  btnClearAll.addEventListener('click', () => {
    if (!confirm('Effacer tous les segments ?')) return;
    segments = [];
    inTime = outTime = null;
    renderInOut();
    renderSegments();
    drawTimeline();
  });

  // ── Timeline canvas ───────────────────────────────────────
  function resizeCanvas() {
    const rect = canvas.getBoundingClientRect();
    canvas.width  = rect.width  * devicePixelRatio;
    canvas.height = rect.height * devicePixelRatio;
    ctx.scale(devicePixelRatio, devicePixelRatio);
    drawTimeline();
  }
  window.addEventListener('resize', resizeCanvas);

  function drawTimeline() {
    if (!duration) return;
    const W = canvas.getBoundingClientRect().width  || canvas.width  / devicePixelRatio;
    const H = canvas.getBoundingClientRect().height || canvas.height / devicePixelRatio;

    ctx.save();
    ctx.clearRect(0, 0, W, H);

    // Fond
    const isDark = document.documentElement.dataset.theme !== 'light';
    ctx.fillStyle = isDark ? '#1a1a1a' : '#e8e8e8';
    ctx.beginPath();
    ctx.roundRect(0, 0, W, H, 4);
    ctx.fill();

    const toX = t => (t / duration) * W;

    // Segments validés (vert)
    segments.forEach(seg => {
      const x1 = toX(seg.start);
      const x2 = toX(seg.end);
      ctx.fillStyle = 'rgba(43,166,64,0.45)';
      ctx.fillRect(x1, 4, x2 - x1, H - 8);
      ctx.strokeStyle = 'rgba(43,166,64,0.85)';
      ctx.lineWidth = 1.5;
      ctx.strokeRect(x1 + 0.75, 4.75, Math.max(x2 - x1 - 1.5, 1), H - 9.5);
    });

    // Sélection en cours IN→OUT (rouge translucide)
    if (inTime !== null && outTime !== null && outTime > inTime) {
      const x1 = toX(inTime);
      const x2 = toX(outTime);
      ctx.fillStyle = 'rgba(255,0,0,0.2)';
      ctx.fillRect(x1, 4, x2 - x1, H - 8);
    }

    // Marqueur IN (orange)
    if (inTime !== null) {
      const x = toX(inTime);
      ctx.strokeStyle = '#FF6600';
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
      // Triangle haut
      ctx.fillStyle = '#FF6600';
      ctx.beginPath();
      ctx.moveTo(x - 5, 0); ctx.lineTo(x + 5, 0); ctx.lineTo(x, 7);
      ctx.fill();
    }

    // Marqueur OUT (orange)
    if (outTime !== null) {
      const x = toX(outTime);
      ctx.strokeStyle = '#FF6600';
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
      ctx.fillStyle = '#FF6600';
      ctx.beginPath();
      ctx.moveTo(x - 5, 0); ctx.lineTo(x + 5, 0); ctx.lineTo(x, 7);
      ctx.fill();
    }

    // Playhead (rouge)
    const px = toX(videoEl.currentTime);
    ctx.strokeStyle = '#FF0000';
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, H); ctx.stroke();
    ctx.fillStyle = '#FF0000';
    ctx.beginPath();
    ctx.moveTo(px - 5, 0); ctx.lineTo(px + 5, 0); ctx.lineTo(px, 8);
    ctx.fill();

    ctx.restore();
  }

  // Click sur la timeline → seek
  canvas.addEventListener('click', e => {
    if (!duration) return;
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    videoEl.currentTime = Math.max(0, Math.min((x / rect.width) * duration, duration));
  });

  // Hover tooltip temps
  const tlTooltip = (() => {
    const el = document.createElement('div');
    el.style.cssText = 'position:fixed;pointer-events:none;display:none;background:rgba(0,0,0,.8);color:#fff;font-size:11px;font-family:monospace;padding:3px 7px;border-radius:4px;z-index:9999;';
    document.body.appendChild(el);
    return el;
  })();
  canvas.addEventListener('mousemove', e => {
    if (!duration) return;
    const rect = canvas.getBoundingClientRect();
    const t = Math.max(0, Math.min(((e.clientX - rect.left) / rect.width) * duration, duration));
    tlTooltip.style.display = 'block';
    tlTooltip.textContent   = fmtTc(t);
    tlTooltip.style.left    = (e.clientX + 12) + 'px';
    tlTooltip.style.top     = (e.clientY - 24) + 'px';
  });
  canvas.addEventListener('mouseleave', () => { tlTooltip.style.display = 'none'; });

  // ── Export ────────────────────────────────────────────────
  btnExport.addEventListener('click', startExport);

  async function startExport() {
    if (segments.length === 0) return;

    const mode = document.querySelector('input[name="cutMode"]:checked')?.value || 'fast';

    _cancelled = false;
    btnExport.disabled = true;
    progressSec.style.display = 'block';
    progressFill.style.width = '2%';
    progressFill.classList.add('running');
    progressPct.textContent  = '0%';
    progressLbl.textContent  = `Export en cours… (${mode === 'fast' ? 'rapide' : 'précis'})`;

    try {
      // Nommer les segments
      const segsData = segments.map((seg, i) => ({
        start:    seg.start,
        end:      seg.end,
        filename: `segment_${String(i + 1).padStart(3, '0')}.mp4`,
      }));

      const startRes  = await fetch('/api/cut/start', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ input: videoPath, segments: segsData, mode }),
      });
      const startData = await startRes.json();
      if (startData.error) throw new Error(startData.error);
      _jobId = startData.job_id;

      // Poller la progression
      await new Promise((resolve, reject) => {
        _pollTimer = setInterval(async () => {
          if (_cancelled) { clearInterval(_pollTimer); return; }
          try {
            const r = await fetch(`/api/cut/progress/${_jobId}`);
            const d = await r.json();
            const pct = d.progress || 0;
            progressFill.style.width = Math.max(pct, 2) + '%';
            progressPct.textContent  = pct + '%';
            // Message adapté à la phase
            if (d.phase === 'downloading') {
              progressLbl.textContent = 'Téléchargement YouTube…';
            } else {
              progressLbl.textContent = `Découpe en cours… (${mode === 'fast' ? 'rapide' : 'précis'})`;
            }
            if (d.status === 'done')           { clearInterval(_pollTimer); resolve(); }
            else if (d.status === 'error')     { clearInterval(_pollTimer); reject(new Error(d.error || 'Erreur inconnue')); }
            else if (d.status === 'cancelled') { clearInterval(_pollTimer); reject(new Error('cancelled')); }
          } catch (_) { /* réseau transitoire */ }
        }, 800);
      });

      // Téléchargement
      progressFill.style.width = '100%';
      progressPct.textContent  = 'Téléchargement…';

      const a    = document.createElement('a');
      const ext  = segments.length === 1 ? 'mp4' : 'zip';
      a.href     = `/api/cut/download/${_jobId}`;
      a.download = `segments.${ext}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);

      progressFill.classList.remove('running');
      progressPct.textContent = '✅ Terminé';
      setTimeout(() => resetExportUI(true), 3000);

    } catch (e) {
      if (e.message !== 'cancelled') {
        progressSec.style.display = 'none';
        alert('Erreur export : ' + e.message);
      }
      resetExportUI(true);
    }
  }

  // Annuler
  btnCancel.addEventListener('click', async () => {
    if (!_jobId) return;
    _cancelled = true;
    clearInterval(_pollTimer);
    try { await fetch(`/api/cut/cancel/${_jobId}`, { method: 'POST' }); } catch (_) {}
    progressPct.textContent = '⛔ Annulé';
    progressFill.classList.remove('running');
    setTimeout(() => resetExportUI(true), 800);
  });

  function resetExportUI(reenable = true) {
    clearInterval(_pollTimer);
    progressSec.style.display = 'none';
    progressFill.style.width  = '0%';
    progressFill.classList.remove('running');
    if (reenable) btnExport.disabled = false;
    _jobId = null; _pollTimer = null; _cancelled = false;
  }

  // ── Reset découpe ────────────────────────────────────────
  function resetCutterTab() {
    // Annuler un job en cours
    if (_jobId) {
      clearInterval(_pollTimer);
      fetch(`/api/cut/cancel/${_jobId}`, { method: 'POST' }).catch(() => {});
    }

    // Arrêter la vidéo
    videoEl.pause();
    videoEl.src = '';

    // Réinitialiser l'état
    videoPath = null;
    duration  = 0;
    inTime    = outTime = null;
    segments  = [];
    speedIdx  = 2;
    videoEl.playbackRate = speeds[speedIdx];
    _jobId = null; _pollTimer = null; _cancelled = false;

    // Réinitialiser le formulaire source
    pathInput.value = '';
    pathError.textContent = '';
    pathError.classList.remove('visible');

    // Masquer le player
    playerSection.style.display = 'none';

    // Remettre à zéro l'UI de découpe
    renderInOut();
    renderSegments();
    resetExportUI(true);

    // Vider le canvas
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Cacher le bouton reset
    if (btnResetCutter) btnResetCutter.style.display = 'none';

    pathInput.focus();
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }

  if (btnResetCutter) {
    btnResetCutter.addEventListener('click', resetCutterTab);
  }

  // ── Intégration : remplir le path depuis un autre onglet ─
  // Appelé par downloader.js quand l'utilisateur clique "Découper"
  window.cutterSetPath = (path) => {
    pathInput.value = path;
    window.switchTab('cutter');
    // Déclencher le chargement automatiquement après l'animation du tab
    setTimeout(loadVideo, 150);
  };

});

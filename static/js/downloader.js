document.addEventListener('DOMContentLoaded', () => {
  const { formatDuration, pad, tcToSeconds, postJSON } = window.appUtils;

  // Éléments DOM
  const urlInput     = document.getElementById('videoUrl');
  const urlError     = document.getElementById('urlError');
  const btnPreview   = document.getElementById('btnPreview');
  const previewBlock = document.getElementById('previewBlock');
  const previewThumb = document.getElementById('previewThumb');
  const previewTitle = document.getElementById('previewTitle');
  const previewDur   = document.getElementById('previewDuration');
  const previewRes   = document.getElementById('previewRes');
  const previewAudio = document.getElementById('previewAudio');
  const tcError      = document.getElementById('tcError');
  const fileNameInput= document.getElementById('fileName');
  const btnAddQueue  = document.getElementById('btnAddQueue');
  const btnDownload  = document.getElementById('btnDownloadNow');
  const progressSec  = document.getElementById('dlProgressSection');
  const progressFill = document.getElementById('dlProgressFill');
  const progressPct  = document.getElementById('dlProgressPct');
  const logConsole   = document.getElementById('dlLog');
  const btnGoDownload= document.getElementById('btnGoDownload');

  let videoDuration = null;
  let videoInfo     = null;
  let selectedFormat = 'mp4';

  // ── Toggle MP4 / MP3 ────────────────────────────────────
  const fmtMp4       = document.getElementById('fmtMp4');
  const fmtMp3       = document.getElementById('fmtMp3');
  const mp3QualityGrp= document.getElementById('mp3QualityGroup');
  const cutModeGrp   = document.getElementById('cutModeGroup');

  [fmtMp4, fmtMp3].forEach(btn => {
    btn.addEventListener('click', () => {
      selectedFormat = btn.dataset.format;
      fmtMp4.classList.toggle('active', selectedFormat === 'mp4');
      fmtMp3.classList.toggle('active', selectedFormat === 'mp3');
      mp3QualityGrp.style.display = selectedFormat === 'mp3' ? 'block' : 'none';
      cutModeGrp.style.display    = selectedFormat === 'mp4' ? 'block' : 'none';
      if (typeof lucide !== 'undefined') lucide.createIcons();
    });
  });

  // ── Timecode Picker ──────────────────────────────────────
  function initTcPicker(prefix) {
    const display  = document.getElementById(`tc${prefix}Display`);
    const popover  = document.getElementById(`tc${prefix}Popover`);
    const textEl   = document.getElementById(`tc${prefix}Text`);
    const hidden   = document.getElementById(`tc${prefix}`);
    const hInput   = document.getElementById(`tc${prefix}H`);
    const mInput   = document.getElementById(`tc${prefix}M`);
    const sInput   = document.getElementById(`tc${prefix}S`);
    const btnClear = document.getElementById(`tc${prefix}Clear`);
    const btnOk    = document.getElementById(`tc${prefix}Ok`);

    let isSet = false;

    function openPopover() {
      popover.classList.add('open');
      display.classList.add('open');
    }
    function closePopover() {
      popover.classList.remove('open');
      display.classList.remove('open');
    }

    display.addEventListener('click', (e) => {
      e.stopPropagation();
      const wasOpen = popover.classList.contains('open');
      // Fermer les autres pickers
      document.querySelectorAll('.tc-popover.open').forEach(p => p.classList.remove('open'));
      document.querySelectorAll('.tc-display.open').forEach(d => d.classList.remove('open'));
      if (!wasOpen) openPopover();
    });

    display.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); display.click(); }
      if (e.key === 'Escape') closePopover();
    });

    // Boutons +/- avec long press (maintien = défilement continu)
    popover.querySelectorAll('.tc-spin-btn').forEach(btn => {
      let holdTimer = null;
      let holdInterval = null;

      function step() {
        const spin  = btn.dataset.spin;
        const dir   = btn.dataset.dir;
        const field = spin.endsWith('-h') ? hInput : spin.endsWith('-m') ? mInput : sInput;
        const max   = field === hInput ? 23 : 59;
        let val = parseInt(field.value) || 0;
        val = dir === 'up' ? Math.min(val + 1, max) : Math.max(val - 1, 0);
        field.value = val;
      }

      function startHold() {
        step(); // premier clic immédiat
        holdTimer = setTimeout(() => {
          holdInterval = setInterval(step, 80); // défilement rapide après 400ms
        }, 400);
      }

      function stopHold() {
        clearTimeout(holdTimer);
        clearInterval(holdInterval);
        holdTimer = null;
        holdInterval = null;
      }

      btn.addEventListener('mousedown',  (e) => { e.stopPropagation(); startHold(); });
      btn.addEventListener('touchstart', (e) => { e.stopPropagation(); e.preventDefault(); startHold(); }, { passive: false });
      btn.addEventListener('mouseup',    stopHold);
      btn.addEventListener('mouseleave', stopHold);
      btn.addEventListener('touchend',   stopHold);
      btn.addEventListener('touchcancel',stopHold);
      // Empêcher le click de re-déclencher step() après mousedown
      btn.addEventListener('click', (e) => e.stopPropagation());
    });

    // Validation champs
    [hInput, mInput, sInput].forEach(inp => {
      inp.addEventListener('input', () => {
        const max = inp === hInput ? 23 : 59;
        let v = parseInt(inp.value);
        if (isNaN(v) || v < 0) v = 0;
        if (v > max) v = max;
        inp.value = v;
      });
      inp.addEventListener('click', e => e.stopPropagation());
    });

    // OK
    btnOk.addEventListener('click', (e) => {
      e.stopPropagation();
      const h = parseInt(hInput.value) || 0;
      const m = parseInt(mInput.value) || 0;
      const s = parseInt(sInput.value) || 0;
      const tc = `${pad(h)}:${pad(m)}:${pad(s)}`;
      hidden.value = tc;
      textEl.textContent = tc;
      display.classList.remove('empty');
      display.classList.add('has-value');
      isSet = true;
      closePopover();
      validateTimecodes();
    });

    // Effacer
    btnClear.addEventListener('click', (e) => {
      e.stopPropagation();
      hInput.value = 0; mInput.value = 0; sInput.value = 0;
      hidden.value = '';
      textEl.textContent = prefix === 'Start' ? 'Début de la vidéo' : 'Fin de la vidéo';
      display.classList.add('empty');
      display.classList.remove('has-value');
      isSet = false;
      closePopover();
      validateTimecodes();
    });

    return { getValue: () => hidden.value };
  }

  const startPicker = initTcPicker('Start');
  const endPicker   = initTcPicker('End');

  // Fermer popover au clic extérieur
  document.addEventListener('click', () => {
    document.querySelectorAll('.tc-popover.open').forEach(p => p.classList.remove('open'));
    document.querySelectorAll('.tc-display.open').forEach(d => d.classList.remove('open'));
  });

  // ── Validation timecodes ─────────────────────────────────
  function validateTimecodes() {
    const start = startPicker.getValue();
    const end   = endPicker.getValue();

    if (!start && !end) { showTcError(''); return true; }
    if (start && end) {
      const s = tcToSeconds(start);
      const e = tcToSeconds(end);
      if (e <= s) {
        showTcError('Le timecode fin doit être supérieur au début');
        return false;
      }
      if (videoDuration && e > videoDuration) {
        showTcError('Le timecode fin dépasse la durée de la vidéo', 'warning');
        return true;
      }
    }
    showTcError('');
    return true;
  }

  function showTcError(msg, type = 'error') {
    tcError.textContent = msg;
    tcError.classList.toggle('visible', !!msg);
    tcError.style.color = type === 'warning' ? 'var(--color-warning)' : 'var(--color-error)';
  }

  // ── Prévisualisation ─────────────────────────────────────
  btnPreview.addEventListener('click', async () => {
    const url = urlInput.value.trim();
    if (!url) { showUrlError('Veuillez entrer une URL YouTube'); return; }
    setPreviewLoading(true);
    try {
      const res  = await fetch('/api/info?' + new URLSearchParams({ url }));
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      videoInfo     = data;
      videoDuration = data.duration;
      showPreview(data);
      showUrlError('');
    } catch (e) {
      showUrlError('Impossible de charger la vidéo : ' + e.message);
      previewBlock.style.display = 'none';
    } finally {
      setPreviewLoading(false);
    }
  });

  urlInput.addEventListener('keydown', e => { if (e.key === 'Enter') btnPreview.click(); });

  function setPreviewLoading(loading) {
    btnPreview.disabled = loading;
    btnPreview.innerHTML = loading
      ? '<i data-lucide="loader-2" class="spin"></i><span>Chargement...</span>'
      : '<i data-lucide="search"></i><span>Prévisualiser</span>';
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }

  function showPreview(data) {
    previewThumb.src         = data.thumbnail || '';
    previewThumb.onerror     = () => { previewThumb.style.display = 'none'; };
    previewTitle.textContent  = data.title || 'Titre inconnu';
    previewDur.innerHTML     = `<i data-lucide="clock-3"></i> ${formatDuration(data.duration)}`;
    previewRes.innerHTML     = `<i data-lucide="monitor"></i> ${data.max_res}`;
    previewAudio.innerHTML   = `<i data-lucide="volume-2"></i> ${data.audio_codec || 'AAC'}`;
    previewBlock.style.display = 'block';
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }

  function showUrlError(msg) {
    urlError.textContent = msg;
    urlError.classList.toggle('visible', !!msg);
    urlInput.classList.toggle('error', !!msg);
  }

  // ── Construction de la tâche ─────────────────────────────
  function buildTask() {
    const url      = urlInput.value.trim();
    const start    = startPicker.getValue();
    const end      = endPicker.getValue();
    const filename = fileNameInput.value.trim() || 'extrait';
    const precise  = document.querySelector('input[name="cutMode"]:checked')?.value === 'precise';
    const bitrate  = document.querySelector('input[name="mp3Bitrate"]:checked')?.value || '320k';

    if (!url) { showUrlError('URL requise'); return null; }
    if ((start || end) && !validateTimecodes()) return null;

    return { url, start, end, filename, precise, format: selectedFormat,
             bitrate, title: videoInfo?.title || url };
  }

  // ── Ajouter à la file ────────────────────────────────────
  btnAddQueue.addEventListener('click', async () => {
    const task = buildTask();
    if (!task) return;
    btnAddQueue.disabled = true;
    try {
      const res = await postJSON('/queue/add', task);
      if (res.error) throw new Error(res.error);
      window.switchTab('queue');
    } catch (e) {
      alert('Erreur : ' + e.message);
    } finally {
      btnAddQueue.disabled = false;
    }
  });

  // ── Télécharger maintenant ───────────────────────────────
  btnDownload.addEventListener('click', async () => {
    const task = buildTask();
    if (!task) return;

    btnDownload.disabled = true;
    progressSec.style.display = 'block';
    progressFill.style.width  = '0%';
    progressFill.classList.add('running');
    progressPct.textContent   = '0%';
    logConsole.innerHTML      = '<span class="log-line">Ajout à la file d\'attente...</span>';

    let taskId = null;
    let sse    = null;

    try {
      const res = await postJSON('/queue/add', task);
      if (res.error) throw new Error(res.error);
      taskId = res.task_id;
      logLine('Téléchargement démarré...');

      sse = new EventSource('/stream/queue');
      sse.onmessage = (event) => {
        const queue = JSON.parse(event.data);
        const mine  = queue.find(t => t.id === taskId);
        if (!mine) return;

        const pct = mine.progress || 0;
        progressFill.style.width = pct + '%';
        progressPct.textContent  = pct + '%';
        logLine(`[download] ${pct}%`);

        if (mine.status === 'done') {
          sse.close();
          progressFill.classList.remove('running');
          progressFill.style.width = '100%';
          progressPct.textContent  = '100%';
          logLine('✅ Terminé — démarrage du téléchargement...');
          // Déclencher le téléchargement navigateur
          window.location.href = `/download/file/${encodeURIComponent(taskId)}`;
          btnDownload.disabled = false;
          setTimeout(() => { progressSec.style.display = 'none'; }, 3000);
        } else if (mine.status === 'error') {
          sse.close();
          logLine('❌ Erreur : ' + (mine.error || 'inconnue'));
          btnDownload.disabled = false;
        } else if (mine.status === 'cancelled') {
          sse.close();
          logLine('⛔ Annulé');
          btnDownload.disabled = false;
        }
      };

      sse.onerror = () => {
        sse.close();
        btnDownload.disabled = false;
      };

    } catch (e) {
      logLine('❌ ' + e.message);
      btnDownload.disabled = false;
    }
  });

  function logLine(text) {
    const last = logConsole.lastElementChild;
    if (last && last.textContent === text) return;
    const span = document.createElement('span');
    span.className   = 'log-line';
    span.textContent = text;
    logConsole.appendChild(span);
    logConsole.scrollTop = logConsole.scrollHeight;
  }

  if (btnGoDownload) {
    btnGoDownload.addEventListener('click', () => window.switchTab('download'));
  }
});

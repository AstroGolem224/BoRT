(() => {
  const $ = (id) => document.getElementById(id);
  const bridgeWaiters = new Map();
  let callNumber = 0;
  let api = null;

  // Theme (hell/dunkel) – rein clientseitig via localStorage, Default dunkel.
  const applyTheme = (theme) => {
    document.documentElement.setAttribute('data-theme', theme === 'light' ? 'light' : 'dark');
  };
  let currentTheme = 'dark';
  try { currentTheme = localStorage.getItem('bort-theme') || 'dark'; } catch (_) { currentTheme = 'dark'; }
  applyTheme(currentTheme);

  const setStatus = (message, error = false) => {
    const node = $('status');
    node.textContent = message;
    node.classList.toggle('error', error);
  };
  const appendLog = (line) => {
    const log = $('log');
    log.textContent = `${log.textContent}${line}\n`.slice(-30000);
    log.scrollTop = log.scrollHeight;
  };
  const setProgress = (percent, label) => {
    const value = Math.max(0, Math.min(100, Number(percent) || 0));
    $('progress-bar').style.width = `${value}%`;
    $('progress-value').textContent = `${Math.round(value)} %`;
    $('progress-label').textContent = label || '';
  };
  const formatTime = (value) => {
    const total = Math.max(0, Number(value) || 0);
    return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(Math.floor(total % 60)).padStart(2, '0')}`;
  };
  const callBridge = (name, args) => new Promise((resolve, reject) => {
    const id = `bort-${++callNumber}`;
    bridgeWaiters.set(id, { resolve, reject });
    window.pywebview._jsApiCallback(name, args, id);
  });
  const makeApi = () => new Proxy({}, { get: (_, name) => (...args) => callBridge(name, args) });
  const setPath = (kind, path) => { $(`${kind}-path`).value = path || ''; };
  const toggleBackend = () => {
    const whisperx = $('backend').value === 'whisperx';
    $('whispercpp-options').hidden = whisperx;
    $('whisperx-options').hidden = !whisperx;
    $('diarize-options').hidden = !whisperx;
  };
  const selectedFormats = () => [...document.querySelectorAll('input[name="format"]:checked')].map((item) => item.value);
  const formSettings = () => ({
    backend: $('backend').value, language: $('language').value, task: $('task').value,
    whisperx_model: $('whisperx-model').value, min_speakers: $('min-speakers').value,
    max_speakers: $('max-speakers').value, formats: selectedFormats(),
    keep_wav: $('keep-wav').checked, verbose: $('verbose').checked,
    no_diarize: $('no-diarize').checked, auto_markers: $('auto-markers').checked,
  });
  const applyInitialState = (state) => {
    Object.entries(state.paths || {}).forEach(([key, value]) => setPath(key, value));
    const settings = state.settings || {};
    [['backend', 'backend'], ['language', 'language'], ['task', 'task'], ['whisperx_model', 'whisperx-model']]
      .forEach(([key, id]) => { if (settings[key]) $(id).value = settings[key]; });
    [['min_speakers', 'min-speakers'], ['max_speakers', 'max-speakers']]
      .forEach(([key, id]) => { if (settings[key]) $(id).value = settings[key]; });
    [['keep_wav', 'keep-wav'], ['verbose', 'verbose'], ['no_diarize', 'no-diarize'], ['auto_markers', 'auto-markers']]
      .forEach(([key, id]) => { if (typeof settings[key] === 'boolean') $(id).checked = settings[key]; });
    if (Array.isArray(settings.formats)) {
      document.querySelectorAll('input[name="format"]').forEach((item) => {
        item.checked = settings.formats.includes(item.value);
      });
    }
    toggleBackend();
  };
  const renderPreview = (segments, outputLocation) => {
    const preview = $('preview');
    const target = $('segments');
    target.textContent = '';
    $('output-location').textContent = outputLocation ? `Ausgabe gespeichert in: ${outputLocation}` : '';
    preview.hidden = false;
    let index = 0;
    const renderBatch = () => {
      const fragment = document.createDocumentFragment();
      const end = Math.min(index + 50, segments.length);
      for (; index < end; index += 1) {
        const segment = segments[index] || {};
        const row = document.createElement('div');
        row.className = 'segment';
        const timestamp = document.createElement('span');
        timestamp.className = 'timestamp';
        timestamp.textContent = `${formatTime(segment.start)} – ${formatTime(segment.end)}`;
        const speaker = document.createElement('span');
        speaker.className = 'speaker';
        speaker.textContent = segment.speaker || 'Sprecher';
        const text = document.createElement('span');
        text.textContent = segment.text || '';
        row.append(timestamp, speaker, text);
        fragment.append(row);
      }
      target.append(fragment);
      if (index < segments.length) requestAnimationFrame(renderBatch);
    };
    renderBatch();
  };

  window.__bortDispatch = (payloadJson) => {
    let payload;
    try { payload = JSON.parse(payloadJson); } catch (_) { return; }
    if (payload.type === 'bridge-result') {
      const waiter = bridgeWaiters.get(payload.id);
      if (!waiter) return;
      bridgeWaiters.delete(payload.id);
      if (payload.ok) waiter.resolve(payload.result); else waiter.reject(new Error(payload.error));
    } else if (payload.type === 'progress') setProgress(payload.percent, payload.phase);
    else if (payload.type === 'log') appendLog(payload.message);
    else if (payload.type === 'error') {
      setStatus(payload.message, true);
      $('start').disabled = false;
      appendLog(`FEHLER: ${payload.message}`);
    } else if (payload.type === 'done') {
      setStatus(payload.message);
      setProgress(100, 'Fertig');
      $('start').disabled = false;
      renderPreview(payload.segments || [], payload.output_location);
    }
  };
  $('theme-toggle').addEventListener('click', () => {
    currentTheme = currentTheme === 'light' ? 'dark' : 'light';
    applyTheme(currentTheme);
    try { localStorage.setItem('bort-theme', currentTheme); } catch (_) { /* egal */ }
  });
  document.querySelectorAll('.nav-item').forEach((button) => button.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach((item) => item.classList.toggle('active', item === button));
    document.querySelectorAll('.view').forEach((view) => view.classList.toggle('active', view.id === button.dataset.view));
  }));
  $('backend').addEventListener('change', toggleBackend);
  [['audio', 'pick-audio'], ['marker', 'pick-marker'], ['output', 'pick-output'], ['model', 'pick-model']]
    .forEach(([kind, id]) => $(id).addEventListener('click', async () => {
      const result = await api[`pick_${kind}`]();
      if (result && result.ok) setPath(kind, result.path);
    }));
  $('start').addEventListener('click', async () => {
    $('preview').hidden = true;
    $('segments').textContent = '';
    $('output-location').textContent = '';
    $('log').textContent = '';
    setProgress(0, 'Warte');
    setStatus('Transkription wird gestartet …');
    const result = await api.start_transcription(formSettings());
    if (!result.ok) {
      setStatus((result.errors || [result.error || 'Start fehlgeschlagen.']).join(' '), true);
      return;
    }
    $('start').disabled = true;
  });
  window.addEventListener('pywebviewready', async () => {
    window.pywebview.api = makeApi();
    api = window.pywebview.api;
    try {
      const initial = await api.initial_state();
      if (initial.ok) applyInitialState(initial);
      else setStatus(initial.error || 'Initialisierung fehlgeschlagen.', true);
    } catch (error) {
      setStatus(`Bridge nicht verfügbar: ${error}`, true);
    }
  });
})();

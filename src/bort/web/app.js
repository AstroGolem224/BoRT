(() => {
  const $ = (id) => document.getElementById(id);
  const bridgeWaiters = new Map();
  let callNumber = 0;
  let api = null;
  let reviewId = null;
  let reviewSegments = [];
  let activeBatchId = null;
  let pendingBatchItems = [];

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
  const setViewStatus = (id, message, error = false) => {
    const node = $(id);
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
  const setBatchProgress = (percent, label) => {
    const value = Math.max(0, Math.min(100, Number(percent) || 0));
    $('batch-progress-bar').style.width = `${value}%`;
    $('batch-progress-value').textContent = `${Math.round(value)} %`;
    $('batch-progress-label').textContent = label || '';
  };
  const appendBatchLog = (line) => {
    const log = $('batch-log');
    log.textContent = `${log.textContent}${line}\n`.slice(-30000);
    log.scrollTop = log.scrollHeight;
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
  const renderSpeakers = (speakers) => {
    const target = $('speaker-rows');
    target.textContent = '';
    speakers.forEach((speaker) => {
      const row = document.createElement('div');
      row.className = 'speaker-edit-row';
      const identity = document.createElement('span');
      identity.className = 'speaker-id';
      identity.textContent = speaker.id;
      const input = document.createElement('input');
      input.type = 'text';
      input.value = speaker.name || '';
      input.dataset.speakerId = speaker.id;
      input.addEventListener('input', renderSpeakerTranscript);
      const play = document.createElement('button');
      play.type = 'button';
      play.textContent = '▶ Abspielen';
      play.addEventListener('click', async () => {
        const result = await api.play_segment(reviewId, speaker.id);
        setViewStatus('speaker-status', result.ok ? `${speaker.name || speaker.id} wird abgespielt.` : result.error, !result.ok);
      });
      row.append(identity, input, play);
      target.append(row);
    });
    $('speaker-editor').hidden = false;
    renderSpeakerTranscript();
  };
  const currentSpeakerNames = () => {
    const names = {};
    document.querySelectorAll('#speaker-rows input[data-speaker-id]').forEach((input) => {
      names[input.dataset.speakerId] = input.value.trim();
    });
    return names;
  };
  const renderSpeakerTranscript = () => {
    const target = $('speaker-transcript');
    if (!target) return;
    const names = currentSpeakerNames();
    const fragment = document.createDocumentFragment();
    reviewSegments.forEach((segment) => {
      const row = document.createElement('div');
      row.className = 'segment';
      const timestamp = document.createElement('span');
      timestamp.className = 'timestamp';
      timestamp.textContent = `${formatTime(segment.start)} – ${formatTime(segment.end)}`;
      const speaker = document.createElement('span');
      speaker.className = 'speaker';
      const mapped = segment.speaker_id != null ? names[segment.speaker_id] : '';
      speaker.textContent = mapped || segment.speaker_id || 'Sprecher';
      const text = document.createElement('span');
      text.textContent = segment.text || '';
      row.append(timestamp, speaker, text);
      fragment.append(row);
    });
    target.textContent = '';
    target.append(fragment);
  };
  const renderBatchItems = (items) => {
    const target = $('batch-items');
    target.textContent = '';
    items.forEach((item) => {
      const row = document.createElement('div');
      row.className = 'batch-item';
      const names = document.createElement('div');
      const audio = document.createElement('strong');
      audio.textContent = item.audio_name;
      names.append(audio);
      if (item.marker_name) {
        const marker = document.createElement('span');
        marker.textContent = `Marker: ${item.marker_name}`;
        names.append(marker);
      }
      const outcome = document.createElement('span');
      outcome.className = 'batch-outcome';
      outcome.dataset.audioName = item.audio_name;
      outcome.textContent = 'Ausstehend';
      row.append(names, outcome);
      target.append(row);
    });
    if (!items.length) {
      const empty = document.createElement('p');
      empty.className = 'empty-state';
      empty.textContent = 'Keine ausstehenden Dateien gefunden.';
      target.append(empty);
    }
    $('pending-count').textContent = `${items.length} ${items.length === 1 ? 'Datei' : 'Dateien'}`;
    $('start-batch').disabled = items.length === 0 || Boolean(activeBatchId);
  };
  const setBatchOutcome = (audioName, text, error = false) => {
    document.querySelectorAll('.batch-outcome').forEach((node) => {
      if (node.dataset.audioName === audioName) {
        node.textContent = text;
        node.classList.toggle('error', error);
      }
    });
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
    } else if (payload.type === 'batch_item_start') {
      setBatchOutcome(payload.audio_name, 'Läuft …');
      setBatchProgress(((payload.index - 1) / payload.total) * 100, `${payload.index}/${payload.total}: ${payload.audio_name}`);
    } else if (payload.type === 'batch_item_progress') {
      const overall = ((payload.index - 1) + (Number(payload.percent) || 0) / 100) / payload.total * 100;
      setBatchProgress(overall, `${payload.index}/${payload.total}: ${payload.phase || ''}`);
    } else if (payload.type === 'batch_item_log') {
      appendBatchLog(`[${payload.index}/${payload.total}] ${payload.message}`);
    } else if (payload.type === 'batch_item_done') {
      const failed = String(payload.message || '').startsWith('Fehler:');
      setBatchOutcome(payload.audio_name, payload.message || 'Fertig', failed);
    } else if (payload.type === 'batch_item_error') {
      setBatchOutcome(payload.audio_name, payload.message || 'Fehler', true);
      appendBatchLog(`FEHLER ${payload.audio_name}: ${payload.message}`);
    } else if (payload.type === 'batch_item_skip') {
      setBatchOutcome(payload.audio_name, `Übersprungen: ${payload.message}`);
    } else if (payload.type === 'batch_finished') {
      activeBatchId = null;
      pendingBatchItems = [];
      $('cancel-batch').disabled = true;
      $('start-batch').disabled = true;
      setBatchProgress(100, 'Batch beendet');
      setViewStatus('batch-status', `${payload.succeeded} OK, ${payload.failed} Fehler, ${payload.skipped} übersprungen`);
      renderBatchItems([]);
      $('batch-items').querySelector('.empty-state').textContent = 'Batch beendet. Vor dem nächsten Lauf bitte neu scannen.';
    }
  };
  $('theme-toggle').addEventListener('click', () => {
    currentTheme = currentTheme === 'light' ? 'dark' : 'light';
    applyTheme(currentTheme);
    try { localStorage.setItem('bort-theme', currentTheme); } catch (_) { /* egal */ }
  });
  document.querySelectorAll('.nav-item').forEach((button) => button.addEventListener('click', async () => {
    const current = document.querySelector('.view.active');
    if (current && current.id === 'speakers' && button.dataset.view !== 'speakers' && api) {
      await api.stop_playback();
    }
    document.querySelectorAll('.nav-item').forEach((item) => item.classList.toggle('active', item === button));
    document.querySelectorAll('.view').forEach((view) => view.classList.toggle('active', view.id === button.dataset.view));
    if (activeBatchId && button.dataset.view !== 'batch') {
      setStatus('Der Batch läuft im Hintergrund weiter. Status und Abbruch bleiben in der Batch-Ansicht verfügbar.');
    }
  }));
  $('backend').addEventListener('change', toggleBackend);
  [['audio', 'pick-audio'], ['marker', 'pick-marker'], ['output', 'pick-output'], ['model', 'pick-model']]
    .forEach(([kind, id]) => $(id).addEventListener('click', async () => {
      const result = await api[`pick_${kind}`]();
      if (result && result.ok) setPath(kind, result.path);
    }));
  $('open-output').addEventListener('click', async () => {
    const result = await api.open_output_dir();
    if (result && !result.ok) setStatus(result.error || 'Ordner konnte nicht geöffnet werden.', true);
  });
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
  $('pick-review').addEventListener('click', async () => {
    const result = await api.pick_review_file();
    if (!result || result.cancelled) return;
    if (!result.ok) {
      setViewStatus('speaker-status', result.error || 'Review konnte nicht geladen werden.', true);
      return;
    }
    reviewId = result.review_id;
    reviewSegments = result.segments || [];
    $('review-name').value = result.audio_name || '';
    renderSpeakers(result.speakers || []);
    setViewStatus('speaker-status', `${(result.speakers || []).length} Sprecher geladen.`);
  });
  $('stop-playback').addEventListener('click', async () => {
    await api.stop_playback();
    setViewStatus('speaker-status', 'Wiedergabe gestoppt.');
  });
  $('apply-speakers').addEventListener('click', async () => {
    const renameMap = {};
    document.querySelectorAll('#speaker-rows input[data-speaker-id]').forEach((input) => {
      renameMap[input.dataset.speakerId] = input.value;
    });
    const result = await api.apply_speaker_rename(reviewId, renameMap);
    if (!result.ok) {
      setViewStatus('speaker-status', result.error || 'Änderungen konnten nicht gespeichert werden.', true);
      return;
    }
    renderSpeakers(result.speakers || []);
    setViewStatus('speaker-status', `${result.files_rewritten} Dateien neu geschrieben.`);
  });
  $('pick-watch').addEventListener('click', async () => {
    const result = await api.pick_watch_dir();
    if (result && result.ok) $('watch-path').value = result.path || '';
  });
  $('scan-batch').addEventListener('click', async () => {
    setViewStatus('batch-status', 'Ordner wird gescannt …');
    const result = await api.scan_batch();
    if (!result.ok) {
      setViewStatus('batch-status', result.error || 'Scan fehlgeschlagen.', true);
      return;
    }
    pendingBatchItems = result.items || [];
    renderBatchItems(pendingBatchItems);
    $('unstable-count').textContent = `${result.skipped_unstable || 0} noch instabile Dateien übersprungen.`;
    setViewStatus('batch-status', `${pendingBatchItems.length} ausstehende Dateien gefunden.`);
  });
  $('start-batch').addEventListener('click', async () => {
    $('batch-log').textContent = '';
    setBatchProgress(0, 'Batch wird gestartet …');
    const result = await api.start_batch(formSettings());
    if (!result.ok) {
      const message = (result.errors || [result.busy ? 'Es läuft bereits ein Job.' : result.error]).join(' ');
      setViewStatus('batch-status', message, true);
      return;
    }
    activeBatchId = result.batch_id;
    $('start-batch').disabled = true;
    $('cancel-batch').disabled = false;
    setViewStatus('batch-status', 'Batch läuft. Beim Verlassen dieser Ansicht läuft er weiter.');
  });
  $('cancel-batch').addEventListener('click', async () => {
    const result = await api.cancel_batch(activeBatchId);
    setViewStatus('batch-status', result.ok ? 'Abbruch angefordert; der aktuelle Eintrag wird beendet.' : result.error, !result.ok);
  });
  window.addEventListener('beforeunload', (event) => {
    if (!activeBatchId) return;
    event.preventDefault();
    event.returnValue = 'Der Batch läuft noch.';
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

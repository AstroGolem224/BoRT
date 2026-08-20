(() => {
  const $ = (id) => document.getElementById(id);
  const bridgeWaiters = new Map();
  let callNumber = 0;
  let api = null;
  let reviewId = null;
  let reviewBaseName = '';
  let reviewSegments = [];
  let reviewBookmarks = [];
  let waveformResult = null;
  let waveformRequest = null;
  let mediaMetadataReady = false;
  let mediaFailed = false;
  let waveCache = null;
  let activeBatchId = null;
  let pendingBatchItems = [];
  let voiceCatalogNames = [];
  let reviewSpeakers = [];
  let speakerDraftNames = new Map();
  let activeSpeakerId = null;
  let inlineSpeakerEditor = null;
  let inlineEditorSpeakerId = null;
  let speakerApplyFeedbackTimer = null;

  // Theme (hell/dunkel) – rein clientseitig via localStorage, Default dunkel.
  const applyTheme = (theme) => {
    document.documentElement.setAttribute('data-theme', theme === 'light' ? 'light' : 'dark');
    if (window.BortWave && document.getElementById('player-wave')) {
      requestAnimationFrame(() => {
        waveCache = null;
        renderWaveform();
      });
    }
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
  const setPath = (kind, path) => {
    const el = $(`${kind}-path`);
    if (el) el.value = path || '';
  };
  const toggleVoiceProfiles = () => {
    const disabled = $('no-diarize').checked || $('backend').value !== 'whisperx';
    $('voice-profiles').disabled = disabled;
    if (disabled) $('voice-profiles').checked = false;
  };
  const toggleBackend = () => {
    const whisperx = $('backend').value === 'whisperx';
    $('whispercpp-options').hidden = whisperx;
    $('whisperx-options').hidden = !whisperx;
    $('diarize-options').hidden = !whisperx;
    toggleVoiceProfiles();
  };
  const selectedFormats = () => [...document.querySelectorAll('input[name="format"]:checked')].map((item) => item.value);
  const formSettings = () => ({
    backend: $('backend').value, language: $('language').value, task: $('task').value,
    whisperx_model: $('whisperx-model').value, min_speakers: $('min-speakers').value,
    max_speakers: $('max-speakers').value, formats: selectedFormats(),
    keep_wav: $('keep-wav').checked, verbose: $('verbose').checked,
    no_diarize: $('no-diarize').checked, auto_markers: $('auto-markers').checked,
    colocate: $('colocate').checked, voice_profiles: $('voice-profiles').checked,
    performance_profile: $('performance-profile').value,
  });
  const renderGlobalSettingsSummary = () => {
    const whisperx = $('backend').value === 'whisperx';
    const backend = whisperx ? 'whisperX / GPU' : 'whisper.cpp / CPU';
    const language = $('language').selectedOptions[0]?.textContent || 'Automatisch';
    const modelPath = $('model-path').value.split(/[\\/]/).pop();
    const model = whisperx ? $('whisperx-model').value : modelPath || 'kein Modell';
    const formats = selectedFormats().map((item) => item.toUpperCase()).join(', ') || 'kein Format';
    const storage = $('colocate').checked ? 'neben Audio' : 'Ausgabeordner';
    const summary = `${backend} · ${language} · ${model} · ${formats} · ${storage}`;
    document.querySelectorAll('.global-settings-summary').forEach((node) => {
      node.textContent = summary;
      node.title = summary;
    });
  };
  const toggleColocate = () => {
    const active = $('colocate').checked;
    $('output-path').disabled = active;
    $('pick-output').disabled = active;
    $('open-output').disabled = active;
    $('output-mode-hint').textContent = active
      ? 'Globale Option aktiv: Die Ausgabe wird neben der Audio-Datei gespeichert.'
      : 'Globale Option aktiv: Einzeltranskription und Batch verwenden den zentralen Ausgabeordner.';
  };
  const applyInitialState = (state) => {
    Object.entries(state.paths || {}).forEach(([key, value]) => setPath(key, value));
    const settings = state.settings || {};
    [['backend', 'backend'], ['language', 'language'], ['task', 'task'], ['whisperx_model', 'whisperx-model'], ['performance_profile', 'performance-profile']]
      .forEach(([key, id]) => { if (settings[key]) $(id).value = settings[key]; });
    [['min_speakers', 'min-speakers'], ['max_speakers', 'max-speakers']]
      .forEach(([key, id]) => { if (settings[key]) $(id).value = settings[key]; });
    [['keep_wav', 'keep-wav'], ['verbose', 'verbose'], ['no_diarize', 'no-diarize'], ['auto_markers', 'auto-markers'], ['colocate', 'colocate'], ['voice_profiles', 'voice-profiles']]
      .forEach(([key, id]) => { if (typeof settings[key] === 'boolean') $(id).checked = settings[key]; });
    if (Array.isArray(settings.formats)) {
      document.querySelectorAll('input[name="format"]').forEach((item) => {
        item.checked = settings.formats.includes(item.value);
      });
    }
    toggleBackend();
    toggleColocate();
    renderGlobalSettingsSummary();
    applyVoiceCatalog(state.voice_catalog || {});
  };
  const applyVoiceCatalog = (catalog) => {
    voiceCatalogNames = Array.isArray(catalog.names) ? catalog.names : [];
    const profiles = Array.isArray(catalog.profiles) ? catalog.profiles : [];
    const target = $('voice-profile-names');
    target.textContent = '';
    voiceCatalogNames.forEach((name) => {
      const option = document.createElement('option');
      option.value = name;
      target.append(option);
    });
    refreshSavedNameSelects();
    const status = $('voice-catalog-status');
    const profileList = $('voice-catalog-list');
    profileList.textContent = '';
    $('voice-catalog-count').textContent = `${profiles.length} ${profiles.length === 1 ? 'Eintrag' : 'Einträge'}`;
    if (catalog.available === false) {
      status.textContent = catalog.error || 'Lokaler Namenskatalog ist nicht verfügbar.';
      status.classList.add('error');
      $('voice-catalog-panel').open = true;
      $('remember-speakers').disabled = true;
      return;
    }
    status.classList.remove('error');
    $('remember-speakers').disabled = false;
    status.textContent = voiceCatalogNames.length
      ? `${voiceCatalogNames.length} lokale Namen als Vorschläge verfügbar.`
      : 'Noch keine Namen gespeichert. Stimmabdrücke werden nur nach ausdrücklicher Aktivierung ergänzt.';
    profiles.forEach((profile) => {
      const chip = document.createElement('span');
      chip.className = 'voice-profile-chip';
      const label = document.createElement('button');
      label.type = 'button';
      label.className = 'voice-profile-use';
      label.textContent = profile.has_voiceprint
        ? `${profile.name} · Stimme ×${profile.sample_count}`
        : `${profile.name} · nur Name`;
      label.title = `${profile.name} für den ausgewählten Sprecher verwenden`;
      label.addEventListener('click', () => assignActiveSpeakerName(profile.name));
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'voice-profile-delete';
      remove.textContent = '×';
      remove.title = `${profile.name} aus dem lokalen Katalog löschen`;
      remove.setAttribute('aria-label', remove.title);
      remove.addEventListener('click', async () => {
        if (!window.confirm(`Lokales Profil „${profile.name}“ wirklich löschen?`)) return;
        const result = await api.delete_voice_profile(profile.id);
        if (!result.ok) {
          setViewStatus('speaker-status', result.error || 'Profil konnte nicht gelöscht werden.', true);
          return;
        }
        applyVoiceCatalog(result.voice_catalog || {});
        setViewStatus('speaker-status', `Lokales Profil „${profile.name}“ gelöscht.`);
      });
      chip.append(label, remove);
      profileList.append(chip);
    });
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
    reviewSpeakers = speakers;
    speakerDraftNames = new Map(speakers.map((speaker) => [speaker.id, speaker.name || '']));
    const target = $('speaker-rows');
    target.textContent = '';
    const colors = speakerColorMap();
    speakers.forEach((speaker) => {
      const choice = document.createElement('button');
      choice.type = 'button';
      choice.className = 'speaker-choice';
      choice.dataset.speakerId = speaker.id;
      choice.setAttribute('role', 'option');
      choice.setAttribute('aria-selected', 'false');
      const dot = document.createElement('span');
      dot.className = 'speaker-color-dot';
      const color = colors.get(speaker.id);
      if (color) {
        dot.style.background = color;
        dot.style.color = color;
      }
      const name = document.createElement('span');
      name.className = 'speaker-choice-name';
      name.textContent = speaker.name || 'Unbenannt';
      const identity = document.createElement('span');
      identity.className = 'speaker-choice-id';
      identity.textContent = speaker.id;
      choice.append(dot, name, identity);
      choice.addEventListener('click', () => selectSpeaker(speaker.id, true));
      target.append(choice);
    });
    $('speaker-picker-count').textContent = `${speakers.length} Sprecher`;
    activeSpeakerId = speakers.some((speaker) => speaker.id === activeSpeakerId)
      ? activeSpeakerId
      : speakers[0]?.id || null;
    $('speaker-editor').hidden = false;
    $('apply-speakers-floating').hidden = speakers.length === 0;
    $('speaker-detail').hidden = !activeSpeakerId;
    if (activeSpeakerId) selectSpeaker(activeSpeakerId);
    renderSpeakerTranscript();
    renderWaveformLabels();
  };
  const currentSpeakerNames = () => {
    return Object.fromEntries(
      [...speakerDraftNames.entries()].map(([speakerId, name]) => [speakerId, name.trim()]),
    );
  };
  const updateSpeakerChoiceName = (speakerId) => {
    const choice = document.querySelector(
      `#speaker-rows .speaker-choice[data-speaker-id="${CSS.escape(speakerId)}"]`,
    );
    const name = choice?.querySelector('.speaker-choice-name');
    if (name) name.textContent = speakerDraftNames.get(speakerId)?.trim() || 'Unbenannt';
  };
  const populateSavedNameSelect = (select, currentName = '') => {
    if (!select) return;
    const trimmedName = currentName.trim();
    select.textContent = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = voiceCatalogNames.length
      ? 'Gespeicherten Namen wählen …'
      : 'Noch keine Namen gespeichert';
    select.append(placeholder);
    voiceCatalogNames.forEach((name) => {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = name;
      select.append(option);
    });
    select.value = voiceCatalogNames.includes(trimmedName) ? trimmedName : '';
    select.disabled = voiceCatalogNames.length === 0;
  };
  const refreshSavedNameSelects = () => {
    document.querySelectorAll('.saved-speaker-name-select').forEach((select) => {
      const speakerId = select.dataset.speakerId || activeSpeakerId;
      populateSavedNameSelect(select, speakerDraftNames.get(speakerId) || '');
    });
  };
  const closeInlineSpeakerEditor = () => {
    inlineSpeakerEditor?.remove();
    inlineSpeakerEditor = null;
    inlineEditorSpeakerId = null;
  };
  const updateSpeakerName = (speakerId, name, sourceInput = null) => {
    if (!speakerId) return;
    speakerDraftNames.set(speakerId, name);
    updateSpeakerChoiceName(speakerId);
    if (activeSpeakerId === speakerId) {
      if ($('speaker-name-input') !== sourceInput) $('speaker-name-input').value = name;
      $('speaker-saved-name').dataset.speakerId = speakerId;
      populateSavedNameSelect($('speaker-saved-name'), name);
    }
    if (inlineSpeakerEditor && inlineEditorSpeakerId === speakerId) {
      const inlineInput = inlineSpeakerEditor.querySelector('.inline-speaker-name');
      if (inlineInput && inlineInput !== sourceInput) inlineInput.value = name;
      populateSavedNameSelect(
        inlineSpeakerEditor.querySelector('.saved-speaker-name-select'),
        name,
      );
    }
    updateSpeakerTranscriptNames();
    renderWaveformLabels();
  };
  const assignActiveSpeakerName = (name) => {
    if (!activeSpeakerId) return;
    updateSpeakerName(activeSpeakerId, name);
  };
  const selectSpeaker = (speakerId, focusName = false) => {
    const speaker = reviewSpeakers.find((item) => item.id === speakerId);
    if (!speaker) return;
    if (inlineEditorSpeakerId && inlineEditorSpeakerId !== speakerId) closeInlineSpeakerEditor();
    activeSpeakerId = speakerId;
    document.querySelectorAll('#speaker-rows .speaker-choice').forEach((choice) => {
      const selected = choice.dataset.speakerId === speakerId;
      choice.classList.toggle('active', selected);
      choice.setAttribute('aria-selected', String(selected));
    });
    const color = speakerColorMap().get(speakerId);
    const dot = $('speaker-detail-dot');
    if (color) {
      dot.style.background = color;
      dot.style.color = color;
    }
    $('speaker-detail-id').textContent = speakerId;
    $('speaker-name-input').value = speakerDraftNames.get(speakerId) || '';
    $('speaker-saved-name').dataset.speakerId = speakerId;
    populateSavedNameSelect($('speaker-saved-name'), speakerDraftNames.get(speakerId) || '');
    const suggestion = (speaker.suggestions || [])[0];
    const suggestionButton = $('speaker-suggestion');
    suggestionButton.hidden = !suggestion;
    suggestionButton.textContent = suggestion
      ? `Vorschlag: ${suggestion.name} · ${Math.round(suggestion.score * 100)} %`
      : '';
    $('speaker-detail').hidden = false;
    if (focusName) $('speaker-name-input').focus();
  };
  const openInlineSpeakerEditor = (speakerId, row) => {
    if (!speakerId || !row) return;
    if (inlineSpeakerEditor && inlineEditorSpeakerId === speakerId
        && inlineSpeakerEditor.parentElement === row) {
      inlineSpeakerEditor.querySelector('.inline-speaker-name')?.focus();
      return;
    }
    closeInlineSpeakerEditor();
    selectSpeaker(speakerId);
    const speaker = reviewSpeakers.find((item) => item.id === speakerId);
    const color = speakerColorMap().get(speakerId);
    const editor = document.createElement('div');
    editor.className = 'inline-speaker-editor';
    editor.setAttribute('role', 'group');
    editor.setAttribute('aria-label', `Sprecher ${speakerId} benennen`);
    editor.addEventListener('click', (event) => event.stopPropagation());
    editor.addEventListener('keydown', (event) => event.stopPropagation());

    const heading = document.createElement('div');
    heading.className = 'inline-speaker-heading';
    const dot = document.createElement('span');
    dot.className = 'speaker-color-dot';
    if (color) {
      dot.style.background = color;
      dot.style.color = color;
    }
    const title = document.createElement('strong');
    title.textContent = `${speakerId} überall benennen`;
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'inline-speaker-close';
    close.textContent = '×';
    close.title = 'Editor schließen';
    close.setAttribute('aria-label', close.title);
    close.addEventListener('click', closeInlineSpeakerEditor);
    heading.append(dot, title, close);

    const fields = document.createElement('div');
    fields.className = 'inline-speaker-fields';
    const inputLabel = document.createElement('label');
    inputLabel.textContent = 'Anzeigename';
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'inline-speaker-name';
    input.setAttribute('list', 'voice-profile-names');
    input.autocomplete = 'off';
    input.placeholder = 'Name eingeben';
    input.value = speakerDraftNames.get(speakerId) || '';
    input.addEventListener('input', (event) => {
      updateSpeakerName(speakerId, event.target.value, event.target);
    });
    inputLabel.append(input);

    const savedLabel = document.createElement('label');
    savedLabel.textContent = 'Gespeicherter Name';
    const saved = document.createElement('select');
    saved.className = 'saved-speaker-name-select';
    saved.dataset.speakerId = speakerId;
    populateSavedNameSelect(saved, speakerDraftNames.get(speakerId) || '');
    saved.addEventListener('change', (event) => {
      if (event.target.value) updateSpeakerName(speakerId, event.target.value);
    });
    savedLabel.append(saved);
    fields.append(inputLabel, savedLabel);

    const actions = document.createElement('div');
    actions.className = 'inline-speaker-actions';
    const suggestion = (speaker?.suggestions || [])[0];
    if (suggestion) {
      const suggestionButton = document.createElement('button');
      suggestionButton.type = 'button';
      suggestionButton.className = 'inline-speaker-suggestion';
      suggestionButton.textContent = `Vorschlag: ${suggestion.name} · ${Math.round(suggestion.score * 100)} %`;
      suggestionButton.addEventListener('click', () => updateSpeakerName(speakerId, suggestion.name));
      actions.append(suggestionButton);
    }
    const play = document.createElement('button');
    play.type = 'button';
    play.textContent = '▶ Hörprobe';
    play.addEventListener('click', () => {
      const label = speakerDraftNames.get(speakerId)?.trim() || speakerId;
      playFromSpeaker(speakerId, label);
    });
    const done = document.createElement('button');
    done.type = 'button';
    done.className = 'primary';
    done.textContent = 'Fertig';
    done.addEventListener('click', closeInlineSpeakerEditor);
    actions.append(play, done);
    editor.append(heading, fields, actions);
    inlineSpeakerEditor = editor;
    inlineEditorSpeakerId = speakerId;
    row.append(editor);
    input.focus();
    input.select();
  };
  const renderSpeakerTranscript = () => {
    const target = $('speaker-transcript');
    if (!target) return;
    closeInlineSpeakerEditor();
    const names = currentSpeakerNames();
    const fragment = document.createDocumentFragment();
    reviewSegments.forEach((segment) => {
      const row = document.createElement('div');
      row.className = 'segment';
      if (segment.speaker_id != null) row.dataset.speakerId = segment.speaker_id;
      const timestamp = document.createElement('span');
      timestamp.className = 'timestamp';
      timestamp.textContent = `${formatTime(segment.start)} – ${formatTime(segment.end)}`;
      const mapped = segment.speaker_id != null ? names[segment.speaker_id] : '';
      const displayName = mapped || segment.speaker_id || 'Sprecher';
      const speaker = document.createElement(segment.speaker_id != null ? 'button' : 'span');
      speaker.className = segment.speaker_id != null
        ? 'speaker speaker-inline-button'
        : 'speaker';
      speaker.textContent = displayName;
      if (segment.speaker_id != null) {
        speaker.type = 'button';
        speaker.title = `${displayName} überall ändern`;
        speaker.setAttribute('aria-label', `${displayName} – Sprechernamen ändern`);
        speaker.addEventListener('click', (event) => {
          event.stopPropagation();
          openInlineSpeakerEditor(segment.speaker_id, row);
        });
      }
      const text = document.createElement('span');
      text.textContent = segment.text || '';
      row.append(timestamp, speaker, text);
      row.addEventListener('click', () => {
        if (segment.speaker_id != null) selectSpeaker(segment.speaker_id);
        seekToSegment(segment);
      });
      fragment.append(row);
    });
    target.textContent = '';
    target.append(fragment);
    const count = $('speaker-transcript-count');
    if (count) {
      count.textContent = reviewSegments.length === 1
        ? '1 Segment'
        : `${reviewSegments.length} Segmente`;
    }
  };
  const updateSpeakerTranscriptNames = () => {
    const target = $('speaker-transcript');
    if (!target) return;
    const names = currentSpeakerNames();
    target.querySelectorAll('.segment[data-speaker-id]').forEach((row) => {
      const speaker = row.querySelector('.speaker');
      if (!speaker) return;
      const speakerId = row.dataset.speakerId;
      const displayName = names[speakerId] || speakerId || 'Sprecher';
      speaker.textContent = displayName;
      if (speaker.matches('button')) {
        speaker.title = `${displayName} überall ändern`;
        speaker.setAttribute('aria-label', `${displayName} – Sprechernamen ändern`);
      }
    });
  };

  // --- Audio-Player (Sprecher-Ansicht) ---
  const audioEl = () => $('player-audio');
  const speakerPalette = [
    '#22d3ee', '#8b5cf6', '#ec4899', '#06b6d4', '#a855f7',
    '#f472b6', '#38bdf8', '#c026d3', '#2dd4bf', '#818cf8',
  ];
  const currentTimelineDuration = () => {
    const audio = audioEl();
    if (mediaMetadataReady && Number.isFinite(audio.duration) && audio.duration > 0) return audio.duration;
    if (waveformResult && Number.isFinite(waveformResult.duration)
        && (mediaFailed || waveformResult.source === 'sidecar')) return waveformResult.duration;
    return 0;
  };
  const activeRequestIsCurrent = () => {
    const audio = audioEl();
    return waveformRequest && window.BortWave.isCurrentReview(
      waveformRequest.reviewId, reviewId, waveformRequest.src, audio.src,
    );
  };
  const updateAria = () => {
    const audio = audioEl();
    const values = window.BortWave.ariaValues(audio.currentTime, currentTimelineDuration());
    const bar = $('player-bar');
    Object.entries(values).forEach(([name, value]) => bar.setAttribute(`aria-${name}`, value));
  };
  const speakerColorMap = () => {
    const colors = new Map();
    reviewSegments.forEach((segment) => {
      const key = segment.speaker_id;
      if (!colors.has(key)) colors.set(key, speakerPalette[colors.size % speakerPalette.length]);
    });
    return colors;
  };
  const renderWaveformLabels = () => {
    const target = $('player-labels');
    target.textContent = '';
    const duration = currentTimelineDuration();
    const bar = $('player-bar');
    if (!duration || !waveformResult || bar.clientWidth <= 0) return;
    const normalized = window.BortWave.normalizeSegments(reviewSegments, duration);
    const blocks = window.BortWave.mergeBlocks(normalized, 2);
    const names = currentSpeakerNames();
    const context = $('player-wave').getContext('2d');
    context.font = '700 10px sans-serif';
    const labels = window.BortWave.layoutLabels(
      blocks,
      duration,
      bar.clientWidth,
      (speakerId) => names[speakerId] || speakerId || 'Sprecher',
      (text) => context.measureText(text).width,
    );
    labels.forEach((label) => {
      const node = document.createElement('span');
      node.className = 'player-label';
      node.textContent = label.text;
      node.style.left = `${label.center}px`;
      node.style.width = `${label.right - label.left}px`;
      target.append(node);
    });
  };
  const buildWaveCache = (duration) => {
    const bar = $('player-bar');
    const canvas = $('player-wave');
    const width = bar.clientWidth;
    const height = bar.clientHeight;
    if (!width || !height || !waveformResult) return null;
    const dpr = Math.max(1, window.devicePixelRatio || 1);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    const normalized = window.BortWave.normalizeSegments(reviewSegments, duration);
    const colors = speakerColorMap();
    const createLayer = (alpha) => {
      const layer = document.createElement('canvas');
      layer.width = canvas.width;
      layer.height = canvas.height;
      const context = layer.getContext('2d');
      context.scale(dpr, dpr);
      context.globalAlpha = alpha;
      context.lineWidth = Math.max(1, width / Math.max(waveformResult.peaks.length, 1) * 0.72);
      context.lineCap = 'round';
      const center = height * 0.57;
      const amplitude = height * 0.32;
      waveformResult.peaks.forEach((peak, index) => {
        const start = index / waveformResult.peaks.length * duration;
        const end = (index + 1) / waveformResult.peaks.length * duration;
        const segment = window.BortWave.bucketSpeaker(start, end, normalized);
        context.strokeStyle = segment ? colors.get(segment.speaker_id) : '#526078';
        const x = (index + 0.5) / waveformResult.peaks.length * width;
        const low = Math.max(-1, Math.min(1, Number(peak[0]) || 0));
        const high = Math.max(-1, Math.min(1, Number(peak[1]) || 0));
        context.beginPath();
        context.moveTo(x, center - high * amplitude);
        context.lineTo(x, center - low * amplitude);
        context.stroke();
      });
      return layer;
    };
    return { width, height, dpr, dim: createLayer(0.34), bright: createLayer(0.98) };
  };
  const renderWaveform = () => {
    const canvas = $('player-wave');
    if (!canvas || !waveformResult) return;
    const duration = currentTimelineDuration();
    if (!duration || !activeRequestIsCurrent()) return;
    const bar = $('player-bar');
    const dpr = Math.max(1, window.devicePixelRatio || 1);
    if (!waveCache || waveCache.width !== bar.clientWidth || waveCache.height !== bar.clientHeight
        || waveCache.dpr !== dpr) {
      waveCache = buildWaveCache(duration);
      renderWaveformLabels();
    }
    if (!waveCache) return;
    const context = canvas.getContext('2d');
    context.setTransform(1, 0, 0, 1, 0, 0);
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(waveCache.dim, 0, 0);
    const fraction = mediaFailed ? 0 : Math.max(0, Math.min(1, audioEl().currentTime / duration));
    const clipWidth = Math.round(canvas.width * fraction);
    if (clipWidth > 0) {
      context.save();
      context.beginPath();
      context.rect(0, 0, clipWidth, canvas.height);
      context.clip();
      context.drawImage(waveCache.bright, 0, 0);
      context.restore();
    }
    bar.classList.remove('waveform-loading');
    bar.classList.add('waveform-ready');
    renderPlayerMarkers();
    updateAria();
  };
  const tryRenderWaveform = () => {
    if (!waveformResult || !activeRequestIsCurrent()) return;
    if (!mediaFailed && !mediaMetadataReady && waveformResult.source !== 'sidecar') return;
    const audio = audioEl();
    if (!mediaFailed && (!Number.isFinite(audio.duration) || audio.duration <= 0)) return;
    if (!mediaFailed && waveformResult.duration > 0) {
      const mismatch = Math.abs(waveformResult.duration - audio.duration) / audio.duration;
      if (mismatch > 0.02) {
        console.warn(`Waveform-/Mediendauer weichen um ${(mismatch * 100).toFixed(1)} % ab.`);
      }
    }
    renderWaveform();
  };
  const requestReviewWaveform = () => {
    if (!api || !reviewId || !audioEl().src) return;
    const captured = { reviewId, src: audioEl().src };
    waveformRequest = captured;
    api.get_waveform(captured.reviewId).then((result) => {
      if (!window.BortWave.isCurrentReview(captured.reviewId, reviewId, captured.src, audioEl().src)) return;
      if (!result || !result.ok) {
        if (!waveformResult || waveformResult.source !== 'sidecar') {
          waveformResult = null;
          $('player-bar').classList.remove('waveform-loading');
        }
        setViewStatus('speaker-status', result && result.error
          ? `Waveform nicht verfügbar: ${result.error}` : 'Waveform nicht verfügbar.');
        return;
      }
      waveformResult = {
        duration: Number(result.duration) || 0,
        peaks: Array.isArray(result.peaks) ? result.peaks : [],
        source: 'ffmpeg',
      };
      waveCache = null;
      tryRenderWaveform();
    }).catch((error) => {
      if (!window.BortWave.isCurrentReview(captured.reviewId, reviewId, captured.src, audioEl().src)) return;
      if (!waveformResult || waveformResult.source !== 'sidecar') {
        waveformResult = null;
        $('player-bar').classList.remove('waveform-loading');
      }
      setViewStatus('speaker-status', `Waveform nicht verfügbar: ${error}`);
    });
  };
  const loadReviewAudio = (url, bookmarks, sidecarPeaks = [], sidecarDurationMs = 0) => {
    reviewBookmarks = bookmarks || [];
    const audio = audioEl();
    const card = $('player-card');
    waveformResult = null;
    waveformRequest = null;
    waveCache = null;
    mediaMetadataReady = false;
    mediaFailed = false;
    $('player-wave').getContext('2d').clearRect(0, 0, $('player-wave').width, $('player-wave').height);
    $('player-labels').textContent = '';
    $('player-bar').classList.add('waveform-loading');
    $('player-bar').classList.remove('waveform-ready');
    $('player-bar').removeAttribute('aria-disabled');
    $('player-play').disabled = false;
    if (!url) {
      card.hidden = true;
      audio.removeAttribute('src');
      audio.load();
      return;
    }
    card.hidden = false;
    audio.src = url;
    audio.load();
    $('player-play').textContent = '▶';
    $('player-progress').style.width = '0%';
    $('player-head').style.left = '0%';
    $('player-time').textContent = '00:00';
    $('player-duration').textContent = '00:00';
    $('player-markers').textContent = '';
    updateAria();
    const sidecarDuration = Number(sidecarDurationMs) / 1000;
    if (sidecarDuration > 0 && Array.isArray(sidecarPeaks) && sidecarPeaks.length) {
      waveformResult = {
        duration: sidecarDuration,
        peaks: sidecarPeaks.map((peak) => [-Number(peak) || 0, Number(peak) || 0]),
        source: 'sidecar',
      };
      waveformRequest = { reviewId, src: audio.src };
      waveCache = null;
      tryRenderWaveform();
    }
  };
  const renderPlayerMarkers = () => {
    const target = $('player-markers');
    const audio = audioEl();
    const dur = currentTimelineDuration();
    target.textContent = '';
    if (!dur || !isFinite(dur)) return;
    reviewBookmarks.forEach((mark) => {
      const tick = document.createElement('div');
      tick.className = 'player-marker';
      tick.style.left = `${Math.max(0, Math.min(100, (mark.time / dur) * 100))}%`;
      const parts = [mark.type, mark.label].filter(Boolean);
      tick.title = `${formatTime(mark.time)}${parts.length ? ' · ' + parts.join(' – ') : ''}`;
      target.append(tick);
    });
  };
  const updatePlayerUI = () => {
    const audio = audioEl();
    const dur = audio.duration;
    const frac = dur && isFinite(dur) ? audio.currentTime / dur : 0;
    $('player-progress').style.width = `${frac * 100}%`;
    $('player-head').style.left = `${frac * 100}%`;
    $('player-time').textContent = formatTime(audio.currentTime);
    updateAria();
    if (waveformResult) renderWaveform();
  };
  const seekToFraction = (frac) => {
    const audio = audioEl();
    if (!mediaFailed && audio.duration && isFinite(audio.duration)) {
      audio.currentTime = Math.max(0, Math.min(1, frac)) * audio.duration;
    }
  };
  const seekToSegment = (segment) => {
    const audio = audioEl();
    if (!audio.src) return;
    // play() synchron in der Klick-Geste (WebKitGTK-Autoplay-Policy).
    const target = segment.start || 0;
    if (audio.readyState >= 1) audio.currentTime = target;
    else audio.addEventListener('loadedmetadata', () => { audio.currentTime = target; }, { once: true });
    audio.play().catch(() => {});
  };
  const scrollTranscriptToSpeaker = (speakerId) => {
    const target = document.querySelector(`#speaker-transcript .segment[data-speaker-id="${CSS.escape(speakerId)}"]`);
    if (!target) return;
    target.scrollIntoView({ block: 'center', behavior: 'smooth' });
    target.classList.add('segment-highlight');
    setTimeout(() => target.classList.remove('segment-highlight'), 1600);
  };
  const playFromSpeaker = (speakerId, label) => {
    const segment = reviewSegments.find((s) => s.speaker_id === speakerId);
    const audio = audioEl();
    if (segment && audio.src) {
      // play() MUSS synchron in der Klick-Geste laufen (WebKitGTK erlaubt sonst
      // kein Autoplay -> NotAllowedError). Seek best-effort jetzt + erneut,
      // sobald die Metadaten da sind.
      const target = segment.start || 0;
      if (audio.readyState >= 1) audio.currentTime = target;
      else audio.addEventListener('loadedmetadata', () => { audio.currentTime = target; }, { once: true });
      audio.play().catch(() => {});
      setViewStatus('speaker-status', `${label} ab ${formatTime(segment.start)}.`);
    } else if (!segment) {
      // Alte v1-Reviews mit doppelten Namen: Segmente dieser ID sind kollabiert.
      setViewStatus('speaker-status', `Keine Segmente für ${label} (${speakerId}) — Altdatei mit doppelten Namen?`);
    }
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
  const activateView = (viewId) => {
    document.querySelectorAll('.nav-item').forEach(
      (item) => item.classList.toggle('active', item.dataset.view === viewId),
    );
    document.querySelectorAll('.view').forEach(
      (view) => view.classList.toggle('active', view.id === viewId),
    );
  };
  const renderMiniWave = (canvas, peaks) => {
    const values = window.BortWave.resamplePeaks(peaks, 34);
    const width = canvas.clientWidth || 260;
    const height = canvas.clientHeight || 58;
    const dpr = Math.max(1, window.devicePixelRatio || 1);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    const context = canvas.getContext('2d');
    context.scale(dpr, dpr);
    const gradient = context.createLinearGradient(0, 0, width, 0);
    [[0, '#00D8E8'], [0.26, '#22D3EE'], [0.48, '#C9D4FF'], [0.70, '#A855F7'], [1, '#8B5CF6']]
      .forEach(([position, color]) => gradient.addColorStop(position, color));
    context.strokeStyle = gradient;
    context.lineCap = 'round';
    context.lineWidth = Math.max(2, width / 68);
    const bars = values.length ? values : Array(34).fill(0.03);
    bars.forEach((peak, index) => {
      const amplitude = Math.max(0.03, Math.min(1, Number(peak) || 0)) * height * 0.42;
      const x = (index + 0.5) / bars.length * width;
      context.beginPath();
      context.moveTo(x, height / 2 - amplitude);
      context.lineTo(x, height / 2 + amplitude);
      context.stroke();
    });
  };
  const librarySelection = new Set();
  let mailPasswordStored = false;
  // Ein geteilter Player für alle Bibliothekskarten; es spielt immer nur eine.
  let libraryActive = null; // { itemId, playButton, playhead, waveWrap }
  const libraryAudioEl = () => $('library-audio');
  const libraryStop = () => {
    const audio = libraryAudioEl();
    audio.pause();
    if (libraryActive) {
      libraryActive.playButton.textContent = '▶';
      libraryActive.playhead.hidden = true;
      libraryActive = null;
    }
    audio.removeAttribute('src');
    audio.load();
  };
  const libraryActivate = (item, controls) => {
    if (libraryActive && libraryActive.itemId !== item.item_id) libraryStop();
    const audio = libraryAudioEl();
    if (!audio.src || libraryActive === null) {
      audio.src = item.audio_url;
      libraryActive = { itemId: item.item_id, ...controls };
      libraryActive.playhead.hidden = false;
    }
    return audio;
  };
  const updateExportButton = () => {
    const count = librarySelection.size;
    const button = $('export-selection');
    button.textContent = `Auswahl exportieren (${count})`;
    button.disabled = count === 0;
    const send = $('export-send');
    send.textContent = `Exportieren & senden (${count})`;
    send.disabled = count === 0;
  };
  const updateMailPasswordRow = () => {
    $('mail-password-row').hidden = mailPasswordStored;
  };
  const applyMailState = (state) => {
    if (!state || !state.ok) return;
    if (state.recipient && !$('mail-to').value) $('mail-to').value = state.recipient;
    if (state.sender && !$('mail-from').value) $('mail-from').value = state.sender;
    mailPasswordStored = Boolean(state.has_password);
    updateMailPasswordRow();
  };
  const renderLibraryItems = (items) => {
    const target = $('library-items');
    target.textContent = '';
    libraryStop();
    librarySelection.clear();
    updateExportButton();
    if (!items.length) {
      const empty = document.createElement('p');
      empty.className = 'empty-state';
      empty.textContent = 'Keine Aufnahmen gefunden.';
      target.append(empty);
      return;
    }
    items.forEach((item) => {
      const card = document.createElement('article');
      card.className = 'card library-card';
      const select = document.createElement('input');
      select.type = 'checkbox';
      select.className = 'library-select';
      const exportable = (item.formats_present || []).length > 0;
      select.disabled = !exportable;
      select.title = exportable ? 'Für Export auswählen' : 'Kein Transkript vorhanden';
      select.addEventListener('change', () => {
        if (select.checked) librarySelection.add(item.item_id);
        else librarySelection.delete(item.item_id);
        updateExportButton();
      });
      const playButton = document.createElement('button');
      playButton.type = 'button';
      playButton.className = 'library-play';
      playButton.title = 'Anhören';
      playButton.textContent = '▶';
      const waveWrap = document.createElement('div');
      waveWrap.className = 'library-wave-wrap';
      const canvas = document.createElement('canvas');
      canvas.className = 'library-wave';
      const playhead = document.createElement('div');
      playhead.className = 'library-playhead';
      playhead.hidden = true;
      waveWrap.append(canvas, playhead);
      const controls = { playButton, playhead, waveWrap };
      playButton.addEventListener('click', () => {
        const audio = libraryActivate(item, controls);
        if (audio.paused) audio.play().catch(() => {}); else audio.pause();
      });
      const seekFromPointer = (event) => {
        const audio = libraryAudioEl();
        const rect = waveWrap.getBoundingClientRect();
        if (!rect.width || !Number.isFinite(audio.duration) || audio.duration <= 0) return;
        const frac = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
        audio.currentTime = frac * audio.duration;
        playhead.style.left = `${frac * 100}%`;
      };
      waveWrap.addEventListener('pointerdown', (event) => {
        const audio = libraryActivate(item, controls);
        // play() synchron in der Geste (WebKitGTK-Autoplay-Policy).
        if (audio.paused) audio.play().catch(() => {});
        if (audio.readyState >= 1) seekFromPointer(event);
        else audio.addEventListener('loadedmetadata', () => seekFromPointer(event), { once: true });
        waveWrap.setPointerCapture(event.pointerId);
        const move = (moveEvent) => seekFromPointer(moveEvent);
        const up = () => {
          waveWrap.removeEventListener('pointermove', move);
          waveWrap.removeEventListener('pointerup', up);
          waveWrap.removeEventListener('pointercancel', up);
        };
        waveWrap.addEventListener('pointermove', move);
        waveWrap.addEventListener('pointerup', up);
        waveWrap.addEventListener('pointercancel', up);
      });
      const body = document.createElement('div');
      body.className = 'library-body';
      const titleRow = document.createElement('div');
      titleRow.className = 'library-title';
      const title = document.createElement('strong');
      title.textContent = item.name;
      const renameButton = document.createElement('button');
      renameButton.type = 'button';
      renameButton.className = 'library-rename';
      renameButton.title = 'Umbenennen';
      renameButton.textContent = '✏️';
      renameButton.addEventListener('click', () => {
        const stem = item.name.replace(/\.[^.]+$/, '');
        const editor = document.createElement('input');
        editor.type = 'text';
        editor.value = stem;
        editor.className = 'library-rename-input';
        titleRow.replaceChildren(editor);
        editor.focus();
        editor.select();
        let done = false;
        const finish = async (commit) => {
          if (done) return;
          done = true;
          const value = editor.value.trim();
          if (!commit || !value || value === stem) {
            titleRow.replaceChildren(title, renameButton);
            return;
          }
          const result = await api.rename_library_item(item.item_id, value);
          if (!result.ok) {
            setViewStatus('library-status', result.error || 'Umbenennen fehlgeschlagen.', true);
            titleRow.replaceChildren(title, renameButton);
            return;
          }
          setViewStatus('library-status', `Umbenannt zu „${result.name}". Liste wird aktualisiert …`);
          $('scan-library').click();
        };
        editor.addEventListener('keydown', (event) => {
          if (event.key === 'Enter') finish(true);
          if (event.key === 'Escape') finish(false);
        });
        editor.addEventListener('blur', () => finish(true));
      });
      titleRow.append(title, renameButton);
      const detail = document.createElement('span');
      const date = item.started_at ? new Date(item.started_at).toLocaleString('de-DE') : 'Datum unbekannt';
      detail.textContent = `${date} · ${formatTime((Number(item.duration_ms) || 0) / 1000)} · ${item.folder}`;
      const badges = document.createElement('div');
      badges.className = 'library-badges';
      (item.formats_present || []).forEach((format) => {
        const badge = document.createElement('span');
        badge.textContent = format.toUpperCase();
        badges.append(badge);
      });
      const reviewBadge = document.createElement('span');
      reviewBadge.textContent = item.has_review ? 'Review ✓' : 'Kein Review';
      badges.append(reviewBadge);
      const markerBadge = document.createElement('span');
      markerBadge.textContent = `⚑ ${item.marker_count || 0} Marker`;
      badges.append(markerBadge);
      body.append(titleRow, detail, badges);
      const actions = document.createElement('div');
      actions.className = 'library-actions';
      if (item.has_review) {
        const review = document.createElement('button');
        review.type = 'button';
        review.textContent = 'Review öffnen';
        review.addEventListener('click', async () => {
          const result = await api.open_library_review(item.item_id);
          if (!result.ok) {
            setViewStatus('library-status', result.error || 'Review konnte nicht geladen werden.', true);
            return;
          }
          acceptReviewResult(result);
          activateView('speakers');
        });
        actions.append(review);
      }
      const transcribe = document.createElement('button');
      transcribe.type = 'button';
      transcribe.className = 'primary';
      transcribe.textContent = 'Transkribieren';
      transcribe.addEventListener('click', async () => {
        const result = await api.prepare_library_transcription(item.item_id);
        if (!result.ok) {
          setViewStatus('library-status', result.error || 'Aufnahme nicht mehr verfügbar.', true);
          return;
        }
        setPath('audio', result.audio_path);
        setPath('marker', result.marker_path);
        activateView('transcribe');
        setStatus('Aufnahme aus der Bibliothek vorbereitet.');
      });
      actions.append(transcribe);
      card.append(select, playButton, waveWrap, body, actions);
      target.append(card);
      requestAnimationFrame(() => renderMiniWave(canvas, item.peaks34 || []));
    });
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
    if (api) api.set_theme(currentTheme);
  });
  document.querySelectorAll('.nav-item').forEach((button) => button.addEventListener('click', async () => {
    const current = document.querySelector('.view.active');
    if (current && current.id === 'speakers' && button.dataset.view !== 'speakers' && api) {
      await api.stop_playback();
    }
    if (current && current.id === 'library' && button.dataset.view !== 'library') {
      libraryStop();
    }
    document.querySelectorAll('.nav-item').forEach((item) => item.classList.toggle('active', item === button));
    document.querySelectorAll('.view').forEach((view) => view.classList.toggle('active', view.id === button.dataset.view));
    if (button.dataset.view === 'speakers') {
      requestAnimationFrame(() => {
        waveCache = null;
        renderWaveform();
      });
    }
    if (activeBatchId && button.dataset.view !== 'batch') {
      setStatus('Der Batch läuft im Hintergrund weiter. Status und Abbruch bleiben in der Batch-Ansicht verfügbar.');
    }
  }));
  document.querySelectorAll('.open-settings').forEach((button) => {
    button.addEventListener('click', () => activateView('settings'));
  });
  // Alle Transkriptionsoptionen sofort appweit persistieren.
  const persistGlobalOptions = () => {
    renderGlobalSettingsSummary();
    if (!api) return;
    const s = formSettings();
    api.save_output_options(s).then((result) => {
      setViewStatus(
        'settings-status',
        result.ok
          ? 'Gespeichert. Einzeltranskription und Batch verwenden diese Optionen beim nächsten Lauf.'
          : result.error || 'Optionen konnten nicht gespeichert werden.',
        !result.ok,
      );
    }).catch(() => {
      setViewStatus('settings-status', 'Optionen konnten nicht gespeichert werden.', true);
    });
  };
  document.querySelectorAll(
    '#backend, #language, #task, #whisperx-model, #performance-profile, '
    + '#min-speakers, #max-speakers, input[name="format"], #keep-wav, #verbose, '
    + '#no-diarize, #auto-markers, #colocate, #voice-profiles',
  ).forEach((input) => input.addEventListener('change', () => {
    if (input.id === 'backend') toggleBackend();
    if (input.id === 'colocate') toggleColocate();
    if (input.id === 'no-diarize') toggleVoiceProfiles();
    persistGlobalOptions();
  }));
  [['audio', 'pick-audio'], ['marker', 'pick-marker'], ['output', 'pick-output'], ['model', 'pick-model']]
    .forEach(([kind, id]) => $(id).addEventListener('click', async () => {
      const result = await api[`pick_${kind}`]();
      if (result && result.ok) {
        setPath(kind, result.path);
        if (kind === 'model') renderGlobalSettingsSummary();
      }
    }));
  $('open-output').addEventListener('click', async () => {
    const result = await api.open_output_dir($('colocate').checked);
    if (result && !result.ok) {
      setViewStatus('settings-status', result.error || 'Ordner konnte nicht geöffnet werden.', true);
    }
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
  const acceptReviewResult = (result) => {
    reviewId = result.review_id;
    reviewSegments = result.segments || [];
    reviewBaseName = result.base_name || '';
    $('review-name').value = reviewBaseName;
    $('review-name').readOnly = result.rename_allowed === false;
    $('review-rename-hint').hidden = result.rename_allowed !== false;
    loadReviewAudio(
      result.audio_url, result.bookmarks, result.sidecar_peaks, result.sidecar_duration_ms,
    );
    renderSpeakers(result.speakers || []);
    setViewStatus('speaker-status', `${(result.speakers || []).length} Sprecher geladen.`);
    requestReviewWaveform();
  };
  $('pick-review').addEventListener('click', async () => {
    const result = await api.pick_review_file();
    if (!result || result.cancelled) return;
    if (!result.ok) {
      setViewStatus('speaker-status', result.error || 'Review konnte nicht geladen werden.', true);
      return;
    }
    acceptReviewResult(result);
  });
  const renameReview = async () => {
    const input = $('review-name');
    const newBase = input.value.trim();
    if (!reviewId || !newBase || newBase === reviewBaseName) {
      input.value = reviewBaseName;
      return;
    }
    const result = await api.rename_review(reviewId, newBase);
    if (!result.ok) {
      input.value = reviewBaseName;
      setViewStatus('speaker-status', result.error || 'Umbenennen fehlgeschlagen.', true);
      return;
    }
    reviewBaseName = result.base_name;
    input.value = reviewBaseName;
    // Audio-Pfad hat sich geändert: src tauschen, Position/Zustand erhalten.
    const audio = audioEl();
    if (result.audio_url && audio.src !== result.audio_url) {
      const time = audio.currentTime;
      const wasPlaying = !audio.paused && !audio.ended;
      audio.src = result.audio_url;
      audio.load();
      audio.addEventListener('loadedmetadata', () => {
        audio.currentTime = time;
        if (wasPlaying) audio.play().catch(() => {});
      }, { once: true });
      waveformResult = null;
      waveformRequest = null;
      waveCache = null;
      mediaMetadataReady = false;
      mediaFailed = false;
      $('player-bar').classList.add('waveform-loading');
      $('player-bar').classList.remove('waveform-ready');
      requestReviewWaveform();
    }
    setViewStatus('speaker-status', `Dateien umbenannt zu „${result.base_name}".`);
  };
  $('review-name').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') event.target.blur();
    if (event.key === 'Escape') { event.target.value = reviewBaseName; event.target.blur(); }
  });
  $('review-name').addEventListener('blur', () => { renameReview(); });
  $('stop-playback').addEventListener('click', () => {
    const audio = audioEl();
    audio.pause();
    audio.currentTime = 0;
    setViewStatus('speaker-status', 'Wiedergabe gestoppt.');
  });
  // Bibliotheks-Player-Verdrahtung (einmalig)
  (() => {
    const audio = libraryAudioEl();
    audio.addEventListener('timeupdate', () => {
      if (!libraryActive || !Number.isFinite(audio.duration) || audio.duration <= 0) return;
      libraryActive.playhead.style.left = `${(audio.currentTime / audio.duration) * 100}%`;
    });
    audio.addEventListener('play', () => { if (libraryActive) libraryActive.playButton.textContent = '⏸'; });
    audio.addEventListener('pause', () => { if (libraryActive) libraryActive.playButton.textContent = '▶'; });
    audio.addEventListener('ended', () => { if (libraryActive) libraryActive.playButton.textContent = '▶'; });
    audio.addEventListener('error', () => {
      if (!audio.src) return;
      setViewStatus('library-status', 'Dieses Audioformat kann nicht abgespielt werden.', true);
      libraryStop();
    });
  })();

  // Audio-Player-Verdrahtung (einmalig)
  (() => {
    const audio = audioEl();
    audio.addEventListener('loadedmetadata', () => {
      mediaMetadataReady = true;
      mediaFailed = false;
      $('player-play').disabled = false;
      $('player-bar').removeAttribute('aria-disabled');
      $('player-duration').textContent = formatTime(audio.duration);
      renderPlayerMarkers();
      tryRenderWaveform();
    });
    audio.addEventListener('error', () => {
      if (!reviewId || !audio.src) return;
      mediaFailed = true;
      mediaMetadataReady = false;
      audio.pause();
      $('player-play').disabled = true;
      $('player-bar').setAttribute('aria-disabled', 'true');
      setViewStatus(
        'speaker-status',
        'Das Audioformat kann vom Player nicht wiedergegeben werden; die Waveform bleibt als Vorschau sichtbar.',
      );
      if (waveformResult && waveformResult.duration > 0) {
        $('player-duration').textContent = formatTime(waveformResult.duration);
      }
      tryRenderWaveform();
    });
    audio.addEventListener('timeupdate', updatePlayerUI);
    audio.addEventListener('play', () => { $('player-play').textContent = '⏸'; });
    audio.addEventListener('pause', () => { $('player-play').textContent = '▶'; });
    audio.addEventListener('ended', () => { $('player-play').textContent = '▶'; });
    $('player-play').addEventListener('click', () => {
      if (!audio.src || mediaFailed) return;
      if (audio.paused) audio.play(); else audio.pause();
    });
    const seekFromEvent = (event) => {
      const rect = $('player-bar').getBoundingClientRect();
      if (!mediaFailed && rect.width > 0) seekToFraction((event.clientX - rect.left) / rect.width);
    };
    $('player-bar').addEventListener('click', seekFromEvent);
    $('player-bar').addEventListener('keydown', (event) => {
      if (mediaFailed) return;
      const target = window.BortWave.keyboardSeekTarget(
        event.key, audio.currentTime, audio.duration, 5,
      );
      if (target === null) return;
      event.preventDefault();
      audio.currentTime = target;
      updatePlayerUI();
    });
    if (typeof ResizeObserver !== 'undefined') {
      const observer = new ResizeObserver(() => {
        waveCache = null;
        renderWaveform();
      });
      observer.observe($('player-bar'));
    }
  })();
  $('speaker-name-input').addEventListener('input', (event) => {
    if (!activeSpeakerId) return;
    updateSpeakerName(activeSpeakerId, event.target.value, event.target);
  });
  $('speaker-saved-name').addEventListener('change', (event) => {
    if (!activeSpeakerId || !event.target.value) return;
    updateSpeakerName(activeSpeakerId, event.target.value);
  });
  $('speaker-suggestion').addEventListener('click', () => {
    const speaker = reviewSpeakers.find((item) => item.id === activeSpeakerId);
    const suggestion = (speaker?.suggestions || [])[0];
    if (!speaker || !suggestion) return;
    assignActiveSpeakerName(suggestion.name);
  });
  $('play-selected-speaker').addEventListener('click', () => {
    if (!activeSpeakerId) return;
    const label = speakerDraftNames.get(activeSpeakerId)?.trim() || activeSpeakerId;
    playFromSpeaker(activeSpeakerId, label);
  });
  $('show-selected-speaker').addEventListener('click', () => {
    if (activeSpeakerId) scrollTranscriptToSpeaker(activeSpeakerId);
  });
  $('speaker-rows').addEventListener('keydown', (event) => {
    if (!['ArrowDown', 'ArrowRight', 'ArrowUp', 'ArrowLeft'].includes(event.key)) return;
    const choices = [...document.querySelectorAll('#speaker-rows .speaker-choice')];
    const index = choices.indexOf(document.activeElement);
    if (index < 0 || !choices.length) return;
    event.preventDefault();
    const direction = ['ArrowDown', 'ArrowRight'].includes(event.key) ? 1 : -1;
    const next = choices[(index + direction + choices.length) % choices.length];
    next.focus();
    selectSpeaker(next.dataset.speakerId);
  });
  const speakerApplyButtons = () => [$('apply-speakers'), $('apply-speakers-floating')];
  const resetSpeakerApplyLabels = () => {
    $('apply-speakers').textContent = 'Anwenden';
    $('apply-speakers-floating').textContent = '✓ Änderungen anwenden';
    $('apply-speakers-floating').classList.remove('save-confirmed', 'save-error');
  };
  const showSpeakerApplyFeedback = (message, className) => {
    clearTimeout(speakerApplyFeedbackTimer);
    const floating = $('apply-speakers-floating');
    floating.textContent = message;
    floating.classList.remove('save-confirmed', 'save-error');
    floating.classList.add(className);
    speakerApplyFeedbackTimer = setTimeout(resetSpeakerApplyLabels, 2200);
  };
  const applySpeakerRenames = async () => {
    if (!reviewId || speakerApplyButtons().some((button) => button.disabled)) return;
    clearTimeout(speakerApplyFeedbackTimer);
    speakerApplyButtons().forEach((button) => {
      button.disabled = true;
      button.textContent = 'Speichert …';
    });
    try {
      const result = await api.apply_speaker_rename(reviewId, currentSpeakerNames());
      if (!result.ok) {
        const message = result.error || 'Änderungen konnten nicht gespeichert werden.';
        setViewStatus('speaker-status', message, true);
        showSpeakerApplyFeedback('Speichern fehlgeschlagen', 'save-error');
        return;
      }
      renderSpeakers(result.speakers || []);
      setViewStatus('speaker-status', `${result.files_rewritten} Dateien neu geschrieben.`);
      showSpeakerApplyFeedback('✓ Gespeichert', 'save-confirmed');
    } catch (error) {
      setViewStatus('speaker-status', error?.message || 'Änderungen konnten nicht gespeichert werden.', true);
      showSpeakerApplyFeedback('Speichern fehlgeschlagen', 'save-error');
    } finally {
      speakerApplyButtons().forEach((button) => { button.disabled = false; });
      $('apply-speakers').textContent = 'Anwenden';
    }
  };
  $('apply-speakers').addEventListener('click', applySpeakerRenames);
  $('apply-speakers-floating').addEventListener('click', applySpeakerRenames);
  $('remember-speakers').addEventListener('click', async () => {
    const result = await api.save_voice_profile_names(currentSpeakerNames(), reviewId);
    if (!result.ok) {
      setViewStatus('speaker-status', result.error || 'Namen konnten nicht gespeichert werden.', true);
      return;
    }
    applyVoiceCatalog(result.voice_catalog || {});
    const voiceprints = result.voiceprints_saved
      ? `, ${result.voiceprints_saved} Stimmprofile aktualisiert`
      : '';
    setViewStatus('speaker-status', `${result.saved.length} Namen lokal gespeichert${voiceprints}.`);
  });
  $('pick-watch').addEventListener('click', async () => {
    const result = await api.pick_watch_dir();
    if (result && result.ok) $('watch-path').value = result.path || '';
  });
  $('scan-batch').addEventListener('click', async () => {
    setViewStatus('batch-status', 'Ordner wird gescannt …');
    const result = await api.scan_batch(formSettings());
    if (!result.ok) {
      setViewStatus('batch-status', result.error || 'Scan fehlgeschlagen.', true);
      return;
    }
    pendingBatchItems = result.items || [];
    renderBatchItems(pendingBatchItems);
    $('unstable-count').textContent = `${result.skipped_unstable || 0} noch instabile Dateien übersprungen.`;
    setViewStatus('batch-status', `${pendingBatchItems.length} ausstehende Dateien gefunden.`);
  });
  $('pick-library').addEventListener('click', async () => {
    const result = await api.pick_library_dir();
    if (result && result.ok) $('library-path').value = result.path || '';
  });
  $('library-stop').addEventListener('click', async () => {
    // Stoppt ALLES: Bibliotheks-Player, Sprecher-Audio und Backend-Player.
    libraryStop();
    const speakerAudio = audioEl();
    speakerAudio.pause();
    if (api) await api.stop_playback();
    setViewStatus('library-status', 'Alle Wiedergaben gestoppt.');
  });
  $('pick-export').addEventListener('click', async () => {
    const result = await api.pick_export_dir();
    if (result && result.ok) $('export-path').value = result.path || '';
  });
  $('open-export').addEventListener('click', async () => {
    const result = await api.open_export_dir();
    if (result && !result.ok) setViewStatus('library-status', result.error || 'Ordner konnte nicht geöffnet werden.', true);
  });
  $('export-selection').addEventListener('click', async () => {
    const result = await api.export_library_zip([...librarySelection]);
    if (!result.ok) {
      setViewStatus('library-status', result.error || 'Export fehlgeschlagen.', true);
      return;
    }
    const skipped = result.skipped ? ` (${result.skipped} ohne Transkript übersprungen)` : '';
    setViewStatus('library-status', `${result.file_count} Dateien exportiert nach ${result.zip_path}${skipped}.`);
  });
  $('save-mail-password').addEventListener('click', async () => {
    const sender = $('mail-from').value.trim();
    const password = $('mail-password').value;
    const result = await api.save_mail_password(sender, password);
    if (!result.ok) {
      setViewStatus('library-status', result.error || 'Passwort konnte nicht gespeichert werden.', true);
      return;
    }
    $('mail-password').value = '';
    mailPasswordStored = true;
    updateMailPasswordRow();
    setViewStatus('library-status', 'App-Passwort im Schlüsselbund gespeichert.');
  });
  $('export-send').addEventListener('click', async () => {
    const recipient = $('mail-to').value.trim();
    const sender = $('mail-from').value.trim();
    const button = $('export-send');
    button.disabled = true;
    setViewStatus('library-status', 'Export läuft, Mail wird gesendet …');
    try {
      const result = await api.export_and_send([...librarySelection], recipient, sender);
      if (!result.ok) {
        if (result.needs_password) {
          mailPasswordStored = false;
          updateMailPasswordRow();
        }
        setViewStatus('library-status', result.error || 'Versand fehlgeschlagen.', true);
        return;
      }
      setViewStatus('library-status', `${result.file_count} Dateien an ${result.recipient} gesendet (Zip: ${result.zip_path}).`);
    } finally {
      button.disabled = librarySelection.size === 0;
    }
  });
  $('scan-library').addEventListener('click', async () => {
    setViewStatus('library-status', 'Bibliothek wird gescannt …');
    const result = await api.scan_library();
    if (!result.ok) {
      setViewStatus('library-status', result.error || 'Scan fehlgeschlagen.', true);
      return;
    }
    renderLibraryItems(result.items || []);
    $('library-summary').textContent = `${result.scanned} Einträge untersucht · ${result.warning_count} Warnungen${result.truncated ? ' · Ergebnis begrenzt' : ''}`;
    setViewStatus('library-status', `${(result.items || []).length} Aufnahmen gefunden.`);
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
      if (initial.ok) {
        if (initial.theme) {
          currentTheme = initial.theme;
          applyTheme(currentTheme);
          try { localStorage.setItem('bort-theme', currentTheme); } catch (_) { /* egal */ }
        }
        applyInitialState(initial);
        api.get_mail_state().then(applyMailState).catch(() => {});
      } else {
        setStatus(initial.error || 'Initialisierung fehlgeschlagen.', true);
      }
    } catch (error) {
      setStatus(`Bridge nicht verfügbar: ${error}`, true);
    }
  });
})();

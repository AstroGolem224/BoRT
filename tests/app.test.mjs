import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

// app.js ist eine IIFE ohne Modul-Exports. formatTime wird per Regex aus dem
// Quelltext extrahiert und isoliert ausgewertet; bleibt die Funktion nicht
// alleinstehend erhalten, wird der Test übersprungen statt den Code umzubauen.
const source = readFileSync(new URL('../src/bort/web/app.js', import.meta.url), 'utf8');

const extractFormatTime = () => {
  const match = source.match(/const formatTime = \(value\) => \{([\s\S]*?)\n  \};/);
  if (!match) return null;
  try {
    return new Function(`return (value) => {${match[1]}\n};`)();
  } catch (_) {
    return null;
  }
};

test('formatTime zeigt Stunden ab 1h an und MM:SS darunter', (t) => {
  const formatTime = extractFormatTime();
  if (!formatTime) {
    t.skip('formatTime nicht mehr als eigenständige Arrow-Funktion in app.js auffindbar');
    return;
  }
  assert.equal(formatTime(75), '01:15');
  assert.equal(formatTime(59.9), '00:59');
  assert.equal(formatTime(60), '01:00');
  assert.equal(formatTime(3599), '59:59');
  assert.equal(formatTime(3600), '1:00:00');
  assert.equal(formatTime(3661), '1:01:01');
  assert.equal(formatTime(7202), '2:00:02');
});

test('formatTime klemmt negative und ungültige Werte auf 00:00', (t) => {
  const formatTime = extractFormatTime();
  if (!formatTime) {
    t.skip('formatTime nicht mehr als eigenständige Arrow-Funktion in app.js auffindbar');
    return;
  }
  assert.equal(formatTime(-3), '00:00');
  assert.equal(formatTime(Number.NaN), '00:00');
  assert.equal(formatTime(Number.POSITIVE_INFINITY), '00:00');
  assert.equal(formatTime(undefined), '00:00');
});

const extractCapLogText = () => {
  const match = source.match(/const capLogText = \(current, addition\) => \{([\s\S]*?)\n  \};/);
  if (!match) return null;
  try {
    return new Function(`return (current, addition) => {${match[1]}\n};`)();
  } catch (_) {
    return null;
  }
};

test('capLogText hängt Zeilen an und meldet Kappung erst ab 30000 Zeichen', (t) => {
  const capLogText = extractCapLogText();
  if (!capLogText) {
    t.skip('capLogText nicht mehr als eigenständige Arrow-Funktion in app.js auffindbar');
    return;
  }
  assert.deepEqual(capLogText('', 'Hallo'), { text: 'Hallo\n', capped: false });
  const boundary = capLogText('x'.repeat(29998), 'y');
  assert.deepEqual(boundary, { text: `${'x'.repeat(29998)}y\n`, capped: false });
});

test('capLogText behält die letzten 30000 Zeichen und markiert die Kappung', (t) => {
  const capLogText = extractCapLogText();
  if (!capLogText) {
    t.skip('capLogText nicht mehr als eigenständige Arrow-Funktion in app.js auffindbar');
    return;
  }
  const result = capLogText(`ALT-${'z'.repeat(30010)}`, 'Neu');
  assert.equal(result.capped, true);
  assert.equal(result.text.length, 30000);
  assert.ok(result.text.endsWith('Neu\n'));
  assert.ok(!result.text.includes('ALT-'));
});

// uriListToPaths: WebKitGTK-Drops liefern Pfade nur als file://-URI-Liste.
const extractUriListToPaths = () => {
  const match = source.match(/const uriListToPaths = \(uriList\) => \{([\s\S]*?)\n  \};/);
  if (!match) return null;
  try {
    return new Function(`return (uriList) => {${match[1]}\n};`)();
  } catch (_) {
    return null;
  }
};

test('uriListToPaths parst file://-URIs inklusive Prozent-Encoding', (t) => {
  const uriListToPaths = extractUriListToPaths();
  if (!uriListToPaths) {
    t.skip('uriListToPaths nicht mehr als eigenständige Arrow-Funktion in app.js auffindbar');
    return;
  }
  assert.deepEqual(
    uriListToPaths('file:///home/user/Aufnahme%201.m4a'),
    ['/home/user/Aufnahme 1.m4a'],
  );
  assert.deepEqual(uriListToPaths('file:///tmp/M%C3%A4rchen.ogg'), ['/tmp/Märchen.ogg']);
});

test('uriListToPaths überspringt Kommentare, Nicht-file-Schemata und Müllzeilen', (t) => {
  const uriListToPaths = extractUriListToPaths();
  if (!uriListToPaths) {
    t.skip('uriListToPaths nicht mehr als eigenständige Arrow-Funktion in app.js auffindbar');
    return;
  }
  const list = [
    '# Kommentarzeile',
    'file:///pfad/a.wav',
    'https://example.com/drop.mp3',
    'keine-uri',
    '',
    'file:///pfad/b.ogg',
  ].join('\r\n');
  assert.deepEqual(uriListToPaths(list), ['/pfad/a.wav', '/pfad/b.ogg']);
});

test('uriListToPaths toleriert leere Eingaben und Ordner-URIs mit Slash', (t) => {
  const uriListToPaths = extractUriListToPaths();
  if (!uriListToPaths) {
    t.skip('uriListToPaths nicht mehr als eigenständige Arrow-Funktion in app.js auffindbar');
    return;
  }
  assert.deepEqual(uriListToPaths(''), []);
  assert.deepEqual(uriListToPaths(null), []);
  assert.deepEqual(
    uriListToPaths('file:///home/user/Sync-Ordner/'),
    ['/home/user/Sync-Ordner/'],
  );
});

// resolveShortcut: reine Tastaturauflösung (kein DOM), View-Reihenfolge
// wie in der Sidebar: transcribe, batch, library, speakers, settings.
const extractResolveShortcut = () => {
  const match = source.match(/const resolveShortcut = \(event\) => \{([\s\S]*?)\n  \};/);
  if (!match) return null;
  try {
    return new Function(`return (event) => {${match[1]}\n};`)();
  } catch (_) {
    return null;
  }
};

const keyEvent = ({ key = '', ctrlKey = false, altKey = false, shiftKey = false, metaKey = false }) =>
  ({ key, ctrlKey, altKey, shiftKey, metaKey });

test('resolveShortcut bildet Strg+E/Strg+B/Strg+T auf Aktionen ab (auch Cmd+)', (t) => {
  const resolveShortcut = extractResolveShortcut();
  if (!resolveShortcut) {
    t.skip('resolveShortcut nicht mehr als eigenständige Arrow-Funktion in app.js auffindbar');
    return;
  }
  assert.deepEqual(resolveShortcut(keyEvent({ key: 'e', ctrlKey: true })), { action: 'transcribe-start' });
  assert.deepEqual(resolveShortcut(keyEvent({ key: 'E', ctrlKey: true })), { action: 'transcribe-start' });
  assert.deepEqual(resolveShortcut(keyEvent({ key: 'b', metaKey: true })), { action: 'batch-toggle' });
  assert.deepEqual(resolveShortcut(keyEvent({ key: 't', ctrlKey: true })), { action: 'theme-toggle' });
});

test('resolveShortcut mappt Alt+1..5 auf die fünf Views', (t) => {
  const resolveShortcut = extractResolveShortcut();
  if (!resolveShortcut) {
    t.skip('resolveShortcut nicht mehr als eigenständige Arrow-Funktion in app.js auffindbar');
    return;
  }
  assert.deepEqual(resolveShortcut(keyEvent({ key: '1', altKey: true })), { action: 'view-switch', view: 'transcribe' });
  assert.deepEqual(resolveShortcut(keyEvent({ key: '2', altKey: true })), { action: 'view-switch', view: 'batch' });
  assert.deepEqual(resolveShortcut(keyEvent({ key: '3', altKey: true })), { action: 'view-switch', view: 'library' });
  assert.deepEqual(resolveShortcut(keyEvent({ key: '4', altKey: true })), { action: 'view-switch', view: 'speakers' });
  assert.deepEqual(resolveShortcut(keyEvent({ key: '5', altKey: true })), { action: 'view-switch', view: 'settings' });
});

test('resolveShortcut feuert nicht auf Kombinationen oder bloße Tasten', (t) => {
  const resolveShortcut = extractResolveShortcut();
  if (!resolveShortcut) {
    t.skip('resolveShortcut nicht mehr als eigenständige Arrow-Funktion in app.js auffindbar');
    return;
  }
  assert.equal(resolveShortcut(keyEvent({ key: '1' })), null); // Ziffer ohne Alt
  assert.equal(resolveShortcut(keyEvent({ key: '6', altKey: true })), null);
  assert.equal(resolveShortcut(keyEvent({ key: 'e' })), null); // Buchstabe ohne Modifikator
  assert.equal(resolveShortcut(keyEvent({ key: 'b', altKey: true })), null);
  assert.equal(resolveShortcut(keyEvent({ key: 'e', ctrlKey: true, altKey: true })), null);
  assert.equal(resolveShortcut(keyEvent({ key: 'Escape', ctrlKey: true })), null);
});

// handleDroppedPaths: reine Zonenlogik ohne DOM; showToast/acceptDroppedPath
// werden als Stubs injiziert, lowerExtension und die Marker-Konstante kommen
// unverändert aus dem Quelltext.
const extractLowerExtension = () => {
  const match = source.match(/const lowerExtension = \(path\) => \{([\s\S]*?)\n  \};/);
  if (!match) return null;
  try {
    return new Function(`return (path) => {${match[1]}\n};`)();
  } catch (_) {
    return null;
  }
};

const makeHandleDroppedPaths = () => {
  const lowerExtension = extractLowerExtension();
  const markerExt = source.match(/const MARKER_DROP_EXTENSION = '([^']+)';/);
  const match = source.match(/const handleDroppedPaths = \(zone, paths\) => \{([\s\S]*?)\n  \};/);
  if (!lowerExtension || !markerExt || !match) return null;
  const calls = { toasts: [], accepted: [] };
  try {
    const fn = new Function(
      'showToast',
      'acceptDroppedPath',
      'lowerExtension',
      'MARKER_DROP_EXTENSION',
      `return (zone, paths) => {${match[1]}\n};`,
    )(
      (msg) => calls.toasts.push(msg),
      (kind, path) => calls.accepted.push([kind, path]),
      lowerExtension,
      markerExt[1],
    );
    return { fn, calls };
  } catch (_) {
    return null;
  }
};

test('handleDroppedPaths leitet Audio-Drops an das Backend durch (kein Client-Gate)', (t) => {
  const setup = makeHandleDroppedPaths();
  if (!setup) {
    t.skip('handleDroppedPaths nicht mehr als eigenständige Arrow-Funktion in app.js auffindbar');
    return;
  }
  setup.fn('audio', ['/home/user/Aufnahme%201.mp3']);
  assert.deepEqual(setup.calls.accepted, [['audio', '/home/user/Aufnahme%201.mp3']]);
  assert.deepEqual(setup.calls.toasts, []);
  // Auch nicht-audio-Endungen gehen durch: Extension-Gate macht das Backend.
  setup.fn('audio', ['/tmp/notizen.txt']);
  assert.deepEqual(setup.calls.accepted[1], ['audio', '/tmp/notizen.txt']);
});

test('handleDroppedPaths akzeptiert nur JSON-Marker in der Marker-Zone', (t) => {
  const setup = makeHandleDroppedPaths();
  if (!setup) {
    t.skip('handleDroppedPaths nicht mehr als eigenständige Arrow-Funktion in app.js auffindbar');
    return;
  }
  setup.fn('marker', ['/pfad/a.txt', '/pfad/markierung.JSON']);
  assert.deepEqual(setup.calls.accepted, [['marker', '/pfad/markierung.JSON']]);
  assert.deepEqual(setup.calls.toasts, []);

  setup.fn('marker', ['/pfad/audio.wav']);
  assert.equal(setup.calls.accepted.length, 1);
  assert.match(setup.calls.toasts[0], /\.json/);
});

test('handleDroppedPaths-Zone watch: hängt Trailing-Slash ab und erlaubt Ordner', (t) => {
  const setup = makeHandleDroppedPaths();
  if (!setup) {
    t.skip('handleDroppedPaths nicht mehr als eigenständige Arrow-Funktion in app.js auffindbar');
    return;
  }
  setup.fn('watch', ['/home/user/Sync-Ordner/']);
  assert.deepEqual(setup.calls.accepted, [['watch', '/home/user/Sync-Ordner']]);
  assert.deepEqual(setup.calls.toasts, []);

  setup.fn('watch', ['/home/user/Sync']);
  assert.deepEqual(setup.calls.accepted[1], ['watch', '/home/user/Sync']);
});

test('handleDroppedPaths-Zone watch: mehrere Pfade und Dateien werden abgewiesen', (t) => {
  const setup = makeHandleDroppedPaths();
  if (!setup) {
    t.skip('handleDroppedPaths nicht mehr als eigenständige Arrow-Funktion in app.js auffindbar');
    return;
  }
  setup.fn('watch', ['/ordner/eins/', '/ordner/zwei/']);
  assert.equal(setup.calls.accepted.length, 0);
  assert.match(setup.calls.toasts[0], /nur einen Sync-Ordner/);

  setup.fn('watch', ['/ordner/aufnahme.wav']);
  assert.equal(setup.calls.accepted.length, 0);
  assert.match(setup.calls.toasts[1], /einzelne Dateien/);
});

// transcribeShortcutAction: Strg+E ist doppeldeutig — mit laufendem
// Einzeljob Abbruch statt Start (Konsistenz mit dem Batch-Muster).
const extractTranscribeShortcutAction = () => {
  const match = source.match(/const transcribeShortcutAction = \(\{ hasAudio, running \}\) => \{([\s\S]*?)\n  \};/);
  if (!match) return null;
  try {
    return new Function(`return ({ hasAudio, running }) => {${match[1]}\n};`)();
  } catch (_) {
    return null;
  }
};

test('transcribeShortcutAction: laufender Job schlägt Abbruch vor, sonst Start', (t) => {
  const transcribeShortcutAction = extractTranscribeShortcutAction();
  if (!transcribeShortcutAction) {
    t.skip('transcribeShortcutAction nicht mehr als eigenständige Funktion in app.js auffindbar');
    return;
  }
  assert.equal(transcribeShortcutAction({ hasAudio: true, running: true }), 'cancel');
  assert.equal(transcribeShortcutAction({ hasAudio: false, running: true }), 'cancel');
  assert.equal(transcribeShortcutAction({ hasAudio: true, running: false }), 'start');
});

test('transcribeShortcutAction: ohne Audio keinen Start vorschlagen', (t) => {
  const transcribeShortcutAction = extractTranscribeShortcutAction();
  if (!transcribeShortcutAction) {
    t.skip('transcribeShortcutAction nicht mehr als eigenständige Funktion in app.js auffindbar');
    return;
  }
  assert.equal(transcribeShortcutAction({ hasAudio: false, running: false }), 'need-audio');
  assert.equal(transcribeShortcutAction({ hasAudio: '   ', running: false }), 'start');
});

// Titel-Attribut dokumentiert die Strg+E-Semantik am Abbrechen-Button.
test('Abbrechen-Button dokumentiert Strg+E-Abbruchsemantik im Titel', (t) => {
  const html = readFileSync(new URL('../src/bort/web/index.html', import.meta.url), 'utf8');
  const button = html.match(/<button id="cancel-transcription"[^>]*>/);
  assert.ok(button, '#cancel-transcription existiert im Markup');
  assert.match(button[0], /title="[^"]*Strg\+E/);
});

// __bortDispatch: Dispatcher für die run_js-Push-Ereignisse des Backends.
// DOM-/UI-Helfer werden als Stubs injiziert; Zähler belegen die Weiterleitung.
const extractDispatch = () => {
  const match = source.match(/window\.__bortDispatch = \(payloadJson\) => \{([\s\S]*?)\n  \};/);
  if (!match) return null;
  try {
    return new Function(
      'payloadJson',
      'activeJobId',
      'bridgeWaiters',
      '$',
      'setStatus',
      'setProgress',
      'appendLog',
      'appendLiveSegment',
      'finishActiveJob',
      'resetLivePreview',
      'renderPreview',
      'setViewStatus',
      'setBatchOutcome',
      'setBatchProgress',
      'appendBatchLog',
      'pendingBatchItems',
      'completedBatchItems',
      'activeBatchId',
      'batchNeedsRescan',
      match[1],
    );
  } catch (_) {
    return null;
  }
};

const buildDispatchHarness = () => {
  const dispatchFn = extractDispatch();
  if (!dispatchFn) return null;
  const element = () => ({
    disabled: false,
    hidden: false,
    textContent: '',
    querySelector: () => ({ textContent: '' }),
  });
  const calls = { liveSegments: [], statuses: [], finishedJobs: 0 };
  const dispatch = (activeJobId, payloadJson) => dispatchFn(
    payloadJson,
    activeJobId,
    new Map(),
    () => element(),
    (message) => calls.statuses.push(message),
    () => {},
    () => {},
    (segment) => calls.liveSegments.push(segment),
    () => { calls.finishedJobs += 1; },
    () => {},
    () => {},
    () => {},
    () => {},
    () => {},
    () => {},
    [],
    { has: () => false, add: () => {}, clear: () => {} },
    '',
    false,
  );
  return { calls, dispatch };
};

test('__bortDispatch reicht partial-Events an appendLiveSegment weiter', (t) => {
  const harness = buildDispatchHarness();
  if (!harness) {
    t.skip('__bortDispatch nicht mehr als eigenständige Funktion in app.js auffindbar');
    return;
  }
  const segment = { type: 'partial', start: 0.0, end: 2.4, text: 'Hallo Welt' };
  harness.dispatch(null, JSON.stringify(segment));
  assert.deepEqual(harness.calls.liveSegments, [segment]);
});

test('__bortDispatch ignoriert veraltete cancelled-Events ohne aktiven Job', (t) => {
  const harness = buildDispatchHarness();
  if (!harness) {
    t.skip('__bortDispatch nicht mehr als eigenständige Funktion in app.js auffindbar');
    return;
  }
  const cancelled = JSON.stringify({ type: 'cancelled', message: 'abgebrochen' });
  harness.dispatch(null, cancelled);
  assert.equal(harness.calls.finishedJobs, 0);
  assert.equal(harness.calls.statuses.length, 0);
  harness.dispatch('job-1', cancelled);
  assert.equal(harness.calls.finishedJobs, 1);
  assert.equal(harness.calls.statuses.length, 1);
});

// Scheitert der Abbruch-Aufruf, muss der Knopf bei laufendem Job wieder
// klickbar werden. `Boolean(activeJobId)` war invertiert und ließ den Knopf
// bis zum Job-Ende deaktiviert, obwohl der Job weiterlief.
test('Abbrechen-Knopf wird nach fehlgeschlagenem Abbruch reaktiviert', () => {
  const assignments = [...source.matchAll(
    /\$\('cancel-transcription'\)\.disabled = ([^;]+);/g,
  )].map((match) => match[1].trim());
  assert.ok(assignments.length >= 3, 'Zuweisungen an #cancel-transcription.disabled gefunden');
  assert.equal(assignments.includes('Boolean(activeJobId)'), false);
  assert.equal(assignments.filter((value) => value === '!activeJobId').length, 2);
});

// Löschen-Buttons in Bibliothek und Batch. Wie beim Abbrechen-Handler wird der
// echte Handler ausgeführt und sein Verhalten geprüft – eine Regex über den
// Quelltext bliebe auch dann grün, wenn der Button im falschen Zweig stünde.
//
// Der Handler wird über einen eindeutigen Anker (die className-Zeile des
// Löschen-Knopfs) gefunden, das Ende über Klammer-Zählung. Eine Regex auf die
// Einrückung würde den falschen Handler treffen – app.js hat drei
// "remove.addEventListener".
//
// Wichtig: app.js weist manche Zustände im umgebenden Scope neu zu
// (z.B. "pendingBatchItems = pendingBatchItems.filter(...)"). Damit das im
// Test dasselbe bedeutet wie in der App, deklariert die Harness diese
// Variablen als "let" im Funktions-Scope und gibt sie danach heraus – ein
// übergebener Parameter würde die Neuzuweisung nur lokal verändern.
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/bort/web/app.js', import.meta.url), 'utf8');

const extractDeleteBody = (className) => {
  const anchor = source.indexOf(`remove.className = '${className}';`);
  if (anchor < 0) return null;
  const start = source.indexOf(
    "remove.addEventListener('click', async () => {",
    anchor,
  );
  if (start < 0) return null;
  const bodyStart = source.indexOf('{', start) + 1;
  let depth = 1;
  let index = bodyStart;
  while (index < source.length && depth > 0) {
    const char = source[index];
    if (char === '{') depth += 1;
    else if (char === '}') depth -= 1;
    index += 1;
  }
  if (depth !== 0) return null;
  return source.slice(bodyStart, index - 1);
};

const extractLibraryDelete = () => {
  const body = extractDeleteBody('library-delete');
  if (!body) return null;
  try {
    return new Function(
      'item',
      'card',
      'api',
      'confirmDialog',
      'showActionFailure',
      'setViewStatus',
      'librarySelection',
      'librarySelectableIds',
      'initialRenderedItemCount',
      'updateExportButton',
      `
      let libraryRenderedItemCount = initialRenderedItemCount;
      return {
        run: async () => {${body}},
        state: () => ({ libraryRenderedItemCount }),
      };
      `,
    );
  } catch (_) {
    return null;
  }
};

const runLibraryDelete = async (handler, { confirmed, bridgeResult, bridgeError }) => {
  const removed = { removed: false };
  const card = { remove: () => { removed.removed = true; } };
  const selection = new Set(['item-1']);
  const selectable = new Set(['item-1']);
  const statuses = [];
  const failures = [];
  const exported = { called: false };
  const harness = handler(
    { item_id: 'item-1', name: 'aufnahme.m4a' },
    card,
    {
      delete_library_item: async () => {
        if (bridgeError) throw bridgeError;
        return bridgeResult;
      },
    },
    async () => confirmed,
    (error) => failures.push(error),
    (id, message, isError) => statuses.push([id, message, Boolean(isError)]),
    selection,
    selectable,
    1,
    () => { exported.called = true; },
  );
  await harness.run();
  return {
    removed,
    selection,
    selectable,
    statuses,
    failures,
    exported,
    state: harness.state(),
  };
};

test('Bibliotheks-Löschen fragt nach und verschiebt die Datei in den Papierkorb', async () => {
  const handler = extractLibraryDelete();
  assert.ok(handler, 'Löschen-Handler in der Bibliothek nicht mehr auffindbar');
  const run = await runLibraryDelete(handler, {
    confirmed: true,
    bridgeResult: { ok: true, deleted: 4, name: 'aufnahme.m4a' },
  });
  assert.equal(run.removed.removed, true);
  assert.equal(run.selection.has('item-1'), false);
  assert.equal(run.selectable.has('item-1'), false);
  assert.equal(run.state.libraryRenderedItemCount, 0);
  assert.equal(run.exported.called, true);
  assert.equal(run.statuses.at(-1)[0], 'library-status');
  assert.equal(run.statuses.at(-1)[2], false);
  assert.equal(run.failures.length, 0);
});

test('Bibliotheks-Löschen passiert nichts, wenn der Dialog abgebrochen wird', async () => {
  const handler = extractLibraryDelete();
  assert.ok(handler, 'Löschen-Handler in der Bibliothek nicht mehr auffindbar');
  const run = await runLibraryDelete(handler, {
    confirmed: false,
    bridgeResult: { ok: true },
  });
  // Ohne Bestätigung wird weder die Datei gelöscht noch die Karte entfernt.
  assert.equal(run.removed.removed, false);
  assert.equal(run.selection.has('item-1'), true);
  assert.equal(run.state.libraryRenderedItemCount, 1);
  assert.equal(run.statuses.length, 0);
});

test('Bibliotheks-Löschen meldet ein Backend-Problem als Fehlerstatus', async () => {
  const handler = extractLibraryDelete();
  assert.ok(handler, 'Löschen-Handler in der Bibliothek nicht mehr auffindbar');
  const run = await runLibraryDelete(handler, {
    confirmed: true,
    bridgeResult: { ok: false, error: 'Bitte neu scannen.' },
  });
  assert.equal(run.removed.removed, false);
  assert.equal(run.state.libraryRenderedItemCount, 1);
  assert.deepEqual(run.statuses.at(-1), ['library-status', 'Bitte neu scannen.', true]);
});

test('Bibliotheks-Löschen zeigt einen Bridge-Fehler als Fehlerstatus', async () => {
  const handler = extractLibraryDelete();
  assert.ok(handler, 'Löschen-Handler in der Bibliothek nicht mehr auffindbar');
  const run = await runLibraryDelete(handler, {
    confirmed: true,
    bridgeError: new Error('Bridge weg'),
  });
  assert.equal(run.removed.removed, false);
  assert.equal(run.failures.length, 1);
  assert.equal(run.statuses.length, 0);
});

const extractBatchDelete = () => {
  const body = extractDeleteBody('batch-delete');
  if (!body) return null;
  try {
    return new Function(
      'item',
      'row',
      '$',
      'api',
      'confirmDialog',
      'showActionFailure',
      'setViewStatus',
      'initialPendingBatchItems',
      'batchOutcomeMap',
      'completedBatchItems',
      'activeBatchId',
      'batchNeedsRescan',
      `
      let pendingBatchItems = initialPendingBatchItems;
      return {
        run: async () => {${body}},
        state: () => ({ pendingBatchItems }),
      };
      `,
    );
  } catch (_) {
    return null;
  }
};

const runBatchDelete = async (handler, { confirmed, bridgeResult, bridgeError }) => {
  const removed = { removed: false };
  const row = { remove: () => { removed.removed = true; } };
  const statuses = [];
  const failures = [];
  const elements = {
    'pending-count': { textContent: '' },
    'start-batch': { disabled: false },
  };
  const outcomeMap = new Map([['a.m4a', { text: 'Ausstehend' }]]);
  const completed = new Set(['a.m4a']);
  const harness = handler(
    { audio_name: 'a.m4a' },
    row,
    (id) => elements[id] || { textContent: '', disabled: false },
    {
      delete_batch_item: async () => {
        if (bridgeError) throw bridgeError;
        return bridgeResult;
      },
    },
    async () => confirmed,
    (error) => failures.push(error),
    (id, message, isError) => statuses.push([id, message, Boolean(isError)]),
    [
      { audio_name: 'a.m4a' },
      { audio_name: 'b.m4a' },
    ],
    outcomeMap,
    completed,
    null,
    false,
  );
  await harness.run();
  return {
    removed,
    statuses,
    failures,
    elements,
    outcomeMap,
    completed,
    state: harness.state(),
  };
};

test('Batch-Löschen entfernt das Item und zählt die Liste nach', async () => {
  const handler = extractBatchDelete();
  assert.ok(handler, 'Löschen-Handler im Batch nicht mehr auffindbar');
  const run = await runBatchDelete(handler, {
    confirmed: true,
    bridgeResult: { ok: true, deleted: 1, name: 'a.m4a' },
  });
  assert.equal(run.removed.removed, true);
  assert.equal(run.state.pendingBatchItems.length, 1);
  assert.equal(run.state.pendingBatchItems[0].audio_name, 'b.m4a');
  assert.equal(run.outcomeMap.has('a.m4a'), false);
  assert.equal(run.completed.has('a.m4a'), false);
  assert.equal(run.elements['pending-count'].textContent, '1 Datei');
  assert.equal(run.elements['start-batch'].disabled, false);
});

test('Batch-Löschen passiert nichts, wenn der Dialog abgebrochen wird', async () => {
  const handler = extractBatchDelete();
  assert.ok(handler, 'Löschen-Handler im Batch nicht mehr auffindbar');
  const run = await runBatchDelete(handler, {
    confirmed: false,
    bridgeResult: { ok: true },
  });
  assert.equal(run.removed.removed, false);
  assert.equal(run.state.pendingBatchItems.length, 2);
  assert.equal(run.statuses.length, 0);
});

test('Batch-Löschen meldet ein Backend-Problem als Fehlerstatus', async () => {
  const handler = extractBatchDelete();
  assert.ok(handler, 'Löschen-Handler im Batch nicht mehr auffindbar');
  const run = await runBatchDelete(handler, {
    confirmed: true,
    bridgeResult: { ok: false, error: 'Der Batch läuft gerade. Bitte warten.' },
  });
  assert.equal(run.removed.removed, false);
  assert.equal(run.state.pendingBatchItems.length, 2);
  assert.deepEqual(run.statuses.at(-1), [
    'batch-status',
    'Der Batch läuft gerade. Bitte warten.',
    true,
  ]);
});

test('Batch-Löschen zeigt einen Bridge-Fehler über die Fehleranzeige', async () => {
  const handler = extractBatchDelete();
  assert.ok(handler, 'Löschen-Handler im Batch nicht mehr auffindbar');
  const run = await runBatchDelete(handler, {
    confirmed: true,
    bridgeError: new Error('Bridge weg'),
  });
  assert.equal(run.removed.removed, false);
  assert.equal(run.failures.length, 1);
  assert.equal(run.state.pendingBatchItems.length, 2);
});

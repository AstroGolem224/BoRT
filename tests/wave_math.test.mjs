import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const wave = require('../src/bort/web/wave_math.js');

test('normalizeSegments filtert, clippt, kopiert und sortiert', () => {
  const source = [
    { start: 5, end: 12, speaker_id: 'B' },
    { start: -1, end: 2, speaker_id: 'X' },
    { start: 1, end: 3, speaker_id: 'A' },
    { start: NaN, end: 2, speaker_id: 'X' },
    { start: 4, end: 4, speaker_id: 'X' },
    { start: 2, end: Infinity, speaker_id: 'X' },
  ];
  const result = wave.normalizeSegments(source, 10);
  assert.deepEqual(result.map(({ start, end, speaker_id }) => ({ start, end, speaker_id })), [
    { start: 1, end: 3, speaker_id: 'A' },
    { start: 5, end: 10, speaker_id: 'B' },
  ]);
  assert.equal(source[0].end, 12);
});

test('bucketSpeaker nutzt Überlappung, früheren Start und Originalindex', () => {
  const segments = [
    { start: 0, end: 4, speaker_id: 'frueh', _index: 4 },
    { start: 2, end: 6, speaker_id: 'spaet', _index: 0 },
  ];
  assert.equal(wave.bucketSpeaker(1, 3, segments).speaker_id, 'frueh');
  const tied = [
    { start: 0, end: 2, speaker_id: 'hoch', _index: 5 },
    { start: 0, end: 2, speaker_id: 'niedrig', _index: 1 },
  ];
  assert.equal(wave.bucketSpeaker(0, 1, tied).speaker_id, 'niedrig');
  assert.equal(wave.bucketSpeaker(8, 9, segments), null);
});

test('mergeBlocks toleriert kleine Lücken desselben Sprechers', () => {
  const blocks = wave.mergeBlocks([
    { start: 0, end: 2, speaker_id: 'A' },
    { start: 3.5, end: 5, speaker_id: 'A' },
    { start: 5, end: 6, speaker_id: 'B' },
  ]);
  assert.deepEqual(blocks.map(({ start, end, speaker_id }) => ({ start, end, speaker_id })), [
    { start: 0, end: 5, speaker_id: 'A' },
    { start: 5, end: 6, speaker_id: 'B' },
  ]);
});

test('layoutLabels arbeitet pixelbasiert und verhindert Kollisionen', () => {
  const labels = wave.layoutLabels([
    { start: 0, end: 8, speaker_id: 'A' },
    { start: 5, end: 9, speaker_id: 'B' },
    { start: 10, end: 10.5, speaker_id: 'C' },
  ], 20, 200, (id) => id, () => 30, 10);
  assert.deepEqual(labels.map((label) => label.speaker_id), ['A']);
});

test('keyboardSeekTarget begrenzt Schritte und behandelt Home/End', () => {
  assert.equal(wave.keyboardSeekTarget('ArrowLeft', 2, 20), 0);
  assert.equal(wave.keyboardSeekTarget('ArrowRight', 18, 20), 20);
  assert.equal(wave.keyboardSeekTarget('Home', 8, 20), 0);
  assert.equal(wave.keyboardSeekTarget('End', 8, 20), 20);
  assert.equal(wave.keyboardSeekTarget('Enter', 8, 20), null);
});

test('ariaValues liefert laufend aktualisierbare Slider-Werte', () => {
  assert.deepEqual(wave.ariaValues(65.2, 130), {
    valuemin: '0',
    valuemax: '130',
    valuenow: '65',
    valuetext: '01:05 von 02:10',
  });
});

test('isCurrentReview schützt gegen alte Review- und src-Antworten', () => {
  assert.equal(wave.isCurrentReview('r1', 'r1', 'file:///a', 'file:///a'), true);
  assert.equal(wave.isCurrentReview('r1', 'r2', 'file:///a', 'file:///a'), false);
  assert.equal(wave.isCurrentReview('r1', 'r1', 'file:///a', 'file:///b'), false);
});

/* Reine Waveform- und Timeline-Logik; im Browser und unter Node nutzbar. */
((root) => {
  'use strict';

  const finite = (value) => Number.isFinite(Number(value));
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  // Unter einer Stunde MM:SS, ab einer Stunde H:MM:SS (Aufnahmen > 59:59).
  const formatTime = (value) => {
    const total = Math.max(0, Math.floor(Number(value) || 0));
    const minutes = String(Math.floor(total / 60) % 60).padStart(2, '0');
    const seconds = String(total % 60).padStart(2, '0');
    const hours = Math.floor(total / 3600);
    return hours > 0 ? `${hours}:${minutes}:${seconds}` : `${minutes}:${seconds}`;
  };

  const normalizeSegments = (segments, duration) => {
    const limit = Number(duration);
    if (!finite(limit) || limit <= 0 || !Array.isArray(segments)) return [];
    return segments.map((segment, index) => ({ ...segment, _index: index }))
      .filter((segment) => finite(segment.start) && finite(segment.end)
        && Number(segment.start) >= 0 && Number(segment.end) > Number(segment.start))
      .map((segment) => ({
        ...segment,
        start: clamp(Number(segment.start), 0, limit),
        end: clamp(Number(segment.end), 0, limit),
      }))
      .filter((segment) => segment.end > segment.start)
      .sort((left, right) => left.start - right.start || left._index - right._index);
  };

  const bucketSpeaker = (start, end, segments) => {
    let winner = null;
    let bestOverlap = 0;
    (segments || []).forEach((segment) => {
      const overlap = Math.max(0, Math.min(end, segment.end) - Math.max(start, segment.start));
      if (overlap <= 0) return;
      const earlier = winner === null || segment.start < winner.start;
      const sameStart = winner !== null && segment.start === winner.start;
      const lowerIndex = sameStart && (segment._index || 0) < (winner._index || 0);
      if (overlap > bestOverlap || (overlap === bestOverlap && (earlier || lowerIndex))) {
        winner = segment;
        bestOverlap = overlap;
      }
    });
    return winner;
  };

  const mergeBlocks = (segments, toleratedGap = 2) => {
    const blocks = [];
    (segments || []).forEach((segment) => {
      const previous = blocks[blocks.length - 1];
      if (previous && previous.speaker_id === segment.speaker_id
          && segment.start - previous.end < toleratedGap) {
        previous.end = Math.max(previous.end, segment.end);
        previous.segmentCount += 1;
      } else {
        blocks.push({
          start: segment.start,
          end: segment.end,
          speaker_id: segment.speaker_id,
          segmentCount: 1,
        });
      }
    });
    return blocks;
  };

  const layoutLabels = (blocks, duration, width, nameForSpeaker, measure, padding = 14) => {
    if (!(duration > 0) || !(width > 0)) return [];
    const placed = [];
    [...(blocks || [])].sort((left, right) =>
      (right.end - right.start) - (left.end - left.start))
      .forEach((block) => {
        const text = String(nameForSpeaker(block.speaker_id) || block.speaker_id || 'Sprecher');
        const left = block.start / duration * width;
        const right = block.end / duration * width;
        const textWidth = Math.max(0, Number(measure(text)) || 0) + padding;
        if (textWidth > right - left) return;
        const center = (left + right) / 2;
        const labelLeft = center - textWidth / 2;
        const labelRight = center + textWidth / 2;
        if (placed.some((label) => labelLeft < label.right && labelRight > label.left)) return;
        placed.push({ ...block, text, left: labelLeft, right: labelRight, center });
      });
    return placed.sort((left, right) => left.left - right.left);
  };

  const keyboardSeekTarget = (key, current, duration, step = 5) => {
    if (!finite(current) || !finite(duration) || Number(duration) <= 0) return null;
    const now = Number(current);
    const limit = Number(duration);
    if (key === 'ArrowLeft') return clamp(now - step, 0, limit);
    if (key === 'ArrowRight') return clamp(now + step, 0, limit);
    if (key === 'Home') return 0;
    if (key === 'End') return limit;
    return null;
  };

  const ariaValues = (current, duration) => {
    const limit = finite(duration) && Number(duration) > 0 ? Number(duration) : 0;
    const now = clamp(finite(current) ? Number(current) : 0, 0, limit);
    return {
      valuemin: '0',
      valuemax: String(Math.round(limit)),
      valuenow: String(Math.round(now)),
      valuetext: `${formatTime(now)} von ${formatTime(limit)}`,
    };
  };

  const isCurrentReview = (capturedId, currentId, capturedSrc, currentSrc) =>
    Boolean(capturedId && capturedId === currentId && capturedSrc === currentSrc);

  const resamplePeaks = (peaks, count) => {
    if (!Array.isArray(peaks) || peaks.length === 0 || !(count > 0)) return [];
    if (peaks.length === count) return peaks.slice();
    if (peaks.length > count) {
      return Array.from({ length: count }, (_, index) => {
        const start = Math.floor(index * peaks.length / count);
        const end = Math.floor((index + 1) * peaks.length / count);
        return Math.max(...peaks.slice(start, end).map(Number));
      });
    }
    return Array.from({ length: count }, (_, index) =>
      Number(peaks[Math.min(peaks.length - 1, Math.floor(index * peaks.length / count))]));
  };

  const api = {
    normalizeSegments,
    bucketSpeaker,
    mergeBlocks,
    layoutLabels,
    keyboardSeekTarget,
    ariaValues,
    isCurrentReview,
    resamplePeaks,
  };
  if (typeof window !== 'undefined') window.BortWave = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root && !root.BortWave) root.BortWave = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);

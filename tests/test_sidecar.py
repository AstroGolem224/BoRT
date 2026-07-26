"""Vertragstests für die ausschließlich lesende BoR-Metadatei."""

import json
import math
from pathlib import Path

from bort.sidecar import read_recording_meta, resample_peaks


def _write(path: Path, **changes: object) -> Path:
    data = {
        "file": "aufnahme.m4a",
        "startedAt": "2026-07-24T13:59:12+02:00",
        "durationMs": 4150000,
        "markers": [{"timeMs": 12, "type": "note", "label": ""}],
        "peaks": [index / 103 for index in range(104)],
    }
    data.update(changes)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_read_recording_meta_normalfall(tmp_path: Path) -> None:
    meta = read_recording_meta(_write(tmp_path / "aufnahme.json"), "aufnahme.m4a")
    assert meta is not None
    assert meta.duration_ms == 4150000
    assert meta.marker_count == 1
    assert len(meta.peaks) == 104
    assert meta.warnings == []


def test_read_recording_meta_rejects_mismatch_and_broken_json(tmp_path: Path) -> None:
    assert read_recording_meta(
        _write(tmp_path / "aufnahme.json", file="falsch.m4a"), "aufnahme.m4a"
    ) is None
    broken = tmp_path / "broken.json"
    broken.write_text("{halb", encoding="utf-8")
    assert read_recording_meta(broken, "aufnahme.m4a") is None


def test_read_recording_meta_filters_nonfinite_and_caps(tmp_path: Path) -> None:
    meta = read_recording_meta(
        _write(
            tmp_path / "aufnahme.json",
            durationMs=math.inf,
            peaks=[-2, 0.5, 4, math.nan, math.inf] + [0.2] * 1100,
            markers=[{"timeMs": math.nan}, "müll", {"timeMs": 2}],
        ),
        "aufnahme.m4a",
    )
    assert meta is not None
    assert meta.duration_ms == 0
    assert meta.peaks[:3] == [0, 0.5, 1]
    assert len(meta.peaks) == 998
    assert meta.marker_count == 1
    assert meta.warnings


def test_resample_peaks_reference_shapes() -> None:
    assert resample_peaks([], 34) == []
    assert resample_peaks(list(range(34)), 34) == list(range(34))
    assert resample_peaks([0, 1, 2, 3, 4], 34) == [
        [0, 1, 2, 3, 4][min(4, index * 5 // 34)] for index in range(34)
    ]
    source = list(range(104))
    result = resample_peaks(source, 34)
    assert len(result) == 34
    assert result == [
        max(source[index * 104 // 34:(index + 1) * 104 // 34])
        for index in range(34)
    ]

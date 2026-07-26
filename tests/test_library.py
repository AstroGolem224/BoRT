"""Bibliotheks-Scan und opake generationsgebundene Aktionen."""

import json
from pathlib import Path

from bort.app import Bridge
from bort.config import Config


def _bridge(tmp_path: Path, root: Path) -> Bridge:
    bridge = Bridge(config=Config(path=tmp_path / "settings.json"))
    bridge._paths["library"] = root
    return bridge


def test_scan_library_reads_sidecar_and_invalidates_old_ids(tmp_path: Path) -> None:
    root = tmp_path / "library"
    day = root / "2026-07-24"
    day.mkdir(parents=True)
    audio = day / "aufnahme.m4a"
    audio.write_bytes(b"audio")
    (day / "aufnahme.txt").write_text("text", encoding="utf-8")
    (day / "aufnahme.json").write_text(
        json.dumps({
            "file": audio.name,
            "startedAt": "2026-07-24T13:59:12+02:00",
            "durationMs": 12000,
            "markers": [{"timeMs": 10, "type": "note", "label": ""}],
            "peaks": [0.2] * 104,
        }),
        encoding="utf-8",
    )
    bridge = _bridge(tmp_path, root)
    first = bridge.scan_library()
    assert first["ok"] is True
    assert first["items"][0]["peaks34"] == [0.2] * 34
    assert first["items"][0]["formats_present"] == ["txt"]
    old_id = first["items"][0]["item_id"]
    prepared = bridge.prepare_library_transcription(old_id)
    assert prepared["audio_path"] == str(audio.resolve())
    bridge.scan_library()
    assert bridge.prepare_library_transcription(old_id)["error"] == "Bitte neu scannen."

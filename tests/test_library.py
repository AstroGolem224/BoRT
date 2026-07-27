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


def test_export_library_zip_creates_archive(tmp_path, monkeypatch):
    import zipfile as zf

    from bort.app import Bridge
    from bort.config import Config

    day = tmp_path / "lib" / "2026-07-20"
    day.mkdir(parents=True)
    audio = day / "clip.m4a"
    audio.write_bytes(b"a")
    (day / "clip.txt").write_text("transkript", encoding="utf-8")
    other = day / "leer.m4a"
    other.write_bytes(b"a")
    export = tmp_path / "export"
    export.mkdir()

    bridge = Bridge(config=Config(path=tmp_path / "settings.json"))
    with bridge._state_lock:
        bridge._paths["library"] = tmp_path / "lib"
        bridge._paths["export"] = export
    scan = bridge.scan_library()
    assert scan["ok"] and len(scan["items"]) == 2

    ids = [item["item_id"] for item in scan["items"]]
    result = bridge.export_library_zip(ids)
    assert result["ok"], result
    assert result["file_count"] == 1
    assert result["skipped"] == 1
    with zf.ZipFile(result["zip_path"]) as archive:
        assert archive.namelist() == ["2026-07-20/clip.txt"]


def test_export_library_zip_requires_export_dir(tmp_path):
    from bort.app import Bridge
    from bort.config import Config

    bridge = Bridge(config=Config(path=tmp_path / "settings.json"))
    assert bridge.export_library_zip(["x"])["ok"] is False

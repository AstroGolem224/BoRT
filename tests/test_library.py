"""Bibliotheks-Scan und opake generationsgebundene Aktionen."""

import json
import os
import time
from pathlib import Path

import bort.app
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


def _sidecar(root: Path, name: str) -> Path:
    return root / f"{name}.json"


def test_scan_library_cache_hits_and_invalidates_on_mtime(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "library"
    day = root / "2026-08-27"
    day.mkdir(parents=True)
    audio = day / "aufnahme.m4a"
    audio.write_bytes(b"audio")
    (day / "aufnahme.txt").write_text("text", encoding="utf-8")
    _sidecar(day, "aufnahme").write_text(
        json.dumps({
            "file": audio.name,
            "startedAt": "2026-08-27T08:15:00+02:00",
            "durationMs": 9000,
            "markers": [{"timeMs": 10, "type": "note", "label": ""}],
            "peaks": [0.2] * 104,
        }),
        encoding="utf-8",
    )
    bridge = _bridge(tmp_path, root)
    first = bridge.scan_library()
    assert first["ok"] is True
    assert first["warning_count"] == 0

    calls = {"n": 0}
    real_read = bort.app.read_recording_meta

    def counting_read(json_path: Path, audio_name: str):
        calls["n"] += 1
        return real_read(json_path, audio_name)

    monkeypatch.setattr("bort.app.read_recording_meta", counting_read)
    # Abhängige Dateien ändern sich, ohne dass die Audio-mtime sich ändert:
    # formats_present/has_review werden frisch geprüft (nicht aus dem Cache),
    # nur das Sidecar-Parsing kommt aus dem Cache.
    (day / "aufnahme.txt").unlink()
    (day / "aufnahme.review.json").write_text("{}", encoding="utf-8")
    second = bridge.scan_library()
    assert calls["n"] == 0, "unveränderte Datei muss aus dem Cache kommen"
    assert second["items"][0]["formats_present"] == []
    assert second["items"][0]["has_review"] is True
    fields = ("name", "duration_ms", "marker_count", "peaks34")
    assert [
        {key: item[key] for key in fields} for item in second["items"]
    ] == [{key: item[key] for key in fields} for item in first["items"]]
    assert second["warning_count"] == first["warning_count"]

    new_time = time.time() + 10
    os.utime(audio, (new_time, new_time))
    bridge.scan_library()
    assert calls["n"] == 1, "geänderte mtime muss den Cache-Eintrag invalidieren"


def test_scan_library_formats_and_review_fresh_across_scans(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    (root / "aufnahme.m4a").write_bytes(b"audio")
    bridge = _bridge(tmp_path, root)
    first = bridge.scan_library()
    assert first["ok"] is True
    assert first["items"][0]["formats_present"] == []
    assert first["items"][0]["has_review"] is False

    (root / "aufnahme.md").write_text("transkript", encoding="utf-8")
    (root / "aufnahme.review.json").write_text("{}", encoding="utf-8")
    second = bridge.scan_library()
    assert second["items"][0]["formats_present"] == ["md"]
    assert second["items"][0]["has_review"] is True

    (root / "aufnahme.md").unlink()
    (root / "aufnahme.review.json").unlink()
    third = bridge.scan_library()
    assert third["items"][0]["formats_present"] == []
    assert third["items"][0]["has_review"] is False


def test_scan_library_skips_file_disappearing_before_stat(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    (root / "bleibt.m4a").write_bytes(b"a")
    (root / "weg.m4a").write_bytes(b"a")
    bridge = _bridge(tmp_path, root)

    real_stat = Path.stat

    def vanishing_stat(self, *, follow_symlinks=True):
        if self.name == "weg.m4a":
            raise FileNotFoundError(2, "zwischen Walk und stat verschwunden")
        return real_stat(self, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", vanishing_stat)
    result = bridge.scan_library()
    assert result["ok"] is True
    assert [item["name"] for item in result["items"]] == ["bleibt.m4a"]
    assert result["warning_count"] == 0


def test_rename_library_item_returns_fresh_audio_uri(tmp_path: Path) -> None:
    root = tmp_path / "library"
    day = root / "2026-08-27"
    day.mkdir(parents=True)
    audio = day / "clip.m4a"
    audio.write_bytes(b"audio")
    bridge = _bridge(tmp_path, root)
    scan = bridge.scan_library()
    assert scan["ok"] and scan["items"]

    result = bridge.rename_library_item(scan["items"][0]["item_id"], "neu")
    assert result == {
        "ok": True,
        "name": "neu.m4a",
        "audio_url": (day / "neu.m4a").resolve().as_uri(),
    }
    assert not audio.exists()
    assert (day / "neu.m4a").is_file()


def test_rename_keeps_item_id_usable_for_prepare_and_review(tmp_path: Path) -> None:
    root = tmp_path / "library"
    day = root / "2026-08-27"
    day.mkdir(parents=True)
    audio = day / "clip.m4a"
    audio.write_bytes(b"audio")
    (day / "clip.txt").write_text("transkript", encoding="utf-8")
    review = {
        "schema_version": 1,
        "audio_path": str(audio.resolve()),
        "segments": [{"start": 0.0, "end": 1.0, "speaker": "SP1", "text": "Hallo"}],
        "speaker_map": {"SP1": "sprecher001"},
        "markers": [{"start": 0.0, "end": 1.0, "speaker": "SP1"}],
        "bookmarks": [],
        "base_name": "clip",
        "formats": ["txt"],
    }
    (day / "clip.review.json").write_text(
        json.dumps(review), encoding="utf-8"
    )
    bridge = _bridge(tmp_path, root)
    scan = bridge.scan_library()
    assert scan["ok"] and scan["items"]
    item_id = scan["items"][0]["item_id"]

    result = bridge.rename_library_item(item_id, "neu")
    assert result["ok"] is True

    prepared = bridge.prepare_library_transcription(item_id)
    assert prepared["ok"] is True
    assert prepared["audio_path"] == str((day / "neu.m4a").resolve())
    assert prepared["marker_path"] == ""

    opened = bridge.open_library_review(item_id)
    assert opened.get("ok") is True, opened


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


def test_scan_library_picks_up_late_arriving_sidecar(tmp_path: Path) -> None:
    """Sync-Ordner: .m4a kommt vor der .json — der zweite Scan zeigt die Metadaten.

    Der Cache-Schlüssel darf nicht allein am Audio-stat hängen: das
    nachgereichte Sidecar ändert ihn nicht, der Eintrag bliebe sonst für den
    Rest der Sitzung auf 00:00 / 0 Marker / leerer Wellenform stehen.
    """
    root = tmp_path / "library"
    day = root / "2026-08-27"
    day.mkdir(parents=True)
    audio = day / "aufnahme.m4a"
    audio.write_bytes(b"audio")
    bridge = _bridge(tmp_path, root)

    first = bridge.scan_library()
    assert first["items"][0]["duration_ms"] == 0
    assert first["items"][0]["peaks34"] == []

    _sidecar(day, "aufnahme").write_text(
        json.dumps({
            "file": audio.name,
            "startedAt": "2026-08-27T08:15:00+02:00",
            "durationMs": 9000,
            "markers": [{"timeMs": 10, "type": "note", "label": ""}],
            "peaks": [0.2] * 104,
        }),
        encoding="utf-8",
    )

    second = bridge.scan_library()
    assert second["items"][0]["duration_ms"] == 9000
    assert second["items"][0]["marker_count"] == 1
    assert second["items"][0]["peaks34"] == [0.2] * 34


def test_library_scan_cache_is_bounded(tmp_path: Path) -> None:
    """Der Sidecar-Cache verdrängt alte Einträge statt unbegrenzt zu wachsen."""
    root = tmp_path / "library"
    root.mkdir()
    bridge = _bridge(tmp_path, root)
    limit = bort.app.MAX_LIBRARY_SCAN_CACHE
    for index in range(limit + 5):
        audio = root / f"aufnahme-{index}.m4a"
        audio.write_bytes(b"audio")
        bridge._scan_library_file(audio)
    assert len(bridge._library_scan_cache) == limit

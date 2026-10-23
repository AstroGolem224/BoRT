"""Löschen von Bibliotheks- und Batch-Einträgen über die Bridge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bort.app import Bridge
from bort.config import Config


@pytest.fixture(autouse=True)
def _trash_in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr("bort.recording_delete._gio_trash", lambda _path: False)


def _bridge(tmp_path: Path, **paths: Path) -> Bridge:
    bridge = Bridge(config=Config(path=tmp_path / "settings.json"))
    for key, value in paths.items():
        bridge._paths[key] = value
    return bridge


def _recording(day: Path, name: str = "aufnahme") -> Path:
    audio = day / f"{name}.m4a"
    audio.write_bytes(b"audio")
    (day / f"{name}.txt").write_text("text", encoding="utf-8")
    (day / f"{name}.review.json").write_text("{}", encoding="utf-8")
    (day / f"{name}.json").write_text(json.dumps({"file": audio.name}), encoding="utf-8")
    return audio


def test_delete_library_item_moves_the_whole_family_to_trash(tmp_path: Path) -> None:
    root = tmp_path / "library"
    day = root / "2026-10-23"
    day.mkdir(parents=True)
    audio = _recording(day)
    bridge = _bridge(tmp_path, library=root)
    scan = bridge.scan_library()
    assert scan["ok"] is True
    item_id = scan["items"][0]["item_id"]

    result = bridge.delete_library_item(item_id)

    assert result["ok"] is True
    assert result["deleted"] == 4
    assert not audio.exists()
    assert not (day / "aufnahme.txt").exists()
    assert not (day / "aufnahme.review.json").exists()
    assert not (day / "aufnahme.json").exists()


def test_delete_library_item_rejects_unknown_id(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    bridge = _bridge(tmp_path, library=root)
    result = bridge.delete_library_item("gibt-es-nicht")
    assert result["ok"] is False
    assert "neu scannen" in result["error"]


def test_delete_library_item_rejects_path_traversal(tmp_path: Path) -> None:
    """Ein item_id darf niemals auf eine Datei außerhalb der Bibliothek zeigen."""
    outside = tmp_path / "ausserhalb.m4a"
    outside.write_bytes(b"audio")
    root = tmp_path / "library"
    root.mkdir()
    bridge = _bridge(tmp_path, library=root)
    bridge._library_items["fremd"] = (bridge._library_generation, outside)
    result = bridge.delete_library_item("fremd")
    assert result["ok"] is False
    assert outside.exists()


def test_delete_batch_item_removes_the_source_file(tmp_path: Path) -> None:
    watch = tmp_path / "sync"
    watch.mkdir()
    audio = _recording(watch, "sitzung")
    bridge = _bridge(tmp_path, watch=watch, output=watch)
    scan = bridge.scan_batch({})
    assert scan["ok"] is True
    assert scan["items"][0]["audio_name"] == "sitzung.m4a"

    result = bridge.delete_batch_item("sitzung.m4a")

    assert result["ok"] is True
    assert result["deleted"] == 4
    assert not audio.exists()
    assert not (watch / "sitzung.txt").exists()


def test_delete_batch_item_rejects_unknown_name(tmp_path: Path) -> None:
    watch = tmp_path / "sync"
    watch.mkdir()
    bridge = _bridge(tmp_path, watch=watch, output=watch)
    result = bridge.delete_batch_item("gibt-es-nicht.m4a")
    assert result["ok"] is False


def test_delete_batch_item_rejects_path_traversal(tmp_path: Path) -> None:
    """Ein Dateiname darf niemals auf eine Datei außerhalb des Sync-Ordners zeigen."""
    watch = tmp_path / "sync"
    watch.mkdir()
    outside = tmp_path / "ausserhalb.m4a"
    outside.write_bytes(b"audio")
    bridge = _bridge(tmp_path, watch=watch, output=watch)
    result = bridge.delete_batch_item("../ausserhalb.m4a")
    assert result["ok"] is False
    assert outside.exists()


def test_delete_batch_item_is_refused_while_a_batch_runs(tmp_path: Path) -> None:
    watch = tmp_path / "sync"
    watch.mkdir()
    _recording(watch, "sitzung")
    bridge = _bridge(tmp_path, watch=watch, output=watch)
    bridge.scan_batch({})
    bridge._active_batch_id = "batch-1"
    result = bridge.delete_batch_item("sitzung.m4a")
    assert result["ok"] is False
    assert (watch / "sitzung.m4a").exists()

"""Löschen einer Aufnahmefamilie über den Papierkorb."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from bort.recording_delete import (
    DeleteError,
    default_trash_dir,
    delete_recording_family,
    move_to_trash,
    recording_family,
)


@pytest.fixture(autouse=True)
def _trash_in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Papierkorb in ein temporäres Verzeichnis umbiegen.

    ``gio trash`` wird für die Tests abgeschaltet: es schiebt in den echten
    Papierkorb des Systems und in mount-eigene Papierkörbe, was die
    Testumgebung des Rechners verändern würde.
    """
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr("bort.recording_delete._gio_trash", lambda _path: False)


def _family(day: Path) -> Path:
    audio = day / "aufnahme.m4a"
    audio.write_bytes(b"audio")
    (day / "aufnahme.txt").write_text("text", encoding="utf-8")
    (day / "aufnahme.md").write_text("markdown", encoding="utf-8")
    (day / "aufnahme.csv").write_text("csv", encoding="utf-8")
    (day / "aufnahme.review.json").write_text("{}", encoding="utf-8")
    (day / "aufnahme.json").write_text("{}", encoding="utf-8")
    (day / "aufnahme.markers.json").write_text("{}", encoding="utf-8")
    (day / "fremd.txt").write_text("gehört nicht dazu", encoding="utf-8")
    return audio


def test_recording_family_collects_audio_and_all_artifacts(tmp_path: Path) -> None:
    day = tmp_path / "2026-10-23"
    day.mkdir()
    audio = _family(day)
    names = [path.name for path in recording_family(audio)]
    assert names == [
        "aufnahme.m4a",
        "aufnahme.txt",
        "aufnahme.md",
        "aufnahme.csv",
        "aufnahme.review.json",
        "aufnahme.markers.json",
        "aufnahme.json",
    ]
    # Dateien anderer Aufnahmen bleiben unberührt.
    assert (day / "fremd.txt").exists()


def test_delete_recording_family_moves_every_artifact_to_trash(tmp_path: Path) -> None:
    day = tmp_path / "2026-10-23"
    day.mkdir()
    audio = _family(day)
    moved = delete_recording_family(audio)
    assert len(moved) == 7
    assert not audio.exists()
    assert not (day / "aufnahme.txt").exists()
    assert not (day / "aufnahme.review.json").exists()
    # Unbeteiligte Datei im selben Ordner bleibt liegen.
    assert (day / "fremd.txt").exists()
    # Alles liegt im BoRT-Papierkorb, nicht mehr im Quellordner.
    trash = default_trash_dir()
    assert trash.is_dir()
    assert len(list(trash.iterdir())) == 7


def test_delete_recording_family_reports_missing_file(tmp_path: Path) -> None:
    with pytest.raises(DeleteError):
        delete_recording_family(tmp_path / "gibt-es-nicht.m4a")


def test_move_to_trash_prefers_system_trash_when_gio_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Meldet gio Erfolg, ist die Datei weg und der BoRT-Papierkorb bleibt leer."""
    target = tmp_path / "weg.m4a"
    target.write_bytes(b"x")

    def fake_gio(path: Path) -> bool:
        path.unlink()
        return True

    monkeypatch.setattr("bort.recording_delete._gio_trash", fake_gio)
    move_to_trash(target)
    assert not target.exists()
    assert not default_trash_dir().exists()


def test_move_to_trash_falls_back_to_bort_trash_when_gio_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Schlägt gio fehl, wandert die Datei in den BoRT-Papierkorb."""
    monkeypatch.setattr("bort.recording_delete._gio_trash", lambda _path: False)
    target = tmp_path / "weg.m4a"
    target.write_bytes(b"x")
    move_to_trash(target)
    assert not target.exists()
    assert len(list(default_trash_dir().iterdir())) == 1


def test_default_trash_dir_follows_xdg_data_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "custom"))
    assert default_trash_dir() == tmp_path / "custom" / "BoRT" / "trash"
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert default_trash_dir() == Path.home() / ".local" / "share" / "BoRT" / "trash"
    assert os.environ.get("XDG_DATA_HOME") is None

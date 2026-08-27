"""Drag & Drop: übernommene Pfade landen in derselben Registrierung wie Dialoge."""

from pathlib import Path

from bort.app import Bridge
from bort.audio import SUPPORTED_AUDIO_EXTS
from bort.config import Config


def _bridge(tmp_path: Path) -> Bridge:
    return Bridge(config=Config(path=tmp_path / "settings.json"))


def test_dropped_audio_path_registers_like_file_dialog(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    audio = tmp_path / "aufnahme.m4a"
    audio.write_bytes(b"")

    result = bridge.set_dropped_path("audio", str(audio))

    assert result["ok"] is True
    assert Path(result["path"]) == audio
    assert bridge._paths["audio"] == audio


def test_dropped_marker_path_registers(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    marker = tmp_path / "marker.json"
    marker.write_text("{}", encoding="utf-8")

    assert bridge.set_dropped_path("marker", str(marker))["ok"] is True
    assert bridge._paths["marker"] == marker


def test_dropped_watch_dir_persists_last_watch_dir(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    watch_dir = tmp_path / "sync"
    watch_dir.mkdir()

    result = bridge.set_dropped_path("watch", str(watch_dir))

    assert result["ok"] is True
    reloaded = Bridge(config=Config(path=tmp_path / "settings.json"))
    assert reloaded._paths["watch"] == watch_dir


def test_dropped_watch_rejects_files(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    file = tmp_path / "kein-ordner.wav"
    file.write_bytes(b"")

    result = bridge.set_dropped_path("watch", str(file))
    assert result["ok"] is False
    assert bridge._paths.get("watch") != file


def test_dropped_audio_rejects_unsupported_extension(tmp_path: Path) -> None:
    """Backend-Gate: Extension wird gegen SUPPORTED_AUDIO_EXTS geprüft."""
    bridge = _bridge(tmp_path)
    text = tmp_path / "notizen.txt"
    text.write_text("", encoding="utf-8")

    result = bridge.set_dropped_path("audio", str(text))

    assert result["ok"] is False
    assert ".mp3" in result["error"]
    for ext in sorted(SUPPORTED_AUDIO_EXTS):
        assert ext in result["error"]
    assert bridge._paths.get("audio") != text


def test_dropped_target_needs_existing_file(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    missing = tmp_path / "fehlt.mp3"

    result = bridge.set_dropped_path("audio", str(missing))
    assert result["ok"] is False


def test_dropped_target_rejects_unknown_kind_and_empty_path(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    assert bridge.set_dropped_path("library", str(tmp_path))["ok"] is False
    assert bridge.set_dropped_path("audio", "")["ok"] is False

"""Persistenz: Theme-Wahl und zuletzt genutzter Review-Ordner."""

import json
from pathlib import Path

from bort.app import Bridge
from bort.config import Config


def _bridge_with_config(tmp_path: Path) -> Bridge:
    cfg = Config(path=tmp_path / "settings.json")
    return Bridge(config=cfg)


def test_set_theme_persists_and_initial_state_returns_it(tmp_path):
    bridge = _bridge_with_config(tmp_path)
    assert bridge.initial_state()["theme"] == "dark"  # Default

    result = bridge.set_theme("light")
    assert result == {"ok": True, "theme": "light"}

    # neue Bridge aus derselben Config-Datei -> Wahl bleibt erhalten
    reloaded = Bridge(config=Config(path=tmp_path / "settings.json"))
    assert reloaded.initial_state()["theme"] == "light"


def test_set_theme_rejects_garbage_defaults_to_dark(tmp_path):
    bridge = _bridge_with_config(tmp_path)
    assert bridge.set_theme("bogus")["theme"] == "dark"


def test_pick_review_remembers_folder(tmp_path, monkeypatch):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"")
    review = tmp_path / "clip.review.json"
    review.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "audio_path": str(audio),
                "segments": [],
                "speaker_map": {},
                "markers": [],
                "bookmarks": [],
                "base_name": "clip",
                "formats": ["txt"],
            }
        ),
        encoding="utf-8",
    )
    bridge = _bridge_with_config(tmp_path)
    bridge.window = object()
    monkeypatch.setattr(Bridge, "_dialog", lambda self, *a, **k: str(review))

    assert bridge.pick_review_file()["ok"]
    # Im Speicher gemerkt (nächster Dialog öffnet dort) ...
    assert bridge._paths["review"] == review
    # ... und in der Config persistiert.
    reloaded = Bridge(config=Config(path=tmp_path / "settings.json"))
    assert reloaded._paths["review"] == review


def test_save_output_options_persists_immediately(tmp_path):
    bridge = _bridge_with_config(tmp_path)
    result = bridge.save_output_options(
        {
            "backend": "whisperx",
            "language": "de",
            "task": "transcribe",
            "whisperx_model": "medium",
            "min_speakers": "2",
            "max_speakers": "8",
            "formats": ["md", "tsv", "exe"],
            "keep_wav": True,
            "verbose": False,
            "no_diarize": True,
            "auto_markers": False,
            "performance_profile": "fast",
            "colocate": False,
        }
    )
    assert result == {"ok": True}

    reloaded = Bridge(config=Config(path=tmp_path / "settings.json"))
    settings = reloaded.initial_state()["settings"]
    assert settings["backend"] == "whisperx"
    assert settings["language"] == "de"
    assert settings["task"] == "transcribe"
    assert settings["whisperx_model"] == "medium"
    assert settings["min_speakers"] == "2"
    assert settings["max_speakers"] == "8"
    assert settings["formats"] == ["md", "tsv"]  # "exe" verworfen
    assert settings["keep_wav"] is True
    assert settings["no_diarize"] is True
    assert settings["auto_markers"] is False
    assert settings["performance_profile"] == "fast"
    assert settings["colocate"] is False


def test_save_output_options_rejects_non_dict(tmp_path):
    bridge = _bridge_with_config(tmp_path)
    assert bridge.save_output_options("quatsch")["ok"] is False


def test_save_output_options_rejects_invalid_global_values(tmp_path):
    bridge = _bridge_with_config(tmp_path)

    assert bridge.save_output_options({"backend": "cloud"})["ok"] is False
    assert bridge.save_output_options({"min_speakers": "hundert"})["ok"] is False

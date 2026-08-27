"""Tests für die Konfigurationspersistenz."""

import json
import os
import tempfile
from pathlib import Path

from bort import config as config_module
from bort.config import Config


def test_config_load_save() -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        path = Path(f.name)

    try:
        config = Config(path)
        config.set_path("last_model_path", Path("/home/user/models/ggml.bin"))
        config.set("last_language", "de")
        config.save()

        config2 = Config(path)
        assert config2.get_path("last_model_path") == Path("/home/user/models/ggml.bin")
        assert config2.get("last_language") == "de"
    finally:
        path.unlink()


def test_config_get_path_missing_key() -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        path = Path(f.name)

    try:
        config = Config(path)
        assert config.get_path("missing_key") is None
        config.set("missing_key", "/some/path")
        assert config.get_path("missing_key") == Path("/some/path")
    finally:
        path.unlink()


def test_config_save_replaces_atomically_and_leaves_no_debris(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "settings.json"
    config = Config(path)
    config.set("last_theme", "light")

    replaced: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy_replace(src: str, dst: str) -> None:
        replaced.append((src, dst))
        real_replace(src, dst)

    monkeypatch.setattr(config_module.os, "replace", spy_replace)

    config.save()

    assert len(replaced) == 1
    source, destination = replaced[0]
    assert Path(destination) == path
    assert Path(source) != path  # geschrieben wird ins Tempfile ...
    assert Path(source).parent == path.parent  # ... im selben Verzeichnis
    assert json.loads(path.read_text(encoding="utf-8"))["last_theme"] == "light"
    assert [entry.name for entry in tmp_path.iterdir()] == ["settings.json"]


def test_config_save_failure_keeps_previous_file_intact(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "settings.json"
    config = Config(path)
    config.set("last_theme", "dark")
    config.save()
    config.set("last_theme", "light")

    def failing_dump(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(config_module.json, "dump", failing_dump)

    config.save()  # OSError wird geloggt, nicht geworfen.

    assert json.loads(path.read_text(encoding="utf-8"))["last_theme"] == "dark"
    assert [entry.name for entry in tmp_path.iterdir()] == ["settings.json"]

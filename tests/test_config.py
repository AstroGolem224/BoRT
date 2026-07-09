"""Tests für die Konfigurationspersistenz."""

import tempfile
from pathlib import Path

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

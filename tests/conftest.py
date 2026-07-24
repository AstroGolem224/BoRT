"""Gemeinsame Fixtures: Tests dürfen nie die echte Nutzer-Config anfassen."""

import pytest

import bort.config


@pytest.fixture(autouse=True)
def _isolierte_config(tmp_path, monkeypatch):
    """Lenkt jede parameterlose ``Config()`` auf eine Wegwerf-Datei um.

    Ohne diese Fixture schreiben Bridge-Tests in ``~/.config/bort/settings.json``
    und überschreiben dort echte Nutzereinstellungen (passiert; siehe Git-Historie).
    """
    monkeypatch.setattr(
        bort.config, "DEFAULT_CONFIG_PATH", tmp_path / "settings.json"
    )

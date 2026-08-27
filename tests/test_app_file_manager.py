"""Plattform-Dispatch für das Öffnen von Ordnern im Dateimanager."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from bort import app


def test_open_path_dispatches_to_xdg_open_on_linux(
    monkeypatch, tmp_path: Path
) -> None:
    opened: list[list[str]] = []
    monkeypatch.setattr(app.sys, "platform", "linux")
    monkeypatch.setattr(app.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(app.subprocess, "Popen", lambda cmd, **_kwargs: opened.append(cmd))

    assert app.open_path_in_file_manager(tmp_path) is True

    assert opened == [["xdg-open", str(tmp_path)]]


def test_open_path_dispatches_to_open_on_macos(monkeypatch, tmp_path: Path) -> None:
    opened: list[list[str]] = []
    monkeypatch.setattr(app.sys, "platform", "darwin")
    monkeypatch.setattr(app.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(app.subprocess, "Popen", lambda cmd, **_kwargs: opened.append(cmd))

    assert app.open_path_in_file_manager(tmp_path) is True

    assert opened == [["open", str(tmp_path)]]


def test_open_path_dispatches_to_explorer_on_windows(
    monkeypatch, tmp_path: Path
) -> None:
    opened: list[list[str]] = []
    monkeypatch.setattr(app.sys, "platform", "win32")
    monkeypatch.setattr(app.shutil, "which", lambda name: f"C:/Windows/{name}.exe")
    monkeypatch.setattr(app.subprocess, "Popen", lambda cmd, **_kwargs: opened.append(cmd))

    assert app.open_path_in_file_manager(tmp_path) is True

    assert opened == [["explorer", str(tmp_path)]]


def test_open_path_fails_with_warning_when_opener_missing(
    monkeypatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    opened: list[list[str]] = []
    monkeypatch.setattr(app.sys, "platform", "linux")
    monkeypatch.setattr(app.shutil, "which", lambda _name: None)
    monkeypatch.setattr(app.subprocess, "Popen", lambda cmd, **_kwargs: opened.append(cmd))

    with caplog.at_level(logging.WARNING):
        assert app.open_path_in_file_manager(tmp_path) is False

    assert opened == []
    assert "Dateimanager" in caplog.text


def test_open_path_fails_with_warning_when_popen_raises(
    monkeypatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(app.sys, "platform", "linux")
    monkeypatch.setattr(app.shutil, "which", lambda name: f"/usr/bin/{name}")

    def failing_popen(_cmd, **_kwargs) -> None:
        raise OSError("spawn failed")

    monkeypatch.setattr(app.subprocess, "Popen", failing_popen)

    with caplog.at_level(logging.WARNING):
        assert app.open_path_in_file_manager(tmp_path) is False

    assert "Dateimanager" in caplog.text

"""Robustes Finden des whisperX-JSON-Ergebnisses in verunreinigtem stdout."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from bort import streaming
from bort import whisperx_backend as backend


def _patch_stdout(monkeypatch: pytest.MonkeyPatch, stdout: str) -> None:
    monkeypatch.setattr(backend, "_ensure_backend_available", lambda: None)
    monkeypatch.setattr(streaming, "run_stream_progress", lambda cmd, **_kwargs: (stdout, ""))


def test_prefix_lines_with_brace_are_ignored_and_valid_json_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.dumps({"segments": [{"start": 0, "end": 1, "text": "Hallo"}], "language": "de"})
    _patch_stdout(
        monkeypatch,
        "{'progress': 42}\n"  # Python-Dict-Literal: kein gültiges JSON.
        "warn { kaputt\n"
        + payload
        + "\nnachlauf\n",
    )

    data = backend._run_whisperx(Path("audio.wav"), None, "medium", None, None)

    assert data["language"] == "de"
    assert data["segments"][0]["text"] == "Hallo"


def test_metric_json_line_loses_against_segments_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Eine gültige JSON-Störzeile darf nicht als Ergebnis durchgehen."""
    payload = json.dumps({"segments": [{"start": 0, "end": 1, "text": "Hi"}]})
    _patch_stdout(monkeypatch, '{"metrics": 1}\n' + payload + "\n")

    data = backend._run_whisperx(Path("audio.wav"), None, "medium", None, None)

    assert data == {"segments": [{"start": 0, "end": 1, "text": "Hi"}]}


def test_json_line_without_segments_kept_as_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ohne segments-Zeile gilt weiterhin die erste gültige JSON-Zeile."""
    _patch_stdout(monkeypatch, '{"metrics": 1}\n')

    data = backend._run_whisperx(Path("audio.wav"), None, "medium", None, None)

    assert data == {"metrics": 1}


def test_metric_line_loses_against_pretty_printed_segments_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gültige JSON-Störzeile verliert gegen das mehrzeilige Ergebnis-Dokument."""
    _patch_stdout(
        monkeypatch,
        '{"metrics": 1}\n'
        '{\n  "language": "de",\n'
        '  "segments": [{"start": 0, "end": 1, "text": "Hi"}]\n'
        "}\n",
    )

    data = backend._run_whisperx(Path("audio.wav"), None, "medium", None, None)

    assert data["language"] == "de"
    assert data["segments"][0]["text"] == "Hi"


def test_pretty_printed_first_brace_line_logs_no_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ein reines `{` ist Pretty-Print-Erste-Zeile, kein Müll: keine Warnung."""
    _patch_stdout(monkeypatch, '{\n  "segments": []\n}\n')

    with caplog.at_level(logging.DEBUG, logger="bort.whisperx_backend"):
        data = backend._run_whisperx(Path("audio.wav"), None, "medium", None, None)

    assert data == {"segments": []}
    assert not [
        r
        for r in caplog.records
        if r.levelno >= logging.WARNING and r.name == "bort.whisperx_backend"
    ]


def test_missing_json_raises_whisperx_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_stdout(monkeypatch, "nur Text, kein JSON")

    with pytest.raises(backend.WhisperXError, match="kein gültiges JSON"):
        backend._run_whisperx(Path("audio.wav"), None, "medium", None, None)


def test_pretty_printed_json_falls_back_to_first_brace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_stdout(
        monkeypatch,
        'log zeile\n{\n  "language": "de",\n  "segments": []\n}\n',
    )

    data = backend._run_whisperx(Path("audio.wav"), None, "medium", None, None)

    assert data == {"language": "de", "segments": []}

"""Tests für Marker-Laden."""

import json
import tempfile
from pathlib import Path

import pytest

from bort.markers import MarkerError, SpeakerMarker, load_markers


def test_load_markers_full() -> None:
    data = {
        "speakers": {"SP1": "Alice", "SP2": "Bob"},
        "markers": [
            {"start": 0.0, "end": 10.0, "speaker": "SP1"},
            {"start": 10.0, "end": 20.0, "speaker": "SP2"},
        ],
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = Path(f.name)

    try:
        speaker_map, markers = load_markers(path)
        assert speaker_map == {"SP1": "Alice", "SP2": "Bob"}
        assert markers == [
            SpeakerMarker(0.0, 10.0, "SP1"),
            SpeakerMarker(10.0, 20.0, "SP2"),
        ]
    finally:
        path.unlink()


def test_load_markers_missing_file() -> None:
    with pytest.raises(MarkerError, match="nicht gefunden"):
        load_markers(Path("/does/not/exist.json"))


def test_load_markers_invalid_type() -> None:
    data = {"markers": "not-a-list"}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = Path(f.name)

    try:
        with pytest.raises(MarkerError, match="Liste"):
            load_markers(path)
    finally:
        path.unlink()


def test_load_markers_missing_field() -> None:
    data = {"markers": [{"start": 0.0, "end": 10.0}]}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = Path(f.name)

    try:
        with pytest.raises(MarkerError, match="fehlen"):
            load_markers(path)
    finally:
        path.unlink()

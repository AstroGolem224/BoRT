"""pick_review_file muss Segmente (mit speaker_id + Text) an JS liefern,
damit die Sprecher-Ansicht das Transkript live rendern kann."""

import json
from pathlib import Path

from bort.app import Bridge


def _write_review(tmp_path: Path) -> Path:
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"")
    data = {
        "schema_version": 1,
        "audio_path": str(audio),
        "segments": [
            {"start": 0.0, "end": 2.0, "speaker": "sprecher001", "text": "Hallo"},
            {"start": 2.0, "end": 4.0, "speaker": "sprecher002", "text": "Servus"},
        ],
        "speaker_map": {"sprecher001": "sprecher001", "sprecher002": "sprecher002"},
        "markers": [],
        "bookmarks": [],
        "base_name": "clip",
        "formats": ["txt"],
    }
    path = tmp_path / "clip.review.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_pick_review_returns_segments_with_speaker_ids(tmp_path, monkeypatch):
    review_path = _write_review(tmp_path)
    bridge = Bridge()
    bridge.window = object()  # nicht benutzt, _dialog wird gepatcht
    monkeypatch.setattr(Bridge, "_dialog", lambda self, *a, **k: str(review_path))

    result = bridge.pick_review_file()

    assert result["ok"]
    assert result["review_id"]
    segments = result["segments"]
    assert len(segments) == 2
    assert set(segments[0]) == {"start", "end", "speaker_id", "text"}
    speaker_ids = {s["id"] for s in result["speakers"]}
    assert segments[0]["speaker_id"] in speaker_ids
    assert segments[0]["text"] == "Hallo"

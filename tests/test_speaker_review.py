"""Tests für das Laden/Validieren von Speaker-Review-Sidecars."""

import json
import logging
from pathlib import Path

import pytest

from bort.markers import Bookmark, SpeakerMarker
from bort.speaker_review import ReviewData, ReviewError, load_review

VALID_DATA = {
    "schema_version": 1,
    "audio_path": "",
    "segments": [{"start": 0.0, "end": 1.0, "speaker": "SP1", "text": "Hallo"}],
    "speaker_map": {"SP1": "sprecher001"},
    "markers": [{"start": 0.0, "end": 1.0, "speaker": "SP1"}],
    "bookmarks": [{"time": 0.5, "label": "Wichtig", "type": "note", "color": ""}],
    "base_name": "session",
    "formats": ["txt"],
}


def test_load_review_success(tmp_path: Path) -> None:
    audio_path = tmp_path / "session.m4a"
    audio_path.write_bytes(b"")
    review_path = tmp_path / "session.review.json"
    review_path.write_text(
        json.dumps(dict(VALID_DATA, audio_path=str(audio_path))), encoding="utf-8"
    )
    result = load_review(review_path)
    assert isinstance(result, ReviewData)
    assert result.audio_path == audio_path
    assert result.segments[0].speaker == "SP1"
    assert result.speaker_map == {"SP1": "sprecher001"}
    assert result.markers == [SpeakerMarker(0.0, 1.0, "SP1")]
    assert result.bookmarks == [Bookmark(0.5, "Wichtig", "note", "")]
    assert result.base_name == "session"
    assert result.formats == ["txt"]


def test_load_review_missing_file() -> None:
    with pytest.raises(ReviewError, match="nicht gefunden"):
        load_review(Path("/does/not/exist.review.json"))


def test_load_review_invalid_json(tmp_path: Path) -> None:
    p = tmp_path / "broken.review.json"
    p.write_text("not json", encoding="utf-8")
    with pytest.raises(ReviewError, match="ungültig"):
        load_review(p)


def test_load_review_missing_field(tmp_path: Path) -> None:
    p = tmp_path / "incomplete.review.json"
    data = dict(VALID_DATA, audio_path=str(tmp_path / "x.m4a"))
    del data["speaker_map"]
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ReviewError, match="speaker_map"):
        load_review(p)


def test_load_review_unsupported_schema_version(tmp_path: Path) -> None:
    p = tmp_path / "future.review.json"
    p.write_text(
        json.dumps(dict(VALID_DATA, audio_path=str(tmp_path / "x.m4a"), schema_version=99)),
        encoding="utf-8",
    )
    with pytest.raises(ReviewError, match="schema_version"):
        load_review(p)


def test_load_review_missing_audio_file(tmp_path: Path) -> None:
    p = tmp_path / "session.review.json"
    p.write_text(
        json.dumps(dict(VALID_DATA, audio_path=str(tmp_path / "does-not-exist.m4a"))),
        encoding="utf-8",
    )
    with pytest.raises(ReviewError, match="Audio"):
        load_review(p)


def test_load_review_malformed_nested_segment_raises_review_error(tmp_path: Path) -> None:
    audio_path = tmp_path / "session.m4a"
    audio_path.write_bytes(b"")
    p = tmp_path / "session.review.json"
    data = dict(VALID_DATA, audio_path=str(audio_path))
    data["segments"] = [{"start": 0.0, "end": 1.0, "text": "Hallo"}]
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ReviewError, match="segments"):
        load_review(p)


def test_load_review_rejects_path_traversal_base_name(tmp_path: Path) -> None:
    audio_path = tmp_path / "session.m4a"
    audio_path.write_bytes(b"")
    p = tmp_path / "session.review.json"
    p.write_text(
        json.dumps(dict(VALID_DATA, audio_path=str(audio_path), base_name="../../etc/evil")),
        encoding="utf-8",
    )
    with pytest.raises(ReviewError, match="base_name"):
        load_review(p)


def test_load_review_rejects_non_string_audio_path(tmp_path: Path) -> None:
    p = tmp_path / "session.review.json"
    p.write_text(json.dumps(dict(VALID_DATA, audio_path=123)), encoding="utf-8")
    with pytest.raises(ReviewError, match="audio_path"):
        load_review(p)


def test_load_review_rejects_unknown_format(tmp_path: Path) -> None:
    audio_path = tmp_path / "session.m4a"
    audio_path.write_bytes(b"")
    p = tmp_path / "session.review.json"
    p.write_text(
        json.dumps(dict(VALID_DATA, audio_path=str(audio_path), formats=["exe"])), encoding="utf-8"
    )
    with pytest.raises(ReviewError, match="formats"):
        load_review(p)


def test_load_review_v3_validates_voiceprints_and_metrics(tmp_path: Path) -> None:
    audio_path = tmp_path / "session.m4a"
    audio_path.write_bytes(b"")
    path = tmp_path / "session.review.json"
    data = dict(VALID_DATA, audio_path=str(audio_path), schema_version=3)
    data.update(
        speaker_embeddings={"SP1": [3.0, 4.0]},
        embedding_model="pyannote/speaker-diarization-3.1",
        runtime_metrics={"total_seconds": 4.2},
        run_metadata={"backend": "whisperx", "model": "large-v3-turbo"},
    )
    path.write_text(json.dumps(data), encoding="utf-8")

    review = load_review(path)

    assert review.speaker_embeddings["SP1"] == pytest.approx([0.6, 0.8])
    assert review.embedding_model == "pyannote/speaker-diarization-3.1"
    assert review.runtime_metrics == {"total_seconds": 4.2}
    assert review.run_metadata["model"] == "large-v3-turbo"


def test_load_review_v3_drops_unknown_embedding_speaker(tmp_path: Path, caplog) -> None:
    """Ein Embedding ohne Eintrag in der speaker_map darf die Datei nicht
    unlesbar machen: die Diarisierung liefert es auch fuer Sprecher, die kein
    Segment gewonnen haben."""
    audio_path = tmp_path / "session.m4a"
    audio_path.write_bytes(b"")
    path = tmp_path / "session.review.json"
    data = dict(VALID_DATA, audio_path=str(audio_path), schema_version=3)
    known_speaker = next(iter(data["speaker_map"]))
    data.update(
        speaker_embeddings={known_speaker: [3.0, 4.0], "UNKNOWN": [1.0, 0.0]},
        embedding_model="embed-v1",
    )
    path.write_text(json.dumps(data), encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="bort.speaker_review"):
        review = load_review(path)

    assert set(review.speaker_embeddings) == {known_speaker}
    assert "UNKNOWN" in caplog.text

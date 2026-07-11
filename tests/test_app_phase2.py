from pathlib import Path

import pytest

from bort.app import _representative_segment
from bort.controller.playback import PlaybackError
from bort.controller.speaker_edit import RegisteredReview, SpeakerEditError
from bort.speakers import SpeakerSegment


def _review(tmp_path: Path) -> RegisteredReview:
    return RegisteredReview(
        audio_path=tmp_path / "meeting.wav",
        segments=[
            SpeakerSegment(-1, 1, "Alice", "invalid"),
            SpeakerSegment(4, 7, "Alice", "valid"),
            SpeakerSegment(8, 9, "Bob", "other"),
        ],
        speaker_map={"S1": "Alice", "S2": "Bob", "S3": "No audio"},
        markers=[],
        bookmarks=[],
        output_dir=tmp_path,
        base_name="meeting",
        formats=["txt"],
        segment_ids=["S1", "S1", "S2"],
    )


def test_representative_segment_uses_registered_id_and_valid_bounds(tmp_path: Path) -> None:
    segment = _representative_segment(_review(tmp_path), "S1")
    assert (segment.start, segment.end, segment.text) == (4, 7, "valid")


def test_representative_segment_rejects_unknown_or_missing_audio(tmp_path: Path) -> None:
    review = _review(tmp_path)
    with pytest.raises(SpeakerEditError, match="Unbekannte Sprecher-ID"):
        _representative_segment(review, "unknown")
    with pytest.raises(PlaybackError, match="kein gültiges Audiosegment"):
        _representative_segment(review, "S3")

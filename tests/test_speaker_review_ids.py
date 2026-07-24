"""Schema v2: Segment-Sprecher-IDs überleben Umbenennen + Neuladen.

Regression: Bei doppelten Anzeigenamen (zwei IDs -> "Dennis") kollabierte die
Namens-Rückabbildung beim Neuladen, ein Teil der Abspielen-Buttons fand keine
Segmente mehr.
"""

import json
from pathlib import Path

from bort.controller.speaker_edit import RegisteredReview, SpeakerEditController
from bort.markers import SpeakerMarker
from bort.speaker_review import load_review
from bort.speakers import SpeakerSegment


def _register_fresh(tmp_path: Path) -> tuple[SpeakerEditController, str, Path]:
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"")
    controller = SpeakerEditController()
    review = RegisteredReview(
        audio_path=audio,
        segments=[
            SpeakerSegment(0.0, 1.0, "SPEAKER_00", "hallo"),
            SpeakerSegment(1.0, 2.0, "SPEAKER_01", "servus"),
            SpeakerSegment(2.0, 3.0, "SPEAKER_00", "genau"),
        ],
        speaker_map={"SPEAKER_00": "SPEAKER_00", "SPEAKER_01": "SPEAKER_01"},
        markers=[SpeakerMarker(0.0, 1.0, "SPEAKER_00")],
        bookmarks=[],
        output_dir=tmp_path,
        base_name="clip",
        formats=["txt"],
    )
    review_id = controller.register(review)
    return controller, review_id, tmp_path / "clip.review.json"


def test_duplicate_names_keep_distinct_segment_ids_after_reload(tmp_path):
    controller, review_id, review_json = _register_fresh(tmp_path)

    # Beide Sprecher bekommen denselben Anzeigenamen.
    controller.apply(review_id, {"SPEAKER_00": "Dennis", "SPEAKER_01": "Dennis"})
    assert review_json.exists()

    reloaded = load_review(review_json)
    fresh = RegisteredReview(
        audio_path=reloaded.audio_path,
        segments=reloaded.segments,
        speaker_map=reloaded.speaker_map,
        markers=reloaded.markers,
        bookmarks=reloaded.bookmarks,
        output_dir=tmp_path,
        base_name=reloaded.base_name,
        formats=reloaded.formats,
        segment_ids=list(reloaded.segment_ids),
        marker_ids=list(reloaded.marker_ids),
    )
    fresh_controller = SpeakerEditController()
    fresh_id = fresh_controller.register(fresh)
    stored = fresh_controller.get(fresh_id)

    # Kernaussage: die IDs bleiben pro Segment unterschieden.
    assert stored.segment_ids == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00"]
    assert stored.marker_ids == ["SPEAKER_00"]


def test_schema_v1_files_still_load_with_name_fallback(tmp_path):
    audio = tmp_path / "old.wav"
    audio.write_bytes(b"")
    review_json = tmp_path / "old.review.json"
    review_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "audio_path": str(audio),
                "segments": [
                    {"start": 0.0, "end": 1.0, "speaker": "Anna", "text": "hi"}
                ],
                "speaker_map": {"SPEAKER_00": "Anna"},
                "markers": [],
                "bookmarks": [],
                "base_name": "old",
                "formats": ["txt"],
            }
        ),
        encoding="utf-8",
    )
    reloaded = load_review(review_json)
    assert reloaded.segment_ids == []  # v1: keine IDs, Fallback greift in register()

    controller = SpeakerEditController()
    fresh_id = controller.register(
        RegisteredReview(
            audio_path=reloaded.audio_path,
            segments=reloaded.segments,
            speaker_map=reloaded.speaker_map,
            markers=reloaded.markers,
            bookmarks=reloaded.bookmarks,
            output_dir=tmp_path,
            base_name=reloaded.base_name,
            formats=reloaded.formats,
        )
    )
    assert controller.get(fresh_id).segment_ids == ["SPEAKER_00"]

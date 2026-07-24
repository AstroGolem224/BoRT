"""rename_base muss die komplette Dateifamilie umbenennen und das JSON patchen."""

import json
from pathlib import Path

import pytest

from bort.controller.speaker_edit import (
    RegisteredReview,
    SpeakerEditController,
    SpeakerEditError,
)


def _make_review(tmp_path: Path, base: str = "alt") -> tuple[SpeakerEditController, str, Path]:
    audio = tmp_path / f"{base}.m4a"
    audio.write_bytes(b"audio")
    review_json = tmp_path / f"{base}.review.json"
    review_json.write_text(
        json.dumps({"base_name": base, "audio_path": str(audio), "schema_version": 1}),
        encoding="utf-8",
    )
    (tmp_path / f"{base}.txt").write_text("text", encoding="utf-8")
    controller = SpeakerEditController()
    review_id = controller.register(
        RegisteredReview(
            audio_path=audio,
            segments=[],
            speaker_map={},
            markers=[],
            bookmarks=[],
            output_dir=tmp_path,
            base_name=base,
            formats=["txt"],
            review_path=review_json,
        )
    )
    return controller, review_id, tmp_path


def test_rename_base_renames_family_and_patches_json(tmp_path: Path) -> None:
    controller, review_id, root = _make_review(tmp_path)
    review = controller.rename_base(review_id, "neu")
    assert (root / "neu.review.json").exists()
    assert (root / "neu.m4a").exists()
    assert (root / "neu.txt").exists()
    assert not (root / "alt.review.json").exists()
    assert not (root / "alt.m4a").exists()
    data = json.loads((root / "neu.review.json").read_text(encoding="utf-8"))
    assert data["base_name"] == "neu"
    assert data["audio_path"] == str(root / "neu.m4a")
    assert review.base_name == "neu"
    assert review.audio_path == root / "neu.m4a"
    assert review.review_path == root / "neu.review.json"


def test_rename_base_rejects_existing_target(tmp_path: Path) -> None:
    controller, review_id, root = _make_review(tmp_path)
    (root / "neu.txt").write_text("belegt", encoding="utf-8")
    with pytest.raises(SpeakerEditError, match="existiert bereits"):
        controller.rename_base(review_id, "neu")
    assert (root / "alt.m4a").exists()
    assert (root / "alt.review.json").exists()


def test_rename_base_rejects_path_separators(tmp_path: Path) -> None:
    controller, review_id, _root = _make_review(tmp_path)
    with pytest.raises(SpeakerEditError, match="Ungültiger Dateiname"):
        controller.rename_base(review_id, "../boese")

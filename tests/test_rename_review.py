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


def test_rename_recording_family_renames_neighbors_and_patches_json(tmp_path):
    import json

    from bort.controller.speaker_edit import (
        SpeakerEditError,
        rename_recording_family,
    )

    audio = tmp_path / "alt.m4a"
    audio.write_bytes(b"a")
    (tmp_path / "alt.txt").write_text("t", encoding="utf-8")
    (tmp_path / "alt.review.json").write_text(
        json.dumps({"base_name": "alt", "audio_path": str(audio)}), encoding="utf-8"
    )
    (tmp_path / "alt.json").write_text(
        json.dumps({"version": 1, "file": "alt.m4a"}), encoding="utf-8"
    )

    new_audio = rename_recording_family(audio, "neu")
    assert new_audio == tmp_path / "neu.m4a"
    assert not audio.exists()
    assert (tmp_path / "neu.txt").is_file()
    review = json.loads((tmp_path / "neu.review.json").read_text(encoding="utf-8"))
    assert review["base_name"] == "neu"
    assert review["audio_path"] == str(new_audio)
    sidecar = json.loads((tmp_path / "neu.json").read_text(encoding="utf-8"))
    assert sidecar["file"] == "neu.m4a"

    # Kollision: Ziel existiert -> Fehler, nichts umbenannt.
    (tmp_path / "besetzt.txt").write_text("x", encoding="utf-8")
    import pytest

    with pytest.raises(SpeakerEditError):
        rename_recording_family(new_audio, "besetzt")
    assert (tmp_path / "neu.m4a").is_file()


def test_rename_review_allows_bor_paired_recordings(tmp_path):
    import json

    from bort.app import Bridge
    from bort.config import Config

    audio = tmp_path / "clip.m4a"
    audio.write_bytes(b"a")
    (tmp_path / "clip.json").write_text(
        json.dumps({"version": 1, "file": "clip.m4a"}), encoding="utf-8"
    )
    review_path = tmp_path / "clip.review.json"
    review_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "audio_path": str(audio),
                "segments": [],
                "speaker_map": {},
                "markers": [],
                "bookmarks": [],
                "base_name": "clip",
                "formats": ["txt"],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "clip.txt").write_text("t", encoding="utf-8")

    bridge = Bridge(config=Config(path=tmp_path / "settings.json"))
    loaded = bridge._register_review_from_path(review_path)
    assert loaded["ok"] and loaded["rename_allowed"] is True
    result = bridge.rename_review(loaded["review_id"], "meeting_x")
    assert result["ok"], result
    assert (tmp_path / "meeting_x.m4a").is_file()
    assert (tmp_path / "meeting_x.json").is_file()
    sidecar = json.loads((tmp_path / "meeting_x.json").read_text(encoding="utf-8"))
    assert sidecar["file"] == "meeting_x.m4a"

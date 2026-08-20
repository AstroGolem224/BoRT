from __future__ import annotations

import json
from pathlib import Path

from bort.app import Bridge
from bort.config import Config
from bort.voice_profiles import VoiceCatalog


def _bridge(tmp_path: Path) -> Bridge:
    return Bridge(
        config=Config(path=tmp_path / "settings.json"),
        voice_catalog=VoiceCatalog(tmp_path / "catalog" / "profiles.json"),
    )


def test_initial_state_exposes_only_safe_voice_profile_metadata(tmp_path: Path) -> None:
    catalog = VoiceCatalog(tmp_path / "catalog.json")
    catalog.enroll("Anna", [1.0, 0.0], "embed-v1")
    bridge = Bridge(
        config=Config(path=tmp_path / "settings.json"),
        voice_catalog=catalog,
    )

    state = bridge.initial_state()["voice_catalog"]

    assert state["available"] is True
    assert state["names"] == ["Anna"]
    assert state["profiles"] == [
        {
            "id": catalog.list_profiles()[0].id,
            "name": "Anna",
            "has_voiceprint": True,
            "sample_count": 1,
        }
    ]
    assert "embedding" not in state["profiles"][0]


def test_confirmed_names_are_saved_but_generic_labels_are_skipped(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.save_voice_profile_names(
        {"sprecher001": "Anna Beispiel", "sprecher002": "sprecher002"}
    )

    assert result["ok"] is True
    assert result["saved"] == ["Anna Beispiel"]
    assert result["skipped"] == ["sprecher002"]
    assert bridge.voice_catalog is not None
    assert bridge.voice_catalog.names() == ["Anna Beispiel"]


def test_empty_or_invalid_catalog_submission_is_rejected(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    assert bridge.save_voice_profile_names({"sprecher001": "sprecher001"})["ok"] is False
    assert bridge.save_voice_profile_names(["Anna"])["ok"] is False


def test_profile_can_be_deleted_through_safe_bridge_api(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    created = bridge.voice_catalog.enroll("Anna")

    result = bridge.delete_voice_profile(created.id)

    assert result["ok"] is True
    assert result["voice_catalog"]["profiles"] == []
    assert bridge.delete_voice_profile(created.id)["ok"] is False


def test_review_voiceprint_is_suggested_then_enrolled_only_on_confirmation(
    tmp_path: Path,
) -> None:
    catalog = VoiceCatalog(tmp_path / "catalog.json")
    catalog.enroll("Anna", [1.0, 0.0], "embed-v1")
    bridge = Bridge(
        config=Config(path=tmp_path / "settings.json"),
        voice_catalog=catalog,
    )
    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"")
    review_path = tmp_path / "meeting.review.json"
    review_path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "audio_path": str(audio),
                "segments": [
                    {
                        "start": 0.0,
                        "end": 1.0,
                        "speaker": "sprecher001",
                        "speaker_id": "SPEAKER_00",
                        "text": "Hallo",
                    }
                ],
                "speaker_map": {"SPEAKER_00": "sprecher001"},
                "markers": [],
                "bookmarks": [],
                "base_name": "meeting",
                "formats": ["txt"],
                "speaker_embeddings": {"SPEAKER_00": [0.99, 0.1]},
                "embedding_model": "embed-v1",
            }
        ),
        encoding="utf-8",
    )

    loaded = bridge._register_review_from_path(review_path)

    assert loaded["speakers"][0]["name"] == "sprecher001"
    assert loaded["speakers"][0]["suggestions"][0]["name"] == "Anna"
    before = catalog.list_profiles()[0].sample_count

    saved = bridge.save_voice_profile_names(
        {"SPEAKER_00": "Anna"}, loaded["review_id"]
    )

    assert saved["ok"] is True
    assert saved["voiceprints_saved"] == 1
    assert catalog.list_profiles()[0].sample_count == before + 1

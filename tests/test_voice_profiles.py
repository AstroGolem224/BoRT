from __future__ import annotations

import json
import math
import stat
from pathlib import Path

import pytest

from bort.voice_profiles import VoiceCatalog, VoiceCatalogError


def test_name_only_profile_persists_with_private_permissions(tmp_path: Path) -> None:
    path = tmp_path / "private" / "voice_profiles.json"
    catalog = VoiceCatalog(path)

    created = catalog.enroll("  Anna   Beispiel  ")

    assert created.name == "Anna Beispiel"
    assert created.embedding is None and created.sample_count == 0
    assert VoiceCatalog(path).names() == ["Anna Beispiel"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_matching_is_model_scoped_and_sorted(tmp_path: Path) -> None:
    catalog = VoiceCatalog(tmp_path / "catalog.json")
    anna = catalog.enroll("Anna", [1.0, 0.0, 0.0], "embed-v1")
    catalog.enroll("Berta", [0.8, 0.6, 0.0], "embed-v1")
    catalog.enroll("Andere Engine", [1.0, 0.0, 0.0], "embed-v2")

    matches = catalog.match([0.99, 0.1, 0.0], "embed-v1", threshold=0.7)

    assert [match.name for match in matches] == ["Anna", "Berta"]
    assert matches[0].profile_id == anna.id
    assert matches[0].score > matches[1].score


def test_repeated_confirmations_update_normalized_centroid(tmp_path: Path) -> None:
    catalog = VoiceCatalog(tmp_path / "catalog.json")
    profile = catalog.enroll("Anna", [1.0, 0.0], "embed-v1")

    updated = catalog.enroll("Anna", [0.0, 1.0], "embed-v1", profile_id=profile.id)

    assert updated.sample_count == 2
    assert updated.embedding is not None
    assert math.sqrt(sum(value * value for value in updated.embedding)) == pytest.approx(1.0)
    assert updated.embedding == pytest.approx([2**-0.5, 2**-0.5])


def test_incompatible_or_non_finite_embeddings_are_rejected(tmp_path: Path) -> None:
    catalog = VoiceCatalog(tmp_path / "catalog.json")
    profile = catalog.enroll("Anna", [1.0, 0.0], "embed-v1")

    with pytest.raises(VoiceCatalogError, match="passt nicht"):
        catalog.enroll("Anna", [1.0, 0.0], "embed-v2", profile_id=profile.id)
    with pytest.raises(VoiceCatalogError, match="nicht-finite"):
        catalog.enroll("Berta", [float("nan"), 1.0], "embed-v1")


def test_corrupt_catalog_is_not_silently_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text("{kaputt", encoding="utf-8")

    with pytest.raises(VoiceCatalogError, match="geladen"):
        VoiceCatalog(path)

    assert path.read_text(encoding="utf-8") == "{kaputt"


def test_delete_and_schema_validation(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    catalog = VoiceCatalog(path)
    profile = catalog.enroll("Anna")
    catalog.delete(profile.id)
    assert VoiceCatalog(path).list_profiles() == []

    path.write_text(json.dumps({"schema_version": 99, "profiles": []}), encoding="utf-8")
    with pytest.raises(VoiceCatalogError, match="Schema-Version"):
        VoiceCatalog(path)

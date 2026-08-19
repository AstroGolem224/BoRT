"""Lokaler Namens- und Stimmprofilkatalog für bestätigte Sprecher."""

from __future__ import annotations

import json
import math
import os
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = 1
MAX_NAME_LENGTH = 120
MAX_EMBEDDING_DIMENSION = 4096
DEFAULT_MATCH_THRESHOLD = 0.75


class VoiceCatalogError(Exception):
    """Fehler beim Validieren oder Speichern des lokalen Stimmenkatalogs."""


def default_catalog_path() -> Path:
    """Liefert den XDG-konformen Standardpfad des lokalen Katalogs."""
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return base / "bort" / "voice_profiles.json"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _validate_name(name: str) -> str:
    if not isinstance(name, str):
        raise VoiceCatalogError("Profilname muss Text sein.")
    normalized = " ".join(name.split())
    if not normalized:
        raise VoiceCatalogError("Profilname darf nicht leer sein.")
    if len(normalized) > MAX_NAME_LENGTH:
        raise VoiceCatalogError(f"Profilname darf höchstens {MAX_NAME_LENGTH} Zeichen haben.")
    if any(ord(char) < 32 for char in normalized):
        raise VoiceCatalogError("Profilname enthält ungültige Steuerzeichen.")
    return normalized


def normalize_embedding(values: list[float]) -> list[float]:
    """Validiert und L2-normalisiert ein Embedding."""
    if not isinstance(values, list) or not 2 <= len(values) <= MAX_EMBEDDING_DIMENSION:
        raise VoiceCatalogError("Embedding hat eine ungültige Dimension.")
    try:
        vector = [float(value) for value in values]
    except (TypeError, ValueError) as exc:
        raise VoiceCatalogError("Embedding enthält ungültige Werte.") from exc
    if not all(math.isfinite(value) for value in vector):
        raise VoiceCatalogError("Embedding enthält nicht-finite Werte.")
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 1e-12:
        raise VoiceCatalogError("Embedding darf kein Nullvektor sein.")
    return [value / norm for value in vector]


@dataclass
class VoiceProfile:
    id: str
    name: str
    embedding: list[float] | None
    embedding_model: str | None
    sample_count: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class VoiceMatch:
    profile_id: str
    name: str
    score: float


class VoiceCatalog:
    """Atomar gespeicherter Katalog für Namen und optionale Stimm-Embeddings."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_catalog_path()
        self._lock = threading.RLock()
        self._profiles: dict[str, VoiceProfile] = {}
        self.load()

    def load(self) -> None:
        with self._lock:
            if not self.path.exists():
                self._profiles = {}
                return
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                message = f"Stimmenkatalog konnte nicht geladen werden: {exc}"
                raise VoiceCatalogError(message) from exc
            if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
                raise VoiceCatalogError("Stimmenkatalog hat eine unbekannte Schema-Version.")
            entries = raw.get("profiles")
            if not isinstance(entries, list):
                raise VoiceCatalogError("Stimmenkatalog enthält keine gültige Profilliste.")
            profiles: dict[str, VoiceProfile] = {}
            for entry in entries:
                profile = self._parse_profile(entry)
                if profile.id in profiles:
                    raise VoiceCatalogError("Stimmenkatalog enthält doppelte Profil-IDs.")
                profiles[profile.id] = profile
            self._profiles = profiles

    @staticmethod
    def _parse_profile(entry: Any) -> VoiceProfile:
        if not isinstance(entry, dict):
            raise VoiceCatalogError("Stimmenkatalog enthält einen ungültigen Profileintrag.")
        try:
            profile_id = str(entry["id"])
            name = _validate_name(entry["name"])
            embedding = entry.get("embedding")
            model = entry.get("embedding_model")
            sample_count = int(entry.get("sample_count", 0))
            created_at = str(entry["created_at"])
            updated_at = str(entry["updated_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise VoiceCatalogError("Stimmenkatalog enthält unvollständige Profildaten.") from exc
        if not profile_id or sample_count < 0:
            raise VoiceCatalogError("Stimmenkatalog enthält ungültige Profilmetadaten.")
        if embedding is None:
            if model is not None or sample_count != 0:
                raise VoiceCatalogError("Namensprofil enthält widersprüchliche Embedding-Daten.")
            normalized_embedding = None
            normalized_model = None
        else:
            if not isinstance(model, str) or not model.strip() or sample_count < 1:
                raise VoiceCatalogError("Stimmprofil enthält kein gültiges Embedding-Modell.")
            normalized_embedding = normalize_embedding(embedding)
            normalized_model = model.strip()
        return VoiceProfile(
            profile_id,
            name,
            normalized_embedding,
            normalized_model,
            sample_count,
            created_at,
            updated_at,
        )

    def list_profiles(self) -> list[VoiceProfile]:
        with self._lock:
            return sorted(
                (VoiceProfile(**asdict(profile)) for profile in self._profiles.values()),
                key=lambda profile: (profile.name.casefold(), profile.id),
            )

    def names(self) -> list[str]:
        """Liefert eindeutige Anzeigenamen für Auswahllisten."""
        return list(dict.fromkeys(profile.name for profile in self.list_profiles()))

    def enroll(
        self,
        name: str,
        embedding: list[float] | None = None,
        embedding_model: str | None = None,
        *,
        profile_id: str | None = None,
    ) -> VoiceProfile:
        """Legt einen Namen an oder ergänzt ein bestätigtes Embedding.

        Ohne ``profile_id`` wird ein eindeutig gleichnamiges Profil aktualisiert.
        Andernfalls wird ein neuer Eintrag angelegt. Mehrere Personen dürfen also
        denselben Anzeigenamen besitzen.
        """
        name = _validate_name(name)
        vector = normalize_embedding(embedding) if embedding is not None else None
        if vector is not None and (
            not isinstance(embedding_model, str) or not embedding_model.strip()
        ):
            raise VoiceCatalogError("Für ein Embedding ist eine Modellkennung erforderlich.")
        with self._lock:
            profile = self._resolve_enrollment_target(name, profile_id)
            model = embedding_model.strip() if isinstance(embedding_model, str) else None
            if (
                vector is not None
                and profile is not None
                and profile.embedding is not None
                and (
                    profile.embedding_model != model
                    or len(profile.embedding) != len(vector)
                )
            ):
                if profile_id is None:
                    # Modellwechsel erzeugen ein getrenntes Profil mit demselben
                    # Anzeigenamen; inkompatible Räume dürfen nie gemischt werden.
                    profile = None
                else:
                    raise VoiceCatalogError(
                        "Embedding-Modell oder Dimension passt nicht zum bestehenden Profil."
                    )
            timestamp = _now()
            if profile is None:
                profile = VoiceProfile(uuid4().hex, name, None, None, 0, timestamp, timestamp)
                self._profiles[profile.id] = profile
            else:
                profile.name = name
                profile.updated_at = timestamp
            if vector is not None:
                if profile.embedding is None:
                    profile.embedding = vector
                    profile.embedding_model = model
                    profile.sample_count = 1
                else:
                    count = profile.sample_count
                    centroid = [
                        (old * count + new) / (count + 1)
                        for old, new in zip(profile.embedding, vector, strict=True)
                    ]
                    profile.embedding = normalize_embedding(centroid)
                    profile.sample_count = count + 1
            self.save()
            return VoiceProfile(**asdict(profile))

    def _resolve_enrollment_target(
        self, name: str, profile_id: str | None
    ) -> VoiceProfile | None:
        if profile_id is not None:
            try:
                return self._profiles[profile_id]
            except KeyError as exc:
                raise VoiceCatalogError("Unbekannte Stimmprofil-ID.") from exc
        matches = [
            profile
            for profile in self._profiles.values()
            if profile.name.casefold() == name.casefold()
        ]
        return matches[0] if len(matches) == 1 else None

    def match(
        self,
        embedding: list[float],
        embedding_model: str,
        *,
        threshold: float = DEFAULT_MATCH_THRESHOLD,
        limit: int = 3,
    ) -> list[VoiceMatch]:
        """Liefert kompatible Vorschläge oberhalb der konservativen Schwelle."""
        vector = normalize_embedding(embedding)
        if not isinstance(embedding_model, str) or not embedding_model.strip():
            raise VoiceCatalogError("Embedding-Modell fehlt.")
        if not math.isfinite(threshold) or not -1.0 <= threshold <= 1.0:
            raise VoiceCatalogError("Ähnlichkeitsschwelle ist ungültig.")
        if limit < 1:
            return []
        with self._lock:
            matches = []
            for profile in self._profiles.values():
                if (
                    profile.embedding is None
                    or profile.embedding_model != embedding_model.strip()
                    or len(profile.embedding) != len(vector)
                ):
                    continue
                score = sum(
                    left * right for left, right in zip(profile.embedding, vector, strict=True)
                )
                if score >= threshold:
                    matches.append(VoiceMatch(profile.id, profile.name, score))
            return sorted(matches, key=lambda match: (-match.score, match.name.casefold()))[:limit]

    def delete(self, profile_id: str) -> None:
        with self._lock:
            if profile_id not in self._profiles:
                raise VoiceCatalogError("Unbekannte Stimmprofil-ID.")
            del self._profiles[profile_id]
            self.save()

    def save(self) -> None:
        """Schreibt den Katalog atomar und mit restriktiven Dateirechten."""
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.chmod(self.path.parent, 0o700)
                document = {
                    "schema_version": SCHEMA_VERSION,
                    "profiles": [asdict(profile) for profile in self.list_profiles()],
                }
                handle = tempfile.NamedTemporaryFile(
                    "w",
                    encoding="utf-8",
                    dir=self.path.parent,
                    prefix=f".{self.path.name}.",
                    delete=False,
                )
                temporary = Path(handle.name)
                try:
                    with handle:
                        json.dump(document, handle, ensure_ascii=False, indent=2)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.chmod(temporary, 0o600)
                    os.replace(temporary, self.path)
                    os.chmod(self.path, 0o600)
                finally:
                    temporary.unlink(missing_ok=True)
            except OSError as exc:
                message = f"Stimmenkatalog konnte nicht gespeichert werden: {exc}"
                raise VoiceCatalogError(message) from exc

"""Laden und Validieren von Speaker-Review-Sidecar-Dateien (`*.review.json`)."""

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

from .markers import Bookmark, SpeakerMarker
from .speakers import SpeakerSegment
from .voice_profiles import VoiceCatalogError, normalize_embedding
from .writers import FORMATS

logger = logging.getLogger(__name__)

SUPPORTED_SCHEMA_VERSIONS = {1, 2, 3}
REQUIRED_FIELDS = (
    "schema_version",
    "audio_path",
    "segments",
    "speaker_map",
    "markers",
    "bookmarks",
    "base_name",
    "formats",
)


class ReviewError(Exception):
    """Fehler beim Laden/Validieren einer Review-Sidecar-Datei."""


@dataclass(frozen=True)
class ReviewData:
    audio_path: Path
    segments: list[SpeakerSegment]
    speaker_map: dict[str, str]
    markers: list[SpeakerMarker]
    bookmarks: list[Bookmark]
    base_name: str
    formats: list[str]
    # Schema v2: stabile Sprecher-IDs pro Segment/Marker. Leer bei v1-Dateien;
    # dann rekonstruiert register() sie per Namens-Rückabbildung (verlustbehaftet
    # bei doppelten Anzeigenamen).
    segment_ids: list[str | None] = field(default_factory=list)
    marker_ids: list[str | None] = field(default_factory=list)
    speaker_embeddings: dict[str, list[float]] = field(default_factory=dict)
    embedding_model: str | None = None
    runtime_metrics: dict[str, float] = field(default_factory=dict)
    run_metadata: dict[str, object] = field(default_factory=dict)


def load_review(path: Path) -> ReviewData:
    """Lädt und validiert eine Review-Sidecar-Datei."""
    path = Path(path)
    if not path.exists():
        raise ReviewError(f"Review-Datei nicht gefunden: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ReviewError(f"Review-Datei ist ungültig (kein JSON): {exc}") from exc
    except OSError as exc:
        raise ReviewError(f"Review-Datei konnte nicht gelesen werden: {exc}") from exc
    if not isinstance(data, dict):
        raise ReviewError("Review-Datei ist ungültig (kein JSON-Objekt).")
    missing = [field for field in REQUIRED_FIELDS if field not in data]
    if missing:
        raise ReviewError(f"Review-Datei fehlt Pflichtfeld(er): {', '.join(missing)}")
    if data["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS:
        raise ReviewError(
            f"Nicht unterstützte schema_version: {data['schema_version']} "
            f"(erwartet: {sorted(SUPPORTED_SCHEMA_VERSIONS)})"
        )
    if not isinstance(data["audio_path"], str) or not data["audio_path"]:
        raise ReviewError(f"audio_path ist ungültig: {data['audio_path']!r}")
    audio_path = Path(data["audio_path"])
    if not audio_path.exists():
        raise ReviewError(f"Audio-Datei nicht mehr vorhanden: {audio_path}")
    base_name = data["base_name"]
    if (
        not isinstance(base_name, str)
        or not base_name
        or "/" in base_name
        or "\\" in base_name
        or base_name in {".", ".."}
    ):
        raise ReviewError(f"base_name ist ungültig (kein Pfadtrenner/'..' erlaubt): {base_name!r}")
    formats = data["formats"]
    if not isinstance(formats, list) or not all(
        isinstance(fmt, str) and fmt in FORMATS for fmt in formats
    ):
        raise ReviewError(f"formats enthält unbekannte(s) Format(e): {formats!r}")
    try:
        segments = [
            SpeakerSegment(
                start=float(s["start"]),
                end=float(s["end"]),
                speaker=str(s["speaker"]),
                text=str(s["text"]),
            )
            for s in data["segments"]
        ]
        markers = [
            SpeakerMarker(start=float(m["start"]), end=float(m["end"]), speaker=str(m["speaker"]))
            for m in data["markers"]
        ]
        bookmarks = [
            Bookmark(
                time=float(b["time"]),
                label=str(b.get("label", "")),
                type=str(b.get("type", "")),
                color=str(b.get("color", "")),
            )
            for b in data["bookmarks"]
        ]
        speaker_map = {str(k): str(v) for k, v in data["speaker_map"].items()}

        def read_ids(entries: list[dict]) -> list[str | None]:
            # Nur IDs übernehmen, die die speaker_map kennt; alles andere -> None
            # (dann greift die Namens-Rückabbildung in register()).
            ids: list[str | None] = []
            for entry in entries:
                value = entry.get("speaker_id")
                ids.append(value if isinstance(value, str) and value in speaker_map else None)
            return ids

        has_ids = any("speaker_id" in entry for entry in data["segments"])
        segment_ids = read_ids(data["segments"]) if has_ids else []
        marker_ids = read_ids(data["markers"]) if has_ids else []
        raw_embeddings = data.get("speaker_embeddings", {})
        embedding_model = data.get("embedding_model")
        if not isinstance(raw_embeddings, dict):
            raise TypeError("speaker_embeddings ist keine Map")
        if raw_embeddings and (
            not isinstance(embedding_model, str) or not embedding_model.strip()
        ):
            raise ValueError("embedding_model fehlt")
        speaker_embeddings = {
            str(speaker_id): normalize_embedding(vector)
            for speaker_id, vector in raw_embeddings.items()
            if str(speaker_id) in speaker_map
        }
        if len(speaker_embeddings) != len(raw_embeddings):
            # Die Diarisierung liefert Embeddings auch fuer Sprecher-IDs, die
            # kein Segment gewonnen haben; die speaker_map kennt sie nicht.
            # Ein Wurf machte solche Dateien unlesbar, obwohl nur ein nirgends
            # referenziertes Embedding fehlt -> verwerfen und protokollieren.
            unknown = sorted(set(map(str, raw_embeddings)) - set(speaker_embeddings))
            logger.warning(
                "Review-Datei %s: Embeddings ohne Eintrag in der speaker_map "
                "verworfen: %s",
                path,
                ", ".join(unknown),
            )
        raw_metrics = data.get("runtime_metrics", {})
        if not isinstance(raw_metrics, dict):
            raise TypeError("runtime_metrics ist keine Map")
        runtime_metrics = {str(key): float(value) for key, value in raw_metrics.items()}
        if any(not math.isfinite(value) or value < 0 for value in runtime_metrics.values()):
            raise ValueError("runtime_metrics enthält ungültige Werte")
        raw_metadata = data.get("run_metadata", {})
        if not isinstance(raw_metadata, dict) or not all(
            isinstance(key, str)
            and isinstance(value, (str, int, float, bool, type(None)))
            for key, value in raw_metadata.items()
        ):
            raise TypeError("run_metadata enthält ungültige Werte")
        run_metadata = dict(raw_metadata)
    except (KeyError, TypeError, ValueError, AttributeError, VoiceCatalogError) as exc:
        raise ReviewError(
            f"Review-Datei enthält ungültige segments/markers/bookmarks/speaker_map-Einträge: {exc}"
        ) from exc
    return ReviewData(
        audio_path,
        segments,
        speaker_map,
        markers,
        bookmarks,
        base_name,
        list(formats),
        segment_ids,
        marker_ids,
        speaker_embeddings,
        embedding_model.strip() if isinstance(embedding_model, str) else None,
        runtime_metrics,
        run_metadata,
    )

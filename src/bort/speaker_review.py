"""Laden und Validieren von Speaker-Review-Sidecar-Dateien (`*.review.json`)."""

import json
from dataclasses import dataclass
from pathlib import Path

from .markers import Bookmark, SpeakerMarker
from .speakers import SpeakerSegment
from .writers import FORMATS

SUPPORTED_SCHEMA_VERSION = 1
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
    if data["schema_version"] != SUPPORTED_SCHEMA_VERSION:
        raise ReviewError(
            f"Nicht unterstützte schema_version: {data['schema_version']} "
            f"(erwartet: {SUPPORTED_SCHEMA_VERSION})"
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
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ReviewError(
            f"Review-Datei enthält ungültige segments/markers/bookmarks/speaker_map-Einträge: {exc}"
        ) from exc
    return ReviewData(
        audio_path, segments, speaker_map, markers, bookmarks, base_name, list(formats)
    )

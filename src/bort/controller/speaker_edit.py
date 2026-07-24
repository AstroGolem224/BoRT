"""Registrierte Speaker-Reviews sicher umbenennen und neu schreiben."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from ..markers import Bookmark, SpeakerMarker
from ..speakers import SpeakerSegment
from ..writers import FORMATS, write_outputs


class SpeakerEditError(Exception):
    """Fehler beim Anwenden einer Speaker-Umbenennung."""


@dataclass
class RegisteredReview:
    audio_path: Path
    segments: list[SpeakerSegment]
    speaker_map: dict[str, str]
    markers: list[SpeakerMarker]
    bookmarks: list[Bookmark]
    output_dir: Path
    base_name: str
    formats: list[str]
    segment_ids: list[str | None] = field(default_factory=list)
    marker_ids: list[str | None] = field(default_factory=list)
    review_path: Path | None = None


@dataclass(frozen=True)
class RenameResult:
    output_paths: list[Path]
    location: Path
    segments: list[SpeakerSegment]
    speaker_map: dict[str, str]
    markers: list[SpeakerMarker]


class SpeakerEditController:
    """Hält validierte Review-Daten hinter opaken IDs."""

    def __init__(self) -> None:
        self._reviews: dict[str, RegisteredReview] = {}

    def register(self, review: RegisteredReview) -> str:
        reverse_map = {name: speaker_id for speaker_id, name in review.speaker_map.items()}
        if not review.segment_ids:
            review.segment_ids = [reverse_map.get(segment.speaker) for segment in review.segments]
        if not review.marker_ids:
            review.marker_ids = [reverse_map.get(marker.speaker) for marker in review.markers]
        review_id = uuid4().hex
        self._reviews[review_id] = review
        return review_id

    def get(self, review_id: str) -> RegisteredReview:
        try:
            return self._reviews[review_id]
        except KeyError as exc:
            raise SpeakerEditError("Unbekannte Review-ID.") from exc

    def rename_base(self, review_id: str, new_base: str) -> RegisteredReview:
        """Benennt die komplette Dateifamilie (Review-JSON, Outputs, Audio) um."""
        review = self.get(review_id)
        new_base = new_base.strip()
        if not new_base or "/" in new_base or "\\" in new_base or new_base in {".", ".."}:
            raise SpeakerEditError("Ungültiger Dateiname.")
        if new_base == review.base_name:
            return review

        old_json = review.review_path or (
            review.output_dir / f"{review.base_name}.review.json"
        )
        new_json = old_json.with_name(f"{new_base}.review.json")
        new_audio = review.audio_path.with_name(new_base + review.audio_path.suffix)
        pairs: list[tuple[Path, Path]] = [(old_json, new_json)]
        for fmt in review.formats:
            suffix = FORMATS[fmt][0]
            pairs.append(
                (
                    review.output_dir / f"{review.base_name}{suffix}",
                    review.output_dir / f"{new_base}{suffix}",
                )
            )
        pairs.append((review.audio_path, new_audio))
        pairs = [(src, dst) for src, dst in pairs if src != dst]

        for _src, dst in pairs:
            if dst.exists():
                raise SpeakerEditError(f"Zieldatei existiert bereits: {dst.name}")
        renamed: list[tuple[Path, Path]] = []
        try:
            for src, dst in pairs:
                if not src.exists():
                    continue
                src.rename(dst)
                renamed.append((src, dst))
        except OSError as exc:
            for src, dst in reversed(renamed):
                try:
                    dst.rename(src)
                except OSError:
                    pass
            raise SpeakerEditError(f"Umbenennen fehlgeschlagen: {exc}") from exc

        try:
            data = json.loads(new_json.read_text(encoding="utf-8"))
            data["base_name"] = new_base
            data["audio_path"] = str(new_audio)
            new_json.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except (OSError, ValueError) as exc:
            raise SpeakerEditError(
                f"Review-JSON konnte nicht aktualisiert werden: {exc}"
            ) from exc

        review.base_name = new_base
        review.audio_path = new_audio
        review.review_path = new_json
        return review

    def apply(self, review_id: str, rename_map: dict[str, str]) -> RenameResult:
        """Wendet genau eine Speaker-ID-zu-Name-Map an und überschreibt Outputs."""
        review = self.get(review_id)
        if not isinstance(rename_map, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in rename_map.items()
        ):
            raise SpeakerEditError("Umbenennungen müssen eine {speaker_id: new_name}-Map sein.")
        expected = set(review.speaker_map)
        if set(rename_map) != expected:
            missing = sorted(expected - set(rename_map))
            unknown = sorted(set(rename_map) - expected)
            details = []
            if missing:
                details.append(f"fehlend: {', '.join(missing)}")
            if unknown:
                details.append(f"unbekannt: {', '.join(unknown)}")
            raise SpeakerEditError("Ungültige Sprecher-IDs (" + "; ".join(details) + ").")

        new_map = {
            speaker_id: name.strip() or review.speaker_map[speaker_id]
            for speaker_id, name in rename_map.items()
        }
        segments = [
            SpeakerSegment(
                segment.start,
                segment.end,
                new_map.get(speaker_id, segment.speaker),
                segment.text,
            )
            for segment, speaker_id in zip(review.segments, review.segment_ids, strict=True)
        ]
        markers = [
            SpeakerMarker(marker.start, marker.end, new_map.get(speaker_id, marker.speaker))
            for marker, speaker_id in zip(review.markers, review.marker_ids, strict=True)
        ]
        review_data = {
            "schema_version": 1,
            "audio_path": str(review.audio_path),
            "segments": [
                {
                    "start": segment.start,
                    "end": segment.end,
                    "speaker": segment.speaker,
                    "text": segment.text,
                }
                for segment in segments
            ],
            "speaker_map": dict(new_map),
            "markers": [
                {"start": marker.start, "end": marker.end, "speaker": marker.speaker}
                for marker in markers
            ],
            "bookmarks": [
                {
                    "time": bookmark.time,
                    "label": bookmark.label,
                    "type": bookmark.type,
                    "color": bookmark.color,
                }
                for bookmark in review.bookmarks
            ],
            "base_name": review.base_name,
            "formats": review.formats,
        }
        output_paths = write_outputs(
            segments,
            review.output_dir,
            review.base_name,
            review.formats,
            review.bookmarks or None,
            review_data,
            overwrite=True,
        )
        review.segments = segments
        review.markers = markers
        review.speaker_map = new_map
        location = output_paths[0].parent if output_paths else review.output_dir
        return RenameResult(output_paths, location, segments, dict(new_map), markers)

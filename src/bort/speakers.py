"""Sprecherzuordnung für Transkriptionssegmente."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .markers import SpeakerMarker


@dataclass(frozen=True)
class Segment:
    """Ein Transkriptionssegment."""

    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        """Länge des Segments in Sekunden."""
        return self.end - self.start


@dataclass(frozen=True)
class SpeakerSegment:
    """Ein Segment mit zugeordnetem Sprecher."""

    start: float
    end: float
    speaker: str
    text: str


class SpeakerResolver(ABC):
    """Basis-Klasse zur Sprecherzuordnung."""

    @abstractmethod
    def resolve(self, segments: list[Segment]) -> list[SpeakerSegment]:
        """Ordnet jedem Segment einen Sprecher zu."""


class PlaceholderSpeakerResolver(SpeakerResolver):
    """Fallback-Resolver mit generischen Sprecher-Labels."""

    def __init__(self, prefix: str = "SP", unknown: str = "Unbekannt") -> None:
        self.prefix = prefix
        self.unknown = unknown

    def resolve(self, segments: list[Segment]) -> list[SpeakerSegment]:
        return [
            SpeakerSegment(
                start=seg.start,
                end=seg.end,
                speaker=f"{self.prefix}{idx + 1}" if len(segments) > 1 else self.unknown,
                text=seg.text,
            )
            for idx, seg in enumerate(segments)
        ]


class MarkerSpeakerResolver(SpeakerResolver):
    """Ordnet Segmente anhand von Zeitintervallen aus einer Marker-Datei zu."""

    def __init__(
        self,
        markers: list[SpeakerMarker],
        speaker_map: dict[str, str] | None = None,
        fallback: str = "Unbekannt",
    ) -> None:
        self.markers = sorted(markers, key=lambda m: m.start)
        self.speaker_map = speaker_map or {}
        self.fallback = fallback

    def _display_name(self, speaker_id: str) -> str:
        return self.speaker_map.get(speaker_id, speaker_id)

    def _resolve_speaker(self, segment: Segment) -> str:
        best_marker: SpeakerMarker | None = None
        best_overlap = 0.0

        for marker in self.markers:
            overlap_start = max(segment.start, marker.start)
            overlap_end = min(segment.end, marker.end)
            overlap = max(0.0, overlap_end - overlap_start)

            if overlap > best_overlap:
                best_overlap = overlap
                best_marker = marker

        if best_marker is None:
            return self.fallback

        return self._display_name(best_marker.speaker)

    def resolve(self, segments: list[Segment]) -> list[SpeakerSegment]:
        return [
            SpeakerSegment(
                start=seg.start,
                end=seg.end,
                speaker=self._resolve_speaker(seg),
                text=seg.text,
            )
            for seg in segments
        ]

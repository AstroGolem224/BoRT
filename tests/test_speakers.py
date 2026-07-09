"""Tests für Sprecherzuordnung."""

from bort.markers import SpeakerMarker
from bort.speakers import (
    MarkerSpeakerResolver,
    PlaceholderSpeakerResolver,
    Segment,
    SpeakerSegment,
)


def test_placeholder_resolver() -> None:
    segments = [
        Segment(0.0, 5.0, "Hallo"),
        Segment(5.0, 10.0, "Welt"),
    ]
    resolver = PlaceholderSpeakerResolver()
    result = resolver.resolve(segments)
    assert result == [
        SpeakerSegment(0.0, 5.0, "SP1", "Hallo"),
        SpeakerSegment(5.0, 10.0, "SP2", "Welt"),
    ]


def test_placeholder_single_segment() -> None:
    resolver = PlaceholderSpeakerResolver()
    result = resolver.resolve([Segment(0.0, 5.0, "Hallo")])
    assert result[0].speaker == "Unbekannt"


def test_marker_resolver() -> None:
    markers = [
        SpeakerMarker(0.0, 10.0, "SP1"),
        SpeakerMarker(10.0, 20.0, "SP2"),
    ]
    resolver = MarkerSpeakerResolver(markers, {"SP1": "Alice", "SP2": "Bob"})
    segments = [
        Segment(1.0, 4.0, "Hallo Alice"),
        Segment(12.0, 15.0, "Hallo Bob"),
    ]
    result = resolver.resolve(segments)
    assert result[0].speaker == "Alice"
    assert result[1].speaker == "Bob"


def test_marker_resolver_fallback() -> None:
    markers = [SpeakerMarker(0.0, 10.0, "SP1")]
    resolver = MarkerSpeakerResolver(markers)
    segments = [Segment(20.0, 25.0, "Kein Marker")]
    result = resolver.resolve(segments)
    assert result[0].speaker == "Unbekannt"

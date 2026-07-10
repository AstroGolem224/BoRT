"""Laden und Validieren von JSON-Marker-Dateien für Sprecher."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpeakerMarker:
    """Ein Zeitintervall mit zugeordnetem Sprecher."""

    start: float
    end: float
    speaker: str

    @property
    def duration(self) -> float:
        """Länge des Intervalls in Sekunden."""
        return self.end - self.start


@dataclass(frozen=True)
class Bookmark:
    """Ein Punkt-Marker (Bookmark) aus der Android-Partner-App.

    Bookmarks sind Zeitpunkte, die beim Aufnehmen gesetzt wurden (z.B.
    "hier passiert etwas Wichtiges"). Im Gegensatz zu SpeakerMarkern haben
    sie keine Intervall-Ausdehnung und keine Sprecher-Info.
    """

    time: float  # Sekunden
    label: str = ""
    type: str = ""
    color: str = ""

    @property
    def time_ms(self) -> int:
        """Zeit in Millisekunden (wie im Android-Format)."""
        return int(self.time * 1000)

    @property
    def display(self) -> str:
        """Anzeige-Text für das Transkript (Typ + Label, was verfügbar ist).

        Der Typ wird immer gezeigt (auch "note"), damit klar erkennbar ist,
        dass die Info aus der Marker-JSON stammt.
        """
        parts: list[str] = []
        if self.type:
            parts.append(self.type)
        if self.label:
            parts.append(self.label)
        if self.color:
            parts.append(f"[{self.color}]")
        return " – ".join(parts) if parts else "Bookmark"


class MarkerError(Exception):
    """Fehler im Marker-Format."""

    pass


def load_markers(path: Path | str) -> tuple[dict[str, str], list[SpeakerMarker]]:
    """Lädt eine JSON-Marker-Datei.

    Unterstützt zwei Formate:
    1. **BoRT-Format** (Intervall-Marker):
       ``{"speakers": {id: name}, "markers": [{start, end, speaker}]}``
    2. **Android-Format** (Punkt-Marker, z.B. von der Partner-App):
       ``{"version": 1, "file": "...", "markers": [{timeMs, type, label}]}``
       Punkt-Marker werden in Intervalle umgewandelt (Bookmark zu Bookmark).
       Da das Android-Format keine Sprecher-Info enthält, wird ein einzelner
       Sprecher "sprecher001" angenommen.

    Args:
        path: Pfad zur JSON-Datei.

    Returns:
        Tuple aus (speaker_map, markers).
        speaker_map mappt Sprecher-IDs auf Anzeigenamen.
        markers ist die sortierte Liste der Zeitintervalle.

    Raises:
        MarkerError: Bei ungültigem Format.
    """
    path = Path(path)
    if not path.exists():
        raise MarkerError(f"Marker-Datei nicht gefunden: {path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise MarkerError(f"Ungültiges JSON in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise MarkerError("Marker-Datei muss ein JSON-Objekt sein.")

    # Format-Erkennung: Android-Format hat timeMs-basierte Punkt-Marker
    raw_markers = data.get("markers", [])
    if not isinstance(raw_markers, list):
        raise MarkerError("'markers' muss eine Liste sein.")

    if _is_android_format(data, raw_markers):
        logger.info("Erkanntes Format: Android (Punkt-Marker in ms)")
        return _load_android_markers(data, raw_markers)

    # BoRT-Format (Intervall-Marker)
    speakers = data.get("speakers", {})
    if not isinstance(speakers, dict):
        raise MarkerError("'speakers' muss ein Objekt sein.")

    markers: list[SpeakerMarker] = []
    for idx, item in enumerate(raw_markers):
        marker = _parse_marker_item(idx, item)
        markers.append(marker)

    markers.sort(key=lambda m: m.start)
    _warn_overlaps(markers)

    return speakers, markers


def _is_android_format(data: dict, raw_markers: list) -> bool:
    """Erkennt das Android-Marker-Format.

    Indizien: ``version`` vorhanden, Marker haben ``timeMs`` (nicht ``start``).
    """
    if "version" in data and isinstance(data["version"], int):
        return True
    if raw_markers and isinstance(raw_markers[0], dict):
        if "timeMs" in raw_markers[0] and "start" not in raw_markers[0]:
            return True
    return False


def _load_android_markers(
    data: dict, raw_markers: list
) -> tuple[dict[str, str], list[SpeakerMarker]]:
    """Wandelt Android-Punkt-Marker in Intervall-Marker um.

    Android setzt beim Aufnehmen Bookmarks (Punkt-Marker mit ``timeMs``).
    Wir erzeugen daraus Intervalle: von Bookmark zu Bookmark je ein Abschnitt.
    Da das Android-Format keine Sprecher-Info enthält, wird ein einzelner
    Sprecher "sprecher001" angenommen.

    Die Audio-Dauer (``durationMs``) wird als Ende des letzten Intervalls genutzt.
    """
    duration_ms: int | None = None
    if "durationMs" in data:
        try:
            duration_ms = int(data["durationMs"])
        except (TypeError, ValueError):
            duration_ms = None

    # Zeitpunkte der Bookmarks in Sekunden
    times: list[float] = []
    labels: list[str] = []
    for idx, item in enumerate(raw_markers):
        if not isinstance(item, dict):
            logger.warning("Android-Marker[%d] ist kein Objekt – übersprungen", idx)
            continue
        if "timeMs" not in item:
            logger.warning("Android-Marker[%d] hat kein timeMs – übersprungen", idx)
            continue
        try:
            t_ms = float(item["timeMs"])
        except (TypeError, ValueError) as exc:
            raise MarkerError(f"Android-Marker[{idx}]: timeMs muss eine Zahl sein.") from exc
        times.append(t_ms / 1000.0)
        labels.append(str(item.get("label") or ""))

    if not times:
        # Keine Bookmarks → ein Intervall über die gesamte Dauer
        end = (duration_ms / 1000.0) if duration_ms else 0.0
        return {"sprecher001": "sprecher001"}, [
            SpeakerMarker(start=0.0, end=end, speaker="sprecher001")
        ]

    # Sortieren nach Zeit
    pairs = sorted(zip(times, labels))
    times = [p[0] for p in pairs]
    labels = [p[1] for p in pairs]

    # Intervalle erzeugen: [0, bookmark1], [bookmark1, bookmark2], ...
    speakers = {"sprecher001": "sprecher001"}
    markers: list[SpeakerMarker] = []
    prev = 0.0
    for t, label in zip(times, labels):
        if t > prev:
            markers.append(SpeakerMarker(start=prev, end=t, speaker="sprecher001"))
        prev = t
    # Letztes Intervall bis Audio-Ende
    end = (duration_ms / 1000.0) if duration_ms else prev
    if end > prev:
        markers.append(SpeakerMarker(start=prev, end=end, speaker="sprecher001"))

    logger.info("Android-Marker: %d Bookmarks → %d Intervalle", len(times), len(markers))
    _warn_overlaps(markers)
    return speakers, markers


def _parse_marker_item(idx: int, item: Any) -> SpeakerMarker:
    """Parst ein einzelnes Marker-Element."""
    if not isinstance(item, dict):
        raise MarkerError(f"Marker[{idx}] muss ein Objekt sein.")

    required = {"start", "end", "speaker"}
    missing = required - item.keys()
    if missing:
        raise MarkerError(f"Marker[{idx}] fehlen Felder: {missing}")

    try:
        start = float(item["start"])
        end = float(item["end"])
    except (TypeError, ValueError) as exc:
        raise MarkerError(f"Marker[{idx}]: start/end müssen Zahlen sein.") from exc

    speaker = str(item["speaker"])
    if not speaker:
        raise MarkerError(f"Marker[{idx}]: speaker darf nicht leer sein.")

    if end < start:
        raise MarkerError(f"Marker[{idx}]: end ({end}) < start ({start}).")

    return SpeakerMarker(start=start, end=end, speaker=speaker)


def save_markers(
    speakers: dict[str, str],
    markers: list[SpeakerMarker],
    path: Path | str,
) -> Path:
    """Schreibt eine Marker-Datei im BoRT-Format.

    Args:
        speakers: Mapping Sprecher-ID -> Anzeigename.
        markers: Liste der Sprecher-Marker.
        path: Zieldatei.

    Returns:
        Pfad der geschriebenen Datei.
    """
    path = Path(path)
    data = {
        "speakers": speakers,
        "markers": [{"start": m.start, "end": m.end, "speaker": m.speaker} for m in markers],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Marker gespeichert: %s", path)
    return path


def _warn_overlaps(markers: list[SpeakerMarker]) -> None:
    """Warnt vor überlappenden Markern."""
    for i in range(len(markers) - 1):
        a, b = markers[i], markers[i + 1]
        if a.end > b.start:
            logger.warning(
                "Marker %d (%s %.2f-%.2f) überlappt mit Marker %d (%s %.2f-%.2f)",
                i,
                a.speaker,
                a.start,
                a.end,
                i + 1,
                b.speaker,
                b.start,
                b.end,
            )


def load_bookmarks(path: Path | str) -> list[Bookmark]:
    """Lädt Bookmarks (Punkt-Marker) aus einer Android-Marker-Datei.

    Die Android-Partner-App speichert Bookmarks beim Aufnehmen mit Zeitstempel
    und optionalem Label. Diese Funktion extrahiert nur die Bookmarks (ohne
    sie in Speaker-Intervalle umzuwandeln), damit sie als Referenz-Marker im
    Transkript erscheinen können.

    Args:
        path: Pfad zur JSON-Marker-Datei (Android-Format).

    Returns:
        Nach Zeit sortierte Liste der Bookmarks.

    Raises:
        MarkerError: Bei ungültigem Format.
    """
    path = Path(path)
    if not path.exists():
        raise MarkerError(f"Marker-Datei nicht gefunden: {path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise MarkerError(f"Ungültiges JSON in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise MarkerError("Marker-Datei muss ein JSON-Objekt sein.")

    raw_markers = data.get("markers", [])
    if not isinstance(raw_markers, list):
        raise MarkerError("'markers' muss eine Liste sein.")

    bookmarks: list[Bookmark] = []
    for idx, item in enumerate(raw_markers):
        if not isinstance(item, dict):
            logger.warning("Marker[%d] ist kein Objekt – übersprungen", idx)
            continue
        if "timeMs" not in item:
            # Kein Android-Format oder kein Bookmark – überspringen
            continue
        try:
            t_ms = float(item["timeMs"])
        except (TypeError, ValueError) as exc:
            raise MarkerError(f"Marker[{idx}]: timeMs muss eine Zahl sein.") from exc
        label = str(item.get("label") or "")
        btype = str(item.get("type") or "")
        color = str(item.get("color") or "")
        bookmarks.append(
            Bookmark(
                time=t_ms / 1000.0,
                label=label,
                type=btype,
                color=color,
            )
        )

    bookmarks.sort(key=lambda b: b.time)
    logger.info("Bookmarks geladen: %d aus %s", len(bookmarks), path)
    return bookmarks


def _looks_like_marker_file(path: Path) -> bool:
    """Prüft heuristisch, ob ``path`` eine lesbare Marker-JSON ist."""
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False
    return isinstance(data, dict) and isinstance(data.get("markers"), list)


def find_companion_marker(audio_path: Path) -> Path | None:
    """Sucht eine passende Marker-JSON zu einer Audiodatei (gleicher Ordner)."""
    candidates = [
        audio_path.with_suffix(".json"),
        audio_path.parent / f"{audio_path.stem}.markers.json",
    ]
    for cand in candidates:
        if cand.exists() and _looks_like_marker_file(cand):
            return cand
    return None

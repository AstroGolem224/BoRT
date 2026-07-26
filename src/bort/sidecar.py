"""Robuster, ausschließlich lesender Zugriff auf BoR-Aufnahme-Sidecars."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)
MAX_SIDECAR_BYTES = 2 * 1024 * 1024
MAX_PEAKS = 1000
MAX_DURATION_MS = 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class RecordingMeta:
    started_at: datetime | None
    duration_ms: float
    marker_count: int
    peaks: list[float]
    warnings: list[str]


def _warning(path: Path, warnings: list[str], reason: str) -> None:
    warnings.append(reason)
    logger.warning("BoR-Sidecar %s: %s", path, reason)


def read_recording_meta(json_path: Path, audio_name: str) -> RecordingMeta | None:
    """Liest genau eine passende BoR-Sidecar; beschädigte Dateien werden abgelehnt."""
    path = Path(json_path)
    if not path.is_file():
        return None
    warnings: list[str] = []
    try:
        if path.stat().st_size > MAX_SIDECAR_BYTES:
            _warning(path, warnings, "Datei ist größer als 2 MB")
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _warning(path, warnings, f"nicht lesbar: {exc}")
        return None
    if not isinstance(data, dict):
        _warning(path, warnings, "Wurzel ist kein JSON-Objekt")
        return None
    if data.get("file") != audio_name:
        _warning(path, warnings, "file stimmt nicht mit der Audio-Datei überein")
        return None

    started_at = None
    raw_started = data.get("startedAt")
    if isinstance(raw_started, str):
        try:
            started_at = datetime.fromisoformat(raw_started.replace("Z", "+00:00"))
        except ValueError:
            _warning(path, warnings, "startedAt ist kein gültiger ISO-Zeitpunkt")
    elif raw_started is not None:
        _warning(path, warnings, "startedAt hat einen ungültigen Typ")

    raw_duration = data.get("durationMs", 0)
    if (
        isinstance(raw_duration, (int, float))
        and not isinstance(raw_duration, bool)
        and math.isfinite(float(raw_duration))
        and 0 <= float(raw_duration) <= MAX_DURATION_MS
    ):
        duration_ms = float(raw_duration)
    else:
        duration_ms = 0.0
        _warning(path, warnings, "durationMs wurde verworfen")

    peaks: list[float] = []
    raw_peaks = data.get("peaks", [])
    if not isinstance(raw_peaks, list):
        _warning(path, warnings, "peaks ist keine Liste")
    else:
        if len(raw_peaks) > MAX_PEAKS:
            _warning(path, warnings, "peaks wurde auf 1000 Einträge begrenzt")
        for index, value in enumerate(raw_peaks[:MAX_PEAKS]):
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
            ):
                peaks.append(max(0.0, min(1.0, float(value))))
            else:
                _warning(path, warnings, f"peak {index} wurde verworfen")

    marker_count = 0
    raw_markers = data.get("markers", [])
    if not isinstance(raw_markers, list):
        _warning(path, warnings, "markers ist keine Liste")
    else:
        for index, marker in enumerate(raw_markers):
            time_ms = marker.get("timeMs") if isinstance(marker, dict) else None
            marker_type = marker.get("type", "") if isinstance(marker, dict) else None
            label = marker.get("label", "") if isinstance(marker, dict) else None
            if (
                isinstance(time_ms, (int, float))
                and not isinstance(time_ms, bool)
                and math.isfinite(float(time_ms))
                and 0 <= float(time_ms) <= MAX_DURATION_MS
                and isinstance(marker_type, str)
                and isinstance(label, str)
            ):
                marker_count += 1
            else:
                _warning(path, warnings, f"Marker {index} wurde verworfen")
    return RecordingMeta(started_at, duration_ms, marker_count, peaks, warnings)


def resample_peaks(peaks: list[float], count: int) -> list[float]:
    """Resampelt Maxima nach dem BoR-Vertrag ohne Renormalisierung."""
    if not peaks or count <= 0:
        return []
    if len(peaks) == count:
        return list(peaks)
    if len(peaks) > count:
        return [
            max(peaks[index * len(peaks) // count:(index + 1) * len(peaks) // count])
            for index in range(count)
        ]
    return [peaks[min(len(peaks) - 1, index * len(peaks) // count)] for index in range(count)]

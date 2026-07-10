"""Findet unverarbeitete Audio+Marker-Paare in einem Sync-/Watch-Ordner."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .audio import is_supported_audio
from .markers import find_companion_marker
from .writers import FORMATS

_OUTPUT_SUFFIXES = tuple(suffix for suffix, _writer in FORMATS.values())


@dataclass(frozen=True)
class PendingItem:
    """Ein noch nicht transkribiertes Audio, optional mit Marker-Datei."""

    audio_path: Path
    marker_path: Path | None


def _has_output(audio_path: Path, output_dir: Path) -> bool:
    """Prüft, ob bereits eine gültige, aktuelle Ausgabedatei existiert."""
    if not output_dir.is_dir():
        return False
    audio_mtime = audio_path.stat().st_mtime
    for suffix in _OUTPUT_SUFFIXES:
        for candidate in output_dir.rglob(f"{audio_path.stem}{suffix}"):
            if candidate.stat().st_mtime >= audio_mtime:
                return True
    return False


def is_file_stable(
    path: Path,
    interval: float = 2.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> bool:
    """Prüft per Doppel-Stichprobe, ob eine Datei fertig kopiert wurde."""
    try:
        first = path.stat()
    except OSError:
        return False
    sleep_fn(interval)
    try:
        second = path.stat()
    except OSError:
        return False
    return (first.st_size, first.st_mtime) == (second.st_size, second.st_mtime)


def scan_pending(watch_dir: Path, output_dir: Path) -> list[PendingItem]:
    """Findet Audio-Dateien in ``watch_dir`` ohne gültiges Output."""
    if not watch_dir.is_dir():
        return []
    items: list[PendingItem] = []
    for audio_path in sorted(watch_dir.iterdir()):
        if not audio_path.is_file() or not is_supported_audio(audio_path):
            continue
        if _has_output(audio_path, output_dir):
            continue
        items.append(PendingItem(audio_path, find_companion_marker(audio_path)))
    return items

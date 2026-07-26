"""Findet unverarbeitete Audio+Marker-Paare in einem Sync-/Watch-Ordner."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .audio import is_supported_audio
from .controller.jobs import expected_artifacts
from .markers import find_companion_marker
from .writers import FORMATS, recover_transactions

_OUTPUT_SUFFIXES = tuple(suffix for suffix, _writer in FORMATS.values())


@dataclass(frozen=True)
class PendingItem:
    """Ein noch nicht transkribiertes Audio, optional mit Marker-Datei."""

    audio_path: Path
    marker_path: Path | None


def _has_output(
    audio_path: Path,
    output_dir: Path,
    settings: dict | None = None,
) -> bool:
    """Prüft, ob bereits eine gültige, aktuelle Ausgabedatei existiert."""
    if not output_dir.is_dir() and (
        settings is None or not settings.get("colocate", True)
    ):
        return False
    audio_mtime = audio_path.stat().st_mtime
    if settings is not None:
        suffixes = expected_artifacts(settings)
        if settings.get("colocate", True):
            recover_transactions(audio_path.parent)
            return bool(suffixes) and all(
                (candidate := audio_path.with_name(audio_path.stem + suffix)).is_file()
                and candidate.stat().st_mtime >= audio_mtime
                for suffix in suffixes
            )
        if not suffixes:
            return False
        directories = [
            output_dir,
            *(path for path in output_dir.rglob("*") if path.is_dir()),
        ]
        for directory in directories:
            recover_transactions(directory)
            if all(
                (candidate := directory / f"{audio_path.stem}{suffix}").is_file()
                and candidate.stat().st_mtime >= audio_mtime
                for suffix in suffixes
            ):
                return True
        return False
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


def iter_audio_paths(watch_dir: Path) -> list[Path]:
    """Listet unterstützte Audios im Root und in echten direkten Unterordnern."""
    directories = [watch_dir]
    try:
        directories.extend(
            path for path in watch_dir.iterdir() if path.is_dir() and not path.is_symlink()
        )
    except OSError:
        return []
    paths: list[Path] = []
    for directory in directories:
        recover_transactions(directory)
        try:
            paths.extend(
                path for path in directory.iterdir()
                if path.is_file() and is_supported_audio(path)
            )
        except OSError:
            continue
    return sorted(paths)


def scan_pending(
    watch_dir: Path,
    output_dir: Path,
    settings: dict | None = None,
) -> list[PendingItem]:
    """Findet Audio-Dateien in ``watch_dir`` ohne gültiges Output."""
    if not watch_dir.is_dir():
        return []
    items: list[PendingItem] = []
    for audio_path in iter_audio_paths(watch_dir):
        if _has_output(audio_path, output_dir, settings):
            continue
        items.append(PendingItem(audio_path, find_companion_marker(audio_path)))
    return items

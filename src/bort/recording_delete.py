"""Löscht eine Aufnahme samt Artefakten – über den Papierkorb, nicht endgültig.

Eine Aufnahme ist nie nur die Audio-Datei: daneben liegen Transkripte
(``.txt``/``.md``/``.csv``/``.tsv``/``.srt``/``.vtt``), das Review
(``.review.json``) und die Marker-/BoR-Sidecar (``.json``/``.markers.json``).
Ein Löschen, das nur die Audio trifft, hinterlässt Halbgut und zählt beim
nächsten Scan als "Aufnahme ohne Transcript".

Gelöscht wird deshalb die ganze Familie. Weil das unwiderruflich wäre,
geht alles in den Papierkorb: der Nutzer kann eine versehentlich gelöschte
Aufnahme wiederherstellen.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

#: Suffixe der Artefakte, die zu einer Aufnahme gehören. ``.json`` ist die
#: Marker-/BoR-Sidecar, ``.markers.json`` die von whisperX geschriebene
#: Marker-Datei. Die Namen werden aus dem Stamm konstruiert, nicht per
#: Glob-Muster gesucht – ``<stem>.review.json`` und ``<stem>.json`` sind
#: verschiedene Dateien.
FAMILY_SUFFIXES: tuple[str, ...] = (
    ".txt",
    ".md",
    ".csv",
    ".tsv",
    ".srt",
    ".vtt",
    ".review.json",
    ".markers.json",
    ".json",
)


class DeleteError(RuntimeError):
    """Eine Aufnahme konnte nicht gelöscht werden."""


def default_trash_dir() -> Path:
    """Der BoRT-eigene Papierkorb, in den der System-Papierkorb-Fallback geht.

    Respektiert ``XDG_DATA_HOME``; der Pfad wird bei jedem Aufruf neu gelesen,
    damit Tests ihn über die Umgebungsvariable umbiegen können.
    """
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "BoRT" / "trash"


def _gio_trash(path: Path) -> bool:
    """Schiebt die Datei in den System-Papierkorb. False bei jedem Problem."""
    try:
        result = subprocess.run(
            ["gio", "trash", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("gio trash nicht ausführbar (%s) – nutze BoRT-Papierkorb.", exc)
        return False
    if result.returncode != 0:
        logger.warning(
            "gio trash fehlgeschlagen (%s): %s", result.returncode, result.stderr.strip()
        )
        return False
    return not path.exists()


def _move_to_fallback_trash(path: Path) -> Path:
    """Verschiebt die Datei in den BoRT-Papierkorb (Rückfallweg)."""
    trash_dir = default_trash_dir()
    try:
        trash_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DeleteError(f"Kein Papierkorb anlegbar: {exc}") from exc
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    target = trash_dir / f"{stamp}_{path.name}"
    counter = 1
    while target.exists():
        target = trash_dir / f"{stamp}_{counter}_{path.name}"
        counter += 1
    try:
        shutil.move(str(path), str(target))
    except OSError as exc:
        raise DeleteError(f"{path.name} konnte nicht gelöscht werden: {exc}") from exc
    return target


def move_to_trash(path: Path) -> None:
    """Verschiebt eine einzelne Datei in den Papierkorb.

    Raises:
        DeleteError: Die Datei konnte nicht verschoben werden.
    """
    path = Path(path)
    if not path.exists():
        raise DeleteError(f"Datei existiert nicht: {path.name}")
    if _gio_trash(path):
        return
    _move_to_fallback_trash(path)


def recording_family(audio: Path) -> list[Path]:
    """Alle existierenden Artefakte, die zu dieser Aufnahme gehören.

    Die Audio-Datei kommt zuerst, danach die Neben-Dateien in
    ``FAMILY_SUFFIXES``-Reihenfolge.
    """
    audio = Path(audio)
    family = [audio] if audio.is_file() else []
    for suffix in FAMILY_SUFFIXES:
        candidate = audio.with_name(audio.stem + suffix)
        if candidate.is_file():
            family.append(candidate)
    return family


def delete_recording_family(audio: Path) -> list[Path]:
    """Verschiebt die Aufnahme samt Artefakten in den Papierkorb.

    Returns:
        Die verschobenen Dateien, in Verschiebungsreihenfolge.

    Raises:
        DeleteError: Eine Datei konnte nicht verschoben werden. Bereits
            verschobene Dateien bleiben im Papierkorb – der Aufrufer meldet
            das, statt eine Teillöschung zu verschweigen.
    """
    family = recording_family(audio)
    if not family:
        raise DeleteError(f"Datei nicht gefunden: {Path(audio).name}")
    moved: list[Path] = []
    for path in family:
        try:
            move_to_trash(path)
        except DeleteError:
            raise
        moved.append(path)
    return moved

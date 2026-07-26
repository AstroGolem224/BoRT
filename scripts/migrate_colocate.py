#!/usr/bin/env python3
"""Migriert alte BoRT-Ausgabefamilien sicher neben ihre Audio-Dateien."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

AUDIO_SUFFIXES = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".wma"}
FAMILY_SUFFIXES = (".review.json", ".markers.json", ".txt", ".md", ".csv", ".tsv")
DEFAULT_TRANSCRIPTS = Path.home() / "Dokumente" / "BoR_Transkripte"
DEFAULT_RECORDINGS = Path.home() / "Dokumente" / "BoR_Aufnahmen"


@dataclass
class Family:
    base: str
    audio: Path
    sources: list[Path]
    review: Path | None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bytes(path: Path) -> bytes:
    return path.read_bytes()


def _normalized_review(path: Path, audio: Path) -> bytes:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Review-Wurzel ist kein Objekt")
    data["audio_path"] = str(audio)
    data["base_name"] = audio.stem
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def _valid_audio_from_review(review: Path, recordings: Path) -> Path:
    data = json.loads(review.read_text(encoding="utf-8"))
    raw = data.get("audio_path") if isinstance(data, dict) else None
    if not isinstance(raw, str):
        raise ValueError("audio_path fehlt")
    audio = Path(raw).expanduser().resolve()
    root = recordings.resolve()
    try:
        audio.relative_to(root)
    except ValueError as exc:
        raise ValueError("audio_path liegt außerhalb des Aufnahme-Roots") from exc
    if audio.suffix.lower() not in AUDIO_SUFFIXES or not audio.is_file():
        raise ValueError("audio_path ist keine unterstützte vorhandene Audio-Datei")
    return audio


def _family_sources(review: Path) -> list[Path]:
    base = review.name.removesuffix(".review.json")
    return [
        candidate for suffix in FAMILY_SUFFIXES
        if (candidate := review.with_name(base + suffix)).is_file()
    ]


def discover(transcripts: Path, recordings: Path) -> tuple[list[Family], list[str]]:
    conflicts: list[str] = []
    by_audio: dict[Path, list[Family]] = {}
    claimed: set[Path] = set()
    for review in transcripts.rglob("*.review.json"):
        try:
            audio = _valid_audio_from_review(review, recordings)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            conflicts.append(f"{review}: ungültige Review ({exc})")
            continue
        sources = _family_sources(review)
        claimed.update(sources)
        family = Family(review.name.removesuffix(".review.json"), audio, sources, review)
        by_audio.setdefault(audio, []).append(family)
    families: list[Family] = []
    for audio, generations in by_audio.items():
        winner = max(generations, key=lambda family: family.review.stat().st_mtime)
        families.append(winner)
        for loser in generations:
            if loser is not winner:
                conflicts.append(
                    f"{loser.review}: ältere Generation für {audio.name}, bleibt unangetastet"
                )

    audios_by_stem: dict[str, list[Path]] = {}
    for audio in recordings.rglob("*"):
        if audio.is_file() and audio.suffix.lower() in AUDIO_SUFFIXES:
            audios_by_stem.setdefault(audio.stem, []).append(audio.resolve())
    grouped: dict[tuple[Path, str], list[Path]] = {}
    for source in transcripts.rglob("*"):
        if not source.is_file() or source in claimed:
            continue
        suffix = next((item for item in FAMILY_SUFFIXES[1:] if source.name.endswith(item)), None)
        if suffix is None:
            continue
        base = source.name.removesuffix(suffix)
        matches = audios_by_stem.get(base, [])
        if len(matches) != 1:
            state = "mehrdeutig" if matches else "unbekannt"
            conflicts.append(f"{source}: Stem-Zuordnung ist {state}")
            continue
        grouped.setdefault((matches[0], base), []).append(source)
    families.extend(
        Family(base, audio, sources, None)
        for (audio, base), sources in grouped.items()
    )
    return families, conflicts


def migrate_family(family: Family, apply: bool) -> tuple[str, list[str]]:
    messages: list[str] = []
    expected: list[tuple[Path, Path, bytes]] = []
    for source in family.sources:
        suffix = source.name.removeprefix(family.base)
        target = family.audio.with_name(family.audio.stem + suffix)
        try:
            content = (
                _normalized_review(source, family.audio)
                if source == family.review else _bytes(source)
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return "conflict", [f"{source}: {exc}"]
        if target.exists():
            try:
                if _sha(_bytes(target)) != _sha(content):
                    return "conflict", [f"{target}: Zielkollision mit abweichendem Inhalt"]
                messages.append(f"FORTSETZEN {source} -> {target}")
            except OSError as exc:
                return "conflict", [f"{target}: {exc}"]
        else:
            messages.append(f"VERSCHIEBEN {source} -> {target}")
        expected.append((source, target, content))
    if not apply:
        return "planned", messages

    staged: list[tuple[Path, Path, bytes]] = []
    try:
        for source, target, content in expected:
            if target.exists():
                continue
            temp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
            with temp.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if _sha(_bytes(temp)) != _sha(content):
                raise OSError(f"Hash-Prüfung fehlgeschlagen: {temp}")
            staged.append((temp, target, content))
        for temp, target, _content in staged:
            os.replace(temp, target)
        descriptor = os.open(family.audio.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        for temp, _target, _content in staged:
            temp.unlink(missing_ok=True)
        return "conflict", [f"{family.base}: Publikation abgebrochen ({exc}); Quellen intakt"]

    # Review bleibt bis zuletzt als Resume-Anker für nummerierte Familien erhalten.
    deletion = [source for source, _target, _content in expected if source != family.review]
    if family.review is not None:
        deletion.append(family.review)
    for source in deletion:
        source.unlink(missing_ok=True)
    return "migrated", messages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcripts", type=Path, default=DEFAULT_TRANSCRIPTS)
    parser.add_argument("--recordings", type=Path, default=DEFAULT_RECORDINGS)
    parser.add_argument("--apply", action="store_true", help="Änderungen wirklich ausführen")
    args = parser.parse_args(argv)
    if not args.transcripts.is_dir() or not args.recordings.is_dir():
        parser.error("--transcripts und --recordings müssen vorhandene Ordner sein")
    families, conflicts = discover(args.transcripts.resolve(), args.recordings.resolve())
    counts = {"planned": 0, "migrated": 0, "conflict": len(conflicts)}
    for message in conflicts:
        print(f"KONFLIKT {message}")
    for family in families:
        status, messages = migrate_family(family, args.apply)
        counts[status] += 1
        for message in messages:
            print(message if status != "conflict" else f"KONFLIKT {message}")
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(
        f"{mode}: {counts['planned']} geplant, {counts['migrated']} migriert, "
        f"{counts['conflict']} Konflikte"
    )
    return 1 if counts["conflict"] else 0


if __name__ == "__main__":
    sys.exit(main())

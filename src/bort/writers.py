"""Ausgabeformate: Text, Markdown, CSV/TSV (optional mit Bookmarks)."""

import csv
import fcntl
import hashlib
import json
import logging
import os
import re
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .markers import Bookmark
from .speakers import SpeakerSegment

BOOKMARK_INDICATOR = "🔖"  # Bookmark-Marker im Transkript
logger = logging.getLogger(__name__)
_MANIFEST_RE = re.compile(r"^\.bort-txn-([0-9a-f]{32})\.json$")
_ORPHAN_RE = re.compile(r"^(.+)\.([0-9a-f]{32})\.(tmp|bak)$")
_ALLOWED_FINAL_SUFFIXES = (".txt", ".md", ".csv", ".tsv", ".review.json", ".markers.json")
_STALE_SECONDS = 3600


def _write_json(path: Path, data: dict[str, Any], *, private: bool = False) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if private:
        os.chmod(path, 0o600)


def _format_time(seconds: float) -> str:
    """Formatiert Sekunden als HH:MM:SS."""
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _merge_bookmarks(
    segments: list[SpeakerSegment], bookmarks: list[Bookmark]
) -> list[tuple[str, SpeakerSegment | Bookmark]]:
    """Mergt Bookmarks in den Segment-Stream nach Zeitstempel.

    Returns:
        Liste von (kind, item) Paaren, sortiert nach Zeit.
        kind ist "segment" oder "bookmark".
    """
    items: list[tuple[float, str, SpeakerSegment | Bookmark]] = []
    for seg in segments:
        items.append((seg.start, "segment", seg))
    for bm in bookmarks:
        items.append((bm.time, "bookmark", bm))
    items.sort(key=lambda x: x[0])
    return [(kind, item) for _, kind, item in items]


def write_text(
    segments: list[SpeakerSegment],
    path: Path,
    bookmarks: list[Bookmark] | None = None,
) -> None:
    """Schreibt ein Plaintext-Transkript, optional mit Bookmarks."""
    with path.open("w", encoding="utf-8", newline="") as f:
        if bookmarks:
            for kind, item in _merge_bookmarks(segments, bookmarks):
                if kind == "bookmark":
                    bm: Bookmark = item  # type: ignore[assignment]
                    f.write(f"[{_format_time(bm.time)}] {BOOKMARK_INDICATOR} {bm.display}\n")
                else:
                    seg: SpeakerSegment = item  # type: ignore[assignment]
                    start = _format_time(seg.start)
                    f.write(f"[{start}] {seg.speaker}: {seg.text}\n")
        else:
            for seg in segments:
                start = _format_time(seg.start)
                f.write(f"[{start}] {seg.speaker}: {seg.text}\n")


def write_markdown(
    segments: list[SpeakerSegment],
    path: Path,
    bookmarks: list[Bookmark] | None = None,
) -> None:
    """Schreibt ein Markdown-Transkript mit Zeitstempel, Sprecher und Bookmarks."""
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write("# Transkript\n\n")
        if bookmarks:
            for kind, item in _merge_bookmarks(segments, bookmarks):
                if kind == "bookmark":
                    bm: Bookmark = item  # type: ignore[assignment]
                    f.write(
                        f"**{_format_time(bm.time)}** {BOOKMARK_INDICATOR} **{bm.display}**\n\n"
                    )
                else:
                    seg: SpeakerSegment = item  # type: ignore[assignment]
                    f.write(
                        f"**{_format_time(seg.start)} – {_format_time(seg.end)}** "
                        f"**{seg.speaker}:** {seg.text}\n\n"
                    )
        else:
            current_speaker: str | None = None
            for seg in segments:
                if seg.speaker != current_speaker:
                    f.write(f"\n## {seg.speaker}\n\n")
                    current_speaker = seg.speaker
                f.write(f"**{_format_time(seg.start)} – {_format_time(seg.end)}** {seg.text}\n\n")


def write_csv(
    segments: list[SpeakerSegment],
    path: Path,
    delimiter: str = ",",
    bookmarks: list[Bookmark] | None = None,
) -> None:
    """Schreibt eine CSV/TSV-Datei, optional mit Bookmark-Zeilen."""
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=delimiter)
        writer.writerow(["start", "end", "speaker", "type", "text"])
        if bookmarks:
            for kind, item in _merge_bookmarks(segments, bookmarks):
                if kind == "bookmark":
                    bm: Bookmark = item  # type: ignore[assignment]
                    writer.writerow(
                        [
                            f"{bm.time:.3f}",
                            f"{bm.time:.3f}",
                            "",
                            "bookmark",
                            bm.display,
                        ]
                    )
                else:
                    seg: SpeakerSegment = item  # type: ignore[assignment]
                    writer.writerow(
                        [
                            f"{seg.start:.3f}",
                            f"{seg.end:.3f}",
                            seg.speaker,
                            "segment",
                            seg.text,
                        ]
                    )
        else:
            for seg in segments:
                writer.writerow(
                    [
                        f"{seg.start:.3f}",
                        f"{seg.end:.3f}",
                        seg.speaker,
                        "segment",
                        seg.text,
                    ]
                )


def _date_subdir(output_dir: Path) -> Path:
    """Erzeugt den Datums-Unterordner für Ausgabedateien."""
    subdir = output_dir / datetime.now().strftime("%Y-%m-%d")
    subdir.mkdir(parents=True, exist_ok=True)
    return subdir


def _unique_base_name(output_dir: Path, base_name: str, formats: list[str]) -> str:
    """Findet einen Dateinamen, der keine bestehenden Ausgabedateien überschreibt."""
    candidate = base_name
    counter = 0
    while any((output_dir / f"{candidate}{FORMATS[fmt][0]}").exists() for fmt in formats):
        counter += 1
        candidate = f"{base_name}_{counter}"
    return candidate


FORMATS = {
    "txt": (".txt", write_text),
    "md": (".md", write_markdown),
    "csv": (".csv", lambda segs, path, **kw: write_csv(segs, path, ",", **kw)),
    "tsv": (".tsv", lambda segs, path, **kw: write_csv(segs, path, "\t", **kw)),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def output_lock(output_dir: Path) -> Iterator[None]:
    """Serialisiert Recovery und Co-located-Schreibvorgänge pro Zielordner."""
    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / ".bort-lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _valid_manifest(path: Path, data: Any) -> tuple[str, list[dict[str, Any]]] | None:
    match = _MANIFEST_RE.fullmatch(path.name)
    if not match or not isinstance(data, dict) or set(data) != {"schema_version", "txn", "files"}:
        return None
    txn = match.group(1)
    if data["schema_version"] != 1 or data["txn"] != txn or not isinstance(data["files"], list):
        return None
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for member in data["files"]:
        if not isinstance(member, dict) or set(member) != {
            "final_name", "had_predecessor", "staged_sha256", "predecessor_sha256"
        }:
            return None
        name = member["final_name"]
        predecessor = member["predecessor_sha256"]
        if (
            not isinstance(name, str)
            or name != Path(name).name
            or name in seen
            or not name.endswith(_ALLOWED_FINAL_SUFFIXES)
            or not isinstance(member["had_predecessor"], bool)
            or not isinstance(member["staged_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", member["staged_sha256"])
            or (predecessor is not None and not (
                isinstance(predecessor, str) and re.fullmatch(r"[0-9a-f]{64}", predecessor)
            ))
            or member["had_predecessor"] != (predecessor is not None)
        ):
            return None
        seen.add(name)
        files.append(member)
    return txn, files


def _recover_locked(output_dir: Path) -> list[str]:
    reports: list[str] = []
    manifests = sorted(output_dir.glob(".bort-txn-*.json"))
    active_txns: set[str] = set()
    for manifest in manifests:
        match = _MANIFEST_RE.fullmatch(manifest.name)
        txn = match.group(1) if match else ""
        active_txns.add(txn)
        try:
            parsed = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            parsed = None
        validated = _valid_manifest(manifest, parsed)
        if validated is None:
            invalid = manifest.with_name(f"{manifest.name}.invalid")
            try:
                os.replace(manifest, invalid)
                _fsync_dir(output_dir)
            except OSError as exc:
                reports.append(f"Ungültiges Manifest {manifest}: {exc}")
            else:
                reports.append(f"Ungültiges Manifest isoliert: {invalid}")
            continue
        txn, members = validated
        conflict = False
        actions: list[tuple[str, Path, Path | None]] = []
        for member in members:
            final = output_dir / member["final_name"]
            backup = output_dir / f"{member['final_name']}.{txn}.bak"
            final_hash = _sha256(final) if final.is_file() else None
            backup_hash = _sha256(backup) if backup.is_file() else None
            if member["had_predecessor"]:
                predecessor = member["predecessor_sha256"]
                if final_hash in {None, member["staged_sha256"]} and backup_hash == predecessor:
                    actions.append(("restore", final, backup))
                elif final_hash == predecessor and backup_hash is None:
                    actions.append(("noop", final, None))
                else:
                    conflict = True
            elif final_hash is None:
                actions.append(("noop", final, None))
            elif final_hash == member["staged_sha256"] and backup_hash is None:
                actions.append(("delete", final, None))
            else:
                conflict = True
        if conflict:
            reports.append(f"Manueller Recovery-Konflikt: {manifest}")
            continue
        for action, final, backup in actions:
            if action == "restore" and backup is not None:
                os.replace(backup, final)
            elif action == "delete":
                final.unlink()
        for member in members:
            (output_dir / f"{member['final_name']}.{txn}.tmp").unlink(missing_ok=True)
            (output_dir / f"{member['final_name']}.{txn}.bak").unlink(missing_ok=True)
        manifest.unlink()
        _fsync_dir(output_dir)
        reports.append(f"Unvollständige Transaktion zurückgesetzt: {txn}")

    cutoff = time.time() - _STALE_SECONDS
    for candidate in output_dir.iterdir():
        match = _ORPHAN_RE.fullmatch(candidate.name)
        if (
            not match
            or not match.group(1).endswith(_ALLOWED_FINAL_SUFFIXES)
            or match.group(2) in active_txns
        ):
            continue
        try:
            if candidate.is_file() and candidate.stat().st_mtime < cutoff:
                candidate.unlink()
        except OSError:
            logger.warning(
                "Verwaistes Transaktionsartefakt konnte nicht entfernt werden: %s",
                candidate,
            )
    return reports


def recover_transactions(output_dir: Path) -> list[str]:
    """Rollt streng validierte, unvollständige Manifest-Transaktionen zurück."""
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        return []
    has_work = False
    for candidate in output_dir.iterdir():
        name = candidate.name
        orphan_match = _ORPHAN_RE.fullmatch(name)
        if _MANIFEST_RE.fullmatch(name) or (
            orphan_match
            and orphan_match.group(1).endswith(_ALLOWED_FINAL_SUFFIXES)
        ):
            has_work = True
            break
    if not has_work:
        return []
    with output_lock(output_dir):
        reports = _recover_locked(output_dir)
    for report in reports:
        logger.warning("%s", report)
    return reports


def _transactional_publish(
    output_dir: Path,
    producers: list[tuple[Path, Any]],
) -> list[Path]:
    txn = uuid.uuid4().hex
    staged: list[tuple[Path, Path]] = []
    manifest_path = output_dir / f".bort-txn-{txn}.json"
    manifest_tmp = output_dir / f".bort-txn-{txn}.json.{uuid.uuid4().hex}.tmp"
    members: list[dict[str, Any]] = []
    with output_lock(output_dir):
        _recover_locked(output_dir)
        try:
            for final, producer in producers:
                temp = output_dir / f"{final.name}.{txn}.tmp"
                with temp.open("xb"):
                    pass
                staged.append((final, temp))
                producer(temp)
                with temp.open("rb") as stream:
                    os.fsync(stream.fileno())
                predecessor = _sha256(final) if final.is_file() else None
                members.append({
                    "final_name": final.name,
                    "had_predecessor": predecessor is not None,
                    "staged_sha256": _sha256(temp),
                    "predecessor_sha256": predecessor,
                })
            manifest = {"schema_version": 1, "txn": txn, "files": members}
            with manifest_tmp.open("x", encoding="utf-8") as stream:
                json.dump(manifest, stream, indent=2, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(manifest_tmp, manifest_path)
            _fsync_dir(output_dir)
        except Exception:
            for _final, temp in staged:
                temp.unlink(missing_ok=True)
            manifest_tmp.unlink(missing_ok=True)
            manifest_path.unlink(missing_ok=True)
            raise

        backups: list[tuple[Path, Path]] = []
        try:
            for final, _temp in staged:
                if final.exists():
                    backup = output_dir / f"{final.name}.{txn}.bak"
                    os.replace(final, backup)
                    backups.append((final, backup))
                    _fsync_dir(output_dir)
        except Exception:
            for final, backup in reversed(backups):
                if backup.exists():
                    os.replace(backup, final)
            for _final, temp in staged:
                temp.unlink(missing_ok=True)
            manifest_path.unlink(missing_ok=True)
            _fsync_dir(output_dir)
            raise

        try:
            for final, temp in staged:
                os.replace(temp, final)
            _fsync_dir(output_dir)
            manifest_path.unlink()
            _fsync_dir(output_dir)
        except Exception:
            # Manifest und Hashes bleiben absichtlich für Recovery erhalten.
            raise
        for _final, backup in backups:
            backup.unlink(missing_ok=True)
        return [final for final, _temp in staged]


def write_outputs(
    segments: list[SpeakerSegment],
    output_dir: Path,
    base_name: str,
    formats: list[str],
    bookmarks: list[Bookmark] | None = None,
    review_data: dict | None = None,
    overwrite: bool = False,
    marker_data: dict | None = None,
) -> list[Path]:
    """Schreibt die gewünschten Ausgabeformate, optional mit Bookmarks.

    Args:
        segments: Sprechersegmente.
        output_dir: Zielverzeichnis. Bei ``overwrite=False`` das Elternverzeichnis
            für einen Datums-Unterordner, bei ``overwrite=True`` das exakte Ziel.
        base_name: Basisname für die Ausgabedateien.
        formats: Liste der gewünschten Formate ('txt', 'md', 'csv', 'tsv').
        bookmarks: Optionale Bookmarks aus der Android-Partner-App.
        review_data: Optionales Speaker-Review-Sidecar-Dict.
        overwrite: Überschreibt exakt ``base_name`` in ``output_dir``.

    Returns:
        Liste der erzeugten Dateipfade (inkl. Review-Sidecar, falls vorhanden).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if overwrite:
        date_dir = output_dir
        unique_base = base_name
    else:
        date_dir = _date_subdir(output_dir)
        unique_base = _unique_base_name(date_dir, base_name, formats)

    for fmt in formats:
        if fmt not in FORMATS:
            raise ValueError(f"Unbekanntes Format: {fmt}. Möglich: {list(FORMATS)}")

    written: list[Path] = []
    if overwrite:
        producers: list[tuple[Path, Any]] = []
        if review_data is not None:
            normalized = {**review_data, "base_name": unique_base}
            producers.append((
                date_dir / f"{unique_base}.review.json",
                lambda path, data=normalized: _write_json(
                    path, data, private=bool(data.get("speaker_embeddings"))
                ),
            ))
        if marker_data is not None:
            producers.append((
                date_dir / f"{unique_base}.markers.json",
                lambda path, data=marker_data: path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
                ),
            ))
        for fmt in formats:
            suffix, writer = FORMATS[fmt]
            producers.append((
                date_dir / f"{unique_base}{suffix}",
                lambda path, writer=writer: writer(segments, path, bookmarks=bookmarks),
            ))
        return _transactional_publish(date_dir, producers)

    try:
        if review_data is not None:
            normalized_review_data = {**review_data, "base_name": unique_base}
            review_path = date_dir / f"{unique_base}.review.json"
            _write_json(
                review_path,
                normalized_review_data,
                private=bool(normalized_review_data.get("speaker_embeddings")),
            )
            written.append(review_path)

        if marker_data is not None:
            marker_path = date_dir / f"{unique_base}.markers.json"
            marker_path.write_text(
                json.dumps(marker_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            written.append(marker_path)

        for fmt in formats:
            suffix, writer = FORMATS[fmt]
            path = date_dir / f"{unique_base}{suffix}"
            writer(segments, path, bookmarks=bookmarks)
            written.append(path)
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise

    return written

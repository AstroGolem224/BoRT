"""Ausgabeformate: Text, Markdown, CSV/TSV (optional mit Bookmarks)."""

import csv
from datetime import datetime
from pathlib import Path

from .markers import Bookmark
from .speakers import SpeakerSegment

BOOKMARK_INDICATOR = "🔖"  # Bookmark-Marker im Transkript


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
                    f.write(
                        f"[{_format_time(bm.time)}] "
                        f"{BOOKMARK_INDICATOR} {bm.display}\n"
                    )
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
                        f"**{_format_time(bm.time)}** "
                        f"{BOOKMARK_INDICATOR} **{bm.display}**\n\n"
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
                f.write(
                    f"**{_format_time(seg.start)} – {_format_time(seg.end)}** "
                    f"{seg.text}\n\n"
                )


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
    while any(
        (output_dir / f"{candidate}{FORMATS[fmt][0]}").exists() for fmt in formats
    ):
        counter += 1
        candidate = f"{base_name}_{counter}"
    return candidate


FORMATS = {
    "txt": (".txt", write_text),
    "md": (".md", write_markdown),
    "csv": (".csv", lambda segs, path, **kw: write_csv(segs, path, ",", **kw)),
    "tsv": (".tsv", lambda segs, path, **kw: write_csv(segs, path, "\t", **kw)),
}


def write_outputs(
    segments: list[SpeakerSegment],
    output_dir: Path,
    base_name: str,
    formats: list[str],
    bookmarks: list[Bookmark] | None = None,
) -> list[Path]:
    """Schreibt die gewünschten Ausgabeformate, optional mit Bookmarks.

    Args:
        segments: Sprechersegmente.
        output_dir: Zielverzeichnis (Elternverzeichnis für Datumsordner).
        base_name: Basisname für die Ausgabedateien.
        formats: Liste der gewünschten Formate ('txt', 'md', 'csv', 'tsv').
        bookmarks: Optionale Bookmarks aus der Android-Partner-App.

    Returns:
        Liste der erzeugten Dateipfade.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    date_dir = _date_subdir(output_dir)
    unique_base = _unique_base_name(date_dir, base_name, formats)

    written: list[Path] = []
    for fmt in formats:
        if fmt not in FORMATS:
            raise ValueError(f"Unbekanntes Format: {fmt}. Möglich: {list(FORMATS)}")
        suffix, writer = FORMATS[fmt]
        path = date_dir / f"{unique_base}{suffix}"
        writer(segments, path, bookmarks=bookmarks)
        written.append(path)

    return written

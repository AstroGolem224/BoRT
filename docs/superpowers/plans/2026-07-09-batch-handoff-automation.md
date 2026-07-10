# Batch-Scan + Speaker-Review Handoff-Automatisierung Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BoRT bekommt einen "Batch verarbeiten"-Dialog, der unverarbeitete Audio+Marker-Paare in
einem Sync-Ordner findet und nacheinander mit der bestehenden Transkriptions-Pipeline verarbeitet, plus
einen "Sprecher nachträglich bearbeiten"-Flow, der Sprecher-Umbenennung auch lange nach einem
Batch-Lauf ermöglicht.

**Architektur:** Siehe `PLAN.md` (Repo-Wurzel) für die vollständige Design-Begründung, inkl. 3 Runden
Codex-Adversarial-Review (Verlauf in `PLAN-REVIEW-LOG.md`). Diese Datei ist der ausführbare
Task-für-Task-Plan mit vollständigem Code.

**Tech Stack:** Python 3.10+, customtkinter, pytest. Keine neuen Abhängigkeiten.

---

### Task 1: Companion-Marker-Suche nach `markers.py` extrahieren

**Files:**
- Modify: `src/bort/markers.py` (neue Funktionen anhängen)
- Modify: `src/bort/gui.py:52-65` (lokale `_looks_like_marker_file` entfernen, Import nutzen), `src/bort/gui.py:811-841` (`_auto_load_companion_marker` auf neue Funktion umstellen)
- Test: `tests/test_markers.py`

- [ ] **Step 1: Failing Tests schreiben**

An `tests/test_markers.py` anhängen:

```python
def test_find_companion_marker_android_format(tmp_path: Path) -> None:
    audio_path = tmp_path / "2026-07-08_19-30_BoR_Session.m4a"
    audio_path.write_bytes(b"")
    marker_path = tmp_path / "2026-07-08_19-30_BoR_Session.json"
    marker_path.write_text(
        json.dumps({"version": 1, "file": audio_path.name, "markers": []}),
        encoding="utf-8",
    )

    found = find_companion_marker(audio_path)

    assert found == marker_path


def test_find_companion_marker_bort_auto_markers(tmp_path: Path) -> None:
    audio_path = tmp_path / "session.m4a"
    audio_path.write_bytes(b"")
    marker_path = tmp_path / "session.markers.json"
    marker_path.write_text(
        json.dumps({"speakers": {}, "markers": []}), encoding="utf-8"
    )

    found = find_companion_marker(audio_path)

    assert found == marker_path


def test_find_companion_marker_none_found(tmp_path: Path) -> None:
    audio_path = tmp_path / "session.m4a"
    audio_path.write_bytes(b"")

    assert find_companion_marker(audio_path) is None


def test_find_companion_marker_ignores_non_marker_json(tmp_path: Path) -> None:
    audio_path = tmp_path / "session.m4a"
    audio_path.write_bytes(b"")
    (tmp_path / "session.json").write_text(
        json.dumps({"unrelated": True}), encoding="utf-8"
    )

    assert find_companion_marker(audio_path) is None
```

Import ergänzen in `tests/test_markers.py`:

```python
from bort.markers import MarkerError, SpeakerMarker, find_companion_marker, load_markers
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag verifizieren**

Run: `cd /home/itiger013/Dokumente/Github/BoRT && python -m pytest tests/test_markers.py -v`
Expected: FAIL mit `ImportError: cannot import name 'find_companion_marker'`

- [ ] **Step 3: `_looks_like_marker_file` und `find_companion_marker` in `markers.py` implementieren**

An `src/bort/markers.py` anhängen:

```python
def _looks_like_marker_file(path: Path) -> bool:
    """Prüft heuristisch, ob ``path`` eine lesbare Marker-JSON ist.

    Verhindert, dass zufällige ``<stem>.json``-Dateien ohne Marker-Bezug
    (z.B. andere Metadaten) als Marker übernommen werden. Akzeptiert werden
    JSON-Objekte mit einem ``markers``-Feld (Liste) – das deckt sowohl das
    Android-Format als auch das BoRT-Format ab.
    """
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False
    return isinstance(data, dict) and isinstance(data.get("markers"), list)


def find_companion_marker(audio_path: Path) -> Path | None:
    """Sucht eine passende Marker-JSON zu einer Audiodatei (gleicher Ordner).

    Reihenfolge:
      1. ``<stem>.json`` – Android-Partner-App (BookofRecords) mit Bookmarks
      2. ``<stem>.markers.json`` – BoRT-eigene Auto-Marker (whisperX)

    Gibt ``None`` zurück, wenn keine passende Datei existiert oder gefundene
    JSONs kein gültiges Marker-Format haben (ungültige JSONs werden still
    verworfen).
    """
    candidates = [
        audio_path.with_suffix(".json"),
        audio_path.parent / f"{audio_path.stem}.markers.json",
    ]
    for cand in candidates:
        if cand.exists() and _looks_like_marker_file(cand):
            return cand
    return None
```

- [ ] **Step 4: Tests laufen lassen, Erfolg verifizieren**

Run: `cd /home/itiger013/Dokumente/Github/BoRT && python -m pytest tests/test_markers.py -v`
Expected: PASS (alle Tests inkl. der 4 neuen)

- [ ] **Step 5: `gui.py` auf die extrahierte Funktion umstellen**

In `src/bort/gui.py:15-19` Import erweitern:

```python
from .markers import Bookmark, MarkerError, find_companion_marker, load_bookmarks, load_markers
```

In `src/bort/gui.py:52-65` die lokale Funktion `_looks_like_marker_file` komplett entfernen.

In `src/bort/gui.py:811-841` (`_auto_load_companion_marker`) ersetzen:

```python
    def _auto_load_companion_marker(self, audio_path: Path) -> None:
        """Sucht eine passende Marker-JSON zum Audio und trägt sie ein.

        Es wird nur eingetragen, wenn das Feld aktuell leer ist oder die
        gesetzte Datei nicht (mehr) existiert – eine bewusst gewählte Datei
        wird nicht überschrieben.
        """
        current = self.marker_var.get().strip()
        if current and Path(current).exists():
            return

        found = find_companion_marker(audio_path)
        if found is not None:
            self.marker_var.set(str(found))
            self.config.set_path("last_marker_path", found)
            self.config.set_path("last_marker_dir", found.parent)
            self.config.save()
            self._log("INFO", f"Marker-JSON automatisch geladen: {found.name}")
            return
        if current and not Path(current).exists():
            self.marker_var.set("")
```

- [ ] **Step 6: Vollen Testlauf verifizieren**

Run: `cd /home/itiger013/Dokumente/Github/BoRT && python -m pytest -v`
Expected: alle Tests PASS

- [ ] **Step 7: Commit**

```bash
cd /home/itiger013/Dokumente/Github/BoRT
git add src/bort/markers.py src/bort/gui.py tests/test_markers.py
git commit -m "refactor: extract companion-marker lookup into markers.py"
```

---

### Task 2: `write_outputs()` — `overwrite`- und `review_data`-Unterstützung

Fixt nebenbei einen bestehenden Bug: `SpeakerManagerWindow._on_apply` (Task 8) ruft `write_outputs()`
mit demselben `base_name` auf, der Sekunden zuvor schon geschrieben wurde — `_unique_base_name()`
sieht die existierende Datei und erzeugt `_1`-Duplikate statt zu überschreiben. `overwrite=True` behebt
das für beide Aufrufer (Live-Rename direkt nach einem Lauf UND den neuen Reopen-Flow).

**Files:**
- Modify: `src/bort/writers.py`
- Test: `tests/test_writers.py`

- [ ] **Step 1: Failing Tests schreiben**

An `tests/test_writers.py` anhängen:

```python
def test_write_outputs_overwrite_replaces_existing_files(tmp_path: Path) -> None:
    segments = [SpeakerSegment(start=0.0, end=1.0, speaker="SP1", text="Hallo")]

    first = write_outputs(segments, tmp_path, "session", ["txt"])
    assert first[0].read_text(encoding="utf-8").strip() != ""

    updated_segments = [
        SpeakerSegment(start=0.0, end=1.0, speaker="SP1", text="Geändert")
    ]
    second = write_outputs(
        updated_segments, first[0].parent, "session", ["txt"], overwrite=True
    )

    assert second[0] == first[0]
    assert "Geändert" in second[0].read_text(encoding="utf-8")
    # Kein _1-Duplikat erzeugt:
    assert not (first[0].parent / "session_1.txt").exists()


def test_write_outputs_without_overwrite_creates_unique_name(tmp_path: Path) -> None:
    segments = [SpeakerSegment(start=0.0, end=1.0, speaker="SP1", text="Hallo")]

    first = write_outputs(segments, tmp_path, "session", ["txt"])
    second = write_outputs(segments, tmp_path, "session", ["txt"])

    assert first[0] != second[0]
    assert second[0].name == "session_1.txt"


def test_write_outputs_with_review_data_writes_sidecar(tmp_path: Path) -> None:
    segments = [SpeakerSegment(start=0.0, end=1.0, speaker="SP1", text="Hallo")]
    review_data = {
        "schema_version": 1,
        "audio_path": str(tmp_path / "session.m4a"),
        "segments": [{"start": 0.0, "end": 1.0, "speaker": "SP1", "text": "Hallo"}],
        "speaker_map": {"SP1": "sprecher001"},
        "markers": [],
        "bookmarks": [],
        "base_name": "session",
        "formats": ["txt"],
    }

    paths = write_outputs(
        segments, tmp_path, "session", ["txt"], review_data=review_data
    )

    review_path = paths[0].parent / "session.review.json"
    assert review_path in paths
    saved = json.loads(review_path.read_text(encoding="utf-8"))
    assert saved == review_data
```

Imports in `tests/test_writers.py` sicherstellen (am Dateianfang ergänzen, falls nicht vorhanden):

```python
import json
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag verifizieren**

Run: `cd /home/itiger013/Dokumente/Github/BoRT && python -m pytest tests/test_writers.py -v`
Expected: FAIL — `write_outputs()` kennt `overwrite`/`review_data` noch nicht (`TypeError`)

- [ ] **Step 3: `write_outputs()` erweitern**

In `src/bort/writers.py`, `write_outputs` ersetzen durch:

```python
def write_outputs(
    segments: list[SpeakerSegment],
    output_dir: Path,
    base_name: str,
    formats: list[str],
    bookmarks: list[Bookmark] | None = None,
    review_data: dict | None = None,
    overwrite: bool = False,
) -> list[Path]:
    """Schreibt die gewünschten Ausgabeformate, optional mit Bookmarks.

    Args:
        segments: Sprechersegmente.
        output_dir: Zielverzeichnis. Bei ``overwrite=False`` das
            Elternverzeichnis für einen Datums-Unterordner (bisheriges
            Verhalten). Bei ``overwrite=True`` das exakte Zielverzeichnis
            selbst (kein Datums-Unterordner-Neuaufbau) — der Aufrufer muss
            in diesem Fall bereits den konkreten Ordner kennen, in dem die
            zu überschreibenden Dateien liegen.
        base_name: Basisname für die Ausgabedateien.
        formats: Liste der gewünschten Formate ('txt', 'md', 'csv', 'tsv').
        bookmarks: Optionale Bookmarks aus der Android-Partner-App.
        review_data: Optionales Speaker-Review-Sidecar-Dict. Wenn gesetzt,
            wird zusätzlich ``{unique_base}.review.json`` geschrieben.
        overwrite: Wenn True, wird kein neuer eindeutiger Dateiname gesucht,
            sondern exakt ``{base_name}{suffix}`` in ``output_dir``
            überschrieben (Verhalten für Sprecher-Umbenennung nach einem
            Lauf – siehe ``SpeakerManagerWindow._on_apply``).

    Returns:
        Liste der erzeugten Dateipfade (inkl. Review-Sidecar, falls
        angegeben).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if overwrite:
        date_dir = output_dir
        unique_base = base_name
    else:
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

    # Sidecar VOR den Transkripten schreiben: schlägt sie fehl, existieren noch
    # keine Transkript-Dateien, die scan_pending() später fälschlich als
    # "bereits verarbeitet, aber nicht nachbearbeitbar" einstufen könnte.
    if review_data is not None:
        # base_name in der Sidecar muss den TATSÄCHLICH gewählten unique_base
        # widerspiegeln (bei Kollision z.B. "session_1"), sonst zeigt der
        # spätere Reopen-Flow auf die falsche Transkript-Datei.
        normalized_review_data = {**review_data, "base_name": unique_base}
        review_path = date_dir / f"{unique_base}.review.json"
        with review_path.open("w", encoding="utf-8") as f:
            json.dump(normalized_review_data, f, indent=2, ensure_ascii=False)
        written.append(review_path)

    for fmt in formats:
        if fmt not in FORMATS:
            raise ValueError(f"Unbekanntes Format: {fmt}. Möglich: {list(FORMATS)}")
        suffix, writer = FORMATS[fmt]
        path = date_dir / f"{unique_base}{suffix}"
        writer(segments, path, bookmarks=bookmarks)
        written.append(path)

    return written
```

Der `for fmt in formats:`-Block, der vorher VOR dem `if review_data is not None:`-Block stand, wird
also nach hinten verschoben (Reihenfolge: Sidecar zuerst, dann Transkripte) — im obigen Codeblock ist
das bereits die finale Reihenfolge; beim Einfügen in `write_outputs()` den alten, doppelten
`for fmt in formats:`-Block (der ursprünglich vor `if review_data` stand) entfernen, sodass er nur
noch einmal (nach dem Sidecar-Block) vorkommt.

`json` muss in `src/bort/writers.py` importiert sein — am Dateianfang prüfen/ergänzen:

```python
import json
```

- [ ] **Step 3b: Test für `_1`-Kollision + Sidecar-`base_name`-Normalisierung ergänzen**

An `tests/test_writers.py` anhängen:

```python
def test_write_outputs_review_sidecar_base_name_matches_collision_name(
    tmp_path: Path,
) -> None:
    """Bei einer _1-Namenskollision muss die Sidecar auf den TATSÄCHLICH
    gewählten Dateinamen zeigen, sonst überschreibt ein späterer Reopen die
    falsche (erste) Transkript-Datei."""
    segments = [SpeakerSegment(start=0.0, end=1.0, speaker="SP1", text="Hallo")]
    review_data = {
        "schema_version": 1, "audio_path": str(tmp_path / "session.m4a"),
        "segments": [{"start": 0.0, "end": 1.0, "speaker": "SP1", "text": "Hallo"}],
        "speaker_map": {}, "markers": [], "bookmarks": [],
        "base_name": "session", "formats": ["txt"],
    }

    write_outputs(segments, tmp_path, "session", ["txt"])  # belegt "session.txt"
    second = write_outputs(
        segments, tmp_path, "session", ["txt"], review_data=review_data
    )

    review_path = second[0].parent / "session_1.review.json"
    assert review_path in second
    saved = json.loads(review_path.read_text(encoding="utf-8"))
    assert saved["base_name"] == "session_1"


def test_write_outputs_review_sidecar_failure_prevents_transcript_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Schlägt das Sidecar-Schreiben fehl, dürfen keine Transkript-Dateien
    entstehen — sonst hält scan_pending() den Lauf für abgeschlossen, obwohl
    er nicht nachbearbeitbar ist."""
    segments = [SpeakerSegment(start=0.0, end=1.0, speaker="SP1", text="Hallo")]
    review_data = {
        "schema_version": 1, "audio_path": str(tmp_path / "session.m4a"),
        "segments": [], "speaker_map": {}, "markers": [], "bookmarks": [],
        "base_name": "session", "formats": ["txt"],
    }

    real_open = Path.open

    def failing_open(self: Path, *args: object, **kwargs: object):
        if self.name == "session.review.json":
            raise OSError("Simulierter Schreibfehler")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)

    with pytest.raises(OSError):
        write_outputs(segments, tmp_path, "session", ["txt"], review_data=review_data)

    assert not (tmp_path / _today_subdir_name() / "session.txt").exists()
```

Hilfsfunktion `_today_subdir_name()` an den Anfang von `tests/test_writers.py` ergänzen (nutzt
`datetime`, muss bereits importiert sein oder wird ergänzt):

```python
from datetime import datetime


def _today_subdir_name() -> str:
    return datetime.now().strftime("%Y-%m-%d")
```

`import pytest` sicherstellen (für `monkeypatch`-Fixture, ist über pytest automatisch verfügbar,
kein separater Import nötig — nur `pytest.MonkeyPatch` als Typannotation braucht `import pytest`).

- [ ] **Step 4: Tests laufen lassen, Erfolg verifizieren**

Run: `cd /home/itiger013/Dokumente/Github/BoRT && python -m pytest tests/test_writers.py -v`
Expected: PASS (alle Tests inkl. der 5 neuen)

- [ ] **Step 5: Commit**

```bash
cd /home/itiger013/Dokumente/Github/BoRT
git add src/bort/writers.py tests/test_writers.py
git commit -m "feat: add overwrite and review_data support to write_outputs()

Fixes a latent bug where re-writing a transcript right after speaker
rename created _1 duplicates instead of overwriting."
```

---

### Task 3: `scan_pending()` — unverarbeitete Paare finden

**Files:**
- Create: `src/bort/batch.py`
- Test: `tests/test_batch.py`

- [ ] **Step 1: Failing Test schreiben**

Erstelle `tests/test_batch.py`:

```python
"""Tests für Batch-Scan (unverarbeitete Audio+Marker-Paare finden)."""

import json
import os
import time
from pathlib import Path

from bort.batch import PendingItem, is_file_stable, scan_pending


def test_scan_pending_finds_new_pair(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    output_dir = tmp_path / "output"
    watch_dir.mkdir()
    output_dir.mkdir()

    audio_path = watch_dir / "2026-07-08_19-30_BoR_Session.m4a"
    audio_path.write_bytes(b"")
    marker_path = watch_dir / "2026-07-08_19-30_BoR_Session.json"
    marker_path.write_text(
        json.dumps({"version": 1, "file": audio_path.name, "markers": []}),
        encoding="utf-8",
    )

    pending = scan_pending(watch_dir, output_dir)

    assert pending == [PendingItem(audio_path=audio_path, marker_path=marker_path)]


def test_scan_pending_excludes_already_processed(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    output_dir = tmp_path / "output"
    watch_dir.mkdir()
    output_dir.mkdir()

    audio_path = watch_dir / "session.m4a"
    audio_path.write_bytes(b"")

    date_dir = output_dir / "2026-07-09"
    date_dir.mkdir()
    (date_dir / "session.txt").write_text("transcript", encoding="utf-8")

    pending = scan_pending(watch_dir, output_dir)

    assert pending == []


def test_scan_pending_ignores_review_and_markers_sidecars_as_output(
    tmp_path: Path,
) -> None:
    """Eine Auto-Marker- oder Review-Sidecar-Datei allein zählt NICHT als
    Nachweis, dass eine Aufnahme verarbeitet wurde (Kernbug aus Codex-Review
    Runde 1: eine vor einem Exportfehler geschriebene Sidecar würde sonst
    einen Fehlschlag als Erfolg tarnen)."""
    watch_dir = tmp_path / "watch"
    output_dir = tmp_path / "output"
    watch_dir.mkdir()
    output_dir.mkdir()

    audio_path = watch_dir / "session.m4a"
    audio_path.write_bytes(b"")

    date_dir = output_dir / "2026-07-09"
    date_dir.mkdir()
    (date_dir / "session.markers.json").write_text("{}", encoding="utf-8")
    (date_dir / "session.review.json").write_text("{}", encoding="utf-8")

    pending = scan_pending(watch_dir, output_dir)

    assert pending == [PendingItem(audio_path=audio_path, marker_path=None)]


def test_scan_pending_stale_output_does_not_mask_newer_audio(
    tmp_path: Path,
) -> None:
    """Ein altes Transkript darf ein SPÄTER neu eingetroffenes, gleichnamiges
    Audio nicht als 'erledigt' maskieren (mtime-Vergleich)."""
    watch_dir = tmp_path / "watch"
    output_dir = tmp_path / "output"
    watch_dir.mkdir()
    output_dir.mkdir()

    date_dir = output_dir / "2026-07-01"
    date_dir.mkdir()
    old_output = date_dir / "session.txt"
    old_output.write_text("altes transkript", encoding="utf-8")
    old_time = time.time() - 3600
    os.utime(old_output, (old_time, old_time))

    audio_path = watch_dir / "session.m4a"
    audio_path.write_bytes(b"")  # mtime = jetzt, neuer als old_output

    pending = scan_pending(watch_dir, output_dir)

    assert pending == [PendingItem(audio_path=audio_path, marker_path=None)]


def test_scan_pending_ignores_non_audio_files(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    output_dir = tmp_path / "output"
    watch_dir.mkdir()
    output_dir.mkdir()

    (watch_dir / "session.json").write_text("{}", encoding="utf-8")
    (watch_dir / "notes.txt").write_text("hi", encoding="utf-8")

    assert scan_pending(watch_dir, output_dir) == []


def test_scan_pending_missing_watch_dir_returns_empty(tmp_path: Path) -> None:
    assert scan_pending(tmp_path / "does-not-exist", tmp_path / "output") == []


def test_is_file_stable_true_when_unchanged_across_samples(tmp_path: Path) -> None:
    path = tmp_path / "audio.m4a"
    path.write_bytes(b"1234")

    assert is_file_stable(path, interval=0.0, sleep_fn=lambda _: None) is True


def test_is_file_stable_false_when_size_changes_between_samples(
    tmp_path: Path,
) -> None:
    path = tmp_path / "audio.m4a"
    path.write_bytes(b"1234")

    calls = {"n": 0}

    def fake_sleep(_seconds: float) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            path.write_bytes(b"12345678")  # wächst zwischen den Samples

    assert is_file_stable(path, interval=0.0, sleep_fn=fake_sleep) is False
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag verifizieren**

Run: `cd /home/itiger013/Dokumente/Github/BoRT && python -m pytest tests/test_batch.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'bort.batch'`

- [ ] **Step 3: `src/bort/batch.py` implementieren**

```python
"""Findet unverarbeitete Audio+Marker-Paare in einem Sync-/Watch-Ordner.

Dateisystem ist die alleinige Wahrheitsquelle: ein Audio gilt als bereits
verarbeitet, sobald unter ``output_dir`` (auch in einem Datums-Unterordner,
siehe ``writers.write_outputs``) eine echte Transkript-Ausgabedatei mit
gleichem Stem existiert, die nicht älter ist als das Audio selbst.
Auto-Marker- und Review-Sidecar-Dateien zählen dabei NICHT als Nachweis, da
sie bereits vor einem möglichen Exportfehler geschrieben werden können.
"""

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
    """Prüft per Doppel-Stichprobe, ob eine Datei fertig kopiert wurde.

    Vergleicht Größe und Änderungszeit zweier Beobachtungen im Abstand von
    ``interval`` Sekunden. Nur wenn beide übereinstimmen, gilt die Datei als
    stabil (kein noch laufender SMB-Kopiervorgang). ``sleep_fn`` ist
    injizierbar, damit Tests nicht real warten müssen.
    """
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
    """Findet Audio-Dateien in ``watch_dir`` ohne gültiges Output.

    Prüft NICHT die Kopier-Stabilität (siehe :func:`is_file_stable` für
    einen separaten, expliziten Aufruf durch die GUI vor der Anzeige) — dies
    bleibt eine reine, schnelle Dateisystem-Abfrage ohne Wartezeit.

    Args:
        watch_dir: Ordner, in den die Partner-App (BoR) Aufnahmen ablegt
            (z.B. ein per Tailscale+SMB erreichbarer Ordner).
        output_dir: Ausgabeverzeichnis der Transkriptions-Pipeline.

    Returns:
        Liste von :class:`PendingItem`, sortiert nach Dateiname.
    """
    if not watch_dir.is_dir():
        return []

    items: list[PendingItem] = []
    for audio_path in sorted(watch_dir.iterdir()):
        if not audio_path.is_file() or not is_supported_audio(audio_path):
            continue
        if _has_output(audio_path, output_dir):
            continue
        items.append(
            PendingItem(
                audio_path=audio_path,
                marker_path=find_companion_marker(audio_path),
            )
        )
    return items
```

- [ ] **Step 4: Test laufen lassen, Erfolg verifizieren**

Run: `cd /home/itiger013/Dokumente/Github/BoRT && python -m pytest tests/test_batch.py -v`
Expected: PASS (alle Tests)

- [ ] **Step 5: Commit**

```bash
cd /home/itiger013/Dokumente/Github/BoRT
git add src/bort/batch.py tests/test_batch.py
git commit -m "feat: add scan_pending() and is_file_stable() for batch handoff"
```

---

### Task 4: `_build_params()` aus `_validate()` extrahieren

Reiner Refactor, verhaltensgleich — macht die Parameter-Erzeugung für beliebige Audio/Marker-Pfade
wiederverwendbar. Wird ausschließlich im Main-Thread aufgerufen (Task 11 baut alle Batch-Params im
Main-Thread, bevor der Worker-Thread startet — verhindert Tk-Zugriff aus einem Hintergrund-Thread).

**Files:**
- Modify: `src/bort/gui.py:916-991` (`_validate`)

- [ ] **Step 1: `_validate` in zwei Methoden aufteilen**

Ersetze die bestehende `_validate`-Methode durch:

```python
    def _validate(self) -> TranscriptionParams | None:
        """Validiert die Eingaben und gibt Parameter zurück oder None."""
        audio_path = Path(self.audio_var.get())
        if not audio_path.exists():
            show_error(self.root, "Fehler", "Audio-Datei nicht gefunden.")
            return None
        if not is_supported_audio(audio_path):
            show_error(
                self.root,
                "Fehler",
                f"Nicht unterstütztes Format: "
                f"{audio_path.suffix or '(keine Endung)'}.\n"
                f"Unterstützt: {', '.join(sorted(SUPPORTED_AUDIO_EXTS))}",
            )
            return None

        marker_path = Path(self.marker_var.get()) if self.marker_var.get() else None
        if marker_path and not marker_path.exists():
            show_error(self.root, "Fehler", "Marker-Datei nicht gefunden.")
            return None

        return self._build_params(audio_path, marker_path)

    def _build_params(
        self, audio_path: Path, marker_path: Path | None
    ) -> TranscriptionParams | None:
        """Baut TranscriptionParams aus den aktuellen Engine/Ausgabe-Einstellungen.

        Nimmt Audio- und Marker-Pfad als Argumente entgegen (statt aus den
        Tk-Feldern zu lesen), damit dieselbe Logik auch für Batch-Verarbeitung
        beliebiger Dateien genutzt werden kann. Darf NUR im Main-Thread
        aufgerufen werden (liest Tk-Variablen, kann Fehlerdialoge öffnen).
        """
        backend = BACKENDS[self.backend_display_var.get()]
        model_path: Path | None = None
        whisperx_model = "large-v3"
        if backend == "whispercpp":
            model_path = Path(self.model_var.get())
            if not model_path.exists():
                show_error(self.root, "Fehler", "Modell-Datei nicht gefunden.")
                return None
        else:
            whisperx_model = self.model_combo_var.get() or "large-v3"

        output_dir = Path(self.output_var.get())
        output_dir.mkdir(parents=True, exist_ok=True)

        formats = [fmt for fmt, var in self.format_vars.items() if var.get()]
        if not formats:
            show_error(self.root, "Fehler", "Mindestens ein Ausgabeformat auswählen.")
            return None

        language = self.language_var.get()

        min_speakers = None
        max_speakers = None
        if backend == "whisperx":
            if self.min_speakers_var.get().strip():
                try:
                    min_speakers = int(self.min_speakers_var.get())
                except ValueError:
                    show_error(self.root, "Fehler", "Min. Sprecher muss eine Zahl sein.")
                    return None
            if self.max_speakers_var.get().strip():
                try:
                    max_speakers = int(self.max_speakers_var.get())
                except ValueError:
                    show_error(self.root, "Fehler", "Max. Sprecher muss eine Zahl sein.")
                    return None

        return TranscriptionParams(
            audio_path=audio_path,
            marker_path=marker_path,
            model_path=model_path,
            language=language,
            output_dir=output_dir,
            formats=formats,
            keep_wav=self.keep_wav_var.get(),
            verbose=self.verbose_var.get(),
            task=TASK_OPTIONS[self.task_display_var.get()],
            backend=backend,
            whisperx_model=whisperx_model,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
            no_diarize=self.no_diarize_var.get(),
            auto_markers=self.auto_markers_var.get(),
        )
```

- [ ] **Step 2: Vollen Testlauf + manuellen Smoke-Test verifizieren**

Run: `cd /home/itiger013/Dokumente/Github/BoRT && python -m pytest -v`
Expected: alle Tests PASS

Manueller Smoke-Test: `python -m bort.gui` starten, Audio auswählen, "▶ Transkribieren" klicken —
Verhalten unverändert zu vorher.

- [ ] **Step 3: Commit**

```bash
cd /home/itiger013/Dokumente/Github/BoRT
git add src/bort/gui.py
git commit -m "refactor: extract _build_params() from _validate() for reuse by batch mode"
```

---

### Task 5: Job-Lock in `TranscriptionApp` + Logger-Handler-Fix

Zentrales, appweites Lock, das Haupt-„Transkribieren" und Batch-„Alle verarbeiten" gegenseitig
ausschließt (GPU-gebundene Pipeline erlaubt keine zwei gleichzeitigen Läufe). Freigabe läuft über
eine einzige Routine, die auf JEDEM Beendigungspfad aufgerufen wird. Zusätzlich: `_setup_worker_logging`
leert aktuell bei JEDEM Aufruf den kompletten Root-Logger (`root.handlers.clear()`) — bei mehreren
Läufen hintereinander (Batch!) reißt das andere Logger-Hierarchien mit und ist nicht robust gegen
parallele/schnell aufeinanderfolgende Aufrufe. Fix: nur den selbst hinzugefügten Handler gezielt
wieder entfernen.

**Files:**
- Modify: `src/bort/gui.py` (`_setup_worker_logging`, `transcription_worker`, `__init__`, `_on_run`, `_poll_queue`)

- [ ] **Step 0: `_setup_worker_logging`/`transcription_worker` Handler-Lebenszyklus fixen**

`_setup_worker_logging` (gui.py:104-111) ersetzen durch:

```python
def _setup_worker_logging(log_queue: queue.Queue, verbose: bool) -> logging.Handler:
    """Hängt einen Queue-Handler an den Root-Logger, OHNE bestehende Handler
    zu entfernen (wichtig bei mehreren Läufen hintereinander, z.B. Batch).
    Gibt den neu hinzugefügten Handler zurück, damit der Aufrufer ihn nach
    Lauf-Ende gezielt per `removeHandler` wieder entfernt.
    """
    root = logging.getLogger()
    handler = QueueLogHandler(log_queue)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    return handler
```

`transcription_worker` (gui.py:114-266) umschließt seinen bisherigen Körper mit `try/finally`, um den
Handler garantiert wieder zu entfernen:

```python
def transcription_worker(params: TranscriptionParams, log_queue: queue.Queue) -> None:
    """Läuft im Hintergrund-Thread und führt die Transkription aus."""
    handler = _setup_worker_logging(log_queue, params.verbose)
    logger = logging.getLogger(__name__)
    try:
        # --- ab hier: bisheriger Methodenkörper unverändert (Bookmarks laden,
        # whisperX/whisper.cpp-Zweig, write_outputs-Aufruf aus Task 6/2,
        # done_data, except-Block) ---
        ...
    finally:
        logging.getLogger().removeHandler(handler)
```

(Der `try:`/`except (...)`-Block, der im Original bereits vorhanden ist, bleibt als innerer Block
erhalten — das neue `try/finally` umschließt ihn zusätzlich von außen, entfernt also den Handler
sowohl bei Erfolg als auch nach einer der bestehenden `except`-Zweige.)

- [ ] **Step 0b: Manueller Test**

Run: `python -m bort.gui`, zwei Einzel-Läufe kurz hintereinander starten (z.B. gleiche Testdatei
zweimal). Expected: Log-Zeilen erscheinen in beiden Läufen jeweils genau einmal (kein doppeltes
Logging durch akkumulierte Handler).

- [ ] **Step 1: Lock-Attribut und Hilfsmethoden ergänzen**

In `TranscriptionApp.__init__` (nach `self.worker_thread: threading.Thread | None = None`, gui.py:287) ergänzen:

```python
        self.job_running = False
```

Neue Methoden nach `_hide_progress` (gui.py, nach Zeile 1077) einfügen:

```python
    def try_acquire_job(self) -> bool:
        """Versucht das appweite Job-Lock zu belegen. False, wenn belegt."""
        if self.job_running:
            return False
        self.job_running = True
        return True

    def release_job(self) -> None:
        """Gibt das appweite Job-Lock frei (idempotent)."""
        self.job_running = False
```

- [ ] **Step 2: `_on_run` das Lock nutzen lassen**

`_on_run` (gui.py:993-1015) am Anfang ergänzen:

```python
    def _on_run(self) -> None:
        if not self.try_acquire_job():
            show_error(
                self.root, "Fehler",
                "Es läuft bereits eine Transkription (Einzel-Lauf oder Batch).",
            )
            return
        params = self._validate()
        if params is None:
            self.release_job()
            return
        ...
```

(Restlicher Methodenkörper unverändert, nur die ersten Zeilen wie oben ergänzt — `params is None`
gibt das Lock sofort wieder frei statt es hängen zu lassen.)

- [ ] **Step 3: `_poll_queue` gibt das Lock bei `done`/`error` frei**

In `_poll_queue` (gui.py:1017-1072), sowohl im `"done"`- als auch im `"error"`-Zweig, direkt nach
`self.run_button.configure(state="normal")` ergänzen:

```python
                    self.release_job()
```

(Einmal im `done`-Zweig, einmal im `error`-Zweig — beide Stellen rufen bereits
`self.run_button.configure(state="normal")` auf, direkt danach `self.release_job()` einfügen.)

- [ ] **Step 4: Manueller Smoke-Test**

Run: `python -m bort.gui`, zweimal schnell hintereinander "▶ Transkribieren" klicken (zweiter Klick
während erster Lauf noch läuft) → Fehlerdialog "Es läuft bereits eine Transkription" statt zweitem
parallelen Lauf.

- [ ] **Step 5: Commit**

```bash
cd /home/itiger013/Dokumente/Github/BoRT
git add src/bort/gui.py
git commit -m "feat: add app-wide job lock to prevent concurrent transcription runs"
```

---

### Task 6: Review-Sidecar beim whisperX-Lauf schreiben

**Files:**
- Modify: `src/bort/gui.py` (`transcription_worker`)

- [ ] **Step 1: `review_data` im whisperX-Zweig bauen und an `write_outputs` übergeben**

In `transcription_worker` (gui.py:114-266), im `write_outputs`-Aufruf (gui.py:223-229) ersetzen durch:

```python
        review_data = None
        if params.backend == "whisperx":
            review_data = {
                "schema_version": 1,
                "audio_path": str(params.audio_path),
                "segments": [
                    {
                        "start": s.start, "end": s.end,
                        "speaker": s.speaker, "text": s.text,
                    }
                    for s in speaker_segments
                ],
                "speaker_map": dict(wx_speaker_map) if wx_speaker_map else {},
                "markers": [
                    {"start": m.start, "end": m.end, "speaker": m.speaker}
                    for m in (wx_markers or [])
                ],
                "bookmarks": [
                    {
                        "time": b.time, "label": b.label,
                        "type": b.type, "color": b.color,
                    }
                    for b in bookmarks
                ],
                "base_name": params.audio_path.stem,
                "formats": params.formats,
            }

        output_paths = write_outputs(
            segments=speaker_segments,
            output_dir=params.output_dir,
            base_name=params.audio_path.stem,
            formats=params.formats,
            bookmarks=bookmarks or None,
            review_data=review_data,
        )
```

In `done_data` (gui.py:244-255) den Schlüssel `"output_location"` ergänzen:

```python
        done_data = {
            "backend": params.backend,
            "audio_path": params.audio_path,
            "marker_path": params.marker_path,
            "segments": speaker_segments,
            "speaker_map": wx_speaker_map,
            "markers": wx_markers,
            "bookmarks": bookmarks,
            "output_dir": params.output_dir,
            "output_location": output_location,
            "base_name": params.audio_path.stem,
            "formats": params.formats,
        }
```

- [ ] **Step 2: `_open_speaker_manager` das exakte Zielverzeichnis übergeben**

In `_open_speaker_manager` (gui.py:1079-1101), im `SpeakerManagerWindow(...)`-Aufruf
`output_dir=data["output_dir"]` ersetzen durch `output_dir=data["output_location"]`:

```python
            SpeakerManagerWindow(
                parent=self.root,
                audio_path=data["audio_path"],
                segments=data["segments"],
                raw_segments=[],
                speaker_map=data["speaker_map"],
                markers=data["markers"] or [],
                bookmarks=data.get("bookmarks") or [],
                output_dir=data["output_location"],
                base_name=data["base_name"],
                formats=data["formats"],
            )
```

(Grund: `output_dir` war bisher der Wurzel-Ausgabeordner; `_on_apply`, Task 8, überschreibt künftig
direkt im übergebenen Verzeichnis, statt erneut einen Datums-Unterordner zu berechnen — dafür muss
das exakte, bereits existierende Zielverzeichnis übergeben werden.)

- [ ] **Step 3: Vollen Testlauf + manuellen Smoke-Test verifizieren**

Run: `cd /home/itiger013/Dokumente/Github/BoRT && python -m pytest -v`
Expected: alle Tests PASS

Manueller Smoke-Test: `python -m bort.gui`, whisperX-Backend, echte Audiodatei transkribieren →
im Ausgabeordner liegt zusätzlich `<stem>.review.json` neben den Transkript-Dateien.

- [ ] **Step 4: Commit**

```bash
cd /home/itiger013/Dokumente/Github/BoRT
git add src/bort/gui.py
git commit -m "feat: write speaker-review sidecar for whisperX runs"
```

---

### Task 7: `SpeakerManagerWindow` — Overwrite statt Duplikat, Sidecar aktuell halten

**Files:**
- Modify: `src/bort/speaker_manager.py` (`_on_apply`)

- [ ] **Step 1: `_on_apply` auf `overwrite=True` umstellen und Sidecar mitschreiben**

In `_on_apply` (speaker_manager.py:280-329), den `write_outputs`-Aufruf ersetzen:

```python
        review_data = {
            "schema_version": 1,
            "audio_path": str(self.audio_path),
            "segments": [
                {
                    "start": s.start, "end": s.end,
                    "speaker": s.speaker, "text": s.text,
                }
                for s in updated_segments
            ],
            "speaker_map": dict(new_map),
            "markers": [
                {"start": m.start, "end": m.end, "speaker": m.speaker}
                for m in updated_markers
            ],
            "bookmarks": [
                {
                    "time": b.time, "label": b.label,
                    "type": b.type, "color": b.color,
                }
                for b in self.bookmarks
            ],
            "base_name": self.base_name,
            "formats": self.formats,
        }

        try:
            output_paths = write_outputs(
                segments=updated_segments,
                output_dir=self.output_dir,
                base_name=self.base_name,
                formats=self.formats,
                bookmarks=self.bookmarks or None,
                review_data=review_data,
                overwrite=True,
            )
```

(Nur der `write_outputs(...)`-Aufruf wird ersetzt; die Zeilen davor — Aufbau von `new_map`,
`updated_segments`, `updated_markers` — und danach — `show_info(...)`, Exception-Handling — bleiben
unverändert.)

- [ ] **Step 2: Manueller Smoke-Test**

Run: `python -m bort.gui`, whisperX-Backend, echte Audiodatei transkribieren, im sich öffnenden
Speaker-Manager einen Sprecher umbenennen, "Anwenden" klicken.
Expected: dieselbe(n) Transkript-Datei(en) werden überschrieben (kein `_1`-Duplikat im
Ausgabeordner), `<stem>.review.json` enthält den neuen Sprechernamen.

- [ ] **Step 3: Commit**

```bash
cd /home/itiger013/Dokumente/Github/BoRT
git add src/bort/speaker_manager.py
git commit -m "fix: overwrite transcript in-place on speaker rename instead of creating _1 duplicates

Also keeps the speaker-review sidecar in sync with renames."
```

---

### Task 8: `speaker_review.py` — Sidecar laden/validieren

Reine, testbare Lade-Logik, getrennt von der GUI-Verdrahtung (Task 9).

**Files:**
- Create: `src/bort/speaker_review.py`
- Test: `tests/test_speaker_review.py`

- [ ] **Step 1: Failing Tests schreiben**

Erstelle `tests/test_speaker_review.py`:

```python
"""Tests für das Laden/Validieren von Speaker-Review-Sidecars."""

import json
from pathlib import Path

import pytest

from bort.markers import Bookmark, SpeakerMarker
from bort.speaker_review import ReviewData, ReviewError, load_review

VALID_DATA = {
    "schema_version": 1,
    "audio_path": "",  # wird pro Test mit echtem tmp_path gefüllt
    "segments": [{"start": 0.0, "end": 1.0, "speaker": "SP1", "text": "Hallo"}],
    "speaker_map": {"SP1": "sprecher001"},
    "markers": [{"start": 0.0, "end": 1.0, "speaker": "SP1"}],
    "bookmarks": [{"time": 0.5, "label": "Wichtig", "type": "note", "color": ""}],
    "base_name": "session",
    "formats": ["txt"],
}


def test_load_review_success(tmp_path: Path) -> None:
    audio_path = tmp_path / "session.m4a"
    audio_path.write_bytes(b"")
    review_path = tmp_path / "session.review.json"
    data = dict(VALID_DATA, audio_path=str(audio_path))
    review_path.write_text(json.dumps(data), encoding="utf-8")

    result = load_review(review_path)

    assert isinstance(result, ReviewData)
    assert result.audio_path == audio_path
    assert result.segments[0].speaker == "SP1"
    assert result.speaker_map == {"SP1": "sprecher001"}
    assert result.markers == [SpeakerMarker(0.0, 1.0, "SP1")]
    assert result.bookmarks == [Bookmark(0.5, "Wichtig", "note", "")]
    assert result.base_name == "session"
    assert result.formats == ["txt"]


def test_load_review_missing_file() -> None:
    with pytest.raises(ReviewError, match="nicht gefunden"):
        load_review(Path("/does/not/exist.review.json"))


def test_load_review_invalid_json(tmp_path: Path) -> None:
    review_path = tmp_path / "broken.review.json"
    review_path.write_text("not json", encoding="utf-8")

    with pytest.raises(ReviewError, match="ungültig"):
        load_review(review_path)


def test_load_review_missing_field(tmp_path: Path) -> None:
    review_path = tmp_path / "incomplete.review.json"
    incomplete = dict(VALID_DATA, audio_path=str(tmp_path / "x.m4a"))
    del incomplete["speaker_map"]
    review_path.write_text(json.dumps(incomplete), encoding="utf-8")

    with pytest.raises(ReviewError, match="speaker_map"):
        load_review(review_path)


def test_load_review_unsupported_schema_version(tmp_path: Path) -> None:
    review_path = tmp_path / "future.review.json"
    future = dict(VALID_DATA, audio_path=str(tmp_path / "x.m4a"), schema_version=99)
    review_path.write_text(json.dumps(future), encoding="utf-8")

    with pytest.raises(ReviewError, match="schema_version"):
        load_review(review_path)


def test_load_review_missing_audio_file(tmp_path: Path) -> None:
    review_path = tmp_path / "session.review.json"
    data = dict(VALID_DATA, audio_path=str(tmp_path / "does-not-exist.m4a"))
    review_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ReviewError, match="Audio"):
        load_review(review_path)


def test_load_review_malformed_nested_segment_raises_review_error(
    tmp_path: Path,
) -> None:
    """Ein Segment-Eintrag mit fehlendem/falsch typisiertem Feld darf keinen
    rohen KeyError/TypeError durchreichen, sondern muss als ReviewError
    landen (sonst crasht die GUI beim Reopen mit unklarer Meldung)."""
    audio_path = tmp_path / "session.m4a"
    audio_path.write_bytes(b"")
    review_path = tmp_path / "session.review.json"
    broken = dict(VALID_DATA, audio_path=str(audio_path))
    broken["segments"] = [{"start": 0.0, "end": 1.0, "text": "Hallo"}]  # "speaker" fehlt
    review_path.write_text(json.dumps(broken), encoding="utf-8")

    with pytest.raises(ReviewError, match="segments"):
        load_review(review_path)


def test_load_review_rejects_path_traversal_base_name(tmp_path: Path) -> None:
    """base_name aus einer (potenziell manuell bearbeiteten) Sidecar darf
    kein Pfadtrenner/'..' enthalten – sonst könnte SpeakerManagerWindow beim
    Overwrite außerhalb des Review-Ordners schreiben."""
    audio_path = tmp_path / "session.m4a"
    audio_path.write_bytes(b"")
    review_path = tmp_path / "session.review.json"
    malicious = dict(
        VALID_DATA, audio_path=str(audio_path), base_name="../../etc/evil"
    )
    review_path.write_text(json.dumps(malicious), encoding="utf-8")

    with pytest.raises(ReviewError, match="base_name"):
        load_review(review_path)


def test_load_review_rejects_unknown_format(tmp_path: Path) -> None:
    audio_path = tmp_path / "session.m4a"
    audio_path.write_bytes(b"")
    review_path = tmp_path / "session.review.json"
    bad_format = dict(VALID_DATA, audio_path=str(audio_path), formats=["exe"])
    review_path.write_text(json.dumps(bad_format), encoding="utf-8")

    with pytest.raises(ReviewError, match="formats"):
        load_review(review_path)
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag verifizieren**

Run: `cd /home/itiger013/Dokumente/Github/BoRT && python -m pytest tests/test_speaker_review.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'bort.speaker_review'`

- [ ] **Step 3: `src/bort/speaker_review.py` implementieren**

```python
"""Laden und Validieren von Speaker-Review-Sidecar-Dateien (`*.review.json`).

Diese Sidecars werden von `transcription_worker` (whisperX-Zweig) und von
`SpeakerManagerWindow._on_apply` geschrieben (siehe `writers.write_outputs`,
Parameter `review_data`). Sie erlauben es, Sprecher-Umbenennung auch lange
nach einem Transkriptions-Lauf erneut zu öffnen.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from .markers import Bookmark, SpeakerMarker
from .speakers import SpeakerSegment
from .writers import FORMATS

SUPPORTED_SCHEMA_VERSION = 1

REQUIRED_FIELDS = (
    "schema_version", "audio_path", "segments", "speaker_map",
    "markers", "bookmarks", "base_name", "formats",
)


class ReviewError(Exception):
    """Fehler beim Laden/Validieren einer Review-Sidecar-Datei."""


@dataclass(frozen=True)
class ReviewData:
    """Rekonstruierte, typisierte Sicht auf eine Review-Sidecar-Datei."""

    audio_path: Path
    segments: list[SpeakerSegment]
    speaker_map: dict[str, str]
    markers: list[SpeakerMarker]
    bookmarks: list[Bookmark]
    base_name: str
    formats: list[str]


def load_review(path: Path) -> ReviewData:
    """Lädt und validiert eine Review-Sidecar-Datei.

    Raises:
        ReviewError: bei fehlender Datei, ungültigem JSON, fehlenden
            Pflichtfeldern, nicht unterstützter Schema-Version oder wenn
            die referenzierte Audiodatei nicht mehr existiert.
    """
    path = Path(path)
    if not path.exists():
        raise ReviewError(f"Review-Datei nicht gefunden: {path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ReviewError(f"Review-Datei ist ungültig (kein JSON): {exc}") from exc

    if not isinstance(data, dict):
        raise ReviewError("Review-Datei ist ungültig (kein JSON-Objekt).")

    missing = [field for field in REQUIRED_FIELDS if field not in data]
    if missing:
        raise ReviewError(f"Review-Datei fehlt Pflichtfeld(er): {', '.join(missing)}")

    if data["schema_version"] != SUPPORTED_SCHEMA_VERSION:
        raise ReviewError(
            f"Nicht unterstützte schema_version: {data['schema_version']} "
            f"(erwartet: {SUPPORTED_SCHEMA_VERSION})"
        )

    audio_path = Path(data["audio_path"])
    if not audio_path.exists():
        raise ReviewError(f"Audio-Datei nicht mehr vorhanden: {audio_path}")

    base_name = data["base_name"]
    if (
        not isinstance(base_name, str)
        or not base_name
        or "/" in base_name
        or "\\" in base_name
        or base_name in {".", ".."}
    ):
        raise ReviewError(
            f"base_name ist ungültig (kein Pfadtrenner/'..' erlaubt): {base_name!r}"
        )

    formats = data["formats"]
    if not isinstance(formats, list) or not all(
        isinstance(fmt, str) and fmt in FORMATS for fmt in formats
    ):
        raise ReviewError(f"formats enthält unbekannte(s) Format(e): {formats!r}")

    try:
        segments = [
            SpeakerSegment(
                start=float(s["start"]), end=float(s["end"]),
                speaker=str(s["speaker"]), text=str(s["text"]),
            )
            for s in data["segments"]
        ]
        markers = [
            SpeakerMarker(
                start=float(m["start"]), end=float(m["end"]),
                speaker=str(m["speaker"]),
            )
            for m in data["markers"]
        ]
        bookmarks = [
            Bookmark(
                time=float(b["time"]), label=str(b.get("label", "")),
                type=str(b.get("type", "")), color=str(b.get("color", "")),
            )
            for b in data["bookmarks"]
        ]
        speaker_map = {str(k): str(v) for k, v in data["speaker_map"].items()}
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ReviewError(
            f"Review-Datei enthält ungültige segments/markers/bookmarks/"
            f"speaker_map-Einträge: {exc}"
        ) from exc

    return ReviewData(
        audio_path=audio_path,
        segments=segments,
        speaker_map=speaker_map,
        markers=markers,
        bookmarks=bookmarks,
        base_name=base_name,
        formats=list(formats),
    )
```

- [ ] **Step 4: Test laufen lassen, Erfolg verifizieren**

Run: `cd /home/itiger013/Dokumente/Github/BoRT && python -m pytest tests/test_speaker_review.py -v`
Expected: PASS (alle Tests)

- [ ] **Step 5: Commit**

```bash
cd /home/itiger013/Dokumente/Github/BoRT
git add src/bort/speaker_review.py tests/test_speaker_review.py
git commit -m "feat: add speaker-review sidecar loader with schema validation"
```

---

### Task 9: Reopen-Flow — "🎧 Sprecher nachträglich bearbeiten…"

**Files:**
- Modify: `src/bort/gui.py` (neue Methode + neuer Button)

- [ ] **Step 1: Neue Methode `_open_speaker_review` ergänzen**

Nach `_open_speaker_manager` (gui.py, nach Zeile 1101) einfügen:

```python
    def _open_speaker_review(self) -> None:
        """Öffnet eine gespeicherte Review-Sidecar zur nachträglichen Bearbeitung."""
        from .speaker_review import ReviewError, load_review

        path_str = ask_open_file(
            parent=self.root,
            title="Review-Datei auswählen",
            filetypes=[("Review-Dateien", "*.review.json"), ("Alle", "*.*")],
        )
        if not path_str:
            return

        try:
            review = load_review(Path(path_str))
        except ReviewError as exc:
            show_error(self.root, "Fehler", str(exc))
            return

        try:
            SpeakerManagerWindow(
                parent=self.root,
                audio_path=review.audio_path,
                segments=review.segments,
                raw_segments=[],
                speaker_map=review.speaker_map,
                markers=review.markers,
                bookmarks=review.bookmarks,
                output_dir=Path(path_str).parent,
                base_name=review.base_name,
                formats=review.formats,
            )
        except Exception as exc:
            logger = logging.getLogger(__name__)
            logger.exception("Speaker-Manager konnte nicht geöffnet werden")
            show_error(
                self.root, "Fehler",
                f"Speaker-Manager konnte nicht geöffnet werden:\n{exc}",
            )
```

- [ ] **Step 2: Button im Aktionsbereich ergänzen**

In `action_frame` (gui.py:521-544), nach dem "Beenden"-Button einfügen:

```python
        ctk.CTkButton(
            action_frame,
            text="🎧 Sprecher bearbeiten…",
            command=self._open_speaker_review,
            width=200,
            height=46,
            fg_color=COLORS["input_bg"],
            border_width=2,
            border_color=COLORS["border"],
            text_color=COLORS["text"],
        ).grid(row=0, column=3, padx=10)
```

(Vergibt `column=3` — `column=2` ist für den Batch-Button aus Task 12 reserviert.)

- [ ] **Step 3: Manueller End-to-End-Test**

Run: `python -m bort.gui`, whisperX-Backend, Testaudio transkribieren (erzeugt `.review.json`),
Speaker-Manager-Popup schließen ohne umzubenennen, dann "🎧 Sprecher bearbeiten…" klicken, die soeben
erzeugte `.review.json` auswählen.
Expected: Speaker-Manager öffnet sich erneut mit denselben Segmenten/Sprechern, Umbenennen+Anwenden
überschreibt das Transkript wie in Task 7 getestet.

- [ ] **Step 4: Commit**

```bash
cd /home/itiger013/Dokumente/Github/BoRT
git add src/bort/gui.py
git commit -m "feat: add reopen flow for post-hoc speaker review"
```

---

### Task 10: `BatchWindow` — Batch-Scan-Dialog

**Files:**
- Create: `src/bort/batch_window.py`

- [ ] **Step 1: `BatchWindow`-Klasse implementieren**

```python
"""Batch-Scan-Fenster: findet und verarbeitet unerledigte Sync-Ordner-Paare."""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk

from .batch import PendingItem, is_file_stable, scan_pending
from .dialogs import show_error, show_info
from .filedialogs import ask_directory
from .gui import transcription_worker
from .markers import MarkerError, load_markers
from .theme import COLORS

if TYPE_CHECKING:
    from .gui import TranscriptionApp

logger = logging.getLogger(__name__)


class BatchWindow(ctk.CTkToplevel):
    """Fenster zum Scannen und Batch-Verarbeiten eines Sync-Ordners."""

    def __init__(self, parent_app: "TranscriptionApp") -> None:
        super().__init__(parent_app.root)
        self.title("Batch verarbeiten")
        self.geometry("760x560")
        self.minsize(640, 480)

        self.parent_app = parent_app
        self.pending: list[PendingItem] = []
        self.log_queue: queue.Queue = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.scan_thread: threading.Thread | None = None
        self._stop_requested = False
        self._batch_running = False

        self.watch_dir_var = ctk.StringVar(
            value=str(parent_app.config.get_path("last_watch_dir") or "")
        )

        self._build_ui()
        self.transient(parent_app.root)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll_queue()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        dir_frame = ctk.CTkFrame(self, fg_color=COLORS["card_bg"], corner_radius=14)
        dir_frame.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 6))
        dir_frame.columnconfigure(1, weight=1)

        ctk.CTkLabel(dir_frame, text="Sync-Ordner:", width=110, anchor="w").grid(
            row=0, column=0, sticky="w", padx=14, pady=12
        )
        ctk.CTkEntry(
            dir_frame, textvariable=self.watch_dir_var,
            fg_color=COLORS["input_bg"], border_color=COLORS["border"],
        ).grid(row=0, column=1, sticky="we", padx=(0, 10), pady=12)
        ctk.CTkButton(
            dir_frame, text="Ordner wählen", command=self._browse_watch_dir,
            width=130, fg_color=COLORS["coral"], hover_color=COLORS["coral_hover"],
        ).grid(row=0, column=2, padx=(0, 10), pady=12)
        self.scan_button = ctk.CTkButton(
            dir_frame, text="🔍 Scannen", command=self._on_scan,
            width=110, fg_color=COLORS["coral"], hover_color=COLORS["coral_hover"],
        )
        self.scan_button.grid(row=0, column=3, padx=(0, 14), pady=12)

        list_frame = ctk.CTkFrame(self, fg_color=COLORS["card_bg"], corner_radius=14)
        list_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=6)
        list_frame.columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            list_frame, text="Noch nicht gescannt.", anchor="w",
        )
        self.status_label.grid(row=0, column=0, sticky="w", padx=14, pady=(12, 4))

        self.pending_text = ctk.CTkTextbox(
            list_frame, height=140, state="disabled", wrap="none",
            fg_color=COLORS["input_bg"], border_width=1,
            border_color=COLORS["border"], corner_radius=10,
        )
        self.pending_text.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))

        log_frame = ctk.CTkFrame(self, fg_color=COLORS["card_bg"], corner_radius=14)
        log_frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=6)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = ctk.CTkTextbox(
            log_frame, state="disabled", wrap="word",
            fg_color=COLORS["input_bg"], border_width=1,
            border_color=COLORS["border"], corner_radius=10,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=14, pady=14)

        action_frame = ctk.CTkFrame(self, fg_color="transparent")
        action_frame.grid(row=3, column=0, pady=(6, 16))
        self.process_button = ctk.CTkButton(
            action_frame, text="▶  Alle verarbeiten", command=self._on_process_all,
            width=200, height=42, fg_color=COLORS["coral"],
            hover_color=COLORS["coral_hover"], state="disabled",
        )
        self.process_button.grid(row=0, column=0, padx=10)
        self.cancel_button = ctk.CTkButton(
            action_frame, text="Abbrechen", command=self._on_cancel,
            width=120, height=42, fg_color="transparent", border_width=2,
            border_color=COLORS["border"], text_color=COLORS["muted"],
            state="disabled",
        )
        self.cancel_button.grid(row=0, column=1, padx=10)
        self.close_button = ctk.CTkButton(
            action_frame, text="Schließen", command=self._on_close,
            width=120, height=42, fg_color="transparent", border_width=2,
            border_color=COLORS["border"], text_color=COLORS["muted"],
        )
        self.close_button.grid(row=0, column=2, padx=10)

    def _browse_watch_dir(self) -> None:
        initial = self.watch_dir_var.get() or None
        path = ask_directory(
            parent=self, title="Sync-Ordner auswählen", initialdir=initial,
        )
        if path:
            self.watch_dir_var.set(path)
            self.parent_app.config.set_path("last_watch_dir", Path(path))
            self.parent_app.config.save()

    def _on_scan(self) -> None:
        watch_dir_raw = self.watch_dir_var.get().strip()
        if not watch_dir_raw:
            show_error(self, "Fehler", "Bitte zuerst einen Sync-Ordner wählen.")
            return
        if self.scan_thread is not None or self._batch_running:
            return

        self.scan_button.configure(state="disabled")
        self.process_button.configure(state="disabled")
        self.status_label.configure(text="Scanne …")
        watch_dir = Path(watch_dir_raw)
        output_dir = Path(self.parent_app.output_var.get())

        self.scan_thread = threading.Thread(
            target=self._run_scan, args=(watch_dir, output_dir), daemon=True,
        )
        self.scan_thread.start()

    def _run_scan(self, watch_dir: Path, output_dir: Path) -> None:
        """Läuft im Hintergrund-Thread: scan_pending() + Stabilitäts-Filter.

        Rührt kein Tk an — Ergebnis geht über die Queue an den Main-Thread.
        """
        candidates = scan_pending(watch_dir, output_dir)
        stable = [item for item in candidates if is_file_stable(item.audio_path)]
        skipped = len(candidates) - len(stable)
        self.log_queue.put(("scan_done", stable, skipped))

    def _on_scan_done(self, stable: list[PendingItem], skipped: int) -> None:
        self.pending = stable
        self.scan_thread = None
        self.scan_button.configure(state="normal")

        self.pending_text.configure(state="normal")
        self.pending_text.delete("1.0", "end")
        for item in self.pending:
            marker_info = f" (+ {item.marker_path.name})" if item.marker_path else ""
            self.pending_text.insert("end", f"{item.audio_path.name}{marker_info}\n")
        self.pending_text.configure(state="disabled")

        count = len(self.pending)
        status = (
            f"{count} unverarbeitete Aufnahme(n) gefunden."
            if count
            else "Keine unverarbeiteten Aufnahmen gefunden."
        )
        if skipped:
            status += f" ({skipped} noch instabil/wird kopiert, übersprungen)"
        self.status_label.configure(text=status)
        self.process_button.configure(state="normal" if count else "disabled")

    def _on_process_all(self) -> None:
        if not self.pending or self._batch_running:
            return
        if not self.parent_app.try_acquire_job():
            show_error(
                self, "Fehler",
                "Es läuft bereits eine Transkription (Einzel-Lauf oder Batch).",
            )
            return

        # Params für ALLE Items im Main-Thread bauen (Tk-Zugriff nur hier).
        built: list[tuple[PendingItem, object]] = []
        for item in self.pending:
            params = self.parent_app._build_params(item.audio_path, item.marker_path)
            built.append((item, params))

        self._batch_running = True
        self._stop_requested = False
        self.process_button.configure(state="disabled")
        self.scan_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")

        self.worker_thread = threading.Thread(
            target=self._run_batch, args=(built,), daemon=True,
        )
        self.worker_thread.start()

    def _run_batch(self, built: list[tuple[PendingItem, object]]) -> None:
        succeeded = 0
        failed = 0
        skipped = 0
        total = len(built)
        try:
            for index, (item, params) in enumerate(built, start=1):
                if self._stop_requested:
                    skipped += total - index + 1
                    break
                self.log_queue.put(
                    ("batch_item_start", index, total, item.audio_path.name)
                )

                if params is None:
                    failed += 1
                    self.log_queue.put(
                        ("batch_item_error", item.audio_path.name, "Ungültige Einstellungen")
                    )
                    continue

                # Erneute Prüfung direkt vor der Verarbeitung: Audio/Marker
                # können sich seit dem Scan verändert haben (SMB-Race).
                if not item.audio_path.exists() or not is_file_stable(item.audio_path):
                    skipped += 1
                    self.log_queue.put(
                        (
                            "batch_item_skip", item.audio_path.name,
                            "Audio nicht mehr vorhanden oder wird noch kopiert",
                        )
                    )
                    continue
                if item.marker_path is not None:
                    if not item.marker_path.exists() or not is_file_stable(
                        item.marker_path
                    ):
                        skipped += 1
                        self.log_queue.put(
                            (
                                "batch_item_skip", item.audio_path.name,
                                "Marker-Datei nicht mehr vorhanden oder wird noch kopiert",
                            )
                        )
                        continue
                    try:
                        load_markers(item.marker_path)
                    except MarkerError as exc:
                        self.log_queue.put(
                            (
                                "batch_item_skip", item.audio_path.name,
                                f"Marker-Datei ungültig geworden: {exc}",
                            )
                        )
                        skipped += 1
                        continue

                item_queue: queue.Queue = queue.Queue()
                transcription_worker(params, item_queue)
                outcome_ok, outcome_msg = self._drain_item_queue(item_queue, index, total)
                if outcome_ok:
                    succeeded += 1
                else:
                    failed += 1
                self.log_queue.put(
                    ("batch_item_done", item.audio_path.name, outcome_msg)
                )
        finally:
            # Garantiert IMMER gesendet, auch bei einer unerwarteten Exception
            # oben — sonst bleibt das Job-Lock (siehe _poll_queue) dauerhaft
            # belegt und die GUI ist gesperrt.
            self.log_queue.put(("batch_finished", succeeded, failed, skipped))

    def _drain_item_queue(
        self, item_queue: queue.Queue, index: int, total: int
    ) -> tuple[bool, str]:
        """Liest die Ergebnis-Queue eines einzelnen Laufs, reicht log/progress durch."""
        ok = False
        message = "Fehler: unbekannt"
        while True:
            try:
                item = item_queue.get_nowait()
            except queue.Empty:
                break
            kind = item[0]
            if kind == "log":
                _, level, msg = item
                self.log_queue.put(("batch_item_log", index, total, level, msg))
            elif kind == "progress":
                percent = item[1]
                phase = item[2] if len(item) > 2 else ""
                self.log_queue.put(("batch_item_progress", index, total, percent, phase))
            elif kind == "done":
                ok = True
                message = "OK"
            elif kind == "error":
                ok = False
                message = f"Fehler: {item[1]}"
        return ok, message

    def _on_cancel(self) -> None:
        self._stop_requested = True
        self.cancel_button.configure(state="disabled")
        self._append_log("Abbruch angefordert — stoppt nach aktuellem Item …")

    def _poll_queue(self) -> None:
        try:
            while True:
                item = self.log_queue.get_nowait()
                kind = item[0]
                if kind == "scan_done":
                    self._on_scan_done(item[1], item[2])
                elif kind == "batch_item_start":
                    _, index, total, name = item
                    self._append_log(f"[{index}/{total}] Verarbeite {name} …")
                elif kind == "batch_item_log":
                    _, index, total, level, msg = item
                    self._append_log(f"    {level}: {msg}")
                elif kind == "batch_item_progress":
                    _, index, total, percent, phase = item
                    self.status_label.configure(
                        text=f"[{index}/{total}] {int(percent)}% · {phase}"
                    )
                elif kind == "batch_item_done":
                    _, name, outcome = item
                    self._append_log(f"  → {name}: {outcome}")
                elif kind == "batch_item_error":
                    _, name, reason = item
                    self._append_log(f"  → {name}: Fehler ({reason})")
                elif kind == "batch_item_skip":
                    _, name, reason = item
                    self._append_log(f"  → {name}: übersprungen ({reason})")
                elif kind == "batch_finished":
                    _, succeeded, failed, skipped = item
                    self._append_log(
                        f"Batch abgeschlossen: {succeeded} OK, {failed} Fehler, "
                        f"{skipped} übersprungen."
                    )
                    self.worker_thread = None
                    self._batch_running = False
                    self.pending = []
                    self.pending_text.configure(state="normal")
                    self.pending_text.delete("1.0", "end")
                    self.pending_text.configure(state="disabled")
                    self.status_label.configure(
                        text="Batch abgeschlossen — erneut scannen für weitere Aufnahmen."
                    )
                    self.process_button.configure(state="disabled")
                    self.scan_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    self.parent_app.release_job()
                    show_info(
                        self, "Fertig",
                        f"Batch abgeschlossen: {succeeded} OK, {failed} Fehler, "
                        f"{skipped} übersprungen.",
                    )
        except queue.Empty:
            pass
        finally:
            self.after(150, self._poll_queue)

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _on_close(self) -> None:
        if self._batch_running:
            show_error(
                self, "Batch läuft noch",
                "Bitte zuerst 'Abbrechen' klicken und das aktuelle Item abwarten, "
                "bevor das Fenster geschlossen wird.",
            )
            return
        if self.scan_thread is not None:
            show_error(
                self, "Scan läuft noch",
                "Bitte warten, bis der Scan abgeschlossen ist, bevor das Fenster "
                "geschlossen wird.",
            )
            return
        self.destroy()
```

**Design-Entscheidungen (bewusst einfach gehalten):**
- Kein eigenes Settings-UI — nutzt Backend/Modell/Formate, die aktuell im Hauptfenster stehen.
- Strikt sequentiell in einem Hintergrund-Thread — passend zur GPU-gebundenen whisperX-Pipeline.
- Ein Item-Fehler bricht den Batch nicht ab, wird geloggt und gezählt.
- Scan läuft ebenfalls in einem Hintergrund-Thread (wegen der 2-Sekunden-Stabilitätsprüfung pro
  Kandidat, die sonst die GUI einfrieren würde) — liest aber ebenfalls keine Tk-Variablen, reicht
  Ergebnisse nur über die Queue zurück.

- [ ] **Step 2: Manueller Smoke-Test**

Run: `cd /home/itiger013/Dokumente/Github/BoRT && python -c "from bort.batch_window import BatchWindow"`
Expected: kein Fehler.

- [ ] **Step 3: Commit**

```bash
cd /home/itiger013/Dokumente/Github/BoRT
git add src/bort/batch_window.py
git commit -m "feat: add BatchWindow with thread-safe scan and sequential processing"
```

---

### Task 11: Batch-Button ins Hauptfenster einhängen

**Files:**
- Modify: `src/bort/gui.py:521-544` (Aktions-Buttons-Zeile)

- [ ] **Step 1: `_open_batch_window`-Methode ergänzen**

Nach `_open_speaker_review` (Task 9) einfügen:

```python
    def _open_batch_window(self) -> None:
        """Öffnet das Batch-Scan-Fenster."""
        if self.job_running:
            show_error(
                self.root, "Fehler",
                "Es läuft bereits eine Transkription (Einzel-Lauf oder Batch).",
            )
            return
        from .batch_window import BatchWindow

        BatchWindow(self)
```

(Der Check hier verhindert nur das ÖFFNEN während eines laufenden Einzel-Laufs; das eigentliche Lock
für den Batch-LAUF selbst übernimmt `BatchWindow._on_process_all` über `try_acquire_job()`, Task 10.)

- [ ] **Step 2: Button in `action_frame` ergänzen**

Nach dem "Beenden"-Button (gui.py:544) einfügen:

```python
        ctk.CTkButton(
            action_frame,
            text="📦 Batch verarbeiten…",
            command=self._open_batch_window,
            width=200,
            height=46,
            fg_color=COLORS["input_bg"],
            border_width=2,
            border_color=COLORS["border"],
            text_color=COLORS["text"],
        ).grid(row=0, column=2, padx=10)
```

- [ ] **Step 3: Manueller End-to-End-Test**

Run: `python -m bort.gui`

1. Zwei Test-Audiodateien in einen leeren Testordner legen, eine mit passender `<stem>.json`
   (Android-Format).
2. Ausgabeverzeichnis im Hauptfenster wählen.
3. "📦 Batch verarbeiten…" klicken → Fenster öffnet sich.
4. Testordner als Sync-Ordner wählen, "🔍 Scannen" klicken (wartet je Kandidat ~2s für den
   Stabilitäts-Check) → beide Dateien erscheinen in der Liste.
5. "▶ Alle verarbeiten" klicken → Log zeigt beide Dateien nacheinander mit "OK", Erfolgs-/Fehlerzahl
   am Ende korrekt.
6. Ausgabeverzeichnis prüfen → Transkripte + (bei whisperX-Backend) `.review.json` im
   Datums-Unterordner.
7. Erneut "Scannen" im selben Sync-Ordner → Liste ist leer.
8. Während "Alle verarbeiten" läuft, Fenster schließen versuchen → Fehlermeldung "Batch läuft noch",
   Fenster bleibt offen. "Abbrechen" klicken, warten bis aktuelles Item fertig, dann schließen →
   funktioniert.
9. Während Batch läuft, im Hauptfenster "▶ Transkribieren" klicken → Fehlermeldung "Es läuft bereits
   eine Transkription".
10. Während "🔍 Scannen" läuft (auf einem Ordner mit mehreren Dateien, damit der ~2s-Stabilitäts-Check
    pro Datei spürbar dauert), Fenster schließen versuchen → Fehlermeldung "Scan läuft noch", Fenster
    bleibt offen.

- [ ] **Step 4: Vollen Testlauf verifizieren**

Run: `cd /home/itiger013/Dokumente/Github/BoRT && python -m pytest -v`
Expected: alle Tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/itiger013/Dokumente/Github/BoRT
git add src/bort/gui.py
git commit -m "feat: wire batch-processing button into main window"
```

---

### Task 12: Transfer-Setup dokumentieren (Tailscale+SMB, kein Code)

**Files:**
- Modify: `HANDOVER.md` (neuer Abschnitt anhängen)

- [ ] **Step 1: Abschnitt "Sync-Ordner-Setup (Tailscale+SMB)" an `HANDOVER.md` anhängen**

```markdown
## Sync-Ordner-Setup (Tailscale+SMB)

Statt manuellem Google-Drive-Download: BoR (Android) legt Aufnahmen direkt auf einer SMB-Freigabe
des PCs ab, erreichbar über Tailscale.

1. **PC:** Samba-Freigabe auf einen Zielordner einrichten (dieser Ordner ist der "Sync-Ordner", der
   in BoRT unter "📦 Batch verarbeiten…" ausgewählt wird). Least-privilege einrichten:
   - dedizierter Samba-Benutzer, kein Gastzugriff (`guest ok = no`)
   - Freigabe nur lesbar/schreibbar für diesen Benutzer, keine anderen lokalen Nutzer
   - Samba-Port (445) nur auf dem Tailscale-Interface binden bzw. per Firewall auf das
     Tailnet-Subnetz beschränken, nicht auf das normale LAN/Internet exponieren
2. **Tailscale:** auf PC und Handy installieren, gleiches Tailnet, Tailnet-ACLs so setzen, dass nur
   das Handy-Gerät auf den SMB-Port des PCs zugreifen darf.
3. **Handy (BoR):** in den BoR-Einstellungen als SAF-Zielordner
   `\\<pc-tailscale-ip>\<freigabename>` wählen (Android-Stock-Dateien-App unterstützt
   SMB-Netzwerkspeicher ab Android 10; falls nicht ausreichend, Fallback-App wie CX File Explorer
   nutzen).
4. Der bestehende BoR-`Mover` kopiert fertige Aufnahme-Paare automatisch dorthin (bei
   Recording-Stop/App-Start/Library-Open) — kein BoR-Code geändert.

**Bekanntes Risiko:** SMB über VPN-Tunnel bei Verbindungsabbruch während des Schreibens. BoRTs
Batch-Scan prüft jede Kandidatendatei per Zwei-Sample-Stabilitätscheck (Größe+mtime im Abstand von
2s), bevor sie als "bereit" gilt — verringert das Risiko, eine Teilkopie zu verarbeiten, eliminiert es
aber nicht vollständig unter echter Netzwerklast. Bei Auffälligkeiten (unvollständige Dateien im
Sync-Ordner) zuerst dort prüfen, bevor BoR-Code angefasst wird.
```

- [ ] **Step 2: Commit**

```bash
cd /home/itiger013/Dokumente/Github/BoRT
git add HANDOVER.md
git commit -m "docs: document Tailscale+SMB sync-folder setup for batch handoff"
```

---

## Spec-Abdeckung (Selbst-Review)

- Transfer (Tailscale+SMB): Task 12 (Doku, kein Code).
- `scan_pending`/Stabilität/„bereits verarbeitet"-Korrektheit: Task 3.
- Batch-UI, Thread-Sicherheit, Job-Lock, sicheres Schließen, ehrliche Zusammenfassung: Task 5, 10, 11.
- Speaker-Review-Sidecar + Reopen-Flow (Nutzer-Entscheidung nach Codex-Runde 2): Task 2, 6, 7, 8, 9.
- Overwrite-Fix für Sprecher-Umbenennung (Codex-Runde 3, betrifft auch bestehenden Live-Rename-Bug):
  Task 2, 7.
- Alle in PLAN.md unter "Key decisions" dokumentierten, bewusst abgelehnten Punkte (Stem-Kollision
  zwischen Audio-Endungen, keine Parallelverarbeitung) sind NICHT Teil dieses Task-Plans — siehe
  PLAN.md „Out of scope" für die Begründung.
- Codex-Runde 4 (Logger-Fix fehlte als Task, Sidecar-`base_name` bei `_1`-Kollision, Atomizitäts-
  Reihenfolge Sidecar-vor-Transkript, `load_review`-Typvalidierung, Path-Traversal-Schutz,
  erneuter Stabilitäts-Check pro Item, `try/finally` um `_run_batch`, Schließen-Sperre auch
  während Scan): eingearbeitet in Task 2, 5, 8, 10.

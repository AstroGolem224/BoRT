# Batch-Scan Handoff-Automatisierung Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BoRT bekommt einen "Batch verarbeiten"-Dialog, der unverarbeitete Audio+Marker-Paare in einem Sync-Ordner findet und nacheinander mit der bestehenden Transkriptions-Pipeline verarbeitet — ersetzt die manuelle Einzeldatei-Auswahl für den Sync-Ordner-Workflow.

**Architektur:** Neue reine Funktion `scan_pending()` in `src/bort/batch.py` findet Audio-Dateien ohne passendes Output-Transkript (Dateisystem als Wahrheitsquelle, kein State-File). Companion-Marker-Suche wird aus `gui.py` in `markers.py` extrahiert (DRY, von Einzeldatei- und Batch-Flow genutzt). Neues `BatchWindow` (customtkinter `CTkToplevel`, analog zu bestehendem `SpeakerManagerWindow`-Pattern) zeigt gefundene Paare, verarbeitet sie sequentiell über die bestehende `transcription_worker()`-Funktion (keine Änderung an der Kernlogik). Die Transfer-Seite (Tailscale+SMB als SAF-Ziel auf dem Handy) ist reine Infrastruktur-/Nutzerkonfiguration ohne Code-Änderung — wird als Dokumentations-Task erfasst.

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

An `src/bort/markers.py` anhängen (ans Ende der Datei):

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

In `src/bort/gui.py:52-65` die lokale Funktion `_looks_like_marker_file` komplett entfernen (Zeilen 52-65).

In `src/bort/gui.py:811-841` (`_auto_load_companion_marker`) den Suchblock ersetzen:

```python
    def _auto_load_companion_marker(self, audio_path: Path) -> None:
        """Sucht eine passende Marker-JSON zum Audio und trägt sie ein.

        Es wird nur eingetragen, wenn das Feld aktuell leer ist oder die
        gesetzte Datei nicht (mehr) existiert – eine bewusst gewählte Datei
        wird nicht überschrieben.
        """
        current = self.marker_var.get().strip()
        if current and Path(current).exists():
            # Bereits eine gültige Marker-Datei gesetzt – nichts ändern.
            return

        found = find_companion_marker(audio_path)
        if found is not None:
            self.marker_var.set(str(found))
            self.config.set_path("last_marker_path", found)
            self.config.set_path("last_marker_dir", found.parent)
            self.config.save()
            self._log("INFO", f"Marker-JSON automatisch geladen: {found.name}")
            return
        # Keine passende JSON gefunden – ggf. veralteten Eintrag löschen.
        if current and not Path(current).exists():
            self.marker_var.set("")
```

- [ ] **Step 6: Vollen Testlauf + manuellen Smoke-Test verifizieren**

Run: `cd /home/itiger013/Dokumente/Github/BoRT && python -m pytest -v`
Expected: alle Tests PASS (kein Verhalten geändert, nur verschoben)

- [ ] **Step 7: Commit**

```bash
cd /home/itiger013/Dokumente/Github/BoRT
git add src/bort/markers.py src/bort/gui.py tests/test_markers.py
git commit -m "refactor: extract companion-marker lookup into markers.py

Enables reuse by the upcoming batch-scan feature without duplicating
the marker-file heuristics that already live in gui.py."
```

---

### Task 2: `scan_pending()` — unverarbeitete Paare finden

**Files:**
- Create: `src/bort/batch.py`
- Test: `tests/test_batch.py`

- [ ] **Step 1: Failing Test schreiben**

Erstelle `tests/test_batch.py`:

```python
"""Tests für Batch-Scan (unverarbeitete Audio+Marker-Paare finden)."""

import json
from pathlib import Path

from bort.batch import PendingItem, scan_pending


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

    # Bereits verarbeitet: Output liegt in einem Datums-Unterordner
    # (schreibt schon `write_outputs()` so), nicht direkt in output_dir.
    date_dir = output_dir / "2026-07-09"
    date_dir.mkdir()
    (date_dir / "session.txt").write_text("transcript", encoding="utf-8")

    pending = scan_pending(watch_dir, output_dir)

    assert pending == []


def test_scan_pending_no_marker_still_included(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    output_dir = tmp_path / "output"
    watch_dir.mkdir()
    output_dir.mkdir()

    audio_path = watch_dir / "session.m4a"
    audio_path.write_bytes(b"")

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
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag verifizieren**

Run: `cd /home/itiger013/Dokumente/Github/BoRT && python -m pytest tests/test_batch.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'bort.batch'`

- [ ] **Step 3: `src/bort/batch.py` implementieren**

```python
"""Findet unverarbeitete Audio+Marker-Paare in einem Sync-/Watch-Ordner.

Dateisystem ist die alleinige Wahrheitsquelle: ein Audio gilt als bereits
verarbeitet, sobald irgendwo unter ``output_dir`` (auch in einem
Datums-Unterordner, siehe ``writers.write_outputs``) eine Datei mit
gleichem Stem existiert. Kein separates State-File nötig.
"""

from dataclasses import dataclass
from pathlib import Path

from .audio import is_supported_audio
from .markers import find_companion_marker


@dataclass(frozen=True)
class PendingItem:
    """Ein noch nicht transkribiertes Audio, optional mit Marker-Datei."""

    audio_path: Path
    marker_path: Path | None


def _has_output(audio_path: Path, output_dir: Path) -> bool:
    """Prüft, ob bereits eine Ausgabedatei für dieses Audio existiert."""
    if not output_dir.is_dir():
        return False
    return any(output_dir.rglob(f"{audio_path.stem}.*"))


def scan_pending(watch_dir: Path, output_dir: Path) -> list[PendingItem]:
    """Findet Audio-Dateien in ``watch_dir`` ohne zugehöriges Output.

    Args:
        watch_dir: Ordner, in den die Partner-App (BoR) Aufnahmen ablegt
            (z.B. ein per Tailscale+SMB erreichbarer Ordner).
        output_dir: Ausgabeverzeichnis der Transkriptions-Pipeline
            (gleicher Ordner, den auch die Einzeldatei-Verarbeitung nutzt).

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
Expected: PASS (alle 5 Tests)

- [ ] **Step 5: Commit**

```bash
cd /home/itiger013/Dokumente/Github/BoRT
git add src/bort/batch.py tests/test_batch.py
git commit -m "feat: add scan_pending() to find unprocessed audio+marker pairs"
```

---

### Task 3: `_build_params()` aus `_validate()` extrahieren (Vorbereitung Batch-Verarbeitung)

Reiner Refactor, verhaltensgleich — macht die Parameter-Erzeugung für beliebige Audio/Marker-Pfade wiederverwendbar (nicht nur die aktuell in der GUI eingetragenen), damit `BatchWindow` (Task 4) dieselbe Validierungs-/Params-Logik nutzt statt sie zu duplizieren.

**Files:**
- Modify: `src/bort/gui.py:916-991` (`_validate`)

- [ ] **Step 1: `_validate` in `gui.py` in zwei Methoden aufteilen**

Ersetze die bestehende `_validate`-Methode (gui.py:916-991) durch:

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
        beliebiger Dateien genutzt werden kann.
        """
        backend = BACKENDS[self.backend_display_var.get()]
        model_path: Path | None = None
        whisperx_model = "large-v3"
        if backend == "whispercpp":
            model_path = Path(self.model_var.get())
            if not model_path.exists():
                show_error(self.root, "Fehler", "Modell-Datei nicht gefunden.")
                return None
        else:  # whisperx
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

- [ ] **Step 2: Bestehende Tests + manuellen Smoke-Test verifizieren**

Run: `cd /home/itiger013/Dokumente/Github/BoRT && python -m pytest -v`
Expected: alle Tests weiterhin PASS (reiner Refactor, betrifft keine Test-Datei direkt)

Manueller Smoke-Test (GUI hat keine automatisierten Tests):
Run: `cd /home/itiger013/Dokumente/Github/BoRT && python -m bort.gui`
Erwartet: App startet unverändert, eine Test-Audiodatei auswählen und "▶ Transkribieren" klicken läuft wie vorher durch (gleiches Verhalten wie vor dem Refactor).

- [ ] **Step 3: Commit**

```bash
cd /home/itiger013/Dokumente/Github/BoRT
git add src/bort/gui.py
git commit -m "refactor: extract _build_params() from _validate() for reuse by batch mode"
```

---

### Task 4: `BatchWindow` — Batch-Scan-Dialog

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

from .batch import PendingItem, scan_pending
from .dialogs import show_error, show_info
from .filedialogs import ask_directory
from .gui import transcription_worker
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
        self._stop_requested = False

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

        # --- Sync-Ordner-Zeile ---
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
        ctk.CTkButton(
            dir_frame, text="🔍 Scannen", command=self._on_scan,
            width=110, fg_color=COLORS["coral"], hover_color=COLORS["coral_hover"],
        ).grid(row=0, column=3, padx=(0, 14), pady=12)

        # --- Ergebnis-Liste ---
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

        # --- Log ---
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

        # --- Aktionen ---
        action_frame = ctk.CTkFrame(self, fg_color="transparent")
        action_frame.grid(row=3, column=0, pady=(6, 16))
        self.process_button = ctk.CTkButton(
            action_frame, text="▶  Alle verarbeiten", command=self._on_process_all,
            width=200, height=42, fg_color=COLORS["coral"],
            hover_color=COLORS["coral_hover"], state="disabled",
        )
        self.process_button.grid(row=0, column=0, padx=10)
        ctk.CTkButton(
            action_frame, text="Schließen", command=self._on_close,
            width=120, height=42, fg_color="transparent", border_width=2,
            border_color=COLORS["border"], text_color=COLORS["muted"],
        ).grid(row=0, column=1, padx=10)

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
        watch_dir = Path(watch_dir_raw)
        output_dir = Path(self.parent_app.output_var.get())

        self.pending = scan_pending(watch_dir, output_dir)

        self.pending_text.configure(state="normal")
        self.pending_text.delete("1.0", "end")
        for item in self.pending:
            marker_info = f" (+ {item.marker_path.name})" if item.marker_path else ""
            self.pending_text.insert("end", f"{item.audio_path.name}{marker_info}\n")
        self.pending_text.configure(state="disabled")

        count = len(self.pending)
        self.status_label.configure(
            text=f"{count} unverarbeitete Aufnahme(n) gefunden."
            if count
            else "Keine unverarbeiteten Aufnahmen gefunden."
        )
        self.process_button.configure(state="normal" if count else "disabled")

    def _on_process_all(self) -> None:
        if not self.pending or self.worker_thread is not None:
            return
        self.process_button.configure(state="disabled")
        self._stop_requested = False
        self.worker_thread = threading.Thread(
            target=self._run_batch, args=(list(self.pending),), daemon=True,
        )
        self.worker_thread.start()

    def _run_batch(self, items: list[PendingItem]) -> None:
        total = len(items)
        for index, item in enumerate(items, start=1):
            if self._stop_requested:
                break
            self.log_queue.put(
                ("batch_item_start", index, total, item.audio_path.name)
            )
            params = self.parent_app._build_params(item.audio_path, item.marker_path)
            if params is None:
                self.log_queue.put(
                    ("batch_item_error", item.audio_path.name, "Ungültige Einstellungen")
                )
                continue
            item_queue: queue.Queue = queue.Queue()
            transcription_worker(params, item_queue)
            outcome = self._drain_item_queue(item_queue)
            self.log_queue.put(
                ("batch_item_done", item.audio_path.name, outcome)
            )
        self.log_queue.put(("batch_finished", total))

    def _drain_item_queue(self, item_queue: queue.Queue) -> str:
        """Liest die Ergebnis-Queue eines einzelnen Transkriptionslaufs aus."""
        result = "Fehler: unbekannt"
        while True:
            try:
                item = item_queue.get_nowait()
            except queue.Empty:
                break
            if item[0] == "done":
                result = "OK"
            elif item[0] == "error":
                result = f"Fehler: {item[1]}"
        return result

    def _poll_queue(self) -> None:
        try:
            while True:
                item = self.log_queue.get_nowait()
                kind = item[0]
                if kind == "batch_item_start":
                    _, index, total, name = item
                    self._append_log(f"[{index}/{total}] Verarbeite {name} …")
                elif kind == "batch_item_done":
                    _, name, outcome = item
                    self._append_log(f"  → {name}: {outcome}")
                elif kind == "batch_item_error":
                    _, name, reason = item
                    self._append_log(f"  → {name}: übersprungen ({reason})")
                elif kind == "batch_finished":
                    total = item[1]
                    self._append_log(f"Batch abgeschlossen ({total} Datei(en)).")
                    self.worker_thread = None
                    self.process_button.configure(state="normal")
                    show_info(self, "Fertig", f"Batch abgeschlossen ({total} Datei(en)).")
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
        self._stop_requested = True
        self.destroy()
```

**Design-Entscheidungen (bewusst einfach gehalten):**
- Kein eigenes Settings-UI in `BatchWindow` — nutzt Backend/Modell/Formate/etc., die im Hauptfenster aktuell eingestellt sind (`parent_app._build_params(...)`), analog zum "was im Hauptfenster steht, gilt" statt Einstellungen zu duplizieren.
- Läuft strikt sequentiell in einem einzigen Hintergrund-Thread (kein Thread-Pool) — passend zur GPU-gebundenen whisperX-Pipeline, die ohnehin keine Parallelverarbeitung erlaubt.
- Ein Item-Fehler bricht den Batch nicht ab, sondern wird geloggt und übersprungen — sinnvoll bei mehreren Aufnahmen pro Sync (ein defektes File soll nicht die restlichen blockieren).

- [ ] **Step 2: Manueller Smoke-Test**

Run: `cd /home/itiger013/Dokumente/Github/BoRT && python -c "from bort.batch_window import BatchWindow"`
Expected: kein Fehler (Import-Zyklus-Check: `batch_window.py` importiert aus `gui.py`, `gui.py` importiert `batch_window.py` erst in Task 5 — bis dahin muss dieser Import fehlerfrei funktionieren)

- [ ] **Step 3: Commit**

```bash
cd /home/itiger013/Dokumente/Github/BoRT
git add src/bort/batch_window.py
git commit -m "feat: add BatchWindow for scanning and processing pending recordings"
```

---

### Task 5: Batch-Button ins Hauptfenster einhängen

**Files:**
- Modify: `src/bort/gui.py:521-544` (Aktions-Buttons-Zeile), Import-Block

- [ ] **Step 1: Import ergänzen**

In `src/bort/gui.py` nach den bestehenden Imports (nicht ganz oben, um Zirkularimport zu vermeiden — `batch_window` importiert `transcription_worker` aus `gui`, daher lokal in der Methode importieren):

Ändere `_open_batch_window` als neue Methode, mit lokalem Import:

```python
    def _open_batch_window(self) -> None:
        """Öffnet das Batch-Scan-Fenster."""
        from .batch_window import BatchWindow

        BatchWindow(self)
```

- [ ] **Step 2: Button in `action_frame` ergänzen**

In `src/bort/gui.py:521-544`, nach dem "Beenden"-Button (Zeile 544) einen neuen Button einfügen, vor dem schließenden Block:

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

(Der bestehende "Beenden"-Button behält `column=1`; neuer Button erhält `column=2`.)

- [ ] **Step 3: Manueller End-to-End-Test**

Run: `cd /home/itiger013/Dokumente/Github/BoRT && python -m bort.gui`

Schritte:
1. Zwei Test-Audiodateien (z.B. kurze `.m4a`) in einen leeren Testordner legen, eine davon mit passender `<stem>.json`-Marker-Datei (Android-Format).
2. Im Hauptfenster ein Ausgabeverzeichnis wählen.
3. "📦 Batch verarbeiten…" klicken → Fenster öffnet sich.
4. Testordner als Sync-Ordner wählen, "🔍 Scannen" klicken → beide Dateien erscheinen in der Liste (eine mit `(+ ...json)`-Hinweis).
5. "▶ Alle verarbeiten" klicken → Log zeigt beide Dateien nacheinander mit "OK".
6. Ausgabeverzeichnis prüfen → für beide Dateien liegt ein Transkript im heutigen Datums-Unterordner.
7. Fenster schließen, erneut "Scannen" im selben Sync-Ordner → Liste ist jetzt leer (`scan_pending` erkennt vorhandenes Output korrekt).

Expected: alle Schritte laufen wie beschrieben ohne Fehlerdialog.

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

### Task 6: Transfer-Setup dokumentieren (Tailscale+SMB, kein Code)

Reine Dokumentation — Transfer-Weg ist Infrastruktur/Konfiguration auf Handy+PC, kein App-Code betroffen (siehe Design-Spec Abschnitt A).

**Files:**
- Modify: `HANDOVER.md` (neuer Abschnitt, an bestehende Struktur anhängen — exakte Zeilennummer erst beim Ausführen prüfen, da sich die Datei zwischen Spec-Erstellung und Implementierung ändern kann)

- [ ] **Step 1: Abschnitt "Sync-Ordner-Setup (Tailscale+SMB)" an `HANDOVER.md` anhängen**

```markdown
## Sync-Ordner-Setup (Tailscale+SMB)

Statt manuellem Google-Drive-Download: BoR (Android) legt Aufnahmen direkt
auf einer SMB-Freigabe des PCs ab, erreichbar über Tailscale.

1. **PC:** Samba-Freigabe auf einen Zielordner einrichten (dieser Ordner
   ist der "Sync-Ordner", der in BoRT unter "📦 Batch verarbeiten…" als
   Sync-Ordner ausgewählt wird).
2. **Tailscale:** auf PC und Handy installieren, gleiches Tailnet.
3. **Handy (BoR):** in den BoR-Einstellungen als SAF-Zielordner
   `\\<pc-tailscale-ip>\<freigabename>` wählen (Android-Stock-Dateien-App
   unterstützt SMB-Netzwerkspeicher ab Android 10; falls nicht ausreichend,
   Fallback-App wie CX File Explorer nutzen).
4. Der bestehende BoR-`Mover` kopiert fertige Aufnahme-Paare automatisch
   dorthin (bei Recording-Stop/App-Start/Library-Open) — kein BoR-Code
   geändert.

**Bekanntes Risiko:** SMB über VPN-Tunnel bei Verbindungsabbruch während
des Schreibens. BoRs Mover verschiebt nur bereits abgeschlossene
Aufnahme-Paare (aktive Aufnahme bleibt lokal) — ein Abbruch mitten im
Kopiervorgang einer bereits fertigen Datei wurde nicht getestet; bei
Auffälligkeiten (unvollständige Dateien im Sync-Ordner) zuerst dort
prüfen, bevor BoR-Code angefasst wird.
```

- [ ] **Step 2: Commit**

```bash
cd /home/itiger013/Dokumente/Github/BoRT
git add HANDOVER.md
git commit -m "docs: document Tailscale+SMB sync-folder setup for batch handoff"
```

---

## Spec-Abdeckung (Selbst-Review)

- Abschnitt A (Tailscale+SMB): Task 6 (Doku, kein Code — wie im Design festgelegt).
- Abschnitt B (`scan_pending`): Task 2.
- Abschnitt C (Batch-UI): Task 4 + 5.
- Abschnitt D (Nachbearbeitung bleibt manuell): keine Task nötig — unverändert.
- Test-Pflicht (`scan_pending` pure Funktion): Task 2, Step 1.
- Zusätzlich identifizierter Bedarf (nicht im ursprünglichen Spec-Text, aber zur Umsetzung nötig): Task 1 (Marker-Suche-Extraktion) und Task 3 (`_build_params`-Extraktion) — beides Voraussetzung dafür, dass Batch-Modus dieselbe Logik wie die Einzeldatei-Verarbeitung nutzt, ohne sie zu duplizieren (DRY).

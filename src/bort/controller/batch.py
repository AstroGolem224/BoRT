"""UI-unabhängige Batch-Orchestrierung mit stabilen Item-Semantiken."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ..batch import PendingItem, _has_output, is_file_stable, scan_pending
from ..markers import MarkerError, load_markers
from ..streaming import terminate_registered_processes
from .jobs import EventEmitter, JobController, TranscriptionParams, transcription_worker


@dataclass(frozen=True)
class BatchResult:
    batch_id: str
    succeeded: int
    failed: int
    skipped: int


class BatchController:
    """Dünner Controller um Scan, Recheck, Cancel und Job-Lock."""

    def __init__(self, jobs: JobController, emit: EventEmitter) -> None:
        self._jobs = jobs
        self._emit = emit
        self._lock = threading.Lock()
        self._active_id: str | None = None
        self._cancel_requested = False
        self._abort = threading.Event()

    def scan(
        self, watch_dir: Path, output_dir: Path, settings: dict | None = None
    ) -> tuple[list[PendingItem], int]:
        candidates = scan_pending(watch_dir, output_dir, settings)
        if not candidates:
            return [], 0
        # is_file_stable wartet 2 s pro Datei; die Stichproben laufen deshalb
        # parallel. executor.map erhält die Kandidatenreihenfolge, das
        # Ergebnis ist damit identisch zum seriellen Lauf.
        with ThreadPoolExecutor(max_workers=min(8, len(candidates))) as executor:
            flags = list(
                executor.map(lambda item: is_file_stable(item.audio_path), candidates)
            )
        stable = [item for item, is_stable in zip(candidates, flags) if is_stable]
        return stable, len(candidates) - len(stable)

    def start(self, built: list[tuple[PendingItem, TranscriptionParams | None]]) -> str | None:
        acquired = self._jobs.acquire()
        if not acquired.acquired:
            return None
        with self._lock:
            if self._active_id is not None:
                self._jobs.release()
                return None
            batch_id = uuid4().hex
            self._active_id = batch_id
            self._cancel_requested = False
            self._abort = threading.Event()
        threading.Thread(target=self._run, args=(batch_id, built), daemon=True).start()
        return batch_id

    def cancel(self, batch_id: str) -> bool:
        with self._lock:
            if batch_id != self._active_id:
                return False
            self._cancel_requested = True
            self._abort.set()
        # Das Flag greift erst zwischen zwei Items; ohne Prozess-Kill liefe
        # eine 90-min-Datei nach dem Klick noch eine halbe Stunde weiter.
        terminate_registered_processes()
        return True

    def _cancelled(self, batch_id: str) -> bool:
        with self._lock:
            return batch_id != self._active_id or self._cancel_requested

    def _run(
        self, batch_id: str, built: list[tuple[PendingItem, TranscriptionParams | None]]
    ) -> None:
        # Der Worker-Thread übernimmt den im Starter-Thread erworbenen Lock.
        self._jobs.adopt()
        succeeded = failed = skipped = 0
        try:
            total = len(built)
            for index, (item, params) in enumerate(built, 1):
                if self._cancelled(batch_id):
                    skipped += total - index + 1
                    break
                self._emit(("batch_item_start", batch_id, index, total, item.audio_path.name))
                outcome = self._process_item(batch_id, item, params, index, total)
                if outcome == "ok":
                    succeeded += 1
                elif outcome == "error":
                    failed += 1
                else:
                    skipped += 1
        finally:
            with self._lock:
                if self._active_id == batch_id:
                    self._active_id = None
            self._jobs.release()
            self._emit(("batch_finished", batch_id, succeeded, failed, skipped))

    def _process_item(
        self,
        batch_id: str,
        item: PendingItem,
        params: TranscriptionParams | None,
        index: int,
        total: int,
    ) -> str:
        if params is None:
            self._emit(
                ("batch_item_error", batch_id, item.audio_path.name, "Ungültige Einstellungen")
            )
            return "error"
        if _has_output(
            item.audio_path,
            params.output_dir,
            {
                "formats": params.formats,
                "backend": params.backend,
                "colocate": params.colocate,
                "no_diarize": params.no_diarize,
                "auto_markers": params.auto_markers,
            },
        ):
            self._emit((
                "batch_item_skip",
                batch_id,
                item.audio_path.name,
                "Übersprungen: bereits vollständig",
            ))
            return "skip"
        if not item.audio_path.exists() or not is_file_stable(item.audio_path):
            self._emit(
                (
                    "batch_item_skip",
                    batch_id,
                    item.audio_path.name,
                    "Audio nicht mehr vorhanden oder wird noch kopiert",
                )
            )
            return "skip"
        if item.marker_path is not None:
            if not item.marker_path.exists() or not is_file_stable(item.marker_path):
                self._emit(
                    (
                        "batch_item_skip",
                        batch_id,
                        item.audio_path.name,
                        "Marker-Datei nicht mehr vorhanden oder wird noch kopiert",
                    )
                )
                return "skip"
            try:
                load_markers(item.marker_path)
            except MarkerError as exc:
                self._emit(
                    (
                        "batch_item_skip",
                        batch_id,
                        item.audio_path.name,
                        f"Marker-Datei ungültig geworden: {exc}",
                    )
                )
                return "skip"
        # Events wie beim Einzeljob live durchreichen: transcription_worker
        # ruft den Callback synchron auf, Fortschritt erreicht die UI während
        # des Laufs statt erst nach Item-Ende.
        outcome: dict[str, object] = {
            "ok": False,
            "message": "Fehler: unbekannt",
            "cancelled": False,
        }

        def forward(event: tuple) -> None:
            if event[0] == "log":
                self._emit(("batch_item_log", batch_id, index, total, event[1], event[2]))
            elif event[0] == "progress":
                self._emit(("batch_item_progress", batch_id, index, total, event[1], event[2]))
            elif event[0] == "done":
                outcome["ok"], outcome["message"] = True, "OK"
            elif event[0] == "error":
                outcome["message"] = f"Fehler: {event[1]}"
            elif event[0] == "cancelled":
                # Nutzer-Abbruch ist kein Fehler: sonst zählte der Batch das
                # abgebrochene Item als „Fehler: unbekannt“.
                outcome["message"] = "Abgebrochen"
                outcome["cancelled"] = True

        transcription_worker(params, forward, self._abort)
        self._emit(("batch_item_done", batch_id, item.audio_path.name, outcome["message"]))
        if outcome["cancelled"]:
            return "skip"
        return "ok" if outcome["ok"] else "error"

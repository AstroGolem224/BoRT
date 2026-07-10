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

    def __init__(self, parent_app: TranscriptionApp) -> None:
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
            dir_frame,
            textvariable=self.watch_dir_var,
            fg_color=COLORS["input_bg"],
            border_color=COLORS["border"],
        ).grid(row=0, column=1, sticky="we", padx=(0, 10), pady=12)
        ctk.CTkButton(
            dir_frame,
            text="Ordner wählen",
            command=self._browse_watch_dir,
            width=130,
            fg_color=COLORS["coral"],
            hover_color=COLORS["coral_hover"],
        ).grid(row=0, column=2, padx=(0, 10), pady=12)
        self.scan_button = ctk.CTkButton(
            dir_frame,
            text="🔍 Scannen",
            command=self._on_scan,
            width=110,
            fg_color=COLORS["coral"],
            hover_color=COLORS["coral_hover"],
        )
        self.scan_button.grid(row=0, column=3, padx=(0, 14), pady=12)
        list_frame = ctk.CTkFrame(self, fg_color=COLORS["card_bg"], corner_radius=14)
        list_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=6)
        list_frame.columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(list_frame, text="Noch nicht gescannt.", anchor="w")
        self.status_label.grid(row=0, column=0, sticky="w", padx=14, pady=(12, 4))
        self.pending_text = ctk.CTkTextbox(
            list_frame,
            height=140,
            state="disabled",
            wrap="none",
            fg_color=COLORS["input_bg"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=10,
        )
        self.pending_text.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))
        log_frame = ctk.CTkFrame(self, fg_color=COLORS["card_bg"], corner_radius=14)
        log_frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=6)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = ctk.CTkTextbox(
            log_frame,
            state="disabled",
            wrap="word",
            fg_color=COLORS["input_bg"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=10,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=14, pady=14)
        action = ctk.CTkFrame(self, fg_color="transparent")
        action.grid(row=3, column=0, pady=(6, 16))
        self.process_button = ctk.CTkButton(
            action,
            text="▶  Alle verarbeiten",
            command=self._on_process_all,
            width=200,
            height=42,
            fg_color=COLORS["coral"],
            hover_color=COLORS["coral_hover"],
            state="disabled",
        )
        self.process_button.grid(row=0, column=0, padx=10)
        self.cancel_button = ctk.CTkButton(
            action,
            text="Abbrechen",
            command=self._on_cancel,
            width=120,
            height=42,
            fg_color="transparent",
            border_width=2,
            border_color=COLORS["border"],
            text_color=COLORS["muted"],
            state="disabled",
        )
        self.cancel_button.grid(row=0, column=1, padx=10)
        self.close_button = ctk.CTkButton(
            action,
            text="Schließen",
            command=self._on_close,
            width=120,
            height=42,
            fg_color="transparent",
            border_width=2,
            border_color=COLORS["border"],
            text_color=COLORS["muted"],
        )
        self.close_button.grid(row=0, column=2, padx=10)

    def _browse_watch_dir(self) -> None:
        path = ask_directory(
            parent=self, title="Sync-Ordner auswählen", initialdir=self.watch_dir_var.get() or None
        )
        if path:
            self.watch_dir_var.set(path)
            self.parent_app.config.set_path("last_watch_dir", Path(path))
            self.parent_app.config.save()

    def _on_scan(self) -> None:
        raw = self.watch_dir_var.get().strip()
        if not raw:
            show_error(self, "Fehler", "Bitte zuerst einen Sync-Ordner wählen.")
            return
        if self.scan_thread is not None or self._batch_running:
            return
        self.scan_button.configure(state="disabled")
        self.process_button.configure(state="disabled")
        self.status_label.configure(text="Scanne …")
        self.scan_thread = threading.Thread(
            target=self._run_scan,
            args=(Path(raw), Path(self.parent_app.output_var.get())),
            daemon=True,
        )
        self.scan_thread.start()

    def _run_scan(self, watch_dir: Path, output_dir: Path) -> None:
        candidates = scan_pending(watch_dir, output_dir)
        stable = [item for item in candidates if is_file_stable(item.audio_path)]
        self.log_queue.put(("scan_done", stable, len(candidates) - len(stable)))

    def _on_scan_done(self, stable: list[PendingItem], skipped: int) -> None:
        self.pending = stable
        self.scan_thread = None
        self.scan_button.configure(state="normal")
        self.pending_text.configure(state="normal")
        self.pending_text.delete("1.0", "end")
        for item in stable:
            marker_info = f" (+ {item.marker_path.name})" if item.marker_path else ""
            self.pending_text.insert("end", f"{item.audio_path.name}{marker_info}\n")
        self.pending_text.configure(state="disabled")
        status = (
            f"{len(stable)} unverarbeitete Aufnahme(n) gefunden."
            if stable
            else "Keine unverarbeiteten Aufnahmen gefunden."
        )
        if skipped:
            status += f" ({skipped} noch instabil/wird kopiert, übersprungen)"
        self.status_label.configure(text=status)
        self.process_button.configure(state="normal" if stable else "disabled")

    def _on_process_all(self) -> None:
        if not self.pending or self._batch_running:
            return
        if not self.parent_app.try_acquire_job():
            show_error(
                self, "Fehler", "Es läuft bereits eine Transkription (Einzel-Lauf oder Batch)."
            )
            return
        built = [
            (item, self.parent_app._build_params(item.audio_path, item.marker_path))
            for item in self.pending
        ]
        self._batch_running = True
        self._stop_requested = False
        self.process_button.configure(state="disabled")
        self.scan_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.worker_thread = threading.Thread(target=self._run_batch, args=(built,), daemon=True)
        self.worker_thread.start()

    def _run_batch(self, built: list[tuple[PendingItem, object]]) -> None:
        succeeded = failed = skipped = 0
        total = len(built)
        try:
            for index, (item, params) in enumerate(built, start=1):
                if self._stop_requested:
                    skipped += total - index + 1
                    break
                self.log_queue.put(("batch_item_start", index, total, item.audio_path.name))
                try:
                    outcome = self._process_one_item(item, params, index, total)
                except Exception as exc:
                    logger.exception("Unerwarteter Fehler bei Batch-Item %s", item.audio_path)
                    self.log_queue.put(("batch_item_error", item.audio_path.name, str(exc)))
                    outcome = "error"
                if outcome == "ok":
                    succeeded += 1
                elif outcome == "error":
                    failed += 1
                else:
                    skipped += 1
        finally:
            self.log_queue.put(("batch_finished", succeeded, failed, skipped))

    def _process_one_item(self, item: PendingItem, params: object, index: int, total: int) -> str:
        if params is None:
            self.log_queue.put(
                ("batch_item_error", item.audio_path.name, "Ungültige Einstellungen")
            )
            return "error"
        if not item.audio_path.exists() or not is_file_stable(item.audio_path):
            self.log_queue.put(
                (
                    "batch_item_skip",
                    item.audio_path.name,
                    "Audio nicht mehr vorhanden oder wird noch kopiert",
                )
            )
            return "skip"
        if item.marker_path is not None:
            if not item.marker_path.exists() or not is_file_stable(item.marker_path):
                self.log_queue.put(
                    (
                        "batch_item_skip",
                        item.audio_path.name,
                        "Marker-Datei nicht mehr vorhanden oder wird noch kopiert",
                    )
                )
                return "skip"
            try:
                load_markers(item.marker_path)
            except MarkerError as exc:
                self.log_queue.put(
                    (
                        "batch_item_skip",
                        item.audio_path.name,
                        f"Marker-Datei ungültig geworden: {exc}",
                    )
                )
                return "skip"
        item_queue: queue.Queue = queue.Queue()
        transcription_worker(params, item_queue)
        ok, message = self._drain_item_queue(item_queue, index, total)
        self.log_queue.put(("batch_item_done", item.audio_path.name, message))
        return "ok" if ok else "error"

    def _drain_item_queue(
        self, item_queue: queue.Queue, index: int, total: int
    ) -> tuple[bool, str]:
        ok = False
        message = "Fehler: unbekannt"
        while True:
            try:
                item = item_queue.get_nowait()
            except queue.Empty:
                break
            kind = item[0]
            if kind == "log":
                self.log_queue.put(("batch_item_log", index, total, item[1], item[2]))
            elif kind == "progress":
                self.log_queue.put(
                    ("batch_item_progress", index, total, item[1], item[2] if len(item) > 2 else "")
                )
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
                    self._append_log(f"[{item[1]}/{item[2]}] Verarbeite {item[3]} …")
                elif kind == "batch_item_log":
                    self._append_log(f"    {item[3]}: {item[4]}")
                elif kind == "batch_item_progress":
                    self.status_label.configure(
                        text=f"[{item[1]}/{item[2]}] {int(item[3])}% · {item[4]}"
                    )
                elif kind == "batch_item_done":
                    self._append_log(f"  → {item[1]}: {item[2]}")
                elif kind == "batch_item_error":
                    self._append_log(f"  → {item[1]}: Fehler ({item[2]})")
                elif kind == "batch_item_skip":
                    self._append_log(f"  → {item[1]}: übersprungen ({item[2]})")
                elif kind == "batch_finished":
                    self._finish_batch(item[1], item[2], item[3])
        except queue.Empty:
            pass
        finally:
            self.after(150, self._poll_queue)

    def _finish_batch(self, succeeded: int, failed: int, skipped: int) -> None:
        self._append_log(
            f"Batch abgeschlossen: {succeeded} OK, {failed} Fehler, {skipped} übersprungen."
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
            self,
            "Fertig",
            f"Batch abgeschlossen: {succeeded} OK, {failed} Fehler, {skipped} übersprungen.",
        )

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _on_close(self) -> None:
        if self._batch_running:
            show_error(
                self,
                "Batch läuft noch",
                "Bitte zuerst 'Abbrechen' klicken und das aktuelle Item "
                "abwarten, bevor das Fenster geschlossen wird.",
            )
            return
        if self.scan_thread is not None:
            show_error(
                self,
                "Scan läuft noch",
                "Bitte warten, bis der Scan abgeschlossen ist, bevor das Fenster geschlossen wird.",
            )
            return
        self.destroy()

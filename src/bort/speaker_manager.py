"""Speaker-Manager: Fenster zum Anhören und Umbenennen von Sprechern.

Öffnet sich nach einer whisperX-Transkription. Zeigt die erkannten Sprecher
mit Beispiel-Segmenten, erlaubt das Abspielen (Start/Stop) und das Umbenennen.
Nach dem Umbenennen wird das Transkript neu geschrieben.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import customtkinter as ctk

from .controller.playback import AudioPlayer, PlaybackError
from .controller.speaker_edit import RegisteredReview, SpeakerEditController
from .dialogs import show_error, show_info
from .markers import Bookmark
from .speakers import Segment, SpeakerMarker, SpeakerSegment
from .theme import COLORS

logger = logging.getLogger(__name__)


class SpeakerManagerWindow(ctk.CTkToplevel):
    """Fenster zum Umbenennen von Sprechern nach der Transkription."""

    def __init__(
        self,
        parent: ctk.CTk,
        audio_path: Path,
        segments: list[SpeakerSegment],
        raw_segments: list[Segment],
        speaker_map: dict[str, str],
        markers: list[SpeakerMarker],
        bookmarks: list[Bookmark] | None,
        output_dir: Path,
        base_name: str,
        formats: list[str],
    ) -> None:
        super().__init__(parent)
        self.title("Sprecher verwalten")
        self.geometry("980x720")
        self.minsize(820, 600)
        ctk.set_appearance_mode("dark")

        self.audio_path = audio_path
        self.segments = segments
        self.raw_segments = raw_segments
        self.speaker_map = dict(speaker_map)
        self.markers = markers
        self.bookmarks = bookmarks or []
        self.output_dir = output_dir
        self.base_name = base_name
        self.formats = formats

        self.player = AudioPlayer(audio_path)
        self.editor = SpeakerEditController()
        self.review_id = self.editor.register(
            RegisteredReview(
                audio_path,
                segments,
                dict(speaker_map),
                list(markers),
                list(bookmarks or []),
                output_dir,
                base_name,
                list(formats),
            )
        )
        self.name_vars: dict[str, ctk.StringVar] = {}
        self.play_buttons: dict[str, ctk.CTkButton] = {}
        self._current_playing: set[str] = set()

        self._build_ui()
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        """Baut die Sprecher-Übersicht im BoR-Card-Design auf."""
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # --- Header-Card ---
        header = ctk.CTkFrame(self, fg_color=COLORS["card_bg"], corner_radius=16)
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 10))
        header.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="👥  Sprecher verwalten",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=COLORS["text"],
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(16, 4))

        ctk.CTkLabel(
            header,
            text="Klicke ▶ um ein Beispiel-Segment anzuhören, "
            "benenne die Sprecher um und klicke auf „Übernehmen“.",
            text_color=COLORS["muted"],
            font=ctk.CTkFont(size=13),
        ).grid(row=1, column=0, sticky="w", padx=20, pady=(0, 16))

        # --- Sprecher-Card (scrollbar) ---
        card = ctk.CTkFrame(self, fg_color=COLORS["card_bg"], corner_radius=14)
        card.grid(row=1, column=0, sticky="nsew", padx=20, pady=6)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)

        scroll = ctk.CTkScrollableFrame(card, fg_color="transparent")
        scroll.grid(row=1, column=0, sticky="nsew", padx=12, pady=12)
        scroll.columnconfigure(0, weight=0)
        scroll.columnconfigure(1, weight=1)
        scroll.columnconfigure(2, weight=0)
        scroll.columnconfigure(3, weight=0)
        scroll.columnconfigure(4, weight=2)

        # Spalten-Header
        headers = [
            ("Original", 0),
            ("Neuer Name", 1),
            ("Segm.", 2),
            ("Anhören", 3),
            ("Beispiel-Text", 4),
        ]
        for text, col in headers:
            ctk.CTkLabel(
                scroll,
                text=text,
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=COLORS["coral"],
            ).grid(row=0, column=col, padx=8, pady=(4, 10), sticky="w")

        # Eintrag pro Sprecher
        speakers_sorted = sorted(self.speaker_map.items())
        for idx, (spk_id, spk_name) in enumerate(speakers_sorted):
            row = idx + 1
            # Original
            ctk.CTkLabel(
                scroll,
                text=spk_id,
                text_color=COLORS["muted"],
            ).grid(row=row, column=0, padx=8, pady=8, sticky="w")

            # Neuer Name (editierbar)
            name_var = ctk.StringVar(value=spk_name)
            self.name_vars[spk_id] = name_var
            ctk.CTkEntry(
                scroll,
                textvariable=name_var,
                width=220,
                fg_color=COLORS["input_bg"],
                border_color=COLORS["border"],
            ).grid(row=row, column=1, padx=8, pady=8, sticky="we")

            # Anzahl Segmente
            n_segs = sum(1 for s in self.segments if s.speaker == spk_name)
            ctk.CTkLabel(
                scroll,
                text=str(n_segs),
                text_color=COLORS["text"],
            ).grid(row=row, column=2, padx=8, pady=8, sticky="w")

            # Beispiel-Segment
            example = next((s for s in self.segments if s.speaker == spk_name), None)
            if example:
                btn = ctk.CTkButton(
                    scroll,
                    text="▶ Abspielen",
                    width=130,
                    command=self._make_play_cmd(spk_id, example.start, example.end),
                    fg_color=COLORS["coral"],
                    hover_color=COLORS["coral_hover"],
                )
                btn.grid(row=row, column=3, padx=8, pady=8, sticky="w")
                self.play_buttons[spk_id] = btn

                # Beispieltext
                preview = example.text[:70]
                if len(example.text) > 70:
                    preview += "…"
                ctk.CTkLabel(
                    scroll,
                    text=f"„{preview}“",
                    text_color=COLORS["muted"],
                    font=ctk.CTkFont(size=12),
                ).grid(row=row, column=4, padx=8, pady=8, sticky="w")
            else:
                ctk.CTkLabel(
                    scroll,
                    text="–",
                    text_color=COLORS["muted"],
                ).grid(row=row, column=3, padx=8, pady=8, sticky="w")

        # --- Aktions-Buttons ---
        action = ctk.CTkFrame(self, fg_color="transparent")
        action.grid(row=2, column=0, pady=(10, 20))

        ctk.CTkButton(
            action,
            text="Schließen",
            width=120,
            height=44,
            fg_color="transparent",
            border_width=2,
            border_color=COLORS["border"],
            text_color=COLORS["muted"],
            command=self._on_close,
        ).grid(row=0, column=0, padx=10)

        ctk.CTkButton(
            action,
            text="✓  Übernehmen & Transkript aktualisieren",
            width=320,
            height=44,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=COLORS["coral"],
            hover_color=COLORS["coral_hover"],
            command=self._on_apply,
        ).grid(row=0, column=1, padx=10)

    def _make_play_cmd(self, spk_id: str, start: float, end: float):
        """Erzeugt eine Play-Callback-Funktion für einen Sprecher."""

        def _cmd() -> None:
            self._toggle_play(spk_id, start, end)

        return _cmd

    def _toggle_play(self, spk_id: str, start: float, end: float) -> None:
        """Startet/stoppt die Wiedergabe für einen Sprecher."""
        if self.player.is_playing() and spk_id in self._current_playing:
            self.player.stop()
            self.play_buttons[spk_id].configure(text="▶ Abspielen")
            self._current_playing.discard(spk_id)
            return
        self.player.stop()
        for btn in self.play_buttons.values():
            btn.configure(text="▶ Abspielen")
        self._current_playing = {spk_id}
        try:
            self.player.play_segment(start, end)
        except PlaybackError as exc:
            show_error(self, "Wiedergabe nicht möglich", str(exc))
            return
        self.play_buttons[spk_id].configure(text="⏹ Stop")
        threading.Thread(target=self._watch_playback, args=(spk_id,), daemon=True).start()

    def _watch_playback(self, spk_id: str) -> None:
        """Wartet bis Wiedergabe endet und setzt Button zurück."""
        while self.player.is_playing():
            time.sleep(0.1)
        self.after(
            0,
            lambda: (
                self.play_buttons.get(spk_id)
                and self.play_buttons[spk_id].configure(text="▶ Abspielen")
            ),
        )

    def _on_apply(self) -> None:
        """Wendet die Umbenennung an und schreibt das Transkript neu."""
        new_map: dict[str, str] = {}
        for spk_id, var in self.name_vars.items():
            new_name = var.get().strip()
            if not new_name:
                new_name = self.speaker_map.get(spk_id, spk_id)
            new_map[spk_id] = new_name

        try:
            result = self.editor.apply(self.review_id, new_map)
            self.speaker_map = result.speaker_map
            self.markers = result.markers
            show_info(
                self,
                "Fertig",
                f"Transkript aktualisiert.\n"
                f"{len(result.segments)} Segmente neu geschrieben in:\n"
                f"{result.location}",
            )
            self.segments = result.segments
        except Exception as exc:
            logger.exception("Fehler beim Neuschreiben des Transkripts")
            show_error(
                self,
                "Fehler",
                f"Transkript konnte nicht aktualisiert werden:\n{exc}",
            )

    def _on_close(self) -> None:
        """Aufräumen beim Schließen."""
        self.player.stop()
        self.destroy()

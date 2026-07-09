"""CustomTkinter-GUI für die Transkriptions-App."""

import json
import logging
import platform
import queue
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import customtkinter as ctk

from .audio import SUPPORTED_AUDIO_EXTS, AudioError, convert_to_wav, is_supported_audio
from .config import Config
from .dialogs import show_error, show_info
from .filedialogs import ask_directory, ask_open_file
from .markers import Bookmark, MarkerError, load_bookmarks, load_markers
from .speaker_manager import SpeakerManagerWindow
from .speakers import (
    MarkerSpeakerResolver,
    PlaceholderSpeakerResolver,
    SpeakerMarker,
)
from .theme import COLORS
from .transcription import TranscriptionError, transcribe
from .whisperx_backend import (
    WhisperXError,
)
from .whisperx_backend import (
    save_markers as save_whisperx_markers,
)
from .whisperx_backend import (
    transcribe as transcribe_whisperx,
)
from .writers import write_outputs

DEFAULT_FORMATS = ["txt", "md", "csv", "tsv"]
LANGUAGES = ["auto", "de", "en", "fr", "es", "it", "pt", "nl", "pl", "ru", "zh", "ja"]
TASK_OPTIONS = {
    "Originalsprache beibehalten": "transcribe",
    "Nach Englisch übersetzen": "translate",
}
BACKENDS = {
    "whisper.cpp": "whispercpp",
    "whisperX (GPU + Diarization)": "whisperx",
}
WHISPERX_MODELS = ["large-v3", "large-v2", "medium", "small", "base", "tiny"]


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


@dataclass
class TranscriptionParams:
    """Parameter für einen Transkriptionslauf."""

    audio_path: Path
    marker_path: Path | None
    model_path: Path | None  # whispercpp: ggml-Pfad; whisperX: None
    language: str | None
    output_dir: Path
    formats: list[str]
    keep_wav: bool
    verbose: bool = False
    task: str = "transcribe"
    backend: str = "whispercpp"  # "whispercpp" | "whisperx"
    whisperx_model: str = "large-v3"
    min_speakers: int | None = None
    max_speakers: int | None = None
    no_diarize: bool = False
    auto_markers: bool = True


class QueueLogHandler(logging.Handler):
    """Logging-Handler, der Records in eine Queue schreibt."""

    def __init__(self, log_queue: queue.Queue) -> None:
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.log_queue.put(("log", record.levelname, msg))
        except Exception:
            self.handleError(record)


def _setup_worker_logging(log_queue: queue.Queue, verbose: bool) -> None:
    """Richtet Logging im Worker-Thread so ein, dass Meldungen in die Queue gehen."""
    root = logging.getLogger()
    root.handlers.clear()
    handler = QueueLogHandler(log_queue)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)


def transcription_worker(params: TranscriptionParams, log_queue: queue.Queue) -> None:
    """Läuft im Hintergrund-Thread und führt die Transkription aus."""
    _setup_worker_logging(log_queue, params.verbose)
    logger = logging.getLogger(__name__)

    # Bookmarks aus der Android-Marker-Datei laden (nur whisperX-Pfad)
    bookmarks: list[Bookmark] = []
    if params.backend == "whisperx" and params.marker_path:
        try:
            bookmarks = load_bookmarks(params.marker_path)
            logger.info("Bookmarks geladen: %d", len(bookmarks))
        except MarkerError:
            bookmarks = []

    # Ergebnisdaten für den Speaker-Manager (nur whisperX)
    wx_speaker_map: dict[str, str] | None = None
    wx_markers: list[SpeakerMarker] | None = None

    # Progress-Callback: leitet Prozentzahl an die GUI-Queue weiter
    def _progress_cb(percent: float, phase: str) -> None:
        log_queue.put(("progress", percent, phase))

    try:
        if params.backend == "whisperx":
            # --- whisperX-Pfad (GPU + Diarization) ---
            logger.info(
                "Starte Transkription mit whisperX (Modell=%s, Sprache=%s)",
                params.whisperx_model,
                params.language or "auto",
            )
            _progress_cb(0.0, "Initialisiere")
            wx_result = transcribe_whisperx(
                audio_path=params.audio_path,
                language=params.language if params.language != "auto" else None,
                model_name=params.whisperx_model,
                min_speakers=params.min_speakers,
                max_speakers=params.max_speakers,
                no_diarize=params.no_diarize,
                progress_cb=_progress_cb,
            )
            logger.info(
                "Transkription abgeschlossen (%d Segmente, %d Sprecher).",
                len(wx_result.segments),
                len(wx_result.speaker_map),
            )
            logger.info("Erkannte Sprache: %s", wx_result.language or "unbekannt")

            if params.auto_markers and not params.no_diarize:
                marker_path = (
                    params.output_dir / f"{params.audio_path.stem}.markers.json"
                )
                save_whisperx_markers(wx_result, marker_path)
                logger.info("Auto-Marker gespeichert: %s", marker_path)

            resolver = MarkerSpeakerResolver(
                markers=wx_result.markers,
                speaker_map=wx_result.speaker_map,
            )
            speaker_segments = resolver.resolve(wx_result.segments)

            # Für Speaker-Manager merken
            wx_speaker_map = dict(wx_result.speaker_map)
            wx_markers = list(wx_result.markers)
        else:
            # --- whisper.cpp-Pfad (ursprünglich) ---
            if not params.model_path:
                raise TranscriptionError(
                    "Modell-Pfad fehlt (für whisper.cpp-Backend erforderlich)"
                )
            logger.info("Konvertiere Audio: %s", params.audio_path)
            _progress_cb(0.0, "Konvertiere Audio")
            wav_path = convert_to_wav(
                params.audio_path,
                output_dir=params.output_dir if params.keep_wav else None,
            )
            logger.info("WAV erzeugt: %s", wav_path)

            logger.info(
                "Starte Transkription mit whisper.cpp (Sprache=%s, Aufgabe=%s)",
                params.language or "auto",
                params.task,
            )
            _progress_cb(0.0, "Transkribiere")
            result = transcribe(
                wav_path=wav_path,
                model_path=params.model_path,
                language=params.language,
                task=params.task,
                progress_cb=_progress_cb,
            )
            logger.info(
                "Transkription abgeschlossen (%d Segmente).",
                len(result.segments),
            )
            logger.info("Erkannte Sprache: %s", result.language or "unbekannt")

            if params.marker_path:
                logger.info("Lade Marker-Datei: %s", params.marker_path)
                speaker_map, markers = load_markers(params.marker_path)
                resolver = MarkerSpeakerResolver(markers, speaker_map)
            else:
                logger.info(
                    "Keine Marker-Datei angegeben – verwende Fallback-Sprecher."
                )
                resolver = PlaceholderSpeakerResolver()

            speaker_segments = resolver.resolve(result.segments)

        _progress_cb(95.0, "Speichere")
        output_paths = write_outputs(
            segments=speaker_segments,
            output_dir=params.output_dir,
            base_name=params.audio_path.stem,
            formats=params.formats,
            bookmarks=bookmarks or None,
        )

        output_location = (
            output_paths[0].parent if output_paths else params.output_dir
        )
        logger.info("Ausgabe gespeichert in %s:", output_location)
        for path in output_paths:
            logger.info("  - %s", path)

        if params.backend != "whisperx" and not params.keep_wav:
            logger.debug("Lösche temporäre WAV-Datei: %s", wav_path)
            wav_path.unlink(missing_ok=True)

        _progress_cb(100.0, "Fertig")
        # done-Nachricht mit Ergebnisdaten für Speaker-Manager
        done_data = {
            "backend": params.backend,
            "audio_path": params.audio_path,
            "marker_path": params.marker_path,
            "segments": speaker_segments,
            "speaker_map": wx_speaker_map,
            "markers": wx_markers,
            "bookmarks": bookmarks,
            "output_dir": params.output_dir,
            "base_name": params.audio_path.stem,
            "formats": params.formats,
        }
        log_queue.put(("done", "Transkription erfolgreich abgeschlossen.", done_data))

    except (
        AudioError,
        MarkerError,
        TranscriptionError,
        WhisperXError,
    ) as exc:
        log_queue.put(("error", str(exc)))
    except Exception as exc:
        log_queue.put(("error", f"Unerwarteter Fehler: {exc}"))


class TranscriptionApp:
    """Hauptfenster der Transkriptions-GUI."""

    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        self.root.title("BoR Transcriber")
        self.root.geometry("1100x880")
        self.root.minsize(950, 780)
        # BoR-Farbschema
        ctk.set_appearance_mode("dark")

        self.config = Config()
        self._apply_appearance_mode()
        self._build_ui()
        self._load_config_values()
        # UI an gespeichertes/Default-Backend anpassen (whisperX als Default)
        self._on_backend_change(self.backend_display_var.get())
        self.log_queue: queue.Queue = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self._audio_trace_id: str | None = None
        # Auto-Load der Begleit-JSON auch beim manuellen Tippen/Einfügen des Pfads.
        self.audio_var.trace_add("write", self._on_audio_var_change)
        self._poll_queue()

    def _build_ui(self) -> None:
        """Baut die Benutzeroberfläche auf (modernes Card-Layout)."""

        # --- Header ---
        header = ctk.CTkFrame(self.root, fg_color=COLORS["card_bg"], corner_radius=16)
        header.grid(row=0, column=0, columnspan=3, sticky="ew", padx=20, pady=(20, 10))
        header.columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text="🎙️",
            font=ctk.CTkFont(size=36),
        ).grid(row=0, column=0, padx=20, pady=14)

        ctk.CTkLabel(
            header,
            text="BoR Transcriber",
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=COLORS["text"],
        ).grid(row=0, column=1, sticky="w", pady=14)

        # Status-Badge (rechts im Header)
        self.status_label = ctk.CTkLabel(
            header,
            text="● Bereit",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["success"],
        )
        self.status_label.grid(row=0, column=2, padx=(20, 4), pady=14)

        # Fortschritts-Balken (rechts neben Status-Badge, unsichtbar bis Transkription)
        self.progress_bar = ctk.CTkProgressBar(
            header,
            width=180,
            progress_color=COLORS["coral"],
            fg_color=COLORS["input_bg"],
        )
        self.progress_bar.set(0)
        self.progress_bar.grid(row=0, column=3, padx=(0, 4), pady=14)
        self.progress_bar.grid_remove()  # erst verstecken

        # Prozent-Label
        self.progress_label = ctk.CTkLabel(
            header,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text"],
            width=44,
        )
        self.progress_label.grid(row=0, column=4, padx=(0, 20), pady=14)
        self.progress_label.grid_remove()

        # --- Card 1: Eingabe ---
        card_in = ctk.CTkFrame(self.root, fg_color=COLORS["card_bg"], corner_radius=14)
        card_in.grid(row=1, column=0, columnspan=3, sticky="ew", padx=20, pady=6)
        card_in.columnconfigure(0, minsize=180, weight=0)
        card_in.columnconfigure(1, weight=1)
        card_in.columnconfigure(2, weight=0)

        ctk.CTkLabel(
            card_in,
            text="📁 Eingabe",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLORS["coral"],
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=18, pady=(14, 6))

        # Audio
        self.audio_var = ctk.StringVar()
        self._build_file_row(card_in, row=1, label="Audio-Datei:",
                             var=self.audio_var, command=self._browse_audio)

        # Marker
        self.marker_var = ctk.StringVar()
        self._build_file_row(card_in, row=2, label="Marker-JSON (optional):",
                             var=self.marker_var, command=self._browse_marker)

        # --- Card 2: Engine ---
        card_eng = ctk.CTkFrame(self.root, fg_color=COLORS["card_bg"], corner_radius=14)
        card_eng.grid(row=2, column=0, columnspan=3, sticky="ew", padx=20, pady=6)
        card_eng.columnconfigure(0, minsize=180, weight=0)
        card_eng.columnconfigure(1, weight=1)
        card_eng.columnconfigure(2, weight=0)

        ctk.CTkLabel(
            card_eng,
            text="⚙️ Engine",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLORS["coral"],
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=18, pady=(14, 6))

        # Backend
        ctk.CTkLabel(card_eng, text="Backend:", width=180, anchor="w").grid(
            row=1, column=0, sticky="w", padx=18, pady=8
        )
        self.backend_display_var = ctk.StringVar(
            value="whisperX (GPU + Diarization)"
        )
        backend_combo = ctk.CTkComboBox(
            card_eng,
            variable=self.backend_display_var,
            values=list(BACKENDS.keys()),
            state="readonly",
            width=280,
            command=self._on_backend_change,
        )
        backend_combo.grid(row=1, column=1, sticky="w", padx=18, pady=8)

        # Modell
        self.model_var = ctk.StringVar()
        self._build_model_row(row=2, parent=card_eng)

        # whisperX-Optionen
        self.wx_options_frame = ctk.CTkFrame(card_eng, fg_color="transparent")
        self.wx_options_frame.grid(row=3, column=1, sticky="w", padx=18, pady=4)

        self.max_speakers_var = ctk.StringVar(value="")
        ctk.CTkLabel(self.wx_options_frame, text="Max. Sprecher:").grid(
            row=0, column=0, padx=(0, 5)
        )
        ctk.CTkEntry(self.wx_options_frame, textvariable=self.max_speakers_var,
                     width=60).grid(row=0, column=1, padx=(0, 20))

        self.min_speakers_var = ctk.StringVar(value="")
        ctk.CTkLabel(self.wx_options_frame, text="Min. Sprecher:").grid(
            row=0, column=2, padx=(0, 5)
        )
        ctk.CTkEntry(self.wx_options_frame, textvariable=self.min_speakers_var,
                     width=60).grid(row=0, column=3, padx=(0, 20))

        self.no_diarize_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self.wx_options_frame, text="Ohne Diarization",
                        variable=self.no_diarize_var).grid(row=0, column=4, padx=8)

        self.auto_markers_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self.wx_options_frame, text="Marker automatisch speichern",
                        variable=self.auto_markers_var).grid(row=0, column=5, padx=8)

        # Sprache & Aufgabe
        ctk.CTkLabel(card_eng, text="Sprache:", width=180, anchor="w").grid(
            row=4, column=0, sticky="w", padx=18, pady=8
        )
        self.language_var = ctk.StringVar(value="auto")
        ctk.CTkOptionMenu(
            card_eng,
            variable=self.language_var,
            values=LANGUAGES,
            width=140,
            fg_color=COLORS["input_bg"],
            button_color=COLORS["coral"],
            button_hover_color=COLORS["coral_hover"],
            dropdown_fg_color=COLORS["card_bg"],
            dropdown_hover_color=COLORS["border"],
            text_color=COLORS["text"],
        ).grid(row=4, column=1, sticky="w", padx=18, pady=8)

        ctk.CTkLabel(card_eng, text="Aufgabe:", width=180, anchor="w").grid(
            row=5, column=0, sticky="w", padx=18, pady=8
        )
        self.task_display_var = ctk.StringVar(value="Originalsprache beibehalten")
        ctk.CTkOptionMenu(
            card_eng,
            variable=self.task_display_var,
            values=list(TASK_OPTIONS.keys()),
            width=280,
            fg_color=COLORS["input_bg"],
            button_color=COLORS["coral"],
            button_hover_color=COLORS["coral_hover"],
            dropdown_fg_color=COLORS["card_bg"],
            dropdown_hover_color=COLORS["border"],
            text_color=COLORS["text"],
        ).grid(row=5, column=1, sticky="w", padx=18, pady=8)

        # --- Card 3: Ausgabe ---
        card_out = ctk.CTkFrame(self.root, fg_color=COLORS["card_bg"], corner_radius=14)
        card_out.grid(row=3, column=0, columnspan=3, sticky="ew", padx=20, pady=6)
        card_out.columnconfigure(0, minsize=180, weight=0)
        card_out.columnconfigure(1, weight=1)
        card_out.columnconfigure(2, weight=0)

        ctk.CTkLabel(
            card_out,
            text="💾 Ausgabe",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLORS["coral"],
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=18, pady=(14, 6))

        # Speicherort: Label in col0, Entry in col1, Buttons in col2 (als Frame)
        ctk.CTkLabel(card_out, text="Speicherort:", width=180, anchor="w").grid(
            row=1, column=0, sticky="w", padx=18, pady=8
        )
        self.output_var = ctk.StringVar(value=str(Path.cwd()))
        ctk.CTkEntry(card_out, textvariable=self.output_var,
                     fg_color=COLORS["input_bg"], border_color=COLORS["border"]
                     ).grid(row=1, column=1, sticky="we", padx=(0, 10), pady=8)
        out_btn_frame = ctk.CTkFrame(card_out, fg_color="transparent")
        out_btn_frame.grid(row=1, column=2, sticky="w", padx=(0, 18), pady=8)
        ctk.CTkButton(out_btn_frame, text="Ordner wählen", command=self._browse_output,
                      width=130, fg_color=COLORS["coral"],
                      hover_color=COLORS["coral_hover"]).grid(
            row=0, column=0, padx=(0, 6))
        ctk.CTkButton(out_btn_frame, text="📂 Öffnen", command=self._open_output_dir,
                      width=100, fg_color=COLORS["input_bg"],
                      border_color=COLORS["border"]).grid(row=0, column=1)

        # Formate
        ctk.CTkLabel(card_out, text="Formate:", width=180, anchor="w").grid(
            row=2, column=0, sticky="w", padx=18, pady=8
        )
        self.format_vars: dict[str, ctk.BooleanVar] = {}
        format_frame = ctk.CTkFrame(card_out, fg_color="transparent")
        format_frame.grid(row=2, column=1, columnspan=2, sticky="w", padx=18, pady=8)
        for idx, fmt in enumerate(DEFAULT_FORMATS):
            var = ctk.BooleanVar(value=True)
            self.format_vars[fmt] = var
            ctk.CTkCheckBox(format_frame, text=fmt.upper(), variable=var).grid(
                row=0, column=idx, padx=12
            )

        # Optionen
        options_frame = ctk.CTkFrame(card_out, fg_color="transparent")
        options_frame.grid(row=3, column=1, columnspan=2, sticky="w", padx=18, pady=4)
        self.keep_wav_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(options_frame, text="WAV behalten",
                        variable=self.keep_wav_var).grid(row=0, column=0, padx=8)
        self.verbose_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(options_frame, text="Detaillierte Logs",
                        variable=self.verbose_var).grid(row=0, column=1, padx=8)

        # --- Aktions-Buttons ---
        action_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        action_frame.grid(row=4, column=0, columnspan=3, pady=(10, 6))
        self.run_button = ctk.CTkButton(
            action_frame,
            text="▶  Transkribieren",
            command=self._on_run,
            width=200,
            height=46,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=COLORS["coral"],
            hover_color=COLORS["coral_hover"],
        )
        self.run_button.grid(row=0, column=0, padx=10)
        ctk.CTkButton(
            action_frame,
            text="Beenden",
            command=self.root.destroy,
            width=120, height=46,
            fg_color="transparent",
            border_width=2,
            border_color=COLORS["border"],
            text_color=COLORS["muted"],
        ).grid(row=0, column=1, padx=10)

        # --- Log-Bereich ---
        log_card = ctk.CTkFrame(self.root, fg_color=COLORS["card_bg"], corner_radius=14)
        log_card.grid(row=5, column=0, columnspan=3, sticky="nsew", padx=20, pady=6)
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(1, weight=1)

        ctk.CTkLabel(log_card, text="📜 Log",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=COLORS["coral"]).grid(
            row=0, column=0, sticky="w", padx=18, pady=(14, 6)
        )
        self.log_text = ctk.CTkTextbox(
            log_card,
            height=200,
            state="disabled",
            wrap="word",
            fg_color=COLORS["input_bg"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=10,
        )
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 14))

        # Grid-Gewichtungen
        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=1)
        self.root.columnconfigure(2, weight=1)
        self.root.rowconfigure(5, weight=1)

    def _build_file_row(
        self,
        parent: ctk.CTkFrame,
        row: int,
        label: str,
        var: ctk.StringVar,
        command: Any,
    ) -> None:
        """Erzeugt eine Zeile mit Label, Eingabefeld und Durchsuchen-Button.

        Layout: Col0=Label (180px), Col1=Entry (expand), Col2=Button (fixed).
        """
        ctk.CTkLabel(parent, text=label, text_color=COLORS["text"],
                     width=180, anchor="w").grid(
            row=row, column=0, sticky="w", padx=18, pady=10
        )
        ctk.CTkEntry(parent, textvariable=var,
                     fg_color=COLORS["input_bg"],
                     border_color=COLORS["border"]).grid(
            row=row, column=1, sticky="we", padx=(0, 10), pady=10
        )
        ctk.CTkButton(
            parent,
            text="Durchsuchen",
            command=command,
            width=120,
            fg_color=COLORS["coral"],
            hover_color=COLORS["coral_hover"],
        ).grid(row=row, column=2, padx=(0, 18), pady=10)

    def _build_model_row(self, row: int, parent: ctk.CTkFrame) -> None:
        """Erzeugt die Modell-Zeile, dynamisch je nach Backend.

        - whispercpp: Datei-Auswahl (ggml-Modell)
        - whisperX: Dropdown (Modellname)
        """
        self.model_parent = parent
        self.model_row = row
        self.model_label = ctk.CTkLabel(parent, text="Modell:", width=180, anchor="w",
                                       text_color=COLORS["text"])
        self.model_label.grid(row=row, column=0, sticky="w", padx=18, pady=10)

        # whisper.cpp: Datei-Auswahl (Entry + Browse-Button)
        self.model_entry = ctk.CTkEntry(
            parent, textvariable=self.model_var, width=560,
            fg_color=COLORS["input_bg"], border_color=COLORS["border"],
        )
        # Noch nicht gridded – wird bei Backend-Wechsel zu whisper.cpp sichtbar

        self.model_browse_btn = ctk.CTkButton(
            parent,
            text="Durchsuchen",
            command=self._browse_model,
            width=120,
            fg_color=COLORS["coral"],
            hover_color=COLORS["coral_hover"],
        )
        # Noch nicht gridded

        # whisperX: Dropdown (OptionMenu)
        self.model_combo_var = ctk.StringVar(value="large-v3")
        self.model_combo = ctk.CTkOptionMenu(
            parent,
            variable=self.model_combo_var,
            values=WHISPERX_MODELS,
            width=220,
            fg_color=COLORS["input_bg"],
            button_color=COLORS["coral"],
            button_hover_color=COLORS["coral_hover"],
            dropdown_fg_color=COLORS["card_bg"],
            dropdown_hover_color=COLORS["border"],
            text_color=COLORS["text"],
        )
        # Noch nicht gridded – wird bei Backend-Wechsel zu whisperX sichtbar

    def _on_backend_change(self, selection: str) -> None:
        """Schaltet die Modell- und Options-UI je nach Backend um."""
        backend = BACKENDS[selection]
        row = getattr(self, "model_row", 2)
        _ = getattr(self, "model_parent", self.root)  # via Widget-Master
        if backend == "whisperx":
            self.model_label.configure(text="whisperX Modell:")
            self.model_entry.grid_remove()
            self.model_browse_btn.grid_remove()
            self.model_combo.grid(
                row=row, column=1, sticky="w", padx=18, pady=10,
            )
            self.wx_options_frame.grid()
        else:
            self.model_label.configure(text="whisper.cpp Modell:")
            self.model_combo.grid_remove()
            self.model_entry.grid(
                row=row, column=1, sticky="we", padx=(0, 10), pady=10,
            )
            self.model_browse_btn.grid(
                row=row, column=2, padx=(0, 18), pady=10
            )
            self.wx_options_frame.grid_remove()

    def _apply_appearance_mode(self) -> None:
        """Setzt das gespeicherte Erscheinungsbild vor dem Bauen der UI."""
        appearance = self.config.get("appearance_mode", "dark")
        if appearance in {"light", "dark", "system"}:
            ctk.set_appearance_mode(appearance)

    def _load_config_values(self) -> None:
        """Lädt gespeicherte Pfade und Einstellungen."""
        audio = self.config.get_path("last_audio_path")
        if audio:
            self.audio_var.set(str(audio))

        marker = self.config.get_path("last_marker_path")
        if marker:
            self.marker_var.set(str(marker))

        model = self.config.get_path("last_model_path")
        if model:
            self.model_var.set(str(model))

        output = self.config.get_path("last_output_dir")
        if output:
            self.output_var.set(str(output))

        language = self.config.get("last_language")
        if language in LANGUAGES:
            self.language_var.set(language)

        task_display = self.config.get("last_task_display")
        if task_display in TASK_OPTIONS:
            self.task_display_var.set(task_display)

        appearance = self.config.get("appearance_mode", "dark")
        if appearance in {"light", "dark", "system"}:
            ctk.set_appearance_mode(appearance)

        # Ausgabeformate wiederherstellen
        saved_formats = self.config.get("last_formats")
        if saved_formats:
            active = {f.strip() for f in saved_formats.split(",") if f.strip()}
            for fmt, var in self.format_vars.items():
                var.set(fmt in active)

    def _save_config_values(self, params: TranscriptionParams) -> None:
        """Speichert die aktuell verwendeten Pfade und Einstellungen."""
        self.config.set_path("last_audio_path", params.audio_path)
        self.config.set_path("last_audio_dir", params.audio_path.parent)
        if params.marker_path:
            self.config.set_path("last_marker_path", params.marker_path)
            self.config.set_path("last_marker_dir", params.marker_path.parent)
        if params.model_path:
            self.config.set_path("last_model_path", params.model_path)
            self.config.set_path("last_model_dir", params.model_path.parent)
        self.config.set_path("last_output_dir", params.output_dir)
        self.config.set("last_language", params.language or "auto")
        self.config.set("last_task_display", self.task_display_var.get())
        self.config.set("last_backend", params.backend)
        if params.backend == "whisperx":
            self.config.set("last_whisperx_model", params.whisperx_model)
        # Ausgabeformate merken
        self.config.set(
            "last_formats",
            ",".join(fmt for fmt, v in self.format_vars.items() if v.get()),
        )
        self.config.set("appearance_mode", ctk.get_appearance_mode().lower())
        self.config.save()

    def _change_appearance(self, value: str) -> None:
        """Wechselt zwischen Light, Dark und System-Theme."""
        mode = value.lower()
        ctk.set_appearance_mode(mode)
        self.config.set("appearance_mode", mode)
        self.config.save()

    def _browse_file(
        self,
        var: ctk.StringVar,
        title: str,
        filetypes: list[tuple[str, str]],
        initialdir_key: str | None = None,
    ) -> None:
        initialdir = None
        if initialdir_key:
            initial = self.config.get(initialdir_key)
            if initial and Path(initial).is_dir():
                initialdir = initial
        path = ask_open_file(
            parent=self.root,
            title=title,
            filetypes=filetypes,
            initialdir=initialdir,
        )
        if path:
            var.set(path)
            if initialdir_key:
                self.config.set_path(initialdir_key, Path(path).parent)
                self.config.save()

    def _browse_audio(self) -> None:
        self._browse_file(
            self.audio_var,
            "Audio-Datei auswählen",
            [
                ("Audio-Dateien", "*.mp3 *.m4a *.aac *.wav *.flac *.ogg *.opus *.wma"),
                ("MP3-Dateien", "*.mp3"),
                ("M4A-Dateien", "*.m4a"),
                ("AAC-Dateien", "*.aac"),
                ("WAV-Dateien", "*.wav"),
                ("Alle", "*.*"),
            ],
            initialdir_key="last_audio_dir",
        )
        # Begleit-JSON automatisch laden (Partner-App BookofRecords oder
        # BoRT-eigene Marker-Datei), falls vorhanden und das Marker-Feld leer
        # bzw. nicht mehr passend ist.
        audio_path = self.audio_var.get()
        if audio_path:
            self._auto_load_companion_marker(Path(audio_path))

    def _on_audio_var_change(self, *_args: Any) -> None:
        """Debounced Reaktion auf Änderungen des Audio-Pfads (auch manuelles Tippen)."""
        if self._audio_trace_id is not None:
            self.root.after_cancel(self._audio_trace_id)
        self._audio_trace_id = self.root.after(300, self._debounced_audio_check)

    def _debounced_audio_check(self) -> None:
        """Prüft den aktuellen Audio-Pfad und lädt ggf. die Begleit-JSON."""
        self._audio_trace_id = None
        raw = self.audio_var.get().strip()
        if not raw:
            return
        audio_path = Path(raw)
        if not audio_path.is_file():
            # Datei existiert (noch) nicht – ignorieren und weitermachen.
            return
        self._auto_load_companion_marker(audio_path)

    def _auto_load_companion_marker(self, audio_path: Path) -> None:
        """Sucht eine passende Marker-JSON zum Audio und trägt sie ein.

        Reihenfolge (gleicher Ordner wie das Audio):
          1. ``<stem>.json`` – Android-Partner-App (BookofRecords) mit Bookmarks
          2. ``<stem>.markers.json`` – BoRT-eigene Auto-Marker (whisperX)

        Es wird nur eingetragen, wenn das Feld aktuell leer ist oder die
        gesetzte Datei nicht (mehr) existiert – eine bewusst gewählte Datei
        wird nicht überschrieben. Ungültige JSONs werden still verworfen.
        """
        current = self.marker_var.get().strip()
        if current and Path(current).exists():
            # Bereits eine gültige Marker-Datei gesetzt – nichts ändern.
            return

        candidates = [
            audio_path.with_suffix(".json"),
            audio_path.parent / f"{audio_path.stem}.markers.json",
        ]
        for cand in candidates:
            if not cand.exists():
                continue
            if not _looks_like_marker_file(cand):
                continue
            self.marker_var.set(str(cand))
            self.config.set_path("last_marker_path", cand)
            self.config.set_path("last_marker_dir", cand.parent)
            self.config.save()
            self._log("INFO", f"Marker-JSON automatisch geladen: {cand.name}")
            return
        # Keine passende JSON gefunden – ggf. veralteten Eintrag löschen.
        if current and not Path(current).exists():
            self.marker_var.set("")

    def _browse_marker(self) -> None:
        self._browse_file(
            self.marker_var,
            "JSON-Marker-Datei auswählen",
            [("JSON-Dateien", "*.json"), ("Alle", "*.*")],
            initialdir_key="last_marker_dir",
        )

    def _browse_model(self) -> None:
        self._browse_file(
            self.model_var,
            "whisper.cpp Modell auswählen",
            [("GGML-Modelle", "*.bin *.gguf"), ("Alle", "*.*")],
            initialdir_key="last_model_dir",
        )

    def _browse_output(self) -> None:
        initialdir = None
        initial = self.config.get("last_output_dir")
        if initial and Path(initial).is_dir():
            initialdir = initial
        path = ask_directory(
            parent=self.root,
            title="Ausgabeverzeichnis auswählen",
            initialdir=initialdir,
        )
        if path:
            self.output_var.set(path)
            self.config.set_path("last_output_dir", Path(path))
            self.config.save()

    def _open_output_dir(self) -> None:
        """Öffnet das Ausgabeverzeichnis im System-Dateimanager."""
        output_dir = Path(self.output_var.get())
        output_dir.mkdir(parents=True, exist_ok=True)

        system = platform.system()
        try:
            if system == "Windows":
                subprocess.run(["explorer", str(output_dir)], check=False)
            elif system == "Darwin":
                subprocess.run(["open", str(output_dir)], check=False)
            else:
                subprocess.run(["xdg-open", str(output_dir)], check=False)
        except FileNotFoundError:
            show_error(
                self.root,
                "Fehler",
                "Kein Dateimanager gefunden. Bitte öffne den Ordner "
                f"manuell:\n{output_dir}",
            )

    def _log(self, level: str, message: str) -> None:
        """Fügt eine Zeile zum Log-Textfeld hinzu."""
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _log_sources(self, done_data: dict) -> None:
        """Zeigt die verarbeiteten Quelldateien (Audio + Marker-JSON) im Log an."""
        audio_path = done_data.get("audio_path")
        marker_path = done_data.get("marker_path")
        lines: list[str] = ["Verarbeitete Quellen:"]
        if audio_path is not None:
            lines.append(f"  • Audio:  {Path(audio_path).name}")
        if marker_path:
            lines.append(f"  • Marker: {Path(marker_path).name}")
        self._log("INFO", "\n".join(lines))

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

        marker_path = Path(self.marker_var.get()) if self.marker_var.get() else None
        if marker_path and not marker_path.exists():
            show_error(self.root, "Fehler", "Marker-Datei nicht gefunden.")
            return None

        output_dir = Path(self.output_var.get())
        output_dir.mkdir(parents=True, exist_ok=True)

        formats = [fmt for fmt, var in self.format_vars.items() if var.get()]
        if not formats:
            show_error(self.root, "Fehler", "Mindestens ein Ausgabeformat auswählen.")
            return None

        language = self.language_var.get()

        # Sprecher-Optionen (whisperX)
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

    def _on_run(self) -> None:
        params = self._validate()
        if params is None:
            return

        self._save_config_values(params)

        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.run_button.configure(state="disabled")
        self.status_label.configure(text="● Läuft…", text_color=COLORS["coral"])
        self.progress_bar.set(0)
        self.progress_bar.grid()
        self.progress_label.configure(text="0%")
        self.progress_label.grid()

        self.worker_thread = threading.Thread(
            target=transcription_worker,
            args=(params, self.log_queue),
            daemon=True,
        )
        self.worker_thread.start()

    def _poll_queue(self) -> None:
        """Holt Nachrichten aus der Queue und aktualisiert die GUI."""
        try:
            while True:
                item = self.log_queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    _, level, message = item
                    self._log(level, message)
                elif kind == "progress":
                    # ("progress", percent: float, phase: str)
                    percent = item[1]
                    phase = item[2] if len(item) > 2 else ""
                    self.progress_bar.set(max(0.0, min(1.0, percent / 100.0)))
                    label = f"{int(percent)}%"
                    if phase:
                        label = f"{int(percent)}% · {phase}"
                    self.progress_label.configure(text=label)
                elif kind == "done":
                    # done kann 2 oder 3 Elemente haben (mit/ohne done_data)
                    message = item[1]
                    done_data = item[2] if len(item) > 2 else None
                    self._log("INFO", message)
                    # Verarbeitete Quellen anzeigen (Audio + ggf. Marker-JSON)
                    if done_data:
                        self._log_sources(done_data)
                    self.run_button.configure(state="normal")
                    self.status_label.configure(
                        text="● Fertig", text_color=COLORS["success"]
                    )
                    self.progress_bar.set(1.0)
                    self.progress_label.configure(text="100%")
                    self.root.after(2000, self._hide_progress)
                    # Speaker-Manager öffnen, wenn whisperX mit Diarization
                    if (
                        done_data
                        and done_data.get("backend") == "whisperx"
                        and done_data.get("speaker_map")
                        and not getattr(self, "_no_diarize", False)
                    ):
                        self._open_speaker_manager(done_data)
                    else:
                        show_info(self.root, "Fertig", message)
                elif kind == "error":
                    _, message = item
                    self._log("ERROR", message)
                    self.run_button.configure(state="normal")
                    self.status_label.configure(
                        text="● Fehler", text_color=COLORS["error"]
                    )
                    self._hide_progress()
                    show_error(self.root, "Fehler", message)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._poll_queue)

    def _hide_progress(self) -> None:
        """Versteckt den Fortschritts-Balken nach Abschluss/Fehler."""
        self.progress_bar.grid_remove()
        self.progress_label.grid_remove()

    def _open_speaker_manager(self, data: dict) -> None:
        """Öffnet den Speaker-Manager nach erfolgreichem whisperX-Lauf."""
        try:
            SpeakerManagerWindow(
                parent=self.root,
                audio_path=data["audio_path"],
                segments=data["segments"],
                raw_segments=[],  # nicht mehr benötigt
                speaker_map=data["speaker_map"],
                markers=data["markers"] or [],
                bookmarks=data.get("bookmarks") or [],
                output_dir=data["output_dir"],
                base_name=data["base_name"],
                formats=data["formats"],
            )
        except Exception as exc:
            logger = logging.getLogger(__name__)
            logger.exception("Speaker-Manager konnte nicht geöffnet werden")
            show_error(
                self.root,
                "Fehler",
                f"Speaker-Manager konnte nicht geöffnet werden:\n{exc}",
            )


def main() -> None:
    """Startet die GUI."""
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    root = ctk.CTk()
    _ = TranscriptionApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

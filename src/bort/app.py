"""Pywebview-basierte Phase-1-Oberfläche für BoRT."""

from __future__ import annotations

import heapq
import json
import os
import subprocess
import sys
import threading
import uuid
import zipfile
from collections import OrderedDict, deque
from concurrent.futures import Future
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any

import gi
import webview

from .audio import is_supported_audio
from .config import Config
from .controller.batch import BatchController
from .controller.jobs import (
    JobController,
    TranscriptionSettings,
    build_params,
    transcription_worker,
)
from .controller.playback import AudioPlayer, PlaybackError
from .controller.speaker_edit import (
    RegisteredReview,
    SpeakerEditController,
    SpeakerEditError,
)
from .sidecar import read_recording_meta, resample_peaks
from .speaker_review import ReviewError, load_review
from .speakers import SpeakerSegment
from .waveform import WaveformError, extract_peaks, terminate_process
from .writers import FORMATS, recover_transactions


def _load_glib() -> Any:
    gi.require_version("GLib", "2.0")
    from gi.repository import GLib

    return GLib


GLib = _load_glib()

# WICHTIG: pywebviews parse_file_type erlaubt in der Beschreibung nur [\w ]+
# (Wortzeichen + Leerzeichen). Bindestriche brechen es -> ValueError beim
# create_file_dialog -> Dialog öffnet nicht. Siehe tests/test_app_file_filters.py.
AUDIO_FILTER = "Audiodateien (*.mp3;*.m4a;*.aac;*.wav;*.flac;*.ogg;*.opus;*.wma)"
JSON_FILTER = "JSON Dateien (*.json)"
REVIEW_FILTER = "Review Dateien (*.review.json)"
GGML_FILTER = "GGML Modelle (*.bin;*.gguf)"
ALL_FILES_FILTER = "Alle Dateien (*.*)"
MAX_QUEUED_LOGS = 300
MAX_WAVEFORM_CACHE = 4


def _representative_segment(
    review: RegisteredReview, speaker_id: str
) -> SpeakerSegment:
    """Wählt das erste gültige Segment einer registrierten Sprecher-ID."""
    if speaker_id not in review.speaker_map:
        raise SpeakerEditError("Unbekannte Sprecher-ID.")
    for segment, segment_id in zip(review.segments, review.segment_ids, strict=True):
        if segment_id == speaker_id and segment.start >= 0 and segment.start < segment.end:
            return segment
    raise PlaybackError("Für diesen Sprecher ist kein gültiges Audiosegment verfügbar.")


class Bridge:
    """Thread-sichere API zwischen der lokalen Oberfläche und den Controllern."""

    def __init__(
        self, config: Config | None = None, controller: JobController | None = None
    ) -> None:
        self.config = config or Config()
        self.controller = controller or JobController()
        self.speaker_controller = SpeakerEditController()
        self.batch_controller = BatchController(self.controller, self._enqueue_batch_event)
        self.window: webview.Window | None = None
        self._state_lock = threading.RLock()
        self._events: deque[tuple[str, dict[str, Any]]] = deque()
        self._latest_progress: tuple[str, dict[str, Any]] | None = None
        self._queued_logs = 0
        self._drain_scheduled = False
        self._delivery_active = False
        self._window_loaded = False
        self._closed = False
        self._active_job_id: str | None = None
        self._active_batch_id: str | None = None
        self._pending_batch: list[Any] = []
        self._pending_batch_fingerprint: tuple[Any, ...] | None = None
        self._library_generation = 0
        self._library_items: dict[str, tuple[int, Path]] = {}
        self._player: AudioPlayer | None = None
        self._window_size: tuple[int, int] | None = None
        self._waveform_processes: dict[
            subprocess.Popen[bytes], threading.RLock
        ] = {}
        self._waveform_cache: OrderedDict[
            tuple[Path, int, int], tuple[float, list[list[float]]]
        ] = OrderedDict()
        self._waveform_inflight: dict[
            tuple[Path, int, int], Future[tuple[float, list[list[float]]]]
        ] = {}
        self._paths: dict[str, Path | None] = {
            "audio": self.config.get_path("last_audio_path"),
            "marker": self.config.get_path("last_marker_path"),
            "output": self.config.get_path("last_output_dir"),
            "model": self.config.get_path("last_model_path"),
            "watch": self.config.get_path("last_watch_dir"),
            "review": self.config.get_path("last_review_path"),
            "library": self.config.get_path("last_library_dir")
            or self.config.get_path("last_watch_dir"),
            "export": self.config.get_path("last_export_dir"),
        }

    def __dir__(self) -> list[str]:
        """Verhindert pywebviews eval-basiertes Erzeugen dynamischer API-Funktionen.

        Die statische Proxy-API in ``app.js`` ruft dieselben Attribute über die GTK-Bridge auf.
        """
        return []

    def attach_window(self, window: Any) -> None:
        """Verknüpft das Fenster, bevor dessen GTK-Loop gestartet wird."""
        self.window = window

    def on_window_loaded(self, *_args: Any) -> None:
        """Öffnet das Python-seitige Ende des Readiness-Gates."""
        with self._state_lock:
            self._window_loaded = True
        self._schedule_drain()

    def on_window_resized(self, width: Any, height: Any) -> None:
        """Merkt sich die aktuelle Fenstergröße für den nächsten Start."""
        try:
            size = (int(width), int(height))
        except (TypeError, ValueError):
            return
        with self._state_lock:
            self._window_size = size

    def on_window_closed(self, *_args: Any) -> None:
        """Verwirft wartende Ereignisse, sobald das Fenster geschlossen ist."""
        with self._state_lock:
            self._closed = True
            window_size = self._window_size
        if window_size is not None:
            def save_size() -> None:
                self.config.set("last_window_width", window_size[0])
                self.config.set("last_window_height", window_size[1])
            self.controller.update_config(self.config, save_size)
        with self._state_lock:
            self._events.clear()
            self._latest_progress = None
            player = self._player
            self._player = None
            waveform_processes = list(self._waveform_processes.items())
        if player is not None:
            player.stop()
        for process, process_lock in waveform_processes:
            terminate_process(process, process_lock)

    def initial_state(self) -> dict[str, Any]:
        """Liefert den durch das JS-Readiness-Gate angeforderten Startzustand."""
        with self._state_lock:
            formats = self.config.get("last_formats", "txt")
            return {
                "ok": True,
                "theme": self.config.get("last_theme", "dark"),
                "paths": {key: str(path) if path else "" for key, path in self._paths.items()},
                "settings": {
                    "backend": self.config.get("last_backend", "whispercpp"),
                    "language": self.config.get("last_language", "auto"),
                    "task": self._task_value(self.config.get("last_task_display", "transcribe")),
                    "whisperx_model": self.config.get("last_whisperx_model", "large-v3"),
                    "formats": [item for item in str(formats).split(",") if item],
                    "min_speakers": self.config.get("last_min_speakers", ""),
                    "max_speakers": self.config.get("last_max_speakers", ""),
                    "keep_wav": self.config.get("last_keep_wav", False),
                    "verbose": self.config.get("last_verbose", False),
                    "no_diarize": self.config.get("last_no_diarize", False),
                    "auto_markers": self.config.get("last_auto_markers", True),
                    "colocate": self.config.get("last_colocate", True),
                },
            }

    def pick_audio(self) -> dict[str, Any]:
        return self._pick_file("audio", "Audio-Datei auswählen", (AUDIO_FILTER, ALL_FILES_FILTER))

    def pick_marker(self) -> dict[str, Any]:
        return self._pick_file("marker", "Marker-Datei auswählen", (JSON_FILTER, ALL_FILES_FILTER))

    def pick_model(self) -> dict[str, Any]:
        return self._pick_file("model", "GGML-Modell auswählen", (GGML_FILTER, ALL_FILES_FILTER))

    def pick_output(self) -> dict[str, Any]:
        result = self._dialog(webview.FOLDER_DIALOG, "Ausgabeordner auswählen", (), "output")
        return self._record_path("output", result, must_be_directory=True)

    def pick_review_file(self) -> dict[str, Any]:
        """Lädt eine Review hinter einer opaken ID, ohne ihren Pfad an JS zu geben."""
        chosen = self._dialog(
            webview.OPEN_DIALOG,
            "Review-Datei auswählen",
            (REVIEW_FILTER, ALL_FILES_FILTER),
            "review",
        )
        if not chosen:
            return {"ok": False, "cancelled": True}
        return self._register_review_from_path(Path(chosen).expanduser())

    def _register_review_from_path(self, path: Path) -> dict[str, Any]:
        """Registriert eine Review aus Dialog oder Bibliothek im identischen Format."""
        try:
            review = load_review(path)
        except ReviewError as exc:
            return {"ok": False, "error": str(exc)}
        registered = RegisteredReview(
            review.audio_path,
            review.segments,
            review.speaker_map,
            review.markers,
            review.bookmarks,
            path.parent,
            review.base_name,
            review.formats,
            segment_ids=list(review.segment_ids),
            marker_ids=list(review.marker_ids),
            review_path=path,
        )
        with self._state_lock:
            review_id = self.speaker_controller.register(registered)
            stored = self.speaker_controller.get(review_id)
            self._paths["review"] = path
        self.controller.update_config(
            self.config,
            lambda: self._save_config_path("last_review_path", path),
        )
        segments = [
            {
                "start": segment.start,
                "end": segment.end,
                "speaker_id": speaker_id,
                "text": segment.text,
            }
            for segment, speaker_id in zip(
                stored.segments, stored.segment_ids, strict=True
            )
        ]
        audio_url = review.audio_path.as_uri() if review.audio_path.exists() else ""
        bookmarks = [
            {
                "time": bookmark.time,
                "label": bookmark.label,
                "type": bookmark.type,
                "color": bookmark.color,
            }
            for bookmark in stored.bookmarks
        ]
        meta = read_recording_meta(
            review.audio_path.with_name(f"{review.audio_path.stem}.json"),
            review.audio_path.name,
        )
        return {
            "ok": True,
            "review_id": review_id,
            "base_name": review.base_name,
            "audio_name": review.audio_path.name,
            "audio_url": audio_url,
            "speakers": [
                {"id": speaker_id, "name": name}
                for speaker_id, name in review.speaker_map.items()
            ],
            "segments": segments,
            "bookmarks": bookmarks,
            "sidecar_peaks": meta.peaks if meta else [],
            "sidecar_duration_ms": meta.duration_ms if meta else 0,
            "rename_allowed": not review.audio_path.with_name(
                f"{review.audio_path.stem}.json"
            ).exists(),
        }

    def _register_waveform_process(
        self,
        process: subprocess.Popen[bytes],
        process_lock: threading.RLock,
    ) -> bool:
        """Registriert ffmpeg atomar oder lehnt ihn nach Fensterschluss ab."""
        with self._state_lock:
            if self._closed:
                return False
            self._waveform_processes[process] = process_lock
            return True

    def _unregister_waveform_process(self, process: subprocess.Popen[bytes]) -> None:
        """Entfernt einen beendeten Waveform-Prozess aus der Registry."""
        with self._state_lock:
            self._waveform_processes.pop(process, None)

    def get_waveform(self, review_id: Any) -> dict[str, Any]:
        """Liefert gecachte Peaks für das Audio einer registrierten Review."""
        if not isinstance(review_id, str):
            return {"ok": False, "error": "Ungültige Review-ID."}
        try:
            with self._state_lock:
                if self._closed:
                    raise WaveformError("Das Fenster wurde bereits geschlossen.")
                review = self.speaker_controller.get(review_id)
                audio_path = review.audio_path.resolve()
            stat = audio_path.stat()
        except (SpeakerEditError, OSError, WaveformError) as exc:
            return {"ok": False, "error": str(exc)}

        key = (audio_path, stat.st_size, stat.st_mtime_ns)
        with self._state_lock:
            cached = self._waveform_cache.get(key)
            if cached is not None:
                self._waveform_cache.move_to_end(key)
                duration, peaks = cached
                return {"ok": True, "duration": duration, "peaks": peaks}
            future = self._waveform_inflight.get(key)
            leader = future is None
            if future is None:
                future = Future()
                self._waveform_inflight[key] = future

        if not leader:
            try:
                duration, peaks = future.result()
                return {"ok": True, "duration": duration, "peaks": peaks}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        result: tuple[float, list[list[float]]] | None = None
        extraction_error: Exception | None = None
        try:
            result = extract_peaks(
                audio_path,
                register_process=self._register_waveform_process,
                unregister_process=self._unregister_waveform_process,
            )
            with self._state_lock:
                self._waveform_cache[key] = result
                self._waveform_cache.move_to_end(key)
                while len(self._waveform_cache) > MAX_WAVEFORM_CACHE:
                    self._waveform_cache.popitem(last=False)
        except Exception as exc:
            extraction_error = exc
        finally:
            # Jeder Leader-Pfad weckt sämtliche Warter, auch bei Abbruch.
            if result is not None:
                future.set_result(result)
            else:
                future.set_exception(
                    extraction_error
                    or WaveformError("Waveform-Extraktion wurde abgebrochen.")
                )
            with self._state_lock:
                self._waveform_inflight.pop(key, None)
        if extraction_error is not None:
            return {"ok": False, "error": str(extraction_error)}
        assert result is not None
        duration, peaks = result
        return {"ok": True, "duration": duration, "peaks": peaks}

    ALLOWED_FORMATS = ("txt", "md", "csv", "tsv")

    def save_output_options(self, options: Any) -> dict[str, Any]:
        """Persistiert Format- und Options-Häkchen sofort bei Auswahl."""
        if not isinstance(options, dict):
            return {"ok": False, "error": "Ungültige Optionen."}
        formats = options.get("formats")
        cleaned = [
            item for item in (formats if isinstance(formats, list) else [])
            if item in self.ALLOWED_FORMATS
        ]

        def update() -> None:
            self.config.set("last_formats", ",".join(cleaned))
            for key in ("keep_wav", "verbose", "no_diarize", "auto_markers"):
                self.config.set(f"last_{key}", bool(options.get(key)))
            if "colocate" in options:
                self.config.set("last_colocate", bool(options.get("colocate")))

        self.controller.update_config(self.config, update)
        return {"ok": True}

    def set_theme(self, theme: Any) -> dict[str, Any]:
        """Persistiert die Hell/Dunkel-Wahl in der Konfiguration."""
        value = "light" if theme == "light" else "dark"
        self.controller.update_config(
            self.config, lambda: self.config.set("last_theme", value)
        )
        return {"ok": True, "theme": value}

    def open_output_dir(self, colocate: Any = False) -> dict[str, Any]:
        """Öffnet den aktuellen Ausgabeordner im System-Dateimanager."""
        with self._state_lock:
            output = (
                self._paths["audio"].parent
                if colocate is True and self._paths["audio"] is not None
                else self._paths["output"]
            )
        if output is None or not output.is_dir():
            return {"ok": False, "error": "Kein gültiger Ausgabeordner ausgewählt."}
        try:
            subprocess.Popen(["xdg-open", str(output)])
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def play_segment(self, review_id: Any, speaker_id: Any) -> dict[str, Any]:
        if not isinstance(review_id, str) or not isinstance(speaker_id, str):
            return {"ok": False, "error": "Ungültige Review- oder Sprecher-ID."}
        try:
            with self._state_lock:
                review = self.speaker_controller.get(review_id)
                segment = _representative_segment(review, speaker_id)
                previous = self._player
                player = AudioPlayer(review.audio_path)
                self._player = player
            if previous is not None:
                previous.stop()
            player.play_segment(segment.start, segment.end)
        except (SpeakerEditError, PlaybackError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def stop_playback(self) -> dict[str, Any]:
        with self._state_lock:
            player = self._player
            self._player = None
        if player is not None:
            player.stop()
        return {"ok": True}

    def rename_review(self, review_id: Any, new_base: Any) -> dict[str, Any]:
        """Benennt Review-JSON, Ausgabedateien und Audio auf einen neuen Basisnamen um."""
        if not isinstance(review_id, str) or not isinstance(new_base, str):
            return {"ok": False, "error": "Ungültige Eingabe."}
        try:
            with self._state_lock:
                current = self.speaker_controller.get(review_id)
                if current.audio_path.with_name(f"{current.audio_path.stem}.json").exists():
                    raise SpeakerEditError(
                        "BoR-Aufnahmen können nicht umbenannt werden, weil ihre Sidecar-Paarung "
                        "erhalten bleiben muss."
                    )
                review = self.speaker_controller.rename_base(review_id, new_base)
                new_path = review.review_path
                if new_path is not None:
                    self._paths["review"] = new_path
        except SpeakerEditError as exc:
            return {"ok": False, "error": str(exc)}
        if new_path is not None:
            self.controller.update_config(
                self.config,
                lambda: self._save_config_path("last_review_path", new_path),
            )
        return {
            "ok": True,
            "base_name": review.base_name,
            "audio_name": review.audio_path.name,
            "audio_url": review.audio_path.as_uri() if review.audio_path.exists() else "",
        }

    def apply_speaker_rename(self, review_id: Any, rename_map: Any) -> dict[str, Any]:
        if not isinstance(review_id, str) or not isinstance(rename_map, dict):
            return {"ok": False, "error": "Ungültige Umbenennung."}
        try:
            with self._state_lock:
                result = self.speaker_controller.apply(review_id, rename_map)
        except SpeakerEditError as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "files_rewritten": len(result.output_paths),
            "speakers": [
                {"id": speaker_id, "name": name}
                for speaker_id, name in result.speaker_map.items()
            ],
        }

    def pick_watch_dir(self) -> dict[str, Any]:
        chosen = self._dialog(webview.FOLDER_DIALOG, "Sync-Ordner auswählen", (), "watch")
        result = self._record_path("watch", chosen, must_be_directory=True)
        if result.get("ok"):
            path = Path(result["path"])
            self.controller.update_config(
                self.config,
                lambda: self._save_config_path("last_watch_dir", path),
            )
        return result

    def pick_library_dir(self) -> dict[str, Any]:
        chosen = self._dialog(
            webview.FOLDER_DIALOG, "Bibliotheksordner auswählen", (), "library"
        )
        result = self._record_path("library", chosen, must_be_directory=True)
        if result.get("ok"):
            path = Path(result["path"])
            with self._state_lock:
                self._library_generation += 1
                self._library_items = {}
            self.controller.update_config(
                self.config,
                lambda: self._save_config_path("last_library_dir", path),
            )
        return result

    @staticmethod
    def _library_epoch(started_at: Any, fallback: float) -> float:
        if started_at is None:
            return fallback
        try:
            if started_at.tzinfo is None:
                return started_at.timestamp()
            return started_at.timestamp()
        except (OSError, OverflowError, ValueError):
            return fallback

    def scan_library(self) -> dict[str, Any]:
        with self._state_lock:
            root = self._paths["library"]
        if root is None or not root.is_dir():
            return {"ok": False, "error": "Bitte einen Bibliotheksordner auswählen."}
        scanned = 0
        truncated = False
        warning_count = 0
        candidates: list[tuple[tuple[float, str], dict[str, Any], Path]] = []
        directories: list[tuple[Path, list[Path] | None]] = []
        try:
            root_entries: list[Path] = []
            for entry in root.iterdir():
                scanned += 1
                if scanned > 5000:
                    truncated = True
                    break
                root_entries.append(entry)
                if entry.is_dir() and not entry.is_symlink():
                    directories.append((entry, None))
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        directories.insert(0, (root, root_entries))
        for directory, known_entries in directories:
            recover_transactions(directory)
            try:
                entries = known_entries if known_entries is not None else directory.iterdir()
            except OSError:
                warning_count += 1
                continue
            for audio in entries:
                if known_entries is None:
                    scanned += 1
                    if scanned > 5000:
                        truncated = True
                        break
                if not audio.is_file() or not is_supported_audio(audio):
                    continue
                sidecar = audio.with_name(f"{audio.stem}.json")
                meta = read_recording_meta(sidecar, audio.name)
                if meta:
                    warning_count += len(meta.warnings)
                elif sidecar.exists():
                    warning_count += 1
                formats = [
                    fmt for fmt, (suffix, _writer) in FORMATS.items()
                    if audio.with_name(audio.stem + suffix).is_file()
                ]
                stat = audio.stat()
                epoch = self._library_epoch(meta.started_at if meta else None, stat.st_mtime)
                item = {
                    "name": audio.name,
                    "folder": str(audio.parent),
                    "duration_ms": meta.duration_ms if meta else 0,
                    "started_at": meta.started_at.isoformat() if meta and meta.started_at else None,
                    "marker_count": meta.marker_count if meta else 0,
                    "peaks34": resample_peaks(meta.peaks, 34) if meta else [],
                    "formats_present": formats,
                    "has_review": audio.with_name(f"{audio.stem}.review.json").is_file(),
                }
                candidates.append(((epoch, audio.name), item, audio.resolve()))
            if truncated:
                break
        newest = heapq.nlargest(500, candidates, key=lambda row: row[0])
        if len(candidates) > 500:
            truncated = True
        generation = uuid.uuid4().hex
        mapping: dict[str, tuple[int, Path]] = {}
        response_items = []
        for index, (_key, item, audio) in enumerate(newest):
            item_id = uuid.uuid4().hex
            item["item_id"] = item_id
            response_items.append(item)
            mapping[item_id] = (self._library_generation + 1, audio)
        with self._state_lock:
            self._library_generation += 1
            numeric_generation = self._library_generation
            mapping = {key: (numeric_generation, value[1]) for key, value in mapping.items()}
            self._library_items = mapping
        return {
            "ok": True,
            "generation": generation,
            "items": response_items,
            "scanned": min(scanned, 5000),
            "truncated": truncated,
            "warning_count": warning_count,
        }

    def _library_audio(self, item_id: Any) -> Path:
        if not isinstance(item_id, str):
            raise ValueError("Bitte neu scannen.")
        with self._state_lock:
            root = self._paths["library"]
            registered = self._library_items.get(item_id)
            generation = self._library_generation
        if root is None or registered is None or registered[0] != generation:
            raise ValueError("Bitte neu scannen.")
        audio = registered[1]
        try:
            audio.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError("Bitte neu scannen.") from exc
        if not audio.is_file() or not is_supported_audio(audio):
            raise ValueError("Bitte neu scannen.")
        return audio

    def open_library_review(self, item_id: Any) -> dict[str, Any]:
        try:
            audio = self._library_audio(item_id)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        review = audio.with_name(f"{audio.stem}.review.json")
        if not review.is_file():
            return {"ok": False, "error": "Review nicht gefunden. Bitte neu scannen."}
        return self._register_review_from_path(review)

    def prepare_library_transcription(self, item_id: Any) -> dict[str, Any]:
        try:
            audio = self._library_audio(item_id)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        marker = audio.with_name(f"{audio.stem}.json")
        if not marker.is_file():
            marker = None
        with self._state_lock:
            self._paths["audio"] = audio
            self._paths["marker"] = marker
        return {
            "ok": True,
            "audio_path": str(audio),
            "marker_path": str(marker) if marker else "",
        }

    def pick_export_dir(self) -> dict[str, Any]:
        chosen = self._dialog(webview.FOLDER_DIALOG, "Export-Ordner auswählen", (), "export")
        result = self._record_path("export", chosen, must_be_directory=True)
        if result.get("ok"):
            path = Path(result["path"])
            self.controller.update_config(
                self.config,
                lambda: self._save_config_path("last_export_dir", path),
            )
        return result

    def open_export_dir(self) -> dict[str, Any]:
        """Öffnet den Export-Ordner im System-Dateimanager."""
        with self._state_lock:
            export_dir = self._paths.get("export")
        if export_dir is None or not export_dir.is_dir():
            return {"ok": False, "error": "Kein gültiger Export-Ordner ausgewählt."}
        try:
            subprocess.Popen(["xdg-open", str(export_dir)])
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def export_library_zip(self, item_ids: Any) -> dict[str, Any]:
        """Packt die Transkripte der gewählten Bibliothekseinträge in ein Zip."""
        if not isinstance(item_ids, list) or not all(
            isinstance(item, str) for item in item_ids
        ) or not item_ids:
            return {"ok": False, "error": "Keine Auswahl."}
        with self._state_lock:
            export_dir = self._paths.get("export")
        if export_dir is None or not export_dir.is_dir():
            return {"ok": False, "error": "Bitte zuerst einen Export-Ordner auswählen."}
        try:
            audios = [self._library_audio(item_id) for item_id in item_ids]
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        files: list[tuple[Path, str]] = []
        skipped = 0
        for audio in audios:
            transcripts = [
                candidate for suffix, _writer in FORMATS.values()
                if (candidate := audio.with_name(audio.stem + suffix)).is_file()
            ]
            if not transcripts:
                skipped += 1
                continue
            files.extend(
                # Tagesordner-Struktur im Zip beibehalten -> keine Namenskollisionen.
                (candidate, f"{audio.parent.name}/{candidate.name}")
                for candidate in transcripts
            )
        if not files:
            return {"ok": False, "error": "Die Auswahl enthält keine Transkripte."}
        zip_name = f"BoR_Transkripte_{datetime.now():%Y-%m-%d_%H-%M-%S}.zip"
        zip_path = export_dir / zip_name
        tmp_path = export_dir / f"{zip_name}.{uuid.uuid4().hex}.tmp"
        try:
            with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for source, arcname in files:
                    archive.write(source, arcname)
            os.replace(tmp_path, zip_path)
        except OSError as exc:
            tmp_path.unlink(missing_ok=True)
            return {"ok": False, "error": f"Zip konnte nicht geschrieben werden: {exc}"}
        return {
            "ok": True,
            "zip_path": str(zip_path),
            "file_count": len(files),
            "skipped": skipped,
        }

    @staticmethod
    def _settings_fingerprint(raw: dict[str, Any]) -> tuple[Any, ...]:
        formats = raw.get("formats")
        return (
            tuple(sorted(formats)) if isinstance(formats, list) else (),
            raw.get("backend"),
            raw.get("colocate") is True,
            raw.get("no_diarize") is True,
            raw.get("auto_markers") is True,
        )

    def scan_batch(self, raw_settings: Any = None) -> dict[str, Any]:
        if not isinstance(raw_settings, dict):
            return {"ok": False, "error": "Ungültige Einstellungen."}
        with self._state_lock:
            watch_dir = self._paths["watch"]
            output_dir = self._paths["output"]
            running = self._active_batch_id is not None
        if running:
            return {"ok": False, "error": "Der Batch läuft bereits."}
        colocate = raw_settings.get("colocate") is True
        if watch_dir is None or (output_dir is None and not colocate):
            return {"ok": False, "error": "Bitte Sync- und Ausgabeordner auswählen."}
        output_unavailable = output_dir is None or not output_dir.is_dir()
        if not watch_dir.is_dir() or (not colocate and output_unavailable):
            return {"ok": False, "error": "Sync- oder Ausgabeordner ist nicht verfügbar."}
        effective_output = output_dir or watch_dir
        items, skipped = self.batch_controller.scan(watch_dir, effective_output, raw_settings)
        with self._state_lock:
            self._pending_batch = items
            self._pending_batch_fingerprint = self._settings_fingerprint(raw_settings)
        return {
            "ok": True,
            "items": [
                {
                    "audio_name": item.audio_path.name,
                    "marker_name": item.marker_path.name if item.marker_path else None,
                }
                for item in items
            ],
            "skipped_unstable": skipped,
        }

    def start_batch(self, raw_settings: Any) -> dict[str, Any]:
        if not isinstance(raw_settings, dict):
            return {"ok": False, "error": "Ungültige Einstellungen."}
        with self._state_lock:
            if self._active_batch_id is not None:
                return {"ok": False, "error": "busy", "busy": True}
            items = list(self._pending_batch)
            paths = dict(self._paths)
            fingerprint = self._pending_batch_fingerprint
        if fingerprint != self._settings_fingerprint(raw_settings):
            return {"ok": False, "error": "Einstellungen geändert. Bitte neu scannen."}
        if not items:
            return {"ok": False, "error": "Bitte zuerst nach Dateien scannen."}
        built = []
        errors: list[str] = []
        for item in items:
            item_paths = dict(paths)
            item_paths["audio"] = item.audio_path
            item_paths["marker"] = item.marker_path
            settings = self._settings_from_request(raw_settings, item_paths)
            if isinstance(settings, str):
                errors.append(settings)
                break
            result = build_params(settings)
            if not result.ok or result.params is None:
                errors.extend(result.errors)
                break
            built.append((item, result.params))
        if errors:
            return {"ok": False, "errors": errors}
        batch_id = self.batch_controller.start(built)
        if batch_id is None:
            return {"ok": False, "error": "busy", "busy": True}
        with self._state_lock:
            self._active_batch_id = batch_id
        self._save_settings(built[0][1])
        return {"ok": True, "batch_id": batch_id}

    def cancel_batch(self, batch_id: Any) -> dict[str, Any]:
        if not isinstance(batch_id, str):
            return {"ok": False, "error": "Ungültige Batch-ID."}
        cancelled = self.batch_controller.cancel(batch_id)
        return {"ok": cancelled, "error": None if cancelled else "Unbekannte Batch-ID."}

    def start_transcription(self, raw_settings: Any) -> dict[str, Any]:
        """Validiert UI-Werte und startet genau einen Controller-Worker."""
        if not isinstance(raw_settings, dict):
            return {"ok": False, "error": "Ungültige Einstellungen."}
        with self._state_lock:
            paths = dict(self._paths)
        settings_or_error = self._settings_from_request(raw_settings, paths)
        if isinstance(settings_or_error, str):
            return {"ok": False, "error": settings_or_error}
        result = build_params(settings_or_error)
        if not result.ok or result.params is None:
            return {"ok": False, "errors": list(result.errors)}
        acquired = self.controller.acquire()
        if not acquired.acquired:
            return {"ok": False, "error": acquired.error or "busy"}
        job_id = str(uuid.uuid4())
        with self._state_lock:
            if self._closed:
                self.controller.release()
                return {"ok": False, "error": "Fenster wurde geschlossen."}
            self._active_job_id = job_id
            self._events.clear()
            self._latest_progress = None
            self._queued_logs = 0
        self._save_settings(result.params)
        worker = threading.Thread(
            target=self._run_worker,
            args=(job_id, result.params),
            daemon=True,
            name=f"bort-transcription-{job_id}",
        )
        worker.start()
        return {"ok": True, "job_id": job_id}

    def _run_worker(self, job_id: str, params: Any) -> None:
        transcription_worker(params, lambda event: self._enqueue_worker_event(job_id, event))

    def _enqueue_worker_event(self, job_id: str, event: tuple[Any, ...]) -> None:
        payload = self._event_payload(event)
        if payload is None:
            return
        with self._state_lock:
            if self._closed or self._active_job_id != job_id:
                return
            if payload["type"] == "progress":
                self._latest_progress = (job_id, payload)
            else:
                if payload["type"] == "log":
                    while self._queued_logs >= MAX_QUEUED_LOGS:
                        self._discard_oldest_log()
                    self._queued_logs += 1
                self._events.append((job_id, payload))
        self._schedule_drain()

    def _enqueue_batch_event(self, event: tuple[Any, ...]) -> None:
        payload = self._batch_event_payload(event)
        if payload is None:
            return
        batch_id = str(event[1])
        with self._state_lock:
            if self._closed:
                return
            if self._active_batch_id not in {None, batch_id}:
                return
            if payload["type"] == "batch_item_progress":
                self._latest_progress = (batch_id, payload)
            else:
                if payload["type"] == "batch_item_log":
                    while self._queued_logs >= MAX_QUEUED_LOGS:
                        self._discard_oldest_log()
                    self._queued_logs += 1
                self._events.append((batch_id, payload))
        self._schedule_drain()

    def enqueue_api_result(self, call_id: str, result: Any, error: str | None = None) -> None:
        """Reiht eine Antwort der statischen CSP-kompatiblen JS-API über den GTK-Dispatcher ein."""
        payload = {"type": "bridge-result", "id": call_id, "ok": error is None}
        if error is None:
            payload["result"] = result
        else:
            payload["error"] = error
        with self._state_lock:
            if self._closed:
                return
            self._events.append(("", payload))
        self._schedule_drain()

    def _schedule_drain(self) -> None:
        with self._state_lock:
            if (
                self._closed
                or not self._window_loaded
                or self._drain_scheduled
                or self._delivery_active
            ):
                return
            self._drain_scheduled = True
        GLib.idle_add(self._drain_events)

    def _drain_events(self) -> bool:
        """Läuft ausschließlich im GTK-Mainloop und übergibt JSON an den festen Dispatcher."""
        with self._state_lock:
            self._drain_scheduled = False
            if self._closed or not self._window_loaded or self.window is None:
                return False
            events = list(self._events)
            self._events.clear()
            if self._latest_progress:
                events.append(self._latest_progress)
                self._latest_progress = None
            self._queued_logs = 0
            if not events:
                return False
            self._delivery_active = True
        threading.Thread(
            target=self._deliver_events,
            args=(events,),
            daemon=True,
            name="bort-js-dispatch",
        ).start()
        return False

    def _deliver_events(self, events: list[tuple[str, dict[str, Any]]]) -> None:
        """Sendet die vom GTK-Idle-Drain gebündelten Daten über pywebviews ``run_js``."""
        for job_id, payload in events:
            with self._state_lock:
                valid_id = job_id in {"", self._active_job_id, self._active_batch_id}
                if self._closed or not valid_id:
                    continue
            try:
                payload_json = json.dumps(payload, ensure_ascii=False)
                self.window.run_js(f"window.__bortDispatch({json.dumps(payload_json)});")
            except Exception:
                self.on_window_closed()
                break
            if payload["type"] in {"done", "error"}:
                with self._state_lock:
                    if self._active_job_id == job_id:
                        self._active_job_id = None
                        self.controller.release()
            elif payload["type"] == "batch_finished":
                with self._state_lock:
                    if self._active_batch_id == job_id:
                        self._active_batch_id = None
                        self._pending_batch = []
        with self._state_lock:
            self._delivery_active = False
        self._schedule_drain()

    def _pick_file(self, key: str, title: str, filters: tuple[str, ...]) -> dict[str, Any]:
        result = self._dialog(webview.OPEN_DIALOG, title, filters, key)
        return self._record_path(key, result)

    def _dialog(
        self, dialog_type: int, title: str, filters: tuple[str, ...], key: str
    ) -> str | None:
        if self.window is None:
            return None
        with self._state_lock:
            current = self._paths.get(key)
            initial = (
                current.parent
                if current and key not in {"output", "watch", "library"}
                else current
            )
        # Verschwundene Ordner (gelöscht, umbenannt, fremder tmp-Pfad) auf den
        # nächsten existierenden Elternordner zurückfallen lassen statt auf Home.
        while initial is not None and not initial.is_dir():
            parent = initial.parent
            initial = parent if parent != initial else None
        directory = str(initial or Path.home())
        # WICHTIG: KEIN Datei-Filter für Ordner-Dialoge. Ein '*.*'-Filter auf
        # GTK SELECT_FOLDER lässt get_filenames() leer -> der geöffnete Ordner
        # ist nicht wählbar. Ordner-Aufrufer übergeben filters=() bewusst.
        chosen = self.window.create_file_dialog(
            dialog_type,
            directory=directory,
            allow_multiple=False,
            file_types=filters,
        )
        if not chosen:
            return None
        return str(chosen[0])

    def _record_path(
        self, key: str, value: str | None, *, must_be_directory: bool = False
    ) -> dict[str, Any]:
        if not value:
            return {"ok": False, "cancelled": True}
        path = Path(value).expanduser()
        if not path.exists() or (must_be_directory and not path.is_dir()):
            return {"ok": False, "error": "Ausgewählter Pfad ist nicht verfügbar."}
        if not must_be_directory and not path.is_file():
            return {"ok": False, "error": "Ausgewählter Pfad ist keine Datei."}
        with self._state_lock:
            self._paths[key] = path
        return {"ok": True, "path": str(path)}

    def _save_config_path(self, key: str, path: Path) -> None:
        self.config.set_path(key, path)

    def _settings_from_request(
        self, raw: dict[str, Any], paths: dict[str, Path | None]
    ) -> TranscriptionSettings | str:
        backend = raw.get("backend")
        language = raw.get("language")
        task = raw.get("task")
        formats = raw.get("formats")
        if backend not in {"whispercpp", "whisperx"}:
            return "Unbekanntes Backend."
        languages = {"auto", "de", "en", "fr", "es", "it", "pt", "nl", "pl", "ru", "zh", "ja"}
        if language not in languages:
            return "Unbekannte Sprache."
        if task not in {"transcribe", "translate"}:
            return "Unbekannte Aufgabe."
        if not isinstance(formats, list) or any(
            item not in {"txt", "md", "csv", "tsv"} for item in formats
        ):
            return "Ungültige Ausgabeformate."
        colocate = raw.get("colocate") is True
        if not paths["audio"] or (not colocate and not paths["output"]):
            return "Bitte Audio-Datei und Ausgabeordner auswählen."
        return TranscriptionSettings(
            audio_path=paths["audio"],
            marker_path=paths["marker"],
            model_path=paths["model"],
            output_dir=paths["output"] or paths["audio"].parent,
            formats=formats,
            language=None if language == "auto" else language,
            task=task,
            backend=backend,
            whisperx_model=self._choice(raw.get("whisperx_model"), "large-v3"),
            min_speakers=self._speaker_count(raw.get("min_speakers")),
            max_speakers=self._speaker_count(raw.get("max_speakers")),
            keep_wav=raw.get("keep_wav") is True,
            verbose=raw.get("verbose") is True,
            no_diarize=raw.get("no_diarize") is True,
            auto_markers=raw.get("auto_markers") is True,
            colocate=colocate,
        )

    @staticmethod
    def _choice(value: Any, default: str) -> str:
        choices = {"large-v3", "large-v2", "medium", "small", "base", "tiny"}
        return value if value in choices else default

    @staticmethod
    def _speaker_count(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            return ""
        try:
            number = int(value)
        except ValueError:
            return value
        return str(number) if 1 <= number <= 99 else value

    def _save_settings(self, params: Any) -> None:
        def update() -> None:
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
            self.config.set("last_task_display", params.task)
            self.config.set("last_backend", params.backend)
            self.config.set("last_whisperx_model", params.whisperx_model)
            self.config.set("last_formats", ",".join(params.formats))
            self.config.set("last_min_speakers", str(params.min_speakers or ""))
            self.config.set("last_max_speakers", str(params.max_speakers or ""))
            self.config.set("last_keep_wav", params.keep_wav)
            self.config.set("last_verbose", params.verbose)
            self.config.set("last_no_diarize", params.no_diarize)
            self.config.set("last_auto_markers", params.auto_markers)
            self.config.set("last_colocate", params.colocate)

        self.controller.update_config(self.config, update)

    def _discard_oldest_log(self) -> None:
        for index, (_job_id, payload) in enumerate(self._events):
            if payload["type"] == "log":
                del self._events[index]
                self._queued_logs -= 1
                return

    @staticmethod
    def _task_value(value: Any) -> str:
        return "translate" if value in {"translate", "Nach Englisch übersetzen"} else "transcribe"

    @staticmethod
    def _event_payload(event: tuple[Any, ...]) -> dict[str, Any] | None:
        if not event:
            return None
        event_type = event[0]
        if event_type == "progress":
            return {"type": "progress", "percent": event[1], "phase": event[2]}
        if event_type == "log":
            return {"type": "log", "level": event[1], "message": event[2]}
        if event_type == "error":
            return {"type": "error", "message": event[1]}
        if event_type == "done":
            data = event[2]
            segments = [
                {
                    "start": segment.start,
                    "end": segment.end,
                    "speaker": segment.speaker,
                    "text": segment.text,
                }
                for segment in data["segments"]
            ]
            return {
                "type": "done",
                "message": event[1],
                "segments": segments,
                "output_location": str(data["output_location"]),
            }
        return None

    @staticmethod
    def _batch_event_payload(event: tuple[Any, ...]) -> dict[str, Any] | None:
        if len(event) < 2 or not isinstance(event[1], str):
            return None
        event_type = event[0]
        payload: dict[str, Any] = {"type": event_type, "batch_id": event[1]}
        if event_type == "batch_item_start":
            payload.update(index=event[2], total=event[3], audio_name=event[4])
        elif event_type in {"batch_item_done", "batch_item_error", "batch_item_skip"}:
            payload.update(audio_name=event[2], message=event[3])
        elif event_type == "batch_item_log":
            payload.update(
                index=event[2], total=event[3], level=event[4], message=event[5]
            )
        elif event_type == "batch_item_progress":
            payload.update(
                index=event[2], total=event[3], percent=event[4], phase=event[5]
            )
        elif event_type == "batch_finished":
            payload.update(succeeded=event[2], failed=event[3], skipped=event[4])
        else:
            return None
        return payload


def _install_strict_csp_bridge() -> None:
    """Ersetzt pywebviews eval-Antwortpfad durch den festen ``run_js``-Dispatcher.

    pywebview 6 erzeugt sonst mit ``new Function`` dynamische API-Methoden und antwortet mit
    ``evaluate_js``. Beides würde eine ``unsafe-eval``-CSP-Ausnahme erzwingen. Die
    Frontend-Proxy-API
    sendet weiterhin über die native pywebview-GTK-Message-Bridge, die Antworten werden jedoch als
    JSON-Daten in die vorhandene, GTK-mainloop-gesteuerte Dispatch-Queue gelegt.
    """
    import webview.platforms.gtk as gtk

    def js_bridge_call(window: Any, func_name: str, params: Any, value_id: str) -> None:
        bridge = window._js_api
        func = getattr(bridge, func_name, None)
        if not callable(func) or not isinstance(params, list):
            bridge.enqueue_api_result(value_id, None, "Unbekannte Bridge-Methode.")
            return

        def call() -> None:
            try:
                bridge.enqueue_api_result(value_id, func(*params))
            except Exception as exc:
                bridge.enqueue_api_result(value_id, None, str(exc))

        threading.Thread(target=call, daemon=True, name="bort-web-bridge").start()

    gtk.js_bridge_call = js_bridge_call


def _saved_dimension(value: Any, default: int, minimum: int) -> int:
    """Validiert eine gespeicherte Fensterabmessung aus der Config."""
    try:
        size = int(value)
    except (TypeError, ValueError):
        return default
    return max(size, minimum)


def main() -> None:
    """Startet das einzelne lokale pywebview-Fenster."""
    # WM_CLASS "bort" statt "app.py": KDE ordnet das Fenster damit dem
    # bort.desktop-Eintrag zu (StartupWMClass) -> richtiger Name + Icon in
    # Taskbar/Fensterwechsler. sys.argv[0] MUSS mit gesetzt werden, weil
    # Gtk.init (in webview.start) den prgname sonst wieder aus argv[0] ableitet.
    sys.argv[0] = "bort"
    GLib.set_prgname("bort")
    GLib.set_application_name("BoR Transcriber")
    bridge = Bridge()
    index = resources.files("bort").joinpath("web", "index.html")
    with resources.as_file(index) as index_path:
        window = webview.create_window(
            "BoR Transcriber",
            # file://-URI erzwingen: bei einem blanken Pfad serviert pywebview die
            # Seite über seinen internen HTTP-Server (Origin http://127.0.0.1:PORT),
            # und eine http-Seite darf keine file://-Audio-URLs laden -> Player tot
            # (MEDIA_ERR_SRC_NOT_SUPPORTED). Als file://-Seite ist das Review-Audio
            # über allow_file_access_from_file_urls (pywebview-Default) erlaubt.
            url=Path(index_path).resolve().as_uri(),
            js_api=bridge,
            width=_saved_dimension(bridge.config.get("last_window_width"), 1280, 900),
            height=_saved_dimension(bridge.config.get("last_window_height"), 900, 700),
            min_size=(900, 700),
        )
        bridge.attach_window(window)
        window.events.loaded += bridge.on_window_loaded
        window.events.resized += bridge.on_window_resized
        window.events.closed += bridge.on_window_closed
        icon = resources.files("bort").joinpath("web", "icon.png")
        with resources.as_file(icon) as icon_path:
            webview.start(_install_strict_csp_bridge, gui="gtk", icon=str(icon_path))


if __name__ == "__main__":
    main()

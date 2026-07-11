"""Pywebview-basierte Phase-1-Oberfläche für BoRT."""

from __future__ import annotations

import json
import threading
import uuid
from collections import deque
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any

import gi
import webview

from .config import Config
from .controller.jobs import (
    JobController,
    TranscriptionSettings,
    build_params,
    transcription_worker,
)


def _load_glib() -> Any:
    gi.require_version("GLib", "2.0")
    from gi.repository import GLib

    return GLib


GLib = _load_glib()

AUDIO_FILTER = "Audio-Dateien (*.mp3;*.m4a;*.aac;*.wav;*.flac;*.ogg;*.opus;*.wma)"
JSON_FILTER = "JSON-Dateien (*.json)"
GGML_FILTER = "GGML-Modelle (*.bin;*.gguf)"
ALL_FILES_FILTER = "Alle Dateien (*.*)"
MAX_QUEUED_LOGS = 300


class Bridge:
    """Thread-sichere API zwischen der lokalen Oberfläche und den Controllern."""

    def __init__(
        self, config: Config | None = None, controller: JobController | None = None
    ) -> None:
        self.config = config or Config()
        self.controller = controller or JobController()
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
        self._paths: dict[str, Path | None] = {
            "audio": self.config.get_path("last_audio_path"),
            "marker": self.config.get_path("last_marker_path"),
            "output": self.config.get_path("last_output_dir"),
            "model": self.config.get_path("last_model_path"),
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

    def on_window_closed(self, *_args: Any) -> None:
        """Verwirft wartende Ereignisse, sobald das Fenster geschlossen ist."""
        with self._state_lock:
            self._closed = True
            self._events.clear()
            self._latest_progress = None

    def initial_state(self) -> dict[str, Any]:
        """Liefert den durch das JS-Readiness-Gate angeforderten Startzustand."""
        with self._state_lock:
            formats = self.config.get("last_formats", "txt,md,csv,tsv")
            return {
                "ok": True,
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
                },
            }

    def pick_audio(self) -> dict[str, Any]:
        return self._pick_file("audio", "Audio-Datei auswählen", (AUDIO_FILTER, ALL_FILES_FILTER))

    def pick_marker(self) -> dict[str, Any]:
        return self._pick_file("marker", "Marker-Datei auswählen", (JSON_FILTER, ALL_FILES_FILTER))

    def pick_model(self) -> dict[str, Any]:
        return self._pick_file("model", "GGML-Modell auswählen", (GGML_FILTER, ALL_FILES_FILTER))

    def pick_output(self) -> dict[str, Any]:
        result = self._run_on_gtk(
            lambda: self._dialog(webview.FOLDER_DIALOG, "Ausgabeordner auswählen", (), "output")
        )
        return self._record_path("output", result, must_be_directory=True)

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
                if self._closed or (job_id and job_id != self._active_job_id):
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
        with self._state_lock:
            self._delivery_active = False
        self._schedule_drain()

    def _pick_file(self, key: str, title: str, filters: tuple[str, ...]) -> dict[str, Any]:
        result = self._run_on_gtk(lambda: self._dialog(webview.OPEN_DIALOG, title, filters, key))
        return self._record_path(key, result)

    def _run_on_gtk(self, callback: Callable[[], Any]) -> Any:
        """Führt einen Dialog aus einem js_api-Thread sicher auf dem GTK-Mainloop aus."""
        completed = threading.Event()
        result: dict[str, Any] = {"value": None, "error": None}

        def invoke() -> bool:
            try:
                result["value"] = callback()
            except Exception as exc:
                result["error"] = exc
            finally:
                completed.set()
            return False

        GLib.idle_add(invoke)
        completed.wait()
        if result["error"]:
            return None
        return result["value"]

    def _dialog(
        self, dialog_type: int, title: str, filters: tuple[str, ...], key: str
    ) -> str | None:
        if self.window is None:
            return None
        with self._state_lock:
            current = self._paths.get(key)
            initial = current.parent if current and key != "output" else current
            directory = str(initial or Path.home())
        chosen = self.window.create_file_dialog(
            dialog_type,
            directory=directory,
            allow_multiple=False,
            file_types=filters or (ALL_FILES_FILTER,),
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
        if not paths["audio"] or not paths["output"]:
            return "Bitte Audio-Datei und Ausgabeordner auswählen."
        return TranscriptionSettings(
            audio_path=paths["audio"],
            marker_path=paths["marker"],
            model_path=paths["model"],
            output_dir=paths["output"],
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


def main() -> None:
    """Startet das einzelne lokale pywebview-Fenster."""
    bridge = Bridge()
    index = resources.files("bort").joinpath("web", "index.html")
    with resources.as_file(index) as index_path:
        window = webview.create_window(
            "BoR Transcriber",
            url=str(index_path),
            js_api=bridge,
            width=1280,
            height=900,
            min_size=(900, 700),
        )
        bridge.attach_window(window)
        window.events.loaded += bridge.on_window_loaded
        window.events.closed += bridge.on_window_closed
        webview.start(_install_strict_csp_bridge)


if __name__ == "__main__":
    main()

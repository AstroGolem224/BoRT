"""Transkriptions-Parameter, Worker und synchronisierte Job-Steuerung."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..audio import AudioError, convert_to_wav, is_supported_audio
from ..markers import Bookmark, MarkerError, load_bookmarks, load_markers
from ..speakers import MarkerSpeakerResolver, PlaceholderSpeakerResolver, SpeakerMarker
from ..transcription import TranscriptionError, transcribe
from ..whisperx_backend import WhisperXError, save_markers
from ..whisperx_backend import transcribe as transcribe_whisperx
from ..writers import write_outputs

EventEmitter = Callable[[tuple[Any, ...]], None]


@dataclass(frozen=True)
class TranscriptionSettings:
    """Von einer Oberfläche gelesene, noch nicht validierte Einstellungen."""

    audio_path: Path
    marker_path: Path | None
    model_path: Path | None
    output_dir: Path
    formats: list[str]
    language: str | None
    task: str
    backend: str
    whisperx_model: str = "large-v3"
    min_speakers: str = ""
    max_speakers: str = ""
    keep_wav: bool = False
    verbose: bool = False
    no_diarize: bool = False
    auto_markers: bool = True


@dataclass(frozen=True)
class TranscriptionParams:
    """Validierte Parameter für einen Transkriptionslauf."""

    audio_path: Path
    marker_path: Path | None
    model_path: Path | None
    language: str | None
    output_dir: Path
    formats: list[str]
    keep_wav: bool
    verbose: bool = False
    task: str = "transcribe"
    backend: str = "whispercpp"
    whisperx_model: str = "large-v3"
    min_speakers: int | None = None
    max_speakers: int | None = None
    no_diarize: bool = False
    auto_markers: bool = True


@dataclass(frozen=True)
class ParamsResult:
    """Strukturiertes Ergebnis des reinen Parameterbaus."""

    params: TranscriptionParams | None
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.params is not None and not self.errors


@dataclass(frozen=True)
class JobResult:
    """Ergebnis eines Job-Lock-Versuchs."""

    acquired: bool
    error: str | None = None


def build_params(settings: TranscriptionSettings) -> ParamsResult:
    """Validiert Einstellungen ohne UI-Nebenwirkungen oder Dialoge zu öffnen."""
    errors: list[str] = []
    if not settings.audio_path.exists():
        errors.append("Audio-Datei nicht gefunden.")
    elif not is_supported_audio(settings.audio_path):
        errors.append(
            f"Nicht unterstütztes Format: {settings.audio_path.suffix or '(keine Endung)'}."
        )
    if settings.marker_path and not settings.marker_path.exists():
        errors.append("Marker-Datei nicht gefunden.")
    if settings.backend not in {"whispercpp", "whisperx"}:
        errors.append("Unbekanntes Backend.")
    if settings.backend == "whispercpp" and (
        settings.model_path is None or not settings.model_path.exists()
    ):
        errors.append("Modell-Datei nicht gefunden.")
    if not settings.formats:
        errors.append("Mindestens ein Ausgabeformat auswählen.")

    def parse_speakers(value: str, label: str) -> int | None:
        if not value.strip():
            return None
        try:
            return int(value)
        except ValueError:
            errors.append(f"{label} muss eine Zahl sein.")
            return None

    min_speakers = parse_speakers(settings.min_speakers, "Min. Sprecher")
    max_speakers = parse_speakers(settings.max_speakers, "Max. Sprecher")
    if errors:
        return ParamsResult(None, tuple(errors))
    return ParamsResult(
        TranscriptionParams(
            audio_path=settings.audio_path,
            marker_path=settings.marker_path,
            model_path=settings.model_path,
            output_dir=settings.output_dir,
            formats=list(settings.formats),
            language=settings.language,
            task=settings.task,
            backend=settings.backend,
            whisperx_model=settings.whisperx_model or "large-v3",
            min_speakers=min_speakers if settings.backend == "whisperx" else None,
            max_speakers=max_speakers if settings.backend == "whisperx" else None,
            keep_wav=settings.keep_wav,
            verbose=settings.verbose,
            no_diarize=settings.no_diarize,
            auto_markers=settings.auto_markers,
        )
    )


class JobController:
    """Thread-sicherer gemeinsamer Lock für Einzel- und Batch-Jobs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._config_lock = threading.Lock()

    def acquire(self) -> JobResult:
        if self._lock.acquire(blocking=False):
            return JobResult(True)
        return JobResult(False, "busy")

    def release(self) -> None:
        if self._lock.locked():
            self._lock.release()

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def update_config(self, config: Any, update: Callable[[], None]) -> None:
        """Serialisiert zusammengehörige Config-Mutationen samt Speichern."""
        with self._config_lock:
            update()
            config.save()


class EmitLogHandler(logging.Handler):
    """Leitet Log-Records über die UI-agnostische Event-Schnittstelle weiter."""

    def __init__(self, emit: EventEmitter) -> None:
        super().__init__()
        self._emit = emit

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._emit(("log", record.levelname, self.format(record)))
        except Exception:
            self.handleError(record)


def _setup_worker_logging(emit: EventEmitter, verbose: bool) -> tuple[logging.Handler, int]:
    root = logging.getLogger()
    previous_level = root.level
    handler = EmitLogHandler(emit)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    return handler, previous_level


def transcription_worker(params: TranscriptionParams, emit: EventEmitter) -> None:
    """Führt einen Transkriptionslauf aus und emittiert strukturierte Events."""
    logger = logging.getLogger(__name__)
    bookmarks: list[Bookmark] = []
    if params.backend == "whisperx" and params.marker_path:
        try:
            bookmarks = load_bookmarks(params.marker_path)
            logger.info("Bookmarks geladen: %d", len(bookmarks))
        except MarkerError:
            bookmarks = []
    wx_speaker_map: dict[str, str] | None = None
    wx_markers: list[SpeakerMarker] | None = None

    def progress(percent: float, phase: str) -> None:
        emit(("progress", percent, phase))

    handler, previous_level = _setup_worker_logging(emit, params.verbose)
    try:
        if params.backend == "whisperx":
            logger.info(
                "Starte Transkription mit whisperX (Modell=%s, Sprache=%s)",
                params.whisperx_model,
                params.language or "auto",
            )
            progress(0.0, "Initialisiere")
            result = transcribe_whisperx(
                audio_path=params.audio_path,
                language=params.language if params.language != "auto" else None,
                model_name=params.whisperx_model,
                min_speakers=params.min_speakers,
                max_speakers=params.max_speakers,
                no_diarize=params.no_diarize,
                progress_cb=progress,
            )
            if params.auto_markers and not params.no_diarize:
                marker_path = params.output_dir / f"{params.audio_path.stem}.markers.json"
                save_markers(result, marker_path)
                logger.info("Auto-Marker gespeichert: %s", marker_path)
            logger.info(
                "Transkription abgeschlossen (%d Segmente, %d Sprecher).",
                len(result.segments),
                len(result.speaker_map),
            )
            logger.info("Erkannte Sprache: %s", result.language or "unbekannt")
            speaker_segments = MarkerSpeakerResolver(result.markers, result.speaker_map).resolve(
                result.segments
            )
            wx_speaker_map, wx_markers = dict(result.speaker_map), list(result.markers)
        else:
            if not params.model_path:
                raise TranscriptionError("Modell-Pfad fehlt (für whisper.cpp-Backend erforderlich)")
            logger.info("Konvertiere Audio: %s", params.audio_path)
            progress(0.0, "Konvertiere Audio")
            wav_path = convert_to_wav(
                params.audio_path, params.output_dir if params.keep_wav else None
            )
            logger.info("WAV erzeugt: %s", wav_path)
            logger.info(
                "Starte Transkription mit whisper.cpp (Sprache=%s, Aufgabe=%s)",
                params.language or "auto",
                params.task,
            )
            progress(0.0, "Transkribiere")
            result = transcribe(
                wav_path=wav_path,
                model_path=params.model_path,
                language=params.language,
                task=params.task,
                progress_cb=progress,
            )
            logger.info("Transkription abgeschlossen (%d Segmente).", len(result.segments))
            logger.info("Erkannte Sprache: %s", result.language or "unbekannt")
            if params.marker_path:
                logger.info("Lade Marker-Datei: %s", params.marker_path)
                speaker_map, markers = load_markers(params.marker_path)
                resolver = MarkerSpeakerResolver(markers, speaker_map)
            else:
                logger.info("Keine Marker-Datei angegeben – verwende Fallback-Sprecher.")
                resolver = PlaceholderSpeakerResolver()
            speaker_segments = resolver.resolve(result.segments)
        progress(95.0, "Speichere")
        review_data = _review_data(params, speaker_segments, wx_speaker_map, wx_markers, bookmarks)
        output_paths = write_outputs(
            speaker_segments,
            params.output_dir,
            params.audio_path.stem,
            params.formats,
            bookmarks or None,
            review_data,
        )
        output_location = output_paths[0].parent if output_paths else params.output_dir
        logger.info("Ausgabe gespeichert in %s:", output_location)
        for path in output_paths:
            logger.info("  - %s", path)
        if params.backend != "whisperx" and not params.keep_wav:
            wav_path.unlink(missing_ok=True)
        progress(100.0, "Fertig")
        emit(
            (
                "done",
                "Transkription erfolgreich abgeschlossen.",
                {
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
                    "no_diarize": params.no_diarize,
                },
            )
        )
    except (AudioError, MarkerError, TranscriptionError, WhisperXError) as exc:
        emit(("error", str(exc)))
    except Exception as exc:
        emit(("error", f"Unerwarteter Fehler: {exc}"))
    finally:
        root = logging.getLogger()
        root.removeHandler(handler)
        root.setLevel(previous_level)


def _review_data(
    params: TranscriptionParams,
    segments: list[Any],
    speaker_map: dict[str, str] | None,
    markers: list[SpeakerMarker] | None,
    bookmarks: list[Bookmark],
) -> dict[str, Any] | None:
    if params.backend != "whisperx":
        return None
    return {
        "schema_version": 1,
        "audio_path": str(params.audio_path),
        "segments": [
            {"start": s.start, "end": s.end, "speaker": s.speaker, "text": s.text} for s in segments
        ],
        "speaker_map": dict(speaker_map or {}),
        "markers": [{"start": m.start, "end": m.end, "speaker": m.speaker} for m in markers or []],
        "bookmarks": [
            {"time": b.time, "label": b.label, "type": b.type, "color": b.color} for b in bookmarks
        ],
        "base_name": params.audio_path.stem,
        "formats": params.formats,
    }

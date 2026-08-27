"""Transkriptions-Parameter, Worker und synchronisierte Job-Steuerung."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..audio import AudioError, cleanup_wav, convert_to_wav, is_supported_audio
from ..markers import Bookmark, MarkerError, load_bookmarks, load_markers
from ..speakers import MarkerSpeakerResolver, PlaceholderSpeakerResolver, Segment, SpeakerMarker
from ..transcription import TranscriptionError, transcribe
from ..whisperx_backend import WhisperXError
from ..whisperx_backend import transcribe as transcribe_whisperx
from ..writers import write_outputs

logger = logging.getLogger(__name__)

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
    whisperx_model: str = "large-v3-turbo"
    min_speakers: str = ""
    max_speakers: str = ""
    keep_wav: bool = False
    verbose: bool = False
    no_diarize: bool = False
    auto_markers: bool = True
    colocate: bool = True
    voice_profiles: bool = False
    performance_profile: str = "balanced"


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
    whisperx_model: str = "large-v3-turbo"
    min_speakers: int | None = None
    max_speakers: int | None = None
    no_diarize: bool = False
    auto_markers: bool = True
    colocate: bool = True
    voice_profiles: bool = False
    performance_profile: str = "balanced"


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
    effective_output = settings.audio_path.parent if settings.colocate else settings.output_dir
    if settings.colocate:
        if not effective_output.is_dir() or not os.access(effective_output, os.W_OK):
            errors.append("Der Ordner der Audio-Datei ist nicht beschreibbar.")
    elif not settings.output_dir.is_dir():
        errors.append("Ausgabeordner nicht gefunden.")

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
    performance_profile = (
        settings.performance_profile
        if settings.performance_profile in {"fast", "balanced", "quality"}
        else "balanced"
    )
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
            whisperx_model=settings.whisperx_model or "large-v3-turbo",
            min_speakers=min_speakers if settings.backend == "whisperx" else None,
            max_speakers=max_speakers if settings.backend == "whisperx" else None,
            keep_wav=settings.keep_wav,
            verbose=settings.verbose,
            no_diarize=settings.no_diarize,
            auto_markers=settings.auto_markers,
            colocate=settings.colocate,
            voice_profiles=settings.voice_profiles and settings.backend == "whisperx",
            performance_profile=performance_profile,
        )
    )


def expected_artifacts(
    settings: TranscriptionParams | TranscriptionSettings | dict[str, Any],
) -> tuple[str, ...]:
    """Definiert den vom Worker tatsächlich erzeugten vollständigen Artefaktsatz."""
    if isinstance(settings, dict):
        get = settings.get
    else:
        def get(key: str, default: Any = None) -> Any:
            return getattr(settings, key, default)
    suffixes = [f".{fmt}" for fmt in get("formats", [])]
    if get("backend") == "whisperx":
        suffixes.append(".review.json")
        if get("auto_markers", True) and not get("no_diarize", False):
            suffixes.append(".markers.json")
    return tuple(suffixes)


class JobController:
    """Thread-sicherer gemeinsamer Lock für Einzel- und Batch-Jobs.

    Der Lock gehört dem Thread, der ihn ``acquire``d. Ein Worker-Thread kann
    den Besitz per ``adopt`` übernehmen; alle anderen Threads (fremder
    ``release``) werden mit Warnung abgewiesen.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._config_lock = threading.Lock()
        self._owner_lock = threading.Lock()
        self._owner: int | None = None

    def acquire(self) -> JobResult:
        if self._lock.acquire(blocking=False):
            with self._owner_lock:
                self._owner = threading.get_ident()
            return JobResult(True)
        return JobResult(False, "busy")

    def adopt(self) -> None:
        """Überträgt den Lock-Besitz auf den aufrufenden Worker-Thread."""
        if not self._lock.locked():
            return
        with self._owner_lock:
            self._owner = threading.get_ident()

    def release(self) -> None:
        with self._owner_lock:
            if not self._lock.locked():
                return
            if self._owner is not None and self._owner != threading.get_ident():
                logger.warning(
                    "Job-Lock-Freigabe durch fremden Thread verweigert "
                    "(Owner=%s, Aufrufer=%s).",
                    self._owner,
                    threading.get_ident(),
                )
                return
            self._owner = None
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


class _JobAborted(Exception):
    """Internes Signal: Nutzer hat den Lauf abgebrochen (kein Fehlerfall)."""


def transcription_worker(
    params: TranscriptionParams,
    emit: EventEmitter,
    abort_event: threading.Event | None = None,
) -> None:
    """Führt einen Transkriptionslauf aus und emittiert strukturierte Events.

    Mit ``abort_event`` wird ein Nutzer-Abbruch unterstützt: Der Event wird
    zwischen den Stufen (Audio → Transkribieren → Schreiben) geprüft; aktive
    Subprozesse sterben zusätzlich über die Streaming-Registry. Beim Abbruch
    emittiert der Worker ``("cancelled", ...)`` statt eines Fehler-Events.
    """
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
    wx_embeddings: dict[str, list[float]] | None = None
    wx_embedding_model: str | None = None
    wx_runtime_metrics: dict[str, float] | None = None
    wav_path: Path | None = None

    def progress(percent: float, phase: str) -> None:
        emit(("progress", percent, phase))

    def checkpoint() -> None:
        """Bricht zwischen den Stufen sauber ab (abort-vs-error)."""
        if abort_event is not None and abort_event.is_set():
            raise _JobAborted()

    def partial_segment(segment: Segment) -> None:
        """Reicht ein live fertig transkribiertes Segment als Event weiter."""
        emit(("partial", {"start": segment.start, "end": segment.end, "text": segment.text}))

    handler, previous_level = _setup_worker_logging(emit, params.verbose)
    try:
        checkpoint()
        effective_output = params.audio_path.parent if params.colocate else params.output_dir
        if params.backend == "whisperx":
            logger.info(
                "Starte Transkription mit whisperX (Modell=%s, Sprache=%s)",
                params.whisperx_model,
                params.language or "auto",
            )
            progress(0.0, "Initialisiere")
            # Gate direkt vor dem Subprozess: Ein Cancel nach dem letzten
            # Checkpoint greift sofort statt erst nach erneutem Klick.
            checkpoint()
            result = transcribe_whisperx(
                audio_path=params.audio_path,
                language=params.language if params.language != "auto" else None,
                model_name=params.whisperx_model,
                min_speakers=params.min_speakers,
                max_speakers=params.max_speakers,
                no_diarize=params.no_diarize,
                return_embeddings=params.voice_profiles,
                progress_cb=progress,
                performance_profile=params.performance_profile,
            )
            marker_data = None
            if params.auto_markers and not params.no_diarize:
                marker_data = {
                    "speakers": dict(result.speaker_map),
                    "markers": [
                        {"start": marker.start, "end": marker.end, "speaker": marker.speaker}
                        for marker in result.markers
                    ],
                }
            logger.info(
                "Transkription abgeschlossen (%d Segmente, %d Sprecher).",
                len(result.segments),
                len(result.speaker_map),
            )
            logger.info("Erkannte Sprache: %s", result.language or "unbekannt")
            if result.runtime_metrics:
                logger.info("Laufzeiten: %s", result.runtime_metrics)
            speaker_segments = MarkerSpeakerResolver(result.markers, result.speaker_map).resolve(
                result.segments
            )
            wx_speaker_map, wx_markers = dict(result.speaker_map), list(result.markers)
            wx_embeddings = dict(result.speaker_embeddings)
            wx_embedding_model = result.embedding_model
            wx_runtime_metrics = dict(result.runtime_metrics)
        else:
            if not params.model_path:
                raise TranscriptionError("Modell-Pfad fehlt (für whisper.cpp-Backend erforderlich)")
            checkpoint()
            logger.info("Konvertiere Audio: %s", params.audio_path)
            progress(0.0, "Konvertiere Audio")
            wav_path = convert_to_wav(
                params.audio_path, effective_output if params.keep_wav else None
            )
            logger.info("WAV erzeugt: %s", wav_path)
            logger.info(
                "Starte Transkription mit whisper.cpp (Sprache=%s, Aufgabe=%s)",
                params.language or "auto",
                params.task,
            )
            progress(0.0, "Transkribiere")
            # Gate zwischen Konvertierung und whisper-cli-Start: Nach der
            # WAV-Erzeugung geklickter Cancel bricht sofort sauber ab,
            # statt erst whisper-cli laufen zu lassen.
            checkpoint()
            result = transcribe(
                wav_path=wav_path,
                model_path=params.model_path,
                language=params.language,
                task=params.task,
                progress_cb=progress,
                segment_cb=partial_segment,
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
            checkpoint()
        progress(95.0, "Speichere")
        review_data = _review_data(
            params,
            speaker_segments,
            wx_speaker_map,
            wx_markers,
            bookmarks,
            wx_embeddings,
            wx_embedding_model,
            wx_runtime_metrics,
        )
        output_paths = write_outputs(
            speaker_segments,
            effective_output,
            params.audio_path.stem,
            params.formats,
            bookmarks or None,
            review_data,
            overwrite=params.colocate,
            marker_data=marker_data if params.backend == "whisperx" else None,
        )
        output_location = output_paths[0].parent if output_paths else effective_output
        logger.info("Ausgabe gespeichert in %s:", output_location)
        for path in output_paths:
            logger.info("  - %s", path)
        # Kein checkpoint() mehr nach write_outputs: Die Ausgaben liegen
        # vollständig auf der Platte, ein „cancelled“ würde die UI den Lauf
        # als ergebnislos anzeigen lassen (ohne output_location), während die
        # Dateien den nächsten Lauf blockieren.
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
    except _JobAborted:
        emit(("cancelled", "Transkription wurde abgebrochen."))
    except Exception as exc:
        # Nutzer-Abbruch geht vor: Auch wenn der abgebrochene Subprozess als
        # Prozessfehler (z.B. SIGTERM -> Exit -15) ankommt, gilt er nicht
        # als Fehler, sondern als sauberer Abbruch.
        if abort_event is not None and abort_event.is_set():
            emit(("cancelled", "Transkription wurde abgebrochen."))
        elif isinstance(exc, (AudioError, MarkerError, TranscriptionError, WhisperXError)):
            emit(("error", str(exc)))
        else:
            emit(("error", f"Unerwarteter Fehler: {exc}"))
    finally:
        # Auch der Abbruch- und der Fehlerpfad müssen die temporäre WAV
        # loswerden; sonst bleiben pro Abbruch hunderte MB in /tmp liegen.
        if wav_path is not None and not params.keep_wav:
            cleanup_wav(wav_path)
        root = logging.getLogger()
        root.removeHandler(handler)
        root.setLevel(previous_level)


def _review_data(
    params: TranscriptionParams,
    segments: list[Any],
    speaker_map: dict[str, str] | None,
    markers: list[SpeakerMarker] | None,
    bookmarks: list[Bookmark],
    speaker_embeddings: dict[str, list[float]] | None = None,
    embedding_model: str | None = None,
    runtime_metrics: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    if params.backend != "whisperx":
        return None
    # Bei der Ersterstellung sind Anzeigenamen noch eindeutig (rohe SPEAKER_XX),
    # die Rückabbildung ist hier also verlustfrei.
    reverse_map = {name: speaker_id for speaker_id, name in (speaker_map or {}).items()}
    review = {
        "schema_version": 3 if speaker_embeddings or runtime_metrics else 2,
        "audio_path": str(params.audio_path),
        "segments": [
            {
                "start": s.start,
                "end": s.end,
                "speaker": s.speaker,
                "speaker_id": reverse_map.get(s.speaker),
                "text": s.text,
            }
            for s in segments
        ],
        "speaker_map": dict(speaker_map or {}),
        "markers": [
            {
                "start": m.start,
                "end": m.end,
                "speaker": m.speaker,
                "speaker_id": reverse_map.get(m.speaker),
            }
            for m in markers or []
        ],
        "bookmarks": [
            {"time": b.time, "label": b.label, "type": b.type, "color": b.color} for b in bookmarks
        ],
        "base_name": params.audio_path.stem,
        "formats": params.formats,
        "run_metadata": {
            "backend": params.backend,
            "model": params.whisperx_model,
            "language": params.language or "auto",
            "diarize": not params.no_diarize,
            "min_speakers": params.min_speakers,
            "max_speakers": params.max_speakers,
            "voice_profiles": params.voice_profiles,
            "performance_profile": params.performance_profile,
        },
    }
    if speaker_embeddings:
        review["speaker_embeddings"] = speaker_embeddings
        review["embedding_model"] = embedding_model
    if runtime_metrics:
        review["runtime_metrics"] = runtime_metrics
    return review

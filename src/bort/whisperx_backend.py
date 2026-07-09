"""whisperX-Backend: automatische Transkription + Sprecher-Diarisierung.

Ruft die whisperX-Pipeline im whisper-tagger-Projekt als Subprocess auf und
wandelt das Ergebnis in das BoRT-Datenmodell um (SpeakerMarker +
Segment). So bleibt die GPU/PyTorch-Abhängigkeit im separaten uv-Projekt
gekapselt, während BoRT schlank bleibt (wie bei whisper.cpp).

Das Backend erzeugt drei Dinge:
- ``segments``: reine Transkriptionssegmente (ohne Sprecher)
- ``markers``: Sprecher-Zeitintervalle (für die Marker-Datei / GUI)
- ``speaker_map``: Mapping Sprecher-ID -> Anzeigename (sprecher001 ...)

Die Marker lassen sich nachträglich editieren (Speaker-Rename in der GUI) und
über den vorhandenen ``MarkerSpeakerResolver`` erneut auflösen.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .markers import SpeakerMarker
from .speakers import Segment

logger = logging.getLogger(__name__)

# Default-Pfade zum whisper-tagger-Projekt (relativ zu Home).
WHISPER_TAGGER_DIR = Path.home() / "projects" / "whisper-tagger"
WHISPER_TAGGER_SCRIPT = WHISPER_TAGGER_DIR / "whisperx_transcribe.py"
WHISPER_TAGGER_RUN = WHISPER_TAGGER_DIR / "run.sh"

# Default-Speaker-Prefix für das sprecherNNN-Labeling.
DEFAULT_SPEAKER_PREFIX = "sprecher"


class WhisperXError(Exception):
    """Fehler im whisperX-Backend."""


@dataclass(frozen=True)
class WhisperXResult:
    """Ergebnis des whisperX-Backends.

    Attributes:
        segments: Transkribierte Segmente (Start, Ende, Text).
        markers: Sprecher-Zeitintervalle (für Marker-Datei / Resolver).
        speaker_map: Mapping Sprecher-ID -> Anzeigename (sprecher001 ...).
        language: Erkannte Sprache.
    """

    segments: list[Segment]
    markers: list[SpeakerMarker]
    speaker_map: dict[str, str]
    language: str | None


def _ensure_backend_available() -> None:
    """Prüft, dass das whisper-tagger-Projekt vorhanden ist."""
    if not WHISPER_TAGGER_RUN.exists() or not WHISPER_TAGGER_SCRIPT.exists():
        raise WhisperXError(
            f"whisperX-Backend nicht gefunden unter {WHISPER_TAGGER_DIR}. "
            "Bitte das whisper-tagger-Projekt einrichten."
        )


def _run_whisperx(
    audio_path: Path,
    language: str | None,
    model_name: str,
    min_speakers: int | None,
    max_speakers: int | None,
    no_diarize: bool = False,
    progress_cb: Callable[[float, str], None] | None = None,
) -> dict:
    """Führt das whisperX-Script aus und gibt das geparste JSON zurück.

    Args:
        progress_cb: Optionaler Callback (percent, phase) für Fortschritt.
    """
    _ensure_backend_available()

    cmd: list[str] = [
        "bash",
        str(WHISPER_TAGGER_RUN),
        "python",
        str(WHISPER_TAGGER_SCRIPT),
        str(audio_path),
        "--model",
        model_name,
        "--out",
        "-",
    ]
    if language:
        cmd.extend(["--language", language])
    if min_speakers is not None:
        cmd.extend(["--min-speakers", str(min_speakers)])
    if max_speakers is not None:
        cmd.extend(["--max-speakers", str(max_speakers)])
    if no_diarize:
        cmd.append("--no-diarize")

    logger.debug("whisperX-Backend Aufruf: %s", " ".join(cmd))

    # stderr streamen und Fortschritt parsen. tqdm nutzt \r; der robuste
    # Stream-Helper splittet auf \r und \n und vermeidet den EOF-Busy-Wait,
    # der früher zum Hängen der GUI ("Initialisiere" bleibend) führte.
    tqdm_re = re.compile(r"(\d+)%\|")
    pct_re = re.compile(r"(\d+(?:\.\d+)?)\s*%")

    def _on_line(line: str) -> None:
        if not progress_cb:
            return
        phase = "Align" if "align" in line.lower() else "Transkribiere"
        m = tqdm_re.search(line)
        if m:
            try:
                progress_cb(float(m.group(1)), phase)
            except ValueError:
                pass
            return
        m = pct_re.search(line)
        if m:
            try:
                progress_cb(float(m.group(1)), "Verarbeite")
            except ValueError:
                pass

    from .streaming import run_stream_progress

    try:
        stdout_data, stderr_data = run_stream_progress(
            cmd,
            on_line=_on_line,
        )
    except RuntimeError as exc:
        raise WhisperXError(str(exc)) from exc

    if proc.returncode != 0:
        raise WhisperXError(
            f"whisperX-Backend Fehler (Code {proc.returncode}):\n"
            f"{stderr_data.strip()}"
        )

    # stdout may contain stray log lines before the JSON document. Find the
    # first '{' and parse from there to be robust against stdout pollution.
    json_start = stdout_data.find("{")
    if json_start < 0:
        raise WhisperXError(
            "whisperX-Backend lieferte kein JSON.\n"
            f"stdout: {stdout_data[:500]}\nstderr: {stderr_data[:500]}"
        )
    json_text = stdout_data[json_start:]

    try:
        return json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise WhisperXError(
            f"whisperX-Backend lieferte ungültiges JSON: {exc}\n"
            f"stdout: {stdout_data[:500]}\nstderr: {stderr_data[:500]}"
        ) from exc


def _build_speaker_map(
    segments: list[dict], prefix: str = DEFAULT_SPEAKER_PREFIX
) -> dict[str, str]:
    """Erzeugt das Mapping Sprecher-ID -> sprecherNNN.

    Die Reihenfolge richtet sich nach dem ersten Auftreten der Sprecher-ID.
    """
    seen: list[str] = []
    for seg in segments:
        spk = seg.get("speaker") or "SPEAKER_UNKNOWN"
        if spk not in seen:
            seen.append(spk)
    return {spk: f"{prefix}{idx + 1:03d}" for idx, spk in enumerate(seen)}


def _to_domain(
    data: dict,
) -> tuple[list[Segment], list[SpeakerMarker], dict[str, str]]:
    """Wandelt das whisperX-JSON in das BoRT-Datenmodell um."""
    raw_segments = data.get("segments", [])
    speaker_map = _build_speaker_map(raw_segments)

    segments: list[Segment] = []
    marker_dicts: list[dict] = []

    for seg in raw_segments:
        start = round(float(seg.get("start", 0.0)), 3)
        end = round(float(seg.get("end", 0.0)), 3)
        text = str(seg.get("text", "")).strip()
        spk = speaker_map[seg.get("speaker") or "SPEAKER_UNKNOWN"]

        if text:
            segments.append(Segment(start=start, end=end, text=text))
        marker_dicts.append({"start": start, "end": end, "speaker": spk})

    # Benachbarte Marker desselben Sprechers zusammenführen (saubere Intervalle)
    merged: list[dict] = []
    for m in marker_dicts:
        if (
            merged
            and merged[-1]["speaker"] == m["speaker"]
            and merged[-1]["end"] >= m["start"]
        ):
            merged[-1]["end"] = max(merged[-1]["end"], m["end"])
        else:
            merged.append(dict(m))

    markers = [
        SpeakerMarker(start=m["start"], end=m["end"], speaker=m["speaker"])
        for m in merged
    ]

    return segments, markers, speaker_map


def transcribe(
    audio_path: Path,
    language: str | None = None,
    model_name: str = "large-v3",
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    no_diarize: bool = False,
    progress_cb: Callable[[float, str], None] | None = None,
) -> WhisperXResult:
    """Transkribiert Audio mit whisperX und erzeugt Marker + Speaker-Map.

    Args:
        audio_path: Pfad zur Audiodatei (MP3, WAV, ...).
        language: Sprache (z.B. 'de') oder None für automatische Erkennung.
        model_name: Whisper-Modellname (z.B. 'large-v3', 'medium', 'small').
        min_speakers: Mindestanzahl Sprecher für Diarisierung.
        max_speakers: Maximalanzahl Sprecher für Diarisierung.
        no_diarize: Sprecher-Diarisierung überspringen (nur Transkription).
        progress_cb: Optionaler Callback (percent, phase) für Fortschritt.

    Returns:
        WhisperXResult mit Segmenten, Markern und Speaker-Map.

    Raises:
        WhisperXError: Bei Backend- oder Parsing-Fehlern.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise WhisperXError(f"Audiodatei nicht gefunden: {audio_path}")

    data = _run_whisperx(
        audio_path, language, model_name, min_speakers, max_speakers,
        no_diarize, progress_cb=progress_cb,
    )
    segments, markers, speaker_map = _to_domain(data)

    logger.info(
        "whisperX-Backend: %d Segmente, %d Sprecher",
        len(segments),
        len(speaker_map),
    )

    return WhisperXResult(
        segments=segments,
        markers=markers,
        speaker_map=speaker_map,
        language=data.get("language"),
    )


def save_markers(result: WhisperXResult, path: Path) -> Path:
    """Schreibt die erzeugten Marker im BoRT-Marker-Format.

    Das Format ist kompatibel zu ``load_markers``: ein JSON-Objekt mit
    ``speakers`` (ID -> Anzeigename) und ``markers`` (Intervalle).

    Args:
        result: Ergebnis des whisperX-Backends.
        path: Zieldatei (z.B. 'audio.markers.json').

    Returns:
        Pfad der geschriebenen Datei.
    """
    path = Path(path)
    doc = {
        "speakers": dict(result.speaker_map),  # id -> sprecherNNN
        "markers": [
            {"start": m.start, "end": m.end, "speaker": m.speaker}
            for m in result.markers
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Marker gespeichert: %s", path)
    return path

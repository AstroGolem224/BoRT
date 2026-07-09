"""whisper.cpp CLI-Wrapper und Transkriptionsparsing."""

import json
import logging
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .speakers import Segment

logger = logging.getLogger(__name__)


class TranscriptionError(Exception):
    """Fehler bei der Transkription."""

    pass


@dataclass(frozen=True)
class TranscriptionResult:
    """Ergebnis einer Transkription."""

    segments: list[Segment]
    language: str | None
    text: str


def _find_whisper_cli() -> Path:
    """Findet das whisper-cli Binary."""
    # 1. Im Projekt-vendor-Verzeichnis suchen
    project_root = Path(__file__).resolve().parents[2]
    vendored = project_root / "vendor" / "whisper.cpp" / "build" / "bin" / "whisper-cli"
    if vendored.exists():
        return vendored

    # 2. Im PATH suchen
    found = shutil.which("whisper-cli")
    if found:
        return Path(found)

    raise TranscriptionError(
        "whisper-cli nicht gefunden. Bitte baue whisper.cpp oder füge es zum PATH hinzu."
    )


def _run_whisper(
    wav_path: Path,
    model_path: Path,
    language: str | None,
    cli_path: Path | None,
    task: str = "transcribe",
    progress_cb: Callable[[float, str], None] | None = None,
) -> dict:
    """Führt whisper-cli aus und gibt das geparste JSON zurück.

    Args:
        progress_cb: Optionaler Callback (percent, phase) für Fortschritt.
    """
    binary = cli_path or _find_whisper_cli()

    if not binary.exists():
        raise TranscriptionError(f"whisper-cli Binary nicht gefunden: {binary}")
    if not model_path.exists():
        raise TranscriptionError(f"Modell-Datei nicht gefunden: {model_path}")

    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "result.json"

        cmd = [
            str(binary),
            "-m",
            str(model_path),
            "-f",
            str(wav_path),
            "--output-json",
            "--output-file",
            str(json_path.with_suffix("")),
            "--print-progress",  # gibt "whisper_print_progress_callback: progress = NNN%" auf stderr
        ]
        # Wichtig: whisper-cli defaultet auf '-l en', daher immer explizit 'auto' setzen,
        # wenn keine Sprache gewählt wurde. Sonst wird nicht-englische Sprache oft
        # automatisch ins Englische übersetzt/verzerrt.
        cmd.extend(["-l", language if language else "auto"])
        if task == "translate":
            cmd.append("--translate")

        logger.debug("whisper-cli Aufruf: %s", " ".join(cmd))

        import re
        from .streaming import run_stream_progress

        progress_re = re.compile(r"progress\s*=\s*(\d+)\s*%")

        def _on_line(line: str) -> None:
            if not progress_cb:
                return
            m = progress_re.search(line)
            if not m:
                return
            try:
                pct = float(m.group(1))
                progress_cb(pct, "Transkribiere")
            except ValueError:
                pass

        try:
            stdout_data, stderr_data = run_stream_progress(
                cmd,
                on_line=_on_line,
            )
        except RuntimeError as exc:
            raise TranscriptionError(str(exc)) from exc

        # whisper-cli erzeugt eine Datei mit Suffix .json
        expected_json = json_path.with_name(json_path.stem + ".json")
        if not expected_json.exists():
            raise TranscriptionError(
                f"whisper-cli hat keine JSON-Ausgabe erzeugt. stderr: {stderr_data}"
            )

        with expected_json.open("r", encoding="utf-8") as f:
            return json.load(f)


def _parse_segments(data: dict) -> list[Segment]:
    """Extrahiert Segmente aus der whisper-cli JSON-Ausgabe."""
    segments: list[Segment] = []
    for raw in data.get("transcription", []):
        if not isinstance(raw, dict):
            continue
        text = raw.get("text", "").strip()
        if not text:
            continue
        segments.append(
            Segment(
                start=float(raw.get("offsets", {}).get("from", 0.0)) / 1000.0,
                end=float(raw.get("offsets", {}).get("to", 0.0)) / 1000.0,
                text=text,
            )
        )
    return segments


def transcribe(
    wav_path: Path,
    model_path: Path,
    language: str | None = None,
    cli_path: Path | None = None,
    task: str = "transcribe",
    progress_cb: Callable[[float, str], None] | None = None,
) -> TranscriptionResult:
    """Transkribiert eine WAV-Datei mit whisper.cpp.

    Args:
        wav_path: Pfad zur 16 kHz mono WAV-Datei.
        model_path: Pfad zum ggml-Modell.
        language: Optionale Sprache (z.B. 'de', 'en').
        cli_path: Optionales whisper-cli Binary (sonst automatisch finden).
        task: 'transcribe' für Originalsprache, 'translate' für Übersetzung nach Englisch.
        progress_cb: Optionaler Callback (percent, phase) für Fortschritt.

    Returns:
        TranscriptionResult mit Segmenten, Sprache und Rohtext.
    """
    if task not in {"transcribe", "translate"}:
        raise ValueError(f"Ungültiger task: {task}. Erlaubt: transcribe, translate")
    data = _run_whisper(
        wav_path, model_path, language, cli_path, task=task, progress_cb=progress_cb
    )
    segments = _parse_segments(data)
    language = data.get("params", {}).get("language") or data.get("result", {}).get("language")
    full_text = " ".join(seg.text for seg in segments)

    return TranscriptionResult(segments=segments, language=language, text=full_text)

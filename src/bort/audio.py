"""Audio-Vorverarbeitung: Audio (mp3/m4a/aac/...) → WAV für whisper.cpp."""

import contextlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from .streaming import register_process, terminate_process_tree, unregister_process

# Von ffmpeg/whisper unterstützte Eingabeformate.
SUPPORTED_AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".wma"}

# Gesamt-Budget für eine ffmpeg-Konvertierung (sehr großzügig für lange Audios).
CONVERT_TIMEOUT = 1800.0


class AudioError(Exception):
    """Fehler bei der Audioverarbeitung."""

    pass


def _check_ffmpeg() -> None:
    """Stellt sicher, dass ffmpeg installiert ist."""
    if shutil.which("ffmpeg") is None:
        raise AudioError("ffmpeg nicht gefunden. Bitte installiere ffmpeg.")


def is_supported_audio(path: Path) -> bool:
    """Prüft, ob die Datei ein unterstütztes Audio-Format hat."""
    return Path(path).suffix.lower() in SUPPORTED_AUDIO_EXTS


def convert_to_wav(audio_path: Path, output_dir: Path | None = None) -> Path:
    """Konvertiert eine Audiodatei in ein whisper-kompatibles WAV (16 kHz, mono, s16).

    Unterstützt alle Formate, die ffmpeg lesen kann (mp3, m4a, aac, wav, flac,
    ogg, opus, wma). Der Container (z.B. m4a/aac) wird von ffmpeg automatisch
    erkannt, eine explizite Format-Angabe ist nicht nötig.

    Args:
        audio_path: Pfad zur Eingabedatei (mp3, m4a, aac, ...).
        output_dir: Optionales Zielverzeichnis. Wenn None, wird eine temporäre
            Datei erzeugt.

    Returns:
        Pfad zur erzeugten WAV-Datei.

    Raises:
        AudioError: Bei ffmpeg-Fehlern oder nicht unterstütztem Format.
    """
    _check_ffmpeg()

    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise AudioError(f"Audiodatei nicht gefunden: {audio_path}")

    if not is_supported_audio(audio_path):
        raise AudioError(
            f"Nicht unterstütztes Audio-Format: {audio_path.suffix or '(keine Endung)'}. "
            f"Unterstützt: {', '.join(sorted(SUPPORTED_AUDIO_EXTS))}"
        )

    owned_dir: Path | None = None
    if output_dir is None:
        # Eigener 0700-Ordner je Lauf: ein fester Name in /tmp wäre für jeden
        # lokalen Nutzer lesbar und ließe sich vorab blockieren.
        output_dir = owned_dir = Path(tempfile.mkdtemp(prefix="bort-wav-"))
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    wav_path = output_dir / f"{audio_path.stem}_16k_mono.wav"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(audio_path),
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(wav_path),
    ]

    # Scheitert die Konvertierung (ffmpeg fehlt, Timeout, SIGTERM vom
    # Batch-Abbruch), räumt sie den selbst angelegten mkdtemp-Ordner samt
    # halber WAV wieder weg. Ein vom Aufrufer übergebenes output_dir bleibt
    # unangetastet.
    try:
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except OSError as exc:
            raise AudioError(f"ffmpeg konnte nicht gestartet werden: {exc}") from exc
        if not register_process(process):
            terminate_process_tree(process)
            raise AudioError("Audio-Konvertierung wurde abgebrochen.")
        try:
            try:
                _stdout_text, stderr_text = process.communicate(timeout=CONVERT_TIMEOUT)
            except subprocess.TimeoutExpired:
                terminate_process_tree(process)
                _stdout_text, stderr_text = process.communicate()
                raise AudioError(
                    f"ffmpeg Zeitüberschreitung nach {CONVERT_TIMEOUT:g}s "
                    "bei der Audio-Konvertierung."
                )
        finally:
            unregister_process(process)

        if process.returncode != 0:
            raise AudioError(f"ffmpeg Fehler: {stderr_text}")
    except BaseException:
        if owned_dir is not None:
            shutil.rmtree(owned_dir, ignore_errors=True)
        raise

    return wav_path


def cleanup_wav(wav_path: Path) -> None:
    """Löscht eine temporäre WAV-Datei samt ihres leeren mkdtemp-Ordners."""
    Path(wav_path).unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        # rmdir entfernt nur den leeren Ordner; ein vom Nutzer gewähltes
        # Zielverzeichnis (keep_wav) bleibt damit unangetastet.
        Path(wav_path).parent.rmdir()

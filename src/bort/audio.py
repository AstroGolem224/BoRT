"""Audio-Vorverarbeitung: Audio (mp3/m4a/aac/...) → WAV für whisper.cpp."""

import shutil
import subprocess
import tempfile
from pathlib import Path

# Von ffmpeg/whisper unterstützte Eingabeformate.
SUPPORTED_AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".wma"}


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

    if output_dir is None:
        output_dir = Path(tempfile.gettempdir())
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

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise AudioError(f"ffmpeg Fehler: {result.stderr}")

    return wav_path

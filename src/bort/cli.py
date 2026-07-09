"""Kommandozeilen-Interface für die Transkriptions-App."""

import argparse
import logging
import sys
from pathlib import Path

from .audio import SUPPORTED_AUDIO_EXTS, AudioError, convert_to_wav, is_supported_audio
from .markers import MarkerError, load_bookmarks, load_markers
from .speakers import MarkerSpeakerResolver, PlaceholderSpeakerResolver
from .transcription import TranscriptionError
from .transcription import transcribe as transcribe_whispercpp
from .whisperx_backend import (
    WhisperXError,
    save_markers,
)
from .whisperx_backend import (
    transcribe as transcribe_whisperx,
)
from .writers import write_outputs

logger = logging.getLogger(__name__)

DEFAULT_FORMATS = ["txt", "md", "csv", "tsv"]
DEFAULT_WHISPERX_MODEL = "large-v3"


def _positive_int(value: str) -> int:
    try:
        ivalue = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Ganzzahl erwartet: {value}") from exc
    if ivalue < 1:
        raise argparse.ArgumentTypeError("Wert muss >= 1 sein.")
    return ivalue


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="transcribe",
        description=(
            "Transkribiert Audio mit whisper.cpp oder whisperX inkl. "
            "Zeitstempel und Sprecher."
        ),
    )
    parser.add_argument(
        "audio",
        type=Path,
        help="Pfad zur Audiodatei (mp3, m4a, aac, wav, flac, ogg, opus, wma)",
    )
    parser.add_argument("--markers", "-m", type=Path, help="Pfad zur JSON-Marker-Datei")
    parser.add_argument(
        "--backend",
        "-b",
        choices=["whispercpp", "whisperx"],
        default="whispercpp",
        help=(
            "Transkriptions-Backend: whispercpp (Default) oder "
            "whisperX (GPU + Diarization)"
        ),
    )
    parser.add_argument(
        "--model",
        "-M",
        type=str,
        default=None,
        help=(
            "Modell: Pfad zum ggml-Modell (whispercpp) oder "
            "Whisper-Modellname wie 'large-v3' (whisperX)"
        ),
    )
    parser.add_argument(
        "--language",
        "-l",
        type=str,
        default=None,
        help="Sprache (z.B. de, en). Default: auto (automatisch erkennen)",
    )
    parser.add_argument(
        "--task",
        "-t",
        type=str,
        choices=["transcribe", "translate"],
        default="transcribe",
        help="Aufgabe: transcribe (Originalsprache) oder translate (nach Englisch)",
    )
    parser.add_argument(
        "--output-dir", "-o", type=Path, default=Path("."), help="Ausgabeverzeichnis"
    )
    parser.add_argument(
        "--formats",
        "-f",
        type=str,
        default=",".join(DEFAULT_FORMATS),
        help="Kommaseparierte Ausgabeformate: txt,md,csv,tsv",
    )
    parser.add_argument(
        "--whisper-cli", type=Path, default=None, help="Pfad zum whisper-cli Binary (whispercpp)"
    )
    parser.add_argument(
        "--min-speakers",
        type=int,
        default=None,
        help="Mindestanzahl Sprecher (nur whisperX)",
    )
    parser.add_argument(
        "--max-speakers",
        type=int,
        default=None,
        help="Maximalanzahl Sprecher (nur whisperX)",
    )
    parser.add_argument(
        "--no-diarize",
        action="store_true",
        help="Sprecher-Diarisierung überspringen (nur whisperX)",
    )
    parser.add_argument(
        "--auto-markers",
        action="store_true",
        help="Automatisch erzeugte Marker nutzen und speichern (nur whisperX)",
    )
    parser.add_argument(
        "--keep-wav", action="store_true", help="Temporäre WAV-Datei behalten"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Detaillierte Ausgaben"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    formats = [fmt.strip() for fmt in args.formats.split(",") if fmt.strip()]

    if not is_supported_audio(args.audio):
        logger.error(
            "Nicht unterstütztes Audio-Format: %s. Unterstützt: %s",
            args.audio.suffix or "(keine Endung)",
            ", ".join(sorted(SUPPORTED_AUDIO_EXTS)),
        )
        return 1

    # Bookmarks aus Android-Marker-Datei laden (optional)
    bookmarks = []
    if args.markers:
        try:
            bookmarks = load_bookmarks(args.markers)
            logger.info("Bookmarks geladen: %d aus %s", len(bookmarks), args.markers)
        except MarkerError as exc:
            # Kein Android-Format → als Speaker-Marker behandeln (weiter unten)
            logger.debug("Marker-Datei ist kein Bookmark-Format: %s", exc)
            bookmarks = []

    try:
        # --- Backend-Verzweigung ---
        if args.backend == "whisperx":
            logger.info("Starte Transkription mit whisperX (GPU + Diarization)")
            wx_model = args.model or DEFAULT_WHISPERX_MODEL
            wx_result = transcribe_whisperx(
                audio_path=args.audio,
                language=args.language,
                model_name=wx_model,
                min_speakers=args.min_speakers,
                max_speakers=args.max_speakers,
                no_diarize=args.no_diarize,
            )
            logger.info(
                "Transkription abgeschlossen (%d Segmente, %d Sprecher).",
                len(wx_result.segments),
                len(wx_result.speaker_map),
            )

            # Marker-Datei optional speichern (für GUI-Editierung)
            if args.auto_markers:
                marker_path = args.output_dir / f"{args.audio.stem}.markers.json"
                save_markers(wx_result, marker_path)
                logger.info("Auto-Marker gespeichert: %s", marker_path)

            # Sprecher auflösen über die intern erzeugten Marker
            resolver = MarkerSpeakerResolver(
                markers=wx_result.markers,
                speaker_map=wx_result.speaker_map,
            )
            speaker_segments = resolver.resolve(wx_result.segments)

        else:  # whispercpp (ursprünglicher Pfad)
            if not args.model:
                logger.error("--model ist für whispercpp-Backend erforderlich.")
                return 1
            logger.info("Konvertiere Audio: %s", args.audio)
            wav_dir = args.output_dir if args.keep_wav else None
            wav_path = convert_to_wav(args.audio, output_dir=wav_dir)
            logger.info("WAV erzeugt: %s", wav_path)

            logger.info("Starte Transkription mit whisper.cpp")
            result = transcribe_whispercpp(
                wav_path=wav_path,
                model_path=Path(args.model),
                language=args.language,
                cli_path=args.whisper_cli,
                task=args.task,
            )
            logger.info("Transkription abgeschlossen (%d Segmente).", len(result.segments))

            if args.markers:
                logger.info("Lade Marker-Datei: %s", args.markers)
                speaker_map, markers = load_markers(args.markers)
                resolver = MarkerSpeakerResolver(markers, speaker_map)
            else:
                logger.info("Keine Marker-Datei angegeben – verwende Fallback-Sprecher.")
                resolver = PlaceholderSpeakerResolver()

            speaker_segments = resolver.resolve(result.segments)

        # --- Ausgabe ---
        output_paths = write_outputs(
            segments=speaker_segments,
            output_dir=args.output_dir,
            base_name=args.audio.stem,
            formats=formats,
            bookmarks=bookmarks or None,
        )

        output_location = output_paths[0].parent if output_paths else args.output_dir
        logger.info("Ausgabe gespeichert in %s:", output_location)
        for path in output_paths:
            logger.info("  - %s", path)

        if args.backend == "whispercpp" and not args.keep_wav:
            logger.debug("Lösche temporäre WAV-Datei: %s", wav_path)
            wav_path.unlink(missing_ok=True)

    except (
        AudioError,
        MarkerError,
        TranscriptionError,
        WhisperXError,
    ) as exc:
        logger.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        logger.info("Abgebrochen.")
        return 130

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Audio-Wiedergabe ohne Abhängigkeit von einer UI."""

from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

from ..streaming import terminate_process_tree


class PlaybackError(Exception):
    """Ungültige oder nicht mögliche Wiedergabe."""


class AudioPlayer:
    """Spielt Audio-Intervalle via ffplay als Subprocess ab."""

    def __init__(self, audio_path: Path) -> None:
        self.audio_path = audio_path
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()

    def play_segment(self, start: float, end: float) -> None:
        if start < 0 or start >= end:
            raise PlaybackError("Ungültiger Wiedergabebereich: 0 <= start < end erforderlich.")
        if shutil.which("ffplay") is None:
            raise PlaybackError("ffplay wurde nicht gefunden. Bitte FFmpeg installieren.")
        self.stop()
        with self._lock:
            self._process = subprocess.Popen(
                [
                    "ffplay",
                    "-nodisp",
                    "-nostats",
                    "-loglevel",
                    "quiet",
                    "-ss",
                    f"{start:.3f}",
                    "-t",
                    f"{end - start:.3f}",
                    "-autoexit",
                    str(self.audio_path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

    def stop(self) -> None:
        with self._lock:
            if self._process is not None:
                terminate_process_tree(self._process, grace=2.0)
                self._process = None

    def is_playing(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

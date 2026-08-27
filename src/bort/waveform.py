"""Speicherschonende Waveform-Extraktion mit ffmpeg."""

from __future__ import annotations

import math
import subprocess
import sys
import threading
from array import array
from collections import deque
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from .streaming import terminate_process_tree

SAMPLE_RATE = 8000
SAMPLES_PER_BUCKET = 4000
MAX_BUCKETS = 4000
STDERR_LIMIT = 4096
PROBE_TIMEOUT = 5.0


class WaveformError(Exception):
    """Fehler beim Erzeugen einer Waveform."""


def _merge_bucket_pairs(
    buckets: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Fasst benachbarte Min-/Max-Buckets zusammen."""
    merged: list[tuple[float, float]] = []
    for index in range(0, len(buckets), 2):
        pair = buckets[index : index + 2]
        merged.append((min(item[0] for item in pair), max(item[1] for item in pair)))
    return merged


def reduce_peaks(
    pcm_chunks: Iterable[bytes],
    samples_per_bucket: int = SAMPLES_PER_BUCKET,
    max_buckets: int = MAX_BUCKETS,
) -> list[list[float]]:
    """Reduziert little-endian-s16-PCM hierarchisch auf normalisierte Peaks.

    Unvollständige Samples an Chunk-Grenzen werden gepuffert. Sobald die
    maximale Bucket-Zahl erreicht ist, werden Nachbar-Buckets zusammengelegt
    und die zeitliche Bucket-Breite verdoppelt.
    """
    if samples_per_bucket < 1 or max_buckets < 2:
        raise ValueError("Bucket-Größen müssen positiv sein.")

    buckets: list[tuple[float, float]] = []
    target = samples_per_bucket
    count = 0
    minimum = 32767
    maximum = -32768
    remainder = b""

    def finish_bucket() -> None:
        nonlocal buckets, target, count, minimum, maximum
        buckets.append((minimum / 32768.0, maximum / 32768.0))
        count = 0
        minimum = 32767
        maximum = -32768
        if len(buckets) >= max_buckets:
            buckets = _merge_bucket_pairs(buckets)
            target *= 2

    for chunk in pcm_chunks:
        if not chunk:
            continue
        data = remainder + bytes(chunk)
        usable = len(data) - (len(data) % 2)
        remainder = data[usable:]
        if not usable:
            continue
        samples = array("h")
        samples.frombytes(data[:usable])
        if sys.byteorder != "little":
            samples.byteswap()
        for sample in samples:
            minimum = min(minimum, sample)
            maximum = max(maximum, sample)
            count += 1
            if count == target:
                finish_bucket()

    if count:
        finish_bucket()
    return [[low, high] for low, high in buckets]


def terminate_process(
    process: subprocess.Popen[bytes],
    lock: threading.Lock | threading.RLock | None = None,
) -> None:
    """Beendet einen Waveform-Prozess idempotent über die Prozessgruppe."""
    process_lock = lock or threading.RLock()
    with process_lock:
        terminate_process_tree(process)


def _probe_duration(audio_path: Path) -> float | None:
    """Ermittelt die Dauer best-effort für die Watchdog-Planung."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=PROBE_TIMEOUT,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    durations: list[float] = []
    for line in result.stdout.splitlines():
        try:
            value = float(line.strip())
        except ValueError:
            continue
        if math.isfinite(value) and value > 0:
            durations.append(value)
    return max(durations, default=None)


def _deadline_for(duration: float | None) -> float:
    """Berechnet das Watchdog-Limit aus der best-effort ermittelten Dauer."""
    if duration is None:
        return 600.0
    return min(60.0 + 2.0 * duration / 60.0, 600.0)


def _drain_stderr(stream: Any, tail: deque[bytes]) -> None:
    """Leert stderr vollständig und behält nur das Diagnose-Ende."""
    while True:
        chunk = stream.read(1024)
        if not chunk:
            return
        tail.append(bytes(chunk))
        while sum(map(len, tail)) > STDERR_LIMIT:
            excess = sum(map(len, tail)) - STDERR_LIMIT
            first = tail.popleft()
            if len(first) > excess:
                tail.appendleft(first[excess:])


def extract_peaks(
    audio_path: Path,
    *,
    register_process: Callable[
        [subprocess.Popen[bytes], threading.RLock], bool
    ]
    | None = None,
    unregister_process: Callable[[subprocess.Popen[bytes]], None] | None = None,
) -> tuple[float, list[list[float]]]:
    """Dekodiert Audio per ffmpeg und liefert PCM-Dauer sowie Peak-Paare."""
    path = Path(audio_path)
    if not path.is_file():
        raise WaveformError(f"Audiodatei nicht gefunden: {path}")

    probe_duration = _probe_duration(path)
    command = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-f",
        "s16le",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-",
    ]
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except (FileNotFoundError, OSError) as exc:
        raise WaveformError("ffmpeg nicht gefunden oder konnte nicht gestartet werden.") from exc

    process_lock = threading.RLock()
    timed_out = threading.Event()
    stdout_result: list[list[list[float]]] = []
    stdout_error: list[BaseException] = []
    stderr_tail: deque[bytes] = deque()
    decoded_bytes = 0

    def read_stdout() -> None:
        nonlocal decoded_bytes
        try:
            assert process.stdout is not None
            def pcm_chunks() -> Iterable[bytes]:
                nonlocal decoded_bytes
                while True:
                    chunk = process.stdout.read(65536)
                    if not chunk:
                        return
                    decoded_bytes += len(chunk)
                    yield chunk

            chunks = pcm_chunks()
            stdout_result.append(reduce_peaks(chunks))
        except BaseException as exc:  # Thread-Grenze: Fehler an Aufrufer weiterreichen.
            stdout_error.append(exc)

    def watchdog_expired() -> None:
        timed_out.set()
        terminate_process(process, process_lock)

    registered = False
    watchdog = threading.Timer(_deadline_for(probe_duration), watchdog_expired)
    watchdog.daemon = True
    stdout_thread = threading.Thread(
        target=read_stdout, daemon=True, name="bort-waveform-stdout"
    )
    assert process.stderr is not None
    stderr_thread = threading.Thread(
        target=_drain_stderr,
        args=(process.stderr, stderr_tail),
        daemon=True,
        name="bort-waveform-stderr",
    )
    try:
        if register_process is not None:
            registered = register_process(process, process_lock)
            if not registered:
                terminate_process(process, process_lock)
                raise WaveformError("Waveform-Extraktion wurde beim Fensterschluss abgebrochen.")
        stdout_thread.start()
        stderr_thread.start()
        watchdog.start()
        returncode = process.wait()
        stdout_thread.join()
        stderr_thread.join()
        if timed_out.is_set():
            raise WaveformError("Zeitüberschreitung bei der Waveform-Extraktion.")
        if stdout_error:
            raise WaveformError(f"PCM-Daten konnten nicht gelesen werden: {stdout_error[0]}")
        if returncode != 0:
            error = b"".join(stderr_tail).decode("utf-8", errors="replace").strip()
            suffix = f": {error}" if error else ""
            raise WaveformError(f"ffmpeg konnte die Audiodatei nicht dekodieren{suffix}")
        peaks = stdout_result[0] if stdout_result else []
        duration = (decoded_bytes // 2) / SAMPLE_RATE
        return duration, peaks
    finally:
        watchdog.cancel()
        terminate_process(process, process_lock)
        if registered and unregister_process is not None:
            unregister_process(process)

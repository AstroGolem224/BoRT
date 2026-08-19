"""Robuster Subprocess-Streamer für Live-Fortschritt.

Löst das Problem, dass ``select``+``os.read`` EOF-FDs endlos wieder als
"readable" meldet (Busy-Wait / Deadlock), sobald der Subprocess endet.
Dieser Helfer entfernt EOF-Pipes aus dem select-Set und bricht erst ab,
wenn der Prozess beendet *und* beide Pipes vollständig gelesen sind.

Der vorherige Code machte bei EOF nur ``continue`` ohne das fd zu entfernen,
wodurch ``select`` die geschlossene Pipe sofort wieder als readable meldete
und die Schleife nie zur Abbruchbedingung kam. Im Worker-Thread lief das
als Endlos-Schleife, während der Subprocess verwaist weiterlief – die GUI
blieb beim Status "Initialisiere" stehen, obwohl die GPU rechnete.
"""

from __future__ import annotations

import fcntl
import logging
import os
import select
import subprocess
from collections.abc import Mapping
from typing import Callable

logger = logging.getLogger(__name__)


def run_stream_progress(
    cmd: list[str],
    *,
    on_line: Callable[[str], None] | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Führt ``cmd`` aus, streamt stderr und ruft ``on_line`` pro Zeile auf.

    stderr wird zeilenweise verarbeitet, wobei ``\\r`` (tqdm) und ``\\n``
    als Zeilenumbruch zählen – wichtig für Live-Fortschrittsbalken.

    Args:
        cmd: Kommandoliste.
        on_line: Callback, das jede fertige stderr-Zeile (stripped) erhält.
            Darf ``None`` sein.
        env: Optionale Prozessumgebung. Wird unverändert an ``Popen`` gegeben.

    Returns:
        Tuple (stdout_text, stderr_text).

    Raises:
        RuntimeError: Wenn der Prozess mit Exit-Code != 0 endet.
    """
    logger.debug("Stream-Kommando: %s", " ".join(cmd))

    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        env=env,
    ) as proc:
        assert proc.stdout is not None
        assert proc.stderr is not None

        stdout_fd = proc.stdout.fileno()
        stderr_fd = proc.stderr.fileno()

        # stdout non-blocking: das Ergebnis (z.B. JSON) kommt erst am Ende.
        fl = fcntl.fcntl(stdout_fd, fcntl.F_GETFL)
        fcntl.fcntl(stdout_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

        watched = {stdout_fd, stderr_fd}
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        line_buf = ""

        def _feed_stderr(data: bytes) -> None:
            nonlocal line_buf
            if not on_line:
                return
            for ch in data.decode("utf-8", errors="replace"):
                if ch in ("\r", "\n"):
                    line = line_buf.strip()
                    line_buf = ""
                    if line:
                        on_line(line)
                else:
                    line_buf += ch

        while True:
            if not watched:
                # Beide Pipes EOF – nur noch auf Prozessende warten.
                if proc.poll() is not None:
                    break
                select.select([], [], [], 0.05)
                continue

            rlist, _, _ = select.select(list(watched), [], [], 0.1)
            for fd in rlist:
                try:
                    chunk = os.read(fd, 4096)
                except BlockingIOError:
                    continue
                except OSError:
                    # Pipe geschlossen.
                    watched.discard(fd)
                    continue
                if not chunk:
                    # EOF: fd aus dem Set nehmen, sonst Busy-Loop.
                    watched.discard(fd)
                    continue
                if fd == stdout_fd:
                    stdout_chunks.append(chunk)
                else:
                    stderr_chunks.append(chunk)
                    _feed_stderr(chunk)

        proc.wait()

        # Rest-Flush verbleibender Puffer nach Prozessende.
        for fd_name, fd, sink in (
            ("stdout", stdout_fd, stdout_chunks),
            ("stderr", stderr_fd, stderr_chunks),
        ):
            if fd in watched:
                try:
                    while True:
                        chunk = os.read(fd, 4096)
                        if not chunk:
                            break
                        sink.append(chunk)
                        if fd_name == "stderr":
                            _feed_stderr(chunk)
                except (BlockingIOError, OSError):
                    pass

        # Letzte unvollständige Zeile flushen.
        if on_line and line_buf.strip():
            on_line(line_buf.strip())

        stdout_data = b"".join(stdout_chunks).decode("utf-8", errors="replace")
        stderr_data = b"".join(stderr_chunks).decode("utf-8", errors="replace")

    if proc.returncode != 0:
        raise RuntimeError(
            f"Prozessfehler (Code {proc.returncode}):\n{stderr_data.strip()}"
        )

    return stdout_data, stderr_data

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
import signal
import subprocess
import threading
import time
from collections.abc import Mapping
from typing import Callable

logger = logging.getLogger(__name__)

# Abbruch-Registry: Beim Fensterschluss werden alle aktiven Streaming-Prozesse
# über ihre (beim Start ermittelte) Prozessgruppe beendet; Starts nach dem
# Abbruch laufen ins Leere.
_processes: dict[subprocess.Popen, int | None] = {}
_processes_lock = threading.Lock()
_cancel_requested = threading.Event()


def terminate_process_tree(
    proc: subprocess.Popen,
    grace: float = 5.0,
    *,
    signal_exited_group: bool = False,
    pgid: int | None = None,
) -> None:
    """Beendet einen Prozess mitsamt Prozessgruppe: SIGTERM, nach Frist SIGKILL.

    Erwartet, dass der Prozess mit ``start_new_session=True`` gestartet wurde,
    damit die Gruppe nicht den Aufrufer selbst erwischt. Läuft unabhängig von
    der Leseschleife in ``run_stream_progress`` und ist idempotent.

    Args:
        grace: Frist in Sekunden zwischen SIGTERM und SIGKILL.
        signal_exited_group: Signalisiert auch die Prozessgruppe eines bereits
            beendeten Prozesses. Das erwischt Enkelkinder, die nach dem
            Child-Exit noch die Pipes offenhält (gleiche Gruppe wegen
            ``start_new_session=True``).
        pgid: Prozessgruppen-ID, die direkt nach dem Start ermittelt wurde
            (Kind lebt dort zuverlässig). Ohne Angabe wird sie nachträglich
            über ``proc.pid`` geraten – nach dem Ernten könnte die PID
            bereits recycelt sein.
    """
    exited = proc.poll() is not None
    if exited and not signal_exited_group:
        return
    if pgid is None:
        try:
            pgid = os.getpgid(proc.pid)
        except OSError:
            # Bereits beendeter (geernteter) Prozess: Die Gruppe ist nur noch
            # über die bekannte Leader-PID ansprechbar (start_new_session =>
            # pgid == pid).
            pgid = proc.pid if exited else None
    if pgid is not None and pgid != proc.pid:
        # Prozess teilt sich die Gruppe mit anderen (z.B. ohne
        # start_new_session gestartet) – killpg könnte den Aufrufer selbst
        # treffen, also nur den Prozess direkt signalisieren.
        pgid = None

    def _signal_group(sig: int) -> None:
        if pgid is None:
            try:
                proc.send_signal(sig)
            except OSError:
                pass
        else:
            try:
                os.killpg(pgid, sig)
            except OSError:
                pass

    _signal_group(signal.SIGTERM)
    try:
        proc.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    if proc.poll() is not None:
        return
    _signal_group(signal.SIGKILL)
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass


def register_process(
    proc: subprocess.Popen, pgid: int | None = None
) -> bool:
    """Nimmt einen Prozess in die Abbruch-Registry auf (Fensterschluss).

    Ohne übergebene ``pgid`` wird sie hier ermittelt – registriert wird
    direkt nach dem Start, das Kind lebt dann noch zuverlässig.
    """
    with _processes_lock:
        if _cancel_requested.is_set():
            return False
        if pgid is None:
            try:
                pgid = os.getpgid(proc.pid)
            except OSError:
                pgid = None
        _processes[proc] = pgid
        return True


def unregister_process(proc: subprocess.Popen) -> None:
    """Entfernt einen beendeten Prozess aus der Abbruch-Registry."""
    with _processes_lock:
        _processes.pop(proc, None)


def terminate_registered_processes(grace: float = 1.0) -> None:
    """Beendet alle registrierten Prozesse via killpg, ohne Starts zu sperren.

    Anders als :func:`cancel_all_streams` setzt ``_cancel_requested`` nicht:
    Nutzer-initiierter Job-Abbruch darf künftige Transkriptionsstarts nicht
    blockieren. Die Grace-Frist hält den Aufrufer wie beim Fensterschluss
    kurz anstatt lange zu blockieren.
    """
    with _processes_lock:
        processes = list(_processes.items())
    for proc, pgid in processes:
        terminate_process_tree(proc, grace=grace, pgid=pgid)


def cancel_all_streams() -> None:
    """Bricht aktive Streaming-Prozesse ab und blockiert künftige Starts.

    Läuft im GUI-Main-Thread (Fensterschluss); die kurze Grace-Frist hält den
    worst case pro Prozess auf ~2 s statt ~10 s, damit das Fenster nicht
    einfriert.
    """
    _cancel_requested.set()
    terminate_registered_processes(grace=1.0)


def run_stream_progress(
    cmd: list[str],
    *,
    on_line: Callable[[str], None] | None = None,
    env: Mapping[str, str] | None = None,
    idle_timeout: float = 900.0,
    eof_grace: float = 10.0,
    on_stdout_line: Callable[[str], None] | None = None,
) -> tuple[str, str]:
    """Führt ``cmd`` aus, streamt stderr und ruft ``on_line`` pro Zeile auf.

    stderr wird zeilenweise verarbeitet, wobei ``\\r`` (tqdm) und ``\\n``
    als Zeilenumbruch zählen – wichtig für Live-Fortschrittsbalken.

    Args:
        cmd: Kommandoliste.
        on_line: Callback, das jede fertige stderr-Zeile (stripped) erhält.
            Darf ``None`` sein.
        env: Optionale Prozessumgebung. Wird unverändert an ``Popen`` gegeben.
        idle_timeout: Sekunden ohne neue Ausgabe (stdout/stderr), nach denen
            der Prozessbaum beendet wird. Solange Ausgabe ankommt, läuft der
            Prozess unbegrenzt.
        eof_grace: Karenz in Sekunden nach Child-Exit, bis die Ausgabe-Pipes
            EOF geliefert haben. Hält ein Enkelkind die Pipes länger offen
            (z.B. ``bash -c "sleep 30 & exit 0"``), eskaliert die Schleife
            zweistufig: SIGTERM an die Prozessgruppe nach ``eof_grace``
            Sekunden, SIGKILL nach weiteren ``eof_grace`` Sekunden (also
            ``2*eof_grace`` nach Child-Exit) statt endlos auf EOF zu warten.
        on_stdout_line: Optionaler Callback für fertige stdout-Zeilen
            (z.B. fertig transkribierte Segmente von whisper-cli); der
            gesammelte stdout-Text bleibt unverändert vollständig.

    Returns:
        Tuple (stdout_text, stderr_text).

    Raises:
        RuntimeError: Wenn der Prozess mit Exit-Code != 0 endet, nach
            ``idle_timeout`` Sekunden Stille abgebrochen wird oder die Pipes
            auch nach erzwungener Beendigung der Prozessgruppe offen bleiben.
    """
    logger.debug("Stream-Kommando: %s", " ".join(cmd))

    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        env=env,
        # Eigene Prozessgruppe, damit terminate_process_tree beim Abbruch auch
        # Kind-Prozesse (bash -> python -> CUDA-Worker) erwischt.
        start_new_session=True,
    ) as proc:
        # pgid direkt nach dem Start ermitteln: Solange das Kind nicht geerntet
        # ist, kann seine PID nicht recycelt werden – das spätere Raten über
        # proc.pid (siehe terminate_process_tree) entfällt damit.
        try:
            pgid = os.getpgid(proc.pid)
        except OSError:
            pgid = None
        if pgid is not None and pgid != proc.pid:
            # Defensive: Ohne eigene Sitzung teilt der Prozess die Gruppe mit
            # dem Aufrufer – killpg würde uns selbst treffen.
            pgid = None
        if not register_process(proc, pgid):
            terminate_process_tree(proc, pgid=pgid)
            raise RuntimeError("Prozessstart wurde abgebrochen (App wird beendet).")
        try:
            return _stream_process_output(
                proc, cmd, on_line, idle_timeout, eof_grace, pgid, on_stdout_line
            )
        finally:
            unregister_process(proc)


def _stream_process_output(
    proc: subprocess.Popen,
    cmd: list[str],
    on_line: Callable[[str], None] | None,
    idle_timeout: float,
    eof_grace: float,
    pgid: int | None,
    on_stdout_line: Callable[[str], None] | None = None,
) -> tuple[str, str]:
    """Liest beide Pipes bis Prozessende; bricht bei Stille nach Frist ab."""
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
    line_buf = bytearray()
    stdout_buf = bytearray()
    last_output = time.monotonic()
    # Zeitpunkt des Child-Exits bzw. des SIGTERMs an die Prozessgruppe; nach
    # beendetem Child wird die EOF-Karenz (eof_grace) durchgesetzt, damit ein
    # Enkelkind, das die Pipes offenhält, die Leseschleife nicht blockiert.
    child_exited_at: float | None = None
    group_terminated_at: float | None = None

    def _drain_lines(buffer: bytearray, emit_line: Callable[[str], None]) -> None:
        # Erst am Zeilenende dekodieren: Eine über die 4-KB-Chunks verteilte
        # UTF-8-Sequenz ist bis dahin wieder heil statt als U+FFFD zu landen.
        while True:
            ends = [index for index in (buffer.find(b"\r"), buffer.find(b"\n")) if index != -1]
            if not ends:
                return
            cut = min(ends)
            line = bytes(buffer[:cut]).decode("utf-8", errors="replace").strip()
            del buffer[: cut + 1]
            if line:
                emit_line(line)

    def _feed_stderr(data: bytes) -> None:
        if not on_line:
            return
        line_buf.extend(data)
        _drain_lines(line_buf, on_line)

    def _feed_stdout(data: bytes) -> None:
        if not on_stdout_line:
            return
        stdout_buf.extend(data)
        _drain_lines(stdout_buf, on_stdout_line)

    while True:
        now = time.monotonic()
        if proc.poll() is None:
            # Idle-Watchdog: nur beenden, wenn der Prozess still ist UND lebt.
            if now - last_output > idle_timeout:
                terminate_process_tree(proc, pgid=pgid)
                raise RuntimeError(
                    f"Prozess nach {idle_timeout:.0f}s ohne Ausgabe abgebrochen: {cmd[0]}"
                )
        elif child_exited_at is None:
            child_exited_at = now
        elif watched and now - child_exited_at > eof_grace:
            # Child ist beendet, aber ein Enkelkind hält die Pipes offen.
            # Nach der Karenz die Prozessgruppe beenden (start_new_session
            # teilt sie mit dem Enkelkind); hilft auch SIGTERM nicht mehr,
            # folgt SIGKILL und Abbruch statt endlosem Warten auf EOF.
            if group_terminated_at is None:
                group_terminated_at = now
                terminate_process_tree(proc, signal_exited_group=True, pgid=pgid)
            elif now - group_terminated_at > eof_grace:
                # SIGKILL über die beim Start ermittelte pgid (nicht blinding
                # über proc.pid, dessen PID inzwischen recycelt sein könnte).
                if pgid is not None:
                    try:
                        os.killpg(pgid, signal.SIGKILL)
                    except OSError:
                        pass
                raise RuntimeError(
                    f"Ausgabe blieb {now - child_exited_at:.1f}s nach Prozessende "
                    f"offen und wurde erzwungen beendet: {cmd[0]}"
                )
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
            last_output = time.monotonic()
            if fd == stdout_fd:
                stdout_chunks.append(chunk)
                _feed_stdout(chunk)
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
                    else:
                        _feed_stdout(chunk)
            except (BlockingIOError, OSError):
                pass

    # Letzte unvollständige Zeile flushen; der Restpuffer ist nach dem
    # zeilenweisen Puffern eine heile UTF-8-Sequenz.
    if on_line:
        rest = line_buf.decode("utf-8", errors="replace").strip()
        if rest:
            on_line(rest)
    if on_stdout_line:
        rest = stdout_buf.decode("utf-8", errors="replace").strip()
        if rest:
            on_stdout_line(rest)

    stdout_data = b"".join(stdout_chunks).decode("utf-8", errors="replace")
    stderr_data = b"".join(stderr_chunks).decode("utf-8", errors="replace")

    if proc.returncode != 0:
        raise RuntimeError(
            f"Prozessfehler (Code {proc.returncode}):\n{stderr_data.strip()}"
        )

    return stdout_data, stderr_data

"""Prozessgruppen-Beendigung, Abbruch-Registry und Idle-Watchdog."""

from __future__ import annotations

import re
import signal
import subprocess
import time

import pytest

from bort import streaming
from bort.streaming import terminate_process_tree


class _FakeProc:
    """Popen-Stub, der Signale der gefakten Prozessgruppe nachspielt."""

    def __init__(self, *, obeys_sigterm: bool) -> None:
        self.pid = 4223
        self._returncode: int | None = None
        self._obeys_sigterm = obeys_sigterm

    def poll(self) -> int | None:
        return self._returncode

    def wait(self, timeout: float | None = None) -> int:
        if self._returncode is None:
            raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout)
        return self._returncode

    def deliver(self, sig: int) -> None:
        if sig == signal.SIGKILL or self._obeys_sigterm:
            self._returncode = -sig

    def send_signal(self, sig: int) -> None:
        self.deliver(sig)


def _patch_process_group(monkeypatch: pytest.MonkeyPatch, proc: _FakeProc) -> list[int]:
    """Leitet os.killpg auf den Fake-Prozess um und zeichnet Signale auf."""
    signals: list[int] = []

    def fake_killpg(pgid: int, sig: int) -> None:
        assert pgid == proc.pid
        signals.append(sig)
        proc.deliver(sig)

    # getpgid == pid signalisiert den eigenen Gruppenführer (start_new_session).
    monkeypatch.setattr(streaming.os, "getpgid", lambda pid: proc.pid)
    monkeypatch.setattr(streaming.os, "killpg", fake_killpg)
    return signals


def test_terminate_process_tree_escalates_to_sigkill(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProc(obeys_sigterm=False)
    signals = _patch_process_group(monkeypatch, proc)

    terminate_process_tree(proc, grace=0.01)

    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert proc.poll() == -signal.SIGKILL


def test_terminate_process_tree_accepts_sigterm(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProc(obeys_sigterm=True)
    signals = _patch_process_group(monkeypatch, proc)

    terminate_process_tree(proc, grace=0.01)

    assert signals == [signal.SIGTERM]
    assert proc.poll() == -signal.SIGTERM


def test_terminate_process_tree_skips_finished_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeProc(obeys_sigterm=True)
    proc.deliver(signal.SIGTERM)
    signals = _patch_process_group(monkeypatch, proc)

    terminate_process_tree(proc)

    assert signals == []


def test_terminate_process_tree_signals_group_of_exited_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeProc(obeys_sigterm=True)
    proc.deliver(signal.SIGTERM)
    signals = _patch_process_group(monkeypatch, proc)

    terminate_process_tree(proc, signal_exited_group=True)

    assert signals == [signal.SIGTERM]


def test_terminate_process_tree_uses_leader_pid_when_reaped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeProc(obeys_sigterm=True)
    proc.deliver(signal.SIGTERM)
    signals = _patch_process_group(monkeypatch, proc)

    def missing_getpgid(pid: int) -> int:
        raise OSError(f"kein Prozess {pid}")

    monkeypatch.setattr(streaming.os, "getpgid", missing_getpgid)

    terminate_process_tree(proc, signal_exited_group=True)

    assert signals == [signal.SIGTERM]


def test_terminate_process_tree_uses_passed_pgid_without_guessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Übergebene pgid wird genutzt, ohne die (evtl. recycelte) PID zu befragen."""
    proc = _FakeProc(obeys_sigterm=True)
    signals = _patch_process_group(monkeypatch, proc)

    def missing_getpgid(pid: int) -> int:
        raise OSError(f"kein Prozess {pid}")

    monkeypatch.setattr(streaming.os, "getpgid", missing_getpgid)

    terminate_process_tree(proc, grace=0.01, pgid=proc.pid)

    assert signals == [signal.SIGTERM]
    assert proc.poll() == -signal.SIGTERM


def test_terminate_process_tree_signals_process_directly_for_foreign_pgid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pgid != pid (Kind kein Gruppenführer): kein killpg, direkter Signalweg."""
    proc = _FakeProc(obeys_sigterm=True)
    signals = _patch_process_group(monkeypatch, proc)

    terminate_process_tree(proc, grace=0.01, pgid=proc.pid + 1)

    assert signals == []
    assert proc.poll() == -signal.SIGTERM


def test_run_stream_progress_streams_output_and_lines() -> None:
    lines: list[str] = []

    stdout, stderr = streaming.run_stream_progress(
        ["bash", "-c", "echo out; echo err >&2"], on_line=lines.append
    )

    assert stdout.strip() == "out"
    assert stderr.strip() == "err"
    assert lines == ["err"]


def test_run_stream_progress_streams_stdout_lines_without_changing_capture() -> None:
    """stdout-Zeilen erreichen on_stdout_line live; stdout bleibt vollständig."""
    lines: list[str] = []

    stdout, _stderr = streaming.run_stream_progress(
        ["bash", "-c", "printf 'zeile1\\nzeile2\\nrest'"],
        on_stdout_line=lines.append,
    )

    assert lines == ["zeile1", "zeile2", "rest"]
    assert stdout == "zeile1\nzeile2\nrest"


def test_run_stream_progress_without_stdout_callback_is_unchanged() -> None:
    stdout, stderr = streaming.run_stream_progress(
        ["bash", "-c", "echo out; echo err >&2"]
    )
    assert stdout.strip() == "out"
    assert stderr.strip() == "err"


def test_run_stream_progress_decodes_multibyte_chars_split_across_chunks() -> None:
    """Am Chunkrand geteilte UTF-8-Sequenzen landen heil im Live-Text (kein U+FFFD)."""
    lines: list[str] = []
    script = (
        "import sys, time\n"
        "data = 'Zwerg über Wasser'.encode('utf-8')\n"
        "sys.stdout.buffer.write(data[:7])\n"
        "sys.stdout.buffer.flush()\n"
        "time.sleep(0.2)\n"
        "sys.stdout.buffer.write(data[7:] + b'\\n')\n"
        "sys.stdout.buffer.flush()\n"
    )

    streaming.run_stream_progress(["python", "-c", script], on_stdout_line=lines.append)

    assert lines == ["Zwerg über Wasser"]


def test_terminate_registered_processes_kills_without_blocking_future_starts() -> None:
    """Job-Abbruch: aktive Prozesse sterben, neue Starts bleiben erlaubt."""
    proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
    assert streaming.register_process(proc)
    try:
        streaming.terminate_registered_processes(grace=0.5)
        assert proc.poll() is not None
        late = subprocess.Popen(["true"])
        try:
            # Kein globales Cancel-Flag: Registry nimmt den Prozess auf.
            assert streaming.register_process(late) is True
        finally:
            streaming.unregister_process(late)
            assert streaming._processes.get(late) is None
    finally:
        streaming.terminate_process_tree(proc)
        streaming.unregister_process(proc)
        assert streaming._processes.get(proc) is None


def test_run_stream_progress_kills_silent_process_after_idle_timeout() -> None:
    with pytest.raises(RuntimeError, match="ohne Ausgabe"):
        streaming.run_stream_progress(["sleep", "30"], idle_timeout=0.2)


def test_run_stream_progress_enforces_eof_grace_after_child_exit() -> None:
    """Child beendet sich, Enkelkind hält die Pipes offen (bash: sleep & exit).

    Vorher blockierte die Leseschleife bis zum EOF des Enkelkinds (30 s);
    jetzt wird nach der EOF-Karenz die Prozessgruppe beendet.
    """
    start = time.monotonic()

    stdout, stderr = streaming.run_stream_progress(
        ["bash", "-c", "sleep 30 & exit 0"], idle_timeout=0.5, eof_grace=0.3
    )

    elapsed = time.monotonic() - start
    assert stdout == ""
    assert stderr == ""
    assert 0.2 <= elapsed < 5.0


def test_run_stream_progress_reports_actual_elapsed_time_after_sigkill_escalation() -> None:
    """Enkelkind ignoriert SIGTERM: Doppel-Eskalation nach 2x eof_grace.

    Die Fehlermeldung meldet die real verstrichene Zeit seit Child-Exit
    (eine Nachkommastelle), nicht die einfache Karenz gerundet ("0s").
    """
    eof_grace = 0.3
    with pytest.raises(
        RuntimeError, match=r"blieb \d+\.\ds nach Prozessende"
    ) as excinfo:
        streaming.run_stream_progress(
            ["bash", "-c", "trap '' TERM; sleep 30 & exit 0"],
            idle_timeout=10.0,
            eof_grace=eof_grace,
        )

    m = re.search(r"blieb (\d+\.\d)s", str(excinfo.value))
    assert m is not None
    assert float(m.group(1)) >= 2 * eof_grace


def test_cancel_all_streams_terminates_registered_processes() -> None:
    proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
    assert streaming.register_process(proc)
    try:
        streaming.cancel_all_streams()
        assert proc.poll() is not None
    finally:
        streaming.terminate_process_tree(proc)
        streaming.unregister_process(proc)
        # Globales Abbruch-Flag für Folgetests zurücksetzen.
        streaming._cancel_requested.clear()


def test_cancel_all_streams_rejects_new_starts() -> None:
    streaming.cancel_all_streams()
    try:
        proc = subprocess.Popen(["true"])
        try:
            assert streaming.register_process(proc) is False
        finally:
            proc.wait(timeout=5)
    finally:
        streaming._cancel_requested.clear()


def test_cancel_all_streams_uses_short_grace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fensterschluss läuft im GUI-Thread: kurze Grace-Frist, kein Einfrieren."""
    graces: list[float] = []
    monkeypatch.setattr(
        streaming,
        "terminate_process_tree",
        lambda proc, grace=5.0, **_kwargs: graces.append(grace),
    )
    proc = subprocess.Popen(["true"])
    try:
        assert streaming.register_process(proc)

        streaming.cancel_all_streams()
    finally:
        proc.wait(timeout=5)
        streaming.unregister_process(proc)
        streaming._cancel_requested.clear()

    # Andere Tests können noch beendete Prozesse in der Registry lassen;
    # entscheidend ist, dass der Cancel-Pfad für alle kurze Grace nutzt.
    assert graces
    assert set(graces) == {1.0}

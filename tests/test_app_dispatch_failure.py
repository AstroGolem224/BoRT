"""Ein fehlgeschlagener run_js-Versand darf den Streaming-Latch nicht setzen."""

from __future__ import annotations

from pathlib import Path

from bort import streaming
from bort.app import Bridge
from bort.config import Config
from bort.streaming import run_stream_progress


class _BrokenWindow:
    """Fenster, dessen run_js beim ersten Versand scheitert (WebKit-Hänger, Race)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_js(self, script: str) -> None:
        self.calls.append(script)
        if len(self.calls) == 1:
            raise RuntimeError("run_js fehlgeschlagen")


def test_run_js_failure_keeps_app_alive(tmp_path: Path) -> None:
    bridge = Bridge(config=Config(path=tmp_path / "settings.json"))
    window = _BrokenWindow()
    bridge.window = window
    bridge._active_job_id = "job-1"
    bridge._delivery_active = True

    bridge._deliver_events(
        [
            ("job-1", {"type": "progress", "percent": 10.0, "phase": "eins"}),
            ("job-1", {"type": "done", "message": "zwei"}),
        ]
    )

    # Nur das fehlgeschlagene Ereignis fällt aus; die restlichen des Bündels
    # gehen trotzdem raus – sie sind in _drain_events bereits aus der Queue
    # entfernt und wären sonst für immer verloren.
    assert len(window.calls) == 2
    assert "done" in window.calls[1]
    assert bridge._closed is False
    assert bridge._delivery_active is False
    # done kam an: der Job gilt als beendet, Start ist wieder frei.
    assert bridge._active_job_id is None
    # Der Einweg-Latch bleibt offen: weitere Prozessstarts sind möglich.
    assert not streaming._cancel_requested.is_set()
    stdout, _stderr = run_stream_progress(["echo", "hi"])
    assert "hi" in stdout


class _DoneFails:
    """Fenster, bei dem ausgerechnet die Terminal-Ereignisse nicht durchkommen."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_js(self, script: str) -> None:
        self.calls.append(script)
        raise RuntimeError("run_js fehlgeschlagen")


def test_failed_done_still_clears_active_job(tmp_path: Path) -> None:
    bridge = Bridge(config=Config(path=tmp_path / "settings.json"))
    bridge.window = _DoneFails()
    bridge._active_job_id = "job-1"
    bridge._active_job_abort = object()
    bridge._active_batch_id = "batch-1"
    bridge._pending_batch = ["a.wav"]
    bridge._delivery_active = True

    bridge._deliver_events(
        [
            ("job-1", {"type": "done", "message": "fertig"}),
            ("batch-1", {"type": "batch_finished", "message": "done"}),
        ]
    )

    # Der Latch fällt auch, wenn run_js beim Terminal-Ereignis wirft – sonst
    # bliebe der Start gesperrt und Abbrechen liefe ins Leere.
    assert bridge._active_job_id is None
    assert bridge._active_job_abort is None
    assert bridge._active_batch_id is None
    assert bridge._pending_batch == []
    assert bridge._delivery_active is False

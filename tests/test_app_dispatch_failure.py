"""Ein fehlgeschlagener run_js-Versand darf den Streaming-Latch nicht setzen."""

from __future__ import annotations

from pathlib import Path

from bort import streaming
from bort.app import Bridge
from bort.config import Config
from bort.streaming import run_stream_progress


class _BrokenWindow:
    """Fenster, dessen run_js transient scheitert (WebKit-Hänger, Race)."""

    def __init__(self) -> None:
        self.calls = 0

    def run_js(self, _script: str) -> None:
        self.calls += 1
        raise RuntimeError("run_js fehlgeschlagen")


def test_run_js_failure_keeps_app_alive(tmp_path: Path) -> None:
    bridge = Bridge(config=Config(path=tmp_path / "settings.json"))
    window = _BrokenWindow()
    bridge.window = window
    bridge._active_job_id = "job-1"
    bridge._delivery_active = True

    bridge._deliver_events(
        [
            ("job-1", {"type": "log", "level": "INFO", "message": "eins"}),
            ("job-1", {"type": "log", "level": "INFO", "message": "zwei"}),
        ]
    )

    # Nur der fehlgeschlagene Versand bricht ab; das Fenster gilt nicht als zu.
    assert window.calls == 1
    assert bridge._closed is False
    assert bridge._delivery_active is False
    assert bridge._active_job_id == "job-1"
    # Der Einweg-Latch bleibt offen: weitere Prozessstarts sind möglich.
    assert not streaming._cancel_requested.is_set()
    stdout, _stderr = run_stream_progress(["echo", "hi"])
    assert "hi" in stdout

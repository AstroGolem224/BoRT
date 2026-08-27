"""Fensterschluss bricht laufende Transkriptions-Jobs ab."""

from __future__ import annotations

import subprocess

from bort import streaming
from bort.app import Bridge
from bort.config import Config


def test_window_close_cancels_active_batch_and_processes(tmp_path) -> None:
    bridge = Bridge(config=Config(path=tmp_path / "settings.json"))
    procs = [subprocess.Popen(["sleep", "30"], start_new_session=True) for _ in range(2)]
    for proc in procs:
        assert streaming.register_process(proc)
    bridge.batch_controller._active_id = "batch-1"
    bridge._active_batch_id = "batch-1"

    bridge.on_window_closed()

    for proc in procs:
        assert proc.poll() is not None
    assert bridge.batch_controller._cancel_requested is True
    # Nach dem Abbruch lehnt die Registry neue Prozess-Starts ab.
    late = subprocess.Popen(["true"])
    try:
        assert streaming.register_process(late) is False
    finally:
        late.wait(timeout=5)
        streaming._cancel_requested.clear()

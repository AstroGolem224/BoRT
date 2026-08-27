"""Batch-Abbruch tötet den laufenden Subprozess und zählt das Item als übersprungen."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from bort import streaming
from bort.batch import PendingItem
from bort.controller.batch import BatchController
from bort.controller.jobs import JobController, TranscriptionParams


def _params(tmp_path: Path) -> TranscriptionParams:
    return TranscriptionParams(
        audio_path=tmp_path / "session.m4a",
        marker_path=None,
        model_path=tmp_path / "model.bin",
        language=None,
        output_dir=tmp_path,
        formats=["txt"],
        keep_wav=False,
        colocate=True,
    )


def test_cancel_terminates_running_subprocess(tmp_path: Path) -> None:
    jobs = JobController()
    controller = BatchController(jobs, lambda _event: None)
    controller._active_id = "batch-1"
    proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
    assert streaming.register_process(proc)
    try:
        assert controller.cancel("batch-1") is True
        # Ohne Prozess-Kill liefe eine lange Datei nach dem Klick weiter.
        assert proc.wait(timeout=10) is not None
        assert controller._abort.is_set()
    finally:
        streaming.unregister_process(proc)
        if proc.poll() is None:
            proc.kill()
    # Anders als beim Fensterschluss bleiben neue Starts erlaubt.
    assert not streaming._cancel_requested.is_set()


def test_cancelled_item_counts_as_skipped_not_error(tmp_path: Path, monkeypatch) -> None:
    audio = tmp_path / "session.m4a"
    audio.write_bytes(b"audio")
    params = _params(tmp_path)

    def fake_worker(_params, emit, abort_event=None) -> None:
        assert abort_event is not None, "Batch muss den Abort-Event durchreichen"
        assert abort_event.is_set()
        emit(("cancelled", "Transkription wurde abgebrochen."))

    monkeypatch.setattr("bort.controller.batch.transcription_worker", fake_worker)
    monkeypatch.setattr("bort.controller.batch.is_file_stable", lambda _path: True)
    monkeypatch.setattr("bort.controller.batch._has_output", lambda *a, **k: False)

    jobs = JobController()
    events: list[tuple] = []
    controller = BatchController(jobs, events.append)
    controller._abort = threading.Event()
    controller._abort.set()

    outcome = controller._process_item("batch", PendingItem(audio, None), params, 1, 2)

    assert outcome == "skip", "Abbruch ist kein Fehler"
    assert events[-1] == ("batch_item_done", "batch", "session.m4a", "Abgebrochen")

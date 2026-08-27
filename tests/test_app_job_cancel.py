"""Abbruch laufender Einzeltranskription + Live-Teilergebnisse (Bridge-Ebene)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from bort.app import MAX_QUEUED_LOGS, Bridge
from bort.config import Config


def _make_bridge(tmp_path: Path) -> Bridge:
    return Bridge(config=Config(path=tmp_path / "settings.json"))


def _valid_settings() -> dict:
    return {
        "backend": "whispercpp",
        "language": "auto",
        "task": "transcribe",
        "formats": ["txt"],
        "colocate": True,
    }


def _start_running_job(
    bridge: Bridge,
    tmp_path: Path,
    monkeypatch,
    *,
    started: threading.Event,
) -> tuple[str, list[bool]]:
    """Startet einen Fake-Lauf über die echte Bridge-API."""
    audio = tmp_path / "session.wav"
    audio.write_bytes(b"x")
    model = tmp_path / "model.bin"
    model.write_bytes(b"m")
    bridge._paths["audio"] = audio
    bridge._paths["model"] = model

    killed: list[bool] = []

    def fake_kill_registered_processes() -> None:
        killed.append(True)

    monkeypatch.setattr(
        "bort.app.terminate_registered_processes", fake_kill_registered_processes
    )

    def fake_worker(_params, emit, abort_event=None):
        emit(("progress", 10.0, "Transkribiere"))
        started.set()
        if abort_event is not None and abort_event.wait(timeout=10):
            emit(("cancelled", "Transkription wurde abgebrochen."))

    monkeypatch.setattr("bort.app.transcription_worker", fake_worker)

    result = bridge.start_transcription(_valid_settings())
    assert result.get("ok"), result
    job_id = result["job_id"]
    assert bridge._active_job_id == job_id
    # Kill-Hook gehört zum Abbruchpfad, nicht zum Start.
    assert killed == []
    return job_id, killed


def test_cancel_running_single_job_sets_abort_and_frees_lock(
    tmp_path: Path, monkeypatch
) -> None:
    started = threading.Event()
    bridge = _make_bridge(tmp_path)
    job_id, killed = _start_running_job(bridge, tmp_path, monkeypatch, started=started)
    try:
        assert started.wait(timeout=10), "Fake-Worker gestartet"

        cancel = bridge.cancel_transcription()
        assert cancel == {"ok": True}
        assert killed == [True], "Subprozess-Kill beim Abbruch ausgelöst"

        # Worker endet sauber (kein Fehler), Lock wird vom Worker-Thread frei.
        deadline = time.monotonic() + 10.0
        while bridge.controller.running and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not bridge.controller.running, "Job-Lock nach Abbruch nicht freigegeben"

        payloads = [payload for _job, payload in list(bridge._events)]
        assert payloads[-1]["type"] == "cancelled"
        assert payloads[-1]["message"] == "Transkription wurde abgebrochen."
        assert not [payload for payload in payloads if payload["type"] == "error"]

        # Lock frei -> erneuter Start möglich (Runde-1-Lock-Adoption intakt).
        reacquired = bridge.controller.acquire()
        assert reacquired.acquired
        bridge.controller.release()
    finally:
        with bridge._state_lock:
            bridge._active_job_id = None
            bridge._active_job_abort = None


def test_cancel_without_active_job_is_rejected(tmp_path: Path) -> None:
    bridge = _make_bridge(tmp_path)
    result = bridge.cancel_transcription()
    assert result["ok"] is False
    assert "Keine laufende" in result["error"]


def test_partial_and_cancelled_payload_mapping(tmp_path: Path) -> None:
    """partial/cancelled werden zu UI-Payloads gemappt."""
    bridge = _make_bridge(tmp_path)

    partial = bridge._event_payload(("partial", {"start": 0.5, "end": 2.25, "text": "Hi"}))
    assert partial == {"type": "partial", "start": 0.5, "end": 2.25, "text": "Hi"}
    cancelled = bridge._event_payload(("cancelled", "abgebrochen"))
    assert cancelled == {"type": "cancelled", "message": "abgebrochen"}
    # Unbekannte Events bleiben unangetastet gefiltert.
    assert bridge._event_payload(("unknown",)) is None


def test_partial_events_are_not_squeezed_out_by_log_cap(tmp_path: Path) -> None:
    """Partials haben eigenen Platz: das Log-Cap drückt sie nicht aus der Queue."""
    bridge = _make_bridge(tmp_path)
    bridge._active_job_id = "job"
    try:
        for index in range(MAX_QUEUED_LOGS + 10):
            bridge._enqueue_worker_event("job", ("log", "INFO", f"zeile {index}"))
        bridge._enqueue_worker_event(
            "job", ("partial", {"start": 0.0, "end": 1.0, "text": "live"})
        )
        bridge._enqueue_worker_event(
            "job",
            (
                "done",
                "fertig",
                {"segments": [], "output_location": str(tmp_path)},
            ),
        )

        types = [payload["type"] for _job, payload in bridge._events]
        assert types.count("log") <= MAX_QUEUED_LOGS
        assert types[-2:] == ["partial", "done"]
    finally:
        with bridge._state_lock:
            bridge._active_job_id = None

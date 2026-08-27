from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import pytest

from bort.batch import PendingItem
from bort.controller.batch import BatchController
from bort.controller.jobs import (
    JobController,
    TranscriptionParams,
    TranscriptionSettings,
    build_params,
    transcription_worker,
)
from bort.controller.playback import AudioPlayer, PlaybackError
from bort.controller.speaker_edit import RegisteredReview, SpeakerEditController, SpeakerEditError
from bort.markers import SpeakerMarker
from bort.speakers import Segment, SpeakerSegment


def test_params_preserve_whisperx_feature_settings(tmp_path: Path) -> None:
    audio = tmp_path / "meeting.wav"
    audio.touch()
    result = build_params(
        TranscriptionSettings(
            audio,
            None,
            None,
            tmp_path,
            ["txt", "csv"],
            "de",
            "translate",
            "whisperx",
            "medium",
            "1",
            "3",
            True,
            True,
            True,
            False,
        )
    )
    assert result.ok
    assert result.params is not None
    assert result.params.backend == "whisperx"
    assert result.params.language == "de"
    assert result.params.task == "translate"
    assert (result.params.whisperx_model, result.params.min_speakers) == ("medium", 1)
    assert result.params.max_speakers == 3
    assert result.params.no_diarize and not result.params.auto_markers
    assert result.params.keep_wav and result.params.verbose
    assert result.params.formats == ["txt", "csv"]


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        (
            lambda tmp_path: TranscriptionSettings(
                tmp_path / "missing.wav",
                None,
                None,
                tmp_path,
                ["txt"],
                "auto",
                "transcribe",
                "whisperx",
            ),
            "Audio-Datei nicht gefunden.",
        ),
        (
            lambda tmp_path: TranscriptionSettings(
                _touch(tmp_path / "audio.txt"),
                None,
                None,
                tmp_path,
                ["txt"],
                "auto",
                "transcribe",
                "whisperx",
            ),
            "Nicht unterstütztes Format: .txt.",
        ),
        (
            lambda tmp_path: TranscriptionSettings(
                _touch(tmp_path / "audio.wav"),
                tmp_path / "missing.json",
                None,
                tmp_path,
                ["txt"],
                "auto",
                "transcribe",
                "whisperx",
            ),
            "Marker-Datei nicht gefunden.",
        ),
        (
            lambda tmp_path: TranscriptionSettings(
                _touch(tmp_path / "audio.wav"),
                None,
                None,
                tmp_path,
                ["txt"],
                "auto",
                "transcribe",
                "whispercpp",
            ),
            "Modell-Datei nicht gefunden.",
        ),
        (
            lambda tmp_path: TranscriptionSettings(
                _touch(tmp_path / "audio.wav"),
                None,
                None,
                tmp_path,
                [],
                "auto",
                "transcribe",
                "whisperx",
            ),
            "Mindestens ein Ausgabeformat auswählen.",
        ),
        (
            lambda tmp_path: TranscriptionSettings(
                _touch(tmp_path / "audio.wav"),
                None,
                None,
                tmp_path,
                ["txt"],
                "auto",
                "transcribe",
                "whisperx",
                min_speakers="x",
            ),
            "Min. Sprecher muss eine Zahl sein.",
        ),
        (
            lambda tmp_path: TranscriptionSettings(
                _touch(tmp_path / "audio.wav"),
                None,
                None,
                tmp_path,
                ["txt"],
                "auto",
                "transcribe",
                "whisperx",
                max_speakers="x",
            ),
            "Max. Sprecher muss eine Zahl sein.",
        ),
    ],
)
def test_build_params_returns_structured_errors(tmp_path: Path, settings, message: str) -> None:
    result = build_params(settings(tmp_path))
    assert not result.ok
    assert message in result.errors


def test_build_params_whispercpp_happy_path_forces_speaker_limits_none(tmp_path: Path) -> None:
    audio = _touch(tmp_path / "audio.wav")
    model = _touch(tmp_path / "model.bin")
    result = build_params(
        TranscriptionSettings(
            audio,
            None,
            model,
            tmp_path,
            ["txt"],
            "en",
            "translate",
            "whispercpp",
            min_speakers="1",
            max_speakers="2",
        )
    )
    assert result.ok
    assert result.params is not None
    assert result.params.backend == "whispercpp"
    assert result.params.min_speakers is None
    assert result.params.max_speakers is None


def _touch(path: Path) -> Path:
    path.touch()
    return path


def test_job_lock_is_concurrent_and_reports_busy() -> None:
    jobs = JobController()
    assert jobs.acquire().acquired
    result: list[bool] = []
    thread = threading.Thread(target=lambda: result.append(jobs.acquire().acquired))
    thread.start()
    thread.join()
    assert result == [False]
    jobs.release()
    assert jobs.acquire().acquired
    jobs.release()


def test_job_lock_refuses_release_from_foreign_thread(
    caplog: pytest.LogCaptureFixture,
) -> None:
    jobs = JobController()
    assert jobs.acquire().acquired
    still_running: list[bool] = []

    def foreign_release() -> None:
        jobs.release()
        still_running.append(jobs.running)

    thread = threading.Thread(target=foreign_release)
    with caplog.at_level(logging.WARNING):
        thread.start()
        thread.join()

    assert still_running == [True]
    assert "verweigert" in caplog.text
    jobs.release()  # Owner (Main-Thread) darf freigeben.
    assert not jobs.running


def test_job_lock_adopt_transfers_ownership_to_worker_thread() -> None:
    jobs = JobController()
    assert jobs.acquire().acquired

    def worker() -> None:
        jobs.adopt()
        jobs.release()

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert not jobs.running


def test_playback_rejects_invalid_bounds_and_missing_ffplay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    player = AudioPlayer(Path("audio.wav"))
    with pytest.raises(PlaybackError, match="Ungültiger"):
        player.play_segment(2, 2)
    monkeypatch.setattr("bort.controller.playback.shutil.which", lambda _: None)
    with pytest.raises(PlaybackError, match="ffplay"):
        player.play_segment(0, 1)


def test_rename_map_handles_blank_duplicates_missing_and_repeated_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(
        "bort.controller.speaker_edit.write_outputs",
        lambda segments, output_dir, base_name, formats, bookmarks, review_data, overwrite: (
            calls.append(review_data) or [output_dir / f"{base_name}.txt"]
        ),
    )
    controller = SpeakerEditController()
    review_id = controller.register(
        RegisteredReview(
            tmp_path / "audio.wav",
            [SpeakerSegment(0, 1, "Alice", "Hi"), SpeakerSegment(1, 2, "Bob", "Yo")],
            {"S1": "Alice", "S2": "Bob"},
            [SpeakerMarker(0, 1, "Alice")],
            [],
            tmp_path,
            "meeting",
            ["txt"],
        )
    )
    result = controller.apply(review_id, {"S1": " ", "S2": "Alice"})
    assert [segment.speaker for segment in result.segments] == ["Alice", "Alice"]
    assert calls[-1]["markers"][0]["speaker"] == "Alice"
    with pytest.raises(SpeakerEditError, match="fehlend"):
        controller.apply(review_id, {"S1": "Other"})
    repeated = controller.apply(review_id, {"S1": "Ann", "S2": "Alice"})
    assert [segment.speaker for segment in repeated.segments] == ["Ann", "Alice"]


def test_batch_releases_job_lock_and_emits_counted_finish() -> None:
    jobs = JobController()
    events: list[tuple] = []
    controller = BatchController(jobs, events.append)
    assert jobs.acquire().acquired
    controller._run("batch", [])
    assert events == [("batch_finished", "batch", 0, 0, 0)]
    assert jobs.acquire().acquired
    jobs.release()


def test_batch_scan_reports_total_audio_count(tmp_path: Path) -> None:
    """Ohne Gesamtzahl sieht "0 ausstehend" wie ein leerer Ordner aus."""
    watch_dir = tmp_path / "watch"
    output_dir = tmp_path / "output"
    watch_dir.mkdir()
    output_dir.mkdir()
    controller = BatchController(JobController(), lambda _event: None)

    # Leerer Ordner: nichts da, nichts ausstehend.
    assert controller.scan(watch_dir, output_dir) == ([], 0, 0)

    # Vier Aufnahmen, alle mit frischem Transkript: 0 ausstehend, aber 4 gesehen.
    for index in range(4):
        audio = watch_dir / f"session{index}.m4a"
        audio.write_bytes(b"")
        (output_dir / f"session{index}.txt").write_text("fertig", encoding="utf-8")
    stable, unstable, total = controller.scan(watch_dir, output_dir)
    assert (stable, unstable) == ([], 0)
    assert total == 4


def test_batch_scan_checks_stability_in_parallel(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    output_dir = tmp_path / "output"
    watch_dir.mkdir()
    output_dir.mkdir()
    for index in range(6):
        (watch_dir / f"session{index}.m4a").write_bytes(b"")

    jobs = JobController()
    controller = BatchController(jobs, lambda _event: None)
    candidates = [
        PendingItem(watch_dir / f"session{index}.m4a", None) for index in range(6)
    ]
    serial = [item for item in candidates if item.audio_path.stat().st_size >= 0]

    active = {"now": 0, "max": 0}
    lock = threading.Lock()

    def slow_stable(path: Path) -> bool:
        with lock:
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
        time.sleep(0.1)
        with lock:
            active["now"] -= 1
        return True

    import bort.controller.batch as batch_module

    original_stable = batch_module.is_file_stable
    try:
        batch_module.is_file_stable = slow_stable
        stable, unstable, total = controller.scan(watch_dir, output_dir)
    finally:
        batch_module.is_file_stable = original_stable

    # Gleiche Reihenfolge und gleiche Elemente wie seriell, aber parallel.
    assert stable == serial
    assert unstable == 0
    assert total == len(serial)
    assert active["max"] >= 2, "Stabilitätsprüfung muss parallel laufen"


def test_batch_item_progress_arrives_while_worker_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "session.m4a"
    audio.write_bytes(b"x")
    params = TranscriptionParams(
        audio_path=audio,
        marker_path=None,
        model_path=None,
        language=None,
        output_dir=tmp_path,
        formats=["txt"],
        keep_wav=False,
        colocate=True,
    )
    progress_emitted = threading.Event()
    release_worker = threading.Event()

    def fake_worker(_params: object, emit, _abort=None) -> None:
        emit(("progress", 42.0, "Transkribiere"))
        progress_emitted.set()
        release_worker.wait(timeout=5)
        emit(("done", "fertig"))

    monkeypatch.setattr("bort.controller.batch.transcription_worker", fake_worker)
    monkeypatch.setattr(
        "bort.controller.batch.is_file_stable", lambda _path: True
    )

    jobs = JobController()
    events: list[tuple] = []
    controller = BatchController(jobs, events.append)
    item = PendingItem(audio, None)

    outcome: dict[str, str] = {}

    def run() -> None:
        outcome["result"] = controller._process_item("batch", item, params, 1, 1)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert progress_emitted.wait(timeout=5), "Worker hat kein Progress emittiert"
        # Fortschritt muss live ankommen, obwohl der Worker noch läuft.
        assert any(event[0] == "batch_item_progress" for event in events)
    finally:
        release_worker.set()
        thread.join(timeout=5)

    assert outcome["result"] == "ok"
    assert events[-1] == ("batch_item_done", "batch", "session.m4a", "OK")


def _whispercpp_params(tmp_path: Path) -> TranscriptionParams:
    return TranscriptionParams(
        audio_path=tmp_path / "session.wav",
        marker_path=None,
        model_path=tmp_path / "model.bin",
        language="de",
        output_dir=tmp_path,
        formats=["txt"],
        keep_wav=False,
        colocate=True,
    )


def _filter(events: list[tuple], kinds: set[str]) -> list[tuple]:
    return [event for event in events if event[0] in kinds]


class SimpleResult:
    """Attr-Dummy für Backend-Ergebnisse in Worker-Tests."""

    def __init__(self, **kwargs) -> None:
        self.segments = kwargs.get("segments", [])
        self.language = kwargs.get("language")
        self.text = kwargs.get("text", "")
        self.speaker_map = kwargs.get("speaker_map", {})
        self.markers = kwargs.get("markers", [])
        self.speaker_embeddings = kwargs.get("speaker_embeddings", {})
        self.embedding_model = kwargs.get("embedding_model")
        self.runtime_metrics = kwargs.get("runtime_metrics", {})


def test_worker_forwards_partial_segments_in_order(tmp_path: Path, monkeypatch) -> None:
    """Live-Segmente kommen als partial-Events in stdout-Reihenfolge vor done."""
    params = _whispercpp_params(tmp_path)
    monkeypatch.setattr(
        "bort.controller.jobs.convert_to_wav",
        lambda audio, out: tmp_path / "converted.wav",
    )

    def fake_transcribe(**kwargs):
        for text, seconds in (("eins", 1.5), ("zwei", 3.2), ("drei", 5.0)):
            kwargs["segment_cb"](Segment(start=seconds - 1.5, end=seconds, text=text))
        return SimpleResult(
            segments=[Segment(0, 1.5, "eins"), Segment(1.7, 3.2, "zwei")],
            language="de",
            text="eins zwei",
        )

    monkeypatch.setattr("bort.controller.jobs.transcribe", fake_transcribe)
    monkeypatch.setattr(
        "bort.controller.jobs.write_outputs",
        lambda *args, **kwargs: [tmp_path / "out.txt"],
    )

    events: list[tuple] = []
    transcription_worker(params, events.append)

    flow = _filter(events, {"partial", "done", "error"})
    assert [event[0] for event in flow] == ["partial", "partial", "partial", "done"]
    assert flow[0] == ("partial", {"start": 0.0, "end": 1.5, "text": "eins"})
    assert flow[2] == ("partial", {"start": 3.5, "end": 5.0, "text": "drei"})
    # Abbruch war nie gesetzt: kein cancelled-Event im Lauf.
    assert all(event[0] != "cancelled" for event in events)


def test_worker_cancel_between_stages_emits_cancelled_not_error(
    tmp_path: Path, monkeypatch
) -> None:
    """Abort vor Stufenstart: sauberes cancelled-Event, Stufen laufen nicht."""
    params = _whispercpp_params(tmp_path)
    abort = threading.Event()
    abort.set()

    def unexpected(*args, **kwargs):
        raise AssertionError("Stufe dürfte bei gesetztem Abort nicht laufen")

    monkeypatch.setattr("bort.controller.jobs.convert_to_wav", unexpected)
    monkeypatch.setattr("bort.controller.jobs.transcribe", unexpected)
    monkeypatch.setattr("bort.controller.jobs.write_outputs", unexpected)

    events: list[tuple] = []
    transcription_worker(params, events.append, abort_event=abort)

    assert _filter(events, {"error"}) == []
    assert _filter(events, {"done"}) == []
    assert _filter(events, {"cancelled"}) == [
        ("cancelled", "Transkription wurde abgebrochen.")
    ]


def test_worker_maps_subprocess_kill_during_run_to_cancelled(
    tmp_path: Path, monkeypatch
) -> None:
    """Killpg während des Laufs -> Prozessfehler wird Nutzer-Abbruch zugeordnet."""
    params = _whispercpp_params(tmp_path)
    abort = threading.Event()
    monkeypatch.setattr(
        "bort.controller.jobs.convert_to_wav",
        lambda audio, out: tmp_path / "converted.wav",
    )
    partial_before_abort = ("partial", {"start": 0.0, "end": 1.0, "text": "vor dem Abbruch"})

    def fake_transcribe(**kwargs):
        kwargs["segment_cb"](Segment(0.0, 1.0, "vor dem Abbruch"))
        abort.set()  # Cancel-Button während des Laufs gedrückt
        raise RuntimeError("Prozessfehler (Code -15)")

    monkeypatch.setattr("bort.controller.jobs.transcribe", fake_transcribe)

    events: list[tuple] = []
    transcription_worker(params, events.append, abort_event=abort)

    flow = _filter(events, {"partial", "done", "error", "cancelled"})
    assert flow[0] == partial_before_abort
    assert flow[-1] == ("cancelled", "Transkription wurde abgebrochen.")
    assert not _filter(events, {"error"})


def test_worker_reports_error_without_abort(tmp_path: Path, monkeypatch) -> None:
    """Ohne Abort bleibt ein Prozessfehler ein Fehler (abort-vs-error)."""
    params = _whispercpp_params(tmp_path)

    def broken_convert(audio, out):
        raise RuntimeError("ffmpeg Zerquetscht")

    monkeypatch.setattr("bort.controller.jobs.convert_to_wav", broken_convert)

    events: list[tuple] = []
    transcription_worker(params, events.append, abort_event=threading.Event())

    assert _filter(events, {"cancelled"}) == []
    errors = _filter(events, {"error"})
    assert len(errors) == 1
    assert "Unerwarteter Fehler" in errors[0][1]


def test_worker_cancel_exactly_after_conversion_skips_transcription(
    tmp_path: Path, monkeypatch
) -> None:
    """Abort nach der WAV-Konvertierung: Gate vor whisper-cli bricht sofort ab."""
    params = _whispercpp_params(tmp_path)
    abort = threading.Event()

    def convert_and_abort(audio, out):
        abort.set()  # Nutzer klickt exakt zwischen Konvertierung und Start
        return tmp_path / "converted.wav"

    def unexpected(*args, **kwargs):
        raise AssertionError("Stufe dürfte nach Abort nicht mehr laufen")

    monkeypatch.setattr("bort.controller.jobs.convert_to_wav", convert_and_abort)
    monkeypatch.setattr("bort.controller.jobs.transcribe", unexpected)
    monkeypatch.setattr("bort.controller.jobs.write_outputs", unexpected)

    events: list[tuple] = []
    transcription_worker(params, events.append, abort_event=abort)

    assert _filter(events, {"error", "done", "partial"}) == []
    assert _filter(events, {"cancelled"}) == [
        ("cancelled", "Transkription wurde abgebrochen.")
    ]


def test_worker_reports_done_when_write_finishes_after_abort(
    tmp_path: Path, monkeypatch
) -> None:
    """Abort während write_outputs: geschriebene Outputs werden als done samt Pfad gemeldet.

    Ein cancelled-Event würde die UI (resetLivePreview, kein output_location)
    einen ergebnislosen Lauf anzeigen lassen, obwohl txt/md/csv/review.json
    vollständig auf der Platte liegen und den nächsten Lauf blockieren.
    """
    params = _whispercpp_params(tmp_path)
    abort = threading.Event()
    monkeypatch.setattr(
        "bort.controller.jobs.convert_to_wav",
        lambda audio, out: tmp_path / "converted.wav",
    )
    monkeypatch.setattr(
        "bort.controller.jobs.transcribe",
        lambda **kwargs: SimpleResult(segments=[Segment(0.0, 1.0, "eins")], language="de"),
    )

    def write_after_abort(*args, **kwargs):
        abort.set()  # Cancel-Button während des Schreibens gedrückt
        return [tmp_path / "out.txt"]

    monkeypatch.setattr("bort.controller.jobs.write_outputs", write_after_abort)

    events: list[tuple] = []
    transcription_worker(params, events.append, abort_event=abort)

    assert _filter(events, {"cancelled", "error"}) == []
    done = _filter(events, {"done"})
    assert len(done) == 1
    assert done[0][2]["output_location"] == tmp_path


def test_whisperx_receives_no_segment_callback(tmp_path: Path, monkeypatch) -> None:
    """geth-Annahme 2: whisperX liefert EIN JSON am Ende — keine Partials."""
    params = TranscriptionParams(
        audio_path=tmp_path / "session.wav",
        marker_path=None,
        model_path=None,
        language=None,
        output_dir=tmp_path,
        formats=["txt"],
        keep_wav=False,
        colocate=True,
        backend="whisperx",
    )

    captured: dict[str, object] = {}

    def fake_whisperx(audio_path, **kwargs):
        captured.update(kwargs)
        return SimpleResult(language="de")

    monkeypatch.setattr("bort.controller.jobs.transcribe_whisperx", fake_whisperx)
    monkeypatch.setattr(
        "bort.controller.jobs.write_outputs",
        lambda *args, **kwargs: [tmp_path / "out.txt"],
    )

    events: list[tuple] = []
    transcription_worker(params, events.append)

    assert captured.get("segment_cb") is None
    assert _filter(events, {"partial"}) == []
    assert _filter(events, {"done"}) != []

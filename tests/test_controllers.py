from __future__ import annotations

import threading
from pathlib import Path

import pytest

from bort.controller.batch import BatchController
from bort.controller.jobs import JobController, TranscriptionSettings, build_params
from bort.controller.playback import AudioPlayer, PlaybackError
from bort.controller.speaker_edit import RegisteredReview, SpeakerEditController, SpeakerEditError
from bort.markers import SpeakerMarker
from bort.speakers import SpeakerSegment


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

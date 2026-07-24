"""Tests für Streaming-Peaks, ffmpeg-Fehlerpfade und Bridge-Cache."""

from __future__ import annotations

import shutil
import struct
import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from bort import waveform
from bort.app import Bridge
from bort.controller.speaker_edit import RegisteredReview
from bort.waveform import WaveformError, extract_peaks, reduce_peaks


def _pcm(*samples: int) -> bytes:
    return struct.pack(f"<{len(samples)}h", *samples)


def _register_review(bridge: Bridge, audio: Path) -> str:
    review = RegisteredReview(
        audio_path=audio,
        segments=[],
        speaker_map={},
        markers=[],
        bookmarks=[],
        output_dir=audio.parent,
        base_name=audio.stem,
        formats=["txt"],
    )
    return bridge.speaker_controller.register(review)


def test_reduce_peaks_silence_and_full_scale() -> None:
    assert reduce_peaks([_pcm(0, 0, 0, 0)], samples_per_bucket=4) == [[0.0, 0.0]]
    assert reduce_peaks([_pcm(-32768, 32767)], samples_per_bucket=2) == [
        [-1.0, 32767 / 32768]
    ]


def test_reduce_peaks_handles_ramps_boundaries_and_odd_chunks() -> None:
    data = _pcm(-1000, -500, 500, 1000)
    peaks = reduce_peaks([data[:3], data[3:5], data[5:]], samples_per_bucket=2)
    assert peaks == [[-1000 / 32768, -500 / 32768], [500 / 32768, 1000 / 32768]]


def test_reduce_peaks_empty_and_partial_bucket() -> None:
    assert reduce_peaks([]) == []
    assert reduce_peaks([_pcm(123)], samples_per_bucket=4) == [[123 / 32768, 123 / 32768]]


def test_reduce_peaks_rebins_at_maximum() -> None:
    peaks = reduce_peaks([_pcm(*range(8))], samples_per_bucket=1, max_buckets=4)
    assert len(peaks) == 2
    assert peaks[0] == [0.0, 3 / 32768]
    assert peaks[1] == [4 / 32768, 7 / 32768]


@pytest.mark.parametrize("stdout", ["", "N/A\n", "Unsinn\n", "nan\ninf\n"])
def test_ffprobe_garbage_falls_back_to_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdout: str
) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"x")
    monkeypatch.setattr(
        waveform.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=stdout),
    )
    assert waveform._probe_duration(audio) is None
    assert waveform._deadline_for(None) == 600


def test_missing_ffprobe_is_nonfatal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"x")

    def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(waveform.subprocess, "run", missing)
    assert waveform._probe_duration(audio) is None


def test_ffprobe_timeout_is_nonfatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"x")

    def timeout(*args, **kwargs):
        raise waveform.subprocess.TimeoutExpired("ffprobe", 5)

    monkeypatch.setattr(waveform.subprocess, "run", timeout)
    assert waveform._probe_duration(audio) is None


def test_missing_ffmpeg_raises_waveform_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"x")
    monkeypatch.setattr(waveform, "_probe_duration", lambda path: None)
    monkeypatch.setattr(
        waveform.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    with pytest.raises(WaveformError, match="ffmpeg"):
        extract_peaks(audio)


class _FakePipe:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self, _size: int = -1) -> bytes:
        data, self.data = self.data, b""
        return data


class _FakeProcess:
    def __init__(self, returncode: int = 1, stderr: bytes = b"kaputt") -> None:
        self.stdout = _FakePipe(b"")
        self.stderr = _FakePipe(stderr)
        self.returncode = returncode
        self.finished = False

    def poll(self):
        return self.returncode if self.finished else None

    def wait(self, timeout=None):
        self.finished = True
        return self.returncode

    def terminate(self) -> None:
        self.finished = True

    def kill(self) -> None:
        self.finished = True


def test_ffmpeg_nonzero_exit_includes_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"x")
    monkeypatch.setattr(waveform, "_probe_duration", lambda path: 1.0)
    monkeypatch.setattr(waveform.subprocess, "Popen", lambda *args, **kwargs: _FakeProcess())
    with pytest.raises(WaveformError, match="kaputt"):
        extract_peaks(audio)


def test_watchdog_timeout_terminates_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"x")
    released = threading.Event()

    class BlockingProcess(_FakeProcess):
        def wait(self, timeout=None):
            if timeout is None:
                released.wait(1)
            self.finished = True
            return -15

        def terminate(self):
            released.set()
            self.finished = True

    monkeypatch.setattr(waveform, "_probe_duration", lambda path: None)
    monkeypatch.setattr(waveform, "_deadline_for", lambda duration: 0.01)
    monkeypatch.setattr(
        waveform.subprocess, "Popen", lambda *args, **kwargs: BlockingProcess()
    )
    with pytest.raises(WaveformError, match="Zeitüberschreitung"):
        extract_peaks(audio)


def test_bridge_cache_hit_and_path_based_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    bridge = Bridge()
    first = _register_review(bridge, audio)
    second = _register_review(bridge, audio)
    calls = []

    def fake_extract(path, **kwargs):
        calls.append(path)
        return 1.5, [[-0.5, 0.5]]

    monkeypatch.setattr("bort.app.extract_peaks", fake_extract)

    assert bridge.get_waveform(first)["ok"]
    assert bridge.get_waveform(second)["ok"]
    assert len(calls) == 1


def test_bridge_coalesces_parallel_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    bridge = Bridge()
    review_id = _register_review(bridge, audio)
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def slow_extract(path, **kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(1)
        return 2.0, [[0.0, 0.5]]

    monkeypatch.setattr("bort.app.extract_peaks", slow_extract)
    results = []
    first = threading.Thread(target=lambda: results.append(bridge.get_waveform(review_id)))
    second = threading.Thread(target=lambda: results.append(bridge.get_waveform(review_id)))
    first.start()
    assert entered.wait(1)
    second.start()
    time.sleep(0.02)
    release.set()
    first.join()
    second.join()

    assert calls == 1
    assert len(results) == 2
    assert all(result["ok"] for result in results)


def test_bridge_does_not_cache_failed_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    bridge = Bridge()
    review_id = _register_review(bridge, audio)
    calls = 0

    def failing_extract(path, **kwargs):
        nonlocal calls
        calls += 1
        raise WaveformError("defekt")

    monkeypatch.setattr("bort.app.extract_peaks", failing_extract)
    assert not bridge.get_waveform(review_id)["ok"]
    assert not bridge.get_waveform(review_id)["ok"]
    assert calls == 2


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg fehlt")
def test_extract_peaks_with_real_mini_wav(tmp_path: Path) -> None:
    audio = tmp_path / "mini.wav"
    samples = [0, 1000, -1000, 2000, -2000] * 1600
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(_pcm(*samples))

    duration, peaks = extract_peaks(audio)

    assert duration == pytest.approx(1.0, abs=0.01)
    assert peaks
    assert len(peaks) <= waveform.MAX_BUCKETS

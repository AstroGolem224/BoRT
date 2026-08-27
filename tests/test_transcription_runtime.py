from __future__ import annotations

import json
from pathlib import Path

import pytest

from bort import streaming
from bort.transcription import (
    _find_whisper_cli,
    _run_whisper,
    parse_segment_line,
    recommended_thread_count,
)


def test_recommended_threads_uses_half_logical_cores_with_cap() -> None:
    assert recommended_thread_count(1) == 1
    assert recommended_thread_count(8) == 4
    assert recommended_thread_count(64) == 12


def test_whisper_cli_gets_threads_and_local_library_path(
    monkeypatch, tmp_path: Path
) -> None:
    binary = tmp_path / "build" / "bin" / "whisper-cli"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"")
    model = tmp_path / "model.bin"
    model.write_bytes(b"")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(cmd=cmd, env=kwargs["env"])
        prefix = Path(cmd[cmd.index("--output-file") + 1])
        prefix.with_suffix(".json").write_text(
            json.dumps({"transcription": []}), encoding="utf-8"
        )
        return "", ""

    monkeypatch.setattr(streaming, "run_stream_progress", fake_run)

    _run_whisper(tmp_path / "audio.wav", model, None, binary)

    assert "--threads" in captured["cmd"]
    assert captured["env"]["LD_LIBRARY_PATH"].split(":")[0] == str(binary.parent)


def test_find_whisper_cli_supports_pyinstaller_bundle(
    monkeypatch, tmp_path: Path
) -> None:
    binary = tmp_path / "vendor" / "whisper.cpp" / "build" / "bin" / "whisper-cli"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"")
    monkeypatch.setattr("bort.transcription.sys._MEIPASS", str(tmp_path), raising=False)

    assert _find_whisper_cli() == binary


def test_parse_segment_line_parses_timestamps_and_text() -> None:
    segment = parse_segment_line(
        "[00:01:02.500 --> 00:01:05.750]  Hallo Welt"
    )
    assert segment is not None
    assert segment.start == pytest.approx(62.5)
    assert segment.end == pytest.approx(65.75)
    assert segment.text == "Hallo Welt"


def test_parse_segment_line_ignores_garbage_and_empty_text() -> None:
    assert parse_segment_line("progress = 12%") is None
    assert parse_segment_line("[00:00:00.000 --> 00:00:01.000]   ") is None
    assert parse_segment_line("") is None
    assert parse_segment_line("whisper_init_from_file: ...") is None


def test_run_whisper_streams_segments_in_order(monkeypatch, tmp_path: Path) -> None:
    """Live-Segmente erreichen segment_cb in stdout-Reihenfolge."""
    binary = tmp_path / "build" / "bin" / "whisper-cli"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"")
    model = tmp_path / "model.bin"
    model.write_bytes(b"")
    seen = {"stdout_lines": [], "segments": []}

    def fake_run(cmd, **kwargs):
        on_stdout_line = kwargs["on_stdout_line"]
        for line in (
            "[00:00:00.000 --> 00:00:02.100]  erstes Segment",
            "progress = 50%",
            "[00:00:02.100 --> 00:00:04.200]  zweites Segment",
        ):
            on_stdout_line(line.strip())
        prefix = Path(cmd[cmd.index("--output-file") + 1])
        prefix.with_suffix(".json").write_text(
            json.dumps({"transcription": []}), encoding="utf-8"
        )
        return "", ""

    monkeypatch.setattr(streaming, "run_stream_progress", fake_run)

    _run_whisper(
        tmp_path / "audio.wav",
        model,
        None,
        binary,
        segment_cb=lambda seg: seen["segments"].append(seg),
    )

    texts = [seg.text for seg in seen["segments"]]
    # 'progress = 50%' hat kein Zeitstempelformat und wird ignoriert.
    assert texts == ["erstes Segment", "zweites Segment"]
    assert [seg.end for seg in seen["segments"]] == [pytest.approx(2.1), pytest.approx(4.2)]

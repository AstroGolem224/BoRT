from __future__ import annotations

import json
from pathlib import Path

from bort import streaming
from bort.transcription import _run_whisper, recommended_thread_count


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

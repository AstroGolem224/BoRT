from __future__ import annotations

import json
from pathlib import Path

from bort import streaming
from bort import whisperx_backend as backend


def test_subprocess_requests_embeddings_only_when_enabled(monkeypatch) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(backend, "_ensure_backend_available", lambda: None)

    def fake_run(cmd, **_kwargs):
        commands.append(cmd)
        return json.dumps({"segments": []}), ""

    monkeypatch.setattr(streaming, "run_stream_progress", fake_run)

    backend._run_whisperx(Path("audio.wav"), None, "medium", None, None, False, True)
    backend._run_whisperx(Path("audio.wav"), None, "medium", None, None, False, False)

    assert "--return-embeddings" in commands[0]
    assert "--return-embeddings" not in commands[1]


def test_subprocess_maps_performance_profile_to_decode_settings(monkeypatch) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(backend, "_ensure_backend_available", lambda: None)

    def fake_run(cmd, **_kwargs):
        commands.append(cmd)
        return json.dumps({"segments": []}), ""

    monkeypatch.setattr(streaming, "run_stream_progress", fake_run)

    backend._run_whisperx(
        Path("audio.wav"),
        None,
        "large-v3-turbo",
        None,
        None,
        performance_profile="fast",
    )

    command = commands[0]
    assert command[command.index("--beam-size") + 1] == "1"
    assert command[command.index("--batch-size") + 1] == "32"


def test_result_preserves_embedding_metadata(monkeypatch, tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"")
    monkeypatch.setattr(
        backend,
        "_run_whisperx",
        lambda *_args, **_kwargs: {
            "language": "de",
            "segments": [{"start": 0, "end": 1, "text": "Hallo", "speaker": "SPEAKER_00"}],
            "speaker_embeddings": {"SPEAKER_00": [1.0, 0.0]},
            "embedding_model": "embed-v1",
            "runtime_metrics": {"total_seconds": 1.25},
        },
    )

    result = backend.transcribe(audio, return_embeddings=True)

    assert result.speaker_embeddings == {"SPEAKER_00": [1.0, 0.0]}
    assert result.embedding_model == "embed-v1"
    assert result.runtime_metrics == {"total_seconds": 1.25}


def test_result_drops_embeddings_without_segments(monkeypatch, tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"")
    monkeypatch.setattr(
        backend,
        "_run_whisperx",
        lambda *_args, **_kwargs: {
            "language": "de",
            "segments": [{"start": 0, "end": 1, "text": "Hallo", "speaker": "SPEAKER_00"}],
            # SPEAKER_01 wurde diarisiert, hat aber kein Segment gewonnen.
            "speaker_embeddings": {"SPEAKER_00": [1.0, 0.0], "SPEAKER_01": [0.0, 1.0]},
            "embedding_model": "embed-v1",
        },
    )

    result = backend.transcribe(audio, return_embeddings=True)

    assert set(result.speaker_embeddings) == set(result.speaker_map)
    assert result.speaker_embeddings == {"SPEAKER_00": [1.0, 0.0]}


def test_isolated_script_override_runs_real_subprocess(tmp_path: Path) -> None:
    """An alternate script uses the existing protocol including diarization."""
    import os
    import subprocess
    import sys

    script = tmp_path / "alternate pipeline.py"
    script.write_text(
        "import json, sys\n"
        'assert "--no-diarize" not in sys.argv\n'
        'assert "--return-embeddings" in sys.argv\n'
        'print(json.dumps({"segments": [{"start": 0, "end": 1, '
        '"text": "Hallo", "speaker": "SPEAKER_00"}], '
        '"speaker_embeddings": {"SPEAKER_00": [1, 0]}, "embedding_model": "test", '
        '"runtime_metrics": {"majority_assignment_seconds": 0.001}}))\n'
    )
    wrapper = tmp_path / "run.sh"
    wrapper.write_text('#!/bin/bash\nexec "$@"\n')
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"")
    source = Path(__file__).resolve().parents[1] / "src"
    env = dict(os.environ, BORT_WHISPER_TAGGER_SCRIPT=str(script), PYTHONPATH=str(source))
    # Make the wrapper's "python" resolve to the same tested environment.
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    code = """
import sys
from pathlib import Path
from bort import whisperx_backend as backend
backend.WHISPER_TAGGER_RUN = Path(sys.argv[1])
assert backend.WHISPER_TAGGER_SCRIPT.name == "alternate pipeline.py"
result = backend.transcribe(Path(sys.argv[2]), return_embeddings=True)
assert result.segments[0].text == "Hallo"
assert result.speaker_map == {"SPEAKER_00": "sprecher001"}
assert result.speaker_embeddings == {"SPEAKER_00": [1, 0]}
assert result.runtime_metrics["majority_assignment_seconds"] == .001
"""
    run = subprocess.run(
        [sys.executable, "-c", code, str(wrapper), str(audio)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert run.returncode == 0, run.stderr

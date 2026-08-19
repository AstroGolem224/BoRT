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


def test_result_preserves_embedding_metadata(monkeypatch, tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"")
    monkeypatch.setattr(
        backend,
        "_run_whisperx",
        lambda *_args, **_kwargs: {
            "language": "de",
            "segments": [
                {"start": 0, "end": 1, "text": "Hallo", "speaker": "SPEAKER_00"}
            ],
            "speaker_embeddings": {"SPEAKER_00": [1.0, 0.0]},
            "embedding_model": "embed-v1",
            "runtime_metrics": {"total_seconds": 1.25},
        },
    )

    result = backend.transcribe(audio, return_embeddings=True)

    assert result.speaker_embeddings == {"SPEAKER_00": [1.0, 0.0]}
    assert result.embedding_model == "embed-v1"
    assert result.runtime_metrics == {"total_seconds": 1.25}

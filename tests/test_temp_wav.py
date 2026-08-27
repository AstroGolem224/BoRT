"""Temporäre WAVs liegen privat und verschwinden auch auf dem Abbruchpfad."""

from __future__ import annotations

import queue
import stat
import threading
from pathlib import Path

from bort.audio import cleanup_wav, convert_to_wav
from bort.cli import main
from bort.controller.jobs import TranscriptionParams, transcription_worker
from bort.transcription import TranscriptionError


def _params(tmp_path: Path) -> TranscriptionParams:
    return TranscriptionParams(
        audio_path=tmp_path / "session.wav",
        marker_path=None,
        model_path=tmp_path / "model.bin",
        language=None,
        output_dir=tmp_path,
        formats=["txt"],
        keep_wav=False,
        colocate=False,
    )


def test_convert_uses_private_dir_without_predictable_name(tmp_path, monkeypatch) -> None:
    audio = tmp_path / "sitzung.m4a"
    audio.write_bytes(b"x")
    captured: dict[str, list[str]] = {}

    class FakeProcess:
        returncode = 0

        def communicate(self, timeout=None):
            Path(captured["cmd"][-1]).write_bytes(b"RIFF")
            return ("", "")

    def fake_popen(cmd, **_kwargs):
        captured["cmd"] = cmd
        return FakeProcess()

    monkeypatch.setattr("bort.audio.subprocess.Popen", fake_popen)
    monkeypatch.setattr("bort.audio.register_process", lambda _proc: True)
    monkeypatch.setattr("bort.audio.unregister_process", lambda _proc: None)
    monkeypatch.setattr("bort.audio._check_ffmpeg", lambda: None)

    wav_path = convert_to_wav(audio)
    try:
        # Eigener Ordner statt festem /tmp/<stem>_16k_mono.wav: nur der
        # Besitzer kommt an die vollständige Sitzungsaufnahme.
        assert wav_path.parent != Path("/tmp")
        mode = stat.S_IMODE(wav_path.parent.stat().st_mode)
        assert mode == 0o700, oct(mode)
    finally:
        cleanup_wav(wav_path)
    assert not wav_path.exists()
    assert not wav_path.parent.exists()


def test_worker_removes_temp_wav_on_abort(tmp_path, monkeypatch) -> None:
    """Abbruch nach *und* während der Konvertierung lässt keine WAV in /tmp zurück."""
    params = _params(tmp_path)
    abort = threading.Event()
    wav_dir = tmp_path / "tmpwav"
    wav_dir.mkdir()
    wav_path = wav_dir / "session_16k_mono.wav"

    def convert_and_abort(_audio, _out):
        wav_path.write_bytes(b"RIFF" * 1000)
        abort.set()  # Cancel-Klick zwischen Konvertierung und whisper-cli
        return wav_path

    monkeypatch.setattr("bort.controller.jobs.convert_to_wav", convert_and_abort)

    events: list[tuple] = []
    transcription_worker(params, events.append, abort_event=abort)

    assert [event[0] for event in events if event[0] == "cancelled"] == ["cancelled"]
    assert not wav_path.exists(), "WAV bleibt nach Abbruch liegen"
    assert not wav_dir.exists(), "Temp-Ordner bleibt nach Abbruch liegen"

    # Zweiter Fall: der Abbruch trifft ffmpeg mitten in der Konvertierung
    # (terminate_registered_processes tötet es zuerst). convert_to_wav wirft,
    # wav_path bleibt None – der mkdtemp-Ordner muss trotzdem verschwinden.
    params.audio_path.write_bytes(b"x")
    captured: dict[str, list[str]] = {}

    class KilledProcess:
        returncode = 1

        def communicate(self, timeout=None):
            Path(captured["cmd"][-1]).write_bytes(b"RIFF" * 100)  # halbe WAV
            return ("", "Terminated")

    def fake_popen(cmd, **_kwargs):
        captured["cmd"] = cmd
        return KilledProcess()

    monkeypatch.setattr("bort.controller.jobs.convert_to_wav", convert_to_wav)
    monkeypatch.setattr("bort.audio.subprocess.Popen", fake_popen)
    monkeypatch.setattr("bort.audio.register_process", lambda _proc: True)
    monkeypatch.setattr("bort.audio.unregister_process", lambda _proc: None)
    monkeypatch.setattr("bort.audio._check_ffmpeg", lambda: None)

    events.clear()
    transcription_worker(params, events.append, abort_event=threading.Event())

    assert [event[0] for event in events if event[0] == "error"] == ["error"]
    temp_wav = Path(captured["cmd"][-1])
    assert not temp_wav.exists(), "halbe WAV bleibt nach Konvertierungsfehler liegen"
    assert not temp_wav.parent.exists(), "mkdtemp-Ordner bleibt nach Konvertierungsfehler liegen"


def _fake_ffmpeg(monkeypatch) -> dict[str, list[str]]:
    """Ersetzt ffmpeg durch einen Erfolgslauf und meldet den WAV-Zielpfad."""
    captured: dict[str, list[str]] = {}

    class FakeProcess:
        returncode = 0

        def communicate(self, timeout=None):
            Path(captured["cmd"][-1]).write_bytes(b"RIFF")
            return ("", "")

    def fake_popen(cmd, **_kwargs):
        captured["cmd"] = cmd
        return FakeProcess()

    monkeypatch.setattr("bort.audio.subprocess.Popen", fake_popen)
    monkeypatch.setattr("bort.audio.register_process", lambda _proc: True)
    monkeypatch.setattr("bort.audio.unregister_process", lambda _proc: None)
    monkeypatch.setattr("bort.audio._check_ffmpeg", lambda: None)
    return captured


def test_cli_removes_temp_wav_when_transcription_fails(tmp_path, monkeypatch) -> None:
    """Scheitert whisper-cli, darf die CLI keinen mkdtemp-Ordner zurücklassen."""
    audio = tmp_path / "sitzung.m4a"
    audio.write_bytes(b"x")
    captured = _fake_ffmpeg(monkeypatch)

    def boom(**_kwargs):
        raise TranscriptionError("whisper-cli nicht gefunden")

    monkeypatch.setattr("bort.cli.transcribe_whispercpp", boom)

    exit_code = main([
        str(audio),
        "--backend", "whispercpp",
        "--model", str(tmp_path / "model.bin"),
        "--output-dir", str(tmp_path / "out"),
    ])

    assert exit_code == 1
    temp_wav = Path(captured["cmd"][-1])
    assert not temp_wav.exists(), "WAV bleibt nach Fehllauf liegen"
    assert not temp_wav.parent.exists(), "mkdtemp-Ordner bleibt nach Fehllauf liegen"


def test_gui_worker_removes_temp_wav_when_transcription_fails(tmp_path, monkeypatch) -> None:
    """Gleicher Fehlerpfad im GUI-Worker: kein Ordner bleibt zurück."""
    from bort.gui import TranscriptionParams as GuiParams
    from bort.gui import transcription_worker as gui_worker

    audio = tmp_path / "sitzung.m4a"
    audio.write_bytes(b"x")
    captured = _fake_ffmpeg(monkeypatch)

    def boom(**_kwargs):
        raise TranscriptionError("whisper-cli nicht gefunden")

    monkeypatch.setattr("bort.gui.transcribe", boom)

    log_queue: queue.Queue = queue.Queue()
    gui_worker(
        GuiParams(
            audio_path=audio,
            marker_path=None,
            model_path=tmp_path / "model.bin",
            language=None,
            output_dir=tmp_path / "out",
            formats=["txt"],
            keep_wav=False,
            verbose=False,
            backend="whispercpp",
        ),
        log_queue,
    )

    messages = []
    while not log_queue.empty():
        messages.append(log_queue.get_nowait())
    assert any(msg[0] == "error" for msg in messages)
    temp_wav = Path(captured["cmd"][-1])
    assert not temp_wav.exists(), "WAV bleibt nach Fehllauf liegen"
    assert not temp_wav.parent.exists(), "mkdtemp-Ordner bleibt nach Fehllauf liegen"


def test_worker_keeps_wav_when_requested(tmp_path, monkeypatch) -> None:
    """keep_wav: weder Datei noch Zielordner werden aufgeräumt."""
    params = TranscriptionParams(
        audio_path=tmp_path / "session.wav",
        marker_path=None,
        model_path=tmp_path / "model.bin",
        language=None,
        output_dir=tmp_path,
        formats=["txt"],
        keep_wav=True,
        colocate=False,
    )
    abort = threading.Event()
    wav_path = tmp_path / "session_16k_mono.wav"

    def convert_and_abort(_audio, _out):
        wav_path.write_bytes(b"RIFF")
        abort.set()
        return wav_path

    monkeypatch.setattr("bort.controller.jobs.convert_to_wav", convert_and_abort)

    transcription_worker(params, [].append, abort_event=abort)

    assert wav_path.exists()
    assert tmp_path.is_dir()

"""Dry-run, nummerierte Familie und idempotenter Apply der Migration."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def _module() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "migrate_colocate.py"
    spec = importlib.util.spec_from_file_location("migrate_colocate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_migration_dry_run_then_apply_numbered_family(tmp_path: Path) -> None:
    migration = _module()
    transcripts = tmp_path / "transcripts"
    recordings = tmp_path / "recordings"
    old = transcripts / "2026-01-01"
    day = recordings / "2026-01-01"
    old.mkdir(parents=True)
    day.mkdir(parents=True)
    audio = day / "session.m4a"
    audio.write_bytes(b"audio")
    review = old / "session_1.review.json"
    review.write_text(
        json.dumps({"audio_path": str(audio), "base_name": "session_1"}),
        encoding="utf-8",
    )
    transcript = old / "session_1.txt"
    transcript.write_text("Text", encoding="utf-8")
    args = ["--transcripts", str(transcripts), "--recordings", str(recordings)]
    assert migration.main(args) == 0
    assert review.exists() and transcript.exists()
    assert not (day / "session.review.json").exists()
    assert migration.main([*args, "--apply"]) == 0
    assert not review.exists() and not transcript.exists()
    normalized = json.loads((day / "session.review.json").read_text(encoding="utf-8"))
    assert normalized["audio_path"] == str(audio)
    assert normalized["base_name"] == "session"
    assert (day / "session.txt").read_text(encoding="utf-8") == "Text"
    assert migration.main([*args, "--apply"]) == 0

"""Tests für Batch-Scan (unverarbeitete Audio+Marker-Paare finden)."""

import json
import os
import time
from pathlib import Path

from bort.batch import PendingItem, is_file_stable, scan_pending
from bort.controller.jobs import expected_artifacts


def test_scan_pending_finds_new_pair(tmp_path: Path) -> None:
    watch_dir, output_dir = tmp_path / "watch", tmp_path / "output"
    watch_dir.mkdir()
    output_dir.mkdir()
    audio_path = watch_dir / "2026-07-08_19-30_BoR_Session.m4a"
    audio_path.write_bytes(b"")
    marker_path = watch_dir / "2026-07-08_19-30_BoR_Session.json"
    marker_path.write_text(
        json.dumps({"version": 1, "file": audio_path.name, "markers": []}), encoding="utf-8"
    )
    assert scan_pending(watch_dir, output_dir) == [PendingItem(audio_path, marker_path)]


def test_scan_pending_excludes_already_processed(tmp_path: Path) -> None:
    watch_dir, output_dir = tmp_path / "watch", tmp_path / "output"
    watch_dir.mkdir()
    output_dir.mkdir()
    audio_path = watch_dir / "session.m4a"
    audio_path.write_bytes(b"")
    date_dir = output_dir / "2026-07-09"
    date_dir.mkdir()
    (date_dir / "session.txt").write_text("transcript", encoding="utf-8")
    assert scan_pending(watch_dir, output_dir) == []


def test_scan_pending_ignores_review_and_markers_sidecars_as_output(tmp_path: Path) -> None:
    watch_dir, output_dir = tmp_path / "watch", tmp_path / "output"
    watch_dir.mkdir()
    output_dir.mkdir()
    audio_path = watch_dir / "session.m4a"
    audio_path.write_bytes(b"")
    date_dir = output_dir / "2026-07-09"
    date_dir.mkdir()
    (date_dir / "session.markers.json").write_text("{}", encoding="utf-8")
    (date_dir / "session.review.json").write_text("{}", encoding="utf-8")
    assert scan_pending(watch_dir, output_dir) == [PendingItem(audio_path, None)]


def test_scan_pending_stale_output_does_not_mask_newer_audio(tmp_path: Path) -> None:
    watch_dir, output_dir = tmp_path / "watch", tmp_path / "output"
    watch_dir.mkdir()
    output_dir.mkdir()
    date_dir = output_dir / "2026-07-01"
    date_dir.mkdir()
    old_output = date_dir / "session.txt"
    old_output.write_text("alt", encoding="utf-8")
    old_time = time.time() - 3600
    os.utime(old_output, (old_time, old_time))
    audio_path = watch_dir / "session.m4a"
    audio_path.write_bytes(b"")
    assert scan_pending(watch_dir, output_dir) == [PendingItem(audio_path, None)]


def test_scan_pending_ignores_non_audio_files(tmp_path: Path) -> None:
    watch_dir, output_dir = tmp_path / "watch", tmp_path / "output"
    watch_dir.mkdir()
    output_dir.mkdir()
    (watch_dir / "session.json").write_text("{}", encoding="utf-8")
    (watch_dir / "notes.txt").write_text("hi", encoding="utf-8")
    assert scan_pending(watch_dir, output_dir) == []


def test_scan_pending_missing_watch_dir_returns_empty(tmp_path: Path) -> None:
    assert scan_pending(tmp_path / "does-not-exist", tmp_path / "output") == []


def test_expected_artifacts_matches_whisperx_worker() -> None:
    base = {
        "formats": ["txt", "md"],
        "backend": "whisperx",
        "auto_markers": True,
        "no_diarize": False,
    }
    assert expected_artifacts(base) == (
        ".txt", ".md", ".review.json", ".markers.json"
    )
    assert expected_artifacts({**base, "no_diarize": True}) == (
        ".txt", ".md", ".review.json"
    )


def test_scan_pending_colocate_requires_complete_current_family(tmp_path: Path) -> None:
    day = tmp_path / "2026-07-24"
    day.mkdir()
    audio = day / "aufnahme.m4a"
    audio.write_bytes(b"audio")
    settings = {
        "formats": ["txt"],
        "backend": "whisperx",
        "colocate": True,
        "auto_markers": True,
        "no_diarize": False,
    }
    (day / "aufnahme.txt").write_text("text")
    (day / "aufnahme.review.json").write_text("{}")
    assert scan_pending(tmp_path, tmp_path / "unused", settings) == [
        PendingItem(audio, None)
    ]
    (day / "aufnahme.markers.json").write_text("{}")
    assert scan_pending(tmp_path, tmp_path / "unused", settings) == []


def test_scan_pending_skips_symlink_directories(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "aufnahme.m4a").write_bytes(b"audio")
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    assert scan_pending(root, tmp_path / "output") == []


def test_is_file_stable_true_when_unchanged_across_samples(tmp_path: Path) -> None:
    path = tmp_path / "audio.m4a"
    path.write_bytes(b"1234")
    assert is_file_stable(path, interval=0.0, sleep_fn=lambda _: None) is True


def test_is_file_stable_false_when_size_changes_between_samples(tmp_path: Path) -> None:
    path = tmp_path / "audio.m4a"
    path.write_bytes(b"1234")
    calls = {"n": 0}

    def fake_sleep(_seconds: float) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            path.write_bytes(b"12345678")

    assert is_file_stable(path, interval=0.0, sleep_fn=fake_sleep) is False


def test_scan_pending_reads_output_listing_once_for_all_audios(
    tmp_path: Path, monkeypatch
) -> None:
    watch_dir, output_dir = tmp_path / "watch", tmp_path / "output"
    watch_dir.mkdir()
    output_dir.mkdir()
    for index in range(3):
        (watch_dir / f"session{index}.m4a").write_bytes(b"")
    (output_dir / "2026-08-27").mkdir()
    (output_dir / "2026-08-27" / "session1.txt").write_text("fertig", encoding="utf-8")
    settings = {"formats": ["txt"], "backend": "whispercpp", "colocate": False}

    rglob_calls = {"n": 0}
    real_rglob = Path.rglob

    def counting_rglob(self: Path, pattern: str):
        rglob_calls["n"] += 1
        return real_rglob(self, pattern)

    monkeypatch.setattr(Path, "rglob", counting_rglob)
    items = scan_pending(watch_dir, output_dir, settings)

    # session1 hat Output, die anderen beiden nicht; das output_dir-Listing
    # wird trotz drei Audios nur einmal geholt statt dreimal per rglob.
    assert [item.audio_path.name for item in items] == [
        "session0.m4a",
        "session2.m4a",
    ]
    assert rglob_calls["n"] == 1

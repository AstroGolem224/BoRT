"""Recovery-Wahrheitstabelle und Crash-Verhalten der Manifest-Transaktion."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from bort.speakers import SpeakerSegment
from bort.writers import recover_transactions, write_outputs

TXN = "a" * 32


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest(
    root: Path,
    *,
    had_predecessor: bool,
    staged: bytes = b"neu",
    predecessor: bytes = b"alt",
) -> Path:
    path = root / f".bort-txn-{TXN}.json"
    path.write_text(
        json.dumps({
            "schema_version": 1,
            "txn": TXN,
            "files": [{
                "final_name": "aufnahme.txt",
                "had_predecessor": had_predecessor,
                "staged_sha256": _hash(staged),
                "predecessor_sha256": _hash(predecessor) if had_predecessor else None,
            }],
        }),
        encoding="utf-8",
    )
    return path


def test_recovery_without_artifacts_does_not_create_lock(tmp_path: Path) -> None:
    recover_transactions(tmp_path)
    assert not (tmp_path / ".bort-lock").exists()


@pytest.mark.parametrize("target", [None, b"neu"])
def test_recovery_restores_valid_predecessor(tmp_path: Path, target: bytes | None) -> None:
    _manifest(tmp_path, had_predecessor=True)
    if target is not None:
        (tmp_path / "aufnahme.txt").write_bytes(target)
    (tmp_path / f"aufnahme.txt.{TXN}.bak").write_bytes(b"alt")
    recover_transactions(tmp_path)
    assert (tmp_path / "aufnahme.txt").read_bytes() == b"alt"
    assert not (tmp_path / f".bort-txn-{TXN}.json").exists()


def test_recovery_accepts_unpublished_predecessor(tmp_path: Path) -> None:
    _manifest(tmp_path, had_predecessor=True)
    (tmp_path / "aufnahme.txt").write_bytes(b"alt")
    recover_transactions(tmp_path)
    assert (tmp_path / "aufnahme.txt").read_bytes() == b"alt"
    assert not (tmp_path / f".bort-txn-{TXN}.json").exists()


@pytest.mark.parametrize("published", [False, True])
def test_recovery_removes_only_published_new_file(
    tmp_path: Path, published: bool
) -> None:
    _manifest(tmp_path, had_predecessor=False)
    if published:
        (tmp_path / "aufnahme.txt").write_bytes(b"neu")
    recover_transactions(tmp_path)
    assert not (tmp_path / "aufnahme.txt").exists()
    assert not (tmp_path / f".bort-txn-{TXN}.json").exists()


def test_recovery_conflict_leaves_everything_untouched(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, had_predecessor=True)
    target = tmp_path / "aufnahme.txt"
    target.write_bytes(b"extern")
    backup = tmp_path / f"aufnahme.txt.{TXN}.bak"
    backup.write_bytes(b"alt")
    recover_transactions(tmp_path)
    assert manifest.exists()
    assert target.read_bytes() == b"extern"
    assert backup.read_bytes() == b"alt"


def test_publish_crash_is_recovered_as_complete_set(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "aufnahme.txt").write_bytes(b"alt")
    real_replace = os.replace
    failed = False

    def fail_mid_publish(source: Path | str, target: Path | str) -> None:
        nonlocal failed
        source_path = Path(source)
        target_path = Path(target)
        if (
            not failed
            and source_path.name.endswith(".tmp")
            and target_path.name == "aufnahme.txt"
        ):
            failed = True
            raise OSError("simulierter Crash")
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_mid_publish)
    with pytest.raises(OSError, match="simulierter Crash"):
        write_outputs(
            [SpeakerSegment(0, 1, "SP1", "neu")],
            tmp_path,
            "aufnahme",
            ["txt"],
            review_data={"base_name": "aufnahme"},
            overwrite=True,
        )
    monkeypatch.setattr(os, "replace", real_replace)
    recover_transactions(tmp_path)
    assert (tmp_path / "aufnahme.txt").read_bytes() == b"alt"
    assert not (tmp_path / "aufnahme.review.json").exists()


def test_overwrite_publish_crash_recovers_srt_vtt_predecessors(
    tmp_path: Path, monkeypatch
) -> None:
    """Colocate-Transaktion akzeptiert .srt/.vtt-Mitglieder und rollt sie zurück."""
    (tmp_path / "aufnahme.srt").write_bytes(b"alt-srt")
    (tmp_path / "aufnahme.vtt").write_bytes(b"alt-vtt")
    real_replace = os.replace
    failed = False

    def fail_mid_publish(source: Path | str, target: Path | str) -> None:
        nonlocal failed
        if (
            not failed
            and Path(source).name.endswith(".tmp")
            and Path(target).name == "aufnahme.srt"
        ):
            failed = True
            raise OSError("simulierter Crash")
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_mid_publish)
    with pytest.raises(OSError, match="simulierter Crash"):
        write_outputs(
            [SpeakerSegment(0, 1, "SP1", "neu")],
            tmp_path,
            "aufnahme",
            ["srt", "vtt"],
            overwrite=True,
        )
    # Crash im Commit: die Final-Dateien liegen als Backups vor, Recovery
    # muss beide Vorgänger zurückstellen.
    monkeypatch.setattr(os, "replace", real_replace)
    reports = recover_transactions(tmp_path)
    assert any("zurückgesetzt" in report for report in reports)
    assert (tmp_path / "aufnahme.srt").read_bytes() == b"alt-srt"
    assert (tmp_path / "aufnahme.vtt").read_bytes() == b"alt-vtt"
    assert not list(tmp_path.glob(".bort-txn-*.json"))
    assert not list(tmp_path.glob("*.bak"))
    assert not list(tmp_path.glob("*.tmp"))


def test_recovery_treats_unpublished_vtt_as_valid_new_file(tmp_path: Path) -> None:
    """Manifest mit .vtt-Mitglied validiert und wird beim Recovery gelöscht."""
    manifest = _manifest(tmp_path, had_predecessor=False)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["files"][0]["final_name"] = "aufnahme.vtt"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    published = tmp_path / "aufnahme.vtt"
    published.write_bytes(b"neu")
    recover_transactions(tmp_path)
    assert not published.exists()
    assert not manifest.exists()

"""Tests für Ausgabeformate."""

import json
import tempfile
from datetime import datetime
from pathlib import Path

from bort.speakers import SpeakerSegment
from bort.writers import (
    _unique_base_name,
    write_csv,
    write_markdown,
    write_outputs,
    write_text,
)


def _today_subdir_name() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def test_write_text() -> None:
    segments = [
        SpeakerSegment(0.0, 5.0, "Alice", "Hallo"),
        SpeakerSegment(5.0, 10.0, "Bob", "Welt"),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "out.txt"
        write_text(segments, path)
        content = path.read_text(encoding="utf-8")
        assert "[00:00:00] Alice: Hallo" in content
        assert "[00:00:05] Bob: Welt" in content


def test_write_markdown() -> None:
    segments = [SpeakerSegment(0.0, 5.0, "Alice", "Hallo")]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "out.md"
        write_markdown(segments, path)
        content = path.read_text(encoding="utf-8")
        assert "# Transkript" in content
        assert "## Alice" in content
        assert "**00:00:00" in content


def test_write_csv() -> None:
    segments = [SpeakerSegment(1.5, 4.25, "Alice", "Hallo")]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "out.csv"
        write_csv(segments, path)
        content = path.read_text(encoding="utf-8")
        assert "start,end,speaker,type,text" in content
        assert "1.500,4.250,Alice,segment,Hallo" in content


def test_write_csv_with_bookmarks() -> None:
    from bort.markers import Bookmark

    segments = [SpeakerSegment(0.0, 5.0, "Alice", "Hallo")]
    bookmarks = [Bookmark(time=2.0, label="wichtig", type="note")]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "out.csv"
        write_csv(segments, path, bookmarks=bookmarks)
        content = path.read_text(encoding="utf-8")
        assert "bookmark" in content
        assert "wichtig" in content


def test_write_text_with_bookmarks() -> None:
    from bort.markers import Bookmark

    segments = [SpeakerSegment(0.0, 5.0, "Alice", "Hallo")]
    bookmarks = [Bookmark(time=2.0, label="notiz", type="note")]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "out.txt"
        write_text(segments, path, bookmarks=bookmarks)
        content = path.read_text(encoding="utf-8")
        assert "🔖" in content
        assert "notiz" in content


def test_write_text_bookmark_with_type() -> None:
    from bort.markers import Bookmark

    segments = [SpeakerSegment(0.0, 5.0, "Alice", "Hallo")]
    bookmarks = [Bookmark(time=2.0, type="highlight", color="red")]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "out.txt"
        write_text(segments, path, bookmarks=bookmarks)
        content = path.read_text(encoding="utf-8")
        assert "highlight" in content
        assert "[red]" in content


def test_write_outputs_creates_date_subdir() -> None:
    segments = [SpeakerSegment(0.0, 1.0, "Alice", "Hi")]
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = write_outputs(segments, Path(tmpdir), "test", ["txt", "md"])
        assert len(paths) == 2
        today = datetime.now().strftime("%Y-%m-%d")
        for path in paths:
            assert path.parent.name == today
            assert path.suffix in {".txt", ".md"}
            assert path.stem == "test"


def test_write_outputs_overwrite_replaces_existing_files(tmp_path: Path) -> None:
    segments = [SpeakerSegment(0.0, 1.0, "SP1", "Hallo")]
    first = write_outputs(segments, tmp_path, "session", ["txt"])
    updated = [SpeakerSegment(0.0, 1.0, "SP1", "Geändert")]
    second = write_outputs(updated, first[0].parent, "session", ["txt"], overwrite=True)
    assert second[0] == first[0]
    assert "Geändert" in second[0].read_text(encoding="utf-8")
    assert not (first[0].parent / "session_1.txt").exists()


def test_write_outputs_without_overwrite_creates_unique_name(tmp_path: Path) -> None:
    segments = [SpeakerSegment(0.0, 1.0, "SP1", "Hallo")]
    first = write_outputs(segments, tmp_path, "session", ["txt"])
    second = write_outputs(segments, tmp_path, "session", ["txt"])
    assert first[0] != second[0]
    assert second[0].name == "session_1.txt"


def _review_data(tmp_path: Path) -> dict:
    return {
        "schema_version": 1,
        "audio_path": str(tmp_path / "session.m4a"),
        "segments": [{"start": 0.0, "end": 1.0, "speaker": "SP1", "text": "Hallo"}],
        "speaker_map": {"SP1": "sprecher001"},
        "markers": [],
        "bookmarks": [],
        "base_name": "session",
        "formats": ["txt"],
    }


def test_write_outputs_with_review_data_writes_sidecar(tmp_path: Path) -> None:
    segments = [SpeakerSegment(0.0, 1.0, "SP1", "Hallo")]
    review_data = _review_data(tmp_path)
    paths = write_outputs(segments, tmp_path, "session", ["txt"], review_data=review_data)
    review_path = paths[0].parent / "session.review.json"
    assert review_path in paths
    assert json.loads(review_path.read_text(encoding="utf-8")) == review_data


def test_write_outputs_review_sidecar_base_name_matches_collision_name(tmp_path: Path) -> None:
    segments = [SpeakerSegment(0.0, 1.0, "SP1", "Hallo")]
    write_outputs(segments, tmp_path, "session", ["txt"])
    second = write_outputs(
        segments, tmp_path, "session", ["txt"], review_data=_review_data(tmp_path)
    )
    review_path = second[0].parent / "session_1.review.json"
    assert review_path in second
    assert json.loads(review_path.read_text(encoding="utf-8"))["base_name"] == "session_1"


def test_write_outputs_review_sidecar_failure_prevents_transcript_write(
    tmp_path: Path, monkeypatch
) -> None:
    segments = [SpeakerSegment(0.0, 1.0, "SP1", "Hallo")]
    real_open = Path.open

    def failing_open(self: Path, *args: object, **kwargs: object):
        if self.name == "session.review.json":
            raise OSError("Simulierter Schreibfehler")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)
    import pytest

    with pytest.raises(OSError):
        write_outputs(segments, tmp_path, "session", ["txt"], review_data=_review_data(tmp_path))
    assert not (tmp_path / _today_subdir_name() / "session.txt").exists()


def test_write_outputs_numbers_conflicts() -> None:
    segments = [SpeakerSegment(0.0, 1.0, "Alice", "Hi")]
    with tempfile.TemporaryDirectory() as tmpdir:
        today = datetime.now().strftime("%Y-%m-%d")
        date_dir = Path(tmpdir) / today
        date_dir.mkdir(parents=True, exist_ok=True)
        (date_dir / "test.txt").write_text("existing")

        paths = write_outputs(segments, Path(tmpdir), "test", ["txt", "md"])
        txt_path = next(p for p in paths if p.suffix == ".txt")
        md_path = next(p for p in paths if p.suffix == ".md")
        assert txt_path.stem == "test_1"
        assert md_path.stem == "test_1"


def test_unique_base_name() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        today = datetime.now().strftime("%Y-%m-%d")
        date_dir = Path(tmpdir) / today
        date_dir.mkdir(parents=True, exist_ok=True)
        (date_dir / "foo.txt").write_text("x")
        (date_dir / "foo_1.txt").write_text("x")
        assert _unique_base_name(date_dir, "foo", ["txt"]) == "foo_2"
        assert _unique_base_name(date_dir, "bar", ["txt"]) == "bar"

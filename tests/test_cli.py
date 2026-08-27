"""CLI-Format-Parser: --formats akzeptiert txt,md,csv,tsv,srt,vtt."""

import pytest

from bort.cli import DEFAULT_FORMATS, build_parser, parse_formats
from bort.writers import FORMATS


def test_parse_formats_accepts_all_registered_formats() -> None:
    names = parse_formats("txt,md,csv,tsv,srt,vtt")
    assert names == ["txt", "md", "csv", "tsv", "srt", "vtt"]
    assert all(name in FORMATS for name in names)


def test_parse_formats_is_case_insensitive_and_strips_whitespace() -> None:
    assert parse_formats(" TXT , Md ") == ["txt", "md"]


def test_parse_formats_deduplicates_and_keeps_order() -> None:
    assert parse_formats("txt,txt") == ["txt"]
    assert parse_formats("md,csv,md,txt,csv") == ["md", "csv", "txt"]


def test_parse_formats_keeps_empty_input_empty() -> None:
    assert parse_formats("") == []
    assert parse_formats(" , ,") == []


def test_parse_formats_rejects_unknown_formats() -> None:
    with pytest.raises(ValueError, match="exe"):
        parse_formats("txt,exe")


def test_default_formats_are_all_valid() -> None:
    assert parse_formats(",".join(DEFAULT_FORMATS)) == DEFAULT_FORMATS


def test_parser_passes_formats_flag_through() -> None:
    args = build_parser().parse_args(["audio.m4a", "--formats", "srt,vtt"])
    assert args.formats == "srt,vtt"

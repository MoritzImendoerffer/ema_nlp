"""The parser preference file and its reader (TASK-001 of work unit 27).

Until 2026-11-25 nothing read ``harness/configs/parser_preference.yaml`` (its header said
so). The build kept the first clean row per URL in cursor order, and a new parse never won.
"""

from pathlib import Path

import pytest

from harness.indexing.parser_preference import (
    PreferenceEntry,
    load_parser_preference,
    parse_entry,
    parse_preference,
)


def test_loads_shipped_file():
    pref = load_parser_preference()
    assert pref == {
        "application/pdf": [("pymupdf4llm", "legacy"), ("pymupdf4llm", None)],
        "text/html": [("trafilatura", None)],
    }


def test_entry_with_version_matches_that_version_only():
    entry = parse_entry("pymupdf4llm@legacy")
    assert entry == PreferenceEntry("pymupdf4llm", "legacy")
    assert entry.matches("pymupdf4llm", "legacy")
    # The defect decision D exists for: the byte parser writes the same name with
    # the installed version. The legacy entry must not match that row.
    assert not entry.matches("pymupdf4llm", "1.27.2.3")
    assert not entry.matches("trafilatura", "legacy")


def test_entry_without_version_matches_every_version():
    entry = parse_entry("trafilatura")
    assert entry == PreferenceEntry("trafilatura", None)
    assert entry.matches("trafilatura", "legacy")
    assert entry.matches("trafilatura", "2.0.0")
    assert not entry.matches("pymupdf4llm", "legacy")


@pytest.mark.parametrize(
    "raw",
    [
        ["pymupdf4llm"],  # top level is a list, not a mapping
        {"application/pdf": "pymupdf4llm"},  # value is not a list
        {"application/pdf": [""]},  # empty entry
        {"application/pdf": ["a@"]},  # version marker without a version
        {"application/pdf": ["@legacy"]},  # version without a name
    ],
)
def test_malformed_file_raises(raw):
    with pytest.raises(ValueError):
        parse_preference(raw)


def test_load_reads_a_given_path(tmp_path: Path):
    f = tmp_path / "pref.yaml"
    f.write_text("Application/PDF:\n  - b@2\n  - a\n", encoding="utf-8")
    assert load_parser_preference(f) == {"application/pdf": [("b", "2"), ("a", None)]}

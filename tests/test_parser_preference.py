"""Tests for the parser-preference YAML loader + --parser-preference overrides
(MIGR-009).
"""

from __future__ import annotations

import logging

import pytest

from harness.embed_pg import (
    _PREFERENCE_YAML,
    DEFAULT_PARSER_PREFERENCE,
    load_parser_preference,
)


def test_default_yaml_loads():
    """Real harness/configs/parser_preference.yaml maps to the documented defaults."""
    pref = load_parser_preference()
    assert pref["application/pdf"] == ["pymupdf4llm"]
    assert pref["text/html"] == ["trafilatura"]


def test_yaml_default_lives_on_disk():
    assert _PREFERENCE_YAML.exists()


def test_cli_override_replaces_yaml_default_for_one_content_type(tmp_path):
    pref = load_parser_preference(
        overrides=["application/pdf=llamahub_pdf"],
    )
    assert pref["application/pdf"] == ["llamahub_pdf"]
    # text/html still uses the YAML default
    assert pref["text/html"] == ["trafilatura"]


def test_multiple_overrides_apply_independently():
    pref = load_parser_preference(
        overrides=[
            "application/pdf=llamahub_pdf",
            "text/html=trafilatura_v2",
        ],
    )
    assert pref["application/pdf"] == ["llamahub_pdf"]
    assert pref["text/html"] == ["trafilatura_v2"]


def test_malformed_override_raises():
    with pytest.raises(ValueError, match="parser-preference"):
        load_parser_preference(overrides=["no-equals-sign"])


def test_empty_left_side_raises():
    with pytest.raises(ValueError):
        load_parser_preference(overrides=["=foo"])


def test_missing_yaml_falls_back_to_builtin_default(tmp_path, caplog):
    missing = tmp_path / "absent.yaml"
    with caplog.at_level(logging.WARNING, logger="harness.embed_pg"):
        pref = load_parser_preference(path=missing)
    assert pref == DEFAULT_PARSER_PREFERENCE
    assert any("parser_preference.yaml not found" in r.message for r in caplog.records)


def test_yaml_with_extra_keys_passes_through(tmp_path):
    custom = tmp_path / "pref.yaml"
    custom.write_text(
        "application/pdf:\n  - a\n  - b\ntext/html:\n  - c\nimage/png:\n  - d\n",
        encoding="utf-8",
    )
    pref = load_parser_preference(path=custom)
    assert pref["application/pdf"] == ["a", "b"]
    assert pref["text/html"] == ["c"]
    assert pref["image/png"] == ["d"]


def test_yaml_non_mapping_top_level_raises(tmp_path):
    custom = tmp_path / "bad.yaml"
    custom.write_text("- not a mapping\n- still not\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        load_parser_preference(path=custom)

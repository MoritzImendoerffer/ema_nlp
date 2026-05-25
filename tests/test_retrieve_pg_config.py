"""Unit tests for RetrievalConfigPG / PrefilterConfig / TraversalConfig (NARR-015).

These cover the YAML round-trip surface only; the retrieval functions
themselves (dense / BM25 / hybrid / traversal) arrive in NARR-016..-019 and
are exercised by tests/test_retrieve_pg.py (NARR-026)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from harness.retrieve_pg import (
    PrefilterConfig,
    RetrievalConfigPG,
    TraversalConfig,
)


def test_defaults_when_yaml_missing():
    cfg = RetrievalConfigPG.from_yaml_section(None)
    assert cfg.mode == "hybrid"
    assert cfg.k == 10
    assert cfg.prefilter.is_empty
    assert cfg.traversal.mode == "none"
    assert cfg.traversal.max_hops == 1
    assert cfg.traversal.link_types == ["hyperlink", "reference_number"]


def test_round_trip_full_section():
    raw = {
        "mode": "dense",
        "k": 25,
        "prefilter": {
            "topic_path_prefix": "/en/medicines/",
            "committee": ["CHMP", "PRAC"],
            "date_range": ["2020-01-01", "2024-12-31"],
        },
        "traversal": {
            "mode": "auto",
            "max_hops": 2,
            "link_types": ["hyperlink"],
        },
    }
    cfg = RetrievalConfigPG.from_yaml_section(raw)
    assert cfg.mode == "dense"
    assert cfg.k == 25
    assert cfg.prefilter.topic_path_prefix == "/en/medicines/"
    assert cfg.prefilter.committee == ["CHMP", "PRAC"]
    assert cfg.prefilter.date_range == (
        datetime(2020, 1, 1, tzinfo=UTC),
        datetime(2024, 12, 31, tzinfo=UTC),
    )
    assert cfg.traversal.mode == "auto"
    assert cfg.traversal.max_hops == 2
    assert cfg.traversal.link_types == ["hyperlink"]


def test_committee_scalar_promoted_to_list():
    cfg = RetrievalConfigPG.from_yaml_section({"prefilter": {"committee": "CHMP"}})
    assert cfg.prefilter.committee == ["CHMP"]


def test_link_types_scalar_promoted_to_list():
    cfg = RetrievalConfigPG.from_yaml_section({"traversal": {"mode": "auto", "link_types": "hyperlink"}})
    assert cfg.traversal.link_types == ["hyperlink"]


def test_bad_mode_rejected():
    with pytest.raises(ValueError):
        RetrievalConfigPG.from_yaml_section({"mode": "fulltext"})


def test_bad_k_rejected():
    with pytest.raises(ValueError):
        RetrievalConfigPG.from_yaml_section({"k": 0})


def test_bad_traversal_mode_rejected():
    with pytest.raises(ValueError):
        RetrievalConfigPG.from_yaml_section({"traversal": {"mode": "magic"}})


def test_date_range_inverted_rejected():
    with pytest.raises(ValueError):
        PrefilterConfig.from_dict({"date_range": ["2024-12-31", "2020-01-01"]})


def test_date_range_single_value_rejected():
    with pytest.raises(ValueError):
        PrefilterConfig.from_dict({"date_range": ["2024-01-01"]})


def test_prefilter_is_empty_when_unspecified():
    assert PrefilterConfig().is_empty is True
    assert PrefilterConfig(topic_path_prefix="/x/").is_empty is False
    assert PrefilterConfig(committee=["CHMP"]).is_empty is False


def test_traversal_negative_hops_rejected():
    with pytest.raises(ValueError):
        TraversalConfig.from_dict({"mode": "auto", "max_hops": -1})

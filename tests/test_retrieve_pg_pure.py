"""Pure-Python unit tests for harness/retrieve_pg.py.

These exercise the bits that don't need a live Postgres connection:
prefilter SQL composition, RRF fusion, and the topic-prefix wildcard rule.
The integration tests against a seeded DB live in tests/test_retrieve_pg.py
and arrive with NARR-026.
"""

from __future__ import annotations

from datetime import UTC, datetime

from harness.retrieve_pg import (
    PrefilterConfig,
    RetrievalConfigPG,
    _compose_bm25_prefilter,
    _compose_dense_prefilter,
    _compose_prefilter_fragments,
    _normalise_topic_prefix,
    _rrf_fuse,
)

# ---------------------------------------------------------------------------
# topic_path prefix normalisation
# ---------------------------------------------------------------------------


def test_topic_prefix_appends_wildcard_when_missing():
    assert _normalise_topic_prefix("/en/medicines/") == "/en/medicines/%"


def test_topic_prefix_keeps_existing_wildcard():
    assert _normalise_topic_prefix("/en/medicines/%") == "/en/medicines/%"


# ---------------------------------------------------------------------------
# _compose_prefilter_fragments / dense / bm25
# ---------------------------------------------------------------------------


def test_compose_empty_prefilter():
    clauses, params = _compose_prefilter_fragments(PrefilterConfig())
    assert clauses == []
    assert params == {}


def test_compose_committee_only():
    cfg = PrefilterConfig(committee=["CHMP", "PRAC"])
    clauses, params = _compose_prefilter_fragments(cfg)
    assert clauses == ["d.committee = ANY(%(committee)s)"]
    assert params == {"committee": ["CHMP", "PRAC"]}


def test_compose_all_three_filters():
    start = datetime(2020, 1, 1, tzinfo=UTC)
    end = datetime(2024, 12, 31, tzinfo=UTC)
    cfg = PrefilterConfig(
        topic_path_prefix="/en/medicines/",
        committee=["CHMP"],
        date_range=(start, end),
    )
    clauses, params = _compose_prefilter_fragments(cfg)
    assert clauses == [
        "d.topic_path LIKE %(topic_prefix)s",
        "d.committee = ANY(%(committee)s)",
        "d.last_updated BETWEEN %(date_start)s AND %(date_end)s",
    ]
    assert params == {
        "topic_prefix": "/en/medicines/%",
        "committee": ["CHMP"],
        "date_start": start,
        "date_end": end,
    }


def test_dense_prefilter_starts_with_where():
    cfg = PrefilterConfig(committee=["CHMP"])
    sql, _params = _compose_dense_prefilter(cfg)
    assert sql.startswith("WHERE ")


def test_dense_prefilter_empty_when_no_filter():
    sql, params = _compose_dense_prefilter(PrefilterConfig())
    assert sql == ""
    assert params == {}


def test_bm25_prefilter_starts_with_and():
    cfg = PrefilterConfig(committee=["CHMP"])
    sql, _params = _compose_bm25_prefilter(cfg)
    assert sql.startswith(" AND ")


def test_bm25_prefilter_empty_when_no_filter():
    sql, params = _compose_bm25_prefilter(PrefilterConfig())
    assert sql == ""
    assert params == {}


# ---------------------------------------------------------------------------
# _rrf_fuse
# ---------------------------------------------------------------------------


def test_rrf_fuse_orders_overlap_first():
    fused = _rrf_fuse(
        [
            [("a", 0.9, {}), ("b", 0.8, {})],
            [("b", 0.7, {}), ("c", 0.6, {})],
        ],
        k=10,
    )
    ids = [chunk_id for chunk_id, _score, _meta in fused]
    assert ids[0] == "b"  # appears in both lists → highest fused score
    assert set(ids) == {"a", "b", "c"}


def test_rrf_fuse_respects_k():
    ranked = [[(str(i), 1.0 / (i + 1), {}) for i in range(20)]]
    fused = _rrf_fuse(ranked, k=5)
    assert len(fused) == 5


def test_rrf_fuse_empty_inputs():
    assert _rrf_fuse([], k=5) == []
    assert _rrf_fuse([[], []], k=5) == []


def test_rrf_fuse_preserves_metadata_dict():
    fused = _rrf_fuse([[("a", 0.5, {"src": "dense"})], [("a", 0.3, {"src": "bm25"})]], k=1)
    # Second metadata wins (overwrites in-place) — match the documented behaviour
    # so callers know which dict identity they get back.
    assert fused[0][2]["src"] == "bm25"


# ---------------------------------------------------------------------------
# RetrievalConfigPG default propagation into retriever signature
# ---------------------------------------------------------------------------


def test_default_config_is_hybrid_k10_no_traversal_no_prefilter():
    cfg = RetrievalConfigPG()
    assert cfg.mode == "hybrid"
    assert cfg.k == 10
    assert cfg.prefilter.is_empty
    assert cfg.traversal.mode == "none"

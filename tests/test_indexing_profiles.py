"""Unit tests for harness.indexing — profile schema, loader, env switch, registries."""

from __future__ import annotations

import textwrap

import pytest

from harness.indexing import (
    build_index,
    build_retriever,
    load_index_profile,
    register_index,
    register_retriever,
    resolve_profile_name,
)
from harness.indexing.profiles import (
    ChunkingConfig,
    IndexConfig,
    IndexProfile,
    RetrievalConfig,
    ScopeConfig,
)
from harness.indexing.registry import INDEX_BUILDERS, RETRIEVER_BUILDERS

# ── shipped default profile parses correctly ────────────────────────────────

def test_default_profile_parses():
    p = load_index_profile("neo4j_hier")
    assert p.name == "neo4j_hier"
    assert p.index.kind == "property_graph"
    assert p.index.store.graph == "neo4j"
    assert p.index.chunking.parser == "hierarchical"
    assert p.index.chunking.chunk_sizes == [2048, 512, 128]
    assert p.index.scope.limit == 50
    assert p.retrieval.strategy == "hierarchical"
    assert p.retrieval.merge is True
    assert p.retrieval.graph.edge_types == ["links_to"]


# ── profile-name resolution: explicit > env > default ───────────────────────

def test_resolve_profile_name(monkeypatch):
    monkeypatch.delenv("EMA_INDEX_PROFILE", raising=False)
    assert resolve_profile_name() == "neo4j_hier"
    monkeypatch.setenv("EMA_INDEX_PROFILE", "some_other")
    assert resolve_profile_name() == "some_other"
    assert resolve_profile_name("explicit") == "explicit"  # arg wins over env


def test_env_selects_profile(monkeypatch):
    monkeypatch.setenv("EMA_INDEX_PROFILE", "neo4j_hier")
    assert load_index_profile().name == "neo4j_hier"


def test_unknown_profile_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="not found"):
        load_index_profile("does_not_exist", profile_dir=tmp_path)


def test_load_from_custom_dir(tmp_path):
    (tmp_path / "tiny.yaml").write_text(
        textwrap.dedent(
            """
            index:
              kind: property_graph
              chunking: {parser: hierarchical, chunk_sizes: [512, 128]}
              scope: {limit: 5}
            retrieval: {strategy: hierarchical, k: 3}
            """
        ),
        encoding="utf-8",
    )
    p = load_index_profile("tiny", profile_dir=tmp_path)
    assert p.index.chunking.chunk_sizes == [512, 128]
    assert p.index.scope.limit == 5
    assert p.retrieval.k == 3


# ── scope / chunking parsing edge cases ─────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [(0, None), ("", None), (None, None), (10, 10)])
def test_scope_limit_normalisation(raw, expected):
    assert ScopeConfig.from_dict({"limit": raw}).limit == expected


def test_scope_committee_str_to_list():
    assert ScopeConfig.from_dict({"committee": "CHMP"}).committee == ["CHMP"]


def test_chunking_rejects_nonpositive_sizes():
    with pytest.raises(ValueError, match="positive"):
        ChunkingConfig.from_dict({"chunk_sizes": [512, 0]})


def test_retrieval_rejects_bad_k():
    with pytest.raises(ValueError, match="k must be"):
        RetrievalConfig.from_dict({"k": 0})


# ── registry dispatch ───────────────────────────────────────────────────────

@pytest.fixture
def clean_registries():
    idx, retr = dict(INDEX_BUILDERS), dict(RETRIEVER_BUILDERS)
    yield
    INDEX_BUILDERS.clear()
    INDEX_BUILDERS.update(idx)
    RETRIEVER_BUILDERS.clear()
    RETRIEVER_BUILDERS.update(retr)


def _minimal_profile(kind="__test_kind__", strategy="__test_strat__") -> IndexProfile:
    return IndexProfile(
        name="t",
        index=IndexConfig(kind=kind),
        retrieval=RetrievalConfig(strategy=strategy),
    )


def test_register_and_dispatch_index(clean_registries):
    @register_index("__test_kind__")
    def _build(profile, **kw):
        return ("built", profile.index.kind, kw)

    out = build_index(_minimal_profile(), foo=1)
    assert out == ("built", "__test_kind__", {"foo": 1})


def test_register_and_dispatch_retriever(clean_registries):
    @register_retriever("__test_strat__")
    def _build(profile, index, **kw):
        return ("retr", index, profile.retrieval.strategy)

    out = build_retriever(_minimal_profile(), index="IDX")
    assert out == ("retr", "IDX", "__test_strat__")


def test_unregistered_index_kind_raises():
    # 'property_graph' builder is not registered until LIR-007.
    with pytest.raises(NotImplementedError, match="property_graph"):
        build_index(_minimal_profile(kind="property_graph"))


def test_unregistered_retriever_raises():
    with pytest.raises(NotImplementedError, match="hierarchical"):
        build_retriever(_minimal_profile(strategy="hierarchical"), index=None)

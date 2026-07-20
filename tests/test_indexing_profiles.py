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
    GraphRetrievalConfig,
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
    # The SHIPPED default must be the full corpus — a checked-in cap silently
    # shrinks a rebuild to a toy graph (F11). CPU-iteration caps belong in an
    # $EMA_CONFIG_DIR override profile.
    assert p.index.scope.limit is None
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


# ── graph link_context / document_type filter knobs (link-extraction upgrade) ─

def test_graph_link_contexts_defaults():
    g = GraphRetrievalConfig.from_dict({})
    assert g.link_contexts == ["file_component", "card_or_listing", "inline"]
    assert g.document_types == []
    assert g.edge_types == ["links_to"]  # unchanged


def test_graph_link_contexts_and_document_types_override():
    g = GraphRetrievalConfig.from_dict(
        {"link_contexts": ["file_component"], "document_types": ["scientific-guideline"]}
    )
    assert g.link_contexts == ["file_component"]
    assert g.document_types == ["scientific-guideline"]


def test_graph_rejects_unknown_link_context():
    with pytest.raises(ValueError, match="unknown"):
        GraphRetrievalConfig.from_dict({"link_contexts": ["bogus"]})


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
    # 'property_graph' is now registered (LIR-007); an unknown kind still raises.
    with pytest.raises(NotImplementedError, match="flat_faiss"):
        build_index(_minimal_profile(kind="flat_faiss"))


def test_unregistered_retriever_raises():
    with pytest.raises(NotImplementedError, match="bm25"):
        build_retriever(_minimal_profile(strategy="bm25"), index=None)


# ── $EMA_CONFIG_DIR override (F9) ────────────────────────────────────────────

def test_load_index_profile_honors_ema_config_dir(tmp_path, monkeypatch):
    external = tmp_path / "index"
    external.mkdir()
    (external / "neo4j_hier.yaml").write_text(
        textwrap.dedent(
            """
            index:
              kind: property_graph
              scope: {limit: 7}
            retrieval:
              strategy: hierarchical
              k: 4
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EMA_CONFIG_DIR", str(tmp_path))
    p = load_index_profile("neo4j_hier")  # external shadows the built-in
    assert p.index.scope.limit == 7
    assert p.retrieval.k == 4

    monkeypatch.delenv("EMA_CONFIG_DIR")
    assert load_index_profile("neo4j_hier").index.scope.limit is None  # built-in again


def test_load_index_profile_unknown_lists_available(monkeypatch):
    monkeypatch.delenv("EMA_CONFIG_DIR", raising=False)
    with pytest.raises(FileNotFoundError, match="neo4j_hier"):
        load_index_profile("does_not_exist")


# ── source-category steering keys (Options A + B) ────────────────────────────


def _load_retrieval(tmp_path, retrieval_yaml: str):
    (tmp_path / "steer.yaml").write_text(
        textwrap.dedent(f"index: {{kind: property_graph}}\nretrieval:\n{retrieval_yaml}"),
        encoding="utf-8",
    )
    return load_index_profile("steer", profile_dir=tmp_path).retrieval


def test_steering_defaults_are_off():
    r = load_index_profile("neo4j_hier").retrieval
    assert r.oversample == 4
    assert r.category_quota == {}
    assert r.graph.expand is False


def test_steered_profile_parses():
    r = load_index_profile("neo4j_steered").retrieval
    assert r.category_quota == {"scientific_guideline": 2, "qa": 1}
    assert r.graph.expand is True
    assert r.graph.expand_categories == ["scientific_guideline", "qa"]
    assert r.graph.max_expand == 3


def test_quota_and_expansion_keys_parse(tmp_path):
    r = _load_retrieval(
        tmp_path,
        """\
  k: 8
  oversample: 6
  category_quota: {qa: 2}
  graph: {expand: true, expand_categories: [epar], max_expand: 5}
""",
    )
    assert r.oversample == 6
    assert r.category_quota == {"qa": 2}
    assert r.graph.expand_categories == ["epar"] and r.graph.max_expand == 5


def test_quota_unknown_category_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown"):
        _load_retrieval(tmp_path, "  category_quota: {bogus: 1}\n")


def test_quota_total_over_k_rejected(tmp_path):
    with pytest.raises(ValueError, match="exceeds"):
        _load_retrieval(tmp_path, "  k: 3\n  category_quota: {qa: 2, epar: 2}\n")


def test_oversample_must_be_positive(tmp_path):
    with pytest.raises(ValueError, match="oversample"):
        _load_retrieval(tmp_path, "  oversample: 0\n")


def test_expand_categories_validated(tmp_path):
    with pytest.raises(ValueError, match="unknown"):
        _load_retrieval(tmp_path, "  graph: {expand: true, expand_categories: [bogus]}\n")


def test_expand_requires_hops(tmp_path):
    with pytest.raises(ValueError, match="max_hops"):
        _load_retrieval(tmp_path, "  graph: {expand: true, max_hops: 0}\n")


def test_graph_ancestor_keys_parse_and_default_off():
    g = GraphRetrievalConfig.from_dict({})
    assert g.ancestors is False and g.max_ancestors == 3
    g2 = GraphRetrievalConfig.from_dict({"ancestors": True, "max_ancestors": 5})
    assert g2.ancestors is True and g2.max_ancestors == 5


def test_graph_rejects_nonpositive_max_ancestors():
    import pytest

    with pytest.raises(ValueError, match="max_ancestors"):
        GraphRetrievalConfig.from_dict({"max_ancestors": 0})

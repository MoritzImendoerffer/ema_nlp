"""Unit tests for harness.retrieval (config-driven pipeline: transforms + rerank).

Offline: a fake BaseRetriever and a fake BaseNodePostprocessor exercise the seam;
the real cross-encoder/LLM rerankers register behind lazy imports and are not
constructed here.
"""

from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

from harness.retrieval import (
    RetrievalPipelineConfig,
    build_postprocessors,
    get_transform,
    list_postprocessors,
    list_transforms,
    load_pipeline_config,
    register_postprocessor,
    run_retrieval,
)
from harness.retrieval.postprocessors import apply_postprocessors


class _QueryEchoRetriever(BaseRetriever):
    """Returns one node whose id == the query string (lets us test dedup/merge)."""

    def __init__(self):
        super().__init__()

    def _retrieve(self, query_bundle: QueryBundle):
        q = query_bundle.query_str
        return [NodeWithScore(node=TextNode(text=q, id_=q, metadata={"source_url": q}), score=1.0)]


class _ReverseRerank(BaseNodePostprocessor):
    """Fake postprocessor: reverses node order (tests stage application)."""

    def _postprocess_nodes(self, nodes, query_bundle=None):
        return list(reversed(nodes))


@register_postprocessor("reverse_test")
def _build_reverse(**_):
    return _ReverseRerank()


# --- registries -------------------------------------------------------------


def test_builtin_transforms_registered():
    names = list_transforms()
    assert "none" in names
    assert "acronym" in names
    assert "llm_rewrite" in names


def test_builtin_postprocessors_registered():
    names = list_postprocessors()
    assert "cross_encoder" in names
    assert "llm_sme" in names


def test_unknown_transform_raises():
    try:
        get_transform("nope")
    except ValueError as exc:
        assert "Unknown query transform" in str(exc)
    else:
        raise AssertionError("expected ValueError")


# --- transforms -------------------------------------------------------------


def test_identity_transform():
    assert get_transform("none")("what is the AI for NDMA?") == ["what is the AI for NDMA?"]


def test_acronym_transform_expands_known_token():
    transform = get_transform("acronym", acronyms={"AI": "Acceptable Intake"})
    variants = transform("what is the AI for NDMA")
    assert variants == ["what is the AI for NDMA", "what is the Acceptable Intake for NDMA"]


def test_acronym_transform_no_match_returns_single():
    transform = get_transform("acronym", acronyms={"AI": "Acceptable Intake"})
    assert transform("nitrosamine limit") == ["nitrosamine limit"]


def test_llm_rewrite_requires_llm():
    try:
        get_transform("llm_rewrite")
    except ValueError as exc:
        assert "llm" in str(exc)
    else:
        raise AssertionError("expected ValueError")


# --- postprocessors ---------------------------------------------------------


def test_build_postprocessors_skips_none():
    assert build_postprocessors(["none", "off", ""]) == []


def test_build_and_apply_postprocessor():
    pps = build_postprocessors(["reverse_test"])
    assert len(pps) == 1
    nodes = [
        NodeWithScore(node=TextNode(text="a", id_="a"), score=0.1),
        NodeWithScore(node=TextNode(text="b", id_="b"), score=0.2),
    ]
    out = apply_postprocessors(nodes, pps, query="q")
    assert [n.node.node_id for n in out] == ["b", "a"]


# --- pipeline ---------------------------------------------------------------


def test_run_retrieval_dedupes_across_query_variants():
    # transform yields a duplicate variant -> same node id -> deduped to one
    out = run_retrieval(
        _QueryEchoRetriever(),
        query="q",
        transform=lambda q: [q, q],
    )
    assert len(out) == 1


def test_run_retrieval_merges_distinct_variants_then_reranks():
    out = run_retrieval(
        _QueryEchoRetriever(),
        query="q1",
        transform=lambda _q: ["q1", "q2"],
        postprocessors=[_ReverseRerank()],
    )
    assert [n.node.node_id for n in out] == ["q2", "q1"]


# --- config -----------------------------------------------------------------


def test_load_native_pipeline_config():
    cfg = load_pipeline_config("native")
    assert isinstance(cfg, RetrievalPipelineConfig)
    assert cfg.query_transform == "acronym"
    assert cfg.rerank == ["cross_encoder"]
    assert cfg.rerank_top_n == 8
    # The dead sub_retrievers/graph_mode/k fields were removed outright (F8):
    # the config holds exactly what assemble_agent wires, nothing declared-only.
    assert not hasattr(cfg, "sub_retrievers")
    assert not hasattr(cfg, "graph_mode")
    assert not hasattr(cfg, "k")


def test_resolved_attributes_only_stamps_active_stages():
    cfg = load_pipeline_config("native")
    attrs = cfg.resolved_attributes()
    assert attrs["ema.retrieval.query_transform"] == "acronym"
    assert attrs["ema.retrieval.rerank"] == "cross_encoder"
    # The trace never advertises a retrieval stage that didn't run (F8: the
    # formerly-declared-but-unwired knobs no longer exist at all).
    assert "ema.retrieval.graph_mode" not in attrs
    assert "ema.retrieval.sub_retrievers" not in attrs
    assert "ema.retrieval.k" not in attrs


def test_resolved_attributes_empty_rerank_is_explicit_none():
    cfg = RetrievalPipelineConfig(profile="x", rerank=[])
    attrs = cfg.resolved_attributes()
    assert attrs["ema.retrieval.rerank"] == "none"


# --- doc_type_priority postprocessor (deterministic source-type reorder) -----


def _fake_node(url, score, category=None):
    from llama_index.core.schema import NodeWithScore, TextNode

    meta = {"source_url": url}
    if category:
        meta["category"] = category
    return NodeWithScore(node=TextNode(text="x", metadata=meta), score=score)


def test_doc_type_priority_floats_guideline_above_higher_scoring_epar():
    from harness.retrieval.postprocessors import get_postprocessor

    epar = _fake_node("https://ema.eu/documents/assessment-report/x-epar-public-assessment-report.pdf", 0.95)
    guideline = _fake_node("https://ema.eu/documents/scientific-guideline/ich-q3a.pdf", 0.80)
    qa = _fake_node("https://ema.eu/x/questions-answers-nitrosamines", 0.90)

    pp = get_postprocessor("doc_type_priority", doc_type_priority=["scientific_guideline", "qa", "epar"])
    out = pp.postprocess_nodes([epar, qa, guideline])
    urls = [n.node.metadata["source_url"] for n in out]
    assert "scientific-guideline" in urls[0]
    assert "questions-answers" in urls[1]
    assert "assessment-report" in urls[2]


def test_doc_type_priority_stable_within_category_and_unknown_last():
    from harness.retrieval.postprocessors import get_postprocessor

    g1 = _fake_node("https://ema.eu/documents/scientific-guideline/a.pdf", 0.9)
    g2 = _fake_node("https://ema.eu/documents/scientific-guideline/b.pdf", 0.7)
    misc = _fake_node("https://example.org/unrelated", 0.99)  # category "other" → last

    pp = get_postprocessor("doc_type_priority", doc_type_priority=["scientific_guideline"])
    out = pp.postprocess_nodes([misc, g1, g2])
    urls = [n.node.metadata["source_url"] for n in out]
    assert urls == [g1.node.metadata["source_url"], g2.node.metadata["source_url"],
                    misc.node.metadata["source_url"]]


def test_doc_type_priority_prefers_precomputed_category_metadata():
    from harness.retrieval.postprocessors import get_postprocessor

    # metadata["category"] (set by the live retriever) wins over URL heuristics
    tagged = _fake_node("https://example.org/whatever", 0.5, category="qa")
    other = _fake_node("https://example.org/other", 0.9)
    pp = get_postprocessor("doc_type_priority", doc_type_priority=["qa"])
    out = pp.postprocess_nodes([other, tagged])
    assert out[0].node.metadata["source_url"].endswith("/whatever")


def test_pipeline_config_validates_doc_type_priority(tmp_path):
    import textwrap

    import pytest

    bad = tmp_path / "bad.yaml"
    bad.write_text(textwrap.dedent(
        """
        retrieval:
          rerank: [doc_type_priority]
          doc_type_priority: [guidelines]
        """
    ), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown categor"):
        load_pipeline_config("bad", config_dir=tmp_path)

    good = tmp_path / "good.yaml"
    good.write_text(textwrap.dedent(
        """
        retrieval:
          rerank: [doc_type_priority]
          doc_type_priority: [scientific_guideline, qa]
        """
    ), encoding="utf-8")
    cfg = load_pipeline_config("good", config_dir=tmp_path)
    assert cfg.doc_type_priority == ["scientific_guideline", "qa"]
    attrs = cfg.resolved_attributes()
    assert attrs["ema.retrieval.doc_type_priority"] == "scientific_guideline,qa"

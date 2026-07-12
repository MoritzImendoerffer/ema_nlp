"""Unit tests for harness.tools (registry, resolve_substance, ema_search).

Offline: resolve_substance uses an injected fake fetcher; ema_search uses a fake
BaseRetriever. No network, no Neo4j.
"""

from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode
from llama_index.core.tools import FunctionTool

from harness.tools import build_tools, get_tool, list_tools
from harness.tools.search import format_nodes
from harness.tools.substance import parse_pubchem, resolve_substance

# --- fixtures ---------------------------------------------------------------

_PUBCHEM_PAYLOAD = {
    "properties": {
        "PropertyTable": {
            "Properties": [
                {"CID": 6124, "MolecularWeight": "74.05", "IUPACName": "N-methyl-N-nitrosomethanamine"}
            ]
        }
    },
    "synonyms": {
        "InformationList": {
            "Information": [{"CID": 6124, "Synonym": ["N-Nitrosodimethylamine", "62-75-9", "NDMA"]}]
        }
    },
}


class _FakeRetriever(BaseRetriever):
    def __init__(self):
        super().__init__()

    def _retrieve(self, query_bundle: QueryBundle):
        return [
            NodeWithScore(
                node=TextNode(
                    text="The AI for NDMA is 96 ng/day.",
                    metadata={"source_url": "https://ema.europa.eu/ndma", "doc_id": "d1"},
                ),
                score=0.91,
            )
        ]


# --- registry ---------------------------------------------------------------


def test_registry_lists_builtin_tools():
    assert list_tools() == ["corrective_search", "ema_search", "resolve_substance"]


def test_get_unknown_tool_raises():
    try:
        get_tool("does_not_exist")
    except ValueError as exc:
        assert "Unknown tool" in str(exc)
    else:
        raise AssertionError("expected ValueError")


# --- resolve_substance ------------------------------------------------------


def test_parse_pubchem_extracts_cas_mw_synonyms():
    sub = parse_pubchem("NDMA", _PUBCHEM_PAYLOAD)
    assert sub.cas == "62-75-9"
    assert sub.molecular_weight == 74.05
    assert "NDMA" in sub.synonyms
    assert sub.source == "pubchem"
    assert sub.found is True


def test_resolve_substance_with_fake_fetcher():
    sub = resolve_substance("NDMA", fetcher=lambda _q: _PUBCHEM_PAYLOAD)
    assert sub.cas == "62-75-9"


def test_resolve_substance_handles_fetch_failure():
    def _boom(_q):
        raise RuntimeError("network down")

    sub = resolve_substance("NDMA", fetcher=_boom)
    assert sub.found is False
    assert sub.cas == ""


def test_resolve_substance_tool_is_functiontool_and_runs():
    tool = get_tool("resolve_substance", fetcher=lambda _q: _PUBCHEM_PAYLOAD)
    assert isinstance(tool, FunctionTool)
    assert tool.metadata.name == "resolve_substance"
    out = tool.call(substance_name="NDMA")
    assert "62-75-9" in str(out)


# --- ema_search -------------------------------------------------------------


def test_format_nodes_renders_sources():
    rendered = format_nodes(_FakeRetriever()._retrieve(QueryBundle(query_str="x")))
    assert "ema.europa.eu/ndma" in rendered
    assert "0.910" in rendered


def test_ema_search_requires_retriever():
    try:
        get_tool("ema_search")
    except ValueError as exc:
        assert "retriever" in str(exc)
    else:
        raise AssertionError("expected ValueError when no retriever supplied")


def test_ema_search_tool_runs_over_fake_retriever():
    tool = get_tool("ema_search", retriever=_FakeRetriever())
    assert tool.metadata.name == "ema_search"
    out = tool.call(query="ndma acceptable intake")
    assert "ema.europa.eu/ndma" in str(out)


def test_capture_search_nodes_collects_retrieved_nodes():
    from harness.tools.search import capture_search_nodes

    tool = get_tool("ema_search", retriever=_FakeRetriever())
    with capture_search_nodes() as sink:
        tool.call(query="q1")
        tool.call(query="q2")
    # both calls' nodes accumulate; metadata is the real node provenance
    assert len(sink) == 2
    assert sink[0].node.metadata["doc_id"] == "d1"
    assert sink[0].score == 0.91


def test_ema_search_without_capture_scope_is_inert():
    # No active sink -> the tool still returns its string, no error.
    tool = get_tool("ema_search", retriever=_FakeRetriever())
    assert "ema.europa.eu/ndma" in str(tool.call(query="q"))


def test_build_tools_heterogeneous_kwargs():
    tools = build_tools(
        ["ema_search", "resolve_substance"],
        retriever=_FakeRetriever(),
        fetcher=lambda _q: _PUBCHEM_PAYLOAD,
    )
    assert {t.metadata.name for t in tools} == {"ema_search", "resolve_substance"}


# --- ema_search source-category steering -------------------------------------


class _SteerableFakeRetriever(BaseRetriever):
    """Fake with the ``with_categories`` seam: records the filter it was given."""

    def __init__(self, categories=None, results=None):
        self.categories = categories
        self.filter_calls: list = []
        self._results = results
        super().__init__()

    def with_categories(self, categories):
        self.filter_calls.append(categories)
        clone = _SteerableFakeRetriever(categories=categories, results=self._results)
        clone.filter_calls = self.filter_calls  # share the recorder
        return clone

    def _retrieve(self, query_bundle: QueryBundle):
        if self._results is not None:
            return list(self._results)
        nodes = [
            NodeWithScore(
                node=TextNode(
                    text="EPAR passage",
                    metadata={"source_url": "https://ema.europa.eu/epar", "category": "epar"},
                ),
                score=0.9,
            ),
            NodeWithScore(
                node=TextNode(
                    text="Guideline passage",
                    metadata={"source_url": "https://ema.europa.eu/gl", "category": "scientific_guideline"},
                ),
                score=0.8,
            ),
        ]
        if self.categories:
            nodes = [n for n in nodes if n.node.metadata["category"] in self.categories]
        return nodes


def test_ema_search_source_category_filters_and_notes():
    retriever = _SteerableFakeRetriever()
    tool = get_tool("ema_search", retriever=retriever)
    out = str(tool.call(query="q", source_category="scientific_guideline"))
    assert retriever.filter_calls == [["scientific_guideline"]]
    assert "[category filter: scientific_guideline]" in out
    assert "Guideline passage" in out and "EPAR passage" not in out


def test_ema_search_invalid_category_returns_vocabulary_error():
    tool = get_tool("ema_search", retriever=_SteerableFakeRetriever())
    out = str(tool.call(query="q", source_category="guidelines"))
    assert "Unknown source categor" in out
    assert "scientific_guideline" in out  # the agent can self-correct from this


def test_ema_search_empty_filter_falls_back_unfiltered():
    retriever = _SteerableFakeRetriever()
    tool = get_tool("ema_search", retriever=retriever)
    out = str(tool.call(query="q", source_category="qa"))  # fake has no qa nodes
    assert "retried unfiltered" in out
    assert "EPAR passage" in out and "Guideline passage" in out


def test_ema_search_filter_unsupported_retriever_degrades_honestly():
    out = str(
        get_tool("ema_search", retriever=_FakeRetriever()).call(
            query="q", source_category="qa"
        )
    )
    assert "not supported" in out
    assert "ema.europa.eu/ndma" in out  # unfiltered results still returned


def test_ema_search_router_prefer_reorders_with_note():
    from harness.retrieval.routing import QueryRouter, RoutingRule

    router = QueryRouter(
        [RoutingRule(name="r1", keywords=("impurity",), categories=("scientific_guideline",))]
    )
    tool = get_tool("ema_search", retriever=_SteerableFakeRetriever(), router=router)
    out = str(tool.call(query="impurity limits"))
    assert "[routing: rule 'r1' -> prefer scientific_guideline]" in out
    # guideline floated above the higher-scoring EPAR hit
    assert out.index("Guideline passage") < out.index("EPAR passage")


def test_ema_search_router_filter_mode_restricts():
    from harness.retrieval.routing import QueryRouter, RoutingRule

    router = QueryRouter(
        [RoutingRule(name="r1", keywords=("impurity",), categories=("epar",), mode="filter")]
    )
    retriever = _SteerableFakeRetriever()
    out = str(get_tool("ema_search", retriever=retriever, router=router).call(query="impurity"))
    assert retriever.filter_calls == [["epar"]]
    assert "EPAR passage" in out and "Guideline passage" not in out


def test_ema_search_explicit_category_beats_router():
    from harness.retrieval.routing import QueryRouter, RoutingRule

    router = QueryRouter(
        [RoutingRule(name="r1", keywords=("impurity",), categories=("epar",), mode="filter")]
    )
    retriever = _SteerableFakeRetriever()
    tool = get_tool("ema_search", retriever=retriever, router=router)
    out = str(tool.call(query="impurity", source_category="scientific_guideline"))
    assert retriever.filter_calls == [["scientific_guideline"]]  # router never consulted
    assert "routing:" not in out


def test_ema_search_no_router_no_category_is_plain():
    out = str(get_tool("ema_search", retriever=_SteerableFakeRetriever()).call(query="q"))
    assert "routing:" not in out and "category filter" not in out  # no steering note
    assert "EPAR passage" in out and "Guideline passage" in out


def test_format_nodes_shows_category_and_expansion_origin():
    nodes = [
        NodeWithScore(
            node=TextNode(
                text="linked guideline",
                metadata={
                    "source_url": "https://ema.europa.eu/gl",
                    "category": "scientific_guideline",
                    "retrieval_origin": "link_expansion",
                },
            ),
            score=0.7,
        )
    ]
    rendered = format_nodes(nodes)
    assert "category=scientific_guideline" in rendered
    assert "via=link_expansion" in rendered

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
    assert list_tools() == ["ema_search", "resolve_substance"]


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


def test_build_tools_heterogeneous_kwargs():
    tools = build_tools(
        ["ema_search", "resolve_substance"],
        retriever=_FakeRetriever(),
        fetcher=lambda _q: _PUBCHEM_PAYLOAD,
    )
    assert {t.metadata.name for t in tools} == {"ema_search", "resolve_substance"}

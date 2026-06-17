"""Unit tests for the ema_search tool wired to the retrieval pipeline."""

from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

from harness.tools import get_tool


class _QueryEcho(BaseRetriever):
    """One node whose id/source == the query string."""

    def __init__(self):
        super().__init__()

    def _retrieve(self, query_bundle: QueryBundle):
        q = query_bundle.query_str
        return [NodeWithScore(node=TextNode(text=q, id_=q, metadata={"source_url": q}), score=1.0)]


class _Reverse(BaseNodePostprocessor):
    def _postprocess_nodes(self, nodes, query_bundle=None):
        return list(reversed(nodes))


def test_ema_search_plain_retrieve():
    tool = get_tool("ema_search", retriever=_QueryEcho())
    out = str(tool.call(query="hello"))
    assert "source=hello" in out


def test_ema_search_runs_pipeline_when_transform_or_rerank_supplied():
    tool = get_tool(
        "ema_search",
        retriever=_QueryEcho(),
        transform=lambda _q: ["orig", "variant2"],
        postprocessors=[_Reverse()],
    )
    out = str(tool.call(query="orig"))
    assert "source=orig" in out
    assert "source=variant2" in out

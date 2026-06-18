"""Unit tests for harness.retrieval.native_pg (native PG composition wiring).

The real VectorContextRetriever/CypherTemplateRetriever need a live graph store, so
here we pass explicit sub_retrievers and assert the as_retriever wiring with a fake
index.
"""

from harness.retrieval import build_native_composed_retriever


class _FakeIndex:
    def __init__(self):
        self.captured = None
        self.property_graph_store = object()

    def as_retriever(self, *, sub_retrievers, include_text=True):
        self.captured = {"sub_retrievers": sub_retrievers, "include_text": include_text}
        return "COMPOSED_RETRIEVER"


def test_build_native_composed_with_explicit_sub_retrievers():
    index = _FakeIndex()
    sentinel = object()
    out = build_native_composed_retriever(index, sub_retrievers=[sentinel], include_text=True)
    assert out == "COMPOSED_RETRIEVER"
    assert index.captured["sub_retrievers"] == [sentinel]
    assert index.captured["include_text"] is True

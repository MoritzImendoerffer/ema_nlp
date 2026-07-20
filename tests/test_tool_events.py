"""Unit tests for chain-event capture (harness.tools.events).

Offline: fake NodeWithScore-shaped objects, no retriever/LLM/Neo4j. Verifies the
ContextVar sink contract (ordering, nested-scope sharing, no-op outside a scope)
and the NodeRef provenance projection incl. link-expansion / topic-hub fields.
"""

from harness.tools.events import (
    ChainStep,
    NodeRef,
    capture_chain_events,
    node_ref_from_nws,
    record_tool_event,
)


class _FakeNode:
    def __init__(self, node_id: str, text: str = "some text", **meta):
        self.node_id = node_id
        self.text = text
        self.metadata = meta


class _FakeNWS:
    def __init__(self, node: _FakeNode, score=0.5):
        self.node = node
        self.score = score


def _nws(doc="d1", chunk="c1", origin="vector", **extra) -> _FakeNWS:
    meta = {
        "doc_id": doc,
        "chunk_id": chunk,
        "matched_chunk": chunk,
        "source_url": f"https://ema.test/{doc}",
        "title": f"Title {doc}",
        "category": "qa",
        "doc_type": "questions-and-answers",
        "retrieval_origin": origin,
        **extra,
    }
    return _FakeNWS(_FakeNode(chunk, **meta))


def test_record_is_noop_outside_capture_scope():
    record_tool_event(tool="ema_search", args={"query": "q"}, notes=[], nodes=[_nws()])
    with capture_chain_events() as steps:
        pass
    assert steps == []


def test_steps_are_sequenced_in_call_order():
    with capture_chain_events() as steps:
        record_tool_event(
            tool="ema_search",
            args={"query": "q1", "source_category": ""},
            notes=["[routing: rule 'nitrosamine' -> filter qa]"],
            nodes=[_nws("d1"), _nws("d2")],
            output="body1",
            duration_ms=12.5,
        )
        record_tool_event(
            tool="topic_context",
            args={"topic": "referral_procedures", "query": "q2", "page": 1},
            notes=["[topic: referral_procedures]"],
            nodes=[],
            output="map only",
        )
    assert [s.seq for s in steps] == [1, 2]
    assert [s.tool for s in steps] == ["ema_search", "topic_context"]
    assert steps[0].notes == ["[routing: rule 'nitrosamine' -> filter qa]"]
    assert len(steps[0].nodes) == 2
    assert steps[0].output_chars == len("body1")
    assert steps[0].raw_output == "body1"
    assert steps[0].duration_ms == 12.5
    assert steps[1].nodes == []  # map-only pages still record a step


def test_nested_scopes_share_the_outermost_sink():
    with capture_chain_events() as outer:
        with capture_chain_events() as inner:
            record_tool_event(tool="ema_search", args={}, notes=[], nodes=[])
        assert inner is outer
    assert len(outer) == 1 and outer[0].seq == 1


def test_node_ref_projects_provenance():
    ref = node_ref_from_nws(_nws("d9", "c9", origin="link_expansion", linked_from=["d1", "d2"]))
    assert ref.doc_id == "d9"
    assert ref.chunk_id == "c9"
    assert ref.source_url == "https://ema.test/d9"
    assert ref.title == "Title d9"
    assert ref.category == "qa"
    assert ref.doc_type == "questions-and-answers"
    assert ref.score == 0.5
    assert ref.retrieval_origin == "link_expansion"
    assert ref.linked_from == ["d1", "d2"]


def test_node_ref_topic_hub_and_missing_meta_defaults():
    ref = node_ref_from_nws(_nws("d3", origin="topic_subgraph", topic_hub="referral_procedures"))
    assert ref.topic_hub == "referral_procedures"
    bare = node_ref_from_nws(_FakeNWS(_FakeNode("n1"), score=None))
    assert bare.retrieval_origin == "vector"
    assert bare.score is None
    assert bare.chunk_id == "n1"  # falls back to node_id
    assert bare.linked_from == []


def test_ema_search_tool_records_a_chain_step():
    from llama_index.core.retrievers import BaseRetriever
    from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

    from harness.tools import get_tool

    class _QueryEcho(BaseRetriever):
        def _retrieve(self, query_bundle: QueryBundle):
            q = query_bundle.query_str
            return [
                NodeWithScore(
                    node=TextNode(
                        text=q, id_=q, metadata={"source_url": q, "doc_id": "d1", "category": "qa"}
                    ),
                    score=1.0,
                )
            ]

    tool = get_tool("ema_search", retriever=_QueryEcho())
    with capture_chain_events() as steps:
        tool.call(query="hello")
    assert len(steps) == 1
    step = steps[0]
    assert step.tool == "ema_search"
    assert step.args == {"query": "hello", "source_category": ""}
    assert [n.doc_id for n in step.nodes] == ["d1"]
    assert step.duration_ms is not None and step.started_at
    assert "source=hello" in step.raw_output


def test_to_dict_round_trip_shapes():
    step = ChainStep(
        seq=1,
        tool="ema_search",
        args={"query": "q"},
        nodes=[NodeRef(doc_id="d1", linked_from=["d0"])],
    )
    d = step.to_dict()
    assert d["seq"] == 1
    assert d["nodes"][0]["doc_id"] == "d1"
    assert d["nodes"][0]["linked_from"] == ["d0"]
    # mutating the dict must not touch the dataclass (defensive copies)
    d["args"]["query"] = "mutated"
    d["nodes"][0]["doc_id"] = "mutated"
    assert step.args["query"] == "q"
    assert step.nodes[0].doc_id == "d1"


def test_node_ref_carries_tree_view_fields():
    ref = node_ref_from_nws(
        _nws("d5", topic_path="/en/medicines/human/EPAR/x/", source_type="pdf")
    )
    assert ref.topic_path == "/en/medicines/human/EPAR/x/"
    assert ref.source_type == "pdf"
    d = ref.to_dict()
    assert d["topic_path"] == "/en/medicines/human/EPAR/x/"
    assert d["source_type"] == "pdf"
    # absent meta -> empty strings, never None
    bare = node_ref_from_nws(_FakeNWS(_FakeNode("n2"), score=None))
    assert bare.topic_path == "" and bare.source_type == ""

"""Unit tests for trace → chain reconstruction (harness.export.chain_from_trace).

Fake span objects pin the empirically observed mlflow 3.14 + llama_index autolog
contract (see the module docstring of chain_from_trace): TOOL spans carry
``outputs.tool_name`` / ``outputs.raw_output`` / ``inputs.kwargs``; RETRIEVER
descendants carry full node metadata; the explicit turn span carries the
question inputs and the RegulatoryAnswer outputs.
"""

from types import SimpleNamespace

from harness.export.chain_from_trace import bundle_from_trace, chain_steps_from_trace

_NS = 1_000_000  # 1 ms in ns


def _span(
    span_id,
    name,
    span_type,
    *,
    parent=None,
    start=0,
    end=None,
    inputs=None,
    outputs=None,
    attributes=None,
):
    return SimpleNamespace(
        span_id=span_id,
        name=name,
        span_type=span_type,
        parent_id=parent,
        start_time_ns=start,
        end_time_ns=end if end is not None else start + 5 * _NS,
        inputs=inputs,
        outputs=outputs,
        attributes=attributes or {},
    )


def _retriever_out(url, **meta):
    return {
        "page_content": "text",
        "metadata": {"source_url": url, "score": 0.9, **meta},
        "id": meta.get("chunk_id", "c"),
    }


def _trace(spans, assessments=None, trace_id="tr-deadbeefcafe", ts=1_752_915_600_000):
    return SimpleNamespace(
        data=SimpleNamespace(spans=spans),
        info=SimpleNamespace(trace_id=trace_id, assessments=assessments or [], timestamp_ms=ts),
    )


_RAW_1 = (
    "[routing: rule 'nitrosamine' -> filter qa]\n\n"
    "[1] source=https://ema.eu/d1 category=qa score=0.900\nsnippet one\n\n"
    "[2] source=https://ema.eu/d3 category=epar score=0.700 via=link_expansion\nsnippet two"
)
_RAW_2 = (
    "[topic context: best passages from 1 of 5 members, ~100 of 2000 token budget]\n\n"
    "[1] source=https://ema.eu/d4 score=0.800 via=topic_subgraph\nchunk text"
)


def _tool_span(span_id, tool, raw, kwargs, *, parent="root", start=0):
    return _span(
        span_id,
        "FunctionTool.call",
        "TOOL",
        parent=parent,
        start=start,
        inputs={"kwargs": kwargs},
        outputs={"tool_name": tool, "raw_output": raw, "is_error": False},
        attributes={"name": tool},
    )


def _default_spans():
    root = _span(
        "root",
        "AgentWorkflowAdapter.invoke",
        "UNKNOWN",
        start=0,
        inputs={"question": "What is the AI for NDMA?"},
        outputs={
            "answer": "The AI is 96 ng/day.",
            "claims": [],
            "citations": [
                {"source_url": "https://ema.eu/d1", "doc_id": "d1", "chunk_id": "c1",
                 "quote": "The AI is 96 ng/day", "category": "qa"}
            ],
            "confidence": 0.8,
            "caveats": [],
        },
        attributes={"ema.recipe": "steered_agent", "ema.run.id": "run-42"},
    )
    tool2 = _tool_span(
        "t2", "topic_context", _RAW_2,
        {"topic": "referral_procedures", "query": "nitrosamine", "page": 1},
        start=20 * _NS,
    )
    tool1 = _tool_span(
        "t1", "ema_search", _RAW_1,
        {"query": "NDMA acceptable intake", "source_category": ""},
        start=10 * _NS,
    )
    retr = _span(
        "r1",
        "Retriever.retrieve",
        "RETRIEVER",
        parent="t1",
        start=11 * _NS,
        outputs=[
            _retriever_out("https://ema.eu/d1", doc_id="d1", chunk_id="c1", title="Doc 1",
                           category="qa", retrieval_origin="vector"),
            _retriever_out("https://ema.eu/d3", doc_id="d3", chunk_id="c3", title="Doc 3",
                           category="epar", retrieval_origin="link_expansion",
                           linked_from=["d1"]),
        ],
    )
    # deliberately unordered: reconstruction must sort by start_time_ns
    return [root, tool2, tool1, retr]


def test_steps_ordered_by_start_time_with_args_and_notes():
    steps = chain_steps_from_trace(_trace(_default_spans()))
    assert [s.tool for s in steps] == ["ema_search", "topic_context"]
    assert [s.seq for s in steps] == [1, 2]
    assert steps[0].args == {"query": "NDMA acceptable intake", "source_category": ""}
    assert steps[0].notes == ["[routing: rule 'nitrosamine' -> filter qa]"]
    assert steps[1].notes == [
        "[topic context: best passages from 1 of 5 members, ~100 of 2000 token budget]"
    ]
    assert steps[0].duration_ms == 5.0
    assert steps[0].started_at.startswith("1970-01-01T00:00:00")


def test_nodes_parsed_from_output_and_enriched_from_retriever_spans():
    steps = chain_steps_from_trace(_trace(_default_spans()))
    n1, n2 = steps[0].nodes
    assert (n1.source_url, n1.doc_id, n1.title) == ("https://ema.eu/d1", "d1", "Doc 1")
    assert n1.category == "qa" and n1.score == 0.9
    assert n1.retrieval_origin == "vector"
    assert n2.retrieval_origin == "link_expansion"
    assert n2.linked_from == ["d1"]  # only present via RETRIEVER-span metadata
    # topic_context line has no category and no retriever child: falls back gracefully
    (n3,) = steps[1].nodes
    assert n3.source_url == "https://ema.eu/d4"
    assert n3.retrieval_origin == "topic_subgraph"
    assert n3.score == 0.8
    assert n3.doc_id == ""  # honest: not recoverable from the string alone


def test_bundle_from_trace_carries_answer_config_and_judges():
    assessment = SimpleNamespace(
        name="faithfulness", feedback=SimpleNamespace(value=4), rationale="grounded"
    )
    bundle = bundle_from_trace(_trace(_default_spans(), assessments=[assessment]))
    assert bundle.question == "What is the AI for NDMA?"
    assert bundle.answer.answer == "The AI is 96 ng/day."
    assert bundle.recipe_name == "steered_agent"
    assert bundle.run_id == "run-42"
    assert bundle.trace_id == "tr-deadbeefcafe"
    assert bundle.resolved_config["ema.recipe"] == "steered_agent"
    assert bundle.judge_results == [
        {"name": "faithfulness", "score": 4, "rationale": "grounded"}
    ]
    assert len(bundle.chain) == 2
    assert bundle.asked_at.startswith("2025") or bundle.asked_at  # ISO stamped


def test_bundle_renders_via_chain_html():
    from harness.export import ExportOptions, get_exporter

    bundle = bundle_from_trace(_trace(_default_spans()))
    html = get_exporter("chain_html").render(bundle, ExportOptions())
    assert "ema_search" in html and "topic_context" in html
    assert "badge link_expansion" in html
    assert "cited [1]" in html  # d1 citation matched by chunk_id/doc_id


def test_trace_without_tool_spans_yields_empty_chain():
    root = _span("root", "chat.turn", "UNKNOWN", inputs={"question": "q"}, outputs={"a": 1})
    trace = _trace([root])
    assert chain_steps_from_trace(trace) == []
    bundle = bundle_from_trace(trace)
    assert bundle.chain == [] and bundle.question == "q"
    assert bundle.answer.answer == ""  # no RegulatoryAnswer-shaped span → empty fallback


def test_question_falls_back_to_autolog_user_msg():
    # Pre-chain-capture traces have no record_answer_on_span span; the only
    # question source is autolog's FunctionAgent.run root span ("user_msg").
    root = _span(
        "root", "FunctionAgent.run", "AGENT",
        inputs={"user_msg": "What is the AI for NDMA?"}, outputs={},
    )
    bundle = bundle_from_trace(_trace([root]))
    assert bundle.question == "What is the AI for NDMA?"


def test_malformed_outputs_are_tolerated():
    weird = _span(
        "t1", "FunctionTool.call", "TOOL",
        inputs="not-a-dict",
        outputs={"tool_name": "ema_search", "raw_output": "No results found."},
    )
    steps = chain_steps_from_trace(_trace([weird]))
    assert steps[0].args == {}
    assert steps[0].nodes == []
    assert steps[0].notes == []


def test_tree_view_fields_recovered_from_retriever_spans_and_path_kv():
    raw = (
        "[1] source=https://ema.eu/d1 category=qa score=0.900 path=/medicines/human\n"
        "snippet"
    )
    tool = _tool_span("t1", "ema_search", raw, {"query": "q"})
    retr = _span(
        "r1", "Retriever.retrieve", "RETRIEVER", parent="t1", start=1,
        outputs=[
            _retriever_out(
                "https://ema.eu/d1", doc_id="d1", chunk_id="c1", title="Doc 1",
                category="qa", retrieval_origin="vector",
                topic_path="/en/medicines/human/", source_type="html",
            )
        ],
    )
    root = _span("root", "chat.turn", "UNKNOWN", inputs={"question": "q"}, outputs={})
    (step,) = chain_steps_from_trace(_trace([root, tool, retr]))
    (node,) = step.nodes
    assert node.topic_path == "/en/medicines/human/"  # RETRIEVER meta wins
    assert node.source_type == "html"

    # without a RETRIEVER child, the path= kv is the fallback (topic_subgraph case)
    tool_only = _tool_span("t2", "ema_search", raw, {"query": "q"})
    (step2,) = chain_steps_from_trace(_trace([root, tool_only]))
    (node2,) = step2.nodes
    assert node2.topic_path == "medicines/human"
    assert node2.source_type == ""

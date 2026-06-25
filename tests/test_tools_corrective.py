"""Unit tests for the CRAG primitives (harness.retrieval.corrective) and the
``corrective_search`` agent tool. Offline: fake retriever + fake (scripted) LLM,
no network / Neo4j / real model."""

from types import SimpleNamespace

from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

from harness.retrieval.corrective import (
    grade_messages,
    grade_note,
    is_sufficient,
    parse_grade,
    rewrite_messages,
)
from harness.tools import get_tool

_SUFFICIENT = '{"per_doc": [{"qa_id": "a", "score": 2}], "missing_facts": []}'
_INSUFFICIENT = '{"per_doc": [{"qa_id": "a", "score": 1}], "missing_facts": ["the specific ng/day limit"]}'


# --- fixtures ---------------------------------------------------------------


class _FakeRetriever(BaseRetriever):
    def __init__(self):
        super().__init__()
        self.queries: list[str] = []

    def _retrieve(self, query_bundle: QueryBundle):
        self.queries.append(query_bundle.query_str)
        return [
            NodeWithScore(
                node=TextNode(
                    text=f"passage for {query_bundle.query_str}",
                    metadata={"source_url": "https://ema.europa.eu/ndma", "doc_id": "d1"},
                ),
                score=0.9,
            )
        ]


class _FakeLLM:
    """Scripted LLM: returns the next grade JSON for grading calls, a fixed string
    for rewrite calls. Distinguishes by the system prompt content."""

    def __init__(self, grade_responses: list[str], rewrite: str = "ndma acceptable intake ng/day limit"):
        self._grades = list(grade_responses)
        self._rewrite = rewrite
        self.grade_calls = 0
        self.rewrite_calls = 0

    def chat(self, messages):
        system = messages[0].content
        if "relevance grader" in system:
            content = self._grades[min(self.grade_calls, len(self._grades) - 1)]
            self.grade_calls += 1
        else:
            self.rewrite_calls += 1
            content = self._rewrite
        return SimpleNamespace(message=SimpleNamespace(content=content))


# --- pure CRAG primitives ---------------------------------------------------


def test_parse_grade_valid_and_fenced():
    pd, miss = parse_grade('```json\n{"per_doc": [{"qa_id": "a", "score": 2}], "missing_facts": []}\n```')
    assert pd == [{"qa_id": "a", "score": 2}]
    assert miss == []


def test_parse_grade_garbage_is_treated_insufficient():
    pd, miss = parse_grade("the model rambled, no json here")
    assert pd == []
    assert miss and "parse error" in miss[0]
    assert is_sufficient(pd, miss) is False


def test_is_sufficient_rule():
    assert is_sufficient([{"score": 2}], []) is True
    assert is_sufficient([{"score": 2}], ["x"]) is False  # a gap blocks sufficiency
    assert is_sufficient([{"score": 1}], []) is False  # no fully-relevant doc


def test_message_builders_use_shared_prompts():
    gm = grade_messages("Q", "CTX")
    assert "relevance grader" in gm[0].content and "CTX" in gm[1].content
    rm = rewrite_messages("Q", ["missing fact"])
    assert "query rewriter" in rm[0].content and "missing fact" in rm[1].content


def test_grade_note_surfaces_residual_gap():
    assert "STILL MISSING" in grade_note(2, [{"score": 1}], ["the limit"])
    assert "sufficient" in grade_note(0, [{"score": 2}], [])


# --- corrective_search tool -------------------------------------------------


def test_corrective_search_sufficient_first_pass_no_rewrite():
    r, llm = _FakeRetriever(), _FakeLLM([_SUFFICIENT])
    tool = get_tool("corrective_search", retriever=r, llm=llm, max_cycles=2)
    out = str(tool.call(query="ndma ai"))
    assert len(r.queries) == 1
    assert llm.rewrite_calls == 0
    assert "sufficient" in out


def test_corrective_search_rewrites_then_succeeds():
    r, llm = _FakeRetriever(), _FakeLLM([_INSUFFICIENT, _SUFFICIENT])
    tool = get_tool("corrective_search", retriever=r, llm=llm, max_cycles=2)
    str(tool.call(query="ndma ai"))
    assert len(r.queries) == 2  # original + one corrected retry
    assert r.queries[1] != r.queries[0]
    assert llm.rewrite_calls == 1


def test_corrective_search_is_bounded_by_max_cycles():
    r, llm = _FakeRetriever(), _FakeLLM([_INSUFFICIENT])  # never sufficient
    tool = get_tool("corrective_search", retriever=r, llm=llm, max_cycles=2)
    out = str(tool.call(query="q"))
    assert len(r.queries) == 3  # 1 + max_cycles, never unbounded
    assert llm.rewrite_calls == 2
    assert "STILL MISSING" in out


def test_corrective_search_feeds_node_sink():
    from harness.tools.search import capture_search_nodes

    r, llm = _FakeRetriever(), _FakeLLM([_SUFFICIENT])
    tool = get_tool("corrective_search", retriever=r, llm=llm)
    with capture_search_nodes() as sink:
        tool.call(query="q")
    assert len(sink) == 1
    assert sink[0].node.metadata["doc_id"] == "d1"


def test_corrective_search_requires_retriever():
    try:
        get_tool("corrective_search", llm=_FakeLLM([_SUFFICIENT]))
    except ValueError as exc:
        assert "retriever" in str(exc)
    else:
        raise AssertionError("expected ValueError when no retriever supplied")


def test_nested_capture_scopes_share_outer_sink():
    # The adapter wraps the agent run in an outer capture; arun_agent opens an inner one.
    # The inner must REUSE the outer sink so the adapter sees the retrieved nodes.
    from harness.tools.search import capture_search_nodes

    r, llm = _FakeRetriever(), _FakeLLM([_SUFFICIENT])
    tool = get_tool("corrective_search", retriever=r, llm=llm)
    with capture_search_nodes() as outer:
        with capture_search_nodes() as inner:
            assert inner is outer  # nested scope reuses the active sink
            tool.call(query="q")
        assert len(outer) == 1  # outer sees what the tool retrieved inside the inner scope
        assert outer[0].node.metadata["doc_id"] == "d1"

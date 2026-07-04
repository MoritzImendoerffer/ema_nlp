"""Unit tests for harness.eval.predict (predict_fn adapter)."""

from harness.eval import build_predict_fn
from harness.schemas import Citation, RegulatoryAnswer


class _FakeSession:
    def run(self, question):
        return RegulatoryAnswer(
            answer=f"A:{question}", citations=[Citation(source_url="u1")], confidence=0.7
        )


class _FakeAdapter:
    """Mimics AgentWorkflowAdapter's invoke contract (F5)."""

    def __init__(self):
        self.payloads = []

    def invoke(self, payload):
        self.payloads.append(payload)
        return {
            "answer_text": "adapted",
            "docs": [],
            "answer": RegulatoryAnswer(answer="adapted", confidence=0.9),
            "context_passages": ["passage one", "passage two"],
        }


def test_build_predict_fn_from_session():
    fn = build_predict_fn(_FakeSession())
    out = fn("what is the NDMA AI?")
    assert out["answer"] == "A:what is the NDMA AI?"
    assert out["citations"] == ["u1"]
    assert out["confidence"] == 0.7
    assert out["num_claims"] == 0
    # No search tool ran, so the captured retrieval is empty — but the key exists
    # so the faithfulness judge's contract holds (F3).
    assert out["context_passages"] == []


def test_build_predict_fn_from_callable():
    fn = build_predict_fn(lambda _q: RegulatoryAnswer(answer="x"))
    out = fn("q")
    assert out["answer"] == "x"
    assert out["context_passages"] == []


def test_build_predict_fn_from_workflow_adapter():
    adapter = _FakeAdapter()
    fn = build_predict_fn(adapter)
    out = fn("q")
    assert out["answer"] == "adapted"
    assert out["confidence"] == 0.9
    # The adapter's retrieval capture flows through to the judge (F3+F5).
    assert out["context_passages"] == ["passage one", "passage two"]
    # The eval origin is stamped on the payload so traces are attributable.
    assert adapter.payloads == [{"question": "q", "source": "eval"}]


def test_build_predict_fn_session_captures_search_nodes():
    """A session whose run triggers ema_search-style capture returns real passages."""

    class _Node:
        def __init__(self, text):
            self.text = text

    class _NodeWithScore:
        def __init__(self, text):
            self.node = _Node(text)

    class _SearchingSession:
        def run(self, question):
            from harness.tools.search import _NODE_SINK

            sink = _NODE_SINK.get()
            if sink is not None:
                sink.extend([_NodeWithScore("ctx A"), _NodeWithScore("  "), _NodeWithScore("ctx B")])
            return RegulatoryAnswer(answer="found")

    out = build_predict_fn(_SearchingSession())("q")
    assert out["context_passages"] == ["ctx A", "ctx B"]

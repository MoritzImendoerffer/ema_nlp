"""Unit tests for harness.eval.predict (predict_fn adapter and the prediction loop)."""

import asyncio

from harness.eval import build_predict_fn
from harness.eval.predict import predict_items
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


# --- predict_items: the runner's own prediction loop (eval reliability, TASK-002) ---

_ROWS = [
    {"bench_id": "T1-001", "type": "T1", "question": "q1"},
    {"bench_id": "T1-002", "type": "T1", "question": "q2"},
    {"bench_id": "T1-003", "type": "T1", "question": "q3"},
]


class _AsyncAgent:
    """Stand-in for AgentWorkflowAdapter.ainvoke; raises on the questions in ``fail_on``."""

    def __init__(self, fail_on=(), passages=("p1", "p2")):
        self.fail_on = set(fail_on)
        self.passages = list(passages)
        self.loop_ids: list[int] = []

    async def ainvoke(self, payload):
        self.loop_ids.append(id(asyncio.get_running_loop()))
        if payload["question"] in self.fail_on:
            raise RuntimeError("Event loop is closed")
        return {
            "answer": RegulatoryAnswer(answer=f"A:{payload['question']}"),
            "context_passages": list(self.passages),
        }


def _counting_trace_ids():
    """A trace-id function that yields a new id after each item (tr-0 before the first)."""
    state = {"n": 0}

    def fn():
        value = f"tr-{state['n']}"
        state["n"] += 1
        return value

    return fn


def test_predict_items_counts_a_failed_item_and_goes_on():
    """A crashed agent run is recorded as failed, not handed on as an answer.

    On 2026-07-13 five evaluation runs ended with 'Event loop is closed' and the
    judges scored them anyway (one got correctness 5).
    """
    results = predict_items(_AsyncAgent(fail_on={"q2"}), _ROWS, trace_id_fn=_counting_trace_ids())
    assert [r.ok for r in results] == [True, False, True]
    assert results[1].error.startswith("RuntimeError")
    assert results[1].outputs is None
    assert [r.bench_id for r in results] == ["T1-001", "T1-002", "T1-003"]
    assert all(r.question_type == "T1" for r in results)
    # A failed item keeps the trace it made; the runner links it to the run.
    assert results[1].trace_id is not None


def test_predict_items_uses_one_event_loop():
    """One loop for all questions: one loop per question closed the shared client's pool."""
    agent = _AsyncAgent()
    predict_items(agent, _ROWS, trace_id_fn=_counting_trace_ids())
    assert len(agent.loop_ids) == 3
    assert len(set(agent.loop_ids)) == 1


def test_predict_items_never_gives_two_items_one_trace_id():
    """last_trace_id returns the previous item's id when an item made no trace."""
    ids = iter(["tr-before", "tr-a", "tr-a", "tr-b"])
    results = predict_items(_AsyncAgent(), _ROWS, trace_id_fn=lambda: next(ids))
    assert [r.trace_id for r in results] == ["tr-a", None, "tr-b"]


def test_predict_items_carries_the_passages():
    results = predict_items(
        _AsyncAgent(passages=["ctx A", "ctx B"]), _ROWS[:1], trace_id_fn=_counting_trace_ids()
    )
    assert results[0].ok
    assert results[0].outputs["context_passages"] == ["ctx A", "ctx B"]
    assert results[0].outputs["answer"] == "A:q1"


def test_predict_items_prefers_the_trace_id_the_agent_returns():
    """The newest-trace lookup missed T1-001's trace on 2026-11-23: it was written late."""

    class _AgentWithId(_AsyncAgent):
        async def ainvoke(self, payload):
            result = await super().ainvoke(payload)
            return {**result, "trace_id": f"tr-own-{payload['question']}"}

    results = predict_items(_AgentWithId(), _ROWS[:2], trace_id_fn=lambda: None)
    assert [r.trace_id for r in results] == ["tr-own-q1", "tr-own-q2"]

"""Unit tests for harness.eval.inline_judge — the optional per-turn judge layer.

Offline: a scripted fake LLM stands in for the judge model (no real call)."""

from types import SimpleNamespace

from harness.eval.inline_judge import run_inline_judges, runtime_judges


class _FakeJudgeLLM:
    def __init__(self, content: str):
        self._content = content

    def chat(self, _messages):
        return SimpleNamespace(message=SimpleNamespace(content=self._content))


def test_runtime_judges_filters_to_gold_free():
    assert runtime_judges(["faithfulness", "correctness"]) == ["faithfulness"]


def test_run_inline_faithfulness_scores_and_normalizes():
    llm = _FakeJudgeLLM('{"score": 4, "reason": "well grounded"}')
    res = run_inline_judges(
        ["faithfulness"], question="q", answer="a", context_passages=["ctx"], llm=llm
    )
    assert len(res) == 1
    assert res[0].name == "faithfulness"
    assert res[0].score == 4
    assert abs(res[0].value - 0.8) < 1e-6
    assert "grounded" in res[0].rationale


def test_correctness_is_skipped_inline():
    res = run_inline_judges(
        ["correctness"], question="q", answer="a", context_passages=["ctx"], llm=_FakeJudgeLLM("{}")
    )
    assert res == []  # needs a gold answer -> offline only


def test_non_answer_scores_zero_without_calling_model():
    res = run_inline_judges(
        ["faithfulness"],
        question="q",
        answer="No answer generated.",
        context_passages=[],
        llm=_FakeJudgeLLM("should not be used"),
    )
    assert res and res[0].score == 0 and res[0].value == 0.0


def test_judge_error_is_swallowed():
    class _BoomLLM:
        def chat(self, _messages):
            raise RuntimeError("model down")

    res = run_inline_judges(
        ["faithfulness"], question="q", answer="a", context_passages=["ctx"], llm=_BoomLLM()
    )
    assert res == []  # a failing judge never breaks the turn

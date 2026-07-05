"""Unit tests for harness.eval.inline_judge — the optional per-turn judge layer.

Offline: a scripted fake LLM stands in for the judge model (no real call)."""

from types import SimpleNamespace

from harness.eval.inline_judge import JudgeResult, run_inline_judges, runtime_judges


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


def test_run_inline_judges_honors_model_role(monkeypatch):
    """The recipe's judge.model_role reaches the Judge (F10 — stamped knob is real)."""
    import harness.judge as judge_mod

    seen: dict = {}

    class _FakeJudge:
        def __init__(self, llm=None, *, model_role="judge"):
            seen["model_role"] = model_role

        def faithfulness(self, question, answer, context):
            return {"score": 4, "reason": "ok"}

    monkeypatch.setattr(judge_mod, "Judge", _FakeJudge)
    results = run_inline_judges(
        ["faithfulness"], question="q", answer="a", context_passages=["c"], model_role="reviewer"
    )
    assert seen["model_role"] == "reviewer"
    assert results[0].score == 4


# ---------------------------------------------------------------------------
# F18: soft reviewer gate (advisory verdict)
# ---------------------------------------------------------------------------

def test_review_verdict_disabled_without_threshold():
    from harness.eval import review_verdict

    passed, note = review_verdict([JudgeResult("faithfulness", 1, 0.2, "bad")], None)
    assert passed is True and note == ""


def test_review_verdict_passes_at_or_above_threshold():
    from harness.eval import review_verdict

    passed, note = review_verdict([JudgeResult("faithfulness", 3, 0.6, "ok")], 3)
    assert passed is True and note == ""


def test_review_verdict_below_threshold_annotates_but_never_blocks():
    from harness.eval import review_verdict

    passed, note = review_verdict([JudgeResult("faithfulness", 2, 0.4, "weak")], 3)
    assert passed is False
    assert "faithfulness 2/5" in note and "Reviewer recommendation" in note


def test_review_verdict_no_usable_score_fails_safe():
    from harness.eval import review_verdict

    # judge errored (no results) or returned 0 = could-not-score: flag as unreviewed
    for results in ([], [JudgeResult("faithfulness", 0, 0.0, "")]):
        passed, note = review_verdict(results, 3)
        assert passed is False
        assert "could not be" in note


def test_judge_policy_parses_threshold_and_rejects_unknown_on_fail():
    from harness.recipes.config import JudgePolicy

    policy = JudgePolicy.from_dict({"enabled": True, "judges": ["faithfulness"], "threshold": 3})
    assert policy.threshold == 3.0 and policy.on_fail == "annotate"
    assert JudgePolicy.from_dict({}).threshold is None

    import pytest

    with pytest.raises(ValueError, match="on_fail"):
        JudgePolicy.from_dict({"on_fail": "retry"})


def test_judged_recipe_stamps_threshold():
    from harness.recipes import get_recipe

    r = get_recipe("agentic_judged")
    assert r.judge.threshold == 3.0
    attrs = r.resolved_attributes()
    assert attrs["ema.judge.threshold"] == 3.0
    assert attrs["ema.judge.on_fail"] == "annotate"

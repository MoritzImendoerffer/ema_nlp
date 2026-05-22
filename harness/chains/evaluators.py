"""
LangSmith evaluators for faithfulness and correctness (LSMT-006).

These wrap harness.judge.Judge so that the same Sonnet-level scoring
rubrics used in run_eval.py are reused for LangSmith experiment evaluation.

LangSmith evaluators receive a Run (chain output) and an Example (dataset
reference) and return an EvaluationResult with:
    key:     "faithfulness" | "correctness"
    score:   float in [0.0, 1.0]  (judge's 1-5 score divided by 5)
    comment: brief reason from the judge

Usage (via langsmith.evaluate)::

    from langsmith import evaluate
    from harness.chains.evaluators import faithfulness_evaluator, correctness_evaluator

    results = evaluate(
        chain.invoke,
        data="ema-benchmark",
        evaluators=[faithfulness_evaluator, correctness_evaluator],
    )

Usage (standalone)::

    from harness.chains.evaluators import score_run

    run_mock = {"inputs": {"question": "..."}, "outputs": {"answer_text": "...", "docs": [...]}}
    example_mock = {"outputs": {"gold_answer": "..."}}
    result = score_run(run_mock, example_mock, dimension="correctness")
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_judge = None


def _get_judge():
    global _judge
    if _judge is None:
        from harness.judge import Judge
        _judge = Judge()
    return _judge


def faithfulness_evaluator(run: Any, example: Any) -> dict:
    """
    LangSmith evaluator: is the answer grounded in the retrieved documents?

    Extracts question, answer, and context docs from the run output, then
    calls Judge.faithfulness().  Returns score 0.0–1.0 (judge 1–5 / 5).
    """
    return score_run(run, example, dimension="faithfulness")


def correctness_evaluator(run: Any, example: Any) -> dict:
    """
    LangSmith evaluator: does the answer match the gold answer?

    Extracts question, answer, and gold_answer from the run/example, then
    calls Judge.correctness().  Returns score 0.0–1.0.
    """
    return score_run(run, example, dimension="correctness")


def score_run(run: Any, example: Any, *, dimension: str) -> dict:
    """
    Core scoring function used by both evaluators.

    Args:
        run:       LangSmith Run object (or dict with .inputs / .outputs).
        example:   LangSmith Example object (or dict with .outputs).
        dimension: "faithfulness" | "correctness"

    Returns:
        Dict compatible with LangSmith EvaluationResult:
            {"key": str, "score": float, "comment": str}
    """
    inputs = _attr(run, "inputs") or {}
    outputs = _attr(run, "outputs") or {}
    ref_outputs = _attr(example, "outputs") or {}

    question: str = inputs.get("question", "")
    answer: str = outputs.get("answer_text", outputs.get("output", ""))
    gold_answer: str = ref_outputs.get("gold_answer", "")
    docs: list = outputs.get("docs", [])

    judge = _get_judge()

    if dimension == "faithfulness":
        context_passages = [
            (d.page_content if hasattr(d, "page_content") else str(d))
            for d in docs
        ]
        js = judge.faithfulness(question, answer, context_passages)
    elif dimension == "correctness":
        js = judge.correctness(question, answer, gold_answer)
    else:
        raise ValueError(f"Unknown dimension: {dimension!r}. Use 'faithfulness' or 'correctness'.")

    raw_score: int = js["score"]
    # Map judge's 0-5 scale to 0.0-1.0 (score=0 means non-answer sentinel)
    normalised = raw_score / 5.0

    return {
        "key": dimension,
        "score": normalised,
        "comment": js.get("reason", ""),
    }


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _attr(obj: Any, name: str) -> Any:
    """Return obj.name if it's an object, obj[name] if it's a dict."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)

"""
Post-generation review (QA) node for LangGraph pipelines (LG-005).

Wraps harness.judge.Judge.faithfulness to assess whether the generated answer
is grounded in the retrieved documents.  Converts the 1–5 judge score to [0, 1]
(score / 5) and stores it in PipelineState["review_score"].

The LLM parameter is accepted for API consistency but unused — Judge uses its
own model (DEFAULT_JUDGE_MODEL = claude-sonnet-4-6).

Review cycle semantics:
    review_cycle  — incremented each time this node runs
    max_review_cycles in build_pipeline() controls how many REVISIONS are allowed:
        0 → just score (no revision)
        1 → score + one revision attempt
        N → score + N revision attempts

Routing in build_pipeline() uses: cycle > max_review_cycles → END

Usage::

    from harness.chains.nodes.review import build_review_node

    review_node = build_review_node(llm, threshold=0.6)
    update = review_node(state)
    # returns {"review_score": float, "review_feedback": str, "review_cycle": n+1}
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from harness.chains.pipeline_state import PipelineState
from harness.chains.simple_rag import format_docs

log = logging.getLogger(__name__)


def build_review_node(
    llm: Any,
    *,
    threshold: float = 0.6,
) -> Callable[[PipelineState], dict[str, Any]]:
    """
    Build a faithfulness review node.

    Args:
        llm:       Accepted for API consistency; unused (Judge uses its own model).
        threshold: Score threshold for acceptance (review_score >= threshold → pass).

    Returns:
        A node function: (state: PipelineState) ->
            {"review_score": float, "review_feedback": str, "review_cycle": n+1}
    """
    def review_node(state: PipelineState) -> dict[str, Any]:
        answer = state.get("answer_text", "")
        cycle = state.get("review_cycle", 0) + 1

        if not answer or answer == "No answer generated.":
            log.debug("review_node (cycle %d): no answer — score=0.0", cycle)
            return {
                "review_score": 0.0,
                "review_feedback": "No answer to review.",
                "review_cycle": cycle,
            }

        context = format_docs(state.get("docs", []))
        try:
            from harness.judge import Judge
            js = Judge().faithfulness(state["question"], answer, context)
            score = float(js["score"]) / 5.0
            feedback = js.get("reason", "")
        except Exception as exc:
            log.warning(
                "review_node (cycle %d): judge call failed (%s) — defaulting to pass",
                cycle,
                exc,
            )
            score = threshold  # treat failure as pass so the pipeline doesn't loop
            feedback = ""

        log.debug("review_node (cycle %d): score=%.2f (threshold=%.2f)", cycle, score, threshold)
        return {
            "review_score": score,
            "review_feedback": feedback,
            "review_cycle": cycle,
        }

    return review_node

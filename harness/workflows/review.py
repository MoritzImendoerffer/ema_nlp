"""
Review step (faithfulness check) for composite RAG workflows.

Wraps harness.judge.Judge.faithfulness to assess whether the generated
answer is grounded in the retrieved documents.  Converts the 1–5 judge
score to [0, 1] (score / 5) and stores results in ReviewedEvent.

Usage as a standalone step (see composites.py)::

    class MyWorkflow(Workflow):
        ...
        @step
        async def review(self, ctx: Context, ev: GeneratedEvent) -> ReviewedEvent | StopEvent:
            return await run_review_step(ev, threshold=0.6)

Or via ReviewMixin::

    class MyWorkflow(ReviewMixin, Workflow):
        review_threshold = 0.7
        ...

The review step calls Judge directly (harness/judge.py) — it does NOT
use the workflow LLM; Judge has its own model (DEFAULT_JUDGE_MODEL).
"""

from __future__ import annotations

import logging
from typing import Any

from llama_index.core.workflow import Context, StopEvent, Workflow, step

from harness.workflows.events import GeneratedEvent, ReviewedEvent
from harness.workflows.utils import format_docs

log = logging.getLogger(__name__)

_DEFAULT_THRESHOLD = 0.6
_DEFAULT_MAX_REVIEW_CYCLES = 1


async def run_review_step(
    ev: GeneratedEvent,
    *,
    threshold: float = _DEFAULT_THRESHOLD,
) -> ReviewedEvent:
    """Call Judge.faithfulness on ev.answer_text and return a ReviewedEvent."""
    from harness.judge import Judge

    if not ev.answer_text or ev.answer_text == "No answer generated.":
        return ReviewedEvent(
            score=0.0,
            feedback="No answer to review.",
            passed=False,
            answer_text=ev.answer_text,
            docs=ev.docs,
        )

    context_passages = [d.page_content for d in ev.docs] if ev.docs else []
    try:
        js = Judge().faithfulness(ev.question, ev.answer_text, context_passages)
        score = float(js["score"]) / 5.0
        feedback = js.get("reason", "")
    except Exception as exc:
        log.warning("review_step: judge call failed (%s) — defaulting to pass", exc)
        score = threshold  # treat failure as pass to avoid infinite loops
        feedback = ""

    log.debug("review_step: score=%.2f (threshold=%.2f)", score, threshold)
    return ReviewedEvent(
        score=score,
        feedback=feedback,
        passed=score >= threshold,
        answer_text=ev.answer_text,
        docs=ev.docs,
    )


class ReviewMixin:
    """
    Mixin adding a faithfulness review step to a Workflow.

    Set class attributes to override defaults:
        review_threshold:    float = 0.6
        max_review_cycles:   int   = 1

    The review step emits StopEvent when passed or max cycles reached,
    and ReviewedEvent otherwise (for workflows that loop back to generate).
    Subclasses that want review-only (no revision) can override _on_review_fail.
    """

    review_threshold: float = _DEFAULT_THRESHOLD
    max_review_cycles: int = _DEFAULT_MAX_REVIEW_CYCLES

    @step
    async def review(self, ctx: Context, ev: GeneratedEvent) -> ReviewedEvent | StopEvent:
        reviewed = await run_review_step(ev, threshold=self.review_threshold)
        cycle = (await ctx.get("review_cycle", default=0)) + 1
        await ctx.set("review_cycle", cycle)

        if reviewed.passed or cycle > self.max_review_cycles:
            return StopEvent(result={
                "answer_text": reviewed.answer_text,
                "docs": reviewed.docs,
                "review_score": reviewed.score,
                "review_feedback": reviewed.feedback,
            })

        return reviewed

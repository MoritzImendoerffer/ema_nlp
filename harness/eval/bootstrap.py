"""Teacher -> judge-filter -> DSPy bootstrap of few-shot exemplars (aim 1).

The bootstrap loop you described: run an (expensive) teacher to author candidate
exemplars, **filter them through the aligned judge** (the guardrail against training
on confident-but-wrong teacher outputs), then compile an optimized few-shot prompt
with DSPy. The judge filter is pure (and tested); the teacher generation reuses the
predict_fn adapter (testable with a fake teacher); DSPy compilation is lazy/runtime.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class Exemplar:
    """A candidate few-shot example with its judge score (``None`` = not judged)."""

    question: str
    answer: str
    score: float | None = None
    citations: list[str] = field(default_factory=list)


def judge_filter(exemplars: list[Exemplar], *, min_score: float = 4.0) -> list[Exemplar]:
    """Keep only exemplars whose judge score >= ``min_score`` (the guardrail).

    Unjudged exemplars (``score is None``) are a composition error, not a low
    score: silently treating them as 0.0 used to empty the trainset without a
    trace (F16). Judge them first (``generate_exemplars(..., judge=...)``, e.g.
    :func:`faithfulness_judge`) or filter with your own criterion.
    """
    unjudged = sum(1 for e in exemplars if e.score is None)
    if unjudged:
        raise ValueError(
            f"judge_filter got {unjudged} unjudged exemplar(s) (score=None) — run "
            "generate_exemplars with a judge (e.g. faithfulness_judge()) before filtering"
        )
    return [e for e in exemplars if e.score is not None and e.score >= min_score]


def faithfulness_judge(llm: Any = None, *, model_role: str = "judge") -> Any:
    """A ``(question, prediction) -> float`` judge for :func:`generate_exemplars`.

    Wraps :class:`harness.judge.Judge`'s faithfulness rubric (1–5) and grades the
    teacher's answer against the retrieval it actually used — the prediction's
    ``context_passages`` (carried by ``build_predict_fn`` since F3), so the
    signatures compose out of the box (F16).
    """
    from harness.judge import Judge

    judge = Judge(llm, model_role=model_role)

    def _score(question: str, prediction: dict) -> float:
        result = judge.faithfulness(
            question,
            prediction.get("answer", ""),
            list(prediction.get("context_passages") or []),
        )
        return float(result.get("score", 0))

    return _score


def generate_exemplars(
    questions: list[str],
    *,
    teacher: Any,
    judge: Any = None,
) -> list[Exemplar]:
    """Have ``teacher`` answer each question and (optionally) ``judge`` score it.

    ``teacher`` is anything ``build_predict_fn`` accepts (an ``AgentWorkflowAdapter``
    from ``build_recipe``, an ``AgentSession``, or a callable ``question ->
    RegulatoryAnswer``). ``judge`` is a callable ``(question, prediction_dict) ->
    float`` — use :func:`faithfulness_judge` for the project rubric. Without a
    judge, exemplars carry ``score=None`` and ``judge_filter`` will refuse them.
    """
    from harness.eval.predict import build_predict_fn

    predict = build_predict_fn(teacher)
    out: list[Exemplar] = []
    for question in questions:
        prediction = predict(question)
        score = float(judge(question, prediction)) if judge is not None else None
        out.append(
            Exemplar(
                question=question,
                answer=prediction.get("answer", ""),
                score=score,
                citations=list(prediction.get("citations", [])),
            )
        )
    return out


def compile_fewshot(trainset: list, *, student: Any, metric: Any) -> Any:
    """Compile an optimized few-shot program with DSPy ``BootstrapFewShot`` (lazy)."""
    import dspy

    optimizer = dspy.BootstrapFewShot(metric=metric)
    return optimizer.compile(student, trainset=trainset)

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
    """A candidate few-shot example with its judge score."""

    question: str
    answer: str
    score: float = 0.0
    citations: list[str] = field(default_factory=list)


def judge_filter(exemplars: list[Exemplar], *, min_score: float = 4.0) -> list[Exemplar]:
    """Keep only exemplars whose judge score >= ``min_score`` (the guardrail)."""
    return [e for e in exemplars if e.score >= min_score]


def generate_exemplars(
    questions: list[str],
    *,
    teacher: Any,
    judge: Any = None,
) -> list[Exemplar]:
    """Have ``teacher`` answer each question and (optionally) ``judge`` score it.

    ``teacher`` is anything ``build_predict_fn`` accepts (an AgentSession or a
    callable ``question -> RegulatoryAnswer``). ``judge`` is a callable
    ``(question, prediction_dict) -> float``.
    """
    from harness.eval.predict import build_predict_fn

    predict = build_predict_fn(teacher)
    out: list[Exemplar] = []
    for question in questions:
        prediction = predict(question)
        score = float(judge(question, prediction)) if judge is not None else 0.0
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

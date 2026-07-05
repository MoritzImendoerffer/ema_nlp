"""Inline (per-turn) judging — the optional post-generation orchestration layer.

Runs the project's **gold-free** judges (currently ``faithfulness``) on a generated
answer against its retrieved context, so a recipe with ``judge.enabled: true`` gets a
live quality score whose result is logged to MLflow as an LLM-judge assessment (see
``harness.obs.log_judge_feedback``) — visible next to the 👍/👎 human feedback.

This is intentionally lightweight and reuses the proven inline ``harness.judge.Judge``.
The calibrated ``mlflow.genai`` judges (``harness.eval.judges``) with ``align()`` remain
the *offline* batch-eval / reward path; ``correctness`` needs a gold answer and so only
runs there, not here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Judges that can run at inference time (no gold answer required).
RUNTIME_JUDGES = ("faithfulness",)


@dataclass
class JudgeResult:
    name: str
    score: int  # 1–5 (0 = could not score / non-answer)
    value: float  # normalized to [0, 1] for MLflow
    rationale: str


def runtime_judges(names: list[str]) -> list[str]:
    """The subset of requested judges that can run inline (gold-free), order preserved."""
    return [n for n in names if n in RUNTIME_JUDGES]


def review_verdict(
    results: list[JudgeResult], threshold: float | None
) -> tuple[bool, str]:
    """Soft reviewer gate (F18): ``(passed, note)`` for a 1–5 ``threshold``.

    Advisory by design (R1-Q3, owner: recommendation, not a block) — a failing
    verdict yields a visible caution note to attach to the answer; the answer
    still ships. ``threshold=None`` disables the gate. No usable score (judge
    errored or returned 0 = could-not-score) fails safe: the answer is flagged
    as unreviewed rather than silently passing.
    """
    if threshold is None:
        return True, ""
    scored = [r for r in results if r.score]
    if not scored:
        return False, (
            "\n\n_⚠️ Reviewer: no judge score available — answer could not be "
            "verified against its sources; treat with caution._"
        )
    failing = [r for r in scored if r.score < threshold]
    if not failing:
        return True, ""
    detail = ", ".join(f"{r.name} {r.score}/5 (threshold {threshold:g})" for r in failing)
    return False, (
        f"\n\n_⚠️ Reviewer recommendation: {detail} — statements may not be fully "
        "supported by the retrieved sources; verify before relying on this answer._"
    )


def run_inline_judges(
    names: list[str],
    *,
    question: str,
    answer: str,
    context_passages: list[str],
    llm: object = None,
    model_role: str = "judge",
) -> list[JudgeResult]:
    """Run the gold-free judges in ``names`` and return their results.

    ``llm`` defaults to the models.yaml role in ``model_role`` (the recipe's
    ``judge.model_role``, honestly honored — F10) via ``harness.judge.Judge``.
    Non-runnable names (e.g. ``correctness``) are skipped. Never raises on a judge error
    — a failed judge is simply omitted (logged), so it can't break a turn.
    """
    runnable = runtime_judges(names)
    if not runnable:
        return []

    from harness.judge import Judge

    judge = Judge(llm, model_role=model_role)
    results: list[JudgeResult] = []
    for name in runnable:
        try:
            if name == "faithfulness":
                js = judge.faithfulness(question, answer, context_passages)
            else:  # pragma: no cover - guarded by runtime_judges
                continue
            score = int(js.get("score", 0))
            results.append(
                JudgeResult(
                    name=name,
                    score=score,
                    value=(score / 5.0) if score else 0.0,
                    rationale=str(js.get("reason", "")),
                )
            )
        except Exception as exc:
            log.warning("inline judge %r failed: %s", name, exc)
    return results

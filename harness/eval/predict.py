"""Adapt an agent/session to an ``mlflow.genai`` ``predict_fn`` (aim 1 eval).

``mlflow.genai.evaluate(predict_fn=...)`` wants a callable ``question -> output``.
``build_predict_fn`` wraps an :class:`~harness.agents.session.AgentSession` (or any
object with ``.run(query)`` / any callable) and returns the structured answer as a
plain dict so judges/scorers can read ``answer`` + ``citations``.
"""

import logging
from collections.abc import Callable
from typing import Any

from harness.schemas import RegulatoryAnswer

log = logging.getLogger(__name__)


def _to_answer(result: Any) -> RegulatoryAnswer:
    if isinstance(result, RegulatoryAnswer):
        return result
    from harness.agents.runner import coerce_answer

    return coerce_answer(result)


def build_predict_fn(runnable: Any) -> Callable[[str], dict]:
    """Return ``question:str -> {answer, citations, num_claims, confidence}``.

    ``runnable`` may be an ``AgentSession`` (uses ``.run``) or any callable
    ``question -> RegulatoryAnswer``.
    """
    runner = getattr(runnable, "run", runnable)

    def predict_fn(question: str) -> dict:
        answer = _to_answer(runner(question))
        return {
            "answer": answer.answer,
            "citations": [c.source_url for c in answer.citations],
            "num_claims": len(answer.claims),
            "confidence": answer.confidence,
        }

    return predict_fn

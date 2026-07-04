"""Adapt an agent/session/recipe-adapter to an ``mlflow.genai`` ``predict_fn`` (aim 1 eval).

``mlflow.genai.evaluate(predict_fn=...)`` wants a callable ``question -> output``.
``build_predict_fn`` accepts, in order of preference:

- an ``AgentWorkflowAdapter`` (what :func:`harness.recipes.build_recipe` returns) — its
  ``invoke`` contract already carries the retrieved passages as ``context_passages``;
- an :class:`~harness.agents.session.AgentSession` (uses ``.run``) or any bare callable
  ``question -> RegulatoryAnswer`` — the retrieval is captured around the call via
  :func:`~harness.tools.search.capture_search_nodes`.

Either way the returned dict includes ``context_passages`` so the offline faithfulness
judge grades against the retrieval that actually ran (F3/F5).
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


def _prediction(answer: RegulatoryAnswer, context_passages: list[str]) -> dict:
    return {
        "answer": answer.answer,
        "citations": [c.source_url for c in answer.citations],
        "num_claims": len(answer.claims),
        "confidence": answer.confidence,
        "context_passages": context_passages,
    }


def build_predict_fn(runnable: Any) -> Callable[[str], dict]:
    """Return ``question:str -> {answer, citations, num_claims, confidence, context_passages}``.

    ``runnable`` may be an ``AgentWorkflowAdapter`` (uses ``.invoke``), an
    ``AgentSession`` (uses ``.run``), or any callable ``question -> RegulatoryAnswer``.
    """
    invoke = getattr(runnable, "invoke", None)
    if callable(invoke):

        def predict_fn(question: str) -> dict:
            result = invoke({"question": question, "source": "eval"})
            answer = _to_answer(result.get("answer"))
            return _prediction(answer, list(result.get("context_passages") or []))

        return predict_fn

    runner = getattr(runnable, "run", runnable)

    def predict_fn(question: str) -> dict:
        from harness.tools.search import capture_search_nodes, passages_from_nodes

        with capture_search_nodes() as evidence:
            answer = _to_answer(runner(question))
        return _prediction(answer, passages_from_nodes(evidence))

    return predict_fn

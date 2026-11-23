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

``predict_items`` is the evaluation runner's own prediction loop. It awaits every
question on one event loop and records, per benchmark item, whether the agent finished.
It exists because of a crash: ``AgentWorkflowAdapter.invoke`` opens a new event loop per
question, while the agent's ``AsyncAnthropic`` client keeps pooled connections bound to
an earlier loop. Five evaluation traces of 2026-07-13 ended with
``RuntimeError: Event loop is closed``, and ``mlflow.genai.evaluate`` then judged those
crashed rows as answers. A probe without model calls failed 3 of 6 sequential calls with
one loop per call and 0 of 40 with one loop for all calls.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from harness.schemas import RegulatoryAnswer

log = logging.getLogger(__name__)


@dataclass
class ItemResult:
    """What the prediction loop recorded for one benchmark item.

    ``ok`` is False when the agent raised; ``error`` then holds the exception's type and
    message, and ``outputs`` is None. ``trace_id`` is the trace the item made, or None
    when no new trace appeared during the item.
    """

    bench_id: str
    question_type: str
    ok: bool
    error: str | None = None
    outputs: dict | None = None
    trace_id: str | None = None


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


async def apredict_items(
    runnable: Any,
    rows: list[dict],
    *,
    trace_id_fn: Callable[[], str | None] | None = None,
) -> list[ItemResult]:
    """Await ``runnable.ainvoke`` for each benchmark row, one after the other.

    A row whose agent raises an ``Exception`` is recorded with ``ok=False`` and the loop
    goes on. ``BaseException`` (Ctrl-C, task cancellation) is not caught: it stops the run.

    A ``trace_id`` in the ``ainvoke`` result (the adapter's own root span) is used first.
    Otherwise ``trace_id_fn`` returns the newest finished trace id of the process (default
    :func:`harness.obs.last_trace_id`). It is read before the first row and after each
    row. When the id did not change, the row made no trace and gets ``trace_id=None``:
    reusing the previous id would put a judge value on another item's trace. The lookup
    alone missed a trace that the exporter wrote late (2026-11-23, item ``T1-001``).
    """
    if trace_id_fn is None:
        from harness.obs import last_trace_id as trace_id_fn

    previous = trace_id_fn()
    results: list[ItemResult] = []
    for row in rows:
        bench_id = str(row.get("bench_id", ""))
        qtype = str(row.get("type", ""))
        own_trace_id = None
        try:
            result = await runnable.ainvoke({"question": row["question"], "source": "eval"})
            own_trace_id = result.get("trace_id")
            answer = _to_answer(result.get("answer"))
            outputs: dict | None = _prediction(answer, list(result.get("context_passages") or []))
            ok, error = True, None
        except Exception as exc:
            log.warning("item %s failed: %s: %s", bench_id, type(exc).__name__, exc)
            outputs, ok, error = None, False, f"{type(exc).__name__}: {exc}"
        current = trace_id_fn()
        trace_id = own_trace_id or (current if current is not None and current != previous else None)
        if current is not None:
            previous = current
        results.append(
            ItemResult(
                bench_id=bench_id,
                question_type=qtype,
                ok=ok,
                error=error,
                outputs=outputs,
                trace_id=trace_id,
            )
        )
    return results


def predict_items(
    runnable: Any,
    rows: list[dict],
    *,
    trace_id_fn: Callable[[], str | None] | None = None,
) -> list[ItemResult]:
    """Run :func:`apredict_items` inside one event loop for all rows (sync entry point)."""
    return asyncio.run(apredict_items(runnable, rows, trace_id_fn=trace_id_fn))

"""MLflow tracing setup for the agentic pipeline.

``setup_tracing`` points MLflow at an experiment and enables LlamaIndex autolog
when available (``mlflow.llama_index`` — the ``mlflow[llama-index]`` extra).
FunctionAgent runs on the LlamaIndex Workflow engine, and autolog of workflows has
a known trace-completion caveat (mlflow#13352); ``traced()`` opens an explicit
MLflow span as a fallback root so ``ema.*`` config attributes always have a span to
land on. All ops no-op gracefully when mlflow is unavailable.

Runtime-verified later (autolog needs ``mlflow[llama-index]``; spans need a live
tracking backend).
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from harness.obs.runs import _mlflow, setup_mlflow

log = logging.getLogger(__name__)


def enable_llama_index_autolog() -> bool:
    """Enable MLflow autolog for LlamaIndex. Returns False if the integration is absent."""
    try:
        import mlflow.llama_index as mlflow_llama_index

        mlflow_llama_index.autolog()
        return True
    except Exception as exc:
        log.info(
            "mlflow.llama_index autolog unavailable (%s) — install mlflow[llama-index]", exc
        )
        return False


def setup_tracing(
    experiment: str = "ema_nlp",
    *,
    tracking_uri: str | None = None,
    autolog: bool = True,
) -> bool:
    """Point MLflow at ``experiment`` and (optionally) enable LlamaIndex autolog."""
    ok = setup_mlflow(experiment, tracking_uri=tracking_uri)
    if ok and autolog:
        enable_llama_index_autolog()
    return ok


@contextmanager
def traced(name: str, *, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """Open an explicit MLflow span (no-op/yield None if mlflow/spans unavailable)."""
    mf = _mlflow()
    span_cm = None
    if mf is not None:
        try:
            span_cm = mf.start_span(name=name)
        except Exception:
            span_cm = None
    if span_cm is None:
        yield None
        return
    with span_cm as span:
        if attributes:
            try:
                span.set_attributes(dict(attributes))
            except Exception:
                pass
        yield span

"""MLflow tracing + human-feedback for the live app and the agentic pipeline.

``setup_tracing`` points MLflow at a tracking backend + experiment and enables
LlamaIndex autolog when available (``mlflow.llama_index`` — present whenever
``llama-index`` is installed). FunctionAgent and the LlamaIndex Workflows both run
on the Workflow engine; autolog has a known trace-completion caveat on some
versions (mlflow#13352), so ``traced()`` opens an explicit MLflow span as a root
that the ``ema.*`` config attributes always land on (autolog spans nest under it).

Feedback: ``log_user_feedback`` attaches a 👍/👎 (or numeric) assessment to a trace
via ``mlflow.log_feedback``. MLflow exports traces *asynchronously*, so it flushes
the trace queue first; otherwise the assessment can race the export and 404.

All ops no-op gracefully when mlflow is unavailable **or** tracing was never set up
(so a ``EMA_TRACING_DISABLED`` run never touches a tracking backend).
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from harness.obs.runs import DEFAULT_EXPERIMENT, _mlflow, setup_mlflow

log = logging.getLogger(__name__)

# Flipped True by ``setup_tracing``. ``traced()`` checks it so spans are only opened
# once a backend is configured — a disabled run leaves it False and stays inert.
_TRACING_ENABLED = False
_EXPERIMENT = DEFAULT_EXPERIMENT


def tracing_enabled() -> bool:
    """True once ``setup_tracing`` has configured a backend this process."""
    return _TRACING_ENABLED


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
    experiment: str = DEFAULT_EXPERIMENT,
    *,
    tracking_uri: str | None = None,
    autolog: bool = True,
) -> bool:
    """Point MLflow at ``experiment`` and (optionally) enable LlamaIndex autolog.

    On success, marks tracing enabled for this process so ``traced()`` starts
    opening spans.
    """
    global _TRACING_ENABLED, _EXPERIMENT
    ok = setup_mlflow(experiment, tracking_uri=tracking_uri)
    if ok:
        _TRACING_ENABLED = True
        _EXPERIMENT = experiment
        if autolog:
            enable_llama_index_autolog()
    return ok


@contextmanager
def traced(name: str, *, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """Open an explicit MLflow span (no-op/yield None if tracing is off/unavailable)."""
    mf = _mlflow()
    span_cm = None
    if mf is not None and _TRACING_ENABLED:
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
                # MLflow span attributes must be JSON-scalars; drop Nones.
                span.set_attributes({k: v for k, v in attributes.items() if v is not None})
            except Exception:
                pass
        yield span


def tag_current_trace(tags: dict[str, Any]) -> bool:
    """Best-effort: set ``tags`` on the *current trace* (the root, not a span).

    Trace-level tags are what ``mlflow.search_traces`` filters on, so the recipe
    name must land here — stamping it only on a child span makes recipe-level
    filtering require span drilling (F14). No-op (False) when tracing is off,
    no trace is active, or the client predates ``update_current_trace``.
    """
    mf = _mlflow()
    if mf is None or not _TRACING_ENABLED or not tags:
        return False
    try:
        mf.update_current_trace(tags={k: str(v) for k, v in tags.items() if v is not None})
        return True
    except Exception as exc:
        log.debug("tag_current_trace failed: %s", exc)
        return False


def record_answer_on_span(span: Any, *, question: Any = None, answer: Any = None) -> None:
    """Best-effort: set the turn's question + structured answer as the span's I/O.

    Makes the MLflow trace's root span show a uniform ``RegulatoryAnswer`` response
    regardless of strategy. No-op when ``span`` is None (tracing off) or on any error.
    """
    if span is None:
        return
    try:
        if question is not None:
            span.set_inputs({"question": question})
        if answer is not None:
            span.set_outputs(answer.model_dump() if hasattr(answer, "model_dump") else answer)
    except Exception:
        pass


def last_trace_id() -> str | None:
    """Trace id of the most recently completed trace in this process, or None."""
    mf = _mlflow()
    if mf is None or not _TRACING_ENABLED:
        return None
    try:
        return mf.get_last_active_trace_id()
    except Exception:
        return None


def _log_feedback(
    trace_id: str | None,
    *,
    name: str,
    value: bool | int | float | str,
    source_type: str,
    source_id: str,
    rationale: str | None,
    metadata: dict[str, Any] | None,
    span_id: str | None = None,
) -> bool:
    """Attach an assessment to ``trace_id`` (shared by human + judge feedback).

    Flushes MLflow's async trace export first so the trace exists before the
    assessment is written (otherwise ``log_feedback`` 404s on a not-yet-exported
    trace). Degrades to a no-op (False) when mlflow/tracing is unavailable.
    """
    mf = _mlflow()
    if mf is None or not trace_id:
        return False
    try:
        try:
            mf.flush_trace_async_logging()
        except Exception:
            pass
        source = None
        try:
            from mlflow.entities import AssessmentSource

            source = AssessmentSource(source_type=source_type, source_id=source_id)
        except Exception:
            source = None
        kwargs: dict[str, Any] = {}
        if span_id:
            kwargs["span_id"] = span_id  # scope the assessment to one span (OSS 3.x)
        mf.log_feedback(
            trace_id=trace_id,
            name=name,
            value=value,
            source=source,
            rationale=rationale,
            metadata=metadata,
            **kwargs,
        )
        return True
    except Exception as exc:
        log.warning("MLflow feedback failed: %s", exc)
        return False


def log_user_feedback(
    trace_id: str | None,
    *,
    value: bool | int | float,
    name: str = "user_rating",
    rationale: str | None = None,
    source_id: str = "chainlit",
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Attach a human 👍/👎 (or numeric) feedback assessment to ``trace_id``."""
    return _log_feedback(
        trace_id,
        name=name,
        value=value,
        source_type="HUMAN",
        source_id=source_id,
        rationale=rationale,
        metadata=metadata,
    )


def log_citation_feedback(
    trace_id: str | None,
    *,
    rank: int,
    verdict: str,
    chunk_id: str = "",
    doc_id: str = "",
    source_url: str = "",
    category: str = "",
    preferred_category: str | None = None,
    note: str | None = None,
    run_id: str = "",
    source_id: str = "chainlit",
    span_id: str | None = None,
) -> bool:
    """Attach one SME per-citation verdict to ``trace_id`` (the citation-review loop).

    ``verdict`` is ``supports | partial | no`` (plus the optional
    ``preferred_category`` when the source *type* is wrong — the
    EPAR-where-a-guideline-belongs case). Each citation gets a UNIQUE assessment
    name (``citation_<rank>_<chunk8>``) so re-rating one citation never
    overwrites another; the metadata carries everything a future re-ranking
    aggregation needs. Mirrors the ``step_quality`` pattern that
    ``harness.export_traces`` reads back.
    """
    chunk8 = (chunk_id or "x")[:8]
    metadata: dict[str, Any] = {
        "rank": rank,
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "source_url": source_url,
        "category": category,
        "run_id": run_id,
    }
    if preferred_category:
        metadata["preferred_category"] = preferred_category
    return _log_feedback(
        trace_id,
        name=f"citation_{rank}_{chunk8}",
        value=verdict,
        source_type="HUMAN",
        source_id=source_id,
        rationale=note or None,
        metadata=metadata,
        span_id=span_id,
    )


def log_judge_feedback(
    trace_id: str | None,
    *,
    name: str,
    value: bool | int | float,
    rationale: str | None = None,
    source_id: str = "llm_judge",
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Attach an LLM-judge assessment to ``trace_id`` (the optional inline judge layer).

    Logged with ``source_type="LLM_JUDGE"`` so it appears in MLflow alongside — but
    distinct from — human feedback. Returns True if logged.
    """
    return _log_feedback(
        trace_id,
        name=name,
        value=value,
        source_type="LLM_JUDGE",
        source_id=source_id,
        rationale=rationale,
        metadata=metadata,
    )


def experiment_traces_url(ui_url: str, experiment: str | None = None) -> str:
    """Best-effort deep link to the experiment's Traces tab in the MLflow UI.

    Falls back to the UI root if the experiment id can't be resolved.
    """
    mf = _mlflow()
    exp_name = experiment or _EXPERIMENT
    if mf is not None:
        try:
            exp = mf.get_experiment_by_name(exp_name)
            if exp is not None:
                return f"{ui_url}/#/experiments/{exp.experiment_id}/traces"
        except Exception:
            pass
    return ui_url

"""MLflow run recording — local, server-free reproducibility (no ``log_model``).

Records each pipeline run as an MLflow run: the resolved config as params, the
answer's shape as metrics, and the answer text as an artifact. This is the
reproducibility substrate the target architecture relies on (MLflow runs + params
+ artifacts), deliberately *without* ``log_model`` (see DECISIONS / target doc).

Defaults to a local **file-store** tracking URI (``./mlruns``) and opts out of
MLflow's file-store maintenance-mode exception, so it needs **no server and no SQL
backend**. Switch ``tracking_uri`` to ``sqlite:///mlflow.db`` or a server URL in
production. Degrades gracefully if ``mlflow`` is not importable (all ops no-op).

See ``docs/TARGET_ARCHITECTURE.md`` §4.7.
"""

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from harness.schemas import RegulatoryAnswer

log = logging.getLogger(__name__)

DEFAULT_EXPERIMENT = "ema_nlp"
DEFAULT_TRACKING_DIR = "mlruns"
_PARAM_VALUE_MAX = 250


def _mlflow() -> Any:
    """Return the ``mlflow`` module, or ``None`` if it is not importable."""
    try:
        import mlflow

        return mlflow
    except Exception:
        return None


def mlflow_available() -> bool:
    """True if ``mlflow`` can be imported."""
    return _mlflow() is not None


def setup_mlflow(experiment: str = DEFAULT_EXPERIMENT, *, tracking_uri: str | None = None) -> bool:
    """Point MLflow at a tracking backend + experiment. Returns False if unavailable."""
    mf = _mlflow()
    if mf is None:
        log.info("mlflow not installed — run recording disabled")
        return False
    # The file store is in maintenance mode in mlflow>=3; opt out so the local,
    # server-free backend keeps working.
    os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
    uri = tracking_uri or f"file:{Path(DEFAULT_TRACKING_DIR).resolve()}"
    mf.set_tracking_uri(uri)
    mf.set_experiment(experiment)
    log.info("mlflow tracking → %s (experiment=%s)", uri, experiment)
    return True


class RunHandle:
    """Thin handle over the active MLflow run (all methods no-op when unavailable)."""

    def __init__(self, mlflow_module: Any) -> None:
        self._mf = mlflow_module

    @property
    def active(self) -> bool:
        return self._mf is not None

    def log_param(self, key: str, value: Any) -> None:
        if self._mf is not None:
            self._mf.log_param(key, str(value)[:_PARAM_VALUE_MAX])

    def log_params(self, params: dict[str, Any]) -> None:
        if self._mf is not None and params:
            self._mf.log_params(params)

    def log_metric(self, key: str, value: float) -> None:
        if self._mf is not None:
            self._mf.log_metric(key, float(value))

    def log_metrics(self, metrics: dict[str, float]) -> None:
        if self._mf is not None and metrics:
            self._mf.log_metrics({k: float(v) for k, v in metrics.items()})

    def log_text(self, text: str, artifact_file: str) -> None:
        if self._mf is not None:
            self._mf.log_text(text, artifact_file)


@contextmanager
def record_run(
    run_name: str,
    *,
    params: dict[str, Any] | None = None,
    tags: dict[str, Any] | None = None,
) -> Iterator[RunHandle]:
    """Open an MLflow run and yield a :class:`RunHandle`.

    ``params`` should already be flattened scalars (e.g. from
    ``RetrievalPipelineConfig.resolved_attributes()`` or
    ``harness.obs.resolved_config_attributes``).
    """
    mf = _mlflow()
    if mf is None:
        yield RunHandle(None)
        return
    with mf.start_run(run_name=run_name, tags=tags):
        if params:
            mf.log_params(params)
        yield RunHandle(mf)


def answer_metrics(answer: RegulatoryAnswer) -> dict[str, float]:
    """Numeric shape of an answer (logged as MLflow metrics)."""
    return {
        "answer_chars": float(len(answer.answer)),
        "num_citations": float(len(answer.citations)),
        "num_claims": float(len(answer.claims)),
        "confidence": float(answer.confidence),
    }


def record_answer_run(
    run_name: str,
    answer: RegulatoryAnswer,
    *,
    params: dict[str, Any] | None = None,
    query: str | None = None,
) -> bool:
    """Log a run with config params + answer metrics + the answer text artifact.

    Returns True if recorded (mlflow available), False otherwise. Call
    :func:`setup_mlflow` first (or rely on MLflow's default tracking URI).
    """
    with record_run(run_name, params=params) as handle:
        if not handle.active:
            return False
        if query:
            handle.log_param("query", query)
        handle.log_metrics(answer_metrics(answer))
        handle.log_text(answer.answer, "answer.txt")
    return True

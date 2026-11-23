"""Run ``mlflow.genai`` evaluation over a dataset with scorers (and an optional predict_fn).

Thin lazy wrapper: points MLflow at an experiment (local file store by default) and
calls ``mlflow.genai.evaluate``. Runtime (needs LLM judges + a dataset).
"""

import logging
from typing import Any

log = logging.getLogger(__name__)


def run_evaluation(
    data: Any,
    *,
    scorers: list,
    predict_fn: Any = None,
    experiment: str | None = None,
    tracking_uri: str | None = None,
    configure: bool = True,
) -> Any:
    """Evaluate ``data`` with ``scorers`` and log to MLflow.

    Without ``predict_fn`` each row of ``data`` carries its own ``outputs`` (and may
    carry ``trace``); this is how the eval runner passes the items it predicted itself.

    ``experiment=None`` resolves via ``EMA_MLFLOW_EXPERIMENT`` (same resolver as the
    live app) so eval assessments land in the same experiment as human feedback (F15).
    ``configure=False`` keeps the tracking URI and experiment the caller set up: the
    eval runner calls this inside a run it opened.
    """
    import mlflow.genai as genai

    from harness.obs import default_experiment, setup_mlflow

    if configure:
        setup_mlflow(experiment or default_experiment(), tracking_uri=tracking_uri)
    return genai.evaluate(data=data, predict_fn=predict_fn, scorers=scorers)

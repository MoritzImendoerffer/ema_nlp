"""Run ``mlflow.genai`` evaluation over a dataset with a predict_fn + scorers.

Thin lazy wrapper: points MLflow at an experiment (local file store by default) and
calls ``mlflow.genai.evaluate``. Runtime (needs LLM judges + a dataset).
"""

import logging
from typing import Any

log = logging.getLogger(__name__)


def run_evaluation(
    data: Any,
    *,
    predict_fn: Any,
    scorers: list,
    experiment: str | None = None,
    tracking_uri: str | None = None,
) -> Any:
    """Evaluate ``predict_fn`` over ``data`` with ``scorers`` and log to MLflow.

    ``experiment=None`` resolves via ``EMA_MLFLOW_EXPERIMENT`` (same resolver as the
    live app) so eval assessments land in the same experiment as human feedback (F15).
    """
    import mlflow.genai as genai

    from harness.obs import default_experiment, setup_mlflow

    setup_mlflow(experiment or default_experiment(), tracking_uri=tracking_uri)
    return genai.evaluate(data=data, predict_fn=predict_fn, scorers=scorers)

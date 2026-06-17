"""Observability helpers (transparency / resolved-config stamping).

See ``docs/TARGET_ARCHITECTURE.md`` §4.7.
"""

from harness.obs.config_attrs import (
    echo_resolved_config,
    resolved_config_attributes,
    stamp_current_span,
)
from harness.obs.runs import (
    RunHandle,
    answer_metrics,
    mlflow_available,
    record_answer_run,
    record_run,
    setup_mlflow,
)

__all__ = [
    "RunHandle",
    "answer_metrics",
    "echo_resolved_config",
    "mlflow_available",
    "record_answer_run",
    "record_run",
    "resolved_config_attributes",
    "setup_mlflow",
    "stamp_current_span",
]

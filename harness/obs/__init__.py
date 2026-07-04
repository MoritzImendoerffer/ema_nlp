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
    default_experiment,
    mlflow_available,
    record_answer_run,
    record_run,
    setup_mlflow,
)
from harness.obs.tracing import (
    enable_llama_index_autolog,
    experiment_traces_url,
    last_trace_id,
    log_judge_feedback,
    log_user_feedback,
    record_answer_on_span,
    setup_tracing,
    tag_current_trace,
    traced,
    tracing_enabled,
)

__all__ = [
    "RunHandle",
    "answer_metrics",
    "default_experiment",
    "echo_resolved_config",
    "enable_llama_index_autolog",
    "experiment_traces_url",
    "last_trace_id",
    "log_judge_feedback",
    "log_user_feedback",
    "mlflow_available",
    "record_answer_on_span",
    "record_answer_run",
    "record_run",
    "resolved_config_attributes",
    "setup_mlflow",
    "setup_tracing",
    "stamp_current_span",
    "tag_current_trace",
    "traced",
    "tracing_enabled",
]

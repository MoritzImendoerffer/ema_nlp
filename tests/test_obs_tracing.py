"""Unit tests for harness.obs.tracing (MLflow tracing setup, graceful)."""

from harness.obs import enable_llama_index_autolog, setup_tracing
from harness.obs.tracing import traced


def test_enable_llama_index_autolog_absent_returns_false():
    # mlflow.llama_index (the mlflow[llama-index] extra) isn't installed in CI.
    assert enable_llama_index_autolog() is False


def test_setup_tracing_returns_true(tmp_path):
    assert setup_tracing(
        "trace_exp", tracking_uri=f"file:{tmp_path / 'mlruns'}", autolog=False
    ) is True


def test_traced_context_does_not_raise(tmp_path):
    setup_tracing("trace_exp2", tracking_uri=f"file:{tmp_path / 'mlruns'}", autolog=False)
    with traced("unit", attributes={"ema.x": "y"}):
        pass

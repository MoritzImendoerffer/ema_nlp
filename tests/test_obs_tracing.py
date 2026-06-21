"""Unit tests for harness.obs.tracing (MLflow tracing setup, graceful)."""

from harness.obs import enable_llama_index_autolog, setup_tracing
from harness.obs.tracing import traced


def test_enable_llama_index_autolog_reflects_availability():
    # Returns True iff the mlflow.llama_index integration is importable (it ships in
    # mlflow core and only needs llama-index present), False otherwise. This holds in
    # both CI (extra absent -> False) and on a host with llama-index installed (-> True).
    try:
        import mlflow.llama_index  # noqa: F401

        available = True
    except Exception:
        available = False
    assert enable_llama_index_autolog() is available


def test_setup_tracing_returns_true(tmp_path):
    assert setup_tracing(
        "trace_exp", tracking_uri=f"file:{tmp_path / 'mlruns'}", autolog=False
    ) is True


def test_traced_context_does_not_raise(tmp_path):
    setup_tracing("trace_exp2", tracking_uri=f"file:{tmp_path / 'mlruns'}", autolog=False)
    with traced("unit", attributes={"ema.x": "y"}):
        pass

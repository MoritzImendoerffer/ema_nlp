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


def test_log_citation_feedback_maps_params(monkeypatch):
    """The per-citation helper builds a unique name, verdict value, and the
    re-ranking metadata (rank/ids/category/preferred), and passes span_id."""
    import harness.obs.tracing as tracing

    calls = {}

    class _FakeMlflow:
        def flush_trace_async_logging(self):
            pass

        def log_feedback(self, **kwargs):
            calls.update(kwargs)

    monkeypatch.setattr(tracing, "_mlflow", lambda: _FakeMlflow())
    ok = tracing.log_citation_feedback(
        "trace-1",
        rank=2,
        verdict="partial",
        chunk_id="chunk-abcdef123",
        doc_id="doc-1",
        source_url="https://ema.eu/x",
        category="epar",
        preferred_category="scientific_guideline",
        note="guideline should be cited first",
        run_id="run-9",
        span_id="span-7",
    )
    assert ok is True
    assert calls["trace_id"] == "trace-1"
    assert calls["name"] == "citation_2_chunk-ab"
    assert calls["value"] == "partial"
    assert calls["rationale"] == "guideline should be cited first"
    assert calls["span_id"] == "span-7"
    md = calls["metadata"]
    assert md["rank"] == 2 and md["category"] == "epar"
    assert md["preferred_category"] == "scientific_guideline"
    assert md["run_id"] == "run-9"


def test_log_citation_feedback_without_trace_is_noop(monkeypatch):
    import harness.obs.tracing as tracing

    assert tracing.log_citation_feedback("", rank=1, verdict="supports") is False

"""Unit tests for harness.obs.runs (MLflow run recording, local file store).

Uses a temp file-store tracking URI (no server) and reads runs back via
MlflowClient (no pandas). Also verifies graceful no-op when mlflow is absent.
"""

from harness.obs.runs import (
    answer_metrics,
    mlflow_available,
    record_answer_run,
    record_run,
    setup_mlflow,
)
from harness.schemas import Citation, Claim, RegulatoryAnswer


def _answer() -> RegulatoryAnswer:
    return RegulatoryAnswer(
        answer="The AI for NDMA is 96 ng/day.",
        claims=[Claim(text="AI for NDMA is 96 ng/day", citations=[Citation(source_url="u")])],
        citations=[Citation(source_url="u1"), Citation(source_url="u2")],
        confidence=0.8,
    )


def test_answer_metrics():
    m = answer_metrics(_answer())
    assert m["num_citations"] == 2.0
    assert m["num_claims"] == 1.0
    assert m["confidence"] == 0.8
    assert m["answer_chars"] > 0


def test_mlflow_available_in_test_env():
    assert mlflow_available() is True


def test_record_run_logs_params_and_metrics_to_file_store(tmp_path):
    uri = f"file:{tmp_path / 'mlruns'}"
    assert setup_mlflow("test_exp", tracking_uri=uri) is True

    ok = record_answer_run(
        "run1",
        _answer(),
        params={"ema.retrieval.k": 20, "ema.retrieval.graph_mode": "links"},
        query="what is the AI for NDMA?",
    )
    assert ok is True

    from mlflow.tracking import MlflowClient

    client = MlflowClient(tracking_uri=uri)
    experiment = client.get_experiment_by_name("test_exp")
    runs = client.search_runs([experiment.experiment_id])
    assert len(runs) == 1
    run = runs[0]
    assert run.data.params["ema.retrieval.k"] == "20"
    assert run.data.params["ema.retrieval.graph_mode"] == "links"
    assert run.data.params["query"].startswith("what is the AI")
    assert run.data.metrics["num_citations"] == 2.0
    assert run.data.metrics["confidence"] == 0.8


def test_record_run_context_manager_yields_active_handle(tmp_path):
    setup_mlflow("test_exp2", tracking_uri=f"file:{tmp_path / 'mlruns'}")
    with record_run("r", params={"ema.x": 1}) as handle:
        assert handle.active is True
        handle.log_metric("m", 2.0)


def test_graceful_noop_without_mlflow(monkeypatch):
    import harness.obs.runs as runs_mod

    monkeypatch.setattr(runs_mod, "_mlflow", lambda: None)
    assert runs_mod.setup_mlflow() is False
    with runs_mod.record_run("r", params={"a": 1}) as handle:
        assert handle.active is False
        handle.log_metric("x", 1.0)  # must not raise
    assert runs_mod.record_answer_run("r", _answer()) is False

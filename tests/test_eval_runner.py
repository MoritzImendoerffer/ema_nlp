"""Unit tests for harness.eval.runner (pure parts of the R6 recipe×benchmark vehicle).

run_recipe_benchmark itself is runtime-only (Neo4j + model credentials); the
loading / data-shaping / grouping / summary pieces are verified offline against
the real shipped benchmark file.
"""

import json

import pytest

from harness.eval.predict import ItemResult
from harness.eval.runner import (
    BENCHMARK_PATH,
    JudgeStats,
    TypeSummary,
    format_summary,
    group_by_type,
    judged_rows,
    load_benchmark,
    score_stats,
)


def test_load_shipped_benchmark_all_types_present():
    rows = load_benchmark(BENCHMARK_PATH)
    assert len(rows) == 45
    assert {r["type"] for r in rows} == {"T1", "T2", "T3", "T4"}
    assert all(r["question"] and r["gold_answer"] for r in rows)


def test_load_benchmark_type_filter_and_per_type_limit():
    rows = load_benchmark(BENCHMARK_PATH, types=["T1", "T3"], limit=2)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["type"]] = counts.get(r["type"], 0) + 1
    assert counts == {"T1": 2, "T3": 2}  # limit is per type, not global


def test_load_benchmark_empty_selection_raises(tmp_path):
    path = tmp_path / "bench.jsonl"
    path.write_text(json.dumps({"type": "T1", "question": "q", "gold_answer": "a"}) + "\n")
    with pytest.raises(ValueError):
        load_benchmark(path, types=["T4"])


def test_group_by_type_ordered_t1_to_t4():
    rows = [{"type": t, "question": "q", "gold_answer": "a"} for t in ("T3", "T1", "T4", "T1")]
    grouped = group_by_type(rows)
    assert list(grouped) == ["T1", "T3", "T4"]
    assert len(grouped["T1"]) == 2


def test_group_by_type_includes_showcase_t5_after_t4():
    rows = [{"type": t, "question": "q", "gold_answer": "a"} for t in ("T5", "T1", "T4")]
    grouped = group_by_type(rows)
    assert list(grouped) == ["T1", "T4", "T5"]  # T5 groups cleanly, not "unknown"
    assert "unknown" not in grouped


def test_showcase_benchmark_file_loads_as_t5():
    from pathlib import Path

    from harness.eval.runner import BENCHMARK_PATH

    path = Path(BENCHMARK_PATH).parent / "showcase.jsonl"
    rows = load_benchmark(path)
    assert rows and all(r["type"] == "T5" for r in rows)
    assert all(r["question"] and r["gold_answer"] for r in rows)
    assert all(r["gold_sources"] for r in rows)  # every showcase item names its anchor


# --- judged rows, counts and the printed summary (eval reliability, TASK-004) ---

_BENCH = [
    {"bench_id": "T1-001", "type": "T1", "question": "q1", "gold_answer": "g1"},
    {"bench_id": "T1-002", "type": "T1", "question": "q2", "gold_answer": "g2"},
    {"bench_id": "T1-003", "type": "T1", "question": "q3", "gold_answer": "g3"},
]


def _item(bench_id, ok=True, error=None):
    outputs = {"answer": f"a-{bench_id}", "context_passages": []} if ok else None
    return ItemResult(bench_id=bench_id, question_type="T1", ok=ok, error=error, outputs=outputs)


def test_eval_rows_carry_bench_id_and_leave_out_a_failed_item():
    """to_eval_data dropped bench_id, and mlflow judged the crashed rows."""
    items = [_item("T1-001"), _item("T1-002", ok=False, error="RuntimeError: x"), _item("T1-003")]
    trace = object()
    data = judged_rows(items, _BENCH, traces={"T1-003": trace})
    assert len(data) == 2
    for entry, bench_id in zip(data, ["T1-001", "T1-003"], strict=True):
        assert entry["inputs"]["question"]
        assert entry["outputs"]["answer"] == f"a-{bench_id}"
        assert entry["expectations"]["gold_answer"]
        assert entry["tags"]["ema.bench_id"] == bench_id
    assert "trace" not in data[0]
    assert data[1]["trace"] is trace


def test_score_stats_counts_a_value_that_is_not_a_number():
    """A text value such as ' agent errored' was skipped by the mean and never counted."""
    stats = score_stats({"faithfulness": [5, " agent errored", None, 3]}, finished=4)
    assert stats["faithfulness"] == JudgeStats(mean=4.0, n=2, invalid=2)


def test_score_stats_counts_a_missing_judge_value():
    """A judge call that left no assessment at all still counts as invalid."""
    stats = score_stats({"correctness": [4, 5]}, finished=3)
    assert stats["correctness"].invalid == 1
    assert stats["correctness"].n == 2


def test_format_summary_prints_n_failed_ids_and_invalid():
    items = [
        _item("T1-001"),
        _item("T1-002", ok=False, error="RuntimeError: Event loop is closed\nTraceback ..."),
        _item("T1-003"),
    ]
    stats = score_stats({"faithfulness": [4, 5], "correctness": [3, 5]}, finished=2)
    text = format_summary([TypeSummary("T1", items, stats)])
    assert "n=3 failed=1" in text
    assert "T1-002" in text
    assert "RuntimeError: Event loop is closed" in text
    assert "Traceback" not in text
    assert "judge_invalid=0" in text
    assert "faithfulness=4.500 (n=2)" in text
    assert "correctness=4.000 (n=2)" in text


def test_format_summary_for_a_type_where_every_item_failed():
    items = [_item(f"T1-00{i}", ok=False, error="RuntimeError: x") for i in (1, 2, 3)]
    stats = score_stats({"faithfulness": [], "correctness": []}, finished=0)
    text = format_summary([TypeSummary("T1", items, stats)])
    first = text.splitlines()[0]
    assert "n=3 failed=3" in first
    assert "faithfulness=" not in text and "correctness=" not in text


# --- the offline driver against the installed mlflow (eval reliability, TASK-005) ---
#
# These tests call the real mlflow.genai.evaluate on a sqlite store under a temporary
# directory. The agent and the judges are stand-ins: no model call, no Neo4j.


@pytest.fixture(scope="module")
def _eval_db(tmp_path_factory):
    root = tmp_path_factory.mktemp("eval_store")
    return f"sqlite:///{root / 'mlflow.db'}", root


@pytest.fixture
def eval_store(_eval_db, monkeypatch, request):
    """A fresh experiment in a temporary store; never the repository's mlflow.db."""
    import mlflow
    import mlflow.tracking.fluent as fluent

    import harness.obs.tracing as tracing

    uri, root = _eval_db
    previous_uri, previous_exp = mlflow.get_tracking_uri(), fluent._active_experiment_id
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    # Synchronous trace export: each flush of the async queue waits up to 1 s.
    monkeypatch.setenv("MLFLOW_ENABLE_ASYNC_TRACE_LOGGING", "false")
    mlflow.set_tracking_uri(uri)
    name = request.node.name
    exp_id = mlflow.create_experiment(name, artifact_location=(root / name).as_uri())
    mlflow.set_experiment(experiment_id=exp_id)
    # last_trace_id() reads traces only once tracing is marked enabled.
    monkeypatch.setattr(tracing, "_TRACING_ENABLED", True)
    yield exp_id
    mlflow.flush_trace_async_logging()
    mlflow.set_tracking_uri(previous_uri)
    fluent._active_experiment_id = previous_exp


_T1_ROWS = [
    {"bench_id": f"T1-00{i}", "type": "T1", "question": f"q{i}", "gold_answer": f"g{i}"}
    for i in (1, 2, 3)
]
_RUN_TAGS = {"ema.recipe": "naive_rag", "ema.benchmark": "benchmark.jsonl"}


class _TracedAgent:
    """Opens two nested spans per question, as the real agent's trace has many."""

    def __init__(self, fail_on=(), traced=True):
        self.fail_on, self.traced = set(fail_on), traced

    async def ainvoke(self, payload):
        import mlflow

        from harness.schemas import RegulatoryAnswer

        question = payload["question"]
        if not self.traced:
            return {"answer": RegulatoryAnswer(answer=f"A:{question}"), "context_passages": ["p"]}
        with mlflow.start_span(name="agent"), mlflow.start_span(name="retrieve"):
            if question in self.fail_on:
                raise RuntimeError("Event loop is closed")
            return {"answer": RegulatoryAnswer(answer=f"A:{question}"), "context_passages": ["p"]}


def _counting_scorers(faith_values=None):
    """Two stand-in judges named like the real ones; each counts its calls."""
    from mlflow.genai.scorers import scorer

    calls = {"faithfulness": 0, "correctness": 0}
    faith_values = dict(faith_values or {})

    @scorer(name="faithfulness")
    def faithfulness(outputs):
        calls["faithfulness"] += 1
        return faith_values.get(outputs["answer"], 4)

    @scorer(name="correctness")
    def correctness(outputs):
        calls["correctness"] += 1
        return 5

    return [faithfulness, correctness], calls


def _run_data(run_id):
    from mlflow.tracking import MlflowClient

    return MlflowClient().get_run(run_id).data


def test_failed_item_is_counted_and_not_judged(eval_store):
    """A crashed item is listed by id, gets no judge call, and is out of every mean."""
    import mlflow

    from harness.eval.runner import evaluate_items

    scorers, calls = _counting_scorers()
    summaries = evaluate_items(
        _TracedAgent(fail_on={"q2"}), _T1_ROWS, scorers, run_tags=_RUN_TAGS
    )
    text = format_summary(summaries)
    assert "n=3 failed=1" in text
    assert "T1-002" in text
    assert calls == {"faithfulness": 2, "correctness": 2}
    (summary,) = summaries
    assert summary.stats["faithfulness"].n == 2
    assert summary.stats["correctness"].n == 2

    data = _run_data(summary.run_id)
    assert data.metrics["n"] == 3
    assert data.metrics["failed"] == 1
    assert data.metrics["judge_invalid"] == 0
    assert data.tags["ema.recipe"] == "naive_rag"
    assert data.tags["ema.benchmark"] == "benchmark.jsonl"
    assert data.tags["ema.question_type"] == "T1"

    traces = mlflow.search_traces(run_id=summary.run_id, return_type="list")
    bench_ids = sorted(t.info.tags.get("ema.bench_id") for t in traces)
    assert bench_ids == ["T1-001", "T1-002", "T1-003"]


def test_judge_values_land_on_the_agents_own_trace(eval_store):
    """Without the trace column, mlflow puts each judge value on a new one-span trace."""
    import mlflow

    from harness.eval.runner import evaluate_items

    scorers, _ = _counting_scorers()
    (summary,) = evaluate_items(_TracedAgent(), _T1_ROWS[:1], scorers, run_tags=_RUN_TAGS)
    traces = mlflow.search_traces(run_id=summary.run_id, return_type="list")
    judged = [t for t in traces if any(a.name == "faithfulness" for a in t.info.assessments)]
    assert len(judged) == 1
    span_names = {s.name for s in judged[0].data.spans}
    assert {"agent", "retrieve"} <= span_names
    assert "root_span" not in span_names


def test_judge_text_value_is_counted_as_invalid(eval_store):
    from harness.eval.runner import evaluate_items

    scorers, _ = _counting_scorers(faith_values={"A:q1": " agent errored", "A:q2": 3})
    (summary,) = evaluate_items(_TracedAgent(), _T1_ROWS[:2], scorers, run_tags=_RUN_TAGS)
    assert "judge_invalid=1" in format_summary([summary])
    assert summary.stats["faithfulness"].mean == 3.0
    assert summary.stats["faithfulness"].invalid == 1


def test_type_where_every_item_failed_gets_a_run_and_no_judge_call(eval_store):
    from harness.eval.runner import evaluate_items

    scorers, calls = _counting_scorers()
    (summary,) = evaluate_items(
        _TracedAgent(fail_on={"q1", "q2", "q3"}), _T1_ROWS, scorers, run_tags=_RUN_TAGS
    )
    data = _run_data(summary.run_id)
    assert data.metrics["failed"] == data.metrics["n"] == 3
    assert calls == {"faithfulness": 0, "correctness": 0}


def test_finished_item_without_a_trace_is_judged_and_counted(eval_store):
    """An answer exists, so the item is judged; the missing trace is counted, not hidden."""
    from harness.eval.runner import evaluate_items

    scorers, calls = _counting_scorers()
    (summary,) = evaluate_items(
        _TracedAgent(traced=False), _T1_ROWS[:1], scorers, run_tags=_RUN_TAGS
    )
    assert calls == {"faithfulness": 1, "correctness": 1}
    assert "no_trace=1" in format_summary([summary])
    assert _run_data(summary.run_id).metrics["no_trace"] == 1


# --- the judge as a setting, both model ids on the run (eval reliability, TASK-007) ---


def test_judge_option_reaches_the_judges(monkeypatch):
    """run_eval.py had --model for the generator and nothing for the judge."""
    import runpy
    import sys
    import types

    import mlflow.genai.judges as mj

    import harness.eval.runner as runner_mod
    from harness.eval.judges import ema_judges
    from harness.recipes import get_recipe

    received = {}

    def fake_run(recipe_name, **kwargs):
        received.update(kwargs, recipe=recipe_name)
        return runner_mod.EvalReport(summaries=[])

    monkeypatch.setattr(runner_mod, "run_recipe_benchmark", fake_run)
    monkeypatch.setitem(sys.modules, "config", types.ModuleType("config"))  # no env file load
    monkeypatch.setattr(sys, "argv", ["run_eval.py", "--recipe", "naive_rag", "--judge", "claude_sonnet"])
    runpy.run_path("scripts/run_eval.py", run_name="__main__")
    assert received["recipe"] == "naive_rag"
    assert received["judge"] == "claude_sonnet"

    # The same resolution run_recipe_benchmark makes, down to make_judge.
    choice = runner_mod.resolve_models(get_recipe("naive_rag").model, judge=received["judge"])
    built = []
    monkeypatch.setattr(mj, "make_judge", lambda **kw: built.append(kw["model"]))
    ema_judges(route=choice.judge_route)
    assert built == ["anthropic:/claude-sonnet-5", "anthropic:/claude-sonnet-5"]


def test_run_is_tagged_with_both_model_ids(eval_store):
    from harness.eval.runner import evaluate_items, resolve_models

    choice = resolve_models("claude_opus", judge="claude_sonnet")
    scorers, _ = _counting_scorers()
    (summary,) = evaluate_items(
        _TracedAgent(), _T1_ROWS[:1], scorers, run_tags={**_RUN_TAGS, **choice.run_tags()}
    )
    tags = _run_data(summary.run_id).tags
    assert tags["ema.generator_model"] == "claude-opus-4-7"
    assert tags["ema.judge_model"] == "claude-sonnet-5"


def test_summary_names_both_models_and_warns_when_they_are_one():
    from harness.eval.runner import EvalReport, resolve_models

    differ = resolve_models("claude_opus", judge="claude_sonnet")
    text = EvalReport(summaries=[], header=differ.header()).text()
    assert "claude-opus-4-7" in text and "claude-sonnet-5" in text
    assert not [line for line in text.splitlines() if line.startswith("WARNING")]

    same = resolve_models("claude_opus", judge="claude_opus")
    lines = EvalReport(summaries=[], header=same.header()).text().splitlines()
    assert len([line for line in lines if line.startswith("WARNING")]) == 1


# --- the resolved recipe on the run, layers not run (eval reliability, TASK-008) ---


class _FakeSession:
    async def arun(self, user_msg):
        from harness.schemas import RegulatoryAnswer

        return RegulatoryAnswer(answer=f"A:{user_msg}")


def test_run_carries_the_resolved_recipe(eval_store):
    """90 of 100 stored evaluation traces carried no recipe; the run carried its name only."""
    import mlflow

    from harness.agents.workflow_adapter import AgentWorkflowAdapter
    from harness.eval.runner import evaluate_items
    from harness.recipes import get_recipe

    adapter = AgentWorkflowAdapter(
        _FakeSession(), extra_attributes=get_recipe("naive_rag").resolved_attributes()
    )
    scorers, _ = _counting_scorers()
    (summary,) = evaluate_items(adapter, _T1_ROWS[:1], scorers, run_tags=_RUN_TAGS)
    tags = _run_data(summary.run_id).tags
    assert tags["ema.retrieval.index_profile"] == "neo4j_hier"
    assert tags["ema.generation.model"] == "claude_opus"
    # The adapter's own root span makes the trace (setup_tracing's shape in the app).
    (trace,) = [
        t for t in mlflow.search_traces(run_id=summary.run_id, return_type="list")
        if t.info.tags.get("ema.bench_id") == "T1-001"
    ]
    assert trace.info.tags.get("ema.recipe") == "naive_rag"


def test_layers_the_runner_does_not_run_are_named():
    """regulatory_fewshot and agentic_judged ran as regulatory_agent, and nothing said so."""
    from harness.eval.runner import EvalReport, layers_not_run
    from harness.recipes import get_recipe

    def summary_lines(name):
        header = layers_not_run(get_recipe(name).resolved_attributes())
        return EvalReport(summaries=[], header=header).text().splitlines()

    fewshot = summary_lines("regulatory_fewshot")
    assert len([line for line in fewshot if "few-shot" in line]) == 1
    judged = summary_lines("agentic_judged")
    assert len([line for line in judged if "inline judge" in line]) == 1
    naive = summary_lines("naive_rag")
    assert not [line for line in naive if "few-shot" in line or "inline judge" in line]


def test_adapter_returns_its_own_trace_id(eval_store):
    """The runner takes the trace id from the adapter's root span, not the newest trace."""
    import asyncio

    import mlflow

    from harness.agents.workflow_adapter import AgentWorkflowAdapter

    result = asyncio.run(AgentWorkflowAdapter(_FakeSession()).ainvoke({"question": "q", "source": "eval"}))
    mlflow.flush_trace_async_logging()
    trace = mlflow.get_trace(result["trace_id"])
    assert trace is not None
    assert [s.name for s in trace.data.spans if s.parent_id is None] == ["AgentWorkflowAdapter.invoke"]

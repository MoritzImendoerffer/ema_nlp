"""Recipe × benchmark eval runner — the R6 experiment vehicle.

"Run recipe X on benchmark Y" as one call: build the recipe (the same
``build_recipe`` path the live app uses), predict every question on one event loop
(:func:`harness.eval.predict.predict_items`), and judge the items whose agent finished
with the project's judges. **MLflow is the system of record** (R6-Q1): one MLflow run
*per question type* (T1–T4), each tagged ``ema.recipe`` / ``ema.benchmark`` /
``ema.question_type`` when it opens — metrics are always reported broken down by type,
never aggregate-only (the CLAUDE.md eval rule). A failed item is listed and left out
of every mean, and every mean prints its n.

``load_benchmark`` / ``group_by_type`` / ``judged_rows`` / ``score_stats`` /
``format_summary`` are pure; ``evaluate_items`` is tested offline with stand-ins;
``run_recipe_benchmark`` is the runtime driver (needs Neo4j + model credentials).
CLI: ``scripts/run_eval.py``.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness.eval.predict import ItemResult

log = logging.getLogger(__name__)

BENCHMARK_PATH = Path(__file__).parents[2] / "benchmark" / "benchmark.jsonl"
# T1-T4 = the curated benchmark; T5 = link-traversal showcase items
# (benchmark/showcase.jsonl — chain HTML is the primary artifact there).
QUESTION_TYPES = ("T1", "T2", "T3", "T4", "T5")


def load_benchmark(
    path: Path | str = BENCHMARK_PATH,
    *,
    types: list[str] | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Load benchmark rows (one JSON object per line), optionally filtered.

    ``types`` filters on the row's ``type`` (T1–T4); ``limit`` caps rows *per type*
    so a smoke run still touches every question type.
    """
    rows: list[dict] = []
    per_type: dict[str, int] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        qtype = str(row.get("type", ""))
        if types and qtype not in types:
            continue
        if limit is not None and per_type.get(qtype, 0) >= limit:
            continue
        per_type[qtype] = per_type.get(qtype, 0) + 1
        rows.append(row)
    if not rows:
        raise ValueError(f"No benchmark rows loaded from {path} (types={types})")
    return rows


def group_by_type(rows: list[dict]) -> dict[str, list[dict]]:
    """Rows keyed by question type, in T1→T4 order (unknown types last)."""
    grouped: dict[str, list[dict]] = {}
    for qtype in QUESTION_TYPES:
        group = [r for r in rows if r.get("type") == qtype]
        if group:
            grouped[qtype] = group
    rest = [r for r in rows if r.get("type") not in QUESTION_TYPES]
    if rest:
        grouped["unknown"] = rest
    return grouped


def judged_rows(
    items: list[ItemResult],
    rows: list[dict],
    traces: dict[str, Any] | None = None,
) -> list[dict]:
    """The ``mlflow.genai.evaluate`` data for the items whose agent finished.

    A failed item gives no row, so no judge scores a crash (decision A of the eval
    reliability proposal: a failed item is listed and left out of every mean). Each row
    carries ``tags['ema.bench_id']``, which mlflow writes to the trace, so a judged trace
    names its benchmark item. ``traces`` maps a bench id to the agent's own trace; with
    it, mlflow puts the judge values on that trace instead of on a new one-span trace.
    """
    by_id = {str(r.get("bench_id", "")): r for r in rows}
    traces = traces or {}
    data: list[dict] = []
    for item in items:
        if not item.ok:
            continue
        row = by_id[item.bench_id]
        entry: dict[str, Any] = {
            "inputs": {"question": row["question"]},
            "outputs": item.outputs,
            "expectations": {"gold_answer": row.get("gold_answer", "")},
            "tags": {"ema.bench_id": item.bench_id},
        }
        if traces.get(item.bench_id) is not None:
            entry["trace"] = traces[item.bench_id]
        data.append(entry)
    return data


@dataclass
class JudgeStats:
    """One judge's numbers for one question type.

    ``n`` counts the numeric values behind ``mean``. ``invalid`` is the number of
    finished items minus ``n``: it counts a text value, a null value from a refused judge
    call, and a judge call that left no value at all.
    """

    mean: float | None
    n: int
    invalid: int


def _numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def score_stats(values_by_judge: dict[str, list[Any]], finished: int) -> dict[str, JudgeStats]:
    """Mean, n and invalid count per judge, over the values of ``finished`` items.

    The old ``mean_scores`` skipped a value that ``float()`` rejected and counted
    nothing: run ``5ba51e5c`` stored ``correctness_mean`` 4.353, which is 74 / 17 over
    20 items, and nothing said that three were missing.
    """
    stats: dict[str, JudgeStats] = {}
    for name, values in values_by_judge.items():
        numbers = [x for x in (_numeric(v) for v in values) if x is not None]
        mean = sum(numbers) / len(numbers) if numbers else None
        stats[name] = JudgeStats(mean=mean, n=len(numbers), invalid=max(finished - len(numbers), 0))
    return stats


@dataclass
class TypeSummary:
    """What the runner knows about one question type after its run."""

    question_type: str
    items: list[ItemResult]
    stats: dict[str, JudgeStats] = field(default_factory=dict)
    no_trace: int = 0
    run_id: str | None = None

    @property
    def n(self) -> int:
        return len(self.items)

    @property
    def failed(self) -> list[ItemResult]:
        return [i for i in self.items if not i.ok]

    @property
    def judge_invalid(self) -> int:
        return sum(s.invalid for s in self.stats.values())


_ERROR_CHARS = 200


def format_summary(summaries: list[TypeSummary], header: list[str] | None = None) -> str:
    """The printed summary: one line per question type, then one line per failed item.

    Every mean is followed by its own n, so a reader sees how many items stand behind it.
    A type in which no item finished prints no mean.
    """
    lines = list(header or [])
    for s in summaries:
        parts = [f"{s.question_type}: n={s.n} failed={len(s.failed)} judge_invalid={s.judge_invalid}"]
        if s.no_trace:
            parts.append(f"no_trace={s.no_trace}")
        for name, st in s.stats.items():
            if st.mean is None:
                continue
            counts = f"n={st.n}" + (f" invalid={st.invalid}" if st.invalid else "")
            parts.append(f"{name}={st.mean:.3f} ({counts})")
        lines.append(" ".join(parts))
        for item in s.failed:
            first = (item.error or "").splitlines()[0] if item.error else ""
            lines.append(f"  failed {item.bench_id}: {first[:_ERROR_CHARS]}")
    return "\n".join(lines)


def _scorer_name(scorer: Any) -> str:
    return str(getattr(scorer, "name", None) or getattr(scorer, "__name__", "judge"))


def _judge_values(run_id: str, names: list[str]) -> dict[str, list[Any]]:
    """Every judge value stored on the traces linked to ``run_id``, by judge name."""
    import mlflow

    values: dict[str, list[Any]] = {name: [] for name in names}
    traces = mlflow.search_traces(run_id=run_id, return_type="list", max_results=1000)
    for trace in traces:
        for assessment in trace.info.assessments or []:
            if assessment.name in values:
                values[assessment.name].append(
                    getattr(getattr(assessment, "feedback", None), "value", None)
                )
    return values


def _record_failed_items(failed: list[ItemResult]) -> None:
    """Link each failed item's trace to the active run, tag it, and list the items.

    A failed item gets no judge call. Its trace (status ERROR) stays findable from the
    run, and ``failed_rows.json`` on the run lists the id, the error and the trace id.
    """
    import mlflow
    from mlflow.tracking import MlflowClient

    run_id = mlflow.active_run().info.run_id
    trace_ids = [i.trace_id for i in failed if i.trace_id]
    for item in failed:
        if item.trace_id:
            mlflow.set_trace_tag(item.trace_id, "ema.bench_id", item.bench_id)
    if trace_ids:
        MlflowClient().link_traces_to_run(trace_ids, run_id)
    mlflow.log_dict(
        [{"bench_id": i.bench_id, "error": i.error, "trace_id": i.trace_id} for i in failed],
        "failed_rows.json",
    )


def _log_counts(summary: TypeSummary) -> None:
    import mlflow

    metrics: dict[str, float] = {
        "n": summary.n,
        "failed": len(summary.failed),
        "judge_invalid": summary.judge_invalid,
        "no_trace": summary.no_trace,
    }
    for name, st in summary.stats.items():
        metrics[f"{name}_n"] = st.n
        if st.mean is not None:
            metrics[f"{name}_mean"] = st.mean
    mlflow.log_metrics(metrics)


# mlflow 3.14.0 limits (mlflow/utils/validation.py:60 and :64).
_TAG_KEY_MAX = 250
_TAG_VALUE_MAX = 8000


def recipe_run_tags(attributes: dict[str, Any]) -> dict[str, str]:
    """The resolved recipe's ``ema.*`` attributes as run tags (strings, within mlflow's limits).

    Before this, 90 of the 100 stored evaluation traces carried no recipe at all, and
    no run carried more than the recipe's name.
    """
    return {
        str(k)[:_TAG_KEY_MAX]: str(v)[:_TAG_VALUE_MAX]
        for k, v in attributes.items()
        if str(k).startswith("ema.")
    }


# Declared recipe layers that only app.py runs (app.py:702-715 and 740-751).
_APP_ONLY_LAYERS = (
    ("ema.fewshot.enabled", "the few-shot layer (fewshot.enabled)"),
    ("ema.judge.enabled", "the inline judge (judge.enabled)"),
)


def layers_not_run(attributes: dict[str, Any]) -> list[str]:
    """One line per layer the recipe declares and this runner does not run.

    Under the runner, ``regulatory_fewshot`` and ``agentic_judged`` behave exactly
    like ``regulatory_agent``, while their traces say ``ema.fewshot.enabled=True``.
    """
    return [
        f"NOTE: the recipe declares {label}; it runs in app.py only, not in this runner"
        for key, label in _APP_ONLY_LAYERS
        if attributes.get(key) is True
    ]


def evaluate_items(
    runnable: Any,
    rows: list[dict],
    scorers: list,
    *,
    run_tags: dict[str, str],
    trace_id_fn: Any = None,
) -> list[TypeSummary]:
    """Predict every row, then judge the finished items, one MLflow run per question type.

    The offline part of :func:`run_recipe_benchmark`: it takes any object with
    ``ainvoke`` and needs no Neo4j and no credentials. Tracking must be set up by the
    caller; this function does not call ``setup_tracing``.

    Why the runner predicts itself: with ``predict_fn``, ``mlflow.genai.evaluate``
    3.14.0 runs every scorer on a row whose prediction raised (``_run_predict`` leaves
    ``outputs=None``, ``_run_score`` scores it anyway). Six crashed rows were judged in
    the stored runs; one holds correctness 5 beside faithfulness 1.

    Each run gets its tags when it opens, so a run that dies still says what it was:
    7 of 17 stored runs had no tag, because tags were set after ``evaluate`` returned.
    """
    import mlflow

    from harness.eval.evaluate import run_evaluation
    from harness.eval.predict import predict_items

    items = predict_items(runnable, rows, trace_id_fn=trace_id_fn)
    # Traces are exported asynchronously; flush before reading them back.
    mlflow.flush_trace_async_logging()
    traces: dict[str, Any] = {}
    for item in items:
        if item.ok and item.trace_id:
            trace = mlflow.get_trace(item.trace_id, silent=True)
            if trace is not None:
                traces[item.bench_id] = trace
    by_id = {i.bench_id: i for i in items}
    names = [_scorer_name(s) for s in scorers]
    # The resolved recipe, as the adapter holds it (absent on a bare stand-in).
    base_tags = {**recipe_run_tags(getattr(runnable, "config_attributes", None) or {}), **run_tags}

    summaries: list[TypeSummary] = []
    for qtype, group in group_by_type(rows).items():
        type_items = [by_id[str(r.get("bench_id", ""))] for r in group]
        with mlflow.start_run(tags={**base_tags, "ema.question_type": qtype}) as run:
            failed = [i for i in type_items if not i.ok]
            if failed:
                _record_failed_items(failed)
            data = judged_rows(type_items, group, traces)
            # evaluate() reads df.iloc[0]: a type in which every item failed is not passed.
            if data:
                log.info("judging type=%s: %d of %d items finished", qtype, len(data), len(type_items))
                run_evaluation(data, scorers=scorers, configure=False)
                mlflow.flush_trace_async_logging()
            values = _judge_values(run.info.run_id, names) if data else {n: [] for n in names}
            summary = TypeSummary(
                question_type=qtype,
                items=type_items,
                stats=score_stats(values, finished=len(data)),
                no_trace=sum(1 for i in type_items if i.ok and i.bench_id not in traces),
                run_id=run.info.run_id,
            )
            _log_counts(summary)
        summaries.append(summary)
    return summaries


@dataclass(frozen=True)
class ModelChoice:
    """The generator and the judge of one evaluation, as model ids.

    Ids, not models.yaml keys: a key such as ``claude_opus`` can be rebound to another
    model, and a number must say which model produced it. Until 2026-11-23 every stored
    number was judged by the model that generated it, and no run said so.
    """

    generator_model: str
    judge_model: str
    judge_route: Any

    def run_tags(self) -> dict[str, str]:
        return {"ema.generator_model": self.generator_model, "ema.judge_model": self.judge_model}

    def header(self) -> list[str]:
        lines = [f"generator={self.generator_model} judge={self.judge_model}"]
        if self.generator_model == self.judge_model:
            lines.append(
                f"WARNING: the generator and the judge are one model ({self.judge_model}); "
                "use --judge to pick another"
            )
        return lines


def resolve_models(
    recipe_model: str,
    *,
    model: str | None = None,
    judge: str | None = None,
    judge_role: str = "judge",
) -> ModelChoice:
    """Resolve the generator and the judge from the recipe and the options (pure).

    ``model`` overrides the recipe's model key, ``judge`` overrides ``roles.<judge_role>``;
    both are keys of the ``models:`` section of ``harness/configs/models.yaml``.
    """
    from harness.eval.judges import resolve_judge_route
    from harness.models import load_model_config

    generator = load_model_config(model or recipe_model)
    route = resolve_judge_route(judge_role, model_key=judge)
    return ModelChoice(generator.model_id, route.model_id, route)


@dataclass
class EvalReport:
    """What :func:`run_recipe_benchmark` returns: the header lines and one summary per type."""

    summaries: list[TypeSummary]
    header: list[str] = field(default_factory=list)

    def text(self) -> str:
        return format_summary(self.summaries, self.header)


def run_recipe_benchmark(
    recipe_name: str,
    *,
    benchmark_path: Path | str = BENCHMARK_PATH,
    types: list[str] | None = None,
    limit: int | None = None,
    experiment: str | None = None,
    judge_role: str = "judge",
    judge: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    retrieval_k: int | None = None,
) -> EvalReport:
    """Evaluate ``recipe_name`` over the benchmark; one MLflow run per question type.

    ``model``/``temperature``/``retrieval_k`` are the same live overrides
    ``build_recipe`` accepts. ``judge`` is a models.yaml key that overrides
    ``roles.<judge_role>`` for this run. Returns an :class:`EvalReport`; its ``text()``
    is the printed summary. Runtime: needs Neo4j (the recipe's index profile) + model
    credentials.

    It calls ``setup_tracing`` (with LlamaIndex autolog), so each item's trace carries
    the agent's spans and the recipe, as in the app.
    """
    from harness.eval.judges import ema_judges
    from harness.indexing import load_index_profile, open_index
    from harness.obs import default_experiment, setup_tracing
    from harness.recipes import build_recipe, get_recipe

    rows = load_benchmark(benchmark_path, types=types, limit=limit)
    recipe = get_recipe(recipe_name)
    models = resolve_models(recipe.model, model=model, judge=judge, judge_role=judge_role)
    setup_tracing(experiment or default_experiment())
    index = open_index(load_index_profile(recipe.index_profile))
    runner = build_recipe(
        recipe, index, model=model, temperature=temperature, retrieval_k=retrieval_k
    )
    scorers = ema_judges(route=models.judge_route)
    run_tags = {
        "ema.recipe": recipe_name,
        "ema.benchmark": Path(benchmark_path).name,
        **models.run_tags(),
    }
    summaries = evaluate_items(runner, rows, scorers, run_tags=run_tags)
    header = models.header() + layers_not_run(runner.config_attributes)
    return EvalReport(summaries=summaries, header=header)

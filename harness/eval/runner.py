"""Recipe × benchmark eval runner — the R6 experiment vehicle.

"Run recipe X on benchmark Y" as one call: build the recipe (the same
``build_recipe`` path the live app uses), wrap it as an ``mlflow.genai``
``predict_fn`` (which carries ``context_passages`` for the faithfulness judge,
F3/F5), and evaluate against ``benchmark/benchmark.jsonl`` with the project's
judges. **MLflow is the system of record** (R6-Q1): one MLflow run *per question
type* (T1–T4), each tagged ``ema.recipe`` / ``ema.benchmark`` /
``ema.question_type`` — metrics are always reported broken down by type, never
aggregate-only (the CLAUDE.md eval rule).

``load_benchmark`` / ``to_eval_data`` / ``group_by_type`` are pure and
offline-tested; ``run_recipe_benchmark`` is the runtime driver (needs Neo4j +
model credentials). CLI: ``scripts/run_eval.py``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

BENCHMARK_PATH = Path(__file__).parents[2] / "benchmark" / "benchmark.jsonl"
QUESTION_TYPES = ("T1", "T2", "T3", "T4")


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


def to_eval_data(rows: list[dict]) -> list[dict]:
    """Benchmark rows → the ``mlflow.genai.evaluate`` data format.

    ``inputs.question`` feeds the predict_fn; ``expectations.gold_answer`` feeds the
    correctness judge (the ``{{gold_answer}}`` → ``expectations`` var mapping).
    """
    return [
        {
            "inputs": {"question": row["question"]},
            "expectations": {"gold_answer": row.get("gold_answer", "")},
        }
        for row in rows
    ]


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


def _tag_eval_run(result: Any, tags: dict[str, str]) -> None:
    """Best-effort: stamp the evaluate run with recipe/benchmark tags for filtering."""
    run_id = getattr(result, "run_id", None)
    if not run_id:
        return
    try:
        from mlflow.tracking import MlflowClient

        client = MlflowClient()
        for key, value in tags.items():
            client.set_tag(run_id, key, value)
    except Exception as exc:  # tagging must never fail the eval itself
        log.warning("could not tag eval run %s: %s", run_id, exc)


def run_recipe_benchmark(
    recipe_name: str,
    *,
    benchmark_path: Path | str = BENCHMARK_PATH,
    types: list[str] | None = None,
    limit: int | None = None,
    experiment: str | None = None,
    judge_role: str = "judge",
    model: str | None = None,
    temperature: float | None = None,
    retrieval_k: int | None = None,
) -> dict[str, Any]:
    """Evaluate ``recipe_name`` over the benchmark; one MLflow run per question type.

    ``model``/``temperature``/``retrieval_k`` are the same live overrides
    ``build_recipe`` accepts. Returns ``{question_type: mlflow EvaluationResult}``.
    Runtime: needs Neo4j (the recipe's index profile) + model credentials.
    """
    from harness.eval.evaluate import run_evaluation
    from harness.eval.judges import ema_judges, judge_model_uri
    from harness.eval.predict import build_predict_fn
    from harness.indexing import load_index_profile, open_index
    from harness.recipes import build_recipe, get_recipe

    rows = load_benchmark(benchmark_path, types=types, limit=limit)
    recipe = get_recipe(recipe_name)
    index = open_index(load_index_profile(recipe.index_profile))
    runner = build_recipe(
        recipe, index, model=model, temperature=temperature, retrieval_k=retrieval_k
    )
    predict_fn = build_predict_fn(runner)
    scorers = ema_judges(model=judge_model_uri(judge_role))

    benchmark_name = Path(benchmark_path).name
    results: dict[str, Any] = {}
    for qtype, group in group_by_type(rows).items():
        log.info("evaluating recipe=%s type=%s (%d questions)", recipe_name, qtype, len(group))
        result = run_evaluation(
            to_eval_data(group), predict_fn=predict_fn, scorers=scorers, experiment=experiment
        )
        _tag_eval_run(
            result,
            {
                "ema.recipe": recipe_name,
                "ema.benchmark": benchmark_name,
                "ema.question_type": qtype,
            },
        )
        results[qtype] = result
    return results


def summarize(results: dict[str, Any]) -> str:
    """Per-type metric table (plain text) from ``run_recipe_benchmark`` results."""
    lines = []
    for qtype, result in results.items():
        metrics = getattr(result, "metrics", None) or {}
        rendered = ", ".join(f"{k}={v:.3f}" for k, v in sorted(metrics.items())) or "(no metrics)"
        lines.append(f"{qtype}: {rendered}")
    return "\n".join(lines)

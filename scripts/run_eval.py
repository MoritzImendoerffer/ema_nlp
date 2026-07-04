"""Run a recipe against the benchmark and log per-type results to MLflow (R6).

Usage:
    python scripts/run_eval.py --recipe naive_rag
    python scripts/run_eval.py --recipe crag_agentic --types T3 T4 --limit 2
    EMA_MLFLOW_EXPERIMENT=ema_eval python scripts/run_eval.py --recipe naive_rag

One MLflow run per question type (T1–T4), tagged ema.recipe / ema.benchmark /
ema.question_type, in the same experiment as the live app's feedback (F15) unless
overridden. Runtime: needs Neo4j (the recipe's index profile) + model credentials.
"""

import argparse
import logging


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Evaluate a recipe over the benchmark (MLflow)")
    parser.add_argument("--recipe", required=True, help="recipe name (harness/configs/recipes)")
    parser.add_argument("--benchmark", default=None, help="benchmark JSONL path (default: repo benchmark)")
    parser.add_argument("--types", nargs="*", default=None, help="question types to run (default: all)")
    parser.add_argument("--limit", type=int, default=None, help="max questions per type (smoke runs)")
    parser.add_argument("--experiment", default=None, help="MLflow experiment (default: EMA_MLFLOW_EXPERIMENT)")
    parser.add_argument("--model", default=None, help="model override (models.yaml key)")
    args = parser.parse_args()

    import config  # noqa: F401  (loads ~/.myenvs/ema_nlp.env)
    from harness.eval.runner import BENCHMARK_PATH, run_recipe_benchmark, summarize

    results = run_recipe_benchmark(
        args.recipe,
        benchmark_path=args.benchmark or BENCHMARK_PATH,
        types=args.types,
        limit=args.limit,
        experiment=args.experiment,
        model=args.model,
    )
    print(f"\n=== {args.recipe} — per-type results ===")
    print(summarize(results))


if __name__ == "__main__":
    main()

"""
Upload the EMA benchmark to LangSmith as a named dataset (LSMT-005).

Each benchmark item is stored as a LangSmith Example with:
    inputs:  {question, type, gold_qa_ids, topic_path}
    outputs: {gold_answer}

The dataset is identified by *dataset_name* and can be referenced by
run_langsmith_eval.py via --dataset.  Running this script twice is safe —
existing examples are updated, new ones are added (idempotent by bench_id).

Usage::

    python3 -m harness.langsmith_dataset              # default name "ema-benchmark"
    python3 -m harness.langsmith_dataset --dataset my-ema-v2
    python3 -m harness.langsmith_dataset --benchmark benchmark/benchmark.jsonl

Requires LANGSMITH_API_KEY in ~/.myenvs/ema_nlp.env.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from langsmith import Client

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_BENCHMARK = REPO_ROOT / "benchmark" / "benchmark.jsonl"
DEFAULT_DATASET_NAME = "ema-benchmark"


def upload_benchmark_dataset(
    path: Path = DEFAULT_BENCHMARK,
    dataset_name: str = DEFAULT_DATASET_NAME,
    *,
    update_existing: bool = True,
) -> str:
    """
    Create or update a LangSmith dataset from benchmark.jsonl.

    Args:
        path:            Path to benchmark JSONL file.
        dataset_name:    Name of the LangSmith dataset to create/update.
        update_existing: If True, update existing examples rather than skipping.

    Returns:
        The LangSmith dataset ID (UUID string).

    Raises:
        FileNotFoundError: If *path* does not exist.
        OSError:           If LANGSMITH_API_KEY is not set.
    """
    if not path.exists():
        raise FileNotFoundError(f"Benchmark not found: {path}")

    import os
    api_key = os.getenv("LANGSMITH_API_KEY")
    if not api_key:
        raise OSError(
            "LANGSMITH_API_KEY not set. "
            "Add it to ~/.myenvs/ema_nlp.env (see docs/SETUP.md)."
        )

    client = Client(api_key=api_key)

    # Load benchmark items
    items: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            items.append(json.loads(line))

    log.info("Loaded %d benchmark items from %s", len(items), path)

    # Get or create dataset
    dataset_id: str | None = None
    for ds in client.list_datasets():
        if ds.name == dataset_name:
            dataset_id = str(ds.id)
            log.info("Found existing dataset %r (id=%s)", dataset_name, dataset_id)
            break

    if dataset_id is None:
        ds = client.create_dataset(
            dataset_name=dataset_name,
            description=(
                "EMA Q&A benchmark — 30-50 stratified questions (T1-T4) "
                "for evaluating RAG pipelines on European Medicines Agency regulatory content."
            ),
        )
        dataset_id = str(ds.id)
        log.info("Created new dataset %r (id=%s)", dataset_name, dataset_id)

    # Map existing examples by bench_id (stored in metadata)
    existing: dict[str, str] = {}  # bench_id → example_id
    if update_existing:
        for ex in client.list_examples(dataset_id=dataset_id):
            bid = (ex.metadata or {}).get("bench_id") or ex.inputs.get("bench_id")
            if bid:
                existing[bid] = str(ex.id)

    # Upsert examples
    created = updated = 0
    for item in items:
        bench_id: str = item["bench_id"]
        inputs = {
            "question": item["question"],
            "type": item["type"],
            "gold_qa_ids": item.get("gold_qa_ids", []),
            "topic_path": item.get("topic_path", ""),
        }
        outputs = {"gold_answer": item["gold_answer"]}
        metadata = {"bench_id": bench_id, "question_type": item["type"]}

        if bench_id in existing and update_existing:
            client.update_example(
                example_id=existing[bench_id],
                inputs=inputs,
                outputs=outputs,
                metadata=metadata,
            )
            updated += 1
        elif bench_id not in existing:
            client.create_example(
                inputs=inputs,
                outputs=outputs,
                metadata=metadata,
                dataset_id=dataset_id,
            )
            created += 1

    log.info(
        "Dataset %r: %d created, %d updated, %d unchanged",
        dataset_name, created, updated, len(items) - created - updated,
    )
    return dataset_id


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _main() -> None:
    parser = argparse.ArgumentParser(description="Upload EMA benchmark to LangSmith")
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--dataset", default=DEFAULT_DATASET_NAME)
    parser.add_argument("--no-update", action="store_true", help="Skip existing examples")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        dataset_id = upload_benchmark_dataset(
            path=args.benchmark,
            dataset_name=args.dataset,
            update_existing=not args.no_update,
        )
        print(f"Dataset '{args.dataset}' ready — id={dataset_id}")
    except (FileNotFoundError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _main()

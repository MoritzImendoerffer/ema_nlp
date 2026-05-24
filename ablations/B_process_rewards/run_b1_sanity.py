"""
B1 sanity check: run the react workflow on 5 benchmark questions and save trajectories.

Selects 1 T1, 1 T2, 2 T3, 1 T4 from benchmark.jsonl and runs the native ReAct workflow.
Writes trajectories to ablations/B_process_rewards/b1_trajectories.jsonl.

Usage::

    source ~/.myenvs/ema_nlp.env
    python3 ablations/B_process_rewards/run_b1_sanity.py

Options:
    --benchmark PATH    path to benchmark JSONL (default: benchmark/benchmark.jsonl)
    --corpus PATH       path to corpus JSONL (default: ~/Nextcloud/…)
    --index-dir PATH    path to FAISS index dir
    --dry-run           print selected questions, do not call the LLM
    --output PATH       output JSONL (default: ablations/B_process_rewards/b1_trajectories.jsonl)
    --rate              prompt for 1-5 rating after each answer (for B3 labeling)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent
DEFAULT_BENCHMARK = REPO_ROOT / "benchmark" / "benchmark.jsonl"
DEFAULT_OUTPUT = Path(__file__).parent / "b1_trajectories.jsonl"

# One question per type for B1 sanity check — represents each difficulty tier.
SANITY_QUESTION_IDS = {
    "T1": "T1-001",   # single-source lookup (worksharing 2-month notice)
    "T2": "T2-001",   # scoping (Art30 default contact person vs PRAC)
    "T3a": "T3-001",  # multi-hop chain 1
    "T3b": "T3-006",  # multi-hop chain 2 (different topic area)
    "T4": "T4-001",   # synthesis (cross-document)
}


def _load_benchmark(path: Path) -> dict[str, dict]:
    items: dict[str, dict] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            item = json.loads(line)
            items[item["bench_id"]] = item
    return items


def _select_questions(items: dict[str, dict]) -> list[dict]:
    selected = []
    for label, bench_id in SANITY_QUESTION_IDS.items():
        if bench_id in items:
            item = items[bench_id].copy()
            item["_sanity_label"] = label
            selected.append(item)
        else:
            log.warning("bench_id %s not found in benchmark, skipping", bench_id)
    return selected


async def _run_questions(
    workflow: Any,
    questions: list[dict],
    output_path: Path,
    *,
    rate_interactively: bool = False,
) -> list[dict]:
    records: list[dict] = []
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as out:
        for q in questions:
            log.info("Running B1 on %s: %s", q["bench_id"], q["question"][:80])
            ts_start = datetime.now(UTC).isoformat()
            try:
                result = await workflow.ainvoke({"question": q["question"]})
                answer_text: str = result.get("answer_text", "")
                cited_qa_ids: list = result.get("cited_qa_ids", [])
                trajectory: list = result.get("trajectory", [])

                record: dict[str, Any] = {
                    "bench_id": q["bench_id"],
                    "type": q["type"],
                    "sanity_label": q["_sanity_label"],
                    "question": q["question"],
                    "gold_qa_ids": q["gold_qa_ids"],
                    "gold_sources": q.get("gold_sources", []),
                    "agent_answer": answer_text,
                    "cited_qa_ids": cited_qa_ids,
                    "trajectory": trajectory,
                    "timestamp_start": ts_start,
                    "timestamp_end": datetime.now(UTC).isoformat(),
                }

                if rate_interactively:
                    import uuid
                    from harness.rating import prompt_for_rating
                    run_id = str(uuid.uuid4())
                    print(f"\n[{q['bench_id']}] Answer: {answer_text[:200]}")
                    rating = prompt_for_rating(
                        run_id=run_id,
                        question=q["question"],
                        answer_text=answer_text,
                        trajectory=trajectory,
                        non_interactive=False,
                    )
                    record["rating"] = rating
                    record["run_id"] = run_id

            except Exception as exc:
                log.error("Error on %s: %s", q["bench_id"], exc)
                record = {
                    "bench_id": q["bench_id"],
                    "type": q["type"],
                    "sanity_label": q["_sanity_label"],
                    "question": q["question"],
                    "gold_qa_ids": q["gold_qa_ids"],
                    "error": str(exc),
                    "timestamp_start": ts_start,
                    "timestamp_end": datetime.now(UTC).isoformat(),
                }

            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            records.append(record)
            log.info(
                "  → cited: %s | trajectory steps: %d",
                record.get("cited_qa_ids", []),
                len(record.get("trajectory", [])),
            )

    return records


def run_b1_sanity(
    benchmark_path: Path = DEFAULT_BENCHMARK,
    corpus_path: Path | None = None,
    index_dir: Path | None = None,
    output_path: Path = DEFAULT_OUTPUT,
    dry_run: bool = False,
    rate_interactively: bool = False,
) -> list[dict]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from config import CORPUS_PATH, INDEX_DIR
    from harness.embed import build_index
    from harness.llms import get_llm
    from harness.providers import configure_embed_model
    from harness.workflows.registry import get_workflow

    configure_embed_model()

    corpus = corpus_path or CORPUS_PATH
    index_d = index_dir or INDEX_DIR

    items = _load_benchmark(benchmark_path)
    questions = _select_questions(items)

    log.info("Selected %d questions for B1 sanity check:", len(questions))
    for q in questions:
        log.info("  [%s] %s: %s", q["_sanity_label"], q["bench_id"], q["question"][:80])

    if dry_run:
        print("Dry-run: would run B1 on:")
        for q in questions:
            print(f"  [{q['_sanity_label']}] {q['bench_id']}: {q['question']}")
        return []

    index = build_index(corpus_path=Path(corpus), index_dir=Path(index_d))
    llm = get_llm("agent")
    workflow = get_workflow("react", index=index, llm=llm)

    records = asyncio.run(
        _run_questions(workflow, questions, output_path, rate_interactively=rate_interactively)
    )
    log.info("B1 trajectories written to %s", output_path)
    return records


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--corpus", type=Path, default=None)
    parser.add_argument("--index-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--rate",
        action="store_true",
        help="Prompt for 1-5 rating + step labels after each run (for B3 labeling)",
    )
    args = parser.parse_args()

    result = run_b1_sanity(
        benchmark_path=args.benchmark,
        corpus_path=args.corpus,
        index_dir=args.index_dir,
        output_path=args.output,
        dry_run=args.dry_run,
        rate_interactively=args.rate,
    )
    sys.exit(0 if result is not None else 1)

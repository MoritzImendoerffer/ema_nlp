"""
Interactive labeling session for HITL pipeline.

Runs a workflow on N stratified or uniform benchmark questions, prompts the
user for 1–5 ratings via harness/rating.py, and writes a per-question
checkpoint JSONL to ~/Nextcloud/Datasets/ema_nlp/label_sessions/{session_id}.jsonl
after each question so the session can be resumed after a crash or interrupt.

Usage::

    python -m harness.label_session \\
        --workflow react \\
        --config harness/configs/workflow_react.yaml \\
        --n 20 \\
        --sample stratified

    # Resume a previous session by ID
    python -m harness.label_session \\
        --workflow react \\
        --config harness/configs/workflow_react.yaml \\
        --session-id session_20260524_120000
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import random
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent
CHECKPOINT_DIR = Path.home() / "Nextcloud" / "Datasets" / "ema_nlp" / "label_sessions"
DEFAULT_BENCHMARK = REPO_ROOT / "benchmark" / "benchmark.jsonl"


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

def _load_benchmark(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _stratified_sample(questions: list[dict], n: int) -> list[dict]:
    """ceil(n/4) per type T1–T4, with replacement if a type has fewer items."""
    by_type: dict[str, list[dict]] = {}
    for q in questions:
        t = q.get("type", "")
        by_type.setdefault(t, []).append(q)

    per_type = math.ceil(n / 4)
    result: list[dict] = []
    for t in ("T1", "T2", "T3", "T4"):
        items = by_type.get(t, [])
        if not items:
            log.warning("No benchmark questions found for type %s", t)
            continue
        if len(items) < per_type:
            result.extend(random.choices(items, k=per_type))
        else:
            result.extend(random.sample(items, per_type))
    return result


def _uniform_sample(questions: list[dict], n: int) -> list[dict]:
    return random.sample(questions, min(n, len(questions)))


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------

def _load_checkpoint(path: Path) -> dict[str, dict]:
    """Return dict keyed by bench_id for rows already in the checkpoint file."""
    if not path.exists():
        return {}
    rated: dict[str, dict] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                rated[row["bench_id"]] = row
    return rated


def _append_checkpoint(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def run_session(args: argparse.Namespace) -> None:
    from harness.embed import build_index
    from harness.llms import get_llm
    from harness.providers import configure_embed_model
    from harness.rating import prompt_for_rating
    from harness.retrieve import RetrievalConfig
    from harness.run_eval import load_config, _resolve
    from harness.workflows.registry import get_workflow

    cfg = load_config(Path(args.config))
    idx_cfg = cfg["index"]
    configure_embed_model(idx_cfg.get("embed_model"))

    corpus_path = _resolve(idx_cfg["corpus"])
    index_dir = _resolve(idx_cfg["index_dir"])

    log.info("Loading index from %s …", index_dir)
    index = build_index(corpus_path, index_dir, force=False)

    ret_section = cfg.get("retrieval", {})
    ret_config = RetrievalConfig.from_yaml_section(ret_section) if ret_section else None

    llm = get_llm("agent")
    workflow = get_workflow(args.workflow, index=index, llm=llm, retrieval_config=ret_config)

    benchmark_path = Path(args.benchmark) if args.benchmark else (
        _resolve(cfg["benchmark"]["path"]) if cfg.get("benchmark") else DEFAULT_BENCHMARK
    )
    questions = _load_benchmark(benchmark_path)

    if args.sample == "stratified":
        sampled = _stratified_sample(questions, args.n)
    else:
        sampled = _uniform_sample(questions, args.n)

    session_id = args.session_id or f"session_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    checkpoint_path = CHECKPOINT_DIR / f"{session_id}.jsonl"
    already_rated = _load_checkpoint(checkpoint_path)

    pending = [q for q in sampled if q["bench_id"] not in already_rated]

    print(f"\nSession: {session_id}")
    print(f"Workflow: {args.workflow}  |  Sample: {args.sample}  |  N={args.n}")
    print(f"Questions: {len(sampled)} total, {len(already_rated)} already rated, {len(pending)} pending")
    print(f"Checkpoint: {checkpoint_path}\n")

    if not pending:
        print("All questions already rated — nothing to do.")
        _print_summary(session_id, already_rated)
        return

    new_rows: list[dict] = []
    for i, q in enumerate(pending, 1):
        print(f"\n{'='*70}")
        print(f"[{i}/{len(pending)}] {q['bench_id']} ({q['type']})")
        print(f"{'='*70}")
        print(f"Q: {q['question']}\n")

        run_id = str(uuid.uuid4())
        try:
            result: dict[str, Any] = workflow.invoke({"question": q["question"]})
        except Exception as exc:
            log.error("Workflow failed for %s: %s", q["bench_id"], exc)
            continue

        answer_text: str = result.get("answer_text", "")
        cited_qa_ids: list[str] = result.get("cited_qa_ids", [])
        trajectory: list[dict] = result.get("trajectory", [])

        print(f"A: {answer_text}")
        if cited_qa_ids:
            print(f"\nCited QA IDs: {', '.join(cited_qa_ids)}")

        rating = prompt_for_rating(
            run_id=run_id,
            question=q["question"],
            answer_text=answer_text,
            trajectory=trajectory,
        )

        row = {
            "bench_id": q["bench_id"],
            "type": q["type"],
            "question": q["question"],
            "answer_text": answer_text,
            "cited_qa_ids": cited_qa_ids,
            "rating": rating,
            "run_id": run_id,
            "workflow": args.workflow,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        _append_checkpoint(checkpoint_path, row)
        new_rows.append(row)

    all_rows = {**already_rated, **{r["bench_id"]: r for r in new_rows}}
    _print_summary(session_id, all_rows)


def _print_summary(session_id: str, rows: dict[str, dict]) -> None:
    all_list = list(rows.values())
    rated = [r for r in all_list if r.get("rating") is not None]
    skipped = [r for r in all_list if r.get("rating") is None]
    avg = sum(r["rating"] for r in rated) / len(rated) if rated else 0.0

    print(f"\n{'='*70}")
    print(f"Session summary: {session_id}")
    print(f"  Total: {len(all_list)} | Rated: {len(rated)} | Skipped: {len(skipped)}")
    if rated:
        print(f"  Average rating: {avg:.2f}/5")
    by_type: dict[str, list[dict]] = {}
    for r in all_list:
        by_type.setdefault(r.get("type", "?"), []).append(r)
    for t in sorted(by_type):
        items = by_type[t]
        r_items = [i for i in items if i.get("rating") is not None]
        avg_t = sum(i["rating"] for i in r_items) / len(r_items) if r_items else 0.0
        avg_str = f", avg={avg_t:.1f}" if r_items else ""
        print(f"  {t}: {len(r_items)}/{len(items)} rated{avg_str}")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Interactive HITL labeling session — run a workflow and rate answers."
    )
    parser.add_argument("--workflow", required=True, help="Workflow key from WORKFLOW_REGISTRY")
    parser.add_argument("--config", required=True, help="Path to workflow YAML config")
    parser.add_argument("--n", type=int, default=20, help="Number of questions to label (default 20)")
    parser.add_argument(
        "--sample",
        choices=["stratified", "uniform"],
        default="stratified",
        help="Sampling strategy: stratified (ceil(n/4) per type) or uniform (random N)",
    )
    parser.add_argument("--session-id", help="Resume an existing session by ID")
    parser.add_argument("--benchmark", help="Path to benchmark JSONL (overrides config)")
    args = parser.parse_args()

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    run_session(args)


if __name__ == "__main__":
    main()

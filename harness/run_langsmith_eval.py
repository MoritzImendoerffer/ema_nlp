"""
Run an EMA RAG chain as a LangSmith experiment over the benchmark dataset.

Each run:
1. Loads the named LangSmith dataset (default "ema-benchmark").
2. Invokes the selected chain/agent for every benchmark example.
3. Evaluates with faithfulness + correctness judges (wrapping harness/judge.py).
4. Reports the LangSmith experiment URL for side-by-side comparison.
5. Also writes results/<run_id>/ (judge_scores.jsonl + run_summary.md)
   in the same format as run_eval.py for backward compatibility.

Usage::

    python3 -m harness.run_langsmith_eval \\
        --chain simple_rag_zero \\
        --tier mid \\
        --dataset ema-benchmark

    python3 -m harness.run_langsmith_eval \\
        --chain crag \\
        --tier frontier \\
        --run-id ablation_c_frontier_crag_v1

Available chains: simple_rag_zero, simple_rag_few, simple_rag_cot, react, crag

Requires: ANTHROPIC_API_KEY, LANGSMITH_API_KEY in ~/.myenvs/ema_nlp.env
          LANGCHAIN_TRACING_V2=true, LANGCHAIN_PROJECT=ema-nlp
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent


def run_experiment(
    chain_name: str,
    *,
    tier_id: str = "mid",
    dataset_name: str = "ema-benchmark",
    run_id: str | None = None,
    index_dir: Path | None = None,
    corpus_path: Path | None = None,
    results_base: Path = REPO_ROOT / "results",
    retrieval_mode: str = "hybrid",
    retrieval_strategy: str = "flat",
    k: int = 10,
) -> dict:
    """
    Run a LangSmith experiment and return summary dict.

    Args:
        chain_name:      Name from CHAIN_REGISTRY (e.g. "simple_rag_zero", "crag").
        tier_id:         Model tier: "mid" | "frontier" | "olmo".
        dataset_name:    LangSmith dataset to evaluate against.
        run_id:          Unique identifier for this run (defaults to auto-generated).
        index_dir:       Path to persisted FAISS index directory.
        corpus_path:     Path to corpus JSONL (for index rebuild if needed).
        results_base:    Base directory for writing results files.
        retrieval_mode:  "dense" | "bm25" | "hybrid".
        k:               Number of documents to retrieve per query.

    Returns:
        Dict with keys: run_id, experiment_url, n_examples, avg_faithfulness, avg_correctness.
    """
    import os
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    effective_run_id = run_id or f"langsmith_{chain_name}_{tier_id}_{timestamp}"

    # --- Build/load index ---
    from harness.embed import build_index
    from harness.providers import configure_embed_model
    from config import CORPUS_PATH as _default_corpus, INDEX_DIR as _default_index

    _corpus = corpus_path or _default_corpus
    _index = index_dir or _default_index
    configure_embed_model()
    index = build_index(Path(_corpus), Path(_index))

    # --- Build retriever and LLM ---
    from harness.retrieve import RetrievalConfig
    from harness.chains.retriever import make_retriever
    from harness.chains.llms import get_langchain_llm
    from harness.chains.registry import get_chain

    ret_cfg = RetrievalConfig(
        strategy=retrieval_strategy,  # type: ignore[arg-type]
        mode=retrieval_mode,  # type: ignore[arg-type]
        k=k,
    )
    retriever = make_retriever(ret_cfg, index)
    llm = get_langchain_llm(tier_id)  # type: ignore[arg-type]
    chain = get_chain(chain_name, tier_id=tier_id, retriever=retriever, llm=llm)

    # --- LangSmith experiment ---
    api_key = os.getenv("LANGSMITH_API_KEY")
    if not api_key:
        raise OSError("LANGSMITH_API_KEY not set. Add it to ~/.myenvs/ema_nlp.env")

    from langsmith import evaluate
    from harness.chains.evaluators import correctness_evaluator, faithfulness_evaluator

    def _predict(inputs: dict) -> dict:
        try:
            return chain.invoke({"question": inputs["question"]})
        except Exception as exc:
            log.warning("Chain failed for question=%r: %s", inputs.get("question", ""), exc)
            return {"answer_text": "No answer generated.", "docs": [], "prompt_strategy": chain_name}

    log.info("Starting LangSmith experiment: chain=%s tier=%s dataset=%s", chain_name, tier_id, dataset_name)

    experiment_results = evaluate(
        _predict,
        data=dataset_name,
        evaluators=[faithfulness_evaluator, correctness_evaluator],
        experiment_prefix=effective_run_id,
        metadata={"chain": chain_name, "tier": tier_id, "retrieval_mode": retrieval_mode, "k": k},
    )

    experiment_url: str = getattr(experiment_results, "url", "") or ""
    if experiment_url:
        log.info("LangSmith experiment: %s", experiment_url)
        print(f"\nLangSmith experiment URL:\n  {experiment_url}\n")

    # --- Write compatible results to disk ---
    judge_scores = _extract_judge_scores(experiment_results)
    out_dir = results_base / effective_run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_judge_scores(out_dir, judge_scores)
    _write_summary(out_dir, effective_run_id, chain_name, tier_id, judge_scores, timestamp)

    log.info("Results written to %s", out_dir)

    n = len(judge_scores)
    faith_avg = sum(s.get("faithfulness", {}).get("score", 0) for s in judge_scores) / n if n else 0.0
    corr_avg = sum(s.get("correctness", {}).get("score", 0) for s in judge_scores) / n if n else 0.0

    return {
        "run_id": effective_run_id,
        "experiment_url": experiment_url,
        "n_examples": n,
        "avg_faithfulness": faith_avg,
        "avg_correctness": corr_avg,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_judge_scores(experiment_results: Any) -> list[dict]:
    """Convert LangSmith ExperimentResults to judge_scores.jsonl format."""
    rows: list[dict] = []
    try:
        for result in experiment_results:
            inputs = result.get("inputs", {}) if isinstance(result, dict) else {}
            outputs = result.get("outputs", {}) if isinstance(result, dict) else {}
            eval_results = result.get("evaluation_results", {}) if isinstance(result, dict) else {}

            faith_score = _get_eval_score(eval_results, "faithfulness")
            corr_score = _get_eval_score(eval_results, "correctness")

            rows.append({
                "bench_id": inputs.get("bench_id", "?"),
                "type": inputs.get("type", "?"),
                "faithfulness": {"score": round(faith_score * 5), "reason": ""},
                "correctness": {"score": round(corr_score * 5), "reason": ""},
            })
    except Exception as exc:
        log.warning("Could not extract judge scores from experiment results: %s", exc)
    return rows


def _get_eval_score(eval_results: Any, key: str) -> float:
    """Extract a named evaluator score from LangSmith evaluation result."""
    if isinstance(eval_results, dict):
        for k, v in eval_results.items():
            if key in k.lower():
                return float(getattr(v, "score", 0) or 0)
    return 0.0


def _write_judge_scores(out_dir: Path, judge_scores: list[dict]) -> None:
    with (out_dir / "judge_scores.jsonl").open("w", encoding="utf-8") as fh:
        for row in judge_scores:
            fh.write(json.dumps(row) + "\n")


def _write_summary(
    out_dir: Path,
    run_id: str,
    chain_name: str,
    tier_id: str,
    judge_scores: list[dict],
    timestamp: str,
) -> None:
    lines = [
        f"# Run summary: {run_id}",
        "",
        f"**Timestamp:** {timestamp}  ",
        f"**Chain:** {chain_name}  ",
        f"**Tier:** {tier_id}  ",
        f"**Runner:** LangSmith experiment  ",
        "",
    ]
    if judge_scores:
        lines += [
            "## LLM judge scores",
            "",
            "| Type | n | Faithfulness | Correctness |",
            "|------|---|-------------|-------------|",
        ]
        by_type: dict[str, list] = {}
        for s in judge_scores:
            by_type.setdefault(s.get("type", "?"), []).append(s)
        for t in ("T1", "T2", "T3", "T4"):
            rows = by_type.get(t, [])
            if not rows:
                continue
            n = len(rows)
            faith = sum(r["faithfulness"]["score"] for r in rows) / n
            corr = sum(r["correctness"]["score"] for r in rows) / n
            lines.append(f"| {t} | {n} | {faith:.2f}/5 | {corr:.2f}/5 |")
        n_all = len(judge_scores)
        faith_all = sum(r["faithfulness"]["score"] for r in judge_scores) / n_all
        corr_all = sum(r["correctness"]["score"] for r in judge_scores) / n_all
        lines.append(f"| **overall** | {n_all} | **{faith_all:.2f}/5** | **{corr_all:.2f}/5** |")

    (out_dir / "run_summary.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run EMA RAG chain as LangSmith experiment")
    parser.add_argument("--chain", required=True, help="Chain name (e.g. simple_rag_zero, crag)")
    parser.add_argument("--tier", default="mid", choices=["mid", "frontier", "olmo"])
    parser.add_argument("--dataset", default="ema-benchmark")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--retrieval-mode", default="hybrid", choices=["dense", "bm25", "hybrid"])
    parser.add_argument("--retrieval-strategy", default="flat",
                        choices=["flat", "recursive", "hierarchical", "agentic"])
    parser.add_argument("-k", type=int, default=10)
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    result = run_experiment(
        args.chain,
        tier_id=args.tier,
        dataset_name=args.dataset,
        run_id=args.run_id,
        retrieval_mode=args.retrieval_mode,
        retrieval_strategy=args.retrieval_strategy,
        k=args.k,
    )
    print(f"run_id:           {result['run_id']}")
    print(f"n_examples:       {result['n_examples']}")
    print(f"avg_faithfulness: {result['avg_faithfulness']:.2f}/5")
    print(f"avg_correctness:  {result['avg_correctness']:.2f}/5")


if __name__ == "__main__":
    main()

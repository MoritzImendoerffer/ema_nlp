"""
Single entry point for evaluation runs.

Usage:
    python3 -m harness.run_eval --config harness/configs/baseline_a0.yaml
    python3 -m harness.run_eval --config harness/configs/baseline_a0plus.yaml

Each run:
1. Loads a YAML config from harness/configs/.
2. Builds (or reloads) the LlamaIndex VectorStoreIndex.
3. Runs retrieval eval (Recall@k, Precision@k, Citation Accuracy by T1–T4).
4. Optionally runs LLM judges (faithfulness + correctness) — requires ANTHROPIC_API_KEY.
5. Writes results to results/<run_id>/:
       config.yaml          — copy of the run config
       retrieval.json       — full retrieval results dict
       retrieval.png        — grouped bar chart
       judge_scores.jsonl   — one line per benchmark item (if judge enabled)
       run_summary.md       — human-readable summary
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(config_path: Path) -> dict:
    with config_path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return p


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run(config_path: Path) -> dict:
    cfg = load_config(config_path)
    run_id = cfg["run_id"]
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    out_dir = _resolve(cfg["results"]["base_dir"]) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # Save config snapshot
    shutil.copy(config_path, out_dir / "config.yaml")

    log.info("=== Run %s [%s] ===", run_id, timestamp)

    # ---------- Build / reload index ----------
    from llama_index.core.settings import Settings
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    from harness.embed import build_index, load_index

    idx_cfg = cfg["index"]
    corpus_path = _resolve(idx_cfg["corpus"])
    index_dir = _resolve(idx_cfg["index_dir"])
    embed_model_name = idx_cfg.get("embed_model", "BAAI/bge-large-en-v1.5")
    force_rebuild = idx_cfg.get("force_rebuild", False)

    Settings.embed_model = HuggingFaceEmbedding(model_name=embed_model_name)
    Settings.llm = None

    if force_rebuild or not (index_dir / "docstore.json").exists():
        log.info("Building index from %s", corpus_path)
        index = build_index(corpus_path, index_dir, force=True)
    else:
        log.info("Loading existing index from %s", index_dir)
        index = load_index(index_dir)

    # ---------- Build retriever ----------
    from harness.retrieve import RetrieverMode, retrieve
    mode: RetrieverMode = cfg["retrieval"]["mode"]
    k: int = cfg["retrieval"]["k"]

    def retrieve_fn(query: str):
        return retrieve(index, query, mode=mode, k=k)

    # ---------- Retrieval eval ----------
    from harness.eval_retrieval import run_eval as eval_retrieval

    benchmark_path = _resolve(cfg["benchmark"]["path"])
    if not benchmark_path.exists():
        log.warning("Benchmark not found at %s — skipping retrieval eval", benchmark_path)
        retrieval_results = {"k": k, "per_item": [], "by_type": {}}
    else:
        log.info("Running retrieval eval (k=%d, mode=%s) …", k, mode)
        retrieval_results = eval_retrieval(
            benchmark_path, retrieve_fn, k=k, out_dir=out_dir
        )
        (out_dir / "retrieval.json").write_text(
            json.dumps(retrieval_results, indent=2), encoding="utf-8"
        )

    # ---------- LLM judge (optional) ----------
    judge_scores: list[dict] = []
    judge_cfg = cfg.get("judge", {})
    if judge_cfg.get("enabled", False):
        from harness.judge import Judge
        judge = Judge(model=judge_cfg.get("model", "claude-haiku-4-5-20251001"))
        log.info("Running LLM judge …")
        with benchmark_path.open(encoding="utf-8") as fh:
            bench_items = [json.loads(line) for line in fh]

        # Load mini-corpus for context (map qa_id → answer text)
        corpus_map: dict[str, str] = {}
        try:
            with corpus_path.open(encoding="utf-8") as fh:
                for line in fh:
                    r = json.loads(line)
                    corpus_map[r["qa_id"]] = f"Q: {r['question']}\nA: {r['answer']}"
        except FileNotFoundError:
            pass

        for item in bench_items:
            retrieved = retrieve_fn(item["question"])
            # Build answer from top-1 retrieved context (retrieval-only evaluation)
            if retrieved:
                _qa_id, _score, _meta = retrieved[0]
                answer = corpus_map.get(_qa_id, "No answer found.")
                context_passages = [corpus_map[r[0]] for r in retrieved[:3] if r[0] in corpus_map]
            else:
                answer = "No answer found."
                context_passages = []

            scores = judge.score_item(
                question=item["question"],
                answer=answer,
                gold_answer=item["gold_answer"],
                context_passages=context_passages,
            )
            judge_scores.append({"bench_id": item["bench_id"], "type": item["type"], **scores})

        with (out_dir / "judge_scores.jsonl").open("w", encoding="utf-8") as fh:
            for row in judge_scores:
                fh.write(json.dumps(row) + "\n")

    # ---------- Write summary ----------
    _write_summary(out_dir, cfg, retrieval_results, judge_scores, timestamp)

    log.info("Results written to %s", out_dir)
    return {"run_id": run_id, "out_dir": str(out_dir), "retrieval": retrieval_results}


def _write_summary(
    out_dir: Path,
    cfg: dict,
    retrieval: dict,
    judge_scores: list[dict],
    timestamp: str,
) -> None:
    lines = [
        f"# Run summary: {cfg['run_id']}",
        "",
        f"**Timestamp:** {timestamp}  ",
        f"**Description:** {cfg.get('description', '')}  ",
        f"**Mode:** {cfg['retrieval']['mode']} @ k={cfg['retrieval']['k']}  ",
        "",
        "## Retrieval metrics",
        "",
    ]

    by_type = retrieval.get("by_type", {})
    if by_type:
        lines += [
            "| Type | n | Recall@k | Precision@k | Citation Acc. |",
            "|------|---|----------|-------------|---------------|",
        ]
        for t in ("T1", "T2", "T3", "T4", "overall"):
            if t not in by_type:
                continue
            row = by_type[t]
            lines.append(
                f"| {t} | {row['n_items']} "
                f"| {row['recall_at_k']:.3f} "
                f"| {row['precision_at_k']:.3f} "
                f"| {row['citation_accuracy']:.3f} |"
            )
    else:
        lines.append("*(no benchmark found — retrieval eval skipped)*")

    if judge_scores:
        lines += ["", "## LLM judge scores", ""]
        faith_avg = sum(x["faithfulness"]["score"] for x in judge_scores) / len(judge_scores)
        corr_avg = sum(x["correctness"]["score"] for x in judge_scores) / len(judge_scores)
        lines.append(f"- Faithfulness (avg): **{faith_avg:.2f}** / 5")
        lines.append(f"- Correctness (avg): **{corr_avg:.2f}** / 5")

    (out_dir / "run_summary.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run EMA NLP evaluation harness")
    parser.add_argument(
        "--config", type=Path, required=True, help="Path to run config YAML"
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    run(args.config)


if __name__ == "__main__":
    main()

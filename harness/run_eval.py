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
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent

EMA_RETRIEVER = os.getenv("EMA_RETRIEVER", "faiss").lower()
if EMA_RETRIEVER not in ("faiss", "pgvector"):
    raise ValueError(
        f"EMA_RETRIEVER must be 'faiss' or 'pgvector', got {EMA_RETRIEVER!r}"
    )


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(config_path: Path) -> dict:
    with config_path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _resolve(path_str: str) -> Path:
    p = Path(path_str).expanduser()
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
    from harness.providers import configure_embed_model

    idx_cfg = cfg["index"]
    embed_model_name: str | None = idx_cfg.get("embed_model")
    # Always resolved: also used by QueryCache (few-shot injection) regardless of backend.
    index_dir = _resolve(idx_cfg["index_dir"])

    log.info("EMA_RETRIEVER=%s", EMA_RETRIEVER)

    # ---------- Retrieval config (YAML) ----------
    # Legacy RetrievalConfig is kept for workflow config_attributes() span
    # stamping in both backends; the pgvector retrieve_fn ignores it and
    # consults RetrievalConfigPG instead. Mirrors app.py NARR-021 dispatch.
    from harness.retrieve import RetrievalConfig

    ret_section = cfg["retrieval"]
    ret_config = RetrievalConfig.from_yaml_section(ret_section)
    k: int = ret_config.k

    if EMA_RETRIEVER == "pgvector":
        configure_embed_model(embed_model_name)
        log.info("EMA_RETRIEVER=pgvector — skipping FAISS index load")
        index = None

        from harness.retrieve_pg import RetrievalConfigPG, build_retrieve_fn_pg
        ret_config_pg = RetrievalConfigPG.from_yaml_section(ret_section)
        retrieve_fn = build_retrieve_fn_pg(ret_config_pg)
    else:
        from harness.embed import build_index

        corpus_path = _resolve(idx_cfg["corpus"])
        force_rebuild = idx_cfg.get("force_rebuild", False)

        configure_embed_model(embed_model_name)

        if force_rebuild or not (index_dir / "docstore.json").exists():
            log.info("Building index from %s", corpus_path)
            index = build_index(corpus_path, index_dir, force=True)
        else:
            log.info("Loading existing index from %s", index_dir)
            index = build_index(corpus_path, index_dir, force=False)

        from harness.retrieve import AblationConfig, build_retrieve_fn
        abl_config = AblationConfig.from_yaml(cfg.get("ablation", {}))
        retrieve_fn = build_retrieve_fn(ret_config, abl_config, index)

    # ---------- Retrieval eval ----------
    from harness.eval_retrieval import run_eval as eval_retrieval

    benchmark_path = _resolve(cfg["benchmark"]["path"])
    if not benchmark_path.exists():
        log.warning("Benchmark not found at %s — skipping retrieval eval", benchmark_path)
        retrieval_results = {"k": k, "per_item": [], "by_type": {}}
    else:
        log.info("Running retrieval eval (k=%d, mode=%s, strategy=%s) …", k, ret_config.mode, ret_config.strategy)
        retrieval_results = eval_retrieval(
            benchmark_path, retrieve_fn, k=k, out_dir=out_dir
        )
        (out_dir / "retrieval.json").write_text(
            json.dumps(retrieval_results, indent=2), encoding="utf-8"
        )

    # ---------- Answer generation (orchestration via workflow registry) ----------
    orch_cfg: dict = cfg.get("orchestration", {})
    generated_answers: dict[str, str] = {}  # bench_id → answer text
    docs_cache: dict[str, list] = {}        # bench_id → list[TextNode]
    if orch_cfg:
        from harness.llms import get_llm
        from harness.workflows.registry import get_workflow
        orch_strategy = orch_cfg["strategy"]
        orch_prompt_strategy: str | None = orch_cfg.get("prompt_strategy") or None
        log.info(
            "Orchestration enabled: strategy=%s prompt_strategy=%s (agent role)",
            orch_strategy, orch_prompt_strategy or "default",
        )

        llm = get_llm("agent")
        workflow = get_workflow(
            orch_strategy,
            index=index,
            llm=llm,
            retrieval_config=ret_config,
            prompt_strategy=orch_prompt_strategy,
            retrieve_fn=retrieve_fn,
        )

        cache_inject: bool = orch_cfg.get("cache_inject", False)
        _eval_cache = None
        if cache_inject:
            import numpy as np
            from llama_index.core import Settings
            from harness.fewshot_inject import get_fewshot_context
            from harness.query_cache import QueryCache
            _eval_cache = QueryCache(index_dir)
            log.info("Few-shot injection enabled (cache_inject=true)")

        with benchmark_path.open(encoding="utf-8") as fh:
            orch_items = [json.loads(line) for line in fh]

        ag_out_path = out_dir / "generated_answers.jsonl"
        with ag_out_path.open("w", encoding="utf-8") as ag_out:
            for item in orch_items:
                try:
                    few_shot_context = ""
                    if cache_inject and _eval_cache is not None:
                        q_vec = np.array(
                            Settings.embed_model.get_text_embedding(item["question"]),
                            dtype=np.float32,
                        )
                        few_shot_context = get_fewshot_context(q_vec, _eval_cache, k=3, min_rating=4) or ""
                    result = workflow.invoke({
                        "question": item["question"],
                        "few_shot_context": few_shot_context,
                        "run_id": cfg["run_id"],
                        "source": "eval",
                    })
                    generated_answers[item["bench_id"]] = result["answer_text"]
                    docs_cache[item["bench_id"]] = result.get("docs", [])
                    row = {
                        "bench_id": item["bench_id"],
                        "type": item["type"],
                        "answer_text": result["answer_text"],
                        "prompt_strategy": result.get("prompt_strategy", orch_strategy),
                        "trajectory": result.get("trajectory", []),
                        "cited_qa_ids": result.get("cited_qa_ids", []),
                    }
                except Exception as exc:
                    log.warning("Answer generation failed for %s: %s", item["bench_id"], exc)
                    generated_answers[item["bench_id"]] = "No answer generated."
                    docs_cache[item["bench_id"]] = []
                    row = {"bench_id": item["bench_id"], "type": item["type"], "error": str(exc)}
                ag_out.write(json.dumps(row, ensure_ascii=False) + "\n")
        log.info("Generated answers written to %s", ag_out_path)

        failure_count = sum(1 for v in generated_answers.values() if v == "No answer generated.")
        if generated_answers and failure_count / len(generated_answers) > 0.5:
            log.warning(
                "HIGH ANSWER FAILURE RATE: %d/%d items returned 'No answer generated.' "
                "— check ANTHROPIC_API_KEY and model config",
                failure_count, len(generated_answers),
            )

    # ---------- LLM judge (optional) ----------
    judge_scores: list[dict] = []
    judge_cfg = cfg.get("judge", {})
    if judge_cfg.get("enabled", False):
        from harness.judge import Judge
        from harness.workflows.utils import results_to_docs
        judge = Judge()  # model configured via models.yaml roles.judge
        log.info("Running LLM judge …")
        with benchmark_path.open(encoding="utf-8") as fh:
            bench_items = [json.loads(line) for line in fh]

        for item in bench_items:
            docs = docs_cache.get(item["bench_id"])
            if docs is None:
                raw = retrieve_fn(item["question"])
                docs = results_to_docs(raw, index)
                docs_cache[item["bench_id"]] = docs

            if item["bench_id"] in generated_answers:
                answer = generated_answers[item["bench_id"]]
            elif docs:
                answer = docs[0].text
            else:
                answer = "No answer found."

            context_passages = [doc.text for doc in docs[:10]]
            cited_qa_ids = [doc.metadata["qa_id"] for doc in docs[:10]]

            scores = judge.score_item(
                question=item["question"],
                answer=answer,
                gold_answer=item["gold_answer"],
                context_passages=context_passages,
            )
            judge_scores.append({
                "bench_id": item["bench_id"],
                "type": item["type"],
                "cited_qa_ids": cited_qa_ids,
                **scores,
            })

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
        f"**Mode:** {cfg['retrieval'].get('mode','hybrid')} @ k={cfg['retrieval'].get('k',10)} strategy={cfg['retrieval'].get('strategy','flat')}  ",
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
        lines += [
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
            faith = sum(x["faithfulness"]["score"] for x in rows) / n
            corr = sum(x["correctness"]["score"] for x in rows) / n
            lines.append(f"| {t} | {n} | {faith:.2f}/5 | {corr:.2f}/5 |")
        n_all = len(judge_scores)
        faith_all = sum(x["faithfulness"]["score"] for x in judge_scores) / n_all
        corr_all = sum(x["correctness"]["score"] for x in judge_scores) / n_all
        lines.append(f"| **overall** | {n_all} | **{faith_all:.2f}/5** | **{corr_all:.2f}/5** |")

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

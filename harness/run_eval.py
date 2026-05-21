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

    # cache: false — the interactive semantic cache (app.py) is bypassed for batch runs
    if cfg.get("cache", False):
        log.warning("cache: true has no effect in run_eval — cache is interactive-only (app.py)")

    # ---------- Build / reload index ----------
    from harness.embed import build_index
    from harness.providers import configure_embed_model, get_llm_model

    idx_cfg = cfg["index"]
    corpus_path = _resolve(idx_cfg["corpus"])
    index_dir = _resolve(idx_cfg["index_dir"])
    embed_model_name: str | None = idx_cfg.get("embed_model")
    force_rebuild = idx_cfg.get("force_rebuild", False)

    configure_embed_model(embed_model_name)

    if force_rebuild or not (index_dir / "docstore.json").exists():
        log.info("Building index from %s", corpus_path)
        index = build_index(corpus_path, index_dir, force=True)
    else:
        log.info("Loading existing index from %s", index_dir)
        index = build_index(corpus_path, index_dir, force=False)

    # ---------- Build retriever ----------
    from harness.retrieve import RetrieverMode, retrieve
    mode: RetrieverMode = cfg["retrieval"]["mode"]
    k: int = cfg["retrieval"]["k"]

    # ---------- Ablation config ----------
    abl_cfg: dict = cfg.get("ablation", {})
    _query_exp_cfg: dict = abl_cfg.get("query_expansion", {})
    _topic_cfg: dict = abl_cfg.get("topic_filter", {})
    _reranker_name: str | None = abl_cfg.get("reranker", None)
    _reranker_model: str = abl_cfg.get("reranker_model") or get_llm_model()
    _reranker_max_chunks: int = abl_cfg.get("reranker_max_chunks", 5)

    _expander = None
    if _query_exp_cfg.get("enabled", False):
        from harness.ablations.a1_query_expansion import QueryExpander
        _dict_path_str: str | None = _query_exp_cfg.get("acronym_dict")
        _dict_path = _resolve(_dict_path_str) if _dict_path_str else None
        _expander = QueryExpander(_dict_path) if _dict_path else QueryExpander()
        log.info("A1 query expansion enabled (dict: %s)", _expander)

    _topic_filter_mode: str | None = _topic_cfg.get("mode") if _topic_cfg.get("enabled", False) else None
    if _topic_filter_mode:
        log.info("A2 topic filter enabled (mode: %s)", _topic_filter_mode)

    if _reranker_name:
        log.info("Reranker enabled: %s (model=%s, max_chunks=%d)", _reranker_name, _reranker_model, _reranker_max_chunks)

    def retrieve_fn(query: str):
        # A1 — optional query expansion
        expanded = _expander.expand(query) if _expander else query
        if expanded != query:
            log.debug("A1 expanded: %r → %r", query, expanded)

        results = retrieve(index, expanded, mode=mode, k=k)

        # A2 — optional topic filter
        if _topic_filter_mode == "keyword":
            from harness.ablations.a2_topic_filter import filter_by_topic_keyword
            results = filter_by_topic_keyword(results, query)
        elif _topic_filter_mode == "concept":
            from harness.ablations.a2_topic_filter import make_concept_retriever
            retriever = make_concept_retriever(index, query, k=k)
            from harness.retrieve import _results_from_nodes
            results = _results_from_nodes(retriever.retrieve(expanded))

        # A3/A4 — optional LLM reranker
        if _reranker_name == "sme":
            import harness.ablations.a3_reranker as _a3
            results = _a3.rerank(results, query, index, model=_reranker_model, max_chunks=_reranker_max_chunks)
        elif _reranker_name == "generic":
            import harness.ablations.a4_reranker as _a4
            results = _a4.rerank(results, query, index, model=_reranker_model, max_chunks=_reranker_max_chunks)

        return results

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

    # ---------- Answer generation (Ablation C) ----------
    ans_gen_cfg = cfg.get("answer_generation", {})
    generated_answers: dict[str, str] = {}  # bench_id → answer text
    retrieved_cache: dict[str, list] = {}   # bench_id → retrieve_fn output (avoid double call)
    if ans_gen_cfg.get("enabled", False):
        from harness.answer_gen import generate_answer
        from harness.models import TIER_MID
        ag_strategy = ans_gen_cfg.get("strategy", "zero_shot")
        ag_tier = ans_gen_cfg.get("tier_id", TIER_MID)
        log.info("Answer generation enabled: strategy=%s tier=%s", ag_strategy, ag_tier)

        # Build corpus map qa_id → {text, source_title, source_url}
        ag_corpus_map: dict[str, dict] = {}
        try:
            with corpus_path.open(encoding="utf-8") as fh:
                for line in fh:
                    r = json.loads(line)
                    ag_corpus_map[r["qa_id"]] = {
                        "qa_id": r["qa_id"],
                        "text": f"Q: {r['question']}\n\nA: {r['answer']}",
                        "source_title": r.get("source_title", ""),
                        "source_url": r.get("source_url", ""),
                    }
        except FileNotFoundError:
            log.warning("Corpus not found for answer generation; answers will be empty")

        with benchmark_path.open(encoding="utf-8") as fh:
            ag_items = [json.loads(line) for line in fh]

        ag_out_path = out_dir / "generated_answers.jsonl"
        with ag_out_path.open("w", encoding="utf-8") as ag_out:
            for item in ag_items:
                retrieved = retrieve_fn(item["question"])
                retrieved_cache[item["bench_id"]] = retrieved
                docs = []
                for qa_id, score, meta in retrieved[:10]:
                    doc = ag_corpus_map.get(qa_id, {})
                    if doc:
                        docs.append({**doc, "score": score})
                try:
                    gen = generate_answer(
                        item["question"],
                        docs,
                        strategy=ag_strategy,
                        tier_id=ag_tier,
                    )
                    generated_answers[item["bench_id"]] = gen["answer_text"]
                    row = {"bench_id": item["bench_id"], "type": item["type"], **gen}
                except Exception as exc:
                    log.warning("Answer generation failed for %s: %s", item["bench_id"], exc)
                    generated_answers[item["bench_id"]] = "No answer generated."
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
        judge = Judge(model=judge_cfg.get("model") or get_llm_model())
        log.info("Running LLM judge …")
        with benchmark_path.open(encoding="utf-8") as fh:
            bench_items = [json.loads(line) for line in fh]

        # Load corpus for context
        corpus_map: dict[str, str] = {}
        try:
            with corpus_path.open(encoding="utf-8") as fh:
                for line in fh:
                    r = json.loads(line)
                    corpus_map[r["qa_id"]] = f"Q: {r['question']}\nA: {r['answer']}"
        except FileNotFoundError:
            pass

        for item in bench_items:
            retrieved = retrieved_cache.get(item["bench_id"]) or retrieve_fn(item["question"])
            # Use LLM-generated answer if available (Ablation C), else top-1 retrieved
            if item["bench_id"] in generated_answers:
                answer = generated_answers[item["bench_id"]]
            elif retrieved:
                _qa_id, _score, _meta = retrieved[0]
                answer = corpus_map.get(_qa_id, "No answer found.")
            else:
                answer = "No answer found."
            context_passages = [corpus_map[r[0]] for r in retrieved[:10] if r[0] in corpus_map]

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

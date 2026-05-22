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
    from harness.retrieve import RetrievalConfig, make_raw_retriever

    ret_section = cfg["retrieval"]
    ret_config = RetrievalConfig.from_yaml_section(ret_section)
    k: int = ret_config.k

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

    # Load hierarchical index if needed
    _hier_index = None
    if ret_config.strategy == "hierarchical":
        hier_dir = ret_config.hierarchical.summary_index_dir
        if hier_dir:
            try:
                from harness.embed_hierarchical import load_hierarchical_index
                _hier_index = load_hierarchical_index(Path(hier_dir).expanduser())
                log.info("Hierarchical index loaded from %s", hier_dir)
            except Exception as exc:
                log.warning("Could not load hierarchical index from %s: %s — falling back to flat", hier_dir, exc)

    _base_retriever = make_raw_retriever(ret_config, index, hier_index=_hier_index)

    def retrieve_fn(query: str):
        # A1 — optional query expansion
        expanded = _expander.expand(query) if _expander else query
        if expanded != query:
            log.debug("A1 expanded: %r → %r", query, expanded)

        results = _base_retriever(expanded)

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
    docs_cache: dict[str, list] = {}        # bench_id → list[Doc]
    if orch_cfg:
        from harness.llms import get_llm
        from harness.workflows.registry import get_workflow
        orch_strategy = orch_cfg["strategy"]
        orch_tier = orch_cfg.get("tier_id", "mid")
        log.info("Orchestration enabled: strategy=%s tier=%s", orch_strategy, orch_tier)

        llm = get_llm(orch_tier)
        workflow = get_workflow(
            orch_strategy, index=index, llm=llm, retrieval_config=ret_config
        )

        with benchmark_path.open(encoding="utf-8") as fh:
            orch_items = [json.loads(line) for line in fh]

        ag_out_path = out_dir / "generated_answers.jsonl"
        with ag_out_path.open("w", encoding="utf-8") as ag_out:
            for item in orch_items:
                try:
                    result = workflow.invoke({"question": item["question"]})
                    generated_answers[item["bench_id"]] = result["answer_text"]
                    docs_cache[item["bench_id"]] = result.get("docs", [])
                    row = {
                        "bench_id": item["bench_id"],
                        "type": item["type"],
                        "answer_text": result["answer_text"],
                        "prompt_strategy": result.get("prompt_strategy", orch_strategy),
                        "tier_id": orch_tier,
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
        judge = Judge(model=judge_cfg.get("model") or get_llm_model())
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
                answer = docs[0].page_content
            else:
                answer = "No answer found."

            context_passages = [doc.page_content for doc in docs[:10]]
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

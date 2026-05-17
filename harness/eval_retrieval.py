"""
Retrieval evaluation: Recall@k, Precision@k, Citation Accuracy.

Metrics (per benchmark item, then averaged by question type T1–T4):
    Recall@k         = |gold_qa_ids ∩ top_k_qa_ids| / |gold_qa_ids|
    Precision@k      = |gold_qa_ids ∩ top_k_qa_ids| / k
    Citation Accuracy = |{source_url in top_k} ∩ gold_source_urls| / |gold_source_urls|

Citation Accuracy is a URL-level recall check: does the retriever surface nodes
from the correct *source documents*, independent of qa_id identity.

Usage:
    from harness.eval_retrieval import score_item, summarise_by_type, plot_by_type, run_eval
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib
import matplotlib.pyplot as plt

matplotlib.use("Agg")  # headless rendering

from harness.retrieve import RetrievalResult

# ---------------------------------------------------------------------------
# Per-item scoring
# ---------------------------------------------------------------------------

def score_item(
    gold_qa_ids: list[str],
    gold_source_urls: list[str],
    results: list[RetrievalResult],
    k: int,
) -> dict[str, float]:
    """Return Recall@k, Precision@k, and Citation Accuracy for one benchmark item."""
    top_k = results[:k]
    retrieved_ids = {qa_id for qa_id, _score, _meta in top_k}
    retrieved_urls = {meta.get("source_url", "") for _qa_id, _score, meta in top_k}

    gold_id_set = set(gold_qa_ids)
    gold_url_set = set(gold_source_urls)

    n_gold = max(1, len(gold_id_set))
    n_k = max(1, len(top_k))
    n_gold_urls = max(1, len(gold_url_set))

    recall = len(gold_id_set & retrieved_ids) / n_gold
    precision = len(gold_id_set & retrieved_ids) / n_k
    citation_acc = len(gold_url_set & retrieved_urls) / n_gold_urls

    return {"recall_at_k": recall, "precision_at_k": precision, "citation_accuracy": citation_acc}


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def summarise_by_type(
    per_item: list[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    """Average per-item scores by question type (T1/T2/T3/T4) and across all items."""
    buckets: dict[str, list[dict[str, float]]] = {}
    for item in per_item:
        t = item["type"]
        buckets.setdefault(t, []).append(item)

    result: dict[str, dict[str, float]] = {}
    all_items = per_item
    for label, items in list(buckets.items()) + [("overall", all_items)]:
        if not items:
            continue
        result[label] = {
            "recall_at_k": sum(x["recall_at_k"] for x in items) / len(items),
            "precision_at_k": sum(x["precision_at_k"] for x in items) / len(items),
            "citation_accuracy": sum(x["citation_accuracy"] for x in items) / len(items),
            "n_items": len(items),
        }
    return result


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

_METRIC_LABELS = {
    "recall_at_k": "Recall@k",
    "precision_at_k": "Precision@k",
    "citation_accuracy": "Citation Acc.",
}
_COLORS = ["#4C72B0", "#DD8452", "#55A868"]


def plot_by_type(
    by_type: dict[str, dict[str, float]],
    k: int,
    out_path: Path,
    title: str | None = None,
) -> None:
    """Save a grouped bar chart of retrieval metrics to *out_path*."""
    type_order = [t for t in ("T1", "T2", "T3", "T4", "overall") if t in by_type]
    metrics = ["recall_at_k", "precision_at_k", "citation_accuracy"]
    n_types = len(type_order)
    n_metrics = len(metrics)

    bar_width = 0.2
    x = range(n_types)

    fig, ax = plt.subplots(figsize=(max(6, n_types * 1.8), 5))

    for m_idx, metric in enumerate(metrics):
        offsets = [i + (m_idx - n_metrics / 2 + 0.5) * bar_width for i in x]
        values = [by_type[t].get(metric, 0.0) for t in type_order]
        ax.bar(offsets, values, bar_width, label=_METRIC_LABELS[metric], color=_COLORS[m_idx])

    ax.set_xlabel("Question type")
    ax.set_ylabel("Score")
    ax.set_ylim(0, 1.05)
    ax.set_xticks(list(x))
    ax.set_xticklabels(type_order)
    ax.set_title(title or f"Retrieval metrics @k={k}")
    ax.legend(loc="upper right")
    ax.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Top-level runner (for use from run_eval.py)
# ---------------------------------------------------------------------------

def run_eval(
    benchmark_path: Path,
    retrieve_fn,
    k: int = 10,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Evaluate a retriever over the benchmark JSONL.

    Args:
        benchmark_path: Path to benchmark.jsonl
        retrieve_fn:    Callable(query: str) -> list[RetrievalResult] (already bound to index + mode + k)
        k:              Cutoff for retrieval metrics
        out_dir:        If given, write results.json and metrics.png there

    Returns:
        Results dict with "k", "per_item", "by_type" keys.
    """
    per_item: list[dict[str, Any]] = []

    with benchmark_path.open(encoding="utf-8") as fh:
        for line in fh:
            item = json.loads(line)
            bench_id = item["bench_id"]
            q_type = item["type"]
            gold_qa_ids = item.get("gold_qa_ids", [])
            gold_sources = item.get("gold_sources", [])
            gold_source_urls = [s["url"] for s in gold_sources]
            question = item["question"]

            results = retrieve_fn(question)
            scores = score_item(gold_qa_ids, gold_source_urls, results, k)

            per_item.append({"bench_id": bench_id, "type": q_type, **scores})

    by_type = summarise_by_type(per_item)
    output = {"k": k, "per_item": per_item, "by_type": by_type}

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "results.json").write_text(
            json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        plot_by_type(by_type, k=k, out_path=out_dir / "metrics.png")

    return output

"""
Compute lift: open-book correctness minus closed-book correctness (Bug 8).

Lift is the headline metric in ROADMAP.md — it measures how much the RAG
pipeline adds over the model's parametric knowledge, and is contamination-robust
because a model that memorised the answer gains zero lift.

Usage::

    python3 -m harness.compute_lift \\
        --closed results/baseline_closed \\
        --open   results/ablation_c_frontier_zero

Output: lift per question-type (T1–T4) and overall, printed as a Markdown table.
Optionally writes a JSON file with full item-level details.

A "closed-book" run is any run without answer_generation (judge falls back to
top-1 retrieved passage), OR an explicit closed-book config where the answer
generator receives zero context documents.  Both produce a correctness score
that represents the system without helpful evidence — the open-book run provides
the same question answered with retrieved context, and lift = open − closed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_scores(run_dir: Path) -> dict[str, dict]:
    """Return bench_id → score row dict from judge_scores.jsonl."""
    path = run_dir / "judge_scores.jsonl"
    if not path.exists():
        raise FileNotFoundError(
            f"No judge_scores.jsonl in {run_dir}. "
            "Re-run with judge: enabled: true first."
        )
    scores: dict[str, dict] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            scores[row["bench_id"]] = row
    return scores


def compute_lift(
    closed_dir: Path,
    open_dir: Path,
    output_path: Path | None = None,
) -> dict:
    """
    Compute per-type and overall lift.

    Returns a dict with keys "by_type" and "overall", each containing:
        n, closed_correctness, open_correctness, lift
    """
    closed = _load_scores(closed_dir)
    open_ = _load_scores(open_dir)

    shared_ids = set(closed) & set(open_)
    if not shared_ids:
        raise ValueError(
            "No bench_ids in common between the two runs. "
            "Both runs must evaluate the same benchmark."
        )

    items: list[dict] = []
    for bid in sorted(shared_ids):
        c_row = closed[bid]
        o_row = open_[bid]
        items.append(
            {
                "bench_id": bid,
                "type": c_row.get("type", "?"),
                "closed_correctness": c_row["correctness"]["score"],
                "open_correctness": o_row["correctness"]["score"],
                "lift": o_row["correctness"]["score"] - c_row["correctness"]["score"],
                "closed_faithfulness": c_row["faithfulness"]["score"],
                "open_faithfulness": o_row["faithfulness"]["score"],
            }
        )

    def _aggregate(rows: list[dict]) -> dict:
        n = len(rows)
        if n == 0:
            return {"n": 0, "closed_correctness": 0.0, "open_correctness": 0.0, "lift": 0.0}
        return {
            "n": n,
            "closed_correctness": sum(r["closed_correctness"] for r in rows) / n,
            "open_correctness": sum(r["open_correctness"] for r in rows) / n,
            "lift": sum(r["lift"] for r in rows) / n,
        }

    by_type: dict[str, dict] = {}
    for t in ("T1", "T2", "T3", "T4"):
        subset = [r for r in items if r["type"] == t]
        if subset:
            by_type[t] = _aggregate(subset)

    result = {
        "closed_run": str(closed_dir),
        "open_run": str(open_dir),
        "by_type": by_type,
        "overall": _aggregate(items),
        "items": items,
    }

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    return result


def _print_table(result: dict) -> None:
    closed_label = Path(result["closed_run"]).name
    open_label = Path(result["open_run"]).name
    print(f"\n## Lift: {open_label} vs {closed_label} (closed-book)\n")
    print("| Type | n | Closed corr. | Open corr. | Lift |")
    print("|------|---|-------------|-----------|------|")

    for t in ("T1", "T2", "T3", "T4"):
        if t not in result["by_type"]:
            continue
        r = result["by_type"][t]
        print(
            f"| {t} | {r['n']} "
            f"| {r['closed_correctness']:.2f}/5 "
            f"| {r['open_correctness']:.2f}/5 "
            f"| **{r['lift']:+.2f}** |"
        )

    ov = result["overall"]
    print(
        f"| **overall** | {ov['n']} "
        f"| {ov['closed_correctness']:.2f}/5 "
        f"| {ov['open_correctness']:.2f}/5 "
        f"| **{ov['lift']:+.2f}** |"
    )
    print()


def _main() -> None:
    parser = argparse.ArgumentParser(description="Compute RAG lift from two eval runs")
    parser.add_argument(
        "--closed", type=Path, required=True,
        help="Results dir for closed-book (no-context) run",
    )
    parser.add_argument(
        "--open", type=Path, required=True,
        help="Results dir for open-book (RAG) run",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Optional JSON output path for item-level lift data",
    )
    args = parser.parse_args()

    try:
        result = compute_lift(args.closed, args.open, args.output)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    _print_table(result)
    if args.output:
        print(f"Item-level lift written to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    _main()

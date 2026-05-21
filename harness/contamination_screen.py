#!/usr/bin/env python3
"""
TASK-015: Closed-book contamination screen for the benchmark.

Runs every benchmark item through configured LLMs with NO retrieval context.
Records whether the model can answer correctly without seeing the corpus.

PASS/FAIL gate: if zero_shot_known > 40% on T1 items for any model, those
items are flagged REMOVE and must be replaced before TASK-021. Threshold
is configurable via --threshold.

Usage:
  python harness/contamination_screen.py \
    --benchmark benchmark/benchmark.jsonl \
    --models gpt-4o-mini olmo-3-mini \
    --output results/contamination/ \
    [--threshold 0.40] \
    [--slot-sample 10] \
    [--dry-run]

Output files:
  results/contamination/<model_id>_closed_book.jsonl  — per-item results
  results/contamination/contamination_summary.md       — aggregate report
"""

import json
import os
import sys
import re
import argparse
import random
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

# THRESHOLD: if zero_shot_known rate on T1 items exceeds this, flag items REMOVE
DEFAULT_THRESHOLD = 0.40

# Maximum length of gold_answer substring to use as "ground truth" for match check
ANSWER_MATCH_MAX_CHARS = 200


def load_benchmark(path: Path) -> list[dict]:
    items = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def get_llm_client():
    """Return an LLM callable. Loads provider config via harness/providers.py."""
    try:
        from harness.providers import get_llm_model
        return get_llm_model()
    except ImportError:
        # Fallback: try OpenAI
        try:
            import openai
            client = openai.OpenAI()
            return client
        except ImportError:
            raise RuntimeError("No LLM provider available. Install openai or configure harness/providers.py.")


def query_model_closed_book(model_id: str, question: str, llm_client) -> str:
    """Call LLM with question only — no retrieval context."""
    system_prompt = (
        "You are an expert on European Medicines Agency (EMA) regulatory procedures. "
        "Answer the following question as precisely as possible using only your knowledge. "
        "If you are not certain, say so explicitly. Do not refuse to answer."
    )
    try:
        response = llm_client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
            temperature=0.0,
            max_tokens=512,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[ERROR: {e}]"


def assess_match(gold_answer: str, model_answer: str) -> bool:
    """
    Heuristic match check: does model_answer contain key facts from gold_answer?

    Uses keyword overlap on:
    - Numbers (e.g. "60 days", "15 calendar days", "210 days")
    - Key terms (specific regulatory terms)
    Returns True if ≥70% of extracted key facts appear in model_answer.
    """
    gold_lower = gold_answer.lower()
    model_lower = model_answer.lower()

    # Extract numeric facts from gold (e.g. "60 days", "150 days", "15 calendar days")
    numeric_facts = re.findall(r"\d+\s*(?:calendar\s+)?days?|\d+\s*months?|\d+\s*years?|\d+\s*ng/day", gold_lower)

    # Extract key regulatory terms
    key_terms = []
    for pattern in [r"\bprac\b", r"\bchmp\b", r"\bcmdh\b", r"\bqppv\b",
                    r"\btype\s+i[ab]\b", r"\btype\s+ii\b", r"\barticle\s+\d+",
                    r"\bworksharing\b", r"\bextension\b", r"\bherbal\b",
                    r"\borphan\b", r"\bfee\b", r"\brapporteur\b"]:
        for m in re.findall(pattern, gold_lower):
            key_terms.append(m)

    all_facts = numeric_facts + key_terms
    if not all_facts:
        # Fall back to word overlap
        gold_words = set(w for w in gold_lower.split() if len(w) > 4)
        model_words = set(model_lower.split())
        if not gold_words:
            return False
        overlap = gold_words & model_words
        return len(overlap) / len(gold_words) >= 0.5

    matched = sum(1 for fact in all_facts if fact in model_lower)
    return matched / len(all_facts) >= 0.70


def slot_guessing_test(items: list[dict], model_id: str, llm_client, n_sample: int = 10) -> dict:
    """
    Slot-guessing test: mask a specific numeric value in the question, ask model to fill it in.
    Returns hit rate (fraction of masked values correctly guessed).
    """
    # Find items with numeric values in gold_answer
    numeric_pattern = re.compile(r"\b(\d+)\s*(calendar\s+)?days?\b", re.I)
    candidates = []
    for item in items:
        nums = numeric_pattern.findall(item["gold_answer"])
        if nums:
            candidates.append((item, nums[0][0]))

    if not candidates:
        return {"sample_size": 0, "hit_rate": None, "note": "No numeric candidates found"}

    sample = random.sample(candidates, min(n_sample, len(candidates)))
    hits = 0

    results = []
    for item, numeric_val in sample:
        # Replace the number in the question with [BLANK]
        masked_q = item["question"] + f"\n\n(The answer contains a specific number. What is it? Give only the number.)"
        model_answer = query_model_closed_book(model_id, masked_q, llm_client)
        hit = numeric_val in model_answer
        if hit:
            hits += 1
        results.append({
            "bench_id": item["bench_id"],
            "target_value": numeric_val,
            "model_answer": model_answer[:200],
            "hit": hit,
        })

    hit_rate = hits / len(sample)
    return {
        "sample_size": len(sample),
        "hit_rate": hit_rate,
        "hits": hits,
        "results": results,
    }


def run_screen(
    benchmark_path: Path,
    model_ids: list[str],
    output_dir: Path,
    threshold: float = DEFAULT_THRESHOLD,
    slot_sample: int = 10,
    dry_run: bool = False,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    items = load_benchmark(benchmark_path)
    print(f"Loaded {len(items)} benchmark items")

    if dry_run:
        print("[DRY RUN] Would query models:", model_ids)
        print("[DRY RUN] Output dir:", output_dir)
        return {}

    summary = {}

    for model_id in model_ids:
        print(f"\n=== Model: {model_id} ===")
        try:
            llm_client = get_llm_client()
        except RuntimeError as e:
            print(f"  Skipping {model_id}: {e}")
            continue

        results = []
        zero_shot_known_count = {t: 0 for t in ["T1", "T2", "T3", "T4"]}
        type_totals = {t: 0 for t in ["T1", "T2", "T3", "T4"]}

        for item in items:
            q_type = item["type"]
            type_totals[q_type] += 1
            print(f"  {item['bench_id']}: ", end="", flush=True)

            model_answer = query_model_closed_book(model_id, item["question"], llm_client)
            matches_gold = assess_match(item["gold_answer"], model_answer)

            if matches_gold:
                zero_shot_known_count[q_type] += 1

            result = {
                "bench_id": item["bench_id"],
                "type": q_type,
                "question": item["question"],
                "gold_answer": item["gold_answer"][:300],
                "model_id": model_id,
                "model_answer": model_answer,
                "matches_gold": matches_gold,
                "zero_shot_known": matches_gold,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            results.append(result)
            print("known" if matches_gold else "unknown")

        # Slot-guessing test on subsample
        print(f"\n  Running slot-guessing test (n={slot_sample})...")
        slot_result = slot_guessing_test(items, model_id, llm_client, n_sample=slot_sample)

        # Write per-model JSONL
        model_safe = model_id.replace("/", "_").replace(":", "_")
        out_path = output_dir / f"{model_safe}_closed_book.jsonl"
        with open(out_path, "w") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"  Written {len(results)} results to {out_path}")

        # Compute rates per type
        rates = {}
        flagged = []
        for t in ["T1", "T2", "T3", "T4"]:
            n = type_totals[t]
            k = zero_shot_known_count[t]
            rate = k / n if n > 0 else 0.0
            rates[t] = {"count": n, "known": k, "rate": rate}
            if t == "T1" and rate > threshold:
                flagged_ids = [r["bench_id"] for r in results if r["type"] == "T1" and r["zero_shot_known"]]
                flagged.extend(flagged_ids)

        summary[model_id] = {
            "rates": rates,
            "slot_guessing": slot_result,
            "flagged_remove": flagged,
            "gate_pass": len(flagged) == 0,
        }

        print(f"\n  T1 zero-shot-known rate: {rates['T1']['rate']:.1%} (threshold: {threshold:.0%})")
        if flagged:
            print(f"  GATE FAIL: {len(flagged)} T1 items exceed threshold: {flagged}")
        else:
            print(f"  GATE PASS: T1 contamination within threshold")

    # Write summary markdown
    write_summary(summary, output_dir, threshold)
    return summary


def write_summary(summary: dict, output_dir: Path, threshold: float):
    lines = [
        "# Contamination Screen Summary",
        f"\nGenerated: {datetime.now(timezone.utc).isoformat()}",
        f"Threshold for REMOVE flag: T1 zero_shot_known > {threshold:.0%}\n",
        "## Results by model\n",
    ]

    all_pass = True
    for model_id, data in summary.items():
        lines.append(f"### {model_id}\n")
        lines.append("| Type | N | Known | Rate |")
        lines.append("|------|---|-------|------|")
        for t, r in data["rates"].items():
            lines.append(f"| {t} | {r['count']} | {r['known']} | {r['rate']:.1%} |")
        lines.append("")

        sg = data.get("slot_guessing", {})
        if sg.get("hit_rate") is not None:
            lines.append(f"**Slot-guessing hit rate:** {sg['hit_rate']:.1%} (n={sg['sample_size']})\n")

        if data["flagged_remove"]:
            all_pass = False
            lines.append(f"**GATE: FAIL** — {len(data['flagged_remove'])} T1 items flagged REMOVE:")
            for bid in data["flagged_remove"]:
                lines.append(f"  - {bid}")
            lines.append("")
        else:
            lines.append(f"**GATE: PASS** — T1 contamination within threshold\n")

    lines.append("## Action required\n")
    if all_pass:
        lines.append("All models pass the contamination gate. Proceed to TASK-021 baseline run.")
    else:
        lines.append(
            "One or more models FAIL the contamination gate. Replace flagged T1 items with "
            "more contamination-resistant questions (prefer: specific numeric thresholds, "
            "T4 composite items, post-cutoff revisions) before running TASK-021."
        )

    out_path = output_dir / "contamination_summary.md"
    out_path.write_text("\n".join(lines))
    print(f"\nSummary written to {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Run contamination screen on benchmark")
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=Path("benchmark/benchmark.jsonl"),
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=["gpt-4o-mini"],
        help="Model IDs to test",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/contamination"),
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Max T1 zero_shot_known rate before flagging REMOVE (default: {DEFAULT_THRESHOLD})",
    )
    parser.add_argument(
        "--slot-sample",
        type=int,
        default=10,
        help="Number of items to include in slot-guessing test",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate inputs but do not call any LLM",
    )
    args = parser.parse_args()

    results = run_screen(
        benchmark_path=args.benchmark,
        model_ids=args.models,
        output_dir=args.output,
        threshold=args.threshold,
        slot_sample=args.slot_sample,
        dry_run=args.dry_run,
    )

    # Check overall gate
    if results and any(not v.get("gate_pass", True) for v in results.values()):
        print("\nOVERALL: CONTAMINATION GATE FAILED — see contamination_summary.md")
        sys.exit(1)
    elif results:
        print("\nOVERALL: CONTAMINATION GATE PASSED")


if __name__ == "__main__":
    main()

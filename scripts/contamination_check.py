"""
Extract distinctive sentences from key EMA source documents for training-data
contamination checks (TASK-009).

Output:
    docs/contamination_sentences.tsv  — (source_key, qa_id, sentence) table
    Prints up to N sentences per source, ready for manual Infini-gram search.

Usage:
    python scripts/contamination_check.py [--n 7] [--seed 42]

Infini-gram search (manual, open in browser):
    https://infini-gram.io/?index=v4_dolma-v1_7-sampling&query=<SENTENCE>

OLMoTrace (for OLMo 3 training data):
    https://olmotrace.allenai.org/
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

TARGET_SOURCES: list[tuple[str, str]] = [
    ("gmp_qa", "good-manufacturing-practice-good-distribution-practice-questions-answers"),
    ("quality_p1", "quality-medicines-questions-answers-part-1"),
    ("quality_p2", "quality-medicines-questions-answers-part-2"),
    ("clinical_pk", "clinical-pharmacology-pharmacokinetics-questions-answers"),
    ("bio_qa", "biological-medicinal-products"),
]


def _split_sentences(text: str) -> list[str]:
    """Split text on sentence boundaries, keeping only informative ones."""
    raw = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    return [
        s.strip()
        for s in raw
        if len(s.strip()) >= 80
        and any(c.isupper() for c in s[:30])
        and not s.strip().startswith("Rev.")
        and not s.strip().startswith("See ")
    ]


def extract(corpus_path: Path, n_per_source: int = 7, seed: int = 42) -> list[tuple[str, str, str]]:
    """Return list of (source_key, qa_id, sentence) for contamination searching."""
    random.seed(seed)
    records = [json.loads(line) for line in corpus_path.open(encoding="utf-8")]

    rows: list[tuple[str, str, str]] = []
    for key, kw in TARGET_SOURCES:
        matching = [r for r in records if kw in r.get("source_url", "")]
        if not matching:
            print(f"[WARN] No records found for {key} ({kw!r})", file=sys.stderr)
            continue

        sample = random.sample(matching, min(n_per_source * 3, len(matching)))
        collected = 0
        for rec in sample:
            sentences = _split_sentences(rec["answer"])
            # pick from middle of answer to avoid boilerplate headers/footers
            mid = sentences[1:-1] if len(sentences) > 2 else sentences
            for sent in mid:
                if collected >= n_per_source:
                    break
                rows.append((key, rec["qa_id"], sent))
                collected += 1
            if collected >= n_per_source:
                break

        print(f"{key}: extracted {collected} sentences from {len(matching)} records")

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=7, help="Sentences per source (default: 7)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "contamination_sentences.tsv")
    args = parser.parse_args()

    from config import CORPUS_PATH

    rows = extract(CORPUS_PATH, n_per_source=args.n, seed=args.seed)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["source_key", "qa_id", "sentence"])
        w.writerows(rows)

    print(f"\nWrote {len(rows)} sentences to {args.out}")
    print("\nNext steps:")
    print("  1. Open https://infini-gram.io/?index=v4_dolma-v1_7-sampling")
    print("     Paste each sentence into the search box and record count/presence.")
    print("  2. For OLMo 3 training data: https://olmotrace.allenai.org/")
    print("  3. Update docs/training_data_verification.md with findings.")


if __name__ == "__main__":
    main()

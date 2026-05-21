#!/usr/bin/env python3
"""
Validate benchmark/benchmark.jsonl against benchmark/SCHEMA.md rules.

Checks:
  1. All required fields present and non-empty
  2. bench_ids unique and correctly formatted (T1-NNN, T2-NNN, T3-NNN, T4-NNN)
  3. Type field is one of T1/T2/T3/T4
  4. gold_qa_ids are non-empty lists of strings
  5. paraphrases field present and non-empty
  6. gold_sources is a list of {"url": ..., "page": ...} objects
  7. Type distribution matches targets: T1=20, T2=10, T3=10, T4≥5
  8. gold_qa_ids exist in corpus (mini_corpus.jsonl or corpus.jsonl, whichever is available)
  9. T1 items: exactly 1 gold_qa_id
  10. T4 items: gold_qa_ids span ≥2 distinct source_urls (verified against corpus)

Exits non-zero on any failure.

Usage:
  python benchmark/validate_benchmark.py [--benchmark benchmark/benchmark.jsonl] [--corpus corpus/corpus.jsonl]
"""

import json
import sys
import re
import argparse
from pathlib import Path
from collections import Counter


REQUIRED_FIELDS = ["bench_id", "question", "paraphrases", "type", "gold_answer", "gold_qa_ids", "gold_sources", "topic_path"]
VALID_TYPES = {"T1", "T2", "T3", "T4"}
TYPE_TARGETS = {"T1": 20, "T2": 10, "T3": 10}
T4_MIN = 5
BENCH_ID_PATTERN = re.compile(r"^T[1-4]-\d{3}$")


def load_jsonl(path: Path) -> list[dict]:
    items = []
    with open(path) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"FAIL: JSON parse error on line {i} of {path}: {e}")
                sys.exit(1)
    return items


def validate(benchmark_path: Path, corpus_path: Path | None) -> bool:
    ok = True

    def fail(msg: str):
        nonlocal ok
        ok = False
        print(f"FAIL: {msg}")

    def warn(msg: str):
        print(f"WARN: {msg}")

    # Load benchmark
    if not benchmark_path.exists():
        fail(f"Benchmark file not found: {benchmark_path}")
        return False

    items = load_jsonl(benchmark_path)
    print(f"Loaded {len(items)} benchmark items from {benchmark_path}")

    # Load corpus for qa_id lookups
    corpus_qa_ids: dict[str, dict] = {}
    if corpus_path and corpus_path.exists():
        for r in load_jsonl(corpus_path):
            corpus_qa_ids[r["qa_id"]] = r
        print(f"Loaded {len(corpus_qa_ids)} corpus records from {corpus_path}")
    else:
        # Try fallback paths
        for fallback in [Path("corpus/corpus.jsonl"), Path("corpus/mini_corpus.jsonl")]:
            if fallback.exists():
                for r in load_jsonl(fallback):
                    corpus_qa_ids[r["qa_id"]] = r
                print(f"Loaded {len(corpus_qa_ids)} corpus records from {fallback} (fallback)")
                break
        else:
            warn("No corpus file found — skipping gold_qa_id existence checks")

    # 1. Required fields
    for item in items:
        bid = item.get("bench_id", "<missing>")
        for field in REQUIRED_FIELDS:
            if field not in item:
                fail(f"[{bid}] Missing required field: {field}")
            elif item[field] is None or item[field] == "" or item[field] == [] or item[field] == {}:
                fail(f"[{bid}] Required field '{field}' is empty")

    # 2. bench_id uniqueness and format
    bench_ids = [item.get("bench_id", "") for item in items]
    seen = set()
    for bid in bench_ids:
        if bid in seen:
            fail(f"Duplicate bench_id: {bid}")
        seen.add(bid)
        if not BENCH_ID_PATTERN.match(bid):
            fail(f"bench_id does not match expected pattern T[1-4]-NNN: '{bid}'")

    # 3. Type field
    for item in items:
        if item.get("type") not in VALID_TYPES:
            fail(f"[{item.get('bench_id')}] Invalid type: {item.get('type')!r}")

    # 4. gold_qa_ids
    for item in items:
        bid = item.get("bench_id", "")
        gids = item.get("gold_qa_ids", [])
        if not isinstance(gids, list) or len(gids) == 0:
            fail(f"[{bid}] gold_qa_ids must be a non-empty list")
        else:
            for gid in gids:
                if not isinstance(gid, str) or len(gid) == 0:
                    fail(f"[{bid}] gold_qa_ids contains non-string or empty entry: {gid!r}")
                if corpus_qa_ids and gid not in corpus_qa_ids:
                    fail(f"[{bid}] gold_qa_id '{gid}' not found in corpus")

    # 5. paraphrases
    for item in items:
        bid = item.get("bench_id", "")
        p = item.get("paraphrases", [])
        if not isinstance(p, list) or len(p) == 0:
            fail(f"[{bid}] paraphrases must be a non-empty list")
        elif len(p) < 1:
            warn(f"[{bid}] Only {len(p)} paraphrase(s); recommend ≥2")

    # 6. gold_sources
    for item in items:
        bid = item.get("bench_id", "")
        sources = item.get("gold_sources", [])
        if not isinstance(sources, list) or len(sources) == 0:
            fail(f"[{bid}] gold_sources must be a non-empty list")
        else:
            for s in sources:
                if not isinstance(s, dict):
                    fail(f"[{bid}] gold_sources entry is not an object: {s!r}")
                elif "url" not in s:
                    fail(f"[{bid}] gold_sources entry missing 'url' key: {s!r}")
                elif "page" not in s:
                    fail(f"[{bid}] gold_sources entry missing 'page' key: {s!r}")

    # 7. Type distribution
    type_counts = Counter(item.get("type") for item in items)
    print(f"\nType distribution: {dict(type_counts)}")
    for t, target in TYPE_TARGETS.items():
        if type_counts[t] != target:
            fail(f"Type {t} count is {type_counts[t]}, expected {target}")
    if type_counts["T4"] < T4_MIN:
        fail(f"T4 count is {type_counts['T4']}, minimum required is {T4_MIN}")
    else:
        print(f"  T4 count: {type_counts['T4']} (≥{T4_MIN} required) ✓")

    # 8. T1 items: exactly 1 gold_qa_id
    for item in items:
        if item.get("type") == "T1":
            gids = item.get("gold_qa_ids", [])
            if len(gids) != 1:
                fail(f"[{item.get('bench_id')}] T1 item must have exactly 1 gold_qa_id, found {len(gids)}")

    # 9. T4 items: gold_qa_ids span ≥2 distinct source_urls (from gold_sources)
    for item in items:
        if item.get("type") == "T4":
            bid = item.get("bench_id", "")
            sources = item.get("gold_sources", [])
            distinct_urls = set(s.get("url") for s in sources if isinstance(s, dict))
            if len(distinct_urls) < 2:
                # Also check via corpus
                gids = item.get("gold_qa_ids", [])
                if corpus_qa_ids:
                    corpus_urls = set(
                        corpus_qa_ids[gid]["source_url"]
                        for gid in gids
                        if gid in corpus_qa_ids
                    )
                    if len(corpus_urls) < 2:
                        fail(f"[{bid}] T4 item gold_qa_ids do not span ≥2 distinct source_urls (found {len(corpus_urls)})")
                else:
                    if len(distinct_urls) < 2:
                        warn(f"[{bid}] T4 item gold_sources has only {len(distinct_urls)} distinct URL(s); could not verify via corpus")

    # Summary
    print()
    total = len(items)
    if ok:
        print(f"✓ All checks passed — {total} benchmark items validated.")
    else:
        print(f"✗ Validation failed — {total} items checked, see FAIL messages above.")

    return ok


def main():
    parser = argparse.ArgumentParser(description="Validate benchmark.jsonl")
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=Path("benchmark/benchmark.jsonl"),
        help="Path to benchmark.jsonl",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=None,
        help="Path to corpus.jsonl (optional; falls back to mini_corpus.jsonl)",
    )
    args = parser.parse_args()

    success = validate(args.benchmark, args.corpus)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

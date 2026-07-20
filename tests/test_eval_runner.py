"""Unit tests for harness.eval.runner (pure parts of the R6 recipe×benchmark vehicle).

run_recipe_benchmark itself is runtime-only (Neo4j + model credentials); the
loading / data-shaping / grouping / summary pieces are verified offline against
the real shipped benchmark file.
"""

import json

import pytest

from harness.eval.runner import (
    BENCHMARK_PATH,
    group_by_type,
    load_benchmark,
    summarize,
    to_eval_data,
)


def test_load_shipped_benchmark_all_types_present():
    rows = load_benchmark(BENCHMARK_PATH)
    assert len(rows) == 45
    assert {r["type"] for r in rows} == {"T1", "T2", "T3", "T4"}
    assert all(r["question"] and r["gold_answer"] for r in rows)


def test_load_benchmark_type_filter_and_per_type_limit():
    rows = load_benchmark(BENCHMARK_PATH, types=["T1", "T3"], limit=2)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["type"]] = counts.get(r["type"], 0) + 1
    assert counts == {"T1": 2, "T3": 2}  # limit is per type, not global


def test_load_benchmark_empty_selection_raises(tmp_path):
    path = tmp_path / "bench.jsonl"
    path.write_text(json.dumps({"type": "T1", "question": "q", "gold_answer": "a"}) + "\n")
    with pytest.raises(ValueError):
        load_benchmark(path, types=["T4"])


def test_to_eval_data_shape():
    data = to_eval_data([{"type": "T1", "question": "Q?", "gold_answer": "G."}])
    assert data == [{"inputs": {"question": "Q?"}, "expectations": {"gold_answer": "G."}}]


def test_group_by_type_ordered_t1_to_t4():
    rows = [{"type": t, "question": "q", "gold_answer": "a"} for t in ("T3", "T1", "T4", "T1")]
    grouped = group_by_type(rows)
    assert list(grouped) == ["T1", "T3", "T4"]
    assert len(grouped["T1"]) == 2


def test_summarize_renders_per_type_metrics():
    class _Result:
        metrics = {"faithfulness/mean": 0.8}

    out = summarize({"T1": _Result(), "T2": object()})
    assert "T1: faithfulness/mean=0.800" in out
    assert "T2: (no metrics)" in out


def test_mean_scores_averages_numeric_and_skips_non_numeric():
    from harness.eval.runner import mean_scores

    means = mean_scores(
        [("faithfulness", "5"), ("faithfulness", 3), ("correctness", 4),
         ("gold_answer", None), ("note", "text")]
    )
    assert means == {"faithfulness_mean": 4.0, "correctness_mean": 4.0}


def test_group_by_type_includes_showcase_t5_after_t4():
    rows = [{"type": t, "question": "q", "gold_answer": "a"} for t in ("T5", "T1", "T4")]
    grouped = group_by_type(rows)
    assert list(grouped) == ["T1", "T4", "T5"]  # T5 groups cleanly, not "unknown"
    assert "unknown" not in grouped


def test_showcase_benchmark_file_loads_as_t5():
    from pathlib import Path

    from harness.eval.runner import BENCHMARK_PATH

    path = Path(BENCHMARK_PATH).parent / "showcase.jsonl"
    rows = load_benchmark(path)
    assert rows and all(r["type"] == "T5" for r in rows)
    assert all(r["question"] and r["gold_answer"] for r in rows)
    assert all(r["gold_sources"] for r in rows)  # every showcase item names its anchor

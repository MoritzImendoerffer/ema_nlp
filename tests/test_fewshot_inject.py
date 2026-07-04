"""Tests for harness/fewshot_inject.py — get_fewshot_context()."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

import numpy as np

from harness.fewshot_inject import get_fewshot_context

# ---------------------------------------------------------------------------
# Minimal mock of QueryCache
# ---------------------------------------------------------------------------

@dataclass
class _MockEntry:
    run_id: str
    question_text: str
    answer_summary: str
    rating: float | None
    cited_qa_ids: list[str] = field(default_factory=list)


def _make_cache(n_rated: int) -> MagicMock:
    """Return a QueryCache mock whose get_similar returns n_rated entries."""
    entries = [
        (
            _MockEntry(
                run_id=f"run-{i}",
                question_text=f"What is rule {i}?",
                answer_summary=f"Answer {i}.",
                rating=5.0,
                cited_qa_ids=[f"qa-{i}"],
            ),
            0.92 - i * 0.01,
        )
        for i in range(n_rated)
    ]
    cache = MagicMock()
    cache.get_similar.return_value = entries
    return cache


_QUERY_VEC = np.zeros(1024, dtype=np.float32)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_fewshot_suppressed_zero_entries():
    cache = _make_cache(0)
    result = get_fewshot_context(_QUERY_VEC, cache, k=3, min_rating=4.0, min_examples=3)
    assert result is None


def test_fewshot_suppressed_two_entries():
    cache = _make_cache(2)
    result = get_fewshot_context(_QUERY_VEC, cache, k=3, min_rating=4.0, min_examples=3)
    assert result is None


def test_fewshot_returns_string_three_entries():
    cache = _make_cache(3)
    result = get_fewshot_context(_QUERY_VEC, cache, k=3, min_rating=4.0, min_examples=3)
    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0
    assert "What is rule 0?" in result


def test_fewshot_cache_none():
    result = get_fewshot_context(_QUERY_VEC, None, k=3, min_rating=4.0, min_examples=3)
    assert result is None

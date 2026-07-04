"""
Runtime few-shot injection from rated past interactions.

Fetches the top-k rated past interactions from the query cache and formats them
as a few-shot prefix injected into the workflow system prompt before each run.
Each example is the question + answer + cited sources stored in the cache.

Injection is disabled when:
- Fewer than *min_examples* rated interactions exist in the cache.
- cache is None.
- k=0 or min_rating is too restrictive to find any candidates.

Usage::

    from harness.fewshot_inject import get_fewshot_context
    import numpy as np

    context = get_fewshot_context(query_vec, cache, k=3, min_rating=4)
    # context is None  → no injection (not enough rated examples)
    # context is str   → pass as few_shot_context to AgentWorkflowAdapter.ainvoke()
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

_FEW_SHOT_HEADER = """\
Below are {n} example(s) of well-rated past interactions that are similar to \
the current question.  Use them to guide your reasoning and answer.
"""

_EXAMPLE_TEMPLATE = """\
--- Example {i} (rating {rating:.0f}/5) ---
Question: {question}
Answer: {answer}
Cited sources: {cited}
"""


def get_fewshot_context(
    query_vec: np.ndarray,
    cache: Any,
    *,
    k: int = 3,
    min_rating: float = 4.0,
    min_examples: int = 1,
) -> str | None:
    """
    Build a few-shot prefix from top-k rated cache entries similar to query_vec.

    Args:
        query_vec:     Embedding vector for the current question (shape (1024,)).
        cache:         QueryCache instance.
        k:             Maximum number of examples to include.
        min_rating:    Minimum rating threshold (default 4 out of 5).
        min_examples:  Suppress injection if fewer than this many candidates exist
                       (tunable per recipe via ``FewshotPolicy.min_examples``; must be
                       ≤ k to be reachable — ``get_similar`` returns at most k hits).

    Returns:
        Formatted few-shot string or None if injection is suppressed.
    """
    if cache is None:
        return None

    hits = cache.get_similar(query_vec, k=k, min_rating=min_rating)
    if len(hits) < min_examples:
        log.debug(
            "Few-shot injection suppressed: found %d/%d rated examples (min_rating≥%.1f)",
            len(hits),
            min_examples,
            min_rating,
        )
        return None

    blocks: list[str] = []
    for i, (entry, _sim) in enumerate(hits, 1):
        cited_str = ", ".join(entry.cited_qa_ids) if entry.cited_qa_ids else "none"
        blocks.append(
            _EXAMPLE_TEMPLATE.format(
                i=i,
                rating=entry.rating or 0,
                question=entry.question_text,
                answer=entry.answer_summary,
                cited=cited_str,
            )
        )

    header = _FEW_SHOT_HEADER.format(n=len(blocks))
    return header + "\n".join(blocks)

"""
Runtime few-shot injection for the ReActRAGAgent (TASK-027.7).

Fetches the top-k rated past interactions from the query cache and formats
them as a few-shot prefix that is injected into the ReActAgent system prompt
before each run.  Phoenix is queried to enrich the examples with trajectory
steps (tool calls) when available; falls back to question+answer format if
Phoenix is unreachable or the trajectory was not stored.

Injection is disabled when:
- Fewer than *min_examples* rated interactions exist in the cache.
- cache is None.
- k=0 or min_rating is too restrictive to find any candidates.

Usage::

    from harness.fewshot_inject import get_fewshot_context
    import numpy as np

    context = get_fewshot_context(query_vec, cache, k=3, min_rating=4)
    # context is None  → no injection (not enough rated examples)
    # context is str   → prepend to agent system prompt

    agent = ReActRAGAgent(index, fewshot_context=context)
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

PHOENIX_URL = "http://localhost:6006"
PHOENIX_PROJECT = "default"

_FEW_SHOT_HEADER = """\
Below are {n} example(s) of well-rated past interactions that are similar to \
the current question.  Use them to guide your reasoning and tool-call strategy.
"""

_EXAMPLE_TEMPLATE = """\
--- Example {i} (rating {rating:.0f}/5) ---
Question: {question}
{trajectory_block}Answer: {answer}
Cited sources: {cited}
"""


def get_fewshot_context(
    query_vec: np.ndarray,
    cache: Any,
    *,
    k: int = 3,
    min_rating: float = 4.0,
    min_examples: int = 3,
    phoenix_url: str = PHOENIX_URL,
    project: str = PHOENIX_PROJECT,
) -> str | None:
    """
    Build a few-shot prefix from top-k rated cache entries similar to query_vec.

    Args:
        query_vec:     Embedding vector for the current question (shape (1024,)).
        cache:         QueryCache instance.
        k:             Maximum number of examples to include.
        min_rating:    Minimum rating threshold (default 4 out of 5).
        min_examples:  Suppress injection if fewer than this many candidates exist.
        phoenix_url:   Phoenix server base URL (for trajectory enrichment).
        project:       Phoenix project identifier.

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
        trajectory = _fetch_trajectory(entry.run_id, phoenix_url=phoenix_url, project=project)
        trajectory_block = _format_trajectory(trajectory) if trajectory else ""
        cited_str = ", ".join(entry.cited_qa_ids) if entry.cited_qa_ids else "none"
        blocks.append(
            _EXAMPLE_TEMPLATE.format(
                i=i,
                rating=entry.rating or 0,
                question=entry.question_text,
                trajectory_block=trajectory_block,
                answer=entry.answer_summary,
                cited=cited_str,
            )
        )

    header = _FEW_SHOT_HEADER.format(n=len(blocks))
    return header + "\n".join(blocks)


def _fetch_trajectory(run_id: str, *, phoenix_url: str, project: str) -> list[dict]:
    """
    Fetch trajectory steps for *run_id* from Phoenix.

    Looks for root spans annotated with run_id, then retrieves their TOOL child spans.
    Returns an empty list if Phoenix is unreachable or no data is found.
    """
    try:
        from datetime import UTC, datetime, timedelta

        from phoenix.client import Client as PhoenixClient

        client = PhoenixClient(base_url=phoenix_url)
        # Fetch recent annotated root spans and find the one with our run_id
        root_spans = client.spans.get_spans(
            project_identifier=project,
            parent_id="null",
            limit=200,
            start_time=datetime.now(UTC) - timedelta(days=30),
        )
        target_span_id: str | None = None
        for span in root_spans:
            anns = client.spans.get_span_annotations(
                spans=[span],
                project_identifier=project,
                include_annotation_names=["user_rating"],
            )
            for ann in anns:
                meta = (ann.get("metadata") if isinstance(ann, dict) else getattr(ann, "metadata", {})) or {}
                if meta.get("run_id") == run_id:
                    ctx = (
                        span.get("context")
                        if isinstance(span, dict)
                        else getattr(span, "context", None)
                    )
                    target_span_id = (
                        ctx.get("span_id") if isinstance(ctx, dict) else getattr(ctx, "span_id", None)
                    )
                    break
            if target_span_id:
                break

        if not target_span_id:
            return []

        child_spans = client.spans.get_spans(
            project_identifier=project,
            parent_id=target_span_id,
            span_kind="TOOL",
            limit=50,
        )
        steps: list[dict] = []
        for cs in child_spans:
            attrs = (cs.get("attributes") if isinstance(cs, dict) else getattr(cs, "attributes", {})) or {}
            steps.append(
                {
                    "tool_name": attrs.get("tool.name") or "?",
                    "tool_kwargs": attrs.get("input.value") or "",
                    "tool_output": (attrs.get("output.value") or "")[:200],
                }
            )
        return steps

    except Exception as exc:
        log.debug("Trajectory fetch from Phoenix failed (run_id=%s): %s", run_id, exc)
        return []


def _format_trajectory(steps: list[dict]) -> str:
    if not steps:
        return ""
    lines: list[str] = ["Trajectory:\n"]
    for i, step in enumerate(steps, 1):
        tool = step.get("tool_name", "?")
        kwargs = step.get("tool_kwargs", "")
        output = step.get("tool_output", "")
        lines.append(f"  Step {i}: {tool}({kwargs[:80]})\n")
        if output:
            lines.append(f"    → {output[:120]}\n")
    return "".join(lines) + "\n"

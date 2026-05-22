"""
Shared state schema for all LangGraph pipeline strategies (LG-001).

PipelineState is the single TypedDict used by the build_pipeline() factory and
all pipeline node functions.  Each node reads from it and returns a partial update
dict (only the keys the node modifies); LangGraph merges the update into the state
using last-write-wins semantics.

Usage::

    from harness.chains.pipeline_state import PipelineState, make_initial_state

    state = make_initial_state("What is the AI for NDMA?")
    # ... pass to a compiled LangGraph graph
"""

from __future__ import annotations

from typing import TypedDict

from langchain_core.documents import Document


class PipelineState(TypedDict):
    # ── Input ──────────────────────────────────────────────────────────────────
    question: str
    few_shot_context: str          # pre-injected few-shot examples; empty = disabled

    # ── Retrieval ─────────────────────────────────────────────────────────────
    docs: list[Document]

    # ── Optional summarization ────────────────────────────────────────────────
    summary: str                   # empty = summarization not run

    # ── Generation ────────────────────────────────────────────────────────────
    answer_text: str
    cited_qa_ids: list[str]
    trajectory: list[dict]         # ReAct: tool call steps; pipeline: node steps
    prompt_strategy: str

    # ── Review / correction loops ─────────────────────────────────────────────
    review_score: float            # 0.0 = review not run; else judge score in [0, 1]
    review_feedback: str           # judge reason string
    rewrite_cycle: int             # number of query rewrites performed (CRAG)
    review_cycle: int              # number of times review node has run
    grade: str                     # "sufficient" | "insufficient" | ""


def make_initial_state(
    question: str,
    *,
    few_shot_context: str = "",
) -> PipelineState:
    """Return a fresh PipelineState with all fields at their zero values."""
    return PipelineState(
        question=question,
        few_shot_context=few_shot_context,
        docs=[],
        summary="",
        answer_text="",
        cited_qa_ids=[],
        trajectory=[],
        prompt_strategy="",
        review_score=0.0,
        review_feedback="",
        rewrite_cycle=0,
        review_cycle=0,
        grade="",
    )

"""Shared Corrective-RAG (CRAG) primitives: relevance grading + query rewrite.

CRAG treats retrieval as a step that can be *graded and corrected* before
generation: score each retrieved passage for relevance, and if the set doesn't
cover the question, rewrite the query toward the missing facts and retry
(bounded). Reference: Yan et al., 2024, "Corrective Retrieval Augmented
Generation" (arXiv:2401.15884).

These pure pieces (the grading rubric, the JSON parser, the sufficiency rule, the
rewrite prompt, and the chat-message builders) are the single source of truth for
the CRAG technique. They are consumed by the ``corrective_search`` agent tool
(``harness/tools/corrective_search.py``). They make no LLM/retriever calls and are
unit-testable offline; callers supply the LLM and run the loop.
"""

from __future__ import annotations

import json
import logging
import re

from llama_index.core.llms import ChatMessage, MessageRole

log = logging.getLogger(__name__)

MAX_CYCLES = 2  # max retrieve-rewrite iterations before accepting the best-so-far

GRADE_SYSTEM = """\
You are a relevance grader for EMA regulatory Q&A retrieval.

Score each retrieved document on a 0–2 scale:
  0 — not relevant; shares keywords but doesn't address the question
  1 — partially relevant; addresses the topic but misses key details
  2 — fully relevant; directly answers the question with specific information

Also list any facts the question requires that are absent from ALL retrieved documents.

Respond with ONLY valid JSON in this exact format:
{
  "per_doc": [
    {"qa_id": "<qa_id>", "score": <0|1|2>},
    ...
  ],
  "missing_facts": ["<description of missing fact>", ...]
}

If all necessary facts are covered (score=2 exists and nothing is missing), set missing_facts to [].
"""

REWRITE_SYSTEM = """\
You are a query rewriter for EMA regulatory document retrieval.
The original query did not retrieve sufficient documents.

Rewrite the query to target the specific missing facts listed below.
Use precise EMA terminology. Return only the rewritten query — nothing else.
"""


def parse_grade(raw: str) -> tuple[list[dict], list[str]]:
    """Parse grader JSON response. Returns ``(per_doc, missing_facts)``.

    Tolerant of markdown code fences and surrounding prose; on a parse failure
    returns ``([], ["(parse error — treating as insufficient)"])`` so the caller
    treats an unparseable grade as "not yet sufficient" (fail-safe toward another
    corrective cycle rather than a falsely-confident answer).
    """
    # Strip markdown code fences
    raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    # Extract JSON object: take from first { to last }
    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        raw = raw[first_brace : last_brace + 1]
    try:
        data = json.loads(raw)
        per_doc: list[dict] = data.get("per_doc", [])
        missing_facts: list[str] = data.get("missing_facts", [])
        return per_doc, missing_facts
    except (json.JSONDecodeError, KeyError):
        log.warning("CRAG: could not parse grader JSON: %s", raw[:200])
        return [], ["(parse error — treating as insufficient)"]


def is_sufficient(per_doc: list[dict], missing_facts: list[str]) -> bool:
    """Grade is sufficient when at least one doc scores 2 AND missing_facts is empty."""
    has_excellent = any(d.get("score", 0) == 2 for d in per_doc)
    return has_excellent and not missing_facts


def grade_messages(question: str, context_str: str) -> list[ChatMessage]:
    """Build the chat messages that ask the LLM to grade ``context_str`` vs ``question``."""
    return [
        ChatMessage(role=MessageRole.SYSTEM, content=GRADE_SYSTEM),
        ChatMessage(
            role=MessageRole.USER,
            content=f"Question: {question}\n\nRetrieved documents:\n{context_str}",
        ),
    ]


def rewrite_messages(question: str, missing_facts: list[str]) -> list[ChatMessage]:
    """Build the chat messages that ask the LLM to rewrite ``question`` toward the gaps."""
    missing_str = "\n".join(f"- {f}" for f in missing_facts) or "(unspecified)"
    return [
        ChatMessage(role=MessageRole.SYSTEM, content=REWRITE_SYSTEM),
        ChatMessage(
            role=MessageRole.USER,
            content=(
                f"Original query: {question}\n\n"
                f"Missing facts that the retrieved documents do not cover:\n{missing_str}"
            ),
        ),
    ]


def grade_note(cycles: int, per_doc: list[dict], missing_facts: list[str]) -> str:
    """A short, honest suffix describing the corrective outcome for the agent/trace.

    Tells the agent how many rewrite cycles ran, the best relevance achieved, and
    any residual missing facts — so a still-incomplete result is surfaced, not hidden.
    """
    best = max((d.get("score", 0) for d in per_doc), default=0)
    cyc = f"{cycles} rewrite cycle(s)"
    if missing_facts:
        miss = "; ".join(missing_facts[:3])
        return f"\n\n[corrective_search: {cyc}; best relevance {best}/2; STILL MISSING: {miss}]"
    return f"\n\n[corrective_search: {cyc}; passages judged sufficient (best relevance {best}/2)]"

"""
A4 — LLM reranker with a generic relevance prompt (A3 control).

Identical architecture to a3_reranker.py but uses a generic
"is this passage relevant?" prompt instead of the SME-authored rubric.

A3 vs A4 comparison isolates the value of SME rubric authorship:
- If A3 beats A4 → the rubric matters.
- If they tie → generic reranking already captures most of the gain.
"""

from __future__ import annotations

import logging

import anthropic

from harness.retrieve import RetrievalResult

log = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_DEFAULT_MAX_CHUNKS = 5

_GENERIC_PROMPT = """\
You are a relevance assessor for a regulatory Q&A retrieval system.

Score the retrieved Q&A on a 0–2 scale:
- 2: Directly and specifically addresses what the query asks.
- 1: Related to the topic but does not directly answer the query.
- 0: Not relevant — shares keywords but does not help answer the query.

Respond with ONLY the integer score (0, 1, or 2) — no explanation.

Query: {query}

Retrieved Q&A:
{chunk_text}
"""


def _score_chunk(
    client: anthropic.Anthropic,
    model: str,
    query: str,
    chunk_text: str,
) -> float:
    """Score a single chunk 0–2 using a generic relevance prompt."""
    prompt = _GENERIC_PROMPT.format(query=query, chunk_text=chunk_text)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=4,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = next((b.text for b in response.content if hasattr(b, "text")), "").strip()
        return float(raw[0]) if raw and raw[0] in "012" else 0.0
    except Exception as exc:
        log.warning("Reranker API error: %s", exc)
        return 0.0


def rerank(
    results: list[RetrievalResult],
    query: str,
    index,
    *,
    model: str = _DEFAULT_MODEL,
    max_chunks: int = _DEFAULT_MAX_CHUNKS,
) -> list[RetrievalResult]:
    """
    Rerank *results* by generic LLM relevance score.

    Same interface as a3_reranker.rerank() — drop-in swap.
    """
    client = anthropic.Anthropic()

    to_score = results[:max_chunks]
    remainder = results[max_chunks:]

    scored: list[tuple[float, RetrievalResult]] = []
    for qa_id, score, meta in to_score:
        node = index.docstore.get_node(qa_id)
        chunk_text = node.text if node else "Q: (missing)\nA: (missing)"
        llm_score = _score_chunk(client, model, query, chunk_text)
        scored.append((llm_score, (qa_id, score, meta)))
        log.debug("A4 score %s → %.0f", qa_id, llm_score)

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored] + remainder

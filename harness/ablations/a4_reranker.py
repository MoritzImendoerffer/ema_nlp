"""
A4 — LLM reranker with a generic relevance prompt (A3 control).

Identical architecture to a3_reranker.py but uses a generic
"is this passage relevant?" prompt instead of the SME-authored rubric.

A3 vs A4 comparison isolates the value of SME rubric authorship:
- If A3 beats A4 → the rubric matters.
- If they tie → generic reranking already captures most of the gain.

Two interfaces:
  rerank()                     — tuple-based (RetrievalResult list); used by run_eval.py
  GenericRerankerPostprocessor — LlamaIndex BaseNodePostprocessor; produces Phoenix spans
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import NodeWithScore, QueryBundle
from pydantic import Field

from harness.retrieve import RetrievalResult

log = logging.getLogger(__name__)

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


def _score_chunk(llm: Any, query: str, chunk_text: str) -> float:
    """Score a single chunk 0–2 using a generic relevance prompt."""
    from llama_index.core.llms import ChatMessage, MessageRole

    prompt = _GENERIC_PROMPT.format(query=query, chunk_text=chunk_text)
    try:
        response = llm.chat([ChatMessage(role=MessageRole.USER, content=prompt)])
        raw = (response.message.content or "").strip()
        return float(raw[0]) if raw and raw[0] in "012" else 0.0
    except Exception as exc:
        log.warning("Reranker API error: %s", exc)
        return 0.0


def rerank(
    results: list[RetrievalResult],
    query: str,
    index: Any,
    *,
    llm: Any = None,
    max_chunks: int = _DEFAULT_MAX_CHUNKS,
) -> list[RetrievalResult]:
    """
    Rerank *results* by generic LLM relevance score.

    Same interface as a3_reranker.rerank() — drop-in swap.

    Args:
        results:    Retrieval results from harness.retrieve.retrieve().
        query:      The original query string.
        index:      VectorStoreIndex — used to fetch node text.
        llm:        LlamaIndex LLM; uses get_llm('reranker') if None.
        max_chunks: Maximum number of chunks to score (cost cap).
    """
    if llm is None:
        from harness.llms import get_llm
        llm = get_llm("reranker")

    to_score = results[:max_chunks]
    remainder = results[max_chunks:]

    scored: list[tuple[float, RetrievalResult]] = []
    for qa_id, score, meta in to_score:
        node = index.docstore.get_node(qa_id)
        chunk_text = node.text if node else "Q: (missing)\nA: (missing)"
        llm_score = _score_chunk(llm, query, chunk_text)
        scored.append((llm_score, (qa_id, score, meta)))
        log.debug("A4 score %s → %.0f", qa_id, llm_score)

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored] + remainder


class GenericRerankerPostprocessor(BaseNodePostprocessor):
    """LlamaIndex NodePostprocessor wrapping the A4 generic reranker.

    Usage::

        from harness.ablations.a4_reranker import GenericRerankerPostprocessor
        postprocessor = GenericRerankerPostprocessor(max_chunks=5)
        reranked = postprocessor.postprocess_nodes(nodes, query_str="NDMA limit")
    """

    max_chunks: int = Field(default=_DEFAULT_MAX_CHUNKS)

    @classmethod
    def class_name(cls) -> str:
        return "GenericRerankerPostprocessor"

    def _postprocess_nodes(
        self,
        nodes: list[NodeWithScore],
        query_bundle: Optional[QueryBundle] = None,
    ) -> list[NodeWithScore]:
        if not nodes:
            return nodes

        query_str = query_bundle.query_str if query_bundle else ""
        from harness.llms import get_llm
        llm = get_llm("reranker")

        to_score = nodes[:self.max_chunks]
        remainder = nodes[self.max_chunks:]

        scored: list[tuple[float, NodeWithScore]] = []
        for nws in to_score:
            llm_score = _score_chunk(llm, query_str, nws.node.text)
            scored.append((llm_score, nws))
            log.debug("A4 (postprocessor) score %s → %.0f", nws.node.node_id, llm_score)

        scored.sort(key=lambda x: x[0], reverse=True)
        return [nws for _, nws in scored] + remainder

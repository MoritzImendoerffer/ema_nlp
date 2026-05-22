"""
A3 — LLM reranker using the SME-authored relevance rubric.

Calls the 'reranker' role LLM (via get_llm('reranker') — configured in
models.yaml) to score each retrieved chunk against the SME relevance rubric
(harness/prompts/relevance_rubric_sme.md), then re-orders results by score.

Cost budget: one LLM call per chunk. Use max_chunks to cap spend.

Two interfaces:
  rerank()                — tuple-based (RetrievalResult list); used by run_eval.py
  SMERerankerPostprocessor — LlamaIndex BaseNodePostprocessor; produces Phoenix spans
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import NodeWithScore, QueryBundle
from pydantic import Field

from harness.retrieve import RetrievalResult

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent
_RUBRIC_PATH = REPO_ROOT / "harness" / "prompts" / "relevance_rubric_sme.md"
_DEFAULT_MAX_CHUNKS = 5


def _load_rubric(path: Path = _RUBRIC_PATH) -> str:
    return path.read_text(encoding="utf-8")


def _score_chunk(llm: Any, query: str, chunk_text: str, rubric: str) -> float:
    """Score a single chunk 0–2 against the rubric. Returns 0.0 on error."""
    from llama_index.core.llms import ChatMessage, MessageRole

    prompt = (
        f"{rubric}\n\n"
        f"---\n\n"
        f"Query: {query}\n\n"
        f"Retrieved Q&A:\n{chunk_text}\n\n"
        f"Score this retrieved Q&A using the rubric above (0, 1, or 2). "
        f"Respond with ONLY the integer score — no explanation."
    )
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
    rubric_path: Path = _RUBRIC_PATH,
) -> list[RetrievalResult]:
    """
    Rerank *results* by LLM relevance score (SME rubric).

    Args:
        results:    Retrieval results from harness.retrieve.retrieve().
        query:      The original query string.
        index:      VectorStoreIndex — used to fetch node text.
        llm:        LlamaIndex LLM; uses get_llm('reranker') if None.
        max_chunks: Maximum number of chunks to score (cost cap).
        rubric_path: Path to the SME relevance rubric markdown file.

    Returns:
        Results re-ordered by LLM score descending. Unscored chunks (beyond
        max_chunks) are appended after scored ones, preserving their original order.
    """
    if llm is None:
        from harness.llms import get_llm
        llm = get_llm("reranker")

    rubric = _load_rubric(rubric_path)

    to_score = results[:max_chunks]
    remainder = results[max_chunks:]

    scored: list[tuple[float, RetrievalResult]] = []
    for qa_id, score, meta in to_score:
        node = index.docstore.get_node(qa_id)
        chunk_text = node.text if node else "Q: (missing)\nA: (missing)"
        llm_score = _score_chunk(llm, query, chunk_text, rubric)
        scored.append((llm_score, (qa_id, score, meta)))
        log.debug("A3 score %s → %.0f", qa_id, llm_score)

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored] + remainder


class SMERerankerPostprocessor(BaseNodePostprocessor):
    """LlamaIndex NodePostprocessor wrapping the A3 SME reranker.

    Each call to postprocess_nodes() produces a distinct Phoenix span so the
    reranking step is separately traceable.

    Usage::

        from harness.ablations.a3_reranker import SMERerankerPostprocessor
        postprocessor = SMERerankerPostprocessor(max_chunks=5)
        reranked = postprocessor.postprocess_nodes(nodes, query_str="NDMA limit")
    """

    max_chunks: int = Field(default=_DEFAULT_MAX_CHUNKS)
    rubric_path: str = Field(default=str(_RUBRIC_PATH))

    @classmethod
    def class_name(cls) -> str:
        return "SMERerankerPostprocessor"

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
        rubric = _load_rubric(Path(self.rubric_path))

        to_score = nodes[:self.max_chunks]
        remainder = nodes[self.max_chunks:]

        scored: list[tuple[float, NodeWithScore]] = []
        for nws in to_score:
            llm_score = _score_chunk(llm, query_str, nws.node.text, rubric)
            scored.append((llm_score, nws))
            log.debug("A3 (postprocessor) score %s → %.0f", nws.node.node_id, llm_score)

        scored.sort(key=lambda x: x[0], reverse=True)
        return [nws for _, nws in scored] + remainder

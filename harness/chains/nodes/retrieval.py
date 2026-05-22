"""
Retrieval node for LangGraph pipelines (LG-001).

Thin adapter that calls EMARetriever.invoke() and stores the result in
PipelineState["docs"].  EMARetriever wraps the LlamaIndex FAISS+BM25 index
and remains the single retrieval entry point regardless of which pipeline
strategy is active.

Usage::

    from harness.chains.nodes.retrieval import build_retrieval_node
    from harness.chains.retriever import EMARetriever

    retrieval_node = build_retrieval_node(retriever)
    update = retrieval_node(state)   # returns {"docs": [...]}
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from langchain_core.documents import Document

from harness.chains.pipeline_state import PipelineState

log = logging.getLogger(__name__)


def build_retrieval_node(retriever: Any) -> Callable[[PipelineState], dict[str, Any]]:
    """
    Build a retrieval node that calls *retriever*.invoke(question).

    Args:
        retriever: Any object with an `.invoke(query: str) -> list[Document]`
                   method — typically an EMARetriever instance.

    Returns:
        A node function compatible with LangGraph StateGraph.
        Signature: (state: PipelineState) -> {"docs": list[Document]}
    """
    def retrieval_node(state: PipelineState) -> dict[str, Any]:
        question = state["question"]
        docs: list[Document] = retriever.invoke(question)
        log.debug("retrieval_node: %d docs for %r", len(docs), question[:60])
        return {"docs": docs}

    return retrieval_node

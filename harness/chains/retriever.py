"""
LangChain BaseRetriever adapter wrapping the LlamaIndex-backed EMA retrieval stack.

The persisted FAISS+BM25 index (built by harness.embed) is reused without
re-indexing.  EMARetriever translates between LlamaIndex's internal result
format (qa_id, score, metadata) and LangChain's Document objects.

Usage::

    from harness.embed import build_index
    from harness.retrieve import RetrievalConfig
    from harness.chains.retriever import EMARetriever, make_retriever

    index = build_index(corpus_path, index_dir)

    # Simple flat retrieval (default):
    retriever = EMARetriever(index=index, mode="hybrid", k=10)

    # Recursive retrieval (follows cross_refs automatically):
    cfg = RetrievalConfig(strategy="recursive", mode="hybrid", k=10)
    retriever = make_retriever(cfg, index)

    # Standard LangChain retrieval
    docs = retriever.invoke("What is the AI limit for NDMA?")

    # Agent helper methods
    cross_refs = retriever.get_cross_refs("some-qa-id")
    filtered   = retriever.filter_by_topic(docs, "genotoxic")
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForRetrieverRun,
    CallbackManagerForRetrieverRun,
)
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, PrivateAttr

from harness.embed import follow_cross_refs as _follow_cross_refs, get_node_by_id
from harness.retrieve import (
    RetrievalConfig,
    RetrievalStrategyId,
    RetrieverMode,
    retrieve_with_config,
)

log = logging.getLogger(__name__)


class EMARetriever(BaseRetriever):
    """
    LangChain retriever backed by the LlamaIndex EMA FAISS+BM25 index.

    Supports all retrieval modes via ``mode``:
        - "dense"  — vector similarity only
        - "bm25"   — BM25 keyword only
        - "hybrid" — Reciprocal Rank Fusion of dense + BM25 (default)

    And all retrieval strategies via ``retrieval_strategy``:
        - "flat"         — standard flat retrieval (default)
        - "recursive"    — flat + automatic cross_ref expansion
        - "hierarchical" — page-level → Q&A-level drill-down

    Each returned Document carries the full node metadata so downstream
    chains and agents can access qa_id, score, topic_path, cross_refs, etc.

    Prefer using ``make_retriever(config, index)`` for config-driven construction.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    index: Any
    mode: RetrieverMode = "hybrid"
    k: int = 10
    retrieval_strategy: RetrievalStrategyId = "flat"
    recursive_max_hops: int = 1
    hier_index: Any = None        # required when retrieval_strategy == "hierarchical"
    hier_top_doc_k: int = 5

    _config: RetrievalConfig = PrivateAttr()

    def model_post_init(self, __context: Any) -> None:
        from harness.retrieve import HierarchicalConfig, RecursiveConfig
        self._config = RetrievalConfig(
            strategy=self.retrieval_strategy,
            mode=self.mode,
            k=self.k,
            recursive=RecursiveConfig(max_hops=self.recursive_max_hops),
            hierarchical=HierarchicalConfig(top_doc_k=self.hier_top_doc_k),
        )

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        results = retrieve_with_config(self._config, self.index, query, hier_index=self.hier_index)
        return self._results_to_docs(results)

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: AsyncCallbackManagerForRetrieverRun,
    ) -> list[Document]:
        results = retrieve_with_config(self._config, self.index, query, hier_index=self.hier_index)
        return self._results_to_docs(results)

    def _results_to_docs(self, results: list) -> list[Document]:
        """Convert (qa_id, score, meta) triples to LangChain Documents with node text."""
        docs = []
        for qa_id, score, meta in results:
            node = get_node_by_id(self.index, qa_id)
            page_content = node.text if node is not None else f"[qa_id: {qa_id}]"
            docs.append(
                Document(
                    page_content=page_content,
                    metadata={**meta, "qa_id": qa_id, "score": score},
                )
            )
        return docs

    # ------------------------------------------------------------------
    # Agent helper methods — used directly by LangGraph tool nodes
    # ------------------------------------------------------------------

    def get_cross_refs(self, qa_id: str) -> list[Document]:
        """Return Documents for all qa_ids cross-referenced by *qa_id*."""
        nodes = _follow_cross_refs(self.index, qa_id)
        docs = []
        for node in nodes:
            meta = dict(node.metadata)
            ref_id = meta.get("qa_id", node.node_id)
            docs.append(
                Document(
                    page_content=node.text,
                    metadata={**meta, "qa_id": ref_id, "score": 1.0, "retrieval_type": "cross_ref"},
                )
            )
        return docs

    def filter_by_topic(self, docs: list[Document], topic: str) -> list[Document]:
        """
        Return the subset of *docs* whose topic_path or source_url contains *topic*
        (case-insensitive substring match).
        """
        topic_lower = topic.lower()
        filtered = [
            d for d in docs
            if topic_lower in (d.metadata.get("topic_path") or "").lower()
            or topic_lower in (d.metadata.get("source_url") or "").lower()
        ]
        log.debug("filter_by_topic(%r): %d/%d docs retained", topic, len(filtered), len(docs))
        return filtered


def make_retriever(
    config: RetrievalConfig,
    index: Any,
    *,
    hier_index: Any = None,
) -> EMARetriever:
    """
    Build an EMARetriever from a RetrievalConfig.

    This is the preferred factory for constructing retrievers in eval scripts
    and the interactive app, ensuring all code paths use the same configuration.

    Args:
        config:     RetrievalConfig (from YAML or constructed in code).
        index:      Flat VectorStoreIndex built by harness.embed.build_index.
        hier_index: Hierarchical VectorStoreIndex (required for strategy='hierarchical').

    Returns:
        Configured EMARetriever ready for use in LCEL chains, LangGraph agents,
        or direct .invoke() calls.

    Example::

        from harness.retrieve import RetrievalConfig
        from harness.chains.retriever import make_retriever

        cfg = RetrievalConfig(strategy="recursive", mode="hybrid", k=10)
        retriever = make_retriever(cfg, index)
        docs = retriever.invoke("What is the AI for NDMA?")
    """
    return EMARetriever(
        index=index,
        mode=config.mode,
        k=config.k,
        retrieval_strategy=config.strategy,
        recursive_max_hops=config.recursive.max_hops,
        hier_index=hier_index,
        hier_top_doc_k=config.hierarchical.top_doc_k,
    )

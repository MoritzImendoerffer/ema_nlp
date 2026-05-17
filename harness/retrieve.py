"""
Retrieval façade for the EMA Q&A harness.

Three modes, selectable at call time:
  "dense"  (A0)  — VectorStoreIndex similarity search only
  "bm25"         — BM25 keyword search only (rank-bm25 via llama-index-retrievers-bm25)
  "hybrid" (A0+) — Reciprocal Rank Fusion of dense + BM25

All three return a uniform list of (qa_id, score, metadata) triples where metadata
includes at minimum: qa_id, topic_path, source_url, source_type, cross_refs.

RRF is implemented directly (no LLM required) using the standard formula:
  RRF(d) = Σ_r  1 / (RRF_K + rank_r(d))
with RRF_K = 60 (Cormack et al. 2009).
"""

from __future__ import annotations

from typing import Literal

from llama_index.core import VectorStoreIndex
from llama_index.retrievers.bm25 import BM25Retriever

RetrieverMode = Literal["dense", "bm25", "hybrid"]

# (qa_id, normalised_score, node_metadata)
RetrievalResult = tuple[str, float, dict]

_RRF_K = 60  # standard RRF constant


def _results_from_nodes(nodes_with_scores) -> list[RetrievalResult]:
    results: list[RetrievalResult] = []
    for nws in nodes_with_scores:
        node = nws.node
        qa_id = node.metadata.get("qa_id", node.node_id)
        score = float(nws.score or 0.0)
        results.append((qa_id, score, dict(node.metadata)))
    return results


def make_dense_retriever(index: VectorStoreIndex, k: int, embed_model=None):
    """Return a LlamaIndex dense retriever from the given VectorStoreIndex."""
    kwargs: dict = {"similarity_top_k": k}
    if embed_model is not None:
        kwargs["embed_model"] = embed_model
    return index.as_retriever(**kwargs)


def make_bm25_retriever(index: VectorStoreIndex, k: int) -> BM25Retriever:
    """Return a BM25Retriever built from the docstore of the VectorStoreIndex."""
    return BM25Retriever.from_defaults(
        docstore=index.docstore,
        similarity_top_k=k,
    )


def _rrf_fuse(
    ranked_lists: list[list[RetrievalResult]],
    k: int,
) -> list[RetrievalResult]:
    """
    Reciprocal Rank Fusion over multiple ranked result lists.

    Each list is a list of (qa_id, score, metadata) already ordered by rank.
    Returns a new ranked list of length ≤ k, ordered by descending RRF score.
    """
    rrf_scores: dict[str, float] = {}
    metadata_store: dict[str, dict] = {}

    for ranked in ranked_lists:
        for rank, (qa_id, _score, meta) in enumerate(ranked):
            rrf_scores[qa_id] = rrf_scores.get(qa_id, 0.0) + 1.0 / (_RRF_K + rank + 1)
            metadata_store[qa_id] = meta

    fused = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:k]
    return [(qa_id, score, metadata_store[qa_id]) for qa_id, score in fused]


def retrieve(
    index: VectorStoreIndex,
    query: str,
    *,
    mode: RetrieverMode = "hybrid",
    k: int = 10,
    embed_model=None,
) -> list[RetrievalResult]:
    """
    Retrieve the top-k Q&A nodes for *query* using the selected *mode*.

    Args:
        index:       VectorStoreIndex built by harness.embed.build_index.
        query:       Natural-language query string.
        mode:        "dense" | "bm25" | "hybrid"
        k:           Number of results to return.
        embed_model: Override the embedding model (used in tests).

    Returns:
        Ordered list of (qa_id, score, metadata) — highest score first.
        For "hybrid" the score is the RRF fused score (higher = better).
    """
    if mode == "dense":
        retriever = make_dense_retriever(index, k, embed_model)
        nodes = retriever.retrieve(query)
        return _results_from_nodes(nodes)

    if mode == "bm25":
        retriever = make_bm25_retriever(index, k)
        nodes = retriever.retrieve(query)
        return _results_from_nodes(nodes)

    # hybrid: RRF fusion of dense + BM25 (no LLM required)
    dense_results = _results_from_nodes(make_dense_retriever(index, k, embed_model).retrieve(query))
    bm25_results = _results_from_nodes(make_bm25_retriever(index, k).retrieve(query))
    return _rrf_fuse([dense_results, bm25_results], k)

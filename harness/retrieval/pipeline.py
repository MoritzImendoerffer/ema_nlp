"""Run a retrieval pipeline: query transform -> retrieve -> dedupe -> rerank.

Retriever-agnostic: works over any LlamaIndex ``BaseRetriever`` (the live
``CustomPGRetriever`` over Neo4j at runtime, a fake in tests). The native
``index.as_retriever(sub_retrievers=[...])`` composition is built by the caller and
passed in as ``retriever``; this module orchestrates the transform + multi-query
merge + node-postprocessor (rerank) stages around it.
"""

import logging
from typing import Any

from llama_index.core.schema import QueryBundle

log = logging.getLogger(__name__)


def _node_id(node_with_score: Any) -> str:
    node = getattr(node_with_score, "node", node_with_score)
    return getattr(node, "node_id", None) or str(id(node_with_score))


def run_retrieval(
    retriever: Any,
    *,
    query: str,
    transform: Any = None,
    postprocessors: list | None = None,
) -> list:
    """Transform the query, retrieve (multi-query, deduped), then rerank."""
    queries = transform(query) if transform is not None else [query]

    seen: set[str] = set()
    merged: list = []
    for variant in queries:
        for node_with_score in retriever.retrieve(variant):
            nid = _node_id(node_with_score)
            if nid in seen:
                continue
            seen.add(nid)
            merged.append(node_with_score)

    qb = QueryBundle(query_str=query)
    for postprocessor in postprocessors or []:
        merged = postprocessor.postprocess_nodes(merged, query_bundle=qb)
    return merged

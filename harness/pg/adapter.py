"""Adapters between the pgvector retrieval layer and LlamaIndex.

Workflows in ``harness/workflows`` consume two shapes:

    list[RetrievalResult]                from the raw retrieve function
    list[NodeWithScore] / TextNode       from VectorStoreIndex.docstore

The pgvector path returns the first shape natively; this module bridges to
the second so callers that still need LlamaIndex nodes (e.g. the cross-ref
expansion logic in ``_retrieve_recursive``) keep working.

Two entry points:

    to_node_with_score(result)             RetrievalResult → NodeWithScore
    get_node_by_id(chunk_id, pool=None)    chunks table → TextNode | None
"""

from __future__ import annotations

from typing import Any

from llama_index.core.schema import NodeWithScore, TextNode

from harness.pg import queries as Q
from harness.pg.conn import get_pool


def _row_metadata(row: dict[str, Any]) -> dict[str, Any]:
    """Project a chunks-join-documents row into a node metadata dict."""
    last_updated = row.get("last_updated")
    if last_updated is not None and hasattr(last_updated, "isoformat"):
        last_updated = last_updated.isoformat()
    return {
        "chunk_id": row.get("chunk_id"),
        "doc_id": row.get("doc_id"),
        "chunk_index": row.get("chunk_index"),
        "heading_path": row.get("heading_path"),
        "token_count": row.get("token_count"),
        "source_url": row.get("source_url"),
        "source_type": row.get("source_type"),
        "title": row.get("title"),
        "topic_path": row.get("topic_path"),
        "reference_number": row.get("reference_number"),
        "committee": row.get("committee"),
        "revision": row.get("revision"),
        "last_updated": last_updated,
    }


def to_text_node(metadata: dict[str, Any], text: str) -> TextNode:
    """Build a LlamaIndex TextNode whose id is the chunk_id from ``metadata``."""
    chunk_id = metadata.get("chunk_id") or ""
    node = TextNode(text=text or "", metadata=dict(metadata), id_=chunk_id)
    return node


def to_node_with_score(result: tuple[str, float, dict[str, Any]]) -> NodeWithScore:
    """Convert a (chunk_id, score, metadata) tuple into a NodeWithScore.

    The metadata dict is expected to carry the chunk text under the ``"text"``
    key — the retrievers populate that to keep the tuple self-contained and
    avoid a second round-trip for the text payload.
    """
    chunk_id, score, metadata = result
    text = metadata.get("text", "") or ""
    md = {k: v for k, v in metadata.items() if k != "text"}
    md.setdefault("chunk_id", chunk_id)
    return NodeWithScore(node=to_text_node(md, text), score=float(score))


def to_nodes_with_scores(results: list[tuple[str, float, dict[str, Any]]]) -> list[NodeWithScore]:
    return [to_node_with_score(r) for r in results]


def get_node_by_id(chunk_id: str, *, pool=None) -> TextNode | None:
    """Fetch a single chunk from PG and return it as a LlamaIndex TextNode.

    Replaces ``VectorStoreIndex.docstore.get_node`` for the pgvector path.
    Returns None when the chunk does not exist."""
    if not chunk_id:
        return None
    pool = pool or get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(Q.CHUNK_BY_ID, {"chunk_id": chunk_id})
            cols = [d[0] for d in cur.description] if cur.description else []
            row = cur.fetchone()
    if row is None:
        return None
    raw = dict(zip(cols, row))
    text = raw.pop("text", "") or ""
    metadata = _row_metadata(raw)
    return to_text_node(metadata, text)

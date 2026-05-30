"""Hierarchical chunker — multi-level TextNodes with parent/child kept.

Unlike the old ``corpus/ingestion/chunker.py`` (which discarded every non-leaf
node at line 92), this keeps the full hierarchy so small-to-big / AutoMerging
retrieval has parents to merge up to (R4 / FR6).

``chunk_document`` returns ALL nodes across the configured ``chunk_sizes``
levels, with:
  - LlamaIndex PARENT/CHILD relationships intact (set by HierarchicalNodeParser)
  - deterministic node ids (sha256 of doc_id + running index) → idempotent rebuild
  - per-node metadata: doc_id, source_url, title, is_leaf, + caller base_metadata
  - leaf chunks flagged ``is_leaf=True`` (those are what LIR-007 embeds)
"""

from __future__ import annotations

import hashlib
from typing import Any

from llama_index.core.node_parser import HierarchicalNodeParser
from llama_index.core.schema import BaseNode, Document, NodeRelationship

from harness.indexing.profiles import ChunkingConfig

# metadata keys kept out of the embedding / LLM text (they're provenance, not content)
_EXCLUDED_META = ["doc_id", "source_url", "title", "is_leaf", "committee", "topic_path", "page"]


def doc_id_for(source_url: str) -> str:
    """Stable document id = sha256(source_url) — matches the rest of the pipeline."""
    return hashlib.sha256(source_url.encode("utf-8")).hexdigest()


def chunk_document(
    text: str,
    *,
    source_url: str,
    title: str | None = None,
    base_metadata: dict[str, Any] | None = None,
    config: ChunkingConfig | None = None,
) -> list[BaseNode]:
    """Split ``text`` into a hierarchy of TextNodes (all levels kept)."""
    config = config or ChunkingConfig()
    doc_id = doc_id_for(source_url)

    meta: dict[str, Any] = {"doc_id": doc_id, "source_url": source_url}
    if title:
        meta["title"] = title
    if base_metadata:
        meta.update({k: v for k, v in base_metadata.items() if v is not None})

    parser = HierarchicalNodeParser.from_defaults(chunk_sizes=list(config.chunk_sizes))
    doc = Document(text=text, metadata=dict(meta), doc_id=doc_id)
    nodes = parser.get_nodes_from_documents([doc])

    # Assign deterministic ids (stable across rebuilds) and rewrite the
    # parent/child/prev/next references to match. HierarchicalNodeParser emits
    # nodes in a stable order for identical input, so index-based ids are stable.
    id_map = {
        n.node_id: hashlib.sha256(f"{doc_id}|{i}".encode()).hexdigest()[:32]
        for i, n in enumerate(nodes)
    }

    def _remap(rel: Any) -> None:
        for ri in rel if isinstance(rel, list) else [rel]:
            if ri.node_id in id_map:
                ri.node_id = id_map[ri.node_id]

    out: list[BaseNode] = []
    for n in nodes:
        for rel in n.relationships.values():
            _remap(rel)
        is_leaf = NodeRelationship.CHILD not in n.relationships
        n.id_ = id_map[n.node_id]
        body = (n.text or "").strip()
        if len(body) < config.min_chunk_chars:
            continue
        n.metadata["doc_id"] = doc_id
        n.metadata["is_leaf"] = is_leaf
        n.excluded_embed_metadata_keys = list(_EXCLUDED_META)
        n.excluded_llm_metadata_keys = list(_EXCLUDED_META)
        out.append(n)
    return out


def leaf_nodes(nodes: list[BaseNode]) -> list[BaseNode]:
    """The leaf chunks (smallest level) — the ones to embed for retrieval."""
    return [n for n in nodes if n.metadata.get("is_leaf")]

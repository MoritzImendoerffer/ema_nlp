"""
Build and persist a two-level (page → Q&A) hierarchical index over the EMA corpus.

Structure
---------
- **Parent nodes** (one per unique ``source_url``): summary text built from metadata —
  title, topic path, and the first three Q&A question texts. No LLM call required.
  Metadata includes ``child_qa_ids`` (the list of Q&A nodes belonging to this page).
- **Child nodes**: the existing flat Q&A ``TextNode`` objects (unchanged). Not re-stored
  here — fetched on demand from the flat docstore during retrieval.

The hierarchical index persists to ``<index_dir>/hierarchical/`` as a standard
LlamaIndex FAISS-backed ``VectorStoreIndex`` over parent nodes only.

Usage::

    from harness.embed_hierarchical import build_hierarchical_index, load_hierarchical_index

    # Build (idempotent with force=False):
    hier_index = build_hierarchical_index(corpus_path, index_dir, force=False)

    # Load existing:
    hier_index = load_hierarchical_index(index_dir / "hierarchical")
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

import faiss
from llama_index.core import StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.core.schema import TextNode
from llama_index.vector_stores.faiss import FaissVectorStore

from corpus.models import QARecord
from harness.embed import EMBED_DIM, _load_records

log = logging.getLogger(__name__)

_HIER_SUBDIR = "hierarchical"


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _build_parent_nodes(records: list[QARecord]) -> list[TextNode]:
    """
    Group Q&A records by source_url and create one parent TextNode per page.

    Parent node text is metadata-derived (no LLM):
        Title: {source_title}
        Topic: {topic_path}
        Q&A count: {n}
        Sample questions:
          - {question_1[:120]}
          - {question_2[:120]}
          - {question_3[:120]}
    """
    by_url: dict[str, list[QARecord]] = defaultdict(list)
    for rec in records:
        by_url[rec.source_url].append(rec)

    parent_nodes: list[TextNode] = []
    for source_url, recs in by_url.items():
        n = len(recs)
        first_rec = recs[0]
        sample_qs = "\n".join(
            f"  - {r.question[:120]}" for r in recs[:3]
        )
        text = (
            f"Title: {first_rec.source_title}\n"
            f"Topic: {first_rec.topic_path}\n"
            f"Source: {source_url}\n"
            f"Q&A count: {n}\n"
            f"Sample questions:\n{sample_qs}"
        )
        child_qa_ids = [r.qa_id for r in recs]
        metadata = {
            "source_url": source_url,
            "source_type": first_rec.source_type,
            "source_title": first_rec.source_title,
            "topic_path": first_rec.topic_path,
            "child_qa_ids": child_qa_ids,
            "n_children": n,
        }
        node = TextNode(
            id_=f"parent::{source_url}",
            text=text,
            metadata=metadata,
            excluded_embed_metadata_keys=list(metadata.keys()),
        )
        parent_nodes.append(node)

    log.info("Built %d parent nodes from %d source URLs", len(parent_nodes), len(by_url))
    return parent_nodes


def build_hierarchical_index(
    corpus_path: Path,
    index_dir: Path,
    *,
    force: bool = False,
    embed_model=None,
) -> VectorStoreIndex:
    """
    Build (or reload) the hierarchical parent-node FAISS index.

    The index embeds one parent node per unique EMA source URL. Child Q&A nodes
    are not embedded here — they are fetched at query time from the flat docstore.

    Args:
        corpus_path: Source JSONL file (same corpus used by the flat index).
        index_dir:   Root persistence directory (same as flat index root).
                     The hierarchical index goes into ``<index_dir>/hierarchical/``.
        force:       Rebuild even if the index already exists.
        embed_model: Override the embedding model (used in tests).

    Returns:
        VectorStoreIndex over parent (page-level) nodes.
    """
    hier_dir = Path(index_dir) / _HIER_SUBDIR
    docstore_path = hier_dir / "docstore.json"

    if docstore_path.exists() and not force:
        log.info("Loading existing hierarchical index from %s", hier_dir)
        return load_hierarchical_index(hier_dir, embed_model=embed_model)

    log.info("Building hierarchical index from %s …", corpus_path)
    hier_dir.mkdir(parents=True, exist_ok=True)

    records = _load_records(corpus_path)
    parent_nodes = _build_parent_nodes(records)

    faiss_index = faiss.IndexFlatL2(EMBED_DIM)
    vector_store = FaissVectorStore(faiss_index=faiss_index)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    index = VectorStoreIndex(
        parent_nodes,
        storage_context=storage_context,
        show_progress=True,
        embed_model=embed_model,
    )

    index.storage_context.persist(persist_dir=str(hier_dir))
    faiss.write_index(faiss_index, str(hier_dir / "faiss.index"))
    log.info("Hierarchical index persisted to %s (%d parent nodes)", hier_dir, len(parent_nodes))

    return index


def load_hierarchical_index(
    hier_dir: Path,
    *,
    embed_model=None,
) -> VectorStoreIndex:
    """Load an existing hierarchical index from ``hier_dir``."""
    faiss_index = faiss.read_index(str(hier_dir / "faiss.index"))
    vector_store = FaissVectorStore(faiss_index=faiss_index)
    storage_context = StorageContext.from_defaults(
        vector_store=vector_store,
        persist_dir=str(hier_dir),
    )
    return load_index_from_storage(storage_context, embed_model=embed_model)  # type: ignore[return-value]

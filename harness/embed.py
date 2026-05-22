"""
Build and persist a LlamaIndex VectorStoreIndex over a corpus JSONL file.

The index uses:
  - BGE-large-en embeddings (via llama-index-embeddings-huggingface)
  - FAISS flat-L2 index as vector store (via llama-index-vector-stores-faiss)
  - cross_refs stored as node metadata (list of qa_ids); O(1) lookup at query time

Usage:
    python3 -m harness.embed [--corpus PATH] [--index-dir PATH] [--force]

The index is persisted to harness/index/ and can be reloaded without rebuilding.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import faiss
from llama_index.core import StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.core.schema import TextNode
from llama_index.vector_stores.faiss import FaissVectorStore

from corpus.models import QARecord
from harness.providers import configure_embed_model as _providers_configure

log = logging.getLogger(__name__)

try:
    from config import CORPUS_PATH as DEFAULT_CORPUS, INDEX_DIR as DEFAULT_INDEX_DIR
except ModuleNotFoundError:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent.parent))
    from config import CORPUS_PATH as DEFAULT_CORPUS, INDEX_DIR as DEFAULT_INDEX_DIR
EMBED_MODEL_NAME = "BAAI/bge-large-en-v1.5"
EMBED_DIM = 1024  # BGE-large-en output dimension


def _configure_embed_model(model_name: str | None = None) -> None:
    _providers_configure(model_name)


def _load_records(corpus_path: Path) -> list[QARecord]:
    records = []
    with corpus_path.open(encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            records.append(QARecord(**d))
    log.info("Loaded %d records from %s", len(records), corpus_path)
    return records


def _build_nodes(records: list[QARecord]) -> list[TextNode]:
    """
    Convert QARecord list to TextNodes.

    Node text = "Q: {question}\\n\\nA: {answer}" so embedding captures both
    question signal and answer content.

    cross_refs are stored in metadata as a list of qa_ids for O(1) lookup.
    LlamaIndex's NodeRelationship enum lacks a RELATED variant in this version,
    so cross-reference traversal is implemented directly via metadata lookup.

    All metadata keys are excluded from the embedding text so that only the
    Q+A content is used to compute the embedding vector.
    """
    _METADATA_KEYS = [
        "qa_id", "source_url", "source_type", "source_title",
        "topic_path", "extraction_confidence", "reference_number",
        "revision", "last_updated", "cross_refs",
    ]
    nodes: list[TextNode] = []
    for rec in records:
        text = f"Q: {rec.question}\n\nA: {rec.answer}"
        metadata = {
            "qa_id": rec.qa_id,
            "source_url": rec.source_url,
            "source_type": rec.source_type,
            "source_title": rec.source_title,
            "topic_path": rec.topic_path,
            "extraction_confidence": rec.extraction_confidence,
            "reference_number": rec.reference_number,
            "revision": rec.revision,
            "last_updated": rec.last_updated,
            "cross_refs": rec.cross_refs,
        }
        node = TextNode(
            id_=rec.qa_id,
            text=text,
            metadata=metadata,
            excluded_embed_metadata_keys=_METADATA_KEYS,
        )
        nodes.append(node)

    log.info("Built %d TextNodes", len(nodes))
    return nodes


def build_index(
    corpus_path: Path = DEFAULT_CORPUS,
    index_dir: Path = DEFAULT_INDEX_DIR,
    *,
    force: bool = False,
    embed_model=None,
) -> VectorStoreIndex:
    """
    Build (or reload) the FAISS-backed VectorStoreIndex.

    Args:
        corpus_path: Source JSONL file.
        index_dir:   Persistence directory.
        force:       Rebuild even if index already exists on disk.
        embed_model: Override the embedding model (used in tests; production
                     callers should call _configure_embed_model() first).

    Returns:
        A LlamaIndex VectorStoreIndex ready for retrieval.
    """
    index_dir = Path(index_dir)
    docstore_path = index_dir / "docstore.json"

    if docstore_path.exists() and not force:
        log.info("Loading existing index from %s", index_dir)
        faiss_index = faiss.read_index(str(index_dir / "faiss.index"))
        vector_store = FaissVectorStore(faiss_index=faiss_index)
        storage_context = StorageContext.from_defaults(
            vector_store=vector_store,
            persist_dir=str(index_dir),
        )
        return load_index_from_storage(storage_context, embed_model=embed_model)  # type: ignore[return-value]

    log.info("Building index from %s …", corpus_path)
    index_dir.mkdir(parents=True, exist_ok=True)

    records = _load_records(corpus_path)
    nodes = _build_nodes(records)

    faiss_index = faiss.IndexFlatL2(EMBED_DIM)
    vector_store = FaissVectorStore(faiss_index=faiss_index)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    index = VectorStoreIndex(
        nodes,
        storage_context=storage_context,
        show_progress=True,
        embed_model=embed_model,
    )

    index.storage_context.persist(persist_dir=str(index_dir))
    faiss.write_index(faiss_index, str(index_dir / "faiss.index"))
    log.info("Index persisted to %s", index_dir)

    return index


def get_node_by_id(index: VectorStoreIndex, qa_id: str) -> TextNode | None:
    """Look up a node by qa_id from the docstore (O(1))."""
    try:
        return index.docstore.get_node(qa_id)  # type: ignore[return-value]
    except (KeyError, ValueError):
        return None


def follow_cross_refs(index: VectorStoreIndex, qa_id: str) -> list[TextNode]:
    """
    Return all nodes referenced by cross_refs metadata of the given node.
    O(1) per hop — no retrieval needed.
    """
    node = get_node_by_id(index, qa_id)
    if node is None:
        return []
    related = []
    for ref_id in node.metadata.get("cross_refs", []):
        ref_node = get_node_by_id(index, ref_id)
        if ref_node is not None:
            related.append(ref_node)
    return related


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--force", action="store_true", help="Rebuild index even if it exists")
    args = parser.parse_args()
    _configure_embed_model()
    build_index(args.corpus, args.index_dir, force=args.force)
    log.info("Done.")

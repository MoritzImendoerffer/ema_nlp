"""Unit tests for harness.indexing.chunking — hierarchical, parents kept."""

from __future__ import annotations

import hashlib

from llama_index.core.schema import NodeRelationship

from harness.indexing.chunking import chunk_document, doc_id_for, leaf_nodes
from harness.indexing.profiles import ChunkingConfig

# Long enough to split across all three levels [2048, 512, 128] (tokens).
_LONG = "\n\n".join(
    f"## Section {i}\n\n" + ("lorem ipsum dolor sit amet consectetur adipiscing elit " * 40)
    for i in range(60)
)
_CFG = ChunkingConfig(chunk_sizes=[2048, 512, 128])
_URL = "https://www.ema.europa.eu/en/documents/scientific-guideline/example_en.pdf"
_BASE = {"committee": "CHMP", "topic_path": "/documents/scientific-guideline", "page": None}


def _chunk():
    return chunk_document(_LONG, source_url=_URL, title="Example", base_metadata=_BASE, config=_CFG)


def test_doc_id_is_sha256_of_url():
    assert doc_id_for(_URL) == hashlib.sha256(_URL.encode()).hexdigest()


def test_hierarchy_has_parents_and_leaves():
    nodes = _chunk()
    leaves = leaf_nodes(nodes)
    assert len(nodes) > len(leaves) > 0          # parents exist beyond the leaves
    assert any(not n.metadata["is_leaf"] for n in nodes)
    assert all(isinstance(n.metadata["is_leaf"], bool) for n in nodes)


def test_parent_child_relationships_intact():
    nodes = _chunk()
    assert any(NodeRelationship.CHILD in n.relationships for n in nodes)   # an internal node
    leaves = leaf_nodes(nodes)
    assert all(NodeRelationship.PARENT in n.relationships for n in leaves)


def test_metadata_stamped_and_none_dropped():
    nodes = _chunk()
    n = nodes[0]
    assert n.metadata["doc_id"] == doc_id_for(_URL)
    assert n.metadata["source_url"] == _URL
    assert n.metadata["title"] == "Example"
    assert n.metadata["committee"] == "CHMP"
    assert "page" not in n.metadata          # None values dropped


def test_excluded_embed_metadata_keys_set():
    n = _chunk()[0]
    assert "doc_id" in n.excluded_embed_metadata_keys
    assert "source_url" in n.excluded_llm_metadata_keys


def test_deterministic_ids_across_runs():
    ids1 = [n.node_id for n in _chunk()]
    ids2 = [n.node_id for n in _chunk()]
    assert ids1 == ids2
    assert len(set(ids1)) == len(ids1)       # unique


def test_min_chunk_chars_filters_debris():
    nodes = chunk_document(
        "short", source_url=_URL, config=ChunkingConfig(chunk_sizes=[512, 128], min_chunk_chars=80)
    )
    assert nodes == []                       # below threshold → dropped

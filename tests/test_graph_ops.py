"""The corpus graph's named writes and deletes (work unit 27, TASK-005).

Two halves: the Cypher that ``CorpusGraph`` sends (its shape, on a recording store), and
the in-memory double the build's tests run on (``tests/graph_double.py``). The Cypher
itself runs against a real Neo4j in ``tests/test_graph_ops_neo4j.py``.
"""

from __future__ import annotations

import pytest
from llama_index.core.graph_stores.types import ChunkNode, EntityNode, Relation

from harness.indexing.graph_ops import (
    CorpusGraph,
    delete_chunks_query,
    reset_queries,
)
from tests.graph_double import InMemoryCorpusGraph


class _Recorder:
    def __init__(self, rows=None) -> None:
        self.calls: list[tuple[str, dict | None]] = []
        self.rows = rows or []

    def structured_query(self, query, param_map=None):
        self.calls.append((query, param_map))
        return self.rows


def _all_queries(graph: CorpusGraph) -> list[str]:
    rec = graph.store
    graph.document_states()
    graph.delete_document_chunks(["d1"])
    graph.stamp_parse_identity([{"id": "d1", "parser": "p", "parser_version": "1", "text_sha256": "x"}])
    graph.delete_documents(["d1"])
    graph.reset_corpus()
    return [q for q, _ in rec.calls]


def test_cypher_shapes():
    graph = CorpusGraph(_Recorder())
    queries = _all_queries(graph)
    chunk_delete = delete_chunks_query(10_000)
    # starts at the indexed :Document node and follows HAS_CHUNK (NodeIndexSeek)
    assert "MATCH (d:Document {id: doc_id})-[:HAS_CHUNK]->(c:Chunk)" in chunk_delete
    assert "IN TRANSACTIONS OF 10000 ROWS" in chunk_delete
    for q in reset_queries(5000):
        assert "IN TRANSACTIONS OF 5000 ROWS" in q
    assert "MATCH (c:Chunk)" in reset_queries(1)[0]
    assert "MATCH (d:Document)" in reset_queries(1)[1]
    for q in queries:
        # the two shapes that scan or delete everything
        assert "MATCH (n) DETACH DELETE n" not in q
        assert "WHERE n.id IN" not in q


def test_batches_are_sent_per_doc_batch():
    rec = _Recorder()
    CorpusGraph(rec).delete_document_chunks([f"d{i}" for i in range(2_500)])
    assert [len(p["ids"]) for _, p in rec.calls] == [1_000, 1_000, 500]


def test_batch_size_must_be_positive():
    with pytest.raises(ValueError):
        delete_chunks_query(0)


def test_document_states_maps_rows():
    rec = _Recorder(rows=[
        {"id": "d1", "source_url": "u1", "parser": "pymupdf4llm", "parser_version": "legacy",
         "text_sha256": "abc", "has_chunks": True},
        {"id": "d2", "source_url": "u2", "parser": None, "parser_version": None,
         "text_sha256": None, "has_chunks": False},
    ])
    states = CorpusGraph(rec).document_states()
    assert states["d1"].stamped and states["d1"].has_chunks
    assert not states["d2"].stamped and not states["d2"].has_chunks


# ── the double ─────────────────────────────────────────────────────────────────


def _seed(graph: InMemoryCorpusGraph, doc_id: str, n_chunks: int) -> list[str]:
    ids = [f"{doc_id}-c{i}" for i in range(n_chunks)]
    nodes = [ChunkNode(text=f"t{i}", id_=cid, properties={"doc_id": doc_id}) for i, cid in enumerate(ids)]
    nodes.append(EntityNode(name=doc_id, label="Document", properties={"source_url": f"u-{doc_id}"}))
    rels = [Relation(label="HAS_CHUNK", source_id=doc_id, target_id=cid) for cid in ids]
    rels += [Relation(label="PARENT_OF", source_id=ids[0], target_id=cid) for cid in ids[1:]]
    graph.upsert(nodes, rels)
    return ids


def test_double_delete_removes_chunks_and_their_edges():
    g = InMemoryCorpusGraph()
    a = _seed(g, "a", 4)
    _seed(g, "b", 2)
    g.upsert([], [Relation(label="LINKS_TO", source_id="a", target_id="b")])
    g.delete_document_chunks(["a"])
    assert not any(cid in g.nodes for cid in a)
    assert not any(e for e in g.edges if e[1] in a or e[2] in a)  # PARENT_OF and HAS_CHUNK gone
    assert "a" in g.nodes and ("LINKS_TO", "a", "b") in g.edges  # the document and its links stay
    assert len(g.chunks_of("b")) == 2
    assert g.document_states()["a"].has_chunks is False


def test_double_delete_documents_and_reset():
    g = InMemoryCorpusGraph()
    _seed(g, "a", 2)
    _seed(g, "b", 2)
    g.add_node("dash", {"_Neodash_Dashboard"})
    g.delete_documents(["a"])
    assert "a" not in g.nodes and set(g.document_states()) == {"b"}
    g.reset_corpus()
    assert set(g.nodes) == {"dash"} and not g.edges


def test_double_crash_leaves_chunks_without_entity_update():
    g = InMemoryCorpusGraph()
    g.fail_after_chunks = True
    with pytest.raises(RuntimeError):
        _seed(g, "a", 2)
    assert "a" not in g.nodes and len(g.upserted_chunk_ids) == 2


def test_document_chunks_reads_from_the_indexed_document():
    rec = _Recorder(rows=[{"id": "c1", "text": "t", "is_leaf": True}])
    assert CorpusGraph(rec).document_chunks("d1") == [{"id": "c1", "text": "t", "is_leaf": True}]
    query, params = rec.calls[0]
    assert "MATCH (d:Document {id: $id})-[:HAS_CHUNK]->(c:Chunk)" in query and params == {"id": "d1"}

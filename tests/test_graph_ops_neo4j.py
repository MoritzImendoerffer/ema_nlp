"""The graph deletes on a real Neo4j: a throwaway instance, never the live graph.

Work unit 27, TASK-013. The in-memory double (``tests/graph_double.py``) shows that the
build calls the right operations; these tests show that the Cypher of
``harness/indexing/graph_ops.py`` does on Neo4j 5.26 what the double models.

They run only when ``EMA_SCRATCH_NEO4J_URI`` names a scratch instance, for example::

    docker run -d --name ema_neo4j_scratch -p 127.0.0.1:7688:7687 \\
        -e NEO4J_AUTH=neo4j/<scratch password> -e NEO4J_PLUGINS='["apoc"]' neo4j:5.26
    EMA_SCRATCH_NEO4J_URI=bolt://localhost:7688 EMA_SCRATCH_NEO4J_PASSWORD=<scratch password> \\
        .venv/bin/python -m pytest -m integration tests/test_graph_ops_neo4j.py

Every test empties the scratch database first. Two guards keep that away from the live
graph: a URI on port 7687 (the live container's port) fails the test before it
connects, and a database with more than 100,000 nodes is never emptied.
"""

from __future__ import annotations

import datetime as dt
import os
from urllib.parse import urlparse

import pytest

pytestmark = pytest.mark.integration

_URI = os.getenv("EMA_SCRATCH_NEO4J_URI", "")
_MAX_SCRATCH_NODES = 100_000
_DIMS = 8


def _guard_uri(uri: str) -> None:
    if urlparse(uri).port in (None, 7687):
        raise RuntimeError(
            f"EMA_SCRATCH_NEO4J_URI={uri!r} names port 7687 or no port: that is the live graph's "
            "port. Point it at a throwaway instance, e.g. bolt://localhost:7688"
        )


@pytest.fixture
def store():
    if not _URI:
        pytest.skip("EMA_SCRATCH_NEO4J_URI is not set: no scratch Neo4j to run on")
    _guard_uri(_URI)
    from llama_index.graph_stores.neo4j import Neo4jPropertyGraphStore

    s = Neo4jPropertyGraphStore(
        username=os.getenv("EMA_SCRATCH_NEO4J_USER", "neo4j"),
        password=os.environ["EMA_SCRATCH_NEO4J_PASSWORD"],
        url=_URI,
    )
    n = s.structured_query("MATCH (n) RETURN count(n) AS n")[0]["n"]
    if n > _MAX_SCRATCH_NODES:
        raise RuntimeError(f"the database at {_URI} holds {n} nodes; a scratch instance holds few")
    s.structured_query("MATCH (n) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS")
    s.structured_query("CREATE INDEX ema_document_id IF NOT EXISTS FOR (d:Document) ON (d.id)")
    s.structured_query("DROP INDEX ema_chunk_embedding IF EXISTS")
    yield s
    s.close()


class _Embed:
    def get_text_embedding_batch(self, texts, show_progress=False):
        return [[float((hash(t) >> i) % 97 + 1) for i in range(_DIMS)] for t in texts]


_PDF = "https://www.ema.europa.eu/en/documents/scientific-guideline/scratch_en.pdf"
_PDF2 = "https://www.ema.europa.eu/en/documents/scientific-guideline/scratch-two_en.pdf"
_SENT = "A sentence about acceptable intake and CHMP assessment of nitrosamines. "


def _client(*texts_by_url):
    import mongomock

    from config import MONGO_DB
    from harness.indexing.ingest import PARSED_COLLECTION

    client = mongomock.MongoClient()
    rows = [
        {"url": url, "parser": "pymupdf4llm", "parser_version": "legacy",
         "parsed_at": dt.datetime(2026, 5, 27), "content_type": "application/pdf",
         "text_format": "markdown", "error": "", "text": "# Title\n\n" + _SENT * n}
        for url, n in texts_by_url
    ]
    if rows:
        client[MONGO_DB][PARSED_COLLECTION].insert_many(rows)
    return client


def _profile():
    from harness.indexing.profiles import (
        ChunkingConfig,
        IndexConfig,
        IndexProfile,
        RetrievalConfig,
        ScopeConfig,
    )

    return IndexProfile(
        name="scratch",
        index=IndexConfig(chunking=ChunkingConfig(chunk_sizes=[512, 128]), scope=ScopeConfig()),
        retrieval=RetrievalConfig(),
    )


def _build(store, client, **kw):
    from harness.indexing.graph_ops import CorpusGraph
    from harness.indexing.property_graph import _embed_pass

    return _embed_pass(
        _profile(), CorpusGraph(store), client, lambda _u: None, _Embed(),
        flush_chunks=1_000_000, metadata_lookup=lambda _u: None, **kw,
    )


def _chunk_ids(store, url=_PDF):
    from harness.indexing.chunking import doc_id_for

    rows = store.structured_query(
        "MATCH (:Document {id: $id})-[:HAS_CHUNK]->(c:Chunk) RETURN c.id AS id, c.is_leaf AS leaf",
        param_map={"id": doc_id_for(url)},
    )
    return {r["id"]: r["leaf"] for r in rows}


def test_guard_refuses_the_live_port():
    with pytest.raises(RuntimeError):
        _guard_uri("bolt://localhost:7687")


def test_replace_on_neo4j_leaves_no_chunk_of_the_first_build(store):
    from harness.indexing.graph_ops import CorpusGraph

    _build(store, _client((_PDF, 40)))
    first = _chunk_ids(store)
    assert sum(first.values()) == 6
    stats = _build(store, _client((_PDF, 9)))
    assert stats.replaced == 1
    second = _chunk_ids(store)
    assert sum(second.values()) == 2
    left = store.structured_query(
        "MATCH (c:Chunk) WHERE c.id IN $ids RETURN count(c) AS n", param_map={"ids": list(first)}
    )[0]["n"]
    assert left == len(set(first) & set(second))  # only ids the second build wrote again
    orphans = store.structured_query(
        "MATCH (c:Chunk) WHERE NOT ()-[:HAS_CHUNK]->(c) RETURN count(c) AS n"
    )[0]["n"]
    assert orphans == 0
    states = CorpusGraph(store).document_states()
    assert len(states) == 1 and next(iter(states.values())).stamped


def test_unchanged_build_skips_on_neo4j(store):
    client = _client((_PDF, 40))
    _build(store, client)
    stats = _build(store, client)
    assert stats.skipped == 1 and stats.embedded == 0


def test_deleted_chunk_leaves_the_vector_index_at_once(store):
    _build(store, _client((_PDF, 40)))
    leaf = store.structured_query(
        "MATCH (c:Chunk {is_leaf: true}) RETURN c.id AS id, c.embedding AS e LIMIT 1"
    )[0]
    store.structured_query("CALL db.awaitIndexes(60)")
    query = (
        "CALL db.index.vector.queryNodes('ema_chunk_embedding', 50, $e) YIELD node "
        "RETURN collect(node.id) AS ids"
    )
    assert leaf["id"] in store.structured_query(query, param_map={"e": leaf["e"]})[0]["ids"]
    store.structured_query("MATCH (c:Chunk {id: $id}) DETACH DELETE c", param_map={"id": leaf["id"]})
    assert leaf["id"] not in store.structured_query(query, param_map={"e": leaf["e"]})[0]["ids"]


def test_prune_on_neo4j(store):
    from harness.indexing.graph_ops import CorpusGraph
    from harness.indexing.property_graph import prune_documents

    _build(store, _client((_PDF, 40), (_PDF2, 40)))
    assert prune_documents(CorpusGraph(store), _client((_PDF, 40))) == [_PDF2]
    assert _chunk_ids(store, _PDF2) == {}
    docs = store.structured_query("MATCH (d:Document) RETURN d.source_url AS u")
    assert [r["u"] for r in docs] == [_PDF]


def test_reset_keeps_other_nodes_on_neo4j(store):
    from harness.indexing.graph_ops import CorpusGraph

    _build(store, _client((_PDF, 40), (_PDF2, 40)))
    store.structured_query("CREATE (:_Neodash_Dashboard {title: 'scratch'})")
    CorpusGraph(store).reset_corpus(batch_rows=7)
    labels = store.structured_query("MATCH (n) RETURN labels(n) AS l")
    assert [r["l"] for r in labels] == [["_Neodash_Dashboard"]]

"""Unit tests for harness.indexing.property_graph.to_graph (IR -> graph mapping).

The live build + retrieval are integration-verified against Neo4j (see work unit
20 / LIR-007/008 notes); here we lock the pure IR->nodes/relations mapping with
no infra: entity/chunk ids, HAS_CHUNK/PARENT_OF/LINKS_TO edges, links_to resolution.
"""

from __future__ import annotations

from harness.indexing.chunking import chunk_document, doc_id_for
from harness.indexing.ingest import IngestedDoc
from harness.indexing.links import ExtractedLink
from harness.indexing.profiles import ChunkingConfig
from harness.indexing.property_graph import to_graph

_LONG = "\n\n".join(
    f"## Section {i}\n\n" + ("regulatory guidance about acceptable intake limits " * 30)
    for i in range(20)
)
_URL_A = "https://www.ema.europa.eu/en/page-a"
_URL_B = "https://www.ema.europa.eu/en/doc-b_en.pdf"


def _doc(url: str, links=()) -> IngestedDoc:
    chunks = chunk_document(
        _LONG, source_url=url, title="T", config=ChunkingConfig(chunk_sizes=[512, 128])
    )
    return IngestedDoc(
        doc_id=doc_id_for(url), source_url=url, source_type="html", title="T",
        metadata={"committee": "CHMP", "topic_path": "/en/"}, chunk_nodes=chunks, links=list(links),
    )


def test_to_graph_structure():
    doc_a = _doc(_URL_A, links=[
        ExtractedLink(tgt_url=_URL_B, anchor="b", kind="file"),          # resolves (B in subset)
        ExtractedLink(tgt_url="https://fda.gov/x", anchor="x", kind="external"),  # does not
    ])
    doc_b = _doc(_URL_B)
    ents, chunks, rels = to_graph([doc_a, doc_b])

    assert {e.id for e in ents} == {doc_a.doc_id, doc_b.doc_id}
    assert all(e.label == "Document" for e in ents)

    expected_chunk_ids = {c.node_id for c in doc_a.chunk_nodes + doc_b.chunk_nodes}
    assert {c.id for c in chunks} == expected_chunk_ids

    has_chunk = [r for r in rels if r.label == "HAS_CHUNK"]
    parent_of = [r for r in rels if r.label == "PARENT_OF"]
    links_to = [r for r in rels if r.label == "LINKS_TO"]

    assert len(has_chunk) == len(chunks)
    assert all(r.target_id in expected_chunk_ids for r in has_chunk)
    assert len(parent_of) > 0  # multi-level hierarchy produced
    assert all(r.source_id in expected_chunk_ids and r.target_id in expected_chunk_ids for r in parent_of)

    # exactly one links_to edge, A -> B; the external link is dropped (not in subset)
    assert len(links_to) == 1
    assert links_to[0].source_id == doc_a.doc_id
    assert links_to[0].target_id == doc_b.doc_id


def test_links_to_dropped_when_target_absent():
    doc_a = _doc(_URL_A, links=[ExtractedLink(tgt_url=_URL_B, anchor="b", kind="file")])
    _ents, _chunks, rels = to_graph([doc_a])  # B not ingested
    assert [r for r in rels if r.label == "LINKS_TO"] == []


def test_links_to_carries_typed_properties():
    doc_a = _doc(_URL_A, links=[
        ExtractedLink(tgt_url=_URL_B, anchor="QA PDF", kind="file",
                      link_context="file_component", document_type="scientific-guideline"),
    ])
    doc_b = _doc(_URL_B)
    _ents, _chunks, rels = to_graph([doc_a, doc_b])
    lt = [r for r in rels if r.label == "LINKS_TO"]
    assert len(lt) == 1
    props = lt[0].properties
    assert props["kind"] == "file"
    assert props["link_context"] == "file_component"
    assert props["document_type"] == "scientific-guideline"
    assert props["anchor"] == "QA PDF"


def test_links_to_props_drop_none_document_type():
    doc_a = _doc(_URL_A, links=[
        ExtractedLink(tgt_url=_URL_B, anchor="b", kind="page", link_context="inline"),
    ])
    doc_b = _doc(_URL_B)
    _ents, _chunks, rels = to_graph([doc_a, doc_b])
    props = next(r for r in rels if r.label == "LINKS_TO").properties
    assert "document_type" not in props  # None dropped by _clean
    assert props["link_context"] == "inline"


# ── edge-only rebuild helpers (live ordering/non-destruction verified in TASK-006) ──

class _RecordingStore:
    """Captures (query, param_map) for Cypher-shape assertions; no infra."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict | None]] = []

    def structured_query(self, query, param_map=None):
        self.calls.append((query, param_map))
        return []


def test_delete_links_touches_only_relationships():
    from harness.indexing.property_graph import _delete_links

    store = _RecordingStore()
    _delete_links(store)
    q = store.calls[0][0]
    assert "LINKS_TO" in q and "IN TRANSACTIONS" in q and "DELETE" in q
    # relationship-typed: never mentions chunk/hierarchy node labels
    assert "Chunk" not in q and "HAS_CHUNK" not in q and "PARENT_OF" not in q


def test_merge_links_batch_sets_typed_props():
    from harness.indexing.property_graph import _merge_links_batch

    store = _RecordingStore()
    _merge_links_batch(
        store, [{"s": "a", "t": "b", "props": {"kind": "file", "link_context": "file_component"}}]
    )
    query, param_map = store.calls[0]
    assert "MERGE (a)-[e:LINKS_TO]->(b)" in query
    assert "SET e += p.props" in query
    assert param_map["pairs"][0]["props"]["link_context"] == "file_component"


# ── LOE-002: the build embeds LEAF chunks only (parents stored, unembedded) ──────

class _FakeEmbed:
    """Records every text it is asked to embed; returns dummy vectors."""

    def __init__(self) -> None:
        self.embedded: list[str] = []

    def get_text_embedding_batch(self, texts, show_progress=False):
        self.embedded.extend(texts)
        return [[0.1, 0.2, 0.3] for _ in texts]


class _FakeStore:
    """Captures upserted nodes/relations; structured_query is a no-op (vector index)."""

    def __init__(self) -> None:
        self.nodes: list = []
        self.relations: list = []
        self.queries: list = []

    def upsert_nodes(self, nodes):
        self.nodes.extend(nodes)

    def upsert_relations(self, rels):
        self.relations.extend(rels)

    def structured_query(self, query, param_map=None):
        self.queries.append(query)
        return []


def test_embed_pass_embeds_leaves_only():
    """Regression for LOE-002: only is_leaf chunks get embeddings; parents are
    upserted with text but no embedding (so the Neo4j vector index is leaf-only)."""
    import mongomock

    from config import MONGO_DB
    from harness.indexing.ingest import PARSED_COLLECTION
    from harness.indexing.profiles import (
        IndexConfig,
        IndexProfile,
        RetrievalConfig,
        ScopeConfig,
    )
    from harness.indexing.property_graph import _embed_pass

    client = mongomock.MongoClient()
    client[MONGO_DB][PARSED_COLLECTION].insert_one(
        {  # one large doc -> guaranteed multi-level hierarchy (leaves + parents)
            "url": "https://www.ema.europa.eu/en/doc_en.pdf",
            "parser": "p", "parser_version": "1", "content_type": "application/pdf",
            "text_format": "markdown", "error": "",
            "text": "# Title\n\n" + ("A sentence about acceptable intake and CHMP assessment. " * 400),
        }
    )
    profile = IndexProfile(
        name="t",
        index=IndexConfig(chunking=ChunkingConfig(chunk_sizes=[512, 128]), scope=ScopeConfig()),
        retrieval=RetrievalConfig(),
    )
    store, embed = _FakeStore(), _FakeEmbed()
    _embed_pass(
        profile, store, client, lambda _u: None, embed, done=set(), flush_chunks=1_000_000
    )

    chunk_nodes = [n for n in store.nodes if "is_leaf" in getattr(n, "properties", {})]
    leaves = [n for n in chunk_nodes if n.properties["is_leaf"]]
    parents = [n for n in chunk_nodes if not n.properties["is_leaf"]]

    assert leaves and parents, "fixture must produce both leaf and parent chunks"
    assert all(n.embedding is not None for n in leaves), "leaves must be embedded"
    assert all(n.embedding is None for n in parents), "parents must NOT be embedded"
    # the embedder saw ONLY leaf texts, exactly once each
    assert sorted(embed.embedded) == sorted(n.text for n in leaves)
    assert len(embed.embedded) == len(leaves)
    # the vector index was created (sized from a leaf embedding)
    assert any("VECTOR INDEX" in q for q in store.queries)

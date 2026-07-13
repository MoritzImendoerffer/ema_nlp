"""Unit tests for harness.indexing.property_graph.to_graph (IR -> graph mapping).

The live build + retrieval are integration-verified against Neo4j (see work unit
20 / LIR-007/008 notes); here we lock the pure IR->nodes/relations mapping with
no infra: entity/chunk ids, HAS_CHUNK/PARENT_OF/LINKS_TO edges, links_to resolution.
"""

from __future__ import annotations

from harness.indexing.chunking import chunk_document, doc_id_for
from harness.indexing.ingest import IngestedDoc
from harness.indexing.links import ExtractedLink
from harness.indexing.profiles import ChunkingConfig, GraphRetrievalConfig
from harness.indexing.property_graph import HierarchicalPGRetriever, to_graph

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


# ── HierarchicalPGRetriever metadata mapping (offline, fake store) ────────────

def test_retriever_meta_carries_document_provenance():
    """The retriever surfaces the Document node's reference metadata + real
    chunk_id so citations/reference cards get title/category/committee etc."""
    from llama_index.core import QueryBundle

    from harness.indexing.property_graph import HierarchicalPGRetriever

    rows = [
        {
            "id": "leaf-1",
            "text": "leaf text",
            "score": 0.91,
            "doc": {
                "id": "doc-1",
                "source_url": "https://www.ema.europa.eu/en/documents/scientific-guideline/ich-q3a_en.pdf",
                "title": "ICH Q3A Impurities",
                "topic_path": "/documents/scientific-guideline/",
                "committee": "CHMP",
                "reference_number": "EMA/CHMP/123/2021",
                "source_type": "pdf",
                "topic_hubs": ["referral_procedures"],
            },
            "parent": {"id": "parent-1", "text": "parent text (bigger window)"},
        },
        {   # doc props may be null in the graph — must map to "" not "None"
            "id": "leaf-2",
            "text": "other leaf",
            "score": 0.5,
            "doc": {"id": "doc-2", "source_url": None, "title": None, "topic_path": None,
                    "committee": None, "reference_number": None, "source_type": None},
            "parent": None,
        },
    ]

    class _FakeStore:
        def structured_query(self, query, param_map=None):
            assert "d {.id, .source_url, .title, .topic_path" in query
            assert ".topic_hubs}" in query  # membership rides the doc projection
            return rows

    class _FakeEmbed:
        def get_query_embedding(self, q):
            return [0.0]

    retriever = HierarchicalPGRetriever(_FakeStore(), _FakeEmbed(), k=5, merge=True)
    out = retriever._retrieve(QueryBundle(query_str="q"))
    assert len(out) == 2

    meta = out[0].node.metadata
    assert out[0].node.node_id == "parent-1"  # small-to-big merge
    assert meta["chunk_id"] == "parent-1" and meta["matched_chunk"] == "leaf-1"
    assert meta["title"] == "ICH Q3A Impurities"
    assert meta["committee"] == "CHMP"
    assert meta["reference_number"] == "EMA/CHMP/123/2021"
    assert meta["category"] == "scientific_guideline"
    assert meta["topic_hubs"] == ["referral_procedures"]

    meta2 = out[1].node.metadata
    assert meta2["source_url"] == "" and meta2["title"] == ""  # nulls never become "None"
    assert meta2["category"] == "other"
    assert meta2["topic_hubs"] == []  # unstamped graph -> [], never None


def test_entity_nodes_carry_persisted_category():
    guideline_url = "https://www.ema.europa.eu/en/documents/scientific-guideline/x_en.pdf"
    ents, _chunks, _rels = to_graph([_doc(_URL_A), _doc(guideline_url)])
    by_url = {e.properties["source_url"]: e.properties for e in ents}
    assert by_url[guideline_url]["category"] == "scientific_guideline"
    assert by_url[_URL_A]["category"] == "other"


def test_entity_nodes_carry_topic_hubs_when_joined():
    """topic_hubs (the document_metadata join) persists on :Document; absent = no key."""
    doc = _doc(_URL_A)
    doc.metadata["topic_hubs"] = ["referral_procedures"]
    doc.metadata["revision"] = "4"
    ents, _chunks, _rels = to_graph([doc, _doc(_URL_B)])
    by_url = {e.properties["source_url"]: e.properties for e in ents}
    assert by_url[_URL_A]["topic_hubs"] == ["referral_procedures"]
    assert by_url[_URL_A]["revision"] == "4"
    assert "topic_hubs" not in by_url[_URL_B]  # None is _clean-ed, never persisted


# --- HierarchicalPGRetriever steering (fake store, no Neo4j) ------------------

class _SteerStore:
    """Records Cypher calls; serves canned rows for the vector / expansion queries."""

    def __init__(self, main_rows, expand_rows=None):
        self.main_rows = main_rows
        self.expand_rows = expand_rows or []
        self.calls: list[tuple[str, dict]] = []

    def structured_query(self, query, param_map=None):
        self.calls.append((query, param_map or {}))
        if "queryNodes" in query:
            rows = self.main_rows
            cats = (param_map or {}).get("cats")
            if cats is not None:
                rows = [r for r in rows if (r.get("doc") or {}).get("category") in cats]
            return rows[: (param_map or {})["k"]]
        return self.expand_rows


class _SteerEmbed:
    def get_query_embedding(self, _q):
        return [0.1, 0.2, 0.3]


def _row(i: int, category: str, score: float) -> dict:
    return {
        "id": f"c{i}",
        "text": f"text {i}",
        "score": score,
        "doc": {
            "id": f"d{i}",
            "source_url": f"https://ema.europa.eu/{i}",
            "category": category,
        },
        "parent": None,
    }


def test_retriever_plain_path_unchanged():
    store = _SteerStore([_row(i, "epar", 1 - i / 10) for i in range(3)])
    nodes = HierarchicalPGRetriever(store, _SteerEmbed(), k=2).retrieve("q")
    _query, params = store.calls[0]
    assert params["k"] == 2 and params["cats"] is None  # no oversampling, no filter
    assert [n.node.metadata["category"] for n in nodes] == ["epar", "epar"]
    assert all(n.node.metadata["retrieval_origin"] == "vector" for n in nodes)


def test_retriever_with_categories_oversamples_and_filters():
    rows = [_row(0, "epar", 0.9), _row(1, "qa", 0.8), _row(2, "epar", 0.7), _row(3, "qa", 0.6)]
    store = _SteerStore(rows)
    base = HierarchicalPGRetriever(store, _SteerEmbed(), k=2, oversample=3)
    nodes = base.with_categories(["qa"]).retrieve("q")
    _query, params = store.calls[0]
    assert params["k"] == 6 and params["cats"] == ["qa"]  # k * oversample pool
    assert [n.node.metadata["category"] for n in nodes] == ["qa", "qa"]


def test_retriever_quota_stratifies_pool():
    rows = [_row(i, "epar", 1 - i / 10) for i in range(4)] + [_row(9, "qa", 0.1)]
    store = _SteerStore(rows)
    retriever = HierarchicalPGRetriever(
        store, _SteerEmbed(), k=3, oversample=2, category_quota={"qa": 1}
    )
    nodes = retriever.retrieve("q")
    assert store.calls[0][1]["k"] == 6  # quota also draws from the oversampled pool
    cats = [n.node.metadata["category"] for n in nodes]
    assert len(nodes) == 3 and cats.count("qa") == 1
    assert cats == ["epar", "epar", "qa"]  # score order preserved


def test_retriever_link_expansion_appends_provenance_tagged_nodes():
    expand_rows = [
        {
            "doc": {
                "id": "dg",
                "source_url": "https://ema.europa.eu/guideline",
                "category": "scientific_guideline",
            },
            "linked_from": ["d0"],
            "best": {"id": "cg", "text": "linked guideline text", "score": 0.75, "parent": None},
        }
    ]
    store = _SteerStore([_row(0, "epar", 0.9)], expand_rows=expand_rows)
    graph = GraphRetrievalConfig(expand=True, expand_categories=["scientific_guideline"])
    nodes = HierarchicalPGRetriever(store, _SteerEmbed(), k=1, graph=graph).retrieve("q")

    assert len(store.calls) == 2
    expand_query, expand_params = store.calls[1]
    assert "LINKS_TO*1..1" in expand_query
    assert expand_params["seed_ids"] == ["d0"]
    assert expand_params["cats"] == ["scientific_guideline"]

    assert len(nodes) == 2  # vector hit + additive expansion
    expanded = nodes[-1]
    assert expanded.node.metadata["retrieval_origin"] == "link_expansion"
    assert expanded.node.metadata["linked_from"] == ["d0"]
    assert expanded.node.metadata["category"] == "scientific_guideline"
    assert expanded.score == 0.75


def test_retriever_expansion_dedupes_against_vector_hits():
    expand_rows = [
        {
            "doc": {"id": "d0", "source_url": "u", "category": "epar"},
            "linked_from": ["d0"],
            "best": {"id": "c0", "text": "same chunk", "score": 0.5, "parent": None},
        }
    ]
    store = _SteerStore([_row(0, "epar", 0.9)], expand_rows=expand_rows)
    graph = GraphRetrievalConfig(expand=True)
    nodes = HierarchicalPGRetriever(store, _SteerEmbed(), k=1, graph=graph).retrieve("q")
    assert len(nodes) == 1  # the expanded chunk was already returned by the vector pass

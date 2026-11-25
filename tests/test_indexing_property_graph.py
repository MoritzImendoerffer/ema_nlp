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
        profile, store, client, lambda _u: None, embed, flush_chunks=1_000_000
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
                "tree_path": "medicines/human/EPAR/thing",
                "tree_depth": 4,
                "tree_ancestor_ids": ["anc-root", "anc-near"],
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
            assert ".topic_hubs" in query  # membership rides the doc projection
            assert ".tree_ancestor_ids}" in query  # site-tree place rides it too
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
    assert meta["tree_path"] == "medicines/human/EPAR/thing"
    assert meta["tree_depth"] == 4
    assert meta["tree_ancestor_ids"] == ["anc-root", "anc-near"]

    meta2 = out[1].node.metadata
    assert meta2["source_url"] == "" and meta2["title"] == ""  # nulls never become "None"
    assert meta2["category"] == "other"
    assert meta2["topic_hubs"] == []  # unstamped graph -> [], never None
    assert meta2["tree_path"] == "" and meta2["tree_depth"] is None  # pre-backfill graph
    assert meta2["tree_ancestor_ids"] == []


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
    """Records Cypher calls; serves canned rows for the vector / expansion /
    ancestor queries."""

    def __init__(self, main_rows, expand_rows=None, ancestor_rows=None):
        self.main_rows = main_rows
        self.expand_rows = expand_rows or []
        self.ancestor_rows = ancestor_rows or []
        self.calls: list[tuple[str, dict]] = []

    def structured_query(self, query, param_map=None):
        self.calls.append((query, param_map or {}))
        if "queryNodes" in query:
            rows = self.main_rows
            cats = (param_map or {}).get("cats")
            if cats is not None:
                rows = [r for r in rows if (r.get("doc") or {}).get("category") in cats]
            return rows[: (param_map or {})["k"]]
        if "$seed_ids" in query:
            return self.expand_rows
        return self.ancestor_rows


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


# --- HierarchicalPGRetriever tree-ancestor context (fake store) ---------------

def _row_with_ancestors(i: int, ancestors: list[str], score: float = 0.9) -> dict:
    row = _row(i, "epar", score)
    row["doc"]["tree_ancestor_ids"] = ancestors
    row["doc"]["tree_path"] = "medicines/human/EPAR/x"
    return row


def _ancestor_row(doc_id: str, chunk_id: str, score: float) -> dict:
    return {
        "doc": {
            "id": doc_id,
            "source_url": f"https://ema.europa.eu/{doc_id}",
            "category": "regulatory_overview",
            "tree_path": "medicines",
        },
        "best": {"id": chunk_id, "text": f"text of {doc_id}", "score": score, "parent": None},
    }


def test_retriever_ancestor_context_nearest_first_with_provenance():
    store = _SteerStore(
        [_row_with_ancestors(0, ["root-doc", "mid-doc"])],  # stored root→nearest
        ancestor_rows=[_ancestor_row("mid-doc", "cm", 0.6), _ancestor_row("root-doc", "cr", 0.4)],
    )
    graph = GraphRetrievalConfig(ancestors=True, max_ancestors=3)
    nodes = HierarchicalPGRetriever(store, _SteerEmbed(), k=1, graph=graph).retrieve("q")

    assert len(store.calls) == 2  # vector + one ancestor query (no link expansion)
    _q, params = store.calls[1]
    assert params["ids"] == ["mid-doc", "root-doc"]  # nearest-first
    assert len(nodes) == 3  # vector hit + two additive ancestors
    anc = nodes[1:]
    assert [n.node.metadata["doc_id"] for n in anc] == ["mid-doc", "root-doc"]
    assert all(n.node.metadata["retrieval_origin"] == "tree_ancestor" for n in anc)
    assert all(n.node.metadata["linked_from"] == ["d0"] for n in anc)


def test_retriever_ancestor_cap_and_already_retrieved_are_respected():
    # d1 is both a vector hit and an ancestor of d0 → excluded; cap keeps nearest only
    rows = [
        _row_with_ancestors(0, ["root-doc", "d1", "mid-doc"], score=0.9),
        _row(1, "epar", 0.8),
    ]
    store = _SteerStore(rows, ancestor_rows=[_ancestor_row("mid-doc", "cm", 0.6)])
    graph = GraphRetrievalConfig(ancestors=True, max_ancestors=1)
    nodes = HierarchicalPGRetriever(store, _SteerEmbed(), k=2, graph=graph).retrieve("q")

    _q, params = store.calls[1]
    assert params["ids"] == ["mid-doc"]  # d1 skipped (already retrieved), capped at 1
    assert len(nodes) == 3


def test_retriever_ancestors_noop_without_backfill():
    store = _SteerStore([_row(0, "epar", 0.9)])  # no tree_ancestor_ids on the doc
    graph = GraphRetrievalConfig(ancestors=True)
    nodes = HierarchicalPGRetriever(store, _SteerEmbed(), k=1, graph=graph).retrieve("q")
    assert len(store.calls) == 1  # no ancestor query issued
    assert len(nodes) == 1


def test_retriever_expand_and_ancestors_compose():
    expand_rows = [
        {
            "doc": {"id": "dg", "source_url": "u", "category": "scientific_guideline"},
            "linked_from": ["d0"],
            "best": {"id": "cg", "text": "linked", "score": 0.75, "parent": None},
        }
    ]
    store = _SteerStore(
        [_row_with_ancestors(0, ["mid-doc"])],
        expand_rows=expand_rows,
        ancestor_rows=[_ancestor_row("mid-doc", "cm", 0.6)],
    )
    graph = GraphRetrievalConfig(expand=True, ancestors=True)
    nodes = HierarchicalPGRetriever(store, _SteerEmbed(), k=1, graph=graph).retrieve("q")
    assert len(store.calls) == 3  # vector + expansion + ancestors
    origins = [n.node.metadata["retrieval_origin"] for n in nodes]
    assert origins == ["vector", "link_expansion", "tree_ancestor"]


# --- the matched leaf's text survives the merge to the parent (eval reliability, TASK-010) ---

_LEAF = "LEAF the acceptable intake is 96 ng/day"
_PARENT = f"PARENT opening text of the section. {_LEAF} closing text of the section."


def _merged_row(i: int) -> dict:
    row = _row(i, "epar", 0.9)
    row["text"] = _LEAF
    row["parent"] = {"id": f"p{i}", "text": _PARENT}
    return row


def test_retriever_keeps_the_matched_leaf_text_when_it_merges_to_the_parent():
    """With merge, only the leaf's id survived; the agent saw the parent's first 400 chars."""
    store = _SteerStore([_merged_row(0)])
    (node,) = HierarchicalPGRetriever(store, _SteerEmbed(), k=1, merge=True).retrieve("q")
    assert node.node.text == _PARENT
    assert node.node.metadata["matched_text"] == _LEAF
    assert node.node.metadata["matched_chunk"] == "c0"


def test_expansion_and_ancestor_nodes_keep_the_matched_leaf_text():
    best = {"id": "cl", "text": _LEAF, "score": 0.7, "parent": {"id": "pl", "text": _PARENT}}
    expand_rows = [{"doc": {"id": "dl", "source_url": "https://ema.europa.eu/l"}, "linked_from": ["d0"], "best": best}]
    anc_best = {"id": "ca", "text": _LEAF, "score": 0.5, "parent": {"id": "pa", "text": _PARENT}}
    ancestor_rows = [{"doc": {"id": "anc", "source_url": "https://ema.europa.eu/a"}, "best": anc_best}]
    seed = _merged_row(0)
    seed["doc"]["tree_ancestor_ids"] = ["anc"]
    store = _SteerStore([seed], expand_rows=expand_rows, ancestor_rows=ancestor_rows)
    graph = GraphRetrievalConfig(expand=True, ancestors=True)
    nodes = HierarchicalPGRetriever(store, _SteerEmbed(), k=1, merge=True, graph=graph).retrieve("q")
    by_origin = {n.node.metadata["retrieval_origin"]: n.node for n in nodes}
    for origin in ("link_expansion", "tree_ancestor"):
        assert by_origin[origin].text == _PARENT
        assert by_origin[origin].metadata["matched_text"] == _LEAF


def test_matched_text_stays_out_of_the_reranker_input():
    """SentenceTransformerRerank scores get_content(EMBED); the leaf must not count twice."""
    from llama_index.core.schema import MetadataMode

    store = _SteerStore([_merged_row(0)])
    (node,) = HierarchicalPGRetriever(store, _SteerEmbed(), k=1, merge=True).retrieve("q")
    for mode in (MetadataMode.EMBED, MetadataMode.LLM):
        assert node.node.get_content(metadata_mode=mode).count(_LEAF) <= 1


# ── TASK-003 (unit 27): the :Document records which parse it was built from ──────
#
# Before 2026-11-25 ``:Document`` held neither the parser nor a hash of its text
# (count 0, 0, 0 on the live graph), so a build could not see that a document changed.


def _pdf_row(text: str) -> dict:
    return {
        "url": _URL_B, "parser": "pymupdf4llm", "parser_version": "legacy",
        "content_type": "application/pdf", "text_format": "markdown", "error": "", "text": text,
    }


def test_entity_carries_parse_identity():
    import hashlib

    from harness.indexing.ingest import build_ingested_doc
    from harness.indexing.property_graph import _entity_for

    row = _pdf_row(_LONG)
    doc = build_ingested_doc(row, chunking=ChunkingConfig(chunk_sizes=[512, 128]), html_lookup=lambda u: None)
    props = _entity_for(doc).properties
    assert props["parser"] == "pymupdf4llm"
    assert props["parser_version"] == "legacy"
    assert props["text_sha256"] == hashlib.sha256(row["text"].encode("utf-8")).hexdigest()
    assert len(props["text_sha256"]) == 64


def test_parse_identity_leaves_chunks_unchanged():
    """The identity rides on the entity only: chunk ids and texts stay as embedded."""
    from harness.indexing.ingest import build_ingested_doc

    cfg = ChunkingConfig(chunk_sizes=[512, 128])
    doc = build_ingested_doc(_pdf_row(_LONG), chunking=cfg, html_lookup=lambda u: None)
    expected = chunk_document(
        _LONG, source_url=_URL_B, title=doc.title,
        base_metadata={"source_type": "pdf", "committee": doc.metadata["committee"],
                       "topic_path": doc.metadata["topic_path"],
                       "reference_number": doc.metadata["reference_number"]},
        config=cfg,
    )
    got = [(c.node_id, c.text, c.metadata.get("is_leaf")) for c in doc.chunk_nodes]
    assert got == [(c.node_id, c.text, c.metadata.get("is_leaf")) for c in expected]
    for c in doc.chunk_nodes:
        assert "text_sha256" not in c.metadata and "parser_version" not in c.metadata


# ── TASK-004 (unit 27): the real build joins document_metadata ───────────────────
#
# Until 2026-11-25 ``_embed_pass`` called ``build_ingested_doc`` without the metadata
# lookup (property_graph.py:307). Only ``ingest()`` joined, and only tests call it,
# so a fresh build lost doc_type and topic_hubs until ``propagate`` ran.


def test_build_joins_document_metadata():
    import mongomock

    from config import MONGO_DB
    from harness.indexing.document_metadata import upsert_doc_types
    from harness.indexing.ingest import PARSED_COLLECTION
    from harness.indexing.profiles import IndexConfig, IndexProfile, RetrievalConfig, ScopeConfig
    from harness.indexing.property_graph import _embed_pass

    url = "https://www.ema.europa.eu/en/documents/scientific-guideline/g_en.pdf"
    client = mongomock.MongoClient()
    client[MONGO_DB][PARSED_COLLECTION].insert_one(
        {"url": url, "parser": "pymupdf4llm", "parser_version": "legacy",
         "content_type": "application/pdf", "text_format": "markdown", "error": "",
         "text": "# Title\n\n" + ("A sentence about acceptable intake. " * 200)}
    )
    upsert_doc_types({url: "scientific-guideline"}, client=client)
    profile = IndexProfile(
        name="t",
        index=IndexConfig(chunking=ChunkingConfig(chunk_sizes=[512, 128]), scope=ScopeConfig()),
        retrieval=RetrievalConfig(),
    )
    store = _FakeStore()
    _embed_pass(profile, store, client, lambda _u: None, _FakeEmbed(), flush_chunks=1_000_000)

    (doc_entity,) = [n for n in store.nodes if getattr(n, "label", None) == "Document"]
    assert doc_entity.properties["doc_type"] == "scientific-guideline"


# ── TASK-006 (unit 27): resume by comparison — skip, stamp or replace ────────────
#
# Until 2026-11-25 a resumed build skipped every document that had a chunk
# (``_existing_doc_ids``). A changed text never reached the graph, and a shorter text
# chunked again would have left the old chunks with higher positions behind.

import datetime as _dt  # noqa: E402

import pytest  # noqa: E402

from tests.graph_double import InMemoryCorpusGraph  # noqa: E402

_PDF = "https://www.ema.europa.eu/en/documents/scientific-guideline/refresh_en.pdf"
_SENT = "A sentence about acceptable intake and CHMP assessment of nitrosamines. "


def _text(n_sentences: int) -> str:
    return "# Title\n\n" + (_SENT * n_sentences)


def _refresh_profile():
    from harness.indexing.profiles import IndexConfig, IndexProfile, RetrievalConfig, ScopeConfig

    return IndexProfile(
        name="t",
        index=IndexConfig(chunking=ChunkingConfig(chunk_sizes=[512, 128]), scope=ScopeConfig()),
        retrieval=RetrievalConfig(),
    )


def _client_with(*rows):
    import mongomock

    from config import MONGO_DB
    from harness.indexing.ingest import PARSED_COLLECTION

    client = mongomock.MongoClient()
    client[MONGO_DB][PARSED_COLLECTION].insert_many([dict(r) for r in rows])
    return client


def _prow(text, parser="pymupdf4llm", version="legacy", url=_PDF, ct="application/pdf",
          at=_dt.datetime(2026, 5, 27, 22, 0)):
    return {"url": url, "parser": parser, "parser_version": version, "parsed_at": at,
            "content_type": ct, "text_format": "markdown", "error": "", "text": text}


def _build(graph, client, *, resume=True, embed=None):
    from harness.indexing.property_graph import _embed_pass

    embed = embed or _FakeEmbed()
    stats = _embed_pass(
        _refresh_profile(), graph, client, lambda _u: None, embed,
        flush_chunks=1_000_000, resume=resume, metadata_lookup=lambda _u: None,
    )
    return stats, embed


def _leaves(graph, url=_PDF):
    return [c for c in graph.chunks_of(doc_id_for(url)) if c.properties.get("is_leaf")]


def test_changed_text_replaces_chunks():
    graph = InMemoryCorpusGraph()
    _build(graph, _client_with(_prow(_text(40))))
    first = {c.id for c in graph.chunks_of(doc_id_for(_PDF))}
    assert len(_leaves(graph)) == 6, "fixture: the first text must give 6 leaves"

    stats, _ = _build(graph, _client_with(_prow(_text(9))))
    assert stats.replaced == 1 and stats.new == 0
    assert len(_leaves(graph)) == 2
    second = {c.id for c in graph.chunks_of(doc_id_for(_PDF))}
    # Chunk ids are sha256(doc_id|position): the leftovers would be the high positions.
    assert not (first - second) & set(graph.nodes), "a chunk of the first build remains"


def test_unchanged_document_is_skipped():
    graph = InMemoryCorpusGraph()
    client = _client_with(_prow(_text(40)))
    _build(graph, client)
    stats, embed = _build(graph, client)
    assert embed.embedded == []
    assert stats.skipped == 1 and stats.built == 0


def test_equal_text_new_version_stamps_only():
    """parse-html reproduces the legacy text under a new version: no re-embedding."""
    html = "https://www.ema.europa.eu/en/human-regulatory-overview/page"
    text = _text(40)
    graph = InMemoryCorpusGraph()
    _build(graph, _client_with(_prow(text, "trafilatura", "legacy", url=html, ct="text/html")))
    newer = _client_with(
        _prow(text, "trafilatura", "legacy", url=html, ct="text/html"),
        _prow(text, "trafilatura", "2.0.0", url=html, ct="text/html", at=_dt.datetime(2026, 11, 25)),
    )
    stats, embed = _build(graph, newer)
    assert embed.embedded == []
    assert stats.stamped == 1
    assert graph.nodes[doc_id_for(html)].properties["parser_version"] == "2.0.0"


def test_text_without_chunks_keeps_old_chunks():
    """Chunk first, delete afterwards: a text that gives no chunk never empties a document."""
    graph = InMemoryCorpusGraph()
    _build(graph, _client_with(_prow(_text(40))))
    before = {c.id for c in graph.chunks_of(doc_id_for(_PDF))}
    stats, _ = _build(graph, _client_with(_prow("")))
    assert stats.replace_without_chunks == 1 and stats.replaced == 0
    assert {c.id for c in graph.chunks_of(doc_id_for(_PDF))} == before


def test_unstamped_document_counts_as_old_rule_row():
    """A graph document from before the backfill records no parse: it counts as built from
    the old-rule row, and an unchanged row embeds nothing."""
    graph = InMemoryCorpusGraph()
    client = _client_with(_prow(_text(40)))
    _build(graph, client)
    for key in ("parser", "parser_version", "text_sha256"):
        graph.nodes[doc_id_for(_PDF)].properties.pop(key)
    stats, embed = _build(graph, client)
    assert embed.embedded == [] and stats.skipped == 1


def test_unstamped_document_with_new_selected_text_is_replaced():
    graph = InMemoryCorpusGraph()
    _build(graph, _client_with(_prow(_text(40), "trafilatura", "legacy", ct="text/html")))
    for key in ("parser", "parser_version", "text_sha256"):
        graph.nodes[doc_id_for(_PDF)].properties.pop(key)
    client = _client_with(
        _prow(_text(40), "trafilatura", "legacy", ct="text/html"),
        _prow(_text(9), "trafilatura", "2.0.0", ct="text/html", at=_dt.datetime(2026, 11, 25)),
    )
    stats, _ = _build(graph, client)
    assert stats.replaced == 1 and len(_leaves(graph)) == 2


def test_failed_upsert_is_replaced_again():
    """A crash after the delete leaves values that do not match; the next build replaces."""
    graph = InMemoryCorpusGraph()
    _build(graph, _client_with(_prow(_text(40))))
    changed = _client_with(_prow(_text(9)))
    graph.fail_after_chunks = True
    with pytest.raises(RuntimeError):
        _build(graph, changed)
    graph.fail_after_chunks = False
    stats, _ = _build(graph, changed)
    assert stats.built == 1
    from harness.indexing.ingest import text_sha256

    assert graph.nodes[doc_id_for(_PDF)].properties["text_sha256"] == text_sha256(_text(9))
    assert len(_leaves(graph)) == 2


def test_no_resume_replaces_every_document():
    graph = InMemoryCorpusGraph()
    client = _client_with(_prow(_text(40)))
    _build(graph, client)
    stats, embed = _build(graph, client, resume=False)
    assert stats.replaced == 1 and len(embed.embedded) == 6
    assert len(_leaves(graph)) == 6


def test_embed_pass_logs_the_counts(caplog):
    graph = InMemoryCorpusGraph()
    with caplog.at_level("INFO", logger="harness.indexing.property_graph"):
        _build(graph, _client_with(_prow(_text(40))))
    line = [r.message for r in caplog.records if r.message.startswith("embed pass:")][-1]
    for word in ("new", "replaced", "stamped", "skipped", "preference fallbacks"):
        assert word in line


# ── TASK-007 (unit 27): prune compares with all clean URLs, never with the scope ──

_PDF2 = "https://www.ema.europa.eu/en/documents/scientific-guideline/refresh-two_en.pdf"


def test_prune_deletes_document_without_clean_row():
    from harness.indexing.property_graph import prune_documents

    graph = InMemoryCorpusGraph()
    _build(graph, _client_with(_prow(_text(40)), _prow(_text(40), url=_PDF2)))
    removed = prune_documents(graph, _client_with(_prow(_text(40))))  # _PDF2 left the source
    assert removed == [_PDF2]
    assert set(graph.document_states()) == {doc_id_for(_PDF)}
    assert not graph.chunks_of(doc_id_for(_PDF2))


def test_prune_ignores_scope_limit():
    """A narrowed scope must not delete the documents outside it (exploration 3.7)."""
    from harness.indexing.property_graph import _embed_pass, prune_documents

    graph = InMemoryCorpusGraph()
    client = _client_with(_prow(_text(40)), _prow(_text(40), url=_PDF2))
    _build(graph, client)
    profile = _refresh_profile()
    profile.index.scope.limit = 1
    _embed_pass(profile, graph, client, lambda _u: None, _FakeEmbed(), flush_chunks=1_000_000,
                metadata_lookup=lambda _u: None)
    assert prune_documents(graph, client) == []
    assert set(graph.document_states()) == {doc_id_for(_PDF), doc_id_for(_PDF2)}


def _run_build(monkeypatch, graph, client, **kw):
    import harness.indexing.property_graph as pg

    class _NoIndex:
        @staticmethod
        def from_existing(**_kw):
            return None

    monkeypatch.setattr(pg, "neo4j_store_from_env", lambda: graph)
    monkeypatch.setattr(pg, "PropertyGraphIndex", _NoIndex)
    pg.build_property_graph_index(
        _refresh_profile(), mongo_client=client, html_lookup=lambda _u: None,
        embed_model=_FakeEmbed(), metadata_lookup=lambda _u: None, **kw,
    )


def test_prune_off_by_default(monkeypatch):
    graph = InMemoryCorpusGraph()
    _build(graph, _client_with(_prow(_text(40)), _prow(_text(40), url=_PDF2)))
    only_one = _client_with(_prow(_text(40)))
    _run_build(monkeypatch, graph, only_one)
    assert doc_id_for(_PDF2) in graph.document_states()  # kept: decision B
    _run_build(monkeypatch, graph, only_one, prune=True)
    assert doc_id_for(_PDF2) not in graph.document_states()


def test_prune_logs_the_count_before_deleting(caplog):
    from harness.indexing.property_graph import prune_documents

    graph = InMemoryCorpusGraph()
    _build(graph, _client_with(_prow(_text(40)), _prow(_text(40), url=_PDF2)))
    with caplog.at_level("INFO", logger="harness.indexing.property_graph"):
        prune_documents(graph, _client_with(_prow(_text(40))))
    messages = [r.message for r in caplog.records]
    count_at = next(i for i, m in enumerate(messages) if "have no clean row" in m)
    deleted_at = next(i for i, m in enumerate(messages) if m.startswith("prune: deleted"))
    assert count_at < deleted_at and any(_PDF2 in m for m in messages[count_at:deleted_at])

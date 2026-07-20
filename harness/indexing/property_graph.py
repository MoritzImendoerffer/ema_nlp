"""Hierarchical PropertyGraphIndex on Neo4j — build + retriever (LIR-007/008).

SPIKE OUTCOME (the small-to-big-on-PropertyGraphIndex question):

  Small-to-big does NOT need AutoMergingRetriever (which wants a docstore). On a
  PropertyGraphIndex it falls out of ``VectorContextRetriever(path_depth=N)``:
  the vector hit lands on a (leaf) chunk, then the retriever *walks the graph
  relations* up to ``path_depth`` and returns the connected paths — so the
  parent chunks, the owning Document, and ``LINKS_TO`` neighbours come back with
  the leaf. We build the graph from custom nodes (no LLM extraction):

      Document   -> EntityNode(label="Document", id=doc_id)
      chunk      -> ChunkNode(id=chunk_node_id, text=...)
      relations  -> Document  -HAS_CHUNK->  chunk
                    parent    -PARENT_OF->  child        (hierarchy, from chunker)
                    Document  -LINKS_TO->   Document      (resolved links_to edges)

  Chunk embeddings are computed here and stored on the ChunkNodes; the index is
  wrapped with ``PropertyGraphIndex.from_existing(kg_extractors=[],
  embed_kg_nodes=False)`` so nothing re-embeds or LLM-extracts. Neo4j's native
  vector index serves the dense query.

  v1 embeds ALL chunks (every level) for simplicity; embedding leaves only is a
  later refinement (vector hits leaves, path_depth supplies parents).
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

from llama_index.core import PropertyGraphIndex
from llama_index.core.graph_stores.types import ChunkNode, EntityNode, Relation
from llama_index.core.llms import MockLLM
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeRelationship, NodeWithScore, QueryBundle, TextNode
from llama_index.graph_stores.neo4j import Neo4jPropertyGraphStore
from pymongo import MongoClient

from config import MONGO_URI
from harness.indexing.chunking import doc_id_for
from harness.indexing.ingest import (
    IngestedDoc,
    build_ingested_doc,
    iter_source_rows,
    mongo_html_lookup,
)
from harness.indexing.links import ExtractedLink, extract_links
from harness.indexing.profiles import IndexProfile
from harness.indexing.registry import register_index, register_open, register_retriever

_log = logging.getLogger(__name__)

# Dedicated vector index over Chunk nodes (Neo4j auto-creates `entity` only for
# __Entity__ nodes; our retrievable units are :Chunk, so we index them ourselves).
CHUNK_VECTOR_INDEX = "ema_chunk_embedding"


def neo4j_store_from_env() -> Neo4jPropertyGraphStore:
    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        raise RuntimeError(
            "NEO4J_PASSWORD is not set. Configure it in ~/Nextcloud/Datasets/ema_nlp/ema_nlp.env "
            "(never hardcode credentials)."
        )
    return Neo4jPropertyGraphStore(
        username=os.getenv("NEO4J_USER", "neo4j"),
        password=password,
        url=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
    )


def _embed_model(model_name: str | None = None) -> Any:
    """Configure + return the embedder. Pass the PROFILE's ``embed_model`` so the
    index profile is the single source of truth for the embedding space (F12/R3-Q1);
    ``EMA_EMBED_MODEL`` remains the fallback only when no profile is in play."""
    from llama_index.core import Settings

    from harness.providers import configure_embed_model

    configure_embed_model(model_name)
    return Settings.embed_model


def _clean(props: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in props.items() if v is not None}


def ensure_chunk_vector_index(store: Neo4jPropertyGraphStore, dims: int) -> None:
    """Create the Chunk vector index (idempotent) sized to the embedding model."""
    store.structured_query(
        f"CREATE VECTOR INDEX {CHUNK_VECTOR_INDEX} IF NOT EXISTS "
        "FOR (c:Chunk) ON (c.embedding) "
        f"OPTIONS {{indexConfig: {{`vector.dimensions`: {int(dims)}, "
        "`vector.similarity_function`: 'cosine'}}"
    )


def ensure_document_id_index(store: Neo4jPropertyGraphStore) -> None:
    """Range index on :Document(id), awaited online.

    The LINKS_TO pass matches docs by id (``MATCH (a:Document {id: ...})``).
    LlamaIndex only indexes the base ``__Node__``/``__Entity__`` labels, so without
    this every match is a full :Document label scan — a 20k-pair MERGE batch then
    does billions of comparisons and effectively hangs (and starves the Mongo
    cursor → CursorNotFound). Block until the index is ONLINE so the MERGE uses it.
    """
    store.structured_query(
        "CREATE INDEX ema_document_id IF NOT EXISTS FOR (d:Document) ON (d.id)"
    )
    store.structured_query("CALL db.awaitIndexes(600)")


def to_graph(
    docs: list[IngestedDoc],
) -> tuple[list[EntityNode], list[ChunkNode], list[Relation]]:
    """Map the ingestion IR to PropertyGraph nodes + relations (no embedding)."""
    doc_ids = {d.doc_id for d in docs}
    entities: list[EntityNode] = []
    chunks: list[ChunkNode] = []
    relations: list[Relation] = []
    for d in docs:
        entities.append(_entity_for(d))
        for cn in d.chunk_nodes:
            chunks.append(
                ChunkNode(
                    text=cn.text,
                    id_=cn.node_id,
                    properties=_clean(
                        {
                            "doc_id": d.doc_id,
                            "source_url": d.source_url,
                            "is_leaf": bool(cn.metadata.get("is_leaf")),
                        }
                    ),
                )
            )
            relations.append(Relation(label="HAS_CHUNK", source_id=d.doc_id, target_id=cn.node_id))
            parent = cn.relationships.get(NodeRelationship.PARENT)
            if parent is not None:
                relations.append(
                    Relation(label="PARENT_OF", source_id=parent.node_id, target_id=cn.node_id)
                )
        for link in d.links:
            if link.tgt_doc_id in doc_ids:
                relations.append(
                    Relation(
                        label="LINKS_TO",
                        source_id=d.doc_id,
                        target_id=link.tgt_doc_id,
                        properties=_link_props(link),
                    )
                )
    return entities, chunks, relations


def _link_props(link: ExtractedLink) -> dict[str, Any]:
    """LINKS_TO edge properties (None dropped so they never reach Neo4j)."""
    return _clean(
        {
            "kind": link.kind,
            "link_context": link.link_context,
            "document_type": link.document_type,
            "anchor": link.anchor,
        }
    )


def _entity_for(d: IngestedDoc) -> EntityNode:
    # ``category`` is persisted on the Document node so retrieval can filter /
    # stratify / expand by source category in Cypher (steering Options A+B).
    # Existing graphs get it via scripts/backfill_doc_categories.py (same rules).
    from harness.retrieval.doc_categories import classify_source

    return EntityNode(
        name=d.doc_id,
        label="Document",
        properties=_clean(
            {
                "source_url": d.source_url,
                "title": d.title,
                "source_type": d.source_type,
                "committee": d.metadata.get("committee"),
                "topic_path": d.metadata.get("topic_path"),
                "reference_number": d.metadata.get("reference_number"),
                "doc_type": d.metadata.get("doc_type"),
                "audience": d.metadata.get("audience"),
                "site_topic": d.metadata.get("site_topic"),
                # Joined from document_metadata like the labels above; None
                # (dropped by _clean) until a hub build stamped the row. The
                # revision (from text_metadata) feeds the topic map's
                # latest-per-module grouping.
                "topic_hubs": d.metadata.get("topic_hubs") or None,
                "revision": d.metadata.get("revision"),
                "category": classify_source(
                    d.source_url or "", d.metadata.get("topic_path") or ""
                ),
            }
        ),
    )


def _chunk_nodes_and_rels(d: IngestedDoc) -> tuple[list[ChunkNode], list[Relation]]:
    """ChunkNodes + HAS_CHUNK/PARENT_OF for one doc (LINKS_TO is a separate global pass)."""
    chunks: list[ChunkNode] = []
    rels: list[Relation] = []
    for cn in d.chunk_nodes:
        chunks.append(
            ChunkNode(
                text=cn.text,
                id_=cn.node_id,
                properties=_clean(
                    {
                        "doc_id": d.doc_id,
                        "source_url": d.source_url,
                        "is_leaf": bool(cn.metadata.get("is_leaf")),
                    }
                ),
            )
        )
        rels.append(Relation(label="HAS_CHUNK", source_id=d.doc_id, target_id=cn.node_id))
        parent = cn.relationships.get(NodeRelationship.PARENT)
        if parent is not None:
            rels.append(
                Relation(label="PARENT_OF", source_id=parent.node_id, target_id=cn.node_id)
            )
    return chunks, rels


def _existing_doc_ids(store: Neo4jPropertyGraphStore) -> set[str]:
    """Doc ids already materialized with >=1 chunk — skipped on a resumed build."""
    rows = store.structured_query(
        "MATCH (d:Document)-[:HAS_CHUNK]->(:Chunk) RETURN DISTINCT d.id AS id"
    )
    return {r["id"] for r in rows if r.get("id")}


def _embed_pass(
    profile: IndexProfile,
    store: Neo4jPropertyGraphStore,
    client: Any,
    lookup: Any,
    embed: Any,
    *,
    done: set[str],
    flush_chunks: int,
    pause_every_docs: int = 0,
    pause_seconds: float = 60.0,
) -> None:
    """Stream docs; embed + upsert nodes/edges in flushes of ~``flush_chunks`` chunks.

    When ``pause_every_docs`` > 0, the pass flushes and then sleeps
    ``pause_seconds`` after every that-many *new* documents. This throttles
    sustained GPU load: on this host the 3090's GSP firmware wedges under
    uninterrupted CUDA load (root cause unconfirmed — observed across kernels,
    so not kernel-specific; capping power + pausing avoids it empirically). The
    flush leaves the graph fully persisted at each pause, so a kill during the
    sleep loses nothing.
    """
    scope = profile.index.scope
    chunking = profile.index.chunking
    t0 = time.time()
    ents: list[EntityNode] = []
    chs: list[ChunkNode] = []
    rels: list[Relation] = []
    n_docs = n_chunks = n_embedded = skipped = 0
    last_pause_at = 0
    vindex = {"done": False}

    def flush() -> None:
        nonlocal ents, chs, rels, n_embedded
        if not chs:
            return
        # Embed LEAF chunks only. Parent (mid/root) chunks are reached via PARENT_OF
        # for small-to-big merge-up and are never vector-matched, so embedding them
        # wastes compute and pollutes the vector index with mixed granularities. This
        # is the canonical AutoMerging pattern (index leaves; keep parents in the store).
        leaves = [c for c in chs if c.properties.get("is_leaf")]
        if leaves:
            embs = embed.get_text_embedding_batch([c.text for c in leaves], show_progress=False)
            for c, e in zip(leaves, embs):
                c.embedding = e
            n_embedded += len(leaves)
            if not vindex["done"]:
                ensure_chunk_vector_index(store, len(embs[0]))
                vindex["done"] = True
        store.upsert_nodes(ents + chs)  # parents upserted with text but no embedding
        if rels:
            store.upsert_relations(rels)
        rate = n_embedded / max(time.time() - t0, 1e-6)
        _log.info(
            "flush: %d docs, %d chunks, %d leaf-embedded (%.0f emb/s)",
            n_docs, n_chunks, n_embedded, rate,
        )
        ents, chs, rels = [], [], []

    for row in iter_source_rows(scope, client=client):
        url = row.get("url")
        if not url:
            continue
        if doc_id_for(url) in done:
            skipped += 1
            continue
        doc = build_ingested_doc(row, chunking=chunking, html_lookup=lookup)
        if not doc.chunk_nodes:
            continue
        if scope.committee and doc.metadata.get("committee") not in scope.committee:
            continue
        ents.append(_entity_for(doc))
        c, r = _chunk_nodes_and_rels(doc)
        chs.extend(c)
        rels.extend(r)
        n_docs += 1
        n_chunks += len(c)
        if len(chs) >= flush_chunks:
            flush()
        if scope.limit and n_docs >= scope.limit:
            break
        if pause_every_docs and n_docs - last_pause_at >= pause_every_docs:
            flush()  # persist the batch before sleeping so the pause is crash-safe
            last_pause_at = n_docs
            _log.info(
                "pause: %d docs done — sleeping %.0fs to cool the GPU", n_docs, pause_seconds
            )
            time.sleep(pause_seconds)
    flush()
    _log.info(
        "embed pass: %d docs, %d chunks (%d leaf-embedded), %d skipped, %.0fs",
        n_docs, n_chunks, n_embedded, skipped, time.time() - t0,
    )


def _merge_links_batch(store: Neo4jPropertyGraphStore, pairs: list[dict[str, Any]]) -> None:
    """MERGE doc->doc LINKS_TO edges and stamp their typed properties.

    Each pair is ``{"s": src_id, "t": tgt_id, "props": {kind, link_context,
    document_type, anchor}}`` (props already ``_clean``ed of ``None``).
    """
    if pairs:
        store.structured_query(
            "UNWIND $pairs AS p "
            "MATCH (a:Document {id: p.s}), (b:Document {id: p.t}) "
            "MERGE (a)-[e:LINKS_TO]->(b) "
            "SET e += p.props",
            param_map={"pairs": pairs},
        )


def _delete_links(store: Neo4jPropertyGraphStore) -> None:
    """Delete ALL ``LINKS_TO`` relationships, batched in autocommit transactions.

    Relationship-typed ``MATCH`` → touches no nodes: ``:Chunk`` / ``:Document`` /
    ``HAS_CHUNK`` / ``PARENT_OF`` / embeddings are untouched. ``CALL { … } IN
    TRANSACTIONS`` requires an implicit/autocommit transaction, which
    ``Neo4jPropertyGraphStore.structured_query`` provides (verified, graph-stores
    -neo4j 0.7.0). Lets the link extractor be re-run without re-embedding.
    """
    store.structured_query(
        "MATCH ()-[r:LINKS_TO]->() "
        "CALL { WITH r DELETE r } IN TRANSACTIONS OF 50000 ROWS"
    )


def _links_pass(
    profile: IndexProfile,
    store: Neo4jPropertyGraphStore,
    client: Any,
    lookup: Any,
    *,
    batch: int = 20000,
) -> int:
    """Global LINKS_TO pass: MERGE doc->doc edges for resolvable in-corpus targets.

    Cheap (no embedding) and idempotent, so it can run after the embed pass —
    or standalone via ``links_only`` — and resolve links across the whole corpus.
    """
    scope = profile.index.scope
    ensure_document_id_index(store)  # MERGE matches :Document(id) — must be indexed or it scans
    pending: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    n_html = n_pairs = n_no_links = 0
    for row in iter_source_rows(scope, client=client):
        url = row.get("url")
        if not url or "html" not in (row.get("content_type") or "").lower():
            continue
        if scope.limit and n_html >= scope.limit:
            break
        n_html += 1
        if n_html % 5000 == 0:
            _log.info("links pass: %d html docs scanned, %d pairs so far", n_html, n_pairs)
        try:
            html = lookup(url)
            if not html:
                continue
            src = doc_id_for(url)
            links = extract_links(html, url)
        except Exception as exc:  # one bad page must not abort the whole links pass
            _log.warning("links pass: skipping %s — %s: %s", url, type(exc).__name__, exc)
            continue
        if not links:  # no main-content-wrapper or no content links (chrome-only page)
            n_no_links += 1
            continue
        for link in links:
            key = (src, link.tgt_doc_id)
            if key in seen:
                continue
            seen.add(key)
            pending.append({"s": src, "t": link.tgt_doc_id, "props": _link_props(link)})
            n_pairs += 1
            if len(pending) >= batch:
                _merge_links_batch(store, pending)
                pending = []
    _merge_links_batch(store, pending)
    _log.info(
        "links pass: %d html docs, %d pairs, %d docs with no main-content links",
        n_html, n_pairs, n_no_links,
    )
    return n_pairs


@register_index("property_graph")
def build_property_graph_index(
    profile: IndexProfile,
    *,
    mongo_client: Any = None,
    html_lookup: Any = None,
    embed_model: Any = None,
    reset: bool = False,
    resume: bool = True,
    flush_chunks: int = 4000,
    pause_every_docs: int = 0,
    pause_seconds: float = 60.0,
    links_only: bool = False,
    reset_links: bool = False,
) -> PropertyGraphIndex:
    """Build the hierarchical PropertyGraphIndex in Neo4j from Mongo (batched, resumable).

    The chunk/embedding work is streamed and committed in flushes of
    ~``flush_chunks`` chunks, so a crash loses at most one flush and a re-run
    (``resume=True``) skips documents already materialized. ``LINKS_TO`` edges are
    a final idempotent pass that MERGEs doc->doc edges whose target is in-corpus.
    Pass ``links_only=True`` to (re)build just the link edges over an existing graph.
    Pass ``reset_links=True`` to delete the existing ``LINKS_TO`` edges first (chunks
    and vectors are untouched) — use it with ``links_only=True`` to re-extract the link
    graph after a links.py change without re-embedding.
    """
    embed = embed_model or _embed_model(profile.index.embed_model)
    store = neo4j_store_from_env()
    if reset:
        store.structured_query("MATCH (n) DETACH DELETE n")

    owned = mongo_client is None
    client = MongoClient(MONGO_URI) if owned else mongo_client
    try:
        lookup = html_lookup or mongo_html_lookup(client)
        if not links_only:
            done = _existing_doc_ids(store) if (resume and not reset) else set()
            if done:
                _log.info("resume: %d docs already built — skipping them", len(done))
            _embed_pass(
                profile, store, client, lookup, embed,
                done=done, flush_chunks=flush_chunks,
                pause_every_docs=pause_every_docs, pause_seconds=pause_seconds,
            )
        if reset_links:
            _log.info("reset_links: deleting existing LINKS_TO edges (chunks/vectors untouched)")
            _delete_links(store)
        n_pairs = _links_pass(profile, store, client, lookup)
        _log.info("links pass: %d candidate pairs (kept where target in-corpus)", n_pairs)
    finally:
        if owned:
            client.close()

    return PropertyGraphIndex.from_existing(
        property_graph_store=store,
        embed_model=embed,
        llm=MockLLM(),  # no LLM extraction; avoids OpenAI default-extractor resolution
        kg_extractors=[],
        embed_kg_nodes=False,
    )


@register_open("property_graph")
def open_index(profile: IndexProfile | None = None) -> PropertyGraphIndex:
    """Open the existing Neo4j PropertyGraphIndex without rebuilding (no re-embed)."""
    return PropertyGraphIndex.from_existing(
        property_graph_store=neo4j_store_from_env(),
        embed_model=_embed_model(profile.index.embed_model if profile else None),
        llm=MockLLM(),
        kg_extractors=[],
        embed_kg_nodes=False,
    )


# Document-node projection shared by the retrieval queries: the reference
# metadata (title/topic_path/committee/reference_number/source_type/category)
# that citations, reference cards, and exports need — not just a URL.
_DOC_PROJECTION = (
    "{.id, .source_url, .title, .topic_path, .committee, .reference_number, "
    ".source_type, .category, .doc_type, .audience, .site_topic, .topic_hubs, "
    ".tree_parent_id, .tree_depth, .tree_path, .tree_ancestor_ids}"
)

def _edge_label(edge_types: list[str]) -> str:
    """Map the profile's edge_types (e.g. ['links_to']) to a safe Cypher rel label.

    The label is interpolated into the expansion query (Cypher cannot
    parametrize relationship types), so it is strictly validated.
    """
    raw = (edge_types[0] if edge_types else "links_to").upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", raw):
        raise ValueError(f"invalid graph edge type {raw!r}")
    return raw


class HierarchicalPGRetriever(BaseRetriever):
    """Chunk-centric retriever: vector hit on :Chunk nodes -> small-to-big merge
    (return the parent chunk when present) + source-doc provenance, in one Cypher.

    Neo4j's default `entity` vector index covers only __Entity__ nodes; our
    retrievable units are :Chunk, so we query the dedicated chunk index directly
    (CHUNK_VECTOR_INDEX) and expand HAS_CHUNK (-> doc) / PARENT_OF (-> parent).

    Source-category steering (see docs/RETRIEVAL.md, all generic — no category is
    special-cased in code):

    - **filter** (``categories`` / :meth:`with_categories`): restrict results to
      the given categories. The vector query oversamples (``k * oversample``)
      and filters on the persisted ``:Document.category`` in Cypher, so the
      final top-k is drawn from a pool the filter didn't starve.
    - **quota** (``category_quota``): guarantee slots in the final k per
      category (e.g. 2 × scientific_guideline), stratifying the oversampled
      pool. Membership changes; score order is preserved.
    - **link expansion** (``graph.expand``): follow typed link edges
      (``LINKS_TO``) from the vector-hit documents to linked documents —
      optionally restricted to ``graph.expand_categories`` and the edge's
      ``link_context``/``document_type`` — and append the best-matching chunk of
      up to ``graph.max_expand`` linked docs. Additive: expanded nodes carry
      ``retrieval_origin="link_expansion"`` + ``linked_from`` provenance and
      never displace a vector hit.
    - **ancestor context** (``graph.ancestors``): append the best-matching
      chunk of up to ``graph.max_ancestors`` site-tree ancestors of the
      vector-hit documents (nearest-first), so the agent sees each hit's place
      in the root-anchored hierarchy with content. Reads the persisted
      ``tree_ancestor_ids`` (``scripts/backfill_site_tree.py``) — a lookup,
      not a traversal; stamped ``retrieval_origin="tree_ancestor"``. Every
      retrieved node additionally carries ``tree_path``/``tree_depth`` (its
      level), shown to the LLM by ``format_nodes``.

    Category filter/quota/expansion-restriction require ``:Document.category``
    (stamped at ingest; backfill existing graphs with
    ``scripts/backfill_doc_categories.py``); ancestor context requires the
    site-tree backfill.
    """

    _QUERY = (
        f"CALL db.index.vector.queryNodes('{CHUNK_VECTOR_INDEX}', $k, $q) YIELD node, score "
        f"WITH node, score, head([(node)<-[:HAS_CHUNK]-(d) | d {_DOC_PROJECTION}]) AS doc "
        "WHERE $cats IS NULL OR doc.category IN $cats "
        "RETURN node.id AS id, node.text AS text, score, doc, "
        "head([(node)<-[:PARENT_OF]-(p) | {id: p.id, text: p.text}]) AS parent"
    )

    # Expansion: seeds -> linked docs (edge-property + target-category filtered)
    # -> each linked doc's best chunk vs the query (+ its parent for small-to-big).
    # vector.similarity.cosine is rescaled to (1+cos)/2 to match the [0,1] score
    # range db.index.vector.queryNodes returns for cosine indexes.
    @staticmethod
    def _expand_query(edge_label: str, max_hops: int) -> str:
        hops = max(int(max_hops), 1)
        return (
            "UNWIND $seed_ids AS sid "
            f"MATCH p = (s:Document {{id: sid}})-[:{edge_label}*1..{hops}]->(t:Document) "
            "WHERE NOT t.id IN $seed_ids "
            "AND (size($cats) = 0 OR t.category IN $cats) "
            "AND ALL(e IN relationships(p) WHERE "
            "(size($contexts) = 0 OR e.link_context IN $contexts) "
            "AND (size($doctypes) = 0 OR e.document_type IN $doctypes)) "
            "WITH t, collect(DISTINCT sid) AS linked_from "
            "MATCH (t)-[:HAS_CHUNK]->(c:Chunk) WHERE c.embedding IS NOT NULL "
            "WITH t, linked_from, c, "
            "(1.0 + vector.similarity.cosine(c.embedding, $q)) / 2.0 AS score, "
            "head([(c)<-[:PARENT_OF]-(par) | {id: par.id, text: par.text}]) AS parent "
            "ORDER BY score DESC "
            "WITH t, linked_from, "
            "collect({id: c.id, text: c.text, score: score, parent: parent})[0] AS best "
            f"RETURN t {_DOC_PROJECTION} AS doc, linked_from, best "
            "ORDER BY best.score DESC LIMIT $max_expand"
        )

    # Ancestor context: the seeds' persisted tree_ancestor_ids -> each ancestor
    # doc's best chunk vs the query (same best-chunk + (1+cos)/2 + small-to-big
    # pattern as _expand_query). No traversal — the ancestor chain is a pure
    # property lookup stamped by scripts/backfill_site_tree.py.
    _ANCESTOR_QUERY = (
        "UNWIND $ids AS did "
        "MATCH (d:Document {id: did})-[:HAS_CHUNK]->(c:Chunk) "
        "WHERE c.embedding IS NOT NULL "
        "WITH d, c, "
        "(1.0 + vector.similarity.cosine(c.embedding, $q)) / 2.0 AS score, "
        "head([(c)<-[:PARENT_OF]-(par) | {id: par.id, text: par.text}]) AS parent "
        "ORDER BY score DESC "
        "WITH d, collect({id: c.id, text: c.text, score: score, parent: parent})[0] AS best "
        f"RETURN d {_DOC_PROJECTION} AS doc, best"
    )

    def __init__(
        self,
        store: Neo4jPropertyGraphStore,
        embed_model: Any,
        *,
        k: int = 10,
        merge: bool = True,
        oversample: int = 4,
        category_quota: dict[str, int] | None = None,
        graph: Any = None,
        categories: list[str] | None = None,
    ):
        self._store = store
        self._embed = embed_model
        self._k = k
        self._merge = merge
        self._oversample = max(int(oversample), 1)
        self._quota = dict(category_quota or {})
        self._graph = graph  # GraphRetrievalConfig or None (expansion off)
        self._categories = list(categories) if categories else None
        super().__init__()

    @property
    def store(self) -> Neo4jPropertyGraphStore:
        """The backing graph store (used by tools that need their own queries,
        e.g. ``topic_context``'s subgraph reader)."""
        return self._store

    @property
    def embed_model(self) -> Any:
        """The retriever's query embedder (shared with ``topic_context`` ranking)."""
        return self._embed

    def with_categories(self, categories: list[str] | None) -> HierarchicalPGRetriever:
        """A view of this retriever restricted to ``categories`` (shares the store).

        This is the per-call steering seam ``ema_search`` uses: the agent's
        ``source_category`` argument (or a routing rule in ``filter`` mode)
        becomes a filtered view, leaving the shared retriever untouched.
        """
        return HierarchicalPGRetriever(
            self._store,
            self._embed,
            k=self._k,
            merge=self._merge,
            oversample=self._oversample,
            category_quota=self._quota,
            graph=self._graph,
            categories=list(categories) if categories else None,
        )

    def _node_from_row(
        self, doc: dict, *, chunk_id: str, matched_id: str, text: str, score: float,
        extra: dict[str, Any] | None = None,
    ) -> NodeWithScore:
        from harness.retrieval.doc_categories import classify_source

        doc = doc or {}
        source_url = doc.get("source_url") or ""
        topic_path = doc.get("topic_path") or ""
        meta = {
            "source_url": source_url,
            "doc_id": doc.get("id") or "",
            "title": doc.get("title") or "",
            "topic_path": topic_path,
            "committee": doc.get("committee") or "",
            "reference_number": doc.get("reference_number") or "",
            "source_type": doc.get("source_type") or "",
            "category": doc.get("category") or classify_source(source_url, topic_path),
            # Authoritative EMA labels (None when the doc has none) — see
            # docs/RETRIEVAL.md §7 "Authoritative enrichment".
            "doc_type": doc.get("doc_type"),
            "audience": doc.get("audience"),
            "site_topic": doc.get("site_topic"),
            # Precomputed topic-subgraph memberships (docs/next/topic_subgraphs.md)
            # — [] until scripts/manage_topic_hubs.py build + propagate ran.
            "topic_hubs": list(doc.get("topic_hubs") or []),
            # Site-tree place (scripts/backfill_site_tree.py) — the doc's level
            # in the root-anchored tree; empty/None until the backfill ran.
            "tree_path": doc.get("tree_path") or "",
            "tree_depth": doc.get("tree_depth"),
            "tree_ancestor_ids": list(doc.get("tree_ancestor_ids") or []),
            # chunk_id = the node actually returned (parent after small-to-big
            # merge); matched_chunk = the leaf the vector/similarity hit landed on.
            "chunk_id": chunk_id,
            "matched_chunk": matched_id,
            "retrieval_origin": "vector",
        }
        if extra:
            meta.update(extra)
        return NodeWithScore(
            node=TextNode(id_=chunk_id, text=text, metadata=meta), score=float(score)
        )

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        qvec = self._embed.get_query_embedding(query_bundle.query_str)
        # Oversample whenever a filter or quota must choose from a pool; a plain
        # retrieve keeps the exact-k query (no behavior change for unsteered use).
        steering = bool(self._categories) or bool(self._quota)
        pool_k = self._k * self._oversample if steering else self._k
        rows = self._store.structured_query(
            self._QUERY, param_map={"k": pool_k, "q": qvec, "cats": self._categories}
        )
        seen: set[str] = set()
        out: list[NodeWithScore] = []
        for r in rows:
            parent = r.get("parent")
            if self._merge and parent and parent.get("text"):
                nid, text = parent["id"], parent["text"]  # small-to-big: return the parent
            else:
                nid, text = r["id"], r.get("text") or ""
            if nid in seen:
                continue
            seen.add(nid)
            out.append(
                self._node_from_row(
                    r.get("doc"), chunk_id=nid, matched_id=r["id"],
                    text=text, score=r["score"],
                )
            )
        if self._quota:
            from harness.retrieval.steering import stratify_by_category

            out = stratify_by_category(out, self._quota, self._k)
        else:
            out = out[: self._k]
        graph = self._graph
        vector_hits = list(out)
        if graph is not None and getattr(graph, "expand", False) and out:
            out.extend(self._expand(vector_hits, qvec, seen))
        if graph is not None and getattr(graph, "ancestors", False) and vector_hits:
            out.extend(self._expand_ancestors(vector_hits, qvec, seen, out))
        return out

    def _expand(
        self, nodes: list[NodeWithScore], qvec: list[float], seen: set[str]
    ) -> list[NodeWithScore]:
        """Link-graph expansion pass over the vector hits' source documents."""
        graph = self._graph
        seed_ids = list(
            dict.fromkeys(n.node.metadata.get("doc_id") for n in nodes if n.node.metadata.get("doc_id"))
        )
        if not seed_ids:
            return []
        query = self._expand_query(_edge_label(graph.edge_types), graph.max_hops)
        rows = self._store.structured_query(
            query,
            param_map={
                "seed_ids": seed_ids,
                "q": qvec,
                "cats": list(graph.expand_categories or []),
                "contexts": list(graph.link_contexts or []),
                "doctypes": list(graph.document_types or []),
                "max_expand": int(graph.max_expand),
            },
        )
        out: list[NodeWithScore] = []
        for r in rows:
            best = r.get("best") or {}
            parent = best.get("parent")
            if self._merge and parent and parent.get("text"):
                nid, text = parent["id"], parent["text"]
            else:
                nid, text = best.get("id"), best.get("text") or ""
            if not nid or nid in seen:
                continue
            seen.add(nid)
            out.append(
                self._node_from_row(
                    r.get("doc"), chunk_id=nid, matched_id=best.get("id") or nid,
                    text=text, score=best.get("score") or 0.0,
                    extra={
                        "retrieval_origin": "link_expansion",
                        "linked_from": list(r.get("linked_from") or []),
                    },
                )
            )
        if out:
            _log.debug("link expansion added %d node(s) from %d seed doc(s)", len(out), len(seed_ids))
        return out

    def _expand_ancestors(
        self,
        seeds: list[NodeWithScore],
        qvec: list[float],
        seen: set[str],
        retrieved: list[NodeWithScore],
    ) -> list[NodeWithScore]:
        """Tree-ancestor context pass: best chunk of the seeds' ancestor docs.

        Ancestors come from the seeds' persisted ``tree_ancestor_ids`` metadata
        (root→nearest, stamped by ``scripts/backfill_site_tree.py``) — a pure
        lookup, no traversal. Nearest-first across seeds, capped at
        ``graph.max_ancestors``, additive, stamped
        ``retrieval_origin="tree_ancestor"`` + ``linked_from`` (the seed docs
        the ancestor belongs to). No-op when the backfill hasn't run.
        """
        graph = self._graph
        already = {
            n.node.metadata.get("doc_id")
            for n in retrieved
            if n.node.metadata.get("doc_id")
        }
        # nearest-first per seed (stored root→nearest), deduped across seeds
        contributors: dict[str, list[str]] = {}
        ordered: list[str] = []
        for n in seeds:
            seed_id = n.node.metadata.get("doc_id") or ""
            for anc in reversed(list(n.node.metadata.get("tree_ancestor_ids") or [])):
                if anc in already:
                    continue
                if anc not in contributors:
                    contributors[anc] = []
                    ordered.append(anc)
                if seed_id and seed_id not in contributors[anc]:
                    contributors[anc].append(seed_id)
        ancestor_ids = ordered[: max(int(getattr(graph, "max_ancestors", 3)), 1)]
        if not ancestor_ids:
            return []
        rows = self._store.structured_query(
            self._ANCESTOR_QUERY, param_map={"ids": ancestor_ids, "q": qvec}
        )
        by_id = {(r.get("doc") or {}).get("id"): r for r in rows}
        out: list[NodeWithScore] = []
        for anc in ancestor_ids:  # preserve nearest-first order
            r = by_id.get(anc)
            if r is None:
                continue
            best = r.get("best") or {}
            parent = best.get("parent")
            if self._merge and parent and parent.get("text"):
                nid, text = parent["id"], parent["text"]
            else:
                nid, text = best.get("id"), best.get("text") or ""
            if not nid or nid in seen:
                continue
            seen.add(nid)
            out.append(
                self._node_from_row(
                    r.get("doc"), chunk_id=nid, matched_id=best.get("id") or nid,
                    text=text, score=best.get("score") or 0.0,
                    extra={
                        "retrieval_origin": "tree_ancestor",
                        "linked_from": contributors.get(anc, []),
                    },
                )
            )
        if out:
            _log.debug("tree ancestors added %d node(s)", len(out))
        return out


@register_retriever("hierarchical")
def build_hierarchical_retriever(
    profile: IndexProfile, index: PropertyGraphIndex, **kw: Any
) -> BaseRetriever:
    retrieval = profile.retrieval
    return HierarchicalPGRetriever(
        index.property_graph_store,
        # configure + return the profile's embedder; index._embed_model is None
        # after from_existing
        _embed_model(profile.index.embed_model),
        k=retrieval.k,
        merge=retrieval.merge,
        oversample=retrieval.oversample,
        category_quota=retrieval.category_quota,
        graph=retrieval.graph if (retrieval.graph.expand or retrieval.graph.ancestors) else None,
    )

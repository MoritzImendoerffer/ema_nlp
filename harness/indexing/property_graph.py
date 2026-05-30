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
from typing import Any

from llama_index.core import PropertyGraphIndex
from llama_index.core.graph_stores.types import ChunkNode, EntityNode, Relation
from llama_index.core.llms import MockLLM
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeRelationship, NodeWithScore, QueryBundle, TextNode
from llama_index.graph_stores.neo4j import Neo4jPropertyGraphStore

from harness.indexing.ingest import IngestedDoc, ingest
from harness.indexing.profiles import IndexProfile
from harness.indexing.registry import register_index, register_retriever

_log = logging.getLogger(__name__)

# Dedicated vector index over Chunk nodes (Neo4j auto-creates `entity` only for
# __Entity__ nodes; our retrievable units are :Chunk, so we index them ourselves).
CHUNK_VECTOR_INDEX = "ema_chunk_embedding"


def neo4j_store_from_env() -> Neo4jPropertyGraphStore:
    return Neo4jPropertyGraphStore(
        username=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "ema_nlp_dev_pw"),
        url=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
    )


def _embed_model() -> Any:
    from llama_index.core import Settings

    from harness.providers import configure_embed_model

    configure_embed_model()
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


def to_graph(
    docs: list[IngestedDoc],
) -> tuple[list[EntityNode], list[ChunkNode], list[Relation]]:
    """Map the ingestion IR to PropertyGraph nodes + relations (no embedding)."""
    doc_ids = {d.doc_id for d in docs}
    entities: list[EntityNode] = []
    chunks: list[ChunkNode] = []
    relations: list[Relation] = []
    for d in docs:
        entities.append(
            EntityNode(
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
                    }
                ),
            )
        )
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
                    Relation(label="LINKS_TO", source_id=d.doc_id, target_id=link.tgt_doc_id)
                )
    return entities, chunks, relations


@register_index("property_graph")
def build_property_graph_index(
    profile: IndexProfile,
    *,
    mongo_client: Any = None,
    html_lookup: Any = None,
    embed_model: Any = None,
    reset: bool = False,
) -> PropertyGraphIndex:
    """Build the hierarchical PropertyGraphIndex in Neo4j from the Mongo subset."""
    embed = embed_model or _embed_model()
    store = neo4j_store_from_env()
    if reset:
        store.structured_query("MATCH (n) DETACH DELETE n")

    docs = ingest(profile, mongo_client=mongo_client, html_lookup=html_lookup)
    entities, chunks, relations = to_graph(docs)

    if chunks:
        embeddings = embed.get_text_embedding_batch(
            [c.text for c in chunks], show_progress=True
        )
        for chunk, emb in zip(chunks, embeddings):
            chunk.embedding = emb

    store.upsert_nodes(entities + chunks)
    if relations:
        store.upsert_relations(relations)
    if chunks and chunks[0].embedding:
        ensure_chunk_vector_index(store, len(chunks[0].embedding))
    _log.info(
        "property_graph build: %d docs, %d entities, %d chunks, %d relations",
        len(docs), len(entities), len(chunks), len(relations),
    )

    return PropertyGraphIndex.from_existing(
        property_graph_store=store,
        embed_model=embed,
        llm=MockLLM(),  # no LLM extraction; avoids OpenAI default-extractor resolution
        kg_extractors=[],
        embed_kg_nodes=False,
    )


def open_index(profile: IndexProfile | None = None) -> PropertyGraphIndex:
    """Open the existing Neo4j PropertyGraphIndex without rebuilding (no re-embed)."""
    return PropertyGraphIndex.from_existing(
        property_graph_store=neo4j_store_from_env(),
        embed_model=_embed_model(),
        llm=MockLLM(),
        kg_extractors=[],
        embed_kg_nodes=False,
    )


class HierarchicalPGRetriever(BaseRetriever):
    """Chunk-centric retriever: vector hit on :Chunk nodes -> small-to-big merge
    (return the parent chunk when present) + source-doc provenance, in one Cypher.

    Neo4j's default `entity` vector index covers only __Entity__ nodes; our
    retrievable units are :Chunk, so we query the dedicated chunk index directly
    (CHUNK_VECTOR_INDEX) and expand HAS_CHUNK (-> doc) / PARENT_OF (-> parent).
    """

    _QUERY = (
        f"CALL db.index.vector.queryNodes('{CHUNK_VECTOR_INDEX}', $k, $q) YIELD node, score "
        "RETURN node.id AS id, node.text AS text, score, "
        "head([(node)<-[:HAS_CHUNK]-(d) | d.source_url]) AS source_url, "
        "head([(node)<-[:HAS_CHUNK]-(d) | d.id]) AS doc_id, "
        "head([(node)<-[:PARENT_OF]-(p) | {id: p.id, text: p.text}]) AS parent"
    )

    def __init__(
        self, store: Neo4jPropertyGraphStore, embed_model: Any, *, k: int = 10, merge: bool = True
    ):
        self._store = store
        self._embed = embed_model
        self._k = k
        self._merge = merge
        super().__init__()

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        qvec = self._embed.get_query_embedding(query_bundle.query_str)
        rows = self._store.structured_query(self._QUERY, param_map={"k": self._k, "q": qvec})
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
            meta = {
                "source_url": r.get("source_url"),
                "doc_id": r.get("doc_id"),
                "matched_chunk": r["id"],
            }
            out.append(
                NodeWithScore(node=TextNode(id_=nid, text=text, metadata=meta), score=float(r["score"]))
            )
        return out


@register_retriever("hierarchical")
def build_hierarchical_retriever(
    profile: IndexProfile, index: PropertyGraphIndex, **kw: Any
) -> BaseRetriever:
    return HierarchicalPGRetriever(
        index.property_graph_store,
        _embed_model(),  # configure + return BGE; index._embed_model is None after from_existing
        k=profile.retrieval.k,
        merge=profile.retrieval.merge,
    )

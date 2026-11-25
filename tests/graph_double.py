"""An in-memory corpus graph that models deletion (work unit 27, TASK-005).

The older doubles (``_FakeStore``, ``_RecordingStore`` in
``tests/test_indexing_property_graph.py``) record a query and return ``[]``. On them a
test of "no chunk of the first build remains" passes whatever the code does. This double
implements the operations of :class:`harness.indexing.graph_ops.CorpusGraph` on dicts,
so a delete that the code does not make leaves nodes behind and the test fails.

It mirrors two behaviours of ``Neo4jPropertyGraphStore.upsert_nodes``
(llama-index-graph-stores-neo4j 0.7.0): nodes are merged by id with ``SET +=`` (a
property absent from the new node keeps its old value), and chunks are written before
entities. ``fail_after_chunks`` raises between the two, as a crash would.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from llama_index.core.graph_stores.types import ChunkNode, EntityNode

from harness.indexing.graph_ops import DocState


@dataclass
class Node:
    id: str
    labels: set[str]
    properties: dict[str, Any] = field(default_factory=dict)
    text: str | None = None
    embedding: list[float] | None = None


class InMemoryCorpusGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: set[tuple[str, str, str]] = set()  # (label, source_id, target_id)
        self.queries: list[str] = []
        self.fail_after_chunks = False
        self.upserted_chunk_ids: list[str] = []  # every chunk id written, in order

    # ── the store side ──────────────────────────────────────────────────────────
    def structured_query(self, query: str, param_map: dict[str, Any] | None = None) -> list:
        self.queries.append(query)
        return []

    def add_node(self, node_id: str, labels: set[str], **properties: Any) -> None:
        self.nodes[node_id] = Node(node_id, set(labels), dict(properties))

    def _merge(self, node_id: str, labels: set[str], props: dict[str, Any], text=None, emb=None) -> None:
        node = self.nodes.get(node_id)
        if node is None:
            node = self.nodes[node_id] = Node(node_id, set(labels))
        node.labels |= labels
        node.properties.update({k: v for k, v in props.items() if v is not None})
        if text is not None:
            node.text = text
        if emb is not None:
            node.embedding = emb

    def upsert(self, nodes: list[Any], relations: list[Any]) -> None:
        chunks = [n for n in nodes if isinstance(n, ChunkNode)]
        entities = [n for n in nodes if isinstance(n, EntityNode)]
        for c in chunks:
            self._merge(c.id, {"__Node__", "Chunk"}, c.properties, text=c.text, emb=c.embedding)
            self.upserted_chunk_ids.append(c.id)
        if self.fail_after_chunks:
            raise RuntimeError("simulated crash between the chunk and the entity upsert")
        for e in entities:
            self._merge(e.id, {"__Node__", "__Entity__", e.label}, e.properties)
        for r in relations:
            if r.source_id in self.nodes and r.target_id in self.nodes:
                self.edges.add((r.label, r.source_id, r.target_id))

    # ── the named operations of CorpusGraph ─────────────────────────────────────
    def _docs(self) -> list[Node]:
        return [n for n in self.nodes.values() if "Document" in n.labels]

    def chunks_of(self, doc_id: str) -> list[Node]:
        ids = {t for (label, s, t) in self.edges if label == "HAS_CHUNK" and s == doc_id}
        return [self.nodes[i] for i in ids if i in self.nodes and "Chunk" in self.nodes[i].labels]

    def document_states(self) -> dict[str, DocState]:
        out = {}
        for d in self._docs():
            p = d.properties
            out[d.id] = DocState(
                doc_id=d.id,
                source_url=p.get("source_url"),
                parser=p.get("parser"),
                parser_version=p.get("parser_version"),
                text_sha256=p.get("text_sha256"),
                has_chunks=bool(self.chunks_of(d.id)),
            )
        return out

    def _detach_delete(self, node_ids: set[str]) -> None:
        for i in node_ids:
            self.nodes.pop(i, None)
        self.edges = {e for e in self.edges if e[1] not in node_ids and e[2] not in node_ids}

    def delete_document_chunks(self, doc_ids: Sequence[str], *, batch_rows: int = 1) -> None:
        self._detach_delete({c.id for d in doc_ids for c in self.chunks_of(d)})

    def stamp_parse_identity(self, rows: Sequence[dict[str, Any]]) -> int:
        for r in rows:
            node = self.nodes.get(r["id"])
            if node is not None and "Document" in node.labels:
                node.properties.update(
                    parser=r["parser"], parser_version=r["parser_version"], text_sha256=r["text_sha256"]
                )
        return len(rows)

    def delete_documents(self, doc_ids: Sequence[str], *, batch_rows: int = 1) -> None:
        self.delete_document_chunks(doc_ids)
        self._detach_delete(set(doc_ids))

    def reset_corpus(self, *, batch_rows: int = 1) -> None:
        self._detach_delete({n.id for n in self.nodes.values() if n.labels & {"Chunk", "Document"}})

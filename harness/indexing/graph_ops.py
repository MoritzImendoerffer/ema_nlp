"""The writes and deletes the build makes on the corpus graph, as named operations.

Before 2026-11-25 the build only added: a resumed build skipped every document that had
a chunk, and ``--reset`` ran ``MATCH (n) DETACH DELETE n`` on 7.5 million nodes in one
transaction. A refreshable graph has to delete a changed document's chunks, delete a
document whose URL left the source, and reset in batches. Those deletes live here, in
one place, for two reasons:

- **They can be tested.** The old test doubles of the store record a query and return
  ``[]`` (``tests/test_indexing_property_graph.py``), so a test of "no chunk of the first
  build remains" passed whatever the code did. The build talks to :class:`CorpusGraph`;
  ``tests/graph_double.py`` implements the same operations on dicts and models deletion.
  The Cypher below runs on a real Neo4j in ``tests/test_graph_ops_neo4j.py``.
- **They must not scan.** ``Neo4jPropertyGraphStore.delete`` runs ``MATCH (n) WHERE n.id
  IN $ids DETACH DELETE n`` (llama-index-graph-stores-neo4j 0.7.0,
  ``neo4j_property_graph.py:738-770``), which plans as ``AllNodesScan`` over 7.5 million
  nodes on each call. Every query here starts from ``:Document {id: ...}``, which the
  range index ``ema_document_id`` serves (``NodeIndexSeek``, exploration of work unit 27,
  section 5.1).

``CALL { ... } IN TRANSACTIONS`` needs an autocommit transaction, which
``structured_query`` gives (verified for ``_delete_links`` in ``property_graph.py``).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

# Rows per inner transaction. Provisional until the measurement on a throwaway Neo4j
# (TASK-014 of work unit 27) fixes them. A leaf chunk carries about 2,000 characters
# and 1,024 floats; the live server allows 1.40 GiB for all transactions together.
CHUNK_DELETE_BATCH_ROWS = 10_000
RESET_BATCH_ROWS = 10_000
# Documents per UNWIND when stamping properties or deleting documents.
DOC_BATCH = 1_000


@dataclass(frozen=True)
class DocState:
    """What the graph records about one ``:Document``."""

    doc_id: str
    source_url: str | None
    parser: str | None
    parser_version: str | None
    text_sha256: str | None
    has_chunks: bool

    @property
    def stamped(self) -> bool:
        """True once the document records the parse it was built from."""
        return self.text_sha256 is not None


def _batches(items: Sequence[Any], size: int) -> Iterable[list[Any]]:
    for i in range(0, len(items), size):
        yield list(items[i : i + size])


def _rows(n: int) -> int:
    n = int(n)
    if n < 1:
        raise ValueError(f"batch size must be at least 1, got {n}")
    return n


DOCUMENT_STATES_QUERY = (
    "MATCH (d:Document) "
    "RETURN d.id AS id, d.source_url AS source_url, d.parser AS parser, "
    "d.parser_version AS parser_version, d.text_sha256 AS text_sha256, "
    "EXISTS { (d)-[:HAS_CHUNK]->(:Chunk) } AS has_chunks"
)

STAMP_QUERY = (
    "UNWIND $rows AS r "
    "MATCH (d:Document {id: r.id}) "
    "SET d.parser = r.parser, d.parser_version = r.parser_version, d.text_sha256 = r.text_sha256"
)


def delete_chunks_query(batch_rows: int) -> str:
    """Every chunk of the given documents, at every level, with its edges."""
    return (
        "UNWIND $ids AS doc_id "
        "MATCH (d:Document {id: doc_id})-[:HAS_CHUNK]->(c:Chunk) "
        f"CALL {{ WITH c DETACH DELETE c }} IN TRANSACTIONS OF {_rows(batch_rows)} ROWS"
    )


DELETE_DOCUMENTS_QUERY = (
    "UNWIND $ids AS doc_id "
    "MATCH (d:Document {id: doc_id}) "
    "DETACH DELETE d"
)


def reset_queries(batch_rows: int) -> list[str]:
    """Delete the corpus: chunks first, then documents. Other nodes stay."""
    n = _rows(batch_rows)
    return [
        f"MATCH (c:Chunk) CALL {{ WITH c DETACH DELETE c }} IN TRANSACTIONS OF {n} ROWS",
        f"MATCH (d:Document) CALL {{ WITH d DETACH DELETE d }} IN TRANSACTIONS OF {n} ROWS",
    ]


class CorpusGraph:
    """The corpus graph as the build sees it: upserts plus the named deletes and stamps.

    Wraps a ``Neo4jPropertyGraphStore`` (or anything with ``upsert_nodes``,
    ``upsert_relations`` and ``structured_query``).
    """

    def __init__(self, store: Any) -> None:
        self.store = store

    def structured_query(self, query: str, param_map: dict[str, Any] | None = None) -> Any:
        """Pass a query through to the store (vector index creation and the like)."""
        return self.store.structured_query(query, param_map=param_map)

    def upsert(self, nodes: list[Any], relations: list[Any]) -> None:
        """Write nodes, then relations. The store writes chunks before entities."""
        self.store.upsert_nodes(nodes)
        if relations:
            self.store.upsert_relations(relations)

    def document_states(self) -> dict[str, DocState]:
        """Every ``:Document`` with its parse identity and whether it has chunks."""
        rows = self.store.structured_query(DOCUMENT_STATES_QUERY) or []
        return {
            r["id"]: DocState(
                doc_id=r["id"],
                source_url=r.get("source_url"),
                parser=r.get("parser"),
                parser_version=r.get("parser_version"),
                text_sha256=r.get("text_sha256"),
                has_chunks=bool(r.get("has_chunks")),
            )
            for r in rows
            if r.get("id")
        }

    def delete_document_chunks(
        self, doc_ids: Sequence[str], *, batch_rows: int = CHUNK_DELETE_BATCH_ROWS
    ) -> None:
        """Delete every chunk of these documents. The ``:Document`` nodes stay."""
        for ids in _batches(list(doc_ids), DOC_BATCH):
            self.store.structured_query(delete_chunks_query(batch_rows), param_map={"ids": ids})

    def stamp_parse_identity(self, rows: Sequence[dict[str, Any]]) -> int:
        """Set ``parser``, ``parser_version`` and ``text_sha256``; touch no chunk.

        Each row is ``{id, parser, parser_version, text_sha256}``.
        """
        for batch in _batches(list(rows), DOC_BATCH):
            self.store.structured_query(STAMP_QUERY, param_map={"rows": batch})
        return len(rows)

    def delete_documents(
        self, doc_ids: Sequence[str], *, batch_rows: int = CHUNK_DELETE_BATCH_ROWS
    ) -> None:
        """Delete documents with their chunks and every edge (``LINKS_TO`` included)."""
        ids = list(doc_ids)
        self.delete_document_chunks(ids, batch_rows=batch_rows)
        for batch in _batches(ids, DOC_BATCH):
            self.store.structured_query(DELETE_DOCUMENTS_QUERY, param_map={"ids": batch})

    def reset_corpus(self, *, batch_rows: int = RESET_BATCH_ROWS) -> None:
        """Delete every ``:Chunk`` and ``:Document`` in batches; other nodes stay.

        The reset before 2026-11-25 (``MATCH (n) DETACH DELETE n``) deleted 7.5 million
        nodes and 14.6 million relationships in one transaction against a 2 GB heap,
        and the NeoDash dashboard node with them.
        """
        for query in reset_queries(batch_rows):
            self.store.structured_query(query)

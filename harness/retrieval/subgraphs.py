"""Topic-subgraph query side — lookup, not traversal (docs/next/topic_subgraphs.md §4.4).

The build side (:mod:`harness.indexing.subgraphs`) precomputed membership onto
``:Document.topic_hubs``; everything here is an indexed-property read over
those stamps — no multi-hop walk happens at query time. Two consumers:

  - the ``topic_context`` agent tool (:mod:`harness.tools.topic_context`)
    renders the *topic map* (pageable member catalog) and the optional budgeted
    best-chunk context;
  - :class:`SubgraphPolicy` is the recipe surface (``retrieval.subgraph`` keys)
    that configures it.

:class:`TopicSubgraphReader` takes any store with ``structured_query`` (the
live ``Neo4jPropertyGraphStore`` or a fake in tests) + the profile's embed
model; scores reuse the retriever's ``(1+cos)/2`` rescale so they are
comparable with vector-hit scores on the trace.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

SUBGRAPH_CONTEXTS = ("map", "chunks")

#: Projection for topic-map member rows (superset of what the map renders;
#: ``revision`` exists on newly-built graphs only — the formatter falls back to
#: parsing it out of the title on older graphs).
_MEMBER_FIELDS = (
    "d.id AS id, d.source_url AS url, d.title AS title, d.category AS category, "
    "d.doc_type AS doc_type, d.reference_number AS reference_number, "
    "d.revision AS revision, d.source_type AS source_type, "
    "d.topic_path AS topic_path"
)


@dataclass
class SubgraphPolicy:
    """Recipe-configured guardrails for topic-subgraph context (all budgets explicit).

    ``context``: ``map`` = member catalog only; ``chunks`` = catalog + budgeted
    best-chunk texts. ``max_tokens`` bounds the chunk text (est. 4 chars/token);
    ``page_size`` bounds the catalog page — nothing enters the agent context
    unless it asks for the next page. ``hubs`` names the hubs file. There is no
    ``enabled`` flag: the layer runs iff ``topic_context`` is in the recipe's
    toolset — the policy only sets that tool's guardrails.
    """

    hubs: str = "default"
    context: str = "map"
    max_tokens: int = 4000
    page_size: int = 25

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> SubgraphPolicy:
        d = d or {}
        context = str(d.get("context", "map"))
        if context not in SUBGRAPH_CONTEXTS:
            raise ValueError(
                f"subgraph.context {context!r} is not implemented; valid: {list(SUBGRAPH_CONTEXTS)}"
            )
        max_tokens = int(d.get("max_tokens", 4000))
        if max_tokens < 1:
            raise ValueError("subgraph.max_tokens must be >= 1")
        page_size = int(d.get("page_size", 25))
        if page_size < 1:
            raise ValueError("subgraph.page_size must be >= 1")
        return cls(
            hubs=str(d.get("hubs", "default")),
            context=context,
            max_tokens=max_tokens,
            page_size=page_size,
        )


class TopicSubgraphReader:
    """Membership-stamp reads for one graph store (query-time, no walking)."""

    # Grouping: a PDF member is displayed under the HTML member (detail page)
    # that links to it, so revisions of one module read as one item.
    _MEMBERS_QUERY = (
        "MATCH (d:Document) WHERE $key IN d.topic_hubs "
        f"RETURN {_MEMBER_FIELDS}, "
        "head([(p:Document)-[:LINKS_TO]->(d) "
        "WHERE $key IN p.topic_hubs AND p.source_type = 'html' AND p.id <> d.id "
        "| p.id]) AS parent_id"
    )

    _MEMBERSHIPS_QUERY = (
        "MATCH (d:Document) WHERE d.id = $probe OR d.source_url = $probe "
        "RETURN d.topic_hubs AS hubs LIMIT 1"
    )

    # Best chunk per doc for a set of doc ids — used to rank hubs (their seed
    # pages) against the query for the multi-membership pick.
    _DOC_SCORES_QUERY = (
        "UNWIND $ids AS did "
        "MATCH (d:Document {id: did})-[:HAS_CHUNK]->(c:Chunk) "
        "WHERE c.embedding IS NOT NULL "
        "WITH did, max(vector.similarity.cosine(c.embedding, $q)) AS cos "
        "RETURN did AS id, (1.0 + cos) / 2.0 AS score"
    )

    # Member ranking for the map: best-chunk score per member document.
    _MEMBER_SCORES_QUERY = (
        "MATCH (d:Document) WHERE $key IN d.topic_hubs "
        "MATCH (d)-[:HAS_CHUNK]->(c:Chunk) WHERE c.embedding IS NOT NULL "
        "WITH d, max(vector.similarity.cosine(c.embedding, $q)) AS cos "
        "RETURN d.id AS id, (1.0 + cos) / 2.0 AS score"
    )

    # Budgeted text context: best chunk (+ parent for small-to-big) per member,
    # ranked — the retriever's _expand pattern with a membership filter instead
    # of a hop pattern.
    _BEST_CHUNKS_QUERY = (
        "MATCH (d:Document) WHERE $key IN d.topic_hubs "
        "MATCH (d)-[:HAS_CHUNK]->(c:Chunk) WHERE c.embedding IS NOT NULL "
        "WITH d, c, (1.0 + vector.similarity.cosine(c.embedding, $q)) / 2.0 AS score, "
        "head([(c)<-[:PARENT_OF]-(par) | {id: par.id, text: par.text}]) AS parent "
        "ORDER BY score DESC "
        "WITH d, collect({id: c.id, text: c.text, score: score, parent: parent})[0] AS best "
        f"RETURN {_MEMBER_FIELDS}, best "
        "ORDER BY best.score DESC LIMIT $limit"
    )

    def __init__(self, store: Any, embed_model: Any):
        self._store = store
        self._embed = embed_model

    def query_embedding(self, query: str) -> list[float]:
        return self._embed.get_query_embedding(query)

    def members(self, key: str) -> list[dict[str, Any]]:
        """All member rows of one hub's stamped subgraph (with grouping parent)."""
        rows = self._store.structured_query(self._MEMBERS_QUERY, param_map={"key": key})
        return [dict(r) for r in rows]

    def memberships(self, url_or_doc_id: str) -> list[str]:
        """The ``topic_hubs`` stamps of one document (by URL or doc id); [] if none."""
        rows = self._store.structured_query(
            self._MEMBERSHIPS_QUERY, param_map={"probe": url_or_doc_id}
        )
        return list((rows[0].get("hubs") if rows else None) or [])

    def member_scores(self, key: str, qvec: list[float]) -> dict[str, float]:
        """``member doc id -> best-chunk score`` vs the query (map ranking)."""
        rows = self._store.structured_query(
            self._MEMBER_SCORES_QUERY, param_map={"key": key, "q": qvec}
        )
        return {r["id"]: float(r["score"]) for r in rows if r.get("id")}

    def doc_scores(self, doc_ids: list[str], qvec: list[float]) -> dict[str, float]:
        """``doc id -> best-chunk score`` for arbitrary docs (hub seed ranking)."""
        if not doc_ids:
            return {}
        rows = self._store.structured_query(
            self._DOC_SCORES_QUERY, param_map={"ids": list(doc_ids), "q": qvec}
        )
        return {r["id"]: float(r["score"]) for r in rows if r.get("id")}

    def best_chunks(self, key: str, qvec: list[float], *, limit: int) -> list[dict[str, Any]]:
        """Ranked best-chunk rows (doc fields + ``best`` chunk dict) for one hub."""
        rows = self._store.structured_query(
            self._BEST_CHUNKS_QUERY, param_map={"key": key, "q": qvec, "limit": int(limit)}
        )
        return [dict(r) for r in rows]

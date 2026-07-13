"""Topic-subgraph membership build — the offline, bounded qualified walk.

Build side of docs/next/topic_subgraphs.md: for each **confirmed** hub in a
hubs file (:mod:`harness.retrieval.hubs`), walk ``LINKS_TO`` from the seed page
up to ``walk.hops`` hops, keeping only paths whose every node matches the hub's
qualifier (``category`` OR ``doc_type`` — PDFs have ``doc_type``, HTML detail
pages only ``category``), and collect the member documents. Membership rides
the same rails as the other canonical labels: it is stamped into Mongo
``document_metadata`` (``upsert_topic_hubs``, third field group), propagated to
``:Document.topic_hubs`` by ``scripts/propagate_metadata_to_graph.py``, and
joined at ingest so rebuilds keep it.

Precomputation converts the fragile part (multi-hop traversal at query time)
into an inspectable artifact; query time (:mod:`harness.retrieval.subgraphs`)
becomes a property lookup. Everything Cypher-shaped here is stringly-testable
offline; the store calls take any object with ``structured_query`` (the live
``Neo4jPropertyGraphStore`` or a fake in tests).

Staleness rule: memberships must be recomputed after any ``LINKS_TO`` rebuild —
the stamped ``config_hash`` + ``stamped_at`` make violations detectable.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from harness.indexing.chunking import doc_id_for
from harness.retrieval.hubs import HubSpec

_log = logging.getLogger(__name__)

#: provenance.topic_hubs.source value (mirrors the other label groups' sources)
HUB_WALK_SOURCE = "hub_walk"

# Title patterns that mark a *candidate* hub as archive/news-ish — such pages
# out-fan real hubs ("Archive of development of GVP": 126 vs the live GVP
# page's 22) and must be penalized, not rewarded, in hub detection (§2).
_ARCHIVE_TITLE_RE = re.compile(r"\barchiv\w*\b|\bnews\b|\bnewsletter\b|\bevents?\b", re.IGNORECASE)

# Audience badges that mark a candidate as out of human-regulatory scope.
_PENALIZED_AUDIENCE = frozenset({"veterinary", "corporate"})

# Curation link contexts (file components, card/listing grids) signal an
# index-page relationship; inline prose links are weaker evidence of hub-ness.
CURATED_CONTEXTS = ("file_component", "card_or_listing")


def walk_query(hops: int) -> str:
    """The bounded qualified-walk Cypher for one hub seed.

    Every node along the path (not just the endpoint) must match the qualifier
    — otherwise a 2-hop walk happily tunnels through a news page to reach a
    qualified PDF, which is exactly the pollution the qualifier exists to stop.
    Cypher cannot parametrize variable-length bounds, so ``hops`` is validated
    and interpolated (same rule as ``_edge_label`` in property_graph).
    """
    h = int(hops)
    if h < 1:
        raise ValueError(f"walk hops must be >= 1, got {hops}")
    return (
        f"MATCH p = (s:Document {{id: $seed_id}})-[:LINKS_TO*1..{h}]->(t:Document) "
        "WHERE ALL(n IN nodes(p)[1..] WHERE "
        "(n.category IN $cats OR n.doc_type IN $doctypes) "
        "AND NOT coalesce(n.audience, '') IN $exclude) "
        "RETURN DISTINCT t.id AS id, t.source_url AS url, t.title AS title, "
        "t.category AS category, t.doc_type AS doc_type, t.source_type AS source_type"
    )


def seed_resolves(store: Any, seed_url: str) -> bool:
    """Does the seed URL exist as a ``:Document`` in the graph?"""
    rows = store.structured_query(
        "MATCH (d:Document {id: $id}) RETURN d.id AS id LIMIT 1",
        param_map={"id": doc_id_for(seed_url)},
    )
    return bool(rows)


def walk_members(store: Any, hub: HubSpec) -> list[dict[str, Any]]:
    """All member documents of one hub's qualified subgraph (seed included).

    The seed page is a member too — it is the topic's own curated index page
    and belongs in the topic map.
    """
    rows = store.structured_query(
        walk_query(hub.walk.hops),
        param_map={
            "seed_id": doc_id_for(hub.seed_url),
            "cats": list(hub.walk.categories),
            "doctypes": list(hub.walk.doc_types),
            "exclude": list(hub.walk.exclude_audience),
        },
    )
    seed_id = doc_id_for(hub.seed_url)
    members = [dict(r) for r in rows if r.get("url")]
    if not any(m["id"] == seed_id for m in members):
        members.insert(0, {"id": seed_id, "url": hub.seed_url, "title": hub.title or None})
    return members


def build_memberships(store: Any, hubs: list[HubSpec]) -> dict[str, list[dict[str, Any]]]:
    """Walk every given hub; return ``hub key -> member rows``.

    Callers pass ``config.confirmed()`` for a real build, or any subset for a
    preview (``manage_topic_hubs.py report``). A hub whose seed is missing from
    the graph raises — never a silent empty subgraph.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    for hub in hubs:
        if not seed_resolves(store, hub.seed_url):
            raise ValueError(
                f"hub {hub.key!r}: seed_url does not resolve to a :Document "
                f"({hub.seed_url}) — fix the URL or rebuild the graph"
            )
        members = walk_members(store, hub)
        _log.info("hub %r: %d members (hops=%d)", hub.key, len(members), hub.walk.hops)
        out[hub.key] = members
    return out


def invert_memberships(per_hub: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    """``hub key -> members`` inverted to ``url -> sorted hub keys`` (multi-membership)."""
    by_url: dict[str, set[str]] = {}
    for key, members in per_hub.items():
        for m in members:
            by_url.setdefault(m["url"], set()).add(key)
    return {url: sorted(keys) for url, keys in by_url.items()}


def composition_histogram(members: list[dict[str, Any]], label: str) -> Counter:
    """Counter over one member field (``category`` / ``doc_type``) for reports."""
    return Counter((m.get(label) or "(none)") for m in members)


# ── hub auto-detection: explainable qualified-fanout score (NOT centrality) ──


@dataclass
class HubCandidate:
    """One ``propose`` candidate with its explainable score components."""

    url: str
    title: str
    curated_links: int  # qualified out-links via file_component / card_or_listing
    inline_links: int  # qualified out-links via inline prose
    audience: str | None = None
    score: float = field(init=False, default=0.0)
    penalized: str = field(init=False, default="")

    def __post_init__(self) -> None:
        self.score = float(2 * self.curated_links + self.inline_links)
        reasons = []
        if _ARCHIVE_TITLE_RE.search(self.title or ""):
            # Strong on purpose: the §2 trap is an archive out-fanning its live
            # hub ~6x (GVP: 126 vs 22) — the penalty must invert that ranking.
            self.score *= 0.1
            reasons.append("archive/news title")
        if (self.audience or "").lower() in _PENALIZED_AUDIENCE:
            self.score *= 0.2
            reasons.append(f"audience={self.audience}")
        self.penalized = ", ".join(reasons)


#: ``propose`` query: rank regulatory_overview pages by qualified out-fanout,
#: split by curation-vs-inline link context. Pure counting — every score is
#: explainable to the human who must confirm the hub (§4.2; GDS/HITS is the
#: fallback, not the default — the plugin is not installed).
PROPOSE_QUERY = (
    "MATCH (h:Document {category: 'regulatory_overview'})-[e:LINKS_TO]->(t:Document) "
    "WHERE (t.category IN $cats OR t.doc_type IN $doctypes) "
    "WITH h, "
    "sum(CASE WHEN e.link_context IN $curated THEN 1 ELSE 0 END) AS curated, "
    "sum(CASE WHEN e.link_context = 'inline' THEN 1 ELSE 0 END) AS inline "
    "WHERE curated + inline >= $min_fanout "
    "RETURN h.source_url AS url, h.title AS title, h.audience AS audience, "
    "curated, inline "
    "ORDER BY 2 * curated + inline DESC LIMIT $limit"
)


def propose_candidates(
    store: Any,
    *,
    categories: list[str],
    doc_types: list[str] | None = None,
    min_fanout: int = 5,
    limit: int = 50,
) -> list[HubCandidate]:
    """Rank hub candidates by qualified fan-out (penalties applied python-side)."""
    rows = store.structured_query(
        PROPOSE_QUERY,
        param_map={
            "cats": list(categories),
            "doctypes": list(doc_types or []),
            "curated": list(CURATED_CONTEXTS),
            "min_fanout": int(min_fanout),
            "limit": int(limit),
        },
    )
    candidates = [
        HubCandidate(
            url=r["url"],
            title=r.get("title") or "",
            curated_links=int(r.get("curated") or 0),
            inline_links=int(r.get("inline") or 0),
            audience=r.get("audience"),
        )
        for r in rows
        if r.get("url")
    ]
    return sorted(candidates, key=lambda c: c.score, reverse=True)


def key_for_url(url: str, existing: set[str]) -> str:
    """A stable snake_case hub key from a URL tail, de-duplicated against ``existing``."""
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    base = re.sub(r"[^a-z0-9]+", "_", tail.lower()).strip("_") or "hub"
    if not base[0].isalpha():
        base = f"hub_{base}"
    key, n = base, 2
    while key in existing:
        key, n = f"{base}_{n}", n + 1
    return key

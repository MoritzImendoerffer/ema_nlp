"""``topic_context`` tool — the pageable *topic map* over precomputed subgraphs.

The capability top-k retrieval structurally cannot provide (docs/next/
topic_subgraphs.md): exhaustive, EMA-curated topic context. Membership was
precomputed offline (``scripts/manage_topic_hubs.py build``) onto
``:Document.topic_hubs``; this tool is a lookup, never a traversal.

The tool returns the subgraph's **member catalog** (title, labels, reference
number, revision, URL — PDF members grouped under the HTML detail page that
links to them, so revisions don't read as separate items), ranked by query
relevance, in fixed-size pages with a total count and a ``truncated`` flag —
nothing enters the agent context unless it asks for the next page (the primary
overflow guardrail). With ``subgraph.context: chunks`` the map is followed by
best-chunk-per-member text under an explicit token budget; those nodes carry
``retrieval_origin="topic_subgraph"`` and feed the same capture sink as
``ema_search``, so citations and faithfulness judging see them.

Resolution precedence (mirrors the steering stack): an explicit hub key from
the agent wins; otherwise the argument is treated as a document URL/id and its
stamped memberships decide — several memberships are disambiguated by which
hub's seed page best embedding-matches the query.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import UTC
from typing import Any

from llama_index.core.tools import FunctionTool

from harness.tools.registry import register_tool

log = logging.getLogger(__name__)

_CHARS_PER_TOKEN = 4  # coarse budget estimate; the budget is a guardrail, not billing
_CHUNK_FETCH_LIMIT = 50  # rows fetched before the token budget cuts (no hub is near this)

_REV_RE = re.compile(r"\brev(?:ision)?\.?\s*(\d+)\b", re.IGNORECASE)


def _revision(row: dict[str, Any]) -> str | None:
    """Stamped revision, else best-effort parse from the (descriptive EMA) title."""
    rev = row.get("revision")
    if rev not in (None, ""):
        return str(rev)
    m = _REV_RE.search(row.get("title") or "")
    return m.group(1) if m else None


def _member_line(row: dict[str, Any]) -> str:
    label = row.get("doc_type") or row.get("category") or "?"
    parts = [f"{row.get('title') or row.get('url') or '?'} [{label}]"]
    ref = row.get("reference_number")
    rev = _revision(row)
    if ref:
        parts.append(f"(ref {ref}{f', rev {rev}' if rev else ''})")
    elif rev:
        parts.append(f"(rev {rev})")
    parts.append(f"— {row.get('url') or '?'}")
    return " ".join(parts)


def group_members(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group PDF members under the HTML detail page that links to them.

    Returns group dicts ``{head, children}``; a PDF whose ``parent_id`` is not a
    member (or absent) becomes its own single-item group. Never drops a member —
    old revisions stay visible (regulatory questions can be revision-specific).
    """
    by_id = {m["id"]: m for m in members if m.get("id")}
    groups: dict[str, dict[str, Any]] = {}
    orphans: list[dict[str, Any]] = []
    for m in members:
        if (m.get("source_type") or "") != "pdf":
            groups.setdefault(m["id"], {"head": m, "children": []})
    for m in members:
        if (m.get("source_type") or "") != "pdf":
            continue
        parent = m.get("parent_id")
        if parent in groups:
            groups[parent]["children"].append(m)
        elif parent in by_id:  # parent is a member but itself a PDF — flat
            orphans.append(m)
        else:
            orphans.append(m)
    out = list(groups.values()) + [{"head": m, "children": []} for m in orphans]
    for g in out:
        g["children"].sort(key=lambda m: (m.get("title") or "", m.get("url") or ""))
    return out


def render_map(
    groups: list[dict[str, Any]],
    *,
    key: str,
    page: int,
    page_size: int,
    total_members: int,
) -> str:
    """One catalog page + the honest header (total count, page x/y, truncated flag)."""
    pages = max(math.ceil(len(groups) / page_size), 1)
    page = max(int(page), 1)
    if page > pages:
        return (
            f"[topic: {key} — {total_members} documents in {len(groups)} groups; "
            f"page {page} is out of range (valid: 1..{pages})]"
        )
    window = groups[(page - 1) * page_size : page * page_size]
    truncated = page < pages
    lines = [
        f"[topic: {key} — {total_members} documents in {len(groups)} groups; "
        f"page {page}/{pages}; truncated={str(truncated).lower()}"
        + (f" — call topic_context(topic='{key}', page={page + 1}) for more]" if truncated else "]")
    ]
    n0 = (page - 1) * page_size
    for i, g in enumerate(window, n0 + 1):
        lines.append(f"{i}. {_member_line(g['head'])}")
        lines.extend(f"   - {_member_line(c)}" for c in g["children"])
    return "\n".join(lines)


def _chunk_node(row: dict[str, Any], key: str) -> Any:
    """A NodeWithScore for one best-chunk row (small-to-big parent merge, stamped
    origin) — mirrors ``HierarchicalPGRetriever._node_from_row`` provenance."""
    from llama_index.core.schema import NodeWithScore, TextNode

    best = row.get("best") or {}
    parent = best.get("parent")
    if parent and parent.get("text"):
        nid, text = parent["id"], parent["text"]
    else:
        nid, text = best.get("id"), best.get("text") or ""
    meta = {
        "source_url": row.get("url") or "",
        "doc_id": row.get("id") or "",
        "title": row.get("title") or "",
        "category": row.get("category") or "",
        "doc_type": row.get("doc_type"),
        "reference_number": row.get("reference_number") or "",
        "source_type": row.get("source_type") or "",
        "topic_path": row.get("topic_path") or "",
        "chunk_id": nid,
        "matched_chunk": best.get("id") or nid,
        "retrieval_origin": "topic_subgraph",
        "topic_hub": key,
    }
    return NodeWithScore(
        node=TextNode(id_=nid or (row.get("id") or "chunk"), text=text, metadata=meta),
        score=float(best.get("score") or 0.0),
    )


@register_tool("topic_context")
def build_topic_context_tool(
    *,
    retriever: Any = None,
    hubs: Any = None,
    subgraph: Any = None,
    reader: Any = None,
    **_: Any,
) -> FunctionTool:
    """Build the ``topic_context`` FunctionTool.

    ``reader`` (a :class:`~harness.retrieval.subgraphs.TopicSubgraphReader` or a
    fake in tests) is derived from the retriever's store + embed model when not
    given. ``hubs`` is the loaded :class:`~harness.retrieval.hubs.HubsConfig`
    (loaded from ``subgraph.hubs`` when absent); ``subgraph`` a
    :class:`~harness.retrieval.subgraphs.SubgraphPolicy` (defaults when absent).
    """
    from harness.retrieval.subgraphs import SubgraphPolicy, TopicSubgraphReader

    policy = subgraph or SubgraphPolicy()
    if hubs is None:
        from harness.retrieval.hubs import load_hubs

        hubs = load_hubs(policy.hubs)
    if reader is None:
        store = getattr(retriever, "store", None)
        embed = getattr(retriever, "embed_model", None)
        if store is None or embed is None:
            raise ValueError(
                "topic_context needs a `reader` or a retriever exposing "
                "`store` + `embed_model` (HierarchicalPGRetriever does)"
            )
        reader = TopicSubgraphReader(store, embed)

    def _resolve_topic(topic: str, query: str, notes: list[str]) -> str | None:
        """Hub key (explicit key > document membership); None + note when unresolvable."""
        probe = (topic or "").strip()
        if hubs.get(probe) is not None:
            return probe
        keys = reader.memberships(probe)
        if not keys:
            notes.append(
                f"[{probe!r} is neither a known topic key nor a document with "
                f"topic membership. Known topics: {', '.join(hubs.keys()) or '(none)'}]"
            )
            return None
        if len(keys) == 1:
            key = keys[0]
        else:
            key = _pick_hub(keys, query)
            notes.append(f"[document belongs to {len(keys)} topics ({', '.join(sorted(keys))})"
                         f" — picked {key!r} as the best query match]")
        if hubs.get(probe) is None and key != probe:
            notes.append(f"[topic resolved from document membership: {key}]")
        return key

    def _pick_hub(keys: list[str], query: str) -> str:
        """Multi-membership policy: the hub whose seed page best matches the query."""
        if not query:
            return sorted(keys)[0]
        from harness.indexing.chunking import doc_id_for

        seed_ids = {
            doc_id_for(spec.seed_url): k
            for k in keys
            if (spec := hubs.get(k)) is not None
        }
        if not seed_ids:
            return sorted(keys)[0]
        scores = reader.doc_scores(list(seed_ids), reader.query_embedding(query))
        best = max(seed_ids, key=lambda sid: (scores.get(sid, 0.0), seed_ids[sid]))
        return seed_ids[best] if scores else sorted(keys)[0]

    def _budgeted_chunks(key: str, query: str) -> tuple[str, list]:
        qvec = reader.query_embedding(query)
        rows = reader.best_chunks(key, qvec, limit=_CHUNK_FETCH_LIMIT)
        budget = policy.max_tokens * _CHARS_PER_TOKEN
        nodes: list[Any] = []
        lines: list[str] = []
        used = 0
        for row in rows:
            node = _chunk_node(row, key)
            text = node.node.text or ""
            if not text.strip():
                continue
            if used + len(text) > budget and nodes:
                break
            used += len(text)
            nodes.append(node)
            lines.append(
                f"[{len(nodes)}] source={node.node.metadata['source_url']} "
                f"score={node.score:.3f} via=topic_subgraph\n{' '.join(text.split())}"
            )
        header = (
            f"[topic context: best passages from {len(nodes)} of {len(rows)} members, "
            f"~{used // _CHARS_PER_TOKEN} of {policy.max_tokens} token budget]"
        )
        return header + "\n\n" + "\n\n".join(lines) if nodes else header, nodes

    def topic_context(topic: str, query: str = "", page: int = 1) -> str:
        """List the complete, EMA-curated document catalog of a topic subgraph.

        Args:
            topic: A topic key (see the tool description) OR the URL/id of a
                retrieved document — its precomputed topic membership is used.
            query: The question at hand; ranks the catalog (and any text
                context) by relevance. Strongly recommended.
            page: Catalog page number (fixed page size; the header says how
                many pages exist).
        """
        import time
        from datetime import datetime

        from harness.tools.events import record_tool_event

        started_at = datetime.now(UTC).isoformat()
        t0 = time.perf_counter()

        def _record(out: str, nodes: list, notes: list[str]) -> str:
            # Chain-event capture: even a map-only page (no chunk nodes) is a step
            # in how the run's context evolved.
            record_tool_event(
                tool="topic_context",
                args={"topic": topic, "query": query, "page": int(page)},
                notes=notes,
                nodes=nodes,
                output=out,
                started_at=started_at,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
            )
            return out

        notes: list[str] = []
        key = _resolve_topic(topic, query, notes)
        if key is None:
            return _record("\n".join(notes), [], notes)
        members = reader.members(key)
        if not members:
            msg = (
                f"[topic {key!r} has no built subgraph — membership has not been "
                "stamped (scripts/manage_topic_hubs.py build) or the hub is not confirmed]"
            )
            return _record(msg, [], notes + [msg])
        groups = group_members(members)
        if query:
            scores = reader.member_scores(key, reader.query_embedding(query))
            groups.sort(
                key=lambda g: max(
                    [scores.get(g["head"].get("id"), 0.0)]
                    + [scores.get(c.get("id"), 0.0) for c in g["children"]]
                ),
                reverse=True,
            )
        else:
            groups.sort(key=lambda g: (g["head"].get("title") or "", g["head"].get("url") or ""))
        body = render_map(
            groups, key=key, page=page, page_size=policy.page_size, total_members=len(members)
        )
        out = "\n".join(notes + [body]) if notes else body
        chunk_nodes: list = []
        if policy.context == "chunks" and int(page) <= 1:
            if query:
                chunk_text, chunk_nodes = _budgeted_chunks(key, query)
                from harness.tools.search import sink_nodes

                sink_nodes(chunk_nodes)
                out += "\n\n" + chunk_text
            else:
                out += "\n\n[no query given — returning the map only; pass query= for text context]"
        return _record(out, chunk_nodes, notes + [f"[topic: {key}]"])

    known = ", ".join(h.key for h in hubs.confirmed()) or "(none built yet)"
    return FunctionTool.from_defaults(
        fn=topic_context,
        name="topic_context",
        description=(
            "Return the COMPLETE curated catalog (the 'topic map') of a precomputed EMA "
            "topic subgraph: every member document with title, type, reference number and "
            "URL, ranked by your query, in pages. Use it for scoping/comparison questions "
            "(the answer needs sibling documents, not just the best hit) and exhaustive "
            "enumeration ('all guidelines on X') — top-k search cannot prove completeness, "
            "this catalog can. Pass a topic key or the URL of a good ema_search hit "
            f"(its topic membership is looked up). Available topics: {known}."
        ),
    )

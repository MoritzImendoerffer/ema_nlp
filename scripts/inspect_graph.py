#!/usr/bin/env python
"""Inspect the Neo4j retrieval graph — structure, LINKS_TO quality, per-doc drill-down.

Read-only companion to the Neo4j Browser (http://localhost:7474; paste-ready
queries in ``deploy/neo4j/inspect_queries.cypher``). Uses the plain ``neo4j``
driver (no LlamaIndex import) so it starts fast; connection comes from
``NEO4J_URI`` / ``NEO4J_USER`` / ``NEO4J_PASSWORD`` via ``config.py``'s dotenv
load, same as the ingest layer.

The ``links`` subcommand is the boilerplate audit: LINKS_TO edges carry
``{kind, link_context, document_type, anchor}`` (stamped by
``harness.indexing.property_graph._link_props`` from ``harness.indexing.links``,
the main-content-scoped extractor ported from ema_scraper's ``EmaPageParser``).
Chrome/boilerplate has a recognisable signature: a handful of targets absorbing
most edges, with repeated nav anchors ("Home", "Contact", ...). Pre-scoping,
74 chrome targets absorbed 94.4% of 1.72M edges (see ``links.py`` module doc);
the concentration stats printed here let you check the live graph against that.

Usage:
    python scripts/inspect_graph.py overview                 # node/edge/label census
    python scripts/inspect_graph.py links                    # LINKS_TO quality audit
    python scripts/inspect_graph.py links --top 30 --samples 20
    python scripts/inspect_graph.py doc <doc-id | url-substring>
    python scripts/inspect_graph.py cypher "MATCH (d:Document) RETURN count(d)"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from neo4j import GraphDatabase  # noqa: E402

import config  # noqa: E402,F401  (loads ~/Nextcloud/Datasets/ema_nlp/ema_nlp.env)


def _driver():
    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        raise RuntimeError(
            "NEO4J_PASSWORD is not set. Configure it in ~/Nextcloud/Datasets/ema_nlp/ema_nlp.env "
            "(never hardcode credentials)."
        )
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), password),
    )


def _rows(session, query: str, **params: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in session.run(query, **params)]


def _fmt(v: Any, width: int | None = None) -> str:
    s = "" if v is None else str(v)
    s = s.replace("\n", " ")
    if width and len(s) > width:
        s = s[: width - 1] + "…"
    return s


def _table(rows: list[dict[str, Any]], max_col: int = 78) -> None:
    if not rows:
        print("  (no rows)")
        return
    headers = list(rows[0].keys())
    cells = [[_fmt(r.get(h), max_col) for h in headers] for r in rows]
    widths = [max(len(h), *(len(c[i]) for c in cells)) for i, h in enumerate(headers)]
    print("  " + "  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("  " + "  ".join("-" * w for w in widths))
    for c in cells:
        print("  " + "  ".join(v.ljust(w) for v, w in zip(c, widths)))


def _pct(n: int, total: int) -> str:
    return f"{100.0 * n / total:5.1f}%" if total else "  n/a"


# ── overview ─────────────────────────────────────────────────────────────────


def cmd_overview(args: argparse.Namespace) -> None:
    with _driver() as drv, drv.session() as s:
        try:
            stats = _rows(s, "CALL apoc.meta.stats() YIELD labels, relTypesCount "
                             "RETURN labels, relTypesCount")[0]
            labels, rels = stats["labels"], stats["relTypesCount"]
        except Exception:  # APOC unavailable — fall back to count-store queries
            labels = {
                r["label"]: r["c"]
                for r in _rows(s, "MATCH (n) UNWIND labels(n) AS label "
                                  "RETURN label, count(*) AS c")
            }
            rels = {
                r["t"]: r["c"]
                for r in _rows(s, "MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c")
            }

        print("== Node labels ==")
        _table([{"label": k, "count": v} for k, v in sorted(labels.items(), key=lambda x: -x[1])])
        print("\n== Relationship types ==")
        _table([{"type": k, "count": v} for k, v in sorted(rels.items(), key=lambda x: -x[1])])

        print("\n== Documents by category ==")
        _table(_rows(s, "MATCH (d:Document) RETURN coalesce(d.category,'(unset)') AS category, "
                        "count(*) AS docs ORDER BY docs DESC"))
        print("\n== Documents by source_type ==")
        _table(_rows(s, "MATCH (d:Document) RETURN coalesce(d.source_type,'(unset)') AS source_type, "
                        "count(*) AS docs ORDER BY docs DESC"))

        print("\n== Enrichment coverage (derived properties) ==")
        _table(_rows(s, "MATCH (d:Document) RETURN d.source_type AS source_type, count(*) AS docs, "
                        "count(d.category) AS category, count(d.doc_type) AS doc_type, "
                        "count(d.audience) AS audience, count(d.site_topic) AS site_topic "
                        "ORDER BY docs DESC"))

        print("\n== Top doc_type (EMA JSON export; PDFs) ==")
        _table(_rows(s, "MATCH (d:Document) WHERE d.doc_type IS NOT NULL "
                        "RETURN d.doc_type AS doc_type, count(*) AS docs ORDER BY docs DESC LIMIT 15"))
        print("\n== Documents by audience (page badge; HTML) ==")
        _table(_rows(s, "MATCH (d:Document) WHERE d.audience IS NOT NULL "
                        "RETURN d.audience AS audience, count(*) AS docs ORDER BY docs DESC"))
        print("\n== Top site_topic (page badge; HTML) ==")
        _table(_rows(s, "MATCH (d:Document) WHERE d.site_topic IS NOT NULL "
                        "RETURN d.site_topic AS site_topic, count(*) AS docs ORDER BY docs DESC LIMIT 15"))

        print("\n== Indexes ==")
        _table(_rows(s, "SHOW INDEXES YIELD name, type, state, labelsOrTypes, properties "
                        "RETURN name, type, state, labelsOrTypes, properties"))


# ── links (boilerplate audit) ────────────────────────────────────────────────


def cmd_links(args: argparse.Namespace) -> None:
    top, samples = args.top, args.samples
    with _driver() as drv, drv.session() as s:
        total = _rows(s, "MATCH ()-[r:LINKS_TO]->() RETURN count(r) AS c")[0]["c"]
        print(f"== LINKS_TO edges: {total:,} ==")
        if not total:
            print("  no LINKS_TO edges — was the links pass run? "
                  "(python -m harness.indexing.build --links-only)")
            return

        print("\n== By kind (URL shape) ==")
        _table([{**r, "share": _pct(r["edges"], total)} for r in _rows(
            s, "MATCH ()-[r:LINKS_TO]->() RETURN coalesce(r.kind,'(unset)') AS kind, "
               "count(*) AS edges ORDER BY edges DESC")])

        print("\n== By link_context (DOM component the anchor sat in) ==")
        _table([{**r, "share": _pct(r["edges"], total)} for r in _rows(
            s, "MATCH ()-[r:LINKS_TO]->() RETURN coalesce(r.link_context,'(unset)') AS link_context, "
               "count(*) AS edges ORDER BY edges DESC")])

        print(f"\n== Top {top} document_type (file cards only) ==")
        _table(_rows(s, "MATCH ()-[r:LINKS_TO]->() WHERE r.document_type IS NOT NULL "
                        "RETURN r.document_type AS document_type, count(*) AS edges "
                        "ORDER BY edges DESC LIMIT $top", top=top))

        # In-degree concentration — the boilerplate signature. Pre-scoping, the
        # top ~74 chrome targets absorbed 94.4% of all edges.
        indeg = sorted(
            (r["c"] for r in _rows(s, "MATCH ()-[:LINKS_TO]->(b:Document) "
                                      "RETURN b.id AS id, count(*) AS c")),
            reverse=True,
        )
        n_targets = len(indeg)
        print(f"\n== In-degree concentration ({n_targets:,} distinct targets) ==")
        for k in (1, 10, 50, 100):
            if n_targets >= k:
                print(f"  top {k:>3} targets absorb {_pct(sum(indeg[:k]), total)} of edges")
        print(f"  median in-degree: {indeg[n_targets // 2]}, max: {indeg[0]}")
        print("  (pre-scoping baseline: 74 chrome targets = 94.4% — "
              "high top-10/50 share means nav boilerplate survived)")

        print(f"\n== Top {top} in-degree targets ==")
        _table([{**r, "share": _pct(r["in_edges"], total)} for r in _rows(
            s, "MATCH ()-[:LINKS_TO]->(b:Document) "
               "WITH b, count(*) AS in_edges ORDER BY in_edges DESC LIMIT $top "
               "RETURN in_edges, coalesce(b.category,'?') AS category, "
               "coalesce(b.title, b.source_url, b.id) AS target", top=top)], max_col=90)

        print(f"\n== Top {top} out-degree sources ==")
        _table(_rows(s, "MATCH (a:Document)-[:LINKS_TO]->() "
                        "WITH a, count(*) AS out_edges ORDER BY out_edges DESC LIMIT $top "
                        "RETURN out_edges, coalesce(a.title, a.source_url, a.id) AS source",
                     top=top), max_col=90)

        print(f"\n== Top {top} repeated anchor texts ==")
        _table([{**r, "share": _pct(r["edges"], total)} for r in _rows(
            s, "MATCH ()-[r:LINKS_TO]->() "
               "RETURN coalesce(r.anchor,'(empty)') AS anchor, count(*) AS edges, "
               "count(DISTINCT startNode(r)) AS from_docs "
               "ORDER BY edges DESC LIMIT $top", top=top)], max_col=70)

        print(f"\n== {samples} random edges ==")
        _table(_rows(s, "MATCH (a:Document)-[r:LINKS_TO]->(b:Document) "
                        "WITH a, r, b ORDER BY rand() LIMIT $n "
                        "RETURN coalesce(a.title, a.source_url) AS source, r.anchor AS anchor, "
                        "r.kind AS kind, r.link_context AS ctx, "
                        "coalesce(b.title, b.source_url) AS target", n=samples), max_col=48)


# ── doc drill-down ───────────────────────────────────────────────────────────


def cmd_doc(args: argparse.Namespace) -> None:
    with _driver() as drv, drv.session() as s:
        docs = _rows(s, "MATCH (d:Document) WHERE d.id = $q OR d.source_url = $q "
                        "OR toLower(coalesce(d.source_url,'')) CONTAINS toLower($q) "
                        "OR toLower(coalesce(d.title,'')) CONTAINS toLower($q) "
                        "RETURN d.id AS id, d.title AS title, d.source_url AS source_url "
                        "LIMIT 20", q=args.query)
        if not docs:
            print(f"no :Document matched {args.query!r}")
            return
        if len(docs) > 1:
            print(f"== {len(docs)} matches — showing the first; narrow the query for others ==")
            _table(docs, max_col=80)
            print()
        doc_id = docs[0]["id"]

        print("== Properties ==")
        props = _rows(s, "MATCH (d:Document {id: $id}) RETURN properties(d) AS p", id=doc_id)[0]["p"]
        for k in sorted(k for k in props if k != "embedding"):
            print(f"  {k}: {_fmt(props[k], 100)}")
        chunks = _rows(s, "MATCH (:Document {id: $id})-[:HAS_CHUNK]->(c:Chunk) "
                          "RETURN count(c) AS n, sum(CASE WHEN c.is_leaf THEN 1 ELSE 0 END) AS leaves",
                       id=doc_id)[0]
        print(f"  chunks: {chunks['n']} ({chunks['leaves']} leaf)")

        print("\n== Outgoing LINKS_TO ==")
        _table(_rows(s, "MATCH (:Document {id: $id})-[r:LINKS_TO]->(b:Document) "
                        "RETURN r.anchor AS anchor, r.kind AS kind, r.link_context AS ctx, "
                        "coalesce(b.title, b.source_url) AS target "
                        "ORDER BY ctx, anchor LIMIT $top", id=doc_id, top=args.top), max_col=60)

        print("\n== Incoming LINKS_TO ==")
        _table(_rows(s, "MATCH (a:Document)-[r:LINKS_TO]->(:Document {id: $id}) "
                        "RETURN coalesce(a.title, a.source_url) AS source, r.anchor AS anchor, "
                        "r.link_context AS ctx ORDER BY ctx LIMIT $top",
                     id=doc_id, top=args.top), max_col=60)


# ── raw cypher ───────────────────────────────────────────────────────────────


def cmd_cypher(args: argparse.Namespace) -> None:
    with _driver() as drv, drv.session() as s:
        _table(_rows(s, args.query), max_col=args.max_col)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("overview", help="node/edge/label census + indexes")

    p = sub.add_parser("links", help="LINKS_TO quality audit (boilerplate check)")
    p.add_argument("--top", type=int, default=20, help="rows per top-N table (default 20)")
    p.add_argument("--samples", type=int, default=10, help="random edge samples (default 10)")

    p = sub.add_parser("doc", help="drill into one document by id / url / title substring")
    p.add_argument("query")
    p.add_argument("--top", type=int, default=25, help="max in/out edges to list (default 25)")

    p = sub.add_parser("cypher", help="run a raw read query, print as table")
    p.add_argument("query")
    p.add_argument("--max-col", type=int, default=78)

    args = ap.parse_args()
    {"overview": cmd_overview, "links": cmd_links, "doc": cmd_doc, "cypher": cmd_cypher}[args.cmd](args)


if __name__ == "__main__":
    main()

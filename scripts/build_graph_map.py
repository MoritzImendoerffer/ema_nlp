#!/usr/bin/env python
"""Build the static knowledge-base map — one self-contained WebGL HTML file.

Pulls the document-level graph from Neo4j (all ``:Document`` nodes +
``LINKS_TO`` edges; the 5.8M ``:Chunk`` nodes are deliberately out of scope),
computes a deterministic layout offline (igraph — DrL for large components,
Fruchterman-Reingold for small ones, shelf-packed component boxes, isolated
docs in a category-grouped ring band), and emits ``template.html`` with the
vendored sigma.js/graphology and the gzip+base64 payload inlined. The result
opens anywhere offline — no CDN, no server.

Usage:
    python scripts/build_graph_map.py                     # → $EMA_RESULTS_DIR/graph_map/
    python scripts/build_graph_map.py --tree              # radial site tree, root = ema.europa.eu
    python scripts/build_graph_map.py --limit 2000        # fast smoke build
    python scripts/build_graph_map.py --raw-json          # uncompressed embed (debug)
    python scripts/build_graph_map.py --out /tmp/map.html # explicit output path

``--tree`` replaces the force layout with a radial tree: HTML docs sit at their
breadcrumb (topic_path) slot, PDFs under the page that links to them (LINKS_TO
— unlinked PDFs fall back to their documents/<type> bucket), synthetic
"site section" nodes fill in the skeleton. Output: ``ema_kb_tree.html``.

Output defaults to ``config.RESULTS_DIR / graph_map/ema_kb_map.html`` — the
Nextcloud-synced results folder, so the map shows up on every machine.

Requires the ``viz`` extra for the layout step: ``pip install -e ".[viz]"``.
Connection via NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD (config.py dotenv),
same as scripts/inspect_graph.py.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import math
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_LIB = _REPO / "scripts" / "lib" / "graph_map"
_VENDOR_FILES = ("graphology-0.25.4.umd.min.js", "sigma-2.4.0.min.js")

# Shared URL prefix factored out of the payload (~40 bytes/node saved).
URL_PREFIX = "https://www.ema.europa.eu"


# ── Neo4j fetch ───────────────────────────────────────────────────────────────

def _driver():
    from neo4j import GraphDatabase

    import config  # noqa: F401  (loads ~/Nextcloud/Datasets/ema_nlp/ema_nlp.env)

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


def fetch_documents(session, limit: int = 0) -> list[dict[str, Any]]:
    """All ``:Document`` rows with the label properties the map filters on."""
    q = (
        "MATCH (d:Document) RETURN d.id AS id, d.title AS title, "
        "d.source_url AS source_url, d.category AS category, d.doc_type AS doc_type, "
        "d.audience AS audience, d.site_topic AS site_topic, d.topic_path AS topic_path, "
        "d.source_type AS source_type"
    )
    if limit:
        q += f" LIMIT {int(limit)}"
    return [dict(r) for r in session.run(q)]


def fetch_links(session, ids: set[str] | None = None) -> list[tuple[str, str]]:
    """``(src_id, dst_id)`` for every LINKS_TO edge (induced on ``ids`` if given)."""
    rows = session.run(
        "MATCH (a:Document)-[:LINKS_TO]->(b:Document) RETURN a.id AS s, b.id AS t"
    )
    edges = [(r["s"], r["t"]) for r in rows]
    if ids is not None:
        edges = [(s, t) for s, t in edges if s in ids and t in ids]
    return edges


# ── Layout ────────────────────────────────────────────────────────────────────

def _normalize(coords: list[tuple[float, float]], side: float) -> list[tuple[float, float]]:
    """Scale/translate coords into a ``side``×``side`` box at the origin."""
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    w = (max(xs) - min(xs)) or 1.0
    h = (max(ys) - min(ys)) or 1.0
    scale = side / max(w, h)
    return [((x - min(xs)) * scale, (y - min(ys)) * scale) for x, y in coords]


def compute_layout(
    nodes: list[dict[str, Any]],
    edges: list[tuple[str, str]],
    *,
    seed: int = 42,
) -> dict[str, tuple[float, float]]:
    """Deterministic ``id -> (x, y)`` for the whole graph.

    Components with ≥3 nodes are laid out independently (DrL when large, FR when
    small — DrL degenerates on tiny graphs) and shelf-packed left-to-right into
    rows; isolated nodes and 2-node components go into a grid band below the
    packed area, grouped by category so the periphery stays legible.
    """
    import igraph

    rng = random.Random(seed)
    random.seed(seed)  # igraph's Python-RNG bridge reads the global module RNG
    igraph.set_random_number_generator(random)

    index = {n["id"]: i for i, n in enumerate(nodes)}
    edge_idx = list(
        {(index[s], index[t]) for s, t in edges if s in index and t in index and s != t}
    )
    g = igraph.Graph(len(nodes), edge_idx, directed=False)
    components = g.connected_components()

    boxes: list[tuple[float, list[int], list[tuple[float, float]]]] = []  # (side, members, xy)
    band: list[list[int]] = []  # small components → grid band
    for members in components:
        if len(members) < 3:
            band.append(list(members))
            continue
        sub = g.induced_subgraph(members)
        layout = sub.layout("drl") if len(members) >= 300 else sub.layout("fr", niter=250)
        side = 6.0 * math.sqrt(len(members))  # area ∝ component size
        boxes.append((side, list(members), _normalize(list(layout), side)))

    positions: dict[str, tuple[float, float]] = {}
    # Shelf-pack the component boxes, biggest first, into rows of ~total width.
    boxes.sort(key=lambda b: -b[0])
    row_width = max((b[0] for b in boxes), default=100.0)
    total_area = sum(b[0] ** 2 for b in boxes)
    row_width = max(row_width, 1.25 * math.sqrt(total_area))
    gap = 18.0
    x = y = row_height = 0.0
    for side, members, xy in boxes:
        if x > 0 and x + side > row_width:
            x, y, row_height = 0.0, y + row_height + gap, 0.0
        for m, (mx, my) in zip(members, xy):
            positions[nodes[m]["id"]] = (x + mx, y + my)
        x += side + gap
        row_height = max(row_height, side)

    # Band of isolates/pairs below, grouped by category then title for stability.
    band_nodes = [m for comp in band for m in comp]
    band_nodes.sort(key=lambda m: (str(nodes[m].get("category") or ""), str(nodes[m].get("title") or ""), nodes[m]["id"]))
    if band_nodes:
        y0 = y + row_height + 3 * gap
        cols = max(1, int(row_width // 4.0))
        for i, m in enumerate(band_nodes):
            jitter = rng.uniform(-0.8, 0.8)
            positions[nodes[m]["id"]] = (
                (i % cols) * 4.0 + jitter,
                y0 + (i // cols) * 4.0 + jitter,
            )
    return positions


# ── Tree mode (--tree): everything under one root, ema.europa.eu ─────────────
#
# The site hierarchy is real for HTML pages (topic_path = breadcrumb); PDFs
# (72% of docs) only carry a flat /documents/<type>/ bucket — their true site
# position is "under the page that links to them", so LINKS_TO provides the
# tree slot and the flat bucket is the fallback for unlinked PDFs.

SECTION_CATEGORY = "site section"
_SEC_PREFIX = "§"  # section node ids: §medicines/human — cannot collide with doc ids


def _site_segments(node: dict[str, Any]) -> list[str]:
    """Breadcrumb segments for a doc: topic_path preferred, URL path fallback."""
    raw = str(node.get("topic_path") or "").strip()
    if not raw.strip("/"):
        host_path = str(node.get("source_url") or "").split("://", 1)[-1]
        raw = host_path.split("/", 1)[1] if "/" in host_path else ""
    segs = [s for s in raw.split("/") if s]
    if segs and segs[0] == "en":
        segs = segs[1:]
    return segs


def build_tree(
    nodes: list[dict[str, Any]], edges: list[tuple[str, str]]
) -> tuple[list[dict[str, Any]], dict[str, list[str]], list[tuple[str, str]]]:
    """``(section_nodes, children, tree_edges)`` — the whole KB as one tree.

    Every doc gets exactly one parent: HTML docs their breadcrumb prefix (a doc
    whose path *is* a section becomes that section node); linked PDFs the first
    HTML doc that LINKS_TO them; unlinked PDFs their documents/<type> bucket.
    Synthetic ``§path`` section nodes fill in the prefixes, rooted at
    ``ema.europa.eu``.
    """
    by_id = {n["id"]: n for n in nodes}
    html_ids = {n["id"] for n in nodes if str(n.get("source_type") or "") != "pdf"}
    segs_of = {n["id"]: _site_segments(n) for n in nodes}

    # First HTML linker per PDF (deterministic: smallest doc id).
    linker: dict[str, str] = {}
    for s, t in sorted(edges):
        if s in html_ids and t in by_id and t not in html_ids:
            linker.setdefault(t, s)

    # Section prefixes needed: every proper prefix of each doc's slot path.
    doc_parent_path: dict[str, tuple[str, ...]] = {}  # doc id -> section path (fallback)
    section_paths: set[tuple[str, ...]] = set()
    for n in nodes:
        nid = n["id"]
        if nid in linker:
            continue  # parented by a doc, not a section
        segs = segs_of[nid]
        # HTML breadcrumbs end with the page's own slug → parent is the prefix;
        # a PDF's topic_path IS its shared documents/<type> bucket → parent is
        # the full path.
        if nid in html_ids and segs:
            parent = tuple(segs[:-1])
        else:
            parent = tuple(segs)
        doc_parent_path[nid] = parent
        for i in range(len(parent) + 1):
            section_paths.add(parent[:i])

    # A doc whose full path equals a section prefix *becomes* that section.
    doc_at: dict[tuple[str, ...], str] = {}
    for nid in sorted(html_ids):
        path = tuple(segs_of[nid])
        if path in section_paths and path not in doc_at and path != ():
            doc_at[path] = nid

    def slot(path: tuple[str, ...]) -> str:
        """Tree-node key for a section path: the doc occupying it, else §synthetic."""
        return doc_at.get(path) or (_SEC_PREFIX + "/".join(path))

    children: dict[str, list[str]] = {}
    tree_edges: list[tuple[str, str]] = []

    def attach(parent_key: str, child_key: str) -> None:
        children.setdefault(parent_key, []).append(child_key)
        tree_edges.append((parent_key, child_key))

    # Section skeleton (synthetic or doc-backed), wired parent → child.
    section_nodes: list[dict[str, Any]] = []
    for path in sorted(section_paths):
        key = slot(path)
        if path:
            attach(slot(path[:-1]), key)
        if key.startswith(_SEC_PREFIX):
            section_nodes.append(
                {
                    "id": key,
                    "title": path[-1] if path else "ema.europa.eu",
                    "category": SECTION_CATEGORY,
                    "doc_type": "", "audience": "", "site_topic": "",
                    "source_url": URL_PREFIX + "/en/" + "/".join(path),
                    "topic_path": "/en/" + "/".join(path) + ("/" if path else ""),
                    "source_type": "section",
                }
            )

    # Docs: under their linking page, or their section prefix (unless they ARE it).
    occupied = set(doc_at.values())
    for n in nodes:
        nid = n["id"]
        if nid in occupied:
            continue
        if nid in linker:
            attach(linker[nid], nid)
        else:
            attach(slot(doc_parent_path[nid]), nid)
    return section_nodes, children, tree_edges


def tree_layout(
    all_nodes: list[dict[str, Any]], children: dict[str, list[str]]
) -> dict[str, tuple[float, float]]:
    """Radial tree positions: depth → radius, angular span ∝ subtree doc count.

    Internal children get contiguous span slices (biggest first); leaf children
    are packed into concentric arc rows inside the remaining span, so huge fans
    (an EPAR bucket, a hub page's PDFs) stay compact instead of demanding an
    absurd radius.
    """
    STEP, GAP = 150.0, 2.5  # ring distance per depth / leaf spacing in coord units
    by_id = {n["id"]: n for n in all_nodes}
    root = _SEC_PREFIX

    weight: dict[str, int] = {}

    def _weigh(key: str) -> int:
        w = 0 if key.startswith(_SEC_PREFIX) else 1
        w += sum(_weigh(k) for k in children.get(key, []))
        weight[key] = max(w, 1)
        return weight[key]

    _weigh(root)

    positions: dict[str, tuple[float, float]] = {}

    def _place(key: str, depth: float, a0: float, a1: float) -> None:
        mid = (a0 + a1) / 2
        r = depth * STEP
        positions[key] = (round(r * math.cos(mid), 2), round(r * math.sin(mid), 2))
        kids = children.get(key, [])
        if not kids:
            return
        internal = sorted(
            (k for k in kids if children.get(k)),
            key=lambda k: (-weight[k], str(by_id[k].get("title") or ""), k),
        )
        leaves = sorted(
            (k for k in kids if not children.get(k)),
            key=lambda k: (str(by_id[k].get("category") or ""), str(by_id[k].get("title") or ""), k),
        )
        total = sum(weight[k] for k in kids)
        a = a0
        for k in internal:
            span = (a1 - a0) * weight[k] / total
            _place(k, depth + 1, a, a + span)
            a += span
        if not leaves:
            return
        span = max(a1 - a, 1e-6)
        base, i, row = (depth + 1) * STEP, 0, 0
        while i < len(leaves):
            r_row = base + row * GAP
            cap = max(1, int(span * r_row / GAP))
            for j, k in enumerate(leaves[i : i + cap]):
                ang = a + span * (j + 0.5) / cap
                positions[k] = (round(r_row * math.cos(ang), 2), round(r_row * math.sin(ang), 2))
            i += cap
            row += 1

    _place(root, 0.0, 0.0, 2 * math.pi)
    return positions


# ── Payload ───────────────────────────────────────────────────────────────────

def _string_table(values: list[str]) -> tuple[list[str], dict[str, int]]:
    table = sorted({v for v in values if v})
    return table, {v: i for i, v in enumerate(table)}


def build_payload(
    nodes: list[dict[str, Any]],
    edges: list[tuple[str, str]],
    positions: dict[str, tuple[float, float]],
    *,
    tree_edges: list[tuple[str, str]] | None = None,
    section_sizes: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Columnar, string-table-compressed JSON payload for the viewer.

    ``tree_edges`` render like links but don't count toward in-degree (which
    drives node size); ``section_sizes`` gives synthetic section nodes a size
    (child count) since they have no LINKS_TO in-degree.
    """
    index = {n["id"]: i for i, n in enumerate(nodes)}
    in_deg = [0] * len(nodes)
    flat_edges: list[int] = []
    for s, t in edges:
        si, ti = index.get(s), index.get(t)
        if si is None or ti is None:
            continue
        flat_edges += [si, ti]
        in_deg[ti] += 1
    for s, t in tree_edges or []:
        si, ti = index.get(s), index.get(t)
        if si is not None and ti is not None:
            flat_edges += [si, ti]
    for nid, size in (section_sizes or {}).items():
        if nid in index:
            in_deg[index[nid]] = size

    def col(key: str) -> list[str]:
        return [str(n.get(key) or "") for n in nodes]

    categories, cat_i = _string_table(col("category"))
    doc_types, dt_i = _string_table(col("doc_type"))
    audiences, aud_i = _string_table(col("audience"))
    site_topics, st_i = _string_table(col("site_topic"))

    def idx_col(values: list[str], table_index: dict[str, int]) -> list[int]:
        return [table_index.get(v, -1) for v in values]

    return {
        "meta": {
            "node_count": len(nodes),
            "edge_count": len(flat_edges) // 2,
            "url_prefix": URL_PREFIX,
        },
        "categories": categories,
        "doc_types": doc_types,
        "audiences": audiences,
        "site_topics": site_topics,
        "nodes": {
            "id": [str(n["id"] or "")[:12] for n in nodes],
            "x": [round(positions[n["id"]][0], 2) for n in nodes],
            "y": [round(positions[n["id"]][1], 2) for n in nodes],
            "in_deg": in_deg,
            "cat": idx_col(col("category"), cat_i),
            "dt": idx_col(col("doc_type"), dt_i),
            "aud": idx_col(col("audience"), aud_i),
            "st": idx_col(col("site_topic"), st_i),
            "title": col("title"),
            "url": [
                u[len(URL_PREFIX):] if u.startswith(URL_PREFIX) else u
                for u in col("source_url")
            ],
            "topic": col("topic_path"),
        },
        "edges": flat_edges,
    }


# ── Emit ──────────────────────────────────────────────────────────────────────

def emit_html(payload: dict[str, Any], out: Path, *, raw_json: bool = False) -> None:
    template = (_LIB / "template.html").read_text(encoding="utf-8")
    vendor_js = "\n;\n".join(
        (_LIB / "vendor" / name).read_text(encoding="utf-8") for name in _VENDOR_FILES
    )
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if raw_json:
        blob, encoding = data.replace("</", "<\\/"), "json"
    else:
        blob = base64.b64encode(
            gzip.compress(data.encode("utf-8"), mtime=0)  # mtime=0 → reproducible
        ).decode("ascii")
        encoding = "gzip-base64"
    html = (
        template.replace("__DATA_ENCODING__", encoding)
        .replace("/*__VENDOR_JS__*/", vendor_js)
        .replace("__DATA_PAYLOAD__", blob)
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(
        f"wrote {out}  ({len(html) / 1e6:.1f} MB, "
        f"{payload['meta']['node_count']} nodes, {payload['meta']['edge_count']} edges, "
        f"payload {'raw' if raw_json else 'gzip'} {len(blob) / 1e6:.1f} MB)"
    )


def main(argv: list[str] | None = None) -> int:
    import config

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        default=str(config.RESULTS_DIR / "graph_map" / "ema_kb_map.html"),
        help="output HTML path (default: Nextcloud-synced results dir)",
    )
    parser.add_argument("--limit", type=int, default=0, help="subsample N docs (smoke build)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--raw-json", action="store_true", help="uncompressed embed (debug)")
    parser.add_argument(
        "--tree",
        action="store_true",
        help="radial site tree rooted at ema.europa.eu instead of the force layout "
        "(HTML docs by breadcrumb, PDFs under their linking page)",
    )
    args = parser.parse_args(argv)
    default_out = parser.get_default("out")
    if args.tree and args.out == default_out:
        args.out = str(Path(default_out).with_name("ema_kb_tree.html"))

    t0 = time.perf_counter()
    with _driver() as driver, driver.session() as session:
        nodes = fetch_documents(session, limit=args.limit)
        edges = fetch_links(session, ids={n["id"] for n in nodes} if args.limit else None)
    print(f"fetched {len(nodes)} docs / {len(edges)} links in {time.perf_counter() - t0:.1f}s")

    t1 = time.perf_counter()
    if args.tree:
        section_nodes, children, tree_edges = build_tree(nodes, edges)
        all_nodes = nodes + section_nodes
        positions = tree_layout(all_nodes, children)
        payload = build_payload(
            all_nodes,
            edges,
            positions,
            tree_edges=tree_edges,
            section_sizes={
                n["id"]: len(children.get(n["id"], [])) for n in section_nodes
            },
        )
        print(
            f"tree layout in {time.perf_counter() - t1:.1f}s "
            f"({len(section_nodes)} section nodes, {len(tree_edges)} tree edges)"
        )
    else:
        positions = compute_layout(nodes, edges, seed=args.seed)
        payload = build_payload(nodes, edges, positions)
        print(f"layout in {time.perf_counter() - t1:.1f}s")

    emit_html(payload, Path(args.out), raw_json=args.raw_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

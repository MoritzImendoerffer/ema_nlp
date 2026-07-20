"""Site tree — the whole document graph as one tree rooted at the site root.

The generic algorithm (corpus-agnostic; no EMA-specific names appear in code):
given a root, every document gets exactly one parent from a priority chain of
parent signals —

1. **explicit path metadata** (breadcrumb ``topic_path``, URL-path fallback):
   the document sits at its path slot, parented by the path prefix; a document
   whose path *is* a section occupies that section node;
2. **first structural linker**: a document with no own place in the hierarchy
   (here: PDFs, whose ``topic_path`` is only a flat shared bucket) is parented
   under the first non-leaf document with a typed link edge to it
   (deterministic: smallest linker id);
3. **flat path bucket**: remaining documents fall back to their shared bucket
   path.

Synthetic ``§path`` section nodes fill in the path prefixes. For a corpus with
no path metadata at all, signal (2) applied transitively degrades to BFS
layering over the link graph from the root — levels are then BFS depth. Levels
are *emergent*: a "level" is the sibling set under one tree node
(``tree_path`` prefix + ``tree_depth``), never a hardcoded category list.

Consumers: the KB map (``scripts/build_graph_map.py --tree``), the site-tree
backfill (``scripts/backfill_site_tree.py`` → ``:Document`` properties
``tree_parent_id`` / ``tree_depth`` / ``tree_path`` / ``tree_ancestor_ids``),
and the chain-export tree view (``harness/export/chain_html.py``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

SECTION_CATEGORY = "site section"
SEC_PREFIX = "§"  # section node ids: §medicines/human — cannot collide with doc ids

# Shared URL prefix of the corpus (factored out of payloads; the site root).
URL_PREFIX = "https://www.ema.europa.eu"


def site_segments(node: dict[str, Any]) -> list[str]:
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
    segs_of = {n["id"]: site_segments(n) for n in nodes}

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
        return doc_at.get(path) or (SEC_PREFIX + "/".join(path))

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
        if key.startswith(SEC_PREFIX):
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
    root = SEC_PREFIX

    weight: dict[str, int] = {}

    def _weigh(key: str) -> int:
        w = 0 if key.startswith(SEC_PREFIX) else 1
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


# ── Tree records (retrieval backfill) ─────────────────────────────────────────

@dataclass(frozen=True)
class TreeRecord:
    """One document's place in the site tree (persisted onto ``:Document``)."""

    parent_id: str  # doc id of the parent when doc-backed, "" for synthetic sections
    depth: int  # root = 0
    path: str  # "/"-joined slot segments, e.g. "medicines/human/EPAR/comirnaty"
    ancestor_ids: tuple[str, ...]  # doc-backed ancestors only, root→nearest


def derive_tree_records(
    nodes: list[dict[str, Any]], edges: list[tuple[str, str]]
) -> dict[str, TreeRecord]:
    """Per-document tree records from a :func:`build_tree` walk.

    Path rules: an HTML doc's slot is its own breadcrumb path (also when it
    occupies a section); a linker-parented doc inherits the linker's path; a
    bucket-parented doc's path is the bucket. ``ancestor_ids`` collects only
    doc-backed slots strictly above the node (synthetic sections and the root
    contribute no id), ordered root→nearest.
    """
    _, children, _ = build_tree(nodes, edges)
    doc_ids = {n["id"] for n in nodes}
    html_ids = {n["id"] for n in nodes if str(n.get("source_type") or "") != "pdf"}
    segs_of = {n["id"]: site_segments(n) for n in nodes}

    records: dict[str, TreeRecord] = {}
    # BFS from the synthetic root, carrying (depth, path, doc-backed ancestors).
    stack: list[tuple[str, int, str, tuple[str, ...]]] = [(SEC_PREFIX, 0, "", ())]
    while stack:
        key, depth, path, ancestors = stack.pop()
        for child in children.get(key, []):
            if child.startswith(SEC_PREFIX):
                child_path = child[len(SEC_PREFIX):]
            elif child in html_ids:
                child_path = "/".join(segs_of[child])
            elif key in doc_ids:
                child_path = path  # linker-parented: inherit the linker's path
            else:
                child_path = "/".join(segs_of[child])  # bucket fallback
            if child in doc_ids:
                records[child] = TreeRecord(
                    parent_id=key if key in doc_ids else "",
                    depth=depth + 1,
                    path=child_path,
                    ancestor_ids=ancestors,
                )
                child_ancestors = ancestors + (child,)
            else:
                child_ancestors = ancestors
            stack.append((child, depth + 1, child_path, child_ancestors))
    return records


def layered_positions(
    all_nodes: list[dict[str, Any]],
    children: dict[str, list[str]],
    root: str = SEC_PREFIX,
) -> dict[str, tuple[float, float]]:
    """Deterministic left-to-right layered tree positions in unit coordinates.

    x = depth / max_depth (root at x=0); leaves get successive y slots in a
    stable order, internal nodes sit at the mean y of their children — the
    layout the chain-export SVG uses for "path to root" readability.
    """
    titles = {n["id"]: str(n.get("title") or "") for n in all_nodes}

    def _kids(key: str) -> list[str]:
        return sorted(children.get(key, []), key=lambda k: (titles.get(k, k), k))

    depth_of: dict[str, int] = {root: 0}
    order: list[str] = [root]
    i = 0
    while i < len(order):
        key = order[i]
        i += 1
        for child in _kids(key):
            depth_of[child] = depth_of[key] + 1
            order.append(child)

    max_depth = max(depth_of.values()) or 1
    leaf_count = sum(1 for k in depth_of if not children.get(k)) or 1
    ys: dict[str, float] = {}
    next_slot = 0

    def _assign(key: str) -> float:
        nonlocal next_slot
        kids = _kids(key)
        if not kids:
            y = (next_slot + 0.5) / leaf_count
            next_slot += 1
        else:
            y = sum(_assign(k) for k in kids) / len(kids)
        ys[key] = y
        return y

    _assign(root)
    return {
        key: (round(depth_of[key] / max_depth, 4), round(ys[key], 4))
        for key in depth_of
        if key in ys
    }

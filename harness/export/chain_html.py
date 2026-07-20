"""Self-contained retrieval-chain HTML export — how one turn's context evolved.

Renders the ordered ``ChainStep`` events captured by ``harness.tools.events``
(``bundle.chain``) as a readable story: a timeline of tool calls (args + verbatim
routing/steering notes), the documents each call retrieved (origin-badged:
vector / link_expansion / topic_subgraph), and a context-evolution table showing
when each distinct document first entered the context and whether it ended up
cited ``[n]`` in the answer. Same discipline as ``html.py``: one file, inline
CSS + JS, no external requests.

Separate exporter (not an ``include_chain`` flag on ``HtmlExporter``) because the
audience differs: this is the developer/debug story of the retrieval, the HTML
export is the SME-facing answer review. Enable via ``export.formats`` config.
The pure helpers (``_step_html``, ``_evolution_rows``) are reused by the
trace-read-back path (``harness.export.chain_from_trace``).
"""

from __future__ import annotations

import html as html_mod
import json
from typing import Any

from harness.export.base import Exporter, ExportOptions
from harness.export.bundle import ExportBundle
from harness.export.registry import register_exporter

_CSS = """
:root { --accent: #2456a3; --border: #d0d7de; --vector: #dbeafe; --vector-b: #1d4ed8;
        --expand: #ffedd5; --expand-b: #c2410c; --topic: #ede9fe; --topic-b: #6d28d9;
        --tree: #ccfbf1; --tree-b: #0d9488;
        --cited: #d3f9d8; --cited-b: #2b8a3e; color-scheme: light; }
* { box-sizing: border-box; }
body { font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
       margin: 0 auto; max-width: 70rem; padding: 2rem 1.25rem 4rem; color: #1f2328; }
h1 { font-size: 1.4rem; line-height: 1.3; }
h2 { font-size: 1.1rem; margin-top: 2rem; border-bottom: 1px solid var(--border);
     padding-bottom: .3rem; }
.meta { color: #57606a; font-size: .85rem; }
.step { border: 1px solid var(--border); border-left: 4px solid var(--accent);
        border-radius: 8px; padding: .8rem 1rem; margin: 1rem 0; }
.step h3 { margin: 0 0 .35rem; font-size: 1rem; }
.step .args { font-family: ui-monospace, monospace; font-size: .82rem; color: #333;
              background: #f6f8fa; border-radius: 6px; padding: .4rem .6rem;
              overflow-x: auto; white-space: pre-wrap; }
.note { color: #9a6700; background: #fff8c5; border-radius: 6px; font-size: .82rem;
        padding: .25rem .6rem; margin: .3rem 0; font-family: ui-monospace, monospace; }
.node { display: flex; flex-wrap: wrap; gap: .45em; align-items: baseline;
        padding: .3rem .2rem; border-top: 1px dashed var(--border); font-size: .86rem;
        cursor: pointer; }
.node.hl { background: #fff3bf; }
.node a { color: inherit; }
.badge { display: inline-block; border: 1px solid var(--border); border-radius: 999px;
         padding: 0 .5em; font-size: .72rem; white-space: nowrap; }
.badge.vector { background: var(--vector); border-color: var(--vector-b); color: var(--vector-b); }
.badge.link_expansion { background: var(--expand); border-color: var(--expand-b); color: var(--expand-b); }
.badge.topic_subgraph { background: var(--topic); border-color: var(--topic-b); color: var(--topic-b); }
.badge.tree_ancestor { background: var(--tree); border-color: var(--tree-b); color: var(--tree-b); }
.badge.cited { background: var(--cited); border-color: var(--cited-b); color: var(--cited-b);
               font-weight: 600; }
.badge.new { background: #e7f5ff; border-color: #1971c2; color: #1971c2; }
.score { color: #57606a; font-size: .78rem; }
table { border-collapse: collapse; font-size: .84rem; width: 100%; }
td, th { border: 1px solid var(--border); padding: .3rem .55rem; text-align: left;
         vertical-align: top; }
tr.hl td { background: #fff3bf; }
tr[data-doc] { cursor: pointer; }
details { margin: .5rem 0 0; }
details summary { cursor: pointer; font-size: .82rem; color: #57606a; }
details pre { font-size: .78rem; background: #f6f8fa; border-radius: 6px;
              padding: .6rem .75rem; overflow-x: auto; white-space: pre-wrap; }
.empty { color: #57606a; font-style: italic; }
"""

# Clicking any node row (or evolution row) highlights every appearance of that
# document across the whole chain — the "follow one doc through the run" gesture.
_JS = """
document.querySelectorAll('[data-doc]').forEach(el =>
  el.addEventListener('click', () => {
    const doc = el.dataset.doc;
    const on = !el.classList.contains('hl');
    document.querySelectorAll('[data-doc]').forEach(e => e.classList.remove('hl'));
    if (on) document.querySelectorAll('[data-doc="' + doc + '"]')
      .forEach(e => e.classList.add('hl'));
  }));
"""


def _esc(text: str) -> str:
    return html_mod.escape(str(text), quote=True)


def _cited_refs(attribution: Any) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Reference number by chunk_id / doc_id / source_url, for cited-flag lookup."""
    by_chunk: dict[str, int] = {}
    by_doc: dict[str, int] = {}
    by_url: dict[str, int] = {}
    for ref in getattr(attribution, "references", []) or []:
        cit = ref.citation
        if getattr(cit, "chunk_id", ""):
            by_chunk.setdefault(cit.chunk_id, ref.n)
        if getattr(cit, "doc_id", ""):
            by_doc.setdefault(cit.doc_id, ref.n)
        if getattr(cit, "source_url", ""):
            by_url.setdefault(cit.source_url, ref.n)
    return by_chunk, by_doc, by_url


def _node_cited_n(node: dict[str, Any], cited: tuple[dict, dict, dict]) -> int | None:
    """The answer reference number this node supports, if any (chunk > doc > url)."""
    by_chunk, by_doc, by_url = cited
    for key, table in (
        (node.get("chunk_id"), by_chunk),
        (node.get("matched_chunk"), by_chunk),
        (node.get("doc_id"), by_doc),
        (node.get("source_url"), by_url),
    ):
        if key and key in table:
            return table[key]
    return None


def _doc_key(node: dict[str, Any]) -> str:
    return node.get("doc_id") or node.get("source_url") or node.get("chunk_id") or "?"


def _node_html(node: dict[str, Any], *, is_new: bool, cited_n: int | None) -> str:
    origin = node.get("retrieval_origin") or "vector"
    title = node.get("title") or node.get("source_url") or "(untitled)"
    url = node.get("source_url") or ""
    title_html = f"<a href='{_esc(url)}'>{_esc(title)}</a>" if url else _esc(title)
    bits = [f"<span class='badge {_esc(origin)}'>{_esc(origin)}</span>"]
    if node.get("category"):
        bits.append(f"<span class='badge'>{_esc(node['category'])}</span>")
    if node.get("doc_type"):
        bits.append(f"<span class='badge'>{_esc(node['doc_type'])}</span>")
    if origin == "link_expansion" and node.get("linked_from"):
        seeds = ", ".join(str(s)[:8] for s in node["linked_from"])
        bits.append(f"<span class='meta'>← from {_esc(seeds)}</span>")
    if origin == "topic_subgraph" and node.get("topic_hub"):
        bits.append(f"<span class='meta'>hub {_esc(node['topic_hub'])}</span>")
    bits.append(title_html)
    if isinstance(node.get("score"), (int, float)):
        bits.append(f"<span class='score'>score {node['score']:.3f}</span>")
    if is_new:
        bits.append("<span class='badge new'>new</span>")
    if cited_n is not None:
        bits.append(f"<span class='badge cited'>cited [{cited_n}]</span>")
    return f"<div class='node' data-doc='{_esc(_doc_key(node))}'>{''.join(bits)}</div>"


def _step_html(
    step: dict[str, Any],
    *,
    seen_docs: set[str],
    cited: tuple[dict, dict, dict],
    include_output: bool,
) -> str:
    """One timeline card. Mutates ``seen_docs`` (first-appearance tracking)."""
    head_bits = [f"Step {step.get('seq', '?')} — <code>{_esc(step.get('tool', '?'))}</code>"]
    if isinstance(step.get("duration_ms"), (int, float)):
        head_bits.append(f"<span class='meta'>{step['duration_ms']:.0f} ms</span>")
    nodes = step.get("nodes") or []
    head_bits.append(f"<span class='meta'>{len(nodes)} node(s)</span>")
    parts = [f"<article class='step'><h3>{' · '.join(head_bits)}</h3>"]
    args = {k: v for k, v in (step.get("args") or {}).items() if v not in ("", None)}
    if args:
        parts.append(f"<div class='args'>{_esc(json.dumps(args, ensure_ascii=False))}</div>")
    for note in step.get("notes") or []:
        parts.append(f"<div class='note'>{_esc(note)}</div>")
    for node in nodes:
        key = _doc_key(node)
        is_new = key not in seen_docs
        seen_docs.add(key)
        parts.append(_node_html(node, is_new=is_new, cited_n=_node_cited_n(node, cited)))
    if include_output and step.get("raw_output"):
        parts.append(
            "<details><summary>Raw tool output</summary>"
            f"<pre>{_esc(step['raw_output'])}</pre></details>"
        )
    parts.append("</article>")
    return "".join(parts)


def _evolution_rows(chain: list[dict[str, Any]], attribution: Any) -> list[dict[str, Any]]:
    """One row per distinct document, in first-seen order.

    Keys: doc_key, title, source_url, category, first_step, origins (set→sorted),
    chunk_count, cited_n. This is the "which docs made it into context, which
    became citations" view — every sunk node IS judge-visible context, so the
    interesting delta is retrieved → cited.
    """
    cited = _cited_refs(attribution)
    rows: dict[str, dict[str, Any]] = {}
    for step in chain:
        for node in step.get("nodes") or []:
            key = _doc_key(node)
            row = rows.setdefault(
                key,
                {
                    "doc_key": key,
                    "title": node.get("title") or node.get("source_url") or "(untitled)",
                    "source_url": node.get("source_url") or "",
                    "category": node.get("category") or "",
                    "first_step": step.get("seq"),
                    "origins": set(),
                    "chunk_count": 0,
                    "cited_n": None,
                },
            )
            row["origins"].add(node.get("retrieval_origin") or "vector")
            row["chunk_count"] += 1
            if row["cited_n"] is None:
                row["cited_n"] = _node_cited_n(node, cited)
    out = list(rows.values())
    for row in out:
        row["origins"] = sorted(row["origins"])
    return out


_ORIGIN_STROKE = {
    "vector": "#1d4ed8",
    "link_expansion": "#c2410c",
    "topic_subgraph": "#6d28d9",
    "tree_ancestor": "#0d9488",
}
# Node fill by source category: the 8 validated categorical hues for the
# information-carrying categories, muted neutrals for the epar mass + tail
# (same visual language as the KB map, scripts/lib/graph_map/template.html).
_CATEGORY_FILL = {
    "medicine_page": "#2a78d6", "scientific_guideline": "#008300", "qa": "#e87ba4",
    "regulatory_overview": "#eda100", "regulatory_procedure": "#1baf7a", "news": "#eb6834",
    "meeting_doc": "#4a3aa7", "presentation": "#e34948",
    "epar": "#9aa7b8", "herbal": "#7d8f6d", "glossary": "#a08d7a",
    "veterinary": "#9c7f96", "other": "#8b939c",
}


def _tree_svg(chain: list[dict[str, Any]], attribution: Any) -> str:
    """Inline SVG: the retrieved documents placed in the site tree.

    Only the documents this turn touched exist in the drawing — plus the
    synthetic (grey) section skeleton connecting them up to the site root, so
    the "traverse up to the root with awareness of each level" story is
    visible per turn. Layout is layered left-to-right (root at the left,
    depth = column; ``harness.indexing.site_tree.layered_positions``). Grey
    solid edges = tree structure; dashed orange lines = the captured
    ``linked_from`` provenance (link expansion / ancestor context seeds).
    Fill = category, stroke = retrieval origin, thick green stroke = cited.
    Clicking a doc node highlights it everywhere via the shared data-doc
    handler. Dependency-free (no igraph).
    """
    from harness.indexing.site_tree import SEC_PREFIX, build_tree, layered_positions

    rows = _evolution_rows(chain, attribution)
    if len(rows) < 2:
        return ""
    by_doc: dict[str, dict[str, Any]] = {}
    for step in chain:
        for node in step.get("nodes") or []:
            by_doc.setdefault(_doc_key(node), node)
    docs = [
        {
            "id": row["doc_key"],
            "title": row["title"],
            "category": row["category"],
            "source_url": row["source_url"],
            "topic_path": (by_doc.get(row["doc_key"]) or {}).get("topic_path") or "",
            # missing on old traces → treated as html (breadcrumb/URL parenting)
            "source_type": (by_doc.get(row["doc_key"]) or {}).get("source_type") or "",
        }
        for row in rows
    ]
    prov_edges: list[tuple[str, str]] = []
    for key, node in by_doc.items():
        for seed in node.get("linked_from") or []:
            if str(seed) in by_doc:
                prov_edges.append((str(seed), key))
    sections, children, tree_edges = build_tree(docs, prov_edges)
    pos = layered_positions(docs + sections, children)

    leaf_count = sum(1 for k in pos if not children.get(k))
    width, pad = 720, 30
    height = max(300, 26 * leaf_count + 2 * pad)

    def _xy(key: str) -> tuple[float, float]:
        x, y = pos[key]
        return pad + x * (width - 2 * pad - 60), pad + y * (height - 2 * pad)

    parts = [
        f"<svg viewBox='0 0 {width} {height}' role='img' "
        "style='max-width:100%;border:1px solid var(--border);border-radius:8px'>"
    ]
    # tree skeleton first (underneath): grey solid parent→child edges
    for s, t in tree_edges:
        if s not in pos or t not in pos:
            continue
        x1, y1 = _xy(s)
        x2, y2 = _xy(t)
        parts.append(
            f"<line x1='{x1:.0f}' y1='{y1:.0f}' x2='{x2:.0f}' y2='{y2:.0f}' "
            "stroke='#d0d7de' stroke-width='1.2'/>"
        )
    # provenance overlay: dashed orange seed→doc lines
    for s, t in prov_edges:
        if s not in pos or t not in pos:
            continue
        x1, y1 = _xy(s)
        x2, y2 = _xy(t)
        parts.append(
            f"<line x1='{x1:.0f}' y1='{y1:.0f}' x2='{x2:.0f}' y2='{y2:.0f}' "
            "stroke='#c2410c' stroke-width='1.2' stroke-dasharray='4 3'/>"
        )
    # grey section skeleton nodes (the ancestor path — not retrieved docs)
    for sec in sections:
        key = sec["id"]
        if key not in pos:
            continue
        x, y = _xy(key)
        label = sec["title"] if key != SEC_PREFIX else "ema.europa.eu"
        parts.append(
            f"<g><circle cx='{x:.0f}' cy='{y:.0f}' r='4' fill='#c7ced6' "
            f"stroke='#9aa4b2' stroke-width='1'>"
            f"<title>{_esc('/' + key[len(SEC_PREFIX):] if key != SEC_PREFIX else label)}</title>"
            f"</circle>"
            f"<text x='{x:.0f}' y='{y - 8:.0f}' text-anchor='middle' "
            f"font-size='9' fill='#9aa4b2'>{_esc(str(label)[:20])}</text></g>"
        )
    # retrieved documents on top
    for row in rows:
        key = row["doc_key"]
        if key not in pos:
            continue
        node = by_doc.get(key, {})
        x, y = _xy(key)
        fill = _CATEGORY_FILL.get(row["category"], "#8b939c")
        cited = row["cited_n"] is not None
        origin = (node.get("retrieval_origin") or "vector") if node else "vector"
        stroke = "#2b8a3e" if cited else _ORIGIN_STROKE.get(origin, "#1d4ed8")
        r = 8 + 2 * min(row["chunk_count"], 4)
        title = row["title"] + (f" — cited [{row['cited_n']}]" if cited else "")
        parts.append(
            f"<g data-doc='{_esc(key)}' style='cursor:pointer'>"
            f"<circle cx='{x:.0f}' cy='{y:.0f}' r='{r}' fill='{fill}' "
            f"stroke='{stroke}' stroke-width='{3 if cited else 1.5}'>"
            f"<title>{_esc(title)}</title></circle>"
            f"<text x='{x + r + 4:.0f}' y='{y + 3:.0f}' text-anchor='start' "
            f"font-size='10' fill='#57606a'>{_esc((row['title'] or key)[:32])}</text></g>"
        )
    parts.append("</svg>")
    return "".join(parts)


@register_exporter("chain_html")
class ChainHtmlExporter(Exporter):
    """The retrieval-chain debug view; see the module docstring."""

    name = "chain_html"
    file_extension = "html"
    mime = "text/html"

    def filename(self, bundle: ExportBundle, options: ExportOptions) -> str:
        # "_chain" suffix so it never collides with HtmlExporter's file.
        stem = options.filename_template.format(
            msg_num=bundle.msg_num, run8=(bundle.run_id or "run")[:8], recipe=bundle.recipe_name
        )
        return f"{stem}_chain.{self.file_extension}"

    def render(self, bundle: ExportBundle, options: ExportOptions) -> str:
        chain = bundle.chain or []
        parts: list[str] = [
            "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
            "<meta name='viewport' content='width=device-width, initial-scale=1'>",
            f"<title>Chain — {_esc(bundle.question[:110])}</title>",
            f"<style>{_CSS}</style></head><body>",
            f"<h1>Retrieval chain: {_esc(bundle.question)}</h1>",
        ]
        meta_bits = [b for b in (
            bundle.asked_at,
            f"recipe {bundle.recipe_name}" if bundle.recipe_name else "",
            f"run {bundle.run_id[:8]}" if bundle.run_id else "",
            f"trace {bundle.trace_id[:12]}" if bundle.trace_id else "",
        ) if b]
        if meta_bits:
            parts.append(f"<p class='meta'>{_esc(' · '.join(meta_bits))}</p>")
        if options.include_trace_link and bundle.trace_url:
            parts.append(f"<p class='meta'><a href='{_esc(bundle.trace_url)}'>View trace →</a></p>")

        parts.append("<h2>Tool-call timeline</h2>")
        if not chain:
            parts.append(
                "<p class='empty'>No chain captured for this turn — it predates chain "
                "capture, or no retrieval tool ran.</p>"
            )
        cited = _cited_refs(bundle.attribution)
        seen_docs: set[str] = set()
        for step in chain:
            parts.append(
                _step_html(
                    step,
                    seen_docs=seen_docs,
                    cited=cited,
                    include_output=options.include_chain_output,
                )
            )

        if chain and options.include_chain_graph:
            svg = _tree_svg(chain, bundle.attribution)
            if svg:
                parts.append("<h2>Documents touched this turn</h2>")
                parts.append(
                    "<p class='meta'>Site tree, root at the left — grey nodes/edges = "
                    "the section levels connecting the retrieved documents to "
                    "ema.europa.eu (nothing else is drawn). Fill = category, dashed "
                    "orange = retrieval provenance (link expansion / ancestor seeds), "
                    "green ring = cited. Click a doc to highlight it across the "
                    "timeline.</p>"
                )
                parts.append(svg)

        if chain:
            parts.append("<h2>Context evolution</h2>")
            parts.append(
                "<p class='meta'>Every retrieved document, in order of first appearance. "
                "All of these were visible context; <em>cited</em> marks the ones the "
                "answer actually references.</p>"
            )
            parts.append(
                "<table><tr><th>First step</th><th>Document</th><th>Category</th>"
                "<th>Origin(s)</th><th>Chunks</th><th>Cited</th></tr>"
            )
            for row in _evolution_rows(chain, bundle.attribution):
                link = (
                    f"<a href='{_esc(row['source_url'])}'>{_esc(row['title'])}</a>"
                    if row["source_url"]
                    else _esc(row["title"])
                )
                cited_cell = (
                    f"<span class='badge cited'>[{row['cited_n']}]</span>"
                    if row["cited_n"] is not None
                    else "—"
                )
                parts.append(
                    f"<tr data-doc='{_esc(row['doc_key'])}'><td>{row['first_step']}</td>"
                    f"<td>{link}</td><td>{_esc(row['category'])}</td>"
                    f"<td>{_esc(', '.join(row['origins']))}</td>"
                    f"<td>{row['chunk_count']}</td><td>{cited_cell}</td></tr>"
                )
            parts.append("</table>")

        # Machine-readable copy — same interchange dict as the answer export.
        parts.append(
            "<script type='application/json' id='ema-export-bundle'>"
            + json.dumps(bundle.to_dict(), ensure_ascii=False).replace("</", "<\\/")
            + "</script>"
        )
        parts.append(f"<script>{_JS}</script></body></html>")
        return "".join(parts)

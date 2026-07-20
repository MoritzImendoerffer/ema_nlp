# Chain capture & export — making a run readable

`harness/tools/events.py` (capture) → `harness/export/chain_html.py` (render) →
`harness/export/chain_from_trace.py` + `scripts/render_trace.py` (post-hoc).

Every retrieval-shaped tool call records what it did; the per-turn export turns
that record into a document you can read instead of clicking through MLflow
spans. This is the debugging surface for everything in this folder.

## Capture

Two dataclasses:

**`ChainStep`** — one tool call, in run order: `seq`, `tool`, `args`, `notes`
(verbatim `[routing: …]` / `[category filter: …]` / corrective grade lines),
`nodes`, `started_at`, `duration_ms`, `output_chars`, `raw_output`.

**`NodeRef`** — provenance-only projection of one retrieved node (never the
passage text, which lives in the citation path):

```
doc_id, chunk_id, matched_chunk, source_url, title, category, doc_type, score,
retrieval_origin, linked_from, topic_hub, topic_path, source_type
```

`retrieval_origin` is the vocabulary that makes a run legible:

| Origin | Meaning |
|---|---|
| `vector` | Plain semantic hit. |
| `link_expansion` | Reached by following `LINKS_TO` from a seed (`linked_from`). |
| `tree_ancestor` | A site-tree ancestor of a seed (`linked_from`), added for context. |
| `topic_subgraph` | Member of a curated hub (`topic_hub`). |

`topic_path` + `source_type` exist so the export can re-derive the
[site tree](site_tree.md) **offline**, with no Neo4j access at render time.

Mechanism: a `ContextVar` sink (`capture_chain_events()`), the same idiom as the
node sink. Outside a capture scope `record_tool_event()` is a **no-op**, so tools
are safe to call anywhere. Nested scopes share the outermost sink. The workflow
adapter wraps each turn and puts the steps on `ExportBundle.chain`.

## The per-turn export

The ⬇ Export button under each answer renders the configured formats
(`harness/configs/export/default.yaml`), including `<name>_chain.html`:

- **Tool-call timeline** — one card per call: tool, args, verbatim steering
  notes, duration, node count.
- **Per-node badges** — origin, category/doc_type, `← from <seeds>` for
  link/ancestor provenance, `hub <key>`, **new** (first appearance in the run),
  **cited [n]** (matched to the answer's attribution).
- **Site-tree view** — see below.
- **Context-evolution table** — one row per distinct document: first-seen step,
  origins, chunk count, cited-as. Every retrieved node *is* judge-visible
  context, so the interesting delta is retrieved → cited.
- **Raw tool output** behind `include_chain_output` (off by default).
- The machine-readable bundle JSON (`#ema-export-bundle`).

Clicking any document — node row, table row, or SVG node — highlights it
everywhere. That is the "follow one document through the run" gesture.

## The site-tree view

Replaces the old force-directed subgraph. The retrieved documents are placed in
the **site tree**, layered left-to-right with the root at the left:

```
ema.europa.eu ─ medicines ─ human ─ EPAR ─ [comirnaty page] ═╗ cited
   (grey)        (grey)     (grey)  (grey)                   ├─ [overview.pdf]   link_expansion
                                                             ├─ [variation rpt]  link_expansion
                                                             └─ [safety update]  link_expansion
```

- **Only** the retrieved documents and the grey section path connecting them to
  the root are drawn — nothing else exists in the picture.
- Grey solid edges = tree structure; **dashed orange** = retrieval provenance
  (`linked_from`); fill = category; stroke = origin; thick green ring = cited.
- Height grows with the number of leaves; the whole thing is inline SVG with no
  dependency (the exporter no longer needs igraph).

Because it uses the same derivation as the KB map, a turn reads as a traversal of
the tree you already know from `ema_kb_tree.html`.

Gated by `include_chain_graph` (default on); needs ≥2 distinct documents.

## Post-hoc: chains from any MLflow trace

```bash
python scripts/render_trace.py <trace_id>                 # one turn
python scripts/render_trace.py --run-id <mlflow_run_id>   # every trace of an eval run
```

`chain_from_trace.py` reconstructs `ChainStep`s from the autolog span tree: TOOL
spans give tool name/args/raw output, nested RETRIEVER spans give full node
metadata, and the final node order is parsed from the `format_nodes` string (the
source of truth after rerank/steering). Output goes to
`$EMA_RESULTS_DIR/chains/`.

This is what turns an eval run into browsable evidence — render a
`scripts/run_eval.py` run id and read the chains instead of pandas tables.

**Honest limits.** Traces predating chain capture still render with whatever the
spans contain. `topic_subgraph` nodes have no RETRIEVER child span, so `doc_id` /
`source_type` are not recoverable post hoc. `topic_path` falls back to the
`path=` tag in the output line when span metadata is absent. Old traces without
either degrade to URL-path parenting in the tree view.

## Adding a tool to the chain view

Call both sinks — that is the whole contract:

```python
sink_nodes(nodes)            # citations + faithfulness judge see the evidence
record_tool_event(
    tool="my_tool", args={...}, notes=[...], nodes=nodes,
    output=rendered, started_at=iso, duration_ms=ms,
)
```

If the tool stamps a new `retrieval_origin`, add a stroke colour in
`_ORIGIN_STROKE` and a `.badge.<origin>` CSS rule.

## Tests

`tests/test_tool_events.py` (capture semantics, `NodeRef` projection incl.
`topic_path`/`source_type`), `tests/test_export_chain.py` (timeline, badges, the
tree SVG: root present, grey sections, one circle per document, dashed
provenance overlay, gating), `tests/test_chain_from_trace.py` (the span contract,
pinned with fake spans and verified against mlflow 3.14).

See also [`../VISUALIZATION.md`](../VISUALIZATION.md) for the KB map and the
NeoDash dashboards.

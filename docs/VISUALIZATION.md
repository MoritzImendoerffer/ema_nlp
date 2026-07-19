# Visualization — knowledge-base map + retrieval-chain exports

Two complementary surfaces, added 2026-07-19 (plan: understanding the knowledge
base, and making "how did the retrieval chain evolve?" answerable without
clicking through raw MLflow spans):

| Surface | What it shows | Entry point |
|---|---|---|
| **KB map** (static HTML) | Every `:Document` + `LINKS_TO` edge as one WebGL map | `scripts/build_graph_map.py` |
| **NeoDash** (live, :5005) | Census / link-audit / topic-hub / drill-down dashboards | `deploy/neo4j/` + `scripts/seed_neodash.py` |
| **Chain export** (per turn) | Tool-call timeline, per-node origin, context evolution | ⬇ Export in Chainlit (`chain_html` format) |
| **Chain from trace** (post hoc) | Same view rebuilt from any MLflow trace / eval run | `scripts/render_trace.py` |

## 1. Static knowledge-base map

```bash
pip install -e ".[viz]"                      # python-igraph (layout, offline only)
python scripts/build_graph_map.py --limit 2000   # smoke build (~seconds)
python scripts/build_graph_map.py --out results/graph_map/ema_kb_map.html
```

One self-contained HTML file (no CDN, no server — open it anywhere, mail it).
Document-level only: ~80k `:Document` nodes + ~100k `LINKS_TO` edges; the 5.8M
`:Chunk` nodes are deliberately excluded.

**Pipeline** (`scripts/build_graph_map.py`): plain-driver Cypher pull →
deterministic igraph layout (DrL for components ≥300 nodes, Fruchterman-Reingold
for small ones; shelf-packed component boxes; isolates in a category-grouped
band; fixed `--seed`) → columnar gzip+base64 payload → `scripts/lib/graph_map/
template.html` with vendored sigma.js 2.4.0 + graphology 0.25.4
(`scripts/lib/graph_map/vendor/`, MIT, pinned).

**Viewer features**: color = category (8 validated categorical hues for the
information-carrying categories; muted neutrals for the dominant `epar` mass and
rare tail — identity there comes from the legend, deliberately), size =
in-degree, category legend with counts + isolate toggles, doc_type/audience/
site_topic dropdown filters, title search (jump + select), click → detail panel
(badges, topic_path, URL, neighbor list). Performance: WebGL nodes are cheap —
the always-on 100k edges are not, so edges render only when zoomed in past a
cutoff or when incident to the hovered/selected node (the LightRAG trick), plus
`hideEdgesOnMove`.

Payload size estimate: ~190 B/node raw → ~4–6 MB HTML for the full graph.
The build prints exact numbers. Regenerate after a graph rebuild; artifacts go
under `results/` (gitignored). Full build verified on marvin-gpu (2026-07-19):
79,882 docs / 99,520 links → 5.1 MB HTML, layout ~90 s.

## 2. NeoDash

See `deploy/neo4j/README.md` §NeoDash. Live dashboards (census, link audit,
topic hubs, doc drill-down) over the same Cypher as
`deploy/neo4j/inspect_queries.cypher`; the dashboard definition is committed at
`deploy/neo4j/neodash_dashboard.json` and round-tripped with
`scripts/seed_neodash.py` (`--dump` after UI edits).

## 3. Retrieval-chain HTML (`chain_html` export)

Every retrieval-shaped tool call (`ema_search`, `corrective_search`,
`topic_context`) records a `ChainStep` event (`harness/tools/events.py` —
ContextVar sink, same idiom as `capture_search_nodes`; no-op outside a capture
scope). The workflow adapter captures them per turn and they land on
`ExportBundle.chain`, so the per-turn **⬇ Export** now includes
`<name>_chain.html` alongside the answer export (`export.formats` in
`harness/configs/export/default.yaml`).

The document shows:
- **Tool-call timeline** — one card per call: tool + args (incl.
  `source_category`), the verbatim `[routing: …]` / `[category filter: …]` /
  corrective-grade notes, duration, node count;
- **per-node origin badges** — `vector` / `link_expansion` (with "← from
  <seed docs>") / `topic_subgraph` (with hub key), plus **new** (first
  appearance of the doc in the run) and **cited [n]** (matched against the
  answer's attribution by chunk → doc → URL);
- **mini subgraph** (`include_chain_graph`) — inline SVG of the docs touched
  this turn; dashed edges = link-expansion provenance, green ring = cited;
- **context-evolution table** — one row per distinct document: first-seen step,
  origins, chunk count, cited-as. All retrieved nodes *are* the judge-visible
  context, so the interesting delta is retrieved → cited;
- raw tool output per step behind `include_chain_output` (off by default);
- the machine-readable bundle JSON (`#ema-export-bundle`), as in the answer
  export.

Clicking any document (node row, table row, SVG node) highlights it everywhere —
the "follow one doc through the run" gesture.

## 4. Rebuilding chains from MLflow traces

```bash
python scripts/render_trace.py <trace_id>                 # one turn
python scripts/render_trace.py --run-id <mlflow_run_id>   # every trace of an eval run
```

`harness/export/chain_from_trace.py` reconstructs `ChainStep`s from the autolog
span tree — TOOL spans give tool name/args/raw output, nested RETRIEVER spans
give full node metadata, and the final node order is parsed from the
`format_nodes` output string (the source of truth after rerank/steering). The
span contract is pinned by fake-span tests (`tests/test_chain_from_trace.py`)
and was verified against real traces on mlflow 3.14 (2026-07-19, marvin-gpu):
`--run-id` resolves the run's experiment and passes it as `locations`
(`search_traces` otherwise only looks in experiment 0). Traces predating chain
capture still render (with whatever the spans contain) — the question falls
back to the `user_msg` input on autolog's `FunctionAgent.run` root span when no
`record_answer_on_span` span exists. `scripts/run_eval.py`
run ids feed straight into `--run-id`, which answers the docs/eval pain point —
e.g. re-render any run from `docs/eval/2026-07-13_topic_subgraphs.md` and read
the chains instead of pandas tables.

## 5. Remote access via `ssh -L`

Everything above runs on **marvin-gpu** (the host with the full Neo4j graph,
`mlflow.db`, and the Docker services). From another machine (e.g. the laptop),
forward the ports of whatever surface you want to open — the services bind to
`localhost` on the host, so an SSH tunnel is the intended access path:

```bash
# NeoDash: the UI is on :5005, but NeoDash runs client-side in YOUR browser and
# opens the database connection itself — so Bolt :7687 must be forwarded too.
ssh -L 5005:localhost:5005 -L 7687:localhost:7687 moritz@marvin-gpu

# Neo4j Browser: same client-side pattern — UI on :7474, Bolt on :7687.
ssh -L 7474:localhost:7474 -L 7687:localhost:7687 moritz@marvin-gpu

# MLflow UI (traces, eval runs, feedback assessments):
ssh -L 5000:localhost:5000 moritz@marvin-gpu

# Or all of them in one session:
ssh -L 5005:localhost:5005 -L 7474:localhost:7474 \
    -L 7687:localhost:7687 -L 5000:localhost:5000 moritz@marvin-gpu
```

Then open `http://localhost:<port>` locally and, in the NeoDash / Neo4j Browser
connect dialog, use host `localhost`, port `7687`, protocol **`bolt`** (not
`neo4j://` — routing discovery would redirect to the server's advertised
address instead of the tunneled one; see `deploy/neo4j/README.md`). Tunneling
only the UI port is the classic mistake: the page loads, the DB connection
fails.

Gotchas:

- **Port collisions on the local machine** — if a local Neo4j already holds
  7474/7687 (the laptop does: its project container is remapped to 7688/7475
  for exactly this reason), pick free local ports and connect to those instead:
  `ssh -L 17687:localhost:7687 -L 17474:localhost:7474 …` → browser to
  `http://localhost:17474`, connect dialog port `17687`.
- **Static artifacts need no tunnel** — the KB map and chain exports are
  self-contained single files; `scp` them (or let Nextcloud sync them) and open
  locally:
  `scp moritz@marvin-gpu:github_repos/ema_nlp/results/graph_map/ema_kb_map.html .`
- MLflow on :5000 is only up while `run_ui.sh` (or a manual
  `mlflow server`) is running on the host.

## Design decisions

- **One self-contained file per artifact** — map and chain exports embed all
  JS/CSS/data (gzip+base64, decoded via the browser's `DecompressionStream`).
  Nothing fetches from a CDN.
- **Layout offline, in Python** — no GDS on the Community server, and browser-side
  force layout on 80k nodes burns minutes on every open. igraph is a `viz`
  extra, never a runtime dep of the app (the chain SVG falls back to a circle
  layout without it).
- **Mini subgraph is SVG, not sigma.js** — a per-turn subgraph is ≤~50 nodes;
  vendoring 200 KB of WebGL into every export is unjustified (repo rule).
- **`chain_html` is its own exporter**, not a flag on the SME-facing HTML
  export: different audience, zero risk to the reviewed answer document,
  enabled purely by config.

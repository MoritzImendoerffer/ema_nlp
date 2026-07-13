# Plan: precomputed topic subgraphs — hub-seeded, metadata-qualified, budget-guarded context

*Status: 🚧 **steps 1–4 implemented + offline-tested** (2026-07-13, branch
`claude/agentic-rag-foundation`) — config+loader (`configs/hubs/default.yaml`,
`harness/retrieval/hubs.py`), membership build (`harness/indexing/subgraphs.py`,
`upsert_topic_hubs`, `scripts/manage_topic_hubs.py`, `update_graph.py` step
`subgraphs`, propagate), node metadata (`topic_hubs` on projection/ingest/entity),
and the `topic_context` tool + `retrieval.subgraph` recipe keys + `topic_agent`
recipe. **Steps 5–6 (live build + T2 eval) remain — GPU host.** Feasibility was
**verified live** (§2 evidence). Complements
[`metadata_steering.md`](metadata_steering.md) (which refines the signal for existing
top-k steering); this plan adds the capability top-k structurally cannot provide:
exhaustive, curated topic context. See `docs/RETRIEVAL.md` §7.1 for the shipped
surface.*

## 1. Why

Two retrieval needs the current stack cannot serve, both visible in the benchmark:

- **T2 scoping questions** compare *sibling* documents ("which referral procedure
  charges fees regardless of initiator?"). A top-k hit lands on one sibling; answering
  needs the others. All 10 T2 items draw on the referral-procedures Q&A family —
  cross-sibling by construction.
- **Exhaustive enumeration** ("all guidelines on X"). Similarity-ranked top-k returns the
  *best-matching* members of a set, never provably *all* of them; the existing
  `graph.expand` is 1-hop, capped at 3, and seeded by whatever vector hits happen to be —
  context enrichment, not enumeration.

EMA's site already encodes the answer: **topic hub pages are curated indices** whose
`LINKS_TO` fan-out (2 hops: hub → detail page → PDF) *is* the exhaustive, EMA-curated
member list. The design: identify hubs **in advance** (SME- or agent-proposed, human
confirmed), precompute each hub's subgraph as **membership stamps**, and at query time
expand a hit *only within its own subgraph*, under explicit context-budget guardrails.
Precomputation converts the fragile part (multi-hop traversal at query time) into an
offline, inspectable artifact; query time becomes an indexed property lookup.

## 2. Feasibility evidence (verified live, 2026-07-13)

- **T2 reachability — PASSED.** The 3 gold documents behind all 10 T2 items
  (`questions-answers-article-{31-pharmacovigilance,30,31-non-pharmacovigilance}-…`) are
  all `:Document` nodes, and share a **1-hop** common `LINKS_TO` ancestor of exactly the
  expected identity: *"Referral procedures: human medicines"*
  (`category=regulatory_overview`, fanout 16; a second guidance hub, fanout 29, also
  reaches all three). The hub's qualified 2-hop subgraph is a coherent ~100-doc bundle
  (15 `qa` pages, 18 `regulatory-procedural-guideline` docs, overview siblings).
- **Two hops are required.** The GVP hub reaches 22 docs at 1 hop but **143 guideline
  documents at 2 hops** (125 PDFs + 18 HTML detail pages) — EMA's structure is
  hub → guideline detail page → PDF.
- **The metadata qualifier is what makes the walk reliable.** Unqualified 2-hop reverse
  ancestors of the T2 gold docs are dominated by news pages that merely link *into* the
  topic; requiring `category='regulatory_overview'` isolates the true hub immediately.
  Symmetrically: hub out-links mix PDFs (have `doc_type`) and HTML detail pages (only
  `category`) — every qualifier must be **`doc_type` OR `category`**, never `doc_type`
  alone.
- **Raw fanout is a trap.** "Archive of development of GVP" out-fans the current GVP page
  126 vs 22 — archive/news pages must be penalized, not rewarded, in hub detection.

## 3. What already exists to build on

- **The canonical label pipeline (2026-07-13)** — Mongo `document_metadata` (one row per
  URL + per-label-group provenance), `scripts/enrich_document_metadata.py`,
  ingest join, `scripts/propagate_metadata_to_graph.py`, `scripts/update_graph.py`.
  Membership is *the same kind of derived fact* and should ride the same rails.
- **Labels on the graph**: `category` (13 values, 100%), `doc_type` (96.6% of PDFs),
  `audience`/`site_topic` (HTML). `LINKS_TO` edges (99,520) with typed
  `{kind, link_context, document_type}` properties; link audit confirms hubs are real
  (median in-degree 1 → reverse steps are near-deterministic).
- **`HierarchicalPGRetriever._expand`** (`harness/indexing/property_graph.py`) — the
  best-chunk-per-document Cypher pattern (embed query once, cosine per chunk, take the
  best per doc) to reuse with a membership filter instead of a hop pattern.
- **Steering precedence + routing table** (`harness/retrieval/steering.py`,
  `configs/routing/*.yaml`) — the precedence idiom (explicit arg > routing > profile) and
  the config-not-code rule this plan must follow.
- **`scripts/inspect_graph.py`** + `deploy/neo4j/inspect_queries.cypher` — the
  verification/curation surface (Neo4j Browser at :7474 gives click-a-node property
  panels + hover captions out of the box).

## 4. Design

### 4.1 Seed list — `configs/hubs/default.yaml` (pure data, SME-editable)

```yaml
hubs:
  - key: referral_procedures
    seed_url: https://www.ema.europa.eu/en/human-regulatory-overview/post-authorisation/referral-procedures-human-medicines
    status: confirmed            # confirmed | proposed  (only confirmed hubs are built)
    proposed_by: sme             # sme | agent | discovery
    walk:                        # per-hub — hubs differ wildly in shape (COVID: 340 1-hop links)
      hops: 2
      categories: [qa, scientific_guideline, regulatory_procedure, regulatory_overview]
      doc_types: []              # OR-qualified with categories (coverage asymmetry, §2)
      exclude_audience: [Veterinary, Corporate]
```

Load-time validation (fail loudly): seed URL must resolve to a `:Document` in the graph
(EMA reorganizations silently break URLs), category/doc_type vocab checked, `hops >= 1`.
`$EMA_CONFIG_DIR/hubs/` shadows the repo file, matching routing.

### 4.2 Hub auto-detection — explainable qualified-fanout score, NOT graph centrality

`scripts/manage_topic_hubs.py propose` ranks candidates with plain Cypher:

- **candidates**: `category = 'regulatory_overview'` (optionally scoped by `site_topic`);
- **score**: count of out-`LINKS_TO` whose target matches the qualifier categories/
  doc_types, weighted toward `link_context IN [file_component, card_or_listing]`
  (curation links) over `inline`;
- **penalties**: title matching archive/news patterns; `audience` Corporate/Veterinary.

Rationale: hub-ness here is a *labeled* property (EMA tells us which pages are overview
pages) more than an emergent one, and the human-confirmation gate demands explainable
scores. Classic graph algorithms are the fallback, not the default: **HITS**
(hubs-and-authorities — the textbook match), PageRank on the reversed graph, or
Louvain/label-propagation community detection (seed-free topic clusters, hubs = top
out-degree per community). All need the **GDS plugin, which is NOT installed** in
`deploy/neo4j/` (verified 2026-07-13: `gds.version()` unknown) — a container config
change. Revisit only if the simple score demonstrably misses hubs.

`propose` writes candidates into the YAML with `status: proposed` (agent- or
SME-supplied URLs enter the same way); a human flips to `confirmed`; `report` prints
per-hub size + composition histograms so oversized/polluted subgraphs are visible
*before* they go live. Curation viz: Neo4j Browser (:7474) already provides
click-to-inspect + hover; add a "hub candidates / subgraph preview" section to
`deploy/neo4j/inspect_queries.cypher`. A bespoke point-and-click UI is **overengineering
for this task** (≤ tens of hubs, confirmed rarely); if a dashboard is ever wanted,
NeoDash over the same queries is the 80/20.

### 4.3 Membership build — same rails as the labels

`build` (in `manage_topic_hubs.py`, callable as an `update_graph.py` step `subgraphs`):
for each **confirmed** hub, run the bounded qualified walk from the seed, collect member
doc URLs, and write `topic_hubs: [keys...]` (list — docs legitimately belong to several
topics) into Mongo `document_metadata` with
`provenance.topic_hubs = {source: "hub_walk", stamped_at, config_hash}`. Propagate adds
`topic_hubs` as a third field group → `:Document.topic_hubs` (list property, indexed).
Ingest joins it like the other labels. Staleness rule: **recompute after any `LINKS_TO`
rebuild**; the `config_hash` + `stamped_at` make violations detectable.

### 4.4 Query-time — lookup, not traversal; pageable map; explicit budget

- Retrieved nodes carry `topic_hubs` (extend `_DOC_PROJECTION` + `_node_from_row`).
- **New agent tool `topic_context(hub_or_doc, page=1)`** returns the **topic map**: the
  subgraph's member catalog (title, `doc_type`/`category`, reference number, revision,
  URL — grouped by detail page so PDF revisions don't read as separate items), ranked by
  query relevance, in fixed-size pages with a total count + `truncated` flag (no silent
  caps). ~30–50 tokens/doc → even a 143-doc subgraph is small, and *nothing enters the
  context unless the agent asks for the next page* — the primary overflow guardrail.
- **Optional budgeted text context**: best-chunk-per-member under a recipe-configured
  token budget (`retrieval.subgraph: {context: map|chunks, max_tokens: 4000, page_size:
  25}`), reusing the `_expand` Cypher with a membership filter. Additive, stamped
  `retrieval_origin="topic_subgraph"` — the MLflow trace shows where every doc came from.
- **Multi-membership policy**: when a hit belongs to several subgraphs, pick the hub whose
  page best embedding-matches the query (routing keywords as tie-break); never expand all
  memberships at full budget.
- **LLM summaries (LlamaIndex recursive-retriever style) are explicitly deferred**: EMA
  titles are long and descriptive, so the title catalog likely suffices; summaries add an
  offline LLM pass + silent staleness on membership change. Build them only if eval shows
  the map is too thin (then: one summary per hub + one-liners per member, re-summarized
  on membership change).

Precedence mirrors the steering stack: explicit agent arg > routing-selected hub >
membership of the vector hits. Prompt instruction (recipe, not code): *"for
list/compare/scoping questions, call `topic_context` on the best hit before answering."*

## 5. Implementation steps (ordered; 1–4 CPU/offline, 5–6 need the live graph/GPU)

1. **Config + loader**: `configs/hubs/default.yaml` + `harness/retrieval/hubs.py`
   (schema, load, validation). Unit tests: vocab/hops validation, shadowing, unknown-seed
   failure (store lookup mocked).
2. **Membership build**: `harness/indexing/subgraphs.py` — the qualified-walk Cypher +
   `document_metadata.upsert_topic_hubs(...)` (third field group, same batching);
   extend `scripts/propagate_metadata_to_graph.py` with the `topic_hubs` group;
   `scripts/manage_topic_hubs.py` (`propose | confirm | build | report`);
   `update_graph.py` gains optional step `subgraphs`. Unit tests: upsert composition
   with the other two groups; walk query string; propose scoring on fixtures.
3. **Node metadata**: `_DOC_PROJECTION` + `_node_from_row` carry `topic_hubs`. Test in
   `test_indexing_property_graph.py` style.
4. **Tool + recipe surface**: `harness/tools/topic_context.py` (pageable map; ranked;
   count + truncated flag), registry entry, `retrieval.subgraph` recipe keys, prompt
   paragraph in the relevant agent prompt file. Offline tests with a fake store.
5. **Live build (GPU host)**: `propose` → confirm `referral_procedures` + `gvp` (+ 2–3
   more from the report) → `build` → propagate → `inspect_graph` spot-checks +
   the new Browser queries.
6. **Eval**: recipe `topic_agent` (steered_agent + subgraph keys); `scripts/run_eval.py`
   over the T2 slice; per-type metrics must improve on T2 with no regression elsewhere
   (the resolved recipe stamp shows the lever honestly).

## 6. Open decisions & risks

- **Where does step-2 code live** — `harness/indexing/` (build-side, chosen above) vs
  `harness/retrieval/`; keep the split: build = indexing, query-time = retrieval/tools.
- **Dynamic listing pages**: EMA's search-driven listing pages render lists client-side —
  their scraped `html_raw` under-represents the fan-out. Curate *static* overview pages
  only; the `report` histograms make thin subgraphs visible.
- **Subgraph size variance**: per-hub walk params handle COVID-sized hubs; `report` must
  print sizes so a 1,000-doc subgraph is a red flag, not a surprise.
- **Revision noise**: group the map by detail page; surface `revision` so the agent can
  say "latest per module". Do NOT silently drop old revisions (regulatory questions can
  be revision-specific).
- **Benchmark honesty**: all 10 T2 items sit in ONE topic family — a T2 win proves the
  mechanism, not breadth. Consider adding 2–3 T2 items from other families (GVP,
  nitrosamines) when extending the benchmark.
- **`site_topic` is NOT a membership substitute** (27% HTML / 0% PDF) — it seeds
  *proposals*, never membership.

## 7. Verification

Offline: unit tests per step 1–4 (no store, no LLM, matching `test_retrieval_steering`
style). Live: step-5 spot-checks (the referral hub's subgraph must contain the 3 T2 gold
docs — the §2 check re-run through the shipped code) and the step-6 eval gate. The §2
reachability evidence stands as the recorded baseline.

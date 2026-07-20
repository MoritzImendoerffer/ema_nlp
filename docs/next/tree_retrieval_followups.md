# Tree-aware retrieval — follow-ups

**Status:** 🚧 in progress — **step 1 done** (measurement report:
[`../eval/2026-07-20_tree_seeding.md`](../eval/2026-07-20_tree_seeding.md)),
steps 2–4 planned. Prerequisite landed 2026-07-20 (tree-aware retrieval,
tree-view chain export, T5 showcase — see [`../RETRIEVAL.md`](../RETRIEVAL.md)
§7.2 and [`../tools/retriever.md`](../tools/retriever.md)).

## Why

The tree machinery works: the backfill places 79,882 documents (55,911 parented
by the link graph, max depth 7), and a live `neo4j_tree` retrieve returns all
three origins — 10 `vector`, 5 `link_expansion`, 3 `tree_ancestor` — with the
level (`path=/…`) on every node.

But the very first T5 showcase run produced a **concrete failure**, which is
exactly what the showcase is for:

> *"Summarize the information available for Comirnaty, including the timeline of
> its regulatory milestones."* → the vector pass seeds on CHMP/COMP **meeting
> minutes**, not the Comirnaty hub page. Traversal then expands from the wrong
> seed. Rephrasing to `"Comirnaty COVID-19 mRNA vaccine authorisation"` does put
> the EPAR overview on the comirnaty branch.

**Diagnosis: seeding, not traversal, is the weak link.** Hub pages are short and
navigational; leaf-chunk cosine similarity favours long documents that repeat the
substance name many times. Every downstream mechanism (expansion, ancestors, the
tree view) is only as good as the seed set it starts from.

This is the benchmark failure the repo rule asks for before adding complexity —
so these follow-ups are now justified, in this order.

## What already exists to build on

- `tree_path` / `tree_depth` / `tree_ancestor_ids` on every `:Document`
  ([`../tools/site_tree.md`](../tools/site_tree.md)).
- `HierarchicalPGRetriever` passes + `GraphRetrievalConfig`
  ([`../tools/retriever.md`](../tools/retriever.md)).
- `benchmark/showcase.jsonl` (5 T5 hub anchors) + per-type MLflow runs +
  `scripts/render_trace.py --run-id` for readable chains.
- The steering seams: `with_categories`, routing table, `doc_type_priority`
  postprocessor.

## Step 1 — measure the miss precisely ✅ DONE (2026-07-20)

**Report: [`../eval/2026-07-20_tree_seeding.md`](../eval/2026-07-20_tree_seeding.md).**
Anchor rank in the final result and in the candidate pool, per showcase item,
plus an ANN sweep over query `k`. Headline: the miss is **three different
problems**, not one.

| Verdict | Items | Meaning |
|---|---|---|
| **ANN recall** | T5-005 | Anchor is the *true* rank-5 chunk but invisible at k≤100 — Neo4j's vector index is approximate. |
| **scoring** | T5-002 (58), T5-004 (~99) | In the pool, ranked too deep. |
| **recall** | T5-001, T5-003 | Not in the top 500 at all — the length-bias hypothesis, confirmed. |

Two findings that changed the plan:

- **`oversample` is currently gated behind steering**, which `neo4j_tree`
  deliberately disables — so the profile runs at a raw k=10 and loses documents
  that are near-top-ranked. Every rank in the report is therefore a *lower bound*.
- **The ancestor pass is already partially fixing this.** T5-002 and T5-003 got
  their anchor in at rank 11 **via `tree_ancestor`, not vector search** — for
  T5-003 the hub is absent from the top 500 yet still reached the agent, because
  its retrieved PDFs are tree children and the pass walked up. It only works when
  *something* on the branch is retrieved (T5-001/T5-004: 0 branch nodes).

## ⚠️ Step 1b — re-scope before building anything (NEW, 2026-07-20)

A live `tree_agent` run of T5-001 showed the step-1 probe measured the **wrong
path**: the agent never searches on the raw question. It reformulated into five
targeted queries, the first (`Comirnaty COVID-19 vaccine authorisation`) putting
the anchor at **vector rank 1**; the anchor also arrived via `link_expansion` and
`tree_ancestor` later in the run, and the answer scored 5.000/5.000 with the hub
cited. **The agent's reformulation loop already fixes the failure step 1
diagnosed** ([correction §6](../eval/2026-07-20_tree_seeding.md#6--correction-same-day-after-a-live-agent-run--this-report-measures-the-wrong-path)).

Before any of step 2 is built, measure what is actually broken:

1. **Agent path, all five anchors** — does reformulation rescue every anchor, or
   only Comirnaty? Extract per-step queries and anchor presence from the chain
   bundles (`scripts/render_trace.py --run-id`, then read `chain[].args.query`).
2. **`naive_rag` path, all five anchors** — the recipe that passes the user's
   question straight through is where the raw-question weakness would actually
   hurt. Untested so far.
3. **Keep the ANN item regardless** — T5-005's anchor at true rank 5 yet
   invisible at k≤100 is an index property, independent of phrasing.

Only the gaps that survive (1) and (2) justify building (2.2)–(2.4) below.

## Step 2 — hub-aware seeding (re-ordered by the step-1 evidence)

Cheapest first; implement one, re-measure with the step-1 probe, stop when the
success criteria are met:

1. **Restore oversampling unconditionally** *(new, from step 1)* — the
   `oversample` multiplier currently applies only when a category filter or quota
   is active. Ungate it (or set a floor) so the vector pass draws a larger pool
   and truncates. One config/logic change, no new signal; fixes T5-005 outright
   and brings the scoring cases within reach. **Re-run the ANN sweep after this
   — it re-baselines every other number.**
2. **Title / short-document boost** (was 2.1) — a deterministic postprocessor
   lifting documents whose *title* matches query terms, countering the measured
   length bias against navigational hubs. Targets the scoring and recall cases
   that oversampling cannot reach. Config-driven weight, off by default.
3. **Depth-aware scoring** (was 2.2) — `tree_depth` to prefer the shallower
   document among branch siblings. Note it only re-orders what is already in the
   pool, so it cannot fix the recall cases alone; combine with 2.
4. **Anchor-then-expand** (was 2.3) — a first pass over hub-like documents
   (fan-out / depth, computed generically), then expansion from those seeds. The
   only candidate that structurally addresses "not in the pool at all". Last, and
   still bigger than the others.

Ablate on the T5 set; report **per-anchor rank**, not just judge scores.

## Step 3 — the `tree_context` tool (deferred, revisit after step 2)

An agent-facing tool to jump to a hub by name and enumerate one level
(`tree_context(path_or_name, page)`), reusing the `topic_context` paging idiom
but over `tree_path` instead of curated hub membership — i.e. it needs **no
curation**, unlike [`../tools/topic_context.md`](../tools/topic_context.md).

Deferred deliberately: if step 2 fixes seeding, the agent never needs to ask.
Build it only if the T5 chains show the agent *knowing* which hub it wants and
being unable to get there.

## Step 4 — showcase as a regression fixture

Once T5 passes, freeze the expected traversal shape (anchor retrieved, ≥N
link-expanded documents from the anchor, ancestors present) as an assertion over
the chain bundle JSON — a cheap structural regression test that does not depend
on judge scores. Runs offline against a stored bundle.

## Open decisions

- **Is `medicine_page` special?** No — hub-likeness must be computed from graph
  structure (fan-out, depth), never a category literal in code. Step 2.3 must
  respect this or it violates the "no hardcoded categories" rule.
- **Ancestor budget** — `max_ancestors: 3` is a guess. The T5 chains show whether
  ancestor chunks are load-bearing or noise (hub pages can be navigational text);
  tune from evidence, or add a minimum-score floor.
- **Does the KB-map tree need the same fix?** No — the map is complete by
  construction; this is purely a retrieval-seeding concern.

## Success criteria

- The Comirnaty question retrieves the Comirnaty hub in the seed set **without**
  rephrasing, and its chain HTML shows expansion from that anchor.
- The same holds for ≥4 of the 5 T5 anchors.
- No regression on T1–T4 (`neo4j_hier` unchanged; any new knob defaults off).

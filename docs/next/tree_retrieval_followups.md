# Tree-aware retrieval — follow-ups

**Status:** 📋 planned. Prerequisite landed 2026-07-20 (tree-aware retrieval,
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

## Step 1 — measure the miss precisely (no new machinery)

Before changing retrieval, quantify it. For each of the 5 T5 anchors, run the
current `tree_agent` and record: does the anchor document appear in the seed set
at all, and at which rank?

```cypher
// anchor rank probe — per showcase item, is the hub in the top-k?
```

Deliverable: a small table in `docs/eval/<date>_tree_seeding.md` (anchor,
in-seed? rank, origins mix). If the anchor is retrieved but ranked low, this is a
*scoring* problem; if it is absent from the pool entirely, it is a *recall*
problem. **The fix depends on which.** No code changes in this step.

## Step 2 — hub-aware seeding (the likely fix)

Three candidates, cheapest first. Pick based on step 1, implement one, measure,
stop if it works:

1. **Title/short-document boost** — a deterministic postprocessor that lifts
   documents whose *title* matches query terms strongly, counteracting the
   length bias against navigational pages. Reuses the existing postprocessor
   registry; no schema change. Config-driven weight, off by default.
2. **Depth-aware scoring** — use `tree_depth` (already on every node) to prefer
   the shallower document when two candidates are on the same branch: a hub
   above its own PDFs. One config knob, no new query.
3. **Anchor-then-expand retrieval mode** — a first pass restricted to hub-like
   documents (high fan-out / low depth, computed generically, *not* by category),
   then expansion from those seeds. Bigger change; only if 1 and 2 fail.

Ablate on the T5 set with the existing runner; report per-anchor rank, not just
judge scores.

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

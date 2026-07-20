# T5 anchor-seeding measurement — 2026-07-20

*Work item: [`docs/next/tree_retrieval_followups.md`](../next/tree_retrieval_followups.md)
**step 1** ("measure the miss precisely — no new machinery"). Code as of commit
`f9bba89`, branch `develop`, profile `neo4j_tree` on the live marvin-gpu graph
(79,882 docs / 5.82M chunks / 99,520 `LINKS_TO`). Probe was read-only; no code
changed for this report.*

## 1. Question

The tree traversal landed and works, but the first live showcase run seeded on
CHMP meeting minutes instead of the Comirnaty hub page
([`../RETRIEVAL.md`](../RETRIEVAL.md) §7.2). The plan's step 1 asks the one
question that determines the fix:

> For each T5 anchor: does the anchor document appear in the retrieved seed set,
> and at which rank? Retrieved-but-low ⇒ a **scoring** problem. Absent from the
> pool ⇒ a **recall** problem. *The fix differs.*

## 2. Method

Two probes per showcase item, plus one sweep:

- **A — what the agent actually gets**: `retriever.retrieve(question)` under
  `neo4j_tree` (k=10 + expansion + ancestors). Record the anchor's rank in the
  final node list, how many returned nodes sit on the anchor's tree branch
  (`tree_path` equality), and the origin mix.
- **B — the candidate pool**: the same vector query with **k=500**, recording the
  first rank at which the anchor document (and separately, *any* document on its
  branch) appears.
- **C — ANN sweep**: probe B repeated at k = 10 / 40 / 100 / 200 / 500, to
  separate true ranking from approximate-nearest-neighbour recall loss.

## 3. Results

| Item | Anchor | In final? | Branch nodes in final | Anchor rank in pool | Verdict |
|---|---|---|---|---|---|
| T5-001 | comirnaty | ✗ | 0 / 18 | — (not in top 500) | **recall** |
| T5-002 | spikevax | ✓ rank 11 | 11 / 12 | 58 | **scoring** |
| T5-003 | keytruda | ✓ rank 11 | 10 / 13 | — (not in top 500) | **recall** |
| T5-004 | sartans referral | ✗ | 0 / 12 | 99–114 | **scoring** |
| T5-005 | humira | ✗ | 0 / 13 | 5 | **ANN recall** |

ANN sweep — first rank at which the anchor appears, by query k:

| Item | k=10 | k=40 | k=100 | k=200 | k=500 |
|---|---|---|---|---|---|
| T5-001 | – | – | – | – | – |
| T5-002 | – | – | 58 | 58 | 58 |
| T5-003 | – | – | – | – | – |
| T5-004 | – | – | 99 | 99 | 114 |
| T5-005 | – | – | – | **5** | 5 |

## 4. What this says

**The miss is not one problem. It is three, in different proportions than
assumed.**

**(a) One case is an ANN artifact, not a ranking failure (T5-005).** The Humira
hub is the *true* rank-5 chunk for its question, yet a k=10 (or k=100) query
never returns it — Neo4j's vector index is approximate, and the greedy search
explores too little of the HNSW graph at small k to find it. Only at k≥200 does
it surface, at rank 5. **A document can be near-top-ranked and still invisible at
production k.** This is the cheapest possible fix: oversample the vector query
and truncate afterwards. Note `neo4j_tree` currently oversamples *only* when a
category filter or quota is active — precisely the steering this profile
deliberately turns off, so it runs at the raw k=10.

**(b) Two cases are genuine ranking failures at realistic depth (T5-002 rank 58,
T5-004 rank ~99).** Oversampling to k≈120 would reach both, but that is a big
pool to reorder blindly — this is where a title/short-document or depth-aware
signal earns its place (plan step 2.1/2.2).

**(c) Two cases are true recall failures (T5-001, T5-003).** The Comirnaty and
Keytruda hub pages are *not in the top 500 chunks* for their own questions. No
amount of oversampling reaches them. The hypothesis in the plan holds and is now
measured: these pages are short and navigational — a page listing document titles
loses cosine similarity to a 40-page assessment report that discusses the
substance continuously.

**(d) The ancestor pass is already a partial fix — and it is doing real work.**
T5-002 and T5-003 both got their anchor into the final result **at rank 11, i.e.
via `tree_ancestor`, not via vector search**. T5-003 is the striking one: the
Keytruda hub is absent from the top 500 chunks, yet the agent still received it,
because the PDFs that *were* retrieved are its tree children and the ancestor
pass walked up to it. In both cases the branch is then densely covered (11/12 and
10/13 returned nodes sit on the anchor's branch).

So the traversal machinery partially compensates for bad seeding — exactly what
it was designed to do — but only when at least one *child* of the hub is
retrieved. Where nothing on the branch is retrieved (T5-001, T5-004: 0 branch
nodes), there is nothing to walk up from.

## 5. Consequences for step 2

The plan's cheapest-first order survives, with a new step in front of it and one
candidate demoted:

1. **NEW — restore oversampling unconditionally** (`oversample` currently gated
   behind steering). One config change, no new logic; fixes T5-005 outright and
   makes (b) reachable. Measure the sweep again afterwards: the ANN effect means
   *every* rank in this report is a lower bound on what a bigger pool would find.
2. **Title / short-document boost** (plan 2.1) — now targeted at (b) and (c),
   the cases oversampling cannot fix. The measured failure is length bias, which
   is what this signal addresses directly.
3. **Depth-aware scoring** (plan 2.2) — still plausible, but note it only
   re-orders what is already in the pool, so it cannot help (c) alone. Best
   combined with 2.
4. **Anchor-then-expand** (plan 2.3) — the only candidate that addresses (c)
   structurally. Keep it last, and keep hub-likeness graph-derived (fan-out,
   depth) rather than a category literal.

`tree_context` (plan step 3) remains deferred, but the evidence for it changed
shape: the agent would not need to *rank* the hub at all if it could ask for it
by name — that is the natural answer to (c) if 2–4 disappoint.

## 6. Honesty notes / limits

- **n = 5.** Five anchors, one phrasing each, one profile. Directional, not
  statistically meaningful; the ANN finding is mechanistic and reproducible, the
  proportions are not.
- **Anchor-only measurement.** "Answer quality" is not measured here at all —
  only whether the hub document reaches the agent. A run can answer a question
  well from the hub's children without the hub itself.
- **Branch equality is strict.** Branch counting uses exact `tree_path` equality,
  so a document one level below the anchor counts as on-branch (it inherits the
  linker's path) but a sibling section does not.
- **k=500 is not ground truth.** Because of the ANN effect in (a), "not in the
  top 500" means "not found by a k=500 approximate search", not "not in the true
  top 500". An exact-scan probe would be needed to state true ranks.
- Probe script: `scratchpad/probe_seeding.py` (not committed — it is a one-off
  measurement, reproducible from this report's method section).

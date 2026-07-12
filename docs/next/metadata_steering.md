# Plan: steer retrieval on the authoritative node metadata (`doc_type` / `audience` / `site_topic`)

*Status: 💡 designed (2026-07-12) — **build gated on a trigger condition in §5**, per the
"complexity must be justified by a benchmark failure" rule. The metadata already exists on
the graph; only the *use* of it is deferred.*

## 1. Why

The graph now carries three authoritative, EMA-published labels on every `:Document`
(landed 2026-07-12; see [`../RETRIEVAL.md`](../RETRIEVAL.md) §7):

| Property | Source | Coverage | What it is |
|---|---|---|---|
| `doc_type` | website-data JSON export | **96.6% of PDFs** | EMA's own document type — 85 values (`assessment-report`, `product-information`, `scientific-guideline`, …) |
| `audience` | `ema-bg-category` page badge | **93% of HTML** | `Human` / `Veterinary` / `Corporate` / `Herbal` |
| `site_topic` | `ema-bg-topic` page badge | **27% of HTML** | EMA's curated subject taxonomy (`Pharmacovigilance`, `Clinical trials`, …) — **not derivable from the URL** |

They were stamped deliberately as **additive metadata only** — inspectable
(`scripts/inspect_graph.py overview`), carried on retrieved nodes, but **not yet wired into
any steering decision**. Today's steering (`harness/retrieval/steering.py` +
`configs/index/*.yaml` + `configs/routing/*.yaml`) runs entirely on the coarse,
URL-derived `category` (13 values). These three labels are strictly better signal for the
same levers, and one (`site_topic`) opens a routing dimension `category` cannot express.

This plan is the "what I deliberately did not do" companion to that landing: it records the
concrete ways to *use* the metadata, so the work is visible and execution-ready — but held
until a benchmark failure actually calls for it.

## 2. What already exists to build on

- **The properties**, persisted + backfilled: `scripts/backfill_doc_{types,badges}.py`
  (re-runnable), stamped at ingest for new builds
  (`harness/indexing/{doc_types,badges}.py` → `ingest.py` → `property_graph._entity_for`).
- **The steering machinery** they would plug into, all category-based today:
  - `HierarchicalPGRetriever` category filter + `category_quota` (Cypher, Option A);
  - `LINKS_TO` expansion with `expand_categories` targeting (Option B);
  - the query→category routing table (`configs/routing/default.yaml`, Option C);
  - the `doc_type_priority` postprocessor (`harness/retrieval/postprocessors.py`).
- **`classify_source`** (`harness/retrieval/doc_categories.py`) — the URL-substring
  classifier the properties can now *replace* rather than approximate.

## 3. Design — four independent uses, cheapest first

Each is separable; ship only the one a failure motivates.

**(A) Ground `category` on `doc_type` instead of the URL.** Where `doc_type` is present
(96.6% of PDFs), derive `category` from a small `doc_type → category` map instead of URL
substrings — authoritative, and it collapses the ordered-rule fragility in
`classify_source`. Keep the URL rules as the fallback for the ~3% of PDFs + all HTML
without a `doc_type`. Pure function change + a re-run of the category backfill; the biggest
correctness win for the least surface area.

**(B) Replace the `veterinary` URL rule with the `audience` badge.** The human-only
benchmark needs vet content *filterable*; today that hangs on the substring `"veterinary"`
appearing in the URL. `audience == "Veterinary"` is EMA's own call and catches vet pages
whose slug omits the word. Same for isolating `Corporate` chrome (careers, procurement,
"how to find us") that currently muddies `other`/`news`. HTML-only (badges don't reach
PDFs) — combine with (A)'s `doc_type` for the PDF side.

**(C) Route on `site_topic`.** Option C currently maps hand-picked query keywords →
category priors. `site_topic` is EMA's own curated topic on the *documents*, so a query
classified as "Pharmacovigilance" (by keyword, or by a small classifier) can prefer/filter
documents whose `site_topic == "Pharmacovigilance"` — a topical axis orthogonal to
document-type that `category` cannot represent. Needs the new property exposed as a
retriever filter dimension (generalize the category filter in `HierarchicalPGRetriever` to
an arbitrary indexed property) + a routing mode that targets it.
*Caveat:* 27% HTML coverage, 0% on PDFs — weak as a hard filter; best as a soft `prefer`
signal, or paired with (D).

**(D) `doc_type_priority` at document-type granularity.** The postprocessor reorders by the
13-value `category`; with `doc_type` it can express finer preferences a category cannot —
e.g. prefer `product-information` over `assessment-report` within the `epar` category, or
down-rank `presentation` / `agenda` / `minutes` (weak evidence) explicitly. Extend the
postprocessor to read `doc_type` when its priority list contains doc-type values.

**Propagation note (enables C/D on PDFs).** Badges are HTML-only; most PDFs are reached
from exactly one parent HTML page via the `LINKS_TO` file-card edges (verified in the link
audit). `site_topic`/`audience` could be *propagated* to a PDF from its linking page — a
legitimate use of the link graph, but a separate build with its own accuracy check
(a PDF linked from several pages may inherit an ambiguous topic).

## 4. Implementation steps (per use, independently shippable)

1. **(A)** add `DOC_TYPE_TO_CATEGORY` map + `classify_source(..., doc_type=None)` override
   in `doc_categories.py`; thread `doc_type` through `_entity_for`; re-run the category
   backfill. Unit-test the map + fallback precedence.
2. **(B)** add a `veterinary`/`corporate` short-circuit keyed on `audience` ahead of the
   URL rules; unit-test that a vet page with no "veterinary" in the URL still classifies.
3. **(C)** generalize `HierarchicalPGRetriever`'s category filter to a named property
   (`filter_property`, default `category`); add a `site_topic` routing mode + a query→topic
   map (or reuse the keyword table). Offline tests on fixtures.
4. **(D)** extend `build_doc_type_priority` to accept doc-type values and read
   `node.doc_type`; validate against the doc_type vocabulary; offline test the reorder.
5. Runtime (GPU): a recipe enabling the chosen lever, one eval run, confirm the target
   failure moves and nothing else regresses (per-type metrics).

## 5. Build triggers, open decisions & risks

**Build when one of these is actually observed** (not before):

- eval shows a question type dominated by the wrong document type despite category steering
  (e.g. a definitional T1 answered from an `agenda`/`presentation`, or a general-requirement
  T2 answered from an EPAR) — motivates (D), and (A) for cleaner categories;
- vet or corporate documents leak into human-regulatory answers — motivates (B);
- a topical query (e.g. pharmacovigilance-scoped) retrieves the right *type* but the wrong
  *subject*, and no keyword rule captures it — motivates (C);
- the URL-substring `category` is observed to be *wrong* (not just coarse) on eval-relevant
  docs — motivates (A) as a correctness fix.

Open decisions & risks:

- **Coverage asymmetry** — `doc_type` is PDF-only, badges are HTML-only. Any lever using
  one must define behavior on the uncovered side (fall back to `category`, never exclude a
  node merely for lacking the property). (A)+(B) together cover both sides; (C) stays soft.
- **`site_topic` sparsity** (27% HTML / 0% PDF) — do not use as a hard filter without the
  propagation build; a hard filter would silently drop the majority of the corpus.
- **Two labels can disagree** — `doc_type` (JSON) and the `LINKS_TO` edge `document_type`
  (DOM) may differ; prefer the JSON `doc_type` (authoritative, higher coverage) and treat
  the edge value as a fallback.
- **Snapshot drift** — the JSON export and the badges reflect the site at scrape/download
  time; a re-ingest must re-run both backfills. The properties are stamped, so a stale
  value is silent — note the export/scrape date when it matters.
- **Do not over-fit the vocabulary** — 85 `doc_type` values is a long tail; steer on the
  handful a real failure names, not the whole set.

## 6. Verification

Offline: unit tests per use (the `doc_type→category` map + fallback precedence; the
audience short-circuit; the generalized property filter; the doc-type-granular reorder) on
fixtures — no store, no LLM, matching the existing `test_doc_categories` /
`test_retrieval_steering` style. Runtime (GPU): step 5 — the motivating eval failure must
measurably improve on its question type with no regression elsewhere; the resolved recipe
stamped honestly on the MLflow trace shows which lever was active.

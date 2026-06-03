# Requirements — link-extraction upgrade (LINKS_TO data-quality prerequisite)

> Work unit `2026-06-04_24_link-extraction-upgrade`. Feeds `docs/RETRIEVAL_TRACKS.md` §P1.
> Prerequisite for **Track B** (`hierarchical_links`) and inherited by **Track C** (`property_graph_native`)
> via the shared `IngestedDoc` IR.

## Problem statement

`harness/indexing/links.py:extract_links()` parses every `<a href>` in the page and classifies each
target by **URL shape only** (`file` / `page` / `external`), discarding all DOM context. Because it runs
over the *whole* document, global header / footer / mega-menu chrome becomes `LINKS_TO` edges. Measured on
the live graph (see exploration §1): **74 chrome targets absorb 94.4 % (1,624,744 / 1,721,581) of all
edges**; the real content link graph is only ~96,837 edges. A retriever that walks this raw edge set
drowns in nav boilerplate, which is why Track B previously needed a degree-cap blocklist as a workaround.

A **proven, DOM-aware extractor already exists** in the sibling repo `../ema_scraper`
(`parsers/ema_parser.py`, `EmaPageParser`): it scopes to `main.main-content-wrapper`, skips
`bcl-inpage-navigation` / `breadcrumb` / `dropdown-menu` / `<nav>`, and is BCL-component-aware (`bcl-file`
cards carry `data-ema-document-type`, reference number, file format). It is the right source of truth — but
it must be **ported, not imported** (no cross-repo dependency), and its `Link` dataclass currently stores
only `text` + `href`, so DOM context must be **stamped at extraction time**.

## Functional requirements

- **FR1 — main-content scoping.** `extract_links(html, base_url)` parses anchors only within
  `soup.find("main", class_="main-content-wrapper")`; outside-chrome anchors never become links.
  When `main` is absent, behavior is per Decision D4 (default: empty + counted, not whole-doc fallback).
- **FR2 — skip non-content regions.** Within `main`, skip `SKIP_TAGS` (`script/style/noscript/svg/button/
  form/input`), `SKIP_CLASSES` (`bcl-inpage-navigation`, `breadcrumb`, `dropdown-menu`), and `<nav>`
  elements — matching `EmaPageParser._should_skip`.
- **FR3 — component-aware extraction + context stamping.** Each extracted link carries the DOM context it
  was found in: `link_context ∈ {file_component, inline, card_or_listing, other}`. `bcl-file` →
  `file_component` and stamps `document_type` (`data-ema-document-type`) when present; `bcl-listing` /
  `listing-item` / `bcl-content-banner` card titles → `card_or_listing`; paragraph / heading / list /
  table / description-list / alert / blockquote inline anchors → `inline`.
- **FR4 — preserve existing normalization + classification.** Keep, unchanged: `urljoin(base_url, href)`,
  fragment stripping, `http(s)`-only, self-reference drop, de-dup, `ema.europa.eu` allowed-domain →
  `kind ∈ {file, page, external}`, and the existing `anchor` text field. The port adds context **on top
  of** the current `ExtractedLink`, it does not replace its fields.
- **FR5 — extended edge model.** The `LINKS_TO` relationship carries the new context as **properties**
  (`kind`, `link_context`, `document_type`, `anchor`) on a single relationship label (Decision D3). Both
  edge-producers — `to_graph()` (in-memory IR) and `_links_pass()` (global MERGE) — stamp them.
- **FR6 — context filters in the profile.** ⚠ **AMENDED by the plan (DL4 / amendment A6):** rather than
  *reinterpret* `edge_types`, the profile gains **explicit** `GraphRetrievalConfig.link_contexts` (default
  `[file_component, card_or_listing, inline]`, validated against the known set) and `document_types`
  (default `[]` = all); `edge_types` is kept unchanged. Clearer than overloading one field, and existing
  `edge_types == ["links_to"]` tests stay green. Track B's expansion Cypher consumes the explicit fields.
  *(Original wording — "`edge_types` generalizes to a `link_context` predicate" — is superseded; see
  `implementation-plan.md` §2b A6.)*
- **FR7 — rebuild edges only.** Provide a `links_only` rebuild path that **deletes and re-MERGEs only
  `LINKS_TO` edges** (batched), touching no `:Chunk` / embedding / `HAS_CHUNK` / `PARENT_OF`. Re-runnable,
  idempotent, no GPU.
- **FR8 — re-measure + verify.** After the rebuild, re-run the degree-distribution + chrome-share queries
  and assert the chrome concentration is gone (target: edge count drops ~1.72M → ~0.1M; no single target
  exceeds ~5 % of source pages).

## Non-functional requirements

- **NFR1 — no cross-repo import.** `harness/` must not import from `../ema_scraper`; the logic is ported
  into `harness/indexing/links.py` (BCL component knowledge lives in this repo henceforth).
- **NFR2 — caller-compatible.** `extract_links()` keeps its signature and `list[ExtractedLink]` return; the
  three existing callers (`ingest.build_ingested_doc`, `property_graph._links_pass`,
  `scripts/backfill_parsed_documents_subset.select_subset`) keep working with no behavioral regression
  (notably `select_subset` filters on `link.kind == "file"` — `kind` is preserved).
- **NFR3 — CI-testable offline.** New extraction + edge-stamping is unit-tested with HTML fixtures
  (mirroring `tests/test_indexing_links.py`), no live Mongo/Neo4j; the rebuild + re-measure is a gated
  live-infra step like the existing build verifies.
- **NFR4 — parser robustness.** A malformed / chrome-only / `main`-less page must not raise; it yields an
  empty (or appropriately-scoped) link list and is counted in a diagnostic.

## Acceptance criteria

1. `extract_links()` on a fixture EMA page returns only main-content links, each with
   `kind`, `anchor`, `link_context`, and `document_type` (for `bcl-file`), with URL normalization
   identical to today.
2. A whole-page fixture whose chrome links to `/about-us/cookies` etc. yields **zero** edges to those
   chrome targets (they are outside `main` / in skipped regions).
3. `to_graph()` and `_links_pass()` both stamp `{kind, link_context, document_type, anchor}` on `LINKS_TO`;
   a unit test asserts the `Relation.properties` / MERGE `SET` carries them.
4. `graph.edge_types` (generalized) filters expansion by `link_context` in Track B's Cypher (string-level
   test); an unsupported context value raises with the implemented set listed.
5. The `links_only` rebuild deletes + re-MERGEs `LINKS_TO` **without** changing `:Chunk` /
   `HAS_CHUNK` / `PARENT_OF` counts (asserted before/after).
6. Post-rebuild re-measurement: total `LINKS_TO` ≈ 10⁵ (down from 1.72M); top-target in-degree ≤ ~5 % of
   source pages; the 74-target/94.4 % concentration is eliminated. Numbers recorded back into
   `docs/RETRIEVAL_TRACKS.md` §P1 and §0.4.
7. Track B's `is_nav_hub` degree-cap is demoted to a documented **secondary safety-net** (the primary
   hygiene is now structural, at extraction time).
8. `pytest tests/test_indexing_links.py` + the edge-stamping tests green; `ruff` + `mypy` clean.

## Risks / open questions

- **R1 — `main`-less pages (Decision D4).** 40/40 sampled pages had `main.main-content-wrapper`, but the
  full 22,743-page set may include error/legacy pages without it. Must quantify main-presence across all
  pages before committing to strict (empty) vs whole-doc fallback. *Lean: strict + diagnostic count.*
- **R2 — context dedup priority (Decision D5).** A target reachable in multiple contexts (e.g. a PDF both
  as a `bcl-file` card and inline) must dedup to one edge. *Lean: keep the richest context —
  `file_component` > `card_or_listing` > `inline` > `other` — so `document_type` is retained.*
- **R3 — edge-model choice (Decision D3).** Properties-on-single-label vs typed relationship labels — see
  exploration §3 for the trade-off and recommendation (properties).
- **R4 — re-extraction cost / batching.** Deleting 1.72M edges in one transaction will blow Neo4j heap;
  the rebuild must batch deletes (`CALL { ... } IN TRANSACTIONS` / apoc.periodic.iterate) and reuse the
  existing `ensure_document_id_index`.
- **R5 — parser fidelity.** The port must reproduce `EmaPageParser`'s skip/component logic faithfully;
  divergence silently changes the edge set. Mitigation: fixture tests derived from the parser's own
  docstring examples + a small live cross-check (port vs. scraper on N real pages).

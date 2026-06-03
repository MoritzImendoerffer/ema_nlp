# Exploration — link-extraction upgrade

Investigation backing `docs/RETRIEVAL_TRACKS.md` §P1. All numbers are live-measured on this host
(2026-06-04), not estimated.

## 1. Quantify first (the chrome is 94.4 % of edges)

Live `LINKS_TO` graph (`ema_neo4j`, the full 79,882-doc build):

| Metric | Value |
|--------|-------|
| `LINKS_TO` edges | **1,721,581** |
| Distinct **source** pages (have ≥1 outgoing edge) | **21,957** |
| Distinct **target** docs | 61,114 |
| Targets linked from **> 5 % of source pages** (chrome) | **74** |
| Edges absorbed by those 74 chrome targets | **1,624,744 = 94.4 %** |
| Remaining **content** targets / edges | 61,040 / **96,837 (5.6 %)** |
| Edges → PDF targets | 57,993 (**3.4 %**) |
| In-degree distribution | min 0, p50 1, p90 2, p99 11, **max 21,956** |

The top in-degree targets are all global chrome at in-degree **21,956** (≈ every page): *Contacts, Fees
payable, Accessibility, Careers, About us, Cookies, Legal notice, Data protection, Search tips, FAQ…*.
These live in the site header/footer/mega-menu — **outside `<main class="main-content-wrapper">`**.

Source-of-edges = the **22,743** `web_items` rows that have `html_raw` (of 115,101 total; the rest are
PDF-metadata-only). At the **anchor** level (sample of 40 pages): `main.main-content-wrapper` is present on
**40/40** pages and contains only **36.7 %** of the page's `<a href>` (2,459 / 6,706) — the other ~63 % is
chrome. **21/40** pages carry ≥1 `bcl-file` component. So scoping to `main` removes the chrome at the
*source* and the 94.4 %/74-target concentration collapses — no degree-cap heuristic required.

## 2. The proven extractor — `../ema_scraper/parsers/ema_parser.py` (`EmaPageParser`)

Entry: `soup.find("main", class_="main-content-wrapper")` → `parse(main)` → `{"blocks":[…], "links":[…]}`.
Relevant mechanics to port (links only; we do **not** need the block/markdown machinery):

- **Scope:** only descends into `main`. No `main` ⇒ `parse_ema_page` returns `{"blocks":[],"links":[]}`.
- **`_should_skip`** (port verbatim): `SKIP_TAGS = {script,style,noscript,svg,button,form,input}`;
  `SKIP_CLASSES = {bcl-inpage-navigation, breadcrumb, dropdown-menu}`; `element.name == "nav"`; plus an
  `id()`-based processed-set to avoid re-extracting a subtree.
- **`COMPONENT_SELECTORS`** (most-specific first): `bcl-file → _parse_file`, `accordion`,
  `bcl-content-banner → _parse_banner`, `bcl-listing → _parse_listing`, `bcl-date-block`,
  `listing-item → _parse_card`, `alert`.
- **Where links are born + the context each implies:**
  - `_parse_file` (`.bcl-file`): reads `data-ema-document-type`, `file-title`, `reference-number`,
    `language-meta` (→ file_format/size), first/last-published `<time>`, and the **`<a href>` View link**
    → **`link_context = file_component`**, `document_type` set. *This is the high-value EMA→PDF "card".*
  - `_parse_card`/`_parse_listing`/`_parse_banner` (cards, listings, banners): link from card title /
    banner → **`card_or_listing`**.
  - `_parse_paragraph`/`_parse_heading`/`_parse_list`/`_parse_table`/`_parse_description_list`/
    `_parse_alert`/`_parse_blockquote`: `_extract_links()` over inline content → **`inline`**.
  - A standalone `<a>` directly under a container → `_extract_link` → currently uncontextualized → **`other`**.
- **The gap (confirmed in `data_classes.py`):** `@dataclass Link` has only `text, href`. The component
  method *knows* the context (it's literally inside `_parse_file` etc.) but never records it. **`FileBlock`
  does carry `document_type`, but the `Link` it appends does not.** So porting = re-running each
  component's link emission but **stamping `(link_context, document_type)` onto the link at that call
  site**. (The scraper's architecture allows this trivially; it just doesn't do it today.)
- The scraper's `_extract_link` does **no** URL normalization (stores raw href, only drops `#`/`javascript:`).
  Our port keeps the scraper's *DOM logic* but feeds every discovered `(href, link_context, document_type)`
  through **our existing** `urljoin`+fragment-strip+http-only+self-ref+dedup+`_classify` pipeline.

## 3. Edge model — properties on one label (recommended) vs typed labels

The new context (`kind`, `link_context`, `document_type`, `anchor`) has to live somewhere on the edge.

**Option A — single `LINKS_TO` label + properties** *(recommended).*
- `to_graph` emits `Relation(label="LINKS_TO", properties={kind, link_context, document_type, anchor})`
  (`Relation` supports `properties`); `_merge_links_batch` MERGEs the edge then `SET r += $props`.
- `graph.edge_types` **generalizes to a property-predicate filter**: keep the field name for back-compat
  but reinterpret its values as allowed `link_context`s, e.g. `edge_types: [file_component, inline]`
  (default `[file_component, card_or_listing, inline]` — everything but `other`). Track B's expansion
  Cypher: 1-hop `… -[r:LINKS_TO]-> (linked) WHERE r.link_context IN $contexts [AND r.document_type IN $doctypes]`;
  multi-hop uses `ALL(r IN relationships(p) WHERE r.link_context IN $contexts)`. A new optional
  `graph.document_types` predicate enables "follow only `guideline`/`assessment-report` cards".
- **Trade-off:** one label keeps the schema and the registry's edge-type concept simple, makes context a
  *weight/filter* (forward-compatible with edge weighting), and the cleaned graph (~10⁵ edges) makes the
  property predicate's cost negligible. Property filters on variable-length paths need the `ALL(...)`
  form — a minor Cypher nuance, and Track B defaults to 1 hop anyway.

**Option B — typed relationship labels** (`LINKS_TO_FILE`, `LINKS_TO_INLINE`, `LINKS_TO_CARD`).
- **Trade-off:** type-filtered traversal `-[:LINKS_TO_FILE*1..n]->` is marginally faster and reads cleanly,
  but it (i) explodes the label space and forces a label decision per edge at MERGE time, (ii) loses the
  natural place for `document_type` (still a property), (iii) complicates `graph.edge_types` (now it really
  is labels, but mixed file/inline traversal needs `-[:LINKS_TO_FILE|LINKS_TO_INLINE*1..n]->`), and (iv)
  makes "any link" queries awkward. Premature optimization at 10⁵ edges.

**Recommendation: Option A.** Single `LINKS_TO` + properties; `graph.edge_types` reinterpreted as a
`link_context` whitelist, with an optional `graph.document_types` predicate. Revisit B only if a benchmark
failure shows property filtering is too slow (it won't be at this scale).

## 4. Rebuild edges only (no chunk/vector touch)

`_links_pass` (`property_graph.py`) is already embedding-independent — it scans HTML rows, calls
`extract_links`, and MERGEs `:Document -[:LINKS_TO]-> :Document` for in-corpus targets. The rebuild:

1. **Delete only `LINKS_TO`, batched** (1.72M edges → don't do it in one tx):
   `MATCH ()-[r:LINKS_TO]->() CALL { WITH r DELETE r } IN TRANSACTIONS OF 50000 ROWS`
   (or `apoc.periodic.iterate`). `:Chunk` / `HAS_CHUNK` / `PARENT_OF` / embeddings untouched.
2. **Re-MERGE with the new extractor + properties** over the 22,743 `html_raw` pages (reusing
   `ensure_document_id_index` — already required by the MERGE; without it the match is a full `:Document`
   scan, the historical hang). Add the `SET r += {kind, link_context, document_type, anchor}` clause.
3. **Re-measure** (re-run §1 queries) and assert: total `LINKS_TO` ≈ 96,837; max target in-degree ≤ ~5 %
   of 21,957 pages; the 74-target/94.4 % concentration is gone. Record the new numbers in §P1 + §0.4.

CLI surface already exists: `build_property_graph_index(..., links_only=True)` (re-build just the links
over the existing graph). Add a `reset_links=True` (delete-first) flag, or a thin
`scripts/rebuild_links.py`. Cost: no GPU, ~minutes (the original full links pass was ~90 s after the index
fix, per HISTORY 2026-06-03).

## 5. Integration points (3 callers of `extract_links`) + caller impact

| Caller | Use | Impact of the upgrade |
|--------|-----|-----------------------|
| `harness/indexing/ingest.py:build_ingested_doc` | stamps `IngestedDoc.links` (the IR) | **Track C inherits the cleaned, typed links via the IR** (`to_native_graph`). No signature change. |
| `harness/indexing/property_graph.py:_links_pass` + `to_graph` | global `LINKS_TO` MERGE / IR→graph | both must stamp the new `Relation` properties; the MERGE Cypher gains a `SET`. **Track B's edge set.** |
| `scripts/backfill_parsed_documents_subset.py:select_subset` | picks HTML pages by resolvable PDF `link.kind == "file"` | **unaffected** — `kind` is preserved (FR4). Bonus: `bcl-file` links now also carry `link_context=file_component`, a stronger signal it can optionally use. |

## 6. Port plan — `harness/indexing/links.py`

Keep the public surface (`extract_links(html, base_url, *, allowed_domains=…) -> list[ExtractedLink]`).
Internally replace the flat `soup.find_all("a")` with a scoped, component-aware walk:

- Extend `ExtractedLink` (frozen dataclass) with `link_context: str = "other"` and
  `document_type: str | None = None`; **keep `tgt_url`, `anchor`, `kind`, `tgt_doc_id`** exactly as today.
- Add a small ported `_EmaLinkExtractor` (or functions): `_scope_to_main`, `_should_skip` (the SKIP_TAGS /
  SKIP_CLASSES / `nav` set), component dispatch for `bcl-file` (→ context+document_type) and
  card/listing/banner (→ `card_or_listing`), inline default (→ `inline`). Each discovered raw href +
  context flows through the **existing** `_strip_fragment`/`urljoin`/`_classify` + dedup.
- **Dedup priority** (Decision D5): on duplicate target, keep the richest context
  `file_component > card_or_listing > inline > other` (so `document_type` survives).
- **No `main` (Decision D4):** return `[]` and let the caller's diagnostic count it (default strict; a
  `fallback_whole_doc=False` flag documents the rejected whole-doc behavior). Quantify main-presence across
  all 22,743 pages in task T1 before finalizing.
- Parser: keep `BeautifulSoup(html, "lxml")` (current dep; faster than the scraper's `html.parser`).

`to_graph` (`property_graph.py`): emit `Relation(label="LINKS_TO", source_id, target_id,
properties=_clean({kind, link_context, document_type, anchor}))`. `_merge_links_batch`: extend the
`UNWIND … MERGE (a)-[e:LINKS_TO]->(b) SET e += p.props` shape and have `_links_pass` build `props` per pair.

## 7. How this updates the spec (`docs/RETRIEVAL_TRACKS.md`)

- **New §P1 prerequisite** (between P0 and Track A): the full link-extraction upgrade, with §1 numbers, the
  port plan, the edge model, and the rebuild-edges-only procedure. P1 runs **before** Track B.
- **§0.4** updated: the hygiene problem is now *solved structurally* (main-content scoping), pointing to P1;
  the 94.6 %/94.4 % figure is reframed as "what P1 removes."
- **Track B** updated: the retriever now assumes the **cleaned, typed** edge set. The `is_nav_hub`
  degree-cap blocklist is **demoted to a secondary safety-net** (not the primary filter). `graph.edge_types`
  generalizes to a `link_context` whitelist (+ optional `graph.document_types`); the expansion Cypher
  filters on edge properties, and can *prefer* `file_component` / specific `document_type`s for the
  HTML→PDF card signal — far more precise than the URL-shape `source_type` guard.
- **Track C** note: inherits the cleaned, typed links via the IR — no extra work; `to_native_graph`
  carries the same `Relation` properties.

## Key files

- `harness/indexing/links.py` — **the port target** (`ExtractedLink`, `extract_links`).
- `harness/indexing/property_graph.py` — `to_graph` (Relation props), `_links_pass` / `_merge_links_batch`
  (MERGE + SET + delete-first), `ensure_document_id_index` (reuse).
- `harness/indexing/ingest.py` — `build_ingested_doc` (IR links; no change beyond richer `ExtractedLink`).
- `harness/indexing/profiles.py` — `GraphRetrievalConfig` (`edge_types` reinterpretation + optional
  `document_types`).
- `scripts/backfill_parsed_documents_subset.py` — caller (`kind` preserved; unaffected).
- `tests/test_indexing_links.py` — fixture-based tests to extend (port fidelity, context stamping, chrome
  exclusion).
- Reference (read-only, **not** imported): `../ema_scraper/parsers/{ema_parser.py,data_classes.py}`.

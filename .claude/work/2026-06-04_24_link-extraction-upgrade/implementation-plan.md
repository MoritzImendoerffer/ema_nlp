# Implementation plan — link-extraction upgrade (P1)

Work unit `2026-06-04_24_link-extraction-upgrade`. Basis: `requirements.md` + `exploration.md` + the user
directives (2026-06-04): **agreed with all recommendations; no backwards compatibility required; embedding
runtime is a non-constraint.** Spec home: `docs/RETRIEVAL_TRACKS.md` §0.8 (P1). This prerequisite lands
**before Track B** and is inherited by **Track C** via the `IngestedDoc` IR.

## 1. Overview & scope

Replace whole-page, URL-shape link extraction with a **`main.main-content-wrapper`-scoped, BCL-component-
aware** extractor ported from `../ema_scraper/parsers/ema_parser.py`, stamp DOM context onto every
`LINKS_TO` edge, and **rebuild only the edges** (no chunk/embedding touch). This eliminates the **74 chrome
targets that absorb 94.4 %** of the 1.72 M edges (`exploration.md` §1) at the source, so Track B's retriever
walks a clean, typed graph instead of needing a degree-cap workaround.

**In scope:** `harness/indexing/links.py` (the port), `harness/indexing/property_graph.py` (edge properties
+ rebuild path), `harness/indexing/build.py` (CLI), `harness/indexing/profiles.py` (filter knobs), tests,
the live edge rebuild + re-measure, docs.
**Out of scope (Track B's work unit):** the retriever that *consumes* `link_contexts`/`document_types`
(`hierarchical_links`). P1 only produces the typed edges and the profile fields to filter them.

## 2. Locked design decisions

The user agreed with the exploration's recommendations and waived back-compat, so these are settled:

| # | Decision | Resolution (no back-compat exploited) |
|---|----------|----------------------------------------|
| **DL1** | Migration style | **Hard replacement.** Rewrite `extract_links` and reshape `ExtractedLink` in place; delete the old whole-page behavior entirely. No shims, no flags, no deprecation. |
| **DL2** | `main`-less page (D4) | **Strict: return `[]`** + a build-time diagnostic counter of skipped pages. **No whole-doc fallback** (it would reintroduce chrome). |
| **DL3** | Edge model (D3) | **Single `LINKS_TO` label + properties** `{kind, link_context, document_type, anchor}` (verified: `Relation.properties` round-trips). Not typed labels. |
| **DL4** | Profile filter knobs | **Add explicit `GraphRetrievalConfig.link_contexts`** (default `[file_component, card_or_listing, inline]`) **+ `document_types`** (default `[]` = all). **Keep `edge_types`** as-is. *(Refines the spec's "reinterpret edge_types" → explicit fields are clearer; existing `edge_types==["links_to"]` test stays green; consumer = Track B.)* |
| **DL5** | Dedup (D5) | On duplicate target, **keep the richest context** `file_component > card_or_listing > inline > other` (so `document_type` survives). |
| **DL6** | Rebuild mechanism | **Native `CALL { … } IN TRANSACTIONS OF 50000 ROWS`** delete (verified allowed through `structured_query`) + re-MERGE; **no apoc, no raw driver** (apoc 5.26.26 available as fallback). |
| **DL7** | Edge producers | **Both** `to_graph` (IR / full-rebuild / tests) **and** `_links_pass` (live global pass) stamp the properties — the live graph is built by `_links_pass`, so it is the load-bearing one. |

## 2b. Review-driven amendments (adversarial pass — folded in)

A plan review against the actual code surfaced gaps; these amend the tasks/decisions above:

- **A1 — Port the *recursive* walk, not a flat scan (load-bearing, TASK-001).** `EmaPageParser._parse_children`
  (ema_parser.py:148–223) **recurses into generic containers** (`div/section/article/aside/header/footer/
  span` + unknown tags) and into **`accordion` bodies** (`_parse_accordion`→`_parse_children`). A flat
  component-selector pass would **drop every link nested in `<div><div><p><a>` or inside accordions** (EMA
  uses accordions heavily for doc listings). TASK-001 must faithfully port the recursive descent **and** the
  `id()`-based **processed-set** (`_mark_processed`, lines 60/131–136/190–208/581) that prevents a
  `bcl-listing` and its child `listing-item` cards from being walked twice. Add **`accordion`** to the
  taxonomy (body links → `inline`).
- **A2 — `bcl-file` anchor = file-title (TASK-001/002).** `_parse_file` appends `Link(text=block.title or
  link_text, href)` (ema_parser.py:380–383) **before** the `return None` guard, so a `bcl-file` with a URL
  always emits a link whose anchor is the **file-title** (fallback to link text). The acceptance wording
  "anchor byte-identical to today" is **wrong** — reword to: *the per-URL normalize pipeline
  (`urljoin`/`_strip_fragment`/http-only/self-ref/`_classify`) is unchanged; anchor is context-derived
  (file-title for `bcl-file`, link text otherwise)*. TASK-002 fixtures assert the **new** anchor semantics.
- **A3 — Parser parity: use `html.parser`, not `lxml` (TASK-001).** `EmaPageParser` uses `html.parser`
  (ema_parser.py:887); `lxml` repairs malformed HTML differently (tag hoisting/`<table>` repair), which can
  move an `<a>` in/out of `main`. Since embedding runtime is a non-constraint and fidelity > speed, the port
  uses `BeautifulSoup(html, "html.parser")` for true parity with the proven extractor (also drops the lxml
  dependency for this path).
- **A4 — `_merge_links_batch` param-shape + `_clean` (BLOCK-1, TASK-003).** Stamping properties requires
  changing `_merge_links_batch(pairs: list[dict[str,str]])` → carry a nested per-pair `props` map
  (`list[dict[str, str | dict]]`), and applying `_clean(...)` (drop `None`, as `to_graph` does) to the
  `_links_pass` props so `document_type=None` never enters the Cypher param map. The `(src,tgt)` `seen`-set
  dedup (property_graph.py:354) stays — per-page DL5 dedup already guarantees one `ExtractedLink` per target
  per page, so the kept link's props are well-defined.
- **A5 — Main-presence diagnostic needs a real signal (BLOCK-2, TASK-001/005).** `extract_links` returns
  `[]` for both "no `<main>`" and "main but no content links", so `_links_pass` can't distinguish them.
  Mechanism: `links.py` logs at **WARNING** when `main is None` (and the body had anchors); `_links_pass`
  keeps a local `n_no_links` counter and logs the total. This makes R1/FR8's "count main-less pages"
  satisfiable.
- **A6 — DL4 supersedes requirements FR6 + needs membership validation (Q5, TASK-004/007).** The plan **adds
  explicit `link_contexts`/`document_types` and keeps `edge_types`**, which **supersedes** requirements.md
  **FR6** ("`edge_types` generalizes to a `link_context` filter") and its acceptance criterion 4. TASK-007
  records the supersession in the spec so **Track B inherits the explicit-fields design, not the
  reinterpreted-`edge_types` one**. TASK-004 must **validate `link_contexts` membership** against
  `{file_component, card_or_listing, inline, other}` and raise listing the valid set (criterion-4 intent);
  `document_types=[]` means "all".
- **A7 — DL6 was empirically verified.** `store.structured_query("MATCH (n:__NoSuchLabel__) CALL { WITH n
  DELETE n } IN TRANSACTIONS OF 1000 ROWS")` ran without the "not allowed in an (implicit/open) transaction"
  error → `Neo4jPropertyGraphStore.structured_query` (graph-stores-neo4j 0.7.0) executes in **autocommit**
  mode, so the batched delete is valid. `apoc.periodic.iterate` (apoc 5.26.26) remains the documented
  fallback; TASK-005 still spikes the delete against the live store once before wiring the helper.
- **A8 — Test-fixture interaction (TASK-002).** Keep **≥1 external link *inside* `main`** so
  `test_classification_file_page_external` still has an external target to assert; put **chrome** links
  *outside* `main` / in `breadcrumb`/`nav` for the exclusion test. `build.py` must thread
  `reset_links=args.reset_links` into the `build_index(...)` call (it flows via `**kw`).

## 3. Technical architecture

```
                         ┌─ harness/indexing/links.py ─────────────────────────────────┐
 web_items.html_raw ───▶ │  extract_links(html, base_url)                              │
                         │   1. soup.find("main", class_="main-content-wrapper")       │
                         │   2. _should_skip: SKIP_TAGS / SKIP_CLASSES / <nav>         │
                         │   3. component dispatch (ported from EmaPageParser):        │
                         │        bcl-file       -> link_context=file_component        │
                         │                          + document_type (data-ema-…)       │
                         │        bcl-listing /   -> card_or_listing                   │
                         │        listing-item /                                       │
                         │        bcl-content-banner                                   │
                         │        p/h/ul/ol/table/dl/alert/blockquote inline -> inline │
                         │        standalone <a>  -> other                             │
                         │   4. EXISTING normalize: urljoin, _strip_fragment,          │
                         │        http-only, self-ref drop, _classify(kind),           │
                         │        dedup (richest-context-wins, DL5)                    │
                         └───────────────────────┬─────────────────────────────────────┘
                                                 ▼  list[ExtractedLink{tgt_url, anchor,
                                                                       kind, link_context,
                                                                       document_type, tgt_doc_id}]
        ┌────────────────────────────────────────┼────────────────────────────────────────┐
        ▼ (IR path)                               ▼ (live global pass)                      ▼ (subset script)
 ingest.build_ingested_doc            property_graph._links_pass /            scripts/backfill_…select_subset
   -> IngestedDoc.links                 _merge_links_batch                       (filters kind=="file";
   -> to_graph(): Relation(             MERGE (a)-[e:LINKS_TO]->(b)              now main-scoped → cleaner,
   label="LINKS_TO",                    SET e += {kind,link_context,            no code change)
   properties={…})                      document_type,anchor}
   [Track C inherits]                   [Track B's edge set]
```

Rebuild path (DL6, edge-only): `build_property_graph_index(links_only=True, reset_links=True)` →
`MATCH ()-[r:LINKS_TO]->() CALL { WITH r DELETE r } IN TRANSACTIONS OF 50000 ROWS` → `ensure_document_id_index`
(reuse) → `_links_pass` over the 22,743 `html_raw` pages. `:Chunk` / `HAS_CHUNK` / `PARENT_OF` / embeddings
are never read or written.

## 4. Task execution plan

Seven tasks, 2–4 h each, single responsibility. Critical path **001 → 003 → 005 → 006 → 007**; 002 follows
001; 004 is independent (parallelizable). Code lands on `refactor/llamaindex-retrieval-pipeline`.

### TASK-001 — Port the scoped, component-aware extractor into `links.py`  *(foundation, ~4h)*
- Extend `ExtractedLink` (frozen): add `link_context: str = "other"`, `document_type: str | None = None`;
  keep `tgt_url`, `anchor`, `kind`, `tgt_doc_id`.
- Rewrite `extract_links`: scope to `main.main-content-wrapper` (DL2 strict-empty otherwise; **A5** logs
  WARNING when `main is None`); **port the recursive `_parse_children` walk (A1)** — descend into
  `div/section/article/aside/header/footer/span` + unknown tags + `accordion` bodies — with the `id()`-based
  **processed-set** (`_mark_processed`); port `_should_skip`
  (`SKIP_TAGS={script,style,noscript,svg,button,form,input}`,
  `SKIP_CLASSES={bcl-inpage-navigation,breadcrumb,dropdown-menu}`, `<nav>`). Component→context mapping:
  `bcl-file` → `file_component` + `document_type` (`data-ema-document-type`), **anchor = file-title or link
  text (A2)**; `bcl-listing`/`listing-item`/`bcl-content-banner` (with a `card-title`/`teaser-title`) →
  `card_or_listing`; `accordion`/paragraph/heading/list/table/dl/alert/blockquote inline → `inline`;
  standalone `<a>` → `other`. Every discovered `(href, link_context, document_type, anchor)` flows through
  the **existing** `urljoin`/`_strip_fragment`/http-only/self-ref/`_classify` + DL5 dedup. **Use
  `BeautifulSoup(html, "html.parser")` for parity with the scraper (A3).**
- **Acceptance:** `extract_links` returns only main-content links (incl. links nested deep in containers /
  accordions), each with `kind` + `link_context` (+ `document_type` for `bcl-file`); chrome anchors yield
  nothing; the **per-URL normalize pipeline is unchanged** while anchor is context-derived (A2); no
  cross-repo import.

### TASK-002 — Tests for the extractor (+ fix dependent fixtures)  *(testing, ~3h)*
- **Rewrite `tests/test_indexing_links.py`:** wrap existing anchors in `<main class="main-content-wrapper">`
  (current `_HTML` has none → would now return `[]`); add (a) chrome links **outside** main / in
  `breadcrumb`/`dropdown-menu`/`<nav>` → asserted absent; (b) a `bcl-file` card → `link_context ==
  "file_component"`, `document_type` set; (c) a `bcl-listing`/`listing-item` → `card_or_listing`;
  (d) an inline `<p><a>` → `inline`; (e) dedup richest-context-wins; (f) main-less page → `[]`; (g) a link
  nested deep in `<div><div><p><a>` and one inside an `accordion-body` are found (A1 recursion); (h) a
  `bcl-file` anchor equals the file-title (A2). Keep an external link **inside** `main` so the
  classification test still has an external target (**A8**); put chrome links **outside** `main`/in
  `breadcrumb`/`nav`. Keep the existing normalization/classification/dedup/`tgt_doc_id` assertions
  (anchor assertions updated to the context-derived semantics).
- **Fix `tests/test_indexing_ingest.py`:** wrap `_HTML_RAW` body in `<main class="main-content-wrapper">`
  so `test_html_doc_has_links_pdf_does_not` still sees the PDF link.
- **Acceptance:** `pytest tests/test_indexing_links.py tests/test_indexing_ingest.py` green offline; every
  `link_context` branch covered.

### TASK-003 — Stamp `LINKS_TO` edge properties end-to-end  *(feature, ~3h)*
- `to_graph`: `Relation(label="LINKS_TO", source_id, target_id, properties=_clean({kind, link_context,
  document_type, anchor}))`.
- `_links_pass`: build a `_clean`ed (drop `None`) `props` map per resolved pair from the `ExtractedLink`
  (**A4**); change `_merge_links_batch` param shape `list[dict[str,str]]` → `list[dict[str, str | dict]]`
  carrying `props`; Cypher `UNWIND $pairs AS p MATCH (a:Document {id:p.s}),(b:Document {id:p.t}) MERGE
  (a)-[e:LINKS_TO]->(b) SET e += p.props`. The `(src,tgt)` `seen`-set dedup stays (per-page DL5 already
  picks one link/target).
- Extend `tests/test_indexing_property_graph.py`: assert the `LINKS_TO` `Relation.properties` carries the 4
  keys (existing label/source/target assertions stay).
- **Acceptance:** both edge producers stamp `{kind,link_context,document_type,anchor}`; unit + Cypher-shape
  tests green.

### TASK-004 — Profile filter knobs (`link_contexts`, `document_types`)  *(feature, ~2h, parallelizable)*
- `GraphRetrievalConfig`: add `link_contexts: list[str] = [file_component, card_or_listing, inline]` and
  `document_types: list[str] = []` (empty = all); parse in `from_dict` (`_as_str_list`) and **validate
  `link_contexts` membership** against `{file_component, card_or_listing, inline, other}`, raising and
  listing the valid set on an unknown value (**A6**). Keep `edge_types`. **This supersedes requirements FR6 /
  the spec's "reinterpret `edge_types`"** — Track B consumes the explicit fields (recorded in TASK-007).
- Tests in `tests/test_indexing_profiles.py`: defaults + override parse; unknown `link_context` raises;
  `edge_types==["links_to"]` stays.
- **Acceptance:** new fields parse with documented defaults; unknown context rejected; existing profile
  tests unchanged.

### TASK-005 — Rebuild-edges-only path + CLI  *(integration, ~3h)*
- `build_property_graph_index`: add `reset_links: bool = False` → before `_links_pass`, run the batched
  `_delete_links(store)` = `MATCH ()-[r:LINKS_TO]->() CALL { WITH r DELETE r } IN TRANSACTIONS OF 50000 ROWS`
  (relationship-typed MATCH → never touches `:Chunk`/`HAS_CHUNK`/`PARENT_OF`; **A7** autocommit verified;
  apoc fallback). Diagnostic (**A5**): `_links_pass` counts pages returning zero links (`n_no_links`) and
  logs the total; the `main is None` WARNING is emitted in `links.py`.
- `harness/indexing/build.py`: add `--reset-links` (implies `--links-only`) and thread
  `reset_links=args.reset_links` into the `build_index(...)` call (**A8**, flows via `**kw`).
- Test (mongomock/`_FakeStore`): `reset_links=True` issues the `IN TRANSACTIONS` delete then the MERGE; a
  `_FakeStore` asserts the delete Cypher precedes the MERGE and no `:Chunk`/`HAS_CHUNK` query is emitted.
- **Acceptance:** `python -m harness.indexing.build --links-only --reset-links` deletes + re-MERGEs only
  `LINKS_TO`; offline test green.

### TASK-006 — Execute live rebuild, re-measure, verify  *(integration/validation, ~2h)*
- Snapshot `:Chunk`/`HAS_CHUNK`/`PARENT_OF`/`LINKS_TO` counts. Run the rebuild against `ema_neo4j`.
  Re-run the `exploration.md` §1 queries (degree distribution, chrome-share, in/out, target source_type).
- **Acceptance:** `:Chunk`/`HAS_CHUNK`/`PARENT_OF` counts **unchanged**; `LINKS_TO` ≈ 10⁵ (down from 1.72 M);
  **no target exceeds ~5 % of source pages**; the 74-target/94.4 % concentration is gone; edge properties
  present on a sample. Numbers recorded into `docs/RETRIEVAL_TRACKS.md` §0.8/§0.4 and this work unit.

### TASK-007 — Propagate to docs + decisions  *(documentation, ~2h)*
- `DECISIONS.md`: new entry (BCL component-aware, main-scoped extraction; single-label typed `LINKS_TO`;
  edge-only rebuild). `docs/RETRIEVAL.md`: document the new extractor + edge model in the code map.
  Finalize the post-rebuild numbers in the spec. `.claude/HISTORY.md` row.
- **Acceptance:** docs reflect the typed edge set as Track B's basis; `DECISIONS.md` entry present.

## 5. Quality assurance

- **Offline-first:** TASK-001/002/003/004/005 are fully unit-testable (BS4 fixtures + mongomock +
  `_FakeStore`/`_FakeEmbed`), no live infra — matching the `tests/test_indexing_*.py` convention.
- **Port fidelity:** fixtures derived from `EmaPageParser`'s own docstring examples (`bcl-file`,
  inline `<p><a>`, lists) plus one real `html_raw` slice cross-checked against the scraper's output.
- **Non-destructive guarantee:** TASK-005's test asserts the rebuild emits no chunk/vector query; TASK-006
  asserts chunk/edge-hierarchy counts are unchanged before/after the live run.
- **Gates:** `pytest tests/test_indexing_*.py`, `ruff check .`, `mypy .` green at each task.

## 6. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| **Existing fixtures break** (no `<main>` in `_HTML`/`_HTML_RAW`) | Owned explicitly by TASK-002 (rewrite both fixtures). |
| **`main`-less pages at scale** lose all links | TASK-005 diagnostic counts them; DL2 strict is intentional. If the count is material, revisit (but sample was 40/40 present). |
| **Port drift** from `EmaPageParser` silently changes edges | Fixture parity tests (TASK-002) + a one-off live cross-check port-vs-scraper on N pages before the rebuild. |
| **Subset script behavior shift** (`select_subset` now main-scoped) | Acceptable/better — it still finds `bcl-file` PDF cards; note in TASK-007. No code change. |
| **Big delete heap pressure** | `CALL {} IN TRANSACTIONS OF 50000` batches commits (verified path); apoc fallback if needed. |

## 7. Estimate

~19 h ≈ **5–6 evenings** (revises the spec's optimistic "~2–3 evenings" upward once test-fixture rewrites,
the live rebuild + re-measure, and docs are counted). Critical path 001→003→005→006→007 ≈ 14 h; 002 (+3 h)
and 004 (+2 h) parallelize.

## Next

`/next` to start **TASK-001** (or TASK-004 in parallel). After the live rebuild (TASK-006), Track B
(`hierarchical_links`, work-unit lineage `2026-06-03_22`) builds its retriever on the cleaned typed edges.

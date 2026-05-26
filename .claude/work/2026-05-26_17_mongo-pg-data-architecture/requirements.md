# Requirements — Mongo as parser sink, Postgres as canonical retrieval store

## Headline goal

Refactor the Mongo → Postgres data flow so two properties hold simultaneously:

1. **Parsing is decoupled and pluggable.** A new parser (e.g. a llamahub PDF reader, or a higher-quality HTML extractor) can be added without touching the chunking / embedding / retrieval code. Parsers write into MongoDB; nothing else parses raw bytes.
2. **The Mongo → Postgres sync is thin and dumb.** It reads already-parsed text + parser-provided metadata from Mongo, derives URL-only metadata, runs the chunker + embedder, and upserts into PG. No regex on parser-specific markdown shapes inside the sync layer.

The user's framing: *"parse only into mongodb and keep the update from mongodb to postgres simple."* That's the architecture; this work unit designs and ships it.

## Why now

`harness/embed_pg.py` works end-to-end today and is the runtime retrieval default (NARR-028). But swapping in a new PDF parser tomorrow requires:
- adding a parser (the easy part)
- writing the parsed output back to `parsed_pdfs` Mongo collection — currently a free-for-all shape (`{markdown, parsed_with, error}`); no clear contract
- understanding that `corpus/ingestion/pdf_normaliser.py` runs *regexes against the markdown header* to extract title / reference_number / committee / revision / last_updated — which means a different parser's markdown can silently break metadata extraction
- knowing whether to overwrite the existing row or coexist (no convention for that today)
- running `python -m harness.embed_pg --source pdfs --force` to re-ingest, with no fine-grained "only re-do the URLs the new parser touched" support

Same story for HTML: trafilatura is hardcoded into `corpus/ingestion/html_normaliser.py`. There is no `parsed_html` Mongo collection paralleling `parsed_pdfs`; HTML parsing happens inline during the sync. Swapping trafilatura for a llamahub reader (or anything else) requires editing the sync code path, not adding a parser.

So the existing pipeline conflates three concerns:
- **Parsing** (bytes → parsed text + parser-internal metadata)
- **Metadata enrichment** (URL → topic_path, markdown headers → reference_number / committee / revision / last_updated)
- **Chunk + embed + upsert** (parsed text → chunks → PG)

They should be three layers.

## Functional requirements

### FR-1 — Parser contract in MongoDB
A parser writes documents that conform to a stable schema:

```
{
  _id:            <url>          # source URL is the canonical key
  parser:         "pymupdf4llm" | "llamahub_pdf_reader" | "trafilatura" | …
  parser_version: <semver | model rev>,
  parsed_at:      ISO datetime,
  content_type:   "application/pdf" | "text/html" | …
  text:           <parsed text — markdown or plain text>,
  text_format:    "markdown" | "html" | "plain",
  error:          ""  (empty when parse succeeded)
  meta:           { … parser-specific structured output: e.g. page count, table cells, image refs, parser-internal metadata }
}
```

Multiple rows per `_id` are allowed — one per (parser, parser_version) tuple. The compound natural key is `(url, parser, parser_version)`.

This contract is enforced at write time by a thin helper in `corpus/sources/` so all parser implementations go through it.

### FR-2 — Parser plug points
A parser is a Python callable that takes (raw bytes | raw HTML, url, content_type) and returns the parser-contract dict. Parsers live under `corpus/parsers/` (new directory). Each parser is self-contained — its dependencies live in an optional pyproject extra so they're not forced on every install.

Two parsers ship in this work unit:
- `corpus/parsers/pymupdf4llm.py` — re-wraps the existing PDF parsing (currently in `scripts/ingest_parsed_pdfs.py`)
- `corpus/parsers/trafilatura.py` — re-wraps the existing trafilatura call (currently inside `corpus/ingestion/html_normaliser.py:normalise_html`)

A third parser is a smoke target to prove the plug point:
- `corpus/parsers/llamahub_pdf.py` (optional / behind extra) — uses one of the llamahub PDF readers; this is the proof of pluggability, not a production swap.

### FR-3 — Mongo collection layout
Two collections, named for purpose, not parser:

- `parsed_documents` — supersedes today's `parsed_pdfs` and `web_items`. One row per (url, parser, parser_version) per FR-1.
- (optional, see open question 1) keep `web_items` for raw HTML preservation as parser-input cache; or drop it once Scrapy writes raw HTML into `parsed_documents` alongside the trafilatura output.

The current `parsed_pdfs` and `web_items` collections are kept until migration completes — sync code falls back to reading them when `parsed_documents` is absent.

### FR-4 — URL-only metadata extractor
Move the metadata derivations that depend *only on the URL* out of the parser-coupled normalisers into a standalone module:

- `topic_path` — URL path segments, drop filename
- (potentially) `committee` and `reference_number` when they appear in the URL itself

These are computed once per URL, not per parser. Lives in `corpus/metadata/url_metadata.py` (new).

### FR-5 — Parsed-text metadata extractor
The text-derived metadata extractors (currently the regex bag at the top of `pdf_normaliser.py`) move to their own module and accept *any* markdown/text — they are NOT parser-specific:

- `title` (first H1 or fallback)
- `reference_number` (EMA_REF_RE against header window)
- `committee` (parsed from reference_number)
- `revision`
- `last_updated`

Lives in `corpus/metadata/text_metadata.py`. Designed to degrade gracefully when a parser produces a slightly different markdown shape (e.g. wrap regex matches in try/except, log "metadata missing" without failing the doc).

### FR-6 — Sync (`harness/embed_pg.py` refactor)
The sync becomes:

```
for parsed in mongo.parsed_documents.find(<filter>):
    url_meta  = url_metadata(parsed["_id"])
    text_meta = text_metadata(parsed["text"], parsed["text_format"])
    document  = build_document(url_meta, text_meta, parsed)
    chunks    = chunk_text(parsed["text"], parsed["text_format"])
    embed_and_upsert(document, chunks)
```

The sync no longer cares which parser produced the text. It also no longer contains trafilatura or pymupdf4llm imports.

The sync supports a `--parser-preference` flag that, when multiple (url, parser) rows exist for one url, picks one in priority order (default: pinned per-content-type table in config).

### FR-7 — PG schema additions for parser provenance
Add columns to `documents`:

- `parser TEXT` — which parser produced the text this row was synced from
- `parser_version TEXT` — version pin
- `parsed_at TIMESTAMPTZ` — when the parser ran
- `parsed_text_hash TEXT` — sha256 of `parsed.text`; lets sync skip rows where text hasn't changed since the last sync

These let `documents` tell you which parser's output is currently materialised, so a future re-sync can detect "this URL has a newer or different parser output in Mongo" without re-embedding.

### FR-8 — Re-sync semantics
A re-sync run, given a `--parser-preference` and an optional `--since <datetime>` filter:

- iterates `parsed_documents` matching the filter
- skips rows whose `parsed_text_hash` already equals the matching `documents.parsed_text_hash` (no-op)
- for rows where the hash differs OR the parser/parser_version has changed: deletes chunks + links for that `doc_id` (ON DELETE CASCADE) and re-chunks + re-embeds
- never deletes a `documents` row that no longer appears in Mongo — that's a separate `--prune` action, behind a flag, because it could be a Mongo-side bug

### FR-9 — Back-compat / legacy paths
- `harness.embed_pg` keeps an internal compat reader that wraps `parsed_pdfs` and `web_items` as a synthetic `parsed_documents` stream, so the system works against today's data without a one-time migration step.
- Migration utility `scripts/migrate_mongo_to_parsed_documents.py` writes the existing two collections into `parsed_documents` with `parser="pymupdf4llm"` / `parser="trafilatura"` and `parser_version="legacy"`. Optional; not on the critical path.

### FR-10 — Documentation
- `docs/RETRIEVAL_PG.md` gets a new "Adding a parser" section
- `docs/RETRIEVAL_PG.md` gets an updated "Re-sync after parser change" section
- `DECISIONS.md` gets one entry describing the three-layer separation (parse / metadata / sync) and the multi-row-per-URL parser contract

## Non-functional requirements

### NFR-1 — No re-embed required to ship
The cutover from the old normaliser path to the new layered path must not trigger a re-embed of the existing 1k+-chunk seed (and ultimately the ~540k-chunk full ingest, when it lands). The new sync, run against the same `pymupdf4llm` / `trafilatura` outputs, must produce identical `chunk_id`s for unchanged text.

### NFR-2 — Parser swap is incremental
Adding a new parser does not require re-ingesting URLs that the new parser doesn't cover. A llamahub parser run over 100 URLs lights up only those 100 URLs for re-sync, leaving the other 65k untouched.

### NFR-3 — Test isolation
The text-metadata extractor and URL-metadata extractor must be tested in pure Python — no Mongo, no PG, no GPU. The sync's "Mongo iterator" gets a fake-Mongo stand-in.

### NFR-4 — Parser dependencies are optional
Each parser's imports happen inside its module; the rest of the codebase imports parsers lazily. Adding llamahub does not force users who don't want it to install it.

### NFR-5 — Mongo size envelope
Storing multiple parser outputs per URL grows the Mongo footprint linearly per parser. The growth must be tracked and reported; no parser is added without measuring the storage impact on a sample (NARR-011-style timing note).

### NFR-6 — Idempotency
Running the sync twice in a row with no Mongo changes produces zero PG writes. (`parsed_text_hash` skip path makes this trivial.)

## Acceptance criteria

- [ ] `parsed_documents` Mongo collection exists; documents written by any parser conform to the FR-1 schema.
- [ ] At least two parsers (`pymupdf4llm`, `trafilatura`) write through the new contract; one demonstration parser (`llamahub_pdf` or equivalent) is added behind an optional dep and proven to flow through end-to-end on ≥5 URLs.
- [ ] `corpus/parsers/` is the directory that holds parsers; `corpus/metadata/url_metadata.py` and `corpus/metadata/text_metadata.py` exist and are pure-Python testable.
- [ ] `harness/embed_pg.py` no longer imports `trafilatura` or `pymupdf4llm`. Its job is iterate-mongo → metadata → chunk → embed → upsert. (The chunker may still call markdown parsers — those are LlamaIndex internals, not document parsers.)
- [ ] `documents` table has `parser`, `parser_version`, `parsed_at`, `parsed_text_hash` columns and they are populated on every sync.
- [ ] Re-running the sync with no Mongo changes is a no-op (no PG writes; observable via row count + `pg_stat_user_tables`).
- [ ] Switching `--parser-preference` from `pymupdf4llm` to `llamahub_pdf` for a slice of URLs re-syncs only those URLs and leaves the rest untouched.
- [ ] The full test suite is green; new tests cover URL-metadata extractor, text-metadata extractor, parser-contract enforcement, sync no-op path, sync re-sync path, and parser-preference selection.
- [ ] `docs/RETRIEVAL_PG.md` and `DECISIONS.md` updated as per FR-10.

## Risks

| Risk | Mitigation |
|------|------------|
| Multi-row-per-URL grows Mongo unboundedly as parsers proliferate | Cap with a documented eviction rule ("keep latest 3 parser versions per URL" by default); single source of truth for the cap |
| Hash-based skip turns out unreliable when a parser is non-deterministic (e.g. llamahub uses an LLM in the loop) | `parsed_text_hash` is computed on `parsed.text` only, not on `meta`; if a parser is non-deterministic, the hash will simply not match and we re-sync — degraded perf, not correctness |
| Moving regex-on-markdown out of the normaliser breaks edge cases that the current code silently handled | Bring the existing `tests/test_pdf_normaliser.py` + `tests/test_html_normaliser.py` corpus along, plus add golden tests on actual `parsed_pdfs` docs sampled from production Mongo |
| `topic_path` semantics differ between PDF and HTML today (drop-filename rule) — easy to break during the refactor | Pin behaviour with golden tests before moving the code |
| `corpus.jsonl` Q&A extractors (`corpus/extractors/`) also read `parsed_pdfs` / `web_items` directly | Out of scope; flag a future task to migrate those readers once `parsed_documents` is stable. The two paths can coexist during transition. |
| `scripts/ingest_parsed_pdfs.py` writes to `parsed_pdfs` today | Update it to write to `parsed_documents` with `parser="pymupdf4llm"` once the new collection is in place; leave the old write path for one transition period |
| Sync now needs to know which parser output to prefer per (url, content_type) | Encode in `harness/configs/parser_preference.yaml`; sensible defaults; a CLI flag overrides |

## Open questions (need answers before /plan can produce a concrete task list)

### OQ-1 — Mongo collection shape
- **Option A** (recommended): one collection `parsed_documents`, multiple rows per URL, compound natural key `(url, parser, parser_version)`. `_id` is auto-generated (or a composite hash); add a unique index on the triple.
- **Option B**: one collection per parser (`parsed_pdfs_pymupdf4llm`, `parsed_pdfs_llamahub`, `parsed_html_trafilatura`, …). Simpler to reason about; harder to query "best parser per URL."
- **Option C**: one collection per URL, with parser outputs nested under sub-fields (`{ _id: url, parsers: { pymupdf4llm_v2: {...}, llamahub_v0_1: {...} } }`). Hits Mongo's 16 MB doc cap quickly on long PDFs.

### OQ-2 — Should the HTML raw bytes also live in Mongo with a parser of their own?
Today `web_items` holds raw HTML and `parsed_documents` (proposed) would hold trafilatura-extracted markdown. Question: should raw HTML *also* be in `parsed_documents` (as `parser="raw"`, `text_format="html"`)? Or stay in a separate `raw_items` collection as parser input only?

### OQ-3 — Do we store the full parsed text in PG too, or fetch from Mongo on demand?
- **Store in PG**: adds a `parsed_text` column on `documents` (~5–50 KB per doc). Re-chunk without Mongo round-trip. Storage cost: ~1–2 GB extra at full ingest.
- **Mongo only**: PG has only chunks + per-doc metadata; re-chunk requires Mongo. Slightly slower re-chunk; no PG bloat.

### OQ-4 — Parser preference: per content_type, per URL pattern, or both?
- Per content_type (`application/pdf → pymupdf4llm`): simple, default.
- Per URL pattern (e.g. `*/scientific-guidelines/* → llamahub_v2`): more expressive; needed if different EMA sub-corpora benefit from different parsers.

### OQ-5 — What about the Q&A extractors in `corpus/extractors/`?
Those produce `corpus.jsonl` and currently read `parsed_pdfs`/`web_items` directly. Out of scope for this work unit, or in scope?

### OQ-6 — Migration timing
- Big-bang: write `parsed_documents`, update all readers, drop the old collections in one PR.
- Phased: stand up `parsed_documents` alongside, dual-read for a transition window, retire the old paths over 2–3 PRs.

Phased is safer; big-bang is one less PR to manage. Default: phased.

### OQ-7 — Does this work unit also handle ingest improvements like "parse on-demand when a URL appears but has no parser output yet"?
Today the only way to populate Mongo is to run `scripts/ingest_parsed_pdfs.py` against the Scrapy cache. Should the new architecture also let `harness.embed_pg --source url <url>` invoke a parser if no `parsed_documents` row exists?

Out of scope by default; mark as a v2 follow-up.

## Out of scope

- A new parser beyond the llamahub smoke (one is enough to prove the plug point)
- Migrating `corpus/extractors/` Q&A extractors to the new layer (separate work unit when needed)
- Any change to FAISS / `corpus.jsonl` paths
- Any change to retrieval (`harness/retrieve_pg.py`) or workflows
- Re-running the full-corpus ingest (the 6-hour 3090 run); that's a separate operational step

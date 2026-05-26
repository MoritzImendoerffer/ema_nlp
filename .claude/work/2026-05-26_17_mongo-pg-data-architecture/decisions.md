# Decisions — Mongo as parser sink, Postgres as canonical retrieval store

Resolves the seven open questions from `requirements.md` so `/plan` can produce a concrete task list without re-litigating them. Cross-refs `exploration.md`.

---

## OQ-1 — Mongo collection layout

**Decision: Option A — single `parsed_documents` collection, compound unique index `(url, parser, parser_version)`.**

Rationale:
- Simplest schema; single source of truth per (url, parser, parser_version).
- "Best parser per URL" is a one-line aggregate (`$sort` + `$group`); no cross-collection joins.
- Adding a new parser means writing rows, not provisioning a collection.
- Option B (per-parser collections) forces every reader to keep an enum of collection names in sync with the parser registry.
- Option C (nested-by-parser per URL) hits Mongo's 16 MB document cap on long PDFs (we already cap PDF markdown at 14 MB with one parser, so concatenating ≥2 wouldn't fit).
- Row count growth at full ingest: 200k URLs × ≤5 parsers = ≤1M rows. Mongo handles that trivially; we already have 65k rows in `parsed_pdfs` alone.

**Schema (FR-1 from requirements):**
```
{
  _id:            <auto BSON ObjectId>,
  url:            <source URL — natural key part 1>,
  parser:         <parser identifier — natural key part 2>,
  parser_version: <semver or model rev — natural key part 3>,
  parsed_at:      <ISO datetime>,
  content_type:   "application/pdf" | "text/html" | …,
  text:           <parsed text — markdown or plain text>,
  text_format:    "markdown" | "html" | "plain",
  error:          ""  (empty when parse succeeded),
  meta:           { … parser-specific structured output … }
}
```

**Index:** `db.parsed_documents.createIndex({url:1, parser:1, parser_version:1}, {unique:true})`.

---

## OQ-2 — Where does raw HTML live? Where do raw PDF bytes live?

**Decision: raw HTML stays in `web_items` (existing); raw PDF bytes stay in the Scrapy disk cache (existing). Neither is duplicated into `parsed_documents`.**

Rationale:
- Parsers transform raw → parsed. The raw layer is already covered:
  - HTML: `web_items.html_raw` (per `_id = url`)
  - PDF: `~/Nextcloud/Datasets/ema_scraper/cache/<sha>/parsed_pdf.pkl` (Scrapy)
- Duplicating raw bytes into `parsed_documents` doubles storage with no benefit — parsers already know how to read from their existing input locations.
- For PDFs, raw binaries can exceed Mongo's 16 MB doc cap; keeping them on disk avoids the headache.
- The HTML parser implementation reads `web_items` directly. A new HTML parser does the same.

**No new collection.** `parsed_documents` is parser *output* only.

---

## OQ-3 — Full parsed text in PG, or Mongo-only?

**Decision: store full parsed text in PG (new `documents.parsed_text TEXT` column).**

Rationale:
- The prompt is *"migrate everything from mongodb to postgres."* If PG can't re-chunk or surface "what was the parser output for URL X" without a Mongo round-trip, the migration isn't complete.
- Storage cost: ~1–2 GB at full ingest, against an existing ~14–18 GB DB estimate (NARR-011). Small relative impact.
- It's a plain `TEXT` column with no index — no performance hit. The chunker reads it once per re-chunk; nothing reads it on the hot retrieval path.
- The sync writes it once per parser swap. Not a hot path.
- Debugging becomes strictly easier: `SELECT parsed_text FROM documents WHERE doc_id=…` instead of jumping to Mongo.
- This is consistent with `documents.raw_byte_size INT` already living in PG — we've already partly committed to "parser output state lives in PG too."
- If it ever bloats unexpectedly, drop the column; backfilling from Mongo is one query. Reversible decision.

`parsed_text` is *the source* the chunker chunked; `chunks.text` are derived. They differ — `parsed_text` is the whole document; `chunks.text` are slices.

---

## OQ-4 — Parser preference rule shape

**Decision: per `content_type` only, v1. Per-URL-pattern preferences deferred until needed.**

Rationale:
- Today's needs are exactly two content types (PDF, HTML); each maps to exactly one default parser.
- A per-URL-pattern rule is more expressive but solves a problem we don't have yet.
- The config can be extended later without breaking the per-content-type shape (e.g. add a `url_patterns:` block alongside).

**Config (`harness/configs/parser_preference.yaml`):**
```yaml
default:
  "application/pdf":  [pymupdf4llm]
  "text/html":        [trafilatura]
# URL-pattern overrides can be added later under `url_patterns:`
```

**CLI flag:** `--parser-preference 'application/pdf=llamahub_pdf'` overrides the default for one invocation. Repeatable for multiple content types.

---

## OQ-5 — `corpus/extractors/` (Q&A path) in scope?

**Decision: out of scope. The Q&A extractors keep reading `parsed_pdfs` and `web_items` directly.**

Rationale:
- `corpus/extractors/` produces `corpus/corpus.jsonl`, a benchmark-only artifact. Cadence is "once per benchmark refresh," not "every retrieval run."
- They read the same two Mongo collections the sync does today; PR3's backfill into `parsed_documents` doesn't touch those collections (they remain alongside the new one).
- Migrating them is a separate work unit when there's a benchmark-side reason to (e.g. "we want the Q&A extractor to consume llamahub output").

**Follow-up tag:** record this in `metadata.json` as a future work unit lead.

---

## OQ-6 — Migration timing

**Decision: phased, three PRs.**

| PR | Scope | Production impact |
|----|-------|--------------------|
| **PR1** — Foundation | `corpus/parsers/`, `corpus/metadata/`, `parsed_documents` collection + writer + tests. No call sites touched. | None. Pure additions. |
| **PR2** — Sync refactor | ALTER `documents` (5 new columns including `parsed_text`); `harness/embed_pg.py` reads from `parsed_documents` via a synthetic reader that bridges the legacy collections so the existing seed keeps working without a backfill step. `--parser-preference` flag wired. | Default retrieval path is exercised; integration test against `ema_nlp_test` PG plus smoke against the live 446-chunk seed must show `chunk_id` stability (no re-embed). |
| **PR3** — Backfill, parser swap demo, docs | `scripts/migrate_mongo_to_parsed_documents.py` writes legacy rows; synthetic-reader fallback removed; llamahub demo parser; docs. | Backfill is idempotent; removing the synthetic reader is the irreversible step in this PR — gated on the backfill verifying. |

Rationale:
- The retrieval default is `pgvector` (NARR-028) — that's production. Big-bang on a production-default path is unjustified risk for what's saved (one merge, not even a review queue).
- Phased lets each PR be verified against the live seed before moving on.
- PR4 (drop `parsed_pdfs` and `web_items` outright) is **deferred indefinitely** — those collections are still read by `corpus/extractors/` per OQ-5. Their retirement is a future work unit, not part of this one.

---

## OQ-7 — Parse-on-demand in the sync CLI?

**Decision: out of scope. The sync CLI iterates Mongo only; parsing happens in parser CLIs.**

Rationale:
- Composes well via shell: `python -m corpus.parsers.pymupdf4llm --cache <path> && python -m harness.embed_pg`.
- Mixing parse + sync in one CLI conflates the layers we just separated.
- "Parse on demand if missing" is the kind of optimisation that earns its complexity only when there's a concrete user pain point. There isn't today.

---

## Cross-reference

| OQ | Decision | Source-of-truth file |
|----|----------|----------------------|
| 1  | Single `parsed_documents` collection | `corpus/sources/parsed_documents.py` (writer); Mongo index bootstrap in MIGR-001 |
| 2  | No raw layer change | (no file change; documented here only) |
| 3  | `parsed_text TEXT` column in PG | `corpus/pg_schema.sql` (MIGR-006) |
| 4  | Per-content-type preference | `harness/configs/parser_preference.yaml` (MIGR-009) |
| 5  | Out of scope | (Q&A extractors untouched; future WU placeholder in metadata) |
| 6  | Phased, 3 PRs | Task IDs map to PRs in `state.json` `phase_groups` |
| 7  | Out of scope | (no parse-on-demand CLI integration) |

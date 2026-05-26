# Implementation Plan — Mongo as parser sink, Postgres as canonical retrieval store

## Project overview

Refactor the Mongo → Postgres data flow so two properties hold simultaneously:

1. **Parsing is decoupled and pluggable.** A new parser (e.g. a llamahub PDF reader, a richer HTML extractor) plugs in without touching the chunker, the sync, the retriever, or any workflow code. Parsers write into MongoDB; nothing else parses raw bytes.
2. **The Mongo → Postgres sync is thin and dumb.** It reads already-parsed text + parser metadata from Mongo, derives URL- and text-metadata, runs the chunker + embedder, and upserts into PG. No parser-shape regexes inside the sync layer.

See `requirements.md` for the FR/NFR set, `exploration.md` for the architecture analysis (current data flow, parser-coupling map, three-layer proposal), and `decisions.md` for the seven resolved open questions. This plan turns the architecture into **17 ordered, testable tasks** averaging ~2 h each, grouped into three PR-sized phases.

## Scope

**In scope**
- New Mongo collection `parsed_documents` with compound unique key `(url, parser, parser_version)`.
- `corpus/parsers/` directory with two production parsers wrapping the existing code (pymupdf4llm, trafilatura) and one demo parser (llamahub_pdf, behind an optional pyproject extra).
- `corpus/metadata/` split: `url_metadata.py` (URL-only derivations) and `text_metadata.py` (markdown-header regexes).
- `harness/embed_pg.py` refactored to be parser-agnostic — no `trafilatura` or `pymupdf4llm` imports.
- `documents` table additions: `parser`, `parser_version`, `parsed_at`, `parsed_text`, `parsed_text_hash` columns + (`parser`, `parser_version`) index.
- `parser_preference.yaml` config + `--parser-preference` CLI flag (per content_type).
- Backfill script to write legacy `parsed_pdfs` / `web_items` rows into `parsed_documents`.
- Tests: unit (writer, url_metadata, text_metadata, parser protocol, hash-skip path), integration (against `ema_nlp_test` PG + Mongo fixture), smoke (`chunk_id` stability against live seed; parser-swap on 5 URLs).
- Docs: new sections in `docs/RETRIEVAL_PG.md`, new entry in `DECISIONS.md`.

**Out of scope** (per `decisions.md`)
- `corpus/extractors/` Q&A path remains reading `parsed_pdfs` / `web_items` directly.
- Parse-on-demand integration into the sync CLI.
- Retrieval changes (`harness/retrieve_pg.py`, `app.py`, `run_eval.py` untouched).
- FAISS / `corpus.jsonl` paths.
- Retiring the legacy `parsed_pdfs` / `web_items` collections — they coexist with `parsed_documents` indefinitely until the Q&A extractors are also migrated.
- Re-running the full-corpus ingest (separate operational step on the 3090).

## Technical architecture

### Three-layer separation

```
┌──── Layer 1 — Parsers (corpus/parsers/) ──────────────────────────┐
│ pymupdf4llm.py    trafilatura.py    llamahub_pdf.py (demo)        │
│ Each:  (raw_bytes | html, url, content_type) → ParsedDocument     │
│ Writes via corpus/sources/parsed_documents.py (the writer)        │
└───────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──── Layer 2 — Mongo `parsed_documents` ───────────────────────────┐
│ One row per (url, parser, parser_version). Compound unique index. │
│ Schema in decisions.md OQ-1.                                      │
│ web_items + parsed_pdfs coexist (raw inputs for parsers; Q&A      │
│ extractors still read them).                                      │
└───────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──── Layer 3 — Sync to PG (harness/embed_pg.py) ───────────────────┐
│ For each (url, parser, parser_version) selected by preference:    │
│   url_meta  = corpus.metadata.url_metadata(url)                   │
│   text_meta = corpus.metadata.text_metadata(text, text_format)    │
│   if sha256(text) == documents.parsed_text_hash: skip (no-op)     │
│   chunks    = chunk_text(text, text_format)                       │
│   vectors   = embed(chunks)                                       │
│   upsert(documents, chunks, links)                                │
└───────────────────────────────────────────────────────────────────┘
```

### Module layout

```
corpus/
  pg_schema.sql                  + parser, parser_version, parsed_at,
                                   parsed_text, parsed_text_hash columns
                                   on documents
  sources/
    parsed_documents.py          NEW: ParsedDocument dataclass +
                                   Mongo writer + index bootstrap
    synthetic_legacy_reader.py   NEW (PR2 transitional): bridges
                                   parsed_pdfs + web_items to a
                                   parsed_documents stream
    mongo_source.py              UNCHANGED (Q&A extractor path)
  metadata/
    url_metadata.py              NEW: topic_path + URL-only derivations
    text_metadata.py             NEW: title / reference / committee /
                                   revision / last_updated regexes
  parsers/
    __init__.py                  NEW: registry
    base.py                      NEW: Parser protocol + ParsedDocument
                                   dataclass
    pymupdf4llm.py               NEW: wraps the parsing currently in
                                   scripts/ingest_parsed_pdfs.py
    trafilatura.py               NEW: wraps the parsing currently in
                                   corpus/ingestion/html_normaliser.py
    llamahub_pdf.py              NEW (PR3): demo parser behind
                                   [parsers-llamahub] extra
  ingestion/
    chunker.py                   UNCHANGED
    link_extractor.py            UNCHANGED (called from sync)
    pdf_normaliser.py            DELETED at end of PR3 (logic moved)
    html_normaliser.py           DELETED at end of PR3 (logic moved)

harness/
  embed_pg.py                    REFACTORED: parser-agnostic sync
  configs/
    parser_preference.yaml       NEW (PR2): per-content_type defaults

scripts/
  init_db.py                     UNCHANGED (schema file's idempotency handles upgrade)
  ingest_parsed_pdfs.py          REFACTORED (PR1): writes via the new
                                   parser into parsed_documents while
                                   still keeping the old parsed_pdfs
                                   write path for transition
  migrate_mongo_to_parsed_documents.py
                                 NEW (PR3): one-shot backfill

tests/
  test_parsed_documents_writer.py     NEW (PR1)
  test_url_metadata.py                NEW (PR1)
  test_text_metadata.py               NEW (PR1)
  test_parsers_pymupdf4llm.py         NEW (PR1)
  test_parsers_trafilatura.py         NEW (PR1)
  test_embed_pg_sync.py               NEW (PR2)  (replaces no-such-file today)
  test_synthetic_legacy_reader.py     NEW (PR2)
  test_chunker.py                     UNCHANGED
  test_pdf_normaliser.py              DELETED at end of PR3 (covered by parsers/metadata tests)
  test_html_normaliser.py             DELETED at end of PR3
```

### `documents` table delta (PR2)

```sql
ALTER TABLE documents
    ADD COLUMN parser           TEXT,
    ADD COLUMN parser_version   TEXT,
    ADD COLUMN parsed_at        TIMESTAMPTZ,
    ADD COLUMN parsed_text      TEXT,
    ADD COLUMN parsed_text_hash TEXT;

CREATE INDEX IF NOT EXISTS documents_parser_idx ON documents (parser, parser_version);
```

`parsed_text_hash` is `sha256(parsed_text)` after trailing-whitespace trim. The sync's idempotency hinges on this: when the hash matches what's in PG, no re-embed.

### Mongo collection bootstrap (PR1)

```js
db.parsed_documents.createIndex(
  { url: 1, parser: 1, parser_version: 1 },
  { unique: true, name: "url_parser_version_uniq" }
);
db.parsed_documents.createIndex({ url: 1 });
db.parsed_documents.createIndex({ parser: 1, parser_version: 1 });
```

### Compatibility / transition path

The synthetic reader (`corpus/sources/synthetic_legacy_reader.py`, PR2) emits `ParsedDocument` instances from the existing `parsed_pdfs` and `web_items` rows so the refactored sync works against today's data **without a backfill**. The backfill (PR3) writes those legacy rows into `parsed_documents` proper; once that's done, the synthetic reader becomes dead code and is removed.

This means PR1+PR2 can land and run in production without any one-shot data migration step.

## Task execution plan

17 tasks across three PR-sized phases. Each task has acceptance criteria and an estimated time. Phase A is parallel-friendly after MIGR-001; Phase B is mostly sequential through the sync refactor; Phase C is mostly cleanup + demonstration.

### Phase A — Foundation (PR1, no production impact) — 5 tasks, ~13 h

| ID | Title | Depends on | Est |
|----|-------|-----------|-----|
| **MIGR-001** | `ParsedDocument` schema + Mongo writer + index bootstrap | — | 2.5 h |
| **MIGR-002** | `corpus/metadata/url_metadata.py` + golden tests | — | 2 h |
| **MIGR-003** | `corpus/metadata/text_metadata.py` + golden tests | — | 3 h |
| **MIGR-004** | Parser protocol + `corpus/parsers/pymupdf4llm.py` + CLI + tests | MIGR-001 | 3 h |
| **MIGR-005** | `corpus/parsers/trafilatura.py` + CLI + tests | MIGR-001 | 2.5 h |

### Phase B — Sync refactor (PR2, exercises the production retrieval path) — 6 tasks, ~14 h

| ID | Title | Depends on | Est |
|----|-------|-----------|-----|
| **MIGR-006** | ALTER `documents` table — 5 new columns + index; schema test | — | 1.5 h |
| **MIGR-007** | `harness/embed_pg.py` parser-agnostic refactor (sync over `parsed_documents`, hash-skip path) | MIGR-001, MIGR-002, MIGR-003, MIGR-006 | 4 h |
| **MIGR-008** | Synthetic legacy reader (bridges `parsed_pdfs` + `web_items` → `parsed_documents` stream) + tests | MIGR-001, MIGR-007 | 2.5 h |
| **MIGR-009** | `harness/configs/parser_preference.yaml` + `--parser-preference` CLI flag | MIGR-007 | 1.5 h |
| **MIGR-010** | Integration tests against `ema_nlp_test` PG + Mongo fixture (no-op skip, re-sync, preference selection) | MIGR-007, MIGR-008, MIGR-009 | 3 h |
| **MIGR-011** | Smoke verify against live 446-chunk PG seed — assert `chunk_id` stability (no re-embed); full suite green | MIGR-007, MIGR-008 | 1.5 h |

### Phase C — Backfill + parser swap demo + docs (PR3) — 6 tasks, ~9 h

| ID | Title | Depends on | Est |
|----|-------|-----------|-----|
| **MIGR-012** | `scripts/migrate_mongo_to_parsed_documents.py` — idempotent backfill | MIGR-011 | 2 h |
| **MIGR-013** | Run backfill; remove synthetic-reader fallback from sync; full suite green | MIGR-012 | 1 h |
| **MIGR-014** | `corpus/parsers/llamahub_pdf.py` behind `[parsers-llamahub]` extra; smoke on 5 URLs | MIGR-011 | 2 h |
| **MIGR-015** | E2E parser-swap smoke — `--parser-preference 'application/pdf=llamahub_pdf'` re-syncs only those 5 URLs; rest untouched | MIGR-013, MIGR-014 | 1.5 h |
| **MIGR-016** | `docs/RETRIEVAL_PG.md` — "Adding a parser" + "Re-sync after parser change" sections | MIGR-015 | 1 h |
| **MIGR-017** | `DECISIONS.md` — "Three-layer separation" + Mongo compound-key entry | MIGR-013 | 1 h |

**Total estimate:** ~36 h. Critical path: MIGR-001 → 006 → 007 → 008 → 010 → 011 → 012 → 013 → 015 → 016 → 017.

### Parallel opportunities

- After MIGR-001 lands: **002, 003, 004, 005** can be developed in any order (no inter-dependency).
- After MIGR-007 lands: **009 and 011** can run alongside **008/010**.
- **MIGR-014** is independent of MIGR-012/013 (different code paths) and can run as soon as MIGR-011 is green.

### What gates each PR boundary

| PR boundary | Gate |
|-------------|------|
| PR1 → PR2 | All Phase A tasks green; full unit-test suite still green; no production code path touched. |
| PR2 → PR3 | MIGR-011 smoke shows `chunk_id` stability (a re-embed during PR2 deployment would be a regression — by design the sync should no-op against the existing seed); `EMA_RETRIEVER=pgvector chainlit run app.py` continues to answer queries. |
| PR3 close-out | Backfill verified (`SELECT COUNT(*) FROM parsed_documents WHERE parser_version='legacy'` matches the union of `parsed_pdfs` + `web_items` row counts modulo skipped/error rows); llamahub parser-swap smoke shows only the targeted URLs re-synced; docs landed. |

## Quality assurance strategy

### Test layers

| Layer | Purpose | Files |
|-------|---------|-------|
| Pure unit | Metadata extractors, parser contract, hash-skip path | `test_url_metadata.py`, `test_text_metadata.py`, `test_parsed_documents_writer.py`, `test_parsers_*.py` |
| Integration (PG-only) | sync end-to-end against `ema_nlp_test` (skipped when `PG_DSN_TEST` unset; same pattern as NARR-026) | `test_embed_pg_sync.py` |
| Integration (Mongo-required) | Synthetic reader; backfill script | `test_synthetic_legacy_reader.py`, `test_migrate_backfill.py` (created during MIGR-012) |
| Smoke (live data) | Chunk-ID stability against the live 446-chunk seed; parser-swap re-sync | Ad-hoc scripts; results logged in `HISTORY.md` |

### Determinism / idempotency invariants

- **NFR-1 (no re-embed on cutover):** verified by MIGR-011 — running the refactored sync against the live seed must produce zero PG writes (skip-on-hash fires).
- **NFR-6 (sync re-run is a no-op):** verified in integration tests (MIGR-010) — two consecutive `sync()` calls against an unchanged Mongo state produce one set of writes, then zero.
- **NFR-2 (parser swap is incremental):** verified by MIGR-015 — only the URLs covered by the new parser preference re-sync; others' `parsed_text_hash` matches and they skip.

### Phoenix tracing

No span-attribute changes in this work unit. The sync isn't traced via Phoenix today (it's an offline ETL); if we ever wanted that, the existing `ema.*` namespace would extend cleanly.

### Suite green threshold

The full test suite is currently 253 green (last reported in NARR-028). The refactor must maintain that — each task's acceptance criteria includes "full suite green." Coverage on the moved-around code (`url_metadata`, `text_metadata`) should match the existing `pdf_normaliser` + `html_normaliser` coverage (~91% per NARR-025).

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Refactored metadata extraction misses an edge case the old code silently handled | Carry the existing `tests/test_pdf_normaliser.py` + `tests/test_html_normaliser.py` fixtures into the new test files; add golden tests on actual `parsed_pdfs` docs sampled from production Mongo. |
| `chunk_id` instability during PR2 cutover triggers a re-embed of the seed | MIGR-011 is a hard gate before PR3. If it fires, the refactor has a determinism bug; do not proceed. |
| Synthetic reader has subtle differences vs real `parsed_documents` rows | Integration tests (MIGR-010) run the same assertions against both code paths. |
| Backfill script writes duplicate rows on a second invocation | Idempotency via the compound unique index — bulk upserts use `upsert=True` keyed on `(url, parser, parser_version)`. |
| llamahub dependency conflicts with existing pyproject pins | Behind a `[parsers-llamahub]` extra; only installed when explicitly requested. |
| Q&A extractors break when their data shape shifts (the old collections shouldn't shift, but worth flagging) | The old collections are untouched. Q&A extractor tests stay green throughout. |

## Re-entry checklist (for any agent picking this up mid-flight)

```bash
# 1. Verify PG container up + ema_nlp DB present
cd ~/github_repos/ema_nlp/deploy/postgres && docker compose ps

# 2. Verify Mongo up
mongosh --eval "db.adminCommand({listDatabases:1})"

# 3. Check state
cat .claude/work/ACTIVE_WORK
cat .claude/work/2026-05-26_17_mongo-pg-data-architecture/state.json | jq '.current_task'

# 4. Continue from current task
# /workflow:next
```

## Follow-ups (out of scope here)

- Migrate `corpus/extractors/` Q&A path to read from `parsed_documents`. Trigger: benchmark refresh wants the Q&A extractor to consume a different parser's output.
- Retire `parsed_pdfs` and `web_items` collections. Trigger: above migration lands.
- Parse-on-demand integration in the sync CLI. Trigger: an operator workflow that genuinely benefits.
- Per-URL-pattern parser preference. Trigger: a sub-corpus benefits from a different parser (e.g. "all `/scientific-guidelines/*` use the llamahub reader").

# Exploration — Mongo as parser sink, Postgres as canonical retrieval store

## 1. What "everything from MongoDB to Postgres" actually means

Re-reading the prompt carefully:

> "Derive a strategy to migrate everything from mongodb to postgres (parsed pdfs and web items). An important part, it should be possible to parse items with a better parser in the future e.g. from llamahub. However, I think it would be a good separation to parse only into mongodb and to keep the update from mongodb to postgres simple."

Two reads of "migrate everything":

- **Strict read** — Drop MongoDB entirely; PG holds raw HTML + parsed text + chunks + embeddings + links + everything. But the same prompt immediately constrains this: *"parse only into mongodb."* So Mongo cannot disappear.
- **Practical read** — PG holds everything that downstream consumers (retrieval, evals, agents, future apps) need. Mongo retreats to a single role: the place where parser output lands. The sync becomes a thin, dumb ETL.

The practical read is what this work unit implements. The decision is recorded under OQ-3 (whether the *full parsed text* lives in PG or only in Mongo); the rest of the architecture is the same either way.

## 2. Current data flow (precise picture)

```
Scrapy (ema_scraper repo)
  ├──→ ~/Nextcloud/Datasets/ema_scraper/cache/  (parsed_pdf.pkl + meta files)
  ├──→ Mongo ema_scraper.web_items      {_id, url:[str], content_type:[str], html_raw:[str]}
  └──→ Mongo ema_scraper.parsed_pdfs    (populated by scripts/ingest_parsed_pdfs.py;
                                         {_id=url, markdown, parsed_with, error,
                                          cache_path, ingested_at})
                  │
                  ▼
  corpus/ingestion/pdf_normaliser.py    (regex on markdown header for metadata;
                                         pymupdf4llm-shape-coupled)
  corpus/ingestion/html_normaliser.py   (trafilatura inline; chunker-coupled)
                  │
                  ▼
  harness/embed_pg.py:ingest_source     (orchestrates: normalise → chunk → embed → upsert)
                  │
                  ▼
  Postgres ema_nlp:
    - documents (doc_id PK, source_url, source_type, title, topic_path,
                 reference_number, committee, revision, last_updated,
                 raw_byte_size, ingested_at, meta JSONB)
    - chunks    (chunk_id PK, doc_id FK, chunk_index, text, heading_path,
                 token_count, embedding vector(1024), text_tsv generated)
    - links     (src_doc_id FK, tgt_url, tgt_doc_id FK?, link_type, anchor, chunk_id FK)
```

### Where the coupling lives

Three boundaries collapse into one place today:

| Concern | Current location | Coupling |
|---------|------------------|----------|
| Parse PDF bytes → markdown | `parsers.pdf_parser.PdfDocument` (in `ema_scraper` repo, pickled into the Scrapy cache); copied to Mongo by `scripts/ingest_parsed_pdfs.py` | pymupdf4llm |
| Parse HTML → markdown | `corpus/ingestion/html_normaliser.py:normalise_html` (trafilatura.extract call) | trafilatura |
| URL → topic_path | `pdf_normaliser._extract_topic_path` and `html_normaliser._topic_path` (two near-identical copies) | none — pure URL parsing |
| Markdown header → title / reference_number / committee / revision / last_updated | `pdf_normaliser.normalise_pdf_doc` (regexes on `markdown[:2048]`) | implicitly assumes pymupdf4llm's H1 + date conventions |
| markdown → chunks | `corpus/ingestion/chunker.py:chunk_markdown` (LlamaIndex SentenceSplitter / MarkdownNodeParser) | LlamaIndex, not parser-coupled |
| chunks → embeddings → PG rows | `harness/embed_pg.py:ingest_source` | none — same for any parser |

The bold observation: **only the first two rows are actually parser-coupled.** Everything else can be — and should be — parser-agnostic, but today the third and fourth rows live inside the parser-coupled files.

### What's in Mongo that isn't in PG (and whether that matters)

| Field | Mongo? | PG? | Notes |
|-------|--------|-----|-------|
| Raw HTML | `web_items.html_raw` | no | Needed if we want to *re-parse* HTML with a new parser without re-scraping. Today: yes (we'd swap trafilatura, run sync). Future: still yes if Scrapy is the source of truth. |
| pymupdf4llm markdown | `parsed_pdfs.markdown` | no (only post-chunk slices) | Same story — needed for re-chunk without re-parse. |
| Parser identity | `parsed_pdfs.parsed_with` | partially (`documents.meta.parsed_with`) | Not currently usable for "which parser produced this PG row?" because `meta` is a free-form JSONB. |
| Parse error | `parsed_pdfs.error` | no | Failed parses are dropped during sync; PG never knows the URL exists. Fine. |
| Cache path | `parsed_pdfs.cache_path` | no | Machine-local; correctly Mongo-only. |
| Per-doc embedding model used | nowhere | `documents.meta` indirectly | All chunks use BGE-large-en-v1.5; not currently versioned in PG. Out of scope here. |
| Per-chunk embedding | n/a | `chunks.embedding` | PG-only by design. |
| Link graph | nowhere | `links` | PG-only by design; cheap to rebuild. |

So `web_items.html_raw` and `parsed_pdfs.markdown` are the genuine cases of "data only in Mongo." Both are *parser input or parser output* — exactly the thing this work unit wants to keep in Mongo.

## 3. Proposed architecture

Three layers, three modules per layer:

```
┌────────────────────────────────────────────────────────────────────┐
│  Layer 1 — Parsers                                                 │
│  corpus/parsers/                                                   │
│    pymupdf4llm.py     trafilatura.py     llamahub_pdf.py (smoke)   │
│  Each parser: (bytes | html, url, content_type) → parser-contract  │
│  Writes into Mongo collection `parsed_documents` via               │
│  corpus/sources/parser_writer.py                                   │
└────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────┐
│  Layer 2 — Mongo `parsed_documents` collection                     │
│  One row per (url, parser, parser_version). Compound unique index. │
│  Schema is FR-1 from requirements.md.                              │
│  Old collections (web_items, parsed_pdfs) remain during migration. │
└────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────┐
│  Layer 3 — Sync to PG                                              │
│  harness/embed_pg.py (refactored, parser-agnostic)                 │
│  Per row from parsed_documents:                                    │
│    - url_metadata(url) → topic_path, ...                           │
│    - text_metadata(text, text_format) → title, ref, committee, ... │
│    - chunk_text(text, text_format) → chunks                        │
│    - embed_chunks(chunks) → vectors                                │
│    - upsert(documents, chunks, links)                              │
│                                                                    │
│  corpus/metadata/url_metadata.py    (pure URL parsing)             │
│  corpus/metadata/text_metadata.py   (regex on text headers)        │
│  corpus/ingestion/chunker.py        (unchanged)                    │
└────────────────────────────────────────────────────────────────────┘
```

The headline simplification:
- `harness/embed_pg.py` loses both parser imports.
- `corpus/ingestion/pdf_normaliser.py` and `html_normaliser.py` either disappear or become thin shims (`normalise_*_doc` becomes a parser-writer-shim around the new contract).

### Parser contract (FR-1, copied for reference)

```python
@dataclass
class ParsedDocument:
    url: str
    parser: str                 # "pymupdf4llm" | "trafilatura" | …
    parser_version: str         # semver or model rev
    parsed_at: datetime
    content_type: str           # "application/pdf" | "text/html"
    text: str                   # markdown or plain text
    text_format: Literal["markdown", "html", "plain"]
    error: str = ""             # empty when parse succeeded
    meta: dict = field(default_factory=dict)  # parser-specific
```

The Mongo document is the JSON-encoded version of this; the compound unique key in Mongo is `(url, parser, parser_version)` to allow multiple parser runs per URL.

### Sync semantics (FR-6 + FR-8 in code shape)

```python
def sync(
    *,
    parser_preference: dict[str, list[str]],   # content_type → ordered parser list
    since: datetime | None = None,
    parser_filter: list[str] | None = None,
    url_filter: list[str] | None = None,
) -> SyncStats:
    docs_by_url = pick_best_parser_per_url(parser_preference, since, parser_filter, url_filter)
    for url, parsed in docs_by_url.items():
        existing = pg.documents.fetch(doc_id=hash(url))
        if existing and existing.parsed_text_hash == sha256(parsed.text):
            # text identical to what's already in PG — no-op
            continue
        if existing:
            pg.delete_chunks_and_links(existing.doc_id)
        url_meta = url_metadata(url)
        text_meta = text_metadata(parsed.text, parsed.text_format)
        chunks = chunk_text(parsed.text, parsed.text_format)
        vectors = embed(chunks)
        pg.upsert(documents=build_doc(url, parsed, url_meta, text_meta),
                  chunks=chunks_with_vectors(chunks, vectors),
                  links=extract_links(parsed.text, parsed.text_format))
    return stats
```

The skip-on-hash path makes re-runs free. The `pick_best_parser_per_url` step is where the parser preference rule lives; everything else is parser-agnostic.

### PG schema delta (FR-7)

```sql
ALTER TABLE documents
    ADD COLUMN parser           TEXT,
    ADD COLUMN parser_version   TEXT,
    ADD COLUMN parsed_at        TIMESTAMPTZ,
    ADD COLUMN parsed_text_hash TEXT;

CREATE INDEX IF NOT EXISTS documents_parser_idx ON documents (parser, parser_version);
```

`parsed_text_hash` is sha256 of the parser's `text` field (after trimming trailing whitespace). It is *not* sha256 of the chunks — chunks are derived; the parser output is the source.

## 4. Implementation approach (sketch — concrete tasks come from /plan)

Phase A — Foundation
- Define `ParsedDocument` dataclass + Mongo writer + collection bootstrapping
- Move URL-derived metadata extraction out of `pdf_normaliser` / `html_normaliser` into `corpus/metadata/url_metadata.py` with golden tests against the existing fixtures
- Move text-derived metadata extraction into `corpus/metadata/text_metadata.py` with golden tests

Phase B — Parsers
- `corpus/parsers/pymupdf4llm.py` — wrap the existing parse logic from `scripts/ingest_parsed_pdfs.py`, write through the new contract
- `corpus/parsers/trafilatura.py` — wrap the existing trafilatura call
- Both parsers ship a small CLI: `python -m corpus.parsers.pymupdf4llm --url <url>` / `--cache <path>` / `--all` (for the cache walk).

Phase C — Sync refactor
- ALTER `documents` with the four new columns
- Rewrite `harness/embed_pg.ingest_source` as `harness/embed_pg.sync` using only `parsed_documents` (with a fallback synthetic reader over the old collections during transition)
- Hash-based skip path; tests for both the skip and re-sync branches
- Update `app.py` / `harness/run_eval.py` if any sync-related references changed (probably none — they only touch the retriever)

Phase D — Llamahub smoke
- `corpus/parsers/llamahub_pdf.py` behind a `[parsers-llamahub]` extra
- Run on ≥5 URLs; show that `--parser-preference llamahub_pdf` re-syncs only those URLs

Phase E — Tests / docs / cutover
- Unit tests for url_metadata, text_metadata, parser contract, sync skip-path, sync re-sync, parser preference
- Integration test against a seeded Mongo + PG
- `docs/RETRIEVAL_PG.md` "Adding a parser" + "Re-sync after parser change"
- `DECISIONS.md` entry: three-layer separation + multi-row-per-URL Mongo convention
- HISTORY.md row per phase per the project convention

## 5. Critical files (current code) and what changes

| File | Current role | Post-refactor role |
|------|--------------|--------------------|
| `harness/embed_pg.py` | Mongo-iter + normalise + chunk + embed + upsert | Mongo-iter (over `parsed_documents`) + url_meta + text_meta + chunk + embed + upsert. Parser-agnostic. |
| `corpus/ingestion/pdf_normaliser.py` | normalise pymupdf4llm doc → DocumentInput; also hosts all the metadata regexes | Either deleted or thinned to a compat shim that reads the old `parsed_pdfs` shape and emits a `ParsedDocument` |
| `corpus/ingestion/html_normaliser.py` | normalise web_items HTML → DocumentInput via trafilatura | Trafilatura call moves to `corpus/parsers/trafilatura.py`; the rest moves to `corpus/metadata/` |
| `corpus/ingestion/chunker.py` | text → chunks via LlamaIndex | Unchanged |
| `corpus/ingestion/link_extractor.py` | markdown/HTML → Link list | Unchanged (lives in the sync layer) |
| `corpus/sources/mongo_source.py` | streams QARecord from web_items + parsed_pdfs for `corpus.jsonl` | Unchanged in this work unit; later (separate WU) migrate to read `parsed_documents` |
| `scripts/ingest_parsed_pdfs.py` | Scrapy cache → `parsed_pdfs` Mongo collection | Refactored to write through `corpus/parsers/pymupdf4llm.py` into `parsed_documents` |
| `corpus/pg_schema.sql` | documents/chunks/links DDL | Adds `parser`, `parser_version`, `parsed_at`, `parsed_text_hash` columns to `documents` |
| `scripts/init_db.py` | applies pg_schema.sql | Unchanged (the schema file's IF NOT EXISTS / ADD COLUMN handles upgrade) |
| `docs/RETRIEVAL_PG.md` | operator's guide for pg retrieval | Adds parser-swap + re-sync sections |
| `DECISIONS.md` | architecture log | Adds three-layer separation decision |

## 6. Cross-cutting considerations

### 6.1 Determinism / `chunk_id` stability (NFR-1)
`chunk_id = sha256(doc_id || chunk_index || text)`. For the cutover to be a no-op for unchanged data, the `text` produced by the refactored sync must be byte-identical to today's. Concretely:
- `chunk_markdown(parsed.markdown, ChunkConfig())` today → same `text` field on each chunk → same `chunk_id`.
- The refactored sync runs `chunk_markdown(parsed.text, ...)` where `parsed.text` is the same markdown string that today travels via `DocumentInput.markdown`. As long as the parser writes the same markdown into Mongo, chunk IDs match.
- The PG `parsed_text_hash` will be identical the second time, so the skip-on-hash branch fires and no re-embed happens.

This is verifiable on the live 25-doc seed before any production-scale ingest.

### 6.2 Parser non-determinism (Risk 2)
If a parser is LLM-backed (some llamahub readers are) it may produce different text on different runs. The hash will differ → re-sync triggers. This is correct behaviour, just expensive. Mitigation: cache LLM-backed parser output in Mongo (which is exactly what this architecture does), so the LLM only runs once per (url, parser, parser_version).

### 6.3 Parser preference rules
Initial: per `content_type`, single-best parser, configured in `harness/configs/parser_preference.yaml`:

```yaml
"application/pdf":
  - pymupdf4llm      # default
"text/html":
  - trafilatura      # default
```

Override via `--parser-preference` CLI flag (e.g. `--parser-preference 'application/pdf=llamahub_pdf'`). Per-URL-pattern preferences (OQ-4) deferred until needed.

### 6.4 Migration safety
Phased migration (OQ-6 default):

1. **PR1**: stand up `parsed_documents` + parsers + writer + tests; the new path coexists with the old. Sync still reads `parsed_pdfs`/`web_items`.
2. **PR2**: refactor sync to read from `parsed_documents` (via synthetic reader that wraps the old collections so we don't need a one-time backfill).
3. **PR3**: run the backfill `scripts/migrate_mongo_to_parsed_documents.py` (writes legacy parser_version="legacy" rows into the new collection from the old ones); drop the synthetic-reader fallback.
4. **PR4** (optional, later): delete `parsed_pdfs`/`web_items` once `corpus/extractors/` is also migrated.

PR1+PR2 is the bulk of the work; PR3 is operational; PR4 is post-cleanup.

### 6.5 What this work unit is NOT
- A full re-ingest. The pipeline change is a no-op for unchanged inputs by design (NFR-1).
- A retrieval change. `harness/retrieve_pg.py`, `app.py`, `run_eval.py` are not touched.
- A `corpus.jsonl` migration. The Q&A extractors (`corpus/extractors/`) keep reading `parsed_pdfs`/`web_items` until a follow-up work unit moves them too.
- A parser quality study. We ship two existing parsers + one llamahub smoke. Comparing parser output quality on EMA content is a separate research task.

## 7. Open questions (cross-link to requirements.md)

Repeating the open questions here for visibility; resolutions go in `decisions.md` once the user picks.

- **OQ-1** Mongo collection layout: single collection w/ compound key (A, recommended), per-parser collections (B), or nested-by-parser per URL (C)?
- **OQ-2** Raw HTML: separate raw-input store, or also a row in `parsed_documents` with `parser="raw"`?
- **OQ-3** Full parsed text in PG, or Mongo-only?
- **OQ-4** Parser preference: per content_type (simple), per URL pattern (richer), or both?
- **OQ-5** `corpus/extractors/` in scope?
- **OQ-6** Big-bang vs phased migration?
- **OQ-7** Parse-on-demand integration into the sync CLI?

## 8. Recommended next step

The architecture is concrete enough that the **next step is `/plan`** — break Phase A–E into 15–25 numbered tasks with acceptance criteria, but only after resolving OQ-1, OQ-3, and OQ-6 (the three that materially change the task list). The others can be answered during execution.

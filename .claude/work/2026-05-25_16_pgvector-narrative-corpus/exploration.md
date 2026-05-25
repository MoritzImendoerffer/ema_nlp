# Exploration — pgvector narrative corpus

## Current state (confirmed via reads)

- Mongo is **localhost:27017, version 7.0.22 Community**. No Atlas
  modules; `$vectorSearch` not available.
- `ema_scraper.parsed_pdfs`: **65,263 total**, **38,729** with
  `error: ""` AND non-empty `markdown` — these are the usable PDFs.
- `ema_scraper.web_items`: **22,743** HTML pages
  (`content_type: "text/html"`). Sample homepage is ~74 KB.
- `corpus/corpus.jsonl`: 26,251 Q&A records. **Will remain unchanged**
  as the benchmark source artifact.
- `harness/embed.py` builds a FAISS index from `corpus.jsonl`. **Will
  remain available as `EMA_RETRIEVER=faiss` for back-compat / ablation.**
- `harness/retrieve.py` defines `RetrievalConfig`, `retrieve_with_config`,
  `build_retrieve_fn`. Workflows consume the resulting `retrieve_fn`.
- pgvector / Postgres not yet in `pyproject.toml`. `libpq-dev` is
  installed (`/usr/bin/pg_config` present); the Postgres server itself
  may not be running yet.

## Target architecture

```
                      MongoDB ema_scraper (unchanged)
                        │
                        │  read-once during ingest
                        ▼
   scripts/ingest_to_pg.py
        │      ┌────────────────────────────────────────┐
        │      │  Per source (pdf | html):              │
        │      │   1. read raw                          │
        │      │   2. normalise (markdown → blocks, html → text) │
        │      │   3. landing-page filter               │
        │      │   4. chunk (heading-aware / window)    │
        │      │   5. extract outgoing links            │
        │      └────────────────────────────────────────┘
        ▼
   PostgreSQL (pgvector)
   ├── documents  (one row per source URL)
   ├── chunks     (vector(1024), tsvector for BM25, text, metadata)
   └── links      (edges: src_doc → tgt_doc, type, anchor)

        ▲                                ▲
        │ vector ANN + WHERE filters     │ graph traversal
        │                                │
   harness/retrieve_pg.py  ─────────────►│
        │
        │ same callable signature as harness/retrieve.py
        ▼
   harness/workflows/* (unchanged)
```

## Why pgvector

- **Single store**: vector + metadata + relational `links` in one DB.
  No Mongo↔FAISS sync needed.
- **SQL filters at the ANN layer**: `WHERE topic_path LIKE '/documents/scientific%' ORDER BY embedding <-> $1 LIMIT 10`. The
  user explicitly asked for "preselecting parts of the corpus."
- **Graph traversal**: recursive CTE on `links` is one query.
- **Local, free, mature**: no new service to operate beyond Postgres.
- **HNSW**: pgvector ≥ 0.5.0 ships HNSW with `vector_cosine_ops` /
  `vector_l2_ops` / `vector_ip_ops`.

## Schema (proposed)

```sql
-- enable extensions once per database
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE documents (
    doc_id           TEXT PRIMARY KEY,            -- sha256(source_url)
    source_url       TEXT UNIQUE NOT NULL,
    source_type      TEXT NOT NULL CHECK (source_type IN ('pdf','html')),
    title            TEXT,
    topic_path       TEXT,                        -- derived from URL path
    reference_number TEXT,                        -- EMA/.../YYYY when found
    committee        TEXT,                        -- CHMP/PRAC/CVMP/COMP/PDCO/CAT — parsed from reference_number
    revision         TEXT,
    last_updated     TIMESTAMPTZ,
    raw_byte_size    INT,
    ingested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    meta             JSONB NOT NULL DEFAULT '{}'  -- escape hatch
);
CREATE INDEX documents_topic_path_idx  ON documents (topic_path);
CREATE INDEX documents_reference_idx   ON documents (reference_number);
CREATE INDEX documents_committee_idx   ON documents (committee);
CREATE INDEX documents_last_updated    ON documents (last_updated);
CREATE INDEX documents_title_trgm      ON documents USING gin (title gin_trgm_ops);

CREATE TABLE chunks (
    chunk_id     TEXT PRIMARY KEY,           -- sha256(doc_id || chunk_index || text)
    doc_id       TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    chunk_index  INT  NOT NULL,
    text         TEXT NOT NULL,
    heading_path TEXT,                       -- e.g. "## 2. What is..."
    token_count  INT,
    embedding    vector(1024)  NOT NULL,
    text_tsv     tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);
CREATE INDEX chunks_doc_id_idx     ON chunks (doc_id);
CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m=16, ef_construction=64);
CREATE INDEX chunks_text_tsv_idx   ON chunks USING gin (text_tsv);

CREATE TABLE links (
    src_doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    tgt_url    TEXT NOT NULL,                -- raw target, may not resolve
    tgt_doc_id TEXT REFERENCES documents(doc_id),  -- nullable until resolved
    link_type  TEXT NOT NULL,                -- 'hyperlink' | 'reference_number' | 'see_qa'
    anchor     TEXT,
    chunk_id   TEXT REFERENCES chunks(chunk_id),   -- which chunk contained the link
    PRIMARY KEY (src_doc_id, tgt_url, link_type)
);
CREATE INDEX links_tgt_doc_idx ON links (tgt_doc_id);
CREATE INDEX links_link_type   ON links (link_type);
```

Notes:
- `chunks.text_tsv` gives BM25-ish search via `ts_rank_cd(...)` — first
  cut for hybrid retrieval; can be swapped for rank_bm25 later.
- `documents.meta` is for extracted-but-not-promoted fields (e.g.
  committee, date parsed from reference number).
- `links.tgt_doc_id` is filled by a post-pass once all docs are
  ingested — initial insert may have NULL.

## Module layout (proposed)

```
config.py                  +PG_DSN, +EMA_RETRIEVER env var
pyproject.toml             +psycopg[binary], +pgvector, +trafilatura, +sentence-splitters

corpus/
  ingestion/
    __init__.py
    pdf_to_chunks.py       # markdown → heading-aware chunks
    html_to_chunks.py      # html → text (trafilatura) → chunks
    link_extractor.py      # markdown/html → list[Link]
    landing_filter.py      # generalised landing-page heuristic
  pg_schema.sql            # exact DDL from above

harness/
  embed_pg.py              # entry: build chunks + embeddings, upsert to PG
                           # CLI: --source {pdfs,html,all} --batch-size N --resume
  retrieve_pg.py           # mirror of harness/retrieve.py shape:
                           #   RetrievalConfigPG, retrieve_with_config_pg,
                           #   build_retrieve_fn_pg
  pg/
    __init__.py
    conn.py                # connection pool (psycopg_pool)
    queries.py             # parameterised SQL
    adapter.py             # wraps results into LlamaIndex NodeWithScore so
                           # workflows can keep using .docstore.get_node etc.

scripts/
  setup_pg.sh              # apt install / docker compose / pg_isready check
  init_db.py               # run pg_schema.sql idempotently
  resolve_links.py         # fill links.tgt_doc_id by matching URLs / ref numbers
```

`app.py` and `harness/run_eval.py` get a small dispatch at the point
where they currently call `harness.embed.build_index` /
`harness.retrieve.build_retrieve_fn`:

```python
if os.getenv("EMA_RETRIEVER", "faiss") == "pgvector":
    from harness.retrieve_pg import build_retrieve_fn_pg as build_retrieve_fn
    index = None  # pgvector retriever does not need a loaded index
else:
    from harness.retrieve import build_retrieve_fn
    index = build_index(...)
```

## Chunking — LlamaIndex node parsers, configurable

A small `ChunkConfig` dataclass selects the parser:

```python
@dataclass
class ChunkConfig:
    parser: Literal["markdown", "sentence", "hierarchical"] = "markdown"
    max_tokens: int = 512
    overlap: int = 64
    min_chunk_chars: int = 80  # drop tiny chunks (likely TOC/page numbers)
```

`corpus/ingestion/chunker.py` resolves it to a LlamaIndex parser:

| parser        | LlamaIndex class                             |
|---------------|---------------------------------------------|
| `"markdown"`  | `MarkdownNodeParser` + `SentenceSplitter` fallback |
| `"sentence"`  | `SentenceSplitter`                          |
| `"hierarchical"` | `HierarchicalNodeParser`                 |

Heading-aware default flow (PDF markdown):

1. `MarkdownNodeParser` splits on `^#{1,3} ` boundaries; each section
   yields a `TextNode`.
2. If a node's token count > `max_tokens`, sub-split with
   `SentenceSplitter(chunk_size=max_tokens, chunk_overlap=overlap)`.
3. Drop chunks smaller than `min_chunk_chars` (TOC entries, page
   numbers, "References" stubs).
4. Persist the heading breadcrumb in `chunks.heading_path` so the LLM
   sees document structure (e.g. `"## 2. Acceptable Intake"`).

HTML flow:

1. `trafilatura.extract(html, output_format='markdown', include_links=True, with_metadata=True)`.
2. Drop pages where extracted text < 200 chars (landing/nav guard).
3. Pipe the resulting markdown into the same `ChunkConfig` machinery —
   one code path for both source types.

Both flows produce LlamaIndex `TextNode` objects so we can reuse
`SentenceSplitter`, `TokenTextSplitter`, and `HierarchicalNodeParser`
without re-inventing chunkers.

## Link traversal — configurable two-mode design

`RetrievalConfigPG` gets a `traversal` sub-config:

```python
@dataclass
class TraversalConfig:
    mode: Literal["none", "auto", "agent_tool"] = "none"
    max_hops: int = 1
    link_types: list[str] = field(
        default_factory=lambda: ["hyperlink", "reference_number"]
    )  # 'see_qa' excluded by default to avoid Q&A leakage
```

Behaviour:

- `mode="none"` — vanilla retrieval, no link expansion.
- `mode="auto"` — after the top-k ANN scan, run a recursive CTE on
  `links` to collect chunks from neighbours (up to `max_hops`,
  filtered by `link_types`). Mirrors the current `recursive` strategy
  in `harness/retrieve.py` but over the link graph instead of
  per-node `cross_refs`.
- `mode="agent_tool"` — retrieval returns only the seed top-k.
  A separate `follow_links(chunk_id, link_types?, k?)` tool is
  registered on ReAct agents (`harness/workflows/react_native.py`)
  so the agent decides when to expand.

Both modes share the same SQL helper: a parameterised recursive CTE
that walks `links` joined with `chunks`. The two modes differ only in
when it is called.

## Link extraction sketch

- **HTML**: BeautifulSoup walks `<a href>`; normalise relative URLs
  against the source URL; classify by domain (internal EMA vs external).
- **PDF markdown**: regex `\[([^\]]+)\]\((https?://[^\)]+)\)` — produces
  `(anchor, url)`.
- **Reference numbers**: regex `EMA/[A-Z0-9]+/[A-Z0-9/]*/\d{4}` — when
  matched, `link_type='reference_number'`, `tgt_url` is the raw code;
  later resolved to a `doc_id` if any document has that
  `reference_number`.
- **Internal "see Q&A N" or "see question N"** style: regex extract,
  `link_type='see_qa'`, target is unresolved (best-effort metadata).

## Q&A exclusion mechanic

- `corpus/corpus.jsonl` and `harness/embed.py` are **left alone**.
- The new ingest never reads `corpus.jsonl`. It reads MongoDB
  `parsed_pdfs` and `web_items` directly.
- `chunks.source_record_type` is *not* needed because we don't insert
  Q&A pairs at all. If we ever do, add the column.
- The benchmark pipeline (Phase 2) will draw gold questions from
  `corpus.jsonl` as today. Leakage is a benchmark concern, not an
  ingest concern (per `project_roadmap/LEAKAGE.md`).

## Implementation phases (outline only — /plan will produce ordered tasks)

- **Phase A: Postgres bring-up.** Install Postgres + pgvector, create
  DB, apply schema, smoke-test from Python.
- **Phase B: PDF ingest + embed.** Stream `parsed_pdfs` → markdown
  chunks → BGE embeddings (on 3090 PC) → bulk upsert to `documents` +
  `chunks`. Resumable.
- **Phase C: HTML ingest + embed.** Same shape, different normaliser.
- **Phase D: Link extraction + resolution.** Populate `links`; second
  pass to fill `tgt_doc_id`.
- **Phase E: Retriever rewrite.** `harness/retrieve_pg.py` mirroring
  `harness/retrieve.py` — dense, BM25 (`tsvector`), hybrid (RRF),
  `recursive` (graph traversal via `links`), pre-filter support.
- **Phase F: Wire into app + run_eval + workflows.** Env-var dispatch.
  Smoke-test Simple-RAG end-to-end. Confirm Phoenix traces still
  populated.
- **Phase G: Sub-corpus filters.** Expose `topic_filter` / committee /
  date range pre-filters as `RetrievalConfigPG` fields.
- **Phase H: Tests + docs.** Unit tests for chunkers, link extractor,
  retriever. Update `CLAUDE.md` to describe the two retriever paths
  and the V1 scope change (narrative corpus is now in scope; Q&A
  pairs are evaluation-only).

## Key files that will change

| File | Change |
|------|--------|
| `pyproject.toml` | add `psycopg[binary]`, `pgvector`, `trafilatura` |
| `config.py` | add `PG_DSN`, `EMA_RETRIEVER` |
| `app.py` | dispatch on `EMA_RETRIEVER` for index/retriever loading |
| `harness/run_eval.py` | same dispatch |
| `CLAUDE.md` | document new retrieval path + scope update |
| `corpus/` | new `ingestion/` subpackage |
| `harness/` | new `embed_pg.py`, `retrieve_pg.py`, `pg/` subpackage |
| `scripts/` | `setup_pg.sh`, `init_db.py`, `resolve_links.py` |
| `tests/` | new tests for chunker, link extractor, pg retriever |

## What stays untouched

- `corpus/corpus.jsonl` and everything that builds it
- `harness/embed.py` (FAISS path), `harness/retrieve.py` (FAISS path)
- All `harness/workflows/*.py` — they only see `retrieve_fn`, which we
  swap behind their backs
- `harness/judge.py`, `harness/run_eval.py` orchestration logic
- Phoenix integration

## Recommended next step

All seven design questions are now locked (see
`requirements.md §Locked decisions`). Run **`/plan`** to produce an
ordered `state.json` with acceptance criteria per task. Suggested
task grouping for /plan:

- A1–A3: Postgres bring-up (deps, DDL, smoke test)
- B1–B5: PDF ingest + chunker + embedder + upsert + resume
- C1–C3: HTML ingest (trafilatura + chunker reuse + upsert)
- D1–D3: Link extraction + post-pass resolution
- E1–E6: `retrieve_pg.py` (dense, BM25 via tsvector, hybrid RRF,
  prefilter, traversal=auto, agent_tool)
- F1–F3: Wire `app.py` / `run_eval.py` / one workflow (`simple_rag`)
- G1–G2: Sub-corpus pre-filter exposure in YAML configs
- H1–H4: Tests, docs, CLAUDE.md scope update, retire FAISS-default

Total estimate: ~25 tasks. /plan will refine and order them.

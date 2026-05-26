# pgvector retrieval — operator's guide

This document covers the Postgres + pgvector retrieval stack added in the
`pgvector-narrative-corpus` work unit. It replaces the FAISS path for the
full narrative corpus (PDFs + HTML); the FAISS index over `corpus.jsonl`
remains for benchmark-only experiments.

See also: [SETUP.md](SETUP.md) for general environment setup,
`harness/retrieve_pg.py` for the public API, and
`.claude/work/2026-05-25_16_pgvector-narrative-corpus/` for the design notes
that drove these decisions.

---

## 1. Why Postgres instead of FAISS

| Need | FAISS | Postgres + pgvector |
|------|-------|----------------------|
| Sub-corpus filtering (committee / topic / date) | Post-filter in Python | SQL `WHERE` before ranking |
| Hybrid (dense + BM25) | Two indexes + join | One `JOIN documents USING (doc_id)` |
| Link-graph traversal | External adjacency list | Recursive CTE over `links` |
| Resume / idempotent ingest | Re-embed everything | `INSERT … ON CONFLICT (chunk_id)` |
| One narrative corpus, many sub-corpora | New index per slice | Single DB, prefilters at query time |

The trade-off: dense kNN is slightly slower than FAISS for large k, but the
filters and link walks pay for themselves on the eval workload.

---

## 2. Provisioning

### 2.1 Docker (default)

```bash
cd deploy/postgres
docker compose up -d
```

The compose file pins `pgvector/pgvector:pg16`; the entrypoint creates the
`ema_nlp` database and superuser from `POSTGRES_USER` / `POSTGRES_PASSWORD`
(both default to `ema_nlp`).

Health-check:

```bash
docker exec ema_nlp_pg pg_isready -U ema_nlp -d ema_nlp
docker exec ema_nlp_pg psql -U ema_nlp -d ema_nlp \
    -c "SELECT extversion FROM pg_extension WHERE extname='vector';"
# expect >= 0.5.0 (HNSW support)
```

### 2.2 Apply the schema

```bash
python -m scripts.init_db          # idempotent — re-runs are safe
python -m scripts.init_db --reset  # drop + re-create (destroys data)
```

The DDL lives in `corpus/pg_schema.sql` and is applied verbatim by `init_db`.

---

## 3. Environment variables

Add to `~/.myenvs/ema_nlp.env`:

```bash
# Primary DSN — used by ingest + retrieval + the chat UI
PG_DSN=postgresql://ema_nlp:ema_nlp@localhost:5432/ema_nlp

# Test DSN — used by the integration tests in tests/test_retrieve_pg.py
PG_DSN_TEST=postgresql://ema_nlp:<password>@localhost:5432/ema_nlp_test

# Retrieval backend switch — default is 'pgvector' as of NARR-028 (2026-05-26);
# set EMA_RETRIEVER=faiss to opt back into the legacy FAISS path.
# EMA_RETRIEVER=pgvector
```

`EMA_RETRIEVER` controls which retrieval factory `app.py` and `run_eval.py`
import:

| Value | Code path | Index source |
|-------|-----------|--------------|
| `pgvector` *(default since NARR-028)* | `harness.retrieve_pg.build_retrieve_fn_pg` | `chunks` / `documents` / `links` in Postgres |
| `faiss` *(legacy, kept for back-compat)* | `harness.retrieve.build_retrieve_fn` | `corpus.jsonl` + FAISS docstore |

Switch backends without rebuilding the index:

```bash
EMA_RETRIEVER=pgvector python -m harness.run_eval \
    --config harness/configs/example_chmp_only.yaml
```

The Phoenix span attribute `ema.retrieval.backend` records which backend
served each workflow invocation.

---

## 4. Schema overview

Three tables, one extension (`vector`) + one for trigram filtering (`pg_trgm`).
Full DDL: `corpus/pg_schema.sql`.

### `documents`

One row per source URL. Carries the metadata used by prefilters (`committee`,
`topic_path`, `last_updated`) and link resolution (`reference_number`).

| Column | Type | Notes |
|--------|------|-------|
| `doc_id` | TEXT PK | `sha256(source_url)` |
| `source_url` | TEXT UNIQUE | Original URL |
| `source_type` | TEXT | `'pdf'` or `'html'` |
| `title` | TEXT | H1 / `<title>` / URL fallback |
| `topic_path` | TEXT | URL directory path (without filename) |
| `reference_number` | TEXT | `EMA/<COMMITTEE>/<NNN>/<YYYY>` |
| `committee` | TEXT | `CHMP` / `PRAC` / `CVMP` / `COMP` / `PDCO` / `CAT` |
| `revision` | TEXT | `Rev. N` |
| `last_updated` | TIMESTAMPTZ | Header date or trafilatura metadata |
| `parser` | TEXT | Parser that produced `parsed_text` (e.g. `pymupdf4llm`, `trafilatura`) |
| `parser_version` | TEXT | Pinned version of that parser (or `legacy` from the synthetic reader) |
| `parsed_at` | TIMESTAMPTZ | When the parser ran (`parsed_documents.parsed_at`) |
| `parsed_text` | TEXT | Full pre-chunk text from the parser — feeds re-chunking on parser swap |
| `parsed_text_hash` | TEXT | `sha256(parsed_text)` after trailing-trim — drives the sync hash-skip path |
| `meta` | JSONB | Escape hatch |

### `chunks`

One row per text chunk. The `embedding` column is a 1024-dim `vector` (matches
`BAAI/bge-large-en-v1.5`). `text_tsv` is a `STORED` generated column over the
chunk text — `to_tsvector('english', text)` — used by BM25.

| Index | Type | Used by |
|-------|------|---------|
| `chunks_embedding_hnsw` | HNSW (`vector_cosine_ops`) | dense kNN |
| `chunks_text_tsv_idx` | GIN | BM25 |
| `chunks_doc_id_idx` | btree | per-doc lookups, ingest dedup |

`chunk_id = sha256(doc_id || chunk_index || normalised_text)` so the same chunk
text deterministically maps to the same row across re-runs — `INSERT … ON
CONFLICT (chunk_id) DO NOTHING` makes ingest idempotent.

### `links`

One row per outgoing reference. Populated by the link extractor during
ingest; `tgt_doc_id` is filled in by `scripts/resolve_links.py` once both
endpoints exist in `documents`.

| Column | Notes |
|--------|-------|
| `src_doc_id` | FK → `documents.doc_id` |
| `tgt_url` | Raw target (URL or EMA reference number) |
| `tgt_doc_id` | FK → `documents.doc_id`, nullable |
| `link_type` | `'hyperlink'` / `'reference_number'` / `'see_qa'` |
| `anchor` | Markdown / HTML anchor text |
| `chunk_id` | The chunk this link appeared in |
| PK | `(src_doc_id, tgt_url, link_type)` |

`see_qa` links are excluded from default traversal because they point at
benchmark Q&As and could leak gold answers into eval — see
`TraversalConfig.link_types` defaults.

---

## 5. Ingest CLI

The MIGR-007 refactor split the pipeline into three layers (see §13):
parsers write `ParsedDocument`s to the Mongo `parsed_documents` collection,
and `harness.embed_pg.sync` reads from there into Postgres. The legacy
`--source pdfs|html` mode is still available as a back-compat shim.

```bash
# Default mode — sync from `parsed_documents` using the YAML preference
python -m harness.embed_pg

# Override the preference per content_type (repeatable)
python -m harness.embed_pg \
    --parser-preference 'application/pdf=llamahub_pdf_PDFReader' \
    --parser-preference 'text/html=trafilatura'

# Limit to specific URLs (repeatable)
python -m harness.embed_pg --url-filter 'https://www.ema.europa.eu/.../doc-a.pdf'

# Dry run — compute hash-skip + chunk counts without writing
python -m harness.embed_pg --dry-run

# Read from the legacy parsed_pdfs + web_items via the synthetic reader
python -m harness.embed_pg --legacy-source

# Legacy direct mode (pre-MIGR-007 normalisers)
python -m harness.embed_pg --source pdfs --limit 100
python -m harness.embed_pg --source html --force

# Tune batch size for the BGE encode call (GPU memory)
python -m harness.embed_pg --batch-size 32
```

### Sync output

`sync()` returns and the CLI prints a `SyncStats` JSON dict:

```json
{
  "seen": 25,                         # URLs visited in parsed_documents
  "selected": 25,                     # passed the preference selector
  "new": 0,                           # never previously synced
  "re_synced": 0,                     # parsed_text_hash mismatched, re-embedded
  "skipped_unchanged": 25,            # hash matched — chunker/embedder never ran
  "skipped_no_preferred_parser": 0,   # no row matched the YAML/CLI preference
  "chunks_written": 0,
  "links_written": 0,
  "errors": 0
}
```

After ingest, link resolution turns unresolved `tgt_doc_id` columns into
typed edges:

```bash
python -m scripts.resolve_links
```

The script reports counts per link type and shows a sample of still-unresolved
URLs (mostly off-site references that don't have a document row).

---

## 6. Retrieval modes

`RetrievalConfigPG.mode` selects the retriever:

| Mode | What runs | When to use |
|------|-----------|-------------|
| `dense` | HNSW kNN, score = `1 - cosine_distance` | Pure semantic similarity |
| `bm25` | `ts_rank_cd(plainto_tsquery(...))` | Keyword-heavy queries, rare tokens |
| `hybrid` *(default)* | RRF fusion of dense + BM25 (K=60) | General use; matches the FAISS hybrid behaviour |

```python
from harness.retrieve_pg import RetrievalConfigPG, retrieve_with_config_pg

cfg = RetrievalConfigPG(mode="hybrid", k=10)
results = retrieve_with_config_pg(cfg, "nitrosamine acceptable intake limits")
# -> list[(chunk_id, score, metadata)]
```

Or from YAML (`harness/configs/example_chmp_only.yaml` is a worked example):

```yaml
retrieval:
  mode: hybrid
  k: 10
  prefilter:
    committee: ["CHMP"]
  traversal:
    mode: auto
    max_hops: 1
```

---

## 7. Traversal modes

`TraversalConfig.mode` controls post-retrieval link-graph expansion:

| Mode | Behaviour |
|------|-----------|
| `none` *(default)* | Return the seed top-k as-is |
| `auto` | Walk the `links` table with a recursive CTE up to `max_hops` hops; append one representative chunk per visited doc; seed top-k stays at the front |
| `agent_tool` | Expose `follow_links` as a LlamaIndex `FunctionTool` so ReAct workflows decide when to expand |

`link_types` defaults to `['hyperlink', 'reference_number']` — `see_qa` is
intentionally excluded (see §4).

> **Note**: prefilters apply to the seed top-k via the dense / BM25
> retrievers, but auto-traversal expansion follows the link graph without
> re-applying the prefilter. If you need a strict sub-corpus, set
> `traversal.mode: none`.

---

## 8. Sub-corpus filters

`PrefilterConfig` adds SQL `WHERE` clauses before ranking:

| Field | SQL | Example |
|-------|-----|---------|
| `topic_path_prefix` | `d.topic_path LIKE 'prefix%'` | `"/en/medicines/"` |
| `committee` | `d.committee = ANY([...])` | `["CHMP", "PRAC"]` |
| `date_range` | `d.last_updated BETWEEN start AND end` | `["2020-01-01", "2024-12-31"]` |

Empty defaults disable each filter. See the `example_chmp_only.yaml`
reference config.

---

## 9. Tests

```bash
# Unit tests — no DB required
pytest tests/test_chunker.py tests/test_pdf_normaliser.py \
       tests/test_html_normaliser.py tests/test_link_extractor.py \
       tests/test_retrieve_pg_config.py tests/test_retrieve_pg_pure.py

# Integration test — requires PG_DSN_TEST (see §10)
pytest tests/test_retrieve_pg.py
```

The integration suite seeds a deterministic 10-chunk / 3-doc / 2-link corpus
and monkey-patches the BGE embedding call so it doesn't need the model on
disk.

---

## 10. Provisioning the test database

```bash
# One-time
docker exec ema_nlp_pg psql -U ema_nlp -d ema_nlp \
    -c "CREATE DATABASE ema_nlp_test;"
docker exec -i ema_nlp_pg psql -U ema_nlp -d ema_nlp_test \
    < corpus/pg_schema.sql
```

Add the DSN to `~/.myenvs/ema_nlp.env`:

```bash
PG_DSN_TEST=postgresql://ema_nlp:<password>@localhost:5432/ema_nlp_test
```

`tests/test_retrieve_pg.py` skips when `PG_DSN_TEST` is unset, so CI without
a database simply runs the unit tests.

---

## 11. Troubleshooting

**`SELECT 1` works but `SELECT <vec>::vector` errors.**
The pgvector extension is not enabled on the database. Run
`CREATE EXTENSION IF NOT EXISTS vector;` against the target DB.

**Retrieval calls take 10+ seconds on the first invocation.**
First call loads BGE-large-en-v1.5 (~1.3 GB) into CUDA memory. Subsequent
calls are fast. Set `HF_HUB_OFFLINE=1` to silence metadata warnings if the
model is already cached locally.

**`<=>` operator returns wrong distances.**
`register_vector` only auto-adapts numpy arrays; raw Python lists go through
as `double precision[]` and break the operator. The dense query in
`harness/pg/queries.py` casts the parameter explicitly with `::vector` —
preserve that cast when adding new vector-distance SQL.

**`Settings.embed_model` lazy-loads OpenAI's embedder and fails.**
`harness/retrieve_pg.py::_query_embedding` guards this with a
module-level `_embed_configured` flag that calls
`configure_embed_model()` once before touching `Settings.embed_model`.
Don't read the attribute directly — go through `_query_embedding`.

**Pool is opened against the wrong DSN.**
`harness/pg/conn.py::get_pool` is a process-singleton. The first caller wins
for the DSN. Tests that need a different DSN must either
`close_pool()` first or inject their own `ConnectionPool` via the
`pool=` kwarg on every retriever (`retrieve_dense_pg`, `retrieve_bm25_pg`,
`retrieve_with_config_pg`, …).

**`follow_links` returns `[]` for a chunk_id the agent hallucinated.**
Expected behaviour — `follow_links` returns `[]` for empty or unknown
chunk_ids so the ReAct agent's bad calls aren't fatal.

**`docker exec ema_nlp_pg` not found.**
Container is named in `deploy/postgres/docker-compose.yml`
(`container_name: ema_nlp_pg`). Confirm with `docker compose -f
deploy/postgres/docker-compose.yml ps`.

---

## 13. Three-layer data flow (MIGR-001..017)

Since MIGR-001 the ingest pipeline is three layered modules instead of a
single normalise-and-chunk monolith:

```
                ┌──── Layer 1 — Parsers (corpus/parsers/) ────────┐
raw bytes  ───▶ │  pymupdf4llm  trafilatura  llamahub_pdf (demo)  │ ───▶ ParsedDocument
                └─────────────────────────────────────────────────┘
                                       │
                                       ▼
                ┌──── Layer 2 — Mongo `parsed_documents` ─────────┐
                │  One row per (url, parser, parser_version).     │
                │  Compound unique index. Authoritative store     │
                │  for parsed text + parser identity.             │
                └─────────────────────────────────────────────────┘
                                       │
                                       ▼
                ┌──── Layer 3 — harness/embed_pg.sync ────────────┐
parsed_text ──▶ │  url_metadata + text_metadata derive doc rows;  │ ───▶ documents / chunks / links
                │  sha256(parsed_text) hash-skips unchanged docs; │      (PG, canonical retrieval store)
                │  chunker + embedder + upsert otherwise.         │
                └─────────────────────────────────────────────────┘
```

### Adding a parser

To add a new content extractor (e.g. a richer HTML extractor, an OCR
fallback for scanned PDFs, a domain-tuned LlamaHub reader):

1. **Create `corpus/parsers/<name>.py`** with a class implementing the
   `corpus.parsers.base.Parser` protocol:
   ```python
   class MyParser:
       name: str = "myparser"
       version: str = importlib.metadata.version("my-upstream-pkg")

       def parse(
           self,
           raw: bytes | str,
           url: str,
           content_type: str,
       ) -> ParsedDocument:
           ...
   ```
   Populate `error` instead of raising — the sync layer skips error rows
   rather than aborting the batch. `corpus/parsers/llamahub_pdf.py` is a
   worked example with a CLI-less parser behind an optional extra.

2. **Write through the parsed-documents writer**:
   ```python
   from corpus.sources.parsed_documents import write_parsed_document
   write_parsed_document(parser.parse(raw, url, content_type), client=client)
   ```
   The compound unique key on `(url, parser, parser_version)` makes this
   idempotent — re-running upserts the same row.

3. **Optional: add a CLI** at `python -m corpus.parsers.<name>` for
   batch ingest. `corpus/parsers/pymupdf4llm.py` walks a Scrapy cache;
   `corpus/parsers/trafilatura.py` reads `web_items.html_raw`. Both
   write through the same `write_parsed_document` helper.

4. **Make it discoverable to the sync** via `parser_preference`. Either
   edit `harness/configs/parser_preference.yaml`:
   ```yaml
   application/pdf:
     - myparser           # tried first
     - pymupdf4llm        # fallback
   ```
   …or override per-run with the CLI flag:
   ```bash
   python -m harness.embed_pg \
       --parser-preference 'application/pdf=myparser'
   ```

5. **Optional: pyproject extra** when the parser pulls heavyweight
   dependencies. Pattern in `pyproject.toml`:
   ```toml
   [project.optional-dependencies]
   parsers-myparser = ["my-upstream-pkg>=X.Y"]
   ```
   Import the upstream package at function scope so importing
   `corpus.parsers.<name>` doesn't force the install. Tests skip with
   `importlib.util.find_spec("my-upstream-pkg")` when the extra is
   absent; see `tests/test_parsers_llamahub_pdf.py` for the pattern.

### Re-sync after a parser change

The sync's hash-skip path means a parser swap only re-embeds the URLs
whose `parsed_text` actually changed. The typical workflow:

1. Run the new parser to populate its rows in `parsed_documents`:
   ```bash
   python -m corpus.parsers.myparser --cache <path>
   ```
   Existing rows for other parsers are untouched (different compound
   key).

2. Update the preference. Either edit the YAML or pass `--parser-preference`
   on the next sync.

3. Re-sync against the affected URLs only:
   ```bash
   python -m harness.embed_pg \
       --parser-preference 'application/pdf=myparser' \
       --url-filter 'https://www.ema.europa.eu/.../doc-a.pdf' \
       --url-filter 'https://www.ema.europa.eu/.../doc-b.pdf'
   ```
   The sync iterates URLs, computes `sha256(parsed_text)` for the
   preferred row, compares against `documents.parsed_text_hash`. On
   mismatch: deletes the doc's chunks + links and re-chunks/re-embeds.
   On match: no-op (`skipped_unchanged++`).

4. Roll back by flipping the preference back. The previous parser's row
   is still in `parsed_documents` (different `parser` value), so the
   sync will pick it up again and re-embed against that older text.

### Hash-skip semantics — what re-syncs vs what doesn't

| Change | URL re-syncs? |
|--------|---------------|
| Same parser, same text upstream | No (`skipped_unchanged`) |
| Same parser, parsed_text changed | Yes (`re_synced` — delete + re-embed) |
| Preference flips to a different parser with different text | Yes |
| Preference flips to a different parser with byte-identical text | No |
| New URL appears in `parsed_documents` | Yes (`new`) |
| Preference lists a parser that has no row for the URL | URL is skipped with a warning (`skipped_no_preferred_parser`) |

### `parser_preference.yaml`

The default lives at `harness/configs/parser_preference.yaml`:

```yaml
application/pdf:
  - pymupdf4llm
text/html:
  - trafilatura
```

CLI overrides are `--parser-preference content_type=parser`, repeatable.
Per content_type the override fully replaces the YAML list — there's no
merge — so write the full ordered list when you want a fallback chain.

### Env vars added by MIGR-006/009

| Variable / file | Purpose |
|-----------------|---------|
| `harness/configs/parser_preference.yaml` | Per-content_type parser default list |
| `--parser-preference` CLI flag | Per-run override (`ct=parser`, repeatable) |
| `--url-filter` CLI flag | Restrict sync to specific URLs (repeatable) |
| `--parser-filter` CLI flag | Restrict to specific parser names (repeatable) |
| `--legacy-source` CLI flag | Read via the synthetic legacy reader |

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

# Retrieval backend switch (default: 'faiss')
EMA_RETRIEVER=pgvector
```

`EMA_RETRIEVER` controls which retrieval factory `app.py` and `run_eval.py`
import:

| Value | Code path | Index source |
|-------|-----------|--------------|
| `faiss` *(default for back-compat)* | `harness.retrieve.build_retrieve_fn` | `corpus.jsonl` + FAISS docstore |
| `pgvector` | `harness.retrieve_pg.build_retrieve_fn_pg` | `chunks` / `documents` / `links` in Postgres |

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

```bash
# All PDFs from MongoDB parsed_pdfs (filter {error: ""})
python -m harness.embed_pg --source pdfs

# All HTML from MongoDB web_items where content_type='text/html'
python -m harness.embed_pg --source html

# Small dry run
python -m harness.embed_pg --source pdfs --limit 100

# Force re-ingest (deletes chunks for the affected source_urls first)
python -m harness.embed_pg --source pdfs --force

# Tune batch size for the BGE encode call (GPU memory)
python -m harness.embed_pg --source pdfs --batch-size 32
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

# Session handoff — NARR-001..015 complete, NARR-016 next

Last session ran NARR-001 through NARR-015 on `marvin-gpu` (the 3090 PC).
The two-machine split documented in `decisions.md` §2 is **no longer
applicable** — `marvin-gpu` has the GPU **and** a local MongoDB with the
ema_scraper data, so all remaining tasks execute on this single host.

## What's in place

- **Postgres**: `pgvector/pgvector:pg16` container `ema_nlp_pg`, started by
  `deploy/postgres/docker-compose.yml`. Volume `ema_nlp_pgdata`. pgvector
  extension 0.8.2.
- **Env file**: `~/.myenvs/ema_nlp.env` exists with `PG_DSN`, `MONGO_URI`,
  `EMA_RETRIEVER=faiss` (still legacy default), and the upstream-synced
  ANTHROPIC / GITHUB / chainlit secrets.
- **Schema**: `corpus/pg_schema.sql` applied; `documents`, `chunks`, `links`
  with HNSW + GIN. Idempotent re-runs verified.
- **Ingest** (NARR-007/-008/-010/-013): `harness.embed_pg.ingest_source('pdfs'|'html', …)`
  works end-to-end. PDF + HTML normalisers + chunker + BGE-large-en-v1.5
  on CUDA + bulk-upsert to documents + chunks + links. ON CONFLICT
  semantics + `--force` verified.
- **HTML normaliser** (NARR-009): `corpus.ingestion.html_normaliser` —
  trafilatura with `favor_recall=True`, landing pages (<200 chars) return
  None. Skipped pages are logged with their URL in the main ingest loop.
- **Link extractor** (NARR-012): `corpus.ingestion.link_extractor` with
  four extractors (`extract_from_markdown`, `extract_from_html`,
  `extract_reference_numbers`, `extract_see_qa`) + `extract_all` helper.
  21 unit tests, positive + negative.
- **Link ingestion wiring** (NARR-013): `_prepare_pdf` / `_prepare_html`
  attach a `links` field to `_PreparedDoc`; `_upsert_batch` flushes via
  `INSERT_LINK` (ON CONFLICT DO NOTHING). Per-doc dedup by
  `(tgt_url, link_type)` chooses the chunk_id from the first chunk that
  mentions the target.
- **Link resolution** (NARR-014): `scripts/resolve_links.py` fills
  `links.tgt_doc_id` via two UPDATE passes (URL match + reference-number
  match), reports counts + sample unresolved. Idempotent (re-running
  yields 0 updates).
- **Retrieval scaffolding** (NARR-015): `harness/retrieve_pg.py` with
  `RetrievalConfigPG`, `PrefilterConfig`, `TraversalConfig` +
  `from_yaml_section` round-trip. `harness/pg/adapter.py` with
  `to_node_with_score`, `to_nodes_with_scores`, `get_node_by_id`
  (replaces `VectorStoreIndex.docstore.get_node` for the pg path).
  `retrieve_with_config_pg` / `build_retrieve_fn_pg` are
  `NotImplementedError` stubs until NARR-016..018.

Current data in PG after this session's smoke runs:
- `documents`: 25 rows (15 PDF + 10 HTML)
- `chunks`: 446 rows (361 PDF + 85 HTML — counts drift across reruns
  because `--force` rebuilds the same 10-doc slices)
- `links`: 1106 rows (1012 hyperlink + 94 reference_number; 43 resolved
  to tgt_doc_id; 1063 unresolved — most point off-site or to docs not
  yet ingested)

## Next task: NARR-016 — dense retrieval over pgvector

Acceptance criteria recap from `state.json`:

1. `retrieve_dense_pg(query, config)` embeds the query (via the existing
   `Embedder` in `harness/embed_pg.py` or a thin `LlamaIndex` query
   embedder), runs an HNSW kNN search with the `<=>` operator, joins
   `documents` for metadata.
2. Pre-filter clauses (`topic_path LIKE $prefix || '%'`,
   `committee = ANY($committees)`, `last_updated BETWEEN $start AND $end`)
   are composed in the WHERE *before* LIMIT.
3. Returns ordered `list[RetrievalResult]` = `(chunk_id, score, metadata)`
   where `score = 1 - cosine_distance`. Populate `metadata['text']` so the
   adapter can build NodeWithScore without a second SQL round-trip.
4. Target p50 latency ≤ 200 ms for k=10 on the full corpus (verify in
   NARR-011 follow-up).
5. Unit test against a seeded test DB (see NARR-026 for the fixture
   plan) returns expected top-k for a known fixture.

`harness/pg/queries.py::DENSE_KNN` already has the SQL template with
a `{prefilter}` placeholder for the WHERE fragment. Use
`psycopg.sql.SQL.format(... Literal(...) ...)` to compose the prefilter
fragment safely.

After NARR-016, the remaining critical path is:

```
NARR-017 BM25 retrieval (uses Q.BM25)             ─┐
NARR-018 hybrid (RRF) + build_retrieve_fn_pg       │ Phase E
NARR-019 auto traversal (Q.TRAVERSE_LINKS)         │
NARR-020 follow_links FunctionTool                ─┘
NARR-021 EMA_RETRIEVER dispatch in app.py         ─┐
NARR-022 same in run_eval.py + Phoenix attr       ─┤ Phase F
NARR-023 simple_rag E2E smoke                     ─┘
NARR-024 YAML prefilter/traversal exposure
NARR-025 unit tests (chunker, normalisers, link)  ─┐
NARR-026 retrieve_pg integration test              │ Phase H
NARR-027 docs (CLAUDE + RETRIEVAL_PG)              │
NARR-028 flip EMA_RETRIEVER default               ─┘
```

## Re-entry checklist for the next session

```bash
# 1. Make sure the PG container is up
cd ~/github_repos/ema_nlp/deploy/postgres
docker compose ps        # expect ema_nlp_pg running
docker compose up -d     # if it isn't

# 2. Sanity-check the venv (chowned to user this session — see HISTORY)
ls -la .venv | head -3   # should be moritz:moritz

# 3. Continue with NARR-016
/workflow:next
```

The state.json `current_task` is `NARR-016`; `next_available` is
`["NARR-011", "NARR-016", "NARR-017"]` (NARR-011 is timing notes —
documentation only, doesn't unblock anything; NARR-017 BM25 is parallel
to NARR-016 because both depend on NARR-015).

## Gotchas to remember

- **Venv ownership**: `.venv/` was created as root in an earlier session.
  Chowned to `moritz:moritz` in NARR-001..009; still owned correctly.
- **uv vs pip**: This venv has no `pip` installed; use
  `uv pip install --python .venv/bin/python …` for any new deps.
- **trafilatura's `favor_recall=True`** keeps borderline navigation pages
  alive (homepage produced 1.4k chars). If full HTML ingest shows too
  much nav noise, tighten `_MIN_TEXT_CHARS` in `html_normaliser.py` or
  set `favor_recall=False`.
- **Mongo `content_type: 'text/html'`** works as an equality match
  against the 1-element list field — confirmed (22,743 docs).
- **`harness.pg` package**: `conn.get_pool()` is a process-singleton.
  Tests that need a different DSN must call `close_pool()` first or
  inject their own pool.
- **Link extractor pollution**: HTML anchor extraction on the raw HTML
  contributes most of the link rows (997 of 1012 in the 10-doc smoke).
  That includes navigation chrome (medicines/, committees/, etc.). The
  `topic_path_prefix` prefilter in `PrefilterConfig` is the right knob
  to suppress them at retrieval time once dense/BM25 are wired up.
- **`see_qa` link_type` excluded from default traversal**: the
  `TraversalConfig` default `link_types = ['hyperlink', 'reference_number']`
  intentionally excludes `see_qa` to avoid Q&A leakage into eval (per
  `exploration.md`).

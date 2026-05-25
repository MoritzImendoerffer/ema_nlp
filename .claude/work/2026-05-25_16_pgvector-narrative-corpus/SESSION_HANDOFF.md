# Session handoff — NARR-001..020 complete, NARR-021 next

Phase A (PG bring-up), Phase B (PDF ingest), Phase C (HTML ingest),
Phase D (link graph), and **Phase E (retrieval)** are now all green.
What remains is wiring (Phase F), exposing prefilter/traversal in YAML
(Phase G), and tests / docs / cutover (Phase H).

## What's in place

### Phase A / B / C / D — ingest + link graph

- **Postgres**: `pgvector/pgvector:pg16` container `ema_nlp_pg` (compose
  in `deploy/postgres/`). pgvector 0.8.2; HNSW + GIN indexes built.
- **Schema** (`corpus/pg_schema.sql`): `documents`, `chunks`, `links`,
  idempotent re-runs.
- **Ingest** (`harness.embed_pg.ingest_source`): PDFs + HTML, chunker,
  BGE-large-en-v1.5 on CUDA, bulk-upsert. Resume + `--force` verified.
- **HTML normaliser** (`corpus.ingestion.html_normaliser`): trafilatura
  with `favor_recall=True`; <200 chars treated as landing.
- **Link extractor** (`corpus.ingestion.link_extractor`): markdown
  `[text](url)`, HTML `<a href>`, EMA reference codes, see-Q&A.
- **Link ingestion**: per-chunk for text-based extractors + per-doc for
  HTML anchors; ON CONFLICT (src_doc_id, tgt_url, link_type) DO NOTHING.
- **Link resolution** (`scripts/resolve_links.py`): two UPDATE passes,
  idempotent, reports per-link-type resolution rate + sample unresolved.

### Phase E — retrieval

- **`harness/retrieve_pg.py`** — full surface:
  - `RetrievalConfigPG` / `PrefilterConfig` / `TraversalConfig` + YAML
    round-trip
  - `retrieve_dense_pg(query, config)` — HNSW kNN via `<=>` (with
    explicit `::vector` cast on the query parameter, since `register_vector`
    only auto-adapts numpy arrays — Python lists need the cast). Score
    = 1 - cosine_distance.
  - `retrieve_bm25_pg(query, config)` — `ts_rank_cd(plainto_tsquery(...))`
    over the generated `text_tsv` column.
  - `retrieve_hybrid_pg(query, config)` — sequential dense + BM25, then
    RRF fusion with K=60 (matches `harness.retrieve._rrf_fuse`).
  - `retrieve_with_config_pg(config, query)` — dispatches on `config.mode`
    and applies auto-traversal when `config.traversal.mode == "auto"`.
  - `build_retrieve_fn_pg(config)` — returns a drop-in callable for the
    workflow layer (parity with `harness.retrieve.build_retrieve_fn`).
  - `_expand_via_links(initial, traversal)` — runs `Q.TRAVERSE_LINKS` to
    add one representative chunk per neighbour doc; seeds stay at the
    front; expansion appended with `score=0.0`.
- **`harness/pg/adapter.py`** — bridges pg rows ↔ LlamaIndex:
  - `row_to_result(cols, row)` — used by every retriever to materialise
    a `RetrievalResult` tuple from a `DENSE_KNN`/`BM25`/`TRAVERSE_LINKS`
    row. ISO-encodes `last_updated`. Carries `text` in metadata so the
    adapter can build a NodeWithScore later without a second SQL call.
  - `to_node_with_score`, `to_nodes_with_scores` — RetrievalResult →
    LlamaIndex NodeWithScore.
  - `get_node_by_id(chunk_id)` — replaces `VectorStoreIndex.docstore.get_node`
    on the pg path.
- **`harness/pg/tools.py`** — `follow_links(chunk_id, link_types?, k=5)`
  callable + `follow_links_tool` FunctionTool. Returns one-hop neighbours
  for ReAct workflows when `TraversalConfig.mode == 'agent_tool'`.

### Verified behaviour on the live 25-doc seed

- Dense top-3 for "CHMP variation type II review" returned cosine 0.63–0.67
- BM25 returns hits for keyword queries (`Tryngolza`: 0.8/0.4/0.4)
- Hybrid: top-3 with RRF scores ~0.016 — same docs as dense for this seed
- Auto-traversal (`max_hops=1`): 2 seed chunks → 7 returned (2 seeds +
  5 expanded via legal-notice's outgoing hyperlinks)
- `max_hops=0`: no expansion (n=k confirmed)
- `_rrf_fuse(...)` overlap test: doc appearing in both lists ranks first
- `follow_links("")` and `follow_links("unknown-id")` return `[]`

### Current data state in PG

- `documents`: 25 rows (15 PDF + 10 HTML)
- `chunks`: 446 rows
- `links`: 1106 rows (1012 hyperlink + 94 reference_number; 43 resolved
  to `tgt_doc_id`)

## Next task: NARR-021 — Env-var dispatch in app.py

Per `state.json`, `current_task = "NARR-021"`. The remaining critical
path is short:

```
NARR-021  EMA_RETRIEVER dispatch in app.py        ─┐
NARR-022  same in run_eval.py + Phoenix attr      ─┤ Phase F
NARR-023  simple_rag E2E smoke (5 questions)      ─┘
NARR-024  YAML prefilter/traversal exposure         (Phase G)
NARR-025  unit test suite — chunker/normalisers/  ─┐
          link_extractor                            │
NARR-026  retrieve_pg integration test              │ Phase H
NARR-027  docs (CLAUDE.md + RETRIEVAL_PG.md)        │
NARR-028  flip EMA_RETRIEVER default to pgvector  ─┘
```

`NARR-021` acceptance criteria (from `state.json`):

1. `EMA_RETRIEVER` env var (default 'faiss') switches between
   `harness.retrieve.build_retrieve_fn` and
   `harness.retrieve_pg.build_retrieve_fn_pg`.
2. When `'pgvector'`: skip `build_index` (no FAISS load), still satisfy
   the workflow signature via the adapter.
3. `EMA_RETRIEVER=faiss chainlit run app.py` works exactly as before
   (back-compat check).
4. `EMA_RETRIEVER=pgvector chainlit run app.py` loads without index
   files and answers a sample question end-to-end.

`build_retrieve_fn_pg` already returns a drop-in callable matching
`harness.retrieve.build_retrieve_fn`'s signature (`fn(query) -> list[RetrievalResult]`).
Workflows in `harness/workflows/` only see the callable, so the dispatch
should be a small change at the top of `app.py` plus a noop-index path.

NARR-011 (timing notes) is still off-path; can land any time after
NARR-021..023 confirm the full-corpus ingest is sized correctly.

## Re-entry checklist

```bash
# 1. PG container up
cd ~/github_repos/ema_nlp/deploy/postgres && docker compose ps

# 2. Silence HF Hub metadata noise (optional but tidy)
export HF_HUB_OFFLINE=1

# 3. Continue with NARR-021
/workflow:next
```

## Gotchas to remember

- **Query vector cast**: pgvector's `register_vector` only auto-adapts
  numpy arrays; Python lists go as `double precision[]` and break
  `<=>`. Fix is in `Q.DENSE_KNN`: every `%(qvec)s` is followed by
  `::vector`. Keep that cast when adding new vector-distance queries.
- **`Settings.embed_model` lazy load**: reading the attribute when
  unset triggers LlamaIndex's default OpenAI resolver, which fails when
  `llama-index-embeddings-openai` isn't installed. `_query_embedding`
  uses a module-level `_embed_configured` flag and calls
  `configure_embed_model()` once before touching `Settings.embed_model`.
- **BGE runs local on the 3090** — HF Hub warnings at startup are
  metadata-only (model is cached). `HF_HUB_OFFLINE=1` silences them.
  Inference does not hit any API.
- **`follow_links` returns `[]` for empty / unknown chunk_id** — the
  ReAct agent occasionally hallucinates ids; don't make this fatal.
- **`see_qa` link_type excluded from default traversal** — both
  `TraversalConfig.link_types` default and `follow_links`'s default
  list `['hyperlink', 'reference_number']`. Intentional, per
  `exploration.md`: see-Q&A links reference benchmark Q&As and could
  leak gold answers into eval.
- **Venv ownership**: chowned `.venv/` to `moritz:moritz` early in
  NARR-001..009; re-chown if `pip install` ever errors permission denied.
- **`harness.pg` package** uses a process-singleton pool. Tests with a
  different DSN must `close_pool()` first or inject their own pool.

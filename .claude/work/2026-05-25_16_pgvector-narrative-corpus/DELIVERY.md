# Delivery — pgvector narrative corpus (NARR-001..028)

**Work unit:** `2026-05-25_16_pgvector-narrative-corpus`
**Span:** 2026-05-25 (planning) → 2026-05-26 (cutover)
**Status:** **complete**, 28/28 tasks. `EMA_RETRIEVER=pgvector` is the production default since commit `e36d6fd` (NARR-028).
**Tracking docs (kept for history):** `requirements.md`, `exploration.md`, `decisions.md`, `implementation-plan.md`, `state.json`, `SESSION_HANDOFF.md`, `timing_notes.md`.

This is the post-ship summary. For the operator's guide (provisioning, env vars, ingest CLI, retrieval modes, sub-corpus filters, test DB setup, troubleshooting), see [`docs/RETRIEVAL_PG.md`](../../../docs/RETRIEVAL_PG.md). For decision rationale, see the new "Postgres + pgvector as the narrative-corpus retrieval backend" entry in [`DECISIONS.md`](../../../DECISIONS.md). For roadmap context, see Phase 1.7 in [`project_roadmap/ROADMAP.md`](../../../project_roadmap/ROADMAP.md).

---

## What shipped

A second retrieval target was built alongside the original Q&A corpus: the **full PDF + HTML body text**, ingested into Postgres 16 + pgvector with HNSW (dense) and BM25 (`tsvector` + GIN). Workflows are backend-agnostic; the switch is one env var.

### Architecture at a glance

```
MongoDB ──┬─ ema_scraper.parsed_pdfs (65k docs, markdown)
          └─ ema_scraper.web_items   (115k docs, html_raw)
                       │
                       ▼
     harness.embed_pg.ingest_source
       ├─ normalise (pymupdf4llm md / trafilatura)
       ├─ chunk via LlamaIndex (configurable parser + size/overlap)
       ├─ BGE-large-en-v1.5 on local CUDA (3090)
       ├─ bulk upsert chunks + extracted links
       └─ resolve_links.py: tgt_url → tgt_doc_id passes
                       │
                       ▼
     Postgres `ema_nlp`  (deploy/postgres/, pgvector/pgvector:pg16)
       ├─ documents  (one row per source URL; committee, topic_path, last_updated)
       ├─ chunks     (vector(1024) HNSW + generated text_tsv GIN BM25)
       └─ links      (link_type ∈ {hyperlink, reference_number, see_qa})
                       │
                       ▼
     harness.retrieve_pg
       ├─ retrieve_dense_pg          (HNSW kNN via <=>, ::vector cast)
       ├─ retrieve_bm25_pg           (ts_rank_cd over text_tsv)
       ├─ retrieve_hybrid_pg         (dense + BM25 → RRF, K=60)
       ├─ retrieve_with_config_pg    (dispatcher + auto-traversal via recursive CTE)
       ├─ build_retrieve_fn_pg       (drop-in callable for workflow layer)
       └─ follow_links_tool          (FunctionTool for ReAct agent_tool mode)
                       │
                       ▼
     app.py / harness.run_eval.py    (EMA_RETRIEVER dispatch, ema.retrieval.backend span attr)
```

### What it replaces, what it doesn't

| Layer | Before | After |
|-------|--------|-------|
| Runtime retrieval target | FAISS over `corpus.jsonl` (~26k curated Q&A pairs) | Postgres `chunks` table — full narrative prose with HNSW+BM25 |
| `corpus.jsonl` | Runtime + benchmark | **Benchmark-only.** Not consumed by `app.py` / `run_eval.py` under the default. |
| `EMA_RETRIEVER` default | implicit FAISS | `pgvector` (NARR-028) |
| Query cache (`harness/index/query_cache.faiss`) | FAISS | **Unchanged.** It indexes past query embeddings for similar-question surfacing — not a document store. |
| Cross-ref expansion | `_retrieve_recursive` over `corpus.jsonl[cross_refs]` | Recursive CTE over `links` table (`hyperlink` + `reference_number`; `see_qa` excluded by default to avoid benchmark leakage) |
| Reranker / query-expansion (A1/A3) | Outside the retriever, backend-agnostic | Same — `build_retrieve_fn_pg` carries `.ablation_config` like `build_retrieve_fn` |

---

## Phase-by-phase build

| Phase | Tasks | Outcome |
|-------|-------|---------|
| A — Postgres bring-up | NARR-001..003 | Docker-Compose pgvector container; idempotent `pg_schema.sql` + `scripts/init_db.py`; psycopg pool + vector type registration |
| B — PDF ingest | NARR-004..008 | Configurable LlamaIndex chunker; PDF normaliser; BGE wrapper; ingest pipeline; resume + `--force` semantics verified |
| C — HTML ingest | NARR-009..011 | trafilatura normaliser with landing-page guard (<200 chars); HTML source wired into ingest; full timing + scaling extrapolation on the 3090 |
| D — Link graph | NARR-012..014 | Link extractor (markdown / HTML / EMA reference codes / see-Q&A); per-chunk and per-doc link ingestion; `resolve_links.py` two-pass UPDATE |
| E — Retrieval | NARR-015..020 | `RetrievalConfigPG` / `PrefilterConfig` / `TraversalConfig`; dense + BM25 + hybrid; auto-traversal recursive CTE; `follow_links` agent tool |
| F — Wiring | NARR-021..023 | `EMA_RETRIEVER` env-var dispatch in `app.py` + `run_eval.py`; `ema.retrieval.backend` span attribute; simple_rag E2E smoke on 5 questions |
| G — Filters | NARR-024 | YAML exposure of prefilter + traversal; reference config `example_chmp_only.yaml`; live-verified committee filter |
| H — Tests / docs / cutover | NARR-025..028 | Unit suite (chunker + normalisers + link extractor, 91% coverage); integration suite against `ema_nlp_test` DB; `docs/RETRIEVAL_PG.md`; default flip |

---

## Metrics

### Ingest throughput (NARR-011, marvin-gpu RTX 3090)

| Source | `--limit 100` wall | Throughput | Chunks/doc | Notes |
|--------|--------------------|------------|------------|-------|
| PDF (parsed markdown) | 28.94 s | 207 docs/min, 2,116 chunks/min | ~10.2 | Embed-bound; ~5–15 docs/sec steady-state |
| HTML (trafilatura) | 19.27 s | 311 docs/min, 706 chunks/min | ~2.3 | trafilatura strips boilerplate aggressively |

GPU sat at ~1.8–1.9 GiB / 24 GiB; batch size could grow to 64/128 without OOM. Embed is the dominant cost; chunking is ~1 ms/chunk, PG insert is sub-ms per row even with HNSW attached.

### Full-corpus extrapolation

| Source | Docs in MongoDB | Est. wall on 3090 |
|--------|-----------------|-------------------|
| PDFs (clean parses) | 38,948 | ≈ 3.1 h |
| HTML | ~60,000 content pages | ≈ 3.2 h |
| **Serial total** | | **≈ 6 h** |

DB footprint at full ingest (linear extrapolation from the 1,559-chunk baseline): ~540k chunks, **~14–18 GB** total. Comfortable on the host's nvme0n1p2 (986 GiB free).

### Test coverage

| Suite | Tests | Coverage / scope |
|-------|-------|------------------|
| Unit — `corpus.ingestion` | 53 (chunker / pdf_normaliser / html_normaliser / link_extractor) | 91% on the four ingestion modules; 4 s wall |
| Integration — `tests/test_retrieve_pg.py` | 9 | Against dedicated `ema_nlp_test` PG DB; deterministic seeded embeddings (no BGE load); covers seeded counts, dense self-recall, BM25 keyword hit, hybrid RRF, prefilter (committee + date_range), auto-traversal, max_hops=0, dispatcher routing |
| Pure-Python — `tests/test_retrieve_pg_pure.py` + `test_retrieve_pg_config.py` | 14 + several | Adapter rows, RRF fusion, YAML round-trip, traversal post-processing |
| Span attributes — `tests/test_span_attributes.py` | live OTel SDK + in-memory exporter | Verifies `ema.retrieval.backend` reaches Phoenix |
| **Full suite under new default** | **253 green** | (last reported in NARR-028) |

### E2E confirmation (NARR-023)

5-question slice of `simple_rag` on pgvector:
- 5/5 returned non-empty answers
- **46/50 retrieved chunks came from URLs outside `corpus.jsonl`** → narrative coverage confirmed; the agent is genuinely reading the full document body, not the curated Q&A extract

Also caught and fixed a latent bug: `WorkflowRunner._stamp_span` was stamping into a no-op span (zero `ema.*` attributes reaching Phoenix in practice). `ainvoke()` now opens its own `tracer.start_as_current_span` wrapper. Live Phoenix now shows all `ema.orchestration / retrieval / run` attributes per invocation, including `ema.retrieval.backend`.

---

## Switch contract

```bash
# default since NARR-028
EMA_RETRIEVER=pgvector chainlit run app.py
python -m harness.run_eval --config harness/configs/example_chmp_only.yaml

# legacy opt-out, retained for parity smoke tests
EMA_RETRIEVER=faiss     chainlit run app.py
```

Both paths build a `retrieve_fn(query) -> list[RetrievalResult]` and pass it to the same workflow layer. Phoenix spans tag each invocation with `ema.retrieval.backend = 'pgvector'|'faiss'`.

---

## Gotchas worth remembering

These are the non-obvious traps surfaced during the build; cross-linked here so they don't get lost in commit messages.

- **pgvector query-vector cast.** `register_vector` only auto-adapts numpy arrays; Python lists go as `double precision[]` and break `<=>`. Every `%(qvec)s` in `Q.DENSE_KNN` is followed by `::vector`. Keep that cast on any new vector-distance query.
- **`Settings.embed_model` lazy load.** Reading the attribute when unset triggers LlamaIndex's default OpenAI resolver, which fails without `llama-index-embeddings-openai`. `_query_embedding` uses a module-level `_embed_configured` flag and calls `configure_embed_model()` once.
- **HF Hub warnings are metadata-only.** BGE runs locally on the 3090; the model is cached. `HF_HUB_OFFLINE=1` silences the metadata noise without breaking inference.
- **`follow_links` returns `[]` for unknown / empty chunk_id.** ReAct agents occasionally hallucinate ids; don't make this fatal.
- **`see_qa` excluded from default traversal.** Both `TraversalConfig.link_types` and `follow_links`'s default list `["hyperlink", "reference_number"]`. Intentional — see-Q&A links point at benchmark Q&As and could leak gold answers into eval.
- **`harness.pg` package uses a process-singleton pool.** Tests with a different DSN must `close_pool()` first or inject their own pool. The integration suite does this and skips clean when `PG_DSN_TEST` is unset.

---

## Follow-ups (out of scope for this work unit)

- **Full-corpus ingest run.** The pipeline is verified on the 100-doc slice and extrapolation is sound; the actual 6-hour `--limit none` PDF + HTML ingest happens when the host is free.
- **Quantised BGE (int8).** ~2× embed throughput on the 3090 at a small recall cost; only relevant if re-embed cadence becomes a problem.
- **Hierarchical retrieval (`strategy="hierarchical"`).** Currently FAISS-only by design (`build_retrieve_fn_pg` raises if requested). Port if the hierarchical ablation needs the narrative surface.
- **Phase 2 benchmark.** Continues to read `corpus.jsonl` as ground truth; no schema break.

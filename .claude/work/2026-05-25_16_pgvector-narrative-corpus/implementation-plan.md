# Implementation Plan — pgvector narrative corpus

## Project overview

Pivot retrieval from the 26k Q&A pairs in `corpus/corpus.jsonl` to a
chunked-and-embedded **full EMA narrative corpus** (parsed PDFs +
HTML pages) stored in **PostgreSQL + pgvector**, with a relational
`links` table for cross-document traversal. The Q&A pairs become a
benchmark-only artifact; source documents are not scrubbed (leakage
handled at the metric level per `LEAKAGE.md`).

See `requirements.md` for locked design decisions and
`exploration.md` for the target architecture, schema, and module
layout. This plan turns the eight phase groups (A–H) into 28 ordered,
testable tasks averaging ~2.5 h each.

## Scope

**In scope**
- Postgres + pgvector bring-up (local install or Docker)
- Schema (`documents`, `chunks`, `links`) with HNSW + GIN indexes
- Configurable LlamaIndex chunker (markdown / sentence / hierarchical)
- PDF ingest from `parsed_pdfs` MongoDB collection
- HTML ingest from `web_items` via trafilatura
- BGE-large-en-v1.5 embedding on the user's NVIDIA 3090
- Link extraction (markdown, HTML, EMA reference numbers, see-Q&A)
- Reference-number → URL resolution pass
- Retrieval module (`harness/retrieve_pg.py`) — dense, BM25 via
  tsvector, hybrid RRF, prefilters, auto-traversal, agent tool
- Env-var dispatch between FAISS (legacy) and pgvector (new default)
- Phoenix tracing preserved with a `backend` attribute
- Tests, docs, CLAUDE.md scope update, cutover to pgvector default

**Out of scope**
- Multilingual embedding
- IDMP / SPOR / Neo4j graph infrastructure (still v2+)
- Migrating the benchmark / judge / lift-metric machinery
- Changing the workflow public API (`retrieve_fn` signature stays)

## Technical architecture

### Schema (Postgres + pgvector)

Three tables, defined in `corpus/pg_schema.sql`:

- `documents(doc_id, source_url, source_type, title, topic_path,
   reference_number, committee, revision, last_updated, raw_byte_size,
   ingested_at, meta)` — one row per source URL
- `chunks(chunk_id, doc_id, chunk_index, text, heading_path,
   token_count, embedding vector(1024), text_tsv tsvector …)` — HNSW
   on embedding, GIN on text_tsv
- `links(src_doc_id, tgt_url, tgt_doc_id, link_type, anchor,
   chunk_id)` — edges between documents

### Module layout

```
config.py                     +PG_DSN, +EMA_RETRIEVER
pyproject.toml                +psycopg[binary], +psycopg_pool, +pgvector, +trafilatura

corpus/pg_schema.sql          DDL applied by scripts/init_db.py
corpus/ingestion/
  chunker.py                  ChunkConfig + LlamaIndex-backed chunkers
  pdf_normaliser.py           parsed_pdfs → DocumentInput
  html_normaliser.py          web_items → DocumentInput (trafilatura)
  link_extractor.py           markdown/html/reference-number extractors

harness/embed_pg.py           Embedder + ingest_source CLI entry
harness/retrieve_pg.py        RetrievalConfigPG + dense / bm25 / hybrid / traversal
harness/pg/
  conn.py                     psycopg_pool + pgvector type registration
  queries.py                  parameterised SQL constants
  adapter.py                  RetrievalResult → LlamaIndex NodeWithScore
  tools.py                    follow_links FunctionTool

scripts/init_db.py            apply DDL idempotently
scripts/resolve_links.py      fill links.tgt_doc_id post-ingest

deploy/postgres/              docker-compose.yml + README (optional install path)

tests/test_chunker.py
tests/test_pdf_normaliser.py
tests/test_html_normaliser.py
tests/test_link_extractor.py
tests/test_retrieve_pg.py     uses PG_DSN_TEST and a tiny fixture corpus

docs/RETRIEVAL_PG.md          setup + schema + config reference + troubleshooting
```

### Untouched (back-compat)

- `corpus/corpus.jsonl` and everything that builds it
- `harness/embed.py` (FAISS path) and `harness/retrieve.py` (FAISS path)
- All `harness/workflows/*.py` — they only see `retrieve_fn`
- `harness/judge.py`, the run_eval orchestration logic, Phoenix wiring

## Task execution plan

Tasks are grouped into 8 phases (A–H). Each task ID is `NARR-NNN`
(narrative corpus); statuses and acceptance criteria live in
`state.json`. Run `/next` to claim the next available task.

### Phase A — Postgres bring-up (foundation)
| ID | Title | h |
|----|-------|---|
| NARR-001 | Provision Postgres 16 + pgvector locally | 2 |
| NARR-002 | Schema DDL + idempotent init script | 3 |
| NARR-003 | Python deps + connection pool + pgvector type registration | 2 |

### Phase B — PDF ingest (feature + integration)
| ID | Title | h |
|----|-------|---|
| NARR-004 | Configurable LlamaIndex-backed chunker | 3 |
| NARR-005 | PDF document normaliser + metadata extraction | 3 |
| NARR-006 | BGE embedder wrapper (LlamaIndex on CUDA) | 3 |
| NARR-007 | Ingest pipeline: PDFs → chunks → embeddings → upsert | 4 |
| NARR-008 | Resume + dedup verification + --force semantics | 2 |

### Phase C — HTML ingest (feature + integration)
| ID | Title | h |
|----|-------|---|
| NARR-009 | HTML normaliser via trafilatura | 3 |
| NARR-010 | Extend ingest pipeline to HTML source | 3 |
| NARR-011 | Timing + scaling notes | 2 |

### Phase D — Link graph (feature + integration)
| ID | Title | h |
|----|-------|---|
| NARR-012 | Link extractor module | 3 |
| NARR-013 | Wire link extraction into ingest | 2 |
| NARR-014 | Reference-number → URL resolution pass | 3 |

### Phase E — Retrieval (feature)
| ID | Title | h |
|----|-------|---|
| NARR-015 | RetrievalConfigPG + LlamaIndex adapter scaffolding | 2 |
| NARR-016 | Dense retrieval over pgvector | 3 |
| NARR-017 | BM25 retrieval via Postgres tsvector | 2 |
| NARR-018 | Hybrid (RRF) + dispatcher + build_retrieve_fn_pg | 3 |
| NARR-019 | Auto-traversal (recursive CTE over links) | 3 |
| NARR-020 | follow_links agent tool for ReAct workflows | 2 |

### Phase F — Wiring (integration)
| ID | Title | h |
|----|-------|---|
| NARR-021 | Env-var dispatch in app.py | 2 |
| NARR-022 | Env-var dispatch in run_eval.py + Phoenix backend attribute | 2 |
| NARR-023 | End-to-end smoke test: simple_rag on pgvector | 2 |

### Phase G — Sub-corpus filters (feature)
| ID | Title | h |
|----|-------|---|
| NARR-024 | Expose prefilter + traversal in YAML configs | 2 |

### Phase H — Tests, docs, cutover (testing + documentation + integration)
| ID | Title | h |
|----|-------|---|
| NARR-025 | Unit test suite — chunker, normalisers, link extractor | 3 |
| NARR-026 | Integration test — retrieve_pg end-to-end | 4 |
| NARR-027 | Documentation — CLAUDE.md + RETRIEVAL_PG.md | 2 |
| NARR-028 | Switch default EMA_RETRIEVER to pgvector | 1 |

### Totals

- **28 tasks**, **~71 hours** estimated effort
- **Critical path** (21 tasks): NARR-001 → -003 → -004 → -005 → -006 →
  -007 → -009 → -010 → -012 → -013 → -015 → -016 → -017 → -018 →
  -021 → -022 → -023 → -026 → -027 → -028
- **Off-path parallelisable**: NARR-008 (resume verification),
  NARR-011 (timing), NARR-014 (link resolution), NARR-019/-020
  (traversal modes), NARR-024 (filter exposure), NARR-025 (unit tests
  — can be written incrementally per module)

### Dependency graph (high-level)

```
A: NARR-001 → NARR-002 → NARR-003
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
B: NARR-004 ──┐        NARR-005           NARR-006
        ▲     ├── NARR-007 ── NARR-008
        │     ▼
C: NARR-009 ── NARR-010 ── NARR-011
                  │
                  ├──> D: NARR-012 ── NARR-013 ── NARR-014
                  │
                  └──> E: NARR-015 ── NARR-016 ── NARR-017
                                          │           │
                                          └─NARR-018──┘
                                              │
                                              ├── NARR-019 ── NARR-020
                                              │
                              F: NARR-021 ── NARR-022 ── NARR-023
                                                              │
                                                  G: NARR-024 │
                                                              │
                              H: NARR-025  NARR-026 ── NARR-027 ── NARR-028
```

## Quality assurance strategy

### Test layers

1. **Unit tests** (NARR-025) — chunker, normalisers, link extractor.
   Pure functions or thin wrappers; no DB dependency. Coverage ≥ 80%
   on these four modules.
2. **Integration tests** (NARR-026) — `harness/retrieve_pg.py` end-to-end
   against a `PG_DSN_TEST` database seeded with ~10 fixture chunks
   across 3 documents and 2 links. Covers dense, BM25, hybrid,
   prefilter, traversal.
3. **Smoke tests** (NARR-007, NARR-010, NARR-023) — limit-10 ingest
   runs + a 5-question Simple-RAG run. Verify happy path on real data.
4. **Resume / idempotency tests** (NARR-008) — verify
   `ON CONFLICT DO NOTHING` and `--force` behaviour.

### Phoenix observability

Every workflow continues to emit the existing `ema.retrieval.*` span
attributes. NARR-022 adds `ema.retrieval.backend ∈ {faiss, pgvector}`
so retrieval-mode ablations and the eventual cutover are visible in
traces.

### Back-compat gate

NARR-021/-022/-023 land the new path *behind* `EMA_RETRIEVER=pgvector`.
The FAISS path remains the default until NARR-026 + NARR-027 are
green. Only then does NARR-028 flip the default.

### Risk-driven checkpoints

- After NARR-008: confirm idempotency before scaling beyond limit-10.
- After NARR-011: confirm GPU throughput supports a full embedding
  pass in a reasonable wall-clock (target a few hours).
- After NARR-023: confirm retrieval surfaces non-Q&A narrative content
  (the whole point of the pivot).
- After NARR-026: gate the default switch on a green test DB run.

## Open assumptions to validate during implementation

- **Postgres install path** — apt vs. Docker. NARR-001 picks one;
  document both in `deploy/postgres/README.md` so contributors can
  choose.
- **trafilatura coverage on EMA HTML** — may need a fallback parser
  for legacy pages. Track in NARR-009 acceptance.
- **Reference-number resolution rate** — informally ≥ 30% expected;
  NARR-014 reports the actual number.
- **HNSW parameters** (`m=16, ef_construction=64`) — chosen as
  pgvector defaults; tunable after NARR-026 if recall is poor.
- **Q&A leakage magnitude** — out of scope here; lift-metric story in
  `LEAKAGE.md` is the answer. Spot-check during NARR-023.

## Next step

Run **`/next`** to claim NARR-001. The Postgres bring-up is the
foundation; everything downstream is blocked on it.

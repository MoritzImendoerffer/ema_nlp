# Requirements — pivot retrieval from Q&A pairs to full EMA narrative

## Motivation

The original intent was to retrieve over the **full EMA corpus** (regular
web pages + PDFs) and reserve the extracted Q&A pairs for *evaluation*
of the agentic RAG system. The current pipeline does the opposite — it
indexes only the 26k Q&A pairs and never sees the narrative content.
This work unit corrects that.

## User-confirmed decisions (2026-05-25)

1. **Vector store: PostgreSQL + pgvector** (not FAISS, not MongoDB Atlas).
   Local Mongo 7.0 Community has no `$vectorSearch`. pgvector gives ANN
   + SQL filter pushdown + relational `links` table for graph traversal
   in one engine.
2. **Content scope: PDFs AND HTML.** ~38,729 cleanly-parsed PDFs in
   `ema_scraper.parsed_pdfs` and ~22,743 HTML pages in
   `ema_scraper.web_items`. Hyperlinks between pages and EMA reference
   numbers must be extracted into a link table so retrieval can
   pre-filter by sub-corpus and (optionally) traverse along links.
3. **Q&A pairs: keep `corpus/corpus.jsonl` as a benchmark-only artifact.**
   Source documents are *not* scrubbed of Q&A text. Q&A leakage is
   acknowledged and handled at the metric level (lift = open-book minus
   closed-book, per `project_roadmap/LEAKAGE.md`).
4. **Embedding model: BGE-large-en-v1.5 (unchanged).** 1024-dim. Run on
   the user's NVIDIA 3090 PC for the bulk embedding pass.

## Functional requirements

- **FR-1** Build a chunked-document corpus from MongoDB `parsed_pdfs`
  (markdown) and `web_items` (HTML → text), excluding Q&A pairs as a
  *record type* (we do not insert `corpus.jsonl` rows; the underlying
  PDFs/HTML are still indexed in their entirety).
- **FR-2** Embed chunks with BGE-large-en-v1.5 in batches on GPU and
  store vectors in pgvector with an HNSW index.
- **FR-3** Extract inter-document links (HTML `<a href>`, markdown
  `[text](url)`, EMA reference numbers like `EMA/CHMP/508188/2013`) into
  a relational `links` table.
- **FR-4** Provide a new retriever `harness/retrieve_pg.py` that:
  - returns the same `list[(qa_id_or_chunk_id, score, metadata)]` shape
    used by `harness/retrieve.py`, so workflows in `harness/workflows/`
    keep working;
  - supports `mode="dense"`, `mode="bm25"` (Postgres `tsvector`),
    `mode="hybrid"` (RRF fusion in Python);
  - supports pre-filters on metadata (`topic_path`, `source_type`,
    `reference_number`, date range);
  - supports link-traversal expansion analogous to the current recursive
    cross_refs hop.
- **FR-5** Plug into existing workflows (`simple_rag`, `crag`, `react`,
  `crag_review`, etc.) without changing their public API. Workflows
  currently consume `retrieve_fn(query) -> list[RetrievalResult]`;
  that interface must be preserved.
- **FR-6** Keep the existing FAISS / `corpus.jsonl` path available
  behind a config flag for back-compat and ablation.

## Non-functional requirements

- **NFR-1** Embedding pass must be re-runnable and resumable
  (deterministic chunk IDs; skip already-embedded chunks).
- **NFR-2** Total embedding wall time on a 3090 ≤ a few hours
  (~38k PDFs × ~10–20 chunks + HTML).
- **NFR-3** Query latency at p50 ≤ 200 ms for k=10 over the full
  pgvector index (HNSW).
- **NFR-4** No credentials or DSNs committed to the repo; everything in
  `~/.myenvs/ema_nlp.env`.
- **NFR-5** Workflows still emit Phoenix spans with the same attributes
  (`ema.retrieval.strategy`, `ema.retrieval.mode`, `ema.retrieval.k`).

## Acceptance criteria

- [ ] `documents`, `chunks`, `links` tables exist in Postgres with the
  schema defined in `exploration.md` §Schema.
- [ ] `python -m harness.embed_pg --source pdfs` and
  `python -m harness.embed_pg --source html` ingest, chunk, embed, and
  upsert into pgvector without errors over the full datasets.
- [ ] `corpus.jsonl` records are *not* present in `chunks` (verified via
  a unit test that asserts no chunk has `source_record_type='qa'`).
- [ ] `tests/test_retrieve_pg.py` shows hybrid retrieval returns
  sensible top-k for a fixed seed query against a small fixture corpus.
- [ ] Chainlit app (`app.py`) running with
  `EMA_RETRIEVER=pgvector chainlit run app.py` answers a benchmark
  question using narrative chunks (not Q&A records).
- [ ] At least one workflow (`simple_rag`) runs end-to-end against the
  new retriever and emits a Phoenix trace.
- [ ] FAISS path still works when `EMA_RETRIEVER=faiss` (back-compat).
- [ ] `benchmark.jsonl` construction (Phase 2) can still read
  `corpus.jsonl` as ground truth (no schema break).

## Locked decisions (user-confirmed 2026-05-25)

1. **Chunking.** Performed by **LlamaIndex** node parsers, **configurable**
   via a `ChunkConfig` object (parser + max_tokens + overlap).
   Initial setting: heading-aware
   (`MarkdownNodeParser` for PDF markdown; `trafilatura → markdown →
   MarkdownNodeParser` for HTML), with `SentenceSplitter` as fallback
   when sections exceed `max_tokens` (default 512, overlap 64).
   Easy to swap parser via config without touching ingest code.
2. **HTML normalization.** Use **trafilatura** to extract main content
   to markdown; strip nav/footer/cookie banners; drop pages whose
   extracted text is below a min-length threshold (landing-page guard).
3. **Link semantics.** **Both, configurable.** `TraversalConfig` field
   on `RetrievalConfigPG`:
   - `mode: "none" | "auto" | "agent_tool"` (default `"none"`)
   - `max_hops: int` (default 1, used when mode=`"auto"`)
   - `link_types: list[str]` (whitelist; default
     `["hyperlink", "reference_number"]`, omit `see_qa` by default to
     avoid leakage)
   `"auto"` extends `recursive` strategy semantics to the `links`
   table; `"agent_tool"` exposes a `follow_links(chunk_id)` tool to
   ReAct agents.
4. **BM25 source.** **Postgres `tsvector`** generated column on
   `chunks.text`; ranked with `ts_rank_cd`. Hybrid mode fuses dense
   ANN + tsvector via RRF in Python (same constant K=60 as
   `harness/retrieve.py`). Revisit if benchmark recall is poor.
5. **Sub-corpus pre-filters.** Three filter dimensions on
   `RetrievalConfigPG.prefilter`:
   - `topic_path_prefix: str | None`
   - `committee: list[str] | None` (parsed from `reference_number`,
     e.g. `["CHMP", "PRAC"]`)
   - `date_range: tuple[date, date] | None` (against
     `documents.last_updated`)
   Applied as a `WHERE` clause joined to `documents` before ANN scan.
6. **Reference-number → URL resolution.** Separate pass after both
   ingest phases complete: `scripts/resolve_links.py` updates
   `links.tgt_doc_id` where `tgt_url` matches a `documents.reference_number`.
7. **Re-embed cadence.** **Incremental.**
   `chunk_id = sha256(doc_id || chunk_index || normalised_text)`.
   Ingest uses `INSERT … ON CONFLICT (chunk_id) DO NOTHING`, so re-runs
   only embed new/changed chunks. A `--force` flag re-embeds everything.

## Risk register

| Risk | Mitigation |
|------|------------|
| HTML coverage poor (lots of nav/landing pages dilute index) | landing-page filter (reuse `corpus/build_corpus.py:_is_landing_page` logic, generalised) |
| Q&A leakage into retrievable narrative inflates accuracy | rely on lift metric per `LEAKAGE.md`; spot-check on T1 questions |
| Postgres + pgvector not installed on dev host | provide Docker compose snippet; document `apt install postgresql postgresql-16-pgvector` |
| Re-embed cost when chunking strategy changes | deterministic chunk IDs + content hash → cheap diff vs. embedded set |
| Workflow expects LlamaIndex `VectorStoreIndex` API (`index.docstore.get_node`) | wrap pgvector retriever in a thin adapter that exposes `get_node_by_id` |
| Phoenix span attrs drift | unit test that asserts attribute keys present on a trace from each workflow |

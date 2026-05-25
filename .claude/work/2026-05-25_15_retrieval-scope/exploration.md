# Retrieval scope — what gets searched at query time

## TL;DR

At query time the pipeline searches **only the 26,251 Q&A records in
`corpus/corpus.jsonl`**. MongoDB is **never queried online**; it is only
read during the offline corpus build. Any content in MongoDB that the
extractors could not turn into a Q&A pair is invisible to the RAG
pipeline.

## Data flow

```
                 ┌─────────────────────────────────────────────────────┐
                 │  OFFLINE (corpus build, runs only when ingest changes) │
                 └─────────────────────────────────────────────────────┘

  MongoDB ema_scraper
   ├── web_items    (raw HTML pages)         ──┐
   └── parsed_pdfs  (pymupdf4llm markdown,    ─┤
                      ~65k docs)               │
                                               ▼
              corpus/sources/mongo_source.py::records_from_mongodb()
                                               │
                                               ▼
          ┌──────────────────────┐    ┌─────────────────────────┐
          │ html_extractor.py    │    │ pdf_extractor.py        │
          │ (Bootstrap accordion │    │ (numbered "## **N. Q?**" │
          │  items only)         │    │  headings only)         │
          └──────────┬───────────┘    └────────────┬────────────┘
                     │  17,505 records              │  8,746 records
                     └──────────┬───────────────────┘
                                ▼
                  corpus/build_corpus.py  (dedup + landing-page filter)
                                │
                                ▼
                    corpus/corpus.jsonl  (26,251 Q&A records)
                                │
                                ▼
                  harness/embed.py::build_index()
                                │
                                ▼
       FAISS flat-L2 + LlamaIndex docstore  (persisted to INDEX_DIR)


                 ┌─────────────────────────────────────────────────────┐
                 │  ONLINE (each user question)                         │
                 └─────────────────────────────────────────────────────┘

   user query
        │
        ▼
   app.py / harness.workflows  (Simple-RAG, CRAG, ReAct, …)
        │
        ▼
   harness/retrieve.py::retrieve_with_config()
        │       (mode="hybrid": dense BGE + BM25, fused via RRF, k=10)
        ▼
   the same VectorStoreIndex loaded from disk
        │
        ▼
   top-k Q&A nodes → context for the LLM
```

**MongoDB does not appear on the online path.** Confirmed by reading:

- `app.py:230-237` — `_load_index_sync` calls `harness.embed.build_index`,
  not MongoDB.
- `harness/retrieve.py:166-201` — `retrieve()` only calls
  `index.as_retriever(...)` and `BM25Retriever.from_defaults(docstore=...)`.
- `harness/workflows/simple_rag.py:97-101` — workflows use `_retrieve_fn`
  built from that index; no Mongo client anywhere in `harness/workflows/`.

## What is actually in the corpus

From `corpus/corpus_stats.md`:

| Slice               | Count   | %     |
|---------------------|---------|-------|
| html_accordion      | 17,505  | 66.7% |
| pdf                 |  8,746  | 33.3% |
| **Total**           | **26,251** | 100% |

For context, `ema_scraper.parsed_pdfs` alone holds **~65k** parsed PDFs
(per `CLAUDE.md`). So:

- ~57k PDFs produced no Q&A records (no numbered-question headings).
- An unknown but large share of `web_items` HTML pages produced no
  records either (no Bootstrap accordion markup).

That non-Q&A content (assessment reports, EPARs full text, scientific
guidelines body text, minutes, presentations, etc.) **cannot be
retrieved** by the current pipeline.

## Why this is the design — not a bug

- `CLAUDE.md` V1 scope locks: "EMA human-regulatory Q&As only. No EPARs,
  no FDA content, no clinical trial documents."
- `project_roadmap/ROADMAP.md` Phase 1.1 defines the corpus schema as a
  Q&A record (`question` + `answer` + metadata) — there is no "free text"
  record type.
- The benchmark is a Q&A benchmark (T1–T4 question types), so the index
  is optimised for Q&A retrieval, not generic document retrieval.

## What this means for answering questions

1. If a user asks something whose answer lives in an EMA Q&A page or a
   numbered-Q&A PDF, retrieval should work.
2. If a user asks something whose answer lives only in narrative text —
   a guideline body paragraph, an assessment report, a regulatory
   procedural document without numbered Q&A — retrieval will **silently
   miss**, and the LLM will either say "no relevant context" or
   confabulate from training data.
3. The fact that an EMA URL appears in `parsed_pdfs` is *not* a
   guarantee it is in the search index — it only is if the extractor
   found Q&A-shaped sections in it.

## How to verify quickly

```bash
# Count Q&A records actually in the index corpus
wc -l "$EMA_DATA_DIR/corpus/corpus.jsonl"   # ≈ 26,251

# Count PDFs in Mongo that could theoretically contribute
mongosh ema_scraper --eval 'db.parsed_pdfs.countDocuments({error: ""})'

# Spot-check: pick a topic_path from corpus_stats.md and confirm matching
# qa_ids exist in the docstore; then pick a non-Q&A URL and confirm it's
# NOT in corpus.jsonl (grep by source_url).
```

## Options if you want broader coverage

These are *possibilities*, not a plan — the project is locked to V1
Q&A-only per `CLAUDE.md`. List for awareness:

- **A. Add a "narrative" record type to the corpus.** Chunk non-Q&A PDFs
  (e.g. semantic or fixed-window chunks of `parsed_pdfs.markdown`) and
  emit them as records alongside Q&A pairs. The index then mixes both.
  Trade-off: dilutes retrieval precision on T1/T2 lookup questions
  unless query routing is added.
- **B. Second corpus + second index.** Build a separate
  `narrative.jsonl` + FAISS index, and have the workflow query both
  (e.g. fall back to narrative if Q&A retrieval returns nothing
  high-scoring). Cleaner separation; matches MIRAGE-style "evidence
  pool" patterns.
- **C. Live MongoDB BM25 only.** Add a server-side text index on
  `parsed_pdfs.markdown` and query it at runtime as an extra retriever
  fused with the existing dense/BM25 pair via RRF. Cheapest to wire up;
  no re-embed needed. Worst latency.

Any of these would be a Phase 2+ decision and should be checked against
the benchmark before adopting (per the V1 rule "every added complexity
layer must be justified by a specific benchmark failure").

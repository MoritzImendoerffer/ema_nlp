# ema_nlp

A Q&A benchmark and reference RAG implementations built from European Medicines Agency (EMA) human-regulatory content.

**Goal:** Build a shareable benchmark from EMA Q&A documents and measure where expert effort actually pays off in agentic RAG pipelines — corpus quality, retrieval filtering, agent planning, and prompting strategy.

## Deliverables

| Artifact | Description |
|----------|-------------|
| `corpus/corpus.jsonl` | Normalized Q&A pairs extracted from EMA HTML accordions and PDFs |
| `benchmark/benchmark.jsonl` | ~50 evaluation questions stratified across four types (T1–T4) with gold answers |
| `harness/` | MIRAGE-style evaluation pipeline with LLM judges, config-as-code, full tracing |

## Quick links

- **[Setup guide →](docs/SETUP.md)** — install dependencies, configure credentials, sync the database across machines
- **[Architecture →](docs/ARCHITECTURE.md)** — data flow, MongoDB collections, corpus pipeline, FAISS index, common operations
- **[Retrieval pipeline →](docs/RETRIEVAL_PIPELINE.md)** — LlamaIndex usage, dense/BM25/hybrid modes, RRF, ablation A stages, cross-reference traversal
- **[Decisions →](DECISIONS.md)** — architectural and scope decisions with rationale
- **[Open questions →](OPEN_QUESTIONS.md)** — decisions not yet made
- **[Roadmap →](project_roadmap/ROADMAP.md)** — full phase-by-phase plan and success criteria
- **[Glossary →](project_roadmap/GLOSSARY.md)** — EMA regulatory terminology (read before touching pharma acronyms)

## Current status

**Phase 1 — corpus extraction complete.** `corpus/corpus.jsonl` has been produced:
- 26,251 Q&A records (83,895 extracted, 57,644 deduped)
- Sources: 17,505 HTML accordion + 8,746 PDF records
- 65,263 parsed PDFs ingested into MongoDB `parsed_pdfs` collection (10.5% parse-failure rate documented)

**Phase 2 — benchmark complete.** `benchmark/benchmark.jsonl` has 45 items:
- 20×T1 Lookup, 10×T2 Scoping, 10×T3 Multi-hop, 5×T4 Synthesis
- Covers 7 EMA source documents; 62% of items include specific numeric thresholds for contamination resistance

**Phase 3 — harness complete.** LlamaIndex Workflow pipeline operational:
- 9 registered workflow strategies (simple RAG, CRAG, ReAct, CRAG+summarize, CRAG+review, ReAct+review)
- All orchestration, agent loops, and prompt chains run as LlamaIndex `Workflow` / `FunctionAgent` steps
- Chainlit chat UI (`app.py`) with hybrid retrieval, Phoenix tracing, and 👍/👎 feedback annotation
- Semantic query cache with few-shot injection from rated past trajectories

**Phase 4 — ablations.** Ablation A (retrieval variants) and Ablation C (prompting matrix ×3 tiers) runs complete in `results/`. Ablation B (process-reward supervision) infrastructure done; full run pending.

See `.claude/work/` for all work unit logs.

## Stack

| Layer | Choice |
|-------|--------|
| Retrieval framework | LlamaIndex (`VectorStoreIndex`, `BM25Retriever`, RRF fusion) |
| Workflow orchestration | LlamaIndex Workflows (`Workflow` + typed `Event` steps) |
| Chat UI | Chainlit 2.11 — streaming answers, source sidebar, 👍/👎 |
| Embeddings | BGE-large-en via sentence-transformers (local, no API key) |
| Vector store | FAISS flat-L2 (document index + semantic query cache) |
| Tracing | Arize Phoenix + OpenInference (model-agnostic, self-hosted) |
| Feedback | Phoenix span annotations via Chainlit 👍/👎 |
| LLM | Anthropic Claude (primary); OLMo 2 32B (contamination-verifiable reference) |
| Data | MongoDB (raw scrape) → JSONL (corpus/benchmark) |

## Data sources

| Collection | Contents | Count |
|------------|----------|-------|
| `ema_scraper.web_items` | Raw scraped pages — HTML (`html_raw`) and PDF metadata (`url`, `content_type`) | 115k |
| `ema_scraper.parsed_pdfs` | Parsed PDF markdown keyed by URL (`_id`), produced by `scripts/ingest_parsed_pdfs.py` | 65k |

Scraped content comes from the companion repo [ema_scraper](https://github.com/MoritzImendoerffer/ema_scraper). The `parsed_pdfs` collection is built locally from the Scrapy cache (`~/Nextcloud/Datasets/ema_scraper/cache/`). See the setup guide for sync instructions.

## License

Code: MIT. Corpus and benchmark data: CC-BY-4.0 (EMA content reproduced under EMA terms; cite both this repo and EMA).

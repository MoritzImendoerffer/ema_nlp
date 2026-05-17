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
- **[Decisions →](DECISIONS.md)** — architectural and scope decisions with rationale
- **[Open questions →](OPEN_QUESTIONS.md)** — decisions not yet made
- **[Roadmap →](project_roadmap/ROADMAP.md)** — full phase-by-phase plan and success criteria
- **[Glossary →](project_roadmap/GLOSSARY.md)** — EMA regulatory terminology (read before touching pharma acronyms)

## Current status

**Phase 1 — corpus extraction complete.** `corpus/corpus.jsonl` has been produced:
- 26,251 Q&A records (83,895 extracted, 57,644 deduped)
- Sources: 17,505 HTML accordion + 8,746 PDF records
- 65,263 parsed PDFs ingested into MongoDB `parsed_pdfs` collection (10.5% parse-failure rate documented)

Next phase: benchmark construction (Phase 2 — curating 30–50 evaluation questions).

See `.claude/work/` for all work unit logs.

## Stack

| Layer | Choice |
|-------|--------|
| RAG framework | LlamaIndex (`DocumentSummaryIndex`, `ReActAgent`) |
| Embeddings | BGE-large-en via sentence-transformers |
| Vector store | FAISS (document index + query cache) |
| Keyword retrieval | rank-bm25 via LlamaIndex BM25Retriever |
| Tracing | Arize Phoenix + OpenInference (model-agnostic) |
| Feedback | Phoenix annotations + CLI rating UI |
| LLM | Anthropic Claude (primary); OLMo 3 as contamination-verifiable reference |
| Data | MongoDB (raw scrape) → JSONL (corpus/benchmark) |

## Data sources

| Collection | Contents | Count |
|------------|----------|-------|
| `ema_scraper.web_items` | Raw scraped pages — HTML (`html_raw`) and PDF metadata (`url`, `content_type`) | 115k |
| `ema_scraper.parsed_pdfs` | Parsed PDF markdown keyed by URL (`_id`), produced by `scripts/ingest_parsed_pdfs.py` | 65k |

Scraped content comes from the companion repo [ema_scraper](https://github.com/MoritzImendoerffer/ema_scraper). The `parsed_pdfs` collection is built locally from the Scrapy cache (`~/Nextcloud/Datasets/ema_scraper/cache/`). See the setup guide for sync instructions.

## License

Code: MIT. Corpus and benchmark data: CC-BY-4.0 (EMA content reproduced under EMA terms; cite both this repo and EMA).

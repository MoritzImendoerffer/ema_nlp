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

**Phase 1 — corpus extraction.** Extractors for HTML accordions and PDF Q&As are complete (TASK-005, TASK-006). Next: deduplication and corpus manifest (TASK-007, TASK-008).

See `.claude/work/2026-05-10_02_implementation-plan/state.json` for the full task list.

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

## Data source

Scraped EMA website content from the companion repo [ema_scraper](https://github.com/MoritzImendoerffer/ema_scraper), stored in MongoDB (`ema_scraper` / `web_items`). See the setup guide for sync instructions.

## License

Code: MIT. Corpus and benchmark data: CC-BY-4.0 (EMA content reproduced under EMA terms; cite both this repo and EMA).

# ema_nlp

A Q&A benchmark and reference RAG implementations built from European Medicines Agency (EMA) human-regulatory content.

**Goal:** Build a shareable benchmark from EMA Q&A documents and measure where expert effort actually pays off in agentic RAG pipelines — corpus quality, retrieval filtering, agent planning, and prompting strategy.

> ⚠️ **Retrieval refactor in progress** (branch `refactor/llamaindex-retrieval-pipeline`).
> The retrieval layer is being rebuilt **LlamaIndex-first**: a hierarchical
> `PropertyGraphIndex` on **Neo4j** replaces the former Postgres + pgvector and FAISS
> paths. The offline pipeline (`harness/indexing/`) is built and verified on a CPU
> subset; re-seaming the workflows + chat UI and deleting the old stack are pending.
> See **[docs/RETRIEVAL.md](docs/RETRIEVAL.md)** and the work unit
> [`2026-05-30_20_llamaindex-retrieval-refactor`](.claude/work/2026-05-30_20_llamaindex-retrieval-refactor/state.json).
> Pre-refactor state is preserved on `main` and `archive/pre-llamaindex-refactor`.

## Deliverables

| Artifact | Description |
|----------|-------------|
| `corpus/corpus.jsonl` | Normalized Q&A pairs extracted from EMA HTML accordions and PDFs (benchmark source; not the retrieval target) |
| `benchmark/benchmark.jsonl` | ~50 evaluation questions stratified across four types (T1–T4) with gold answers |
| `harness/indexing/` | LlamaIndex-first retrieval pipeline (Neo4j PropertyGraphIndex) |
| `harness/workflows/` | RAG/agent strategies (simple RAG, CRAG, ReAct, composites) over the retriever |

## Quick links

- **[Setup guide →](docs/SETUP.md)** — install dependencies, configure credentials, start services
- **[Architecture →](docs/ARCHITECTURE.md)** — data flow, MongoDB collections, corpus pipeline
- **[Retrieval →](docs/RETRIEVAL.md)** — Neo4j PropertyGraphIndex: node/graph model, config profiles, build + retrieve, mermaid flows
- **[Decisions →](DECISIONS.md)** — architectural and scope decisions with rationale
- **[Open questions →](OPEN_QUESTIONS.md)** — decisions not yet made
- **[Roadmap →](project_roadmap/ROADMAP.md)** — full phase-by-phase plan
- **[Glossary →](project_roadmap/GLOSSARY.md)** — EMA regulatory terminology (read before touching pharma acronyms)

## Current status

**Phase 1 — corpus extraction complete.** `corpus/corpus.jsonl`: 26,251 Q&A records (17,505 HTML accordion + 8,746 PDF). 65,263 parsed PDFs in MongoDB `parsed_pdfs`.

**Phase 2 — benchmark drafted.** `benchmark/benchmark.jsonl`: 45 items (20×T1, 10×T2, 10×T3, 5×T4).

**Retrieval refactor (current work).** Rebuilding retrieval LlamaIndex-first on Neo4j:
- ✅ `harness/indexing/` — config profiles + registry, hierarchical chunker, link extractor, Mongo→IR ingestion, Neo4j PropertyGraphIndex build + `HierarchicalPGRetriever` (small-to-big + `links_to`). 36 unit tests; verified live on a CPU subset.
- ⏳ Pending: re-seam workflows + chat UI to the retriever (LIR-009/010), delete the old pgvector/FAISS stack (LIR-012), rebuild the benchmark/eval suite (removed from this branch; archived).
- The **benchmark/eval suite** (`run_eval.py`, ablations) was removed from this branch and preserved on `archive/pre-llamaindex-refactor`; it will be rebuilt on the clean retrieval API.

See `.claude/work/` for work unit logs.

## Stack

| Layer | Choice |
|-------|--------|
| Retrieval framework | LlamaIndex (`PropertyGraphIndex`, custom `BaseRetriever`) |
| Index + vector store | **Neo4j** — `Neo4jPropertyGraphStore` (graph) + native vector index over chunk embeddings |
| Workflow orchestration | LlamaIndex Workflows (`Workflow` + typed `Event` steps) |
| Chat UI | Chainlit 2.11 — streaming answers, source sidebar, 👍/👎 |
| Embeddings | BGE-large-en-v1.5 via sentence-transformers (local CUDA, no API key) |
| Tracing | Arize Phoenix + OpenInference (model-agnostic, self-hosted) |
| Feedback | Phoenix span annotations via Chainlit 👍/👎 |
| LLM | Anthropic Claude (primary); OLMo 3 (contamination-verifiable reference) |
| Data | MongoDB (raw scrape + parsed text) → Neo4j (graph + vectors); JSONL (corpus/benchmark) |

## Data sources

| Store | Collection | Contents | Count |
|-------|-----------|----------|-------|
| MongoDB `ema_scraper` | `web_items` | Raw scraped pages — HTML (`html_raw`) + PDF metadata; `url` is a 1-element list | 115k |
| MongoDB `ema_scraper` | `parsed_pdfs` | Parsed PDF markdown keyed by URL (`_id`) | 65k |
| MongoDB `ema_scraper` | `parsed_documents` | Canonical parser output (`url, parser, content_type, text`) — the ingestion source | subset seeded¹ |
| Neo4j | `:Document` / `:Chunk` + edges | Retrieval graph + chunk vector index | built per profile |

¹ `parsed_documents` was never backfilled at scale on this host; `scripts/backfill_parsed_documents_subset.py` seeds a verify subset. Full backfill is future work — see [docs/RETRIEVAL.md](docs/RETRIEVAL.md).

Scraped content comes from the companion repo [ema_scraper](https://github.com/MoritzImendoerffer/ema_scraper). Services (Mongo + Neo4j) are provisioned via Docker Compose under `deploy/` and started by `scripts/start_services.sh`.

## License

Code: MIT. Corpus and benchmark data: CC-BY-4.0 (EMA content reproduced under EMA terms; cite both this repo and EMA).

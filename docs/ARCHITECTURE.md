# Architecture and data guide

How the project stores, processes, and retrieves data — from raw scrape to chat answer.

---

## Overview: data flow

```
EMA website
    │  (scraped by ema_scraper repo)
    ▼
MongoDB  ema_scraper.web_items        ← 115k raw pages (HTML + PDF metadata)
MongoDB  ema_scraper.parsed_pdfs      ← 65k parsed PDF markdown
    │
    │  corpus/build_corpus.py
    ▼
corpus/corpus.jsonl                   ← 26,251 normalised Q&A records (versioned in Git)
    │
    │  python -m harness.embed
    ▼
harness/index/                        ← FAISS vector index + docstore (local, not in Git)
    │
    ├── app.py  (Chainlit chat UI)    ← hybrid retrieval → Claude synthesis → Phoenix traces
    └── harness/run_eval.py           ← benchmark eval runs → results/<run_id>/
```

---

## 1. MongoDB — raw data store

Connection is set by `MONGO_URI` (default `mongodb://localhost:27017/`).  
Database: `ema_scraper`.

### Collections

#### `web_items`

Raw output of the [ema_scraper](https://github.com/MoritzImendoerffer/ema_scraper) Scrapy spider.

| Field | Type | Description |
|-------|------|-------------|
| `_id` | ObjectId | MongoDB ID |
| `url` | `[str]` | 1-element list; full EMA URL |
| `content_type` | `[str]` | `["text/html"]` or `["application/pdf"]` |
| `html_raw` | `str` *(HTML pages only)* | Full page HTML |

- **22,743 HTML pages** — `html_raw` present; accordion Q&A pages, EPAR summaries, committee pages
- **92,358 PDF entries** — metadata only; `html_raw` absent; actual content is in `parsed_pdfs`

Useful queries:

```python
# All HTML pages with Bootstrap accordion (extractable Q&A)
db.web_items.count_documents({"html_raw": re.compile("accordion-item")})
# → 6,095

# Search HTML content for a term
db.web_items.find({"html_raw": re.compile("process charact", re.I)}, {"url": 1})
```

#### `parsed_pdfs`

Parsed PDF content produced by `scripts/ingest_parsed_pdfs.py` from the Scrapy `.pkl` cache
files in `~/Nextcloud/Datasets/ema_scraper/cache/`.

| Field | Type | Description |
|-------|------|-------------|
| `_id` | str | EMA PDF URL (used as lookup key) |
| `url` | str | Same as `_id` |
| `markdown` | str | pymupdf4llm output (may be empty on parse failure) |
| `error` | str | Empty string on success; error message on failure |

- **65,263 documents** total; **38,948 with `error: ""`** (successful parses)
- **10.5% parse failure rate** — scanned PDFs, image-only documents
- **19,494 legacy entries** where `error` is `null` (pre-validation; markdown present)

Useful queries:

```python
# All successfully parsed PDFs
db.parsed_pdfs.find({"error": ""})

# Look up a specific PDF
db.parsed_pdfs.find_one({"_id": "https://www.ema.europa.eu/en/documents/..."})
```

### Syncing MongoDB between machines

Two methods — see [SETUP.md → Section 5](SETUP.md#5-mongodb-sync) for full instructions.

```bash
# Export on source machine (writes archive to Nextcloud)
bash scripts/sync_mongo.sh export

# Import on destination machine (reads archive from Nextcloud)
bash scripts/sync_mongo.sh import

# SSH live-pull (both machines online via Tailscale)
bash scripts/sync_mongo.sh pull --host <tailscale-hostname>
```

> Both methods **drop the local database** before restoring. Confirm the prompt.

---

## 2. Corpus — `corpus/corpus.jsonl`

The corpus is the canonical, versioned Q&A dataset. It lives in Git.

### Stats

| Metric | Value |
|--------|-------|
| Records | 26,251 |
| HTML accordion records | 17,505 |
| PDF records | 8,746 |
| File size | ~95 MB |
| Unique source URLs | 3,298 |

### Record schema

```jsonc
{
  "qa_id": "a341a32a97597497",          // stable 16-hex hash of source_url + question
  "question": "Do I have to pay a fee…",
  "answer": "Yes, EMA charges a fee…",
  "source_url": "https://www.ema.europa.eu/en/…",
  "source_type": "html_accordion",      // "html_accordion" | "pdf"
  "source_title": "EMA fees Q&A",
  "topic_path": "/human-regulatory-overview/about-us/fees-payable-…",
  "cross_refs": ["b7a3c1d2e5f6a7b8"],   // qa_ids of "see also" Q&As (multi-hop edges)
  "extraction_confidence": "high",      // "high" | "medium" | "low"
  "reference_number": "EMA/409815/2020",
  "revision": "Rev.5",
  "last_updated": "2024-03"
}
```

`qa_id` is computed as `sha256(source_url + "\x00" + normalised_question)[:16]` — stable across
re-runs as long as the URL and question text don't change.

### Rebuild the corpus from MongoDB

```bash
python -m corpus.build_corpus
```

Or using the full pipeline script (also runs dedup and filter logging):

```bash
python corpus/build_corpus.py \
  --output corpus/corpus.jsonl \
  --dedup-log corpus/corpus_dedup_log.jsonl \
  --filter-log corpus/corpus_filter_log.jsonl
```

The builder reads from `ema_scraper.web_items` (HTML accordion extractor) and
`ema_scraper.parsed_pdfs` (PDF Q&A extractor), deduplicates by question hash,
and writes one JSONL line per surviving record.

Dedup rule: if the same question appears in both HTML and PDF, the PDF version is
kept (richer metadata). Otherwise the first-seen record wins.

### Mini corpus

`corpus/mini_corpus.jsonl` — 156 records, `human-regulatory-overview` topic only.
Used for rapid development and unit tests. **Not suitable for production retrieval.**

---

## 3. FAISS vector index — `harness/index/`

The index is a LlamaIndex `VectorStoreIndex` backed by a FAISS flat-L2 index.
It is built from `corpus.jsonl` and persisted to `harness/index/`.

**The index directory is excluded from Git** (large binary files). It must be built
locally on each machine.

### Index files

| File | Description |
|------|-------------|
| `faiss.index` | FAISS flat-L2 index (~107 MB: 26k × 1024-dim × 4 bytes float32) |
| `docstore.json` | LlamaIndex docstore — full node text + metadata for every Q&A |
| `default__vector_store.json` | Vector store config and node-id mapping |
| `index_store.json` | Top-level index registry |
| `graph_store.json`, `image__vector_store.json` | Placeholder files written by LlamaIndex |

### Embedding model

Default: **`BAAI/bge-large-en-v1.5`** — 1,024-dim, ~1.3 GB download on first use.
The model is cached in `~/.cache/huggingface/` after the first download.

Each node is embedded as: `"Q: {question}\n\nA: {answer}"` (both fields together).
All metadata fields are excluded from the embedding text.

### Build or rebuild the index

```bash
# Build from corpus.jsonl (skips if index already exists)
python -m harness.embed

# Force rebuild even if index exists
python -m harness.embed --force

# Use a custom corpus or index directory
python -m harness.embed --corpus /path/to/corpus.jsonl --index-dir /path/to/index/
```

Via env vars (useful for the chat UI):

```bash
EMA_CORPUS_PATH=/path/to/corpus.jsonl  # default: corpus/corpus.jsonl
EMA_INDEX_PATH=/path/to/index/         # default: harness/index/
```

> **When to rebuild:**
> - After the corpus changes (`corpus.jsonl` updated)
> - After changing the embedding model (`EMA_EMBED_MODEL`)
> - After changing the embedding provider (`EMA_EMBED_PROVIDER`)
> - If `harness/index/` is deleted or moved
>
> To force a rebuild, either pass `--force` or delete `harness/index/docstore.json`
> (the presence of this file is the "index already built" check).

### Estimated rebuild time

| Corpus | Model | Time (CPU) |
|--------|-------|------------|
| `mini_corpus.jsonl` (156 records) | BGE-large-en | < 1 min |
| `corpus.jsonl` (26,251 records) | BGE-large-en | ~25–30 min |
| `corpus.jsonl` (26,251 records) | BGE-small-en | ~8–10 min |

### Use a lighter model on a laptop

Set in `~/.myenvs/ema_nlp.env`:

```bash
EMA_EMBED_MODEL=BAAI/bge-small-en-v1.5   # ~130 MB, faster, slightly lower recall
```

Then delete `harness/index/docstore.json` and run `python -m harness.embed`.

---

## 4. Retrieval modes

See **[docs/RETRIEVAL_PIPELINE.md](RETRIEVAL_PIPELINE.md)** for a detailed walk-through of LlamaIndex internals, RRF fusion, and the ablation A pipeline.

`harness/retrieve.py` exposes three modes, all returning `(qa_id, score, metadata)` triples:

| Mode | How it works | Best for |
|------|-------------|---------|
| `dense` (A0) | FAISS cosine/L2 similarity on BGE embeddings | Semantic similarity |
| `bm25` | BM25 keyword ranking over docstore | Exact term matching |
| `hybrid` (A0+) | Reciprocal Rank Fusion of dense + BM25 (RRF_K=60) | General use |

The chat UI uses `hybrid` by default. Ablation configs can select any mode.

---

## 5. Chat UI — `app.py`

```bash
# Full start (Phoenix tracing + Chainlit)
bash run_ui.sh

# Chainlit only (no tracing)
PHOENIX_DISABLED=1 bash run_ui.sh

# Custom ports
PHOENIX_PORT=6007 CHAINLIT_PORT=8001 bash run_ui.sh
```

| Service | Default URL |
|---------|-------------|
| Chat UI | http://localhost:8000 |
| Phoenix trace viewer | http://localhost:6006 |

On first message the chat UI:
1. Loads the FAISS index from `harness/index/` (or builds it if missing)
2. Runs hybrid retrieval (top-10 results)
3. Streams a Claude synthesis over the top-5 sources
4. Shows sources in a side panel
5. Records 👍/👎 feedback to Phoenix as span annotations

**Key env vars for the UI:**

| Variable | Default | Description |
|----------|---------|-------------|
| `EMA_CORPUS_PATH` | `corpus/corpus.jsonl` | Corpus file used to build the index |
| `EMA_INDEX_PATH` | `harness/index/` | Where the FAISS index is stored/loaded from |
| `EMA_CLAUDE_MODEL` | `claude-haiku-4-5-20251001` | Synthesis model (UI-specific override) |
| `EMA_LLM_MODEL` | `claude-haiku-4-5-20251001` | Default LLM model across the pipeline |
| `PHOENIX_URL` | `http://localhost:6006` | Phoenix server for traces and feedback |
| `PHOENIX_DISABLED` | *(unset)* | Set to `1` to disable all tracing |

---

## 6. Eval harness — `harness/run_eval.py`

Runs a full benchmark evaluation and writes results to `results/<run_id>/`.

```bash
python -m harness.run_eval --config harness/configs/baseline_a0.yaml
```

### Run configs (`harness/configs/`)

Each YAML file is one run configuration:

| Config | Description |
|--------|-------------|
| `baseline_a0.yaml` | Dense retrieval only |
| `baseline_a0plus.yaml` | Hybrid retrieval (dense + BM25 + RRF) |
| `ablation_a_a1.yaml` | + Query expansion (acronym disambiguation) |
| `ablation_a_a2_keyword.yaml` | + Topic filter (keyword post-filter) |
| `ablation_a_a2_concept.yaml` | + Topic filter (IDMP concept pre-filter) |
| `ablation_a_a3.yaml` | + SME rubric reranker (Claude) |
| `ablation_a_a4.yaml` | + Generic reranker (Claude) |
| `ablation_a_a5.yaml` | + Combined A3+A4 rerankers |

Config fields:

```yaml
run_id: baseline_a0
retrieval:
  mode: hybrid          # dense | bm25 | hybrid
  k: 10
index:
  corpus: corpus/corpus.jsonl
  index_dir: harness/index
  embed_model: BAAI/bge-large-en-v1.5
  force_rebuild: false  # set true to force index rebuild for this run
benchmark:
  path: benchmark/benchmark.jsonl
judge:
  enabled: false        # requires ANTHROPIC_API_KEY
  model: claude-haiku-4-5-20251001
results:
  base_dir: results
```

### Results structure

```
results/
└── baseline_a0_20260517_142301/
    ├── config.yaml          # copy of the run config
    ├── retrieval.json       # Recall@k, Precision@k, Citation Accuracy by T1–T4
    ├── retrieval.png        # bar chart
    ├── judge_scores.jsonl   # one line per benchmark item (if judge enabled)
    └── run_summary.md       # human-readable summary
```

---

## 7. File storage layout

### In Git (versioned)

```
benchmark/benchmark.jsonl      # evaluation questions (30–50, in progress)
harness/configs/               # eval run configs
harness/prompts/               # judge and reranker prompt files
harness/index/.gitkeep         # placeholder to keep the empty index directory
ablations/A_evidence_filter/   # acronym dict and related assets
```

### Local only — gitignored, rebuild from MongoDB

```
corpus/corpus.jsonl            # 95 MB — rebuilt by: python corpus/build_corpus.py
corpus/mini_corpus.jsonl       # 156-record dev subset — rebuilt by: scripts/fetch_mini_corpus.py
corpus/*_log.jsonl             # dedup/filter logs
harness/index/                 # FAISS index (~300 MB once built) — rebuild with: python -m harness.embed
results/                       # eval run outputs
.phoenix.log                   # Phoenix server log
~/.myenvs/ema_nlp.env          # credentials and machine defaults
```

> Both the corpus JSONL and the FAISS index are excluded from Git — they are large
> derived artifacts that can be fully reconstructed from MongoDB + the embedding model.
> The `.gitkeep` in `harness/index/` is the only tracked file there; it just preserves
> the directory so `python -m harness.embed` has somewhere to write.

### Nextcloud (shared via cloud sync)

```
~/Nextcloud/Datasets/
├── ema_scraper/cache/         # Scrapy HTTP cache (~several GB) — source for parsed_pdfs
├── mongo_sync/
│   └── ema_scraper.archive    # MongoDB dump for cross-machine sync
└── Pistoia-Alliance-Ontologies/IDMP-O/1.3.0/
    └── IdentificationOfMedicinalProductsOntology.rdf   # IDMP ontology (used by tag_concepts.py)
```

---

## 8. Scripts reference

| Script | Purpose |
|--------|---------|
| `scripts/setup.sh` | First-time machine setup (deps, Claude Code, env file) |
| `scripts/sync_mongo.sh` | MongoDB export/import/pull between machines |
| `scripts/ingest_parsed_pdfs.py` | Bulk-upsert parsed PDF `.pkl` files → `parsed_pdfs` collection |
| `scripts/fetch_mini_corpus.py` | Rebuild `mini_corpus.jsonl` from MongoDB |
| `scripts/tag_concepts.py` | Tag corpus records with IDMP concept labels |
| `corpus/build_corpus.py` | Rebuild `corpus.jsonl` from MongoDB |
| `python -m harness.embed` | Build or rebuild the FAISS index |
| `python -m harness.run_eval` | Run a benchmark evaluation |
| `bash run_ui.sh` | Start Phoenix + Chainlit chat UI |

---

## 9. Common operations

### Rebuild everything from scratch on a new machine

```bash
# 1. Sync MongoDB from another machine
bash scripts/sync_mongo.sh import       # after exporting on the source machine

# 2. Rebuild corpus from MongoDB
python corpus/build_corpus.py

# 3. Build the FAISS index
python -m harness.embed                 # takes ~25 min with BGE-large-en

# 4. Start the chat UI
bash run_ui.sh
```

### Change the embedding model

```bash
# 1. Update ~/.myenvs/ema_nlp.env
echo "EMA_EMBED_MODEL=BAAI/bge-small-en-v1.5" >> ~/.myenvs/ema_nlp.env

# 2. Delete the old index so it gets rebuilt
rm harness/index/docstore.json

# 3. Rebuild
python -m harness.embed
```

### Update the corpus after new EMA pages are scraped

```bash
# Re-run the corpus builder (re-reads MongoDB, re-deduplicates)
python corpus/build_corpus.py

# Delete old index and rebuild
rm harness/index/docstore.json
python -m harness.embed
```

### Run a quick smoke test after a rebuild

```bash
pytest tests/test_embed.py tests/test_retrieve.py -v
```

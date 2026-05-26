# NARR-011 — Timing + scaling notes

Two `--limit 100` runs on `marvin-gpu` (RTX 3090, 24 GiB), with the Postgres
container co-resident on the same host. BGE-large-en-v1.5 was already cached
locally; `HF_HUB_OFFLINE=1` silenced the Hub metadata noise.

## Setup

```bash
hostname              # marvin-gpu
.venv/bin/python -V   # 3.13.7
nvidia-smi            # RTX 3090, 24576 MiB total
docker compose ps     # ema_nlp_pg (pgvector/pgvector:pg16) — healthy
```

DB state before the runs: 30 documents / 396 chunks / 1106 links (the
NARR-016..023 seed). The two limited runs only add new documents (their
`source_url`s did not overlap the seed).

## Runs

### PDFs — `--source pdfs --limit 100 --batch-size 32`

```
wall:                28.94 s
docs seen / kept:    100 / 100
chunks written:      1021
links written:       626
errors:              0
rss_max_kb:          2,407,960  (≈2.3 GiB Python process)
```

**Throughput**: 100 docs / 28.94 s ≈ **207 docs/min**.
Per-chunk: 1021 chunks / 28.94 s ≈ **2,116 chunks/min**.
~10.2 chunks per PDF on average (PDF Q&A markdown is dense, multi-section).

The first 4 s of wall time is BGE model load + warm-up on CUDA (visible as
the dip in tqdm rate during model initialisation). Steady-state encode is
~5–15 docs/sec depending on chunk depth per doc.

### HTML — `--source html --limit 100 --batch-size 32`

```
wall:                19.27 s
docs seen / kept:    100 / 98     (2 landing pages skipped — see <200-char guard)
chunks written:      227
links written:       11,204
errors:              0
rss_max_kb:          2,447,832  (≈2.3 GiB Python process)
```

**Throughput**: 100 docs / 19.27 s ≈ **311 docs/min** (≈50% faster per doc than PDFs).
Per-chunk: 227 chunks / 19.27 s ≈ **706 chunks/min**.
~2.3 chunks per HTML doc — trafilatura strips boilerplate aggressively, so
the average HTML page yields far fewer chunks than a Q&A PDF.

The 11,204 links on 100 HTML docs comes from the `<a href>` walker — most
of those (>95 %) won't resolve to a `tgt_doc_id` until both endpoints are
in `documents`. Link extraction itself is cheap; the cost is dominated by
the trafilatura `extract` call and the BGE encode batch.

## GPU memory

The 3090 sat at ~1.8–1.9 GiB used throughout both runs (`nvidia-smi`
sampled before, between, and after). BGE-large at fp32 is ~1.3 GiB of
weights; the remainder is the CUDA runtime and the LlamaIndex Settings
state. We are nowhere near the 24 GiB ceiling — batch-size could go
substantially higher (64 or 128) without OOM risk, though throughput
gains plateau because the model is small relative to the GPU.

## Disk / index footprint

After both runs (208 documents / 1,559 chunks / 11,830 links):

```
chunks (heap)         26 MB
chunks_embedding_hnsw 12 MB       (HNSW index)
chunks_text_tsv_idx    3 MB       (BM25 / GIN)
ema_nlp database      40 MB total
```

Per-chunk HNSW cost: ~7.7 KiB/chunk. Each chunk's `vector(1024)` payload
is itself ~4 KiB on disk; HNSW adds ~3.7 KiB/chunk of graph metadata.

## Extrapolation to the full corpus

The 3090 host's MongoDB holds **38,948 clean parsed PDFs** and
**~115k web_items**. Of the web_items, only the `content_type='text/html'`
slice will go through the html path — the remainder are PDF metadata.

| Source | Docs | Throughput (this run) | Est. wall time |
|--------|------|------------------------|----------------|
| PDFs | 38,948 | 207 docs/min | **≈ 3.1 h** |
| HTML (assume 60k content pages) | ~60,000 | 311 docs/min | **≈ 3.2 h** |

The PDF wall time is mostly embed-bound on the GPU; the HTML wall time
mixes trafilatura CPU work with embed. Running them serially is ~6 hours
total; running PDFs and HTML interleaved on the same GPU won't help —
they share the BGE batcher.

For the chunks / index side: extrapolating linearly from the limited
runs, the full ingest will produce roughly:

- PDFs: 38,948 × 10.2 chunks ≈ **400 k chunks**
- HTML: 60,000 × 2.3 chunks ≈ **140 k chunks**
- Total: **~540 k chunks**

Storage (linear from the 1,559-chunk baseline):

| Object | Per-chunk | At 540 k chunks |
|--------|-----------|------------------|
| `chunks` heap | ~17 KB | ~9 GB |
| `chunks_embedding_hnsw` | ~7.7 KB | ~4 GB |
| `chunks_text_tsv_idx` | ~2 KB | ~1 GB |
| **DB total estimate** | | **~14–18 GB** |

Bounded; sits comfortably on the host's nvme0n1p2 (986 GiB free at the
time of this run).

## Bottleneck

**BGE embedding on the GPU dominates both runs.** Evidence:

- PDF wall time scales with chunk count, not with doc count (10x more
  chunks/doc → ~5x slower than HTML per-doc).
- GPU utilisation stays mostly bound during the encode phase (tqdm rate
  is steady once warm, ~5–15 docs/sec).
- The Postgres bulk INSERT is small in absolute terms (40 MB total DB after
  208 docs); `EXPLAIN ANALYZE` on `INSERT_CHUNK` shows sub-millisecond
  per-row even with the HNSW index attached.
- Chunking (LlamaIndex MarkdownNodeParser + SentenceSplitter) costs ~1 ms
  per chunk — negligible against the embed batch.

If we ever needed to compress wall time further, the high-leverage moves are:

1. Bigger embed batches (32 → 128) — modest gain, well within GPU memory.
2. Quantised BGE (int8 via Sentence-Transformers) — ~2x throughput on
   3090, with a small recall hit.
3. CPU-parallel chunking decoupled from the GPU embed loop — only worth
   doing if we hit a different bottleneck.

None of these are blocking for v1 — a one-time 6-hour ingest is
acceptable, and resume + `--force` semantics (verified in NARR-008) make
re-runs cheap.

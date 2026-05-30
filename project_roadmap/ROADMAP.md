# EMA Q&A RAG Benchmark — v1 Roadmap

> ⚠️ **Architecture revision (2026-05-30).** Retrieval is now a **Neo4j hierarchical
> PropertyGraphIndex** — this revises the original "No Neo4j" v1 non-goal below (graph
> structure became the chosen retrieval signal). See `DECISIONS.md` and
> [`docs/RETRIEVAL.md`](../docs/RETRIEVAL.md). The corpus + benchmark methodology (phases,
> T1–T4 types, lift, ablations) still stands; the eval-suite *code* was archived off the
> refactor branch (`archive/pre-llamaindex-refactor`), to be rebuilt on the new retrieval API.

**Project goal.** Build a shareable Q&A benchmark from EMA human-regulatory content, plus reference RAG implementations of increasing sophistication, to test where subject-matter expert (SME) effort actually pays off in agentic RAG.

**Scope lock for v1.** EMA human-regulatory Q&A only. ~30–50 benchmark questions mined directly from EMA Q&A documents. Three targeted ablations. Flat baseline first; graph/ontology only introduced if a specific failure class demands it.

**Non-goals for v1.** No ontology loading (IDMP/SPOR). No Neo4j. No EPARs. No biomedical-literature QA. No multilingual.

**Guiding principles.**
1. Ship a usable thing before adding complexity.
2. Every layer of complexity must be justified by a benchmark failure it addresses.
3. Separate three deliverables that can be released independently: corpus, benchmark, eval harness.
4. Measurements over opinions — every design claim gets a number.

---

## Phase 0 — Scoping data (≈ 1–2 evenings)

**Purpose.** Confirm the Q&A route is viable before any new code is written. Do this before committing to anything downstream.

### 0.1 Inventory Q&A content in existing Mongo scrape
- Query for pages containing accordion Q&As (class `accordion-item` inside `main-content-wrapper`).
- Query for linked Q&A PDFs — URL patterns `questions-answers` and `q-and-a` in filename.
- Produce counts: pages with accordion Q&As, Q&A PDFs, overlap with human-regulatory URL tree.
- Output a CSV: `url`, `type` (html/pdf), `topic_path` (URL-derived), `q_count_estimate`.

### 0.2 Topic stratification
- Group Q&A sources by URL-derived topic path (e.g. `/research-development/scientific-guidelines/quality-guidelines/…`, `/post-authorisation/classification-changes/…`).
- Identify 3–5 topic clusters with enough material to stratify benchmark questions across.
- Exclude anything outside human-regulatory in v1.

### 0.3 Go/no-go decision
- If fewer than ~50 extractable Q&A pairs across ≥3 topics → stop and rescope. Candidates: broaden to include structured guidance-document Q&A sections, or drop the stratification requirement.
- If sufficient → proceed to Phase 1.

**Deliverable.** A one-page notebook output with the counts, the topic split, and a go/no-go call. Nothing built yet.

---

## Phase 1 — Corpus extraction and normalization (≈ 1 week of evenings)

**Purpose.** Turn heterogeneous EMA Q&A sources into one flat, versioned Q&A record format. This *is* the shareable corpus.

### 1.1 Unified Q&A record schema
Define and document:
```
{
  "qa_id": "…",              # stable hash of source+question
  "question": "…",
  "answer": "…",
  "source_url": "…",
  "source_type": "html_accordion | pdf",
  "source_title": "…",       # e.g. "Nitrosamines Q&A"
  "reference_number": "…",   # e.g. "EMA/409815/2020 Rev.23"
  "topic_path": "…",         # URL-derived breadcrumb
  "revision": "…",           # if Q&A doc is versioned
  "last_updated": "…",       # ISO date
  "cross_refs": ["qa_id", …], # explicit "see Q&A X" links
  "extraction_confidence": "high | medium | low"
}
```

### 1.2 HTML accordion extractor
- Existing `ema_parser.py::_parse_accordion` already does the heavy lifting — reuse it.
- Post-processor: split accordion items into Q/A pairs; flag items where the question isn't a question-form heading.
- Build topic_path from URL segments.

### 1.3 PDF Q&A extractor
- Use existing PyMuPDF4LLM output.
- Pattern-based Q segmentation: questions in these docs are numbered headings ("1. Should the risk…", "2. What is the…"). Extract by regex on top-of-section patterns, split on next-number boundary.
- Parse the "Revision History" table (present in most EMA Q&A PDFs) for versioning metadata.
- Parse "see Q&A N" references into `cross_refs` — these are the multi-hop edges.
- Extract reference number from title page.
- Flag PDFs without this structure for manual review or exclusion.

### 1.4 Filter: landing pages that aren't Q&A
- Pages that link to Q&A PDFs but aren't themselves Q&A (e.g. the nitrosamine overview page) — filter out based on accordion absence + no numbered Q headings.

### 1.5 Deduplication
- Same Q&A can appear on HTML page + PDF. Hash-based dedup on normalized question text.
- Prefer PDF version (has revision metadata) when duplicates found.

### 1.6 Corpus manifest
- Output `corpus.jsonl` — one record per Q&A.
- Output `corpus_stats.md` — counts by topic, source type, revision date distribution.

**Deliverable 1 (shareable).** `corpus.jsonl` + schema doc + extraction code. This alone is a usable resource for others.

---

## Phase 1.5 — Training-data verification (≈ 1 afternoon)

**Purpose.** Before building the benchmark, check whether your specific EMA source documents appear in the fully-released training corpora of OLMo 3 (Dolma 3) and Pleias Common Corpus. This tells you whether OLMo 3 can serve as a contamination-measurable reference model in Ablation C.

### Steps
- Pick 5–10 distinctive sentences from each main source document (nitrosamine Q&A, level-of-detail Q&A, Quality Q&A parts 1/2, etc.)
- Search the public Dolma 3 release and Common Corpus for each sentence
- Record per-source-document presence status: present / absent / partial
- Output: `docs/training_data_verification.md` with per-document status

### Why this matters
If EMA content is absent from Dolma 3, OLMo 3 becomes a genuinely clean reference for that content — rare and valuable. If present, you still benefit from OLMo 3 being *verifiably-measured* rather than contamination-opaque, but you'd weight its scores the same as the closed frontier models.

See `docs/LEAKAGE.md` section 7.5 for the full rationale.

---

## Phase 1.7 — Narrative corpus on Postgres + pgvector (added 2026-05-25, shipped 2026-05-26)

**Status:** complete (NARR-001..028, 28 tasks). Work unit: [`.claude/work/2026-05-25_16_pgvector-narrative-corpus/`](../.claude/work/2026-05-25_16_pgvector-narrative-corpus/). Operator's guide: [`docs/RETRIEVAL.md`](../docs/RETRIEVAL.md) *(this Phase 1.7 pgvector work is superseded by the Neo4j refactor — see the banner at the top).*

**Why this phase exists** (not in the original v1 plan). The curated Q&A pairs in `corpus.jsonl` (Phase 1) are an extract, not the full content surface. T2 scoping ("does CHMP say X about Y") and T4 synthesis ("compare PRAC vs CHMP guidance on Z") both need the full narrative prose — chapter body text, headings, tables, hyperlinks — that the Q&A pair extraction discards. Rather than fight the FAISS-flat layout to accommodate a richer surface, the narrative corpus moved into Postgres + pgvector with a relational `links` table so dense / BM25 / link-traversal all share one store.

### 1.7.1 Schema
Three tables, defined in [`corpus/pg_schema.sql`](../corpus/pg_schema.sql):
- `documents` — one row per source URL; carries `source_type` (pdf/html), `committee` (CHMP/PRAC/CMDh/COMP/…), `topic_path`, `reference_number`, `last_updated`.
- `chunks` — text chunks with `embedding vector(1024)`, HNSW index on the embedding, generated `text_tsv` column with GIN index for BM25. FK to `documents`.
- `links` — outbound links per source chunk: `link_type` ∈ {hyperlink, reference_number, see_qa}, `tgt_url`, optional `tgt_doc_id` resolved by a second pass. `see_qa` is excluded from default traversal (would leak benchmark answers).

### 1.7.2 Ingest pipeline
`python -m harness.embed_pg --source pdf|html [--limit N] [--force]`:
1. Read MongoDB (`parsed_pdfs` for PDF, `web_items.html_raw` for HTML)
2. Normalise (pymupdf4llm-derived markdown for PDFs; trafilatura with `favor_recall=True` for HTML; pages <200 chars treated as landing pages and skipped)
3. Chunk via LlamaIndex `SentenceSplitter` (configurable size/overlap)
4. Embed batches with `BAAI/bge-large-en-v1.5` on local CUDA via `harness.providers.configure_embed_model()`
5. Bulk upsert chunks + extracted links (markdown `[text](url)`, HTML `<a href>`, EMA reference codes, see-Q&A patterns)
6. `python scripts/resolve_links.py` runs idempotent UPDATE passes to populate `links.tgt_doc_id`

Resume + dedup verified (NARR-008); `--force` re-embeds. Timing on the 3090 (NARR-011): ~207 docs/min PDF, ~311 docs/min HTML; GPU sits at ~1.9/24 GiB throughout.

### 1.7.3 Retrieval surface
`harness/retrieve_pg.py` exposes:
- `retrieve_dense_pg(query, config)` — HNSW kNN via `<=>` (explicit `::vector` cast on query param; `register_vector` only auto-adapts numpy arrays). Score = `1 - cosine_distance`.
- `retrieve_bm25_pg` — `ts_rank_cd(plainto_tsquery(...))` over the generated `text_tsv` column.
- `retrieve_hybrid_pg` — dense + BM25 fused via RRF (K=60, matches FAISS path).
- `retrieve_with_config_pg(config, query)` — dispatcher; applies auto-traversal when `config.traversal.mode == "auto"` (recursive CTE over `links`, adds one representative chunk per neighbour doc, seeds stay first).
- `build_retrieve_fn_pg(config)` — drop-in callable matching `harness.retrieve.build_retrieve_fn`'s signature. Workflows see only the callable; backend is invisible.
- `follow_links_tool` — `FunctionTool` for ReAct agent_tool traversal mode.

Sub-corpus filters expressed via `RetrievalConfigPG.prefilter` (committee, date range, source_type, topic prefix); example config: [`harness/configs/example_chmp_only.yaml`](../harness/configs/example_chmp_only.yaml).

### 1.7.4 Switch contract
- `EMA_RETRIEVER=pgvector` — runtime default since NARR-028 (commit `e36d6fd`).
- `EMA_RETRIEVER=faiss` — legacy opt-out over `corpus.jsonl`; retained for parity smoke tests.
- Phoenix spans carry `ema.retrieval.backend = 'pgvector'|'faiss'` so cross-backend evals are filterable in the UI.

### 1.7.5 Test coverage
- Unit suite (NARR-025): chunker / PDF normaliser / HTML normaliser / link extractor — 91% on the four ingestion modules, 53 tests in 4 s.
- Integration suite (NARR-026): `tests/test_retrieve_pg.py` against a dedicated `ema_nlp_test` database (`PG_DSN_TEST`), 9 tests covering seeded counts, dense self-recall, BM25 keyword hits, hybrid RRF, prefilter (committee + date), auto-traversal expansion, `max_hops=0` no-op, dispatcher routing. Embeddings seeded deterministically via numpy RNG so tests don't load the BGE model.
- End-to-end smoke (NARR-023): 5-question slice of `simple_rag` on pgvector returns non-empty answers; 46/50 chunks came from URLs outside `corpus.jsonl`, confirming narrative coverage.

**Deliverable.** Production-default narrative-corpus retrieval. No changes required to the Phase 2 benchmark or Phase 3 harness contract — they consume the same `(id, score, metadata)` tuple, with the backend dispatched by env var.

---

## Phase 2 — Benchmark construction (≈ 1 week)

**Purpose.** Build 30–50 evaluation questions from mined Q&A, stratified to discriminate between retrieval strategies.

### 2.1 Question-type taxonomy
Four types, each tests something different about retrieval:
- **T1 Lookup** — single-Q answer, single source. Baseline; most flat retrievers should handle these.
- **T2 Scoping** — requires correct selection among topically-adjacent Q&As. Tests whether retrieval respects topic boundaries.
- **T3 Multi-hop** — requires traversing `cross_refs` (Q22 → Q20 → Q10 in nitrosamines). Tests whether retrieval uses document structure.
- **T4 Synthesis** — requires combining ≥2 Q&As from different docs. Tests recall across siblings.

### 2.2 Question sourcing
- T1: sample directly from mined Q&As. Use the Q as-is, the A as gold.
- T2: pair Qs that share keywords but have different topical scope. Author minor question rephrasings that should retrieve one but not the other.
- T3: follow `cross_refs` chains extracted in Phase 1. Compose questions that need the chain to answer.
- T4: hand-curate from topically related Q&A docs.

Target split for v1: 20 T1, 10 T2, 10 T3, 5–10 T4. Total ≈ 50.

### 2.3 Gold answer format
For each benchmark item:
```
{
  "bench_id": "…",
  "question": "…",
  "type": "T1 | T2 | T3 | T4",
  "gold_answer": "…",               # canonical answer text
  "gold_qa_ids": ["…", …],          # which corpus Q&As must be retrieved
  "gold_sources": [{"url": …, "page": …}, …],
  "topic_path": "…",
  "notes": "…"                       # why this question is the type it is
}
```

### 2.4 Quality review
- You (the SME) review every generated item for: is the question a realistic regulatory question? Is the gold answer actually in the linked source? Is the type label correct?
- Fix or drop ambiguous items. Aim for zero "I guess the answer could also be X" items.

### 2.5 Contamination screen (essential, not optional)
EMA Q&As are old, public, and almost certainly in modern LLMs' training data. Before treating any benchmark score as meaningful:
- Run every candidate model on every benchmark item with **no retrieval** (closed-book). Record which items each model can already answer.
- On a subsample, run a slot-guessing test (mask a specific numeric limit or deadline, ask the model to fill it in without context) to estimate memorization depth.
- Tag each item with `zero_shot_known_<model>` flags. Report results both with and without these items.
- Prefer questions whose answers depend on specific quantitative details, recent revisions, or cross-reference traversal — these are more robust to memorization.
- Include ≥5 "composite" or post-cutoff items: T4 questions you author yourself that combine published Q&As in ways the documents don't, or items from Q&A revisions published after the evaluated model's knowledge cutoff.

See `docs/LEAKAGE.md` for the full treatment: why this matters, what's at risk, what mitigations cost, and how to report results honestly in the face of residual contamination.

**Deliverable 2 (shareable).** `benchmark.jsonl` + stratification report + contamination screen results per model.

---

## Phase 3 — Baseline RAG and evaluation harness (≈ 1 week)

**Purpose.** The control arm. Everything else is measured against this.

### 3.1 Flat retrieval implementation
- Corpus = every mined Q&A record, treated as one chunk each (no splitting — they're already the right granularity).
- Embedding: one open-weight model (BGE-large or similar). Document the choice; avoid premature tuning.
- Store: any lightweight vector DB (Qdrant, Chroma). Or even in-memory FAISS for v1.
- Retrieval: top-k=5 dense similarity. No reranking, no metadata filter.
- Generation: Claude/GPT with a minimal prompt that says "answer from the retrieved Q&As, cite the qa_ids you used."

### 3.2 Evaluation harness — borrow from MIRAGE
Five metrics, all automatable:
- **Retrieval Recall@k** — did the gold `qa_ids` appear in top-k?
- **Retrieval Precision@k** — fraction of retrieved that were gold.
- **Answer Faithfulness** (LLM judge): does the answer only claim things present in retrieved Q&As?
- **Answer Correctness** (LLM judge): is the answer semantically equivalent to gold?
- **Citation Accuracy**: fraction of cited qa_ids that match gold.

LLM judge: use a different model than the one generating answers. Publish the judge prompt.

### 3.3 Scoring per type
Report all five metrics broken down by T1/T2/T3/T4. The interesting result isn't the aggregate — it's which types break which metrics.

### 3.4 Closed-book vs open-book reporting
For each model, report two numbers side by side:
- **Closed-book**: question only, no retrieval. Measures memorization.
- **Open-book**: question + retrieval. Measures the full RAG system.

The **lift** (open-book − closed-book) is the headline number, not absolute Correctness. A system scoring 95% means something very different depending on whether closed-book was 40% or 92%. This framing also makes results more robust to EMA-content training-data leakage. See `docs/LEAKAGE.md`.

### 3.5 Config-as-code
Each run produces a config dict + results dict, both logged. This makes ablations trivial — flip a flag, rerun.

**Deliverable 3 (shareable).** Baseline numbers per question type, harness code, judge prompts.

---

## Phase 4 — The three ablations (≈ 2–3 weeks, one per ablation)

**Purpose.** Test specific SME interventions that the literature says should matter most. Each is a single flag-flip against the Phase 3 baseline.

**See `docs/ABLATIONS.md` for the full design of each ablation** — variants, SME artifacts, expected per-type effects, risks, cost budgets. The summary below is just the headline claim for each.

### 4.1 Ablation A — SME-curated evidence filtering + query reformulation
Retrieval-layer interventions (acronym dictionary, topic-aware filtering, SME-rubric reranker) beat vanilla dense retrieval. Prior art: MIRAGE +18pts from corpus changes; recent expert eval +12/+8.2 from query reformulation + filtering. Expected biggest gain on T2/T3.

### 4.2 Ablation B — Process-reward supervision for agent planning
A ReAct agent with SME-labeled plan-step rewards beats single-pass retrieval, especially on multi-hop (T3) and synthesis (T4). Prior art: RAG-Gym +19 F1 on HotpotQA.

### 4.3 Ablation C — SME few-shot vs self-generated CoT vs zero-shot across model tiers
The counterargument test. **3×3 grid**: mid-tier closed × frontier reasoning × fully-open (OLMo 3) × three prompting strategies. Tests whether frontier reasoning models erode the value of SME-written few-shot exemplars in the regulatory domain (as Medprompt→o1 showed for medical QA). The fully-open tier serves as a contamination-measurable reference — if gain patterns match across all three rows, observed effects are likely real retrieval behavior rather than memorization artifacts.

### 4.4 Optional bonus — citation granularity × trust calibration
Small human study on trust calibration. See `docs/ABLATIONS.md` for full design.

---

## Phase 5 — Writeup and release (≈ 1 week)

### 5.1 Repo structure
```
ema-rag-benchmark/
├── README.md
├── LICENSE (CC-BY-4.0 for data, MIT for code)
├── corpus/
│   ├── corpus.jsonl
│   ├── SCHEMA.md
│   └── STATS.md
├── benchmark/
│   ├── benchmark.jsonl
│   ├── TAXONOMY.md
│   └── curation_notes.md
├── harness/
│   ├── run_eval.py
│   ├── judges/
│   └── configs/
├── ablations/
│   ├── A_evidence_filter/
│   ├── B_process_rewards/
│   └── C_prompting_matrix/
├── results/
│   └── results.md
└── docs/
    └── methodology.md
```

### 5.2 Blog post (audience: ML + pharma tech)
Outline:
1. Hook — "There's no public EMA Q&A benchmark, and here's why that's a problem."
2. Why Q&As are the gold — EMA writes them, so use them.
3. The three kinds of SME effort and what each one bought (one chart per ablation).
4. The surprising finding (whatever it turns out to be — probably about where reasoning models close the gap).
5. What to borrow, what's open.

### 5.3 README (audience: developers evaluating RAG on regulatory content)
- Quickstart: pip install, run baseline, see numbers.
- Corpus and benchmark documentation.
- How to add a new ablation.
- Honest limitations section: corpus size, English-only, EU-only, no biomedical reasoning.

### 5.4 Attribution
- EMA content: reproduced under EMA's terms (source acknowledged).
- Document that the benchmark is derivative of public EMA text; users must cite both the benchmark and EMA.

---

## Success criteria for v1

- Corpus: ≥ 200 Q&As extracted, ≥ 3 topics covered.
- Benchmark: ≥ 30 questions, stratified T1–T4, SME-reviewed.
- Harness: runs end-to-end on a single laptop, reproducible from a config.
- Ablations: three completed with metrics per question type.
- Writeup: blog post + README shipped.
- Usable by someone else: a fresh clone + ≤ 30 min setup runs the baseline.

## What's explicitly deferred to v2+

- EPARs.
- Ontology (IDMP/SPOR) — only if a benchmark failure demands entity linking.
- Graph RAG (Neo4j) — only if Ablation B fails to close the T3 gap.
- Biomedical/clinical questions beyond regulatory.
- Multilingual (OPUS EMEA as a hook).
- SME ablations at the corpus-curation layer that require >1 expert (this is a personal project; simulate with "naive SME" vs "careful SME" versions authored by you).

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Too few extractable Q&As | Phase 0 go/no-go; fallback scope is structured guidance-document Q&A sections. |
| **Training-data contamination of benchmark items** | **Phase 2.5 contamination screen; closed-book-vs-open-book reporting; prefer post-cutoff and composite items. See `docs/LEAKAGE.md`.** |
| Benchmark too small to detect differences | Bootstrap confidence intervals; report effect sizes, not just point estimates; aim for ≥ 30 items. |
| LLM judge is unreliable | Use two different judges; report agreement; hand-grade a 20% sample. |
| Results look like noise | Pre-register expected directions per ablation; stay honest if null results arise — null results are still a contribution. |
| Scope creep back into ontology/graph | ROADMAP deferral list is the commitment device. Anything deferred can only come back if a specific failure mode justifies it. |

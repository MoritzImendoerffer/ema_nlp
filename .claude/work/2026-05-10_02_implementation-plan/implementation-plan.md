# EMA RAG Benchmark — Implementation Plan

**Date:** 2026-05-10  
**Phase at time of planning:** Phase 0 (scoping)  
**Total tasks:** 36 | **Claude tasks:** 23 | **SME (user) tasks:** 7 | **Collaborative:** 6

### Framework decisions (2026-05-15)

| Concern | Decision |
|---------|---------|
| Retrieval framework | **LlamaIndex** — `DocumentSummaryIndex` for document-tree memory, `NodeRelationship` for cross-refs, `ReActAgent` for Ablation B |
| Tracing | **Arize Phoenix + OpenInference** — model-agnostic, self-hosted, wired at TASK-020 before first baseline run |
| Ontology | **Node metadata only** (TASK-016.5) — IDMP concepts as metadata filters; no graph DB; foundation for v2+ graph-RAG |
| Raw backends | Unchanged — FAISS, sentence-transformers, rank-bm25 all used via LlamaIndex wrappers |

See `.claude/work/2026-05-15_04_agentic-memory-architecture/exploration.md` for the full rationale.  
Tasks modified: TASK-016, TASK-017, TASK-020, TASK-027. Task added: TASK-016.5. state.json is authoritative.

---

## Team division of labour

| Who | Does what |
|-----|-----------|
| **Claude** | All code: extractors, harness, retrieval, evaluation, agents, ablation runners, reporting |
| **You (SME)** | All domain knowledge: acronym dictionary, relevance rubric, benchmark question authoring, trajectory labeling, few-shot exemplars, quality review |
| **Both** | Go/no-go decisions, sanity checks, report review |

**Handoff protocol:** Every collaborative task has a clear "Claude produces X → you do Y → Claude integrates Z" structure. You can drop in at any point by reading the task's acceptance criteria in `state.json` and checking what Claude has already produced in the relevant directory.

---

## Architecture overview

```
ema_nlp/
├── corpus/
│   ├── extractors/
│   │   ├── html_extractor.py   # TASK-005
│   │   └── pdf_extractor.py    # TASK-006
│   ├── build_corpus.py         # TASK-007
│   ├── corpus.jsonl            # TASK-008 output
│   ├── SCHEMA.md
│   └── corpus_stats.md
├── benchmark/
│   ├── candidates/             # Claude-generated candidates for SME review
│   ├── validate_benchmark.py   # TASK-014
│   ├── benchmark.jsonl
│   └── SCHEMA.md
├── harness/
│   ├── embed.py                # TASK-016
│   ├── retrieve.py             # TASK-017 (dense + BM25 hybrid)
│   ├── eval_retrieval.py       # TASK-018
│   ├── judge.py                # TASK-019
│   ├── run_eval.py             # TASK-020 (single entry point)
│   ├── models.py               # TASK-032
│   ├── agents/
│   │   └── react_agent.py      # TASK-027
│   ├── ablations/
│   │   ├── a1_query_expansion.py
│   │   ├── a2_topic_filter.py
│   │   ├── a3_reranker.py
│   │   └── a4_reranker.py
│   ├── configs/
│   │   ├── baseline_a0.yaml
│   │   ├── baseline_a0plus.yaml
│   │   └── ablation_*.yaml
│   ├── judges/
│   │   ├── faithfulness.md
│   │   └── correctness.md
│   └── prompts/
│       ├── few_shot_examples.md    # SME-authored
│       ├── relevance_rubric_sme.md # SME-authored
│       └── relevance_rubric_generic.md
├── ablations/
│   ├── A_evidence_filter/
│   │   ├── acronym_dict.yaml   # SME-authored
│   │   └── FINDINGS.md
│   ├── B_process_rewards/
│   │   ├── trajectory_labels.jsonl  # SME-labeled
│   │   └── FINDINGS.md
│   └── C_prompting_matrix/
│       └── FINDINGS.md
├── results/
│   ├── baseline/
│   ├── ablation_a/
│   ├── ablation_b/
│   ├── ablation_c/
│   └── contamination/
├── docs/
│   ├── training_data_verification.md
│   └── blog_post.md
└── scripts/
    ├── phase0_inventory.py
    ├── phase0_topic_report.py
    └── phase0_scope_decision.ipynb
```

---

## Critical path

```
P0: Inventory → Stratification → Go/No-Go
    ↓
P1: Setup → HTML Extractor ─┐
           → PDF Extractor  ├→ Dedup → Corpus (TASK-008)
                            ┘
    ↓ (parallel from TASK-008)
┌─────────────────────────────────────┐
│ P1.5: Contamination check           │ (informs benchmark curation)
│ P2: Benchmark construction          │ (4 question types + validation)
│ P3-setup: Embedding + retrieval     │ (can start before benchmark done)
└─────────────────────────────────────┘
    ↓ (all three must complete)
P3: Baseline run (A0 + A0+)
    ↓
┌───────────────────────┬─────────────────────┐
│ Ablation A (4A)       │ Ablation C (4C)     │
│ SME dict + reranker   │ SME few-shot + grid  │
└───────────────────────┘                     │
    ↓ (A must finish first — B uses A's best) │
│ Ablation B (4B)                             │
│ ReAct agent + labeling                      │
└─────────────────────────────────────────────┘
    ↓ (all ablations done)
P5: Blog post → README → Release
```

---

## Phase 0 — Scoping (current phase)

### TASK-001 · MongoDB Q&A inventory · Claude · 2h
Query `ema_scraper.web_items` for accordion Q&A pages and Q&A-pattern PDF URLs. Output a CSV with `url, type, topic_path, q_count_estimate, last_updated, revision_number`. Print source counts by type.

### TASK-002 · Topic stratification + cross-ref chain completeness · Claude · 3h
Group sources by topic_path. Identify ≥3 clusters. Extract cross-reference pattern counts. Verify what fraction of referenced Q&As are in-corpus (chain completeness %). Output `scripts/phase0_topic_report.md`.

**Depends on:** TASK-001

### TASK-003 · Go/no-go decision notebook · Collaborative · 2h
Claude generates `scripts/phase0_scope_decision.ipynb` with plots. **You fill in the Decision cell: GO / NO-GO + rationale.** Commit with decision before Phase 1 begins.

**Depends on:** TASK-002  
**Gate:** Nothing in Phase 1 starts until this is committed with a GO decision.

---

## Offline work plan (2026-05-17, no MongoDB)

MongoDB is temporarily unavailable. The tasks below can be completed now; they either have no DB dependency or replace it with a direct HTTP fetch. TASK-007 (MongoDB adaptor) and TASK-008 (full corpus) remain blocked until the DB is back.

### Critical path (offline)
```
TASK-007A  →  TASK-007B  →  TASK-016  →  TASK-017
(dedup logic)  (mini-corpus)  (embed+FAISS)  (BM25+hybrid)
```

### TASK-007A · build_corpus.py pure logic · Claude · 2h · **available now**
Source-agnostic orchestrator: `build_corpus(records: Iterable[QARecord], output_path) → CorpusStats`. Hash dedup (prefers PDF), landing-page filter, JSONL write, dedup/filter logs. No pymongo import. Tests on fixture data only.

### TASK-007B · Mini-corpus HTTP fetcher · Claude · 1h · **depends on TASK-007A**
`scripts/fetch_mini_corpus.py` downloads 10 curated EMA Q&A pages from `phase0_inventory.csv` via httpx (1s polite delay). Runs html_extractor, feeds build_corpus → writes `corpus/mini_corpus.jsonl`. Target: ≥80 Q&As across ≥3 topic paths. Idempotent. mini_corpus.jsonl gitignored.

### TASK-007 · MongoDB adaptor · Claude · 2h · **blocked (needs DB)**
`corpus/sources/mongo_source.py`: thin iterator that fetches web_items documents and yields QARecord objects. Wires into build_corpus → corpus/corpus.jsonl. Gated until MongoDB is available.

### TASK-016 · LlamaIndex embed.py + FAISS · Claude · 3–4h · **depends on TASK-007B**
Same as original spec but driven from `mini_corpus.jsonl` (not full corpus.jsonl). Re-index from corpus.jsonl after TASK-008. See Phase 3 for full acceptance criteria.

### TASK-017 · BM25 + hybrid RRF · Claude · 2h · **depends on TASK-016**
Same as original spec. Testable against mini-corpus index.

---

## Phase 1 — Corpus (≈1 week evenings)

### TASK-004 · Project setup · Claude · 2h
pyproject.toml with pinned deps. Directory tree. SCHEMA.md files. ruff/mypy/pytest passing.

**Depends on:** TASK-003 (GO decision)

### TASK-005 · HTML accordion extractor · Claude · 3h
Reuses `ema_parser.py::_parse_accordion`. Q/A splitting, confidence flags, topic_path from URL. Tests on ≥3 real accordion fixtures.

**Depends on:** TASK-004

### TASK-006 · PDF Q&A extractor · Claude · 4h
PyMuPDF4LLM + regex on numbered headings. Revision history parsing. cross_refs from "see Q&A N". Tests with nitrosamine Q&A PDF fixture.

**Depends on:** TASK-004

### TASK-007A · build_corpus.py pure logic · Claude · 2h
Source-agnostic core. See "Offline work plan" section above.

**Depends on:** TASK-005, TASK-006

### TASK-007B · Mini-corpus HTTP fetcher · Claude · 1h
Direct HTTP fetch of 10 EMA pages → mini_corpus.jsonl. Dev fixture for Phases 3+.

**Depends on:** TASK-007A

### TASK-007 · MongoDB adaptor · Claude · 2h · BLOCKED
Thin iterator over ema_scraper.web_items; yields QARecords into build_corpus.

**Depends on:** TASK-007A; blocked until MongoDB available

### TASK-008 · Corpus manifest · Claude · 2h
Writes `corpus.jsonl`. Validates schema. Generates `corpus_stats.md`. **Must hit ≥200 records across ≥3 topic paths or script halts with SCOPE-RISK.**

**Depends on:** TASK-007

---

## Phase 1.5 — Contamination baseline (≈1 afternoon)

### TASK-009 · Dolma 3 / Common Corpus verification · Claude · 3h
5-10 sentences per source doc searched in Dolma 3 + Common Corpus. Per-doc status (present/absent/partial) written to `docs/training_data_verification.md`.

**Depends on:** TASK-008  
**Gate:** TASK-010–013 do not start until this completes — contamination status informs which questions are safe to include.

---

## Phase 2 — Benchmark construction (≈1 week)

### TASK-010 · T1 Lookup questions · Collaborative · 3h
Claude generates 30 candidates + 2 paraphrases each. **You select 20, validate gold_answer accuracy.** Final items → `benchmark.jsonl`.

**Depends on:** TASK-008, TASK-009

### TASK-011 · T2 Scoping questions · SME-led · 4h
**You author 10 scoping questions** pairing topically-adjacent Q&As. Claude validates schema and adds paraphrases.

**Depends on:** TASK-008, TASK-009

### TASK-012 · T3 Multi-hop questions · Collaborative · 3h
Claude enumerates valid cross_ref chains and produces `t3_chain_map.md`. **You compose 10 questions** that require traversing those chains. Claude validates.

**Note:** T3 target is 10 questions, contingent on sufficient complete chains in corpus. If TASK-008 shows fewer than 10 complete chains across ≥2 topic clusters, reduce target to what the data supports and document in `corpus_stats.md`.

**Depends on:** TASK-008, TASK-009, TASK-002

### TASK-013 · T4 Synthesis questions · SME-led · 3h
**You hand-curate ≥5 synthesis questions** combining ≥2 Q&As from different docs. Include ≥2 composite/counterfactual items for contamination resistance.

**Depends on:** TASK-008, TASK-009

### TASK-014 · Benchmark finalisation + validation script · Claude · 2h
`benchmark/validate_benchmark.py` checks: no duplicate bench_ids, all gold_qa_ids in corpus, paraphrases present, T1=20/T2=10/T3=10/T4≥5.

**Depends on:** TASK-010, TASK-011, TASK-012, TASK-013

### TASK-015 · Closed-book contamination screen · Claude · 3h
Runs all models closed-book on full benchmark. Slot-guessing test on 10-item subsample. Tags `zero_shot_known` flags per model per item.

**Depends on:** TASK-014

---

## Phase 3 — Baseline RAG + harness (≈1 week)

### TASK-016 · Embedding pipeline + FAISS vector store · Claude · 3h
BGE-large-en embeddings. FAISS flat index. Dense retrieval returning (qa_id, score) in <100ms.

**Depends on:** TASK-007B (mini-corpus sufficient for dev/test). Full re-index from corpus.jsonl after TASK-008.

### TASK-017 · BM25 hybrid retrieval · Claude · 2h
rank-bm25 on Q&A text. RRF fusion for A0+ (hybrid). Both modes configurable.

**Depends on:** TASK-016

### TASK-018 · Evaluation harness — retrieval metrics · Claude · 3h
Recall@k, Precision@k, Citation Accuracy per item, broken down by T1-T4. Grouped bar chart output.

**Depends on:** TASK-017

### TASK-019 · LLM judge — Faithfulness + Correctness · Claude · 3h
Judge prompts as files. Different model than generator. Agreement validation on 20% hand-graded sample.

**Depends on:** TASK-018

### TASK-020 · Config-as-code + results logging · Claude · 2h
Single `run_eval.py` entry point. YAML-driven. Results in `results/<run_id>/` with config copy.

**Depends on:** TASK-018, TASK-019

### TASK-021 · Baseline run (A0 + A0+) + results report · Claude · 2h
Full run. `results/baseline/baseline_report.md` with all 5 metrics × T1-T4, open-book + closed-book, lift. **This commits the fixed reference for all ablations.**

**Depends on:** TASK-015, TASK-020

---

## Phase 4A — Ablation A: Evidence filtering (≈1-1.5 weeks)

### TASK-022 · SME acronym dictionary · SME · 4h
**You write `ablations/A_evidence_filter/acronym_dict.yaml`** with ≥30 entries. Must include AI=Acceptable Intake disambiguation. Claude integrates into query expansion.

**Depends on:** TASK-008 (can be authored any time after corpus — EMA vocabulary is known independently of benchmark results; baseline helpful but not a hard requirement)

### TASK-023 · A1 query expansion + A2 topic-path filter · Claude · 2h
A2 topic filter has two modes: (a) topic_path keyword filter, (b) IDMP concept metadata filter via `filter_by_concept()` from TASK-016.5.

**Depends on:** TASK-022, TASK-016.5

### TASK-024 · SME relevance rubric · SME · 2h
**You write `harness/prompts/relevance_rubric_sme.md`** (~200 words). Defines relevant vs non-relevant for EMA Q&A reranking.

**Depends on:** TASK-008 (can be authored any time after corpus — rubric is domain knowledge; baseline helpful but not a hard requirement)

### TASK-025 · A3/A4 LLM reranker · Claude · 3h
**Depends on:** TASK-024

### TASK-026 · Run A0-A5 + Ablation A analysis · Claude · 3h
All 6 variants run. A3 vs A4 comparison. `FINDINGS.md` written.

**Depends on:** TASK-023, TASK-025

---

## Phase 4B — Ablation B: Process-reward agent (≈1 week)

### TASK-027 · ReAct agent + 4 tools · Claude · 4h
**Depends on:** TASK-020, TASK-026 (uses A's best retriever)

### TASK-027.8 · CLI rating UI + Phoenix annotation posting · Claude · 1h
After each agent run, prompt for 1–5 rating + optional per-step labels. Post to Phoenix annotation API. Update query cache sidecar.

**Depends on:** TASK-027

### TASK-027.7 · Runtime few-shot injection · Claude · 2h
Fetch top-k rated trajectories (≥4/5) for similar past queries from query cache; inject into agent system prompt as few-shot block. Requires rated interactions to exist.

**Depends on:** TASK-027.5, TASK-027, TASK-027.8 (ratings must exist before injection logic has anything to retrieve)

### TASK-028 · B1 sanity check · Collaborative · 2h
Claude runs B1 on 5 questions. **You review trajectories** and decide: proceed to B3 labeling or drop to B4 tool descriptions.

**Depends on:** TASK-027

### TASK-029 · SME trajectory labeling · SME · 4h (conditional)
**Only if B1 sanity check passes.** **You label ≥50 trajectory steps** as good/suboptimal/wrong. Skipped → only B4 runs.

**Depends on:** TASK-028

### TASK-030 · Run Ablation B variants + analysis · Claude · 3h
Read `ablations/B_process_rewards/SANITY_CHECK.md` first to determine which variants apply. If B3 was skipped, run B0/B1/B2/B4 only.

**Depends on:** TASK-028 (always), TASK-029 (if not skipped)

---

## Phase 4C — Ablation C: Prompting matrix (≈1 week, independent of B)

### TASK-031 · SME few-shot exemplars · SME · 3h
**You write `harness/prompts/few_shot_examples.md`** with 3-5 Q&A solving traces, covering T1/T2/T3. Held-out Q&As only (not in benchmark).

**Depends on:** TASK-021

### TASK-032 · OLMo 3 API + three model tiers · Claude · 2h
**Depends on:** TASK-020

### TASK-033 · 3×3 grid runs + analysis · Claude · 4h
All 9 cells. Row-pattern consistency chart. OlmoTrace on 5 OLMo 3 answers. `FINDINGS.md` written.

**Depends on:** TASK-031, TASK-032

---

## Phase 5 — Writeup + release (≈1 week)

### TASK-034 · Blog post draft · Collaborative · 4h
Claude drafts from `project_roadmap/BLOG_OUTLINE.md`. **You revise.** ~2000-2500 words with contamination caveats section.

**Depends on:** TASK-026, TASK-030, TASK-033

### TASK-035 · README + final repo structure · Claude · 3h
Follows `project_roadmap/README_OUTLINE.md`. Fresh-clone quickstart ≤30 min. Honest limitations. CC-BY-4.0 + MIT licensing.

**Depends on:** TASK-034

---

## Effort summary

| Phase | Claude hours | SME hours | Total |
|-------|-------------|-----------|-------|
| 0: Scoping | 5h | 1h (decision) | 6h |
| 1: Corpus | 13h | — | 13h |
| 1.5: Contamination | 3h | — | 3h |
| 2: Benchmark | 8h | 11h | 19h |
| 3: Baseline RAG | 15h | — | 15h |
| 4A: Ablation A | 8h | 6h | 14h |
| 4B: Ablation B | 9h | 4h | 13h |
| 4C: Ablation C | 9h | 3h | 12h |
| 5: Writeup | 7h | 2h (review) | 9h |
| **Total** | **77h** | **27h** | **104h** |

---

## SME tasks at a glance (your to-do list)

| Task | What you do | When |
|------|-------------|------|
| TASK-003 | Fill in Go/No-Go decision cell in notebook | After P0 |
| TASK-010 | Review 30 T1 candidates, select 20, validate gold answers | After corpus |
| TASK-011 | Author 10 T2 scoping questions | After corpus |
| TASK-012 | Compose 10 T3 multi-hop questions from chain map | After corpus |
| TASK-013 | Hand-curate ≥5 T4 synthesis questions | After corpus |
| TASK-022 | Write acronym dictionary YAML (≥30 entries) | After baseline |
| TASK-024 | Write SME relevance rubric (~200 words) | After baseline |
| TASK-028 | Review 5 B1 trajectories, decide on labeling | After agent built |
| TASK-029 | Label ≥50 trajectory steps (if B1 passes) | After sanity check |
| TASK-031 | Write 3-5 few-shot exemplars | After baseline |
| TASK-034 | Review and revise blog post draft | After all ablations |

---

## How to resume work in any session

1. Read `.claude/work/2026-05-10_02_implementation-plan/state.json` → check `next_available`
2. Run `/next` to pick up the next pending task
3. Or: tell Claude "continue TASK-XXX" with any task id

All SME tasks are clearly marked `"owner": "sme"` in state.json — Claude will produce scaffolding/candidates and wait for your input before proceeding.

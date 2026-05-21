# Baseline Report: A0 + A0+

**Date:** 2026-05-21  
**Benchmark:** `benchmark/benchmark.jsonl` (45 items: T1=20, T2=10, T3=10, T4=5)  
**Corpus:** `~/Nextcloud/Datasets/ema_nlp/corpus/corpus.jsonl` (26,251 Q&A records)  
**Embedding model:** BAAI/bge-large-en-v1.5  
**k:** 10  

---

## A0 — Dense retrieval only (VectorStoreIndex)

| Type | n | Recall@k | Precision@k | Citation Acc. |
|------|---|----------|-------------|---------------|
| T1   | 20 | 0.900    | 0.092       | 0.950         |
| T2   | 10 | 0.500    | 0.060       | 0.800         |
| T3   | 10 | 0.700    | 0.142       | 1.000         |
| T4   | 5  | 0.333    | 0.080       | 0.633         |
| **overall** | **45** | **0.704** | **0.095** | **0.893** |

---

## A0+ — Hybrid retrieval (dense + BM25 via RRF)

| Type | n | Recall@k | Precision@k | Citation Acc. |
|------|---|----------|-------------|---------------|
| T1   | 20 | 0.850    | 0.085       | 0.950         |
| T2   | 10 | 0.700    | 0.080       | 0.900         |
| T3   | 10 | 0.800    | 0.160       | 1.000         |
| T4   | 5  | 0.333    | 0.080       | 0.533         |
| **overall** | **45** | **0.748** | **0.100** | **0.904** |

---

## Side-by-side + Lift (A0+ − A0)

| Type | A0 Recall | A0+ Recall | Recall Δ | A0 Cit.Acc | A0+ Cit.Acc | Cit.Acc Δ |
|------|-----------|------------|----------|------------|-------------|-----------|
| T1   | 0.900     | 0.850      | **−0.050** | 0.950   | 0.950       | 0.000     |
| T2   | 0.500     | 0.700      | **+0.200** | 0.800   | 0.900       | +0.100    |
| T3   | 0.700     | 0.800      | **+0.100** | 1.000   | 1.000       | 0.000     |
| T4   | 0.333     | 0.333      | 0.000    | 0.633      | 0.533       | −0.100    |
| **overall** | 0.704 | 0.748 | **+0.044** | 0.893 | 0.904 | +0.011 |

---

## Key observations

### What works well
- **T1 Lookup**: Dense (A0) achieves 90% Recall@10 and 95% Citation Accuracy — single-source lookups are reliably retrieved by embedding similarity.
- **T3 Multi-hop**: Both methods achieve Citation Accuracy = 1.000, meaning the correct source documents are always in top-10 even when specific qa_ids are partially missed.
- **Hybrid boosts T2 and T3**: BM25 adds significant lift on T2 scoping (+20pp Recall) and T3 multi-hop (+10pp Recall), suggesting keyword matching helps when questions use procedure-specific terminology (e.g., "Article 31 pharmacovigilance" vs "Article 31 non-pharmacovigilance").

### Where retrieval struggles
- **T4 Synthesis**: Both methods achieve only 33% Recall@10 on T4 items (5 items). T4 questions span multiple source documents — the dense retriever tends to surface the most similar single document but misses cross-document gold pairs. This is the primary opportunity for improvement in ablations.
- **T1 slight regression in A0+**: Hybrid RRF slightly hurts T1 (−5pp). This is expected — BM25 injects noise for short, keyword-sparse factual questions.
- **Precision is low overall** (~10%): With k=10 retrievals and 1–4 gold qa_ids per item, this is structurally expected. Precision will be more meaningful at smaller k values (e.g., k=3).

### Contamination context
- `zero_shot_known` not yet populated — contamination screen (`harness/contamination_screen.py`) must be run separately with configured LLM endpoints.
- Contamination sensitivity analysis: see `results/contamination/` after screen runs.
- 28/45 benchmark items (62%) use specific numeric thresholds resistant to memorization; 5/45 (11%) are composite T4 items not found in any single source document.

---

## Reference for ablations

These A0/A0+ numbers are the **fixed reference baseline** for all ablation comparisons.

| Ablation | Expected direction | Target metric |
|----------|-------------------|---------------|
| A1 query expansion (acronyms) | +T2, +T3 | Recall@10 |
| A2 topic-path filter | +T2 | Precision@10 |
| A3/A4 LLM reranker (SME/generic rubric) | +T4 | Citation Accuracy |
| B (ReAct agent) | +T3 | Recall@10 |
| C (prompting matrix) | All types | Judge scores |

Ablation reports are committed separately as they complete.

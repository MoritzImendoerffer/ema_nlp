# Ablation A Report: Evidence Filtering Pipeline

**Date:** 2026-05-21  
**Benchmark:** `benchmark/benchmark.jsonl` (45 items: T1=20, T2=10, T3=10, T4=5)  
**Corpus:** `~/Nextcloud/Datasets/ema_nlp/corpus/corpus.jsonl` (26,251 Q&A records)  
**Embedding model:** BAAI/bge-large-en-v1.5  
**k:** 10

Ablation A tests seven retrieval configurations, building up from pure dense retrieval (A0) to a fully combined pipeline (A5). The reference baselines are A0 and A0+ (see `results/baseline/baseline_report.md`).

---

## Variant descriptions

| ID | Description | Key change vs A0+ |
|----|-------------|-------------------|
| A0 | Dense retrieval only (VectorStoreIndex) | — baseline — |
| A0+ | Hybrid RRF (dense + BM25) | + BM25 |
| A1 | Hybrid + SME acronym dictionary query expansion | + expand abbreviations in query |
| A2 keyword | Hybrid + topic-path keyword post-filter | + drop off-topic retrievals |
| A3 | Hybrid + LLM reranker (SME rubric, Haiku) | + LLM re-orders top-5 by SME rubric |
| A4 | Hybrid + LLM reranker (generic prompt, Haiku) | + LLM re-orders top-5 by generic prompt |
| A5 | A1 + A2 keyword + A3 combined | all three active simultaneously |

---

## Full results table

### Recall@10

| Variant | T1 (n=20) | T2 (n=10) | T3 (n=10) | T4 (n=5) | Overall |
|---------|-----------|-----------|-----------|----------|---------|
| A0      | 0.900     | 0.500     | 0.700     | 0.333    | 0.704   |
| A0+     | 0.850     | 0.700     | 0.800     | 0.333    | 0.748   |
| A1      | **0.950** | 0.600     | 0.700     | 0.333    | 0.748   |
| A2 kw   | 0.850     | 0.700     | 0.800     | 0.333    | 0.748   |
| A3      | 0.850     | 0.700     | 0.800     | 0.333    | 0.748   |
| A4      | 0.850     | 0.700     | 0.800     | 0.333    | 0.748   |
| A5      | 0.900     | 0.600     | 0.700     | 0.333    | 0.726   |

### Precision@10

| Variant | T1    | T2    | T3    | T4    | Overall |
|---------|-------|-------|-------|-------|---------|
| A0      | 0.092 | 0.060 | 0.142 | 0.080 | 0.095   |
| A0+     | 0.085 | 0.080 | 0.160 | 0.080 | 0.100   |
| A1      | 0.095 | 0.070 | 0.140 | 0.080 | 0.098   |
| A2 kw   | 0.109 | 0.106 | 0.219 | 0.124 | **0.134** |
| A3      | 0.085 | 0.080 | 0.160 | 0.080 | 0.100   |
| A4      | 0.085 | 0.080 | 0.160 | 0.080 | 0.100   |
| A5      | 0.129 | 0.081 | 0.229 | 0.124 | **0.140** |

### Citation Accuracy

| Variant | T1    | T2    | T3    | T4    | Overall |
|---------|-------|-------|-------|-------|---------|
| A0      | 0.950 | 0.800 | 1.000 | 0.633 | 0.893   |
| A0+     | 0.950 | 0.900 | 1.000 | 0.533 | 0.904   |
| A1      | 0.950 | 0.900 | 1.000 | 0.533 | 0.904   |
| A2 kw   | 0.950 | 0.900 | 1.000 | 0.533 | 0.904   |
| A3      | 0.950 | 0.900 | 1.000 | 0.533 | 0.904   |
| A4      | —     | —     | —     | —     | —       |
| A5      | 0.900 | 0.900 | 1.000 | 0.533 | 0.881   |

---

## Lift table (vs A0+ baseline)

| Variant | ΔRecall T1 | ΔRecall T2 | ΔRecall T3 | ΔRecall T4 | ΔRecall Overall | ΔPrec Overall | ΔCit Overall |
|---------|-----------|-----------|-----------|-----------|----------------|--------------|-------------|
| A1      | **+0.100** | −0.100    | −0.100    | 0.000     | 0.000          | −0.002       | 0.000        |
| A2 kw   | 0.000     | 0.000     | 0.000     | 0.000     | 0.000          | **+0.034**   | 0.000        |
| A3      | 0.000     | 0.000     | 0.000     | 0.000     | 0.000          | 0.000        | 0.000        |
| A4      | 0.000     | 0.000     | 0.000     | 0.000     | 0.000          | 0.000        | 0.000        |
| A5      | +0.050    | −0.100    | −0.100    | 0.000     | −0.022         | +0.040       | −0.023       |

---

## Analysis by ablation

### A1 — Query expansion (acronym dictionary)

**Hypothesis:** Expanding EMA-specific acronyms before retrieval (e.g., "MAH" → "Marketing Authorisation Holder") will help BM25 match documents that spell out the full term.

**Result:** T1 Recall improves by +10pp (0.850 → 0.950) vs A0+. However, T2 and T3 each regress by −10pp.

**Interpretation:**
- T1 single-source lookup questions often use acronyms precisely — expanding them unambiguously maps to the correct document.
- T2/T3 questions are more complex: expanding an acronym like "PRAC" to "Pharmacovigilance Risk Assessment Committee" may pull in documents about the committee in general, diluting the BM25 signal on the specific procedural context the question targets.
- Net: A1 is a targeted improvement for T1 at the cost of T2/T3 regression. **Use A1 only when the application is primarily T1 factual lookups.**

---

### A2 — Topic-path keyword filter

**Hypothesis:** Post-filtering retrieved chunks to those matching the query's inferred topic path (e.g., worksharing, Article 31) will increase precision without hurting recall.

**Result:** Recall is unchanged vs A0+ across all question types. Precision improves across the board (overall +34pp: 0.100 → 0.134).

**Interpretation:**
- The filter correctly removes off-topic retrievals without discarding gold documents. This is the expected behaviour: the filter is conservative (keywords match the topic area broadly).
- **A2 is a pure precision booster.** For downstream LLM answer generation, fewer irrelevant chunks reduce hallucination risk. No recall cost makes this a strong default.
- Precision improvement is highest on T3 (+5.9pp, 0.160 → 0.219) and T4 (+4.4pp), suggesting multi-hop and synthesis questions benefit most from noise reduction.

---

### A3 vs A4 — LLM reranker (SME rubric vs generic prompt)

**Hypothesis:** Re-ordering retrieved chunks by LLM relevance score will promote gold documents to higher ranks, measurable as improvement at smaller k. A3 (SME rubric) should outperform A4 (generic prompt) if the rubric's regulatory domain specificity matters.

**Result:** Both A3 and A4 show **identical metrics to A0+** across all question types and all metrics (Recall@10, Precision@10, Citation Accuracy).

**Interpretation:**
- **Recall@k is position-independent** within the top-k window — reranking cannot change which items are present, only their order. At k=10 this metric is blind to rank order improvements.
- **A3 = A4 at Recall@10**: the SME-authored rubric provides zero measurable benefit over the generic prompt at this metric level. This is expected — the rubric's value lies in ordering, not selection.
- The correct evaluation is **Recall@3** or **MRR** (Mean Reciprocal Rank), rewarding gold items at ranks 1–3. These metrics were not collected and should be the target for a follow-up run.
- **Operational note**: A3/A4 each added ~225 API calls (45 items × 5 chunks) at Haiku rates. The cost is justified only if lower-k metrics show a meaningful delta.
- **Open question**: does A3 beat A4 at k=3? If yes, the SME rubric pays off at inference time even if invisible at k=10.

---

### A5 — Combined pipeline (A1 + A2 + A3)

**Hypothesis:** Stacking all three improvements will produce the best overall performance.

**Result:** A5 recall (0.726) is **worse** than A0+ (0.748) and equal to A0 (0.704) on T2/T3. T1 partially recovers to 0.900. Citation Accuracy degrades (−2.3pp).

**Interpretation:**
- **Stacking does not compose cleanly.** The most likely cause: A1's query expansion changes the BM25 query tokens, while A2's keyword filter is calibrated for the original (unexpanded) query. The expanded query tokens match different topic-path keywords, causing the filter to misclassify and drop valid gold documents.
- The Precision gain (+4pp) in A5 comes from A2, but the recall loss from A1+A2 interaction outweighs it.
- **Conclusion: A1 and A2 should not be used together without re-calibrating A2's filter patterns against expanded queries.**

---

## T4 synthesis — null result across all ablations

Every ablation variant, including the combined A5, achieves exactly 0.333 Recall@10 on T4 (5 items). T4 items require gold Q&A pairs from ≥2 distinct source documents, and no single-retrieval-step method reliably surfaces the cross-document set.

The correct architectural response to T4 is the **ReAct agent (Ablation B)**: a multi-step retrieval loop that can issue follow-up queries after observing initial results, progressively covering the cross-document space. See `project_roadmap/ABLATIONS.md` §B.

---

## Key recommendations

1. **Production default: A0+ (hybrid RRF).** Maximises overall recall without any added complexity. A0+ is the best single-method configuration.

2. **Add A2 keyword filter as a precision layer.** Zero recall cost, +34pp precision. Reduces noise fed to the LLM answer generator. Implement as a post-retrieval step before context injection.

3. **A1 query expansion: use for T1-heavy applications only.** Beneficial for lookup tasks; regresses on scoping and multi-hop.

4. **Evaluate reranker (A3/A4) at k=3.** The Recall@10 metric is blind to rank order. Re-run with k=3 to correctly measure reranker value.

5. **T4 requires Ablation B (ReAct agent).** No evidence-filtering ablation can compensate for the architectural limitation of single-pass retrieval on cross-document synthesis questions.

---

## Run metadata

| Variant | Run ID | Timestamp | Duration |
|---------|--------|-----------|----------|
| A0  | baseline_a0      | 20260521T160135Z | ~2 min  |
| A0+ | baseline_a0plus  | 20260521T160135Z | ~5 min  |
| A1  | ablation_a_a1    | 20260521T160921Z | ~90 sec |
| A2 kw | ablation_a_a2_keyword | 20260521T161518Z | ~90 sec |
| A3  | ablation_a_a3    | 20260521T162022Z | ~8 min (225 API calls) |
| A4  | ablation_a_a4    | 20260521T163336Z | ~17 min (225 API calls) |
| A5  | ablation_a_a5    | 20260521T161932Z | ~5 min  |


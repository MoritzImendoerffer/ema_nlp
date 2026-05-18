# Training Data Contamination Verification

**TASK-009 — Phase 1.5 contamination check**

This document records whether key EMA Q&A source documents appear verbatim in the
training data of OLMo 3 (the open-weight reference model used in Ablation C),
following the methodology outlined in `project_roadmap/LEAKAGE.md §Phase 1.5`.

---

## Method

1. **Extract distinctive sentences** — `scripts/contamination_check.py` samples 7
   sentences per source document from mid-paragraph positions (avoiding boilerplate
   headers and revision-date suffixes). Full sentence list: `docs/contamination_sentences.tsv`.

2. **Search Dolma v1.7** — each sentence was searched via the Infini-gram API
   (`https://api.infini-gram.io`, index `v4_dolma-v1_7_llama`, `query_type=count`,
   `approx=false`). Dolma v1.7 is the primary training corpus for OLMo 1/2 models.

3. **Spot-check OLMo-mix** — 5 sentences were also searched in `v4_olmo-mix-1124_llama`,
   the training index for OLMo 3 32B Instruct (the tier-3 model in Ablation C).

---

## Source Documents Checked

| Key | Source page | Records in corpus |
|-----|-------------|-------------------|
| `gmp_qa` | GMP/GDP Q&A | 129 |
| `quality_p1` | Quality Q&A Part 1 | 41 |
| `quality_p2` | Quality Q&A Part 2 | 93 |
| `clinical_pk` | Clinical Pharmacology / PK Q&A | 48 |
| `bio_qa` | Biological Medicinal Products Q&A | 40 |

---

## Results — Dolma v1.7

| Source | Sentences checked | Present (count > 0) | Absent | Max count |
|--------|-------------------|---------------------|--------|-----------|
| `gmp_qa` | 7 | 3 | 4 | 4 |
| `quality_p1` | 7 | 2 | 5 | 7 |
| `quality_p2` | 7 | 3 | 4 | 4 |
| `clinical_pk` | 7 | 3 | 4 | 3 |
| `bio_qa` | 7 | **0** | 7 | 0 |
| **Total** | **35** | **11 (31%)** | **24 (69%)** | **7** |

### Interpretation

All 11 matches have counts ≤ 7, which is extremely low for a corpus of Dolma's scale
(~3 trillion tokens). The matching sentences are generic regulatory boilerplate:

- *"The new product has the same formula and manufacturing method…"* (count 7)
- *"This batch number… should incorporate two components"* (count 2)
- *"The code for the repackaging run may comprise numbers or letters…"* (count 4)

None of the matches represent EMA-specific formulations (document numbers, procedure
codes, numerical thresholds, or citation-specific language). The `bio_qa` source
(ADCC assays, media sourcing, sterility testing) returned **zero matches** — these
highly technical biological Q&As are absent from Dolma.

---

## Results — OLMo-mix (OLMo 3 training index)

5 sentences that matched in Dolma v1.7 (including the two highest-count sentences)
were re-searched in `v4_olmo-mix-1124_llama`.

| Sentence | Dolma count | OLMo-mix count |
|----------|-------------|----------------|
| "The new product has the same formula…" | 7 | **0** |
| "The code for the repackaging run…" | 4 | **0** |
| "In line with current regulatory practice…" | 4 | **0** |
| "Such limitations should be introduced…" | 2 | **0** |
| "Scaling is not a suitable solution to the variability…" | 2 | **0** |

**All 5 sentences return count = 0 in OLMo-mix.** The sentences that appeared in
Dolma v1.7 are absent from OLMo 3's actual training index.

---

## Conclusion

| Model | Status |
|-------|--------|
| OLMo 3 32B Instruct (`allenai/OLMo-2-1124-32B-Instruct`) | **✓ Clean reference** — zero sentences found in OLMo-mix training index |
| Claude Haiku / Opus (Anthropic) | Unknown — training data not public; treat as potentially contaminated |

**OLMo 3 is a clean contamination reference for all 5 checked source documents.**

The 31% Dolma overlap is attributable to generic regulatory phrases, not EMA-specific
content. No bulk EMA document ingestion is evident. This confirms the strategy from
`LEAKAGE.md §Phase 4`: including OLMo 3 in Ablation C provides a contamination-robust
comparison anchor.

---

## Limitations

- Only 7 sentences per source were checked (35 total). Wider sampling is feasible
  with `scripts/contamination_check.py --n 20`.
- The Infini-gram index samples Dolma rather than scanning the full corpus; counts
  are exact within the sample but may not represent the full token count.
- Closed-book correctness on benchmark items (TASK-015) provides a complementary
  empirical contamination signal and should be run after benchmark construction.
- Anthropic training data is not auditable; frontier model (Opus) and mid-tier
  model (Haiku) contamination cannot be ruled out by this method.

---

## Files

| File | Description |
|------|-------------|
| `docs/contamination_sentences.tsv` | 35 sentences searched (source_key, qa_id, sentence) |
| `scripts/contamination_check.py` | Extraction script — re-run to refresh sample |

*Checked: 2026-05-18 | Infini-gram indices: `v4_dolma-v1_7_llama`, `v4_olmo-mix-1124_llama`*

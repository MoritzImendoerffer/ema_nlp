# Exploration: Project Plan Soundness + Ontology Decision

**Date:** 2026-05-10  
**Inputs read:** ROADMAP.md, ABLATIONS.md, LEAKAGE.md, GLOSSARY.md  
**Web research:** MIRAGE, RAG-Gym, OLMo 3/OlmoTrace, Pistoia IDMP-O, OG-RAG, Medprompt→o1

---

## Verdict: The plan is sound

The project's design converges independently with current best practice in three areas where it could have gone wrong. Each is verified below.

---

## 1. Research validation — what the literature confirms

### MIRAGE as the eval template

MIRAGE (Xiong et al., ACL 2024) is published and well-cited. It demonstrates that corpus-choice and retrieval-strategy changes produce up to +18% accuracy swings — which directly motivates Ablation A. The benchmark structure (five datasets, per-question-type breakdown, MedRAG retriever ablations) is the right model for this project. The "18-point swing from corpus changes" cited in ABLATIONS.md is accurate.

There is a second, unrelated MIRAGE (NAACL 2025, general-domain Wikipedia QA), so the citation should specify "MIRAGE/MedRAG (Xiong et al., 2024)" to avoid ambiguity.

### RAG-Gym numbers

RAG-Gym (arxiv 2502.13957, Feb 2025) is real. The exact numbers in the roadmap are correct: ReAct baseline 41.09 F1 → 60.19 with full optimization on HotpotQA. A follow-up paper (May 2025: "Process vs. Outcome Reward") is now out and relevant to Ablation B — it directly compares process-reward vs outcome-reward supervision for agentic RAG. Worth reading before implementing B.

### Medprompt → o1 finding

Confirmed in the Microsoft Research paper (arxiv 2411.03590). Few-shot prompting degrades o1's performance on medical benchmarks. The Ablation C pre-registered predictions in ABLATIONS.md are accurately grounded in this finding. The comparison is somewhat domain-specific (medical exam QA), but the regulatory domain is at least as procedural, so the generalization is defensible.

### No existing EMA Q&A benchmark

Searches confirm the gap. The closest existing work is a "QA-RAG" chatbot for pharmaceutical regulatory compliance (FDA-focused, not EMA). One PMC paper (2025) evaluated RAG on drug information and clinical trial protocols. None targeted EMA Q&A specifically. The project's hook — "no public EMA Q&A benchmark" — holds.

### OLMo 3 / OlmoTrace

Confirmed available (Nov 2025): 7B and 32B variants, Dolma 3 training corpus is public and searchable, OlmoTrace traces model outputs to training-data spans in real time. The plan to use OLMo 3 as a contamination-measurable third model tier in Ablation C is technically feasible and methodologically valuable. DigitalOcean and Together AI host it cheaply.

---

## 2. Improvements and gaps

### Gap 1 — Hybrid retrieval missing from baseline

The Phase 3 baseline uses dense-only retrieval (BGE-large, top-k=5). For regulatory text with specific acronyms, numerical thresholds, and reference numbers, BM25/hybrid retrieval is well-established to outperform dense-only on exact-match queries. EMA content ("ICH Q3A", "26.5 ng/day", "EMA/409815/2020") will frequently hit this pattern.

**Recommendation:** Add a variant A0+ = A0 + BM25 hybrid to Ablation A. This costs essentially nothing (BM25 is free and fast) and gives you a cleaner separation between "does SME acronym expansion help beyond BM25?" vs "does dense-only need help?"

### Gap 2 — cross_refs chain completeness is untested

Phase 1.3 plans to extract `cross_refs` from EMA Q&A PDFs. But the multi-hop benchmark (T3) only works if the cross-referenced Q&A is actually in the corpus. If nitrosamine Q22 → Q20 → Q10, all three must be extracted. There is no explicit step in the roadmap to verify chain completeness.

**Recommendation:** Add to Phase 0 or Phase 1.3: for each discovered cross-ref, check whether the target Q&A is in the same source document (in-document chain) or points to a different document (cross-document chain). Count the proportion of chains where all hops are in-corpus. If >20% of T3-relevant chains have missing hops, the T3 benchmark may not be viable.

### Gap 3 — Benchmark schema missing `paraphrase` field

LEAKAGE.md recommends paraphrase variants for each benchmark item as a contamination diagnostic. The schema in Phase 2.3 does not include a `paraphrase` field.

**Recommendation:** Add to Phase 2.3 schema:
```json
"paraphrases": ["…alternative phrasing 1…", "…alternative phrasing 2…"]
```
Generate paraphrases with an LLM (one call per item), review manually, store alongside the canonical question. This is a 1-evening addition in Phase 2.

### Gap 4 — Phase 0 should capture `last_updated` per source

LEAKAGE.md section on Phase 0 notes this but the ROADMAP.md Phase 0 output spec does not include `last_updated` in the CSV. Recency is the cheapest contamination defense.

**Recommendation:** Add `last_updated` and `revision_number` to the Phase 0 CSV output spec. These come from the page metadata or PDF revision history and require no extra extraction effort — they should be harvested during the inventory.

### Gap 5 — Ablation B needs a weak-model sanity check before SME labeling

ABLATIONS.md flags the risk that "a weak model running ReAct can loop forever." The recommended mitigation is implicit. A failed Ablation B wastes 50–100 SME-labeled trajectory steps.

**Recommendation:** Insert an explicit gate before committing to SME labeling: run B1 (ReAct agent, no supervision) on 5 benchmark questions. Check trajectory quality manually. Only proceed to B3 SME labeling if the trajectories show coherent planning (even if the final answers are wrong). If the model can't form coherent search plans, drop to B4 (SME tool descriptions only).

### Minor: "MIRAGE" citation ambiguity

ABLATIONS.md and ROADMAP.md reference "MIRAGE +18pts from corpus changes" — this refers to the medical RAG MIRAGE (Xiong et al., 2024), not the unrelated NAACL 2025 general-domain benchmark of the same name. Add "Xiong et al., 2024" to distinguish.

---

## 3. Ontology question: Pistoia Alliance IDMP-O

### What it is (as of 2026)

The Pistoia Alliance IDMP Ontology (IDMP-O) is at v1.4 public (MIT license) and v1.5 member-only (Dec 2025). It covers all five ISO IDMP standards (11238, 11239, 11240, 11615, 11616) — substances, pharmaceutical products, packaged medicines, regulated authorizations. 43% of pharma companies plan to implement it. ISO TS 21405 (governance methodology) published July 2025.

**Critical constraint**: IDMP-O is a **T-box** (class definitions and relationships). It defines what a `MedicinalProduct` is and how it relates to `Substance` — but contains no instances of actual products, substances, or authorizations. The A-box (instances) lives in EMA's SPOR registries (SMS, PMS, OMS, RMS), which have public APIs.

### The case for adding it now — and why it fails

OG-RAG (Microsoft Research, EMNLP 2025) showed +55% recall and +40% correctness by grounding retrieval in domain ontologies. That result is compelling. The pharma knowledge graph literature confirms that ontology-grounded retrieval helps on entity-disambiguation tasks (exactly the T2 problem this project has).

However, making IDMP-O useful requires:
1. **The T-box** (IDMP-O ✅ — freely available)
2. **An A-box of EMA Q&A entities** — which substances, products, procedures, and authorizations each Q&A discusses (❌ does not exist, must be built)
3. **NER + entity linking** — extracting entity mentions from Q&A text and linking them to SPOR IDs (❌ deferred to v2+, significant engineering)
4. **A hypergraph or knowledge graph construction step** — to implement OG-RAG's method (❌ additional infrastructure)

Without step 2 and 3, IDMP-O is inert. You'd have a beautiful class hierarchy with no instances to put in it. The simpler proxy for T2 disambiguation — the topic_path metadata already in the corpus schema, plus the acronym dictionary from Ablation A — covers most of the same ground at a fraction of the cost.

### Verdict: Defer to v2+, as planned — but track the gateway condition

The current deferral is correct. Every layer of complexity must be justified by a specific benchmark failure, and T2 failures haven't happened yet (the benchmark isn't built). Adding ontology infrastructure now is anticipatory engineering against an unknown failure mode.

### The path toward it: when and how

**Gateway condition:** Introduce ontology when, after completing Ablation A (specifically variants A1+A2+A3), >30% of residual T2 scoping failures are attributable to entity-level disambiguation failures — i.e., the model retrieves Q&As about the right *topic* but the wrong *entity type* (e.g., retrieves a biological-product Q&A for a chemical-product question, or confuses substance-level with product-level scope).

If that condition is met, the implementation path is:

**Step 1 (v2 Phase 0'):** Scope the A-box. For the subset of Q&As causing T2 failures, extract entity mentions using an LLM (not full NER pipeline — just "what substance/product/procedure does this Q&A address?"). Map those mentions to SPOR IDs via the SPOR REST API. This is a targeted, bounded task, not a full ontology-loading exercise.

**Step 2 (v2 Phase 1'):** Load IDMP-O T-box into a lightweight triple store (e.g., rdflib, no Neo4j needed at this scale). Populate with the A-box entities from Step 1. This covers only the T2-failing Q&As, not the full corpus.

**Step 3 (v2 Phase 2'):** Implement OG-RAG's hypergraph retrieval (code at github.com/microsoft/ograg2) over the ontology-populated subset. Compare against Ablation A5 on T2 questions only. Measure Recall@5 and Correctness.

**Step 4:** If OG-RAG shows meaningful T2 improvement over A5, expand to the full corpus. If not, the failure is in entity linking quality, not in the ontology decision.

This incremental approach avoids loading the full SPOR registry (millions of records) and building a full pharma knowledge graph before knowing whether it helps.

**Note:** The IDMP-O v1.4 MIT-licensed ontology is worth downloading and reading now (just as documentation, not for implementation). The class hierarchy reveals what kinds of entity distinctions EMA Q&As make implicitly — useful background when authoring T2 benchmark questions. Understanding whether a Q&A addresses the `SubstanceDefinition` vs `PharmaceuticalProduct` vs `MedicinalProduct` level helps you write better scoping questions.

---

## Summary table

| Area | Verdict | Action |
|------|---------|--------|
| Overall plan soundness | ✅ Sound | No structural changes needed |
| MIRAGE methodology | ✅ Confirmed | Clarify citation to distinguish from NAACL 2025 MIRAGE |
| RAG-Gym numbers | ✅ Confirmed | Read May 2025 follow-up before implementing Ablation B |
| No existing EMA benchmark | ✅ Confirmed | Gap is real |
| OLMo 3 / OlmoTrace | ✅ Available | Proceed as planned in Ablation C |
| Hybrid BM25 baseline | ⚠️ Missing | Add A0+ variant to Ablation A |
| cross_refs chain completeness | ⚠️ Unverified | Add completeness check to Phase 0/1.3 |
| Paraphrase field in schema | ⚠️ Missing | Add to Phase 2.3 schema |
| last_updated in Phase 0 CSV | ⚠️ Missing | Add to Phase 0 output spec |
| Ablation B weak-model gate | ⚠️ Missing | Add explicit B1 sanity check before SME labeling |
| IDMP-O ontology now | ❌ Overkill | Defer; track gateway condition; download as background reading |
| Path toward ontology | — | Gateway: >30% T2 failures are entity-disambiguation; then OG-RAG on targeted subset |

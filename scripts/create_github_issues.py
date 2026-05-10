"""
Create all 35 GitHub issues for the EMA RAG Benchmark project using PyGithub.

Usage:
    GITHUB_TOKEN=ghp_xxx python3 scripts/create_github_issues.py

Get a token at: GitHub → Settings → Developer settings → Personal access tokens → Fine-grained
Required scopes: Issues (read/write), Metadata (read)

Run once from repo root. Safe to re-run — existing issues are detected and skipped.
"""

import os
import sys
import time

try:
    from github import Github, GithubException
except ImportError:
    print("PyGithub not installed. Run: pip install PyGithub")
    sys.exit(1)

REPO_NAME = "MoritzImendoerffer/ema_nlp"

# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

LABELS = [
    ("phase/0",   "0075ca", "Phase 0: Scoping"),
    ("phase/1",   "0052cc", "Phase 1: Corpus extraction"),
    ("phase/1.5", "003d99", "Phase 1.5: Contamination check"),
    ("phase/2",   "7057ff", "Phase 2: Benchmark construction"),
    ("phase/3",   "b60205", "Phase 3: Baseline RAG"),
    ("phase/4A",  "e4e669", "Phase 4A: Ablation A - evidence filtering"),
    ("phase/4B",  "d93f0b", "Phase 4B: Ablation B - process rewards"),
    ("phase/4C",  "0e8a16", "Phase 4C: Ablation C - prompting matrix"),
    ("phase/5",   "c5def5", "Phase 5: Writeup and release"),
    ("owner:claude",        "bfd4f2", "Claude implements"),
    ("owner:sme",           "fef2c0", "You (SME) must do this"),
    ("owner:collaborative", "d4edda", "Both: Claude scaffolds, SME decides"),
    ("blocked",             "e4e4e4", "Waiting on another task"),
]

# ---------------------------------------------------------------------------
# Issues — (title, labels, body)
# ---------------------------------------------------------------------------

ISSUES = [
    # ── Phase 0 ──────────────────────────────────────────────────────────
    (
        "[TASK-001] MongoDB Q&A inventory query",
        ["phase/0", "owner:claude"],
        """\
## Summary
Query `ema_scraper.web_items` for accordion Q&A pages and Q&A-pattern PDF URLs. Output a reproducible inventory CSV.

## Status
✅ **COMPLETED** — 165 sources found (64 HTML, 101 PDFs). 1,506 estimated Q&A pairs. GO signal met.

## Owner
Claude

## Acceptance criteria
- [x] Script `scripts/phase0_inventory.py` queries MongoDB for accordion pages and Q&A PDF URLs
- [x] Output: `scripts/phase0_inventory.csv` with columns: `url, type, topic_path, q_count_estimate, last_updated, revision_number`
- [x] Counts printed: total sources, html vs pdf split, overlap with human-regulatory URL tree
- [x] Reproducible from a fresh MongoDB connection

## Estimated effort
2 hours (Claude)""",
    ),
    (
        "[TASK-002] Topic stratification + cross-ref chain completeness",
        ["phase/0", "owner:claude"],
        """\
## Summary
Group Q&A sources by topic_path. Verify that cross-reference chains are completable within the corpus.

## Status
✅ **COMPLETED** — 11 clusters. Largest: Research & Dev (492 Q&A). Chain completeness: 43.6%.

## Owner
Claude

## Acceptance criteria
- [x] Identifies ≥3 distinct topic clusters from URL-derived topic_path grouping
- [x] Reports Q&A count per cluster; flags clusters with <5 Q&As as thin
- [x] Extracts cross-reference pattern counts from HTML sources
- [x] Computes chain completeness %
- [x] Output: `scripts/phase0_topic_report.md`

## Estimated effort
3 hours (Claude)""",
    ),
    (
        "[TASK-003] Go/no-go decision notebook",
        ["phase/0", "owner:collaborative"],
        """\
## Summary
Claude generates notebook with plots. **You fill in the Decision cell before Phase 1 can begin.**

## Status
⏳ **AWAITING SME** — notebook at `scripts/phase0_scope_decision.ipynb` ready for your decision.

## Owner
Collaborative (Claude generates; you decide)

## Your action
1. Open `scripts/phase0_scope_decision.ipynb`
2. Run all cells
3. Fill the **✏️ DECISION** cell with GO/NO-GO + rationale
4. Commit: `git add scripts/phase0_scope_decision.ipynb && git commit -m 'TASK-003: Phase 0 go/no-go decision — GO'`

## Gate
⚠️ Nothing in Phase 1 begins until this is committed with a GO decision.

## Estimated effort
2 hours (Claude) + your decision""",
    ),
    # ── Phase 1 ──────────────────────────────────────────────────────────
    (
        "[TASK-004] Project setup — pyproject.toml, directory structure, schema docs",
        ["phase/1", "owner:claude", "blocked"],
        """\
## Summary
Lay the project foundation: dependencies, directory tree, and schema documentation.

## Owner
Claude

## Dependencies
Blocked by: TASK-003 (GO decision required)

## Acceptance criteria
- [ ] `pyproject.toml` with pinned deps: pymupdf4llm, pymongo, rank-bm25, faiss-cpu, sentence-transformers, anthropic, pytest, ruff, mypy
- [ ] Directory tree: corpus/, benchmark/, harness/configs/, harness/judges/, harness/prompts/, results/, ablations/A|B|C/, docs/
- [ ] `corpus/SCHEMA.md` documents Q&A record schema
- [ ] `benchmark/SCHEMA.md` documents benchmark item schema
- [ ] pytest/ruff/mypy all pass on empty stubs

## Estimated effort
2 hours (Claude)""",
    ),
    (
        "[TASK-005] HTML accordion extractor",
        ["phase/1", "owner:claude", "blocked"],
        """\
## Summary
Extract Q&A pairs from EMA HTML accordion pages into corpus.jsonl format.

## Owner
Claude

## Dependencies
Blocked by: TASK-004

## Acceptance criteria
- [ ] `corpus/extractors/html_extractor.py` splits accordion items into Q/A pairs
- [ ] Flags items where heading isn't question-form
- [ ] Builds `topic_path` from URL segments; assigns `extraction_confidence`
- [ ] Output matches `corpus/SCHEMA.md`
- [ ] Tests: ≥3 real accordion fixtures; ≥90% Q&A capture rate on known pages
- [ ] ruff + mypy clean

## Estimated effort
3 hours (Claude)""",
    ),
    (
        "[TASK-006] PDF Q&A extractor",
        ["phase/1", "owner:claude", "blocked"],
        """\
## Summary
Extract numbered Q&A pairs from EMA PDFs, including revision history and cross-references.

## Owner
Claude

## Dependencies
Blocked by: TASK-004

## Acceptance criteria
- [ ] `corpus/extractors/pdf_extractor.py` uses PyMuPDF4LLM
- [ ] Regex-based Q segmentation on numbered headings
- [ ] Revision history table parsed → `revision` field
- [ ] `cross_refs` extracted from 'see Q&A N' patterns
- [ ] Tests: nitrosamine Q&A PDF fixture; Q22 has correct cross_refs; revision parsed correctly
- [ ] ruff + mypy clean

## Estimated effort
4 hours (Claude)""",
    ),
    (
        "[TASK-007] Deduplication + landing page filter + corpus writer",
        ["phase/1", "owner:claude", "blocked"],
        """\
## Summary
Orchestrate extraction → dedup → filter → output. Resolve HTML/PDF duplicates.

## Owner
Claude

## Dependencies
Blocked by: TASK-005, TASK-006

## Acceptance criteria
- [ ] `corpus/build_corpus.py` orchestrates: extract → dedup → filter → write
- [ ] Hash-based dedup on normalised question text; prefers PDF version
- [ ] Landing pages filtered out; filter log written
- [ ] Stable `qa_id` = hash(source_url + normalised_question)
- [ ] Tests: dedup correctly drops HTML when PDF exists

## Estimated effort
2 hours (Claude)""",
    ),
    (
        "[TASK-008] Corpus manifest — corpus.jsonl + corpus_stats.md",
        ["phase/1", "owner:claude", "blocked"],
        """\
## Summary
Write the final corpus artifact. Deliverable 1 — usable by others independently of the benchmark.

## Owner
Claude

## Dependencies
Blocked by: TASK-007

## Acceptance criteria
- [ ] `corpus/corpus.jsonl` written; validates against `corpus/SCHEMA.md`
- [ ] `corpus/corpus_stats.md`: counts by topic_path, source_type, revision date distribution
- [ ] Success criterion: ≥200 Q&A records, ≥3 topic paths
- [ ] If <200 records: SCOPE-RISK warning and halt

## Estimated effort
2 hours (Claude)""",
    ),
    # ── Phase 1.5 ─────────────────────────────────────────────────────────
    (
        "[TASK-009] Training data contamination check — Dolma 3 / Common Corpus",
        ["phase/1.5", "owner:claude", "blocked"],
        """\
## Summary
Verify whether EMA source documents appear in public training corpora.

## Owner
Claude

## Dependencies
Blocked by: TASK-008

## Acceptance criteria
- [ ] `docs/training_data_verification.md` written
- [ ] 5-10 distinctive sentences per source doc searched in Dolma 3 + Common Corpus
- [ ] Per-doc status: present / absent / partial
- [ ] OLMo 3 usability as clean reference documented

## Estimated effort
3 hours (Claude)""",
    ),
    # ── Phase 2 ──────────────────────────────────────────────────────────
    (
        "[TASK-010] T1 Lookup benchmark questions — candidates + SME review",
        ["phase/2", "owner:collaborative", "blocked"],
        """\
## Summary
Claude generates 30 T1 candidates with paraphrases. **You select 20 and validate gold answers.**

## Owner
Collaborative (Claude generates; you validate)

## Dependencies
Blocked by: TASK-008

## Your task
Review `benchmark/candidates/t1_candidates.jsonl`, accept 20 items, verify gold_answer accuracy.

## Acceptance criteria
- [ ] Claude generates `benchmark/candidates/t1_candidates.jsonl` with 30 candidates + 2 paraphrases each
- [ ] You select 20 and validate gold_answer accuracy
- [ ] 20 final T1 items appended to `benchmark/benchmark.jsonl`

## Estimated effort
3 hours total""",
    ),
    (
        "[TASK-011] T2 Scoping benchmark questions — author",
        ["phase/2", "owner:sme", "blocked"],
        """\
## Summary
**You author 10 T2 questions** pairing a correct Q&A with topically-adjacent distractors.

## Owner
You (SME) — Claude validates schema and adds paraphrases

## Dependencies
Blocked by: TASK-008

## Your task
Write 10 questions in `benchmark/candidates/t2_authored.md`. Each maps to 1 correct Q&A + 2 distractors that share keywords but address a different procedural step or scope.

## Acceptance criteria
- [ ] 10 T2 questions authored
- [ ] Each: 1 correct Q&A + 2 distractor Q&As
- [ ] Claude converts to JSONL, validates schema
- [ ] 10 T2 items in `benchmark/benchmark.jsonl`

## Estimated effort
4 hours (your domain knowledge)""",
    ),
    (
        "[TASK-012] T3 Multi-hop benchmark questions — chain composition",
        ["phase/2", "owner:collaborative", "blocked"],
        """\
## Summary
Claude identifies valid cross-ref chains. **You compose questions requiring chain traversal.**

## Owner
Collaborative (Claude identifies chains; you compose questions)

## Dependencies
Blocked by: TASK-008, TASK-002

## Acceptance criteria
- [ ] Claude enumerates in-corpus cross-ref chains of length ≥2
- [ ] Claude produces `benchmark/candidates/t3_chain_map.md`
- [ ] You compose 10 questions requiring full chain traversal
- [ ] Claude validates all hops are in corpus
- [ ] 10 T3 items in `benchmark/benchmark.jsonl`

## Estimated effort
3 hours total""",
    ),
    (
        "[TASK-013] T4 Synthesis benchmark questions — hand-curate",
        ["phase/2", "owner:sme", "blocked"],
        """\
## Summary
**You hand-curate ≥5 synthesis questions** combining Q&As from different source documents.

## Owner
You (SME)

## Dependencies
Blocked by: TASK-008

## Your task
Include ≥2 counterfactual questions (e.g., combining published Q&As in ways the documents don't). These are contamination-resistant by construction.

## Acceptance criteria
- [ ] ≥5 T4 questions spanning ≥2 distinct source_urls
- [ ] ≥2 composite/counterfactual items
- [ ] Claude validates and adds paraphrases
- [ ] ≥5 T4 items in `benchmark/benchmark.jsonl`

## Estimated effort
3 hours (your domain knowledge)""",
    ),
    (
        "[TASK-014] Benchmark JSONL finalisation + validation script",
        ["phase/2", "owner:claude", "blocked"],
        """\
## Summary
Final validation gate ensuring benchmark.jsonl is complete, schema-valid, and correctly stratified.

## Owner
Claude

## Dependencies
Blocked by: TASK-010, TASK-011, TASK-012, TASK-013

## Acceptance criteria
- [ ] `benchmark/validate_benchmark.py`: no duplicate bench_ids; all gold_qa_ids in corpus; T1=20, T2=10, T3=10, T4≥5
- [ ] `benchmark/STATS.md`: stratification report, topic distribution
- [ ] Script exits non-zero on any validation failure

## Estimated effort
2 hours (Claude)""",
    ),
    (
        "[TASK-015] Closed-book contamination screen",
        ["phase/2", "owner:claude", "blocked"],
        """\
## Summary
Measure how much each model already knows without retrieval. Sets `zero_shot_known` flags.

## Owner
Claude

## Dependencies
Blocked by: TASK-014

## Acceptance criteria
- [ ] `harness/contamination_screen.py` runs all benchmark items with no retrieval
- [ ] Captures: model answer, matches_gold, zero_shot_known flag per model per item
- [ ] Slot-guessing test on 10-item subsample
- [ ] `contamination_summary.md`: aggregate zero_shot_known rate per model

## Estimated effort
3 hours (Claude)""",
    ),
    # ── Phase 3 ──────────────────────────────────────────────────────────
    (
        "[TASK-016] Embedding pipeline + FAISS vector store",
        ["phase/3", "owner:claude", "blocked"],
        """\
## Summary
Embed the corpus with BGE-large-en and build a FAISS index for dense retrieval.

## Owner
Claude

## Dependencies
Blocked by: TASK-008 (can start in parallel with Phase 2)

## Acceptance criteria
- [ ] `harness/embed.py` embeds Q&A records with BGE-large-en
- [ ] FAISS flat index saved to `harness/index/corpus.faiss`
- [ ] Dense retrieval returns top-k (qa_id, score) in <100ms for k=10
- [ ] Unit test: known question retrieves its own Q&A in top-1

## Estimated effort
3 hours (Claude)""",
    ),
    (
        "[TASK-017] BM25 hybrid retrieval",
        ["phase/3", "owner:claude", "blocked"],
        """\
## Summary
Add BM25 keyword retrieval and RRF hybrid fusion for the A0+ baseline.

## Owner
Claude

## Dependencies
Blocked by: TASK-016

## Acceptance criteria
- [ ] `harness/retrieve.py`: dense-only (A0), BM25-only, hybrid RRF (A0+) via config flag
- [ ] BM25 uses rank-bm25 on tokenised Q&A text
- [ ] Test: hybrid outperforms dense-only on exact-match query (e.g., '26.5 ng/day')

## Estimated effort
2 hours (Claude)""",
    ),
    (
        "[TASK-018] Evaluation harness — Recall@k, Precision@k, Citation Accuracy",
        ["phase/3", "owner:claude", "blocked"],
        """\
## Summary
Retrieval metrics broken down by question type (T1–T4).

## Owner
Claude

## Dependencies
Blocked by: TASK-017

## Acceptance criteria
- [ ] `harness/eval_retrieval.py`: Recall@k, Precision@k, Citation Accuracy per item
- [ ] All metrics broken down by T1/T2/T3/T4
- [ ] Grouped bar chart PNG output
- [ ] Unit tests with synthetic gold qa_ids

## Estimated effort
3 hours (Claude)""",
    ),
    (
        "[TASK-019] LLM judge — Faithfulness + Correctness",
        ["phase/3", "owner:claude", "blocked"],
        """\
## Summary
Automated answer quality evaluation using a judge model different from the generator.

## Owner
Claude

## Dependencies
Blocked by: TASK-018

## Acceptance criteria
- [ ] `harness/judges/faithfulness.md` and `correctness.md`: judge prompts as files
- [ ] `harness/judge.py`: judge model returns score 0-1 + one-line rationale
- [ ] Agreement validation: >0.7 correlation with hand-graded 20% sample

## Estimated effort
3 hours (Claude)""",
    ),
    (
        "[TASK-020] Config-as-code + results logging infrastructure",
        ["phase/3", "owner:claude", "blocked"],
        """\
## Summary
Single evaluation entry point driven by YAML. Ablations become config-file changes.

## Owner
Claude

## Dependencies
Blocked by: TASK-018, TASK-019

## Acceptance criteria
- [ ] `harness/run_eval.py`: all parameters via YAML config
- [ ] Each run creates `results/<run_id>/` with config copy + raw JSONL + metrics + plots
- [ ] `run_id` = datetime + config hash
- [ ] Example configs: `harness/configs/baseline_a0.yaml`, `baseline_a0plus.yaml`

## Estimated effort
2 hours (Claude)""",
    ),
    (
        "[TASK-021] Baseline run (A0 + A0+) + results report",
        ["phase/3", "owner:claude", "blocked"],
        """\
## Summary
The fixed reference point. All ablations are measured against this.

## Owner
Claude

## Dependencies
Blocked by: TASK-015, TASK-020

## Acceptance criteria
- [ ] A0 (dense) and A0+ (hybrid) run end-to-end on full benchmark
- [ ] `results/baseline/baseline_report.md`: all 5 metrics × T1-T4, lift computed
- [ ] Contamination sensitivity: results with/without zero_shot_known items
- [ ] Report committed — this is now the fixed reference

## Estimated effort
2 hours (Claude)""",
    ),
    # ── Phase 4A ─────────────────────────────────────────────────────────
    (
        "[TASK-022] SME acronym dictionary — author",
        ["phase/4A", "owner:sme", "blocked"],
        """\
## Summary
**You write the acronym/synonym dictionary** used for A1 query expansion.

## Owner
You (SME)

## Dependencies
Blocked by: TASK-021

## Your task
Write `ablations/A_evidence_filter/acronym_dict.yaml`.
Example entry:
```yaml
- canonical: "Acceptable Intake"
  acronym: "AI"
  synonyms: ["acceptable daily intake", "safe intake"]
  context_disambiguation:
    - "toxicology/impurity context — NOT artificial intelligence"
```

## Acceptance criteria
- [ ] ≥30 entries covering: AI (Acceptable Intake), MAH, CAPA, ICH Q3A/M7/Q9, GMP, CEP, ASMF, TTC, LoQ, ppm/ppb
- [ ] `context_disambiguation` present for all collision-risk entries (AI, MA)

## Estimated effort
4 hours (your domain knowledge)""",
    ),
    (
        "[TASK-023] A1 query expansion + A2 topic-path filter",
        ["phase/4A", "owner:claude", "blocked"],
        """\
## Summary
Implement the two cheapest retrieval-layer interventions.

## Owner
Claude

## Dependencies
Blocked by: TASK-022

## Acceptance criteria
- [ ] `harness/ablations/a1_query_expansion.py`: expands queries using acronym_dict.yaml
- [ ] `harness/ablations/a2_topic_filter.py`: filters retrieval to matching topic_path
- [ ] Both integrated as config flags in `run_eval.py`
- [ ] Test: 'What is the AI for nitrosamines?' expands to include 'Acceptable Intake'

## Estimated effort
2 hours (Claude)""",
    ),
    (
        "[TASK-024] SME relevance rubric — author",
        ["phase/4A", "owner:sme", "blocked"],
        """\
## Summary
**You write the relevance rubric** used by the A3 LLM reranker.

## Owner
You (SME)

## Dependencies
Blocked by: TASK-021

## Your task
Write `harness/prompts/relevance_rubric_sme.md` (~200 words). Define what makes an EMA Q&A relevant:
- Procedure/obligation match
- Scope alignment (MAH vs applicant, CAP vs NAP, biological vs chemical)
- Non-relevant patterns: same keywords, wrong procedural step

## Acceptance criteria
- [ ] `harness/prompts/relevance_rubric_sme.md` written, ~200 words, version tagged v1

## Estimated effort
2 hours""",
    ),
    (
        "[TASK-025] A3/A4 LLM reranker (SME rubric vs generic)",
        ["phase/4A", "owner:claude", "blocked"],
        """\
## Summary
Implement LLM reranker in two variants: with SME rubric (A3) and generic prompt (A4).

## Owner
Claude

## Dependencies
Blocked by: TASK-024

## Acceptance criteria
- [ ] `harness/ablations/a3_reranker.py`: uses `relevance_rubric_sme.md`
- [ ] `harness/ablations/a4_reranker.py`: generic 'is this relevant?' prompt
- [ ] Both use Haiku-tier model; cost-budget enforced (≤40q × 5 chunks)

## Estimated effort
3 hours (Claude)""",
    ),
    (
        "[TASK-026] Run Ablation A variants A0–A5 + analysis report",
        ["phase/4A", "owner:claude", "blocked"],
        """\
## Summary
Run all 6 variants. Identify best retriever configuration to carry into Ablations B and C.

## Owner
Claude

## Dependencies
Blocked by: TASK-023, TASK-025

## Acceptance criteria
- [ ] All 6 variants run; results in `results/ablation_a/`
- [ ] A3 vs A4 comparison explicitly reported
- [ ] `ablations/A_evidence_filter/FINDINGS.md`: pre-registered predictions vs actual

## Estimated effort
3 hours (Claude)""",
    ),
    # ── Phase 4B ─────────────────────────────────────────────────────────
    (
        "[TASK-027] ReAct agent + tools (search, follow_cross_refs, filter_by_topic, answer)",
        ["phase/4B", "owner:claude", "blocked"],
        """\
## Summary
The Ablation B agent. Multi-hop retrieval via tool calls using best Ablation A retriever.

## Owner
Claude

## Dependencies
Blocked by: TASK-020, TASK-026

## Acceptance criteria
- [ ] `harness/agents/react_agent.py`: ReAct loop with four tools
- [ ] Trajectories logged as JSONL: step, thought, action, observation
- [ ] Terminates on answer() or max_steps

## Estimated effort
4 hours (Claude)""",
    ),
    (
        "[TASK-028] B1 sanity check — 5 questions + trajectory review",
        ["phase/4B", "owner:collaborative", "blocked"],
        """\
## Summary
Gate before SME labeling. **You review 5 trajectories and decide on B3 labeling.**

## Owner
Collaborative (Claude runs; you review)

## Dependencies
Blocked by: TASK-027

## Your task
Review trajectories in `ablations/B_process_rewards/sanity_check_trajectories/`. Document decision in `SANITY_CHECK.md`.
- **GO:** proceed to TASK-029 (labeling)
- **NO-GO:** skip TASK-029; proceed to B4 only

## Estimated effort
2 hours total""",
    ),
    (
        "[TASK-029] SME trajectory labeling (conditional — only if B1 passes)",
        ["phase/4B", "owner:sme", "blocked"],
        """\
## Summary
**Only if TASK-028 = GO.** Label ≥50 trajectory steps as good/suboptimal/wrong.

## Owner
You (SME) — conditional on TASK-028 outcome

## Dependencies
Blocked by: TASK-028 (GO only)

## Acceptance criteria
- [ ] ≥50 steps labeled in `ablations/B_process_rewards/trajectory_labels.jsonl`
- [ ] Each label has a one-line rationale
- [ ] First 10 labels reviewed for internal consistency

## Estimated effort
4 hours (your domain knowledge)""",
    ),
    (
        "[TASK-030] Run Ablation B variants B0–B4 + analysis report",
        ["phase/4B", "owner:claude", "blocked"],
        """\
## Summary
Run all applicable B variants. Key question: does process-reward supervision help on T3?

## Owner
Claude

## Dependencies
Blocked by: TASK-029 (or TASK-028 if B3 skipped)

## Acceptance criteria
- [ ] All applicable variants run
- [ ] B2 vs B3 comparison explicit (LLM-judge vs SME labels)
- [ ] `ablations/B_process_rewards/FINDINGS.md`

## Estimated effort
3 hours (Claude)""",
    ),
    # ── Phase 4C ─────────────────────────────────────────────────────────
    (
        "[TASK-031] SME few-shot exemplars — author",
        ["phase/4C", "owner:sme", "blocked"],
        """\
## Summary
**You write 3-5 Q&A solving traces** for the Ablation C SME few-shot condition.

## Owner
You (SME)

## Dependencies
Blocked by: TASK-021

## Your task
Write `harness/prompts/few_shot_examples.md`. Each example:
```
Question: [question]
Retrieved: [3-5 Q&As — use held-out Q&As NOT in benchmark.jsonl]
Reasoning: [SME-style reasoning: which Q&A to trust, disambiguation, cross-refs]
Answer: [gold-quality answer with qa_id citations]
```
Cover: 1 T1, 1 T2, 1-2 T3.

## Acceptance criteria
- [ ] 3-5 examples covering T1/T2/T3
- [ ] All example Q&As are held-out from benchmark

## Estimated effort
3 hours""",
    ),
    (
        "[TASK-032] OLMo 3 API + three model tiers setup",
        ["phase/4C", "owner:claude", "blocked"],
        """\
## Summary
Wire up the three model tiers: mid-tier, frontier reasoning, and OLMo 3.

## Owner
Claude

## Dependencies
Blocked by: TASK-020

## Acceptance criteria
- [ ] `harness/models.py`: unified interface for Haiku 4.5, Opus 4.x, OLMo 3 (Together AI)
- [ ] All three smoke-tested with a single call
- [ ] Model versions pinned in `harness/configs/models.yaml`

## Estimated effort
2 hours (Claude)""",
    ),
    (
        "[TASK-033] 3×3 grid runs (Ablation C) + analysis report",
        ["phase/4C", "owner:claude", "blocked"],
        """\
## Summary
Run all 9 cells of the prompting strategy × model tier grid.

## Owner
Claude

## Dependencies
Blocked by: TASK-031, TASK-032

## Acceptance criteria
- [ ] All 9 cells run: 3 models × {zero-shot, SME few-shot, self-generated CoT}
- [ ] Δ(few-shot − zero-shot) chart across all model tiers
- [ ] OlmoTrace on 5 OLMo 3 answers for contamination verification
- [ ] `ablations/C_prompting_matrix/FINDINGS.md`

## Estimated effort
4 hours (Claude)""",
    ),
    # ── Phase 5 ──────────────────────────────────────────────────────────
    (
        "[TASK-034] Blog post draft",
        ["phase/5", "owner:collaborative", "blocked"],
        """\
## Summary
Claude drafts from BLOG_OUTLINE.md. **You revise the final post.**

## Owner
Collaborative (Claude drafts; you revise)

## Dependencies
Blocked by: TASK-026, TASK-030, TASK-033

## Acceptance criteria
- [ ] `docs/blog_post.md` follows `project_roadmap/BLOG_OUTLINE.md`
- [ ] All three ablation findings reported
- [ ] Contamination caveats section present
- [ ] You have reviewed and approved final draft (~2000-2500 words)

## Estimated effort
4 hours total""",
    ),
    (
        "[TASK-035] README, final repo structure, and release",
        ["phase/5", "owner:claude", "blocked"],
        """\
## Summary
Final deliverable: a repo someone else can clone and run in 30 minutes.

## Owner
Claude

## Dependencies
Blocked by: TASK-034

## Acceptance criteria
- [ ] README.md follows `project_roadmap/README_OUTLINE.md`
- [ ] Fresh-clone quickstart works in ≤30 minutes
- [ ] Honest limitations section
- [ ] CC-BY-4.0 (data) + MIT (code) licensing documented

## Estimated effort
3 hours (Claude)""",
    ),
]


def ensure_labels(repo) -> None:
    existing = {l.name for l in repo.get_labels()}
    for name, color, description in LABELS:
        if name not in existing:
            repo.create_label(name=name, color=color, description=description)
            print(f"  Created label: {name}")
        else:
            print(f"  Label exists:  {name}")


def existing_titles(repo) -> set:
    return {i.title for i in repo.get_issues(state="all")}


def create_issues(repo) -> None:
    existing = existing_titles(repo)
    created = 0
    skipped = 0

    for title, label_names, body in ISSUES:
        if title in existing:
            print(f"  SKIP (exists): {title}")
            skipped += 1
            continue

        labels = [repo.get_label(ln) for ln in label_names]
        issue = repo.create_issue(title=title, body=body, labels=labels)
        print(f"  Created #{issue.number}: {title}")
        created += 1
        time.sleep(0.5)  # gentle rate limiting

    print(f"\nDone — {created} created, {skipped} skipped.")


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN environment variable not set.")
        print()
        print("Get a token at:")
        print("  GitHub → Settings → Developer settings → Personal access tokens → Fine-grained")
        print("  Required permissions: Issues (read/write), Metadata (read)")
        print()
        print("Then run:")
        print("  GITHUB_TOKEN=ghp_xxx python3 scripts/create_github_issues.py")
        sys.exit(1)

    g = Github(token)
    try:
        repo = g.get_repo(REPO_NAME)
        print(f"Connected to: {repo.full_name}")
    except GithubException as e:
        print(f"Error accessing repo: {e}")
        sys.exit(1)

    print("\nEnsuring labels exist...")
    ensure_labels(repo)

    print(f"\nCreating {len(ISSUES)} issues...")
    create_issues(repo)

    print(f"\nView issues at: https://github.com/{REPO_NAME}/issues")


if __name__ == "__main__":
    main()

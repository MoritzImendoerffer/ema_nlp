#!/bin/bash
# Creates all 35 GitHub issues for the EMA RAG Benchmark project.
# Prerequisites: gh installed and authenticated (`gh auth login`).
# Run once from repo root: bash scripts/create_github_issues.sh
# Issues are created with labels; labels are created first if missing.

set -e
REPO="MoritzImendoerffer/ema_nlp"

echo "Creating labels..."
create_label() {
  gh label create "$1" --color "$2" --description "$3" --repo "$REPO" 2>/dev/null || true
}
create_label "phase/0"   "0075ca" "Phase 0: Scoping"
create_label "phase/1"   "0052cc" "Phase 1: Corpus extraction"
create_label "phase/1.5" "003d99" "Phase 1.5: Contamination check"
create_label "phase/2"   "7057ff" "Phase 2: Benchmark construction"
create_label "phase/3"   "b60205" "Phase 3: Baseline RAG"
create_label "phase/4A"  "e4e669" "Phase 4A: Ablation A - evidence filtering"
create_label "phase/4B"  "d93f0b" "Phase 4B: Ablation B - process rewards"
create_label "phase/4C"  "0e8a16" "Phase 4C: Ablation C - prompting matrix"
create_label "phase/5"   "c5def5" "Phase 5: Writeup and release"
create_label "owner:claude"        "bfd4f2" "Claude implements"
create_label "owner:sme"           "fef2c0" "You (SME) must do this"
create_label "owner:collaborative" "d4edda" "Both: Claude scaffolds, SME decides"
create_label "blocked"             "e4e4e4" "Waiting on another task"

echo "Creating Phase 0 issues..."

gh issue create --repo "$REPO" \
  --title "[TASK-001] MongoDB Q&A inventory query" \
  --label "phase/0,owner:claude" \
  --body "## Summary
Query \`ema_scraper.web_items\` for accordion Q&A pages and Q&A-pattern PDF URLs. Output a reproducible inventory CSV.

## Owner
Claude

## Acceptance criteria
- [ ] Script \`scripts/phase0_inventory.py\` queries MongoDB for accordion pages and Q&A PDF URLs
- [ ] Output: \`scripts/phase0_inventory.csv\` with columns: \`url, type (html/pdf), topic_path, q_count_estimate, last_updated, revision_number\`
- [ ] Counts printed: total sources, html vs pdf split, overlap with human-regulatory URL tree
- [ ] Reproducible from a fresh MongoDB connection

## Estimated effort
2 hours (Claude)"

gh issue create --repo "$REPO" \
  --title "[TASK-002] Topic stratification + cross-ref chain completeness" \
  --label "phase/0,owner:claude,blocked" \
  --body "## Summary
Group Q&A sources by topic_path. Verify that cross-reference chains are completable within the corpus — critical for T3 multi-hop benchmark viability.

## Owner
Claude

## Dependencies
Blocked by: TASK-001

## Acceptance criteria
- [ ] Identifies ≥3 distinct topic clusters from URL-derived topic_path grouping
- [ ] Reports Q&A count per cluster; flags clusters with <5 Q&As as thin
- [ ] Extracts cross-reference ('see Q&A N') counts from PDF sources
- [ ] Computes chain completeness %: fraction of referenced Q&As present in corpus
- [ ] Output: \`scripts/phase0_topic_report.md\` with all counts and chain-completeness flag

## Estimated effort
3 hours (Claude)"

gh issue create --repo "$REPO" \
  --title "[TASK-003] Go/no-go decision notebook" \
  --label "phase/0,owner:collaborative,blocked" \
  --body "## Summary
Claude generates notebook with plots. **You fill in the Decision cell before Phase 1 can begin.**

## Owner
Collaborative (Claude generates; you decide)

## Dependencies
Blocked by: TASK-002

## Acceptance criteria
- [ ] \`scripts/phase0_scope_decision.ipynb\` with plots: source counts, topic split, chain completeness
- [ ] Notebook has a clearly labelled 'Decision' cell for GO / NO-GO + rationale
- [ ] Notebook committed with decision filled in before any Phase 1 task starts

## Gate
⚠️ Nothing in Phase 1 begins until this is committed with a GO decision.

## Estimated effort
2 hours (Claude) + your decision"

echo "Creating Phase 1 issues..."

gh issue create --repo "$REPO" \
  --title "[TASK-004] Project setup — pyproject.toml, directory structure, schema docs" \
  --label "phase/1,owner:claude,blocked" \
  --body "## Summary
Lay the project foundation: dependencies, directory tree, and schema documentation.

## Owner
Claude

## Dependencies
Blocked by: TASK-003 (GO decision required)

## Acceptance criteria
- [ ] \`pyproject.toml\` with pinned deps: pymupdf4llm, pymongo, rank-bm25, faiss-cpu, sentence-transformers, anthropic, pytest, ruff, mypy
- [ ] Directory tree created: corpus/, benchmark/, harness/configs/, harness/judges/, harness/prompts/, results/, ablations/A|B|C/, docs/
- [ ] \`corpus/SCHEMA.md\` documents Q&A record schema (all fields from ROADMAP Phase 1.1)
- [ ] \`benchmark/SCHEMA.md\` documents benchmark item schema (includes \`paraphrases\` field)
- [ ] pytest/ruff/mypy all pass on empty stubs

## Estimated effort
2 hours (Claude)"

gh issue create --repo "$REPO" \
  --title "[TASK-005] HTML accordion extractor" \
  --label "phase/1,owner:claude,blocked" \
  --body "## Summary
Extract Q&A pairs from EMA HTML accordion pages. Reuses existing \`ema_parser.py::_parse_accordion\`.

## Owner
Claude

## Dependencies
Blocked by: TASK-004

## Acceptance criteria
- [ ] \`corpus/extractors/html_extractor.py\` wraps existing parser; splits accordion items into Q/A pairs
- [ ] Flags items where heading isn't question-form
- [ ] Builds \`topic_path\` from URL segments; assigns \`extraction_confidence\`
- [ ] Output matches \`corpus/SCHEMA.md\`
- [ ] Tests in \`tests/test_html_extractor.py\`: ≥3 real accordion fixtures; ≥90% Q&A capture rate on known pages
- [ ] ruff + mypy clean

## Estimated effort
3 hours (Claude)"

gh issue create --repo "$REPO" \
  --title "[TASK-006] PDF Q&A extractor" \
  --label "phase/1,owner:claude,blocked" \
  --body "## Summary
Extract numbered Q&A pairs from EMA PDF documents, including revision history and cross-references.

## Owner
Claude

## Dependencies
Blocked by: TASK-004

## Acceptance criteria
- [ ] \`corpus/extractors/pdf_extractor.py\` uses PyMuPDF4LLM
- [ ] Regex-based Q segmentation on numbered headings ('1. Should the risk…', '2. What is…')
- [ ] Revision history table parsed → \`revision\` field; reference number extracted from title page
- [ ] \`cross_refs\` extracted from 'see Q&A N' patterns → list of qa_id strings
- [ ] Flags PDFs without numbered-heading structure for manual review
- [ ] Tests: nitrosamine Q&A PDF as fixture; Q22 has correct cross_refs [Q20, Q10]; revision parsed correctly
- [ ] ruff + mypy clean

## Estimated effort
4 hours (Claude)"

gh issue create --repo "$REPO" \
  --title "[TASK-007] Deduplication + landing page filter + corpus writer" \
  --label "phase/1,owner:claude,blocked" \
  --body "## Summary
Orchestrate extraction → deduplication → filtering → output. Resolve HTML/PDF duplicates and remove non-Q&A landing pages.

## Owner
Claude

## Dependencies
Blocked by: TASK-005, TASK-006

## Acceptance criteria
- [ ] \`corpus/build_corpus.py\` orchestrates: extract → dedup → filter → write
- [ ] Hash-based dedup on normalised question text; prefers PDF version; dedup log written
- [ ] Landing pages (no accordion + no numbered Q headings) filtered out; filter log written
- [ ] Stable \`qa_id\` = hash(source_url + normalised_question)
- [ ] Tests: dedup correctly drops HTML when PDF exists; landing pages filtered

## Estimated effort
2 hours (Claude)"

gh issue create --repo "$REPO" \
  --title "[TASK-008] Corpus manifest — corpus.jsonl + corpus_stats.md" \
  --label "phase/1,owner:claude,blocked" \
  --body "## Summary
Write the final corpus artifact. This is Deliverable 1 — usable by others independently of the benchmark.

## Owner
Claude

## Dependencies
Blocked by: TASK-007

## Acceptance criteria
- [ ] \`corpus/corpus.jsonl\` written; one record per line; validates against \`corpus/SCHEMA.md\`
- [ ] \`corpus/corpus_stats.md\`: counts by topic_path, source_type, revision date distribution, cross_refs coverage
- [ ] Success criterion: ≥200 Q&A records, ≥3 topic paths covered
- [ ] If <200 records: script prints SCOPE-RISK warning and halts

## Estimated effort
2 hours (Claude)"

echo "Creating Phase 1.5 issues..."

gh issue create --repo "$REPO" \
  --title "[TASK-009] Training data contamination check — Dolma 3 / Common Corpus" \
  --label "phase/1.5,owner:claude,blocked" \
  --body "## Summary
Verify whether EMA source documents appear in public training corpora. Determines whether OLMo 3 is a clean contamination reference for Ablation C.

## Owner
Claude

## Dependencies
Blocked by: TASK-008

## Acceptance criteria
- [ ] \`docs/training_data_verification.md\` written
- [ ] 5-10 distinctive sentences extracted from each main source doc (nitrosamine Q&A, level-of-detail Q&A, Quality Q&A parts 1/2)
- [ ] Each sentence searched in Dolma 3 public release and Common Corpus
- [ ] Per-source-document status recorded: present / absent / partial
- [ ] OLMo 3 usability as clean reference documented per source

## Estimated effort
3 hours (Claude)"

echo "Creating Phase 2 issues..."

gh issue create --repo "$REPO" \
  --title "[TASK-010] T1 Lookup benchmark questions — candidates + SME review" \
  --label "phase/2,owner:collaborative,blocked" \
  --body "## Summary
Claude generates 30 T1 candidates with paraphrases. **You select 20 and validate gold answers.**

## Owner
Collaborative (Claude generates; you validate)

## Dependencies
Blocked by: TASK-008

## Your task
Review \`benchmark/candidates/t1_candidates.jsonl\`, set \`accepted: true\` on 20 items, verify gold_answer accuracy for each.

## Acceptance criteria
- [ ] Claude generates \`benchmark/candidates/t1_candidates.jsonl\` with 30 T1 candidates + 2 paraphrases each
- [ ] You select 20 and validate gold_answer accuracy; mark accepted=true
- [ ] 20 final T1 items appended to \`benchmark/benchmark.jsonl\`

## Estimated effort
3 hours (Claude generates + your review ~1-2h)"

gh issue create --repo "$REPO" \
  --title "[TASK-011] T2 Scoping benchmark questions — author" \
  --label "phase/2,owner:sme,blocked" \
  --body "## Summary
**You author 10 T2 questions** where the answer requires selecting correctly among topically-adjacent Q&As. This is an SME task — it requires regulatory domain knowledge.

## Owner
You (SME) — Claude validates schema and adds paraphrases

## Dependencies
Blocked by: TASK-008

## Your task
Write 10 questions that pair a correct Q&A with 2 topically-adjacent 'distractor' Q&As. Store in \`benchmark/candidates/t2_authored.md\` (human-readable; Claude converts to JSONL).

**Key:** Distractors should share keywords but address a different procedural step, scope, or entity type.

## Acceptance criteria
- [ ] 10 T2 questions authored in \`benchmark/candidates/t2_authored.md\`
- [ ] Each maps to: 1 correct Q&A + 2 distractor Q&As with different scope
- [ ] Claude converts to JSONL, adds paraphrases, validates schema
- [ ] 10 T2 items appended to \`benchmark/benchmark.jsonl\`

## Estimated effort
4 hours (your domain knowledge)"

gh issue create --repo "$REPO" \
  --title "[TASK-012] T3 Multi-hop benchmark questions — chain composition" \
  --label "phase/2,owner:collaborative,blocked" \
  --body "## Summary
Claude identifies valid cross-ref chains. **You compose questions that require traversing them.**

## Owner
Collaborative (Claude identifies chains; you compose questions)

## Dependencies
Blocked by: TASK-008, TASK-002

## Your task
Review \`benchmark/candidates/t3_chain_map.md\` (produced by Claude). For each chain, compose a question that cannot be answered from the first hop alone — the full chain must be traversed.

## Acceptance criteria
- [ ] Claude enumerates valid cross_ref chains of length ≥2 where all hops are in-corpus
- [ ] Claude produces \`benchmark/candidates/t3_chain_map.md\` with each chain + hop Q&As
- [ ] You compose 10 questions requiring full chain traversal
- [ ] Claude validates all hops are in corpus and adds paraphrases
- [ ] 10 T3 items appended to \`benchmark/benchmark.jsonl\`

## Estimated effort
3 hours (Claude maps + your composition ~2h)"

gh issue create --repo "$REPO" \
  --title "[TASK-013] T4 Synthesis benchmark questions — hand-curate" \
  --label "phase/2,owner:sme,blocked" \
  --body "## Summary
**You hand-curate ≥5 synthesis questions** combining ≥2 Q&As from different source documents. Include composite/counterfactual items for contamination resistance.

## Owner
You (SME) — Claude assists with paraphrases and schema validation

## Dependencies
Blocked by: TASK-008

## Your task
Author synthesis questions that require combining Q&As from distinct source documents. Include ≥2 counterfactual questions (e.g., 'if a MAH identified X during CAPA for chronic-use, what would the next step be?') — these combine published Q&As in ways the documents don't, making them contamination-resistant by construction.

## Acceptance criteria
- [ ] ≥5 T4 questions authored combining ≥2 Q&As from different source_urls
- [ ] ≥2 composite/counterfactual items
- [ ] Claude validates gold_qa_ids span ≥2 distinct source_urls and adds paraphrases
- [ ] ≥5 T4 items appended to \`benchmark/benchmark.jsonl\`

## Estimated effort
3 hours (your domain knowledge)"

gh issue create --repo "$REPO" \
  --title "[TASK-014] Benchmark JSONL finalisation + validation script" \
  --label "phase/2,owner:claude,blocked" \
  --body "## Summary
Final validation gate: ensure benchmark.jsonl is complete, schema-valid, and correctly stratified.

## Owner
Claude

## Dependencies
Blocked by: TASK-010, TASK-011, TASK-012, TASK-013

## Acceptance criteria
- [ ] \`benchmark/validate_benchmark.py\` validates each item against \`benchmark/SCHEMA.md\`
- [ ] Checks: no duplicate bench_ids; all gold_qa_ids exist in corpus.jsonl; paraphrases present; T1=20, T2=10, T3=10, T4≥5
- [ ] \`benchmark/STATS.md\`: stratification report, topic distribution, source diversity
- [ ] Script exits non-zero on any validation failure

## Estimated effort
2 hours (Claude)"

gh issue create --repo "$REPO" \
  --title "[TASK-015] Closed-book contamination screen" \
  --label "phase/2,owner:claude,blocked" \
  --body "## Summary
Measure how much each model already knows about benchmark content without retrieval. Sets zero_shot_known flags used in all subsequent reporting.

## Owner
Claude

## Dependencies
Blocked by: TASK-014

## Acceptance criteria
- [ ] \`harness/contamination_screen.py\` runs all benchmark items through configured models with no retrieval
- [ ] Captures: model answer, matches_gold (bool), zero_shot_known flag per model per item
- [ ] Slot-guessing test on 10-item subsample: masks numeric values; records model fill-in hit rate
- [ ] Results written to \`results/contamination/<model>_closed_book.jsonl\`
- [ ] \`contamination_summary.md\`: aggregate zero_shot_known rate per model; most-exposed items flagged

## Estimated effort
3 hours (Claude)"

echo "Creating Phase 3 issues..."

gh issue create --repo "$REPO" \
  --title "[TASK-016] Embedding pipeline + FAISS vector store" \
  --label "phase/3,owner:claude,blocked" \
  --body "## Summary
Embed the entire corpus using BGE-large-en and build a FAISS index for dense retrieval.

## Owner
Claude

## Dependencies
Blocked by: TASK-008 (can run in parallel with Phase 2)

## Acceptance criteria
- [ ] \`harness/embed.py\` embeds each Q&A record (question + answer concatenated) with BGE-large-en
- [ ] FAISS flat index saved to \`harness/index/corpus.faiss\`; id-to-qa_id map saved alongside
- [ ] Dense retrieval function returns top-k (qa_id, score) pairs in <100ms for k=10
- [ ] Unit test: known question retrieves its own Q&A in top-1

## Estimated effort
3 hours (Claude)"

gh issue create --repo "$REPO" \
  --title "[TASK-017] BM25 hybrid retrieval" \
  --label "phase/3,owner:claude,blocked" \
  --body "## Summary
Add keyword-based retrieval and RRF hybrid fusion. Regulatory text with specific numbers and reference codes benefits from BM25 on exact-match queries.

## Owner
Claude

## Dependencies
Blocked by: TASK-016

## Acceptance criteria
- [ ] \`harness/retrieve.py\`: dense-only (A0), BM25-only, hybrid RRF fusion (A0+) — selectable via config
- [ ] BM25 uses rank-bm25 on tokenised Q&A text
- [ ] Reciprocal Rank Fusion merges dense and BM25 result lists
- [ ] Test: hybrid outperforms dense-only on a known exact-match query (e.g., '26.5 ng/day')

## Estimated effort
2 hours (Claude)"

gh issue create --repo "$REPO" \
  --title "[TASK-018] Evaluation harness — Recall@k, Precision@k, Citation Accuracy" \
  --label "phase/3,owner:claude,blocked" \
  --body "## Summary
Retrieval metrics broken down by question type. The contamination-robust part of the evaluation.

## Owner
Claude

## Dependencies
Blocked by: TASK-017

## Acceptance criteria
- [ ] \`harness/eval_retrieval.py\` computes Recall@k, Precision@k, Citation Accuracy per item
- [ ] All three metrics broken down by T1/T2/T3/T4
- [ ] Output: JSON results dict + grouped bar chart PNG
- [ ] Unit tests with synthetic gold qa_ids and retrieval lists

## Estimated effort
3 hours (Claude)"

gh issue create --repo "$REPO" \
  --title "[TASK-019] LLM judge — Faithfulness + Correctness" \
  --label "phase/3,owner:claude,blocked" \
  --body "## Summary
Automated answer quality evaluation. Uses a different model from the generator; prompts live in files.

## Owner
Claude

## Dependencies
Blocked by: TASK-018

## Acceptance criteria
- [ ] \`harness/judges/faithfulness.md\` and \`correctness.md\`: judge prompts as files (not string literals)
- [ ] \`harness/judge.py\` runs judge model on each answer; returns score 0-1 + one-line rationale
- [ ] Judge model different from generator; configurable in YAML
- [ ] Agreement validation: judge scores correlate >0.7 with hand-graded 20% sample (or flag for review)

## Estimated effort
3 hours (Claude)"

gh issue create --repo "$REPO" \
  --title "[TASK-020] Config-as-code + results logging infrastructure" \
  --label "phase/3,owner:claude,blocked" \
  --body "## Summary
Single evaluation entry point driven by YAML. Makes ablations a config-file change, not a code change.

## Owner
Claude

## Dependencies
Blocked by: TASK-018, TASK-019

## Acceptance criteria
- [ ] \`harness/run_eval.py\`: single entry point, all parameters via YAML config
- [ ] Config schema covers: retriever mode, generator model, judge model, k, ablation flags
- [ ] Each run creates \`results/<run_id>/\` with config copy + raw JSONL + metrics + plots
- [ ] \`run_id\` = datetime + config hash (reproducible)
- [ ] Example configs: \`harness/configs/baseline_a0.yaml\`, \`baseline_a0plus.yaml\`

## Estimated effort
2 hours (Claude)"

gh issue create --repo "$REPO" \
  --title "[TASK-021] Baseline run (A0 + A0+) + results report" \
  --label "phase/3,owner:claude,blocked" \
  --body "## Summary
The fixed reference point. All ablations are measured against this. Commits the baseline numbers.

## Owner
Claude

## Dependencies
Blocked by: TASK-015, TASK-020

## Acceptance criteria
- [ ] A0 (dense-only) and A0+ (hybrid) run end-to-end on full benchmark
- [ ] \`results/baseline/baseline_report.md\`: all 5 metrics × T1-T4, open-book + closed-book side by side, lift computed
- [ ] Contamination sensitivity analysis: results with/without zero_shot_known items
- [ ] Report committed — baseline is now the fixed reference for all ablations

## Estimated effort
2 hours (Claude)"

echo "Creating Phase 4A issues..."

gh issue create --repo "$REPO" \
  --title "[TASK-022] SME acronym dictionary — author" \
  --label "phase/4A,owner:sme,blocked" \
  --body "## Summary
**You write the acronym/synonym dictionary** used for A1 query expansion. The most impactful SME artifact in Ablation A.

## Owner
You (SME) — Claude integrates into query expansion

## Dependencies
Blocked by: TASK-021 (baseline motivates which terms matter most)

## Your task
Write \`ablations/A_evidence_filter/acronym_dict.yaml\`. Each entry:
\`\`\`yaml
- canonical: \"Acceptable Intake\"
  acronym: \"AI\"
  synonyms: [\"acceptable daily intake\", \"safe intake\"]
  context_disambiguation:
    - \"toxicology/impurity context — NOT artificial intelligence\"
  topic_paths_where_relevant: [\"nitrosamines\", \"genotoxic-impurities\"]
\`\`\`

## Acceptance criteria
- [ ] ≥30 entries covering: AI (Acceptable Intake), MAH, CAPA, ICH Q3A/M7/Q9, GMP, CEP, ASMF, TTC, LoQ, ppm/ppb, and others encountered during benchmark curation
- [ ] context_disambiguation present for all collision-risk entries (AI, MA)
- [ ] Claude validates: no duplicate acronyms; schema correct

## Estimated effort
4 hours (your domain knowledge)"

gh issue create --repo "$REPO" \
  --title "[TASK-023] A1 query expansion + A2 topic-path filter" \
  --label "phase/4A,owner:claude,blocked" \
  --body "## Summary
Implement the two cheapest retrieval-layer interventions from Ablation A.

## Owner
Claude

## Dependencies
Blocked by: TASK-022

## Acceptance criteria
- [ ] \`harness/ablations/a1_query_expansion.py\`: reads acronym_dict.yaml, expands queries contextually
- [ ] \`harness/ablations/a2_topic_filter.py\`: predicts topic (LLM or keyword rules); filters retrieval to matching topic_path
- [ ] Both integrated as flags in \`run_eval.py\` config
- [ ] Test: query 'What is the AI for nitrosamines?' expands to include 'Acceptable Intake'

## Estimated effort
2 hours (Claude)"

gh issue create --repo "$REPO" \
  --title "[TASK-024] SME relevance rubric — author" \
  --label "phase/4A,owner:sme,blocked" \
  --body "## Summary
**You write the relevance rubric** used by the A3 LLM reranker. This is the key SME input that A3 vs A4 comparison isolates.

## Owner
You (SME)

## Dependencies
Blocked by: TASK-021

## Your task
Write \`harness/prompts/relevance_rubric_sme.md\` (~200 words). Define what makes an EMA Q&A 'relevant' to a question:
- Procedure/obligation match
- Scope alignment (MAH vs applicant, CAP vs NAP, biological vs chemical)
- Threshold specificity
- Non-relevant patterns: same keywords, wrong procedural step

## Acceptance criteria
- [ ] \`harness/prompts/relevance_rubric_sme.md\` written by you, ~200 words
- [ ] Specifies relevant AND non-relevant patterns with EMA-specific examples
- [ ] Version tagged as v1 in file header

## Estimated effort
2 hours (your domain knowledge)"

gh issue create --repo "$REPO" \
  --title "[TASK-025] A3/A4 LLM reranker (SME rubric vs generic)" \
  --label "phase/4A,owner:claude,blocked" \
  --body "## Summary
Implement the LLM reranker in two variants: one using your rubric (A3), one with a generic prompt (A4). The A3 vs A4 comparison isolates whether SME rubric authorship is what helps.

## Owner
Claude

## Dependencies
Blocked by: TASK-024

## Acceptance criteria
- [ ] \`harness/ablations/a3_reranker.py\`: uses \`harness/prompts/relevance_rubric_sme.md\`
- [ ] \`harness/ablations/a4_reranker.py\`: same architecture, generic 'is this relevant?' prompt
- [ ] Both use Haiku-tier model; cost-budget enforced (≤40q × 5 chunks)
- [ ] Integrated as flags in \`run_eval.py\`

## Estimated effort
3 hours (Claude)"

gh issue create --repo "$REPO" \
  --title "[TASK-026] Run Ablation A variants A0–A5 + analysis report" \
  --label "phase/4A,owner:claude,blocked" \
  --body "## Summary
Run all 6 variants. Identify the best retriever configuration to carry forward into Ablations B and C.

## Owner
Claude

## Dependencies
Blocked by: TASK-023, TASK-025

## Acceptance criteria
- [ ] All 6 variants run via \`harness/configs/ablation_a_*.yaml\`
- [ ] Results in \`results/ablation_a/\`: metrics JSON per variant, grouped bar chart per T-type
- [ ] A3 vs A4 comparison explicitly reported (SME rubric vs generic)
- [ ] \`ablations/A_evidence_filter/FINDINGS.md\`: which variant gained most, on which types, pre-registered predictions vs actual

## Estimated effort
3 hours (Claude)"

echo "Creating Phase 4B issues..."

gh issue create --repo "$REPO" \
  --title "[TASK-027] ReAct agent + tools (search, follow_cross_refs, filter_by_topic, answer)" \
  --label "phase/4B,owner:claude,blocked" \
  --body "## Summary
The Ablation B agent. Multi-hop retrieval via tool calls. Uses best Ablation A retriever.

## Owner
Claude

## Dependencies
Blocked by: TASK-020, TASK-026 (uses A's best retriever)

## Acceptance criteria
- [ ] \`harness/agents/react_agent.py\`: ReAct loop: think → act → observe → answer
- [ ] Four tools: search(query,k), follow_cross_refs(qa_id), filter_by_topic(topic), answer(text, cited_qa_ids)
- [ ] Trajectories logged as JSONL: step, thought, action, observation
- [ ] Terminates on answer() or max_steps; no infinite loops

## Estimated effort
4 hours (Claude)"

gh issue create --repo "$REPO" \
  --title "[TASK-028] B1 sanity check — 5 questions + trajectory review" \
  --label "phase/4B,owner:collaborative,blocked" \
  --body "## Summary
Gate before SME labeling investment. **You review 5 trajectories and decide whether B3 labeling is worthwhile.**

## Owner
Collaborative (Claude runs; you review)

## Dependencies
Blocked by: TASK-027

## Your task
Review the 5 trajectories in \`ablations/B_process_rewards/sanity_check_trajectories/\`. Assess: are thought steps coherent? Does the agent pick appropriate tools? Does it avoid loops?

Document your decision in \`ablations/B_process_rewards/SANITY_CHECK.md\`.
- **GO:** proceed to TASK-029 (SME labeling)
- **NO-GO:** skip TASK-029; proceed directly to B4 (tool descriptions only)

## Acceptance criteria
- [ ] B1 run on 5 benchmark questions (1 T1, 1 T2, 2 T3, 1 T4); trajectories saved
- [ ] Your go/no-go decision documented in SANITY_CHECK.md
- [ ] TASK-029 blocked or unblocked based on your decision

## Estimated effort
2 hours (Claude runs + your review ~30-60 min)"

gh issue create --repo "$REPO" \
  --title "[TASK-029] SME trajectory labeling (conditional — only if B1 sanity check passes)" \
  --label "phase/4B,owner:sme,blocked" \
  --body "## Summary
**Only run if TASK-028 resulted in a GO decision.** You label trajectory steps as good/suboptimal/wrong. Becomes few-shot training signal for B3.

## Owner
You (SME) — conditional

## Dependencies
Blocked by: TASK-028 (only if GO)

## Your task
Run B1 on a held-out subset. For each trajectory step, label:
- \`good_step\` — correct next action given history
- \`suboptimal_step\` — not wrong but not the best choice
- \`wrong_step\` — counterproductive

Plus one-line reason per label. Store in \`ablations/B_process_rewards/trajectory_labels.jsonl\`.

Review your first 10 labels for internal consistency before continuing.

## Acceptance criteria
- [ ] ≥50 trajectory steps labeled in \`trajectory_labels.jsonl\`
- [ ] Labels have rationale; first 10 reviewed for consistency
- [ ] Skipped if TASK-028 resulted in NO-GO

## Estimated effort
4 hours (your domain knowledge)"

gh issue create --repo "$REPO" \
  --title "[TASK-030] Run Ablation B variants B0–B4 + analysis report" \
  --label "phase/4B,owner:claude,blocked" \
  --body "## Summary
Run all applicable B variants. Key question: does process-reward supervision help on T3 multi-hop?

## Owner
Claude

## Dependencies
Blocked by: TASK-029 (or TASK-028 if B3 skipped)

## Acceptance criteria
- [ ] All applicable variants run (B0-B4, or B0/B1/B2/B4 if B3 skipped)
- [ ] Results in \`results/ablation_b/\`: per-type Recall@5, Correctness, Citation Accuracy + tool-call trace counts
- [ ] B2 vs B3 comparison explicit (LLM-judge process reward vs SME labels)
- [ ] \`ablations/B_process_rewards/FINDINGS.md\`: pre-registered predictions vs actual

## Estimated effort
3 hours (Claude)"

echo "Creating Phase 4C issues..."

gh issue create --repo "$REPO" \
  --title "[TASK-031] SME few-shot exemplars — author" \
  --label "phase/4C,owner:sme,blocked" \
  --body "## Summary
**You write 3-5 Q&A solving traces** for the Ablation C SME few-shot cells. These are the exemplars used across all three model tiers.

## Owner
You (SME)

## Dependencies
Blocked by: TASK-021

## Your task
Write \`harness/prompts/few_shot_examples.md\`. Each example:
\`\`\`
Question: [example question]
Retrieved: [3-5 Q&As from corpus — use held-out Q&As not in benchmark]
Reasoning: [SME-style reasoning: which Q&A to trust, how to disambiguate, how to follow cross-refs]
Answer: [gold-quality answer with qa_id citations]
\`\`\`

Cover: 1 T1, 1 T2, 1-2 T3 examples. **Use Q&As that are NOT in benchmark.jsonl.**

## Acceptance criteria
- [ ] 3-5 examples in \`harness/prompts/few_shot_examples.md\`
- [ ] Covers T1, T2, T3 question types
- [ ] All example Q&As are held-out from benchmark (not in benchmark.jsonl)
- [ ] Same prompt used identically across all three model tiers

## Estimated effort
3 hours (your domain knowledge)"

gh issue create --repo "$REPO" \
  --title "[TASK-032] OLMo 3 API + three model tiers setup" \
  --label "phase/4C,owner:claude,blocked" \
  --body "## Summary
Wire up the three model tiers for Ablation C: mid-tier, frontier reasoning, and OLMo 3 (the contamination-verifiable reference).

## Owner
Claude

## Dependencies
Blocked by: TASK-020

## Acceptance criteria
- [ ] \`harness/models.py\`: unified interface for mid-tier (Haiku 4.5), frontier reasoning (Opus 4.x), OLMo 3 (Together AI or self-hosted)
- [ ] OLMo 3 32B Think accessible via configured API endpoint
- [ ] All three models smoke-tested with a single call
- [ ] Model versions pinned in \`harness/configs/models.yaml\`

## Estimated effort
2 hours (Claude)"

gh issue create --repo "$REPO" \
  --title "[TASK-033] 3×3 grid runs (Ablation C) + analysis report" \
  --label "phase/4C,owner:claude,blocked" \
  --body "## Summary
Run all 9 cells of the prompting strategy × model tier grid. The contamination-robustness cross-check.

## Owner
Claude

## Dependencies
Blocked by: TASK-031, TASK-032

## Acceptance criteria
- [ ] All 9 cells run: 3 models × {zero-shot, SME few-shot, self-generated CoT}
- [ ] Results in \`results/ablation_c/\`: per-type Correctness and Citation Accuracy for all cells
- [ ] Δ(few-shot − zero-shot) chart across all three model tiers (row-pattern consistency)
- [ ] OlmoTrace used on 5 OLMo 3 answers to verify contamination status post-hoc
- [ ] \`ablations/C_prompting_matrix/FINDINGS.md\`: all pre-registered predictions checked

## Estimated effort
4 hours (Claude)"

echo "Creating Phase 5 issues..."

gh issue create --repo "$REPO" \
  --title "[TASK-034] Blog post draft" \
  --label "phase/5,owner:collaborative,blocked" \
  --body "## Summary
Claude drafts from BLOG_OUTLINE.md. **You revise the final post.**

## Owner
Collaborative (Claude drafts; you revise)

## Dependencies
Blocked by: TASK-026, TASK-030, TASK-033

## Acceptance criteria
- [ ] \`docs/blog_post.md\` follows structure in \`project_roadmap/BLOG_OUTLINE.md\`
- [ ] All three ablation findings reported; 'surprising finding' filled in from actual results
- [ ] Contamination caveats section present
- [ ] You have reviewed and approved final draft
- [ ] ~2000-2500 words

## Estimated effort
4 hours (Claude drafts + your review ~1-2h)"

gh issue create --repo "$REPO" \
  --title "[TASK-035] README, final repo structure, and release" \
  --label "phase/5,owner:claude,blocked" \
  --body "## Summary
Final deliverable: a repo someone else can clone, understand, and run in 30 minutes.

## Owner
Claude

## Dependencies
Blocked by: TASK-034

## Acceptance criteria
- [ ] README.md follows structure in \`project_roadmap/README_OUTLINE.md\`
- [ ] Quickstart: fresh clone + pip install + run baseline works in ≤30 minutes
- [ ] Honest limitations section: corpus size, English-only, EU-only, no biomedical reasoning
- [ ] CC-BY-4.0 (data) + MIT (code) licensing documented
- [ ] EMA content attribution section present

## Estimated effort
3 hours (Claude)"

echo ""
echo "✅ All 35 issues created for MoritzImendoerffer/ema_nlp"
echo "View them at: https://github.com/MoritzImendoerffer/ema_nlp/issues"

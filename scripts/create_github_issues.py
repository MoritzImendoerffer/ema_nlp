"""
Create GitHub issues for the EMA RAG Benchmark project using PyGithub.

Usage:
    GITHUB_TOKEN=ghp_xxx python3 scripts/create_github_issues.py

Get a token at: GitHub → Settings → Developer settings → Personal access tokens → Fine-grained
Required permissions: Issues (read/write), Metadata (read)

Run once from repo root. Safe to re-run — existing issues (matched by title) are skipped.
For updates to existing issues, use scripts/sync_github_issues.py instead.
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
PLAN = "https://github.com/MoritzImendoerffer/ema_nlp/blob/main/.claude/work/2026-05-10_02_implementation-plan/implementation-plan.md"

# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

LABELS = [
    ("phase/0",           "0075ca", "Phase 0: Scoping"),
    ("phase/1",           "0052cc", "Phase 1: Corpus extraction"),
    ("phase/1.5",         "003d99", "Phase 1.5: Contamination check"),
    ("phase/2",           "7057ff", "Phase 2: Benchmark construction"),
    ("phase/3",           "b60205", "Phase 3: Baseline RAG"),
    ("phase/4A",          "e4e669", "Phase 4A: Ablation A - evidence filtering"),
    ("phase/4B",          "d93f0b", "Phase 4B: Ablation B - process rewards"),
    ("phase/4C",          "0e8a16", "Phase 4C: Ablation C - prompting matrix"),
    ("phase/5",           "c5def5", "Phase 5: Writeup and release"),
    ("owner:claude",      "bfd4f2", "Claude implements"),
    ("owner:sme",         "fef2c0", "You (SME) must do this"),
    ("owner:collab",      "d4edda", "Both: Claude scaffolds, SME decides"),
    ("blocked",           "e4e4e4", "Waiting on another task"),
    ("infra",             "f9d0c4", "Infrastructure / machine setup"),
]


def _b(owner, phase, effort, summary, deps="—", sme_action=None, status=None):
    """Return a compact issue body."""
    lines = [f"**Owner:** {owner} · **Phase:** {phase} · **Effort:** {effort}"]
    if status:
        lines[0] += f" · **{status}**"
    lines += ["", summary, "", f"**Depends on:** {deps}", "", f"→ [Full spec]({PLAN})"]
    if sme_action:
        lines.insert(4, f"**Your action:** {sme_action}")
        lines.insert(5, "")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Issues — (title, labels, body)
# ---------------------------------------------------------------------------

ISSUES = [
    # ── Infrastructure ────────────────────────────────────────────────────
    (
        "[INFRA] Create ~/.myenvs/ema_nlp.env with all required credentials",
        ["infra"],
        """\
**Owner:** You · **Status:** per-machine setup task

Create `~/.myenvs/ema_nlp.env` (never committed). Required before any script that hits an external service.

| Variable | Purpose |
|----------|---------|
| `MONGO_URI` | MongoDB — default `mongodb://localhost:27017/` |
| `ANTHROPIC_API_KEY` | Claude API (needed from Phase 3 onward) |
| `GITHUB_TOKEN` | Issues API — fine-grained, Issues read/write + Metadata read |

```bash
mkdir -p ~/.myenvs
cat > ~/.myenvs/ema_nlp.env << 'EOF'
MONGO_URI=mongodb://localhost:27017/
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...
EOF
chmod 600 ~/.myenvs/ema_nlp.env
```

Close this issue once the file exists and `python3 -c "import config"` runs without error.""",
    ),

    # ── Phase 0 ──────────────────────────────────────────────────────────
    (
        "[TASK-001] MongoDB Q&A inventory query",
        ["phase/0", "owner:claude"],
        _b("Claude", "0", "2h",
           "✅ 165 sources found (64 HTML, 101 PDFs). 1,506 estimated Q&A pairs. GO signal met.",
           status="Completed"),
    ),
    (
        "[TASK-002] Topic stratification + cross-ref chain completeness",
        ["phase/0", "owner:claude"],
        _b("Claude", "0", "3h",
           "✅ 11 clusters. Research & Dev largest (492 Q&As). Chain completeness 43.6%. 2 thin PDF-only clusters.",
           status="Completed"),
    ),
    (
        "[TASK-003] Go/no-go decision notebook",
        ["phase/0", "owner:collab"],
        _b("Collaborative", "0", "2h",
           '✅ Decision: GO — "The project scope is clear. The clusters are representative and the chain completeness is ok."',
           status="Completed"),
    ),

    # ── Phase 1 ──────────────────────────────────────────────────────────
    (
        "[TASK-004] Project setup — pyproject.toml, directory structure, schema docs",
        ["phase/1", "owner:claude"],
        _b("Claude", "1", "2h",
           "✅ All dirs created. pytest/ruff/mypy pass. Deps pinned at latest stable.",
           status="Completed"),
    ),
    (
        "[TASK-005] HTML accordion extractor",
        ["phase/1", "owner:claude"],
        _b("Claude", "1", "3h",
           "✅ 10 tests pass. 100% capture rate on 3 fixtures (33 items). Confidence logic on ?-endings and interrogative words.",
           status="Completed"),
    ),
    (
        "[TASK-006] PDF Q&A extractor",
        ["phase/1", "owner:claude"],
        _b("Claude", "1", "4h",
           "✅ 14 tests pass. Benzyl alcohol PDF: 5 Q&As, cross-refs resolved, revision parsed correctly.",
           status="Completed"),
    ),
    (
        "[TASK-007A] build_corpus.py — pure dedup/filter/write logic (no MongoDB)",
        ["phase/1", "owner:claude", "blocked"],
        _b("Claude", "1", "2h",
           "Source-agnostic orchestrator: `build_corpus(records: Iterable[QARecord], output_path) → CorpusStats`. "
           "Hash dedup (PDF preferred), landing-page filter, JSONL write, dedup/filter logs. No pymongo import.",
           deps="TASK-005, TASK-006"),
    ),
    (
        "[TASK-007B] Mini-corpus HTTP fetcher — ~100 real Q&As without MongoDB",
        ["phase/1", "owner:claude", "blocked"],
        _b("Claude", "1", "1h",
           "Fetch 10 EMA Q&A pages from `phase0_inventory.csv` via httpx → `corpus/mini_corpus.jsonl`. "
           "Dev fixture for Phases 3+ when MongoDB is unavailable. Not a substitute for the full corpus.",
           deps="TASK-007A"),
    ),
    (
        "[TASK-007] MongoDB adaptor — feeds build_corpus from ema_scraper.web_items",
        ["phase/1", "owner:claude", "blocked"],
        _b("Claude", "1", "2h",
           "`corpus/sources/mongo_source.py`: iterator over `web_items` → yields QARecord objects into `build_corpus()` → `corpus/corpus.jsonl`. "
           "Blocked until MongoDB is available.",
           deps="TASK-007A + MongoDB available"),
    ),
    (
        "[TASK-008] Corpus manifest — corpus.jsonl + corpus_stats.md",
        ["phase/1", "owner:claude", "blocked"],
        _b("Claude", "1", "2h",
           "Write `corpus/corpus.jsonl`. Validate schema. Generate `corpus_stats.md`. "
           "Gate: ≥200 Q&A records across ≥3 topic paths, or script halts with SCOPE-RISK.",
           deps="TASK-007"),
    ),

    # ── Phase 1.5 ─────────────────────────────────────────────────────────
    (
        "[TASK-009] Training data contamination check — Dolma 3 / Common Corpus",
        ["phase/1.5", "owner:claude", "blocked"],
        _b("Claude", "1.5", "3h",
           "Search 5-10 distinctive sentences per source doc in Dolma 3 + Common Corpus. "
           "Per-doc status (present/absent/partial) → `docs/training_data_verification.md`. "
           "Gates benchmark construction (TASK-010–013).",
           deps="TASK-008"),
    ),

    # ── Phase 2 ──────────────────────────────────────────────────────────
    (
        "[TASK-010] T1 Lookup benchmark questions — candidates + SME review",
        ["phase/2", "owner:collab", "blocked"],
        _b("Collaborative", "2", "3h",
           "Claude generates 30 T1 candidates + 2 paraphrases each. You select 20 and validate gold answers.",
           deps="TASK-008, TASK-009",
           sme_action="Review `benchmark/candidates/t1_candidates.jsonl`, mark 20 items `accepted=true`."),
    ),
    (
        "[TASK-011] T2 Scoping benchmark questions — author",
        ["phase/2", "owner:sme", "blocked"],
        _b("You (SME)", "2", "4h",
           "Author 10 T2 questions: each pairs 1 correct Q&A with 2 topically-adjacent distractors. "
           "Claude converts to JSONL and adds paraphrases.",
           deps="TASK-008, TASK-009",
           sme_action="Draft in `benchmark/candidates/t2_authored.md`."),
    ),
    (
        "[TASK-012] T3 Multi-hop benchmark questions — chain composition",
        ["phase/2", "owner:collab", "blocked"],
        _b("Collaborative", "2", "3h",
           "Claude enumerates in-corpus cross-ref chains of length ≥2 → `t3_chain_map.md`. "
           "You compose 10 questions requiring full chain traversal.",
           deps="TASK-008, TASK-009, TASK-002",
           sme_action="Compose questions from `benchmark/candidates/t3_chain_map.md`."),
    ),
    (
        "[TASK-013] T4 Synthesis benchmark questions — hand-curate",
        ["phase/2", "owner:sme", "blocked"],
        _b("You (SME)", "2", "3h",
           "Hand-curate ≥5 synthesis questions combining Q&As from ≥2 source documents. "
           "Include ≥2 composite/counterfactual items for contamination resistance.",
           deps="TASK-008, TASK-009",
           sme_action="Write items; include `gold_qa_ids` spanning ≥2 distinct source_urls."),
    ),
    (
        "[TASK-014] Benchmark JSONL finalisation + validation script",
        ["phase/2", "owner:claude", "blocked"],
        _b("Claude", "2", "2h",
           "`benchmark/validate_benchmark.py`: checks no duplicate bench_ids, all gold_qa_ids in corpus, "
           "paraphrases present, distribution T1=20/T2=10/T3=10/T4≥5.",
           deps="TASK-010, TASK-011, TASK-012, TASK-013"),
    ),
    (
        "[TASK-015] Closed-book contamination screen",
        ["phase/2", "owner:claude", "blocked"],
        _b("Claude", "2", "3h",
           "Run all benchmark items through configured models with no retrieval. "
           "PASS/FAIL gate: if zero_shot_known > 40% on T1 for any model, those items flagged REMOVE.",
           deps="TASK-014"),
    ),

    # ── Phase 3 ──────────────────────────────────────────────────────────
    (
        "[TASK-016] Embedding pipeline + FAISS vector store",
        ["phase/3", "owner:claude", "blocked"],
        _b("Claude", "3", "3-4h",
           "LlamaIndex `DocumentSummaryIndex` + BGE-large-en + FAISS flat index. "
           "`NodeRelationship.RELATED` for cross-refs. Index persisted to `harness/index/`. "
           "Re-index from `corpus.jsonl` after TASK-008 for production.",
           deps="TASK-007B (dev) / TASK-008 (production)"),
    ),
    (
        "[TASK-016.5] IDMP ontology concept tagging — node metadata",
        ["phase/3", "owner:claude", "blocked"],
        _b("Claude", "3", "2h",
           "Parse IDMP RDF → ~50-100 regulatory concepts. Tag each Q&A node with `metadata['concepts']`. "
           "Write `harness/ontology/concepts.yaml`. `filter_by_concept()` retriever. Graceful fallback if RDF absent.",
           deps="TASK-016"),
    ),
    (
        "[TASK-017] BM25 hybrid retrieval",
        ["phase/3", "owner:claude", "blocked"],
        _b("Claude", "3", "2h",
           "LlamaIndex `BM25Retriever` + `QueryFusionRetriever` (RRF). "
           "Mode selectable via config: dense-only (A0), BM25-only, hybrid (A0+).",
           deps="TASK-016"),
    ),
    (
        "[TASK-018] Evaluation harness — Recall@k, Precision@k, Citation Accuracy",
        ["phase/3", "owner:claude", "blocked"],
        _b("Claude", "3", "3h",
           "`harness/eval_retrieval.py`: all three metrics per item, broken down by T1–T4. Grouped bar chart PNG.",
           deps="TASK-017"),
    ),
    (
        "[TASK-019] LLM judge — Faithfulness + Correctness",
        ["phase/3", "owner:claude", "blocked"],
        _b("Claude", "3", "3h",
           "Judge prompts as files (`harness/judges/`). Separate judge model from generator. "
           "Score 0–1 + one-line rationale. Agreement validation on 20% hand-graded sample.",
           deps="TASK-018"),
    ),
    (
        "[TASK-020] Config-as-code + results logging infrastructure",
        ["phase/3", "owner:claude", "blocked"],
        _b("Claude", "3", "3h",
           "Single `run_eval.py` entry point, YAML-driven. Arize Phoenix launched at startup. "
           "Results in `results/<run_id>/` with config copy, JSONL outputs, metrics, plots, traces.",
           deps="TASK-018, TASK-019"),
    ),
    (
        "[TASK-021] Baseline run (A0 + A0+) + results report",
        ["phase/3", "owner:claude", "blocked"],
        _b("Claude", "3", "2h",
           "Full A0 (dense-only) and A0+ (hybrid) runs. `results/baseline/baseline_report.md`: "
           "all 5 metrics × T1–T4, open-book vs closed-book, lift. Fixed reference for all ablations.",
           deps="TASK-015, TASK-020"),
    ),

    # ── Phase 4A ─────────────────────────────────────────────────────────
    (
        "[TASK-022] SME acronym dictionary — author",
        ["phase/4A", "owner:sme", "blocked"],
        _b("You (SME)", "4A", "4h",
           "≥30 entries covering AI=Acceptable Intake, MAH, ICH Q3A/M7/Q9, GMP, CEP, ASMF, TTC, LoQ, ppm/ppb, etc. "
           "Claude integrates into A1 query expansion.",
           deps="TASK-008",
           sme_action="Write `ablations/A_evidence_filter/acronym_dict.yaml`. Can be authored any time after corpus."),
    ),
    (
        "[TASK-023] A1 query expansion + A2 topic-path filter",
        ["phase/4A", "owner:claude", "blocked"],
        _b("Claude", "4A", "2h",
           "`a1_query_expansion.py` expands queries using acronym dict. "
           "`a2_topic_filter.py`: two modes — topic_path keyword filter or IDMP concept metadata filter.",
           deps="TASK-022, TASK-016.5"),
    ),
    (
        "[TASK-024] SME relevance rubric — author",
        ["phase/4A", "owner:sme", "blocked"],
        _b("You (SME)", "4A", "2h",
           "~200-word rubric defining relevant vs non-relevant for EMA Q&A reranking "
           "(scope alignment, threshold specificity, MAH vs applicant, CAP vs NAP).",
           deps="TASK-008",
           sme_action="Write `harness/prompts/relevance_rubric_sme.md`. Can be authored any time after corpus."),
    ),
    (
        "[TASK-025] A3/A4 LLM reranker (SME rubric vs generic)",
        ["phase/4A", "owner:claude", "blocked"],
        _b("Claude", "4A", "3h",
           "`a3_reranker.py` uses SME rubric; `a4_reranker.py` uses generic 'is this relevant?' prompt. "
           "Both Haiku-tier, cost-capped at ≤40 questions × 5 chunks.",
           deps="TASK-024"),
    ),
    (
        "[TASK-026] Run Ablation A variants A0–A5 + analysis report",
        ["phase/4A", "owner:claude", "blocked"],
        _b("Claude", "4A", "3h",
           "All 6 variants (A0, A0+, A1, A2, A3, A4, A5). A3 vs A4 comparison explicit. "
           "`ablations/A_evidence_filter/FINDINGS.md` with pre-registered predictions vs actual.",
           deps="TASK-023, TASK-025"),
    ),

    # ── Phase 4B ─────────────────────────────────────────────────────────
    (
        "[TASK-027] ReAct agent + tools (search, follow_cross_refs, filter_by_topic, answer)",
        ["phase/4B", "owner:claude", "blocked"],
        _b("Claude", "4B", "3h",
           "LlamaIndex `ReActAgent` with 4 `FunctionTool` wrappers. `follow_cross_refs` uses "
           "`NodeRelationship.RELATED` — O(1) lookup. Trajectories captured by Phoenix automatically.",
           deps="TASK-020, TASK-026"),
    ),
    (
        "[TASK-027.5] Query cache — FAISS index over past query embeddings",
        ["phase/4B", "owner:claude", "blocked"],
        _b("Claude", "4B", "2h",
           "Secondary FAISS index over past query embeddings → `harness/index/query_cache.faiss`. "
           "JSON sidecar maps vector id → {run_id, question, answer_summary, rating, cited_qa_ids}. "
           "Similarity threshold configurable (default 0.88). Benchmark configs always set `cache: false`.",
           deps="TASK-020, TASK-016"),
    ),
    (
        "[TASK-027.6] Semantic cache CLI — similarity lookup + user confirmation",
        ["phase/4B", "owner:claude", "blocked"],
        _b("Claude", "4B", "1h",
           "Before each interactive agent run: call `query_cache.get_similar()`, present matches. "
           "User options: use cached / use as few-shot context / run fresh. Skipped for benchmark runs.",
           deps="TASK-027.5"),
    ),
    (
        "[TASK-027.7] Runtime few-shot injection — top-k rated trajectories in agent prompt",
        ["phase/4B", "owner:claude", "blocked"],
        _b("Claude", "4B", "2h",
           "Fetch top-k similar trajectories rated ≥4/5 from query cache + Phoenix API. "
           "Inject as few-shot block into ReActAgent system prompt. Logged as Phoenix trace metadata.",
           deps="TASK-027.5, TASK-027, TASK-027.8"),
    ),
    (
        "[TASK-027.8] CLI rating UI + Phoenix annotation posting",
        ["phase/4B", "owner:claude", "blocked"],
        _b("Claude", "4B", "1h",
           "After each agent run: prompt for 1–5 rating + optional note + per-step labels. "
           "Post to Phoenix annotation API. Update query cache sidecar. Always skippable.",
           deps="TASK-027"),
    ),
    (
        "[TASK-027.9] JSONL export from Phoenix rated traces",
        ["phase/4B", "owner:claude", "blocked"],
        _b("Claude", "4B", "1h",
           "`export_rated_traces(min_rating, output_path)` → JSONL. Feeds TASK-029 labeling workflow. "
           "Filterable by rating, date range, model, retriever. Committable as reproducibility artifact.",
           deps="TASK-027.8"),
    ),
    (
        "[TASK-028] B1 sanity check — 5 questions + trajectory review",
        ["phase/4B", "owner:collab", "blocked"],
        _b("Collaborative", "4B", "2h",
           "Claude runs B1 on 5 questions (1 T1, 1 T2, 2 T3, 1 T4). "
           "You review trajectories for coherence, tool selection, no runaway loops. "
           "Go/no-go for B3 labeling documented in `ablations/B_process_rewards/SANITY_CHECK.md`.",
           deps="TASK-027",
           sme_action="Review trajectories; record GO/NO-GO in SANITY_CHECK.md."),
    ),
    (
        "[TASK-029] SME trajectory labeling (conditional — only if B1 passes)",
        ["phase/4B", "owner:sme", "blocked"],
        _b("You (SME)", "4B", "4h",
           "Label ≥50 trajectory steps as good_step / suboptimal_step / wrong_step + one-line reason. "
           "Skipped entirely if TASK-028 records NO-GO.",
           deps="TASK-028 (GO only)",
           sme_action="Run B1 on held-out subset; label steps in `ablations/B_process_rewards/trajectory_labels.jsonl`."),
    ),
    (
        "[TASK-030] Run Ablation B variants B0–B4 + analysis report",
        ["phase/4B", "owner:claude", "blocked"],
        _b("Claude", "4B", "3h",
           "Read SANITY_CHECK.md to determine which variants apply. "
           "If B3 GO: run B0/B1/B2/B3/B4. If NO-GO: skip B3. "
           "`ablations/B_process_rewards/FINDINGS.md` with pre-registered predictions vs actual.",
           deps="TASK-028, TASK-029 (if GO)"),
    ),

    # ── Phase 4C ─────────────────────────────────────────────────────────
    (
        "[TASK-031] SME few-shot exemplars — author",
        ["phase/4C", "owner:sme", "blocked"],
        _b("You (SME)", "4C", "3h",
           "3–5 Q&A solving traces covering T1/T2/T3. Must use held-out Q&As not in benchmark. "
           "Same examples used across all three model tiers.",
           deps="TASK-021",
           sme_action="Write `harness/prompts/few_shot_examples.md`."),
    ),
    (
        "[TASK-032] OLMo 3 API + three model tiers setup",
        ["phase/4C", "owner:claude", "blocked"],
        _b("Claude", "4C", "2h",
           "`harness/models.py`: unified interface for Haiku 4.5, Opus 4.x, OLMo 3 (Together AI). "
           "All three smoke-tested. Model versions pinned in `harness/configs/models.yaml`.",
           deps="TASK-020"),
    ),
    (
        "[TASK-033] 3×3 grid runs (Ablation C) + analysis report",
        ["phase/4C", "owner:claude", "blocked"],
        _b("Claude", "4C", "4h",
           "All 9 cells: 3 models × {zero-shot, SME few-shot, self-generated CoT}. "
           "Δ(few-shot − zero-shot) chart. OlmoTrace on 5 OLMo 3 answers. "
           "`ablations/C_prompting_matrix/FINDINGS.md`.",
           deps="TASK-031, TASK-032"),
    ),

    # ── Phase 5 ──────────────────────────────────────────────────────────
    (
        "[TASK-034] Blog post draft",
        ["phase/5", "owner:collab", "blocked"],
        _b("Collaborative", "5", "4h",
           "Claude drafts from `BLOG_OUTLINE.md`. You revise. ~2000–2500 words. "
           "All three ablation findings + contamination caveats section.",
           deps="TASK-026, TASK-030, TASK-033",
           sme_action="Review and approve final draft."),
    ),
    (
        "[TASK-035] README, final repo structure, and release",
        ["phase/5", "owner:claude", "blocked"],
        _b("Claude", "5", "3h",
           "README follows `README_OUTLINE.md`. Fresh-clone quickstart ≤30 min. "
           "Honest limitations. CC-BY-4.0 (data) + MIT (code) licensing.",
           deps="TASK-034"),
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ensure_labels(repo) -> None:
    existing = {lbl.name for lbl in repo.get_labels()}
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
        time.sleep(0.5)

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

    from github import Auth
    g = Github(auth=Auth.Token(token))
    try:
        repo = g.get_repo(REPO_NAME)
        print(f"Connected to: {repo.full_name}")
    except GithubException as e:
        print(f"Error accessing repo: {e}")
        sys.exit(1)

    print("\nEnsuring labels exist...")
    ensure_labels(repo)

    print("\nCreating issues...")
    create_issues(repo)

    print(f"\nView issues at: https://github.com/{REPO_NAME}/issues")


if __name__ == "__main__":
    main()

# Documentation staleness audit (2026-06-04)

Produced by an 11-agent parallel audit of every doc file against the current codebase
(`docs-staleness-audit` workflow). Each doc was read in full and spot-checked against the code it
describes. Verdicts and the concrete fixes that seed the DOC-* tasks in `state.json`.

## Root cause of staleness

The retrieval refactor (LIR-001..012) + the 2026-06-04 link-extraction upgrade (work unit 24) landed
*after* most docs were last touched. The four recurring stale claims:
1. **pgvector / FAISS-over-corpus / `EMA_RETRIEVER` / `harness/retrieve*.py` / `harness/embed*.py`** as
   current — all **deleted** (LIR-012). Selection is now `EMA_INDEX_PROFILE`.
2. **"re-seam pending / CPU subset"** — the workflow+UI re-seam (LIR-009/010) and full graph build are
   **done**; the live graph is the full 79,882-doc build.
3. **`LINKS_TO` = 1.72M / 2.2M anchors** — now **99,520** (typed, main-content-scoped) after work unit 24.
4. **`run_eval.py` / eval+judge suite / 9 workflows** — the eval suite is **archived off-branch**; there
   are **7** workflows.

## Per-doc verdicts

| Doc | Verdict | Priority | Task |
|-----|---------|----------|------|
| `CLAUDE.md` | needs-minor-patch | HIGH | DOC-001 |
| `README.md` | needs-minor-patch | HIGH | DOC-002 |
| `docs/RETRIEVAL.md` | needs-minor-patch | MED | DOC-003 |
| `chainlit.md` | needs-major-rewrite | HIGH | DOC-004 |
| `docs/ARCHITECTURE.md` | needs-minor-patch (many spots) | HIGH | DOC-005 |
| `docs/ONBOARDING.md` | needs-major-rewrite (~70% pre-refactor) | HIGH | DOC-006 |
| `docs/SETUP.md` | needs-major-rewrite (several sections) | HIGH | DOC-007 |
| `HARNESS_REFACTORS.md` | needs-major-rewrite | MED | DOC-008 |
| `project_roadmap/ROADMAP.md` | needs-major-rewrite (delete Phase 1.7) | HIGH | DOC-009 |
| `OPEN_QUESTIONS.md` | needs-minor-patch | LOW-MED | DOC-010 |
| `project_roadmap/ABLATIONS.md` | one-line clarification | LOW | DOC-011 |
| `docs/WORKFLOWS.md` | **current** | — | leave |
| `docs/RETRIEVAL_TRACKS.md` | **current** | — | leave |
| `corpus/corpus_stats.md` | **current** (counts verified) | — | leave |
| `corpus/SCHEMA.md`, `benchmark/SCHEMA.md`, `benchmark/STATS.md` | likely current | LOW | verify in DOC-011 |
| `project_roadmap/{GLOSSARY,LEAKAGE,BLOG_OUTLINE,README_OUTLINE,CLAUDE_CODE_SETUP}.md` | evergreen | — | leave |

## Concrete fixes per doc

### DOC-001 · CLAUDE.md (patch)
- Banner line 6: `1.72M LINKS_TO edges` → `99,520 main-content-scoped LINKS_TO edges` (work unit 24).
- Line 11 disclaimer ("lingering pgvector/FAISS/EMA_RETRIEVER mentions are historical") — condense/remove;
  no phantom references remain.
- Note LIR-009/010 (2026-06-02), LIR-012 (2026-06-03), work unit 24 (2026-06-04) all complete; LIR-011
  (live Phoenix UI) is in place via app.py.

### DOC-002 · README.md (patch)
- Refactor banner (lines 7-14): drop "verified on a CPU subset; re-seaming workflows + chat UI and deleting
  the old stack are pending" → refactor **complete** (full graph, old stack deleted).
- Current status (41-44): remove the ⏳ LIR-009/010/012-pending bullet; mark done. "verified live on a CPU
  subset" → full corpus (79,882 docs).
- Data-sources footnote¹ (71): `parsed_documents` "subset seeded / never backfilled at scale" is stale — the
  full 79,882-doc graph was built from it (~80k docs). Update.
- Stack table (50-60): **current — leave.** Deliverables benchmark "~50" → 45 (consistency).

### DOC-003 · docs/RETRIEVAL.md (patch — only the status box remains stale)
- Status box (lines 9-15): date → 2026-06-04, mark refactor **complete**, remove "CPU subset" caveat, cite
  full graph (79,882 docs / 5.82M leaves / **99,520** LINKS_TO). (The links.py code-map row + the LINKS_TO
  edge bullet were already patched 2026-06-04.)

### DOC-004 · chainlit.md (rewrite — small file)
- Line 6 "Hybrid retrieval (dense + BM25 fusion) over EMA Q&A corpus" → hierarchical Neo4j
  PropertyGraphIndex over EMA regulatory **documents** (parsed_documents, not corpus.jsonl); small-to-big +
  LINKS_TO; BGE-large.
- Lines 9-10 per-step ratings → clarify multi-step workflows (CRAG/ReAct/…) vs single-step simple_rag.
- Add: `EMA_INDEX_PROFILE` / `neo4j_hier`; the 7 workflow strategies (or link app.py).

### DOC-005 · docs/ARCHITECTURE.md (patch, multiple spots)
- Intro warning (5-11): LIR-009/010/012 are **complete**; legacy `harness/retrieve*.py`/`embed*.py`/`pg/`
  deleted.
- Mermaid diagram (31-32): remove "(re-seam pending)" / "(seam pending)".
- §4 (113-114): workflows now consume the LlamaIndex retriever directly (constructor arg) — LIR-009 done.
- Line 106 tools "(redesign pending LIR-009)" — update/clarify.
- Line 168 scripts table "*(build entry pending UI seam)*" — remove.
- Add LINKS_TO 1.72M→99,520 note.

### DOC-006 · docs/ONBOARDING.md (major rewrite — biggest)
- Replace the pre-Neo4j data-flow diagram (59-79) with: Mongo `parsed_documents` →
  `harness.indexing.build_index` → Neo4j PropertyGraphIndex → `HierarchicalPGRetriever` → `get_workflow()`
  → app.py / Phoenix.
- File-map table + "Common tasks" (184-232): remove `run_eval.py`/`harness.embed`/`harness/retrieve.py`/
  `label_session.py`/`ablations.B_process_rewards`/FAISS; replace with `harness.indexing.build_index`,
  `EMA_INDEX_PROFILE`, Chainlit UI / `get_workflow()`, Phoenix annotations + `harness/rating.py`.
- "9 strategies" → **7** (+ prompt_strategy variants); link docs/WORKFLOWS.md.
- Add an explicit "Archived (on archive/pre-llamaindex-refactor)" callout for the eval/judge/ablation suite
  and the lift metric.
- "What you should hold in your head" (246-251): rewrite the 3-axis-grid / RetrievalConfig points.

### DOC-007 · docs/SETUP.md (rewrite stale sections)
- §5 MongoDB sync (213-258): `scripts/sync_mongo.sh` deleted — replace with a note / raw mongodump.
- Nextcloud layout: `index/ ← FAISS + docstore` (374) and the `base_dir results` line (365) — eval
  archived; remove/clarify.
- Phoenix env (294-299): `PHOENIX_COLLECTOR_ENDPOINT` → **`PHOENIX_URL`**; "harness/providers.py reads it"
  → **app.py** registers via `phoenix.otel` (lines 34, 142-148).
- `EMA_CORPUS_PATH`/`EMA_INDEX_PATH` (105-108): verify usage in config.py; remove if dead.
- §2 env vars: drop `NEXTCLOUD_DATASETS` if unused. (`EMA_INDEX_PROFILE` note at 91-92 is correct.)

### DOC-008 · HARNESS_REFACTORS.md (rewrite)
- Collapse Change 2 (build_retrieve_fn, lines 86-133) to a 4-5 line **[SUPERSEDED]** history note (impl'd
  commit 616d338 2026-05-25, removed LIR-012 commit 7bcf5a5).
- Add a completion note for Changes 1 + 3 (shipped, in effect); strike their Effort/Acceptance.
- Fix cross-ref `docs/RETRIEVAL_PIPELINE.md` → `docs/RETRIEVAL.md` (215).

### DOC-009 · project_roadmap/ROADMAP.md (major rewrite)
- Delete Phase 1.7 entirely (Postgres/pgvector, ~lines 115-161, incl. §1.7.1-1.7.5) — backend deleted in
  LIR-012; replace with a single archived-note line.
- Non-goals (14): "No Neo4j" is wrong — Neo4j is the store; "No EPARs" lifted for retrieval (2026-06-02).
- v2+ deferral list (~333-335): remove "Graph RAG (Neo4j)" and "EPARs" (now in scope); reframe to graph-
  ontology/SPARQL.
- Note Phase 2/3 benchmark+eval is archived pending rebuild on the Neo4j API.

### DOC-010 · OPEN_QUESTIONS.md (patch)
- "Embedding model: confirm BGE-large" — **resolved** (BGE-large built into the full graph); move to
  DECISIONS or mark resolved.
- Add a top note: the feedback/benchmark/judge/ablation questions (rating UI, judge model, ablation B,
  index-build TASK numbers) reference the **archived eval suite** and are deferred until it is rebuilt.

### DOC-011 · low-priority sweep
- ABLATIONS.md (9-10): one-line "[note] the Phase 3 eval harness is archived; must be rebuilt on the Neo4j
  API before Phase 4 ablations run."
- Verify counts in `benchmark/SCHEMA.md` / `benchmark/STATS.md` / `corpus/SCHEMA.md` (likely current —
  patch only if drift). GLOSSARY/LEAKAGE/corpus_stats: leave.

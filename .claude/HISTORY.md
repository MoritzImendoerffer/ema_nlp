# Project Work History

Chronological log of all interactions that produced code or config changes.
Do not load this file at session start — read it only when the user asks.

---

| Date | Summary | Changed | Phase | Work unit |
|------|---------|---------|-------|-----------|
| 2026-05-10 | Validated project plan against literature, researched IDMP-O ontology, surfaced roadmap gaps | — | Phase 0 | [exploration](.claude/work/2026-05-10_01_project-exploration/exploration.md) |
| 2026-05-10 | Generated 35-task implementation plan with acceptance criteria and GitHub issue creation script | `scripts/create_github_issues.py`, `scripts/create_github_issues.sh` | Phase 0 | [plan](.claude/work/2026-05-10_02_implementation-plan/implementation-plan.md) |
| 2026-05-10 | Executed Phase 0 inventory: 165 sources, 1,506 est. pairs, 11 topic clusters, 43.6% chain completeness | `scripts/phase0_inventory.py`, `scripts/phase0_topic_report.py` | Phase 0 | [phase0-execution](.claude/work/2026-05-10_03_phase0-execution/decisions.md) |
| 2026-05-15 | Added HTML accordion extractor and PDF Q&A extractor with tests | `corpus/extraction/`, `tests/` | Phase 1 | — |
| 2026-05-15 | Added portable setup script, one-way MongoDB sync script, and dotenv-based config | `scripts/setup.sh`, `scripts/sync_mongo.sh`, `config.py`, `pyproject.toml` | Phase 0 | — |
| 2026-05-15 | Updated HISTORY.md schema (5-column) and CLAUDE.md work-history rule to trigger on all code changes | `CLAUDE.md`, `.claude/HISTORY.md` | Phase 0 | — |
| 2026-05-15 | Added docs/SETUP.md with full setup + sync guide; extended sync_mongo.sh with export/import subcommands via Nextcloud; updated README | `docs/SETUP.md`, `scripts/sync_mongo.sh`, `README.md` | Phase 0 | — |
| 2026-05-15 | Architecture exploration: agentic memory via LlamaIndex DocumentSummaryIndex, model-agnostic tracing via Arize Phoenix/OpenInference, ontology as node metadata | — | Phase 1 | [exploration](.claude/work/2026-05-15_04_agentic-memory-architecture/exploration.md) |
| 2026-05-15 | Adopted LlamaIndex as retrieval framework; updated TASK-016/017/020/027 in state.json; added TASK-016.5 (ontology metadata); added LlamaIndex+Phoenix deps to pyproject.toml | `pyproject.toml`, `state.json`, `implementation-plan.md` | Phase 1 | — |
| 2026-05-15 | Architecture exploration: RL-style feedback store, semantic cache with user confirmation, online few-shot learning from rated trajectories | — | Phase 1 | [exploration](.claude/work/2026-05-15_05_rl-feedback-cache/exploration.md) |
| 2026-05-15 | Revised RL/cache design after library research: Phoenix annotations replace SQLite, thin FAISS query cache stays custom, DSPy deferred; added TASK-027.5–027.9 to state.json | `.claude/work/2026-05-15_05_rl-feedback-cache/exploration.md`, `state.json` | Phase 1 | — |
| 2026-05-15 | Added DECISIONS.md and OPEN_QUESTIONS.md; rewrote README.md (removed stale Neo4j section); updated CLAUDE.md (phase, commands, decisions pointer) | `DECISIONS.md`, `OPEN_QUESTIONS.md`, `README.md`, `CLAUDE.md` | Phase 1 | — |
| 2026-05-15 | Adversarial plan review (24 issues); applied 7 critical + 3 significant fixes to state.json and implementation-plan.md: TASK-009 now gates benchmark construction; TASK-022/024 unblocked to TASK-008; TASK-016.5 wired to TASK-023; TASK-027.7 fixed to depend on TASK-027.8; TASK-030 handles TASK-029 skip path; TASK-015 pass/fail threshold added | `.claude/work/2026-05-10_02_implementation-plan/state.json`, `.claude/work/2026-05-10_02_implementation-plan/implementation-plan.md` | Phase 1 | — |
| 2026-05-17 | Offline plan: split TASK-007 into TASK-007A (pure logic), TASK-007B (mini-corpus HTTP), TASK-007 (MongoDB adaptor); relaxed TASK-016 dependency to TASK-007B; updated state.json and implementation-plan.md | `state.json`, `implementation-plan.md` | Phase 1 | [plan](.claude/work/2026-05-10_02_implementation-plan/implementation-plan.md) |
| 2026-05-17 | Updated create_github_issues.py with new/changed tasks and completed statuses; wrote sync_github_issues.py (create+update+close delta sync) | `scripts/create_github_issues.py`, `scripts/sync_github_issues.py` | Phase 1 | — |
| 2026-05-17 | Completed TASK-007A (build_corpus.py, 16 tests), TASK-007B (fetch_mini_corpus.py), TASK-016 (harness/embed.py, VectorStoreIndex+FAISS, 11 tests incl. top-1 retrieval); fixed FakeEmbedModel to subclass BaseEmbedding; fixed excluded_embed_metadata_keys bug | `corpus/build_corpus.py`, `scripts/fetch_mini_corpus.py`, `harness/embed.py`, `tests/test_build_corpus.py`, `tests/test_embed.py`, `state.json` | Phase 1/3 | [plan](.claude/work/2026-05-10_02_implementation-plan/implementation-plan.md) |
| 2026-05-17 | Completed TASK-017: BM25Retriever + manual RRF hybrid fusion (harness/retrieve.py, 8 tests); QueryFusionRetriever avoided since it requires OpenAI install; RRF implemented directly; hybrid recall test proves dense misses exact-match token "26.5 ng/day" while hybrid finds it | `harness/retrieve.py`, `tests/test_retrieve.py`, `state.json` | Phase 3 | [plan](.claude/work/2026-05-10_02_implementation-plan/implementation-plan.md) |

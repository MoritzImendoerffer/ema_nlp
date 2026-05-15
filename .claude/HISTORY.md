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

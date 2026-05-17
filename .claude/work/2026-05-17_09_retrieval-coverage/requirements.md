# Requirements: Retrieval Coverage Fix

**Work unit:** `2026-05-17_09_retrieval-coverage`

---

## Functional requirements

### FR-1 · Chat UI must use the full corpus by default
The chat UI and harness must default to `corpus/corpus.jsonl` (26,251 records), not `mini_corpus.jsonl` (156 records). The mini_corpus was a development aid; it should not be the production default.

### FR-2 · Index must be rebuilt from full corpus
The FAISS index in `harness/index/` was built from mini_corpus and must be deleted and rebuilt from `corpus.jsonl` before the UI is useful.

### FR-3 · EMA_CORPUS_PATH must be documented
The env var already exists but is undocumented. Document it in `docs/SETUP.md` so users can override the corpus path without code changes.

### FR-4 · Missing corpus pages (P2, deferred)
~2,797 accordion HTML pages in MongoDB have not been extracted to the corpus. These should be added in a separate corpus re-build task (Phase 1 continuation).

---

## Acceptance criteria

| # | Criterion |
|---|-----------|
| AC-1 | `embed.py` `DEFAULT_CORPUS` points to `corpus/corpus.jsonl` |
| AC-2 | `app.py` `DEFAULT_CORPUS` points to `corpus/corpus.jsonl` |
| AC-3 | Running `python -m harness.embed` (no args) builds index from 26,251 records |
| AC-4 | `docs/SETUP.md` documents `EMA_CORPUS_PATH` env var |
| AC-5 | Existing tests pass (embed tests inject corpus path directly, not affected) |

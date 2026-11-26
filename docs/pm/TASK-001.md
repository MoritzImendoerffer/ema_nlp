---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-001
status: done
kind: contract
title: "Fix the stored shape: folder layout, file names, document id, options hash, config roots"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-001 — Fix the stored shape: folder layout, file names, document id, options hash, config roots

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

The module is pure Python and runs in .venv: no Docling import. Proposal section 'What is stored'. A 6-character hash, as doctool uses (ids.py:124-131), gave an expected 4% chance of a silent overwrite; 12 characters are used. Two PDFs with the same bytes share one folder. The parsed root is open question 1 of the proposal (the owner decides after batch 0); batch 0 writes plain JSON under the default root and reports the gzip size beside it.

## Acceptance criteria

- [x] `tests/test_docling_store.py::test_doc_id_is_slug_and_12_hex` passes: `doc_id_for(url, pdf_bytes)` gives `<last URL part, at most 40 characters>_<first 12 hex of sha256(bytes)>`, with `doc` as the fallback slug
- [x] `::test_options_hash_is_stable` passes: the same options dict in another key order gives the same 8-character hash; a changed option gives another
- [x] `::test_folder_path` passes: `<root>/<doc-id>/docling@<hash8>/` with `doc.raw.json`, `doc.json`, `run.json`
- [x] `config.PARSED_ROOT` defaults to `~/Nextcloud/Datasets/ema_nlp/parsed` (override `EMA_PARSED_ROOT`); `config.DOCLING_ENV` defaults to `~/.local/share/ema_nlp/envs/docling` (override `EMA_DOCLING_ENV`)
- [x] `make test` passes and `make lint` passes, each run on its own line

## What was built

corpus/parsers/docling_store.py (pure Python): slug_for, doc_id_for (<slug, at most 40>_<12 hex of sha256(bytes)>), options_hash (8 hex of canonical JSON), parse_folder (<root>/<doc-id>/docling@<hash8>/), parser_version (<docling version>+<hash8>), file names doc.raw.json, doc.json, run.json, failures.jsonl. config.PARSED_ROOT (default ~/Nextcloud/Datasets/ema_nlp/parsed, EMA_PARSED_ROOT) and config.DOCLING_ENV (default ~/.local/share/ema_nlp/envs/docling, EMA_DOCLING_ENV). 6 tests in tests/test_docling_store.py. Callers follow in TASK-009 and TASK-011. Gates: make test 792 passed, 2 skipped, 13 deselected; make lint All checks passed.

## Files it touched

- `corpus/parsers/docling_store.py`
- `config.py`
- `tests/test_docling_store.py`

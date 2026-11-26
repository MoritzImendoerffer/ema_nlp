---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-001
status: todo
kind: contract
title: "Fix the stored shape: folder layout, file names, document id, options hash, config roots"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-001 — Fix the stored shape: folder layout, file names, document id, options hash, config roots

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

The module is pure Python and runs in .venv: no Docling import. Proposal section 'What is stored'. A 6-character hash, as doctool uses (ids.py:124-131), gave an expected 4% chance of a silent overwrite; 12 characters are used. Two PDFs with the same bytes share one folder. The parsed root is open question 1 of the proposal (the owner decides after batch 0); batch 0 writes plain JSON under the default root and reports the gzip size beside it.

## Acceptance criteria

- [ ] `tests/test_docling_store.py::test_doc_id_is_slug_and_12_hex` passes: `doc_id_for(url, pdf_bytes)` gives `<last URL part, at most 40 characters>_<first 12 hex of sha256(bytes)>`, with `doc` as the fallback slug
- [ ] `::test_options_hash_is_stable` passes: the same options dict in another key order gives the same 8-character hash; a changed option gives another
- [ ] `::test_folder_path` passes: `<root>/<doc-id>/docling@<hash8>/` with `doc.raw.json`, `doc.json`, `run.json`
- [ ] `config.PARSED_ROOT` defaults to `~/Nextcloud/Datasets/ema_nlp/parsed` (override `EMA_PARSED_ROOT`); `config.DOCLING_ENV` defaults to `~/.local/share/ema_nlp/envs/docling` (override `EMA_DOCLING_ENV`)
- [ ] `make test` passes and `make lint` passes, each run on its own line

## Files it touched

- `corpus/parsers/docling_store.py`
- `config.py`
- `tests/test_docling_store.py`

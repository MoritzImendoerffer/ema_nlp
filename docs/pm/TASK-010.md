---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-010
status: done
kind: wiring
title: "Wire parse-pdfs to the byte parser and settle the pickle reader"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-010 — Wire parse-pdfs to the byte parser and settle the pickle reader

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

Blocked on decision G. The note recommends G1: the pickle path to parsed_documents is removed, `scripts/ingest_parsed_pdfs.py` keeps `--legacy` and its default mode delegates to the byte parser through `_cli` (it imports `_cli` at line 29).

The cache walker `_iter_pdf_cache` (pymupdf4llm.py:116-130) keeps its `.pdf` suffix test. The 805 `.pdf-N` URLs are row 11's: the plan's choice, since exploration 6.4 asked the plan to name the item. `scripts/ingest_parsed_pdfs.py:44-57` holds a copy of the walker.

The CLI reads `response_body` of each entry and writes nothing into the cache (the scraper wrote parsed_pdf.pkl there; exploration 6.1).

The docstring of scripts/update_graph.py is wrong at lines 18-20 (the cache holds parsed_pdf.pkl per PDF) and 29-31 (propagate 'not needed after a fresh build'); exploration 3.4 says why propagate stays required.

## Acceptance criteria

- [x] `tests/test_parsers_pymupdf4llm.py::test_cli_parses_response_body` passes: a temporary cache folder with `meta` {'url': 'https://www.ema.europa.eu/en/documents/x.pdf'} and `response_body` = the fixture PDF writes one row to mongomock with parser pymupdf4llm, the installed version and non-empty text
- [x] `tests/test_update_graph.py::test_dry_run_lists_parse_pdfs` passes: `update_graph.py --dry-run --pdf-cache X` prints `corpus.parsers.pymupdf4llm --cache X`
- [x] Decision G is applied as its note says (docs/pm/decisions/2026-11-25_pickle-reader.md)
- [x] `grep -n 'not needed' scripts/update_graph.py` prints nothing: the docstring no longer says that propagate is not needed after a fresh build
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-009]]

## What was built

Decision G1 applied. Call-site check before removal: grep for LegacyPickleReader, _load_pickle, parsed_pdf.pkl, corpus.parsers.pymupdf4llm and parsers_cli outside tests/ found two callers, scripts/update_graph.py (parse-pdfs step, via the CLI) and scripts/ingest_parsed_pdfs.py (default mode, via _cli); its --legacy mode has its own pickle loader and stays. Removed LegacyPickleReader, _load_pickle and the pickle import from corpus/parsers/pymupdf4llm.py; _cli parses each entry's response_body with PymuPdf4LlmParser, records cache_path in meta, takes an injectable client, and writes nothing into the cache. Docstrings of both scripts and update_graph's --pdf-cache help updated; update_graph no longer says propagate is not needed after a fresh build. Tests: 11 pickle tests removed; test_cli_parses_response_body, test_cli_dry_run_writes_nothing, tests/test_update_graph.py::test_dry_run_lists_parse_pdfs added. Entry point on real data (rule 6): _cli --limit 3 on ~/Nextcloud/Datasets/ema_scraper/cache/ema-sitemap into an in-memory mongomock: 3 written, 0 errors, 2,175/10,567/7,750 characters, 1.9 s per PDF. Gates: make test 775 passed, 2 skipped, 7 deselected (41 s at load average 14); make lint All checks passed.

## Files it touched

- `corpus/parsers/pymupdf4llm.py`
- `scripts/update_graph.py`
- `scripts/ingest_parsed_pdfs.py`
- `tests/test_parsers_pymupdf4llm.py`
- `tests/test_update_graph.py`

---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-002
status: todo
kind: mechanism
title: "Build the parse environment with pinned versions, outside .venv, and prefetch its models"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-002 — Build the parse environment with pinned versions, outside .venv, and prefetch its models

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

Exploration section 7: installing Docling into .venv would move torch 2.10.0 under the embedding model to 2.15.0. The trial environments of the exploration (~/.local/share/ema_nlp/envs/docling-a, docling-b) proved the install; `make parse-env` makes it reproducible. The English recognition model is not in the rapidocr wheel; RapidOCR fetches it from modelscope.cn on first use, so the script fetches it once and a batch never depends on a download.

## Acceptance criteria

- [ ] `make parse-env` builds a Python 3.12 environment at `config.DOCLING_ENV` from `requirements/parse-docling.txt` (docling 2.153.0, docling-core 2.108.0, docling-ibm-models 4.0.5, docling-parse 7.28.0, rapidocr 3.10.0, transformers 5.24.1, torch 2.15.0, onnxruntime 1.32.0, pypdfium2 5.15.2, pymongo, python-dotenv) and installs this repository into it with `--no-deps`
- [ ] The script downloads `en_PP-OCRv5_rec_mobile`, PaddleOCR-VL-1.6 at revision `c5630abae1d940eafe0697512a0325494b02ab42` and Heron at `8f39ad3c0b4c58e9c2d2c84a38465abf757272d8`, and prints each file's SHA-256
- [ ] After `make parse-env`, `.venv/bin/python -c 'import torch; print(torch.__version__)'` still prints 2.10.0 and `import docling` fails in .venv
- [ ] pyproject registers the marker `gpu`; `make test-parse` runs the tests marked `parse` in the parse environment; `make test` deselects them
- [ ] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-001]]

## Files it touched

- `scripts/setup_parse_env.sh`
- `requirements/parse-docling.txt`
- `Makefile`
- `pyproject.toml`

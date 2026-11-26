---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-007
status: todo
kind: mechanism
title: "Post-processing rule 3: turn the table model's markup into text"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-007 — Post-processing rule 3: turn the table model's markup into text

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

doctool's `paddleocr_vl.py:38-153` is the example. Dashes stay as Docling wrote them (proposal: no guess at the original character).

## Acceptance criteria

- [ ] `::test_latex_markup_becomes_text` passes for the cases seen on EMA tables: `\(\pm\)` gives ±, a literal `\n` gives a space, `2.06e^{-14}` gives 2.06e-14, `\(^{a}\)` gives a superscript mark
- [ ] Each conversion is counted in the counts that run.json and the batch report read
- [ ] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-005]]

## Files it touched

- `corpus/parsers/docling_post.py`
- `tests/test_docling_post.py`

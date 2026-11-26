---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-007
status: done
kind: mechanism
title: "Post-processing rule 3: turn the table model's markup into text"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-007 — Post-processing rule 3: turn the table model's markup into text

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

doctool's `paddleocr_vl.py:38-153` is the example. Dashes stay as Docling wrote them (proposal: no guess at the original character).

## Acceptance criteria

- [x] `::test_latex_markup_becomes_text` passes for the cases seen on EMA tables: `\(\pm\)` gives ±, a literal `\n` gives a space, `2.06e^{-14}` gives 2.06e-14, `\(^{a}\)` gives a superscript mark
- [x] Each conversion is counted in the counts that run.json and the batch report read
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-005]]

## What was built

Rule 3 in corpus/parsers/docling_post.py: convert_markup(text) unwraps \text{}/\mathrm{} and the math delimiters, writes ^{\circ} as °, e^{-14} as e-14 and 10^{9} as 10^9, writes subscripts as plain text (C_{max} -> Cmax, as the text layer has it), maps every Greek letter command (\alpha to \omega, the capitals, variants; 48+ entries) and the symbol commands (\pm ±, \le/\leq ≤, \ge/\geq ≥, \times ×, \neq ≠, \approx ≈, \rightarrow →, ...) to Unicode, drops the spaces between a command word and a following letter (\mu g -> μg), leaves an unknown command as written, and replaces a literal \n by a space only after the commands, so \nu stays ν and \neq stays ≠ (a bug found by the test). convert_table_markup() runs it on every table cell after rule 2; counted as markup_converted. Dashes untouched. 6 new tests (16 in tests/test_docling_post.py), including the whole Greek alphabet (the owner's requirement relayed by the lead, 2026-11-26). Gates: make test 811 passed, 3 skipped, 13 deselected; make lint All checks passed; make test-parse 8 passed.

## Files it touched

- `corpus/parsers/docling_post.py`
- `tests/test_docling_post.py`

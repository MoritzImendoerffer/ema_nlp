---
type: pm-task
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
task: TASK-015
status: todo
kind: measurement
title: "Run batch 0"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-015 — Run batch 0

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

Stop and report if a count differs from the note or the GPU misbehaves (planning workflow; the GSP crash memory). The batch can stop and resume: existing folders are skipped.

## Acceptance criteria

- [ ] The documents of docs/pm/decisions/2026-11-26_batch-0.md in its run order (70 random, then the ranked in rank order) parsed or listed as failed until the stop-file timer at 11 h 00 min, files only under `config.PARSED_ROOT`; no Mongo row and no graph change (the 270 were estimated at 26 h, so the batch is cut to fit the owner's 12 h; amended 2026-11-26)
- [ ] One test with two and with three worker processes on the same 20 documents (batch0/workers20.jsonl, the random documents with the fewest pages), timed, each in its own folder under $EMA_RESULTS_DIR/docling/batch0/ and with a stop-file timer at 20 min
- [ ] The GPU stays at the 250 W cap; the pauses run; no build runs at the same time

**Depends on:** [[TASK-014]]

## Files it touched

- not recorded

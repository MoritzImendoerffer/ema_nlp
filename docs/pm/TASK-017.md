---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-017
status: todo
kind: data
title: "Run one URL through parse-pdfs and build on the live stores"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-017 — Run one URL through parse-pdfs and build on the live stores

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

Writes one row to the live parsed_documents and changes one document in the live graph: blocked on docs/pm/decisions/2026-11-25_live-graph-runs.md.

Exploration 3.6: the proposal's command (`--steps parse-pdfs,build --limit 20`) parses the first 20 PDFs in os.walk order and builds the first 20 URLs in URL order, two unrelated sets. Use `corpus.parsers.pymupdf4llm --url <url>` and then a build whose comparison skips every other document.

This run gives the first recorded embedding rate of a replace in this repository (exploration section 8, 'Cost').

## Acceptance criteria

- [ ] The URL, the shape the owner chose in the decision note, and the counts before and after are written into docs/eval/ (the :Document count, the URL's :Chunk and leaf counts, the build's log line of new, replaced, stamped and skipped documents)
- [ ] The build embeds only that document's leaves; every other document is skipped
- [ ] The duration of the build's full comparison pass is recorded, with the embedding rate of the one document

**Depends on:** [[TASK-016]], [[TASK-010]]

## Files it touched

- not recorded

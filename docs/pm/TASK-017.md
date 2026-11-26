---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-017
status: done
kind: data
title: "Run one URL through parse-pdfs and build on the live stores"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-017 — Run one URL through parse-pdfs and build on the live stores

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

Writes one row to the live parsed_documents and changes one document in the live graph: blocked on docs/pm/decisions/2026-11-25_live-graph-runs.md.

Exploration 3.6: the proposal's command (`--steps parse-pdfs,build --limit 20`) parses the first 20 PDFs in os.walk order and builds the first 20 URLs in URL order, two unrelated sets. Use `corpus.parsers.pymupdf4llm --url <url>` and then a build whose comparison skips every other document.

This run gives the first recorded embedding rate of a replace in this repository (exploration section 8, 'Cost').

## Acceptance criteria

- [x] The URL, the shape the owner chose in the decision note, and the counts before and after are written into docs/eval/ (the :Document count, the URL's :Chunk and leaf counts, the build's log line of new, replaced, stamped and skipped documents)
- [x] The build embeds only that document's leaves; every other document is skipped
- [x] The duration of the build's full comparison pass is recorded, with the embedding rate of the one document

**Depends on:** [[TASK-016]], [[TASK-010]]

## What was built

Shape (b) on veoza-epar-procedural-steps-taken-scientific-information-after-authorisation_en.pdf. Parse --url: 1 row (pymupdf4llm, 1.27.2.3), 2,175 characters, 9.1 s; parsed_documents 80,083 -> 80,084. Build 1 with pymupdf4llm@1.27.2.3 first in the working tree: '0 new, 1 replaced, 0 stamped, 79881 skipped, 0 preference fallbacks', 11 min 55 s. File restored (git checkout; git diff --quiet passes; no commit holds the swap). Build 2: '1 replaced, 79881 skipped', 12 min 13 s. After build 2: same 9 chunk ids as before; chunks equal a rebuild from the legacy row; 6 of 9 texts had differed after build 1; 6 leaves embedded; documents 79,882, chunks 7,435,393, LINKS_TO 99,520, dashboard 1, unstamped 0 (all equal to before); only parsed_documents differs (+1 row, kept as planned). Costs: embed pass 219 s / 224 s (mostly the nulojix RMP summary, 12,454,382 characters, RecursionError on every build); LINKS_TO pass 8 min 4 s / 8 min 17 s (21,957 pages, 404,330 candidate pairs); embedding 6 leaves < 1 s. Recorded in docs/eval/2026-11-25_graph_delete_measurement.md, 'The live runs'; linked from docs/next/corpus_repair.md.

## Files it touched

- not recorded

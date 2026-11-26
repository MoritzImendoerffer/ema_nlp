---
type: pm-board
epic: 2026-11-26_28_pdf-parsing-docling
sprint: 2026-11-26_28_pdf-parsing-docling
generated: true
tags: [pm/board]
---

> [!warning] Generated from `.claude/work/2026-11-26_28_pdf-parsing-docling/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# Board — the active epic

**[[epic|2026-11-26_28_pdf-parsing-docling]]** · **7 of 18 done** · 11 todo

[[epic|Why this epic]] · [[_Archive|Finished epics]] · [[BACKLOG|What is open, in order]]

## Waiting on the project owner

**This is the only section that is yours.** Each is an argument a person has to settle.
None of them blocks the work below.

*None.*

## Not finished — the assistant's work, not the owner's

Nothing in this table needs the project owner. It is what the coding assistant has still to
do, and it is here so the state is visible, not so anyone else acts on it.

| Task | Status | Waiting on | Kind | What it is |
|---|---|---|---|---|
| [[TASK-007]] | `todo` | the assistant | mechanism | Post-processing rule 3: turn the table model's markup into text |
| [[TASK-008]] | `todo` | the assistant | mechanism | Post-processing rule 4: take title and reference number from the page header |
| [[TASK-009]] | `todo` | the assistant | mechanism | Write the writer: three files, a staged move, the failures list, the Markdown text and the Mongo row |
| [[TASK-010]] | `todo` | the assistant | mechanism | Write the ranking script: complex-table score and page count per PDF |
| [[TASK-011]] | `todo` | the assistant | wiring | Write the batch command and wire the parser, the post-processing and the writer into it |
| [[TASK-012]] | `todo` | the assistant | mechanism | Write the batch report: rates, failures, sizes, post-processing counts, table numbers, words held |
| [[TASK-013]] | `todo` | the assistant | documentation | Document the parser, the environment and the batch command |
| [[TASK-014]] | `todo` | the assistant | checkpoint | Checkpoint: write batch 0's decision note and measure the rate on 3 documents |
| [[TASK-015]] | `todo` | the assistant | measurement | Run batch 0 |
| [[TASK-016]] | `todo` | the assistant | measurement | Write batch 0's page in docs/eval |
| [[TASK-017]] | `todo` | the assistant | checkpoint | Checkpoint: report batch 0 to the owner |

## Done

| Task | Status | Waiting on | Kind | What it is |
|---|---|---|---|---|
| [[TASK-001]] | `done` | — | contract | Fix the stored shape: folder layout, file names, document id, options hash, config roots |
| [[TASK-002]] | `done` | — | mechanism | Build the parse environment with pinned versions, outside .venv, and prefetch its models |
| [[TASK-003]] | `done` | — | mechanism | Write the PaddleOCR-VL table stage and register it in code |
| [[TASK-018]] | `done` | — | measurement | Measure the OCR recognition models on pages with a known answer, and choose one |
| [[TASK-004]] | `done` | — | mechanism | Write the docling parser on the Parser protocol |
| [[TASK-005]] | `done` | — | mechanism | Post-processing rule 1: join a table that runs over pages |
| [[TASK-006]] | `done` | — | mechanism | Post-processing rule 2: footnote marks stay marks, footnote texts attach to their table |

---

## The same, as live queries

These need the Dataview plugin. **They query by tag, not by folder**, so they work wherever
the vault is rooted. A folder source such as `FROM "docs/pm"` only resolves when the vault is
opened at the repository root, which is the usual reason a table comes back empty.

Without the plugin these render as code blocks, and the tables above are the board.

```dataview
TABLE status, kind, title
FROM #pm/task
WHERE status != "done"
SORT status ASC
```

```dataview
TABLE waiting_on AS "waiting on"
FROM #pm/decision
WHERE status = "open"
```

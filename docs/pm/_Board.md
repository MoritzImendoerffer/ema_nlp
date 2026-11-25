---
type: pm-board
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
generated: true
tags: [pm/board]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# Board — the active epic

**[[epic|2026-11-23_27_pipeline-refresh]]** · **15 of 18 done** · 3 todo

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
| [[TASK-015]] | `todo` | the assistant | checkpoint | Checkpoint: report the code and the measurement, and ask for the two live runs |
| [[TASK-016]] | `todo` | the assistant | data | Backfill the parse identity on the live graph |
| [[TASK-017]] | `todo` | the assistant | data | Run one URL through parse-pdfs and build on the live stores |

## Done

| Task | Status | Waiting on | Kind | What it is |
|---|---|---|---|---|
| [[TASK-001]] | `done` | — | contract | Give parser_preference.yaml a reader that understands name@version |
| [[TASK-002]] | `done` | — | mechanism | Select one row per URL: the first matching preference entry, then the newest parsed_at |
| [[TASK-003]] | `done` | — | contract | Put parser, parser_version and text_sha256 on the :Document node |
| [[TASK-004]] | `done` | — | mechanism | Make the real build join document_metadata |
| [[TASK-005]] | `done` | — | mechanism | Name the graph's writes and deletes in one module, with an in-memory double that models deletion |
| [[TASK-006]] | `done` | — | mechanism | Resume by comparison: skip, stamp or replace each document |
| [[TASK-007]] | `done` | — | mechanism | Add prune: delete documents whose URL has no clean row, whatever the scope |
| [[TASK-008]] | `done` | — | mechanism | Make the reset delete corpus nodes in batches and keep every other node |
| [[TASK-009]] | `done` | — | mechanism | Add a PDF parser that reads bytes with the installed pymupdf4llm |
| [[TASK-010]] | `done` | — | wiring | Wire parse-pdfs to the byte parser and settle the pickle reader |
| [[TASK-011]] | `done` | — | wiring | Expose --prune on the build and the pipeline, and say what --reset deletes |
| [[TASK-012]] | `done` | — | mechanism | Write the backfill that stamps the parse identity on existing documents |
| [[TASK-013]] | `done` | — | measurement | Measure the deletes and the reset on a throwaway Neo4j |
| [[TASK-014]] | `done` | — | mechanism | Fix the delete and reset batch sizes from the measurement |
| [[TASK-018]] | `done` | — | documentation | Write down what each pipeline step can and cannot refresh |

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

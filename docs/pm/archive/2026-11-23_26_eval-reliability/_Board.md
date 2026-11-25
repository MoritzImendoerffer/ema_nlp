---
type: pm-board
epic: 2026-11-23_26_eval-reliability
sprint: 2026-11-23_26_eval-reliability
generated: true
tags: [pm/board]
---

> [!warning] Generated from `.claude/work/2026-11-23_26_eval-reliability/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# Board — the active epic

**[[epic|2026-11-23_26_eval-reliability]]** · **18 of 18 done**

[[epic|Why this epic]] · [[_Archive|Finished epics]] · [[BACKLOG|What is open, in order]]

## Waiting on the project owner

**This is the only section that is yours.** Each is an argument a person has to settle.
None of them blocks the work below.

*None.*

## Not finished — the assistant's work, not the owner's

Nothing in this table needs the project owner. It is what the coding assistant has still to
do, and it is here so the state is visible, not so anyone else acts on it.

*None.*

## Done

| Task | Status | Waiting on | Kind | What it is |
|---|---|---|---|---|
| [[TASK-001]] | `done` | — | documentation | Take the call that deletes the live graph out of three docs pages |
| [[TASK-002]] | `done` | — | mechanism | Add a prediction loop that runs every question on one event loop and records whether the agent finished |
| [[TASK-003]] | `done` | — | mechanism | Make the faithfulness and the correctness judge return an integer |
| [[TASK-004]] | `done` | — | mechanism | Add the pure functions for the judged rows, the counts and the printed summary |
| [[TASK-005]] | `done` | — | wiring | Switch the driver to the prediction loop: a failed item gets no judge call, and a run gets its tags when it opens |
| [[TASK-006]] | `done` | — | mechanism | Map each provider of models.yaml to the name, the key and the endpoint that an mlflow judge needs |
| [[TASK-007]] | `done` | — | wiring | Add `--judge` to scripts/run_eval.py and record the generator's and the judge's model id on every run |
| [[TASK-008]] | `done` | — | wiring | Stamp the resolved recipe on every evaluation run, and print which declared layers the runner does not run |
| [[TASK-009]] | `done` | — | contract | Bind the judge role to a new models.yaml entry for claude-opus-5-5, and stop sending temperature to that model |
| [[TASK-010]] | `done` | — | mechanism | Keep the matched leaf's text on a retrieved node when the retriever merges to the parent |
| [[TASK-011]] | `done` | — | mechanism | Render a search result as the matched leaf first, then its parent, up to a limit, and give the judge the same text |
| [[TASK-012]] | `done` | — | contract | Make the passage limit a key of the index profile, and stamp it on the trace |
| [[TASK-013]] | `done` | — | wiring | Pass the profile's passage limit from build_recipe to the two search tools |
| [[TASK-014]] | `done` | — | documentation | Say in the docs what the agent reads, how the two earlier result pages were made, and how to choose the judge |
| [[TASK-015]] | `done` | — | measurement | Run the runner once on the live graph and write down what the store shows |
| [[TASK-016]] | `done` | — | mechanism | Send the workspace header on every Anthropic request when ANTHROPIC_WORKSPACE_ID is set |
| [[TASK-017]] | `done` | — | mechanism | Build the anthropic SDK's response-model serializers before the first traced call |
| [[TASK-018]] | `done` | — | mechanism | Take each item's trace id from the adapter's own root span |

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

# Finished epics

One row per work unit that shipped under the planning workflow
([`../PLANNING_WORKFLOW.md`](../PLANNING_WORKFLOW.md)). `/ship` adds the row; the epic's notes
move to `archive/<epic>/` when the next epic starts.

| Epic | Shipped | What it produced |
|---|---|---|
| [Pipeline refresh](epic.md) (`2026-11-23_27_pipeline-refresh`, backlog row 10) | 2026-11-26 | A build that skips, stamps or replaces each document by its selected parse, a PDF parser that reads bytes, the metadata join in the real build, `--prune` and a batched reset, the parse identity on all 79,882 live documents, and one live replace and restore ([page](../eval/2026-11-25_graph_delete_measurement.md)) |
| [Eval reliability](archive/2026-11-23_26_eval-reliability/epic.md) (`2026-11-23_26_eval-reliability`, backlog row 9) | 2026-11-23 | A runner that counts failed runs and prints n beside every mean, the judge as a setting on every run, the passage the judge reads equal to the agent's, and a live check that passed ([page](../eval/2026-11-23_eval_runner_live_check.md)) |

The 27 work units from before 2026-11-23 are not listed here. Their folders are in
`.claude/work/`, and what they did is in `.claude/HISTORY.md`.

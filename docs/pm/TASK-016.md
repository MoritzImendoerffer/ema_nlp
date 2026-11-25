---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-016
status: todo
kind: data
title: "Backfill the parse identity on the live graph"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-016 — Backfill the parse identity on the live graph

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

Writes to the live Neo4j: blocked on docs/pm/decisions/2026-11-25_live-graph-runs.md.

Repeatable: yes, it stamps only documents without text_sha256. Way back: `MATCH (d:Document) CALL { WITH d REMOVE d.parser, d.parser_version, d.text_sha256 } IN TRANSACTIONS OF 10000 ROWS` restores the earlier state exactly, since no document had these properties (count 0, 0, 0 on 2026-11-23). Hours: from TASK-015's dry run. GPU: none. Paid calls: 0.

The NeoDash dashboard and every chunk, vector and edge stay as they are.

## Acceptance criteria

- [ ] Before: `MATCH (d:Document) WHERE d.text_sha256 IS NULL RETURN count(d)` = 79,882; `MATCH (c:Chunk) RETURN count(c)` = 7,435,393; `MATCH ()-[r:LINKS_TO]->() RETURN count(r)` = 99,520 (re-run the queries and write the results into the task before the run)
- [ ] After: the same three queries give 0, 7,435,393 and 99,520
- [ ] `scripts/backfill_parse_identity.py --verify 100` prints 'verify: 100 of 100 equal'
- [ ] A second run stamps 0 documents

**Depends on:** [[TASK-015]]

## Files it touched

- not recorded

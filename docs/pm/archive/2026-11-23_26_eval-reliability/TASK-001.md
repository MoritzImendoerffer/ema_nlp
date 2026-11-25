---
type: pm-task
epic: 2026-11-23_26_eval-reliability
sprint: 2026-11-23_26_eval-reliability
task: TASK-001
status: done
kind: documentation
title: "Take the call that deletes the live graph out of three docs pages"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_26_eval-reliability/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-001 — Take the call that deletes the live graph out of three docs pages

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

Why first: it is independent of every other task, and it removes a snippet that deletes the whole graph when pasted.

The defect. `docs/RETRIEVAL.md:228` shows `index = build_index(profile, reset=True)` under 'Programmatic build + retrieve'. `docs/ARCHITECTURE.md:210` shows `idx = build_index(p, reset=True)` under 'Build the index + verify retrieval'. `docs/RUNTIME_VERIFICATION.md:86` says 'only then rebuild with `harness.indexing.build_index(p, reset=True)`' in running text. `reset` runs `MATCH (n) DETACH DELETE n`. The default profile is the full corpus (`limit: null`, `harness/configs/index/neo4j_hier.yaml:20`). `docs/PLANNING_WORKFLOW.md` rule 7 gives the graph as 7.5 million nodes.

What to write. The two verify snippets open the existing graph: `open_index(profile)`, as `docs/RUNTIME_VERIFICATION.md:80-81` already does. The call with `reset=True` appears at most once per page, inside a block whose own text says that it deletes every node and edge of the live graph, that a rebuild re-embeds 5.82 million chunks, and that `CLAUDE.md` rule 4 asks for the owner's go-ahead first. Do not state rebuild hours unless a recorded run gives them.

Decided by the plan, not by the proposal: the third page. The proposal names two pages; `exploration.md` section 9 found `docs/RUNTIME_VERIFICATION.md:86`. Also decided by the plan: `docs/RETRIEVAL.md:193` shows the command-line form, `--full --reset --pause-every-docs 2000`, which deletes the same graph. Put the same warning in that block. Do not remove the flag from the table at `docs/RETRIEVAL.md:212`; it documents a real option.

`CLAUDE.md:240` names the call inside rule 4, as a warning. Leave it.

## Acceptance criteria

- [x] `grep -c 'open_index(profile)' docs/RETRIEVAL.md` prints at least 1, and the code block under the heading that is 'Programmatic build + retrieve' today calls no `build_index`
- [x] `grep -c 'open_index(p)' docs/ARCHITECTURE.md` prints at least 1, and the block that starts with `# Build the index + verify retrieval (Python)` today calls no `build_index`
- [x] For each of the three files, `grep -c 'reset=True' <file>` prints 0 or 1; where it prints 1, `grep -B8 -A8 'reset=True' <file> | grep -ci 'deletes'` prints at least 1
- [x] `grep -B6 -A6 -- '--full --reset' docs/RETRIEVAL.md | grep -ci 'deletes'` prints at least 1
- [x] `grep -rn 'reset=True' docs/ | grep -v 'docs/next/eval_reliability.md'` lists at most 5 lines: one per page above at most, plus `docs/PLANNING_WORKFLOW.md:71` and `docs/eval/2026-11-23_pkr_testbed_review.md:594`, which describe the defect and stay
- [x] `make test` passes and `make lint` passes, each run on its own line

## What was built

docs/RETRIEVAL.md: 'Programmatic build + retrieve' is now 'Programmatic retrieve' with open_index(profile); the reset call moved into its own block 'Programmatic rebuild from scratch — deletes the live graph', whose comments say it deletes every node and edge, re-embeds 5.82 million chunks, and needs the owner's go-ahead (CLAUDE.md rule 4); the update_graph '--full --reset' block got the same warning; the table row at :212 is unchanged. docs/ARCHITECTURE.md §9 verifies with open_index(p) and points to RETRIEVAL.md §6 for builds (0 reset calls). docs/RUNTIME_VERIFICATION.md:86 now says what the reset deletes. reset=True per page: 1 / 0 / 1, each with 'deletes' within 8 lines. Plan gap: the criterion 'grep -rn reset=True docs/ | grep -v eval_reliability.md' also counts 4 lines of the generated board note docs/pm/TASK-001.md, which quotes the plan; without docs/pm/ it lists 4 lines (<= 5). No hours stated. make test: 692 passed, 2 skipped, 7 deselected (exit 0). make lint: All checks passed (exit 0).

## Files it touched

- [[RETRIEVAL]] — `docs/RETRIEVAL.md`
- [[ARCHITECTURE]] — `docs/ARCHITECTURE.md`
- [[RUNTIME_VERIFICATION]] — `docs/RUNTIME_VERIFICATION.md`

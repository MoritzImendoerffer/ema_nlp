---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-018
status: todo
kind: documentation
title: "Write down what each pipeline step can and cannot refresh"
generated: true
waiting_on: the assistant
tags: [pm/task, pm/todo]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-018 — Write down what each pipeline step can and cannot refresh

**Epic:** [[epic]] · **Status:** `todo` · **Waiting on:** the assistant · **Board:** [[_Board]]

## Why it exists

Exploration 3.4 names three texts that state the wrong thing: the docstring of scripts/update_graph.py (lines 18-20, 29-31; fixed in TASK-010), docs/RETRIEVAL.md lines 220-223, and the docstring of scripts/propagate_metadata_to_graph.py (lines 7-9).

CLAUDE.md also has lines on parse-pdfs and the pipeline that become untrue (exploration section 7). They are left for /ship, with the owner present: CLAUDE.md is the project's instruction file.

/ship deletes backlog row 10 and the proposal, moves the settled decisions into DECISIONS.md, and appends to .claude/HISTORY.md.

## Acceptance criteria

- [ ] The node model of docs/RETRIEVAL.md lists parser, parser_version and text_sha256 on :Document
- [ ] `grep -n 'propagate.*unnecessary\|not needed after a fresh build' docs/RETRIEVAL.md scripts/update_graph.py scripts/propagate_metadata_to_graph.py` prints nothing
- [ ] docs/RETRIEVAL.md says that the comparison ignores chunk_sizes and the embedding model, and names the backfill script
- [ ] Every line of docs/RETRIEVAL.md that shows `--reset` has the word 'deletes' within 6 lines (rule 7)
- [ ] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-006]], [[TASK-007]], [[TASK-008]], [[TASK-010]], [[TASK-011]], [[TASK-012]]

## Files it touched

- [[RETRIEVAL]] — `docs/RETRIEVAL.md`
- `scripts/propagate_metadata_to_graph.py`
- `harness/indexing/build.py`

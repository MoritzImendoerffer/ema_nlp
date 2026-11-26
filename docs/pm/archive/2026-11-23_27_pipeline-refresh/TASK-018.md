---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-018
status: done
kind: documentation
title: "Write down what each pipeline step can and cannot refresh"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-018 — Write down what each pipeline step can and cannot refresh

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

Exploration 3.4 names three texts that state the wrong thing: the docstring of scripts/update_graph.py (lines 18-20, 29-31; fixed in TASK-010), docs/RETRIEVAL.md lines 220-223, and the docstring of scripts/propagate_metadata_to_graph.py (lines 7-9).

CLAUDE.md also has lines on parse-pdfs and the pipeline that become untrue (exploration section 7). They are left for /ship, with the owner present: CLAUDE.md is the project's instruction file.

/ship deletes backlog row 10 and the proposal, moves the settled decisions into DECISIONS.md, and appends to .claude/HISTORY.md.

## Acceptance criteria

- [x] The node model of docs/RETRIEVAL.md lists parser, parser_version and text_sha256 on :Document
- [x] `grep -n 'propagate.*unnecessary\|not needed after a fresh build' docs/RETRIEVAL.md scripts/update_graph.py scripts/propagate_metadata_to_graph.py` prints nothing
- [x] docs/RETRIEVAL.md says that the comparison ignores chunk_sizes and the embedding model, and names the backfill script
- [x] Every line of docs/RETRIEVAL.md that shows `--reset` has the word 'deletes' within 6 lines (rule 7)
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-006]], [[TASK-007]], [[TASK-008]], [[TASK-010]], [[TASK-011]], [[TASK-012]]

## What was built

docs/RETRIEVAL.md: the node model lists the parse identity (parser, parser_version, text_sha256) and names scripts/backfill_parse_identity.py; the data-flow diagram shows response_body per PDF; section 6 gives a refresh example without --reset beside a warned --reset example, a step table with --prune, a table of what each step can and cannot refresh (the build cannot clear a label and does not notice a change of chunk_sizes or the embedding model), and a subsection 'How the build refreshes a document'; the code map lists parser_preference.py and graph_ops.py; section 9 lists the new tests and the scratch-Neo4j integration tests. docs/RUNTIME_VERIFICATION.md: the reset sentence says what it deletes now. scripts/propagate_metadata_to_graph.py: the docstring no longer says new builds do not need it. Checks: the stale-claim grep prints nothing; every --reset / reset=True line of RETRIEVAL.md has 'deletes' within 6 lines (4 of 4). CLAUDE.md is left for /ship with the owner. Gates: make test 786 passed, 2 skipped, 13 deselected; make lint All checks passed.

## Files it touched

- [[RETRIEVAL]] — `docs/RETRIEVAL.md`
- `scripts/propagate_metadata_to_graph.py`
- `harness/indexing/build.py`

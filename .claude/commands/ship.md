---
description: Close a work unit: verify it is reachable, move the findings into docs, retire the proposal
---

Deliver finished work and retire its proposal. Last of four commands: `/explore` → `/plan` →
`/next` → `/ship`. See `docs/PLANNING_WORKFLOW.md`.

**Input**: `$ARGUMENTS`

| Argument | Effect |
|---|---|
| *(empty)* | run every check, report, and stop before changing anything |
| `--commit` | after the checks pass, apply the documentation moves and commit |

The default changes nothing. Delivery is the step that deletes a backlog row and a proposal, so
it asks first. There is no `--pr`: the assistant pushes only when the owner asks, and a push
from its environment does not work in every session (`BACKLOG.md`, the note on pushing).

## The check that matters most

**Is the work reachable?** This repository has paid for the question three times, all found by
the review of 2026-11-23 (`docs/eval/2026-11-23_pkr_testbed_review.md`):

- `ingest()` in `harness/indexing/ingest.py` joins the document labels and has tests, and only
  the tests call it. The real build calls `build_ingested_doc` without the join.
- `harness/configs/parser_preference.yaml` says in its own header that nothing reads it.
- The few-shot layer and the inline judge of a recipe run in `app.py` only. Under
  `scripts/run_eval.py`, three recipes behave as one.

So for every function, flag, tool, recipe key and config file this unit added, name the call
site and run the command that reaches it. `grep` for the symbol and check that at least one hit
is a real call in `harness/`, `corpus/`, `scripts/` or `app.py`, not a definition, a docstring
or a test. **A symbol whose only callers are tests is not delivered.** Report it as open rather
than shipping it as done.

**The eval path has the same test.** A recipe layer, a tool or a retrieval option that `app.py`
runs and `scripts/run_eval.py` does not is measured by nobody. Name the path that reaches it
from the runner, or say that it is a feature of the app only.

## Steps

1. **Load the unit** from `.claude/work/ACTIVE_WORK`. Every task must be `completed`. If any is
   not, list them and stop.

2. **Run the gates**, each on its own line.

   ```bash
   make test
   make lint
   ```

   Both green. Report the counts rather than asserting success.

3. **Run the reachability check above.** List each symbol, tool, recipe key and config file
   added, and the command that exercises it.

4. **Check the claims the work will make.** For each sentence about to be written into `docs/`
   or the README, verify it against the code, against a read-only query, or against the run
   that produced it. A number names its run. A statement about a library names its version.

5. **Check what must not be committed.** `git status` and the diff since the unit opened: no
   credential, no raw scraped data or other large artifact, no result file (they go to
   `config.RESULTS_DIR`), and nothing of the private plan beyond its class and ladder labels.

6. **Move the findings.** This is the delivery, and it is what makes the backlog honest:

   | If the work produced | It goes to |
   |---|---|
   | a command or a workflow a user runs | `README.md`, or the `docs/` page that owns the topic |
   | a stored shape or a design decision | `docs/ARCHITECTURE.md` or `docs/RETRIEVAL.md`, and one entry in `DECISIONS.md` |
   | a measurement or a checkpoint finding | the `docs/eval/` page the task wrote, linked from the `docs/` page it informs |
   | a rule somebody could get wrong twice | the short list in `docs/PLANNING_WORKFLOW.md` |

7. **Update `BACKLOG.md`.** Delete the item's row if it is finished. If the work is only partly
   done, rewrite the row to what remains and say precisely what that is. Change the phase table
   in `project_roadmap/ROADMAP.md` only when a phase's status changed. A deleted row over
   unreachable code is the failure this command exists to prevent.

8. **Delete the proposal.** `docs/next/<name>.md` is removed once its content has moved, and
   `docs/next/README.md` drops the row. `git` keeps the history, and a plan that no longer
   matches the code is worse than no plan. If some of the proposal is still open, do not delete
   it: rewrite it down to what remains and say so.

9. **Append one row to `.claude/HISTORY.md`** for the unit, and **commit**: an imperative subject
   naming what changed, then prose giving the reason and the evidence. State what was verified
   and how.

10. **Archive the work unit.** Set `status` to `delivered` in `metadata.json` and empty
    `.claude/work/ACTIVE_WORK`. An `ACTIVE_WORK` that still names a shipped unit is the defect
    that retired the file once, on 2026-07-20.

11. **Offer a memory entry**, if the work produced a durable preference or a lesson that the code
    and git history do not already record.

## Leave `docs/pm/` on the board, and settle what is open

**Do not delete or archive the epic here.** `docs/pm/` shows the epic being worked on, and a
shipped epic is the one a reader most wants to look at. It is archived when the **next** epic
starts, by `scripts/pm_notes.py`, which moves its task notes, board and epic note into
`docs/pm/archive/<epic>/`. Its decisions stay in `docs/pm/decisions/`, where other documents
link them.

What `/ship` does owe `docs/pm/`:

1. **regenerate it**, so the board matches the final `state.json` (`make pm`);
2. **settle every decision under `docs/pm/decisions/`.** A settled one records the answer and who
   gave it, sets `status: settled`, and gets one entry in `DECISIONS.md` that links the note.
   One still open moves to `OPEN_QUESTIONS.md` with a row in the backlog's question table,
   because an unresolved argument belongs where the open questions live, and it is then deleted
   from here;
3. **update `docs/pm/epic.md`** so its first paragraph says what shipped and what did not;
4. **add the epic's row to `docs/pm/_Archive.md`** with a link to what it produced.

## What this command does not do

It does not push or merge unless asked. When asked to merge, it merges the unit's
branch into `develop`, never into `main`: `main` moves only when the owner asks
(`docs/PLANNING_WORKFLOW.md`, "Branches"). It also does not report success it did not verify: if
a gate fails, a symbol has no caller, or a run has failed rows, say so plainly and leave the
unit open.

---
description: Turn an explored proposal into an ordered task list another session can implement
---

Break one backlog item into tasks, and write them where a different session can pick them up.
Second of four commands: `/explore` → `/plan` → `/next` → `/ship`. See
`docs/PLANNING_WORKFLOW.md`.

**Input**: `$ARGUMENTS` may name a work unit id. When empty, use `.claude/work/ACTIVE_WORK`.

If there is no active work unit, say so and recommend `/explore <proposal>`. Do not invent
requirements from the conversation. The proposal is the requirements, and if no proposal was
explored there is nothing to plan against.

## The rule that shapes this command

**The plan is written for a session that was not here.** Everything a later session needs must
be in `state.json` and `implementation-plan.md`. A task that only makes sense to someone who
read this conversation is a task that will be implemented wrongly.

So each task states its acceptance criterion as something a command can check, not as an
intention. "`tests/test_indexing_ingest.py::test_newest_parser_row_wins` exists and passes" can be
checked. "Make ingestion robust" cannot.

**Every major claim carries a concrete example**, taken from this repository, from the installed
library, from a store or from a run, rather than invented. A reader who was not in the session
cannot check a claim stated in the abstract, and cannot tell a verified finding from a guess.

- Not "the agent sees truncated passages". Instead: "`harness/tools/search.py:116` cuts each
  passage to `_SNIPPET_MAX = 400` characters before the agent reads it."
- Not "an old parse wins". Instead: "`iter_source_rows` (`harness/indexing/ingest.py:178`)
  sorts by `url` and keeps the first error-free row per URL."

An example is also how a wrong claim gets caught. A claim with no example survives review
because there is nothing to check it against.

## Steps

1. **Load the unit.** Read `metadata.json`, the proposal it names, and `exploration.md`. If
   `exploration.md` says the proposal no longer stands, stop and report that instead of planning
   around it.

2. **Break the work into tasks.** One responsibility each, small enough to finish and verify in
   one sitting. Order them so that each task leaves the repository green: `make test` and
   `make lint` pass at every boundary, not only at the end. Follow the proposal's phases and
   keep its checkpoints as tasks of their own.

3. **Give every task an acceptance criterion a command can check.** Prefer:
   - a test name that must exist and pass,
   - a command whose output must contain something specific,
   - a read-only query whose result must be a stated number,
   - a metric that is reported with its denominator and its count of failed rows.

4. **Add the tasks that are easy to leave out.**
   - **A caller.** A function with tests and no caller closes nothing. If the plan adds a
     function, a tool, a recipe key or a config file, one task wires it into an entry point
     (a script, the tool registry, a recipe, `app.py`) and names the command that exercises it.
   - **The approval before a run that deletes or costs.** A task of type `data` that deletes,
     or runs longer than one hour on the GPU, and a task of type `measurement` with paid model
     calls, each depend on a decision note under `docs/pm/decisions/` that states the counts,
     the hours and the cost.
   - **The checkpoint report.** Where the proposal says to stop and report (⏸), a task writes
     the findings to `docs/eval/YYYY-MM-DD_<topic>.md`, and the next task depends on the owner's
     answer through a decision note.
   - **The documentation move.** When the work lands, the description goes to the relevant
     `docs/` page or the README, the backlog row is deleted and the proposal is deleted or cut
     down to what remains. `/ship` does this, and the plan must leave room for it.

5. **Write `state.json`** into the work unit:

   ```json
   {
     "status": "planning_complete",
     "proposal": "docs/next/<name>.md",
     "current_task": null,
     "tasks": [
       {
         "id": "TASK-001",
         "title": "one line, imperative",
         "type": "mechanism",
         "status": "pending",
         "dependencies": [],
         "files": ["harness/..."],
         "acceptance": ["make test passes", "..."],
         "notes": "anything a session that was not here would get wrong"
       }
     ]
   }
   ```

   `type` is one of the seven in the sizing table below. `scripts/pm_notes.py` prints it on the
   board, so a task without one shows a blank column. The key is `acceptance`; the work units
   from before 2026-11-23 used `acceptance_criteria`, which the script does not read.

6. **Write `implementation-plan.md`** beside it, for a person: what is being built, the order and
   why that order, what could go wrong, and what will not be attempted.

7. **Regenerate the board** so the plan is visible outside this session, and write
   `docs/pm/epic.md` if it does not exist yet (why this epic, in a person's words):

   ```bash
   make pm
   ```

8. **Report** the task count, the critical path, and anything the proposal left undecided that
   the plan had to decide. Say which decisions were yours, so they can be overruled.

## Sizing

| Type | What it covers |
|---|---|
| contract | a stored shape: the fields of a Mongo collection, the properties of a node or an edge, the benchmark record, a recipe or profile key. Say what happens to rows and nodes already written |
| mechanism | the function or module that does the work |
| wiring | the script, the registry entry or the recipe that calls it. Never fold this into the mechanism task |
| data | a run that changes a store: a re-parse, a backfill, a rebuild. See below |
| measurement | a run that produces a number, and its `docs/eval/` page. See below |
| checkpoint | a stop to report to the owner, with the finding written to `docs/eval/` |
| documentation | the README or `docs/` page, the backlog row, and deleting the proposal |

## Planning a data task

A data task changes what every later number is computed on, so the plan fixes these before the
run:

- **the counts before**, from a read-only query written into the task, and the counts expected
  after;
- **whether the run can be repeated**: a second run changes nothing, or the task says what it
  changes;
- **the way back**: which command restores the earlier state, or the sentence "there is none";
- **the hours**, measured on a sample of at least 100 documents and scaled, not guessed.

## Planning a measurement task

A measurement here compares arms, so the plan fixes these before the run, not after:

- **the items**: the benchmark file, its commit, and which item ids;
- **the arms, and the one thing that differs between them**: a recipe, a tool or an index
  profile. Two differences in one comparison measure neither;
- **the models**: the exact id of the generator and of the judge. The judge is a setting
  (`roles.judge` in `harness/configs/models.yaml`); it is not the generator's model, and it
  is the same for every arm;
- **the metric, its denominator and the repeats**: "must-have facts covered, out of 34, three
  repeats", with the failed rows left out of the mean and their number printed beside it;
- **what would falsify the claim** that the run is made to support;
- **the cost**, as calls and a rough amount.

## What this command does not do

It writes no implementation code. It also does not reorder the backlog: if the work turns out
larger than its row assumed, say so and let the owner reprioritise.

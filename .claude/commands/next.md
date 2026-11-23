---
description: Implement the next task from a stored plan, in this project's environment and gates
---

Execute pending tasks from the active work unit. Third of four commands: `/explore` → `/plan` →
`/next` → `/ship`. See `docs/PLANNING_WORKFLOW.md`.

**Input**: `$ARGUMENTS`

| Argument | Effect |
|---|---|
| *(empty)* | run the next task whose dependencies are met |
| `--status` | print completed, pending and blocked tasks, then stop |
| `--preview` | print what the next task would change, then stop |
| `--task TASK-003` | run one named task |

## Start here, not from the conversation

Read `.claude/work/ACTIVE_WORK`, then `state.json`, then the proposal it names, then
`exploration.md`. **This is the whole input.** A session picking work up later was not present
for the planning, and behaving as though it was is how a plan gets implemented wrongly.

- No unit in `ACTIVE_WORK` → say so and recommend `/explore <proposal>`.
- No `state.json` → recommend `/plan`.
- `status` is not `planning_complete` or `implementing` → report the status and stop.

## The environment

Use `.venv` and nothing else: `python3` on the maintainer's machine is conda's Python 3.9. The
credentials are in `~/Nextcloud/Datasets/ema_nlp/ema_nlp.env`, which `config.py` loads. Never
print that file, and never copy a value from it into a file of the repository.

The gates are:

```bash
make test      # pytest without the tests marked integration; no store, no model call
make lint      # ruff check .
```

A task that reads or writes a store needs MongoDB at `MONGO_URI` (default
`localhost:27017`) and Neo4j at `NEO4J_URI`, both from the credentials file. Check that both
answer before the task starts, and say what you found. `make
test-live` runs the 7 tests that read the live MongoDB; run it for a task that touches
`corpus/sources/`.

## Steps

1. **Pick the task.** The first pending one whose dependencies are all completed, or the one
   named by `--task`. If every pending task is blocked, print what blocks each and stop.

2. **Implement it.** Write code that reads like the code around it. Follow the rules in
   `CLAUDE.md`: nothing the proposal does not ask for, third-party APIs checked against the
   installed version, source, derived and authored data apart.

3. **If the task adds a function, wire it.** A function with tests and no caller closes nothing.
   The same holds for a tool, a recipe key and a config file. Before marking the task done, name
   the command that reaches it and run that command.

4. **If the task changes a stored shape** (a Mongo collection, a node or edge property, the
   benchmark record, a recipe key), say what happens to what an earlier version wrote: derived
   again by which command, or left as it is and read how.

5. **Write the test with the defect in it.** When the task exists because something was wrong,
   the test states the defect, not only the happy path. A docstring records what a future reader
   cannot reconstruct: the failure that made the code necessary.

6. **Check the acceptance criteria literally.** Run what they name. Do not substitute a judgement
   that it looks right.

7. **Run both gates**, each on its own line with its exit status kept. A gate piped into `tail`
   reports `tail`'s status. Both must pass before the task is marked done. If one fails, say so
   with the output rather than describing it.

8. **Update `state.json`**: the task's `status` becomes `completed`, an `outcome` line says what
   was built, `current_task` moves on, and the unit's `status` becomes `implementing`. **Then
   regenerate the visible board:**

   ```bash
   make pm
   ```

   `docs/pm/` is the only place the owner can see task state; `state.json` is invisible to
   them. The script also archives the previous epic when `ACTIVE_WORK` has moved.

9. **If the outside view changed, update it.** Not on every task. Only when one of these happens:

   - **A task became blocked**, or reached a checkpoint. Write the question under
     `docs/pm/decisions/` with `status: open`, `waiting_on: the owner` and `blocks: TASK-00N`,
     and say so in the Notes cell of the item's row in `BACKLOG.md`.
   - **The last task of a phase completed**, so a capability now exists that did not.
   - **A claim in `docs/next/`, `BACKLOG.md` or a `docs/` page became false.** Building the thing
     usually falsifies the sentence that argued for it.

10. **Append one row to `.claude/HISTORY.md`** for the task, and **commit if the owner has asked
    for commits**: one commit per task, with the HISTORY row in it. An imperative subject naming
    what changed, then prose explaining why and the evidence. Include the task id.

11. **Report** what changed, what the gates said, and what the next available task is.

## Data tasks

A task of type `data` changes a store that every later number is computed on.

- **Count before and after** with the read-only queries the task names, and write both into the
  task's `outcome`.
- **Run it on a sample first**: at least 100 documents, with the time measured.
- **Stop before a run that deletes, or that takes longer than one hour on the GPU**, unless its
  decision note is settled with a yes. `build_index(profile, reset=True)` and `--reset` delete
  the whole graph in one transaction.
- **Never write to `web_items` or the Scrapy cache.** They are the source.

## Measurement tasks

A task of type `measurement` produces a number that somebody will quote.

- **Run what the plan fixed**: the items, the arms, the models, the repeats. A change of any of
  them is a change of the plan, not of the run.
- **MLflow is the record.** The `docs/eval/` page names the run ids, the benchmark file's commit,
  both model ids, n, and the count of failed rows. A row whose agent run failed is listed by
  its id and left out of the mean; it is never judged as an answer. When the generator and
  the judge are of one model family, the page says so.
- **Stop before a run with paid model calls beyond a smoke run of 3 items**, unless its decision
  note is settled with a yes.
- **Report a number with its denominator**, and say what the run did not measure.

## Checkpoint tasks

A task of type `checkpoint` stops the line on purpose:

- **Write the findings to `docs/eval/YYYY-MM-DD_<topic>.md`**: what was checked, on which
  library versions, with file and line references, queries or command output.
- **Open a decision note** for each question the owner has to answer.
- **Stop.** Do not start a task that depends on the checkpoint until the owner has answered.

## What this command does not do

It does not deliver. Moving findings into `docs/`, deleting the backlog row and deleting the
proposal is `/ship`. Step 9 is the narrow exception and it is not delivery: it keeps the status
lines true while the work is in flight.

It does not silently widen the plan. If a task cannot be done as written, stop, say why, and let
the plan be corrected.

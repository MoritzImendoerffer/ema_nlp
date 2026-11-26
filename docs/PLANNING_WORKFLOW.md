# The planning workflow: from a backlog row to delivered work

Four commands carry one item from `docs/next/` to done, across as many sessions as it takes.
They live in `.claude/commands/`. They were adapted on 2026-11-23 from the maintainer's
`doctool` repository; what changed is listed at the bottom of this page.

```
BACKLOG.md               the owner picks the item, in the order the backlog gives
   │
   ▼
/explore <proposal>      opens a work unit, reads the code, the libraries and the stores,
   │                     checks the proposal
   ▼
/plan                    writes state.json and implementation-plan.md
   │
   ▼
/next                    implements one task, runs the gates, updates state.json
   │  (repeat; a checkpoint task stops the line until the owner answers)
   ▼
/ship                    verifies reachability, moves findings into docs/, retires the proposal
```

This page is not [`WORKFLOWS.md`](WORKFLOWS.md). That page is kept history of a deleted
answering engine.

## Why it is built this way

**A session ends and the work does not.** These commands write the state down, so a second
session picks up from files rather than from a conversation it never saw.

**The proposal is the requirements, and there is only one copy.** `/explore` records the *path*
to `docs/next/<name>.md` and never copies its content. Two descriptions of one task drift, and
the drift is invisible until somebody builds the wrong one.

**The backlog stays the only queue.** `BACKLOG.md` says what is open and in what order.
Everything below is the detail of one row: a proposal, a work unit, a board. None of them
orders anything.

## The rules that got somebody twice

The list `/ship` adds to. Each one is here because it was paid for, in this repository or in
the ones this workflow came from, or because it was found one step before it would have been.
Where no source is named, the evidence is in
[`eval/2026-11-23_pkr_testbed_review.md`](eval/2026-11-23_pkr_testbed_review.md).

1. **A function with tests and no caller is not done.** `ingest()` in
   `harness/indexing/ingest.py` joins the document labels, has tests, and is called by tests
   only; the real build calls `build_ingested_doc` without the join, so a fresh build loses
   the labels. `harness/configs/parser_preference.yaml` is read by nothing. `/ship` checks for
   a call site outside the tests.
2. **What the app runs and the runner does not is measured by nobody.** The few-shot layer and
   the inline judge of a recipe run in `app.py` only. Under `scripts/run_eval.py` the recipes
   `regulatory_fewshot` and `agentic_judged` behave exactly like `regulatory_agent`.
3. **A run that failed is not an answer.** Five evaluation runs ended with `RuntimeError: Event
   loop is closed` and were judged all the same; at least two of them received correctness 5.
   The mean left out 7 of 85 faithfulness values that were not numbers and printed no n. A
   measurement prints n, the failed rows and the dropped values. A failed row gets no judge
   call; it is listed by its id and left out of the mean (`DECISIONS.md`, 2026-11-23).
4. **Measure the path that runs.** The first seeding probe measured retrieval for the raw
   question. The agent rewrites the question before it searches, and its rewrite already put
   the anchor at vector rank 1 ([`eval/2026-07-20_tree_seeding.md`](eval/2026-07-20_tree_seeding.md),
   section 6). Four backlog rows had been planned on the first number.
5. **A statement that something exists, or does not, is checked against the store.** The
   instructions said that `ema_scraper.link_graph` was never built; the collection holds
   22,743 documents. A count is a query's result, written beside the query.
6. **A step of a pipeline is done when the entry point ran on real data.** The `parse-pdfs`
   step of `scripts/update_graph.py` fails on every PDF with `pickle_load_failed: No module
   named 'parsers'`, because only another script adds the scraper's repository to the path. No
   test loads a real object of the scraper.
7. **A snippet in the docs gets run.** `docs/RETRIEVAL.md` and `docs/ARCHITECTURE.md` show
   `build_index(profile, reset=True)` as the way to build and verify. Run as written, it
   deletes the live graph of 7.5 million nodes. A command that deletes appears in the docs with its warning in the same
   block, or not at all.
8. **A pointer that nothing clears goes stale.** `.claude/work/ACTIVE_WORK` still named a unit
   of 2026-06-04 six weeks later, and was retired on 2026-07-20. Since 2026-11-23 `/explore`
   writes it and `/ship` empties it, and a session compares it with `Now` of the backlog
   before it plans anything.
9. **A gate piped into `tail` reports `tail`'s exit status.** `make lint 2>&1 | tail -1 && mark`
   marked a task done with lint red, in the repository this workflow started in (2026-09-23).
   Run each gate on its own line, keep its status, and chain on that.
10. **A fake-object test proves the call shape you wrote, not the one the library accepts.**
    Check a third-party API against the installed version, and run one real call before
    building on it.
11. **An answer that an assistant gives in the owner's place is labelled as the assistant's.**
    This holds for a gold answer, a citation verdict, a rating and a review of benchmark items.
    A replay of the owner's earlier answers is never counted as the owner's check (`doctool`,
    2026-10-16 and 2026-10-19).
12. **Whether the assistant reaches GitHub depends on the session.** On 2026-07-20 `git push`
    and `git fetch` failed from its environment; on 2026-11-23 a push worked (`BACKLOG.md`, the
    note on pushing). Before it says what GitHub holds, it runs `git fetch`; when that fails, it
    says the remote state is unknown. A check on another machine waits until the commit is
    pushed, and the decision note that asks for it names the commit that `git log -1` must show
    there.
13. **The first call of a process can fail where every later call passes.** In the live check
    of 2026-11-23 only the first item lost its trace: the anthropic SDK builds a response
    class's serializer lazily, and the first `claude-opus-4-7` response was traced before
    anything had built it. Haiku's responses did not show it. A test of such a defect runs in
    a fresh interpreter, because inside the test process another test has already done the
    first call.
14. **A temporary edit of an authored file is undone by the next command, not later.** The
    live replace of work unit 27 swapped the PDF order of `parser_preference.yaml` for one
    build. The build finished at 17:37 on 2026-11-25; the session then waited, and the file was
    restored at about 07:20 the next morning. For those 14 hours the shared working tree held
    the swapped file, and `make test` failed 4 tests in another session. Chain the restore to
    the run (`run; git checkout -- <file>`), and check `git diff --quiet -- <file>` before
    anything else.

## `docs/pm/` — the sprint you can see

`state.json` is the machine's task list and nobody outside the session can read it. [`docs/pm/`](pm/)
is `state.json` rendered as Obsidian notes with YAML front matter: one note per task, a board, and
one note per decision waiting on the owner. Regenerate with `make pm`. The script reads and
writes UTF-8 with `\n` line ends on every system.

**Generated and hand-written notes are separate files, never two halves of one.** The board and
the task notes carry `generated: true`; the epic note, the decisions, the README and the archive
are written by a person or an agent, and the script never changes their words.

**It holds one epic, and the previous one is archived rather than deleted.** When
`.claude/work/ACTIVE_WORK` names a different unit, `scripts/pm_notes.py` moves the old one's
task notes, board and epic note into `docs/pm/archive/<epic>/`, and rewrites their links so that
they point at the same files from there. Archiving happens when a new epic starts, not when one
ships: a shipped epic is the one a reader most wants to look at. **Decisions stay in
`docs/pm/decisions/`**, since `DECISIONS.md`, the backlog and the `docs/eval/` pages link them
as the reason for what was built; the board lists only the open ones.

The structure is CCPM's (<https://aroussi.com/post/ccpm-claude-code-project-management>) with
GitHub swapped for the repository.

## Who owns what

| Question | Answer lives in | Survives the work |
|---|---|---|
| What should we build, and why? | `docs/next/<name>.md` | no, it is deleted on delivery |
| In what order? | `BACKLOG.md` | yes |
| Which phase is the project in? | `project_roadmap/ROADMAP.md` | yes |
| What does the code look like today? | `.claude/work/<id>/exploration.md` | no |
| Which tasks, in what order? | `.claude/work/<id>/state.json` | no |
| What is waiting on the owner, for the unit in progress? | `docs/pm/decisions/` | settled by `/ship`, with an entry in `DECISIONS.md` |
| What is undecided and tied to no unit? | `OPEN_QUESTIONS.md`, listed in the backlog | until decided |
| What was decided, and why? | `DECISIONS.md` | yes |
| What did a run or a checkpoint find? | `docs/eval/` | yes |
| What was done, by date? | `.claude/HISTORY.md` | yes |
| How do I use it? | `README.md` and `docs/` | yes |

`docs/next/` and `.claude/work/` do different jobs and must not duplicate. `docs/next/` is
reviewed, committed and permanent until the work lands. A work unit is scratch space for one
implementation attempt, and it is disposable the moment `/ship` has moved the findings out.

## The work unit

```
.claude/work/
├── ACTIVE_WORK                         # the id of the unit in progress; empty when none is
└── 2026-11-24_26_eval-reliability/     # an example of the name; no unit is open yet
    ├── metadata.json                   # proposal path, backlog row, status
    ├── exploration.md                  # what the code, the libraries and the stores look like now
    ├── state.json                      # the task list and its progress
    └── implementation-plan.md          # the same plan, for a person
```

The 27 folders from before 2026-11-23 are history. Their `state.json` has another layout, and
`scripts/pm_notes.py` is not run on them.

## Branches

| Name | Holds | Who changes it |
|---|---|---|
| `main` | what GitHub shows first. It equals `develop` on 2026-11-23 (`b8f7216`) | the owner, who asks for `develop` to be merged into it |
| `develop` | every shipped work unit | `/ship`, which merges a proposal's branch when the owner asks |
| one branch per proposal, such as `eval-reliability` | the work unit in progress, made from `develop` | `/explore`, which makes it; `/next`, one commit per task |

1. **All work goes to `develop`, through one branch per proposal.** `/explore` makes the branch
   from `develop` when the work unit opens, and names it by the unit's slug: `git switch -c
   eval-reliability develop`. `/ship` merges it into `develop` by a fast-forward when `develop`
   is its ancestor (`git merge --ff-only`), else by a merge commit, and deletes the branch.
2. **`main` moves only when the owner asks, and only to a commit of `develop`.**
3. **The assistant commits only when asked, and pushes only when asked.** When asked, it tries
   the push once and reports the result. The owner can always push from their own shell.

## The gates

```bash
make test      # .venv/bin/python -m pytest -m "not integration"
make lint      # .venv/bin/python -m ruff check .
```

Both must pass before a task is done. A gate that did not run is reported as "not run", never
"passed". On 2026-11-23: 692 passed and 2 skipped in 14 seconds, and no lint finding.

Two checks are not gates:

- `make test-live` runs the 7 tests marked `integration`. They read a populated MongoDB, so
  their answer depends on the machine. Run it for a task that touches `corpus/sources/`.
- `mypy .` reports 54 errors in 27 files on 2026-11-23. A gate that is red before the work
  starts says nothing about the work.

## What changed when this workflow was adapted, and why

Kept unchanged from `doctool`: the four-command shape, the work-unit layout, "the proposal is
the requirements", the reachability check, `scripts/pm_notes.py` with its test, the decision
notes, one branch per proposal from `develop`, and the rule that every major claim carries a
concrete example.

| Change | Why |
|---|---|
| `BACKLOG.md` owns the order; there is no `docs/ROADMAP.md` | The backlog has been the single ranked queue here since 2026-07-20, with `Now` capped at 3. `project_roadmap/ROADMAP.md` keeps the phases |
| This page is `PLANNING_WORKFLOW.md`, not `WORKFLOW.md` | `docs/WORKFLOWS.md` exists and describes a deleted engine; one letter apart is a trap |
| Findings go to `docs/eval/`, not `docs/results/` | It is this repository's folder for dated findings. Result files go to `config.RESULTS_DIR`, and MLflow is the record of every metric |
| Task types `data` and `measurement` replace `skill` | This repository changes stores and reports numbers, and ships no skills. `measurement` and its planning rules come from the workflow's first home, where runs compare arms |
| `/explore` step 6 checks source, derived and authored data, the live graph, comparable numbers, cost, scope and the public repository | These are what a change here can damage: a graph of 5.8 million vectors that takes hours to rebuild, numbers that later runs are compared with, and a plan that is private |
| `/next` stops before a run that deletes, takes longer than one hour on the GPU, or pays for model calls beyond 3 items | One GPU, one graph, and a bill |
| `make test` leaves out the tests marked `integration` | The gate has to give the same answer on every machine |
| ruff leaves out `idmp_dabbling.py`, `scripts/phase0_*.py` and notebooks | They held 27 of the 31 findings on 2026-11-23 and are not code that runs |
| A settled decision also gets an entry in `DECISIONS.md`; an open one that outlives its unit moves to `OPEN_QUESTIONS.md` | Both files exist and are linked from the backlog |
| `/next` and `/ship` append to `.claude/HISTORY.md` | The rule of this repository since its start |
| `.claude/work/ACTIVE_WORK` is in use again | The board script reads it. Rule 8 above says what keeps it true |
| No `--pr`, no prompt files for a second assistant, no `AGENTS.md` | The assistant pushes only when asked and cannot count on reaching GitHub from every session, and only Claude Code works in this repository, so `CLAUDE.md` holds the rules |

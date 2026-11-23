---
type: pm-task
epic: 2026-11-23_26_eval-reliability
sprint: 2026-11-23_26_eval-reliability
task: TASK-015
status: done
kind: measurement
title: "Run the runner once on the live graph and write down what the store shows"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_26_eval-reliability/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-015 — Run the runner once on the live graph and write down what the store shows

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

Why this run exists. The runner's tests are offline, and a stand-in proves only the call shape that the test's author wrote (`docs/PLANNING_WORKFLOW.md`, rule 10). Two points have no proof yet (`exploration.md` section 5.1): that a trace made by `mlflow.llama_index.autolog()` inside the runner's loop is the one the judge values land on, and that the trace is written before the runner reads it. It is also the first run of the new passage text, of the new judge and of `--experiment` with the run tags, on real data (rule 6: a step is done when the entry point ran on real data).

This is the only paid run of the work unit, apart from the one short completion of TASK-009.

The plan of the run, fixed before it.
- Items: `benchmark/benchmark.jsonl` at commit `ad4b214`, the first item of each question type that runs: `T1-001`, `T2-001`, `T3-001`, and `T4-001` if the owner chose 4 questions. No repeat.
- Arms: one. This run compares nothing. It checks the runner.
- Models: generator `claude-opus-4-7` (the recipe `naive_rag` names `claude_opus`); judge `claude-opus-5-5` (`roles.judge` after TASK-009). Both are Claude models.
- Metric: none is reported as a result. The page lists the values per item with n = 1 per type.
- What would show the work is not done: a line with `Event loop is closed`; judge values on a trace with the single span `root_span`; a trace without `ema.bench_id`; a run without one of the two model tags; a passage the judge received that the agent did not read.
- Cost and time: in the decision note, with the arithmetic. About 14 generator calls and 6 judge calls for 3 questions; about 19 and 8 for 4.

Plan decision, not in the proposal: the run goes to its own experiment, `eval_reliability_smoke`, through the existing option `--experiment` (`scripts/run_eval.py:24`). The experiment `ema_nlp` then keeps only runs that count. Without the option the run lands in `ema_nlp`, since `EMA_MLFLOW_EXPERIMENT` is unset on this machine.

Before the run. Neo4j and the GPU must answer: `scripts/start_services.sh`, then one retrieval. The run embeds about 15 queries on the GPU and writes nothing to the graph. Open `mlflow.db` read-only for every check: `sqlite3.connect('file:mlflow.db?mode=ro', uri=True)`.

The store. The run appends to `mlflow.db`: one experiment, one run per question type, and at least one trace per item. Whether a judge call writes a trace of its own is not known; count the traces of the new experiment and write the number down. The run cannot be undone by a command of this repository. A second run adds a second set of runs and changes none of the first.

If a criterion fails. Do not patch around it inside this task. Write what the store shows to the page, open a decision note under `docs/pm/decisions/` when the owner has to choose, and stop. The proposal names one fallback for the trace question: keep `predict_fn`, with one worker (`MLFLOW_GENAI_EVAL_MAX_WORKERS=1`) and one long-lived event loop. That fallback judges a failed row again, so it is the owner's choice and not a quiet change.

Not verified by this run: a failed item on the live path (no failure can be forced there), and a judge of another provider (no key exists on 2026-11-23).

First run 2026-11-23 19:57 (outcome above): T1's agent trace arrived too late. The owner chose 'fix it now' (decision note 2026-11-23_late-agent-trace.md); TASK-017 and TASK-018 fix it, then this run is repeated as the same command into the same experiment, which then holds the runs of both attempts.

## Acceptance criteria

- [x] Before the run: `grep -c '^status: settled' docs/pm/decisions/2026-11-23_live-check-run.md` prints 1 and the note holds the owner's yes with the number of questions. If it prints 0, stop: the task waits on the owner
- [x] Before the run, read-only: `select count(*) from runs` gives 17 and `select count(*) from trace_info` gives 114 in `mlflow.db`, and no experiment is named `eval_reliability_smoke`. Write the three results into the outcome. A different number means another run happened in between: say which
- [x] The command is run exactly as the settled note states it. For 3 questions: `.venv/bin/python scripts/run_eval.py --recipe naive_rag --types T1 T2 T3 --limit 1 --experiment eval_reliability_smoke > <log> 2>&1`, with the exit status kept. It exits with status 0
- [x] `grep -c 'Event loop is closed' <log>` prints 0
- [x] The log holds one summary line per question type with `n=1`, and one line that names the generator `claude-opus-4-7` and the judge `claude-opus-5-5`
- [x] `select count(*) from runs r join experiments e on e.experiment_id = r.experiment_id where e.name = 'eval_reliability_smoke'` gives one run per question type (3 or 4)
- [x] Each of those runs holds the tags `ema.generator_model` = `claude-opus-4-7`, `ema.judge_model` = `claude-opus-5-5`, `ema.recipe` = `naive_rag` and `ema.retrieval.index_profile`, and the metrics `n`, `failed` and `judge_invalid`: `select key, value from tags where run_uuid = ?` and `select key, value from metrics where run_uuid = ?`
- [x] `select value from trace_tags where key = 'ema.bench_id'` gives exactly the ids that ran (`T1-001`, `T2-001`, `T3-001`, and `T4-001` for 4 questions). Each of those traces also holds the trace tag `ema.recipe` = `naive_rag`
- [x] For each of those traces, `select name, parent_span_id from spans where trace_id = ?` gives more than one span, and the span without a parent is named `AgentWorkflowAdapter.invoke`
- [x] For each finished item, `select name, value from assessments where trace_id = ?` gives one `faithfulness` and one `correctness` row on the agent's own trace, each with an integer from 1 to 5. A row that is not such a number is listed on the page, not hidden
- [x] For one trace: every entry of `context_passages` in the root span's output occurs verbatim in the output of one of the trace's tool spans, and no entry is longer than 2,000 characters
- [x] After the run: the experiment `ema_nlp` still holds 17 runs and 114 traces
- [x] `docs/eval/YYYY-MM-DD_eval_runner_live_check.md` exists, with the date of the run. It names the command, the commit of the code, `benchmark/benchmark.jsonl` at commit `ad4b214`, the item ids, both model ids, the run ids, n per type, the failed items by id, the counts before and after, and every criterion above with its result. It says that the generator and the judge are of one model family, and that the judge values of this run are a check of the runner and not a result for `naive_rag`
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-001]], [[TASK-008]], [[TASK-009]], [[TASK-013]], [[TASK-014]], [[TASK-016]], [[TASK-017]], [[TASK-018]]

## What was built

Second attempt, after TASK-017 and TASK-018: 2026-11-23 20:30:43-20:33:31, exit 0, the same command into eval_reliability_smoke. Runs ed9ebce6 (T1), a67a2090 (T2), ef8c9329 (T3), a099e716 (T4); agent traces tr-da7daf69, tr-5729a943, tr-a3c26f08, tr-655e9b82, 33 spans each, root AgentWorkflowAdapter.invoke, ema.bench_id + ema.recipe on each. Before 21 runs / 119 traces (ema_nlp 17/114, smoke 4/5); after 25 / 123 (ema_nlp 17/114, smoke 8/9). 0 'Event loop is closed', 0 'Failed to end span'. Summary n=1 per type, failed=0, judge_invalid=0, no_trace=0; all 4 runs hold the required tags and metrics; 8 judge values, JSON integers, on the agent's own traces. Criterion 11 (passages in the root span) not checkable as written; 38 result bodies, max 2000. Cost not measured (no token usage on traces). First attempt (19:57, runs ffebfc1d/7995304e/dd2db3ef/5ab99b52) failed criterion 8-10 for T1 (late trace); both attempts are on docs/eval/2026-11-23_eval_runner_live_check.md. make test: 736 passed, 2 skipped, 7 deselected (exit 0). make lint: All checks passed (exit 0).

## Files it touched

- [[YYYY-MM-DD_eval_runner_live_check]] — `docs/eval/YYYY-MM-DD_eval_runner_live_check.md`

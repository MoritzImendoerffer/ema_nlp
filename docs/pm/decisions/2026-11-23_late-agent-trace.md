---
type: pm-decision
epic: 2026-11-23_26_eval-reliability
status: settled
settled: 2026-11-23
opened: 2026-11-23
blocks: TASK-015
tags: [pm/decision]
---

# One of four agent traces arrived too late for its judge values

Written by Claude (Opus 5.5) during `/next` on 2026-11-23, after the live check of TASK-015.
Details and evidence: [`../../eval/2026-11-23_eval_runner_live_check.md`](../../eval/2026-11-23_eval_runner_live_check.md).

## What happened

The live run of 4 questions finished with exit status 0, no crash and no failed item. For
`T1-001` one span of the agent's trace could not end (`'MockValSer' object is not an instance
of 'SchemaSerializer'`, the serializer bug that `harness/llms.py` already works around in one
place). The trace was written, but later than the runner read it. So the runner judged that
answer without its trace, as its rule for this case says, and printed `no_trace=1`. Its two
judge values sit on a one-span trace that mlflow made, not on the agent's trace.

The other three items passed every check: their judge values are integers on the agent's own
trace of 33 spans, tagged with the benchmark id and the recipe.

## The options

| | What | What it costs |
|---|---|---|
| **(a)** | Accept: TASK-015 is done with this failure recorded on the page. Add a backlog row: find the span that still raises the serializer error and fix it; let the runner take the trace id from the adapter's own root span instead of "the newest trace of the process" | No more paid calls now. Until the row is done, an item hit by the bug is judged on a one-span trace, and the summary says so (`no_trace`) |
| **(b)** | Fix it in this work unit before closing it: debug logging to find the span (one more question, about 0.70 dollars, and it may not recur: 1 of 4 here), extend the wrapper's fix, take the trace id from the adapter, then repeat the 4-question check (about 2.90 dollars) | Two more paid runs and new code that the proposal does not list |

## Recommendation

**(a).** The runner behaved as designed: no answer was lost or hidden, and the count is
printed. The serializer error is older than this work and also strips spans from the chat
app's traces, so it is an item of its own, not part of making the runner honest.

## The answers

**2026-11-23, the owner: "fix it now"** — option (b). Find the span that fails to end and fix
the wrapper, let the runner take the trace id from the adapter's own root span, then repeat the
4-question check. Added to the plan as new tasks before TASK-015 is run again.

**Outcome, 2026-11-23.** TASK-017 found and fixed the cause (unbuilt serializers of the
anthropic SDK's response classes; `harness/llms.py` builds them before the first traced
call), TASK-018 takes the trace id from the adapter. The repeated run at 20:30 passed every
check: all four items' judge values are on the agent's own trace
([page](../../eval/2026-11-23_eval_runner_live_check.md#second-attempt-after-the-fix)).

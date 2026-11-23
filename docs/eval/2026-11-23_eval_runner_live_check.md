# Live check of the evaluation runner — 2026-11-23

*Work unit `2026-11-23_26_eval-reliability`, TASK-015 (backlog row 9). Run by Claude (Opus 5.5)
from a Claude Code session, on the owner's go-ahead
([decision note](../pm/decisions/2026-11-23_live-check-run.md)). This page checks the runner.
**The judge values below are not a result for `naive_rag`**: n = 1 per question type.*

**Two attempts.** The first (19:57) passed every check but one: the agent's trace of
`T1-001` was written after the runner read it. The owner chose to fix it at once
([decision](../pm/decisions/2026-11-23_late-agent-trace.md)); TASK-017 and TASK-018 did, and
the second attempt (20:30, [below](#second-attempt-after-the-fix)) passed every check.

## What ran

| | |
|---|---|
| Command | `HF_HUB_OFFLINE=1 .venv/bin/python scripts/run_eval.py --recipe naive_rag --types T1 T2 T3 T4 --limit 1 --experiment eval_reliability_smoke` |
| Started / ended | 2026-11-23 19:57:28 / 20:00:06 (+01:00), 2 min 38 s, exit status 0 |
| Code | `a1c587c` plus the uncommitted changes of tasks 1–16 of this work unit (`git diff HEAD -- harness scripts`, sha256 prefix `789c7a0d0dde94c6`, 20 files) |
| Benchmark | `benchmark/benchmark.jsonl`, identical to commit `ad4b214` (`git diff --quiet ad4b214` succeeds) |
| Items | `T1-001`, `T2-001`, `T3-001`, `T4-001`; one arm, no repeat |
| Generator | `claude-opus-4-7` (recipe `naive_rag`, model key `claude_opus`) |
| Judge | `claude-opus-5-5` (`roles.judge` = `claude_opus_5_5`) |
| Same family | Yes: the generator and the judge are both Claude models |
| Index | profile `neo4j_hier` on the live graph, `passage_chars` 2000; the graph was read, not written |
| Endpoint | the configured `ANTHROPIC_BASE_URL`, with an organization-scoped key and the `anthropic-workspace-id` header (TASK-016) |
| Log | `~/Nextcloud/Datasets/ema_nlp/results/2026-11-23_eval_reliability_smoke.log` (80 lines) |
| Cost | Not measured: the traces record no token usage. The arithmetic estimate in the decision note was about 2.90 dollars |

## The summary the runner printed

```
generator=claude-opus-4-7 judge=claude-opus-5-5
T1: n=1 failed=0 judge_invalid=0 no_trace=1 faithfulness=5.000 (n=1) correctness=5.000 (n=1)
T2: n=1 failed=0 judge_invalid=0 faithfulness=4.000 (n=1) correctness=4.000 (n=1)
T3: n=1 failed=0 judge_invalid=0 faithfulness=5.000 (n=1) correctness=4.000 (n=1)
T4: n=1 failed=0 judge_invalid=0 faithfulness=4.000 (n=1) correctness=1.000 (n=1)
```

No item failed. No judge value was invalid. One finished item, `T1-001`, was judged without
its own trace (`no_trace=1`); see "The failed criterion".

## MLflow runs and traces

| Type | Run | Trace with the judge values | Agent trace |
|---|---|---|---|
| T1 | `ffebfc1d8ab34e37ba0c318f2376ad9c` | `tr-6751e1afa7755787869201eba87d71e6` (1 span, `root_span`) | `tr-ad68d74f77347227f81cfeb7549328cf` (32 spans, not linked) |
| T2 | `7995304ed3fa4279b9d37c26819692bd` | `tr-e017f4b520823b219443e45007c60d9c` (33 spans) | the same |
| T3 | `dd2db3ef5a014a3d8562c52f52fb3ed9` | `tr-6a5f5c3f24ffef140c2c835e10b7031c` (33 spans) | the same |
| T4 | `5ab99b529b114b4195d96be426b213b3` | `tr-a3b4ef05da77e2722b9dfbe4ec6cb5f1` (33 spans) | the same |

## Counts before and after (read-only, `sqlite3 … mode=ro`)

| | Before | After |
|---|---|---|
| runs, all experiments | 17 | 21 |
| traces, all experiments | 114 | 119 |
| runs / traces in `ema_nlp` | 17 / 114 | 17 / 114 |
| experiment `eval_reliability_smoke` | absent | id 2: 4 runs, 5 traces |

The judge calls wrote no trace of their own: the 5 traces are 4 agent traces and 1 one-span
trace made by mlflow for `T1-001`.

## Every criterion of TASK-015

| # | Criterion | Result |
|---|---|---|
| 1 | Decision note settled with the owner's yes and the number of questions | **pass**: 4 questions, settled 2026-11-23 |
| 2 | Before: 17 runs, 114 traces, no `eval_reliability_smoke` | **pass** |
| 3 | The command as the note states it, exit status 0 | **pass** (4 questions: `--types T1 T2 T3 T4 --limit 1`) |
| 4 | `grep -c 'Event loop is closed' <log>` = 0 | **pass**: 0 |
| 5 | One summary line per type with `n=1`; one line naming `claude-opus-4-7` and `claude-opus-5-5` | **pass** |
| 6 | One run per type in `eval_reliability_smoke` | **pass**: 4 runs, all `FINISHED` |
| 7 | Each run holds `ema.generator_model`, `ema.judge_model`, `ema.recipe` = `naive_rag`, `ema.retrieval.index_profile`, and the metrics `n`, `failed`, `judge_invalid` | **pass**: all 4. They also hold `ema.retrieval.passage_chars` = 2000, `no_trace`, `<judge>_n`, `<judge>_mean`, and mlflow's own `<judge>/mean` |
| 8 | `ema.bench_id` gives exactly `T1-001` … `T4-001`, each trace also tagged `ema.recipe` = `naive_rag` | **fail for T1**: the four ids are present, but `T1-001` sits on the one-span trace, which has no `ema.recipe`. The agent's T1 trace has `ema.recipe` and no `ema.bench_id` |
| 9 | Each of those traces has more than one span, root `AgentWorkflowAdapter.invoke` | **pass for T2–T4** (33 spans each); **fail for T1** (1 span, `root_span`) |
| 10 | One `faithfulness` and one `correctness` assessment per finished item on the agent's own trace, each an integer 1–5 | **pass for T2–T4**; T1's two values are integers but sit on the one-span trace. All 8 values are stored as JSON integers, none as text |
| 11 | Every `context_passages` entry of the root span's output occurs verbatim in a tool span's output; none longer than 2,000 characters | **not checkable as written**: the root span's output holds the answer, not `context_passages`, and the judge calls leave no trace. Checked instead: every result body in the 4 agent traces' tool spans is at most 2,000 characters (38 bodies, maximum 2,000). The equality of the judge's passages and the agent's bodies rests on the test `test_passages_from_nodes_returns_what_the_agent_read` and on TASK-013's read-only live call (9 of 9 equal) |
| 12 | After: `ema_nlp` still 17 runs, 114 traces | **pass** |
| 13 | This page | written |
| 14 | `make test`, `make lint` | see the task's outcome |

## The failed criterion: the T1 agent trace arrived late

The log holds one warning, at 19:58:07, during `T1-001`:

```
WARNING mlflow.entities.span: Failed to end span 379f205aa0360569:
'MockValSer' object is not an instance of 'SchemaSerializer'.
```

What the store shows:

- The agent's T1 trace `tr-ad68d74f…` exists, status OK, 31.2 s, root span
  `AgentWorkflowAdapter.invoke`, trace tag `ema.recipe` = `naive_rag`. It holds 32 spans; the
  other three agent traces hold 33. The span that could not end is the one missing.
- The runner read no new trace id after `T1-001` (`mlflow.get_last_active_trace_id()` gave
  nothing new), so it judged the answer on a row without a trace. mlflow made the one-span
  trace `tr-6751e1af…` for it, and the runner printed and logged `no_trace=1`, as the rule of
  TASK-005 says.
- The agent's T1 trace is not linked to the run and has no `ema.bench_id`.

The reading, not proven: when a child span cannot end, mlflow's exporter defers the export of
the root span (`mlflow/tracing/export/mlflow_v3.py`, `_deferred_root_spans`), so the trace is
written later than the runner reads it. The serializer error is the one `harness/llms.py`
documents as fix 2 of the `_Anthropic` wrapper (2026-07-07); this run shows that one path still
raises it. Which span it was is not known: the warning names only its id, and the span is not
stored.

What it means for the runner: a finished answer is never lost. It is judged and counted as
`no_trace`. But its judge values then sit on a trace without the agent's spans, which is the
defect the `trace` column was built to end. One of four items was affected in this run.

The owner chose to fix it now ([decision](../pm/decisions/2026-11-23_late-agent-trace.md)).

**The cause, found after this attempt** (TASK-017). The SDK builds a response with
`construct_type`, without validation, so some response classes keep an unbuilt `MockValSer`
serializer. Autolog closes the `CHAT_MODEL` span of `Anthropic.achat` before the wrapper's
sanitize step, and mlflow's encoder (`mlflow/tracing/utils/__init__.py:77`, `model_dump`)
hits the unbuilt class. In a `claude-opus-4-7` response these were `ToolUseBlock`, its
`caller` (`DirectCaller`), `CacheCreation` and `OutputTokensDetails`; a `claude-haiku-4-5`
response did not fail. Only the first such response of a process fails, because the
sanitize step then builds the classes, which is why it hit the first item. Found with three
short structured calls to a scratch store and mlflow's debug traceback, and reproduced
offline with the SDK's `construct_type`. The missing span of the T1 trace was
`_Anthropic.achat` of type `CHAT_MODEL`.

**The fix.** `harness/llms.py` builds the serializers of all 382 response classes of
`anthropic.types` once per process, before the first traced call (0.09 s). And the runner
takes each item's trace id from the adapter's own root span (TASK-018) instead of asking
mlflow for the newest trace.

## Judge values per item

Listed for completeness; n = 1 per type, and they say nothing about `naive_rag`.

| Item | faithfulness | correctness |
|---|---|---|
| `T1-001` | 5 | 5 |
| `T2-001` | 4 | 4 |
| `T3-001` | 5 | 4 |
| `T4-001` | 4 | 1 |

## What this run did not check

- A failed item on the live path: no failure occurred, and none can be forced there.
- A judge of another provider: no key for one exists.
- The cost: the traces record no token usage.

## Second attempt, after the fix

| | |
|---|---|
| Command | the same as the first attempt, into the same experiment |
| Started / ended | 2026-11-23 20:30:43 / 20:33:31 (+01:00), 2 min 48 s, exit status 0 |
| Code | `a1c587c` plus the uncommitted changes of tasks 1–18 (`git diff HEAD -- harness scripts`, sha256 prefix `8134e58d06517805`, 20 files) |
| Benchmark, items, models, index | as in the first attempt |
| Log | `~/Nextcloud/Datasets/ema_nlp/results/2026-11-23_eval_reliability_smoke_run2.log` (78 lines; 0 `Event loop is closed`, 0 `Failed to end span`) |
| Cost | not measured; the arithmetic estimate was about 2.90 dollars. Diagnosing the cause took four further structured calls of a few hundred tokens each (one `claude-haiku-4-5`, three `claude-opus-4-7`) and one to check the fix |

```
generator=claude-opus-4-7 judge=claude-opus-5-5
T1: n=1 failed=0 judge_invalid=0 faithfulness=4.000 (n=1) correctness=5.000 (n=1)
T2: n=1 failed=0 judge_invalid=0 faithfulness=5.000 (n=1) correctness=4.000 (n=1)
T3: n=1 failed=0 judge_invalid=0 faithfulness=5.000 (n=1) correctness=5.000 (n=1)
T4: n=1 failed=0 judge_invalid=0 faithfulness=4.000 (n=1) correctness=1.000 (n=1)
```

| Type | Run | Agent trace, with the judge values |
|---|---|---|
| T1 | `ed9ebce6c7124a38823fa26ca12cbad1` | `tr-da7daf69b97ce250bddc292896b8a5cd` (33 spans) |
| T2 | `a67a209082f34b26951a6af2c0581e63` | `tr-5729a9438f580719aa325dd92fcf89fd` (33 spans) |
| T3 | `ef8c932943c547c994b7b2f861ad2eb1` | `tr-a3c26f0833411272b693e24755e16677` (33 spans) |
| T4 | `a099e716ecce4a6aae6c3e36af0289ff` | `tr-655e9b82ec80a4a94a4af724b3f4fe21` (33 spans) |

| | Before | After |
|---|---|---|
| runs / traces, all experiments | 21 / 119 | 25 / 123 |
| runs / traces in `ema_nlp` | 17 / 114 | 17 / 114 |
| runs / traces in `eval_reliability_smoke` | 4 / 5 | 8 / 9 |

### The criteria, second attempt

| # | Criterion | Result |
|---|---|---|
| 3 | Command as settled, exit status 0 | **pass** |
| 4 | No `Event loop is closed` | **pass**: 0 |
| 5 | One summary line per type with `n=1`; the line naming both models | **pass**; `no_trace` is 0 everywhere and not printed |
| 6 | One run per type | **pass**: 4 new runs, all `FINISHED` |
| 7 | The five required run tags and `n`, `failed`, `judge_invalid` | **pass**: all 4 runs, plus `ema.retrieval.passage_chars` = 2000 and `no_trace` = 0 |
| 8 | `ema.bench_id` = `T1-001` … `T4-001`, each trace also tagged `ema.recipe` = `naive_rag` | **pass**: on the 4 agent traces |
| 9 | More than one span, root `AgentWorkflowAdapter.invoke` | **pass**: 33 spans each |
| 10 | One `faithfulness` and one `correctness` value per item on the agent's own trace, integers 1–5 | **pass**: 8 values, stored as JSON integers |
| 11 | The passages the judge read | **not checkable as written** (see the first attempt); 38 result bodies in the tool spans, at most 2,000 characters each |
| 12 | `ema_nlp` unchanged | **pass**: 17 runs, 114 traces |

Judge values per item, n = 1 per type and no result for `naive_rag`: `T1-001` faithfulness 4,
correctness 5; `T2-001` 5 and 4; `T3-001` 5 and 5; `T4-001` 4 and 1. The generator and the
judge are both Claude models.

The second attempt checks the runner on the live path for items that finish. It does not
check a failed item on the live path, a judge of another provider, or the cost.

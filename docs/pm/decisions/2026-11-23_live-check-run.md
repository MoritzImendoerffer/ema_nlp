---
type: pm-decision
epic: 2026-11-23_26_eval-reliability
status: settled
settled: 2026-11-23
opened: 2026-11-23
blocks: TASK-015
tags: [pm/decision]
---

# The one paid run of the eval-reliability work: 3 questions or 4, and the go-ahead

Written by Claude (Fable 5.2) during `/plan` on 2026-11-23. The question comes from the
exploration of backlog row 9 (`.claude/work/2026-11-23_26_eval-reliability/exploration.md`,
section 11, question 3, and section 10.4).

## Why a paid run is needed at all

The new runner is tested without a model call: the agent and the judges are stand-ins. A
stand-in proves that the code calls what its author expected. It does not prove that mlflow
and the live agent behave that way. Two points have no proof until one real run:

- that the judge's values land on the agent's own trace, with all its spans, when the trace
  was made by the LlamaIndex autolog inside the runner's loop;
- that the trace is written to the store before the runner reads it back.

The same run is the first time the new passage text, the new judge model and the new run tags
meet real data. It is the last task of the plan (TASK-015), and the only run of this work
unit that pays for more than one short completion.

## The two questions

**1. How many questions.** The proposal's check is `scripts/run_eval.py --recipe naive_rag
--limit 1`. `--limit 1` means one question per question type, and the benchmark has four types
(T1 to T4), so it is 4 questions. `CLAUDE.md` rule 4 allows a smoke run of 3 items without
asking. The proposal's run is one more than that.

**2. The go-ahead** for the run, with its cost below.

## The options

| | Command | Questions | What it checks |
|---|---|---|---|
| **(a)** | `--recipe naive_rag --types T1 T2 T3 --limit 1` | 3: `T1-001`, `T2-001`, `T3-001` | Everything the run exists for. Three question types open three runs, so the per-type loop is exercised. T4 (synthesis) is left out |
| **(b)** | `--recipe naive_rag --limit 1`, as the proposal says | 4: the same plus `T4-001` | The same, and one T4 item. T4 questions search more often, so this is the most expensive item of the four |

Both use `benchmark/benchmark.jsonl` at commit `ad4b214`, the generator `claude-opus-4-7`
(the recipe `naive_rag`) and the judge `claude-opus-5-5`. Both are Claude models. The run
compares nothing, and its judge values are a check of the runner, not a result for
`naive_rag`.

Both write to a new MLflow experiment, `eval_reliability_smoke`, so that the experiment
`ema_nlp` keeps its 17 runs and 114 traces unchanged. That is the plan's choice; say so if the
run should go to `ema_nlp` instead.

## Cost, with the arithmetic

The token counts are arithmetic on measured means, not a bill. The prices are the list prices
per million tokens from the Claude API reference that ships with Claude Code (table cached
2026-11-03): `claude-opus-4-7` 5 US dollars for input and 25 for output; `claude-opus-5-5` 4
and 20. Requests on this machine go through a gateway, which may bill differently.

**Per question, the generator.**

- One search result is 10 passages of up to 2,000 characters: 20,000 characters, about 5,000
  tokens.
- The stored runs average 4.61 searches and 4.73 model calls per question. An agent sends
  every earlier search result again on each later call. With 5 searches that is
  5,000 × (5 + 4 + 3 + 2 + 1) = 75,000 input tokens.
- System prompt, tool description and question: assumed 1,500 tokens on each of 5 calls,
  7,500 tokens. This number is an assumption.
- Input: about 82,500 tokens, 0.41 dollars. Output: assumed 3,000 tokens, 0.08 dollars.
- **About 0.49 dollars.** No prompt caching is assumed, which overstates it.

**Per question, the judges.**

- Each of the two judges receives the whole output of the agent, with the passages
  (`harness/eval/judges.py:32-37` maps both `context` and `answer` to `outputs`).
  4.61 searches × 10 passages × up to 2,000 characters is about 92,000 characters, about
  23,000 tokens per judge call, 46,000 for both: 0.18 dollars.
- Output with the model's thinking: assumed 1,500 tokens per call, 3,000 for both: 0.06
  dollars.
- **About 0.24 dollars.**

| | Generator calls | Judge calls | Rough amount |
|---|---|---|---|
| (a) 3 questions | about 14 | 6 | about 2.20 dollars |
| (b) 4 questions | about 19 | 8 | about 2.90 dollars |

The real amount can be twice that if the T3 or T4 item searches more often than the mean. I
would not expect more than 6 dollars for either option.

**Time.** The stored runs take 44.5 seconds per question on average, and the new runner asks
the questions one after the other. Under 10 minutes for either option, with the judge calls.

**GPU.** About 15 query embeddings. No index is built and nothing is written to the graph.

**The store.** The run appends to `mlflow.db`: one experiment, one run per question type, and
at least one trace per question. No command of this repository undoes that. Nothing that is
in the store today is changed.

## Recommendation

**(a), 3 questions.** This is the assistant's recommendation. The run checks the runner, and
three types exercise everything the fourth would. It also stays inside the smoke limit that
`CLAUDE.md` sets. Option (b) is what the proposal wrote down, costs about 0.70 dollars more,
and adds the one question type that searches the most.

## What waits on this

TASK-015 only, the last task. Every other task of the plan can be done first.

If a check of the run fails, the task stops and reports. It does not repeat the run, and it
does not change the runner without a new note.

## The answers

**2026-11-23, the owner: "run 4 but use claude code for it, not the API".** The number is
settled: 4 questions, `T1-001`, `T2-001`, `T3-001` and `T4-001`. Open: how the model calls
are made through Claude Code instead of the API. The runner's agent and judges call the
Anthropic API today, so this changes what TASK-015 runs; the assistant asked the owner what
is meant before the run.

**2026-11-23, the owner, asked to choose between the planned API run, a judge or agent
backed by the `claude` CLI, and holding the run: "Option 1"** — the planned run on the API,
launched from the Claude Code session: `naive_rag`, 4 questions, experiment
`eval_reliability_smoke`, about 2.90 dollars by the arithmetic above. The owner first
updates `ANTHROPIC_API_KEY` in the credentials file; the run starts after the owner says
the key is updated.

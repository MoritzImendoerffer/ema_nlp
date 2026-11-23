# Implementation plan: eval reliability

| | |
|---|---|
| Work unit | `2026-11-23_26_eval-reliability` |
| Proposal | [`docs/next/eval_reliability.md`](../../../docs/next/eval_reliability.md), the requirements; not copied here |
| What the code looks like today | [`exploration.md`](exploration.md) |
| The task list a session reads | [`state.json`](state.json) |
| Backlog row | 9, top of `Now` |
| Branch | `eval-reliability`, from `develop` at `a1c587c` |
| Planned | 2026-11-23, by Claude (Fable 5.2) |
| Gates before any change | `make test`: 692 passed, 2 skipped, 7 deselected. `make lint`: no finding |

This page is for a person. `state.json` holds the same plan with the acceptance criteria that a
command can check, and a later session works from that file.

## What is being built

Every later number of this project goes through `scripts/run_eval.py`. Today that runner
reports numbers that cannot be trusted, for reasons that were each read in the code:

- A crashed agent run is judged as if it were an answer. Six failed rows went to the judges in
  the stored runs; one holds correctness 5 beside faithfulness 1.
- A mean leaves out what is not a number and prints no count. A stored `correctness_mean` of
  4.353 is 74 / 17 for a run of 20 questions.
- A trace cannot be matched to its benchmark item.
- The judge is the generator's model, and no run says which model judged it.
- The agent reads the first 400 characters of a passage. The judge reads all of it.

After this work:

1. The runner asks the questions itself, one after the other on one event loop. That ends the
   crash `RuntimeError: Event loop is closed`, and it lets the runner know which items failed.
2. A failed item gets no judge call. It is listed by its id and left out of every mean. Every
   mean prints the number of rows behind it.
3. The judge model is a setting: `roles.judge` in `harness/configs/models.yaml`, or `--judge`
   for one run. Every run records the model id of the generator and of the judge. The default
   judge becomes `claude-opus-5-5`, which no recipe generates with.
4. A search result shows the agent the matched leaf first, then its parent, up to 2,000
   characters. The judge receives exactly that text.
5. Three docs pages stop showing a call that deletes the live graph.

No Mongo collection and no graph property changes. Nothing is rebuilt or re-embedded.

## The tasks

| Task | Kind | What it does | Needs |
|---|---|---|---|
| 001 | documentation | Take `build_index(profile, reset=True)` out of three docs pages | |
| 002 | mechanism | The prediction loop: one event loop, a result per item with `ok` and the error | |
| 003 | mechanism | The two judges return an integer | |
| 004 | mechanism | Pure functions: the judged rows, the counts, the printed summary | 002 |
| 005 | wiring | The driver uses the loop. A failed item is not judged. A run gets its tags when it opens | 002, 003, 004 |
| 006 | mechanism | Each provider of `models.yaml` maps to mlflow's name, key and endpoint | |
| 007 | wiring | `--judge`; both model ids on every run; a warning when they are equal | 005, 006 |
| 008 | wiring | The resolved recipe on every run; a line for each declared layer that did not run | 005 |
| 009 | contract | `roles.judge` names a new entry for `claude-opus-5-5`; `harness/llms.py` stops sending `temperature` to it | 007 |
| 010 | mechanism | The retriever keeps the matched leaf's text on the node | |
| 011 | mechanism | The tool renders leaf, then parent, to a limit; the judge gets the same text | 010 |
| 012 | contract | The limit is the profile key `retrieval.passage_chars` | 011, **the owner's answer** |
| 013 | wiring | `build_recipe` passes the limit to the two search tools | 012 |
| 014 | documentation | The tool page, a note on two earlier result pages, `--judge` in the recipe page | 007, 008, 009, 013 |
| 015 | measurement | One run on the live graph, and a page that says what the store shows | all of the above, **the owner's go-ahead** |

## The order, and why

**The docs fix is first.** It depends on nothing, and while it is undone a pasted snippet
deletes a graph of 7.5 million nodes.

**The runner comes before the passage.** Tasks 002 to 009 make a number honest. Tasks 010 to
013 change what the agent reads. The two halves share no code, so either could go first. The
runner goes first because both open questions for the owner sit in the second half and at the
end: eleven tasks can be done before any answer is needed.

**Inside the runner, pure functions come before the driver.** Tasks 002, 003 and 004 add
functions beside the old ones, so `scripts/run_eval.py` keeps working after each of them.
Task 005 switches the driver over and deletes the old functions and their three tests in one
step. Those three tests assert the defect, so they have to go; they go when their last caller
goes.

**The judge is rebound after the run records its judge.** Task 009 comes after task 007, so
the first run that the new judge scores says which model judged it.

**The live run is last.** It checks the final state: the runner, the judge and the passage
together. An earlier, second live run was considered and left out. The two halves are
independent, so a fault found at the end costs no more to fix than one found in the middle,
and one run costs less than two.

**Critical path:** 002 → 004 → 005 → 007 → 009 → 014 → 015. Seven tasks. The passage chain,
010 → 011 → 012 → 013, joins at 014.

Every task ends with `make test` and `make lint` green. No task leaves a half-switched driver.

## What waits on the owner

Two notes under `docs/pm/decisions/`. Neither blocks the first eleven tasks.

| Note | Blocks | The question | The assistant recommends |
|---|---|---|---|
| [`2026-11-23_passage-limit-location.md`](../../../docs/pm/decisions/2026-11-23_passage-limit-location.md) | 012, and with it 013 | The proposal says the limit is "set in the tool's config". No tool has a config file. Does the key go into the index profile, the recipe, or a new file? | the index profile |
| [`2026-11-23_live-check-run.md`](../../../docs/pm/decisions/2026-11-23_live-check-run.md) | 015 | The proposal's live check is 4 questions; the smoke limit of `CLAUDE.md` is 3. Which, and may it run? | 3 questions, about 2.20 US dollars at list price |

## What the plan decided that the proposal left open

Each of these is the assistant's decision. Each can be overruled before its task starts.

| Decision | Task | Why |
|---|---|---|
| The judge's values go on the agent's own trace through a `trace` column in the data, not through the proposal's sketch | 005 | The sketch (`inputs`, `outputs`, `expectations` only) puts each value on a new trace with one span. Checked with a run in the exploration, section 5.1 |
| A finished answer without a trace is judged, and counted as `no_trace` | 005 | The answer exists. Counting it as failed would hide an answer |
| The failed items go to the run as the artifact `failed_rows.json`, and their traces are linked to the run | 005 | The proposal says "logged to the run with its error" and names no form |
| Each mean prints its own n, and the run gets the metric `<judge>_n` beside `n`, `failed` and `judge_invalid` | 004, 005 | With two judges, one total of invalid values does not say how many rows stand behind each mean |
| A judge value counts as invalid when it is text, null or missing: invalid = finished rows minus numeric values | 004 | A refused judge call stores null with an error. Six of the eleven stored non-numbers are of that kind |
| The new model entry is named `claude_opus_5_5` | 009 | A name is needed |
| The overlap rule: the leaf first, then the parent with the leaf taken out, and a gap marker where it was | 011 | The parent contains the leaf. Showing it twice wastes a quarter of the 2,000 characters |
| The judge gets the same text because the tool writes what it rendered onto the node (`agent_text`), and `passages_from_nodes` returns that | 011 | At 2,000 characters, 60.6% of the stored parents are still cut. Returning the full text would keep the defect |
| `matched_text` is kept out of the text that a reranker scores | 010 | `SentenceTransformerRerank` scores the node's content with its metadata (`llama_index/core/postprocessor/sbert_rerank.py:75`) |
| The third docs page, and the warning beside `--full --reset` | 001 | `docs/RUNTIME_VERIFICATION.md:86` shows the same call; `docs/RETRIEVAL.md:193` shows its command-line form |
| The live run goes to its own experiment, `eval_reliability_smoke` | 015 | The experiment `ema_nlp` then holds only runs that count |
| No run tag says which layers did not run; the runner prints a line | 008 | The proposal asks for the printed line and lists the new stored shapes without such a tag. Say so if the tag is wanted |

## The stored shapes that are new

Nothing in Mongo and nothing in the graph. In `mlflow.db`, from the first run after task 005:

| Where | Key | Since |
|---|---|---|
| trace tag | `ema.bench_id` | 005 |
| run tags | `ema.recipe`, `ema.benchmark`, `ema.question_type`, now set when the run opens | 005 |
| run metrics | `n`, `failed`, `judge_invalid`, `no_trace`, `<judge>_mean`, `<judge>_n` | 005 |
| run artifact | `failed_rows.json`, when an item failed | 005 |
| run tags | `ema.generator_model`, `ema.judge_model` | 007 |
| run tags | every `ema.*` key of the resolved recipe | 008 |
| trace attribute and run tag | `ema.retrieval.passage_chars` | 012 |

In configuration: one model entry and one role binding in `harness/configs/models.yaml`
(009), and the key `retrieval.passage_chars` in the three index profiles (012). A profile
without the key reads as 2,000.

The 17 runs and 114 traces stored today have none of these and are not changed. Their numbers
do not compare with a number from the new runner: the runner, the judge model, the type of a
judge value and the text the agent reads all differ. No earlier number is repeated now
(decision D of the proposal).

## What could go wrong

- **The trace handling is the least tested part.** The offline test makes its trace with
  `mlflow.start_span`. A real trace comes from the LlamaIndex autolog inside the runner's
  loop. Only task 015 shows that the judge's values land on such a trace. If they do not, task
  015 stops and reports; the proposal's fallback (`predict_fn` with one worker) judges a
  failed row again, so taking it is the owner's choice.
- **A stale trace id.** `last_trace_id` returns the newest trace of the process. If an item
  makes no trace, it returns the trace of the item before, and a judge value would land on
  the wrong item. Task 002 has a test for exactly this.
- **A test that writes the real store.** Task 005 calls the real `mlflow.genai.evaluate` in a
  test. It must use a store under `tmp_path`, and must not switch LlamaIndex autolog on for
  the rest of the test process. The acceptance list checks that `mlflow.db` keeps its
  modification time.
- **The inline judge fails silently.** `harness/judge.py` sends `temperature` to the judge
  model, `claude-opus-5-5` refuses the field, and `run_inline_judges` swallows the error. Task
  009 fixes the prefix list in the same step as the binding and proves it with one real call.
- **Five times the tokens.** Each search result grows from about 1,000 to about 5,000 tokens,
  in the app as well as in the runner, and the grader of `corrective_search` reads the longer
  text on every cycle. This is the cost that decision C accepted.
- **The chain export parses the tool's output by line.** A body that spans two lines, or one
  that is a single bracketed phrase, breaks `harness/export/chain_from_trace.py`. Task 011
  keeps the body on one line and tests the parser on the new output.
- **A longer wait.** The questions run one after the other. 45 items at 44.5 seconds are about
  33 minutes per recipe for the agent runs; today 10 run at once.
- **Three other providers are untested with a real call.** No key for Together or for an
  OpenAI-compatible server exists on this machine. Task 006 tests those routes up to the model
  name, the key and the endpoint, and says so.

## What will not be attempted

From the proposal, unchanged:

- No repeats, no resume, no new metric. They come with the nine-class benchmark (backlog
  row 15).
- The few-shot layer and the inline judge stay in `app.py`. The runner says that it does not
  run them.
- Citation attribution is not changed.
- No earlier evaluation is repeated.
- No request timeout and no step limit (backlog row 7).

Added by the plan:

- No second live run in the middle of the work.
- No judge call to a provider other than Anthropic.
- No change to `topic_context`, which already shows each chunk in full.
- No change to the two judge prompts under `harness/judges/`.

## Cost of the whole work unit

| What | Calls | Rough amount |
|---|---|---|
| Task 009: one short completion that proves the `temperature` fix | 1 | under 0.01 US dollars |
| Task 015: the live run, 3 questions | about 14 generator calls, 6 judge calls | about 2.20 US dollars |
| Task 015: the live run, 4 questions | about 19 generator calls, 8 judge calls | about 2.90 US dollars |

The arithmetic is in the decision note for the live run. No GPU job runs longer than a few
query embeddings. No run deletes anything.

## The checks of task 015, as queries

Open the store read-only: `sqlite3.connect("file:mlflow.db?mode=ro", uri=True)`. The table and
column names were read from the store on 2026-11-23 (mlflow 3.14.0).

```sql
-- before the run: 17, 114, and no row
select count(*) from runs;
select count(*) from trace_info;
select experiment_id from experiments where name = 'eval_reliability_smoke';

-- after the run: one run per question type
select r.run_uuid from runs r join experiments e on e.experiment_id = r.experiment_id
 where e.name = 'eval_reliability_smoke';

-- each run: both model ids, the recipe, the counts
select key, value from tags    where run_uuid = ?;
select key, value from metrics where run_uuid = ?;

-- each trace: its item, its recipe, the agent's spans, the judge's values
select request_id, value from trace_tags where key = 'ema.bench_id';
select key, value from trace_tags where request_id = ?;
select name, parent_span_id from spans where trace_id = ?;
select name, value, error from assessments where trace_id = ?;

-- the experiment that counts is unchanged: 17, 114
select count(*) from runs where experiment_id = 1;
select count(*) from trace_info where experiment_id = 1;
```

Before 2026-11-23 the store holds no trace tag `ema.bench_id` and no run tag
`ema.generator_model` or `ema.judge_model`, so every row these queries return comes from the
new run.

## After the last task

`/ship` moves the description into `docs/`, adds entries to `DECISIONS.md` for the two
decision notes, deletes the backlog row and the proposal, appends to `.claude/HISTORY.md`,
empties `.claude/work/ACTIVE_WORK` and merges the branch into `develop` when the owner asks.

The backlog row gives this item the size S, about one session. The plan has 15 tasks. That is
closer to M, a few sessions. The order of the backlog is the owner's; the plan changes none of
it.

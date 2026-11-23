# Exploration: eval reliability

| | |
|---|---|
| Work unit | `2026-11-23_26_eval-reliability` |
| Proposal | [`docs/next/eval_reliability.md`](../../../docs/next/eval_reliability.md) (the requirements; not copied here) |
| Backlog row | 9, top of `Now` |
| Explored | 2026-11-23, by Claude (Fable 5.2) |
| Branch | `eval-reliability`, made from `develop` at `a1c587c` |
| Code state | The code read here is `b8f7216` plus the workflow adoption of 2026-11-23. The owner had that adoption committed as `a1c587c` before the branch was made; it changes no file under `harness/` or `scripts/run_eval.py` |
| Gates before any change | `make test`: 692 passed, 2 skipped, 7 deselected, 13.68 s. `make lint`: "All checks passed!", exit 0 |

## 1. Verdict

**The proposal stands.** All seven defects are in the code as described. Every count it gives
was recounted in `mlflow.db` and holds, with one small difference (section 4).

Eight points need a correction or an addition before `/plan`. Three of them change which files
the work touches:

| # | Finding | Consequence |
|---|---|---|
| 1 | The data form the proposal sketches (`inputs`, `outputs`, `expectations`, no `predict_fn`) puts each judge value on a **new trace with one span**, not on the agent's trace. | Add a `trace` column per row. Then the judge values land on the agent's own trace. The proposal's fallback (keep `predict_fn`, one worker) is not needed. Section 5.1. |
| 2 | One worker alone would not end the crash. One event loop per call is the cause; the thread pool only makes it more frequent. | The runner must own one loop for all questions, as the proposal's main idea says. Section 6. |
| 3 | The retriever drops the matched leaf's text when it merges to the parent. It keeps the leaf's id only. | `harness/indexing/property_graph.py` changes too. The proposal lists `harness/tools/search.py` only. No graph change. Section 7.1. |
| 4 | "The judge receives the same text" needs `passages_from_nodes` to change, not only `format_nodes`. 60.6% of the stored passages are longer than 2,000 characters. | `context_passages` becomes the text the tool rendered. Three callers. Section 7.2. |
| 5 | `claude-opus-5-5` refuses the field `temperature` (HTTP 400, real call). `roles.judge` has a second reader that sends it. | `harness/llms.py` needs one more model prefix, or the inline judge of `agentic_judged` fails silently on every turn after the rebinding. Section 8.2. |
| 6 | A provider name is not all that mlflow needs translated. `togetherai` reads another key variable than this repository's, and `openai` reads its key and base from fixed variables. | `build_judge` has to map the key and the endpoint, not only `judge_model_uri` the name. Section 5.3. |
| 7 | A third docs page shows the reset call: `docs/RUNTIME_VERIFICATION.md:86`. | Include it, or word the `grep` check per page. Section 9. |
| 8 | The proposal's live check (`--limit 1`) is 4 questions. The smoke limit of `CLAUDE.md` rule 4 is 3 items. | A decision note with the cost, or `--types T1 T2 T3`. Section 10.4. |

Decision E's condition is met: two real judge calls to `claude-opus-5-5` through the configured
endpoint returned a value (section 8.1).

## 2. The proposal's claims, checked

| Claim | Result | Evidence |
|---|---|---|
| `AgentWorkflowAdapter.invoke` calls `asyncio.run` once per question | true | `harness/agents/workflow_adapter.py:124-126` |
| `MLFLOW_GENAI_EVAL_MAX_WORKERS` defaults to 10 | true | `mlflow/environment_variables.py:786`; unset on this machine, so `_get_pool_sizes` gives 10 predict threads (`mlflow/genai/evaluation/harness.py:173-190`) |
| One agent is shared by all threads | true | `run_recipe_benchmark` builds one runner (`harness/eval/runner.py:179-182`); its LLM holds one `anthropic.AsyncAnthropic` (`llama_index/llms/anthropic/base.py:315`) |
| A crashed row is judged | true, and mlflow gives no way around it with `predict_fn` | `_run_predict` catches the exception, stores `error_message`, leaves `outputs=None`; `_run_score` then runs every scorer (`harness.py:805-822`, `840-877`) |
| `mean_scores` skips what `float()` rejects; `summarize` prints no n | true | `harness/eval/runner.py:90-101`, `204-213` |
| `to_eval_data` drops `bench_id` | true | `runner.py:62-74`. Both benchmark files carry a unique `bench_id` (45 and 5 rows, no duplicate question text) |
| A run carries three tags and neither model | true | `runner.py:192-199`; the store holds exactly the run tag keys `ema.recipe`, `ema.benchmark`, `ema.question_type` |
| `roles.judge` is `claude_opus`; all ten recipes generate with `claude_opus` | true | `harness/configs/models.yaml:55`; `model: claude_opus` in each of the 10 files of `harness/configs/recipes/` |
| `judge_model_uri` raises for every provider but `anthropic` | true | `harness/eval/judges.py:101-105` |
| `run_eval.py` has `--model` and no judge option | true | `scripts/run_eval.py:25`. `run_recipe_benchmark` already takes `judge_role` (`runner.py:159`); the script does not pass it |
| `ema_search` cuts each passage to 400 characters; with `merge: true` it is the parent's first 400 | true | `harness/tools/search.py:29`, `:116`; `harness/indexing/property_graph.py:717-721` |
| The runner never calls `setup_tracing` | true | callers: `app.py:167-168`, `scripts/run_agent_demo.py:35`. In the store, 90 traces have the root span `FunctionAgent.run` and 10 have `AgentWorkflowAdapter.invoke`; 10 traces carry the tag `ema.recipe` |
| Few-shot and the inline judge run in `app.py` only | true | `app.py:603`, `702-720`, `740-751`; no other caller outside `tests/` |
| Two docs pages show `build_index(profile, reset=True)` | true, and a third exists | `docs/RETRIEVAL.md:228`, `docs/ARCHITECTURE.md:210`, and `docs/RUNTIME_VERIFICATION.md:86` |
| The default profile is the full corpus | true | `harness/configs/index/neo4j_hier.yaml:20`, `limit: null` |
| `feedback_value_type` is a parameter of `make_judge` | true | `mlflow/genai/judges/make_judge.py:118`; types accepted: `str`, `int`, `float`, `bool`, `Literal`, and dicts and lists of these |
| `litellm` is not installed | true | `importlib.metadata.version("litellm")` raises |
| `together_ai` and `openai_compatible` are not mlflow provider names | true | `is_supported_provider` returns `False` for both, `True` for `togetherai` and `openai` |
| `models.yaml` lists three Claude models | true | `claude-haiku-4-5-20251001`, `claude-sonnet-5`, `claude-opus-4-7` |

The proposal cites no other repository. Nothing was checked in `ema_scraper` or `doctool`.

## 3. Installed versions

Read from `.venv` with `importlib.metadata` on 2026-11-23. Python 3.13.13.

| Package | Version |
|---|---|
| mlflow | 3.14.0 |
| llama-index-core | 0.14.22 |
| llama-index-llms-anthropic | 0.11.5 |
| anthropic | 0.105.2 |
| httpx | 0.28.1 |
| chainlit | 2.11.1 |
| neo4j (driver) | 5.28.4 |

## 4. Counts, recounted in `mlflow.db`

All queries opened the file read-only (`sqlite3.connect("file:mlflow.db?mode=ro", uri=True)`).
The file's modification time is unchanged after this exploration (2026-07-20 21:30).

| Proposal | Query | Result |
|---|---|---|
| 114 traces | `select count(*) from trace_info` | 114 (105 `OK`, 8 `ERROR`, 1 `IN_PROGRESS`) |
| 5 evaluation traces ended with `Event loop is closed` | `select distinct trace_id from spans where content like '%Event loop is closed%'` | 5, all of 2026-07-13, all `ERROR` |
| 7 of 85 faithfulness values are text or null | `select value from assessments where name='faithfulness' and assessment_type='feedback'`, then `float()` on each | 78 numeric, 7 not |
| 4 of 85 correctness values | the same for `correctness` | 81 numeric, 4 not |
| one row with correctness 5 and faithfulness 1; one with correctness 5 and `" agent errored"` | the assessments of the 5 traces | `tr-3a54d942…`: `"5"` and `"1"`. `tr-97f5ef33…`: `"5"` and `" agent errored"` |
| median passage 2,112 characters | `mlflow.spanOutputs` of the 479 spans named `HierarchicalPGRetriever.retrieve` | 4,875 passages, median **2,130**, maximum 3,330. 98.8% are longer than 400 characters, 60.6% longer than 2,000. The proposal does not say which spans it counted |

What the recount adds:

- **Six failed rows went to the judges, not five.** `tr-95996f3d…` (run `5ba51e5c`, T1) ended
  with the provider's error "Your credit balance is too low". It is an agent failure of another
  kind, and both judge calls for it failed too.
- **The 11 values that are not numbers are of four kinds.** 6 are judge calls refused for the
  credit balance (3 traces, both judges; value null, error set). 1 is "Request exceeds the
  maximum size". 1 is "Failed to parse response from judge model". 3 are text. The last five all
  sit on the five crashed rows. No finished row in the store holds a text value.
- **A stored mean shows the missing n.** Run `5ba51e5c` (`topic_agent`, T1, 20 traces) has
  `correctness_mean` 4.353. That is 74 / 17: three of the 20 rows are not in it.
- **Seven of 17 runs have no tag.** Six are `FAILED` and one is `RUNNING` since 2026-07-13
  (`43d5cc74`, 4 traces, one of them `IN_PROGRESS`). `_tag_eval_run` runs after `evaluate`
  returns, so a run that dies cannot be told from another. A run should get its tags when it
  opens.
- **Timing.** 83 finished evaluation traces: median 41.6 s, mean 44.5 s, maximum 115.4 s. Per
  agent run: 4.61 retrievals and 4.73 model calls (479 and 492 spans over 104 runs).

## 5. mlflow 3.14.0, read in `.venv/lib/python3.13/site-packages/mlflow/`

### 5.1 Which trace a judge value lands on

`genai/evaluation/harness.py:793-837` (`_run_predict`) has three cases:

1. `predict_fn` given: mlflow calls it and takes the trace it made.
2. The row has a `trace`: mlflow links that trace to the run (`link_traces_to_run`), or clones
   it when it belongs to another experiment (`_should_clone_trace`, `harness.py:1044`).
3. Neither: `create_minimal_trace` (`genai/utils/trace_utils.py:1011`) makes a new trace with
   one span, `root_span`.

The proposal's sketch is case 3. A row may carry `inputs`, `outputs`, `expectations`, `tags` and
`trace` together (`genai/evaluation/entities.py:125-174`). `outputs` from the row wins over the
trace's (`genai/evaluation/utils.py:245-252`). The `tags` column is written to the trace as
trace tags (`_run_score`, `harness.py:840-877`).

**Checked with a run, no model call, scratch store** (`trace_probe.py`, not kept):

| Data row | Trace the value is on | Spans | Trace tag |
|---|---|---|---|
| `inputs`, `outputs`, `expectations` | a new trace | `root_span` | none |
| the same plus `trace` and `tags` | the agent's own trace, linked to the run | all 3 of the stand-in agent | `ema.bench_id` set |

In both cases the scorer received the row's `outputs` with `context_passages`.

So the runner can make the predictions itself and still keep the judge values on the traces that
hold the agent's spans. Two points are **not** verified and need the one live run:

- The probe made its trace with `mlflow.start_span`. A real trace comes from
  `mlflow.llama_index.autolog()` inside the runner's loop.
- The trace must be written before `mlflow.get_trace` reads it. The probe called
  `mlflow.flush_trace_async_logging()`. mlflow's own `predict_fn` path turns async logging off
  for the same reason (`harness.py:806-810`).

`harness/llms.py:142-149` records an earlier case where a span never ended and the row's trace
was `None`. The runner needs a rule for a finished answer without a trace.

### 5.2 What mlflow sends for a judge on the `anthropic` route

- The judge is in standard mode. The trace and the tools are sent only when the instructions use
  `{{ trace }}` (`genai/judges/instructions_judge/__init__.py:616-641`). Ours use `inputs`,
  `outputs` and `expectations`.
- The request holds the messages, `max_tokens` 8192 (`gateway/constants.py:39`) and
  `output_config.format` with a JSON schema (`gateway/providers/anthropic.py`, the block after
  `tool_choice`). It holds no `temperature` unless `inference_params` is passed; this repository
  passes none. It holds no `tool_choice`.
- When the model answers 400 to the schema, the adapter retries without it
  (`genai/judges/adapters/gateway_adapter.py:610-624`).
- `base_url` is used as the endpoint verbatim (`gateway_adapter.py:546`).
  `_anthropic_judge_base_url` already appends `/v1/messages` (`harness/eval/judges.py:61-71`).

### 5.3 Other providers

`is_supported_provider` knows 24 names. The judge adapter builds a client for a subset
(`metrics/genai/model_utils.py:319-518`): `openai`, `azure`, `anthropic`, `bedrock`, `gemini`,
`mistral`, `togetherai`, `groq`, `deepseek`, `xai`, `openrouter`, `ollama`, `databricks`,
`vertex_ai`, and mlflow's own `gateway`. Any other name fails on the first judge call with
"Provider … is not supported for evaluation", not when the judge is built.

| `models.yaml` provider | mlflow name | Key | Endpoint |
|---|---|---|---|
| `anthropic` | `anthropic` | `ANTHROPIC_API_KEY` | default, or `base_url` |
| `together_ai` | `togetherai` | **`TOGETHERAI_API_KEY`**; this repository sets `TOGETHER_API_KEY` | default |
| `openai_compatible` | `openai` | **`OPENAI_API_KEY`**, required; the entry names its own variable in `api_key_env` | `OPENAI_API_BASE` or `OPENAI_BASE_URL`; or `base_url`, which then must end in `/chat/completions` |

None of `TOGETHER_API_KEY`, `TOGETHERAI_API_KEY`, `OPENAI_API_KEY` and `LOCAL_LLM_API_KEY` is set
on this machine. These routes stay tested up to the model URI, as the proposal says.

## 6. The crash

### 6.1 The stored stack trace

From the span `FunctionAgent.run` of `tr-97f5ef33…` (2026-07-13), innermost frames, paths
shortened to the package:

```
anthropic/_streaming.py:231     _iter_events
httpx/_models.py:1063           aiter_raw            await self.aclose()
httpx/_transports/default.py:276  aclose
httpcore/_async/connection_pool.py:420  aclose       await self._pool._close_connections(closing)
httpcore/_async/connection_pool.py:345  _close_connections
httpcore/_async/http11.py:258   aclose
anyio/_backends/_asyncio.py:1344  aclose             self._transport.close()
asyncio/selector_events.py:869  close                self._loop.call_soon(...)
asyncio/base_events.py:556      _check_closed
RuntimeError: Event loop is closed
```

The connection pool closes a connection whose transport belongs to a loop that `asyncio.run`
has already closed. That is the cause the proposal inferred.

### 6.2 Reproduced without a model call

`loop_probe.py` (scratch, not kept): one shared `httpx.AsyncClient`, a local HTTP/1.1 server
with keep-alive, a streamed response.

| Arrangement | Calls | `Event loop is closed` | Other errors |
|---|---|---|---|
| one `asyncio.run` per call, one after the other | 6 | 3 | 0 |
| one `asyncio.run` per call, 10 threads | 40 | 14 | 5 |
| one loop for all calls | 40 | 0 | 0 |

**The crash was not reproduced through the agent.** That costs model calls for two question
types, which is beyond a smoke run. With the stored trace and the probe agreeing, the live
reproduction is the owner's choice, not a need.

`AgentSession.run` (`harness/agents/session.py`) and `run_agent`
(`harness/agents/runner.py:109-117`) use one `asyncio.run` per call in the same way. They are
called once per process today. The runner must call `ainvoke`, not `invoke`.

## 7. The passage the agent reads

### 7.1 The leaf's text is gone before the tool sees the node

`HierarchicalPGRetriever` builds a node in three places: `_retrieve`, `_expand` and
`_expand_ancestors` (`harness/indexing/property_graph.py:717-721`, `770-773`, `840-843`). With
`merge: true` each takes `parent["text"]` and keeps the leaf's id as `matched_chunk`. The Cypher
already returns the leaf's text (`c.text`, `best.text`), so the fix is in Python only.

The parent is the direct `PARENT_OF` parent of the matched chunk. With
`chunk_sizes: [2048, 512, 128]` that is the middle level; the stored median of 2,130 characters
fits 512 tokens.

### 7.2 Who reads `format_nodes` and `passages_from_nodes`

| Function | Reader | Effect of the change |
|---|---|---|
| `format_nodes` | `ema_search` (`search.py:235`) | the agent reads about 5 times the text |
| `format_nodes` | `corrective_search` (`corrective_search.py:105`, `119`, `131`) | the grader model reads the longer text too, on each cycle |
| `format_nodes` | `harness/export/chain_from_trace.py:37-41` parses the output by line (`_NODE_LINE`, `_NOTE_LINE`) | the passage body must stay on one line, as it is today |
| `passages_from_nodes` | `workflow_adapter.py:96`, then the inline judge in `app.py:742-750` | the inline judge reads the same text as the agent |
| `passages_from_nodes` | `harness/eval/predict.py:66` | the offline faithfulness judge |
| `context_passages` | `harness/eval/bootstrap.py:60` | the scaffolded bootstrap metric |

`passages_from_nodes` returns `node.text` in full (`search.py:76-87`). With a limit of 2,000
characters, 60.6% of the stored passages are still cut for the agent. The judge reads the same
text only when `context_passages` is built from what the tool rendered.

`topic_context` renders each chunk in full under a token budget (`topic_context.py:229-254`).
It needs no change.

Citation attribution keeps the full text (`workflow_adapter.py:100-108`). The proposal leaves it
alone.

### 7.3 Where the limit lives is not decided

The proposal says "a limit set in the tool's config". No tool has a config file:
`harness/configs/` has no `tools/` folder, and a tool gets its arguments from `assemble_agent`
(`harness/agents/session.py:59-70`). Section 11, question 2.

## 8. Real calls made on 2026-11-23

`ANTHROPIC_BASE_URL` is set on this machine, so requests go through a gateway.

### 8.1 Decision E: the judge model

- `GET /v1/models` (no cost): 15 model ids, among them `claude-opus-5-5`, and the three of
  `models.yaml`.
- Two judge calls through `build_judge("faithfulness", …, model="anthropic:/claude-opus-5-5")`
  with a context of one sentence. With `feedback_value_type=int`: value `5`, type `int`.
  Without it: value `'5'`, type `str`. Neither wrote to a store.

The model is served and mlflow's request is accepted. The condition of decision E is met.

### 8.2 The second reader of `roles.judge`

`harness/judge.py:71` builds its model with `harness.llms.get_llm(model_role)`. That path sends
`temperature: 0.0`. One real call with `claude-opus-5-5` on that path:

```
400 invalid_request_error: `temperature` is deprecated for this model.
```

`_NO_TEMPERATURE_PREFIXES` (`harness/llms.py:118`) holds `claude-sonnet-5`, `claude-fable-5` and
`claude-mythos-5`. It does not hold `claude-opus-5`. `run_inline_judges` swallows a judge error
and logs a warning (`harness/eval/inline_judge.py:104-105`). After the rebinding, the recipe
`agentic_judged` (`judge.model_role: judge`) would lose its inline judge with no visible sign.

`harness/models.py:152-178` (`_call_anthropic`) sends no `temperature` and is not affected.

## 9. Files the work would touch

| File | Why | Tests today |
|---|---|---|
| `harness/eval/runner.py` | prediction loop, `bench_id`, failed rows, n, tags, metrics, `setup_tracing` | `tests/test_eval_runner.py` (9 tests). `test_to_eval_data_shape`, `test_summarize_renders_per_type_metrics` and `test_mean_scores_averages_numeric_and_skips_non_numeric` assert today's behaviour and change |
| `harness/eval/predict.py` | an async prediction that returns `ok`, the error and the trace | `tests/test_eval_predict.py` (4 tests) |
| `harness/eval/evaluate.py` | `predict_fn` becomes optional | none of its own |
| `harness/eval/judges.py` | `feedback_value_type=int`, provider mapping | `tests/test_eval_judges.py` (4 tests) |
| `scripts/run_eval.py` | `--judge`, the summary | none |
| `harness/configs/models.yaml` | the entry for `claude-opus-5-5`, bound to `judge` | `tests/test_models.py`; `test_judge_role_is_opus` still passes |
| `harness/tools/search.py` | leaf first, the limit, `passages_from_nodes` | `tests/test_tools.py` (4 tests on `format_nodes`), `tests/test_tools_corrective.py` |
| **`harness/indexing/property_graph.py`** | carry the leaf's text; not in the proposal | `tests/test_indexing_property_graph.py`, `tests/test_retrieval_steering.py` |
| **`harness/llms.py`** | the prefix `claude-opus-5`; not in the proposal | `tests/test_llms.py` |
| `docs/RETRIEVAL.md`, `docs/ARCHITECTURE.md` | the reset call | — |
| **`docs/RUNTIME_VERIFICATION.md`** | line 86, the third mention; not in the proposal | — |
| `docs/tools/ema_search.md` | what the agent reads; its "Output format" section shows the old shape | — |
| `docs/eval/2026-07-13_topic_subgraphs.md`, `docs/eval/2026-07-20_tree_seeding.md` | one note each | — |

`grep -rn "reset=True" docs/` finds 8 lines today. Three are the calls above. Five describe the
problem: the review (`:594`), `PLANNING_WORKFLOW.md:71` and the proposal (3 lines).
`CLAUDE.md:240` is a ninth, outside `docs/`. The proposal's check has to say which lines may
remain.

## 10. What the work has to preserve

### 10.1 Source, derived and authored data

| Place | Kind | This work |
|---|---|---|
| Scrapy cache, Mongo `web_items` | source | not read, not written |
| `parsed_documents`, `document_metadata`, the Neo4j graph | derived | the graph is read by the one live run; nothing is written |
| `benchmark/*.jsonl`, recipes, prompts, hub and routing YAML | authored | read only. `harness/judges/*.md` stays as it is; the real call shows `feedback_value_type=int` works with the present prompt |
| `harness/configs/models.yaml` | authored | one entry and one binding, edited by hand in a commit |
| `mlflow.db` | the record of every metric | the live run appends runs, traces, tags and metrics. The 17 runs and 114 traces of today are not changed |

### 10.2 The live graph

No delete, no rebuild, no re-embed. The docs change removes a snippet that deletes all of it.

### 10.3 Comparable numbers

The work changes the runner, the judge model, the type of a judge value, and the text every
agent reads from `ema_search` and `corrective_search`. These stop being comparable with any
later number:

- the T1 to T4 tables of `docs/eval/2026-07-13_topic_subgraphs.md`,
- the measurements of `docs/eval/2026-07-20_tree_seeding.md`,
- the 10 tagged and finished runs in `mlflow.db` (`naive_rag`, `topic_agent`, `steered_agent`,
  `tree_agent`).

Decision D says none is repeated now. The two pages get their note.

The same change reaches the live app: longer tool results, and an inline judge that reads the
rendered passages.

**Can the system under test read a gold answer?** No. The agent receives `question` only. The
gold answer goes to the judges as `expectations`. `ema.bench_id` is a tag, not an input. No
index is built. The runner does not write the few-shot cache; it must stay so.

### 10.4 Cost

Spent by this exploration: 3 model calls of a few hundred tokens each (2 judge calls, 1 refused
completion) and 1 free listing.

The proposal's live check, `--recipe naive_rag --limit 1`:

- items × repeats × arms = 4 × 1 × 1 = 4 questions (one per type T1 to T4),
- per question: 1 agent run of about 4.7 model calls, and 2 judge calls,
- so about 19 generator calls and 8 judge calls.

**4 items is one more than the smoke limit of 3.**

Tokens per question after the change, as arithmetic and not as a bill:

- one search result: 10 passages × 2,000 characters = 20,000 characters, about 5,000 tokens.
  Today: 10 × 400 = 4,000 characters, about 1,000 tokens.
- An agent sends earlier tool results again on each later step. With 5 retrievals the added
  input is 4,000 × (5 + 4 + 3 + 2 + 1) = 60,000 tokens per question, before any caching. The
  measured mean is 4.61 retrievals.
- The faithfulness judge already reads the full passages: about 4.61 × 10 × 2,130 characters,
  about 24,500 tokens per question. This does not grow.

No price is written here. The decision note that asks for the run looks it up.

Wall time: the predictions run one after the other. 45 items × 44.5 s is about 33 minutes per
recipe for the agent runs. Today 10 run at once.

GPU: query embeddings only.

### 10.5 Scope

No new layer. The work repairs the evaluation that every later rung reports through. It is
inside Phase 3.

### 10.6 The public repository

This file names no endpoint address, no organisation and no person. Model ids are the public
ones.

### 10.7 What it assumes that is not decided

Section 11.

## 11. Open questions

The proposal says a question from `/explore` becomes a note under `docs/pm/decisions/`. This
command writes nothing there. `/plan` turns each of these into a note or a task.

1. **Answered by the owner on 2026-11-23: the working tree.** `develop` held the uncommitted
   workflow adoption of 2026-11-23, and this proposal was one of its untracked files. The owner
   chose to commit it on `develop` first (`a1c587c`) and to branch from that commit.
2. **For the owner: where the passage limit lives.** Options: (a) a key in the `retrieval`
   block of the index profile, beside `k` and `merge`; (b) a key of the recipe; (c) a new
   `harness/configs/tools/ema_search.yaml`. The assistant recommends (a): the profile already
   decides whether a parent exists, `build_recipe` already reads it, and one profile then gives
   one passage shape to every recipe on it. (b) lets two recipes on one index read different
   text, which makes their numbers harder to compare.
3. **For the owner: the live check.** Run it as written with 4 questions, or with
   `--types T1 T2 T3` and 3?
4. **For `/plan`, the assistant's call unless overruled:** use the `trace` column (section 5.1)
   instead of the proposal's sketch; add `harness/indexing/property_graph.py`,
   `harness/llms.py` and `docs/RUNTIME_VERIFICATION.md` to the files; tag a run when it opens.
5. **For `/plan`: a finished answer without a trace.** Judge it on a minimal trace, or count it
   as failed? The assistant recommends judging it and printing the count, since the answer
   exists.
6. **Noted, not asked:** at 2,000 characters, 60.6% of the stored parents are cut. A limit of
   3,400 would cut none (maximum 3,330). The decision fixes about 2,000 as the default and makes
   it a setting.

## 12. What could go wrong

- The runner's own trace handling is the least tested part: trace id, flush, link. One live run
  decides it. A test with stand-ins proves only the call shape (`PLANNING_WORKFLOW.md`, rule 10).
- `evaluate` reads `df.iloc[0]`. A question type in which every row failed gives it no rows. The
  runner has to log that run itself and skip the call.
- With `setup_tracing`, the root span of an evaluation trace becomes
  `AgentWorkflowAdapter.invoke`, as in the app. Anything that looks for `FunctionAgent.run` as
  the root has to cope.
- The leaf's text in node metadata makes each retriever span larger, by about 500 characters per
  node.
- The repeated leaf: the parent's text contains the leaf's. "Leaf first, then the parent" needs
  a rule for the overlap.
- Three existing runner tests assert the old output and will fail by design.

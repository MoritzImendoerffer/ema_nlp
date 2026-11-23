# Evaluation that can be trusted: failed runs counted, the judge as a setting, the passage the agent read

**Status:** proposed 2026-11-23 · backlog row 9 · no work unit yet.

The owner decided its five questions, A to E, on 2026-11-23. They are listed under
"Decided by the owner" below.

Written by Claude (Fable 5.2) from the review of 2026-11-23
([`../eval/2026-11-23_pkr_testbed_review.md`](../eval/2026-11-23_pkr_testbed_review.md),
section 4). It is step 0 of the rehearsal order: every later item reports numbers through
`scripts/run_eval.py`.

## The problem

Seven defects, each read in the code. The first two were also counted in the 114 traces of
`mlflow.db`.

1. **A run that crashed is judged as an answer.** Five evaluation traces ended with
   `RuntimeError: Event loop is closed`. `AgentWorkflowAdapter.invoke`
   (`harness/agents/workflow_adapter.py:124`) calls `asyncio.run` once per question.
   `mlflow.genai.evaluate` runs `predict_fn` in a thread pool
   (`MLFLOW_GENAI_EVAL_MAX_WORKERS`, default 10, mlflow 3.14.0) over one shared agent. The
   likely cause is the shared async client outliving the loop it was made on; this is read from
   the stack traces and was not reproduced. The judges scored those rows: one has correctness 5
   and faithfulness 1, one has correctness 5 and the faithfulness value `" agent errored"`.
2. **The mean drops what is not a number, and prints no n.** `mean_scores`
   (`harness/eval/runner.py:90`) skips a value that `float()` rejects. 7 of 85 stored
   faithfulness values and 4 of 85 correctness values are text or null. `summarize`
   (`harness/eval/runner.py:204`) prints one mean per judge and question type, with no count
   behind it. The T3 and T4 means in
   [`../eval/2026-07-13_topic_subgraphs.md`](../eval/2026-07-13_topic_subgraphs.md) include
   such rows.
3. **A failed row has no name.** `to_eval_data` (`harness/eval/runner.py:62`) keeps the
   question and the gold answer and drops `bench_id`. A trace cannot be matched to its item
   without comparing question texts.
4. **The judge is the generator's model, and a run does not say which model judged it.**
   `harness/configs/models.yaml` binds the role `judge` to `claude_opus`, and all ten recipes
   generate with `claude_opus`. `judge_model_uri` (`harness/eval/judges.py:101`) raises for
   every provider other than `anthropic`. `scripts/run_eval.py` has the option `--model` for
   the generator and none for the judge. A run carries three tags, `ema.recipe`,
   `ema.benchmark` and `ema.question_type` (`harness/eval/runner.py:195`), and neither model.
5. **The judge reads text that the agent did not.** `harness/tools/search.py:116` cuts each
   passage to `_SNIPPET_MAX = 400` characters before the agent reads it. With `merge: true`
   that passage is the parent chunk, so the agent reads the parent's first 400 characters, not
   the leaf that matched. The faithfulness judge receives the full passage. The reviewer
   measured a median passage of 2,112 characters in the stored traces.
6. **The runner records no configuration, and runs fewer layers than a recipe declares.**
   `setup_tracing` is called by `app.py` and `scripts/run_agent_demo.py` only, so a trace of
   an evaluation carries no resolved recipe. The few-shot layer and the inline judge run in
   `app.py` only: under the runner, `regulatory_fewshot` and `agentic_judged` behave exactly
   like `regulatory_agent`, and nothing says so.
7. **Two pages show a call that deletes the live graph.** `docs/RETRIEVAL.md:228` and
   `docs/ARCHITECTURE.md:210` show `build_index(profile, reset=True)` as the way to build and
   verify. `reset` runs `MATCH (n) DETACH DELETE n`, and the default profile is the full
   corpus (`limit: null` in `harness/configs/index/neo4j_hier.yaml:20`).

## The idea

The runner makes the predictions itself, one question after the other on one event loop, and
records for each item whether the agent finished. It gives the judges only the rows that
finished, as `inputs`, `outputs` and `expectations` (the second form of `data` that
`mlflow.genai.evaluate` of mlflow 3.14.0 accepts, with `predict_fn=None`). Its summary then
prints, per question type, the number of items, the failed ones by id, the judge values that
were not numbers, and the means. A failed item is left out of the mean (decision A below).

The judge model is a setting (decision B below). `roles.judge` in
`harness/configs/models.yaml` names it, an option of `scripts/run_eval.py` overrides it for
one run, and every run records the model id of the generator and of the judge. The default
judge is a model that no recipe generates with.

The agent reads the text that is judged: the matched leaf first, then its parent up to a
limit that is a setting of the tool (decision C below).

## What it deliberately does not do

- **No repeats, no resume, no new metric.** Three repeats, must-have facts and abstention come
  with the nine-class benchmark (backlog row 15). This item makes one run honest.
- **It does not move the few-shot layer and the inline judge out of `app.py`.** The runner says
  which declared layers it does not run. Moving them is its own item.
- **It does not change citation attribution**, which works by URL (review, section 4, item 6).
- **It does not repeat an earlier evaluation** (decision D below). It marks the two earlier
  pages with how their numbers were made.
- **It sets no request timeout and no step limit.** That is in backlog row 7.

## Implementation sketch

| Part | Files | Size |
|---|---|---|
| A prediction loop owned by the runner: one `asyncio.run` around all questions, each question in `try`/`except`, a result per item with `bench_id`, `ok`, the error text, the answer and the passages | `harness/eval/runner.py`, `harness/eval/predict.py` | M |
| `to_eval_data` carries `bench_id`; each trace gets the tag `ema.bench_id` | `harness/eval/runner.py` | S |
| The judges receive finished rows only; a failed row is logged to the run with its error and gets no judge call | `harness/eval/runner.py`, `harness/eval/evaluate.py` | S |
| Judges return a number: `make_judge(..., feedback_value_type=int)`; a value that still is not a number is counted and printed | `harness/eval/judges.py` | S |
| `summarize` prints `n`, `failed` with ids, `judge_invalid`, then the means; the same numbers go to the run as metrics | `harness/eval/runner.py` | S |
| The judge is a setting: `judge_model_uri` maps each provider of `models.yaml` to mlflow's name for it (`anthropic`; `together_ai` to `togetherai`; `openai_compatible` to `openai` with the entry's `api_base`) and raises only for a provider that mlflow cannot serve | `harness/eval/judges.py` | S |
| `scripts/run_eval.py --judge <model key>` overrides `roles.judge` for one run, as `--model` does for the generator | `scripts/run_eval.py`, `harness/eval/runner.py` | S |
| Each run carries the tags `ema.generator_model` and `ema.judge_model` (the model ids). The summary prints both, and one warning line when the two ids are equal | `harness/eval/runner.py` | S |
| A new entry for `claude-opus-5-5`, bound to `judge` | `harness/configs/models.yaml` | S, after the real call that decision E asks for |
| The two earlier pages get one note each: their numbers were made with the 400-character cut, with the generator's model as judge, and with means that print no n | `docs/eval/2026-07-13_topic_subgraphs.md`, `docs/eval/2026-07-20_tree_seeding.md` | S |
| `ema_search` returns the passage that is judged: the matched leaf first, then its parent up to a limit set in the tool's config | `harness/tools/search.py` | S |
| The runner calls `setup_tracing`, stamps the resolved recipe on the run, and prints one line for each declared layer it does not run | `harness/eval/runner.py`, `scripts/run_eval.py` | S |
| The two pages show `open_index(profile)`; the call with `reset=True` moves into a block that says what it deletes | `docs/RETRIEVAL.md`, `docs/ARCHITECTURE.md` | S |
| The tool page says what the agent reads | `docs/tools/ema_search.md` | S |

Stored shapes: no collection and no graph property changes. The trace tag `ema.bench_id`, the
run tags `ema.generator_model` and `ema.judge_model`, and the run metrics `n`, `failed` and
`judge_invalid` are new; runs made before this item do not have them.

## Verification

- A test in which the agent raises on the second of three questions: the summary prints
  `n=3 failed=1` and the item's id, the judges are called twice, and the mean is over two rows.
- A test in which a judge returns `" agent errored"`: `judge_invalid=1`, and the value is not
  in the mean.
- A test that `ema_search` returns the matched leaf's text inside what the agent reads, for a
  leaf that starts after character 400 of its parent.
- A test that `judge_model_uri` returns `anthropic:/<id>` for a Claude entry and
  `togetherai:/<id>` for the entry `olmo_32b`, and that it raises for a provider name that is
  in neither `models.yaml` nor mlflow.
- A test that `--judge claude_sonnet` reaches the judges as that entry's model, that the run
  is tagged with both model ids, and that the summary prints the warning line when the judge
  and the generator have the same id.
- `python scripts/run_eval.py --recipe naive_rag --limit 1` on the live graph ends with no
  `Event loop is closed` in its output, each of its traces carries `ema.bench_id` and the
  recipe's name, and each of its runs carries `ema.generator_model` and `ema.judge_model`.
  This run pays for about 4 questions and 8 judge calls.
- Not verified by this item: a judge call to a provider other than `anthropic`. No key for
  one exists on 2026-11-23, so that route is tested up to the model URI, and its first real
  call is made when a key exists.
- `grep -rn "reset=True" docs/` finds the call only inside a block that names the deletion.
- `make test` and `make lint` pass.

## Decided by the owner on 2026-11-23

All five are also in [`DECISIONS.md`](../../DECISIONS.md), under "Evaluation design".

- **A. A failed row is listed and left out of the mean,** with the count printed beside every
  mean. This was the assistant's recommendation, and the owner accepted it. The alternative
  was to count a failed row as the lowest score. A crash of the harness is not a wrong answer;
  a mean that hides how many rows it covers is the defect to end. A system that times out
  often then shows as `failed=7 of 45`, which no reader can miss.
- **B. The judge model is a setting.** The owner: "it should be possible to configure the
  model judge". The models at hand on this date are Claude's. What follows from it:
  - The judge is named in configuration and can be changed for one run without an edit to a
    tracked file. Every run records which model generated and which model judged.
  - A judge of another family than the generator is not available today. The judge is another
    Claude model than the generator's, and every `docs/eval/` page that reports a judged
    number says that both models are of one family.
  - Another provider is a change of `models.yaml` once a key for it exists. mlflow 3.14.0
    serves a judge for the providers of its gateway registry, among them `anthropic`,
    `openai`, `togetherai`, `mistral`, `gemini` and `ollama`
    (`mlflow.gateway.provider_registry.is_supported_provider`, asked on 2026-11-23). The
    names `together_ai` and `openai_compatible` of `models.yaml` are not among them, so
    `judge_model_uri` has to translate them. `litellm` is not installed in `.venv`.
  - The assistant's reading, not the owner's words: two numbers are compared only when the
    same judge model produced them. A changed judge starts a new series.
- **C. The agent reads the matched leaf and its parent up to about 2,000 characters,** with
  the limit in the tool's configuration. This was the assistant's recommendation. The judge
  and the agent then read the same text, and a search result costs about five times the
  tokens of today. The alternative was the matched leaf only, about 128 tokens. The retriever
  merges to parents because a leaf alone often lacks its context.
- **D. No earlier number is repeated now.** This was the assistant's recommendation. The T1
  to T4 tables of 2026-07-13 and the seeding measurements of 2026-07-20 were made with the
  400-character cut and with the generator's model as judge. The corpus repair (backlog
  row 11) changes the index, and a repeat before it would be repeated again. The question is
  asked again when row 11 has shipped. Until then the two pages carry a note that says how
  their numbers were made; the note is the assistant's addition.
- **E. `judge` is bound to a new entry for `claude-opus-5-5`,** once one real judge call
  through the configured endpoint has shown that the model is served and that mlflow's
  request is accepted. This was the assistant's recommendation. `models.yaml` lists three
  Claude models on this date: `claude-haiku-4-5-20251001`, `claude-sonnet-5` and
  `claude-opus-4-7`, and all ten recipes generate with the third. The alternatives were
  `claude_sonnet`, which is cheaper and less capable than the generator, and no change. A
  judge that is weaker than the generator can mark a correct answer down because it does not
  follow it. The binding stays fixed for a series of runs. If the call is refused, the
  question is open again, as a note under `docs/pm/decisions/`.

## Open questions

None on 2026-11-23. A question that comes up during `/explore` becomes a note under
`docs/pm/decisions/`.

## For the implementing session

- Reproduce the crash before fixing it: run two question types back to back with the code as
  it is, and keep the stack trace in `exploration.md`. If it does not reproduce, say so; the
  cause above is an inference.
- Check in mlflow 3.14.0 that `evaluate` with `outputs` in `data` and no `predict_fn` links
  each judge value to a trace that still holds the agent's spans. If it does not, the runner
  keeps `predict_fn` and makes it safe instead: one worker (`MLFLOW_GENAI_EVAL_MAX_WORKERS=1`)
  and one long-lived event loop. Decide on what the installed version does, and write down the
  file you read.
- `feedback_value_type` is a parameter of `make_judge` in mlflow 3.14.0
  (`mlflow/genai/judges/make_judge.py:118`). Check which types the Anthropic route accepts.
- Before a model entry is added to `models.yaml`, ask the configured endpoint which model ids
  it serves (`GET /v1/models`; the call costs nothing). When `ANTHROPIC_BASE_URL` is set,
  requests go through a gateway, and a gateway can serve fewer models than the API. Write no
  model id from memory.
- Make one real judge call with a model before `judge` is bound to it. Anthropic's migration
  notes say that the current Claude models reject request fields that older ones accepted,
  among them a `temperature` other than the default and a forced `tool_choice`. mlflow builds
  the judge's request (`mlflow/genai/judges/adapters/gateway_adapter.py`), so read what it
  sends, and keep the error text in `exploration.md` if the call is refused.
- For the provider `openai_compatible`, check how mlflow's `openai` provider gets its key and
  its base URL. `models.yaml` names the key's variable per entry (`api_key_env`), and
  `build_judge` passes `base_url` on to `make_judge` already.
- The tests of the runner are offline. Keep them so: the agent and the judges are stand-ins,
  and one live run of 4 questions is the check that the stand-ins match.

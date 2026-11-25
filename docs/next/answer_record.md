# An answer record: a claim names its passage, and the checks produce numbers

**Status:** proposed 2026-11-25 · backlog row 18 · no work unit yet (unit 27 is open) ·
written after an adversarial review
([`../eval/2026-11-25_direction_review.md`](../eval/2026-11-25_direction_review.md)).
Every file and line below comes from a code review of 2026-11-25 at commit `47d2cfa` and
must be checked again by `/explore`.

## The problem

The owner wants answers that a person can confirm quickly, and reasoning that a test can
partly verify (direction review, section 1). The first thing a test or a person needs is
the text a claim rests on. Today that text cannot be named, and what is checked is not
counted.

1. **A claim cites a URL, not a passage.** The model fills `source_url`. The runner then
   copies the chunk id and the quote from the top-scoring chunk of that URL
   (`harness/agents/runner.py:77-79` chooses it, lines 59-61 apply it). In the stored answers, 251 of 351 claims (72%) cite
   at least one URL that returned several passages. The quote shown beside such a claim is
   the best-scoring passage of the document, not the one the claim came from.
2. **The agent cannot name a passage if it wanted to.** A search result starts with
   `[i] source=… category=… score=…` (`harness/tools/search.py:160-163`). The number `i`
   restarts with every call, and 67 of 93 stored answers made several calls.
3. **The checks that exist produce no number.** `harness/attribution.py` locates a claim in
   the answer and a quote in a passage. The result goes to the chat view and to an export.
   It is not stored, and the evaluation runner does not run it.
4. **A lost answer is not counted.** When the structured output fails, the library logs a
   warning (`llama_index/core/agent/workflow/base_agent.py:600-604`, llama-index-core
   0.14.22) and the runner returns plain text (`harness/agents/runner.py:49`). Between 13
   and 15 finished runs in the store carry no claims, and no metric says so. A second way
   to lose claims was found on 2026-11-25 (see "What was tested"): an output that is cut at
   the token limit after the `answer` field validates as an answer with no claims, and is
   reported as a success.
5. **A stored chunk id will stop meaning anything.** A chunk id is the hash of the document
   id and the chunk's position (`harness/indexing/chunking.py:84`). Backlog row 10 replaces
   a changed document's chunks. After that, an id in an old trace can point at other text.

## The idea

Give every passage that the agent receives a short tag. Ask the model to cite the tag and a
verbatim quote for each claim. Write one record per answer, at the one place that both the
chat app and the evaluation runner pass through. A cached answer in the chat app is the
one exception, and open question 5 covers it. The record holds the passages as the agent
saw them, the claims with tag and quote, and the outcome of four checks done by plain code.
The runner prints those outcomes per question type, beside the judge scores, together with
the number of answers that came back without a structure or without claims.

## What it deliberately does not do

- **It does not decide which claims a person may skip.** Version 0 reports check outcomes.
  It marks no claim as settled. The direction review explains why (section 5): a claim that
  matches its source by word overlap can still negate it.
- **No derivation types.** No list of claim kinds, no fixed vocabulary, no validator in the
  output class. In a sample of 60 stored claims, none computed anything.
- **No re-keying of citations.** Fields are added with defaults. Nothing is renamed, and a
  stored trace of today still validates.
- **No change to the review panel**, and no view that hides claims.
- **No fault-injection measurement.** A test may corrupt a record to prove that a check
  fires. That is a unit test, and no number from it is reported as a result.
- **No model that verifies a claim.** That is rung E9. This row is what E9 needs first.
- **No new retrieval strategy and no change to the graph.**

## Implementation sketch

Size: M. The code reviewer's smallest version is one session; tests, the baseline page and
the smoke run make it a few.

| # | Change | Where |
|---|---|---|
| 1 | **Passage tags.** Each result header gains ` id=<tag>`. A tag is short (`p1`, `p2`, …), counted across all tool calls of one run, so it is unique within the run. The same passage shown twice keeps its tag | `harness/tools/search.py:160-163`, `harness/tools/corrective_search.py`, `harness/tools/topic_context.py:245`. The trace parser already accepts extra `key=value` pairs (`harness/export/chain_from_trace.py:37`) |
| 2 | **The contract.** A citation carries the tag and a verbatim quote of at most 240 characters. The prompt of each recipe states it | `harness/schemas/answer.py` (`Citation`), the prompt files named by `harness/configs/recipes/*.yaml` |
| 3 | **Resolution.** The runner resolves a tag to the passage before it falls back to the URL. An unknown tag stays unresolved and is counted | `harness/agents/runner.py:52-64` |
| 4 | **Four checks, as pure functions with tests.** Each reports one outcome per claim. (a) Is the claim located in the answer? Exact, near, missing. (b) Is the quote located in the text shown for the tagged passage? Exact after lower-casing and collapsing whitespace, near, missing, no quote. (c) Does the tag name a passage received in this run? Yes, no, no tag. (d) Do the numbers of the claim occur in its quotes? All, some, none, no number. One share is reported besides: the part of the answer text that lies inside a claim | `harness/attribution.py` already has (a) at line 164 and the core of (b) at line 208 |
| 5 | **The record.** One JSON line per answer, in five parts. The run: question, item id when the runner supplies one, recipe, index profile, models, trace id. The answer, and whether it has a structured output and claims. The passages: tag, chunk id, document id, URL, retrieval origin, score and **the text as shown to the agent**. The claims with their citations and check outcomes. The counts. A child span on the trace carries the counts as well | Written from `AgentWorkflowAdapter.ainvoke` (`harness/agents/workflow_adapter.py:81-135`), which both `app.py:718` and `harness/eval/predict.py:127` call. The record stays out of the root span's outputs, because the judges read that whole dictionary (`harness/eval/judges.py:35-36`). MLflow 3.14.0 offers no artifact per trace, hence a span and a file |
| 6 | **The runner's numbers.** Per question type: answers, answers without a structure, answers without claims, claims, and the share of claims per outcome of each check, with n. Logged as MLflow metrics beside the judge means | `harness/eval/runner.py:241` |
| 7 | **A baseline page.** Check (a) and the coverage share run over the stored answers with the committed functions, and replace the first and the last count of the direction review, section 3.1. Checks (b) to (d) cannot run there: a stored answer holds no tag and no quote. Their first numbers come from the smoke run below | `docs/eval/` |

## Verification

- **Tests.** One per outcome of each check, on fixed strings. One that a record line holds
  the passage text. One that an answer without a structured output yields a record with
  `structured: false`. One, in a fresh interpreter, that the record is written on the first
  call of a process (planning workflow, rule 13).
- **Offline, no model call.** Check (a) over the 351 stored claims reports 22 missing with
  the repository's matcher, as counted on 2026-11-25. A different number means the function
  or the count is wrong, and the page says which.
- **Reachability.** `grep` shows the record writer called on the path of `app.py` and on
  the path of `scripts/run_eval.py`, not only from tests (planning workflow, rules 1
  and 2).
- **A smoke run of 3 items** with `naive_rag`: three record lines; every claim has a tag or
  is counted as having none; the page reports the share of exact quotes, the answers
  without a structure, and the number of model calls that stopped at the output limit.
- **What would stop the row.** If the model fills tag and quote for fewer than half of the
  claims in the smoke run, or if an answer is lost that was not lost before, the contract is
  wrong for this output path. Report it and take open question 2 before anything else.

## What was tested on 2026-11-25

A second session read the installed libraries and made 3 single model calls with
`claude-opus-4-7` from a scratch script, about 0.09 dollars. It changed no file. Versions:
anthropic 0.105.2, llama-index-llms-anthropic 0.11.5, llama-index-core 0.14.22. The API
documentation on citations and on search results was read on the same day.

| Question | Result |
|---|---|
| Can a tool return passages that the API cites? | Yes. Passages returned as `search_result` blocks inside a tool result, with citations switched on, come back as citation objects on the text blocks of a plain-text answer. Each carries the source (the tag given to the passage), the block indices and `cited_text` |
| How fine is the pointer? | One content block. In the test, `cited_text` was the whole passage block of 363 characters. A passage split into one block per sentence gives a pointer per sentence |
| Do citations survive the structured output? | No. With the answer forced through the `RegulatoryAnswer` tool, the reply held no citation object. The model imitated a citation tag inside the answer string and wrote its own quotes. With the other output mode (`output_config.format`) the documentation states an error: citations and structured outputs are incompatible |
| Do they survive the agent's output step today? | No. That step is a second model call over the conversation flattened to text (`llama_index/core/agent/utils.py:35-42`). For `claude-opus-4-7` it is a forced tool call (`llama_index/llms/anthropic/base.py:1121-1127`, `:959-968`) |
| What would the output step have to be? | The tools return citable blocks (`CitableBlock`, `llama_index/core/base/llms/types.py:1025`; sent as `search_result` by `llama_index/llms/anthropic/utils.py:254-264`). The agent runs without an output class, so there is no second call. The claims are built from the cited text blocks, which the adapter already places in the reply (`base.py:411-420`). **Not tested through the `FunctionAgent`** |
| What happens when the structured output is cut at the token limit (4,096, `harness/configs/models.yaml:31`)? | The adapter does not read the stop reason on the tool path. A cut after the `answer` field gives a partial object, which `RegulatoryAnswer` accepts because claims, citations and caveats default to empty lists: an answer without claims, reported as a success, with no warning and no retry. One of the three test calls ended this way. A cut before `answer` is complete raises, and the runner returns plain text. The stop reason is only on the trace's LLM span |
| Are the proposal's file and line references still right? | Yes at `c2fbfea`, after two corrections that are applied above |

One statement of that session was not checked by anyone else and matters for the choice:
by an API reference cached on 2026-11-03, a forced tool choice returns an error on the
newer models (Opus 5.5, Sonnet 5.5). If that holds, the output step of today stops working
when the generator is upgraded, whatever this row decides. `/explore` checks it against the
current documentation.

**Consequences for the sketch.** Step 5 stores the stop reason of the output call in the
record, and step 6 counts answers that were cut at the limit. If option (b) of question 2
holds, steps 1 to 3 change shape: the tag is the `source` of a citable block, the quote is
`cited_text`, and check (b) of step 4 passes by construction and remains as a test of the
code. The record, the counts and the runner's numbers stay as sketched.

## Open questions

| | Question | Options | Recommendation |
|---|---|---|---|
| 1 | Where does the model write the tag? | (a) in the existing `Citation.chunk_id`, which the system then overwrites with the real id; (b) in a new optional field `passage` | (b). `chunk_id` is read by the chat view and the export as a system id. One field with two meanings is how item 1 of the problem arose |
| 2 | Who produces the quote, and through which output step? | (a) the model writes tag and quote into the structured output, as sketched above; (b) the tools return their passages as citable blocks, the agent answers in plain text with the Claude API's citations switched on, and the claims are built from the cited text blocks | **Changed by the test of 2026-11-25:** try (b) first, with one run through the `FunctionAgent`, and fall back to (a) if it does not hold. With (b) the pointer and the quote are valid by construction, the second model call disappears, and the claim is a piece of the answer by construction. (b) works only on a plain-text answer, so `confidence` and `caveats` need another place. See "What was tested" |
| 3 | Against which text is a quote checked? | (a) the window shown to the agent, about 2,000 characters; (b) the whole chunk | (a). It is the text the agent read (`DECISIONS.md`, "The agent reads the passage that is judged") |
| 4 | Where do the record files live? | (a) `config.RESULTS_DIR/records/`, one file per evaluation run and one per day for the chat app; (b) MLflow only | (a), with the span of step 5 as the link from the trace |
| 5 | What does a cached answer in the chat app write? It bypasses the adapter (`app.py:643-700`) | (a) nothing; (b) a line with `cached: true` and no checks | (b). An answer that reached a user and left no record is the defect this row removes |
| 6 | Do quotes exceed the output limit of 4,096 tokens? | Measure in the smoke run | The longest stored answer has 6,963 characters. Cap a quote at 240 characters and count the stops |

Not a question for this row, and named so that nobody assumes it: whether the contract
lowers answer quality. Three items cannot show that. The first full run with the contract
compares the judge means with the runs before it, and needs the owner's yes because it
pays for model calls.

## For the implementing session

- Check every file and line above. They were read at `47d2cfa`, and unit 27 is changing
  the tree.
- Check the library behaviour against the installed versions before relying on it: the
  structured output is a second model call (`llama_index/core/agent/utils.py:35-42`), and a
  `Literal` field raises for the whole answer on one wrong value
  (`llama_index/core/program/function_program.py:55`). Name the version and the file you
  read.
- Keep the five rules of the direction review, section 6.1. The one most easily broken:
  no outcome of a check is called "verified" or "settled".
- `public/elements/` is in `.gitignore`. Do not change the review panel in this row.
- Model calls: the smoke run of 3 items and nothing beyond it.

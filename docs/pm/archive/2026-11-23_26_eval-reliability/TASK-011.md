---
type: pm-task
epic: 2026-11-23_26_eval-reliability
sprint: 2026-11-23_26_eval-reliability
task: TASK-011
status: done
kind: mechanism
title: "Render a search result as the matched leaf first, then its parent, up to a limit, and give the judge the same text"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_26_eval-reliability/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-011 — Render a search result as the matched leaf first, then its parent, up to a limit, and give the judge the same text

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

The defect. `format_nodes` cuts each passage to `_SNIPPET_MAX = 400` characters (`harness/tools/search.py:29` and `:116`). With `merge: true` the passage is the parent chunk, so the agent reads the parent's first 400 characters. The faithfulness judge reads `passages_from_nodes`, which returns `node.text` in full (`search.py:76-87`). In the stored traces, 4,875 retrieved passages have a median of 2,130 characters; 98.8% are longer than 400 (`exploration.md` section 4). A faithfulness score compares the answer with text the agent did not read.

Decision C of the proposal: the agent reads the matched leaf first, then its parent, up to about 2,000 characters, and the judge reads the same text.

The rendering rule. The proposal leaves the overlap open: the parent's text contains the leaf's. This is the plan's rule.
1. Collapse whitespace in both texts, as today.
2. No `matched_text`, or it equals the node's text: the body is the text, cut to the limit.
3. Otherwise the body is the leaf, then a short marker, then the parent with the leaf's first occurrence taken out. Where the leaf was, a gap marker joins the text before it and the text after it. Cut the whole body to the limit.
4. If the leaf is not found in the parent, the body is the leaf, the marker and the whole parent, cut to the limit.
5. The body stays on one line. `harness/export/chain_from_trace.py:37-41` reads the output line by line (`_NODE_LINE`, `_NOTE_LINE`), and `_NOTE_LINE` treats a line that is one bracketed phrase as a steering note. So no body may consist of a bracketed marker alone.

The same text for the judge. A limit of 2,000 still cuts 60.6% of the stored parents, so `passages_from_nodes` cannot return `node.text` any more. The tool writes the body it rendered onto the node as `metadata['agent_text']` before it hands the node to the sink (`sink_nodes`, `search.py:63-73`), and `passages_from_nodes` returns `agent_text` when a node has one and `node.text` otherwise. Three readers follow without a change of their own: `harness/agents/workflow_adapter.py:96` (and through it the inline judge, `app.py:742-750`), `harness/eval/predict.py:66`, and `harness/eval/bootstrap.py:60`.

The limit in this task is a parameter of the two tool builders (`build_ema_search_tool`, `build_corrective_search_tool`) with a default of 2,000, defined as one constant. Where the setting lives in configuration is TASK-012 and waits on the owner. This task does not depend on that answer.

What changes for a user of the app, to say in the outcome. Every recipe's agent reads about five times the text per search result: 10 passages of 2,000 characters are about 5,000 tokens, where 10 of 400 were about 1,000. `corrective_search` shows the longer text to its grader on each cycle (`harness/tools/corrective_search.py:105`, `:119`, `:131`).

Leave alone. `topic_context` renders each chunk in full under a token budget (`harness/tools/topic_context.py:229-254`); its nodes get no `agent_text`. Citation attribution keeps the full parent text (`workflow_adapter.py:100-108`); the proposal excludes it. `harness/tools/events.py` records node references and no passage text.

## Acceptance criteria

- [x] `tests/test_tools.py::test_ema_search_shows_a_leaf_that_starts_after_character_400_of_its_parent` exists and passes: for a parent of 2,100 characters whose leaf starts at character 900, the tool's output contains the whole leaf
- [x] `tests/test_tools.py::test_passage_is_the_leaf_first_then_the_parent_without_the_repeat` exists and passes: the body starts with the leaf's text, and the leaf's text occurs in it exactly once
- [x] `tests/test_tools.py::test_passage_is_cut_at_the_limit` exists and passes: with a limit of 600, no body is longer than 600 characters
- [x] `tests/test_tools.py::test_passage_without_a_parent_is_the_chunk_text` exists and passes: a node without `matched_text`, or whose `matched_text` equals its text, renders as its own text up to the limit
- [x] `tests/test_tools.py::test_passages_from_nodes_returns_what_the_agent_read` exists and passes: after one `ema_search` call inside `capture_search_nodes`, `passages_from_nodes(captured)` equals the list of body lines of the tool's output
- [x] `tests/test_tools_corrective.py::test_corrective_search_renders_with_the_same_limit` exists and passes
- [x] `tests/test_chain_from_trace.py::test_chain_is_rebuilt_from_an_output_with_long_bodies` exists and passes: `harness/export/chain_from_trace.py` parses an output rendered by the new function into the same node list
- [x] `grep -c '_SNIPPET_MAX' harness/tools/search.py` prints 0
- [x] The tests that exist today in `tests/test_tools.py`, `tests/test_tools_corrective.py`, `tests/test_chain_from_trace.py`, `tests/test_export_chain.py` and `tests/test_tools_topic_context.py` pass
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-010]]

## What was built

harness/tools/search.py: _SNIPPET_MAX removed; DEFAULT_PASSAGE_CHARS = 2000 defined once; render_passage(text, matched_text, limit) gives one line: the leaf, ' || in its section: ', then the parent with the leaf's first occurrence replaced by ' [...] ' (the whole parent when the leaf is not found; the plain text when there is no leaf or it equals the text), cut to the limit. format_nodes(nodes, passage_chars) renders it and writes the body to metadata['agent_text'] (excluded from EMBED/LLM content); passages_from_nodes returns agent_text when present, else node.text. ema_search and corrective_search render before they sink, and both builders take passage_chars (default 2000); corrective_search's grader reads the same bodies. 7 new tests (leaf at character 900 of a 2,100-character parent is in the output; leaf first and once; limit 600 holds; no-parent case; passages_from_nodes equals the tool's body lines; corrective_search uses the same limit; chain_from_trace parses 3 nodes and 1 note from an output with long bodies and a bracketed leaf). The existing tests of test_tools, test_tools_corrective, test_chain_from_trace, test_export_chain and test_tools_topic_context pass (81 with the new ones). Change for app users: each search result can be about 5 times longer (10 x 2,000 characters, about 5,000 tokens, where 10 x 400 was about 1,000), and corrective_search's grader reads the longer text on every cycle. topic_context, citation attribution and harness/tools/events.py are unchanged. Lint first failed with I001 (import order in corrective_search.py), fixed with ruff --fix. make test: 725 passed, 2 skipped, 7 deselected (exit 0). make lint: All checks passed (exit 0).

## Files it touched

- `harness/tools/search.py`
- `harness/tools/corrective_search.py`
- `tests/test_tools.py`
- `tests/test_tools_corrective.py`
- `tests/test_chain_from_trace.py`

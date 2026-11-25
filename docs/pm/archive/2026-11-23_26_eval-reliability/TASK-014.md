---
type: pm-task
epic: 2026-11-23_26_eval-reliability
sprint: 2026-11-23_26_eval-reliability
task: TASK-014
status: done
kind: documentation
title: "Say in the docs what the agent reads, how the two earlier result pages were made, and how to choose the judge"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_26_eval-reliability/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-014 — Say in the docs what the agent reads, how the two earlier result pages were made, and how to choose the judge

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

The proposal lists three documentation parts beside the reset call of TASK-001. This task does those three and two lines that keep new options from being undocumented.

1. `docs/tools/ema_search.md`. The section 'Output format' (lines 31-49) shows a one-sentence body. Say what the agent reads now: the matched leaf first, then its parent, up to `passage_chars` characters, on one line. Say that the faithfulness judge receives the same text. The section 'Observability' (lines 85-92) says the sink feeds 'the faithfulness judge's context passages'; make it say which text.

2. The two earlier result pages. Each gets one note near its top, and nothing else on the page changes. The note states how the numbers were made: with the 400-character cut, with the generator's model as the judge, and with means that print no n. It says that they do not compare with a number from the runner of this work unit, and that the question of repeating them is asked again when backlog row 11 has shipped (`DECISIONS.md`, 'Earlier evaluation numbers are not repeated before the corpus repair'). The note is the assistant's addition and says so, with the date. Do not write a model id from memory: read which model was bound to `roles.judge` at the page's commit with `git show <commit>:harness/configs/models.yaml`. The pages name their commits in their first lines (`199f995`, `f9bba89`).

3. `docs/RECIPES.md`. It shows the runner's command at line 119. Add `--judge`, one printed summary with its counts, and the sentence that the generator and the judge are both Claude models. `docs/RECIPES.md` lines 81-83 and 90-96 describe the inline judge and the stamping; say there that the runner does not run the few-shot layer and the inline judge, and prints a line when a recipe declares one.

4. `docs/RETRIEVAL.md`. Name the profile key `passage_chars` where the page describes the `retrieval` block of a profile.

Left for `/ship`, on purpose: the banners and 'Key decisions' of `CLAUDE.md`, the backlog row, the proposal, the entries in `DECISIONS.md` for the two decision notes, and `docs/pm/_Archive.md`. Other pages mention `scripts/run_eval.py` in passing (`docs/SETUP.md`, `docs/ONBOARDING.md`, `docs/ARCHITECTURE.md`, `docs/VISUALIZATION.md`); read each for a sentence this work made false, and change only such a sentence.

## Acceptance criteria

- [x] `grep -c 'passage_chars' docs/tools/ema_search.md` prints at least 1, and `grep -ci 'matched leaf' docs/tools/ema_search.md` prints at least 1
- [x] `grep -c 'passage_chars' docs/RETRIEVAL.md` prints at least 1
- [x] `grep -c -- '--judge' docs/RECIPES.md` prints at least 1, and the page shows one summary line with `n=`, `failed=` and `judge_invalid=`
- [x] For each of the two `docs/eval/` pages: `head -20 <page> | grep -c '400'` prints at least 1, and `head -20 <page> | grep -ci 'judge'` prints at least 1
- [x] `git diff docs/eval/2026-07-13_topic_subgraphs.md docs/eval/2026-07-20_tree_seeding.md | grep -c '^-[^-]'` prints 0: the two pages get an added note and lose no line
- [x] `make test` passes and `make lint` passes, each run on its own line

**Depends on:** [[TASK-007]], [[TASK-008]], [[TASK-009]], [[TASK-013]]

## What was built

docs/tools/ema_search.md: new subsection 'What the agent reads in each result' (matched leaf first, then its parent, up to passage_chars from the index profile, one line, matched_text/agent_text, the judge reads the same text, the old 400-character cut and the live 7-of-9 observation); Observability says which text the judge receives; the recipe example names passage_chars (passage_chars 4x, 'matched leaf' 3x). docs/RETRIEVAL.md §6 profile block shows passage_chars. docs/RECIPES.md: --judge with an example, the default judge, the two run tags, the same-family sentence, one sample summary with n=, failed=, judge_invalid= (marked as shape, not a result), and a bullet that few-shot and the inline judge run in app.py only and print a NOTE line. The two docs/eval pages each got one note in their first 20 lines (400 and judge present; 0 lines removed), labelled as the assistant's, with the judge binding read at the page's commit (git show 199f995 / f9bba89: roles.judge = claude_opus = claude-opus-4-7, every recipe generating with claude_opus, _SNIPPET_MAX = 400); the seeding note says the probe's vector ranks depend on neither point, only section 6 does. Other pages read: docs/ARCHITECTURE.md:155-159 was false (predict_fn, three tags) and was corrected; docs/ONBOARDING.md, docs/VISUALIZATION.md and docs/SETUP.md hold no sentence this work made false (ONBOARDING's 'works live' refers to the 2026-07 verification; the rewritten runner's first live run is TASK-015). Left for /ship as planned: CLAUDE.md banners, the backlog row, the proposal, DECISIONS.md, docs/pm/_Archive.md. make test: 729 passed, 2 skipped, 7 deselected (exit 0). make lint: All checks passed (exit 0).

## Files it touched

- [[ema_search]] — `docs/tools/ema_search.md`
- [[2026-07-13_topic_subgraphs]] — `docs/eval/2026-07-13_topic_subgraphs.md`
- [[2026-07-20_tree_seeding]] — `docs/eval/2026-07-20_tree_seeding.md`
- [[RECIPES]] — `docs/RECIPES.md`
- [[RETRIEVAL]] — `docs/RETRIEVAL.md`

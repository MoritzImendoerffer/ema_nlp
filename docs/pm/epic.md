---
type: pm-epic
epic: 2026-11-23_26_eval-reliability
status: shipped
shipped: 2026-11-23
opened: 2026-11-23
tags: [pm/epic]
---

# Eval reliability — numbers that can be trusted

**Shipped on 2026-11-23, all 18 tasks** (15 planned, 3 added on the owner's answers: the
workspace header for an organization-scoped key, a fix for a trace written late, and taking the
trace id from the adapter). The runner counts a failed run instead of judging it, prints n beside
every mean, records the generator and the judge (`claude-opus-5-5`, or `--judge`), stamps the
resolved recipe, and lets the agent and the judge read the same passage (matched leaf, then
parent, up to the profile's `passage_chars`). The live check passed every check on its second
run ([page](../eval/2026-11-23_eval_runner_live_check.md)). Not shipped: a judge of another
provider was not called (no key), and a failed item was not seen on the live path.

Written by Claude (Fable 5.2) during `/plan` on 2026-11-23. This note is hand-written;
`scripts/pm_notes.py` never changes it.

**Backlog row 9**, top of `Now` in [`BACKLOG.md`](../../BACKLOG.md) ·
proposal: `docs/next/eval_reliability.md` (deleted on delivery, 2026-11-23; in git at `a1c587c`) ·
board: [[_Board]]

## Why this epic

Every later step of the rehearsal reports a number through `scripts/run_eval.py`: the corpus
repair, the cheap rungs, the nine-class benchmark. That runner cannot be trusted today, and a
number built on it would have to be made again.

What was found, each point read in the code and counted in the 114 stored traces
([review, section 4](../eval/2026-11-23_pkr_testbed_review.md)):

- **A crash is scored as an answer.** Five runs ended with `RuntimeError: Event loop is
  closed`, and the judges scored them anyway. One of them holds correctness 5 beside
  faithfulness 1.
- **A mean hides its rows.** A stored mean of 4.353 for 20 questions is 74 / 17. Three
  questions are missing from it and nothing says so.
- **The judge is the model that wrote the answer**, and no run records which model judged it.
- **The judge reads text the agent did not.** The agent sees the first 400 characters of a
  passage. The judge sees all of it; the median passage has 2,130 characters.
- **Two docs pages show a call that deletes the whole graph** as the way to "build and
  verify".

## What will be true when it is done

- A failed question is listed by its id and left out of the mean. Every mean prints how many
  rows it covers.
- The judge model is a setting, `--judge` changes it for one run, and every run records the
  model id of the generator and of the judge.
- The agent reads the matched leaf and its parent up to 2,000 characters, and the judge reads
  the same text.
- A trace names its benchmark item and its recipe.
- No docs page shows the deleting call without its warning.

## What it does not do

No repeats, no resume, no new metric, and no earlier number is made again. It makes one run
honest. Three repeats and the nine classes come with backlog row 15.

## Where things are

| | |
|---|---|
| The tasks | [[_Board]], 15 of them |
| The plan for a person | `.claude/work/2026-11-23_26_eval-reliability/implementation-plan.md` |
| What the code looked like before | `.claude/work/2026-11-23_26_eval-reliability/exploration.md` |
| What waits on the owner | [`decisions/`](decisions/README.md): where the passage limit lives, and the go-ahead for the one paid run |
| The five questions already decided | [`DECISIONS.md`](../../DECISIONS.md), "Evaluation design" |

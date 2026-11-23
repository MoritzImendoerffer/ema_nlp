---
type: pm-decision
epic: 2026-11-23_26_eval-reliability
status: settled
settled: 2026-11-23
opened: 2026-11-23
blocks: TASK-012
tags: [pm/decision]
---

# Where the passage limit lives

Written by Claude (Fable 5.2) during `/plan` on 2026-11-23. The question comes from the
exploration of backlog row 9 (`.claude/work/2026-11-23_26_eval-reliability/exploration.md`,
section 11, question 2).

## What was decided already, and what is still open

You decided on 2026-11-23 that the agent reads the matched leaf first and then its parent
chunk, up to about 2,000 characters, and that "the limit is a setting of the tool"
([`DECISIONS.md`](../../../DECISIONS.md), "The agent reads the passage that is judged").

Words used here:

- A **leaf** is the small chunk that the vector search matched, about 128 tokens.
- Its **parent** is the larger chunk around it, about 512 tokens. The stored parents have a
  median of 2,130 characters.
- The **passage limit** is the number of characters of leaf plus parent that one search result
  shows the agent. Until TASK-011 that number was 400 and sat in the code (`_SNIPPET_MAX`).
  Since TASK-011 (2026-11-23) it is 2,000, defined once as `DEFAULT_PASSAGE_CHARS` in
  `harness/tools/search.py`, and a parameter `passage_chars` of the two tool builders. No
  configuration file sets it yet; that is this question.

What is open: **no tool has a configuration file.** `harness/configs/` has no `tools/` folder.
A tool receives its arguments from the code that builds the agent
(`harness/agents/session.py:59-70`). So "a setting of the tool" has to be put somewhere, and
there are three places.

## The options

| | Where the key lives | What it means for you |
|---|---|---|
| **(a)** | In the index profile, as `retrieval.passage_chars`, beside `k` and `merge` (`harness/configs/index/neo4j_hier.yaml:24-27`) | One profile gives one passage shape to every recipe that uses it. Two recipes on the same index always read the same text, so their numbers compare. To try another limit you copy a profile, as you do for another `k` |
| **(b)** | In the recipe, as a key of its `retrieval` block | Each recipe can have its own limit. Two recipes on one index can then differ in two things at once, the technique and the text length, and a difference between their numbers has two possible causes |
| **(c)** | In a new file, `harness/configs/tools/ema_search.yaml` | The setting is where the proposal's words put it. It adds a new kind of config file and a loader for it, for one number. `corrective_search` renders passages too and would need the same file or a second one |

In all three, a missing key means 2,000, and the limit that was in force is written on every
trace and every evaluation run as `ema.retrieval.passage_chars`.

## Recommendation

**(a), the index profile.** This is the assistant's recommendation.

- The profile already decides whether a parent exists at all (`merge: true`). The limit says
  how much of that parent is shown. The two belong together.
- `build_recipe` already reads the profile and already has an override for `k`
  (`harness/recipes/build.py:42-46`). No new loader is needed.
- It keeps the comparison between recipes clean, which is what the evaluation is for.

What (a) costs: a recipe cannot set its own limit. If a later experiment needs that, a recipe
key that overrides the profile can be added then, as `retrieval_k` overrides `k` today.

## What waits on this

TASK-012 (the config key) and TASK-013 (passing it to the tools). They are tasks 12 and 13 of
15. The eleven tasks before them do not depend on the answer: TASK-011 builds the rendering
with the limit as a parameter that defaults to 2,000.

The plan's tasks are written for (a). With (b) or (c) the files and tests of TASK-012 and
TASK-013 change, and the plan is corrected before either starts.

## The answers

**2026-11-23, the owner: "agree"** — option (a), the recommendation. The passage limit is a
key `passage_chars` in the `retrieval` block of the index profile, beside `k` and `merge`. A
profile without the key reads as 2,000. TASK-012 and TASK-013 are built as planned.

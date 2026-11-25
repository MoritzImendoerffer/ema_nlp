---
type: pm-decision
epic: 2026-11-23_27_pipeline-refresh
status: settled
settled: 2026-11-25
opened: 2026-11-23
waiting_on: the owner (may overrule)
blocks: TASK-007
tags: [pm/decision]
---

# B. Is a URL that left the source deleted from the graph

Open question B of the proposal (`docs/next/pipeline_refresh.md`) and of the exploration
(`.claude/work/2026-11-23_27_pipeline-refresh/exploration.md`, section 10).

## What was found

EMA withdraws documents. Today every one of the 79,882 graph documents has a clean row in
`parsed_documents`, so a prune would delete 0 documents (exploration, section 4.3). A prune
that compared the graph with a narrowed scope would delete almost everything:
`--prune --limit 200` would remove 79,682 documents (exploration, section 3.7).

## The options

1. **Keep by default; `--prune` deletes on request.** The graph can still answer a question
   about a withdrawn text.
2. **Always delete.** The graph always equals the source.

## The answers

**2026-11-25, decided by the lead assistant session `ema-nlp-3b` under the owner's delegation
of 2026-11-25** ("You are allowed to plan and implement ways forward"), relayed to the
implementing session. This is the assistant's answer, not the owner's. The owner can overrule
it.

Option 1, the recommendation. Decide for good once row 13 puts the document status in the
graph.

A choice made by the plan, not by the lead: `--prune` compares the graph with **all** clean
URLs of `parsed_documents`, whatever the scope says, so a narrowed scope cannot delete
documents outside it.

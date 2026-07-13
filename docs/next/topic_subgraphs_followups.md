# Plan: topic-subgraphs follow-ups — baseline, breadth, and the eval-path timeout

*Status: 📋 planned (2026-07-13). Follow-ups from executing
[`topic_subgraphs.md`](topic_subgraphs.md) steps 1–6 — evidence in
[`docs/eval/2026-07-13_topic_subgraphs.md`](../eval/2026-07-13_topic_subgraphs.md).
Four small, independent items, cheapest-first; 1 and 4 are runnable today, 2–3 follow
the complexity rule (each is justified by a concrete, already-observed benchmark
failure, not anticipation).*

## 1. Finish the no-regression verdict — `steered_agent` T1/T3/T4 baseline

**Why.** The step-6 gate is "T2 improves with no regression elsewhere". The T2
head-to-head is done (topic_agent 5.000/5.000 vs steered_agent 4.700/4.900, Opus) and
`topic_agent`'s own T1/T3/T4 numbers show no collapse — but there is no same-model
baseline to compare them against, so "no regression" is currently informal.

**What exists.** All `topic_agent` legs in MLflow (`1239ec66` T1, `0a22ab4b` T3,
`41c3cb35` T4 — Sonnet 5 generation, Opus judges); the `claude_sonnet` model entry +
Claude-5 shims in `harness/llms.py`.

**Step (one command, ~35 questions, needs API budget):**

```bash
python scripts/run_eval.py --recipe steered_agent --types T1 T3 T4 --model claude_sonnet
```

Then compare per type against the `topic_agent` runs above and append the verdict to
the eval report. Regression tolerance: means within ±0.2 = neutral; a bigger drop on
any type must be per-item diagnosed before the recipe is promoted.

## 2. More hubs — worksharing first, then GVP, nitrosamines

**Why (observed failure, not anticipation).** The sweep's T1/T3/T4 point losses
concentrate in **worksharing** questions — exactly where no subgraph exists: one T1
letter-of-intent item flailed through 29 searches (judge could not even score it), the
T3 worksharing/CAP items dropped to 3–4, and the worst T4 item (fee synthesis,
correctness 1) called `topic_context` and got no worksharing coverage back. The
mechanism demonstrably helps where a hub exists (every T2 fee/scoping item it covered
scored 5); the failures sit precisely in the uncovered topic.

**What exists.** The full curation CLI (`manage_topic_hubs.py propose | confirm |
report | build`), the propose scoring (curated-fanout + archive penalties), the §2
evidence that the GVP hub needs 2 hops (22 docs @1 → 143 @2).

**Steps.**
1. `propose --top 10` on the live graph; expect the worksharing/variations overview
   page and the GVP hub to rank high (report already validated GVP reachability).
2. Human-confirm 2–4 hubs (`confirm <key>`), respecting the report histograms
   (oversized/polluted subgraphs are visible before going live).
3. `build` + `propagate`; re-run the affected T1/T3 slice and check the worksharing
   items specifically (per-item, not means — the slice is small).

## 3. Cross-family T2 benchmark items (benchmark honesty)

**Why.** All 10 T2 items sit in the one referral-procedures family — the current T2
win proves the mechanism, not breadth. This was flagged in the original plan (§6) and
stands after the eval.

**Steps.** After item 2 lands, add 2–3 T2 scoping items drawn from the newly-built
families (worksharing timetables, GVP module scoping, nitrosamine limits), following
the Phase 2.3 item schema; keep them out of any hub-tuning loop (write items first,
then never adjust hub walks to fit them).

## 4. Client-side LLM request timeout (`harness/llms.py`)

**Why (observed failure).** The first T4 eval attempt hung for ~70 minutes on a stuck
HTTP call — single sleeping thread, zero API traffic, silent (`mlflow#13352` family).
It burned wall-clock and GPU-host attention, not tokens; a clean rerun completed in
minutes. Evals and the live app share this LLM path.

**Design sketch.** Pass an explicit request timeout (+ bounded retries) into the
`_Anthropic` wrapper (the anthropic SDK accepts `timeout=`/`max_retries=` at client
construction; llama-index forwards constructor kwargs). Config surface: a `timeout_s`
per model in `models.yaml` (default ~120s), so a hung call fails loudly and the eval
runner records the item as errored instead of idling. Offline test: constructor wiring
only (no live call).

## Open decisions

- Item 1: is ±0.2 the right neutrality band for 5–20-item slices? (Judge variance on
  n=5 T4 is large; consider per-item diffs instead of means there.)
- Item 2: does the worksharing overview page exist as a *static* hub page, or is it a
  dynamic listing (the plan's §6 dynamic-listing risk)? `report` will show it.
- Item 4: timeout value for long agent turns (a 19-search T4 turn is legitimate work —
  the timeout is per HTTP request, not per turn, so 120s should be safe).

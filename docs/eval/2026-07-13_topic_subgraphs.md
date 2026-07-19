# Topic-subgraphs evaluation report — 2026-07-13

*Work item: [`docs/next/topic_subgraphs.md`](../next/topic_subgraphs.md) steps 5–6.
Code: commits `199f995` (implementation) + `02bf721`/`5c5ccce` (Claude-5 model shims), branch
`claude/agentic-rag-foundation`. MLflow (sqlite `mlflow.db`, experiment `ema_nlp`) is the
system of record; run IDs below.*

## 1. Background

Two retrieval needs that similarity top-k structurally cannot serve, both visible in the
benchmark: **T2 scoping questions** compare *sibling* documents (all 10 T2 items draw on
the referral-procedures Q&A family — a top-k hit lands on one sibling, answering needs
the others), and **exhaustive enumeration** (top-k returns the best-matching members of a
set, never provably all of them).

The implemented design exploits the fact that EMA's topic hub pages are curated indices:
a hub's qualified `LINKS_TO` fan-out (hub → detail page → PDF, 2 hops, every node on the
path matching a category-OR-doc_type qualifier) *is* the exhaustive member list. The walk
runs **offline** (`scripts/manage_topic_hubs.py build`) and stamps membership
(`:Document.topic_hubs`) through the same canonical rails as the other EMA labels; query
time is a property lookup surfaced to the agent as the **`topic_context` tool** — a
pageable, query-ranked member catalog (honest total + truncated flag) with an optional
token-budgeted best-chunk context. Recipe `topic_agent` = `steered_agent` (category
quotas + LINKS_TO expansion + routing) **plus** this tool.

## 2. Live build (step 5)

- Confirmed hub `referral_procedures` (seed: *Referral procedures: human medicines*
  overview page) walks to **49 members**: 28 `qa`, 14 `regulatory_overview`,
  6 `scientific_guideline`, 1 `regulatory_procedure`; PDF `doc_type`s incl.
  12 `regulatory-procedural-guideline`.
- **Reachability spot-check PASSED**: all 3 gold documents behind the 10 T2 items
  (Q&A Article 30 / Article 31 pharmacovigilance / Article 31 non-pharmacovigilance)
  are members — the plan's §2 live evidence reproduced through the shipped code.
- Membership stamped into Mongo `document_metadata` (49 rows, config_hash
  `bd29a77fd0b6`) and propagated to `:Document.topic_hubs`; live `topic_context`
  smoke test renders the grouped, ranked catalog correctly.

## 3. Evaluation setup (step 6)

- Vehicle: `scripts/run_eval.py` over `benchmark/benchmark.jsonl` (45 items:
  20 T1 lookup / 10 T2 scoping / 10 T3 multi-hop / 5 T4 synthesis); one MLflow run per
  question type; judges = `mlflow.genai` correctness + faithfulness on **Claude Opus 4.7**
  (1–5 scale) in every run below.
- Generation models: the T2 head-to-head ran on **Opus** (recipe default). After the API
  credit top-up, the remaining legs ran on **Claude Sonnet 5** (`--model claude_sonnet`;
  required two `harness/llms.py` shims: Claude-5 `temperature` deprecation + stale
  llama-index model-table fallback). Absolute numbers are therefore comparable only
  within a model; the recipe-vs-recipe T2 comparison is same-model (Opus) and fair.

## 4. Headline result — T2 head-to-head (Opus, 10 items)

| Recipe | correctness | faithfulness | MLflow run |
|---|---|---|---|
| **topic_agent** | **5.000** | **5.000** | `30ceab33` |
| steered_agent (baseline) | 4.700 | 4.900 | `218c45c3` |

The agent called `topic_context` on **6/10** questions (plus 25 `ema_search` calls
across the run). Both baseline failures are precisely the predicted **cross-sibling
completeness** misses, on the two fee questions:

- *"…fees payable only when the MAH initiated…"* — baseline correctness **3**: judge
  rationale: correctly identifies Article 30 but "fails to mention Article 31
  non-pharmacovigilance referrals, which the gold answer explicitly includes as the
  other procedure fitting the same pattern."
- *"…fees always levied regardless of initiator…"* — baseline correctness **4**
  (faithfulness 4): right procedure, incomplete cross-procedure contrast.

`topic_agent` used the topic map on both (tc=1 in the traces) and scored 5/5.

## 5. Cross-type results for topic_agent (no-regression sweep, Sonnet 5)

| Type (n) | correctness | faithfulness | topic_context used | MLflow run |
|---|---|---|---|---|
| T1 lookup (20) | 4.263¹ | 4.526¹ | 9/20 | `1239ec66` |
| T3 multi-hop (10) | 4.600 | 4.600 | 5/10 | `0a22ab4b` |
| T4 synthesis (5) | 3.800 | 5.000² | 1/5 | `41c3cb35` |

¹ 19/20 judged (one judge response failed to parse).
² One agent error during the run; 4/5 judged on faithfulness.

Reference point: a partial **Opus** `topic_agent` T1 run exists from the aborted first
sweep (`5ba51e5c`, 17/20 judged before credits ran out): correctness 4.353 /
faithfulness 4.765 — close to the Sonnet numbers, suggesting T1 is not very
model-sensitive for this recipe.

Per-item lowlights (where the points went, all Sonnet runs):

- **T1**: two worksharing fee/notice questions (correctness 2–3, incl. one 29-search
  flail on a letter-of-intent question) — *worksharing* is outside the one built
  subgraph, so `topic_context` could not help; two more timeline/co-rapporteur items
  at 3–4.
- **T3**: drops on worksharing/CAP items (3–4); one worksharing Type IB+II item scored
  correctness 5 but **faithfulness 1** (answer right, judged insufficiently grounded
  in the retrieved passages after a 14-search session).
- **T4**: the fee-comparison synthesis item scored correctness **1** (it did call
  `topic_context` but synthesized an incomplete comparison); the other four items
  scored 4–5 with perfect faithfulness.

## 6. What is established, and what is not

**Established:**

1. The precompute→lookup mechanism works end-to-end live (build, stamps, propagate,
   tool), and the agent adopts the tool unprompted on appropriate questions
   (6/10 T2, 9/20 T1).
2. On the targeted failure mode — T2 cross-sibling scoping — `topic_agent` hits the
   judge ceiling and removes exactly the completeness failures the baseline shows,
   same model, same judges.

**Not established (honesty section):**

1. **No-regression verdict is incomplete**: the `steered_agent` baseline on T1/T3/T4
   (Sonnet) was not run (budget stop). `topic_agent`'s own cross-type numbers show no
   obvious collapse, but the formal comparison awaits
   `scripts/run_eval.py --recipe steered_agent --types T1 T3 T4 --model claude_sonnet`.
2. **One topic family**: all 10 T2 items sit in the referral-procedures family — this
   proves the mechanism, not breadth. The T1/T3 lowlights are concentrated in
   *worksharing* questions, i.e. exactly where no subgraph exists yet: build/confirm
   more hubs (worksharing/variations, GVP, nitrosamines) and consider 2–3 new T2 items
   from other families.
3. **Model mix**: T2 numbers are Opus, the sweep is Sonnet 5; do not compare across
   the two tables.

## 7. Operational notes

- The first T4 attempt **hung** (~70 min, single sleeping thread, zero API traffic —
  a stuck HTTP call without timeout, in the mlflow#13352 family). A clean rerun
  completed in minutes. Recommendation: add a client-side request timeout in
  `harness/llms.py`.
- The aborted first sweep died on **API credit exhaustion** mid-judging (visible as
  unjudged items in `5ba51e5c`); MLflow kept the partial run — treat any
  run with `n_judged < n` accordingly.
- Claude 5 models needed two shims (now in `harness/llms.py`, offline-tested):
  drop the deprecated `temperature` field, and fall back to correct metadata
  (200k context, function-calling capable) when llama-index's static model table
  doesn't know the model id.

## 8. Critique (2026-07-19) — how far the T2 result carries

A post-hoc challenge of this report sharpened §6.2 into three limits. **Read the
headline table as "the mechanism works", not "the approach generalizes".**

1. **Circular by construction.** The `referral_procedures` hub was built *because*
   all 10 T2 items live in that family, and the step-5 gate verified the 3 gold
   documents were members *before* the eval ran. The eval therefore could not fail
   for coverage reasons — it measured only "given perfect, pre-verified coverage of
   the test set, does the agent adopt the tool and use the catalog". Valid as a
   mechanism unit test; no evidence about unseen topics.
2. **No statistical power + ceiling.** 5.000 vs 4.700 is 2 discordant items out of
   10 (a paired sign test is nowhere near significance). The real evidence is
   qualitative: both baseline failures were *predicted in advance* as cross-sibling
   misses and the fix removed exactly those. The 1–5 judge also ceilings at 5
   (can't distinguish "complete" from "judge-satisfying"), and Claude judging
   Claude carries self-preference risk.
3. **Two unproven generalization halves.** (a) *Walk transfer*: the 2-hop
   hub→detail→PDF pattern + qualifiers is per-hub config tuned on this one hub;
   other families (worksharing — where the sweep's failures concentrate — GVP,
   nitrosamines) may not share the shape. (b) *Membership precision*: the gate
   checked recall of the 3 gold docs only; nothing verified the other 46 members
   belong. False members would inject authoritative-looking noise into
   `topic_context`, and this eval design cannot detect that.

Honest framing: this is a **curated-index strategy** — it generalizes exactly as
far as EMA maintains hub pages with this link structure and a human confirms each
hub. Upgrade path: build 2–3 hubs *without* consulting benchmark items, author new
T2 items from those families blind to hub membership, run the missing
`steered_agent` T1/T3/T4 baseline (§6.1), and add a membership-precision check.

*(Also checked and cleared: the `MockLLM` / unauthenticated-HF-Hub messages seen
when opening the index are retrieval-path artifacts — `Settings.llm = None` in
`harness/providers.py` and `llm=MockLLM()` in `open_index` deliberately block
LlamaIndex's OpenAI default; generation used real Anthropic models via
`build_recipe` → `get_llm_for_model`, the eval recipes run `pipeline: none` so no
LLM-dependent retrieval step existed, and `llm_rewrite` raises rather than
silently degrading. The HF warning is an unauthenticated revision check on the
locally cached embedder, not a re-download.)*

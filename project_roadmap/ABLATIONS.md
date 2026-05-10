# Ablations A, B, C — detailed design

*Companion to `ROADMAP.md` Phase 4. Read that first for scope and measurement context.*

Each ablation tests a specific claim about where subject-matter-expert effort pays off in a RAG pipeline. All three share:

- The same corpus (`corpus.jsonl` from Phase 1)
- The same benchmark (`benchmark.jsonl` from Phase 2)
- The same evaluation harness and metrics (from Phase 3)
- The same baseline configuration to beat

What changes is exactly one thing per ablation — that's what "ablation" means.

---

## Ablation A — SME-curated evidence filtering and query reformulation

### Claim being tested
**Retrieval-layer interventions authored by a domain expert beat vanilla dense retrieval, particularly on questions that require disambiguation or follow-the-thread reasoning.**

### Why this one first
Recent expert evaluation of medical RAG (~80k physician annotations across GPT-4o and Llama-3.1 pipelines) found that only 22% of top-16 retrieved passages were judged relevant, and evidence-selection precision was 41–43%. A combined intervention — query reformulation plus evidence filtering — recovered +12 points on MedMCQA and +8.2 on MedXpertQA. MIRAGE's corpus-choice ablation showed up to 18-point swings from retrieval-side changes alone. If SME effort only moves the needle in one place, the literature says it moves it here most reliably.

### Variants to run

| ID | Description | SME effort required |
|---|---|---|
| A0 | Baseline (Phase 3): dense retrieval, top-k=5, no reranking, no filtering | None |
| A1 | A0 + acronym/synonym dictionary applied as query expansion | You write ~30–50 pharma acronym entries (CAPA, MAH, AI, ICH Q3A, GMP, …) with expansions and synonyms |
| A2 | A0 + topic-path filter: restrict retrieval to chunks sharing the question's predicted topic | Zero if topic prediction is automated; modest if SME-labeled |
| A3 | A0 + LLM reranker with **SME-authored** relevance rubric | You write a ~200-word rubric describing what "relevant" means for EMA Q&A |
| A4 | A0 + LLM reranker with **generic** relevance rubric (control for A3) | None |
| A5 | A1 + A2 + A3 combined | Combined |

A3 vs A4 is the cleanest test of whether SME rubric authorship is what helps, versus reranking in general.

### The SME artifacts (what you actually produce)

**For A1 — acronym/synonym dictionary.** A JSON/YAML file like:
```yaml
- canonical: "Acceptable Intake"
  acronym: "AI"
  synonyms: ["acceptable daily intake", "safe intake"]
  context_disambiguation:
    - "toxicology/impurity context — NOT artificial intelligence"
  topic_paths_where_relevant: ["nitrosamines", "genotoxic-impurities"]
- canonical: "Marketing Authorisation Holder"
  acronym: "MAH"
  synonyms: ["licence holder", "authorisation holder"]
- canonical: "Corrective and Preventive Action"
  acronym: "CAPA"
  synonyms: ["remediation plan"]
# ~30–50 entries total
```
Query expansion: when a question contains "AI" near impurity/nitrosamine words, add "Acceptable Intake" to the query. When it contains "MAH," add "Marketing Authorisation Holder" and vice versa.

**For A2 — topic-aware retrieval.** Your corpus records already carry `topic_path` from Phase 1. For each question, predict the topic path (cheap LLM classification or rule-based by keyword). At retrieval time, boost or filter to the predicted topic.

**For A3 — SME-written relevance rubric.** Something like:
> *A retrieved Q&A is relevant if it directly addresses what the question asks about. For EMA content, this means: (1) the regulatory obligation or procedure in the retrieved Q&A matches the one in the question; (2) the scope (MAH vs. applicant, chemical vs. biological, CAP vs. NAP) aligns; (3) if the question concerns a specific threshold, the retrieved Q&A specifies or is required to compute that threshold. Retrieved Q&As that merely share topic keywords but address a different procedural step are not relevant. Prefer retrieved Q&As from the same regulatory document as the question's gold source when multiple candidates are equally on-topic.*

### Expected per-type effects

| Question type | Expected effect | Why |
|---|---|---|
| T1 Lookup | Small to none | Flat retrieval already works |
| T2 Scoping | Large | Acronym expansion and topic filtering directly address the scoping failure mode |
| T3 Multi-hop | Moderate | Better first-hop retrieval helps, but doesn't solve the traversal problem |
| T4 Synthesis | Moderate | Reranker helps recall across siblings |

### Measurement
Per-type Retrieval Recall@5 and Correctness for each of A0–A5. Plot as a grouped bar chart, one panel per question type. If A3 beats A4 by a meaningful margin, that's evidence your rubric matters. If they tie, the gain is from reranking generically.

### Cost budget
A3/A4 add one LLM call per retrieved chunk. For 40 questions × 5 chunks × 2 runs × a few models, stay on a Haiku-tier or cheaper judge to control spend.

### Risks
- **A1 is underpowered if your dictionary is tiny.** 30 entries may not hit enough questions to move metrics. Grow it as you write the benchmark.
- **A3's rubric quality is hard to audit.** Rewrite the rubric once, midway, based on failure analysis — and record both versions.

---

## Ablation B — Process-reward supervision for agent planning

### Claim being tested
**An agent that can plan, retrieve iteratively, and follow cross-references beats single-pass retrieval, especially when plan steps are supervised by SME labels rather than outcome-only signals.**

### Why this one
RAG-Gym (2025) formalized agentic RAG as a nested MDP and showed that process-level supervision — rewarding good *intermediate* plan steps, not just correct final answers — raised ReAct HotpotQA F1 from 41.09 to 60.19 (+19 points). The biggest single-intervention delta in the current agentic-RAG literature. Your multi-hop (T3) and synthesis (T4) questions are the EMA-domain equivalent of HotpotQA's multi-hop format.

### Architecture
A ReAct-style agent with these tools:
- `search(query, k=5)` — dense retrieval over the corpus
- `follow_cross_refs(qa_id)` — lookup-table traversal using the `cross_refs` field already in your corpus
- `filter_by_topic(topic_path)` — topic-restricted retrieval
- `answer(text, cited_qa_ids)` — emit final answer

The agent loops: think → act → observe → think → …, terminating on `answer`.

### Variants to run

| ID | Description | SME effort required |
|---|---|---|
| B0 | Baseline (Phase 3, single-pass) | None |
| B1 | ReAct agent, no supervision — standard prompt, outcome-only reward | None |
| B2 | ReAct agent + **LLM-judge** process rewards (an LLM scores each plan step as "good next action given history") | None |
| B3 | ReAct agent + **SME-authored** process rewards on a small training subset | You label ~50–100 plan steps from B1 rollouts |
| B4 | ReAct agent + SME-authored *tool descriptions* (versus LLM-generated tool descriptions) | You write 3–4 tool docstrings |

B2 vs B3 isolates whether SME labels beat automated labels. B4 tests a cheaper form of SME input (descriptions rather than step labels).

### The SME artifacts

**For B3 — process-reward labels.** Run B1 on a held-out subset of your benchmark. Dump the agent trajectories as JSONL:
```json
{
  "question": "What interim limit applies during CAPA for chronic-use nitrosamine exceedance?",
  "trajectory": [
    {"step": 0, "thought": "Need to find CAPA interim limit rules", "action": "search('CAPA interim limit nitrosamine')", "observation": "[chunk A: Q22 nitrosamines]"},
    {"step": 1, "thought": "Q22 references Q20 and Q10", "action": "follow_cross_refs('nitrosamines:Q22')", "observation": "[chunks B, C]"},
    {"step": 2, "thought": "I have everything", "action": "answer(…)"}
  ]
}
```
You label each step with: `good_step | suboptimal_step | wrong_step`, plus a one-line reason. Target 50–100 labels.

Those labels become either (a) a training signal if you fine-tune a reward model, or (b) few-shot examples in the agent's planning prompt. For a small project, (b) is easier.

**For B4 — tool descriptions.** For each tool, write a short docstring that encodes regulatory context:
```python
def follow_cross_refs(qa_id: str) -> list[QAChunk]:
    """
    Retrieve the Q&A items explicitly cross-referenced from `qa_id`.
    
    Use this when a retrieved EMA Q&A says 'see Q&A N' or 'as described in Q&A N'
    — these cross-references frequently contain the quantitative detail
    (thresholds, deadlines, specific procedures) that the referring Q&A omits.
    Chronic-use limits, interim limits, and CAPA timelines are almost always
    in cross-referenced chunks rather than the top-level answer.
    """
```
Compare to an LLM-generated docstring from the same function signature.

### Expected per-type effects

| Question type | Expected effect | Why |
|---|---|---|
| T1 Lookup | None or slightly negative | Agent adds latency with no benefit |
| T2 Scoping | Small | Iterative retrieval can re-query with better terms |
| T3 Multi-hop | Large | The whole point — agent can follow `cross_refs` |
| T4 Synthesis | Moderate to large | Agent can retrieve from multiple sources and combine |

### Measurement
Per-type Recall@5, Correctness, and Citation Accuracy. Additionally: **tool-call traces per question**. If B1 and B3 both solve T3 but B3 does it in fewer steps, that's a valuable secondary finding.

### Cost budget
Agents use many more tokens than single-pass RAG. Budget accordingly — expect 5–10× the token spend of Phase 3. Cache aggressively.

### Risks
- **Agent unreliability on small models.** A weak model running ReAct can loop forever or hallucinate tool calls. Test on mid-tier (Haiku/GPT-4o-mini at minimum) before investing SME labeling time.
- **Label noise.** Step-labeling is harder than question-answer labeling because "good next action" is context-dependent. Expect to relabel the first 10 as you figure out your own rubric.
- **B3 needs enough training signal to matter.** If you only label 20 steps, few-shot learning will barely move. Aim for 50+ labeled steps or drop to B4 as your SME-input test.

---

## Ablation C — SME few-shot vs self-generated CoT vs zero-shot, across model tiers

### Claim being tested
**The value of SME-written few-shot examples depends on model capability. Frontier reasoning models may make SME few-shot unnecessary — but regulatory text might be the domain where this generalization breaks.** A fully-open model tier (OLMo 3) with verifiable training data serves as a contamination-measurable reference point.

### Why this one is the most interesting
This is the counterargument test. Microsoft's Medprompt (Nori et al., 2023) showed careful SME-free prompt engineering on GPT-4 beat specialist fine-tuned models on medical QA. The follow-up "From Medprompt to o1" (Nori et al., 2024) showed that on o1-preview, few-shot prompting *actively hurt* performance on some medical tasks — as if the model's internal reasoning was being disrupted by the examples.

If that generalizes to EMA regulatory content: the whole argument for SME involvement at the prompting layer collapses as models improve. That's a big claim and worth testing directly.

If it *doesn't* generalize — if regulatory jurisdiction-specific procedural knowledge resists the Medprompt→o1 pattern — then SME prompting input still matters in your domain. Also a useful finding.

### Experiment design: a 3×3 grid

|  | Zero-shot | SME-written few-shot | Self-generated CoT (Medprompt-style) |
|---|---|---|---|
| **Mid-tier closed** (e.g., Haiku 4.5 or GPT-4o-mini) | cell 1 | cell 2 | cell 3 |
| **Frontier reasoning** (e.g., Opus 4.x or o1/o3-class) | cell 4 | cell 5 | cell 6 |
| **Fully-open with verifiable training data** (OLMo 3 32B Think) | cell 7 | cell 8 | cell 9 |

Nine cells. Each runs the full benchmark. Each reports per-type metrics.

The third row is the contamination-measurable reference. OLMo 3's training data (Dolma 3) is fully released; you can grep it for your specific EMA content before running the experiment. See `LEAKAGE.md` section 7.5 for the rationale and verification steps. If the same effect patterns show up across all three rows, you have strong evidence that observed gains are real retrieval/reasoning effects rather than memorization artifacts.

If OLMo 3 is capacity-constrained on some question types (likely for T3/T4 — fully-open models lag frontier models), report that transparently rather than downplaying it. The point is not that OLMo 3 matches the frontier — it's that gain *patterns* across prompting strategies should look similar if the ablation measures real behavior.

### The SME artifacts

**For "SME-written few-shot" (cells 2, 5, 8).** Write 3–5 example Q&A-solving traces yourself, covering the question types:
```
Question: [example T2 question]
Retrieved: [3–5 Q&As from corpus]
Reasoning: [SME-style reasoning showing how to disambiguate, which Q&A to trust, how to handle regulatory specificity]
Answer: [gold-quality answer with correct citations]

Question: [example T3 question]
Retrieved: […]
Reasoning: [shows how to follow a cross-reference chain]
Answer: […]
```
Include 1–2 examples per question type. Keep them out of your benchmark (use separate held-out Q&As from the corpus). Use the same examples across all three model tiers so the comparison is clean.

**For "self-generated CoT" (cells 3, 6, 9).** Medprompt-style: at inference time, the model generates its own chain-of-thought before answering. No SME examples. Use the same CoT generation prompt across all three models.

**For "zero-shot" (cells 1, 4, 7).** The Phase 3 baseline prompt, unchanged. The negative control.

### Predictions (pre-registered)

| Prediction | Rationale |
|---|---|
| Cell 2 > Cell 1 (SME few-shot beats zero-shot on mid-tier) | Standard result for non-reasoning models |
| Cell 3 ≈ Cell 2 on mid-tier | Medprompt's finding |
| Cell 5 ≤ Cell 4 or Cell 5 ≈ Cell 4 (few-shot doesn't help reasoning model) | Medprompt→o1 finding |
| Cell 6 ≤ Cell 4 or ≈ Cell 4 (self-CoT also doesn't help) | Reasoning models already do internal CoT |
| Cell 8 > Cell 7 (SME few-shot still helps OLMo 3) | OLMo 3 Think is reasoning-capable but less so than frontier; few-shot likely still provides value |
| Absolute: Cells 7/8/9 < Cells 4/5/6 on T3/T4 | OLMo 3 lags frontier on multi-hop |
| **Open question: does cell 5 > cell 4 specifically on T3/T4?** | If regulatory multi-hop resists the Medprompt→o1 generalization, SME few-shot would still help on the hardest questions |
| **Open question: does the pattern of gains (Δ across prompting strategies) match between rows?** | If yes: observed effects are real. If no: frontier results may be memorization-influenced. |

The last two predictions are the scientifically interesting ones. A null result (few-shot doesn't help on reasoning models even in this domain) would be a real contribution — it says the Medprompt→o1 story generalizes further than published. A positive result (few-shot still helps on T3/T4 with a reasoning model in regulatory domain) would be evidence that domain specificity matters in ways the medical QA literature hasn't captured.

The row-pattern consistency check adds a contamination-robustness dimension that most RAG papers can't offer.

### Measurement
Per-type Correctness and Citation Accuracy across all nine cells. Three plots: one per model tier, with the three prompting strategies side by side per question type. Plus a summary plot showing the Δ(few-shot − zero-shot) across all three tiers — this is where the row-pattern consistency either holds up or doesn't.

### Cost budget
Reasoning models are expensive (both per-token and in reasoning tokens). For 50 questions × 9 cells × ~2k tokens per answer, expect the frontier-model cells to dominate your API spend. OLMo 3 can be self-hosted on a single GPU or rented cheaply via Together AI / DigitalOcean / similar — it's much cheaper per token than frontier-closed models. Consider running the frontier cells (4–6) on a subsample of 20 questions if budget is tight.

### Risks
- **Model releases obsolete the results fast.** Pick a specific model version, document it clearly in the results. Do not say "reasoning models" — say "o1-preview as of April 2026" and "OLMo 3 32B Think 1025."
- **Few-shot format sensitivity.** The SME few-shot cells depend heavily on your example quality. Bad examples can hurt rather than help — that's the whole Medprompt→o1 lesson. Iterate on the examples once after seeing initial failures, and mark the old version as v0 and the updated one as v1.
- **Low statistical power.** 50 questions split across 9 cells is very little data per cell. Bootstrap confidence intervals. If effects are small, don't over-claim. Consider aggregating across prompting strategies when within-cell n is too low to make per-cell claims.
- **OLMo 3 capability gap on T3/T4.** OLMo 3 may simply not be capable enough to do meaningful multi-hop retrieval regardless of prompting strategy. If cells 7–9 all floor at zero on T3, that's not a failure of the ablation — it's a reportable finding about the capability gap between fully-open and frontier models on regulatory multi-hop.

---

## Running all three ablations — practical notes

### Order matters
Run A first. Its gains (if any) should feed into B and C as the new baseline retriever. Don't test B with bad retrieval — you'd be measuring the wrong thing.

Suggested sequence:
1. A (1–1.5 weeks)
2. Pick the best A variant as the new retrieval base
3. B (1 week)
4. C (1 week, runs independently of B's agent — uses whichever retriever variant you chose from A)

### Share infrastructure
Each ablation should be a config file under `harness/configs/`, not a new code path. One `run_eval.py` should handle all of them via config flags. Anything you duplicate across ablations is a bug waiting to happen.

### Cache everything
Embeddings, retrieval results, LLM-judge scores. Budget for reruns — you *will* rerun each ablation at least twice as you debug.

### Report honestly
Three findings to call out even if they're boring:
1. Which ablation had the **largest effect**
2. Which ablation had the **most consistent effect across question types**
3. Whether any ablation had **a negative effect on some question type** (these are the most informative results — they tell you where your design assumption was wrong)

Null results are findings. An ablation that didn't move the needle is a real data point, worth reporting.

### Write up per-type, not aggregate-only
The single biggest failure mode in small-benchmark RAG papers is reporting only aggregate accuracy. Your four question types are the whole reason the benchmark is interesting — report everything broken down by type. Aggregate numbers go in a table footer, per-type numbers in the main chart.

---

## Stretch: a fourth ablation on citation granularity × trust calibration

If you finish A/B/C with budget left, the literature flags one more interesting test that fits your project especially well.

### Claim
**Citations increase reader trust even when random; reader trust drops once citations are actually opened and checked. Regulatory reviewers are especially sensitive to this — citation quality isn't just a retrieval metric, it's a trust-calibration feature.**

### Variants
- D0: No citations in answers
- D1: Paragraph-level citations
- D2: Sentence-level citations
- D3: Sentence-level citations with **incorrect** sources (a stress test — does the reviewer catch it?)

### Measurement
Self-run on you + 2–3 colleagues. For each of 10 answers, rate trust on 1–7. Then ask participants to verify 3 random citations. Re-rate trust after verification.

Report: trust-before vs trust-after, by condition. Plus: did participants detect D3's incorrect citations? How quickly?

This is a small human study, not an automated benchmark — but it's the finding most directly useful for regulatory teams deciding whether to adopt RAG tools.

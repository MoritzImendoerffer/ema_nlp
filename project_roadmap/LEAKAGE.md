# Data leakage and benchmark contamination

*What the problem is, why it matters specifically for this project, and what you can actually do about it without over-engineering.*

---

## The problem in plain terms

You're building a benchmark from EMA Q&A documents that have been public on the EMA website for years. Modern LLMs are trained on vast web-scraped corpora. There is a very real chance that the exact Q&As you want to use as test data are already in the training data of the models you're evaluating — meaning the model has memorized the answer rather than reasoned to it from retrieval.

If this happens at scale, your benchmark numbers are inflated, your ablations mean less (any improvement might be "did it activate memorization better" rather than "did it retrieve better"), and your conclusions are brittle. This is called **benchmark contamination** or **test-set leakage**, and it's been one of the dominant methodological concerns in LLM evaluation since 2023.

Quick examples of the problem's severity in general LLM evaluation: a 2024 analysis of 31 LLMs on math benchmarks found substantial evidence of training-on-test-set. MMLU and GSM8K, the two most-cited benchmarks in LLM releases, are now both widely considered contaminated in mainstream frontier models. A 2025 study found 20 commonly-used contamination mitigation strategies and concluded that "none are both effective and faithful to the original evaluation goal."

---

## Why this project is especially exposed

Three reasons this is more acute for EMA Q&A than for, say, a benchmark you hand-authored from scratch:

1. **The source material is old, public, and well-indexed.** EMA Q&As have been on the open web for years, in a format search engines love (HTML with clear headings, linked PDFs). Common Crawl almost certainly includes them.
2. **The documents are self-contained Q&A pairs.** Contamination risk is highest when training data looks exactly like evaluation data — and your benchmark items *are* the training-data format. You're not masking anything.
3. **You're using the gold answer as the gold answer.** The EMA-written answer is what you're asking the system to produce. If the model memorized the document, you can't tell whether it retrieved or recalled.

The irony: the thing that makes this project shareable and cheap to curate (EMA did the question-authoring work) is the same thing that makes contamination plausible.

---

## What's actually at risk — and what isn't

Before designing mitigations, it helps to be precise about what leakage would and wouldn't invalidate.

**Leakage would invalidate:**
- Zero-shot baseline comparisons on T1 (Lookup) questions. If the model memorized the answer, retrieval adds nothing measurable.
- Claims that "RAG helps" — because the non-RAG control would also do well.
- Ablation C specifically on T1 — because there's no retrieval reasoning to improve or degrade.

**Leakage would not fully invalidate:**
- Retrieval metrics (Recall@k, Precision@k). These measure whether the *retriever* found the right chunks, independent of whether the generator could have answered without them.
- Citation accuracy. Memorization doesn't help the model cite the right `qa_id`, which requires the retrieved chunks.
- Per-type deltas for T2, T3, T4. Even a contaminated model should do better when you genuinely help it retrieve, and the *gap* between the baseline and the improved system is still informative.
- Ablation B's multi-hop gain. Following cross-references is a behavior, not a fact — the model can memorize facts but can't memorize "the right next tool to call."

The upshot: **retrieval metrics and improvement deltas are more robust to contamination than absolute correctness.** That's already a mitigation built into your evaluation design.

---

## What you can actually do about it

No solution is perfect. Layered defenses beat any single fix. Here are practical approaches, ranked by cost-benefit for your project:

### 1. Detect contamination empirically (cheap, always do this)

Before making any claim from your benchmark, measure how much the candidate models already know.

**The "retrieval-off" baseline.** Run every ablation model on every benchmark question with *no retrieval* — just the question, plus a prompt saying "answer or say I don't know." This is already in your Phase 2.5 ("LLM-knowledge baseline"), but escalate it from "nice to have" to "essential."

- For each question, record whether the model answered zero-shot, and whether the answer matches gold.
- A model that gets a question right with no context is *probably* contaminated on that item. You can't be certain (it could be reasoning from background pharma knowledge), but it's a strong signal.
- Tag each benchmark item with a `zero_shot_known` score per model. Report results both with and without these items.

**Slot-guessing test (optional but informative).** Mask specific factual slots in your benchmark questions — a number, a deadline, a specific limit — and ask the model to fill them in. A contaminated model gets masked slots correct at rates far above chance. Based on the TS-Guessing protocol (Deng et al., 2023).

Example: take EMA/409815/2020 Q10's numeric AI limits. Replace "26.5 ng/day" with a blank. If the model produces "26.5" without retrieval, that document is likely in its training data.

Run this on a subsample of 5–10 questions for each model. Record the rate. This becomes a contamination flag in your results table.

**Report a contamination section in your writeup.** Even if your results are robust despite contamination, reporting the contamination check is what separates a credible benchmark from a marketing claim.

### 2. Rely on retrieval-grounded metrics, not just answer correctness

In your results, emphasize:
- **Retrieval Recall@k and Precision@k** — these measure the retriever, not the generator, and are largely contamination-proof.
- **Citation accuracy** — even a memorized answer can't cite the right `qa_id` from your retrieval layer.
- **Deltas between conditions** (ablation X vs baseline) — contamination affects both arms roughly equally, so the gap is meaningful even when the absolute numbers are inflated.

In the main results table, report these **alongside** Correctness, not in place of it. A contaminated model and a clean model can both show meaningful retrieval-metric differences across ablations.

### 3. Use "closed-book" vs "open-book" scoring

For each benchmark item, report two numbers per model:
- **Closed-book**: question only, no retrieval. Measures what the model has memorized.
- **Open-book**: question + retrieval. Measures what the full RAG system does.

The **lift** (open-book minus closed-book) is the interesting number. A lift of 0 means either (a) the retrieval wasn't useful, or (b) the model already knew the answer — both are interesting findings, but they're different findings.

Items where closed-book already scores high are low-information for comparing RAG strategies. Flag them and weight them less in your aggregate.

### 4. Prefer questions the model doesn't already know

This is the strongest structural defense. When curating the benchmark in Phase 2:
- Prefer questions whose answers depend on **specific quantitative detail** (exact thresholds, specific deadlines, specific procedural steps). These are memorable, but also easily wrong from memory.
- Prefer questions from **recently revised** Q&A documents. The nitrosamine Q&A has 23 revisions — the current version's details may not be in older training data. Check revision dates on each source document.
- Prefer questions that require **cross-reference traversal** (T3). Even a contaminated model has to *re-combine* memorized facts in a way that resembles reasoning. Pure lookup is the most exposed type.
- Deprioritize questions whose answers are stated in many places on the web (topical overviews, Wikipedia-like summaries).

### 5. Perturb benchmark questions (low-cost, moderate benefit)

For a subset of your benchmark, create **paraphrased variants** of the questions that preserve meaning but change surface form. A contaminated model should do equally well on original and paraphrased. A model reasoning from retrieval should also do equally well.

If performance drops significantly on paraphrased versions, that's a contamination signature.

Cost: for 30–50 questions, paraphrasing via LLM takes minutes. Manual review of each paraphrase adds an hour.

**Caveat from the literature:** a 2025 paper found paraphrasing strategies often change difficulty in ways that muddy the interpretation. So use paraphrase-vs-original as a *diagnostic* (are the two versions equivalent for a clean model?) rather than a fix.

### 6. Include "unseen-by-construction" items (high-impact if feasible)

The strongest defense is including some benchmark items that couldn't possibly be in training data.

Options:
- **Post-cutoff Q&As.** Identify the knowledge cutoffs of your target models (public for most). For documents revised *after* those cutoffs, new content is genuinely unseen. Mark those items clearly in the benchmark with a `post_cutoff_for_<model>` flag.
- **Composite questions.** T4 synthesis questions you author yourself, combining two published Q&As in ways the documents don't do. The *question* is novel even if the *source material* isn't.
- **Counterfactual questions.** Frame questions around hypothetical regulatory scenarios that require reasoning over the published Q&As rather than recalling them. "If a MAH identified a nitrosamine at 95% of the AI during CAPA implementation for a chronic-use product, what would the regulatory next step be?" — the model has to combine Q20, Q22, and Q8.

T3 and T4 questions in your current design are already partially in this category. Emphasize them in the stratification.

### 7. Use contamination-aware evaluation protocols (advanced, optional)

The research literature has a few ready-made protocols:

- **Inference-Time Decontamination (ITD; Zhu et al., EMNLP 2024).** Rewrites prompts using an auxiliary LLM to reduce direct memorization reuse. Easy to plug in but inference-cost-heavy.
- **TreeEval / dynamic evaluation.** Use an LLM examiner to generate questions on the fly rather than from a static benchmark. Prevents leakage by construction, but breaks reproducibility and increases cost.
- **Membership Inference Attacks (MIAs).** Techniques that try to determine whether a specific text was in a model's training set. Open-weight models only; mostly research-grade.

For this project, I'd defer all of these to v2. Strategies 1–5 above are sufficient for a credible v1 benchmark. ITD is worth revisiting if v1 shows strong contamination signals.

### 7.5. Use fully-open models as contamination references

A specific, practical technique worth its own section. Most LLMs (Claude, GPT, Gemini, Llama) don't publicly disclose their training corpora — you can't verify whether EMA content is in them, only infer from behavior. A small family of **fully-open** models does disclose everything: weights, training code, training data, training logs, intermediate checkpoints. These models give you something no closed model can: **verifiable** contamination status.

The tradeoff is real: fully-open models currently lag frontier models on capability. You wouldn't use them as your only evaluation target. But including **one** fully-open model in your evaluation suite gives you a reference point where "was this content in training?" is a searchable question rather than a guess.

**Recommended: OLMo 3 (Allen AI, Nov 2025)** is the strongest fully-open model as of early 2026. Available in 7B and 32B parameter sizes, with instruct, reasoning ("Think"), and RL variants. Trained on **Dolma 3** (~9.3T tokens). Crucially, Allen AI released **OlmoTrace**, a tool that maps model outputs back to the specific training-data passages that influenced them — the closest thing to a contamination microscope that currently exists.

- https://allenai.org/olmo
- https://allenai.org/blog/olmo3
- OlmoTrace: lets you click on an OLMo 3 output and see its training-data ancestors

**Alternatives:**
- **Pythia** (EleutherAI) — trained on The Pile (~300B tokens). Smaller, older, weaker. Good for interpretability; less useful as a capable evaluation target.
- **Pleias Common Corpus models** — trained on ~2T tokens of documented-provenance data. Their OpenGovernment subcorpus includes regulatory-type documents from various jurisdictions. Worth checking whether EMA content is in there.
- **Comma (EleutherAI)** — trained on the Common Pile, EleutherAI's 8TB openly-licensed dataset.

### The important caveat

**Fully-open does not mean clean.** Every fully-open model listed here includes web-scraped data (Common Crawl, FineWeb, CC-derived subsets). EMA content has been publicly indexed for years. The probability that *zero* EMA Q&A content made it into these training corpora is low.

What fully-open models give you is not a contamination-free environment — it's one where contamination is **measurable rather than merely suspected**. That's still a big win:

- You can grep the Dolma 3 release for specific phrases from your benchmark sources to verify whether they appear
- OlmoTrace tells you after the fact whether a specific correct answer was in training
- If an ablation produces similar gains on both frontier-closed models and on a verified-clean-for-this-content open model, that's strong evidence the ablation measures real retrieval rather than memorization activation

### Concrete verification step before relying on this

Spend one afternoon, before Phase 2.5, checking whether your specific EMA documents are in Dolma 3:

1. Pick 5–10 specific sentences from each of your main source documents (e.g., the nitrosamine Q&A, the level-of-detail Q&A)
2. Search the public Dolma 3 release for each
3. Record: for each source document, present/absent/partial
4. If absent — OLMo 3 is a genuinely clean reference for those sources
5. If present — report that clearly, and treat OLMo 3 scores the same way you treat frontier-model scores

### How this slots into the overall evaluation

Add OLMo 3 as a **third model tier** in Ablation C (detailed in `ABLATIONS.md`). You go from a 2×3 grid (mid-tier × frontier × three prompting strategies) to a 3×3 grid, with the third row being the verifiably-measured-contamination model. The headline claim becomes stronger: "our effects hold across mid-tier, frontier, and contamination-verifiable models."

Cost: OLMo 3 can be self-hosted on a single GPU (7B) or rented cheaply via inference providers (Together AI, DigitalOcean, others host OLMo 3 for low $/token). Budget impact is minimal compared to frontier-model calls.

### 8. Accept the residual risk and document it

Perfect decontamination isn't achievable without access to training data. After layering the above, you still have residual contamination risk. The credibility move is to **document it clearly and not overclaim**:

- In the README and blog post, have an explicit "Contamination caveats" section.
- For every model evaluated, report its zero-shot closed-book score alongside its RAG score.
- Never make unqualified "Model X achieves 92% on EMA-RAG-Benchmark" claims. Always frame as "Model X achieves a +18-point lift over its closed-book baseline."
- Track what model version you used and when. Models released later may have eaten more of the source material.

---

## Practical integration into the roadmap

### Phase 0 (scoping)
- When counting extractable Q&As, also pull the **last-updated date** for each source document. Flag recent revisions as lower-contamination candidates.

### Phase 1.5 (between corpus and benchmark — new)
- Run a verification check against Dolma 3 (OLMo 3's training corpus) and Common Corpus: for your main source documents, search the training-data releases for distinctive sentences
- Record per-source-document contamination status (present/absent/partial)
- This is a one-afternoon task and tells you whether OLMo 3 is a clean reference for your specific content

### Phase 2 (benchmark construction)
- Prefer quantitative/specific-detail questions per section 4 above.
- Weight the stratification toward T3/T4 where feasible.
- Include ≥5 "post-cutoff" or "composite/counterfactual" items per section 6.
- Generate paraphrased variants for each item; store both in the benchmark.

### Phase 2.5 (knowledge baseline — formerly optional, now essential)
- For each candidate model, run closed-book on every benchmark item.
- Run slot-guessing test on a subsample.
- Tag items with `zero_shot_known` and `likely_contaminated` flags.
- Report aggregate contamination rate per model.

### Phase 3 (baseline)
- Change the main results format: report **open-book** and **closed-book** side by side.
- Report **lift** (open-book − closed-book) as the headline number.

### Phase 4 (ablations)
- Include OLMo 3 as a third model tier in Ablation C — see `ABLATIONS.md` for details
- Run each ablation on both the full benchmark and the "likely-clean" subset (items where zero-shot failed for the model). Compare.
- Report retrieval metrics prominently — they're the contamination-robust signals.

### Phase 5 (writeup)
- Dedicated "Contamination caveats" section in README and blog.
- Specific model versions and dates documented.
- Headline claims phrased as lifts, not absolute scores.

---

## What this costs

- Phase 1.5 Dolma 3 / Common Corpus verification check: +1 afternoon
- Phase 2.5 work: +2–3 evenings to run closed-book on all models and items
- Paraphrase variants: +1 evening
- Post-cutoff/composite items: +1–2 evenings in Phase 2 (partly already planned)
- OLMo 3 as third model tier in Ablation C: +2–3 evenings (self-hosting setup + runs)
- Retrieval-metric-first reporting: no extra work, just reframing
- Documentation and caveats: +1 evening in Phase 5

Total added cost: roughly 1.5 weeks of evening work across the project. The payoff is a benchmark that's defensible when a reviewer points at the leakage problem, with a measurable contamination reference that most RAG benchmarks lack.

---

## Further reading (if you want to go deeper)

### On contamination detection and mitigation
- Survey: "A Comprehensive Survey of Contamination Detection Methods in LLMs" (Ravaut et al.) — https://arxiv.org/html/2404.00699v4
- Paper list: `lyy1994/awesome-data-contamination` — https://github.com/lyy1994/awesome-data-contamination
- Protocol: "Investigating Data Contamination in Modern Benchmarks for LLMs" (Deng et al., 2023) — https://openreview.net/forum?id=a34bgvner1
- Mitigation study: "When Benchmarks Lie" (Sun et al. 2025) — negative-result survey of 20 mitigation strategies, worth reading for a reality check
- Method: "Inference-Time Decontamination: Reusing Leaked Benchmarks for LLM Evaluation" (Zhu et al., EMNLP 2024)

### On fully-open models and training data
- OLMo 3 launch (Allen AI, Nov 2025) — https://allenai.org/blog/olmo3
- OLMo 3 technical overview by Cameron Wolfe — https://cameronrwolfe.substack.com/p/olmo-3
- OLMo GitHub (code, configs, checkpoints) — https://github.com/allenai/OLMo
- OLMES evaluation framework — https://github.com/allenai/olmes
- Common Corpus paper (Pleias, 2025) — https://arxiv.org/abs/2506.01732
- Common Corpus announcement with full dataset breakdown — https://huggingface.co/blog/Pclanglais/two-trillion-tokens-open
- Pythia suite (EleutherAI) — https://github.com/EleutherAI/pythia

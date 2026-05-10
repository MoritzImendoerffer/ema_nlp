# Blog post outline — "Where SMEs actually matter in agentic RAG"

*Working title; alternate: "Mining EMA's own Q&As to build the benchmark that doesn't exist"*

**Target length.** ~2000–2500 words. One long-read, not a thread.
**Target venue.** Personal blog / Medium / Substack. Cross-post to LinkedIn excerpted.
**Target audience.** Two overlapping groups: (1) ML engineers working on RAG in regulated domains, (2) pharma process/quality/regulatory professionals curious about what AI can and can't do for their work.

## Opening hook (~200 words)

Open with a concrete scene, not an abstract claim. Something like:

> Q22 of the EMA nitrosamine Q&A can't be answered on its own. To know what interim limit applies during CAPA for a chronic-use product, a reader has to traverse Q22 → Q20 → Q10 — and the document is full of explicit "see Q&A N" references that an EMA writer authored by hand. That's a multi-hop retrieval test that someone already wrote for us.

Then the tension: **there's no public benchmark that actually uses this material.** Every biomedical RAG benchmark — MIRAGE, PubMedQA, MedQA — tests clinical knowledge. The one pharma-regulatory RAG paper (QA-RAG) is FDA/ICH only. The European Medicines Agency publishes thousands of hours of expert-authored Q&A content, and nobody has turned it into a benchmark.

## The problem with "let's build graph RAG with an ontology" (~300 words)

The honest story: I started down the ontology-first path. SPOR, IDMP, Pistoia — load all the medicinal-product entities into Neo4j, then do entity linking, then the graph answers questions.

Why I bailed:
- **No question existed yet that required the graph.** Every ablation design starts from a failure mode of a simpler system. If you haven't measured the simpler system, you're guessing.
- **The Polysorbate problem.** IDMP classifies substances but doesn't contain instances like Polysorbate 80. The gap between T-box and A-box takes weeks to bridge, and the payoff is uncertain.
- **Multiple conversations with a generalist assistant that kept proposing more scaffolding.** The plans were structurally correct but front-loaded the wrong work.

What flipped the framing: **the EMA Q&A documents are the benchmark, not just the corpus.** An expert already wrote the questions. The gold answers are the adjacent paragraphs. Cross-references are the multi-hop edges. The curation work I thought I needed — gone.

## What "SME value" actually means (~400 words)

The interesting question isn't whether SMEs help RAG systems. It's *where*. A 2025 expert evaluation with 80,000 annotations across medical RAG pipelines found something sharp: only 22% of top-16 retrieved passages were judged relevant by physicians. Evidence-selection precision ran 41–43%. A simple intervention — expert-guided query reformulation plus evidence filtering — recovered +12 points on MedMCQA and +8.2 on MedXpertQA.

That's the retrieval layer. Nothing to do with prompt craft.

The literature clusters into three surprisingly consistent findings:

1. **Retrieval and evidence selection** is where SME effort pays off first and biggest. MIRAGE showed corpus choice alone moves accuracy by 18 points.
2. **Process-level reward supervision** for agent planning is the second-biggest lever. RAG-Gym got +19 F1 on multi-hop questions by having experts label plan steps.
3. **SME-written few-shot examples** are where frontier reasoning models are closing the gap fastest. Microsoft's Medprompt → o1 paper found few-shot *actively hurt* performance on some medical tasks with o1.

Hypothesis for the regulatory domain: (1) and (2) transfer; (3) may not. Regulatory text is legal, procedural, and jurisdiction-specific in ways that clinical MCQA isn't. Frontier reasoning models may struggle to internalize EU-specific procedural knowledge the way they've internalized medical facts.

That's testable. And that's what the project tests.

## Mining the benchmark from EMA (~300 words)

Walk through the corpus construction quickly:

- HTML accordion Q&As on pages like classification-changes and quality-by-design.
- Q&A PDFs like the nitrosamine one (27 pages, 22 questions, 23 revisions, explicit cross-refs).
- Unified schema: question, answer, source, topic path, revision, cross-refs, extraction confidence.

Show the stratified benchmark taxonomy (T1 Lookup, T2 Scoping, T3 Multi-hop, T4 Synthesis) and why each tests something different about retrieval.

Key technical note: **cross-references already in the EMA documents are multi-hop gold edges**. You don't have to invent multi-hop questions; you compose them along chains the regulator already wrote.

## The three ablations (~500 words)

Three ablations, one paragraph each, with the expected direction and the prior art. Keep it tight — details go in the paper/repo, not the blog post.

**A. Evidence filtering and query reformulation.**
Testing whether SME-authored acronym/synonym dictionaries and topic-aware retrieval lift T2 (scoping) and T3 (multi-hop) metrics. Prior-art anchor: +12/+8.2 points from the 2025 expert-evaluation study. Expected result: large gain on T2, moderate on T3, negligible on T1.

**B. Process-reward supervision for agent planning.**
Testing whether a ReAct agent with SME-labeled plan steps beats single-pass retrieval on T3/T4. Prior-art anchor: RAG-Gym's +19 F1 on HotpotQA. Expected result: the agent should use cross-refs where flat retrieval fails.

**C. SME few-shot vs self-generated CoT vs zero-shot, across model tiers.**
2×3 grid: mid-tier model × reasoning model × three prompting strategies. The counterargument test. Expected result based on Medprompt → o1: few-shot lift shrinks on reasoning models — *for clinical MCQA*. Open question in regulatory domain.

Each ablation gets a chart: metric on y-axis, condition on x-axis, faceted by question type. Faceting matters — aggregates hide where the action is.

## What I expect to find (a pre-registration) (~200 words)

Pre-register expectations before results are in. This is a credibility move and also protects against motivated reasoning.

- A will work; biggest gain on T2.
- B will work; biggest gain on T3.
- C is the one I don't know. If SME few-shot still helps on a reasoning model in the regulatory domain, that's a real finding about where domain specificity matters. If it doesn't help, the Medprompt → o1 story generalizes further than expected.

Whatever happens, the *shape* of the per-type effect is more informative than aggregate numbers.

## What's open and what's next (~200 words)

The deliverables:
- **Corpus** (≈200+ expert-authored Q&A pairs, normalized)
- **Benchmark** (≈30–50 stratified evaluation questions)
- **Harness** (MIRAGE-style eval, five metrics)

All three are independently useful. The corpus is shareable even if nobody agrees with my benchmark design.

What I'm deliberately not doing in v1:
- EPARs, variations, scientific advice
- Ontology/graph infrastructure
- Biomedical/clinical reasoning
- Multilingual

Those all matter. They're v2 candidates, gated on specific failure modes in v1.

## Closing (~150 words)

Two sentences that land the thesis:

> The biggest lesson from this project isn't about RAG architecture. It's that "involve the SME early" is too vague to be useful — the question is *at which layer*. The evidence suggests it's corpus curation and evaluation, not prompts and exemplars.

Invite people to look at the repo, report issues, propose ablations. Flag that the benchmark is small and that null results are fine — that's what small benchmarks are honest about.

## Things to avoid in the writing
- No "revolutionary" / "game-changing" language. You're making a modest contribution to an open gap.
- No uncritical claims about SME value. You're testing *where*, not whether.
- No graphics-heavy; one diagram of the pipeline, one chart per ablation, one table of question types.
- No "AI will replace regulatory writers" framing. The audience on LinkedIn will be hostile to that and it's not what the data says.
- No fabricated quotes or numbers from the literature — every stat needs a citation.

## Post-publication plan
- Cross-post excerpt (opening + closing) to LinkedIn, link to full post.
- Submit to relevant newsletters (Eugene Yan, TLDR AI, etc.) *only after* at least one person unconnected to you reads and gives feedback.
- Share in appropriate pharma-AI Slack/Discord communities without spamming.
- Expect first real response from MLGenX / MIRAGE-adjacent researchers if the methodology is sound.

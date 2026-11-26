# Direction review: answers a person can confirm — 2026-11-25

*Written by the lead assistant session (Claude Fable 5.2) on the owner's instruction of
2026-11-25 to propose a direction, have it reviewed adversarially, and plan the way forward.
Evidence: three independent reviews by subagents, read-only queries on `mlflow.db` and on
the live Neo4j graph, and a labelling of 60 stored claims by two model annotators. No model
call went through the project's API key, no store was written, and no code was changed.
Code state: `47d2cfa` on branch `pipeline-refresh`. Every decision on this page is the
assistant's, taken under the owner's delegation. The owner can overrule each one.*

*Added on 2026-11-26, on the owner's instruction: section 5.2, a vendor's benchmark of a
semantic layer, with one row in section 6.3 and two points in section 8. Added the same
day, after the owner asked about it: section 5.3, the vendor's technical overview and a
post it cites, with one point in section 8.*

## 1. The question

On 2026-11-25 the owner stated what this repository is for, beyond comparing retrieval
strategies:

1. It should become a **platform that compares strategies**, from simple vector retrieval
   through mixed strategies to graph and knowledge-graph strategies.
2. The **main focus** is to learn how project-specific reasoning can be made available to
   an agent, and how an assistant agent can guide a scientist during a project.
3. The pattern of interest: the agent first retrieves prior knowledge, then proposes, and
   **a person confirms before anything is acted on**.
4. That confirmation must be **efficient**. So the reasoning before it must be transparent
   and traceable, and where possible verifiable by automated tests.

Goal 1 is what the review of 2026-11-23 planned
([`2026-11-23_pkr_testbed_review.md`](2026-11-23_pkr_testbed_review.md), section 11): nine
question classes (C1 to C9) and a ladder of experiments (E0 to E9). Goals 2 to 4 had no
backlog row. The nearest items were the guidance arms (E5) and the citation check (E9), at
the far end of the ladder. This page asks what to change so that goals 2 to 4 are served
early, without building on defective parts.

### Terms used on this page

| Term | Meaning here |
|---|---|
| Question classes C1 to C9 | The nine kinds of question of the benchmark that this repository is building. Named on this page: C4 a comparison across products, C5 an aggregate ("how many", "list all"), C6 a question about versions or dates, C7 the reason for a decision, C8 a question that the corpus cannot answer, C9 a table or figure |
| Ladder, rung, E0 to E9 | The experiments, ordered from the cheapest system to the most expensive. One experiment is a rung. Named on this page: E0 an existing external tool, E1 all documents of one product in the prompt, E2 keyword search plus a tool that reads a document, E5 guidance for the agent (none, a written procedure, worked examples), E9 a check of the citations before the answer is given |
| Claim | One statement of an answer, together with the sources it cites |
| Typed derivation | A label on a claim that says how the claim follows from its sources: a restatement, a count, a comparison, an inference |
| Work unit | One implementation attempt for one backlog row, with its plan and task list under `.claude/work/`. One is open at a time |
| Checkpoint | A task at which the work stops until the owner has answered |
| Smoke run | A run on 3 questions that shows the code works. It is too small to be a result |
| Error census | A person reads stored claims and labels each as right or wrong, with the kind of error |
| Sitting | One session in which a person reviews a prepared set of answers, while the time and the missed errors are recorded |
| Audited miss rate | The share of wrong claims among the claims that the checks passed. A person finds it by reading a random sample |
| Lift | The score with the documents minus the score without them. It separates what the model remembers from what retrieval adds |
| Cohen's kappa | Agreement between two annotators, corrected for agreement by chance. 1 is full agreement, 0 is chance |

## 2. Verdict

1. **Repair the citation before adding anything to it.** Today a claim cites a URL. For
   72% of stored claims that URL returned more than one passage, so neither a test nor a
   person can tell which text the claim rests on. A claim must name the passage and quote
   it. This is a repair of a defect that the review of 2026-11-23 recorded (section 4,
   item 6), and it is the precondition of every later check. It becomes backlog row 18
   ([proposal](../next/answer_record.md)).
2. **By an assistant's labels, about six claims in ten restate a passage and four in ten
   need judgement.** Two model annotators sorted 60 stored claims, and no person checked
   them. Both called 37 of the 60 a restatement or a merge of what the agent received
   (62%; the 95% interval for a sample of 60 is about 49% to 73%). At least one of them
   called the other 23 an inference, a generalisation or unsupported (one of the 23 is an
   abstention). So a quote check could apply to about six claims in ten. Six to eight of
   those are merges, which need one quote per passage. No sampled claim was a count or a
   comparison (0 of 60; the other 291 claims were not inspected), so typed derivations
   would label almost nothing in today's answers.
3. **The first draft's measurement was circular, and it is dropped.** The first draft
   (option B of section 4) measured "review cost" by writing faults into stored answers
   and counting how many the checks catch. Each planned fault was the negation of one check. Detection would have been near
   100% by construction. Injected faults stay as regression tests of the checks. They are
   not a measurement.
4. **"Show the person only the exceptions" is not assumed.** It is the obvious way to make
   confirmation fast, and it is the part with the least support. It is tested with a
   person before it is built into any interface. The first number of that test is the
   errors a person misses in claims that the checks passed. Minutes come second.
5. **The order of the foundation stays.** The pipeline refresh (row 10), the corpus repair
   (row 11) and the metadata (row 13) come first for the same reasons as on 2026-11-23.
   The new benchmark (row 15) moves ahead of the MCP servers, and gains a small set of
   proposal-style questions.

## 3. What was measured on stored answers

The store is `mlflow.db` as it stood on 2026-11-25 (sha256 prefix `96278f889203b465`,
last written 2026-11-23). It holds 123 traces of earlier chat and evaluation runs. 108 of
them are finished agent or chat turns (root span `FunctionAgent.run`,
`AgentWorkflowAdapter.invoke` or `chat.turn`, status OK). 93 carry an answer with claims,
351 claims in total. The scripts, the sample and both label files are in
`$EMA_RESULTS_DIR/2026-11-25_direction_review/`.

**A limit that applies to every number below.** 92% of the 2,451 parsed passages are 420
characters long or shorter. They come from runs before the fix of 2026-11-23, when the
search tool showed the agent only the first 400 characters of a passage. Text that a claim
rests on may lie beyond that cut. The questions are the 45 benchmark items, drawn from 7
web pages, plus chat questions. These numbers describe the stored answers. They do not
describe what the repaired runner produces.

### 3.1 Five counts by plain code

Plain code means no model call. The five counts below show what such code can say about
the stored answers. They are not the four checks of the proposal for row 18: a stored
answer holds no passage tag and no quote, so only the first and the last count can be
repeated with that proposal's functions.

| Check | Result on 351 claims | Read it as |
|---|---|---|
| The claim is an exact piece of the answer text (after lower-casing and collapsing whitespace) | 317 pass, 34 fail. With the repository's own matcher, which also accepts a near match of 0.85 or more, 22 fail (the engineering reviewer's count) | The verbatim-span contract mostly holds |
| Every cited URL returned at least one passage in this run | 339 pass, 1 fails, 11 cite no URL | A citation to a source that was never retrieved is rare |
| Every cited URL returned exactly one passage | 89 pass (25%). For 251 claims (72%) at least one cited URL returned several passages. 11 cite no URL | **A URL does not identify the text behind a claim** |
| Every number in the claim occurs in the passages of the cited URLs | Of 206 claims with a number, 169 pass and 37 fail. A lenient variant, the number anywhere in the retrieved text, fails 4 of 198 (the engineering reviewer's count) | A number check raises alarms. Most of them are format differences such as "25,550", or numbers from the substance tool |
| Every sentence of the answer lies inside a claim | Between 110 of 446 and 135 of 366 sentences are uncovered, depending on how sentences are split | A quarter to a third of the answer text is asserted without a claim |

Answers without claims. By the lead's count, 15 of the 108 finished turns carry no answer
with claims. The engineering reviewer counted 106 finished agent runs, 5 of which lost their
structured answer and 8 more of which returned no claim. The two counts differ by two
turns and were not reconciled. The library turns the first
case into a warning (`llama_index/core/agent/workflow/base_agent.py:600-604`, llama-index-core
0.14.22), the runner returns plain text (`harness/agents/runner.py:49`), and nothing counts
either case.

### 3.2 What kind of claim an answer holds

**Method.** 60 claims were drawn at random from the 351 (seed 20261125). Each was shown with
its question and with the passages the agent received from the URLs it cites. Two subagents
labelled all 60 independently with one written codebook. Both are the same model family as
each other and as this page's author. **These are an assistant's labels. Nobody has checked
them, and agreement between two runs of similar models overstates what two people would
reach.**

| Label | Meaning | Annotator A | Annotator B |
|---|---|---|---|
| R | Restates one received passage | 33 | 32 |
| M | Joins statements from several passages, without a conclusion | 6 | 8 |
| C | A count, comparison or other arithmetic over values in the passages | 0 | 0 |
| G | States something general from particular instances | 2 | 6 |
| I | A conclusion that needs a reasoning step | 12 | 7 |
| U | Not in the received passages at all | 6 | 6 |
| X | None fits (one abstention) | 1 | 1 |

| Agreement | Value |
|---|---|
| Same label out of seven | 53 of 60 (88%), Cohen's kappa 0.82 |
| Same side of "restates or merges" against "needs judgement" | 55 of 60 (92%), kappa 0.81 |
| Both say restatement or merge | 37 of 60 (62%) |
| At least one says inference, generalisation, unsupported or none | 23 of 60 (38%) |
| Both say the received passages fully support the claim | 43 of 60 (72%) |
| Both say restatement or merge, and both say fully supported | 35 of 60 (58%) |
| Claims with a number | 39 of 60. Every number found in the passages: 36. Some missing: 3 |

The seven disagreements follow two patterns. A sentence from one product's assessment report is
stated as a general rule, or a single word such as "only" or "must" turns a restatement
into a conclusion. Annotator A called five of them an inference where B chose a
generalisation, a merge or a restatement.

### 3.3 What these numbers support, and what they do not

- **Supported:** a URL is not a citation. This holds on a full count, with no model in it.
- **Supported, as a lead:** most claims restate what was retrieved. A check that finds a
  verbatim quote in a named passage could therefore reach about six claims in ten.
- **Supported, as a lead:** about a quarter of the claims are not fully backed by what the
  agent received. Each annotator alone says so for 15 of 60 (25%); at least one of the two
  says so for 17 of 60 (28%). The 400-character cut can explain part of that. The rest is
  either the model's memory or a real error. Which one is the question that the lift
  metric (row 3) and a person's labels answer.
- **Not supported:** that typed derivations are worth building now. No claim in the sample
  computes anything. They become relevant when the benchmark holds aggregate and version
  questions (C5, C6) and table questions (C9), which it does not yet.
- **Not supported:** any statement about a reviewer's time. Nothing here involved a person.

## 4. The options, and how three reviews ranked them

Four options were written down without a preference and given to one reviewer. A detailed
design of option B was given to two more, each told to find what is wrong with it.

| Option | What it builds first |
|---|---|
| A. Ladder first | The order of 2026-11-23. The main focus is reached by the last rungs |
| B. A "reasoning record" early | A stored record per answer with typed claims and deterministic checks, and review cost measured by fault injection |
| C. A decision-task benchmark first | Proposal-style questions on assessment, withdrawal and variation reports, then the guidance arms |
| D. Adopt instead of build | An external hosted document service as the corpus, and a verification library for the checks |

| Reviewer | Task | Verdict |
|---|---|---|
| Independent ranking | Rank the options. Saw no preference | A fifth option, ahead of A, B, C, D: measure on stored answers, then the repair half of B, then the foundation, with C folded into the benchmark |
| Method | Attack the measurements of B | Accept with required changes. Passage-level quotes and stored checks are justified. The fault-injection measure, the "review load" number and review by exception are not valid as written |
| Engineering | Attack B against the code | Build with changes. Store the passage text, keep the output format loose, make the change additive, leave typed derivations out of the first version |

The lead's own preference before the reviews was B as written. All three reviews rejected
that form, for reasons that do not depend on each other. Section 5 lists what changed.

Why the other options lost:

- **A alone** leaves the main focus without a single scheduled item. The citation check
  (E9) has no backlog row.
- **C first** has no computed gold answer. With about 30 questions and a model as judge,
  differences between arms cannot be told from run-to-run variation. Its questions are
  kept and moved into the benchmark (row 15).
- **D** cannot run a graph strategy: the external service has no guidance pages and no
  links (review of 2026-11-23, section 9). It stays what that review made it, the E0
  comparison arm. Scores from an entailment model or a guardrail library are not the
  deterministic checks that goal 4 asks for.

## 5. What the reviews changed

| In the draft | After the reviews | The argument that changed it |
|---|---|---|
| Review cost is first measured by fault injection | Dropped as a measure. Injected faults are regression tests of the checks | Whoever writes the checks also writes the faults. The detection rate describes the list of faults, not errors that occur |
| A person sees only the claims that code could not settle | **Default to review.** Code settles a claim only when its quote is found verbatim in a passage the agent received, or when a value equals one computed from a table. Everything else goes to the person | A check that passes a claim by word overlap also passes a negation, a dropped condition and "should" turned into "must" |
| The agent labels each claim's derivation, and the label decides who checks it | The agent's own label never removes a claim from the person's list | An inference split into two restatements would pass every check |
| "Review load" per strategy: the share of claims settled by code | Replaced: review items per required fact of the gold answer, at equal correctness, with an audited miss rate. Needs the gold facts of row 15 | An agent can lower the share by making fewer and blander claims, or by quoting long passages |
| A sitting with a person, "later" | The sitting decides. Three arms: the full answer; the review list only; the review list plus random spot checks of passed claims. First number: errors missed in claims the checks passed | A reviewer who is shown only the flagged items is not shown the errors that no check flags |
| Typed derivations in version 0 | Deferred until the benchmark holds questions that need them | 0 of 60 sampled claims compute anything |
| A richer output format with a fixed list of types | No fixed list and no validator in the output class. Count lost answers first | One wrong value fails the whole answer, and 13 to 15 finished runs already carry no claims, unnoticed (section 3.1) |
| The record stores a chunk id and a hash of the passage | The record stores the passage text as the agent saw it | A chunk id is a position in a document. Row 10 replaces a changed document's chunks, after which an id cannot be checked again |
| Citations are re-keyed from URL to passage | Additive: two optional fields are filled, nothing is renamed | Re-keying touches 16 modules and 145 tests |

### 5.1 What published studies say

The reviewers named studies in support of their arguments. A separate literature session
then read 17 papers and checked every number it reports against the text of the paper. The
lead did not read the papers. The numbers below are as that session reported them. A
preprint or a report that was not peer reviewed is marked.

| Question | Finding | Source |
|---|---|---|
| Do injected faults stand for real ones? | Detectors trained on synthetic factual errors reached a label-balanced accuracy of 91.2 to 97.8 on held-out synthetic errors. On 500 human-annotated real errors of one dataset they reached 50.9 to 54.2, where 50 is chance. On a second dataset they reached 64.4 to 76.7 | Goyal and Durrett 2021 |
| | In software testing, with the size of the test suite held constant, the correlation between the share of injected faults detected and the detection of real faults fell from 0.35–0.75 to 0.05–0.20 | Papadakis et al. 2018 |
| | 73% of 357 real software faults were coupled to an injected one. Injected faults are useful as tests; their detection rate is not a score | Just et al. 2014 |
| Is a reviewer safe when an aid marks what to look at? | 80 people monitored a simulated flight task. On 6 events that the aid did not announce, those with the aid missed 2.44 on average, those without it 0.18 | Skitka 1998, a technical report, not peer reviewed |
| | 120 medical students checked prescriptions. A planted error was missed by 77.8% when decision support was present and silent, by 49.1% without decision support, and by 8.3% when the support flagged it | Lyell et al. 2017 |
| | A checklist of requirements that an agent had met did not change the accuracy of 12 reviewers and raised their confidence after a wrong approval | Grunde-McLaughlin et al. 2026, preprint |
| | With a wrong explanation from a model, 80 people verified claims at an accuracy of 0.35, against 0.49 without help | Si et al. 2024 |
| | Radiologists missed the same 50 cancers 12% of the time when half the cases were cancers and 30% of the time when about 1% were. A rare error is missed more often | Evans et al. 2013 |
| What makes a confirmation faster? | 48 people supervised a simulated agent. Confirming at intermediate checkpoints, instead of once at the end, cut the time per confirmation by 38%. Whether errors were detected was not reported in the sections read | Zhou et al. 2026 |
| | Among 731 people, explanations reduced over-reliance only where they made checking cheaper | Vasconcelos et al. 2023 |
| Which errors occur in answers built on retrieved text? | In 17,790 real responses, statements that the retrieved text does not support were more frequent than statements that contradict it | Niu et al. 2024 |
| Which carrier of knowledge helps an agent? | On multi-hop questions over synthetic documents, worked examples gave an F1 of 0.345, general principles 0.036 and no guidance 0.041 (one model) | Light et al. 2026 |
| | Four retrieved earlier cases raised an agent's F1 from 59.9 to 64.5 | Zhou et al. 2025, preprint |
| | Three to five recent decision records served as well as the full history, measured by text similarity only | Gupta et al. 2026 |

Three things the literature session searched for and did not find: a comparison of "flagged
items only" against "flagged items plus spot checks"; a measurement of exact-quote checks
themselves; and the share of claims in agent answers over technical documents that an exact
quote or an exact value settles. In the studies of Skitka and of Lyell the full display
stayed in view, so showing everything is not a safe baseline either.

**What these studies change in the plan for the sitting (row 20):**

1. The errors are real ones, labelled by a person, at the rate at which they occur.
   Answers without an error are mixed in.
2. In the arm that shows the full answer, a claim that passed its checks carries no mark of
   having passed. Or both variants are tested.
3. An instruction to verify, and a second reviewer, are not counted on. Neither reduced
   misses in the second study of Skitka's report (144 people).
4. Errors among the claims that passed may be too rare for one small sitting to count.
   Sittings are pooled, and one reviewer is reported as a case study.
5. A proposal is confirmed step by step, not as one finished text. The proposal-style
   questions of row 15 are therefore written so that each step carries its own claims and
   sources.

References, each read from the copy named:

- Evans, K. K. et al. (2013). If you don't find it often, you often don't find it: why some cancers are missed in breast cancer screening. *PLoS ONE* 8(5): e64366. doi:10.1371/journal.pone.0064366
- Goyal, T. and Durrett, G. (2021). Annotating and modeling fine-grained factuality in summarization. NAACL-HLT 2021, 1449–1462. arXiv:2104.04302
- Grunde-McLaughlin, M. et al. (2026). Overseeing agents without constant oversight: challenges and opportunities. Preprint. arXiv:2602.16844
- Gupta, A. et al. (2026). Context matters: evaluating context strategies for automated ADR generation using LLMs. Accepted at EASE 2026 according to the arXiv record. arXiv:2604.03826
- Just, R. et al. (2014). Are mutants a valid substitute for real faults in software testing? FSE 2014, 654–665. doi:10.1145/2635868.2635929
- Light, D. et al. (2026). Deep reasoning in general purpose agents via structured meta-cognition. NeurIPS 2026 according to the arXiv record. arXiv:2605.11388
- Lyell, D. et al. (2017). Automation bias in electronic prescribing. *BMC Medical Informatics and Decision Making* 17:28. doi:10.1186/s12911-017-0425-5
- Niu, C. et al. (2024). RAGTruth: a hallucination corpus for developing trustworthy retrieval-augmented language models. ACL 2024, 10862–10878. arXiv:2401.00396
- Papadakis, M. et al. (2018). Are mutation scores correlated with real fault detection? ICSE 2018, 537–548. doi:10.1145/3180155.3180183. Read from the authors' preprint
- Si, C. et al. (2024). Large language models help humans verify truthfulness – except when they are convincingly wrong. NAACL 2024, 1459–1474. arXiv:2310.12558
- Skitka, L. J. (1998). Automation: decision aid or decision maker? Final technical report, NASA Ames cooperative agreement NCC 2-986. NASA NTRS record 19980048379. Not peer reviewed
- Vasconcelos, H. et al. (2023). Explanations can reduce overreliance on AI systems during decision-making. *PACM HCI* 7 (CSCW1), article 129. arXiv:2212.06823
- Zhou, H. et al. (2025). Memento: fine-tuning LLM agents without fine-tuning LLMs. Preprint. arXiv:2508.16153
- Zhou, J. et al. (2026). When should users check? Modeling confirmation frequency in multi-step agentic AI tasks. CHI 2026. doi:10.1145/3772318.3790655. Read from arXiv:2510.05307

### 5.2 A vendor's benchmark of a semantic layer (added 2026-11-26)

The owner asked for the BIRD-Interact results published by AtScale to be included here.
AtScale sells semantic-layer software. A semantic layer holds the definitions of an
organisation's terms and measures in one place, and a program computes them. The agent asks
for "net revenue by region" and does not write the calculation itself.

**The benchmark.** BIRD-Interact (Huo et al. 2026) tests an agent that answers questions
from a database. The full set has 600 tasks. The questions are left ambiguous on purpose,
and a simulated user holds the missing definitions, so the agent has to ask. Each task has
a first question and a follow-up. In the paper's abstract the one model result is: "GPT-5
completes only 8.67% of tasks in c-Interact and 17.00% in a-Interact", the two test
settings.

A literature session read the paper in full and reports two findings from it; the lead did
not read the paper. Over 80% of 50 sampled failures came from an ambiguity that the agent
did not resolve. And the systems asked about one question per task, where 3.89 ambiguities
were planted per task on average. The agents ask too little.

**What the vendor measured.** Seven models, each with and without the layer, on the
benchmark's public test harness, in runs of 2026-10-03 to 2026-10-07. The vendor counts
410 of the 600 tasks as business questions. The other 190 are data-management tasks, which
a semantic layer does not touch. Share of the 410 first questions answered correctly:

| Model | Without the layer, one run | With the layer, first run | With the layer, best of three runs |
|---|---|---|---|
| Gemini 3.1 Pro | 36.1% | 55.9% | 62.2% |
| Claude Sonnet 5 | 25.9% | 50.2% | 56.6% |
| Claude Opus 4.6 | 22.7% | 45.4% | 53.7% |
| GPT-5 | 21.5% | 44.6% | 50.5% |
| Kimi K2.5 | 23.4% | 41.7% | 49.3% |
| Nemotron 3 Ultra | 23.2% | 41.2% | 45.9% |
| Grok 4.3 | 24.9% | 39.0% | 44.6% |

- The first run is the fair comparison: one run against one run. Its gain is 14.1 to 24.3
  points. The best of three runs is 4.7 to 8.3 points higher than the first run.
- The weakest model with the layer (39.0%) is above the strongest model without it (36.1%).
- Both answers of a task right, the first question and the follow-up: 10.2% to 16.1%
  without the layer, 25.6% to 45.6% with it (best of three runs against one run).
- The vendor's headline, "46% to 93%", is one model (Claude Sonnet 5) on 317 questions. The
  vendor set aside 93 of the 410 because it judged their answer key to be faulty. For the
  same model on all 410 it gives: "Unadjusted, leaderboard rules: 53.8% vs 25.9% (3-run
  mean)".

**The benchmark's own leaderboard**, read on 2026-11-26 from the data file of its website
(last changed 2026-11-23). It holds no entry by AtScale. For the 410 query tasks of the
full set, in the agentic setting:

| Entry | Dated | Verified by the benchmark's team | First question right | Follow-up also right |
|---|---|---|---|---|
| NVIDIA Auto-Ontology with Claude Opus 5.5 | 2026-11-11 | yes | 42.0% (172 of 410) | 24.9% (102 of 410) |
| AIDBS-DataAgent | 2026-10-27 | no | 37.1% | 23.4% |
| Quick-BlendedIntelligence | 2026-09-15 | no | 31.7% | 17.3% |
| Claude Opus 4.6 alone | 2026-02-17 | no | 19.5% | 12.2% |

The entries used different simulated users, so the rows are not a clean comparison. Four of
the vendor's seven first-run figures above lie over the verified leader's 42.0%.
The leader's evaluation code runs no arm with the same model and without the ontology on this
benchmark, as the literature session reports from its README. The table therefore shows no
measured gain for the ontology.

Auto-Ontology is an open library (Apache-2.0). It builds an ontology automatically from a
database's catalogue, keys, views and query history: terms with descriptions, the columns
each term maps to, joins, and named calculations. People certify the elements. The agent
searches this ontology, and its query is checked against the catalogue before it runs. Its
README states the limit: "With one well-modeled source and a fixed set of questions, direct
SQL may be enough."

**What to hold against it.** Each point is the vendor's own statement, from its methodology
document:

1. The vendor ran and submitted the results. "Results are preliminary and not yet verified
   by the BIRD team."
2. The 22 semantic models were generated by the vendor's software "from the same context
   the raw arm saw, then tuned on this benchmark". An audit of 23 September "removed every
   element traceable to the answer key". The layer was therefore fitted to the questions it
   is scored on.
3. "Only the AtScale agent was told not to round."
4. GPT-5 had another simulated user (GPT-4o) than the other six models (Claude Haiku 4.5).
5. "Adjusted rates can't be compared with the leaderboard's success rate."
6. The vendor's three web pages differ: one table has six models, another seven; one page
   says the arm without the layer got the documentation, two say the benchmark withholds
   it; the 93 questions are set aside for a faulty answer key on one page and as questions
   that cannot be answered as asked on another; and one page dates the runs to 11 to 20
   September, the methodology document to 3 to 7 October.

No independent group has repeated the comparison. A second vendor has published a paired
benchmark of the same kind (arXiv:2604.25149); nobody in this project has read it.

**What it means for the direction.**

1. **One more carrier of project knowledge.** Section 6.3 asks which carrier helps an
   agent: the documents alone, a vocabulary, entity tables, a written procedure, worked
   examples, a graph tool. The semantic layer is a seventh: terms and measures that are
   defined once, in a file a person can read and a test can check, and computed by a tool.
   The result above is evidence that this carrier can matter more than the choice of model.
   It is weak evidence, for the reasons listed.
2. **Where it would apply here.** Not to questions answered from text. It applies to the
   questions with a computed answer (C5, C6, C8) over the entity tables of row 13: counts,
   durations and comparisons over products, statuses and dates. A definition would say, for
   example, which statuses count as "authorised", or which two dates bound a review time.
3. **Why it fits the main focus.** A definition is a small thing a person confirms once.
   An answer that names the definition it used can then be checked by code: the value is
   recomputed from the table. This is the "exact value" case of rule 1 in section 6.1.
4. **A comparison for the ladder, not built now.** For the computed questions, two arms on
   the same tables: the agent gets the tables and their column descriptions; or it gets a
   tool that serves defined terms and measures as well. One run per arm, the same judge, n
   and the failed rows stated. The proposal of row 16 decides whether this arm is run.
5. **How much it matters here: little today.** Writing a database query from a question
   matters where the answers are computed from tables. In this repository no question is
   of that kind yet: 0 of 60 sampled claims compute anything (section 5). EMA's entity
   tables will be a few tables with a few dozen columns, which is the case where direct
   queries or a few fixed tools may be enough. The number of computed questions in
   benchmark v0 (row 15) decides whether the comparison of point 4 is worth a run. What
   carries over without any SQL is the method: a term a person certifies once, a generated
   step that code checks before it runs, an answer that returns the steps it took, and an
   agent that asks when a question is ambiguous. The last one bears on goals 2 to 4: a
   question to the person before the answer is a confirmation that costs one line.
6. **Three lessons from how the result was produced.** A best-of-three number is not
   compared with a single run. Definitions are not tuned on the questions they are scored
   on: the held-out product of row 16 covers this. And a computed gold answer is audited
   before a score is read: the vendor disputes 93 of 410 answer keys of a peer-reviewed
   benchmark.

Sources, read on 2026-11-26. The vendor's pages and its methodology document were read by
the lead, the pages through a fetch tool and the document as text:

- AtScale. BIRD-Interact Benchmark Results: Methodology and Analysis. PDF, 30 pages,
  created 2026-10-12. <https://www.atscale.com/resource/bird-interact-benchmark-ebook/>
- AtScale. How AI scores on BIRD-Interact. <https://www.atscale.com/benchmarks/bird-interact-results/>
- AtScale. A better LLM isn't the biggest upgrade for Text-to-SQL. 2026-10-28.
  <https://www.atscale.com/blog/semantic-layer-text-to-sql-accuracy/>
- BIRD-Interact leaderboard. <https://bird-interact.github.io/>, data file
  `script/task-category-results.js` of the repository `bird-interact/bird-interact.github.io`.
- NVIDIA. Auto Ontology. README of <https://github.com/NVIDIA/auto-ontology>.
- Huo, N. et al. (2026). BIRD-INTERACT: Re-imagining Text-to-SQL Evaluation for Large
  Language Models via Lens of Dynamic Interactions. ICLR 2026 (oral) according to the arXiv
  record. arXiv:2510.05318. Only the abstract page was read.

### 5.3 The vendor's technical overview, and a post it cites (added 2026-11-26)

The owner asked whether the vendor's white paper "AtScale for AI: Technical Overview" was
included. It was not. The lead read it in full on 2026-11-26, and also the one post it
cites that bears on this page.

**The white paper.** 53 pages. Its title page says "Version 274 · October 14, 2026", and
its file name says v271. It describes the vendor's product. It reports no new accuracy
run. Its benchmark numbers are those of the methodology document of section 5.2, with one
exception: an example of one task over three runs, whose source is a draft paper of the
vendor that the literature session did not find in public. It describes a loop, "model,
measure, compute, repeat", and names four places where a person acts in it:

1. **Answers a clarifying question.** The software asks when a term has more than one
   definition. The answer is stored "as a rule or synonym, so the same question isn't asked
   twice". One person's answer then holds for the next person, and the paper names no
   review of such a rule.
2. **Decides a conflict.** Agents draft the definitions from dashboards, spreadsheets,
   documentation, glossaries and database schemas. They "flag the calls only a person can
   make, such as which of two revenue definitions the business reports".
3. **Approves a change.** "Every change arrives as a reviewable SML diff. Nothing ships
   until the data engineer approves it". The definitions are files in Git.
4. **Sets the pass threshold** of a test set. A test case is a question, a reference query
   and its result.

What the software then does with a confirmation, by the paper's description:

- **It reruns the tests on a change.** "When a model, instruction or schema changes,
  Canary reruns the suite to catch regressions."
- **A miss becomes a proposed fix. A pass becomes an example:** a "certified query" that
  is offered to the agent when a similar question arrives.
- **Every answer** "comes back with the metric's definition and the SQL that produced it".

The drafting component and the testing component are "in private preview". On the
remaining errors the paper says: "AtScale hasn't yet published a rerun with these fixes
applied, so 100% is still the target."

**What it changes in section 5.2.**

1. **The memory learned from the benchmark's grader.** "In the benchmark, a query is
   certified when the grader passes the answer". In the paper's example the agent asked
   the simulated user in run 1 and passed. "In runs 2 and 3, semantic memory offered the
   certified query, and the AI agent used the same filter pair the user had chosen in
   run 1." The best-of-three figures, and the 93% headline (a best run of three with the
   memory on, by the paper's note 8), therefore include answers that the grader had
   already confirmed for the same question. Only the first run is free of this. Section
   5.2 compares the first runs. For the 317 questions of the headline no first run is
   published: the methodology document gives a best run (93%) and a mean of three runs
   (90.6%). The mean includes runs 2 and 3, and the best run may be one of them.
2. **The white paper does not say that the definitions were tuned on the benchmark.** It
   says that the software "modeled all 22 databases behind the 600 questions in a couple
   of hours, with object descriptions drawn from BIRD's own corpus". The audit is not
   mentioned. Point 2 of the list in section 5.2 stands.
3. **A table that section 5.2 left out: the cost of model calls per right answer.** It is
   in the methodology document too. Without the layer and with it: from $0.17 and $0.14
   (Grok 4.3) to $0.87 and $0.73 (Claude Opus 4.6). The paper states a fall of 7% to 44%,
   about 21% on average; the seven rows of its table give a mean of 21.3%. The measure is
   the mean model spend per run at list prices, divided by the first questions passed
   over all 600 tasks. Two of the three runs with the layer could reuse the memory, and
   the largest fall (Nemotron 3 Ultra, 44%) rests on runs 2 and 3 only. The cost of the
   database and the cost of the layer (the licence, the modeller's work) are not in it.
4. **Its case against ontologies and knowledge graphs is an argument, not a
   measurement.** "Context doesn't compute anything, though: the model can ignore or
   misread it, and it still writes the query." No run in the vendor's material gives the
   agent the same definitions as text or as a graph. The literature session adds a
   reading: the vendor's own definitions are compiled into what the paper calls a
   "semantic graph", and code walks it. The argument is therefore about who uses a graph,
   the model or code, and not against graphs.

**The post it cites.** The data team of Anthropic describes its own analytics agent
(2026-06-03). It is a company's report on its own system. No data and no test set are
published. The white paper quotes three numbers from it: hand-written files of
definitions and procedures ("skills") lifted the accuracy on the team's tests from 21% to
about 95%, and the accuracy fell to about 65% within a month as the data changed. All
three are in the post. The white paper leaves out the rest:

- **How the decay was stopped.** The files moved into the repository of the data models.
  "A code-review hook flags any reporting-model change that doesn't touch a skill file.
  Roughly 90% of our data-model PRs now include a skill change in the same diff."
- **That team uses a semantic layer too,** and its agent must try it first. Files of
  definitions and a semantic layer are two layers of one system there, not alternatives.
- **Definitions written by a model failed there.** "bootstrapping the semantic layer by
  having an LLM auto-generate metric definitions from raw tables and query logs" gave
  "plausible-looking definitions" and "was net-negative on our evals versus a smaller,
  human-curated layer".
- **Search over earlier work did not help.** Access to thousands of earlier queries
  "moved accuracy by less than a point". For the questions the agent got wrong, the answer
  was in those queries "About 80% of the time". "The information was there, the agent saw
  it, and it still didn't use it." What helped was a small set of reference documents per
  domain, written from that material.
- **A correction becomes a test and a fix.** "We also continuously harvest every time a
  stakeholder corrects the agent in a thread as that correction is a candidate eval." A
  scheduled agent drafts a one-line fix to the reference document and opens a change
  request for the owner of the domain.
- **What a reviewing model costs.** A second model that challenges the answer raised the
  accuracy on the test set by 6% "at the cost of 32% more tokens and 72% higher latency".
  The post does not say whether the 6% are points or a relative gain. A cheaper reviewing
  model "lost most of the accuracy wins".
- **What stays open.** "The answer is wrong, but looks plausible and is used without
  objection." For this case: "we don't have a robust solution yet."

**What it means for the direction.** The lead's reading.

1. **Both sources describe goals 2 to 4 as a loop, and this repository has the first half
   of it.** A person's verdict is stored today: the thumbs and the verdicts per citation go
   to MLflow, and rated answers feed the few-shot cache. The second half is missing. A
   verdict does not become a test case. The benchmark run is started by hand, and no
   change of a prompt, a recipe or the routing table triggers it. A point for the
   proposals of rows 18 and 20 to take up or reject, not built now: the answer record
   holds what a replay needs, which is the question, the claim, the passage with its text
   hash, the verdict, who gave it and when.
2. **Worked examples are tested on new questions.** The vendor's memory gained on the
   same questions asked again. The other team gained under one point from search over
   earlier work. The few-shot cache of this repository works the same way: it retrieves
   rated answers by similarity to the question (`harness/fewshot_inject.py`). Light et
   al. (section 5.1) report a large gain from worked examples on synthetic documents. The
   literature session adds Rabelo et al. (2026): on 48 questions over a database of
   batch records, worked examples from a pool that shares no item with the benchmark
   raised accuracy from 23–25% to 46–48%. The evidence points both ways. So the arm
   "worked examples" of E5 runs on the held-out product, and its example store holds no
   question of the test set.
3. **A model may draft a definition. A person owns it.** The two sources disagree on the
   drafting and agree on the ownership. This applies to every graph or ontology that is
   built automatically. Such an arm of the ladder needs a part that a person has
   certified, and a comparison with a small hand-made one.
4. **An authored file that describes a changing source decays.** Here the routing table,
   the hub file and the prompts describe a corpus that changes with each scrape. Nothing
   flags a file that no longer matches the corpus. Noted as a gap. No backlog row is
   added for it.
5. **A reviewing step has a price.** The check of the citations before the answer (E9)
   reports the accuracy it gains together with the tokens and the seconds it adds.
6. **The silent error stays the hard case** in both sources: an answer that looks right
   and is used without objection. The studies on over-reliance in section 5.1 say the
   same. The sitting of row 20 measures it.

Sources, read by the lead on 2026-11-26 as text:

- AtScale. AtScale for AI: Technical Overview. PDF, 53 pages, "Version 274 · October 14,
  2026". <https://www.atscale.com/resource/atscale-for-ai-technical-overview/>, file
  `AtScale-for-AI-Technical-Overview-v271.pdf`, SHA-256 `cf573488…feb58e6`.
- Cherry, J., Peng, C., Jiao, J., Leder, J. and Chang, C. (2026-06-03). How Anthropic
  enables self-service data analytics with Claude. Blog post.
  <https://claude.com/blog/how-anthropic-enables-self-service-data-analytics-with-claude>

A literature session checked both documents against its own copies on the same day and
corrected three points of the lead's first version of this section. Read by that session
and not by the lead:

- Rabelo, L. et al. (2026). RAG-grounded natural-language-to-SQL for on-premise deployment
  in regulated batch manufacturing. *Applied Sciences* 16(21), 10971.
  doi:10.3390/app162110971

## 6. The direction

### 6.1 Five rules for anything built under goals 2 to 4

1. **Default to review.** A claim is settled by code only on an exact quote or an exact
   value. A heuristic may fail a claim. It never passes one.
2. **The agent does not route its own review.** What the agent says about a claim is
   stored and shown. It never decides whether a person sees the claim.
3. **Measure on errors that occurred.** Recall of a check is reported on claims that a
   person labelled as wrong, per kind of error, with n. Injected faults test the code.
4. **No statement about a reviewer's time without a reviewer.** One person gives a case
   study and is reported as one.
5. **Count what is lost.** An answer without a structured output, or without claims, is a
   counted outcome of the run, like a failed run since 2026-11-23.

### 6.2 The order of work

| Step | Backlog row | What it gives goals 2 to 4 |
|---|---|---|
| 1 | 10, in progress | The graph can be refreshed. Nothing later reaches the graph without it |
| 2 | **18, new**: the answer record | A claim names its passage and quotes it. Four checks produce numbers per run. Lost answers are counted. The same record is written by the chat app and by the evaluation runner |
| 3 | 11, then 13 | A repaired corpus. Product number, status and dates on each document: the "project", and what a recomputed count needs, or a check that a cited document is the current version |
| 4 | 14, narrowed: full-text search and a read tool as plain tools | The cheap rungs E1 and E2 |
| 5 | 15: benchmark v0, extended | Required facts per gold answer. About six proposal-style questions built from assessment, withdrawal and variation reports. Questions with computed gold (C5, C6, C8). C5 and C6 are where typed derivations are first needed |
| 6 | **20, new**: the error census and the review sitting | A person labels real errors. The sitting of section 5 answers whether a checked record helps |
| 7 | 16: the ladder runs | Every rung reports answer quality and what it leaves for a person. The guidance arms (E5) compare the carriers of project knowledge: none, a written procedure, worked examples |
| 8 | **19, new**: the MCP servers | Split from row 14. They serve the E0 arm, which needs the benchmark to run on |

Row 3, the closed-book baseline, keeps its place in `Now`. It gains one more reason. At
least one annotator found 17 of the 60 sampled claims not fully backed by what the agent
received, and only a closed-book run separates the model's memory from an error.

### 6.3 Which question each step answers

| Question | Answered by | Needs a person |
|---|---|---|
| Which carrier of project knowledge helps an agent: the documents alone, a vocabulary, entity tables, a written procedure, worked examples, a graph tool? | The ladder runs (row 16) on benchmark v0, one product held out | For the gold answers of C1 to C4 and C7 |
| What must an answer carry so that its claims can be checked? | Row 18, then the typed derivations with row 15 | No |
| Which errors do the checks catch, and which do they miss? | The error census (row 20) | Yes: the labels are the measurement |
| Does a checked record let a person confirm faster without missing more? | The sitting (row 20) | Yes |
| Do retrieval strategies differ in what they leave for a person? | The second number of every ladder run (row 16) | For the audited sample |
| Can an agent draft a proposal from precedent? | The proposal-style questions of row 15, after a closed-book check | For the gold answers |
| Do terms and measures that are defined once and computed by a tool help on questions with a computed answer? (added 2026-11-26, section 5.2) | An arm of the ladder runs on C5, C6 and C8, if the proposal of row 16 takes it up | For the definitions, which a person confirms once |

## 7. What needs the owner

1. **A second open work unit, or not.** `BACKLOG.md` allows one. Unit 27 (row 10) is open
   and will stop at a checkpoint that needs the owner. Row 18 touches `harness/agents/`,
   `harness/tools/` and `harness/eval/`. Unit 27 touches `harness/indexing/`,
   `corpus/parsers/` and `scripts/`. No code file is shared. The bookkeeping is:
   `ACTIVE_WORK`, `docs/pm/` and one checkout. Recommendation: keep the rule, and open
   row 18 when unit 27 ships or waits at its checkpoint.
2. **The checkpoint of unit 27** (TASK-015). Two runs behind it write to the live stores:
   a backfill on the live graph (TASK-016) and one document through the live pipeline
   (TASK-017).
3. **Time for labels.** The census needs a person's verdict on real claims. A first pass of
   30 claims, pre-sorted by the assistant's labels, shows whether those labels can be
   trusted for the rest.
4. **A smoke run** of 3 items for row 18. Within the limit that needs no question
   (`CLAUDE.md`, rule 4), named here so that it is not a surprise.

## 8. Not verified

- Section 5.2 rests on a vendor's own publications and on the benchmark's leaderboard.
  Nothing in it was run here. The leaderboard rows were read from the data file of the
  benchmark's website, not from the rendered page. Of the benchmark's paper only the
  abstract page was read, and of Auto-Ontology only its README.
- Whether a semantic layer helps on questions over EMA's entity tables is not known. The
  benchmark's databases are business databases, and its questions are not about documents.
- Section 5.3 rests on a vendor's product description and on one company's post about its
  own system. Neither publishes its data or its test set. Every number in it is the
  authors' own report. Nothing in it was run here. Both systems answer questions from
  database tables, not from documents.
- The lead has not read the studies of section 5.1. A literature session read them and
  checked each number against the paper. Its notes are kept outside this repository.
  Studies that the reviewers named and that nobody has read since are not cited here.
- No run was made with a claim that cites a passage and a quote. Whether the model fills
  those fields reliably is unknown. The engineering reviewer found that 8 of 25 quotes which the
  model had written unprompted match their passage exactly.
- The Claude API has a citations feature that returns pointers into supplied text. Whether
  it can replace a model-written quote in this agent, which produces its answer through a
  forced tool call, was not tested. Row 18's exploration checks it against the installed
  versions.
- The labels of section 3.2 are an assistant's. No person has reviewed one.
- The stored answers predate the 2,000-character passages. Every share in section 3 may
  move when the runner of 2026-11-23 produces new traces.

## 9. Found on the way

- `public/elements/` is in `.gitignore` (line 238), so the citation review panel
  `public/elements/CitationReview.jsx` that `CLAUDE.md` and `docs/CITATIONS.md` describe
  is not in the repository. Belongs to row 12 (docs and setup).
- An earlier count by the lead, "266 refusal assessment reports", was wrong and is
  corrected here. 266 documents have "refusal" in the title: 217 are paediatric plan
  decisions and 41 are assessment reports. The graph holds 270 documents of type
  `withdrawal-report` and 301 of type `withdrawal-letter` (Cypher on the live graph,
  2026-11-25, grouped by `doc_type`).
- Lines of `CLAUDE.md` that are out of date, reported by the session that implements
  row 10 (line numbers at `c2fbfea`). They belong to row 12. No assistant session edits that
  file on its own:
  - line 151 says "736 tests, 18 s". On 2026-11-25 `make test` printed 786 passed.
  - line 153 says `make test-live` runs "the 7 tests that read the live MongoDB". There are
    13 tests marked `integration` now. The 6 new ones need a throwaway Neo4j, named by
    `EMA_SCRATCH_NEO4J_URI`, and are skipped without it.
  - lines 241–242 say that `reset=True` and `--reset` "delete the whole live graph". Since
    row 10 they delete every `:Document` and `:Chunk` node in batches and keep other nodes.
    They still delete, and still need the owner's yes.
  - line 138 says the join at ingest keeps the labels on a rebuild. That holds for a
    document that a build writes. A label change on an existing document still needs
    `scripts/propagate_metadata_to_graph.py`.
  - line 143 names `corpus/sources/synthetic_legacy_reader.py`, deleted in LIR-012. Line 133
    says MongoDB must run in the pinned container; the native `mongod` is what runs.

# Benchmark v0: nine classes, four products, and facts a person can check

**Status:** proposed 2026-11-25 · backlog row 15 · no work unit yet · drafting can start after the
owner's answers; the computed items wait for row 13, Stage 1

Written from the review of 2026-11-23
([`../eval/2026-11-23_pkr_testbed_review.md`](../eval/2026-11-23_pkr_testbed_review.md), sections 2
and 5) and the direction review of 2026-11-25
([`../eval/2026-11-25_direction_review.md`](../eval/2026-11-25_direction_review.md), sections 5 and
6). Every count is from 2026-11-25, by a read-only query on the live MongoDB and Neo4j or from
EMA's feed files on disk, unless marked "from the review of 2026-11-23, not re-checked". The code
was read at `0de00d7`. `/explore` checks all of it again.

Terms. A *class* is a kind of question, C1 to C9. A *rung* is one experiment of the ladder E0 to
E9, from the cheapest system to the most expensive. A *product* is a centrally authorised medicine
with EMA's *product number*, such as `EMEA/H/C/005269`; it stands in for a "project". A *feed* is a
JSON file that EMA publishes as website data. A *must-have fact* is one short statement that a
correct answer has to contain. A gold answer is *computed* when a query on an EMA table produces
it. *Closed-book* means without retrieval. *Lift* is the open-book score minus the closed-book one.

## The problem

Every comparison of retrieval strategies here rests on 45 questions. They are too narrow for it.

1. **Seven pages, three classes.** The 45 items cite 7 HTML pages, and 14 cite the same page. The
   graph holds 79,882 documents, 57,925 of them PDFs. T1 and T2 ask for a single fact (C1), the 10
   T3 items have one source each (C2), the 5 T4 items two or three (C3). Six classes have no item.
2. **Nothing reads the gold sources.** The runner passes `question` and `gold_answer` to the judge
   and groups by `type` (`harness/eval/runner.py:34`, `:93-104`). No file under `harness/` or
   `scripts/` reads `gold_sources`. All 52 have `page: null`, and `zero_shot_known` is empty.
3. **One paragraph, one grade.** The judge returns 1 to 5 for a whole answer, so nothing says
   which part is missing. The owner's main focus counts what an answer leaves for a person per
   fact (direction review, section 5). And no item asks for a proposal in steps.

## The idea

Add one file of 30 items beside the 45, on the documents of four related products: three for
development and one held out. Each item states its class, its product, its gold sources with a
verbatim quote, and its must-have facts. Eleven items take their gold answer from a query on EMA's
own tables. Six ask for a proposal in steps, on documents that record a refusal, a withdrawal or a
review of a medicine's status, each with its grounds. An assistant drafts the other 19 items, and
each stays labelled so until the owner has reviewed it. Scoring runs per item, in three repeats.

## What it deliberately does not do

- **No new retrieval strategy**, tool, index or answering prompt.
- **No model-written gold answer presented as an expert's.** `author` and `review_status` travel
  with every item and with every number computed from it.
- **No benchmark number.** A smoke run of 3 items shows that the scorer works. Results are row 16.
- **No tool writes an authored benchmark file**, and the 45 items do not change. A generator
  writes a candidate file, and a person promotes a line.
- **No figure question** (row 17), **no item built on absence from a list**, **no audited miss
  rate** (it needs a person; row 20), and no new scrape.

## What the stores hold, checked on 2026-11-25

### Products

**The join.** The graph has no product property. The join used here is the URL: EMA's documents
export of 2026-07-13 (`.tmp/ema_documents_export.json`, 69,887 records) gives a product number for
20,204 records. 13,667 of them are PDFs of the graph, in 2,137 products, and 2,130 of those join
the medicines feed (2,649 medicines, 2,271 for human use). The join is exact where the export has
a number, and 12,945 of the 13,626 PDFs of these 2,130 products (95.0%) are also linked from the
product's own page. Three limits. It reads a download, not a store: nothing in Mongo or Neo4j
holds the number until row 13. The export is 6.5 months newer than the scrape of 2025-12-28, and
for 148 graph documents it gives a first publication date after the scrape. Probably EMA replaced
the file at that URL; this was not checked. And 0 of 270 withdrawal reports and 0 of 2,314
referral documents carry a number, while all 41 refusal reports do.

Eight candidates, with graph documents by the type in EMA's export. AR: assessment report, or the
older "scientific discussion". A variation is a change to an authorised medicine. Text: the stored
text in million characters.

| Product | Number | Active substance | Authorised | In graph / in export | AR | Procedural steps | Variation reports | Product information | Safety | Orphan, paediatric | Other | Text |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Kalydeco | `EMEA/H/C/002494` | ivacaftor | 2012-07-23 | 29 / 34 | 1 | 2 | 18 | 1 | 1 | 4 | 2 | 4.33 |
| Orkambi | `EMEA/H/C/003954` | lumacaftor, ivacaftor | 2015-11-19 | 18 / 22 | 1 | 2 | 11 | 1 | 1 | 0 | 2 | 1.62 |
| Symkevi | `EMEA/H/C/004682` | tezacaftor, ivacaftor | 2018-10-31 | 10 / 14 | 1 | 1 | 3 | 0 | 1 | 1 | 3 | 1.14 |
| Kaftrio | `EMEA/H/C/005269` | ivacaftor, tezacaftor, elexacaftor | 2020-08-21 | 23 / 24 | 2 | 2 | 11 | 1 | 2 | 3 | 2 | 2.13 |
| Alyftrek | `EMEA/H/C/006382` | deutivacaftor, tezacaftor, vanzacaftor | 2025-06-30 | 6 / 7 | 1 | 0 | 0 | 1 | 0 | 1 | 3 | 0.76 |
| Keppra | `EMEA/H/C/000277` | levetiracetam | 2000-09-29 | 26 / 31 | 1 | 4 | 16 | 1 | 2 | 0 | 2 | 1.12 |
| Spikevax | `EMEA/H/C/005791` | COVID-19 mRNA vaccine | 2021-01-06 | 46 / 67 | 1 | 2 | 18 | 1 | 10 | 0 | 14 | 12.69 |
| Humira | `EMEA/H/C/000481` | adalimumab | 2003-09-08 | 57 / 69 | 0 | 2 | 51 | 1 | 0 | 1 | 2 | 4.03 |

**Recommended: Kalydeco, Orkambi and Kaftrio, with Alyftrek held out.** Symkevi is the reserve.

1. The three share the substance ivacaftor, and Kaftrio and Alyftrek share tezacaftor. Each has an
   assessment report, procedural steps, 11 to 18 variation reports and a safety document.
2. Kalydeco and Kaftrio have three orphan maintenance reports each: reviews of whether a medicine
   for a rare disease keeps its orphan status. Each ends in a fixed list of conclusions.
3. `WS-2551` (2025-07-02) is one variation report for Kalydeco and Kaftrio. It is a worksharing
   procedure: one application for several medicines. 8 of the 45 items cite the guidance on it.
4. Alyftrek is the newest and the successor of the other three: authorised on 2025-06-30, with 6
   graph documents first published on 2025-09-23. "Held out" means that no prompt, worked example
   or written procedure of rung E5 is built from its documents, and its items are reported apart.

**No product can be called post-cutoff today.** `harness/configs/models.yaml` records no training
cutoff. The data gives the upper end only: the newest authorisation in the medicines feed is
2025-11-28, and 1,899 graph documents were first published between 2025-07-01 and the scrape, 984
of them since 2025-10-01. For a model trained after the scrape, no graph document is new.

Against the others: Spikevax is a COVID-19 vaccine, which a model is likely to remember (an
assumption). Humira has no initial assessment report in the graph. Keppra shares no substance with
a second rich product. Two limits of the recommended set. It is one family in one disease (open
question 1). And three of the four exceed one prompt: at 4 characters per token, an assumption,
Kalydeco is about 1.08 million tokens and Alyftrek 0.19 million. The proposal for row 16 has to say
which documents rung E1 loads. The graph also lacks 5 of Kalydeco's 34 documents, 4 of Orkambi's
22, 1 of Kaftrio's 24 and 1 of Alyftrek's 7.

### Documents with a negative or contested outcome

| Kind | In the graph | First published 2025-07-01 or later | Where the grounds are |
|---|---|---|---|
| Assessment reports with "refusal" in the URL | 41, all with a product number | 4 | the section "Recommendations", a list of grounds |
| `withdrawal-report` | 270, none with a product number | 13 | section 1, the major objections that stood at withdrawal |
| `variation-report` | 2,772, 8 of them with "refusal" in the URL | not counted | the conclusion on benefit and risk |
| `orphan-maintenance-report`, `-post` | 152 and 41 | 19 | the last section, the committee's position |
| `referral` | 2,314, none with a product number | not counted | not read |

Four documents were read. The refusal assessment report for Kizfizo (`EMA/96948/2025`, published
2025-11-14) lists the grounds after a re-examination, which the applicant requests. The first: one
uncontrolled phase II study and one retrospective study showed limited activity, and no clinical
benefit was shown. The withdrawal assessment report for Izelvay (`EMA/503729/2024`) names in
section 1 the one major objection that stood. The one for Dupixent II-0083 (`EMA/67383/2025`)
concludes a negative balance of benefit and risk. The orphan maintenance report for Kaftrio and
`WS-2551` ends in four conclusions in a fixed order: the indication lies within the orphan
condition, the prevalence is about 1 in 10,000, the condition is life-threatening, and no
satisfactory method is authorised for all patients. Alyftrek's report ends in the same four.

So a proposal item gives the evidence of a case and asks: "Propose the outcome of the assessment,
with one ground per step." Its gold steps are the grounds listed in the report, each with its
quote. That report is withheld from retrieval (open question 2).

### Tables for the computed items

**The feeds are not in Mongo.** `web_items` has 15 feed URLs, each with a content type and no
body. `parsed_documents` has no `.json` URL, and `document_metadata` (92,630 rows) holds one feed
field, `doc_type`. Eleven feed bodies are files of the JSON spider, dated 2025-12-28. Stage 1 of
row 13 ([`document_metadata_and_entities.md`](document_metadata_and_entities.md)) writes the tables.

| Class | Question | Query | Answer on the feed copy of 2025-12-28 |
|---|---|---|---|
| C5 | How many medicines for human use on EMA's list contain ivacaftor? | medicines: `active_substance`, split at `;`, holds the whole name | 4: Kalydeco, Orkambi, Symkevi, Kaftrio. A substring match returns 5, because "deutivacaftor" contains "ivacaftor" |
| C6 | Which revision of the guideline on the evaluation of anticancer medicines is the newest adopted one? | documents feed: reference number holding `205/95`, status `Adopted`, newest publication date | Revision 6, `EMA/CHMP/205/95 Rev.6`, published 2024-01-23 |
| C6 | Which is the newest variation report for Kaftrio? | documents feed: product `EMEA/H/C/005269`, type `variation-report`, newest publication date | `WS-2551`, 2025-07-02. All 11 are in the graph |
| C8 | On which grounds was the marketing authorisation of Alyftrek refused? | `medicines.find_one({"_id": "EMEA/H/C/006382"})` | The premise is false: status `Authorised`, authorised 2025-06-30, no refusal date |

- **A computed answer still needs a well-posed question.** The feed lists 181 biosimilars, 239
  orphan medicines and 58 conditional approvals for human use; 135, 155 and 44 are `Authorised`.
- **EMA's list and the graph can disagree.** The adopted Revision 6 is in `web_items` and has no
  row in `parsed_documents`. The graph holds Revisions 3, 4 and 5 and the draft of Revision 6, so
  an agent on today's graph answers "Revision 5". The item is fair only after row 11.
- **Absence from a feed proves nothing.** The safety-assessment feed (2,515 rows) names none of
  the five products of the family, yet the graph holds the conclusions of such an assessment for
  Kalydeco. So v0 builds C8 only on a premise that a present value contradicts.
- **A product page does not show its revision number.** Kalydeco's stored page has no word
  "revision". The product items of C6 ask for the newest document of a type instead.
- **Guideline families (C6).** The graph holds 2,032 documents of type `scientific-guideline`: 879
  adopted, 912 draft, 241 of unknown status. Grouped by title without "Draft" and "- Revision N",
  262 families have more than one document (582 documents), and 221 mix an adopted and a draft
  version. Grouped by reference number, it is 359 families, 870 documents and 297 mixed. The
  review's 301, 667 and 267 lie between and are not reproduced: its rule is not recorded. The
  title rule misses Revision 6. 683 of the export's 2,715 guideline records are not in the graph.

## Implementation sketch

Size: M. A few sessions of code, and about 6 hours of the owner's time. Authored files:
`benchmark/benchmark_v0.jsonl` and `benchmark/projects.yaml` (the four products with their role).
Tool output: `benchmark/candidates/v0_*.jsonl`. Code: `harness/eval/computed_gold.py` (the
registered queries), `scripts/make_computed_items.py` (it refuses a path outside the candidates
folder), `benchmark/validate_benchmark_v0.py`, `harness/eval/facts.py` (pure scoring functions),
the prompt `harness/judges/must_have_fact.md`, and in `harness/eval/runner.py`: grouping by
`class`, `--repeats`, the tags `ema.class` and `ema.repeat`. A section in `benchmark/SCHEMA.md`.

### The record

One JSON object per line. The present fields `question`, `gold_answer`, `paraphrases` and `notes`
stay. `type`, `gold_qa_ids` (ids of `corpus.jsonl`, which holds no PDF text) and `topic_path` go.

| Field | Type | Meaning |
|---|---|---|
| `bench_id` | string | The id, such as `C5-001`: the class and a number that is never reused. The key keeps its present name, because the runner and the trace tag `ema.bench_id` read it |
| `class`, `kind` | `C1` to `C9`; `question` or `proposal` | The kind of question, which replaces `type`. A proposal item has `steps` |
| `project` | list of product numbers | Empty for an item about the whole corpus, two for C4. `benchmark/projects.yaml` names the held-out product |
| `expected_behaviour` | `answer`, `abstain` or `correct_premise` | What a right response does. Only C8 differs from `answer`, and its `gold_answer` states the false premise |
| `must_have_facts` | list of `{id, text, sources, value}` | Short atomic statements. `sources` are positions in `gold_sources`. `value` is the exact number, date or name when the fact is one |
| `gold_sources` | list of `{doc_id, url, reference_number, first_published, last_updated, section, page, quote}` | Present field, extended. `doc_id` is the hash of the URL, as in the graph. The dates and the reference number name the version. `quote` is at most 240 characters, verbatim from the stored text. `page` may be null. No chunk id, because row 10 replaces chunks |
| `terms` | list of `{term, aliases}` | Names that a search has to resolve: a trade name and its substance, an abbreviation and its long form |
| `computed` | null or `{query, params, source, snapshot, derivation, result}` | `query` names a registered function, `source` the table, `snapshot` the feed's timestamp. `derivation` is `count`, `list`, `latest`, `compare` or `contradiction`: the typed derivation that a right answer needs |
| `steps` | list of `{n, text, must_have_facts}` | Proposal items only. One step is one conclusion that a person confirms by itself, with its own facts and sources |
| `withheld_sources` | list of `doc_id` | Proposal items only: the documents that hold the outcome (open question 2) |
| `author`, `reviewer`, `review_status` | `owner`, `assistant` or `computed`; a name or null; `unreviewed`, `owner_reviewed` or `rejected` | Who wrote the gold answer and who checked it. Only a person sets `owner_reviewed` |
| `contamination`, `zero_shot_known` | `{newest_source_published, constructed}`; map of model id to boolean | What the author knows: the newest publication date among the gold sources, and whether no document states the answer in one place. `zero_shot_known` is the present field, filled from the closed-book run of row 3 |

### Size and split

| Class | Public meaning | Items | Computed | Proposal | Gold comes from | Waits for |
|---|---|---|---|---|---|---|
| C1 | a single fact | 2 | 0 | 0 | one PDF of a product | |
| C2 | synthesis within one document | 2 | 0 | 0 | one assessment report | |
| C3 | a trace across several documents | 4 | 0 | 0 | procedural steps, variation reports and the assessment report of one product; one item joins `WS-2551` and the worksharing guidance page | |
| C4 | comparison across products | 4 | 0 | 2 | the same section in the reports of two products | |
| C5 | aggregate: how many, list all | 4 | 4 | 0 | the medicines table | row 13, Stage 1 |
| C6 | version and time | 4 | 4 | 0 | status, dates and reference numbers of the documents feed | row 13, Stage 1; the 2 guideline items also row 11 |
| C7 | the reason for a decision | 5 | 0 | 4 | grounds in refusal, withdrawal and orphan maintenance reports | the closed-book check |
| C8 | unanswerable or false premise | 3 | 3 | 0 | a premise that a value of the medicines table contradicts | row 13, Stage 1 |
| C9 | table or figure | 2 | 0 | 0 | a table in an assessment report | |
| | | **30** | **11** | **6** | | |

By product: Kalydeco 5, Orkambi 4, Kaftrio 6, Alyftrek 3, two products 4, no product 8. Proposal
items: 2 on Alyftrek, 2 on two products, 2 on a refusal or withdrawal report outside the family.

**The 45 present items stay as one slice**, unchanged in `benchmark/benchmark.jsonl`. The loader
maps T1 and T2 to C1, T3 to C2 and T4 to C3. They are reported apart, with the present judges,
because they have no must-have facts (open question 5). The 5 showcase items stay outside.

**What waits for which row.** The 19 judged items can be written before rows 11 and 13: their
sources are PDFs in the graph, and URL, section and quote are written by hand. The 11 computed
items wait for row 13, Stage 1, and the 2 guideline items also for row 11, like any item on a
document that the graph lacks. Scoring needs row 18 (the received passages) and row 3.

### Who writes what

| Group | Items | Drafted by | The owner's part | Estimate |
|---|---|---|---|---|
| Computed | 11 | `scripts/make_computed_items.py`, into `benchmark/candidates/` | Is the question well posed? No judgement of the answer | 11 × 3 min ≈ 35 min |
| Plain | 13 | an assistant, `author: assistant` | Open each quote, confirm or correct each fact, accept or reject the item | about 52 facts × 2.53 min ≈ 2.2 h |
| Proposal | 6 | an assistant | The same per step, and a judgement that the task is a fair proposal | about 48 facts × 2.53 min, plus 6 × 10 min ≈ 3 h |

Together about 6 hours. The 2.53 minutes is a published reading time per claim (Si et al. 2024, as
used in the proposal for row 20). No person has timed this work; the first sitting of 5 items
does. Every table says how many of its items are not `owner_reviewed` (planning workflow, rule 11).

### Scoring

| Number | Definition | Decided by |
|---|---|---|
| Retrieval hit | `hit_any`: at least one gold source is among the documents the agent received. `hit_all`: all are. `passage_hit`: a received passage contains the gold quote | code, from the answer record of row 18 |
| Fact score | Each must-have fact gets 0 (absent or contradicted), 1 (stated in part, or without its condition) or 2 (stated). Item score = sum / (2 × number of facts). A proposal item is also scored per step | A fact with a `value`, and every computed item: exact comparison by code. Other facts: the judge, one call per fact |
| Abstention | On C8: the share of responses that abstain or correct the premise. On the other classes: the share that abstain wrongly | the judge, one of three labels |
| Cost | Input and output tokens, tool calls and seconds per item | code, from the trace |
| Repeats | Every item runs 3 times. A class reports the lowest and the highest of its three scores, with n. A failed repeat is listed and left out | code |
| First failing stage | For an item with a fact score below 1 or a wrong abstention, the first of: `run_error`, `no_answer`, `no_source`, `source_missing`, `passage_missing`, `answer` (the passage was received and a fact is still missing), `abstention` | code, from the numbers above |
| Review items per fact | The claims of the answer that code did not settle, divided by the item's must-have facts. Code settles a claim only on an exact quote in a received passage or on a value equal to a computed one (direction review, section 6.1). Two rungs are compared on the items where both have the same fact score | code. Its audited part, the share of wrong claims among the settled ones, needs a person: row 20 |

The judge is `roles.judge`, a setting. A judge of another model family is wanted wherever a judge
is needed; all models at hand are of one family, so every page with a judged number says so. The
11 computed items need no judge. The other 19 hold about 100 facts: about 300 judge calls per rung.

### Contamination

EMA's text is public and is probably in a model's training data. Four measures:

1. **The closed-book run of row 3** covers the 30 items and the 45 and fills `zero_shot_known`.
   Every table is given with and without those items, and lift is reported per class.
2. **Dates.** Each item records the newest publication date among its gold sources. A document is
   called post-cutoff for a model only when that model's cutoff is on record (open question 6).
3. **Constructed items.** The 11 computed items and the 4 comparisons ask what no one document says.
4. **A closed-book check of 3 proposal questions comes first**: one orphan review, one refusal,
   one withdrawal. The rule is fixed before the run. If the closed-book fact score is 0.5 or
   higher on 2 of the 3, the model remembers the outcomes. Then proposal items use only documents
   published on 2025-07-01 or later, and the check runs once more. A second failure drops them.

## Verification

**The validator.** Offline checks run in `make test`. Live checks need `--live` and only read.

| Check | Fails when |
|---|---|
| `schema` | a field is missing or has an unknown value; a `bench_id` is repeated; a proposal has no steps; a C8 item expects `answer` |
| `counts` | the complete file differs from the split table: 30 items; 2, 2, 4, 4, 4, 4, 5, 3, 2 per class; 11 computed; 6 proposals; 5, 4, 6, 3, 4, 8 by product |
| `facts_sourced` | a must-have fact names no gold source and the item is not computed |
| `labels` | `owner_reviewed` without a reviewer; `author: computed` without `computed` |
| `held_out` | the held-out product's name or number occurs in a prompt, a recipe or a few-shot file |
| `sources_in_graph` (live) | a `doc_id` is not the hash of its URL, or no `:Document` has it. It fails today for Revision 6 |
| `quotes_found` (live) | a quote is not in the stored text of its document, after collapsing whitespace |
| `recompute` (live) | the registered query of a computed item returns another value than `computed.result` |
| `answerable` (live) | a computed item expects an answer, and no gold source's text holds the value |

**The recomputing queries.** `recompute` runs the query that each computed item names. Expected on
the feed copies on disk today: the four worked examples above, and 181 for human medicines with
`biosimilar: "Yes"`. A new download changes these values; record the feed's timestamp with them.

**Tests:** `test_fact_without_source_fails`, `test_quote_not_in_text_fails`,
`test_substring_substance_match_is_not_used`, `test_computed_item_recomputes`,
`test_generator_refuses_authored_path`, `test_hit_any_and_hit_all`, `test_first_failing_stage`,
`test_failed_repeat_is_left_out`, `test_runner_groups_by_class`, `test_legacy_types_map_to_classes`.

**Reachability and smoke run.** `grep` shows the scorer called on the path of
`scripts/run_eval.py --benchmark benchmark/benchmark_v0.jsonl`, not only from tests. A run of 3
items (C3, C5, C8) with `naive_rag` produces every number of the scoring table. It is not a result.

**What would stop the row.** The closed-book check fails twice. Or the owner rejects more than 2 of
the first 5 drafts: then the drafting is wrong, and the session stops and asks.

## Open questions

| | Question | Options | Recommendation | Who |
|---|---|---|---|---|
| 1 | Which products? | (a) one family: Kalydeco, Orkambi, Kaftrio, with Alyftrek held out; (b) two families: Kalydeco, Kaftrio and Keppra, with Alyftrek held out; (c) other products that the owner names | (a). It gives the shared substance, the precedent for the held-out product and the newest documents. Its cost is one family in one disease | **Owner** |
| 2 | Does a proposal item withhold the document that holds the outcome? | (a) yes: the item lists `withheld_sources`, and the filter in retrieval is built with row 16; (b) no: the agent may read the outcome | (a). With (b) the item is a C7 question, and nothing is proposed | **Owner**: it defines "proposal" |
| 3 | When does the owner review? | (a) three sittings of about 2 hours; (b) a second reader takes part of the plain items | (a), with 5 items first, to measure the pace | **Owner** |
| 4 | Are the six proposal items part of the 30? | (a) part of them; (b) added, 36 items | (a). It keeps the review at about 6 hours | Lead |
| 5 | Do the 45 present items get must-have facts? | (a) no, they keep the present judges; (b) a person splits each gold answer into facts | (a) in v0. (b) when a rung needs C1 and C2 on the new scale | Lead |
| 6 | Where do training cutoffs come from? | (a) a `training_cutoff` per entry of `models.yaml`, copied from the provider's documentation with the date of reading; (b) none, and no item is called post-cutoff | (a). Without it, measure 2 of "Contamination" stays empty | Lead |
| 7 | Who writes `zero_shot_known`? [`closed_book_lift.md`](closed_book_lift.md) rewrites the benchmark file in place | (a) row 3's script writes a candidate file and a person promotes it; (b) in place | (a). No tool overwrites authored data (`CLAUDE.md`, rule 3) | Lead |

Questions 4 to 7: the lead assistant session accepted the recommendation of each on 2026-11-25,
under the owner's delegation of that day. They are not the owner's answers, and the owner can
overrule each one. Questions 1 to 3 wait for the owner.

## For the implementing session

- Check every count again: unit 27 is changing the build, row 11 will add about 7,700 PDFs and
  change HTML pages, and row 13 will move the tables into Mongo.
- Take a gold source's version fields from a feed copy as old as the scrape. Store no chunk id.
  Check the MLflow calls for tags and repeats against version 3.14.0, and name the file you read.
- An item that an assistant drafted keeps `author: assistant` and `review_status: unreviewed`. No
  tool sets `owner_reviewed`, and a replay of earlier answers is not a review.
- Model calls: the closed-book check and the smoke run have 3 items each. Rule 4 of `CLAUDE.md`
  allows 3 without a question, so ask once, with the cost, before the second of the two.
- Keep the rules of the direction review, section 6.1: a fact that a judge scored is never called
  "verified". An item holds public EMA text and the labels C1 to C9, and nothing else of the plan.

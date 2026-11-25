# OntoCast: can it be used here?

**Date:** 2026-11-25 · **Written by:** Claude (Fable 5.2), the lead assistant session ·
**Asked by:** the owner · **Backlog:** the parked item "GraphRAG vs MCP benchmark"; no work
unit · **Paid model calls:** 17, about 0.89 dollars

[OntoCast](https://github.com/growgraph/ontocast) is an open-source tool that reads
documents and writes a knowledge graph. This page answers whether this repository can use
it. Two things were done: the source and the documentation were read at version 0.9.3
(commit `3ba13ae`, released 2026-11-24), and the tool was run once on one public EMA page.
Every number below comes from that reading or from that run. No file of the repository's
code changed.

## Verdict

1. **Yes, for one role.** OntoCast can build a typed fact graph for a few medicines, as
   one arm of the comparison of strategies: the ladder step E8, "graph as a tool". For that
   role it is a stronger starting point than the repository's own extraction code
   (`harness/ontology/enrich.py`), which has never been run on the corpus.
2. **No, as the retrieval store, the agent engine, or a pass over the whole corpus.** The
   whole corpus would cost about 103,000 dollars at the rate measured here (section 4). It
   would also add a second graph store and a second agent framework (section 2).
3. **Not now.** No benchmark failure asks for a fact graph yet. Rows 13, 15 and 16 of the
   backlog come first: entity tables from EMA's own feeds, the benchmark in nine classes,
   and the first ladder runs. Their failure counts decide whether the graph arm is built.
4. **For the owner's main focus (a person confirms an agent's answer), it helps less than
   its feature list suggests.** A fact points back to a text unit of 3,000 to 6,000
   characters, not to a sentence. And the trial produced an error that no single fact
   shows: 2 of 15 clinical studies in the graph are each a merge of two different studies
   (section 3.4).

## Terms used on this page

| Term | Meaning |
|---|---|
| Ontology | The vocabulary of a domain, written down so that a program can read it: the kinds of things (classes, such as "clinical study") and the relations between them (properties, such as "evaluates regimen") |
| Fact, triple | One statement in the form subject, relation, object. Example: "study 5" "has participant count" "69" |
| Knowledge graph | A set of such facts. Here: the facts that a tool extracted from documents |
| RDF, Turtle | The standard data model for triples, and a text format to store them |
| SPARQL | The query language for RDF graphs, as SQL is for tables |
| SHACL | A standard to write rules that a graph must satisfy, for example "a study has exactly one participant count" |
| Triple store | A database for RDF graphs. Apache Jena Fuseki is one |
| Content unit | OntoCast's name for one piece of a document that goes into one model call. 3,000 to 6,000 characters by default |
| Provenance | The record of where a fact came from |
| Entity merge | Deciding that two names in the text mean the same thing, and joining them into one node of the graph |
| Ladder step E4, E8 | Two steps of the research plan this repository rehearses: E4 "ontology lookup", E8 "graph as a tool" ([`2026-11-23_pkr_testbed_review.md`](2026-11-23_pkr_testbed_review.md), section 2) |

## 1. What OntoCast is

Read in the source tree, the `README.md`, `pyproject.toml`, `CHANGELOG.md` and the pages
under `docs/`.

| | |
|---|---|
| What it does | Converts a document to text, cuts it into content units, lets a language model propose an ontology for the document, then lets the model extract facts in the terms of that ontology. With an ontology given, it extracts facts only (`RENDER_MODE=facts`) |
| Checks without a model | Each unit's output is checked by plain code: terms the ontology does not define, values of the wrong type, a property that may have one value and has two, SHACL rules when given. `ontocast check` runs these checks on any fact graph and exits with 1 when it finds an error |
| Provenance | Every fact gets a record that names the content unit it came from (RDF 1.2 reification, `prov:wasDerivedFrom`). The unit is described by its position and a hash of its text. There is no sentence, no character offset and no quote |
| Model providers | OpenAI, Anthropic, Google, Ollama, through LangChain |
| Storage | In memory (pyoxigraph, full SPARQL 1.1, gone when the process ends) or Apache Jena Fuseki. A Neo4j backend existed and was removed in version 0.4.2 |
| Use from an agent | LangChain tools, among them `ontocast_sparql_select` (read-only queries) and `ontocast_extract`; a function for one passage (`run_unit_pipeline`); a node for a LangGraph workflow; an HTTP server |
| Licence | Apache-2.0 |
| Maturity | Version 0.9.3, classified "Beta" by its authors. The GitHub API lists 3 contributors; 147 of their 151 contributions are one person's. 263 stars and 32 forks on 2026-11-25. 2,956 test functions. The word "BREAKING" occurs 10 times in the changelog |
| Requirements | Python 3.12 or newer. The base install has 12 dependencies. The trial installed 91 packages (416 MB) before the embedding library, which the merge step requires (section 3.5) |

## 2. How it compares with what the repository has

| | This repository today | OntoCast | What follows |
|---|---|---|---|
| Graph model | A property graph in Neo4j: 79,882 documents, 7,435,393 chunks, section hierarchy and 99,520 hyperlink edges. No entity layer | An RDF graph of extracted facts, typed by an ontology | The two do not share a store. OntoCast's output would live beside Neo4j, in memory or in Fuseki, or be converted |
| Agent framework | LlamaIndex `FunctionAgent` with a tool registry | LangChain and LangGraph | The pipeline can run as a separate batch step. Only the query tool needs to reach the agent, and a SPARQL query wrapped as one LlamaIndex tool is small |
| Entities | None in the graph. Row 13 plans tables from EMA's structured feeds (medicine, substance, ATC code), without a model | Extracted by a model from running text | The feeds give the identity of a medicine exactly and for free. OntoCast gives what the feeds lack: studies, results, populations, indications as stated in a document |
| Own extraction code | `harness/ontology/` maps a schema of 7 entity types and 20 relations to a LlamaIndex extractor. Never run on the corpus. No validation, no merging, no provenance beyond the chunk | Validation, merging with guards, versioned ontology, provenance, a cache of model answers, cost counters per phase | If a model-extracted graph is built at all, OntoCast is the better first candidate. The repository's code stays as the second |
| Evidence for a claim | Row 18 (in progress): each claim names a passage and a verbatim quote, checked by plain code | A fact names a unit of 3,000 to 6,000 characters | A fact from the graph cannot pass row 18's quote check on its own. The answer still needs a passage and a quote |

## 3. The trial

### 3.1 Setup

| | |
|---|---|
| Document | The EMA medicine page for Kalydeco, `https://www.ema.europa.eu/en/medicines/human/EPAR/kalydeco`, as stored in Mongo `parsed_documents` (parser `trafilatura`, 16,619 characters). Public content |
| Tool | `ontocast==0.9.3` from PyPI in its own virtual environment outside the repository, extras `anthropic`, `server`, `documents`, later `sentence-transformers` 6.3.0 with CPU-only `torch` 2.15.0. `langchain-anthropic` 1.7.12, `anthropic` 2.14.0, `langgraph` 1.2.24 |
| Command | `ontocast process --input-path kalydeco_epar_page.txt --head-chunks 3 --keep-provenance --ontology-dir "" --shapes-dir ""` |
| Settings | Defaults: `RENDER_MODE=ontology_and_facts`, no seed ontology, no SHACL rules, critic passes off, units of 3,000 to 6,000 characters. `PARALLEL_WORKERS=3`, `LLM_MAX_INFLIGHT=3` |
| Model | `claude-sonnet-5-5` |
| Units | 3, of 5,716, 5,970 and 4,963 characters. They cover the whole page |
| GPU | Not used (`CUDA_VISIBLE_DEVICES=""`). The live graph and the repository were not touched |

### 3.2 What it cost

17 model calls for one page. Token counts are from the run manifest
(`kalydeco_epar_page.run.json`, `budget.tokens_by_phase`).

| Phase | Calls | Input tokens | Output tokens |
|---|---|---|---|
| Choose the home ontology | 1 | 6,937 | 317 |
| Plan the ontology | 1 | 8,377 | 12,676 |
| Write the ontology, per unit | 3 | 26,626 | 21,363 |
| Consolidate the ontology | 1 | 2,830 | 700 |
| Extract facts, per unit | 3 | 42,970 | 24,302 |
| Fill gaps in the facts | 2 | 13,174 | 860 |
| Decide which entities are the same | 6 | 26,339 | 3,120 |
| **Total** | **17** | **127,253** | **63,338** |

At 2 dollars per million input tokens and 10 dollars per million output tokens (the price
table of the Claude API reference, cached 2026-11-03) that is 0.25 + 0.63 = **0.89
dollars**. The four phases that write the ontology cost 0.44 dollars of it. The three
phases that extract and merge facts cost 0.45 dollars.

OntoCast's documentation says that entity merging makes "at most one" model call per
document. This run made 6.

Wall time: the first attempt reached the merge step after 3 minutes 8 seconds, with 11
model calls and 3 in parallel. The step times of the second run include the download of two
embedding models and are not a speed measurement.

### 3.3 What it produced

- **An ontology** named `medprod`: 21 classes, 20 relations between things and 5
  properties with plain values. The classes: ActiveSubstance, AdverseReaction,
  AuthorisationStatus, BenefitRiskConclusion, ClinicalStudy, DocumentType, DoseAdjustment,
  FrequencyCategory, GeneticVariant, MarketingAuthorisation, MedicinalProduct,
  MedicineCategory, MutationClass, PatientPopulation, PharmaceuticalForm,
  ProductInformationDocument, RegulatoryAuthority, StudyEndpoint, StudyResult,
  TherapeuticIndication, TreatmentRegimen. The planning call proposed 66 terms: 48 were
  created, 12 resolved to a term that already existed, 6 were rejected. Consolidation
  merged 2 of the 48 into others. No fact uses 8 of the 21 classes.
- **Facts:** 659 triples, and 656 provenance records that tie facts to one of the 3 units.
  Among the instances: 26 genetic variants, 19 study results, 18 patient populations, 15
  clinical studies, 11 adverse reactions, 10 treatment regimens, 9 indications.
- **A validation report** by OntoCast's own checks: 2 errors (one property with two values,
  twice) and 7 warnings. The run ended with "2 error finding(s) remain after 0 repair
  pass(es)".

As a description of what such a page talks about, the ontology reads well. It has 46 terms;
the facts have 659 triples. No reviewer was timed on either.

### 3.4 A sample of facts, checked against the page

14 of the 274 triples that use a relation or property of the generated ontology, drawn with
seed 20261125. **The check is an assistant's reading of the page, not a person's.**

| | Fact as stored | The page says | Reading |
|---|---|---|---|
| 1 | compassionate use programme → evaluates → the regimen with ivacaftor / tezacaftor / elexacaftor | The same, in the section on that regimen | agrees |
| 2 | "FEV1 improvement of around 5 percentage points" → result for → Kalydeco on its own | The same (fourth study, adults with R117H) | agrees |
| 3 | study of Kalydeco with tezacaftor / ivacaftor, ages 6 to 12 → participants → 69 | "involved 69 patients" | agrees |
| 4 | regimen "Kalydeco alone" → includes product → Kalydeco | — | agrees |
| 5 | indication (tablets with the triple combination) → for condition → cystic fibrosis | The same | agrees |
| 6 | S1251N → affects gene → CFTR | The same | agrees |
| 7 | **study_2** → participants → 403 | 403 patients were in the first study of the triple combination | **true of one of two studies merged into study_2** |
| 8 | population (1 month and older, 3 kg to under 25 kg) → requires variant → G551S | G551S is in the list for this population | agrees |
| 9 | fourth study of the triple combination → participants → 66 | "involved 66 children" | agrees |
| 10 | Kalydeco → medicine category → Human | The page header | agrees |
| 11 | "reduction of 0.4 percentage points" (placebo) → result of → **study_1** | Stated for the study of 307 patients without an F508del mutation | **true of one of two studies merged into study_1** |
| 12 | indication → has treatment regimen → the triple combination | The same | agrees |
| 13 | "reduction of 0.6 percentage points" (placebo) → result of → first study with tezacaftor / ivacaftor | The same | agrees |
| 14 | indication (granules with the triple combination) → for condition → cystic fibrosis | The same | agrees |

**The error.** The page describes several groups of studies. In the first unit and in the
second unit the model numbered its studies from 1. OntoCast kept them apart at first
(`study_1__u0` and `study_1__u1` in `kalydeco_epar_page.units.trig`). The merge step then
joined `study_1` of both units, and `study_2` of both units. It kept `study_3` and
`study_4` of the two units apart. Counted over the whole graph: **2 of the 15 clinical
studies are each a merge of two different studies.**

What the graph holds for `study_2`:

```text
label              "study in patients aged 6 to 11 years with G551D mutation"
label              "first study of Kalydeco with ivacaftor / tezacaftor / elexacaftor"
evaluates regimen  placebo; Kalydeco on its own; Kalydeco with the triple combination
participant count  403
```

The page says that the two G551D studies involved 219 patients together and compared
Kalydeco alone with placebo. The study with 403 patients was a different one: patients
aged 12 and older, treated with the triple combination. A query for the number of
participants in the G551D study of children returns 403. No sentence of the page says so.

OntoCast's own validation flagged `study_1` with a warning (two labels that do not agree).
It did not flag `study_2`. It repaired neither. Which step joined the studies was not
traced.

This matters for review. Each triple of `study_2` looks correct when read alone. The error
is in the join, and a person who checks one fact against one sentence does not see it.

### 3.5 What got in the way

1. **No setting for extra request headers.** The project's Anthropic key is scoped to the
   organisation and needs the header `anthropic-workspace-id`
   (`harness/models.py:32-47`). OntoCast 0.9.3 passes no custom header to its Anthropic
   client. The trial used a wrapper of 10 lines that adds it.
2. **The merge step needs `sentence-transformers`**, which the extras `anthropic`, `server`
   and `documents` do not install. The first attempt paid for 11 model calls and then
   stopped with `MissingDependencyError`. The cache of model answers made the second
   attempt replay those 11 calls at no cost.
3. **Chunking fell back** from "semantic" to "naive", because the extra `semantic-chunking`
   was not installed. The log says so.

## 4. Cost at scale

A linear projection from the one page of section 3: 53.4 dollars per million characters for
ontology and facts, 26.9 dollars for facts against an ontology that already exists. The
character counts are from Mongo `parsed_documents` on 2026-11-25, one row per URL.

| Scope | URLs | Characters | Model calls, about | Ontology and facts | Facts only |
|---|---|---|---|---|---|
| The page of the trial | 1 | 16,619 | 17 | 0.89 dollars (measured) | 0.45 dollars (measured share) |
| The four medicines of benchmark v0 (row 15) | 127 | 9,460,937 | 9,700 | about 505 dollars | about 255 dollars |
| The whole corpus | 80,078 | 1,934,980,496 | 2.0 million | about 103,000 dollars | about 52,000 dollars |

Limits of this table: one page, one model, default settings. A long assessment report may
cost more or less per character than a short web page. With `claude-haiku-5-5` (0.10 and
0.50 dollars per million tokens) and the same token counts the whole corpus would cost
about 5,200 dollars. That model was not tried, and a weaker model may merge worse.

## 5. Where it could fit, and where not

**It could fit as the builder for the graph arm.** The parked proposal
[`../next/graphrag_vs_mcp_benchmark.md`](../next/graphrag_vs_mcp_benchmark.md) plans an arm
that answers from an extracted graph (its section 7.6 names `harness/ontology/enrich.py` as
the extractor). OntoCast is a second candidate for that step. The agent would get one
read-only query tool. The graph would cover the four medicines of benchmark v0, not the
corpus.

**It does not replace row 13.** EMA's feeds state which medicine a document belongs to,
with a product number. A model-extracted graph should link to those identifiers and not
re-derive them.

**It does not replace row 18.** The direction decided on 2026-11-25
([`2026-11-25_direction_review.md`](2026-11-25_direction_review.md), section 6.1) says that
code settles a claim only on an exact quote or an exact value, and that the agent's own
label never decides whether a person sees a claim. A fact graph is a model's output. An
answer that uses it must still cite a passage and a quote, and the merge error of section
3.4 is one more kind of error that the error census of row 20 would have to count.

**Two of its parts are worth remembering apart from the extraction:**

- `ontocast check` tests any fact graph against an ontology and SHACL rules without a model
  call. If claims of an answer are ever written as typed statements, this is a ready
  checker of the kind rule 1 allows: it can fail a claim and never passes one. On
  2026-11-25 typed claims were deferred, because 0 of 60 sampled claims computed anything.
- The generated ontology is a short description of what a set of documents talks about.
  For a body of project documents that has no vocabulary yet, a person could review such
  a draft as a first step. This was not tested beyond one page, and no reviewer was timed.

## 6. Recommendation

1. Nothing in `Now` changes. No dependency is added.
2. The parked backlog item "GraphRAG vs MCP benchmark" now points to this page.
3. When rows 13, 15 and 16 have shipped and the failure counts show questions that fail
   for lack of structured facts, write the proposal for the graph arm with these
   conditions:
   - OntoCast runs in its own environment, as a batch step. Its output is derived data.
   - Facts are extracted against a small ontology that a person has reviewed
     (`RENDER_MODE=facts`), not against one that grows with every document.
   - Each unit keeps its document URL and its position, so that an answer can cite a
     passage and a quote under row 18.
   - Before any answer uses the graph, a person labels a sample of entities and facts for
     wrong merges. The share found is reported.
   - The run for the four medicines costs about 255 to 505 dollars at this page's rate and
     needs the owner's yes, with the cost in a decision note.

## 7. Not verified

- One document, one model, one run. No repeat, so no spread.
- Default settings. Critic passes, SHACL rules, a seed ontology, semantic chunking and a
  stronger or weaker model may each change the merge errors. None was tried.
- The reading of 14 facts is an assistant's. No person checked a fact.
- The cost projection is linear from one page. The price is from a cached table.
- Fuseki, the vector stores, the HTTP server and the LangChain tools were read about and
  not run.
- OntoCast released version 0.9.3 one day before this trial. What is written here about
  missing settings may change quickly.

## 8. Where the files are

`$EMA_RESULTS_DIR/2026-11-25_ontocast_trial/`:

| Path | Holds |
|---|---|
| `input/kalydeco_epar_page.txt` | The page text as sent |
| `out/kalydeco_epar_page.ontology.ttl`, `.facts.ttl` | The ontology and the facts, with provenance |
| `out/kalydeco_epar_page.units.jsonl` | The text of the 3 units |
| `out/kalydeco_epar_page.run.json` | The run manifest: settings, counts, tokens per phase |
| `out/kalydeco_epar_page.facts.validation.json` | OntoCast's validation report |
| `out/run_attempt1.log`, `out/run.log` | The logs of both attempts |
| `cache/` | The cached model answers. A re-run with the same settings pays nothing |
| `scripts/` | `oc_prepare.py` (page text and corpus size), `run_trial.py` (the wrapper), `read_graph.py`, `subjects.py`, `lookup.py`, `size_products.py` (the counts on this page) |

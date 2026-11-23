# Review: ema_nlp as a rehearsal ground for the process-knowledge-retrieval plan

*2026-11-23. Read-only review: no code, config or database content was changed.
Evidence: code reading, the offline test suite (698 passed, 2 skipped), read-only
queries on the live MongoDB and Neo4j stores and on `mlflow.db`, and web reading of
the external tools on the same day. Numbers marked "sample" come from random
samples of the stated size; everything else is a full count.*

"The plan" below is the research plan on process knowledge retrieval kept in the
`cmc_literature` vault (version 2, 2026-11-22). It asks for three things: an
expert-written benchmark in nine question classes (C1 to C9), an experiment ladder
that starts with the cheapest systems (E0 to E9), and a small domain layer
delivered as agent tools. The vault already proposes rehearsing the nine classes on
public corpora before any expert time is spent. This review asks what ema_nlp needs
to serve as that rehearsal.

## 1. Verdict

ema_nlp can serve as the rehearsal ground, and most of the distance is repair and
re-shaping, not new machinery. The corpus, the tool registry, the recipe engine and
the MLflow traces are reusable as they are. The benchmark, the evaluation loop and
the conversion from scrape to database are not yet good enough to draw conclusions
from.

1. **The ontology is not the largest gap.** The plan itself ranks the vocabulary
   rungs (E3, E4) as its least supported and puts three cheaper rungs before them.
   None of those cheaper rungs exists here: there is no keyword search, no
   read-document tool and no full-context loader. The benchmark covers seven web
   pages. Those gaps come first (section 2).
2. **A domain layer can be built from data the scrape already holds, without LLM
   extraction.** EMA publishes its medicines, procedures and document list as JSON.
   Fifteen of those feeds are in `web_items`; eleven are cached on disk. They give
   product, substance, ATC code, therapeutic area, holder, status, revision and the
   product each document belongs to (section 6).
3. **The graph is a faithful copy of what was parsed; the parsing is where content
   is lost.** More than half of the regulatory guidance pages are indexed as a
   title and one paragraph: "Pre-authorisation guidance", 430,000 characters of
   questions and answers, is a single 302-character chunk. About 6,760 English
   PDFs were rejected as "invalid" because their cached bodies are
   gzip-compressed. Measured against EMA's own document list, 20% of documents
   are missing from the graph. The documented update pipeline cannot refresh any
   of this as it stands (section 3).
4. **The published evaluation numbers are unreliable at the margin.** Agent runs
   that crashed were still judged, sometimes as 5 of 5, and non-numeric judge
   outputs were silently dropped from the means. The judge is the same model as
   the generator. The agent reads only the first 400 characters of each retrieved
   passage (section 4).
5. **An MCP server is the right way to open the corpus to other agents**, and it is
   cheap: the `mcp` package is already installed and the existing tool functions
   register unchanged (section 7).
6. **A PaddleOCR pass is worth piloting as a targeted second pass, not a full
   re-parse**, and only after three prerequisites that would otherwise waste it
   (section 8).
7. **The documentation is accurate in its newest layer and unsafe in its setup
   path.** One "build and verify" snippet deletes the live graph (section 10).

## 2. What the plan needs, and what exists

| Plan element | What a rehearsal needs | State in ema_nlp | Gap |
|---|---|---|---|
| Nine question classes | Items in each class, with a project, must-have facts, gold sources with version and location | 45 items in four types (T1 to T4) drawn from **7 HTML pages**; no project, no must-have facts, no unanswerable, version or table items | Large |
| "Project" | A unit that groups documents, with one held out | None in the code. A medicinal product is the natural equivalent: 2,137 products have PDFs in the graph, median 6 per product | Small once product metadata is ingested |
| E1 full context | Load one project's documents into the prompt | Missing. Feasible: a product's PDFs are about 78k tokens at the median, 228k at the 90th percentile | Small |
| E2 keyword search and read-document | The simplest agent configuration | Missing. No full-text index in Neo4j, no BM25 path, no read tool; chunks carry no order, page or section | Medium |
| E3 alias expansion | A vocabulary tool | A 50-entry acronym table exists as a hidden query transform; `resolve_substance` calls PubChem live | Small |
| E4 ontology lookup | Broader, narrower, related terms | Missing. `harness/ontology/` is an extraction scaffold; the graph holds no extracted entities | Medium, cheap route in section 6 |
| E5 guidance arms | No guidance, playbook, playbook plus worked examples | One prompt file per recipe works; worked examples only through the rated cache, and only in the chat UI | Small |
| E6 parsing upgrade | A second parser and a way to choose between parsers per document | Several parser rows per URL can be stored; nothing selects between them | Medium (section 8) |
| E7 hybrid index | BM25 plus vectors as a tool | Vector only | Medium |
| E8 graph as a tool | An explicit graph query tool | The link graph is used inside `ema_search`; no explicit tool | Small |
| E9 citation check | A verification step before answering | Ingredients exist; no step. Blocked by citation attribution by URL (section 4) | Medium |
| E0 any external tool | Run an outside agent on the same questions; the harness only scores | Missing. No MCP server, no score-only entry | Small (section 7) |
| Scoring | Retrieval hit, must-have facts, citation correctness, abstention, cost, three repeats, a judge from another model family | One holistic 1-to-5 correctness judge and one faithfulness judge, same model as the generator, no repeats, nothing reads `gold_sources` | Large |
| Traces | Tool calls, documents opened, tokens, time, readable beside an expert trace, with a failure label | MLflow traces hold all of it; no item id, class or repeat on the trace, no flat export, no failure label | Small |

The vault note "A Public Rehearsal of the Question Classes" says the first thing to
check is whether the four tiers correspond to any of the nine classes. They cover
two and a half:

| Tier | Closest class | Note |
|---|---|---|
| T1 lookup | C1 single fact | Direct match |
| T2 scoping | C1 with distractors | Tests choosing among adjacent Q&As, not a separate capability in the plan |
| T3 multi-hop | C2 single-document synthesis | All ten items have exactly one gold source; the hops are inside one page |
| T4 synthesis | C3 multi-document trace | Two or three sources, all from the same site section |
| T5 showcase (5 items) | C3 / C5 | Hub traversal for one product |

Nothing covers C4 (cross-project), C5 with a complete reference list, C6 (version),
C7 (rationale), C8 (unanswerable) or C9 (table and figure).

**Which classes can be written on this corpus.** At least eight of nine, which
clears the note's own bar of six:

| Class | Material in the corpus | Gold answer comes from |
|---|---|---|
| C1, C2 | Any guideline, Q&A page or assessment report | A person |
| C3 | One product's procedural steps, variation reports and assessment reports | A person |
| C4 | 162 substances with three or more products, for example 17 adalimumab and 31 denosumab products | A person, with the medicines table as a check |
| C5 | Product flags and lists: 181 biosimilars, 239 orphan medicines, 58 conditional approvals, all referrals, all PSUSAs | **Computed** from EMA's tables, complete |
| C6 | 301 guideline families with more than one version or status in the graph (667 documents), 267 of them mixing adopted and draft; `revision_number` per product; file cards grouped under "current" and "superseded" headings | **Computed** from the document list (status and dates) and the card headings |
| C7 | Assessment reports record the committee's reasoning; refusals and withdrawals state grounds | A person. The hardest class to write |
| C8 | A referral, designation or procedure that the complete feeds show never existed | **Constructed** with certainty |
| C9 | 23% of all PDF text is table rows; figures are currently dropped by the parser | A person. Tables yes, figures only after section 8 |

Three classes get gold answers without an expert. That is the same advantage the
synthetic corpus has through its ground-truth annexes, on real documents.

## 3. Conversion from scrape to database

### 3.1 Coverage against EMA's own document list

EMA's "all documents" feed is a manifest of what should exist. The copy in
`.tmp/ema_documents_export.json` (2026-07-13) lists 69,887 documents. Joined on
URL to the graph:

| | Documents | Share |
|---|---|---|
| In the graph | 55,930 | 80.0% |
| Body cached but rejected as "Invalid PDF (bad magic bytes)" | 6,586 | 9.4% |
| Never seen by the crawl | 2,502 | 3.6% |
| Downloaded, not parsed (Word, Excel, zip, no extension, some PDF) | 2,385 | 3.4% |
| Published after the scrape (2025-12-28) | 2,250 | 3.2% |
| URL seen, never downloaded | 189 | 0.3% |
| Parse error | 45 | 0.1% |

The "never seen" group is mostly two document types: scientific conclusions (1,149)
and procedural steps after authorisation (679). Nothing in the pipeline compares
the crawl against this feed, so none of these holes was visible.

### 3.2 Confirmed defects

**Gzip-compressed PDF bodies are rejected as invalid.** 6,776 rows in `parsed_pdfs`
carry the error "Invalid PDF (bad magic bytes)". 6,760 of the cached response
bodies start with the gzip magic bytes; all 169 I decompressed start with `%PDF-`,
and their cached headers say `Content-Encoding: gzip`. The check sits upstream in
`ema_scraper/parsers/pdf_loader.py:109`, which reads `response_body` raw. ema_nlp
only unpickles that parser's output and filters on `error == ""`, so the loss is
silent here. Missing as a result: ICH M7(R2) with its Q&A and addendum, ICH Q5A(R2),
three process-validation guidelines, 945 product-information documents, 538
scientific guidelines, 384 assessment reports. Fix: decompress when the body starts
with `1f 8b`, re-parse those entries, index the delta. No re-scrape is needed.

**The HTML extractor drops the body of the guidance pages.** This is the most
damaging defect, because these pages are what regulatory questions are about.

| Page | Visible main text | Stored and indexed | Chunks in the graph | Re-extracted with the fix |
|---|---|---|---|---|
| Pre-authorisation guidance (98 Q&As) | 430,389 chars | 302 | 1 leaf | 474,197 |
| Quality of medicines Q&A, part 2 (95 Q&As) | 149,378 | 275 | 1 leaf | 152,935 |
| Classification of changes Q&A | 61,953 | 401 | 1 leaf | 65,551 |

Under `/en/human-regulatory-overview/` (393 HTML pages in the graph), 213 pages
(54%) keep less than half of their main text and 199 keep less than a quarter.
Only 703 of 1,516 accordion bodies survive, and where a body survives its question
header survives in 25 of 703 cases, so answers are indexed without their
questions. The other guidance-style sections (about-us, committees,
partners-networks) lose less: 29% of pages keep under half. Product pages keep
their bodies and lose the question headers. Across all HTML pages the share is
lower (7.3% of a 1,500-page sample more than double when repaired), because
medicine and news pages dominate the count.

Two causes act together. Every page carries the site's maintenance notice
("On Monday, 12 January 2026 ... this website will be unavailable") in a
`div.ema-notification` inside the main content, and the extractor stops there on
many pages: removing that one block takes the three pages above from about 300
characters to between 65,000 and 464,000. The accordion markup then costs the
question headers and some collapsed bodies. The repair that recovers both, tested
on the worst pages: extract only `<main>`, drop `.ema-notification` and the
navigation blocks, remove the `collapse` classes, and turn accordion buttons into
`<h3>` headings before extraction. HTML headings also need carrying: 250 sampled
pages hold 1,908 `h2` to `h4` headings and their parsed text holds one.

Side effects of the same defect. The notice itself is indexed as content: about
88% of HTML documents have a chunk containing it, roughly 19,000 near-identical
vectors, and 39 documents consist of nothing else. 786 pages were dropped by the
200-character guard, among them 661 of 1,097 glossary terms. One benchmark item
is affected with certainty: the only gold page of T1-007 holds 391 characters in
the index and 10,521 after repair. The benchmark's other six pages survived
largely intact, which is why the defect did not show in benchmark scores. It may
also explain part of what BACKLOG item 4 calls a length bias against hub pages:
for guidance pages the shortness is this defect, not a property of the page. That
link is untested.

**805 downloaded PDFs are never parsed because of their URL.** The cache walkers
select on `url.endswith(".pdf")`; EMA serves some files as `..._en.pdf-0`, `-1`,
`-2`. All 805 are in `web_items` as `application/pdf` and none is in
`parsed_documents`.

**PDF parsing depends on pickles from another repository.**
`corpus/parsers/pymupdf4llm.py` does not parse PDFs. It unpickles `parsed_pdf.pkl`
files written by `ema_scraper`, with that repository inserted into `sys.path`.
All 58,121 PDF rows carry `parser_version: legacy`, and 26,315 rows in
`parsed_pdfs` record the tool as `unknown`. There is no path in this repo from PDF
bytes to text, which is why the gzip defect cannot be repaired from here today.

**The update pipeline cannot refresh content.** Four separate reasons, each
confirmed in the code and the first reproduced:

1. *The `parse-pdfs` step fails on every PDF.* `scripts/update_graph.py` runs
   `python -m corpus.parsers.pymupdf4llm`, which cannot unpickle the scraper's
   objects because only `scripts/ingest_parsed_pdfs.py` adds that repository to
   the path. Run on a real cache entry in the repo's environment, the parser
   returns `pickle_load_failed: No module named 'parsers'` and no text.
2. *A new parse never wins.* `iter_source_rows` (`harness/indexing/ingest.py:159`)
   takes the first error-free row per URL, which in practice is the oldest.
   `harness/configs/parser_preference.yaml` says in its own header that nothing
   reads it. Every production row has `parser_version: legacy`; a re-parse writes
   a second row that loses on every build.
3. *Changed and removed documents are not handled.* A resumed build skips any
   document that already has a chunk (`_existing_doc_ids`,
   `harness/indexing/property_graph.py:233`). Chunk ids are positional, so a
   forced re-chunk of changed text leaves the old higher-numbered chunks behind.
   Nothing deletes a document that has left the source.
4. *A fresh build loses the document labels.* The real build calls
   `build_ingested_doc` without the metadata lookup
   (`harness/indexing/property_graph.py:307`); only `ingest()` does the join, and
   only tests call `ingest()`. After `--reset`, `doc_type` and `topic_hubs` are
   absent until the `propagate` step runs, which is outside the default steps and
   which the docs describe as unnecessary.

The repair for the HTML and PDF defects above therefore needs these four fixed
first, or it will not reach the graph.

**`--reset` deletes more than the corpus, in one transaction.** It runs
`MATCH (n) DETACH DELETE n`: 7.5 million nodes and 14.6 million relationships
against a 2 GB heap, and it also removes the NeoDash dashboard node. Deleting
`:__Node__` in batches, as the link reset already does, avoids both. Not executed.

### 3.3 Information in the scrape that never reaches the graph

| Information | Where it is | State in the graph |
|---|---|---|
| Document title | `name` in the documents feed | PDF `title` is the URL slug with dashes removed |
| First published and last updated dates | Documents feed, all 55,930 joined rows; 12,072 changed after first publication | Absent |
| Status: adopted, draft, consultation | Documents feed; 20,054 adopted, 2,703 draft among joined rows | Absent |
| Product each document belongs to | `ema_product_number` in the feed, 13,667 joined rows | Absent |
| Reference number | Feed, 43,316 rows | Present on 35% of documents, derived from text |
| Product, substance, ATC, therapeutic area, holder, revision | Medicines feed; 2,640 of 2,649 medicine pages are in the graph | Absent |
| Which version is current | The file cards on guideline pages sit under headings such as "Current effective version", "Document history" and "Superseded documents", and each card carries reference number, legal effective date, first published, last updated and status | `harness/indexing/links.py` keeps only the document type and title of a card |
| Page publication and modification time | `article:published_time` on 242 of 250 sampled pages, `article:modified_time` on 158 | Absent. A `last_updated` value is computed at ingest and then dropped |
| Order of chunks, page, section heading | Order is derivable at chunking time; page and layout boxes are in the scraper's pickles | Chunks carry only `id`, `text`, `is_leaf`, `doc_id`, `source_url`, `embedding` |
| Links inside PDFs, PDF metadata, table of contents | The scraper's pickles | Absent: no `LINKS_TO` edge starts at a PDF |
| Figures | The parser writes "picture intentionally omitted": 509,305 placeholders, 10 or more in 9,064 documents | Absent |

`scripts/enrich_document_metadata.py` already downloads the documents feed and keeps
one field of it, the document type. The parser in `harness/indexing/doc_types.py`
reads only `document_url` and `type` because the file is malformed JSON; the same
brace-split approach reads the other fields.

Three consequences for the plan. Without dates and status the retriever cannot
prefer the valid version, and the corpus holds adopted, draft and superseded
versions side by side. Without the product number there is no "project". Without
chunk order a read-document tool cannot return a document in sequence.

Scope note: the graph holds 3,829 documents in the `veterinary` category although
the scope lock says human-regulatory content only.

### 3.4 Smaller conversion defects

From the code review of `corpus/` and `harness/indexing/`. I re-ran the
reference-number regex and read the chunker and title code; the counts are the
reviewer's measurements on samples or on the live graph.

- **Tables are split mid-row.** The chunker is a sentence splitter with 128-token
  leaves. In a sample of table-bearing documents, 414 of 535 leaves holding table
  cells start in the middle of a row and only 112 include a header row; 56% of
  table rows are intact in any leaf.
- **Titles.** 73.5% of PDFs carry the URL slug as title. Among the rest, generic
  first headings repeat: "The subset(s) of the paediatric population..." 4,316
  times, "Assessment report" 334 times. The documents feed has a curated name for
  55,902 of them.
- **Reference numbers.** The regex in `corpus/metadata/text_metadata.py` returns
  nothing for `EMA/409815/2020`, `EMEA/CHMP/123/2005`, `CPMP/ICH/381/95` and
  `EMEA/H/C/005735`. The graph has a reference number on 12,629 documents; the
  feed has one for 36,635 of the joined PDFs, and where both exist they agree in
  86%.
- **Links to renamed pages are dropped** (plausible, not confirmed). About 17 to
  20% of page-to-page links in a 400-page sample point at an old path or slug
  that redirects; the target is hashed as written and finds no document.
- **Chunk ids depend on metadata.** `source_type` and `reference_number` count
  against the 128-token budget, so correcting a reference number moves chunk
  boundaries and ids for that document. Anything keyed by chunk id, such as
  citation verdicts, then points at different text.
- **The Q&A corpus deduplicates on question text alone**
  (`corpus/build_corpus.py:39`). "How is this medicine expected to work?"
  survives as one record out of about 3,135 orphan-designation pages. This
  affects `corpus.jsonl`, not the retrieval index.
- **Duplicates and noise in the index.** 577 groups of byte-identical documents
  cover 2,603 documents; the two largest are veterinary "publication
  discontinued" placeholders. "Page N/M" footer lines appear in 35,382 PDFs.
- 304 PDFs parsed to empty text and 195 to under 80 characters (image-only, no
  OCR); 1,144 downloaded Office files and archives have no parser; one PDF of
  12.4 million characters is dropped at chunking.

### 3.5 What checked out

The graph matches its source exactly, which matters because it means the repairs
above are parsing work, not graph work.

- Every `:Document.id` equals `sha256(source_url)`; there are no duplicate URLs.
  All 115,101 `web_items` URLs share one form: no fragments, query strings,
  trailing slashes or `http` variants. Every graph URL is in `parsed_documents`
  and every parsed URL is in `web_items`.
- Re-chunking 50 documents with the build's own code reproduces the graph's chunk
  ids and texts. Every chunk has exactly one `HAS_CHUNK` edge, all leaves are
  embedded, no parent crosses documents, and no document lacks chunks.
- `LINKS_TO`: 99,520 edges, none dangling, no self-links, no parallel edges.
  Re-extracting 400 pages reproduces their 2,168 edges with identical properties.
- The `document_metadata` join covers all HTML documents and 96.6% of PDFs, and
  the label counts in the graph equal those in Mongo.
- Only English content is indexed: all parsed URLs are under `/en/`, and the
  24,851 non-English URLs in `web_items` were never downloaded.

### 3.6 Performance

- **Memory.** Neo4j runs with a 2 GB heap and a 1 GB page cache for 5.8 million
  1024-dimension vectors, about 24 GB of raw floats. Link and ancestor expansion
  compute cosine similarity over every chunk of each linked document, and one
  document has 25,916 chunks.
- **Chunk mass is skewed.** The top 1% of documents hold 20.7% of all chunks and
  the top 10% hold 70.9%. The largest are product-list annexes. Capping or
  excluding list annexes would cut embedding cost and noise in the vector search.
- **Three levels store the text three times**, and a short document yields three
  identical chunks. Leaves of 128 tokens produce the 5.8 million vectors; larger
  leaves would cut that several-fold and reduce table splitting, at a retrieval
  cost that would have to be measured.
- The link pass and resumed builds fetch the full text of every row (2 GB) when
  they need only the URL.
- Nothing quadratic was found. Indexes and batch sizes are adequate.

### 3.7 Tests that are missing

The metadata-join tests exercise `ingest()`, which production never calls. No test
asserts which parser row wins, unpickles a real scraper object, covers gzip bodies
or `.pdf-N` URLs, uses real EMA accordion markup, chunks a table, or rebuilds
after a document changed. `scripts/update_graph.py` and the two metadata scripts
have no tests.

## 4. Query-time code and architecture

The items below come from a code review of the query-time half of `harness/` and
`app.py`. I re-checked each numbered item against the code, the crashed traces and
judge values against the 114 traces in `mlflow.db`, and the acronym behaviour by
running it. The passage-length and citation percentages in items 3 and 6 are the
reviewer's measurements on the stored traces, not repeated by me.

**Defects that affect evaluation results**

1. **Crashed agent runs are judged and averaged.** Five eval traces ended with
   `RuntimeError: Event loop is closed`. `AgentWorkflowAdapter.invoke`
   (`harness/agents/workflow_adapter.py:124`) calls `asyncio.run` per question
   while `mlflow.genai.evaluate` runs predictions in a thread pool over one shared
   agent; the likely cause is the shared async client outliving the loop it was
   created on. The judges still scored those rows: correctness 5 with faithfulness
   1, correctness 1 with faithfulness `" STATus - CODE - OK "`, correctness 5 with
   faithfulness `" agent errored"`. `mean_scores` (`harness/eval/runner.py:90`)
   drops whatever is not a number and reports the mean without n. Across all
   stored judge values, 7 of 85 faithfulness and 4 of 85 correctness values are
   non-numeric or null. The T3 and T4 means in
   `docs/eval/2026-07-13_topic_subgraphs.md` include such rows.
2. **The judge is the generator.** `harness/configs/models.yaml` binds `judge` to
   `claude_opus` and all ten recipes generate with `claude_opus`.
   `harness/eval/judges.py` rejects non-Anthropic judge providers, so a judge from
   another model family is not possible on the eval path today.
3. **The agent reads a 400-character prefix of each passage.**
   `harness/tools/search.py` truncates node text to `_SNIPPET_MAX = 400`. With
   `merge: true` that text is the parent chunk, so the agent gets the first 400
   characters of the parent, not the leaf that matched. In stored traces the
   median retrieved passage is 2,112 characters; in a sample of 4,000 leaf and
   parent pairs the matching leaf lies fully inside the visible prefix in 20% of
   cases. The judges and the citation review panel receive the full passage, so
   faithfulness is measured against text the generator never read.
4. **Recipe layers that do not run in evaluation.** Few-shot injection and the
   inline judge live in the Chainlit handler in `app.py`. Under `run_eval.py`,
   `regulatory_fewshot` and `agentic_judged` behave exactly like
   `regulatory_agent`. Eval traces also carry no resolved recipe configuration,
   because `setup_tracing` is only called by the UI and the demo script.
5. **Temperature is recorded and not sent.** The library removes it for the Opus
   model in use and `harness/llms.py` removes it for Claude 5 models, while the UI
   and the trace stamp report 0.0. There is no seed and no repeat loop, so
   run-to-run variation is unmeasured.
6. **Citations are attributed by URL.** A claim is anchored to the top-scoring
   chunk of the cited document, not the chunk it came from; 59% of claim citations
   in stored traces cite a URL with more than one retrieved chunk. A citation to a
   URL outside the evidence set is dropped without being reported.

**Other defects**

- The semantic cache and the few-shot store are global across recipes, models,
  index profiles and users. A cached answer from one recipe is offered under
  another, without citations.
- No request timeout and no step limit are set; a 70-minute hang is on record.
- `oversample` applies only when a category filter or quota is active (already
  BACKLOG item 2), and parent-merge deduplication runs before the cut to k, so
  unsteered profiles return fewer than k distinct passages.
- The acronym expander matches case-insensitively and expands ordinary words
  ("cap", "pass"); it does not expand the flagship case "What is the AI for NDMA?"
  because its context gate needs a word such as "nitrosamines" in the query.
- Config that is parsed and has no effect: the model roles `agent`, `rewriter`
  and `reranker`; the profile's `retrieval.k` in the UI; any output schema other
  than `RegulatoryAnswer`.

**Dead code and leftovers.** `harness/retrieval/native_pg.py` (tests only; "pg"
means property graph, not Postgres), `call_model` in `harness/models.py`,
`get_llm_model` and the `EMA_LLM_MODEL` variable, `harness/eval/bootstrap.py`
(imports `dspy`, which is neither declared nor installed), `harness/export_traces.py`.
On the host: the `ema_nlp_pg` pgvector container is still running and bound to
`0.0.0.0:5432`, and 320 MB of the old FAISS index still sync through Nextcloud.

**Structure.** What works: one composition path with registries for tools,
retrievers, postprocessors and exporters; tools are plain typed functions that
return strings; evidence capture is uniform; MLflow traces are rich; the offline
test suite is fast. What holds the plan back: the evaluation is a thin wrapper
with no run loop of its own (no item ids, repeats, resume or failure accounting);
pipeline logic sits in the 1,061-line UI handler, so the app and the eval behave
differently; retrieval is vector-only over chunks that have no position; answers
and citations are fixed to one schema keyed by URL, with no abstention field.

## 5. Benchmark

- 45 items over **7 source pages**, all HTML Q&A pages from one part of the site.
  Fourteen items share one page. Scores on such items are not independent.
- No item uses a PDF, an assessment report or a table. 72% of the graph is PDFs.
- `gold_sources` has a URL and a null page for every item; nothing in the runner
  reads it. The two paraphrases per item are never used.
- `zero_shot_known` is empty for all 45: the contamination screen has not run.
- `benchmark/validate_benchmark.py` ignores `config.CORPUS_PATH`, skips two of its
  checks and still prints "All checks passed".
- `benchmark/STATS.md` reports 55 unique gold ids, 20 single-id and 25 multi-id
  items; the file has 40, 29 and 16.

For the rehearsal this benchmark is one slice (C1 and C2 on guidance pages). The
nine-class version needs its own record schema: the current fields plus project,
class, must-have facts, gold sources with document date or revision and a section
or page, terms and aliases, author, reviewer and status.

## 6. A domain layer without LLM extraction

The plan's product hypothesis is four tools: resolve a term, expand a concept, give
a project's context, and say which document type holds what. On this corpus all
four can be served from EMA's own structured data.

| Tool in the plan | Source on this corpus | Measured coverage |
|---|---|---|
| Resolve term | Medicine name, INN and active substance from the medicines feed; the 50-entry acronym table; associated names from the referral feed | 2,271 human medicines, 1,252 distinct INNs |
| Expand concept | ATC code (the hierarchy is in the code itself), MeSH therapeutic area, pharmacotherapeutic group, other products with the same substance | ATC on 2,141, MeSH on 2,203 human medicines |
| Project context | Product record, its documents by type, its referrals, PSUSAs, paediatric plans, orphan designations, safety communications and shortages | 2,137 products with PDFs in the graph; 2,130 join to the medicines table |
| Document type guide | EMA's 85 document types plus a short hand-written note on what each holds | Type on 96.6% of PDFs already |

Suggested shape in the graph: `:Medicine`, `:Substance`, `:AtcClass`,
`:TherapeuticArea`, `:Organisation` and `:Procedure` nodes, linked to the existing
`:Document` nodes by product number and URL. Every node and edge is a row of an
official table, so the layer is reproducible and can be rebuilt in minutes.

This changes the role of the existing ontology scaffold. `harness/ontology/enrich.py`
(schema-constrained LLM extraction) and the vault's schema experiment (typed
against schema-free extractors) stay useful as the E8 arm, "a graph built by
extraction, offered as a tool". The deterministic table gives that arm what it
lacked: a reference to score entity resolution and triple precision against,
without an external service.

Licence notes from the web reading: EMA allows reuse with attribution. WHO's ATC
index forbids commercial redistribution and modification, so ATC labels are better
taken from EMA's own `pharmacotherapeutic_group_human` field or from the European
Commission's Union Register file, which is CC BY 4.0.

## 7. Opening the corpus to other agents

The plan's E0 arms run an outside agent against the document system through an MCP
server and let the harness score the result. The rehearsal equivalent is Claude
Code, or any other MCP client, against an ema_nlp server. Two servers mirror the
plan's division of labour:

| Server | Stands in for | Tools |
|---|---|---|
| `ema-docs` | The document system and its connector | `search_documents` (keyword, vector or hybrid; filters on type, product, status, date), `read_document` (by id, with a character or section window), `list_documents` (metadata only), `get_links` |
| `ema-domain` | The plan's ontology server | `resolve_term`, `expand_concept`, `project_context`, `document_type_guide` |

Each tool is switched on per experiment arm, which gives "one changed variable"
without touching prompts or recipes.

What makes this cheap:

- `mcp` 1.27.2 is already in the virtual environment. `FastMCP.add_tool(tool.fn, ...)`
  registers `ema_search` and `resolve_substance` unchanged (verified offline by the
  harness review).
- `rank-bm25` and `llama-index-retrievers-bm25` are installed and unused. For
  keyword search, a Neo4j full-text index on chunk text needs no new service; an
  SQLite FTS5 index over `parsed_documents` is the variant that depends on neither
  vectors nor the graph, which is closer to what E2 means.
- The `claude` CLI is on this host, so a headless run with an MCP config gives a
  complete client-side tool-call trace.

What must be added: a server-side call log (tool, arguments, returned document ids,
latency, run id), because "documents opened" is the plan's retrieval-hit measure;
a score-only entry in the eval runner for answers produced elsewhere; item id,
class and repeat number as trace tags. A REST API is only needed for tools that do
not speak MCP; FastAPI is installed if that arises.

The existing design in `docs/next/graphrag_vs_mcp_benchmark.md` has ema_nlp
*consume* an outside MCP server as one arm. That arm does not need the outside
server for data, since the feeds it wraps are already local (section 9).

## 8. A second PDF parsing pass with PaddleOCR

This is the plan's E6 and bears on C9. The corpus supports the idea and sets its
size.

| Measure over the 58,121 parsed PDFs | Value |
|---|---|
| Contain at least one table | 59.5% (617,886 tables) |
| Share of all PDF text that is table rows | 23.0% |
| Tables with 8 or more columns | 6,382 documents |
| Complex-table candidates: 20 or more table rows and many empty cells, ragged rows or wide tables | 5,424 documents, about 333k pages |
| Strict tier of the same | 2,176 documents, about 131k pages |
| Contain scanned pages (sample of 2,500) | 3.4% of documents; fully scanned 1.7% |
| Landscape pages in the majority (same sample) | 23.8% |
| Omitted pictures | 509,305 placeholders; 10 or more in 9,064 documents |
| Total pages, estimated | about 0.9 million |

A real example of the damage: the header of an "all authorised presentations"
table is split over two rows ("(Invented)" above "name", "Pharmaceutical" above
"Form"), with an empty leading column. That is the stacked-header case the
fidelity notes for the synthetic corpus ask a parser to survive; this corpus has
it in real documents.

**Prerequisites. Without them the pass is wasted.**

1. Repair the gzip defect first. It returns 6,760 documents, more than any parser
   upgrade will.
2. Parser selection per URL (section 3.2), so the second parse is the one indexed.
3. Table-aware chunking. `HierarchicalNodeParser` with sizes 2048, 512 and 128
   tokens splits tables away from their header rows: today 56% of table rows are
   intact in any leaf (section 3.4). A better table would be cut up the same way.
4. The agent must be able to read a table: a read tool, and the end of the
   400-character limit.

**Design.**

- A new module under `corpus/parsers/` that follows the existing `Parser` protocol
  and writes its own rows to `parsed_documents`, with the PaddleOCR version pinned.
  It runs in its own virtual environment: the current docs ask for
  `paddlepaddle-gpu` 3.2.1 or later and Python 3.9 to 3.13, and should not share an
  environment with the torch stack.
- Route by page, not by document. The candidates are long (median 39 pages) and
  their complex tables sit on a few pages. That needs per-page text from the first
  pass, which the re-parse for the gzip repair can produce.
- `PPStructureV3` returns markdown per page and tables as HTML with cell boxes.
  Keep the HTML: merged cells and stacked headers do not survive conversion to
  pipe tables. Chart recognition is off by default and is the route to the figure
  half of C9.

**Risk to measure first.** PaddleOCR reads text from page images. For born-digital
PDFs the embedded text layer is exact, and re-reading it from pixels can introduce
character errors in numbers and units. The stored text already shows what OCR does
on scanned files ("22-0ct-2024"). So compare three arms on a stratified sample of
about 200 documents before spending GPU days: the current text, PaddleOCR, and
Docling, which keeps the text layer and models only the table structure and which
the sibling repositories already use. Acceptance without hand labels: share of
numeric tokens from the text layer that reappear inside the parsed tables, and the
share of rows with a consistent column count. Then 30 to 50 hand-checked tables
covering stacked headers, footnote rows and tables split across pages.

**Cost.** Not estimated. Throughput on the 3090 must be measured on the pilot, and
the pass should run in throttled batches under the 250 W cap because of the known
GSP crash under sustained load.

## 9. External tools

Read on 2026-11-23 by a research agent; I re-read the openpharma code myself.

| Tool | What it is | Use here |
|---|---|---|
| **Open-EMA** (`open-ema.org`) | A hosted, unauthenticated MCP server and REST API over about 71,300 EMA documents with full text (parsed with Docling), hybrid search, and a product and procedure layer keyed on EMA product number. Four tools: `describe_entities`, `search`, `search_documents`, `lookup` | The best reference for the tool surface, and a real comparison system: the equivalent of the plan's "vendor tool" arm. Limits: version 0.0.0, operator not named, source repository not reachable, nightly re-sync (pin runs by date), no HTML guidance pages, so the current 45 items are unanswerable there |
| **BioMCP** (`biomcp.org/sources/ema`) | A CLI and MCP server over 72 sources; its EMA source reads six official feeds and returns name, substance, product number, status, holder | Design ideas only (a small tool catalogue, short default output). No ATC, MeSH, URLs or document text |
| **openpharma-org** | 50 thin MCP wrappers over public APIs. `ema-mcp` exposes one `ema_info` tool with 14 methods over the same EMA feeds | A comparison arm at most. It downloads the full feed on every call, and its document search filters on `title`, `document_title`, `document_type` and `category`, which are not keys of the feed (`name`, `type`, `status`), so a search term returns nothing. ChEBI, ChEMBL and PubChem wrappers are candidate vocabulary sources |
| **BioClaw** | Two projects share the name. `uh-joan/bioclaw` bundles 41 openpharma servers. `Runchuan-BU/BioClaw` is a chat-driven bioinformatics assistant | The second has no EMA or regulatory content |
| **EMA JSON feeds** | 18 files, refreshed twice a day; the product number has been in the documents feeds since 2026-07-04; a scientific-guidelines file was added 2026-10-08 | The source for section 6, and a completeness manifest for the crawl (section 3.1) |
| **Union Register** (European Commission) | JSON, CC BY 4.0: EU number, ATC with descriptions, holder address, link to the EMA page | Fills ATC labels and EU numbers |

None of the tools holds the hyperlink structure or the HTML guidance pages. Those
remain what the local scrape adds.

## 10. Documentation

The audit checked every documented path, command, flag and count against the code
and the live stores. All 261 relative links resolve. The newest layer is accurate:
`docs/tools/`, the recipe anatomy, the onboarding mental model and `BACKLOG.md`.
The setup path is not.

**Would lead a reader into a wrong or destructive action**

- `docs/RETRIEVAL.md` and `docs/ARCHITECTURE.md` show
  `build_index(profile, reset=True)` as the way to "build and verify".
  `reset` runs `MATCH (n) DETACH DELETE n` on the live graph, and the default
  profile is now the full corpus (`limit: null`), while the same doc prints the
  profile as `limit: 50`. The safe call is `open_index(profile)`.
- `docs/RUNTIME_VERIFICATION.md` tells a fresh session to check out and push to a
  branch that is 17 commits behind `develop`.
- `scripts/start_services.sh` aborts on this host because the native `mongod` is
  active. It has been up since 2026-11-19 on kernel 7.0.0-43, contrary to the
  documented rule that it crashes. The Mongo container last failed with "address
  already in use".
- Neo4j compose needs `NEO4J_PASSWORD` exported in the shell; the docs say to put
  it in `ema_nlp.env`, which the script does not load.
- The chat UI needs the `ui` extra; setup installs only `dev`. `UI_PASSWORD` has no
  default although the docs say it defaults to "dev".
- `EMA_LLM_MODEL`, `EMA_CLAUDE_MODEL` and `EMA_EMBED_MODEL` are documented and have
  no effect. `EMA_INDEX_PROFILE` does not select retrieval for the UI, the demo or
  the eval; the recipe does.
- `public/elements/CitationReview.jsx` is described as part of the codebase and is
  gitignored and uncommitted. A fresh clone has no citation review panel.

**Stale.** `CLAUDE.md` carries five stacked banners with branch names that are no
longer current, two overlapping phase sections, the wrong path for the query
cache, and a file that does not exist. The claim that `link_graph` was never built
is repeated in five places; the collection holds 22,743 documents (no code reads
it). Recipe lists show 7 or 8 of 10 recipes. The same three corpus counts are
hard-coded in at least eight files.

**Getting started from the docs alone** fails at the first step: Docker is not
listed as a prerequisite, nothing says how an outsider obtains the Mongo data, and
there is no dump and restore path for the graph, only the 15-hour GPU build. For a
benchmark dataset meant to be used by others, a graph dump is the missing artefact.

**Proposed map.** One entry point per question: `README.md` with a ten-line
quickstart; `docs/SETUP.md` rewritten around the variables the code reads;
`docs/ONBOARDING.md` for how it works; `docs/RECIPES.md` to configure; a new
`docs/EVAL.md` for running and reading an evaluation; `BACKLOG.md` and the roadmap
table for status; `CLAUDE.md` cut to agent rules without branches, dates or counts.
Move history to `docs/history/`.

One note for the vault: the `cmc_nlp` dashboard says commit `b8f7216` "no longer
exists" and that history was rewritten. In this checkout `b8f7216` is the head of
`develop` and `99a9cb3` is its ancestor, so the finding probably came from a
checkout that was behind.

## 11. Proposed order of work

Each step is useful by itself and unlocks the next.

| Step | Work | Unlocks | Size |
|---|---|---|---|
| 0 | Make the evaluation trustworthy: one event loop for all predictions, failed rows counted as failures with n reported, numeric judge output, a judge from another model family, tracing set up in the runner. Replace the destructive snippet in the docs | Any number this repo reports | S |
| 1a | Make the pipeline able to refresh: parser selection per URL, replace-on-change for a document's chunks, the metadata join in the real build, a `parse-pdfs` step that works, batched reset | Every repair below reaching the graph | M |
| 1b | Repair the corpus: re-extract all HTML with the main-content and accordion fix (about 22,700 pages, a small re-embed), decompress and parse the 6,760 gzip PDFs and the 805 `.pdf-N` files, add a completeness check against the documents feed | The guidance pages, a corpus that matches EMA's list, T1-007 | M |
| 2 | Carry the metadata: title, dates, status, reference and product number on `:Document`; current or superseded on file-card edges; chunk order, page and section on `:Chunk`; the entity tables of section 6 | "Project", version filters, the domain layer, a read tool | M |
| 3 | The cheap rungs and the MCP servers: full-text index, `search_documents`, `read_document`, `list_documents`, the call log, the score-only entry | E0, E1, E2 | M |
| 4 | Benchmark v0 in nine classes: the record schema, three products plus one held out, about 30 items with computed gold for C5, C6 and C8; scoring by retrieval hit, must-have facts and abstention; three repeats | The first ladder runs and failure counts | M |
| 5 | E3, E4 and E5 in the order the failure counts give | The vocabulary and guidance questions the literature leaves open | per card |
| 6 | Parser comparison on 200 documents, then the targeted second pass if it wins | C9 and E6 | M |

Step 6 does not depend on steps 3 to 5 and can run in parallel once step 1 is done.

Two items now at the top of `BACKLOG.md`, the seeding re-scope and the `oversample`
change, tune the vector path against the seven-page benchmark. If the rehearsal
becomes the goal they drop in priority. The third, the closed-book baseline, stays:
EMA text is public and probably in training data, so lift remains the number to
report. The documents feed helps here too: `first_published_date` lets a slice be
restricted to documents newer than a model's training cut-off, after a delta
scrape.

## 12. Not verified

- No agent run, eval run or LLM call was made. The cause given for the event-loop
  crash is an inference from the stack and the code; the crashed traces are fact.
- PaddleOCR was not installed or run. Its behaviour on these PDFs, its throughput
  and its error rate on numbers are unknown until the pilot.
- The external tools were read, not benchmarked. Open-EMA was queried once.
- The "complex table" heuristic works on the parsed markdown, so it under-counts
  tables the first pass failed to detect at all.
- The HTML loss was measured on samples and on the 393 pages under
  `/en/human-regulatory-overview/`; the full set of 22,743 pages was not
  re-extracted.
- No build, reset or write was run. The reset behaviour, the stale-chunk case and
  the resume case are read from the code.
- Whether the dropped links to renamed pages really redirect to documents in the
  corpus was judged by slug matching, not by resolving the redirects.
- Findings marked as the reviewers' measurements were produced by three delegated
  code reviews (ingestion, query-time harness, documentation). I re-checked the
  ones stated as re-checked; the rest carry their file references.

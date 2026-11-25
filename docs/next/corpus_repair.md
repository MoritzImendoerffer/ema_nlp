# Corpus repair: page bodies, unparsed PDFs, and a completeness check against EMA's list

**Status:** proposed 2026-11-25 · backlog row 11 · no work unit yet · waits for row 10

Written by Claude (Fable 5.2) from the review of 2026-11-23
([`../eval/2026-11-23_pkr_testbed_review.md`](../eval/2026-11-23_pkr_testbed_review.md),
sections 3.1, 3.2, 3.4 to 3.7 and 12). It is step 1b of the rehearsal order. **Every number
below comes from a read-only query or a dry run on the stores and the cache on 2026-11-25.**
A number after "review:" is the review's own figure and was not reproduced here. Where a
statement of the review did not hold, the text says so in bold. Statements marked *(row 10
session)* were reported on 2026-11-25 by the session that implements row 10; not checked here.

## The problem

Terms. The *graph* is the Neo4j retrieval store: 79,882 `:Document` nodes and 7,435,393
`:Chunk` nodes. A *leaf* is a chunk of the smallest size, 128 tokens. Only leaves carry an
embedding vector; the graph holds 5,817,230. The *feed* is EMA's public list of all its
documents (`.tmp/ema_documents_export.json`, copy of 2026-07-13). The *cache* is the scraper's
folder of downloaded responses, 90,442 entries. The cache and Mongo `web_items` are source data.
`parsed_documents` is the Mongo collection of parser output. A *clean row* has no error. A
*legacy row* carries `parser_version: legacy`; the graph was built from the legacy rows.

### 1. The HTML extractor keeps a page's banner and drops its body

| Page, 2026-11-25 | Text of `<main>` | Stored and indexed | In the graph | Candidate repair |
|---|---|---|---|---|
| Pre-authorisation guidance (101 questions) | 429,979 chars | 302 chars | 3 chunks, 1 leaf | 475,657 chars, 1,105 leaves |
| Quality of medicines Q&A, part 2 | 149,306 | 275 | 3 chunks, 1 leaf | 152,832 chars, 339 leaves |
| Classification of changes Q&A | 61,905 | 401 | 3 chunks, 1 leaf | 66,852 chars, 154 leaves |

- **Scale.** 393 pages lie under `/en/human-regulatory-overview`. 245 of them (62%) hold less
  than half of the text of their `<main>` element, and 219 less than a quarter. The review
  found 213 (54%) and 199. The count depends on the reference text: measured against a repair
  that leaves out file cards (the boxes that list a page's documents), it is 205 (52%).
- **The cause differs from the review.** The review names the site's maintenance notice.
  Removing the notice recovers 3 of the 245 pages. The cause is a rule of trafilatura 2.0.0,
  the library that turns HTML into text. It picks the page body by a list of XPath rules, and
  the second rule is `(.//article)[1]`, the first `<article>` of the page
  (`trafilatura/xpaths.py`, `BODY_XPATH`; the loop is `main_extractor.py:578-613`). On an EMA
  page the first `<article>` is the banner: title, a one-sentence summary and the topic badges.
  The body is a second `<article>`. With the body as the first one, 227 of the 245 recover.
- **Questions are lost.** An accordion is a list of collapsible question-and-answer blocks. The
  question is the text of a `<button>`, which the extraction drops. On the first page above, 3
  of 101 questions reach the text without a fix and 101 with it. All 21,957 stored HTML texts
  together hold 100 heading lines of level 2 to 4; the candidate repair yields 119,599.
- **The notice is indexed as content.** 20,441 of 21,957 HTML documents (93.1%) hold the
  sentence "this website will be unavailable due to scheduled maintenance", in 20,448 leaves.
  The review said about 88% and about 19,000.
- **The length guard.** The parser rejects a page under 200 characters
  (`corpus/parsers/trafilatura.py:49`). 786 of 22,743 pages have no row for that reason, among
  them 661 of 1,097 glossary pages. The notice, 137 characters, lifts other short pages over
  the guard: without it, 329 pages that are indexed today fall under 200 characters.
- **Benchmark.** The gold page of item T1-007 holds 393 characters (review: 391). The
  candidate repair gives 14,900.

### 2. 6,760 downloaded PDFs were rejected because the cached body is gzip-compressed

`parsed_pdfs`, the older parse store, holds 6,776 rows with the error "Invalid PDF (bad magic
bytes)". For 6,760 of them the cached body starts with the bytes `1f 8b`, the mark of gzip
compression, and the cached header says `Content-Encoding: gzip`. All 6,760 decompress to bytes
that start with `%PDF-` and open with pymupdf 1.27.2.3 (the review opened 169). They hold
199,551 pages and 4.67 GB. The other 16 bodies are HTML error pages. None of the 6,760 has a
row in `parsed_documents`. 6,582 are in the feed: 945 product-information documents, 528
scientific guidelines, 491 overviews, 418 referral documents, 380 assessment reports. ICH
M7(R2) with its addendum and ICH Q5A(R2) are among them. 8,671 links on indexed pages point at
these PDFs and have no edge today. Row 10's parser decompresses such a body
(`corpus/parsers/pymupdf4llm.py:104`). Nobody has run it over these files.

### 3. PDFs whose URL ends in `.pdf-0`, `.pdf-1`, … are skipped

The cache walker keeps a URL only if `url.endswith(".pdf")`
(`corpus/parsers/pymupdf4llm.py:171`, and a copy at `scripts/ingest_parsed_pdfs.py:59`).
`web_items` holds 805 rows with a PDF content type and such a URL, as the review says. **The
set is larger than the review says:** the cache holds 918 such responses. All have status 200
and open as PDFs; 73 are also gzip-compressed; 113 carry no content type in `web_items`. None
has a row in `parsed_documents`. 891 are in the feed. They hold 11,907 pages. 183 are
byte-identical to the file at the same URL without the suffix, 700 differ from it, and 35 have
no such twin.

### 4. Nothing compares the graph with EMA's own list

The feed lists 69,887 document URLs. Joined on URL to the graph and the cache on 2026-11-25:

| Feed documents | Count | Share |
|---|---|---|
| In the graph | 55,930 | 80.0% |
| Cached PDF, gzip body, rejected (problem 2) | 6,582 | 9.4% |
| Cached PDF, `.pdf-N` URL, never parsed (problem 3) | 891 | 1.3% |
| Cached, no parser: Word, Excel, zip | 1,173 | 1.7% |
| Parsed to empty text | 316 | 0.5% |
| Parsed, text gives no chunk | 190 | 0.3% |
| Parse error (45), not downloaded (2), other (2) | 49 | 0.1% |
| Never seen by the crawl | 2,506 | 3.6% |
| First published after the scrape of 2025-12-28 | 2,250 | 3.2% |

The review's 80.0% is reproduced. Sorted by `web_items`, as the review did, the query also
gives its 6,586, 2,502 and 2,250. This table sorts by the cache, the record of what was
downloaded, which gives `.pdf-N` a row of its own.

### 5. The first real replacement of a document's chunks happens here

Row 10 ranks the legacy PDF text first, so its own runs replace no text (*row 10 session*).
The HTML repair changes 21,954 documents. It is the first real use of the code that deletes
chunks from the live graph.

## The idea

Repair the two parsers, run them, and let row 10's pipeline carry the result into the graph.
The HTML parser hands trafilatura only the `<main>` element, with the banner and the body as
one article, the notice removed and each accordion question turned into a heading. The PDF
parser runs over the 7,678 cached PDFs that have no row: 6,760 gzip bodies and 918 `.pdf-N`
files. A new script compares the graph with the feed and prints the table of problem 4, before
and after. Every run that deletes or embeds for more than one hour is a checkpoint: it waits
for the owner's yes, and the first replacement is done on one page and counted.

## What it deliberately does not do

- **No new scrape.** The 2,506 documents the crawl never saw and the 2,250 published after it
  stay missing. The check counts them.
- **No parser for Word, Excel or zip** (1,173 feed documents), and **no OCR repair**: 321 PDFs
  parsed to empty text (review: 304), and 196 clean rows give no chunk (195 hold under 200
  characters, one holds 12,454,382). Every build retries the 196. Whether OCR recovers them is
  row 17's question. The check lists them in their own rows, so they stay visible.
- **No second parse of the 58,121 PDFs that have a legacy row.** Row 10's decision A stands
  ([`../pm/decisions/2026-11-25_pdf-parser-order.md`](../pm/decisions/2026-11-25_pdf-parser-order.md)).
- **No change to chunking, titles, reference numbers, dates or tables** (review 3.4; rows 13
  and 17). Row 13 may move chunk boundaries, and those documents are then embedded again.
- **No removal of duplicates** (review: 577 groups of byte-identical documents), no cap on
  long list annexes (review 3.6), no decision on the 3,829 veterinary documents.
- **No removal of `LINKS_TO` edges.** Links come from `web_items.html_raw`, which this row does
  not change. The 5 fixture rows in `parsed_documents` stay: they lose to the legacy rows.
- **No reset, no full rebuild, no evaluation run, no paid model call.** It does not touch
  `corpus.jsonl`, the benchmark files, the recipes or `parser_preference.yaml`.

## Implementation sketch

Size: M. About four sessions of code and three data runs.

| Part | Files | Size |
|---|---|---|
| Completeness check: reads the feed, the graph's URLs, `parsed_documents`, `parsed_pdfs` and the cache; prints the table of problem 4; `--out` writes one JSON line per missing URL with its category. The feed reader also returns `first_published_date` | `scripts/check_completeness.py` (new), `harness/indexing/doc_types.py` | S |
| HTML pre-processing before `trafilatura.extract`: keep `<main>`; make it the single `<article>`; drop the notice block, `<nav>`, the page-contents sidebar, the share block and the expand/collapse buttons; replace each `.accordion-header` by an `<h3>` with its text. A page without `<main>` is extracted as today. The length guard follows open question 2 | `corpus/parsers/trafilatura.py` | M |
| Dry-run report of the HTML parser: per page the stored and the new length, and the leaves that the build's chunker gives; nothing is written | `corpus/parsers/trafilatura.py` (`--dry-run` exists and prints counts only) | S |
| PDF walker: one function that accepts `.pdf` and `.pdf-N`; the copy in `scripts/ingest_parsed_pdfs.py` imports it. `--missing-only` skips a URL that has a clean row. Today the CLI parses every cache entry whose URL ends in `.pdf`: 65,265 files | `corpus/parsers/pymupdf4llm.py`, `scripts/ingest_parsed_pdfs.py` | S |
| A dated page with every count before and after | `docs/eval/` | S |

Stored shapes. `parsed_documents` gains one row per HTML page, `(url, trafilatura, <version>)`,
and one per PDF, `(url, pymupdf4llm, 1.27.2.3)`. No row is overwritten or deleted, so the
legacy text stays as the way back. The graph gains no label and no property. An HTML document
keeps its node, its `LINKS_TO` edges and its labels; its chunks are replaced. A chunk id is the
hash of the document id and the chunk's position, so an old id then names other text. Citation
verdicts and stored traces hold such ids, and the eval page of this row says so.

The order, and what each step costs:

| # | Step | Writes and deletes | CPU | GPU | Leaves embedded |
|---|---|---|---|---|---|
| 1 | Completeness check, the baseline | nothing | 1 to 2 min (the cache walk took 41 s) | 0 | 0 |
| 2 | HTML parser, its tests, and the dry run over 22,743 pages | nothing | 9 to 13 min on one core (551 to 762 s for the candidate) | 0 | 0 |
| 3 | **Checkpoint A: the first replace, on one page** (Pre-authorisation guidance) | 1 row; deletes 3 chunks, writes about 1,400 | seconds, plus the build's comparison of 80,078 URLs (not measured) | under 1 min | about 1,100 |
| 4 | **Checkpoint B: all HTML pages** | 22,743 rows; deletes up to 205,879 chunks with 143,804 vectors; writes about 320,000 chunks | 15 min | about 1.3 h: 238,223 ÷ 265,000 per hour, plus 22 pauses of 60 s | about 238,000 (open question 1: 170,000 to 425,000) |
| 5 | PDF parse rate on 50 of the gzip files, dry run | nothing | minutes | 0 | 0 |
| 6 | Parse the 7,678 PDFs with `--missing-only` | 7,678 rows; no deletion | 4 h at 1.9 s per PDF, to 15 h at 0.25 s per page, on one core | 0 | 0 |
| 7 | **Checkpoint C: the build adds the new PDFs** | up to 7,678 documents; no deletion | minutes | about 4.3 to 4.9 h | about 1.13 to 1.29 million |
| 8 | Link pass of the same build, then the steps `tree`, `subgraphs`, `propagate` | up to 9,709 new `LINKS_TO` edges; properties | minutes | 0 | 0 |
| 9 | Completeness check again, and the page in `docs/eval/` | nothing | 2 min | 0 | 0 |

HTML comes first: it is the most damaging defect, the smallest GPU run, and it tests the
replace path on small documents. The PDFs only add. After step 8 the graph holds about 7.0 to
7.2 million leaves instead of 5.82 million.

Where the costs come from, and where no rate is recorded:

- **Embedding rate.** One figure exists: 3.98 million leaves in about 15 hours on 2026-06-03
  (`.claude/HISTORY.md`), at 250 W with a pause of 60 s after every 1,000 documents. That is
  about 265,000 leaves per hour. Row 10's one-URL run is planned to record a measured rate.
- **HTML leaves.** The candidate repair ran over all 22,743 pages, and the build's own chunker
  counted the leaves. For the stored texts that chunker gives 143,804, the graph's count.
- **PDF leaves.** Two estimates. By document type, with the mean leaves per type in the graph:
  1,058,007 for the gzip files and 72,557 for the `.pdf-N` files. By pages, with 6.09 leaves
  per page measured on 1,000 graph PDFs: 211,458 pages give 1,288,000.
- **PDF parse rate.** Three figures: 1.9 s per PDF on 3 cache entries (*row 10 session*), and
  0.20 and 0.25 s per page on an 8-page and a 6-page PDF. None covers scanned pages, where the
  parser calls OCR. Step 5 measures before step 6 is promised.
- **Not recorded:** the delete rate (row 10 measures it), the duration of the build's
  comparison pass, and query time on a vector index up to 24% larger with a 1 GB page cache.

## Verification

- **Tests.** In `tests/test_parsers_trafilatura.py`: `test_body_article_is_extracted`
  (`tests/fixtures/fixture_html_1.html`, a real EMA page, gives more than 30,000 characters;
  today 378), `test_accordion_questions_become_headings` (15 `###` lines for the same file),
  `test_notice_is_removed`, `test_page_without_main_is_extracted`. For the PDFs:
  `test_walker_yields_pdf_n_urls`, `test_missing_only_skips_a_url_with_a_clean_row`. For the
  check: `test_completeness_categories` on a feed of ten records,
  `test_feed_reader_returns_first_published_date`. `make test` and `make lint` pass.
- **The entry point ran on real data** (planning workflow, rule 6). Steps 3, 4, 6 and 7 run
  through `scripts/update_graph.py` or the CLIs it calls, not through a function call.
- **Completeness, re-runnable.** `scripts/check_completeness.py --feed
  .tmp/ema_documents_export.json --cache <cache>` prints the table of problem 4 before step 3.
  After step 8, with the same feed copy, "in the graph" is at most 63,403 (90.7%). The two PDF
  rows are 0, or every remaining URL is listed with its parse error.
- **Checkpoint A, on one document.** Before: `MATCH (d:Document {source_url: $u})` has 3 chunks
  and 1 leaf, 66 outgoing and 26 incoming `LINKS_TO` edges; the graph has 79,882 documents,
  7,435,393 chunks and 99,520 `LINKS_TO` edges. After: the page has about 1,100 leaves; its
  edge counts and the two totals of documents and edges are the same; the chunk total changed
  by this page's difference only; no chunk lacks a `HAS_CHUNK` edge (0 today); a vector search
  for the page's question 1.1 returns a chunk of this page. The build's log reports 1 replaced
  document and 79,881 skipped.
- **After checkpoint B.** The dry run's leaf count equals `MATCH (d:Document {source_type:
  'html'})-[:HAS_CHUNK]->(c) WHERE c.is_leaf RETURN count(c)`. The notice query (`c.text
  CONTAINS 'this website will be unavailable due to scheduled maintenance'`) goes from 20,448
  leaves to at most 50 (option (b) of question 2). Under `/en/human-regulatory-overview`, pages
  with less than half of their `<main>` text go from 245 to at most 20, each one listed; the
  candidate leaves 18. `:Document` grows by the pages that pass the guard for the first time,
  140 with the candidate. One table gives the length before and after for the benchmark's gold
  pages and for the anchor pages of the seeding report (`docs/eval/2026-07-20_tree_seeding.md`).
  It tells whether backlog row 4, the boost for short hub pages, still has a subject.
- **After checkpoint C.** `:Document` grows by at most 7,678. `LINKS_TO` grows by at most
  9,709: 8,671 pairs point at the gzip PDFs and 1,038 at the `.pdf-N` files. `doc_type` is set
  on every new document that is in the feed, 7,473 at most.
- **What would stop the row.** The dry run lists every page whose new text is more than 100
  characters shorter than its stored text without the notice. The candidate has 246 such pages.
  With more than 100 pages that nobody has explained, checkpoint B is not asked for.

## Open questions

| | Question | Options | Recommendation | Who |
|---|---|---|---|---|
| 1 | Do file cards belong to a page's text? A card lists a document: title, size, dates, and up to 24 other-language versions | (a) all of `<main>`: 425,306 leaves; (b) cards without the other-language lists: 238,223; (c) no cards: 170,352. Today: 143,804 | (b). On many guidance pages the list of documents is the content, and the scope lock already excludes other languages. The review's repair numbers match (c) | **owner** |
| 2 | The length guard. After the repair 1,094 pages are under 200 characters, 940 of them glossary terms | (a) keep 200: 329 indexed pages keep their legacy text with the notice; (b) 80, the chunker's `min_chunk_chars` (`harness/indexing/profiles.py:58`): 398 short pages get clean text, and 50 keep the legacy text | (b). A glossary term under 80 characters cannot give a chunk without a chunking change | implementing session |
| 3 | The 183 `.pdf-N` files that equal their twin byte for byte | (a) parse all 918; (b) skip the 183 | (a), and list the 183 pairs in the eval page. Skipping needs a mechanism that no finding asks for | implementing session |
| 4 | The `parser_version` of the repaired HTML rows | (a) `2.0.0`, the library's version; (b) `2.0.0+ema1`, with a number that rises with every change of the rules | (b). The key then tells two rule sets apart, and both rows remain for comparison | implementing session |
| 5 | Which feed copy does the check use | (a) the copy of 2026-07-13 before and after; (b) a new download | (a) for this row's two tables. A new download adds documents published since and moves every share | implementing session |
| 6 | Checkpoints A, B and C | yes or no for each, on the counts and hours of the order table | A, then B after A's counts are reported, then C | **owner** |

## For the implementing session

- Row 10 must have shipped. Check it in the store: `MATCH (d:Document) WHERE d.text_sha256 IS
  NULL RETURN count(d)` is 0 (79,882 on 2026-11-25). Read row 10's measurement page for the
  delete rate and for the embedding rate, and redo the hours of the order table with them.
- Read trafilatura 2.0.0 before you write the pre-processing, and name the file. The cause
  given above was found on the three example pages and tested on the 393 guidance pages.
- The candidate repair was a scratch script outside the repository. Its steps are the second
  part of the sketch, and its numbers size the work; they are not a specification. It loses
  text on some pages: one paediatric-plan page goes from 990 characters to 0. Find the reason.
- Other code tests the `.pdf` suffix: `corpus/metadata/url_metadata.py:66`,
  `harness/indexing/ingest.py:71` and `harness/indexing/links.py:39`, where a link to a
  `.pdf-N` file gets `kind: page`. Decide for each whether it must change, and say so.
- The GPU wedges under sustained load. Keep the cap of 250 W (`nvidia-smi` showed it on
  2026-11-25) and run every build with `--pause-every-docs 1000 --pause-seconds 60`. A build
  resumes after a crash and loses one flush.
- Each checkpoint is a decision note in `docs/pm/decisions/` with the counts, the hours and the
  way back. The way back from checkpoint B: put `trafilatura@legacy` first in
  `parser_preference.yaml` and build again, about 1 h of GPU for 143,804 leaves and 22 pauses.
- A test that deletes runs on row 10's test double or on a throwaway Neo4j, never on the live
  graph. The cache and `web_items` are read and never written.
- Run no evaluation. `DECISIONS.md` ("Earlier evaluation numbers are not repeated before the
  corpus repair") asks the owner again when this row ships. `/ship` also corrects the counts in
  `CLAUDE.md` and `docs/RETRIEVAL.md`.

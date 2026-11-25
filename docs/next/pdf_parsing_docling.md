# PDF parsing with Docling and PaddleOCR models: the parser, the record format and a pilot

**Status:** proposed 2026-11-25 · backlog row 17, re-scoped after the owner's instruction of
2026-11-25 · no work unit yet · starts when row 10 has shipped, before row 18 (the owner,
2026-11-25) · the pilot has the owner's yes of that day · reviewed by two assistant reviewers
(section "What the review changed")

Written by Claude (Fable 5.2), the lead assistant session. Four kinds of numbers are below
and each is marked.

- **Counted here:** a read-only query or sample by the lead on 2026-11-25.
- **Counted in review:** computed by a review agent on 2026-11-25, read-only. The lead re-ran
  two of its five scripts and got the same output.
- **Review of 2026-11-23:** from
  [`../eval/2026-11-23_pkr_testbed_review.md`](../eval/2026-11-23_pkr_testbed_review.md),
  not reproduced.
- **Measured in doctool:** from the result pages of the owner's repository
  `~/github_repos/doctool`, on synthetic reports, not reproduced here.

The scripts are in `$EMA_RESULTS_DIR/2026-11-25_pdf_parsing_proposal/`.

## What the owner said, and what the lead concludes

**The owner, 2026-11-25:** "make sure the pdfs in ema_nlp are parsed using paddleOCR and
docling (yes it will probably require some re-development) but it would have the same or a
similar format as my doctool repository and docling is a good base."

**The owner's answers to four questions, later that day:**

- doctool "serves a different purpose" and "was just meant as an example". So the format
  here is modelled on doctool's, and nothing is shared with doctool: no common code, no
  requirement that one repository reads the other's files. A connection between the two is
  out of scope, the owner said.
- This row comes before row 18.
- The pilot may run: about 270 PDFs, 7 to 12 GPU hours, files only.
- Whether the PaddleOCR library is used as well is open. The owner asked for the benefits
  and drawbacks of both ways; they are in the section "The two stacks compared".

**The lead concludes** (each point is the lead's reading):

1. "PaddleOCR and Docling" means the stack that doctool runs. That stack uses two models of
   the PaddleOCR project inside Docling. It does not use the PaddleOCR library.
2. Row 17 used to say "the second pass only if it wins". The parser is now decided, so that
   condition no longer applies. The measurement stays: a pilot reports quality, speed and
   size, and every large run needs a yes with its hours (planning rule 4).
3. The work is two rows. **Row 17, this proposal:** the parser, the record format, and a
   pilot. **Row 21, not yet proposed:** chunking from the new records, and the conversion of
   the corpus. Row 21 is designed on the pilot's numbers.

## Terms

| Term | Meaning |
|---|---|
| Text layer | The characters a PDF stores as text. A PDF made from Word has one ("born digital"). A scanned page has none: it is a picture |
| OCR | Reading text from a picture of a page |
| Docling | An open-source library that converts a PDF into a structured document: headings, paragraphs, tables, pictures, each with its page and its position |
| Layout model | The model that finds the regions of a page. Docling's is called Heron |
| PP-OCR | The OCR models of the PaddleOCR project. Version 6 is used here |
| RapidOCR | A small OCR engine that runs the PP-OCR models without the PaddlePaddle framework |
| PaddleOCR-VL | A vision-language model of the PaddleOCR project. Here it reads the grid and the cells of a table from a picture of the table |
| TableFormer | Docling's own table model. It finds the grid and takes the cell text from the text layer |
| Element | One unit of the parsed document: a heading, a paragraph, a list item, a table, a picture |
| Bounding box | The rectangle on the page that an element occupies |
| Pipe table | A table written as text lines with `|` between cells. It has no way to say that one cell spans two rows or columns (a merged cell) |
| Chunk, leaf | The build cuts a document into pieces, called chunks, at three sizes: 2,048, 512 and 128 tokens. The smallest are the leaves. Only leaves are embedded and searched |
| Legacy row | A row of Mongo `parsed_documents` with parser `pymupdf4llm` and version `legacy`: the parse that the 58,121 PDFs in the graph were built from |
| Options hash | A hash of every setting of a parse run. Two runs with different settings get different hashes |
| TEDS | Tree-edit-distance similarity: a score from 0 to 1 for how well a parsed table matches the true table. 1 is identical |
| C9 | The question class "table or figure" of the research plan this repository rehearses |

## The problem

1. **A passage cannot say where it stands.** A chunk in the graph knows no page, no section
   and no position ([`document_metadata_and_entities.md`](document_metadata_and_entities.md)).
   0 of 300 sampled PDF texts hold a page mark. A person who checks a citation has to search
   the PDF.
2. **Tables are damaged twice.** 59.5% of the parsed PDFs hold a table, 617,886 tables in
   all, and 23.0% of the PDF text is table rows (review of 2026-11-23, section 8). Today's
   parse writes pipe tables. The build then cuts through them: 56% of table rows are intact
   in any leaf, and 414 of 535 sampled table leaves start in the middle of a row (same
   review, section 3.4).
3. **Pages without text.** In a sample of 600 of the 58,121 parsed PDFs, 382 of 8,975 pages
   (4.3%) hold under 50 characters of text: scanned or blank. 10 documents (1.7%) consist
   only of such pages (counted here, seed 20261125). Today such a page is read by Tesseract
   5.5.0 through the option `use_ocr=True` of `pymupdf4llm`.
4. **The parse is one Markdown string.** It records no element. For the legacy rows it
   records no model, no option and no library version.

## The idea

One new PDF parser, named `docling`. It runs as a batch command in its own Python
environment. For each PDF it writes a folder of five files, modelled on doctool's format,
and one row in Mongo `parsed_documents`. A pilot on about 270 PDFs then measures three parses of the
same documents: today's, Docling with TableFormer, and Docling with PaddleOCR-VL. Nothing in
the graph changes in this row.

### The stack

Read in doctool's source on 2026-11-25 (`src/dw/parsers/docling_parser.py`,
`paddleocr_vl.py`, `paddleocr_vl_stage.py`):

| Part | Choice | Note |
|---|---|---|
| Base | Docling's standard PDF pipeline. doctool runs version 2.132.0 with `docling-core` 2.99.0 | Which version is used here is open question 10 |
| Layout | Heron, pinned to one revision | Docling asks for the newest revision unless told otherwise |
| Text | From the text layer wherever one exists | Not re-read from the picture |
| OCR | PP-OCRv6 through RapidOCR on onnxruntime, only for regions without PDF text | The models are in the `rapidocr` package. doctool's result page reports that this runs on the CPU |
| Tables | PaddleOCR-VL-1.6 as Docling's table stage, through a Docling plugin; TableFormer is the second setting | Which one reads the bulk is open question 5 |
| Headings | Docling's heading levels from bookmarks and numbering, switched on | |

The PaddlePaddle framework is not installed.

### The two stacks compared

The owner asked for this comparison on 2026-11-25. Stack A is the table above. Stack B adds
the PaddleOCR library with one of its own document pipelines (PP-StructureV3, or its
PaddleOCR-VL pipeline). What is said about stack B comes from PaddleOCR's documentation
(version 3.x, read 2026-11-25) and from the review of 2026-11-23. **Stack B was never
installed or run in this repository or in doctool.**

| | A: PaddleOCR models inside Docling | B: the PaddleOCR library as a second parser |
|---|---|---|
| Text of a born-digital page | Taken from the text layer: the characters are those of the PDF | Its documentation describes the pipeline as layout analysis, text detection and recognition on each page. No option to take the text layer was found. Every character would then be read from the picture, also on the 96% of pages that have a text layer. The review of 2026-11-23 named this risk, with the example "22-0ct-2024" |
| Pages without text | OCR by the small PP-OCRv6 models, measured in doctool on one synthetic scan only | The case it is built for: the whole page is read by models that were trained together |
| Tables | PaddleOCR-VL or TableFormer, one table at a time | Table recognition in the pipeline, and merging of tables across pages |
| Charts, formulas, seals | Not read | The pipelines have steps for them. Charts are the figure half of class C9 |
| What is known about speed and faults | Measured in doctool on this GPU; its faults are listed in "Three properties" | Nothing measured here |
| Software | One library. No PaddlePaddle | A second library and, by default, the PaddlePaddle framework with its own GPU build, in a third environment. The review advised against sharing an environment with torch. The documentation also shows an engine setting `transformers` for the PaddleOCR-VL pipeline; whether that removes the need for PaddlePaddle was not checked |
| Output | Docling's document, the record format of this proposal | Its own JSON and Markdown. Docling 2.132.0 holds a converter from PaddleOCR-VL page results to its document format that nothing in Docling calls (doctool's notes); untested |
| A second, independent parse | No | Yes. Where two independent parses of a table disagree, a person should look. That is a check by plain code, of the kind the main focus asks for. It doubles the parse time wherever both run |

The lead's recommendation: stack A for the corpus. Stack B at most as a fourth parse in the
pilot, on the 40 documents with pages without text. On those pages there is no text layer
to lose, which is B's main drawback, and they are where B could be better. That adds an
environment and an estimated 1 to 2 GPU hours to the pilot. It is the owner's choice (open
question 1).

### Three properties of this stack that the pilot must measure

Measured in doctool on 21 synthetic reports that exist as Word and as PDF
(`docs/results/2026-10-12-evidence-of-the-corpus.md`). Of 10,072 known quotes, the Word
parse holds 95.9% and the PDF parse 81.3% verbatim. Of the 1,477 quotes that only the PDF
parse lacks:

| | Cause | Lost quotes |
|---|---|---|
| 1 | Docling's text reader writes the en dash, the em dash and the minus sign as `-` | 840 |
| 2 | Docling drops a hyphen at the end of a line: `INV-001` becomes `INV001` | 190 |
| 3 | Table structure, with PaddleOCR-VL reading cells from the picture: merged cells, joined rows, changed footnote marks, and `§` read as `$` 75 times | 288 |
| | PaddleOCR-VL leaves markup such as `\n` in cells | 78 |
| | Quotation marks turned into plain ones | 78 |
| | Lines lost or reordered | 14 |

That comparison is PDF against Word. It does not compare the two table models. For those,
doctool has TEDS scores on few tables: PaddleOCR-VL 0.987 against TableFormer 0.784 as the
mean of 2 difficult tables; 0.989 against 0.926 on the 8 tables of one report that the
layout model found whole; 0.857 against 0.782 over all 11 tables of that report
(`docs/results/2026-10-02-tableformer-v2.md`).

For this corpus the three properties matter in different ways. A minus sign written as a
hyphen is harmless to a reader and breaks an exact quote. An identifier that loses its
hyphen is wrong. A number that the table model misreads is wrong and looks right. Row 18
checks that a claim's quote stands in the passage; a quote of a misread cell passes that
check. So the pilot measures all three on EMA documents, and row 18 is told (section "What
comes after").

### The record format

Per parse one folder: `<parsed root>/<doc-id>/docling@<options hash, 8 characters>/`. The
folder is written in a staging place outside any synced folder and moved in as a whole.
The layout follows doctool's `docs/data-contracts.md`, which the owner named as the example.

| File | Holds | Bytes per page |
|---|---|---|
| `doc.raw.json` | Docling's document exactly as the parser returned it, without images. The only file that costs GPU time | 35,800 plain, 1,900 gzip |
| `doc.json` | The same after the steps that need no model: tables split across pages joined, an id written on each element. Rebuilt from `doc.raw.json` at any time | the same |
| `doc.html` | One element per line, in reading order, each with its id. A comment marks each page. Tables are HTML with `rowspan` and `colspan` | 2,300 |
| `sidecar.json` | The index of elements: `id`, `ref`, `label`, `page`, `bbox`, `coord_origin`, `order`, `origin`. It holds the first page and box of an element; `doc.json` holds all of them | 1,600 |
| `run.json` | The run record: source hash, package versions, model revisions, options and their hash, counts (elements, tables, cells, tables without cells), seconds, device | 40 |

Bytes per page: counted in review on doctool's own parses (42 documents, 1,521 pages). For
1.08 million pages that is about 82 GB with plain files and about 8 GB with the two JSON
files gzip-compressed. The disk has 764 GB free. doctool writes a sixth file, `view.html`,
a page for reading with highlights. It is left out here and can be derived later.

Three differences from the example:

- **Document id:** `<slug>_<hash12>`. The slug is the last part of the URL, cut to 40
  characters. `hash12` is the first 12 hex characters of the SHA-256 of the PDF bytes.
  doctool uses 6. Here 856 PDFs share one slug after the cut, and with 6 characters a silent
  overwrite of one folder by another is expected with a probability of about 4% (counted in
  review).
- **The options hash is in the folder name,** so two parses of one PDF with different
  settings lie side by side. The pilot needs that.
- **Two PDFs with the same bytes share one folder** and are parsed once. The review of
  2026-11-23 counted 577 such groups with 2,603 documents.

Element id, as in the example: the first 6 hex characters of the SHA-1 of
`label|page|first 64 characters of the normalised text`; a repeated id gets `-2`, `-3` in
reading order. An id is valid for one `doc.raw.json`.

**The Mongo row:** key `(url, "docling", "<docling version>+<options hash, 8 characters>")`,
`content_type` `application/pdf`. `text` is a compact Markdown rendering of the elements
with a size guard: a Mongo document may hold 16 MB, and one legacy row already holds
12.5 MB. `meta` holds the document id, the folder path relative to a root set in
`config.py`, the source hash, a hash of the files a build would read, and the counts of
pages, tables and cells. No row of another parser is touched.

### The pilot

About 270 PDFs in five strata that do not overlap. Files only: no Mongo row, no change to
the graph, no deletion.

| Stratum | Documents | Pages, estimate |
|---|---|---|
| Complex-table candidates (review of 2026-11-23, section 8) | 60 | 2,340 |
| At least one page without text, not in the stratum above | 40 | 800 |
| The four medicines of benchmark v0 | 40 | 1,600 |
| Never parsed (gzip-compressed body, or a URL ending in `.pdf-N`) | 30 | 900 |
| Random among the rest | 100 | 1,500 |

**Three parses of every document:** today's parser (`pymupdf4llm` 1.27.2.3, on the CPU),
Docling with TableFormer, Docling with PaddleOCR-VL. The reference for text is a fourth
reader that none of the three uses: `pdftotext` from poppler.

**What is reported**, per stratum and for each parse where it applies:

| Question | Measure |
|---|---|
| What does it cost? | Seconds per page without tables, seconds per table and per table cell, tables per page, peak GPU memory, tables stopped at the model's limit of 8,192 output tokens |
| What fails? | Every failed or partial document, by name and cause |
| How large is it? | Bytes per page of each file, plain and gzip |
| Is the text outside tables right? | Share of the reference's tokens found. The same for identifiers such as `EMEA/H/C/002494` and for numbers. Counts of properties 1 and 2 above |
| Are the table numbers right? | Share of the reference's numbers inside the table region that the cells hold. Share of the cells' numbers that the reference holds. A table without a text layer is reported as not checkable |
| Is the table grid right? | Share of rows with the same column count as the table's other rows. For the two Docling parses: share of tables on which both find the same grid, and cell-by-cell agreement there |
| Does the document keep its identity? | Title and reference number as the build derives them from the text, against today's values |
| What does OCR return? | Characters per page without text, for each parse |

**How the numbers are stated.** The strata are sampled at different rates, so a number for
the corpus is the sum of the stratum means weighted by the strata's sizes, with an interval
from resampling documents. The sizes of the strata are counted before the run. The list of
URLs and the seed are stored with the results. The thresholds that would decide open
question 5 are written into the decision note before the run.

**What plain code cannot see:** a number in the wrong cell. So the owner looks at 30 tables
drawn at random, with the model's name hidden, the PDF page beside the parsed table, and
gives two marks per table: the grid is right, every number is right. It is reported as one
reviewer, n = 30. Until then, table quality rests on the measures above.

## What it deliberately does not do

- **No change to the graph.** No chunk is written or deleted in this row.
- **No Mongo row of another parser is touched or deleted.**
- **No chunking from elements.** That is row 21.
- **No conversion of the corpus.** That is row 21, tier by tier, each with its yes.
- **No PaddlePaddle framework, no second parsing library.**
- **No change to HTML parsing, and none to row 11.** Row 11 parses the 7,678 PDFs that have
  no parse today with the present parser, as proposed. They are converted later with all
  others (open question 8).
- **No picture description, chart reading or formula decoding.** The figure half of C9
  stays open.
- **No Docling in the retrieval environment.**

## Implementation sketch

Size: M. In this order.

1. **The parse environment.** A second virtual environment with Docling, `rapidocr` and
   `transformers` 5.6.2 or newer, at the versions that open question 10 settles. The retrieval
   environment (`.venv`) has torch 2.10.0 and no `torchvision`; an install there could move
   the torch build under the embedding model. `/explore` tries the install on a copy before
   this is fixed. The parser's own imports from this repository need three packages:
   `python-dotenv`, `pymongo`, `tqdm` (counted in review).
2. **The table stage:** a Docling table stage for PaddleOCR-VL-1.6, written for this
   repository with doctool's as the example: a pinned model revision, the generation cache
   switched on, the conversion of the model's LaTeX into text. Docling
   finds such a stage through an installed entry point; a dependency group alone installs
   none. The stage is therefore registered in code, or the project is installed without its
   dependencies.
3. **The parser module** `corpus/parsers/docling_pdf.py` on the `Parser` protocol
   (`corpus/parsers/base.py:40-58`). It never raises. It decompresses a gzip body.
4. **The format writer and reader:** ids, the five files, the staged move, a list of
   failures. Plain Python, so its tests run in the gate.
5. **The batch command.** It takes a list of URLs. It finds the cached file through
   `meta.cache_path` or one walk of the cache. It skips a document whose folder for these
   options exists. One worker process holds the models and is stopped and started again
   after a set number of documents. A PDF above a set number of pages is parsed in page
   ranges and joined: the corpus holds PDFs of 3,808, 1,222, 1,022 and 841 pages (counted in
   review). The time limit of a document grows with its pages. It pauses on a schedule and
   stops between documents when a build needs the GPU.
6. **The pilot**, after the owner's yes: a page in `docs/eval/` with the table above and a
   page per table for the owner's 30.

## Costs

| Step | Size | Estimate | Basis |
|---|---|---|---|
| Pilot | about 270 PDFs, about 7,100 pages, three parses | 7 to 12 GPU hours; the present parser runs on the CPU | PaddleOCR-VL 6 to 9.5 hours by the cost fit below; TableFormer 1.3 to 2.6 hours at 0.68 to 1.32 seconds per page |
| Model downloads | PaddleOCR-VL 1.9 GB, Heron 164 MB | once | Measured in doctool |
| Paid model calls | 0 | | |

**What the conversion in row 21 would cost, as far as it can be said today.** These numbers
are why the pilot exists. They are not a forecast.

| | Estimate | Basis |
|---|---|---|
| PDFs and pages | 65,799 PDFs, about 1.08 million pages | 58,121 parsed PDFs with about 870,000 pages (counted here: mean 15.0 per PDF in a sample of 600, median 5) and 211,458 pages in 7,678 unparsed PDFs ([`corpus_repair.md`](corpus_repair.md)) |
| Parse with TableFormer | 8.5 to 16.5 days of GPU time | Measured in doctool on this GPU: 0.68 and 1.32 seconds per page, one run each on two reports of 30 and 55 pages |
| Parse with PaddleOCR-VL | 25 to 33 days, up to 46 | Counted in review. The time follows the table cells more than the pages: on doctool's 29 GPU runs, seconds = 0.50 × pages + 0.069 × cells. Two samples of the legacy text give 320 and 476 cells per PDF. That is about 6 days for the pages and 18 to 27 days for the tables |
| Where the table time sits | 9.3% of the documents hold 76 to 83% of the cells | Counted in review |
| Chunks replaced in the graph | about 7.23 million chunks and 5.67 million vectors deleted and written again | 7,435,393 and 5,817,230 less the HTML share ([`corpus_repair.md`](corpus_repair.md)) |
| Embedding | about 26 GPU hours | 7.0 million leaves at 265,000 per hour (the same file) |
| The way back | about 21 GPU hours | Re-embedding the old text |

None of these includes pauses, crashes or restarts.

## Verification

- **In the gate (`make test`, in `.venv`):** the format writer and reader on a stored small
  document: the five files, their keys, equal ids on a second run, a failed write leaves the
  previous folder byte-identical. The parser returns `missing_extra` where Docling is not
  installed, as `llamahub_pdf` does.
- **In the parse environment (a second make target, reported and not a gate):** the parser
  on one small synthetic PDF with a table, with TableFormer and OCR off, so no 1.9 GB model
  is needed. Protocol, never raises, gzip, `meta`, the command's dry run. One test with
  PaddleOCR-VL is marked `gpu`.
- **The pilot page** in `docs/eval/`: n per stratum, the weighted numbers with intervals,
  every failed document.
- **What would count against the stack:** numbers lost or added in a share of tables above
  the threshold set before the run, under both table models; identifiers changed in body
  text; a cost per page and per cell that puts the conversion above the number of GPU days
  the owner accepts (open question 7).

## What comes after: row 21

Not designed here. The review of this proposal found what its design must settle:

| Point | What is known |
|---|---|
| A table rarely fits a leaf | In a sample of 15,844 tables of the legacy text, 13% fit 128 tokens and 72% fit 512 (counted in review). "One table, one leaf" does not work at today's sizes |
| Header rows | PaddleOCR-VL marks no header cell, so a rule must find the header before a cut table can repeat it |
| Pages of a table | A table joined across pages has one position per page in `doc.json`; the page of a row range comes from there |
| What the agent is shown | `render_passage` prints a leaf and its parent, cut at 2,000 characters (`harness/tools/search.py:107-124`). A table chunk needs a text form that survives this |
| When a document counts as changed | The build compares a hash of the row's text (`harness/indexing/property_graph.py:272-301`). For a Docling row it must compare the hash of the files it reads |
| Chunk ids | Today an id is a hash of the document and the chunk's position (`harness/indexing/chunking.py:83-86`). After a replace the same id would name other text, and stored citations would point at it silently. Ids of the new chunks must include the parse |
| One schema with row 13 | Row 13 plans `page`, `position`, `level` and `section` on a chunk. Both rows must write the same properties, and one of them must show the page to the person who checks a citation |
| Row 18 | A table whose numbers could not be checked against a text layer, or did not all match, is marked on its chunks, so that a claim resting on it goes to a person |
| The preference file | It would name `docling@<version and hash>` first for PDFs. That overrules decision A of 2026-11-25, "the legacy rows first" (`docs/pm/decisions/2026-11-25_pdf-parser-order.md`), a decision the lead took under delegation |
| After each tier | The steps `tree`, `subgraphs` and `propagate` of `scripts/update_graph.py` run again |
| Order of the tiers | The four benchmark medicines first, before the judged items of benchmark v0 are written: their gold quotes are verbatim from the stored text ([`benchmark_v0.md`](benchmark_v0.md)). Then the documents that hold most table cells. Then the rest |

## Open questions

| | Question | Options | Recommendation | Who decides |
|---|---|---|---|---|
| 1 | Is the PaddleOCR library used as well? See "The two stacks compared" | (a) no: PP-OCRv6 for pages without text and PaddleOCR-VL for tables, both inside Docling; (b) yes, as a fourth parse in the pilot on the 40 documents with pages without text; (c) yes, on every document of the pilot | (a), or (b) if the owner wants the evidence. (c) adds an estimated 4 to 8 GPU hours and is not recommended | The owner. **Open** |
| 2 | Where does the parser code come from? | | **Answered by the owner, 2026-11-25:** doctool is an example only. The parser is written in this repository | |
| 3 | When does this row start? | | **Answered by the owner, 2026-11-25:** after row 10 ships and before row 18 | |
| 4 | May the pilot run? | | **Answered by the owner, 2026-11-25:** yes, for about 270 PDFs, 7 to 12 GPU hours, files only, no deletion, no paid call. A pilot that would exceed this is asked again | |
| 5 | Which table model reads the bulk? | (a) PaddleOCR-VL everywhere; (b) TableFormer everywhere; (c) TableFormer where the table has a text layer, PaddleOCR-VL where it has none; (d) PaddleOCR-VL except on list annexes of hundreds of pages | Decide on the pilot's numbers. The options differ by about 1 to 4 weeks of GPU time | The owner, after the pilot |
| 6 | Where do the folders live, and are the JSON files compressed? | (a) under `~/Nextcloud/Datasets/ema_nlp/parsed/`, plain, about 82 GB; (b) the same with the two JSON files gzip-compressed, about 8 GB, and a doctool reader must unpack them; (c) a local disk outside the sync | (b), to be confirmed on the pilot's sizes. About 330,000 files; the cache in the same sync already holds 608,344 | The owner, after the pilot |
| 7 | How many GPU days may the conversion take? | a number | None from the lead | The owner, after the pilot |
| 8 | Does row 11 still parse the 7,678 unparsed PDFs with the present parser? | (a) yes, as proposed: 4 to 15 CPU hours and about 5 GPU hours, and they are parsed again later; (b) no, they wait for the conversion | (a). They are about a tenth of EMA's document list, and (b) holds them back for weeks | The lead, under delegation. The owner can overrule |
| 9 | Are the 3,829 veterinary documents converted? | yes; no | Decide in row 21. The scope of the corpus is human medicines | The owner, in row 21 |
| 10 | Which Docling version? | (a) 2.132.0 with doctool's pins, the set that was measured on this GPU; (b) the newest release | `/explore` tests both on 5 PDFs for properties 1 and 2 and for the table stage. (b) if it removes a property and the table stage runs; otherwise (a). The files need not load in doctool | `/explore` |
| 11 | Which OCR language setting? | (a) Docling's default; (b) English | `/explore` tests both on 5 scanned pages | `/explore` |

## What the review changed

Two review agents read the first draft on 2026-11-25, one for engineering and cost, one for
validity, rules and readability. The lead checked their main findings against the sources.

- **The scope was cut.** The draft held the chunker and the conversion. Its chunk rule could
  not be met at today's leaf sizes, and the build could not have seen a changed Docling
  document. Both moved to row 21.
- **Two statements about doctool's numbers were wrong** and are corrected in "Three
  properties". The draft had read a comparison of PDF against Word as one of the two table
  models.
- **The pilot could not have compared the new parse with today's.** It now parses every
  document three ways and uses a reference reader that none of them uses.
- **The check on tables was too weak to choose a table model.** TableFormer copies its cell
  text from the text layer and passes such a check by construction. The check now also
  counts numbers that the cells hold and the reference lacks, the grid, and the agreement of
  the two models; and a person looks at 30 tables.
- **The cost was stated per page.** For PaddleOCR-VL it follows the table cells. The lower
  end of 16 days did not follow from any measurement.
- **"No deletion" was false for the conversion,** which replaces about 7.23 million chunks.
- **The document id was too short** for 65,799 PDFs.
- **The first tier named the PDFs that the 45 benchmark items cite.** They cite 7 pages and
  no PDF.

## For the implementing session

- Read doctool as the example before `/explore` writes anything: `src/dw/parsers/`, `docs/parsers.md`,
  `docs/data-contracts.md`, and the two result pages named above
  (`.claude/commands/explore.md`, step 4).
- Verify every Docling call against the installed version (planning rule 2).
- Measured in doctool, each of these cost time there: `rapidocr` 3.10 breaks Docling
  2.132.0; the configuration of the PaddleOCR-VL model repository switches the generation
  cache off, which made one table take 7 to 20 times longer; Docling requests Heron at its
  newest revision; the GPU and the CPU ran the table model at different number precisions,
  and 1 of 55 tables differed.
- Docling's time limit stops a document between steps and returns a partial result. A
  partial result is recorded as failed, and the previous parse stays.
- The GPU: keep the 250 W cap and the pauses. The parse and a build do not run at the same
  time.
- The parser never writes a key of another parser.
- The pilot does not start without its decision note and the owner's yes.

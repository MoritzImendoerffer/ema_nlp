# PDF parsing with Docling and PaddleOCR models: the parser, its post-processing and the first batch

**Status:** proposed 2026-11-25 · backlog row 17 · no work unit yet · starts when row 10 has
shipped, before row 18 · scope cut to the essentials on the owner's instruction of
2026-11-25 · the first batch has the owner's yes of that day

Written by Claude (Fable 5.2), the lead assistant session. Numbers are marked by where they
come from. **Counted here:** a read-only query or sample by the lead on 2026-11-25.
**First look:** a run on 12 EMA PDFs that day
([`../eval/2026-11-25_docling_first_look.md`](../eval/2026-11-25_docling_first_look.md)).
**Counted in review:** by a review agent that day; the lead re-ran two of its five scripts.
**Review of 2026-11-23:**
[`../eval/2026-11-23_pkr_testbed_review.md`](../eval/2026-11-23_pkr_testbed_review.md).
**Measured in doctool:** from the result pages of the owner's repository
`~/github_repos/doctool`, on synthetic reports. Scripts:
`$EMA_RESULTS_DIR/2026-11-25_pdf_parsing_proposal/` and
`$EMA_RESULTS_DIR/2026-11-25_docling_first_look/`.

## What the owner decided

All on 2026-11-25, in the owner's words where quoted.

1. "make sure the pdfs in ema_nlp are parsed using paddleOCR and docling (yes it will
   probably require some re-development) but it would have the same or a similar format as
   my doctool repository and docling is a good base."
2. doctool "serves a different purpose" and "was just meant as an example". Nothing is
   shared with it.
3. This row comes before row 18.
4. "Option A only": the PaddleOCR models run inside Docling. The PaddleOCR library is not
   installed.
5. "just the most important functionality (docling, paddle OCR, post processing for parsing
   like tables over pages or footnotes in tables)".
6. "Prioritize the paddle OCR parsing acc. to the amount of complex tables in bacthes so
   that eventually everything is parsed."

**The lead reads points 5 and 6 as follows.** The parser, the PaddleOCR models and a
post-processing step are built, and nothing else that can be added later without a new
parse. Tables are read by PaddleOCR-VL. Every PDF is parsed in the end, in batches, and
the documents with the most complex tables come first. Point 6 settles scope and order. It
is not yet the yes for one particular run: planning rule 4 asks for counts and hours first
(section "The batches").

## Terms

| Term | Meaning |
|---|---|
| Text layer | The characters a PDF stores as text. A scanned page has none: it is a picture |
| OCR | Reading text from a picture of a page |
| Docling | An open-source library that converts a PDF into a structured document: headings, paragraphs, tables, pictures, each with its page and its position |
| PP-OCR | The OCR models of the PaddleOCR project. Version 6 is used here, through the small engine RapidOCR |
| PaddleOCR-VL | A vision-language model of the PaddleOCR project. Here it reads the grid and the cells of a table from a picture of the table |
| Post-processing | Steps after the parse that need no model and no GPU |
| Legacy row | A row of Mongo `parsed_documents` with parser `pymupdf4llm` and version `legacy`: today's parse of the 58,121 PDFs in the graph |
| Chunk, leaf | The build cuts a document into pieces at 2,048, 512 and 128 tokens. The smallest are the leaves; only they are embedded and searched |

## Why, in short

- A chunk knows no page and no position, so a person who checks a citation has to search
  the PDF.
- 59.5% of the parsed PDFs hold a table, 617,886 tables in all (review of 2026-11-23). In
  one of four table documents of the first look, today's parse saw no table where Docling
  found 6 with 400 cells. One table that runs over four pages came out in pieces.
- The first look also showed what the switch does not bring: better text. Today's parse
  holds 99.7% of the body words of a born-digital PDF. The gain is structure and tables.

## What is built

### 1. The parser

A parser named `docling`, run as a batch command in its own Python environment.

| Part | Choice |
|---|---|
| Base | Docling's standard PDF pipeline with the Heron layout model at a pinned revision. The version is open question 2 |
| Text | From the text layer wherever one exists |
| OCR | PP-OCRv6 through RapidOCR, only for regions without PDF text, with the language set to English. With Docling's default the first look returned a Chinese character for an asterisk |
| Tables | PaddleOCR-VL-1.6 as Docling's table stage, on every table |
| Headings | Docling's heading levels from bookmarks and numbering |

doctool's parser (`src/dw/parsers/`) is the example to read. The code is written here.

### 2. The post-processing

Four steps, each a rule in plain code, each with tests.

| Step | What it does | Why |
|---|---|---|
| Tables over pages | A table that ends at the bottom of a page and continues at the top of the next is joined into one table. The joined table keeps the page of each part | Procedural-step tables and study tables run over many pages. In the first look PaddleOCR-VL kept 6 columns on each of four pages, as four separate tables |
| Footnotes in tables | A footnote mark in a cell stays a mark and is not merged into the cell's number. The footnote texts below a table are attached to that table | "12.5" with footnote 1 must not become "12.51". In the first look footnotes below the tables of one document were missing from the export |
| The model's markup | PaddleOCR-VL writes some cell content as LaTeX, such as `\pm` or `e^{-14}`. It is turned into text, and superscripts and subscripts are kept as such | Measured in doctool: 78 lost quotes from such markup |
| Title and reference number | Docling keeps page headers and footers apart from the body. The reference number of an EMA document often stands only in the page header. It is taken from there into the row's text | The build reads title and reference number from the first 2,048 characters of the text (`corpus/metadata/text_metadata.py`) |

Post-processing never changes the file that the parser wrote. It writes a second file, so
a rule can be improved and applied again without a new parse.

### 3. What is stored

Per PDF one folder, `<parsed root>/<doc-id>/docling@<options hash, 8 characters>/`, written
in a staging place and moved in as a whole:

| File | Holds |
|---|---|
| `doc.raw.json` | Docling's document exactly as the parser returned it, without images. The only file that costs GPU time |
| `doc.json` | The same after post-processing. Rebuilt from `doc.raw.json` at any time |
| `run.json` | The run record: source hash, package versions, model revisions, options and their hash, counts of pages, tables and cells, tables joined, seconds, device |

- **Document id:** `<slug>_<hash12>`: the last part of the URL, cut to 40 characters, and the
  first 12 hex characters of the SHA-256 of the PDF bytes. With 6 characters, as in doctool,
  a silent overwrite was expected with a probability of about 4% (counted in review). Two
  PDFs with the same bytes share one folder and are parsed once.
- **The Mongo row:** key `(url, "docling", "<docling version>+<options hash>")`,
  `content_type` `application/pdf`. `text` is a compact Markdown rendering of `doc.json`,
  with a size guard for Mongo's limit of 16 MB per row. `meta` holds the document id, the
  folder path relative to a root set in `config.py`, the source hash and the counts.
- **Size:** `doc.raw.json` takes 35,800 bytes per page plain and 1,900 gzip-compressed
  (counted in review on doctool's parses). Two such files for 1.08 million pages are about
  77 GB plain and about 4 GB compressed. Open question 1.

### 4. The batch command

It takes a ranked list of URLs and a budget of pages. It finds the cached PDF through
`meta.cache_path` or one walk of the cache, and decompresses a gzip body. It skips a
document whose folder for these options exists, so a batch can be stopped and started
again. One worker process holds the models and is replaced after a set number of
documents. A PDF above a set number of pages is parsed in page ranges and joined; the
corpus holds PDFs of 3,808, 1,222, 1,022 and 841 pages (counted in review). A failed or
partial document is listed with its cause, and its previous parse stays. The command pauses
on a schedule and stops between documents when a build needs the GPU.

## The batches

**The ranking.** Each PDF gets a score for its complex tables, computed from today's text
at no GPU cost: the number of table cells in tables that are wide (8 or more columns),
long (20 or more rows) or ragged. The review of 2026-11-23 (section 8) counted 5,424
documents with such tables, about 333,000 pages, and a stricter tier of 2,176 documents,
about 131,000 pages. Documents are parsed in descending score. Behind them come the
documents with pages without text, then all others. A PDF that has no text yet (the 7,678
that row 11 parses) is ranked as soon as it has one.

One limit of this ranking is known: where today's parse saw no table, the score is 0
although the document may be full of tables. Such documents come late. They do come.

**Batch 0, in this row.** The first 200 documents of the ranking that have at most 60
pages, and 70 documents drawn at random from the rest. It is inside what the owner allowed
on 2026-11-25: about 270 PDFs, 7 to 12 GPU hours, files only. Its decision note states the
URLs, the seed, the pages and the estimated hours before it starts, and the batch is cut
to fit if the estimate exceeds 12 hours. The 200 are real work and are kept. The 70 give
the rate for ordinary documents, which decides how long the whole conversion takes.

**What batch 0 reports**, and every later batch after it:

| Question | Measure |
|---|---|
| How fast? | Seconds per page for pages without tables, seconds per table and per cell, for the 200 and the 70 separately. One test with two and with three worker processes: the first look used 3 to 4 CPU cores with one process |
| What failed? | Every failed or partial document, with its cause |
| How large? | Bytes per page of each file, plain and compressed |
| What did post-processing do? | Tables joined, footnotes attached, cells with markup converted |
| Are the table numbers right? | For each table on a page with a text layer: the share of the text layer's numbers inside the table's box that the cells hold, and the share of the cells' numbers that the text layer holds. PaddleOCR-VL reads cells from the picture, so this is the one check on its reading that costs nothing. It cannot see a number in the wrong cell |
| Did anything get worse? | Body words and numbers held, against today's text of the same document, which is already stored |

**The later batches, in row 21.** A batch is about two days of machine time, so a fault
costs at most two days. Each has a short note with its documents, pages and hours. The note
of batch 1 asks the owner for one standing yes for all batches inside a stated total; a
batch outside that total is asked again.

## What it deliberately does not do

Cut on the owner's instruction, "just the most important functionality". Each of these can
be added later from the stored `doc.json`, without a new parse:

- **No file per element, no element ids, no reading page.** doctool's `doc.html`,
  `sidecar.json` and `view.html` are not written.
- **No second table model and no three-way comparison.** The earlier draft parsed each
  pilot document with today's parser, with TableFormer and with PaddleOCR-VL.
- **No page of sample tables for a person to mark.**

And as before:

- **No PaddleOCR library, no PaddlePaddle framework.**
- **No change to the graph, no chunker.** That is row 21.
- **No Mongo row of another parser is touched.**
- **No change to HTML parsing or to row 11.**
- **No picture description, chart reading or formula decoding.**
- **No Docling in the retrieval environment.**

## Implementation sketch

Size: M.

1. **The parse environment:** a second virtual environment with Docling, `rapidocr` and
   `transformers` 5.6.2 or newer. `.venv` is not touched; an install there could move the
   torch build under the embedding model. `/explore` tries the install on a copy.
2. **The table stage** for PaddleOCR-VL-1.6: a pinned model revision, the generation cache
   switched on. Docling finds such a stage through an installed entry point, so it is
   registered in code or the project is installed without its dependencies.
3. **The parser module** `corpus/parsers/docling_pdf.py` on the `Parser` protocol
   (`corpus/parsers/base.py:40-58`). It never raises.
4. **The post-processing module:** the four steps, on stored documents, in plain Python.
5. **The writer:** the three files, the staged move, the Mongo row, the list of failures.
6. **The ranking script and the batch command.**
7. **Batch 0** and its page in `docs/eval/`.

## Costs

| Step | Estimate | Basis |
|---|---|---|
| Batch 0 | about 9 GPU hours, at most 12 | First look: 4.05 seconds per page on table documents, 1.80 on documents without tables. About 7,800 and 1,050 pages |
| Model downloads | PaddleOCR-VL 1.9 GB, Heron 164 MB, once | Measured in doctool |
| Paid model calls | 0 | |
| All PDFs, row 21 | 65,799 PDFs, about 1.08 million pages: 25 to 46 days of one process | Counted in review from doctool's 29 runs: seconds = 0.50 × pages + 0.069 × table cells. The first look's 3.1 seconds per page gives 39 days. No pauses or restarts included. More than one worker process may shorten it; not tested |
| Embedding, row 21 | about 26 GPU hours for about 7.0 million leaves | 265,000 leaves per hour ([`corpus_repair.md`](corpus_repair.md)) |

## Verification

- **In the gate (`make test`, in `.venv`):** the post-processing rules and the writer on
  stored small documents. A table split over two pages is joined and keeps both pages. A
  cell "12.5" with a mark "1" keeps the number 12.5. A footnote text is attached to its
  table. A failed write leaves the previous folder byte-identical. Where Docling is not
  installed the parser returns `missing_extra`, as `llamahub_pdf` does.
- **In the parse environment (a second make target, reported, not a gate):** the parser on
  one small synthetic PDF. One test with PaddleOCR-VL is marked `gpu`.
- **Batch 0's page** in `docs/eval/` with the table above, n for each number, and every
  failed document.
- **What would stop the batches:** table numbers missing or added in a share of tables that
  the note of batch 0 names beforehand; a rate that puts the conversion far beyond the 25 to
  46 days stated here. Either goes to the owner.

## What row 21 must settle

Not designed here. Found by the review of this proposal's first draft:

| Point | What is known |
|---|---|
| A table rarely fits a leaf | Of 15,844 sampled tables, 13% fit 128 tokens and 72% fit 512 (counted in review) |
| Header rows | PaddleOCR-VL marks no header cell; a rule must find the header before a cut table can repeat it |
| What the agent is shown | `render_passage` prints a leaf and its parent, cut at 2,000 characters (`harness/tools/search.py:107-124`) |
| When a document counts as changed | The build compares a hash of the row's text (`harness/indexing/property_graph.py:272-301`); for a Docling row it must compare the stored files |
| Chunk ids | An id is a hash of document and position (`harness/indexing/chunking.py:83-86`). After a replace the same id would name other text. New ids must include the parse |
| One schema with row 13 | Row 13 plans `page`, `position`, `level`, `section` on a chunk. Both rows write the same properties |
| Row 18 | A table whose numbers did not all match a text layer, or that has none, is marked on its chunks, so a claim resting on it goes to a person |
| The preference file | Naming `docling` first for PDFs overrules decision A of 2026-11-25, "the legacy rows first" |
| The graph | The builds replace about 7.23 million chunks and 5.67 million vectors; going back means embedding the old text again, about 21 GPU hours. After each build the steps `tree`, `subgraphs` and `propagate` run again |

## Open questions

| | Question | Options | Recommendation | Who decides |
|---|---|---|---|---|
| 1 | Where do the folders live, and are the two JSON files compressed? | (a) under `~/Nextcloud/Datasets/ema_nlp/parsed/`, compressed, about 4 GB and about 200,000 files; (b) the same, plain, about 77 GB; (c) a local disk outside the sync | (a), confirmed on batch 0's sizes | The owner, after batch 0 |
| 2 | Which Docling version? | (a) 2.132.0 with doctool's pins, the set measured on this GPU; (b) the newest release | `/explore` tests both on 5 PDFs: does the table stage run, and does the newer one still write every dash as a hyphen and drop a hyphen at a line end. (b) if it is better there | `/explore` |
| 3 | Are the batches after batch 0 covered by one yes? | (a) one standing yes inside a stated total of days; (b) a yes for each batch | (a) | The owner, at the note of batch 1 |
| 4 | Does row 11 still parse the 7,678 unparsed PDFs with today's parser first? | (a) yes: 4 to 15 CPU hours and about 5 GPU hours, and it gives them a score for the ranking; (b) no | (a) | The lead, under delegation; the owner can overrule |

Answered by the owner on 2026-11-25: the stack (option A only), the code (written here),
the order (before row 18), the first batch (yes), the table model (PaddleOCR-VL), the scope
(every PDF in the end) and the order of the conversion (by complex tables).

## For the implementing session

- Read doctool as the example before `/explore` writes anything: `src/dw/parsers/`,
  `src/dw/transforms.py` (its join of split tables), `docs/parsers.md`.
- Verify every Docling call against the installed version (planning rule 2).
- Measured in doctool, each of these cost time there: `rapidocr` 3.10 breaks Docling
  2.132.0; the PaddleOCR-VL model repository's configuration switches the generation cache
  off, which made one table 7 to 20 times slower; Docling requests Heron at its newest
  revision; doctool's join rebuilds all elements for each joined part, which is slow on a
  table of hundreds of pages.
- Docling's time limit stops a document between steps and returns a partial result. A
  partial result is recorded as failed.
- Docling writes every dash as a hyphen and drops a hyphen at a line end (measured in
  doctool; the dashes confirmed in the first look). Do not repair this in post-processing
  without asking: a guess at the original character is worse than a known substitution.
- The GPU: keep the 250 W cap and the pauses. A parse and a build do not run at the same
  time.
- Batch 0 does not start without its decision note. No later batch runs in this row.

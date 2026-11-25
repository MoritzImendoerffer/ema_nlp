# Docling against today's PDF parse: a first look on 12 documents

**Date:** 2026-11-25 · **Written by:** Claude (Fable 5.2), the lead assistant session ·
**Asked by:** the owner ("evaluate if the switch to docling really brings so many benefits")
· **Backlog:** rows 17 and 21 · no work unit · **GPU time:** 8.5 minutes · **Paid model
calls:** 0

The owner decided on 2026-11-25 that the PDFs are parsed with Docling
([`../next/pdf_parsing_docling.md`](../next/pdf_parsing_docling.md)), and then asked whether
the switch really brings as many benefits as it seems. This page answers with a small
measurement. It is not the pilot of row 17: 12 documents chosen by hand-written rules, one
run each, checks by plain code, and no person looked at a table.

## Answer

1. **The text of an ordinary PDF does not get better.** On 9 documents with a text layer,
   today's parse holds 99.7% of the body words and 98.5% of the numbers. Docling holds 97.8%
   and 93.3%. Most of what Docling leaves out is page headers and footers, which it removes
   on purpose. It also writes every dash as a hyphen.
2. **The gain is structure.** Every Docling element knows its page. Headings have levels.
   Tables are objects with rows, columns and cells. Today's parse is one string without any
   of that.
3. **Tables gain in some documents and not in others.** In one of four table documents
   today's parse found no table at all, and Docling found 6 with 400 cells. In the other
   three, today's pipe tables were already well formed. Docling's TableFormer broke one
   table that continues over four pages; PaddleOCR-VL kept its 6 columns.
4. **Scanned pages:** both read a similar amount of text. No ground truth exists, so
   nothing can be said about which is more correct.
5. **The cost is high.** 2.4 seconds per page with TableFormer and 3.1 with PaddleOCR-VL on
   this sample. For 1.08 million pages that would be 30 and 39 days of one process.
6. **Page numbers alone do not need Docling.** Today's parser can write its output page by
   page (`page_chunks`, `page_separators` in `pymupdf4llm` 1.27.2.3), on the CPU.

So the switch is justified by structure and by tables, not by text quality. Whether that is
worth a month of machine time for every PDF, or only for the documents where tables and
scans matter, is a question the pilot's numbers should decide (section "What follows").

## Setup

| | |
|---|---|
| Documents | 12 PDFs with 93 pages, drawn from the 58,121 parsed PDFs in a shuffled order (seed 20261125) by rule: 3 with at least 40 table lines in today's parse, 3 without a table and without a page lacking text, 3 where at least half of the pages hold under 50 characters of text, each of 3 to 25 pages; and 3 documents of one benchmark medicine, chosen by URL |
| Today's parse | The rows `(url, pymupdf4llm, legacy)` of Mongo `parsed_documents`: the text the graph was built from |
| Docling | Version 2.132.0 with `docling-core` 2.99.0, Heron layout, RapidOCR 3.9.2 with PP-OCRv6 for regions without PDF text, in the installed environment of the repository doctool. Once with TableFormer, once with PaddleOCR-VL-1.6. Output: Docling's Markdown export, and its elements and tables |
| Reference | `pdftotext` 26.01.0 (poppler), which neither parse uses. For "body" numbers, lines that repeat on at least half of a document's pages are removed from the reference as page headers and footers; digits are ignored in that comparison |
| Measure | For words (two or more letters) and numbers: the share of the reference's tokens that a parse holds, counting repeats |
| Machine | RTX 3090 at the 250 W cap, Ryzen 5 3600. Nothing else used the GPU |

## Speed

Seconds per page, the loading of the models included once per run.

| Group | Pages | TableFormer | PaddleOCR-VL |
|---|---|---|---|
| Table documents | 30 | 2.81 | 4.05 |
| Documents without tables | 38 | 1.84 | 1.80 |
| Scanned documents | 9 | 4.15 | 4.88 |
| One medicine's documents | 16 | 1.85 | 3.40 |
| **All** | **93** | **2.38** (221 s) | **3.10** (288 s) |

- One document without tables or pictures ran at 0.26 seconds per page (8 pages in 2.1 s).
  A slide deck of 8 pages took 31 s.
- The process used 3 to 4 CPU cores on average (13.6 minutes of CPU time in 3.7 minutes).
  Whether the CPU or the GPU limits the rate was not measured.
- These rates are above the 0.68 to 1.32 and 1.29 to 3.65 seconds per page measured in
  doctool on synthetic reports. 6 of the 12 documents here were chosen for their tables or
  their scanned pages, so the rate of the whole corpus may be lower. At these rates 1.08 million pages take 30
  days with TableFormer and 39 days with PaddleOCR-VL.

## Text

The 9 documents with a text layer, against the body reference: 21,516 words, 1,440 numbers,
17 identifiers of the form `EMA/…` or `EMEA/…`.

| Parse | Words held | Numbers held | Identifiers held |
|---|---|---|---|
| Today's | 99.7% | 98.5% | 17 of 17 |
| Docling, TableFormer | 97.8% | 93.3% | 14 of 17 |
| Docling, PaddleOCR-VL | 97.7% | 93.1% | 14 of 17 |

What Docling's export lacks, read from the lists of missed tokens:

- **Page headers and footers.** The agency's address and telephone number, which stand on
  every page, and the document's own reference number where it stands in the page header.
  In the two-page documents the filter of the reference does not remove these lines, so
  they count as missed. Docling keeps them in its document as a separate layer; its
  Markdown export leaves them out. Today's parse keeps them in the text, on every page.
- **Some footnotes** below the tables of one document.

Two consequences. The repeated footer no longer fills chunks, which is a gain. The
reference number can no longer be read from the first 2,048 characters of the text, as the
build does today (`corpus/metadata/text_metadata.py`); it must be taken from the header
layer.

**Dashes.** The reference holds 47 en dashes, em dashes and minus signs. Today's parse holds
46. Docling with TableFormer holds 0: "19 – 22 October" becomes "19 - 22 October". With
PaddleOCR-VL it holds 9, all in table cells that the model read from the picture.

## Tables

| Document | Today's parse | Docling, TableFormer | Docling, PaddleOCR-VL |
|---|---|---|---|
| Scientific advice statistics, 4 pages | 4 table blocks, 138 lines | 4 tables, 298 cells; 10 columns | 4 tables, 582 cells; 11 columns |
| Procedural steps of one medicine, 4 pages | 3 blocks, 79 lines | 4 tables, 31 cells; shapes 2×6, 4×6, 2×4, 1×1 | 4 tables, 89 cells; shapes 2×6, 4×6, 7×6, 3×6 |
| Committee minutes, 22 pages | 15 blocks, 352 lines | 6 tables, 454 cells | 6 tables, 505 cells |
| Assessment report of the benchmark medicine, 12 pages | **0 blocks** | **6 tables, 400 cells** | 6 tables, 401 cells |

- In today's parse every line of a table block has the same number of columns in all three
  documents where it found tables. So its pipe tables are well formed there.
- Today's parse spreads one header over five lines ("Opinion/", "Notification", "1 issued
  on", …). Docling writes one header cell: "Opinion/ Notification 1 issued on".
- In the assessment report today's parse wrote the tables as loose lines. Docling found
  them. How many of the 58,121 PDFs are like this is not known.
- In the procedural-steps document one table runs over four pages. TableFormer gave the
  later pages 4 columns and then 1 cell. PaddleOCR-VL kept 6 columns on every page.
- Whether the cell contents are right was not checked.

## Scanned documents

Characters returned for three documents of 3 pages each:

| Document | Today's parse (Tesseract) | Docling (PP-OCRv6) |
|---|---|---|
| Referral notification | 7,386 | 7,304 |
| Procedural steps | 3,790 | 5,348 |
| Referral notification | 6,537 | 7,071 |

Today's parse turned the agency's logo into "©eClTENCE MEDICINES HEALTH". Docling returned
a Chinese character where the page shows an asterisk: its OCR ran with its default
language setting, which is Chinese. Open question 11 of the proposal (the OCR language) is
therefore not a detail.

## What is certain, what is open

| Benefit claimed for the switch | After this look |
|---|---|
| Better text | No. Today's text is nearly complete. Docling's is slightly less complete, and its dashes are wrong for an exact quote |
| Less noise in chunks | Yes: page headers and footers are a separate layer |
| A page for every passage | Yes. Also available from today's parser, page by page, without a GPU |
| Position on the page, element ids, heading levels | Yes, and only from a structured parse. This is what lets a citation point at a place a person can look at |
| Better tables | In part. A clear gain where today's parse sees no table; no visible gain where its pipe tables are well formed; merged cells and the correctness of cells were not examined |
| Better reading of scans | Unknown. Similar amounts of text, no ground truth |
| A common format | Yes. Docling's document format is open, versioned and documented, and this proposal's record keeps it unchanged |
| Cost | A month or more of machine time at the measured rates, a second environment, a new chunker, about 26 GPU hours of embedding |

## What follows

1. **The pilot of row 17 stays as planned,** and it must report the rate for the random
   stratum separately, because that stratum decides the cost of the bulk.
2. **Three points go to the implementing session:** the reference number must come from the
   header layer; the OCR language must be set; and the rate may be bound by the CPU, so one
   test with two and with three worker processes belongs in the pilot.
3. **A question for the owner at row 21,** when the pilot's numbers exist: convert every
   PDF, or convert where it pays. "Where it pays" would be the documents that hold most
   table cells (9.3% of the documents hold 76 to 83% of the cells, counted in the review of
   the proposal), the documents with scanned pages, the documents where today's parse lost
   the tables, and the benchmark medicines. The rest would keep today's text and could get
   page numbers from today's parser. This is the lead's suggestion and changes nothing in
   the owner's decision until the owner says so.

## Not verified

- 12 documents, one run. No number here is an estimate for the corpus.
- Correctness of table cells, of merged cells and of OCR text. No person looked.
- The filter for page headers and footers is a rule (a line on at least half of the pages).
  It does not work on documents of one or two pages.
- Docling ran with doctool's settings. Other settings, and a newer Docling, were not tried.
- Docling's Markdown export was compared, not the record format of the proposal.

## Where the files are

`$EMA_RESULTS_DIR/2026-11-25_docling_first_look/`: `manifest.json` (the 12 URLs),
`scripts/` (`select.py`, `run_docling.py`, `compare.py`, `compare_body.py`), `out/` (both
Docling parses), the two run logs, `compare_all.txt` and `compare_body.txt` (the tables
behind this page).

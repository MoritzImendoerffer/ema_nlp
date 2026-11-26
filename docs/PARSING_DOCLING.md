# Parsing PDFs with Docling

The `docling` parser reads EMA PDFs with Docling, with PaddleOCR models for OCR and for
tables. It was built in work unit 28 (backlog row 17, 2026-11-26). It writes files only.
**Nothing it writes reaches the Neo4j graph** until backlog row 21 decides how its output
is chunked and selected.

## What it is

| Part | Choice |
|---|---|
| Base | Docling 2.153.0, standard PDF pipeline; text from the PDF's text layer where one exists |
| Layout | the Heron model at a pinned revision |
| OCR | RapidOCR with the multilingual PP-OCRv6 small detector and the PP-OCRv6 **medium** recognizer, only for regions without a text layer |
| Tables | PaddleOCR-VL-1.6 as Docling's table stage, on every table (`corpus/parsers/paddleocr_vl_table.py`) |
| Post-processing | four rules in `corpus/parsers/docling_post.py`, below |

The OCR choice was measured on 30 pages with a known answer (the PDF's own text layer),
in work unit 28's exploration, section 12. The medium recognizer held 92.6% of words, 98.2%
of numbers and 95.5% of µ signs, and returned no CJK character. The PP-OCRv5 and PP-OCRv4
server recognizers, EasyOCR and Nemotron OCR all read worse on the same pages.

Everything that changes a parse is in `OPTIONS` in `corpus/parsers/docling_pdf.py`. Its hash,
8 hex characters (`6eceaf4e` on 2026-11-26), names the output folder and the Mongo row's
`parser_version`. A change of any option is a new hash, so a new parse.

## Docling never enters .venv

Docling, torch 2.15 and the models live in their own environment, outside the repository:
`config.DOCLING_ENV`, default `~/.local/share/ema_nlp/envs/docling`, override
`$EMA_DOCLING_ENV`. The repository's `.venv` keeps torch 2.10 for the embedding model. In
`.venv`, `DoclingPdfParser.parse` returns an error that starts with `missing_extra`.

```bash
make parse-env     # build the environment from requirements/parse-docling.lock.txt
make test-parse    # the tests marked `parse`, in that environment (never in the gate)
```

`make parse-env` runs `scripts/setup_parse_env.sh`. It refuses to build into `.venv`. It
installs the 129 pinned packages, installs this repository without dependencies, downloads
the Heron and PaddleOCR-VL models at pinned revisions and the medium recognizer, and checks
the recognizer's SHA-256. At the end it prints the torch version of `.venv` and fails if
`.venv` can import Docling. The models go to the Hugging Face cache and to `$EMA_DOCLING_ENV/models`.
A batch never downloads a model.

## Run a batch

**1. Rank the PDFs** (in `.venv`, read-only, about 8 minutes):

```bash
.venv/bin/python scripts/rank_pdfs_by_tables.py
```

It writes `$EMA_RESULTS_DIR/docling/ranking_<date>.jsonl`, one line per PDF with a legacy
`pymupdf4llm` row. The order: documents with complex tables by score (the cells in tables
with 8 or more columns, 20 or more rows, or ragged rows), then documents with pages without
text, then the rest. On 2026-11-26: 58,121 rows, 16,633 with a score above 0, 2,726 with
pages without text, 38,762 others.

**2. Cut a list** from the ranking: any JSONL with `url` and `cache_path` per line,
optionally `pages` and `group` (`ranked`, `random`). Batch 0's list is named in its
decision note under `docs/pm/decisions/`.

**3. Parse** (in the parse environment):

```bash
PY=$(.venv/bin/python -c 'import config; print(config.DOCLING_ENV)')/bin/python
$PY scripts/parse_pdfs_docling.py <list.jsonl> --budget-pages 8400
```

| Option | Default | What it does |
|---|---|---|
| `--budget-pages` | required | takes documents in list order until the next would exceed it |
| `--root` | `config.PARSED_ROOT` (`$EMA_PARSED_ROOT`) | where the folders go |
| `--docs-per-worker` | 50 | the worker process holds the models and is replaced after this many documents |
| `--workers` | 1 | worker processes |
| `--range-pages` | 100 | a longer PDF is parsed in ranges of this many pages and joined |
| `--pause-every-docs`, `--pause-seconds` | 20, 60 | the GPU rests with no document in a worker |
| `--stop-file` | `<root>/STOP` | the batch stops between documents when this file exists |
| `--write-mongo` | off | also writes the `parsed_documents` row |

Keep the GPU's 250 W power cap. The command prints the current limit at the start. A
document already parsed with these options is skipped, so a stopped batch can start again
with the same command.

**What it writes**, under `--root`:

| Path | Holds |
|---|---|
| `<doc-id>/docling@<hash>/doc.raw.json` | Docling's document as the parser returned it, without images. The only file that costs GPU time |
| `<doc-id>/docling@<hash>/doc.json` | the same after post-processing; rebuilt from `doc.raw.json` at any time |
| `<doc-id>/docling@<hash>/run.json` | source SHA-256, package versions, options and hash, counts, seconds, device |
| `failures.jsonl` | one line per failed or partial document, with its cause; such a document gets no folder, and an earlier folder stays |
| `batch_logs/<list>_<time>.jsonl` | one line per document of the batch |

The document id is `<last part of the URL, at most 40 characters>_<first 12 hex characters
of the SHA-256 of the PDF bytes>`. The three files are written to a staging folder and
moved in only when all three exist.

With `--write-mongo`, the row in `parsed_documents` has the key `(url, "docling",
"<docling version>+<hash>")`, the Markdown of `doc.json` as its text, cut at 14 MiB, and the
folder in `meta`. Batch 0 does not write rows: the next graph build would select a docling
row for a URL that has no other row.

**4. Stop it**, for example before a graph build needs the GPU:

```bash
touch "$(.venv/bin/python -c 'import config; print(config.PARSED_ROOT)')/STOP"
```

The batch finishes the document in hand and exits. Delete the file before the next batch.

**5. Read the report** (in `.venv`):

```bash
.venv/bin/python scripts/report_docling_batch.py <list.jsonl>
```

It writes `$EMA_RESULTS_DIR/docling/report_<list>.json` and `.md`. Per group, with n:

- seconds per page, and a least-squares fit per page without tables, per table and per cell;
- every failed document with its cause;
- bytes per page of each file, plain and gzip;
- the post-processing counts;
- for each table on a page with a text layer: the layer's numbers inside the table's box
  that the cells hold, and the cells' numbers that the layer holds. A layer number that is a
  cell's number followed by its footnote mark (layer `12.51`, cell `12.5[^1]`) is counted
  apart. The check cannot see a number in the wrong cell;
- Greek letters and the micro sign held against the text layer, for page text and for
  tables. A Greek letter on a line without a run of 3 or more Greek letters counts as a symbol
  in Latin text;
- CJK characters returned;
- words and numbers held against the legacy text of the same document.

## The post-processing rules

`post_process(raw)` in `corpus/parsers/docling_post.py` applies four rules to a copy of
Docling's document and returns the counts that `run.json` records.

| Rule | What it does | Why |
|---|---|---|
| 1. Tables over pages | joins a table that continues on the next page (same label, same column count, no caption on the continuation); a repeated header row is dropped; each part keeps its page | procedural-step and study tables run over many pages; PaddleOCR-VL returns each page's part as its own table |
| 2. Footnotes in tables | writes a footnote mark as a Markdown footnote reference, `12.5[^1]`, and attaches the footnote texts below the table to it as `[^1]: …`. A unit's exponent is not a mark: `1.73 m^2`, `mL min^-1` | "12.5" with footnote 1 must not become "12.51". A Unicode superscript is not safe: NFKC normalisation turns "12.5¹" into "12.51" |
| 3. The table model's markup | turns LaTeX into text: `\pm` → ±, `\le` → ≤, `e^{-14}` → e-14, `C_{max}` → Cmax, and every Greek letter command into its letter (`\alpha` → α, `\Delta` → Δ, `\mu` → μ). An unknown command is left as written | the owner: Greek symbols must be conserved |
| 4. The reference number | copies the first page header that holds an EMA reference (`EMA/CHMP/123456/2020`) into the body's first item, when the body's first 2,048 characters lack one | Docling's export leaves page headers out, and the build reads the reference from the first 2,048 characters (`corpus/metadata/text_metadata.py`) |

## Files

| File | Holds |
|---|---|
| `corpus/parsers/docling_pdf.py` | the options and their hash, the converter, `convert_pdf` with page ranges, the parser class |
| `corpus/parsers/paddleocr_vl_table.py` | the table stage |
| `corpus/parsers/docling_post.py` | the four rules |
| `corpus/parsers/docling_store.py` | ids, folders, the writer, the run record, the Mongo row |
| `corpus/parsers/docling_batch.py` | the batch loop |
| `scripts/setup_parse_env.sh`, `requirements/parse-docling.lock.txt` | the environment |
| `scripts/rank_pdfs_by_tables.py`, `scripts/parse_pdfs_docling.py`, `scripts/report_docling_batch.py` | the three commands |

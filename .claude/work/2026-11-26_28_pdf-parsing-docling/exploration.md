# Exploration: PDF parsing with Docling and PaddleOCR models (backlog row 17)

| | |
|---|---|
| Work unit | `2026-11-26_28_pdf-parsing-docling` |
| Proposal | [`docs/next/pdf_parsing_docling.md`](../../../docs/next/pdf_parsing_docling.md) at `ea628e2` (the requirements; not copied here) |
| Backlog row | 17, top of `Now` since row 10 shipped on 2026-11-26 |
| Explored | 2026-11-26, by Claude (Opus 5.5) |
| Branch | `pdf-parsing-docling`, made from `develop` at `0a37623` |
| Stores read | MongoDB `ema_scraper.parsed_documents` (read only), the Scrapy cache (read only). Neo4j not touched |
| Trial environments | `~/.local/share/ema_nlp/envs/docling-a` and `docling-b`, outside the repository; `.venv` not touched |
| Scripts and outputs | `$EMA_RESULTS_DIR/2026-11-26_row17_explore/` (`count_pages.py`, `count_tables.py`, `docling_probe.py`, logs, parse outputs) |
| GPU used | about 15 minutes of short trial parses, 250 W cap (`nvidia-smi`) |
| Paid model calls | 0 |

## 1. Verdict

**The proposal stands.** The stack runs: Docling, the Heron layout model at a pinned
revision, PP-OCR through RapidOCR, and PaddleOCR-VL-1.6 as Docling's table stage. It ran
on 6 EMA PDFs in both candidate versions, with the table stage registered in code. No
installed entry point is needed.

Eight points need a correction or an addition before `/plan`.

| # | Finding | Consequence | Section |
|---|---|---|---|
| 1 | **Setting the OCR language to English does nothing.** `RapidOcrOptions(lang=["en"])` loads the same multilingual `PP-OCRv6_rec_small.onnx` as `["ch"]`. The Chinese character the first look found ("…after the authorisation 木", where the page shows an asterisk) comes back with `en` in both versions | English recognition needs RapidOCR's own parameters as enums: `Rec.lang_type=LangRec.EN`, `Rec.ocr_version=OCRVersion.PPOCRV5`, `Rec.model_type=ModelType.MOBILE`. With them the character is gone in both versions | 5 |
| 2 | **Open question 2 is answered: Docling 2.153.0** | Same tables and cells as 2.132.0; 16% faster; exports the footnotes under tables, which 2.132.0 drops; dashes become hyphens in both | 4 |
| 3 | The English model `en_PP-OCRv5_rec_mobile` is not in the rapidocr wheel. RapidOCR downloads it from modelscope.cn on first use | The parse environment downloads it once and pins its file and hash in `run.json`. A batch must not depend on a download | 5 |
| 4 | RapidOCR runs on the CPU. The installed `onnxruntime` 1.32.0 has no CUDA provider ("CUDAExecutionProvider is not in available providers") | Part of the first look's 3 to 4 CPU cores. OCR touches 2.7% of pages (section 6), so this matters little, but batch 0's worker test should know it | 4 |
| 5 | The proposal's counts come from estimates. Counted here: 66,183 cached PDF entries, 1,133,660 pages, 58,121 legacy rows with 328,278 tables, 16,633 documents with a complex table under the proposal's own rule | The page total is close to the proposal's 1.08 million. The table count is about half of the review's 617,886, and the complex-table count is three times its 5,424, because the rules differ. The plan must fix one rule | 6 |
| 6 | **Is a Mongo row written in batch 0?** The proposal writes a row `(url, "docling", …)` per parse. The owner's yes for batch 0 says "files only", and the lead's first message said that `parsed_documents` does not change in this row | An open question for the owner or the lead (section 10). The writer can be built and tested on mongomock either way | 10 |
| 7 | pytest knows only the marker `integration` (`pyproject.toml:93-95`). `make test` runs `-m "not integration"`, so a test marked `gpu` would run in the gate | Register the marker, and have the parse-environment tests skip without Docling. Better: run them through a second make target only | 7 |
| 8 | PaddleOCR-VL writes markup inside real EMA cells: `\(\pm\)`, a literal `\n` inside "Pharma\nceutical", footnote marks as `\(^{a}\)` | Confirms post-processing step 3 on real documents, and shows that footnote marks arrive as superscripts, which step 2 must keep as marks | 4 |

## 2. The proposal's claims, checked

| Claim | Result | Evidence |
|---|---|---|
| `corpus/parsers/base.py:40-58` is the `Parser` protocol | true | lines 40-58 |
| `render_passage`, `harness/tools/search.py:107-124` | true | starts at line 107 |
| The build compares a hash of the row's text, `property_graph.py:272-301` | true | `_decide`, lines 272-301 (row 10) |
| Chunk ids, `chunking.py:83-86` | true | |
| Title and reference number come from the first 2,048 characters | true | `corpus/metadata/text_metadata.py:95` |
| `llamahub_pdf` returns `missing_extra` without its extra | true | `corpus/parsers/llamahub_pdf.py:123` |
| `meta.cache_path` exists on legacy PDF rows | true | meta keys `cache_path`, `ingested_at` |
| `rapidocr` 3.10 breaks Docling 2.132.0 | true in doctool's record; not re-tested. 2.153.0 with `rapidocr` 3.10.0 ran without error | doctool `pyproject.toml:39-42`; section 4 |
| PaddleOCR-VL's repository switches the generation cache off | true; doctool's stage sets `use_cache=True` | doctool `paddleocr_vl_stage.py:155-160` |
| Docling requests Heron at its newest revision | true; pinned with `LayoutObjectDetectionOptions.from_preset("layout_heron_default")` and a model spec copy, which works in both versions. The class lives in `docling.datamodel.pipeline_options`, not in `layout_model_specs` | doctool `docling_parser.py:118-130`; section 4 |
| A stage is found through an entry point | **not required.** `get_table_structure_factory(allow_external_plugins=True).register(cls, name, module)` works in 2.132.0 and 2.153.0 | section 4 |
| Docling writes every dash as a hyphen | true in both versions: the text layer's 35 en dashes, em dashes and minus signs in the CAT minutes come out as 9 in both | section 4 |
| Docling drops a hyphen at a line end | **not measured**: the 6 trial PDFs have no line-end hyphen in their text layer | section 4 |
| PDFs of 3,808, 1,222, 1,022 and 841 pages | true | section 6 |
| 65,799 PDFs, about 1.08 million pages | **close**: 66,183 cached entries with 1,133,660 pages | section 6 |
| 59.5% of the PDFs hold a table, 617,886 tables | **share true** (59.4%), **count differs**: 328,278 tables when a table needs a separator line | section 6 |
| 5,424 documents with complex tables, about 333,000 pages | **depends on the rule**: 16,633 documents under the proposal's ranking rule (wide or long or ragged) | section 6 |
| Batch 0: about 7,800 and 1,050 pages, about 9 GPU hours | **close**: 7,749 and 643 pages, 8.4 to 9.0 hours | section 8 |
| Model downloads: PaddleOCR-VL 1.9 GB, Heron 164 MB | already in `~/.cache/huggingface/hub` (also `TableFormerV2`, `docling-models`) | |

## 3. doctool, read as the example

Read by a read-only agent with file:line references; the points this plan uses:

- **Pins** (`pyproject.toml`): `docling[rapidocr]==2.132.0`, `docling-core==2.99.0`,
  `transformers>=5.6.2,<6`, `rapidocr>=3.9.1,<3.10`. There has been no lock file since
  2026-11-16. Its `.venv` holds transformers 5.23.0 and torch 2.15.0.
- **Converter** (`docling_parser.py:114-146`): `allow_external_plugins=True`,
  `RapidOcrOptions(backend="onnxruntime", mode=OcrMode(...))` with no language (so `["ch"]`),
  Heron pinned at `8f39ad3c0b4c58e9c2d2c84a38465abf757272d8`, no `document_timeout`, no device
  set.
- **Table stage** (`paddleocr_vl_stage.py:54-183`): `PaddlePaddle/PaddleOCR-VL-1.6` at
  `c5630abae1d940eafe0697512a0325494b02ab42`, bf16 on CUDA, one `generate` per table,
  `max_new_tokens=8192`, `use_cache=True`, the crop at 200 DPI, OTSL parsed into a `Table`
  without cell boxes.
- **Join over pages** (`transforms.py:132-260`): adjacent in reading order, consecutive
  pages, same label, same `num_cols`, no caption on the continuation. A repeated header is
  dropped, and merged cells are extended. Each join rebuilds the element list of the whole
  document (`transforms.py:153-160`), so the cost is joins × elements.
- **Markup** (`paddleocr_vl.py:38-153`): `\pm`, `\le`, `\times` and others become
  characters, `\n` becomes a space, `e^{-14}` becomes `e-14`, and `^{}`/`_{}` become script
  runs.
- **Failures** (`ingest.py:80-125`): any status other than SUCCESS raises. `failures.json`
  is written per document, and the batch goes on. There are no page ranges and no worker
  processes.
- **Files** (`data-contracts.md:23-30`): six files; the id hash is 6 characters, plain JSON
  with `indent=2`, a staged rename. The proposal keeps three files and 12 characters.

## 4. The Docling version (open question 2)

Both environments: Python 3.12, torch 2.15.0 (CUDA 13.2), transformers 5.24.1, Heron
pinned, English PP-OCRv5 recognition, doctool's PaddleOCR-VL stage borrowed at run time
from `~/github_repos/doctool/src` (nothing installed). The PDFs were 6 of the first look's 12,
48 pages: three table documents, two scanned ones and one assessment report.

| | A: 2.132.0 + doctool's pins | B: 2.153.0, newest |
|---|---|---|
| Packages | docling-core 2.99.0, docling-ibm-models 4.0.5, docling-parse 7.28.0, rapidocr 3.9.2, pypdfium2 5.13.0 | docling-core 2.108.0, docling-ibm-models 4.0.5, docling-parse 7.28.0, rapidocr 3.10.0, pypdfium2 5.15.2 |
| Install | `uv pip install` without error, 6.0 GB | without error; 266 MB new beside A in uv's cache |
| Status | 6 of 6 SUCCESS | 6 of 6 SUCCESS |
| Table stage | ran on every table: 24 tables, 1,625 cells | the same 24 tables and 1,625 cells; table rows identical row for row |
| Time, 48 pages | 205 s, 4.28 s per page (212 s wall) | 173 s, 3.60 s per page (179 s wall) |
| Peak GPU memory, RAM | 2.50 GB, 5.5 GB | 2.69 GB, 5.2 GB |
| Footnotes under tables | not in the Markdown export | **exported** (e.g. the three footnotes of the repatha procedural-steps table) |
| Dashes (35 in the CAT minutes' text layer) | 9 kept | 9 kept |

Against the first look (2.132.0 with transformers 5.23.0, through doctool's parser): the
same row counts. The cells that differ differ only in markup, which doctool's parser
resolved and the trial did not (`±` against `\(\pm\)`). There is no sign that transformers
5.24.1 reads a cell differently.

**Decision of this exploration, as the proposal assigns it (open question 2: "Who decides:
`/explore`"): (b), Docling 2.153.0** with `rapidocr` 3.10.0. Pin the whole set in the parse
environment.

## 5. The OCR language

On the repatha procedural-steps PDF, whose first-look output held "木" where the page shows an
asterisk:

| Setting | A | B | Recognition model loaded |
|---|---|---|---|
| `lang=["ch"]` (default) | 1 CJK character | 1 | `PP-OCRv6_rec_small.onnx` |
| `lang=["en"]` | 1 | 1 | the same file |
| `lang=["en"]` + `rapidocr_params={"Rec.lang_type": LangRec.EN, "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.model_type": ModelType.MOBILE}` | **0** | **0** | `en_PP-OCRv5_rec_mobile` (downloaded) |

The parameters must be RapidOCR's enum values; strings raise "The value of Rec.ocr_version
must be Enum Type". The proposal's "language set to English" is therefore a choice of
recognition model, and it is recorded in `run.json` with the model file's hash.

## 6. The stores and the cache today

| Count | Value | How |
|---|---|---|
| Cached PDF entries (URL contains `.pdf`, has `response_body`) | 66,183; all open with pymupdf 1.27.2.3; 6,833 gzip bodies; 918 URLs not ending in `.pdf` | `count_pages.py` over `~/Nextcloud/Datasets/ema_scraper/cache/ema-sitemap`, 567 s |
| Pages | 1,133,660; median 6, p90 42, p99 159; largest 3,808, 1,222, 1,022, 841, 711 | the same |
| Pages with under 50 characters of text | 30,614 (2.7%), in 5,503 documents | the same |
| PDFs over 60 pages | 4,552, holding 530,343 pages (47% of all) | the same |
| Legacy PDF rows | 58,121; 34,534 (59.4%) hold a table | `count_tables.py`: a table is a run of `|` lines with a separator line |
| Tables in legacy rows | 328,278 | the same |
| Documents with a complex table (8+ columns, 20+ rows or ragged) | 16,633; scores (cells in complex tables) up to 10,975 | the same |
| `parsed_documents` rows | 80,084 (row 10 added one `pymupdf4llm 1.27.2.3` row) | read-only `count_documents` |

## 7. The parse environment

- `.venv` holds torch 2.10.0 (CUDA 12.8) and transformers 5.10.1 under the embedding model.
  Docling 2.153.0 pulls torch 2.15.0. An install into `.venv` would move the embedding model's
  torch, as the proposal warns.
- A second environment with Python 3.12 and `uv pip install "docling[rapidocr]==2.153.0"
  "transformers>=5.6.2,<6"` installs without error. The parser code of this repository
  reaches it by an install without dependencies (`pip install --no-deps -e .`) or by
  `sys.path`. It needs `pymongo` and `python-dotenv` beside Docling for the Mongo row and
  `config.py`.
- The table stage needs no entry point: `factory.register(...)` in the parser module, called
  before the converter is built.
- The trial environments stay on disk until `/plan` decides where the real one lives. They
  hold 6.3 GB in `~/.local/share/ema_nlp/envs/`.

## 8. Batch 0, sized from the counts

| Part | Documents | Pages | At B's trial rate (3.60 s/page) | At the proposal's rates |
|---|---|---|---|---|
| Top of the ranking, at most 60 pages | 200 (scores 4,962 to 10,975) | 7,749 | 7.7 h | 8.7 h (4.05 s) |
| Random, at most 60 pages, seed 20261126 | 70 | 643 | 0.6 h | 0.3 h (1.80 s) |
| Total | 270 | 8,392 | **8.4 h** | **9.0 h** |

Inside the owner's yes of 2026-11-25 (about 270 PDFs, 7 to 12 GPU hours, files only). The
70 above are drawn from documents of at most 60 pages; the proposal says "from the rest",
which could include longer ones (section 10, question 3).

## 9. What the work has to preserve

| Place | Kind | What this work does |
|---|---|---|
| Scrapy cache, `web_items` | source | reads `response_body`; writes nothing |
| `parsed_documents` | derived | possibly new rows `(url, "docling", …)` (section 10, question 1); never changes another parser's row |
| Neo4j | derived | **untouched**. `parser_preference.yaml` does not list `docling`, and every PDF in the graph has a legacy row, so selection (decision F) never picks a docling row |
| The parsed folders | derived, new | under a root set in `config.py` (open question 1 of the proposal) |
| `parser_preference.yaml`, prompts, recipes, benchmark | authored | not touched |

- **Comparable numbers:** none change; the graph and the retriever are not touched.
- **Cost:** batch 0 is 8.4 to 9.0 GPU hours, 0 paid calls. Downloads: `en_PP-OCRv5_rec_mobile`
  (a few MB); PaddleOCR-VL and Heron are cached.
- **The GPU:** keep the 250 W cap and the pauses. A parse and a build do not run together.
- **Scope:** a parser and a batch command, inside Phase 3 and the owner's decision of
  2026-11-25. No new retrieval layer.
- **The public repository:** public EMA content only.

## 10. Open questions

| | Question | Recommendation | Who |
|---|---|---|---|
| 1 | Does batch 0 write the Mongo row, or files only? | Files only in batch 0, as the owner's yes says. The writer is built and tested on mongomock, and a later note asks before rows are written | the lead or the owner |
| 2 | Where does the parse environment live? | outside the repository and outside the Nextcloud sync, e.g. `~/.local/share/ema_nlp/envs/docling`, built by a script in the repository with pinned versions | `/plan` |
| 3 | May the 70 random documents include PDFs over 60 pages? | yes, a few: it is the only test of the page-range path before row 21 | `/plan` |
| 4 | Which complex-table rule ranks the documents? | the proposal's own (8+ columns or 20+ rows or ragged; score = cells in such tables); 16,633 documents | `/plan` |
| 5 | Is `onnxruntime-gpu` installed for RapidOCR? | no in batch 0: OCR touches 2.7% of pages; measure the CPU share instead | `/plan` |

## 11. Found on the way

- The cache holds 66,183 PDF entries, and `parsed_documents` holds 58,121 legacy PDF rows.
  The difference, about 8,000, matches row 11's 7,678 unparsed PDFs plus fixtures and error
  rows. Row 11 counts it exactly.
- Docling 2.153.0 adds `RapidOcrOptions.replace_broken_text_layer` and `detect_orientation`.
  Neither is used here; both may matter for row 21's scanned documents.

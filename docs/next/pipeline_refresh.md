# A pipeline that can refresh the graph: the newest parse wins, a changed document is replaced

**Status:** proposed 2026-11-23 · backlog row 10 · no work unit yet.

Written by Claude (Fable 5.2) from the review of 2026-11-23
([`../eval/2026-11-23_pkr_testbed_review.md`](../eval/2026-11-23_pkr_testbed_review.md),
sections 3.2 and 3.7). It is step 1a of the rehearsal order. The corpus repair (backlog row 11)
re-parses about 22,700 HTML pages and 7,565 PDFs, and none of that would reach the graph today.

## The problem

`scripts/update_graph.py` is documented as the one entry point from the scraper's output to
Neo4j. It can add a document that is new. It cannot change one that exists. Five reasons, each
read in the code; the first was also run.

1. **The `parse-pdfs` step fails on every PDF.** It runs `python -m corpus.parsers.pymupdf4llm`,
   which parses no PDF: it loads `parsed_pdf.pkl` files that the scraper's repository wrote
   (`corpus/parsers/pymupdf4llm.py`, `pickle.loads`). The pickle needs the scraper's classes,
   and only `scripts/ingest_parsed_pdfs.py:34` adds that repository to the path. Run on a real
   cache entry in `.venv`, the parser returns `pickle_load_failed: No module named 'parsers'`
   and no text. All 58,121 PDF rows in `parsed_documents` carry `parser_version: legacy`.
2. **A new parse never wins.** `iter_source_rows` (`harness/indexing/ingest.py:178`) reads
   `find({"error": ""}).sort("url", 1)` and keeps the first row per URL. The key of
   `parsed_documents` is `(url, parser, parser_version)`, so a re-parse with a new version
   writes a second row. The sort does not say which of the two comes first; the review found
   the older one. `harness/configs/parser_preference.yaml` says in its header that nothing
   reads it.
3. **A changed document is skipped, and a removed one stays.** A resumed build skips every
   document that has a chunk (`_existing_doc_ids`, `harness/indexing/property_graph.py:233`).
   `:Document` records neither the parser nor a hash of its text, so the build cannot see a
   change. A chunk's id is `sha256("<doc_id>|<position>")` (`harness/indexing/chunking.py:84`):
   chunking a shorter text again leaves the old chunks with higher positions behind. Nothing
   deletes a document that has left the source.
4. **A fresh build loses the document labels.** The build calls `build_ingested_doc(row,
   chunking=chunking, html_lookup=lookup)` (`harness/indexing/property_graph.py:307`) without
   the metadata lookup. Only `ingest()` joins `document_metadata`, and only tests call
   `ingest()`. After a reset, `doc_type` and `topic_hubs` are absent until the step `propagate`
   runs, which is not among the default steps (`scripts/update_graph.py:61`).
5. **`--reset` deletes everything in one transaction.** `MATCH (n) DETACH DELETE n`
   (`harness/indexing/property_graph.py:453`) on 7.5 million nodes and 14.6 million
   relationships, with a heap of 2 GB. It also deletes the NeoDash dashboard node. The link
   reset in the same file already deletes in batches (`_delete_links`, `IN TRANSACTIONS OF
   50000 ROWS`). The reset was not run.

No test covers any of the five: none asserts which parser row wins, loads a real object of the
scraper, or rebuilds after a document changed. `scripts/update_graph.py` has no test.

## The idea

A document in the graph says which parse it was built from: the parser, its version, and a
hash of the text. The build picks, for each URL, the row that a preference file names first
and, among equals, the newest. It compares that row with what the graph says. Same parse:
skip. Other parse: delete the document's chunks and build them again. A URL that left the
source: delete its document, on request. The PDF step parses bytes with the `pymupdf4llm` that
`.venv` holds, so no step depends on another repository's classes.

## What it deliberately does not do

- **It repairs no content.** The HTML extractor's defect, the gzip bodies and the `.pdf-N`
  files are backlog row 11. This item is the road; that one is the load.
- **It changes no chunking.** Table-aware chunks and chunk order belong to rows 13 and 17.
  Chunk ids stay as they are, so a document whose text did not change keeps its ids.
- **It re-parses no PDF that has a clean `legacy` row.** A legacy row loses only to a row
  that the preference file ranks higher.
- **It does not touch `web_items` or the Scrapy cache.**
- **It runs no reset and no full rebuild.** It makes the reset safe to run; running it is the
  owner's decision.

## Implementation sketch

| Part | Files | Size |
|---|---|---|
| Row selection: per URL, the first parser that the preference file lists for the content type; among rows of that parser, the newest `parsed_at` | `harness/indexing/ingest.py`, `harness/configs/parser_preference.yaml` | S |
| `:Document` gets `parser`, `parser_version` and `text_sha256` | `harness/indexing/property_graph.py`, `docs/RETRIEVAL.md` (the node model) | S |
| Resume by comparison: a document whose three values equal the selected row's is skipped; one that differs has its chunks and their edges deleted and is built again; one without the values counts as built from the row that the old rule would have picked | `harness/indexing/property_graph.py` | M |
| Removed URLs: `--prune` deletes documents whose URL has no clean row any more, and prints the count first | `harness/indexing/build.py`, `harness/indexing/property_graph.py` | S |
| The real build joins `document_metadata`: `build_ingested_doc` receives the lookup; `ingest()` and the build share one function | `harness/indexing/property_graph.py`, `harness/indexing/ingest.py` | S |
| A PDF parser that reads bytes: `response_body` of the cache entry, `pymupdf4llm.to_markdown`, parser name `pymupdf4llm` with the library's version as `parser_version`; the legacy reader keeps the name `legacy_pickle` and leaves the pipeline's steps | `corpus/parsers/pymupdf4llm.py`, `scripts/update_graph.py` | M |
| Reset in batches, limited to the corpus: `:Document` and `:Chunk` nodes in transactions of 50,000 rows; other nodes stay | `harness/indexing/property_graph.py` | S |
| The pipeline's steps: `propagate` leaves the docs as a repair step once the build joins; the docs say what each step can and cannot refresh | `scripts/update_graph.py`, `docs/RETRIEVAL.md` | S |

Stored shapes:

- `parsed_documents` keeps its key. A second parser for a URL is a second row, as today.
- `:Document` gains three properties. The 79,882 documents in the graph do not have them. A
  backfill script sets them from the row that the old rule picked, without touching a chunk.
  It is a data task of minutes, not hours: one `SET` per document.
- The vector index and every chunk id stay.

## Verification

- `test_preferred_parser_row_wins`: two clean rows for one URL, the preferred parser's row is
  yielded whatever the insertion order.
- `test_newest_row_of_one_parser_wins`: two versions of one parser, the newer `parsed_at` wins.
- `test_changed_text_replaces_chunks`: build a document of 6 leaves, change its row to a text
  of 2 leaves, build again: the graph holds 2 leaves for it and no chunk of the first build.
- `test_unchanged_document_is_skipped`: a second build embeds nothing.
- `test_build_joins_document_metadata`: the function that the real build calls returns a
  document with `doc_type` set.
- `test_pdf_parser_reads_bytes`: the parser returns text for `tests/fixtures/fixture_pdf_0.pdf`
  with no import from another repository.
- `test_reset_keeps_other_nodes`: a node without the corpus labels survives the reset, on the
  test double of the store.
- On the live stores, read-only before and after the backfill: `MATCH (d:Document) WHERE
  d.text_sha256 IS NULL RETURN count(d)` goes from 79,882 to 0, and the counts of `:Chunk`
  nodes and `LINKS_TO` edges do not change.
- `python scripts/update_graph.py --steps parse-pdfs,build --limit 20 --pdf-cache <cache>`
  parses 20 PDFs from bytes and builds without an error.
- `make test` and `make lint` pass.

## Open questions

- **A. Which PDF parser does the preference file name first?** (1) `legacy_pickle`, then
  `pymupdf4llm`: nothing changes until row 11 parses the documents that have no legacy row.
  (2) `pymupdf4llm` first: every PDF that is parsed again replaces its legacy text.
  *Recommendation: (1).* 58,121 documents were chunked and embedded from the legacy text; a
  silent swap would re-embed whatever a later run happens to parse.
- **B. Is a removed URL deleted from the graph?** EMA withdraws documents. Deleting keeps the
  graph equal to the source; keeping them lets a version question find a withdrawn text.
  *Recommendation: keep by default, delete with `--prune`,* and decide for good when the
  document status of row 13 is in the graph.
- **C. What does the backfill write for the 26,315 PDF rows whose tool is recorded as
  `unknown`?** *Recommendation: `parser: legacy_pickle`, `parser_version: legacy`,* as their
  row in `parsed_documents` says. The hash identifies the text whatever made it.

## For the implementing session

- Read how the installed `llama-index-core` 0.14.22 and `Neo4jPropertyGraphStore` delete
  nodes before writing the replace step, and name the file. Deleting a document's chunks must
  also remove their vectors from the index `ema_chunk_embedding`; show it with a query on a
  test document, not with an assumption.
- Check `pymupdf4llm` 1.27.2.3: the call, its options, and whether the output for the fixture
  PDF is stable between two runs. The legacy rows came from another version of an unknown
  number; do not expect equal text.
- The cache stores a response as a folder with `meta` and `response_body`. Some bodies are
  gzip-compressed (row 11). The parser of this item may decompress a body that starts with the
  bytes `1f 8b`; whether it then parses the 6,760 such PDFs is row 11's data task.
- The replace step and the reset are the first code here that deletes from the live graph.
  Their tests run on a test double or on a throwaway database, never on the live one. The
  first live run is a task of type `data`, on one document, with the counts before and after.

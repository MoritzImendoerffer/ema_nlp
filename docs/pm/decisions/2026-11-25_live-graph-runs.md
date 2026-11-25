---
type: pm-decision
epic: 2026-11-23_27_pipeline-refresh
status: settled
settled: 2026-11-25
opened: 2026-11-25
waiting_on: —
blocks: TASK-016, TASK-017
tags: [pm/decision]
---

# The two live runs of the pipeline refresh: the backfill, and one URL through the pipeline

Written by Claude (Opus 5.5) at the checkpoint of work unit 27 (TASK-015), 2026-11-25.

## Where the work stands

The code of backlog row 10 is done and committed on branch `pipeline-refresh` (TASK-001 to
TASK-014 and TASK-018; not pushed). For each URL the build picks the preferred and newest parse.
It compares that parse with what the graph records about the document (`parser`,
`parser_version`, `text_sha256`), and then skips the document, stamps it, or replaces it. The
PDF step parses PDF bytes in this repository. `--prune` and a batched `--reset` exist.

The deletes were run on a throwaway Neo4j with the live server's image and memory limits
([measurement page](../../eval/2026-11-25_graph_delete_measurement.md)): a deleted chunk leaves
the vector index at once, and 6 integration tests pass there. **Nothing has been written to the
live MongoDB or the live graph.**

Two runs remain. Both write to live stores, and the proposal and `CLAUDE.md` rule 4 say that
the owner decides. Neither costs a paid model call.

## Run 1 — the backfill (TASK-016)

**What it does.** `python scripts/backfill_parse_identity.py --verify 100` sets three
properties on every graph document that lacks them: `parser`, `parser_version` and
`text_sha256`. The values come from the row each document was built from (its "old-rule" row).
It writes no chunk, vector, edge or Mongo row.

| | Before (read-only, 2026-11-25) | Expected after |
|---|---|---|
| `MATCH (d:Document) WHERE d.text_sha256 IS NULL RETURN count(d)` | 79,882 | 0 |
| `MATCH (c:Chunk) RETURN count(c)` | 7,435,393 (exploration, 2026-11-23; re-run before the run) | 7,435,393 |
| `MATCH ()-[r:LINKS_TO]->() RETURN count(r)` | 99,520 (same) | 99,520 |
| URLs whose old-rule row differs from the selected row | 0 (full dry run) | — |

**Time.** A full read-only dry run on 2026-11-25 read and hashed all 80,078 URLs in 8.0 s,
11.1 s wall time with the graph query, at 392 MB of memory. The writes were not measured on the
live server. They are 80 `UNWIND` batches of 1,000 `SET`s, and each batch finds its documents
through the `ema_document_id` index. The run should take minutes, not hours. The script prints
its own times.

**Repeatable:** yes. A second run stamps 0 documents.

**Way back:** exact, because no document held these properties before:
`MATCH (d:Document) CALL { WITH d REMOVE d.parser, d.parser_version, d.text_sha256 } IN
TRANSACTIONS OF 10000 ROWS`.

**Cost:** 0 paid calls. No GPU.

## Run 2 — one URL through `parse-pdfs` and `build` (TASK-017)

**What the run is for.** It checks the new path on the live stores, for one document, with
counts before and after.

**A finding first.** Under decision A the legacy PDF rows win. A byte parse of a URL that has a
legacy row therefore does **not** replace that document, so a one-URL run cannot exercise the
live replace on its own. There are two shapes:

| | (a) a gzip PDF without a legacy row | (b) a legacy PDF, the preference swapped for one build |
|---|---|---|
| Example URL | `…/orphan-designation/eu3192242-public-summary-opinion-orphan-designation-autologous-cd34-hematopoietic-stem-cells-crispr-edited-erythroid-enhancer-region-bcl11a-gene-treatment-sickle-cell-disease_en.pdf`: not in the graph, no row in `parsed_documents`, cache body 205,704 bytes starting with `1f8b0800` | `…/procedural-steps-after/veoza-epar-procedural-steps-taken-scientific-information-after-authorisation_en.pdf`: one row `(pymupdf4llm, legacy)`, 9 chunks (6 leaves) in the graph |
| Steps | `python -m corpus.parsers.pymupdf4llm --cache <cache> --url <url>` writes 1 row; `python -m harness.indexing.build --full` | the same parse; put `pymupdf4llm@1.27.2.3` first in the PDF list of `parser_preference.yaml`; `build --full`; restore the file; `build --full` again |
| Live writes | 1 Mongo row; 1 new `:Document` with its chunks; the `LINKS_TO` pass may add edges from pages that link to it | 1 Mongo row; the document's 9 chunks are deleted and rebuilt from the new text, and then deleted and rebuilt again from the legacy text |
| What it proves | the byte parser on a real gzip body, the add path, the metadata join, and that 79,882 documents are skipped | **the live replace path** (delete live chunks, write new ones), twice, and the skip of every other document |
| What it does not prove | the replace path: nothing is deleted | the gzip path |
| Counts to record | `:Document` 79,882 → 79,883; the URL's chunks and leaves; `LINKS_TO` before and after | the URL's chunks 9 (6 leaves) → n → 9 (6 leaves) with the same chunk ids; `:Document` 79,882 and `:Chunk` 7,435,393 back to their values after the second build |
| Way back | delete the one `:Document` (`--prune` does it once the row is deleted) and the one Mongo row | the second build restores the document; the Mongo row stays, and is never selected again under the restored file (deleting it is one `deleteOne`) |

**Time per build** (the parts are measured, the sum is not): the graph's document states 7.3 s;
reading and hashing 80,078 rows about 8 to 11 s; loading the embedding model and embedding at
most 10 leaves on the GPU, seconds; the `LINKS_TO` pass, which every build runs, about 90 s in
June 2026 (work unit 24's exploration, line 106; not re-measured). That gives about 2 to 3
minutes per build: (a) needs one build, (b) two. Finding the URL in the cache takes 5 s, and
parsing it about 2 s.

**Cost:** 0 paid calls. GPU: seconds.

**What (b) asks beyond (a).** `parser_preference.yaml` is authored data (`CLAUDE.md` rule 3). The
assistant would edit it for one build and restore it, and no commit would hold the swapped
version. One live document changes twice and spends about 3 minutes between the two builds with
text from the new parse.

## Options

1. **Run 1, then (b).** The replace path is what this work adds that can damage the live graph,
   and (b) is the only shape that runs it on live data. Its second build undoes it.
2. **Run 1, then (a).** It runs no live delete. The first live replace then happens when row 11
   writes new rows.
3. **Run 1, then (a) and (b).** Everything is checked on live data: three builds, about 6 to 9
   minutes.
4. **Run 1 only.** TASK-017 waits.
5. **Neither run now.**

## Recommendation

**Option 1: Run 1, then (b).** The lead assistant session takes the same view in its message of
2026-11-25: (a) alone does not test the replace path, and (b) changes one live document twice.
Row 11 parses the gzip PDFs anyway, which covers what (a) adds.

Before each run, the counts above are re-queried and written into the task's outcome.

## The answers

**2026-11-25, the owner: option 1, "Backfill, then replace one PDF (Recommended)".** Given in the
lead assistant session's question dialog and relayed to the implementing session. The owner
then confirmed it directly in the implementing session ("Yes, all as relayed"). In the same
answer the owner chose to ship row 10 locally afterwards (merge `pipeline-refresh` into
`develop`, no push) and then to start row 18. TASK-016 and TASK-017 run as described above.
